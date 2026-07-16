from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


DRIVE_NAMES: tuple[str, ...] = (
    "attachment",
    "curiosity",
    "reflection",
    "duty",
    "social",
    "fatigue",
    "libido",
    "stress",
)

DEFAULT_BASELINES: dict[str, float] = {
    "attachment": 0.42,
    "curiosity": 0.48,
    "reflection": 0.36,
    "duty": 0.44,
    "social": 0.34,
    "fatigue": 0.22,
    "libido": 0.25,
    "stress": 0.18,
}


def clamp01(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, parsed))


def _bounded_text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


@dataclass(frozen=True)
class DesireGates:
    desire_driven: bool = False
    desire_coupling: bool = False
    desire_baseline_drift: bool = False
    heartbeat_autonomy: bool = False
    desire_self_drive: bool = False

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "DesireGates":
        raw = data or {}
        return cls(
            desire_driven=bool(raw.get("desire_driven", False)),
            desire_coupling=bool(raw.get("desire_coupling", False)),
            desire_baseline_drift=bool(raw.get("desire_baseline_drift", False)),
            heartbeat_autonomy=bool(raw.get("heartbeat_autonomy", False)),
            desire_self_drive=bool(raw.get("desire_self_drive", False)),
        )

    def to_dict(self) -> dict[str, bool]:
        return {
            "desire_driven": self.desire_driven,
            "desire_coupling": self.desire_coupling,
            "desire_baseline_drift": self.desire_baseline_drift,
            "heartbeat_autonomy": self.heartbeat_autonomy,
            "desire_self_drive": self.desire_self_drive,
        }


@dataclass(frozen=True)
class DesireConfig:
    gates: DesireGates = field(default_factory=DesireGates)
    baselines: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_BASELINES))
    tick_seconds: int = 300
    thought_limit: int = 24
    fixation_threshold: float = 0.72
    fixation_release_cycles: int = 3
    intent_threshold: float = 0.72
    fatigue_gate: float = 0.82
    attachment_home: float = 0.42
    attachment_baseline_cap: float = 0.50
    attachment_return_ratio: float = 0.60
    self_curiosity_cap: float = 0.62
    self_experience_pulse_cap: float = 0.10
    heartbeat_base_seconds: int = 3600
    heartbeat_min_seconds: int = 900
    heartbeat_max_seconds: int = 7200
    quiet_heartbeat_floor_seconds: int = 3600
    lease_minutes: int = 10080
    daily_push_cap: int = 7
    cooldown_min_minutes: int = 120
    cooldown_max_minutes: int = 210
    timezone: str = "Asia/Tokyo"
    weekday_quiet_start: int = 0
    weekday_quiet_end: int = 8
    weekend_quiet_start: int = 2
    weekend_quiet_end: int = 11

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "DesireConfig":
        raw = data or {}
        supplied_baselines = raw.get("baselines") if isinstance(raw.get("baselines"), Mapping) else {}
        baselines = {
            name: clamp01(supplied_baselines.get(name, DEFAULT_BASELINES[name]))
            for name in DRIVE_NAMES
        }

        def integer(name: str, default: int, low: int, high: int) -> int:
            try:
                value = int(raw.get(name, default))
            except (TypeError, ValueError):
                value = default
            return min(high, max(low, value))

        cooldown_min = integer("cooldown_min_minutes", 120, 1, 10080)
        cooldown_max = integer("cooldown_max_minutes", 210, cooldown_min, 10080)
        heartbeat_min = integer("heartbeat_min_seconds", 900, 60, 86400)
        heartbeat_max = integer("heartbeat_max_seconds", 7200, heartbeat_min, 172800)
        attachment_home = clamp01(raw.get("attachment_home", baselines["attachment"]))
        attachment_cap = max(
            attachment_home,
            clamp01(raw.get("attachment_baseline_cap", 0.50)),
        )
        return cls(
            gates=DesireGates.from_mapping(raw.get("gates")),
            baselines=baselines,
            tick_seconds=integer("tick_seconds", 300, 30, 86400),
            thought_limit=integer("thought_limit", 24, 1, 100),
            fixation_threshold=clamp01(raw.get("fixation_threshold", 0.72)),
            fixation_release_cycles=integer("fixation_release_cycles", 3, 1, 20),
            intent_threshold=clamp01(raw.get("intent_threshold", 0.72)),
            fatigue_gate=clamp01(raw.get("fatigue_gate", 0.82)),
            attachment_home=attachment_home,
            attachment_baseline_cap=attachment_cap,
            attachment_return_ratio=clamp01(raw.get("attachment_return_ratio", 0.60)),
            self_curiosity_cap=max(
                baselines["curiosity"],
                clamp01(raw.get("self_curiosity_cap", 0.62)),
            ),
            self_experience_pulse_cap=min(
                0.25,
                clamp01(raw.get("self_experience_pulse_cap", 0.10)),
            ),
            heartbeat_base_seconds=integer("heartbeat_base_seconds", 3600, heartbeat_min, heartbeat_max),
            heartbeat_min_seconds=heartbeat_min,
            heartbeat_max_seconds=heartbeat_max,
            quiet_heartbeat_floor_seconds=integer(
                "quiet_heartbeat_floor_seconds", 3600, heartbeat_min, heartbeat_max
            ),
            lease_minutes=integer("lease_minutes", 10080, 30, 43200),
            daily_push_cap=integer("daily_push_cap", 7, 1, 50),
            cooldown_min_minutes=cooldown_min,
            cooldown_max_minutes=cooldown_max,
            timezone=_bounded_text(raw.get("timezone", "Asia/Tokyo"), 80) or "Asia/Tokyo",
            weekday_quiet_start=integer("weekday_quiet_start", 0, 0, 23),
            weekday_quiet_end=integer("weekday_quiet_end", 8, 0, 23),
            weekend_quiet_start=integer("weekend_quiet_start", 2, 0, 23),
            weekend_quiet_end=integer("weekend_quiet_end", 11, 0, 23),
        )


