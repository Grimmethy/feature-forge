# Pure overlap check between a new proposal piece and already-filed pieces.
# No I/O and no timers. A piece is a dict with: id (str), title (str), optional
# files (list of file paths), optional functions (list of names), and optional
# description/body text, which is scanned for identifier-like tokens.
import re

OVERLAP_THRESHOLD = 0.5

_STOP_WORDS = frozenset(['a', 'an', 'and', 'as', 'at', 'be', 'by', 'for', 'from', 'in', 'is', 'it', 'of', 'on', 'or', 'the', 'this', 'to', 'with'])
_WORD_RE = re.compile(r'[a-z0-9]+')
_IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
_CALL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*\(')
_CAMEL_RE = re.compile(r'[a-z][A-Z]')


def _title_words(title):
    words = _WORD_RE.findall(str(title or '').lower())
    return set(w for w in words if w not in _STOP_WORDS)


def _paths(piece):
    return set(str(p).strip() for p in (piece.get('files') or []) if str(p).strip())


def _functions(piece):
    text = ' '.join(str(piece.get(k) or '') for k in ('title', 'description', 'body'))
    names = set(str(f) for f in (piece.get('functions') or []))
    names.update(_CALL_RE.findall(text))
    for tok in _IDENT_RE.findall(text):
        if '_' in tok.strip('_') or _CAMEL_RE.search(tok):
            names.add(tok)
    return names


def _jaccard(a, b):
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_overlaps(new_piece, filed_pieces, threshold=OVERLAP_THRESHOLD):
    if not filed_pieces or not isinstance(new_piece, dict):
        return []
    new_paths = _paths(new_piece)
    new_funcs = _functions(new_piece)
    new_words = _title_words(new_piece.get('title'))
    result = []
    seen = set()
    for filed in filed_pieces or []:
        fid = filed.get('id')
        if fid is None or fid in seen:
            continue
        shares_path = bool(_paths(filed) & new_paths)
        shares_func = bool(_functions(filed) & new_funcs)
        similar = _jaccard(_title_words(filed.get('title')), new_words) >= threshold
        if shares_path or shares_func or similar:
            seen.add(fid)
            result.append(fid)
    return result
