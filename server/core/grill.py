"""Grill sessions: an interview about one feature, run through the Agent Manager chat plugin.

Feature Forge itself never calls a model. It builds a seed prompt, opens a READ-ONLY chat session (Claude can Read,
Grep and Glob the repos, never change them), relays the stream, and saves the transcript into the feature's
interview.md. Standard library only, so it runs under a bare python3.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import checklist, store

PROTOCOL_PATH = Path(__file__).resolve().parents[2] / "Docs" / "GRILL_PROTOCOL.md"
DEFAULT_ACCOUNT = "claude-main"
CONTEXT_CAP = 40_000            # characters of context put into the seed
FILE_CAP = 8_000                # per context file
TREE_CAP = 120                  # lines of the repo file tree
REPO_DOCS = ("CONTEXT.md", "CLAUDE.md", "AGENTS.md", "README.md")
SKIP_REPO = re.compile(r"(?:-pipeline|-manual|-BACKUP|-hub-p\d+|-wake-others\d*|-test-tmp)$", re.I)
BOOKKEEPING_RE = re.compile(r"^(CONTEXT-LOG|TASK-REF):.*$", re.M)
PROPOSAL_RE = re.compile(r"```checklist-diff[ \t]*\n(.*?)\n[ \t]*```", re.S)

_urlopen = urllib.request.urlopen     # tests replace this
TURN_TIME_LIMIT_S = 900         # seconds a single model turn may take before it is reported as timed out


def _sse_frame(payload: dict) -> str:
    """One server-sent-event frame carrying a JSON payload."""
    return "data: " + json.dumps(payload) + "\n\n"


def _is_timeout(exc: BaseException) -> bool:
    """True when the exception, or anything it was raised from, is a timeout."""
    seen: BaseException | None = exc
    while seen is not None:
        if isinstance(seen, TimeoutError) or isinstance(getattr(seen, "reason", None), TimeoutError):
            return True
        seen = seen.__cause__ or seen.__context__
    return False


def _parse_exit_signal(message: str) -> tuple[str, str]:
    """Pull (exit, signal) out of 'claude -p failed: exit=<code> signal=<name> ...'; 'unknown' when absent."""
    m = re.search(r"exit=(\S+) signal=(\S+)", message or "")
    return (m.group(1), m.group(2)) if m else ("unknown", "unknown")


def _read_meminfo() -> dict[str, str]:
    """Read MemAvailable, SwapTotal, SwapFree from /proc/meminfo; 'unknown' if missing."""
    result = {"MemAvailable": "unknown", "SwapTotal": "unknown", "SwapFree": "unknown"}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                line = line.strip()
                for key in result:
                    if line.startswith(key + ":") and key not in result:
                        # Value is in kB, may have units after the number
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                result[key] = str(int(parts[1]))
                            except ValueError:
                                pass
                        break
    except (OSError, IOError):
        pass
    return result


class GrillError(RuntimeError):
    pass


def chat_base() -> str:
    return os.environ.get("FEATUREFORGE_CHAT_URL", "http://127.0.0.1:7442").rstrip("/")


def repos_root() -> Path:
    return Path(os.environ.get("FEATUREFORGE_REPOS_ROOT", "/media/model-cache/github"))


# ---- the chat plugin ----------------------------------------------------------------------------------

def _call(method: str, path: str, body: dict | None = None, timeout: float = 30, stream: bool = False):
    data = json.dumps(body if body is not None else {}).encode("utf-8") if method == "POST" else None
    req = urllib.request.Request(chat_base() + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        resp = _urlopen(req, timeout=timeout)
        if stream:
            return resp
        with resp:
            return json.load(resp)
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GrillError(f"chat plugin unavailable: {e}") from e


# ---- repos ---------------------------------------------------------------------------------------------

def repo_index(root: Path | None = None) -> list[dict]:
    """Existing repositories under the repos root: name, path and the first prose line of their README or CONTEXT."""
    base = Path(root) if root is not None else repos_root()
    out = []
    if not base.is_dir():
        return out
    for d in sorted(p for p in base.iterdir() if p.is_dir() and (p / ".git").exists() and not SKIP_REPO.search(p.name)):
        summary = ""
        for doc in ("CONTEXT.md", "README.md"):
            f = d / doc
            if f.is_file():
                lines = [ln.strip() for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()]
                summary = next((ln for ln in lines if ln and not ln.startswith(("#", "<", "---", "```"))), "")[:160]
                if summary:
                    break
        out.append({"name": d.name, "path": str(d), "summary": summary})
    return out


def target_repo(slug: str, root: Path | None = None, repos: Path | None = None) -> dict:
    """The repo named by a 'repo: <name>' line in request.md: {name, path, exists}; name is '' when none is chosen yet."""
    text = store.read_file(slug, "request.md", root)
    m = re.search(r"^repo:\s*(\S+)\s*$", text, re.M | re.I)
    if not m:
        return {"name": "", "path": "", "exists": False}
    name = m.group(1)
    path = (Path(repos) if repos is not None else repos_root()) / name
    return {"name": name, "path": str(path), "exists": (path / ".git").exists()}


def _capped(p: Path, cap: int) -> str:
    t = p.read_text(encoding="utf-8", errors="replace")
    return t if len(t) <= cap else t[:cap] + "\n[...truncated...]"


def _tree(repo: Path) -> str:
    lines = []
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo)
        if any(part.startswith(".") or part in ("node_modules", "__pycache__") for part in rel.parts) or len(rel.parts) > 2:
            continue
        lines.append(rel.as_posix() + ("/" if p.is_dir() else ""))
        if len(lines) >= TREE_CAP:
            lines.append("[...more files...]")
            break
    return "\n".join(lines)


# ---- seed ------------------------------------------------------------------------------------------------

def item_section(slug: str, node: str, root: Path | None = None) -> str:
    """The seed part for a grill about ONE checklist item: its text, what it waits for, what waits for it."""
    entries = checklist.parse(store.read_file(slug, "checklist.md", root))
    all_items = checklist.items(entries)
    it = next((i for i in all_items if i["id"] == node), None)
    if it is None:
        raise GrillError(f"no such item {node}")
    deps = checklist._deps(it)
    waiting = [i["id"] for i in all_items if node in checklist._deps(i)]
    body = "\n".join(it["body"]) or "(no task text yet)"
    return (f"\n\n## This session is about checklist item {node}: {it['title']}\n\n"
            f"Filed: {'yes (locked: it can only be reworded, never split or removed)' if checklist.is_locked(it) else 'no'}. "
            f"It waits for: {', '.join(deps) or 'nothing'}. Waiting for it: {', '.join(waiting) or 'nothing'}.\n\nTask text:\n{body}\n\n"
            "Your job: make this ONE small, self-contained task that a worker who sees only its own repo can finish. If it is "
            "bigger than that, propose splitting it into smaller tasks. After the owner confirms, end with a checklist-diff block "
            "in the format the protocol describes.")


def build_seed(slug: str, root: Path | None = None, repos: Path | None = None, protocol: Path | None = None,
               node: str = "feature") -> str:
    fdir = store.feature_dir(slug, root)
    proto = Path(protocol) if protocol is not None else PROTOCOL_PATH
    protocol_text = proto.read_text(encoding="utf-8") if proto.is_file() else ""
    parts, used = [], 0

    def add(label: str, text: str) -> None:
        nonlocal used
        if text.strip() and used < CONTEXT_CAP:
            used += len(text)
            parts.append(f"### {label}\n\n{text}")

    for name in ("request.md", "plan.md", "interview.md", "checklist.md"):
        f = fdir / name
        if f.is_file():
            add(f"feature file `{name}`", _capped(f, FILE_CAP))
    tgt = target_repo(slug, root, repos)
    if tgt["exists"]:
        repo = Path(tgt["path"])
        for doc in REPO_DOCS:
            if (repo / doc).is_file():
                add(f"target repo `{tgt['name']}`: `{doc}`", _capped(repo / doc, FILE_CAP))
        add(f"target repo `{tgt['name']}`: file tree", _tree(repo))
        target = (f"The target repo is `{tgt['name']}` at `{tgt['path']}`. You can Read, Grep and Glob there (and in the "
                  "other repos); look things up instead of asking the owner.")
    elif tgt["name"]:
        target = (f"The owner named a NEW repo `{tgt['name']}` that does not exist yet (it would live at `{tgt['path']}`). "
                  "Read the existing repos listed below for conventions.")
    else:
        index = "\n".join(f"- `{r['name']}`: {r['summary']}" for r in repo_index(repos))
        add("existing repositories", index)
        target = ("No target repo is chosen yet. Question 1 of your first round MUST be the repo: recommend an existing repo "
                  "from the list below or a new one (propose its name), say why, and let the owner decide.")
    if node != "feature":
        target += item_section(slug, node, root)
    return (
        f"You are running a Feature Forge grill session for the feature `{slug}`.\n\n"
        "Follow this protocol exactly. This conversation is READ-ONLY: use Read, Grep and Glob to look things up, never try "
        "to change a file. The Forge saves the transcript itself.\n\n"
        f"## Protocol\n\n{protocol_text}\n\n## Target\n\n{target}\n\n## Context\n\n" + "\n\n".join(parts) +
        "\n\n## Now\n\nRead the context, then ask the owner the first round: the whole frontier, numbered, each question "
        "with your recommended answer. Do not ask for anything you can look up.\n")


# ---- sessions (features/<slug>/.grill/<id>.json) ------------------------------------------------------------

def _meta_path(slug: str, sid: str, root: Path | None) -> Path:
    if not sid or not all(c.isalnum() or c == "-" for c in sid):
        raise GrillError("bad session id")
    return store.feature_dir(slug, root) / ".grill" / f"{sid}.json"


def load_meta(slug: str, sid: str, root: Path | None = None) -> dict:
    p = _meta_path(slug, sid, root)
    if not p.is_file():
        raise GrillError("no such grill session")
    return json.loads(p.read_text(encoding="utf-8"))


def save_meta(slug: str, meta: dict, root: Path | None = None) -> None:
    p = _meta_path(slug, meta["id"], root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def list_sessions(slug: str, root: Path | None = None) -> list[dict]:
    d = store.feature_dir(slug, root) / ".grill"
    if not d.is_dir():
        return []
    return sorted((json.loads(p.read_text(encoding="utf-8")) for p in d.glob("*.json")),
                  key=lambda m: m.get("started", ""), reverse=True)


def start(slug: str, node: str = "feature", account: str | None = None, root: Path | None = None) -> dict:
    """Open a read-only Claude chat session for this feature (node: 'feature' or a checklist item id like FF-3)."""
    store.feature_dir(slug, root)
    if node != "feature":
        item_section(slug, node, root)        # refuses an item that does not exist before any chat call
    sid = _call("POST", "/api/chat/new", {"provider": "claude", "readOnly": True})["id"]
    _call("POST", f"/api/chat/{sid}/swap", {"provider": "claude", "account": account or DEFAULT_ACCOUNT})
    meta = {"id": sid, "feature": slug, "node": node, "provider": "claude", "account": account or DEFAULT_ACCOUNT,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "saved": False, "seeded": False}
    save_meta(slug, meta, root)
    return meta


def stream_turn(slug: str, sid: str, message: str | None, root: Path | None = None, repos: Path | None = None):
    """Yield the chat plugin's server-sent-event lines. message=None sends the seed (the first turn)."""
    meta = load_meta(slug, sid, root)
    if message is None:
        text = build_seed(slug, root, repos, node=meta.get("node") or "feature")
        meta["seeded"] = True
        save_meta(slug, meta, root)
    else:
        text = message
    turn = int(meta.get("turns") or 0) + 1      # a retried turn reuses its number: the count only advances after the model accepts it
    yield _sse_frame({"type": "turn-start", "turn": turn, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "phase": "model"})
    terminal_sent = False
    try:
        resp = _call("POST", f"/api/chat/{sid}/message", {"message": text}, timeout=TURN_TIME_LIMIT_S, stream=True)
        meta["turns"] = turn
        save_meta(slug, meta, root)
        with resp:
            failed_seen = False
            for raw in resp:
                line = (raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw).rstrip("\r\n")
                frame = None
                if line.startswith("data:"):
                    try:
                        frame = json.loads(line[5:].strip())
                    except ValueError:
                        frame = None
                if isinstance(frame, dict) and frame.get("type") == "error":
                    msg = str(frame.get("error") or frame.get("message") or "")
                    code, sig = _parse_exit_signal(msg)
                    if not failed_seen:
                        failed_seen = True
                        meta["failed"] = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "exit": code, "signal": sig,
                                          "message": msg[:300], "last_round": turn}
                        save_meta(slug, meta, root)
                        print(f"[grill] turn failed slug={slug} sid={sid} turn={turn} exit={code} signal={sig}",
                              file=sys.stderr, flush=True)
                    frame["retryable"] = True
                    if sig == "SIGKILL":
                        frame["killed"] = True
                        frame["code"] = "interviewer_killed"
                        frame["session_id"] = sid
                        frame["message"] = "The interviewer was stopped (killed by the system, usually memory pressure). Nothing was lost."
                        frame["last_round"] = turn
                        # Write a structured log line with memory info
                        mem_info = _read_meminfo()
                        print(f"interviewer_killed exit_code={code} signal={sig} MemAvailable={mem_info['MemAvailable']} SwapTotal={mem_info['SwapTotal']} SwapFree={mem_info['SwapFree']}",
                              file=sys.stderr, flush=True)
                    yield _sse_frame(frame)
                    continue
                yield line + "\n"
    except Exception as e:
        if terminal_sent:
            return
        terminal_sent = True
        if _is_timeout(e):
            message_text = f"model turn timed out after {TURN_TIME_LIMIT_S} s"
        else:
            message_text = f"model call failed: {e}"
        yield _sse_frame({"type": "error", "turn": turn, "message": message_text, "retryable": True})
        return


