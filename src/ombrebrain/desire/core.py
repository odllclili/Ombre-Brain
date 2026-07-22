from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

from .models import (
    DEFAULT_BASELINES,
    DRIVE_NAMES,
    DesireConfig,
    DesireState,
    PendingSpeak,
    SessionLease,
    Thought,
    clamp01,
)


_DECAY_PER_HOUR: dict[str, float] = {
    "attachment": 0.035,
    "curiosity": 0.055,
    "reflection": 0.045,
    "duty": 0.040,
    "social": 0.050,
    "fatigue": 0.080,
    "libido": 0.060,
    "stress": 0.100,
}

_INTENT_WEIGHTS: dict[str, dict[str, float]] = {
    "reach_out": {"attachment": 1.05, "social": 0.18, "stress": 0.08},
    "explore": {"curiosity": 1.00, "reflection": 0.14},
    "reflect": {"reflection": 1.00, "curiosity": 0.10},
    "make_progress": {"duty": 1.00, "stress": 0.08},
    "connect": {"social": 0.92, "attachment": 0.22},
    "rest": {"fatigue": 1.00, "stress": 0.12},
    "seek_closeness": {"libido": 0.78, "attachment": 0.34},
    "stabilize": {"stress": 0.95, "fatigue": 0.16},
}

_INTENT_SATISFACTION: dict[str, dict[str, float]] = {
    "reach_out": {"attachment": 0.42, "social": 0.16},
    "explore": {"curiosity": 0.38},
    "reflect": {"reflection": 0.40},
    "make_progress": {"duty": 0.42, "stress": 0.08},
    "connect": {"social": 0.38, "attachment": 0.12},
    "rest": {"fatigue": 0.48, "stress": 0.18},
    "seek_closeness": {"libido": 0.42, "attachment": 0.10},
    "stabilize": {"stress": 0.48},
}

_INTENT_META: dict[str, tuple[str, str, str, str]] = {
    "reach_out": ("attachment", "碎语", "我有点想你，想靠近说一句话。", ""),
    "explore": ("curiosity", "查世界", "我想去外面看看，找一点真正让我好奇的东西。", "从最强的好奇念头里取关键词"),
    "reflect": ("reflection", "沉淀", "我想把最近发生的事安静地想一遍。", "最近仍有余温的经历"),
    "make_progress": ("duty", "推进未竟之事", "我还记挂着一件没有做完的事。", "最近的未完成事项"),
    "connect": ("social", "看看人群", "我想看看人群里正在发生什么。", "最近的共同兴趣"),
    "rest": ("fatigue", "歇着或做梦", "我累了，想先安静地歇一会儿。", ""),
    "seek_closeness": ("libido", "亲密互动", "我想更亲近一点。", ""),
    "stabilize": ("stress", "缓一缓", "我有些堵，想先把自己稳下来。", ""),
}

# Every coefficient stays within the spec's |k| <= 0.06 bound. Level edges
# apply continuous pressure; delta edges fire only when their source rose.
_COUPLING_EDGES: tuple[tuple[str, str, float, str], ...] = (
    ("stress", "attachment", 0.030, "level"),
    ("stress", "curiosity", -0.040, "level"),
    ("attachment", "libido", 0.040, "delta"),
    ("curiosity", "reflection", 0.035, "delta"),
    ("reflection", "social", 0.025, "delta"),
)


def new_state(now: float, config: DesireConfig) -> DesireState:
    baselines = {name: clamp01(config.baselines.get(name, DEFAULT_BASELINES[name])) for name in DRIVE_NAMES}
    return DesireState(
        schema_version=2,
        drives=dict(baselines),
        baselines=dict(baselines),
        thoughts=(),
        refractory_until={},
        last_pulse_at={},
        last_tick_at=float(now),
        next_wake_at=float(now) + config.tick_seconds,
        rng_state=2463534242,
        tick_count=0,
        active_session=SessionLease(),
        coupling_levels=dict(baselines),
        refractory_ticks={},
    )


