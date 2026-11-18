"""SDK transport protocol tests, with no live calls or actual credentials."""
import json

import pytest

from bom_pilot.agent import ProviderFailure
from bom_pilot.opendev import OpenDevProvider


def test_config_missing_no_request(monkeypatch):
    monkeypatch.delenv("OPENDEV_API_KEY", raising=False)
    with pytest.raises(ProviderFailure, match="opendev_secret_unavailable"):
        OpenDevProvider()


def test_sdk_native_roundtrip_fallback_preserves_real_tool_evidence(monkeypatch):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx")
    monkeypatch.setenv("OPENDEV_API_KEY", "fixture-placeholder")
    provider = OpenDevProvider()
    calls = []

    def respond(request):
        assert request.url.host == "api.openai-next.com"
        assert request.url.path == "/v1/chat/completions"
        data = json.loads(request.content)
        calls.append(data)
        if len(calls) == 1:
            assert data["tools"]
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "actual-id", "type": "function", "function": {"name": "analyze_bom", "arguments": "{}"}}
            ]}
        elif len(calls) == 2:
            assert data["messages"][-1]["role"] == "tool"
            return httpx.Response(400, json={"error": {"message": "Fixture rejected native feedback"}})
        else:
            assert "tools" not in data and "JSON Schema" in data["messages"][0]["content"]
            assert data["messages"][-1]["content"] == 'Actual tool result: {"total":"12.00"}'
            message = {"role": "assistant", "content": '{"name":"calculate_procurement_plan","arguments":{"strategy":"split"}}'}
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 1, "model": "claude-opus-5-5",
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10, "total_tokens": 50},
        })

    provider.close()
    provider._client = openai.OpenAI(api_key="fixture", base_url="https://api.openai-next.com/v1", max_retries=0,
                                     http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    messages = [{"role": "system", "content": "Test"}, {"role": "user", "content": "Test goal"}]
    try:
        first = provider.next_turn(messages)
        assert first.mode == "native" and first.usage["total_tokens"] == 50
        messages += [first.assistant, {"role": "tool", "tool_call_id": "actual-id", "content": '{"total":"12.00"}'}]
        second = provider.next_turn(messages)
        assert second.mode == "json_schema"
        assert second.calls[0]["arguments"] == {"strategy": "split"}
        assert [x["http_status"] for x in provider.attempts] == [200, 400, 200]
        assert provider.attempts[1]["fallback_reason"] == "native_feedback_rejected"
    finally:
        provider.close()
