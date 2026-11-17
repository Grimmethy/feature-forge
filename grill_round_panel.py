"""Pure helpers for grill rounds in the narrow panel.

Assumed round format (from Docs/GRILL_PROTOCOL.md): a question is a non-blank,
unindented line that does not start with '->'. Lines after it, up to the next
question, are its answer lines. A recommended answer is a line starting with '->'.
This module contains no DOM or framework code and has no side effects.
"""
import html
import json


def split_rounds(text: str) -> list[dict]:
    """Split round text into one block per question.

    Each block is {'question': str, 'answer_lines': list[str]}. Answer lines are
    kept verbatim; trailing blank lines are removed. Empty input returns [].
    """
    if not text or not text.strip():
        return []
    blocks = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip() and line[0] not in " \t" and not line.startswith("->"):
            blocks.append({"question": line.strip(), "answer_lines": []})
        elif blocks:
            blocks[-1]["answer_lines"].append(line)
    for block in blocks:
        while block["answer_lines"] and not block["answer_lines"][-1].strip():
            block["answer_lines"].pop()
    return blocks


def parse_recommended(line: str) -> str | None:
    """Return the recommended answer for a '->' line, or None."""
    stripped = line.lstrip()
    if not stripped.startswith("->"):
        return None
    rest = stripped[2:].strip()
    return rest or None


def render_diff_details(json_text: str) -> str:
    """Render JSON as a closed <details> block with a 'Proposed changes' summary.

    Invalid JSON raises json.JSONDecodeError.
    """
    obj = json.loads(json_text)
    pretty = json.dumps(obj, indent=2, ensure_ascii=False)
    return (
        "<details><summary>Proposed changes</summary><pre>"
        + html.escape(pretty)
        + "</pre></details>"
    )