def _next_random(seed: int) -> tuple[int, float]:
    next_seed = (1664525 * (seed & 0xFFFFFFFF) + 1013904223) & 0xFFFFFFFF
    return next_seed, next_seed / 4294967296.0


def _bounded_step(current: float, target: float, fraction: float, max_delta: float) -> float:
    delta = (target - current) * max(0.0, fraction)
    return clamp01(current + min(max_delta, max(-max_delta, delta)))


def intent_details(intent: str, score: float) -> dict[str, Any]:
    drive, action, reason, query_hint = _INTENT_META[intent]
    return {
        "want_action": action,
        "drive_key": drive,
        "reason": reason,
        "score": round(score, 4),
        "query_hint": query_hint,
    }


def heartbeat_interval(state: DesireState, now: float, config: DesireConfig, *, quiet: bool = False) -> int:
    """Return an adaptive interval from tension and fatigue, with hard bounds."""
    scores = score_intents(state, now, config)
    tension = max(scores.values(), default=0.0)
    fatigue = state.drives["fatigue"]
    multiplier = 1.0 + 0.55 * (1.0 - tension) - 0.65 * tension + 0.90 * fatigue
    seconds = int(round(config.heartbeat_base_seconds * multiplier))
    seconds = min(config.heartbeat_max_seconds, max(config.heartbeat_min_seconds, seconds))
    if quiet:
        seconds = max(seconds, config.quiet_heartbeat_floor_seconds)
    return seconds


def tick(state: DesireState, now: float, config: DesireConfig) -> DesireState:
    """Advance desire state without reading time, randomness, files, or network."""
    now = max(float(now), state.last_tick_at)
    elapsed_seconds = now - state.last_tick_at
    if elapsed_seconds <= 0:
        return state
    elapsed_hours = min(elapsed_seconds / 3600.0, 72.0)
    tick_units = min(864.0, max(1.0, elapsed_seconds / float(config.tick_seconds)))
    whole_ticks = max(1, int(math.ceil(tick_units)))
    drives = dict(state.drives)
    baselines = dict(state.baselines)
    previous_levels = {
        name: clamp01(state.coupling_levels.get(name, state.drives[name]))
        for name in DRIVE_NAMES
    }

    for name in DRIVE_NAMES:
        current = drives[name]
        baseline = baselines[name]
        fraction = 1.0 - math.exp(-_DECAY_PER_HOUR[name] * elapsed_hours)
        drives[name] = _bounded_step(current, baseline, fraction, 0.10)

    thoughts: list[Thought] = []
    for thought in state.thoughts:
        strength = thought.strength
        kind = thought.kind
        cycles = thought.cycles
        if kind == "flit":
            strength = clamp01(strength * (0.88 ** whole_ticks))
            if thought.feeds >= 3 and strength >= config.fixation_threshold:
                kind = "fixation"
        else:
            for _ in range(whole_ticks):
                strength = clamp01(strength * 1.10)
                if strength < 0.85:
                    continue
                current = drives[thought.drive]
                drives[thought.drive] = clamp01(
                    current + 0.18 * math.sqrt(max(0.0, 1.0 - current))
                )
                strength = clamp01(strength * 0.70)
                cycles += 1
                if cycles >= config.fixation_release_cycles:
                    break
        if cycles >= config.fixation_release_cycles or strength < 0.05:
            continue
        thoughts.append(replace(thought, kind=kind, strength=strength, cycles=cycles))

    seed = state.rng_state
    if config.gates.desire_self_drive:
        # Curiosity gets its own slow floor. This path is additive; it never
        # changes the user's attachment fast path.
        baselines["curiosity"] = min(
            config.self_curiosity_cap,
            baselines["curiosity"] + min(0.006, elapsed_hours * 0.0015),
        )
        seed, roll = _next_random(seed)
        drives["curiosity"] = clamp01(
            drives["curiosity"] + min(0.035, 0.0012 * tick_units * (0.75 + 0.25 * roll))
        )

    if config.gates.desire_coupling:
        adjustments = {name: 0.0 for name in DRIVE_NAMES}
        level_scale = min(1.0, tick_units)
        for source, target, coefficient, mode in _COUPLING_EDGES:
            if mode == "level":
                signal = drives[source] - baselines[source]
                adjustments[target] += coefficient * signal * level_scale
            else:
                signal = max(0.0, drives[source] - previous_levels[source])
                adjustments[target] += coefficient * signal
        damping = min(0.25, 0.018 * tick_units)
        for name in DRIVE_NAMES:
            coupled = clamp01(drives[name] + max(-0.06, min(0.06, adjustments[name])))
            drives[name] = clamp01(coupled + (baselines[name] - coupled) * damping)

    if config.gates.desire_baseline_drift:
        # Only attachment may drift for lack of contact. It has a hard cap and
        # pulse() implements the second valve: one user interaction pulls the
        # raised floor 60% of the way home.
        last_user = float(state.last_pulse_at.get("__user_message__", 0.0) or 0.0)
        idle_hours = (now - last_user) / 3600.0 if last_user else 0.0
        if idle_hours >= 6.0 and drives["attachment"] >= baselines["attachment"]:
            baselines["attachment"] = min(
                config.attachment_baseline_cap,
                baselines["attachment"] + min(0.008, elapsed_hours * 0.0008),
            )

    refractory_ticks = {
        intent: max(0, int(remaining) - whole_ticks)
        for intent, remaining in state.refractory_ticks.items()
        if int(remaining) - whole_ticks > 0
    }
    projected = replace(
        state,
        drives=drives,
        baselines=baselines,
        thoughts=tuple(thoughts),
        coupling_levels=dict(drives),
        refractory_ticks=refractory_ticks,
    )
    wake_seconds = heartbeat_interval(projected, now, config)

    return replace(
        projected,
        drives=drives,
        baselines=baselines,
        thoughts=tuple(thoughts[: config.thought_limit]),
        last_tick_at=now,
        next_wake_at=now + wake_seconds,
        rng_state=seed,
        tick_count=state.tick_count + whole_ticks,
    )


