from __future__ import annotations

import json
from typing import Any

from tools import _runtime as rt


def _service():
    service = getattr(rt, "desire_service", None)
    if service is None:
        raise RuntimeError("desire service is not initialized")
    return service


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2)


async def state() -> str:
    """Read-only operational state; it does not write an Ombre memory."""
    return _json(_service().state())


async def claim(session_key: str, handoff: str = "", lease_minutes: int = 10080) -> str:
    return _json(_service().claim(session_key, handoff, lease_minutes))


async def apply_pulse(drive: str, amount: float, source: str = "experience", thought: str = "") -> str:
    return _json(_service().pulse(drive, amount, source, thought))


async def run_heartbeat(session_key: str) -> str:
    return _json(_service().heartbeat(session_key))


async def apply_satisfaction(intent: str, intensity: float = 1.0) -> str:
    return _json(_service().satisfy(intent, intensity))
