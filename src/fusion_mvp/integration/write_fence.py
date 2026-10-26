"""Session write ownership fence shared by HTTP core and MQTT adapter.

Authoritative state lives in the HTTP core process: owner + generation.
Claim / check / transfer are atomic under a single lock (no get-then-set race).

MQTT identifies itself with `X-Fusion-Channel: mqtt` and
`X-Fusion-Write-Generation` once a session is under write governance.
After a formal transfer or release, previous generations are invalid.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

OWNER_MQTT = "mqtt"
OWNER_HTTP = "http"
OWNER_NONE = "none"

CHANNEL_HEADER = "X-Fusion-Channel"
GENERATION_HEADER = "X-Fusion-Write-Generation"

# Authoritative owners inside the HTTP core process.
# value: {"owner": str, "generation": int, "retired_max": int}
_CORE_STATE: dict[str, dict[str, Any]] = {}
_CORE_LOCK = threading.Lock()


def core_get_owner(session_id: str) -> str:
    with _CORE_LOCK:
        st = _CORE_STATE.get(session_id)
        return str(st["owner"]) if st else OWNER_NONE


def core_get_generation(session_id: str) -> int:
    with _CORE_LOCK:
        st = _CORE_STATE.get(session_id)
        return int(st["generation"]) if st else 0


def core_get_state(session_id: str) -> dict[str, Any]:
    with _CORE_LOCK:
        st = _CORE_STATE.get(session_id)
        if not st:
            return {"owner": OWNER_NONE, "generation": 0, "retired_max": 0}
        return {
            "owner": st["owner"],
            "generation": int(st["generation"]),
            "retired_max": int(st.get("retired_max") or 0),
        }


def resolve_channel(session_id: str, header_value: Optional[str]) -> str:
    del session_id  # channel comes only from the request header
    hv = (header_value or "").strip().lower()
    if hv in (OWNER_MQTT, OWNER_HTTP):
        return hv
    return OWNER_HTTP


def check_and_claim(
    session_id: str,
    *,
    channel: str,
    generation: Optional[int] = None,
    handover: bool = False,
) -> Optional[dict]:
    """Return error detail if rejected; None if allowed (may claim owner).

    Entire check/claim runs under one lock so two concurrent first-writers
    cannot both observe OWNER_NONE.
    """
    del handover  # transfers use transfer_owner; process path never auto-handover
    if not session_id:
        return None
    ch = (channel or OWNER_HTTP).strip().lower()
    if ch not in (OWNER_MQTT, OWNER_HTTP):
        ch = OWNER_HTTP
    with _CORE_LOCK:
        st = _CORE_STATE.get(session_id)
        owner = str(st["owner"]) if st else OWNER_NONE
        gen = int(st["generation"]) if st else 0
        retired_max = int(st.get("retired_max") or 0) if st else 0

        # none tombstone after formal release: process cannot auto-reclaim.
        # Reclaim requires formal claim/transfer (write-owner endpoint).
        if owner == OWNER_NONE and retired_max > 0:
            return {
                "error": "write_owner_none_tombstone",
                "sessionId": session_id,
                "writeOwner": OWNER_NONE,
                "writeGeneration": 0,
                "retiredMax": retired_max,
            }

        if owner == OWNER_NONE:
            _CORE_STATE[session_id] = {"owner": ch, "generation": 1, "retired_max": 0}
            return None

        # Initial unclaimed HTTP/default may omit generation (gen==1 first claim).
        # After formal transfer (gen>1), HTTP and MQTT must both present generation.
        # MQTT under governance always requires generation.
        if generation is None:
            if ch == OWNER_MQTT or owner == OWNER_MQTT or gen > 1:
                return {
                    "error": "write_generation_required",
                    "sessionId": session_id,
                    "writeOwner": owner,
                    "writeGeneration": gen,
                }
        elif int(generation) != gen:
            return {
                "error": "write_generation_mismatch",
                "sessionId": session_id,
                "writeOwner": owner,
                "writeGeneration": gen,
            }

        if owner == OWNER_MQTT and ch != OWNER_MQTT:
            return {
                "error": "write_owner_mqtt",
                "sessionId": session_id,
                "writeOwner": OWNER_MQTT,
                "writeGeneration": gen,
            }
        if owner == OWNER_HTTP and ch == OWNER_MQTT:
            return {
                "error": "write_owner_http",
                "sessionId": session_id,
                "writeOwner": OWNER_HTTP,
                "writeGeneration": gen,
            }
        return None


def transfer_owner(
    session_id: str,
    *,
    new_owner: str,
    expected_generation: Optional[int] = None,
    from_owner: Optional[str] = None,
) -> dict[str, Any]:
    """Atomically transfer write ownership; bumps generation. Returns new state."""
    if not session_id:
        raise ValueError("session_id_required")
    target = (new_owner or "").strip().lower()
    if target not in (OWNER_MQTT, OWNER_HTTP, OWNER_NONE):
        raise ValueError("invalid_owner")
    with _CORE_LOCK:
        st = _CORE_STATE.get(session_id)
        owner = str(st["owner"]) if st else OWNER_NONE
        gen = int(st["generation"]) if st else 0
        retired_max = int(st.get("retired_max") or 0) if st else 0
        if expected_generation is not None and gen != int(expected_generation):
            raise RuntimeError("generation_mismatch")
        if from_owner and owner != OWNER_NONE and owner != from_owner:
            raise RuntimeError("from_owner_mismatch")
        if target == OWNER_NONE:
            # Keep tombstone so prior generations cannot resurrect.
            new_retired = max(retired_max, gen)
            _CORE_STATE[session_id] = {
                "owner": OWNER_NONE,
                "generation": 0,
                "retired_max": new_retired,
            }
            return {
                "owner": OWNER_NONE,
                "generation": 0,
                "sessionId": session_id,
                "retiredMax": new_retired,
            }
        new_gen = gen + 1 if st and owner != OWNER_NONE else (retired_max + 1 if retired_max else 1)
        _CORE_STATE[session_id] = {
            "owner": target,
            "generation": new_gen,
            "retired_max": retired_max,
        }
        return {"owner": target, "generation": new_gen, "sessionId": session_id}


# --- deprecated stubs (kept so old imports do not crash; not used for identity) ---
def set_inflight_channel(session_id: str, channel: str) -> None:
    del session_id, channel


def clear_inflight_channel(session_id: str) -> None:
    del session_id


def get_inflight_channel(session_id: str) -> Optional[str]:
    del session_id
    return None


def core_set_owner(session_id: str, owner: str) -> None:
    """Test/helper: set owner without generation bump (prefer transfer_owner)."""
    with _CORE_LOCK:
        if owner in (OWNER_NONE, "", None):
            prev = _CORE_STATE.get(session_id)
            retired = int(prev.get("retired_max") or prev.get("generation") or 0) if prev else 0
            if retired:
                _CORE_STATE[session_id] = {
                    "owner": OWNER_NONE,
                    "generation": 0,
                    "retired_max": retired,
                }
            else:
                _CORE_STATE.pop(session_id, None)
        else:
            prev = _CORE_STATE.get(session_id)
            gen = int(prev["generation"]) if prev and int(prev.get("generation") or 0) else 1
            retired = int(prev.get("retired_max") or 0) if prev else 0
            _CORE_STATE[session_id] = {
                "owner": str(owner),
                "generation": gen or 1,
                "retired_max": retired,
            }
