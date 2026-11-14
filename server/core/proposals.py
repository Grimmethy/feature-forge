"""Repo-scout proposals store: reads proposal files and tracks per-proposal state."""
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = 'proposal-state.json'
HISTORY_FILE = 'proposal-history.jsonl'
DEFAULT_DIR = '~/.local/state/pipeline-ops/reposcout/proposals'
FINGERPRINT_FIELDS = ('title', 'why', 'evidence', 'effort', 'kind', 'outward')
STATES = ('new', 'started', 'dismissed')


class StateCorrupt(Exception):
    'proposal-state.json exists but is not a JSON object.'


def _proposals_dir(root=None):
    if root is not None:
        return Path(root)
    env = os.environ.get('REPOSCOUT_PROPOSALS_DIR')
    if env:
        return Path(env).expanduser()
    return Path(DEFAULT_DIR).expanduser()


def _parse_ts(value):
    if not isinstance(value, str):
        raise ValueError('scoutedAt is not a string')
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fingerprint(p):
    body = {k: p.get(k) for k in FINGERPRINT_FIELDS}
    raw = json.dumps(body, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def _load_state(d):
    path = d / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise StateCorrupt(f'{path}: {e}') from e
    if not isinstance(data, dict):
        raise StateCorrupt(f'{path}: top level is not an object')
    return data


def _write_atomic(path, obj):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_history(d, event):
    with open(d / HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps(event, sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())


def _read_valid(d):
    'Return [(sort_key, entry)] for every valid file, sorted by (-value, scoutedAt).'
    found = []
    if not d.is_dir():
        return found
    for path in sorted(d.glob('*.json')):
        if path.name == STATE_FILE or not path.is_file():
            continue
        try:
            with open(path, encoding='utf-8') as f:
                doc = json.load(f)
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get('repo') != path.stem:
            continue
        value = doc.get('value')
        if type(value) is not int or not 1 <= value <= 5:
            continue
        try:
            scouted = _parse_ts(doc.get('scoutedAt'))
        except (ValueError, TypeError):
            continue
        raw_props = doc.get('proposals')
        if not isinstance(raw_props, list):
            continue
        props = []
        for p in raw_props:
            if not isinstance(p, dict):
                continue
            pid = p.get('id')
            if not isinstance(pid, str) or not pid:
                continue
            item = dict(p)
            item['key'] = f'{path.stem}/{pid}'
            item['fingerprint'] = _fingerprint(p)
            props.append(item)
        entry = dict(doc)
        entry['proposals'] = props
        found.append(((-value, scouted), entry))
    found.sort(key=lambda pair: pair[0])
    return found


def _effective_state(stored, fp):
    # A stored state only applies while the proposal content is unchanged.
    if isinstance(stored, dict) and stored.get('fingerprint') == fp and stored.get('state') in STATES:
        return stored['state']
    return 'new'


def list_proposals(root=None):
    d = _proposals_dir(root)
    state = _load_state(d)
    out = []
    for _, entry in _read_valid(d):
        for p in entry['proposals']:
            p['state'] = _effective_state(state.get(p['key']), p['fingerprint'])
        out.append(entry)
    return out


def dismiss(key, root=None):
    d = _proposals_dir(root)
    match = None
    for _, entry in _read_valid(d):
        for p in entry['proposals']:
            if p['key'] == key:
                match = p
                break
        if match is not None:
            break
    if match is None:
        raise KeyError(key)
    state = _load_state(d)
    prior = state.get(key)
    prior_state = prior.get('state') if isinstance(prior, dict) else None
    d.mkdir(parents=True, exist_ok=True)
    _append_history(d, {
        'ts': datetime.now(timezone.utc).isoformat(),
        'key': key,
        'action': 'dismiss',
        'fingerprint': match['fingerprint'],
        'prior_state': prior_state,
    })
    entry = dict(prior) if isinstance(prior, dict) else {}
    entry.update({'state': 'dismissed', 'fingerprint': match['fingerprint']})
    state[key] = entry
    _write_atomic(d / STATE_FILE, state)