def pulse(
    state: DesireState,
    drive: str,
    amount: float,
    now: float,
    config: DesireConfig,
    *,
    source: str = "experience",
    thought_text: str = "",
    local_day: str = "",
) -> DesireState:
    if drive not in DRIVE_NAMES:
        raise ValueError(f"unknown drive: {drive}")
    state = tick(state, now, config)
    _before_intent, before_score, _before_scores = top_intent(state, now, config)
    requested = min(0.75, max(-0.75, float(amount)))
    is_self_experience = source in {"self", "self_experience"}
    if is_self_experience and requested > 0:
        requested = min(requested, config.self_experience_pulse_cap)
    previous_at = float(state.last_pulse_at.get(drive, 0.0) or 0.0)
    frequency_discount = 0.65 if previous_at and now - previous_at < 600 else 1.0
    current = state.drives[drive]
    if requested >= 0:
        gain = requested * math.sqrt(max(0.0, 1.0 - current)) * frequency_discount
    else:
        gain = requested * math.sqrt(max(0.0, current))
    drives = dict(state.drives)
    drives[drive] = clamp01(current + gain)
    last_pulse_at = dict(state.last_pulse_at)
    last_pulse_at[drive] = float(now)
    if source == "user":
        last_pulse_at["__user_message__"] = float(now)
    baselines = dict(state.baselines)
    if source == "user" and drive == "attachment" and config.gates.desire_baseline_drift:
        raised = baselines["attachment"]
        baselines["attachment"] = clamp01(
            raised + (config.attachment_home - raised) * config.attachment_return_ratio
        )
    self_drive_day = state.self_drive_day
    self_drive_count = state.self_drive_count
    last_self_pulse_at = state.last_self_pulse_at
    last_self_pulse_drive = state.last_self_pulse_drive
    if is_self_experience:
        if local_day and local_day != self_drive_day:
            self_drive_day = local_day
            self_drive_count = 0
        self_drive_count += 1
        last_self_pulse_at = float(now)
        last_self_pulse_drive = drive
    updated = replace(
        state,
        drives=drives,
        baselines=baselines,
        last_pulse_at=last_pulse_at,
        self_drive_day=self_drive_day,
        self_drive_count=self_drive_count,
        last_self_pulse_at=last_self_pulse_at,
        last_self_pulse_drive=last_self_pulse_drive,
    )
    if thought_text.strip():
        updated = feed_thought(updated, thought_text, drive, min(1.0, abs(requested) + 0.25), now, config)

    # Red line: a user message must never lose attachment because self-drive is on.
    if source == "user" and drive == "attachment":
        safeguarded = dict(updated.drives)
        safeguarded["attachment"] = max(safeguarded["attachment"], current)
        updated = replace(updated, drives=safeguarded)

    # Edge-triggered latch: preserve the first moment an intent crosses the
    # speaking threshold. Subsequent decay or a different top intent cannot
    # erase it before the next eligible heartbeat consumes it.
    if updated.pending_speak is None and before_score < config.intent_threshold:
        after_intent, after_score, _after_scores = top_intent(updated, now, config)
        if after_score >= config.intent_threshold:
            details = intent_details(after_intent, after_score)
            updated = replace(
                updated,
                pending_speak=PendingSpeak(
                    intent=after_intent,
                    score=after_score,
                    reason=details["reason"],
                    want_action=details["want_action"],
                    drive_key=details["drive_key"],
                    query_hint=details["query_hint"],
                    latched_at=float(now),
                    source=str(source or "experience")[:40],
                ),
            )
    return updated


