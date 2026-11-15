"""Pure helpers for parallel-piece file overlap and dependency closure. Consumed by HUB0007 · 2/2.

files_of(piece_text) reads the first line whose stripped text starts with 'Files:' and returns the
comma-separated paths on it as a set. It returns set() when there is no such line.

depends_transitively(a, b, deps) is True when b is reachable from a, or a is reachable from b,
through deps (deps maps a node to the nodes it depends on). It is direction-agnostic: either side
reaching the other counts. DECISION: depends_transitively returns False when a == b, because a
piece is not treated as depending on itself. The traversal is iterative with a visited set, so
cyclic graphs terminate.

Known limitation: the separator is a plain comma. Some existing 'Files:' lines in
features/cloud-agent-pool/checklist.md (e.g. line 7, 'Files: src/lanes.js, src/lanes.test.js,
docs/agents/lanes.md. Lines ~145-160 of src/lanes.js treat ...') carry prose after the paths, so a
naive comma split yields prose fragments as 'paths'. This is left for the coordinator to decide;
no extra stripping rule is applied here.

Standard library only. No I/O, timers, threads, or shared state.
"""
def files_of(piece_text: str) -> set[str]:
    for line in piece_text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("Files:"):
            return {entry.strip() for entry in stripped[len("Files:"):].split(",") if entry.strip()}
    return set()


def depends_transitively(a: str, b: str, deps: dict[str, set[str]]) -> bool:
    if a == b:
        return False

    def reaches(start: str, goal: str) -> bool:
        seen = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for nxt in deps.get(node, ()):
                if nxt == goal:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    return reaches(a, b) or reaches(b, a)
