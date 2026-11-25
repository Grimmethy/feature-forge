"""Choose a model for the Grill panel: local first, cloud lane only when available.

This is a trigger-driven choice function (called when the user starts a grill session).
It does NOT poll, sleep, or use timers. It returns a single decision: {provider, model, reason}.

Order of evaluation:
1. Per-session owner override (wins unless the chosen provider is paused)
2. Local model (ornith:35b) when the local server answers /api/ps or /api/tags and no GPU lease blocks
3. Cloud lane (claude) when at least one cloud lane is enabled, its gateway answers /meter,
   Claude is not paused (claudePaused false), and the cloud dial is above 0
4. Refuse with a message naming both failure reasons

Cloud lanes are off today (no lanes configured), so this returns local in the default case.

No polling patterns: no setInterval, cron, poll, or sleep loops.
No model reloads: this function only returns provider/model info; actual model selection
happens elsewhere through src/local-client.js.
"""
from __future__ import annotations

import urllib.request
import urllib.error
from typing import Any


def _health_check_local() -> bool:
    """Check if the local server responds to /api/ps or /api/tags.

    Returns True if either endpoint answers successfully.
    """
    base_url = "http://127.0.0.1:7442"
    endpoints = ["/api/ps", "/api/tags"]
    
    for endpoint in endpoints:
        try:
            url = base_url + endpoint
            req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=2)
            if resp.status == 200:
                return True
        except (urllib.error.URLError, OSError, TimeoutError):
            continue
    
    return False


def _check_gpu_lease() -> bool:
    """Check if there's no GPU lease blocking local model usage.

    Returns True if no lease is blocking (or lease check is unavailable).
    """
    # Check for GPU lease lock file or status
    lease_path = "/tmp/grill-gpu-lease.lock"
    try:
        import os
        if os.path.exists(lease_path):
            # Check if the lease is still valid (process still running)
            with open(lease_path, "r") as f:
                pid_str = f.read().strip()
                if pid_str:
                    pid = int(pid_str)
                    # Check if process is still running
                    os.kill(pid, 0)
                    # Process exists, lease is active
                    return False
    except (OSError, ValueError, TypeError):
        # No lease file, invalid PID, or permission error - no block
        pass
    
    return True


def _check_cloud_lanes(env: dict[str, Any]) -> tuple[bool, str | None]:
    """Check if cloud lanes are available and healthy.

    Returns (is_available, lane_model) where lane_model is the model name if available.
    """
    # Check if at least one cloud lane is enabled
    cloud_lanes = env.get("cloud_lanes", [])
    if not cloud_lanes:
        return False, None
    
    # Check if Claude is paused
    claude_paused = env.get("claudePaused", False)
    if claude_paused:
        return False, None
    
    # Check cloud dial
    cloud_dial = env.get("cloud_dial", 0)
    if cloud_dial <= 0:
        return False, None
    
    # Check gateway health via /meter endpoint
    gateway_url = env.get("cloud_gateway_url", "http://127.0.0.1:7443")
    try:
        url = gateway_url + "/meter"
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=2)
        if resp.status == 200:
            # Get the lane model from the first enabled lane
            lane_model = cloud_lanes[0].get("model", "claude-sonnet")
            return True, lane_model
    except (urllib.error.URLError, OSError, TimeoutError):
        pass
    
    return False, None


def choose(env: dict[str, Any]) -> dict[str, Any]:
    """Choose a model for the Grill panel.

    Args:
        env: Environment dict with keys:
            - owner_override: Optional provider override (e.g., "claude", "local")
            - cloud_lanes: List of cloud lane configs
            - claudePaused: Boolean, True if Claude is paused
            - cloud_dial: Integer, 0-100, cloud token budget dial
            - cloud_gateway_url: URL of the cloud gateway

    Returns:
        Dict with keys: provider, model, reason
    """
    # Priority 0: Owner override (wins unless chosen provider is paused)
    owner_override = env.get("owner_override")
    if owner_override:
        if owner_override == "local":
            # Check if local is available
            if _health_check_local() and _check_gpu_lease():
                return {
                    "provider": "local",
                    "model": "ornith:35b",
                    "reason": "owner override: local available"
                }
        elif owner_override == "claude":
            # Check if Claude is paused
            if not env.get("claudePaused", False):
                is_available, lane_model = _check_cloud_lanes(env)
                if is_available:
                    return {
                        "provider": "claude",
                        "model": lane_model,
                        "reason": "owner override: cloud lane available"
                    }
    
    # Priority 1: Local model
    if _health_check_local() and _check_gpu_lease():
        return {
            "provider": "local",
            "model": "ornith:35b",
            "reason": "local available"
        }
    
    # Priority 2: Cloud lane
    is_available, lane_model = _check_cloud_lanes(env)
    if is_available:
        return {
            "provider": "claude",
            "model": lane_model,
            "reason": "cloud lane available"
        }
    
    # Priority 3: Refuse
    local_ok = _health_check_local()
    gpu_ok = _check_gpu_lease()
    cloud_ok, _ = _check_cloud_lanes(env)
    
    reasons = []
    if not local_ok:
        reasons.append("local server not answering")
    elif not gpu_ok:
        reasons.append("GPU lease blocking")
    
    if not cloud_ok:
        if env.get("claudePaused", False):
            reasons.append("Claude paused")
        elif not env.get("cloud_lanes"):
            reasons.append("no cloud lanes enabled")
        elif env.get("cloud_dial", 0) <= 0:
            reasons.append("cloud dial at zero")
        else:
            reasons.append("cloud gateway not healthy")
    
    reason_str = "; ".join(reasons) if reasons else "both local and cloud unavailable"
    
    return {
        "provider": None,
        "model": None,
        "reason": f"refused: {reason_str}"
    }