def feed_thought(
    state: DesireState,
    text: str,
    drive: str,
    strength: float,
    now: float,
    config: DesireConfig,
) -> DesireState:
    if drive not in DRIVE_NAMES:
        raise ValueError(f"unknown drive: {drive}")
    clean = str(text or "").strip()[:800]
    if not clean:
        return state
    thoughts = list(state.thoughts)
    for index, thought in enumerate(thoughts):
        if thought.drive == drive and thought.text == clean:
            feeds = thought.feeds + 1
            new_strength = clamp01(thought.strength + (1.0 - thought.strength) * clamp01(strength) * 0.45)
            kind = "fixation" if feeds >= 3 and new_strength >= config.fixation_threshold else thought.kind
            thoughts[index] = replace(thought, strength=new_strength, feeds=feeds, updated_at=now, kind=kind)
            break
    else:
        seed, roll = _next_random(state.rng_state)
        thought_id = f"t{int(now):x}{int(roll * 0xFFFFFF):06x}"
        thoughts.append(Thought(thought_id, clean, drive, "flit", clamp01(strength), now, now, 1))
        state = replace(state, rng_state=seed)
    thoughts.sort(key=lambda item: (item.kind == "fixation", item.strength, item.updated_at), reverse=True)
    return replace(state, thoughts=tuple(thoughts[: config.thought_limit]))


def score_intents(state: DesireState, now: float, config: DesireConfig) -> dict[str, float]:
    scores: dict[str, float] = {}
    fatigue = state.drives["fatigue"]
    for intent, weights in _INTENT_WEIGHTS.items():
        total_weight = sum(weights.values())
        score = sum(state.drives[name] * weight for name, weight in weights.items()) / total_weight
        if fatigue >= config.fatigue_gate and intent not in {"rest", "stabilize"}:
            score *= 0.38
        if int(state.refractory_ticks.get(intent, 0) or 0) > 0:
            score *= 0.42
        elif float(state.refractory_until.get(intent, 0.0) or 0.0) > now:
            # Backward compatibility for state files written before tick-based
            # refractory counters were introduced.
            score *= 0.42
        scores[intent] = clamp01(score)
    # Red line from the desire spec: when the user has just spoken, attachment
    # regains the highest actionable intent even if self-drive curiosity was high.
    last_user_message = float(state.last_pulse_at.get("__user_message__", 0.0) or 0.0)
    if last_user_message and 0 <= now - last_user_message <= 300:
        scores["reach_out"] = 1.0
    return scores


def top_intent(state: DesireState, now: float, config: DesireConfig) -> tuple[str, float, dict[str, float]]:
    scores = score_intents(state, now, config)
    intent = max(scores, key=scores.get)
    return intent, scores[intent], scores