def retry_session(slug: str, sid: str, root: Path | None = None) -> dict:
    """Check if a session can be retried. Returns the last round info and clears the failed state."""
    meta = load_meta(slug, sid, root)
    failed = meta.get("failed")
    if not failed:
        raise GrillError("session is not in a failed state")
    last_round = failed.get("last_round")
    if not last_round:
        raise GrillError("session has no last round to retry")
    # Clear the failed state
    meta.pop("failed", None)
    save_meta(slug, meta, root)
    return {"session_id": sid, "round": last_round}


def extract_proposal(text: str) -> dict:
    """The LAST fenced block tagged checklist-diff in a model reply, parsed: {"ops": [...]}."""
    blocks = PROPOSAL_RE.findall(text or "")
    if not blocks:
        raise GrillError("no checklist-diff block found")
    try:
        proposal = json.loads(blocks[-1])
    except ValueError as e:
        raise GrillError(f"the checklist-diff block is not valid JSON: {e}") from e
    if not isinstance(proposal, dict) or not isinstance(proposal.get("ops"), list) or not proposal["ops"]:
        raise GrillError("the checklist-diff block has no ops")
    return proposal


def proposal_from_session(slug: str, sid: str, root: Path | None = None) -> dict:
    """The newest checklist-diff proposal in this grill session's conversation."""
    load_meta(slug, sid, root)
    for e in reversed(transcript(sid)):
        if e.get("role") == "assistant" and not e.get("marker"):
            text = e.get("display_text") or e.get("text") or ""
            if PROPOSAL_RE.search(text):
                return extract_proposal(text)
    raise GrillError("no checklist-diff proposal in this conversation yet")


