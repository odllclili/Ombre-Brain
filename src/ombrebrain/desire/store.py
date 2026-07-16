from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .core import claim_session, heartbeat, intent_details, new_state, pulse, satisfy, top_intent
from .models import DRIVE_NAMES, DesireConfig, DesireState


class DesireStore:
    """Atomic JSON persistence outside Ombre Brain's long-term memory buckets."""

    def __init__(self, buckets_dir: str, config: DesireConfig):
        self.config = config
        self.path = Path(buckets_dir) / ".system" / "desire_state.json"
        self._lock = threading.RLock()

    def read(self, now: float | None = None) -> DesireState:
        with self._lock:
            return self._read_unlocked(time.time() if now is None else float(now))

    def update(self, transform: Callable[[DesireState], DesireState], now: float | None = None) -> DesireState:
        with self._lock:
            state = self._read_unlocked(time.time() if now is None else float(now))
            updated = transform(state)
            self._write_unlocked(updated)
            return updated

    def _read_unlocked(self, now: float) -> DesireState:
        if not self.path.exists():
            return new_state(now, self.config)
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("desire state root must be an object")
            return DesireState.from_dict(data, self.config)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            # Fail closed: do not emit autonomous actions from damaged state.
            state = new_state(now, self.config)
            return replace(state, last_reason="欲望状态文件无法读取，我已回到只观察的安全状态。")

    def _write_unlocked(self, state: DesireState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f".tmp.{os.getpid()}.{threading.get_ident()}")
        payload = json.dumps(state.to_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        try:
            temp_path.write_text(payload, encoding="utf-8")
            os.replace(temp_path, self.path)
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass


class DesireService:
    def __init__(self, config: dict[str, Any]):
        desire_config = DesireConfig.from_mapping(config.get("desire") if isinstance(config, dict) else None)
        buckets_dir = str(config.get("buckets_dir", "buckets"))
        self.config = desire_config
        self.store = DesireStore(buckets_dir, desire_config)

    def state(self, now: float | None = None) -> dict[str, Any]:
        current_now = time.time() if now is None else float(now)
        state = self.store.read(current_now)
        intent, score, scores = top_intent(state, current_now, self.config)
        intent_projection = intent_details(intent, score)
        return {
            "schema_version": state.schema_version,
            "drives": {name: round(state.drives[name], 4) for name in DRIVE_NAMES},
            "baselines": {name: round(state.baselines[name], 4) for name in DRIVE_NAMES},
            "thoughts": [thought.to_dict() for thought in state.thoughts],
            "top_intent": intent,
            "top_intent_score": round(score, 4),
            "intent": intent_projection,
            "intent_scores": {name: round(value, 4) for name, value in scores.items()},
            "gates": self.config.gates.to_dict(),
            "last_tick_at": state.last_tick_at,
            "next_wake_at": state.next_wake_at,
            "active_session": {
                "claimed": bool(state.active_session.session_key),
                "lease_expires_at": state.active_session.lease_expires_at,
                "handoff": state.active_session.handoff,
            },
            "self_drive": {
                "enabled": self.config.gates.desire_self_drive,
                "curiosity_floor": round(state.baselines["curiosity"], 4),
                "actions_today": state.self_drive_count,
                "day": state.self_drive_day,
                "last_experience_pulse_at": state.last_self_pulse_at,
                "last_experience_pulse_drive": state.last_self_pulse_drive,
            },
            "refractory_ticks": dict(state.refractory_ticks),
            "push_count_today": state.push_count,
            "push_day": state.push_day,
            "last_push_at": state.last_push_at,
            "last_reason": state.last_reason,
            "storage": "operational_state_not_long_term_memory",
        }

    def claim(self, session_key: str, handoff: str = "", lease_minutes: int | None = None, now: float | None = None) -> dict[str, Any]:
        current_now = time.time() if now is None else float(now)
        updated = self.store.update(
            lambda state: claim_session(
                state,
                session_key,
                current_now,
                self.config,
                lease_minutes=lease_minutes,
                handoff=handoff,
            ),
            current_now,
        )
        return {
            "claimed": True,
            "lease_expires_at": updated.active_session.lease_expires_at,
            "preserved": ["drives", "thoughts", "cooldowns", "push_counters"],
            "reason": "我把活跃房间交给了这个窗口，原来的欲望数值没有重置。",
        }

    def pulse(self, drive: str, amount: float, source: str = "experience", thought: str = "", now: float | None = None) -> dict[str, Any]:
        current_now = time.time() if now is None else float(now)
        try:
            zone = ZoneInfo(self.config.timezone)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        local_day = datetime.fromtimestamp(current_now, zone).date().isoformat()
        before_holder: dict[str, float] = {}

        def transform(state: DesireState) -> DesireState:
            before_holder["value"] = float(state.drives.get(drive, 0.0))
            return pulse(
                state,
                drive,
                amount,
                current_now,
                self.config,
                source=source,
                thought_text=thought,
                local_day=local_day,
            )

        updated = self.store.update(transform, current_now)
        intent, score, _scores = top_intent(updated, current_now, self.config)
        return {
            "drive": drive,
            "before": round(before_holder.get("value", 0.0), 4),
            "after": round(updated.drives[drive], 4),
            "top_intent": intent,
            "top_intent_score": round(score, 4),
            "reason": f"我感到 {drive} 变成了 {updated.drives[drive]:.2f}。",
        }

    def satisfy(self, intent: str, intensity: float = 1.0, now: float | None = None) -> dict[str, Any]:
        current_now = time.time() if now is None else float(now)
        updated = self.store.update(
            lambda state: satisfy(state, intent, intensity, current_now, self.config),
            current_now,
        )
        next_intent, score, _scores = top_intent(updated, current_now, self.config)
        return {
            "satisfied": intent,
            "next_intent": next_intent,
            "next_intent_score": round(score, 4),
            "reason": f"我完成了 {intent}，对应的欲望已经有针对性地回落。",
        }

    def heartbeat(self, session_key: str, now: float | None = None) -> dict[str, Any]:
        current_now = time.time() if now is None else float(now)
        try:
            zone = ZoneInfo(self.config.timezone)
        except ZoneInfoNotFoundError:
            zone = ZoneInfo("UTC")
        local = datetime.fromtimestamp(current_now, zone)
        result_holder: dict[str, Any] = {}

        def transform(state: DesireState) -> DesireState:
            updated, result = heartbeat(
                state,
                session_key,
                current_now,
                self.config,
                local_day=local.date().isoformat(),
                local_hour=local.hour,
                weekend=local.weekday() >= 5,
            )
            result_holder.update(result)
            return updated

        self.store.update(transform, current_now)
        return result_holder