@dataclass(frozen=True)
class Thought:
    thought_id: str
    text: str
    drive: str
    kind: str
    strength: float
    born_at: float
    updated_at: float
    feeds: int = 1
    cycles: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Thought":
        drive = str(data.get("drive", "reflection"))
        if drive not in DRIVE_NAMES:
            drive = "reflection"
        return cls(
            thought_id=_bounded_text(data.get("thought_id"), 80),
            text=_bounded_text(data.get("text"), 800),
            drive=drive,
            kind="fixation" if data.get("kind") == "fixation" else "flit",
            strength=clamp01(data.get("strength", 0.0)),
            born_at=float(data.get("born_at", 0.0) or 0.0),
            updated_at=float(data.get("updated_at", 0.0) or 0.0),
            feeds=max(1, int(data.get("feeds", 1) or 1)),
            cycles=max(0, int(data.get("cycles", 0) or 0)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "thought_id": self.thought_id,
            "text": self.text,
            "drive": self.drive,
            "kind": self.kind,
            "strength": self.strength,
            "born_at": self.born_at,
            "updated_at": self.updated_at,
            "feeds": self.feeds,
            "cycles": self.cycles,
        }


@dataclass(frozen=True)
class SessionLease:
    session_key: str = ""
    claimed_at: float = 0.0
    lease_expires_at: float = 0.0
    handoff: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "SessionLease":
        raw = data or {}
        return cls(
            session_key=_bounded_text(raw.get("session_key"), 160),
            claimed_at=float(raw.get("claimed_at", 0.0) or 0.0),
            lease_expires_at=float(raw.get("lease_expires_at", 0.0) or 0.0),
            handoff=_bounded_text(raw.get("handoff"), 800),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_key": self.session_key,
            "claimed_at": self.claimed_at,
            "lease_expires_at": self.lease_expires_at,
            "handoff": self.handoff,
        }


@dataclass(frozen=True)
class DesireState:
    schema_version: int
    drives: Mapping[str, float]
    baselines: Mapping[str, float]
    thoughts: tuple[Thought, ...]
    refractory_until: Mapping[str, float]
    last_pulse_at: Mapping[str, float]
    last_tick_at: float
    next_wake_at: float
    rng_state: int
    tick_count: int
    active_session: SessionLease
    coupling_levels: Mapping[str, float] = field(default_factory=dict)
    refractory_ticks: Mapping[str, int] = field(default_factory=dict)
    self_drive_day: str = ""
    self_drive_count: int = 0
    last_self_pulse_at: float = 0.0
    last_self_pulse_drive: str = ""
    push_day: str = ""
    push_count: int = 0
    last_push_at: float = 0.0
    last_intent: str = ""
    last_reason: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], config: DesireConfig) -> "DesireState":
        raw_drives = data.get("drives") if isinstance(data.get("drives"), Mapping) else {}
        raw_baselines = data.get("baselines") if isinstance(data.get("baselines"), Mapping) else {}
        thoughts_raw = data.get("thoughts") if isinstance(data.get("thoughts"), list) else []
        return cls(
            schema_version=1,
            drives={name: clamp01(raw_drives.get(name, config.baselines[name])) for name in DRIVE_NAMES},
            baselines={name: clamp01(raw_baselines.get(name, config.baselines[name])) for name in DRIVE_NAMES},
            thoughts=tuple(Thought.from_dict(item) for item in thoughts_raw if isinstance(item, Mapping))[: config.thought_limit],
            refractory_until={str(k): float(v) for k, v in dict(data.get("refractory_until") or {}).items()},
            last_pulse_at={str(k): float(v) for k, v in dict(data.get("last_pulse_at") or {}).items()},
            last_tick_at=float(data.get("last_tick_at", 0.0) or 0.0),
            next_wake_at=float(data.get("next_wake_at", 0.0) or 0.0),
            rng_state=int(data.get("rng_state", 2463534242) or 2463534242) & 0xFFFFFFFF,
            tick_count=max(0, int(data.get("tick_count", 0) or 0)),
            active_session=SessionLease.from_dict(data.get("active_session")),
            coupling_levels={
                name: clamp01(dict(data.get("coupling_levels") or {}).get(name, raw_drives.get(name, config.baselines[name])))
                for name in DRIVE_NAMES
            },
            refractory_ticks={
                str(k): max(0, int(v))
                for k, v in dict(data.get("refractory_ticks") or {}).items()
            },
            self_drive_day=_bounded_text(data.get("self_drive_day"), 20),
            self_drive_count=max(0, int(data.get("self_drive_count", 0) or 0)),
            last_self_pulse_at=float(data.get("last_self_pulse_at", 0.0) or 0.0),
            last_self_pulse_drive=_bounded_text(data.get("last_self_pulse_drive"), 40),
            push_day=_bounded_text(data.get("push_day"), 20),
            push_count=max(0, int(data.get("push_count", 0) or 0)),
            last_push_at=float(data.get("last_push_at", 0.0) or 0.0),
            last_intent=_bounded_text(data.get("last_intent"), 80),
            last_reason=_bounded_text(data.get("last_reason"), 300),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "drives": dict(self.drives),
            "baselines": dict(self.baselines),
            "thoughts": [thought.to_dict() for thought in self.thoughts],
            "refractory_until": dict(self.refractory_until),
            "last_pulse_at": dict(self.last_pulse_at),
            "last_tick_at": self.last_tick_at,
            "next_wake_at": self.next_wake_at,
            "rng_state": self.rng_state,
            "tick_count": self.tick_count,
            "active_session": self.active_session.to_dict(),
            "coupling_levels": dict(self.coupling_levels),
            "refractory_ticks": dict(self.refractory_ticks),
            "self_drive_day": self.self_drive_day,
            "self_drive_count": self.self_drive_count,
            "last_self_pulse_at": self.last_self_pulse_at,
            "last_self_pulse_drive": self.last_self_pulse_drive,
            "push_day": self.push_day,
            "push_count": self.push_count,
            "last_push_at": self.last_push_at,
            "last_intent": self.last_intent,
            "last_reason": self.last_reason,
        }