def transcript(sid: str) -> list[dict]:
    return _call("GET", f"/api/chat/{sid}").get("transcript") or []


# ---- saving ----------------------------------------------------------------------------------------------

def format_transcript(entries: list[dict]) -> str:
    """Question and answer blocks. The seed (the first user message) and marker rows are left out; the owner's answers stay verbatim."""
    out, seen_seed = [], False
    for e in entries:
        if e.get("marker") or e.get("role") not in ("user", "assistant"):
            continue
        text = BOOKKEEPING_RE.sub("", e.get("display_text") or e.get("text") or "").strip()
        if not text:
            continue
        if e["role"] == "user" and not seen_seed:
            seen_seed = True
            continue
        if e["role"] == "user":
            out.append("**Owner:**\n\n" + text)
        elif seen_seed:
            out.append("**Grill:**\n\n" + text)
    return "\n\n---\n\n".join(out)


def save_to_interview(slug: str, sid: str, root: Path | None = None) -> dict:
    meta = load_meta(slug, sid, root)
    body = format_transcript(transcript(sid))
    if not body:
        raise GrillError("nothing to save yet")
    current = store.read_file(slug, "interview.md", root).replace("_Not started._", "").rstrip()
    block = f"\n\n## Session {time.strftime('%Y-%m-%d %H:%M')} ({meta['node']}, chat {sid})\n\n{body}\n"
    store.write_file(slug, "interview.md", current + block, root)
    meta["saved"] = True
    save_meta(slug, meta, root)
    return {"path": "interview.md", "words": len(body.split())}


def end(slug: str, sid: str, root: Path | None = None) -> dict:
    meta = load_meta(slug, sid, root)
    try:
        _call("POST", f"/api/chat/{sid}/close")
    except GrillError:
        pass
    meta["ended"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    save_meta(slug, meta, root)
    return meta
