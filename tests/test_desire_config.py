from utils import load_config


def test_desire_env_gates_are_explicit_and_default_off(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("buckets_dir: '" + str(tmp_path / "buckets") + "'\n", encoding="utf-8")
    for name in (
        "OMBRE_DESIRE_DRIVEN",
        "OMBRE_DESIRE_COUPLING",
        "OMBRE_DESIRE_BASELINE_DRIFT",
        "OMBRE_HEARTBEAT_AUTONOMY",
        "OMBRE_DESIRE_SELF_DRIVE",
    ):
        monkeypatch.delenv(name, raising=False)
    config = load_config(str(config_path))
    assert not any(config["desire"]["gates"].values())

    monkeypatch.setenv("OMBRE_DESIRE_DRIVEN", "true")
    monkeypatch.setenv("OMBRE_HEARTBEAT_AUTONOMY", "1")
    monkeypatch.setenv("OMBRE_DESIRE_SELF_DRIVE", "nonsense")
    config = load_config(str(config_path))
    assert config["desire"]["gates"]["desire_driven"] is True
    assert config["desire"]["gates"]["heartbeat_autonomy"] is True
    assert config["desire"]["gates"]["desire_self_drive"] is False
