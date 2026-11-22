'''Pick the model a grill session runs on.

choose_model() is pure (no file, network or clock access). gather_inputs() is the only function that does I/O:
it reads dashboard-settings.json fresh on every call, asks /api/cloud-dial for the cloud state and reads the GPU
lease marker. It runs once per call, never on a timer.

Input shapes
  settings    dict: claudePaused (bool), optional grillModelOrder (list of lane ids)
  cloud_state {up: bool, account: str|None, model: str|None, reason: str}
  local_state {lease_held_by_owner: bool, model: str|None, reason: str}
Override payload: {provider, model}; provider is 'claude' or 'local'.

Assumptions (nothing in this repo defines them yet, so they are env-configurable):
  FEATUREFORGE_DASHBOARD_SETTINGS  path of dashboard-settings.json (default: <agent-manager core>/dashboard-settings.json)
  FEATUREFORGE_GPU_LEASE_FILE      path of the GPU lease marker; the file existing means the owner holds the lease
  FEATUREFORGE_LOCAL_GRILL_MODEL   local model name (default 'ornith')
The module never chooses a context size and never talks to the local model server.
'''
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

LANE_CLOUD = 'cloud-haiku'
LANE_LOCAL = 'local-ornith'
DEFAULT_ORDER = [LANE_CLOUD, LANE_LOCAL]
LANE_PROVIDER = {LANE_CLOUD: 'claude', LANE_LOCAL: 'local'}
HAIKU_MODEL = 'haiku'
DEFAULT_ACCOUNT = 'claude-main'
DEFAULT_LOCAL_MODEL = 'ornith'


@dataclass(frozen=True)
class Choice:
    provider: str
    model: str
    account: str | None
    reason: str
    skipped: list = field(default_factory=list)


class NoGrillModelAvailable(Exception):
    def __init__(self, cloud_reason: str, local_reason: str):
        self.cloud_reason = cloud_reason
        self.local_reason = local_reason
        super().__init__(f'no grill model available; cloud: {cloud_reason}; local: {local_reason}')


def choose_model(settings, cloud_state, local_state, override=None, order=None) -> Choice:
    settings = settings or {}
    cloud_state = cloud_state or {}
    local_state = local_state or {}
    paused = bool(settings.get('claudePaused'))
    skipped: list = []

    if paused:
        cloud_reason = 'claude paused'
    elif cloud_state.get('up'):
        cloud_reason = ''
    else:
        cloud_reason = cloud_state.get('reason') or 'cloud lane down'
    if local_state.get('lease_held_by_owner'):
        local_reason = local_state.get('reason') or 'GPU lease held by owner'
    else:
        local_reason = ''
    account = cloud_state.get('account') or DEFAULT_ACCOUNT
    local_model = local_state.get('model') or DEFAULT_LOCAL_MODEL

    lanes = None
    if override and override.get('provider'):
        prov = override.get('provider')
        if prov == 'claude' and paused:
            skipped.append('claude paused: override ignored')
            lanes = [LANE_LOCAL]
        elif prov in ('claude', 'local'):
            model = override.get('model') or (HAIKU_MODEL if prov == 'claude' else local_model)
            return Choice(prov, model, account if prov == 'claude' else None, 'override', skipped)
        else:
            skipped.append(f'override: unknown provider {prov}')

    if lanes is None:
        lanes = []
        for lane in list(order or settings.get('grillModelOrder') or DEFAULT_ORDER):
            if lane in LANE_PROVIDER:
                lanes.append(lane)
            else:
                skipped.append(f'{lane}: unknown lane')

    for lane in lanes:
        if lane == LANE_CLOUD:
            if cloud_reason:
                skipped.append(f'{lane}: {cloud_reason}')
                continue
            return Choice('claude', cloud_state.get('model') or HAIKU_MODEL, account,
                          'cloud lane up and claude not paused', skipped)
        if lane == LANE_LOCAL:
            if local_reason:
                skipped.append(f'{lane}: {local_reason}')
                continue
            return Choice('local', local_model, None, 'local lane free', skipped)

    raise NoGrillModelAvailable(cloud_reason or 'cloud lane not in order', local_reason or 'local lane not in order')


# ---- the only I/O ---------------------------------------------------------------------------------------

def _settings_path() -> Path:
    env = os.environ.get('FEATUREFORGE_DASHBOARD_SETTINGS')
    if env:
        return Path(env)
    core = os.environ.get('FEATUREFORGE_AM_CORE', '/media/model-cache/github/agent-manager')
    return Path(core) / 'dashboard-settings.json'


def _read_settings() -> dict:
    try:
        data = json.loads(_settings_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_cloud_state() -> dict:
    base = os.environ.get('FEATUREFORGE_AM_URL', 'http://localhost:7420').rstrip('/')
    try:
        with urllib.request.urlopen(base + '/api/cloud-dial', timeout=3) as resp:
            data = json.load(resp)
    except Exception as e:  # unreachable, bad JSON, timeout: the cloud lane is simply not usable
        return {'up': False, 'account': None, 'model': None, 'reason': f'cloud-dial unreachable: {e}'}
    if not isinstance(data, dict):
        return {'up': False, 'account': None, 'model': None, 'reason': 'cloud-dial returned unexpected data'}
    if data.get('requested') == 0:
        return {'up': False, 'account': None, 'model': None, 'reason': 'cloud dial set to 0'}
    return {'up': True, 'account': None, 'model': None, 'reason': ''}


def _read_local_state() -> dict:
    model = os.environ.get('FEATUREFORGE_LOCAL_GRILL_MODEL', DEFAULT_LOCAL_MODEL)
    lease = os.environ.get('FEATUREFORGE_GPU_LEASE_FILE')
    if lease and Path(lease).exists():
        return {'lease_held_by_owner': True, 'model': model, 'reason': 'GPU lease held by owner'}
    return {'lease_held_by_owner': False, 'model': model, 'reason': ''}


def gather_inputs():
    '''Return (settings, cloud_state, local_state), read fresh on every call.'''
    return _read_settings(), _read_cloud_state(), _read_local_state()