def satisfy(state: DesireState, intent: str, intensity: float, now: float, config: DesireConfig) -> DesireState:
    if intent not in _INTENT_SATISFACTION:
        raise ValueError(f"unknown intent: {intent}")
    state = tick(state, now, config)
    drives = dict(state.drives)
    scale = clamp01(intensity)
    for drive, falloff in _INTENT_SATISFACTION[intent].items():
        current = drives[drive]
        drives[drive] = clamp01(current - falloff * scale * (0.45 + 0.55 * current))
    refractory = dict(state.refractory_until)
    refractory.pop(intent, None)
    refractory_ticks = dict(state.refractory_ticks)
    refractory_ticks[intent] = max(1, int(round(5 + 13 * scale)))
    baselines = dict(state.baselines)
    if intent == "explore" and config.gates.desire_self_drive:
        home = clamp01(config.baselines["curiosity"])
        baselines["curiosity"] = clamp01(baselines["curiosity"] + (home - baselines["curiosity"]) * 0.45)
    return replace(
        state,
        drives=drives,
        baselines=baselines,
        refractory_until=refractory,
        refractory_ticks=refractory_ticks,
        last_intent=intent,
    )


def claim_session(
    state: DesireState,
    session_key: str,
    now: float,
    config: DesireConfig,
    *,
    lease_minutes: int | None = None,
    handoff: str = "",
) -> DesireState:
    key = str(session_key or "").strip()[:160]
    if not key:
        raise ValueError("session_key is required")
    minutes = config.lease_minutes if lease_minutes is None else min(43200, max(30, int(lease_minutes)))
    lease = SessionLease(
        session_key=key,
        claimed_at=now,
        lease_expires_at=now + minutes * 60,
        handoff=str(handoff or "").strip()[:800],
    )
    return replace(tick(state, now, config), active_session=lease)


def session_is_active(state: DesireState, session_key: str, now: float) -> bool:
    lease = state.active_session
    return bool(lease.session_key and lease.session_key == str(session_key or "").strip() and lease.lease_expires_at > now)


