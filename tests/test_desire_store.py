from __future__ import annotations

import json

from ombrebrain.desire.store import DesireService


def make_service(tmp_path, *, driven: bool = False) -> DesireService:
    return DesireService({
        "buckets_dir": str(tmp_path / "buckets"),
        "desire": {
            "gates": {
                "desire_driven": driven,
                "heartbeat_autonomy": driven,
            },
        },
    })


def test_operational_state_persists_outside_memory_buckets(tmp_path) -> None:
    service = make_service(tmp_path)
    now = 1_700_000_000.0
    service.pulse("attachment", 0.5, "user", "hello", now)

    state_path = tmp_path / "buckets" / ".system" / "desire_state.json"
    assert state_path.exists()
    assert not list((tmp_path / "buckets").glob("dynamic/*.md"))
    reloaded = make_service(tmp_path).state(now)
    assert reloaded["drives"]["attachment"] > reloaded["baselines"]["attachment"]
    assert reloaded["storage"] == "operational_state_not_long_term_memory"


def test_state_read_is_non_mutating(tmp_path) -> None:
    service = make_service(tmp_path)
    now = 1_700_000_000.0
    service.pulse("curiosity", 0.3, now=now)
    state_path = tmp_path / "buckets" / ".system" / "desire_state.json"
    before = state_path.read_bytes()
    service.state(now + 86400)
    after = state_path.read_bytes()
    assert after == before


def test_claiming_new_window_keeps_state_and_old_heartbeat_is_inactive(tmp_path) -> None:
    service = make_service(tmp_path, driven=True)
    now = 1_700_000_000.0
    service.pulse("attachment", 0.75, "user", now=now)
    before = service.state(now)["drives"]
    service.claim("old", now=now)
    service.claim("new", handoff="short capsule", now=now + 1)
    after = service.state(now + 1)["drives"]
    assert after == before
    result = service.heartbeat("old", now + 2)
    assert result["blocked_by"] == "inactive_session"


def test_corrupt_state_fails_closed(tmp_path) -> None:
    service = make_service(tmp_path, driven=True)
    service.store.path.parent.mkdir(parents=True)
    service.store.path.write_text("not json", encoding="utf-8")
    result = service.state(1_700_000_000.0)
    assert result["last_reason"].startswith("欲望状态文件无法读取")
    assert all(0.0 <= value <= 1.0 for value in result["drives"].values())


def test_state_projects_first_person_intent_and_self_drive_metrics(tmp_path) -> None:
    service = DesireService({
        "buckets_dir": str(tmp_path / "buckets"),
        "desire": {"gates": {"desire_self_drive": True}},
    })
    now = 1_700_000_000.0
    service.pulse("curiosity", 0.75, "self", "想看看新的代码", now)
    state = service.state(now)

    assert state["intent"]["reason"].startswith("我")
    assert state["intent"]["drive_key"] in state["drives"]
    assert state["self_drive"]["enabled"] is True
    assert state["self_drive"]["actions_today"] == 1
    assert state["self_drive"]["last_experience_pulse_drive"] == "curiosity"
