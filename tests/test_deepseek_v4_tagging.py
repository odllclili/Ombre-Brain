from pathlib import Path
from types import SimpleNamespace

import pytest

import dehydrator as dehydrator_module
from dehydrator import Dehydrator, safe_provider_error
from provider_detect import deepseek_chat_request_options


ROOT = Path(__file__).resolve().parents[1]


class RecordingClient:
    def __init__(self, *, content='{"ok": true}', error=None):
        self.content = content
        self.error = error
        self.calls = []
        self.retry_options = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create),
        )

    def with_options(self, **kwargs):
        self.retry_options.append(kwargs)
        return self

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.content),
                )
            ]
        )


def make_dehydrator(tmp_path, *, base_url, model):
    return Dehydrator(
        {
            "buckets_dir": str(tmp_path / "vault"),
            "dehydration": {
                "api_key": "test-key",
                "api_format": "openai_compat",
                "base_url": base_url,
                "model": model,
                "timeout_seconds": 1,
            },
        }
    )


@pytest.mark.asyncio
async def test_official_deepseek_legacy_chat_moves_to_v4_non_thinking(tmp_path):
    dehy = make_dehydrator(
        tmp_path,
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )
    client = RecordingClient()
    dehy.client = client

    await dehy._chat_once("system", "user")

    assert client.calls[0]["model"] == "deepseek-v4-flash"
    assert client.calls[0]["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert client.retry_options == [{"max_retries": 0}]
    dehy.close()


@pytest.mark.asyncio
async def test_official_deepseek_legacy_reasoner_preserves_thinking(tmp_path):
    dehy = make_dehydrator(
        tmp_path,
        base_url="https://api.deepseek.com",
        model="deepseek-reasoner",
    )
    client = RecordingClient()
    dehy.client = client

    await dehy._chat_once("system", "user")

    assert client.calls[0]["model"] == "deepseek-v4-flash"
    assert client.calls[0]["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    dehy.close()


@pytest.mark.asyncio
async def test_third_party_deepseek_model_is_not_rewritten(tmp_path):
    dehy = make_dehydrator(
        tmp_path,
        base_url="https://api.siliconflow.cn/v1",
        model="deepseek-chat",
    )
    client = RecordingClient()
    dehy.client = client

    await dehy._chat_once("system", "user")

    assert client.calls[0]["model"] == "deepseek-chat"
    assert "extra_body" not in client.calls[0]
    dehy.close()


def test_deceptive_deepseek_hostname_is_not_matched():
    model, extra = deepseek_chat_request_options(
        "deepseek-chat",
        "https://api.deepseek.com.evil.example/v1",
    )

    assert model == "deepseek-chat"
    assert extra is None


@pytest.mark.asyncio
async def test_outer_retry_is_the_only_retry_layer(tmp_path, monkeypatch):
    class ProviderUnavailable(RuntimeError):
        status_code = 503

    dehy = make_dehydrator(
        tmp_path,
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash",
    )
    client = RecordingClient(error=ProviderUnavailable("temporarily unavailable"))
    dehy.client = client

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(dehydrator_module.asyncio, "sleep", no_sleep)
    with pytest.raises(ProviderUnavailable):
        await dehy._chat("system", "user")

    assert len(client.calls) == 3
    assert client.retry_options == [{"max_retries": 0}] * 3
    dehy.close()


def test_provider_error_summary_keeps_cause_and_redacts_secrets():
    class ProviderError(RuntimeError):
        status_code = 400
        request_id = "req_test_123"
        body = {
            "error": {
                "code": "model_not_found",
                "message": (
                    "retired model; Bearer sk-secret-123456789 "
                    "https://api.example/v1?key=hidden-value"
                ),
            }
        }

    provider = ProviderError("raw provider error")
    wrapper = RuntimeError("API 打标失败")
    wrapper.__cause__ = provider

    summary = safe_provider_error(wrapper, "sk-secret-123456789")

    assert "HTTP 400" in summary
    assert "code=model_not_found" in summary
    assert "retired model" in summary
    assert "request_id=req_test_123" in summary
    assert "sk-secret-123456789" not in summary
    assert "hidden-value" not in summary
    assert "[REDACTED]" in summary


def test_shipped_deepseek_presets_no_longer_use_retired_aliases():
    config = (ROOT / "config.example.yaml").read_text(encoding="utf-8")
    dashboard = (ROOT / "frontend" / "dashboard.html").read_text(
        encoding="utf-8"
    )

    assert 'model: "deepseek-v4-flash"' in config
    assert "model: 'deepseek-v4-flash'" in dashboard
    assert "deepseek-chat" not in config
    assert "deepseek-chat" not in dashboard