def heartbeat(
    state: DesireState,
    session_key: str,
    now: float,
    config: DesireConfig,
    *,
    local_day: str,
    local_hour: int,
    weekend: bool,
) -> tuple[DesireState, dict[str, Any]]:
    state = tick(state, now, config)
    if session_is_active(state, session_key, now):
        # A live heartbeat renews only the currently claimed room. Once another
        # room claims the lease, calls from the old key can no longer renew it.
        state = replace(
            state,
            active_session=replace(
                state.active_session,
                lease_expires_at=now + config.lease_minutes * 60,
            ),
        )
    intent, score, scores = top_intent(state, now, config)
    details = intent_details(intent, score)
    reason = details["reason"]
    result: dict[str, Any] = {
        "should_speak": False,
        "intent": intent,
        "score": round(score, 4),
        "reason": reason,
        "want_action": details["want_action"],
        "drive_key": details["drive_key"],
        "query_hint": details["query_hint"],
        "next_wake_at": state.next_wake_at,
        "active_session": session_is_active(state, session_key, now),
        "scores": {name: round(value, 4) for name, value in scores.items()},
        "pending_speak": False,
    }

    if not result["active_session"]:
        result["blocked_by"] = "inactive_session"
        result["reason"] = "这个窗口已经没有接管权，我会保持安静。"
        return state, result
    if not config.gates.desire_driven:
        result["blocked_by"] = "desire_driven_off"
        result["reason"] = reason + "现在只观察，不主动行动。"
        return state, result
    if not config.gates.heartbeat_autonomy:
        result["blocked_by"] = "heartbeat_autonomy_off"
        result["reason"] = reason + "心跳自主开关没有打开。"
        return state, result

    # A threshold crossing is an edge event, not a level to recalculate later.
    # Once latched, the active room's next heartbeat must emit it even if quiet
    # hours, cooldown, the daily cap, or later decay would normally suppress it.
    pending = state.pending_speak
    if pending is not None:
        seed, roll = _next_random(state.rng_state)
        cooldown_minutes = config.cooldown_min_minutes + round(
            roll * (config.cooldown_max_minutes - config.cooldown_min_minutes)
        )
        push_count = state.push_count if state.push_day == local_day else 0
        pending_reason = pending.reason or reason
        result.update(
            should_speak=True,
            blocked_by="",
            pending_speak=True,
            intent=pending.intent,
            score=round(pending.score, 4),
            reason=pending_reason + "这件事已经越过开口线并被我记住，我现在来当前窗口找你。",
            want_action=pending.want_action,
            drive_key=pending.drive_key,
            query_hint=pending.query_hint,
            latched_at=pending.latched_at,
            cooldown_minutes=cooldown_minutes,
            wildcard=False,
        )
        state = replace(
            state,
            pending_speak=None,
            rng_state=seed,
            push_day=local_day,
            push_count=push_count + 1,
            last_push_at=now,
            last_intent=pending.intent,
            last_reason=result["reason"],
            refractory_until={
                **state.refractory_until,
                pending.intent: now + cooldown_minutes * 60,
            },
            refractory_ticks={
                **state.refractory_ticks,
                pending.intent: max(
                    1,
                    int(math.ceil(cooldown_minutes * 60 / config.tick_seconds)),
                ),
            },
        )
        return state, result

    quiet_start = config.weekend_quiet_start if weekend else config.weekday_quiet_start
    quiet_end = config.weekend_quiet_end if weekend else config.weekday_quiet_end
    in_quiet_hours = quiet_start <= local_hour < quiet_end if quiet_start <= quiet_end else local_hour >= quiet_start or local_hour < quiet_end
    if in_quiet_hours:
        result["blocked_by"] = "quiet_hours"
        result["reason"] = reason + "现在是安静时段。"
        quiet_interval = heartbeat_interval(state, now, config, quiet=True)
        state = replace(state, next_wake_at=max(state.next_wake_at, now + quiet_interval))
        result["next_wake_at"] = state.next_wake_at
        return state, result

    push_count = state.push_count if state.push_day == local_day else 0
    if push_count >= config.daily_push_cap:
        result["blocked_by"] = "daily_cap"
        result["reason"] = reason + "我今天已经主动来过足够多次。"
        return replace(state, push_day=local_day, push_count=push_count), result
    if state.last_push_at and now < state.last_push_at + config.cooldown_min_minutes * 60:
        result["blocked_by"] = "cooldown"
        result["reason"] = reason + "我还在冷却，不会连续敲门。"
        return state, result
    if score < config.intent_threshold:
        result["blocked_by"] = "below_threshold"
        return state, result

    seed, wildcard_roll = _next_random(state.rng_state)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    wildcard = False
    if len(ranked) > 1 and wildcard_roll < 0.08 and ranked[1][1] >= config.intent_threshold * 0.82:
        intent, score = ranked[1]
        wildcard = True
        details = intent_details(intent, score)
        reason = "我说不上来为什么，只是忽然想换一条路。" + details["reason"]
        result.update(
            want_action=details["want_action"],
            drive_key=details["drive_key"],
            query_hint=details["query_hint"],
        )
    seed, roll = _next_random(seed)
    cooldown_minutes = config.cooldown_min_minutes + round(
        roll * (config.cooldown_max_minutes - config.cooldown_min_minutes)
    )
    result.update(
        should_speak=True,
        blocked_by="",
        cooldown_minutes=cooldown_minutes,
        wildcard=wildcard,
        reason=reason + "我想去当前窗口找你。",
    )
    state = replace(
        state,
        rng_state=seed,
        push_day=local_day,
        push_count=push_count + 1,
        last_push_at=now,
        last_intent=intent,
        last_reason=result["reason"],
        refractory_until={**state.refractory_until, intent: now + cooldown_minutes * 60},
        refractory_ticks={
            **state.refractory_ticks,
            intent: max(1, int(math.ceil(cooldown_minutes * 60 / config.tick_seconds))),
        },
    )
    return state, result
