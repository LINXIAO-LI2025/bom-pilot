"""OpenDev adapter. Never log provider bodies, headers, or environment values."""
import importlib
import json
import os
import re
from uuid import uuid4

from .agent import ACTION_SCHEMA, TOOLS, ProviderFailure, Turn

BASE_URL = "https://api.openai-next.com/v1"
DEFAULT_MODEL = "claude-opus-5-5"


class OpenDevProvider:
    def __init__(self, model: str = DEFAULT_MODEL, mode: str = "native", *,
                 max_output_tokens: int = 2048, timeout: float = 75.0, max_request_bytes: int | None = None):
        if mode not in {"native", "json_schema"}:
            raise ValueError("Unsupported provider mode")
        api_key = os.environ.get("OPENDEV_API_KEY")
        if not api_key:
            raise ProviderFailure("opendev_secret_unavailable")
        openai = importlib.import_module("openai")
        httpx = importlib.import_module("httpx")
        self._openai = openai
        self._client = openai.OpenAI(
            api_key=api_key, base_url=BASE_URL, max_retries=0, timeout=timeout,
            http_client=httpx.Client(follow_redirects=False, trust_env=True, timeout=timeout),
        )
        self.max_output_tokens = max_output_tokens
        self.max_request_bytes = max_request_bytes
        self.model = model
        self.mode = mode
        self.attempts = []

    def close(self):
        self._client.close()

    def next_turn(self, messages):
        try:
            return self._request(messages)
        except ProviderFailure as e:
            native_feedback_rejected = e.status == 400 and any(m["role"] == "tool" for m in messages)
            if self.mode != "native" or (e.code != "native_tools_unsupported" and not native_feedback_rejected):
                raise
            self.mode = "json_schema"
            self.attempts[-1]["fallback_reason"] = (
                "native_feedback_rejected" if native_feedback_rejected else e.code
            )
            return self._request(messages)

    @staticmethod
    def _text_history(messages):
        for msg in messages:
            if msg["role"] == "tool":
                yield {"role": "user", "content": "Actual tool result: " + msg["content"]}
            elif msg.get("tool_calls"):
                actions = [call["function"] for call in msg["tool_calls"]]
                yield {"role": "assistant", "content": json.dumps({"previous_tool_calls": actions}, ensure_ascii=False)}
            else:
                yield msg

    def _request(self, messages):
        params = {"model": self.model, "max_tokens": self.max_output_tokens}
        if self.mode == "native":
            params.update(tools=TOOLS, tool_choice="auto")
        else:
            schema_instruction = (
                "Return exactly one JSON action conforming to this JSON Schema, no Markdown or prose. "
                "The application checks the schema before executing any action. "
                + json.dumps(ACTION_SCHEMA, ensure_ascii=False)
            )
            messages = [
                {"role": "system", "content": messages[0]["content"] + "\n" + schema_instruction},
                *self._text_history(messages[1:]),
            ]
        if self.max_request_bytes is not None:
            size = len(json.dumps({"messages": messages, **params}, ensure_ascii=False,
                                  separators=(",", ":")).encode("utf-8"))
            if size > self.max_request_bytes:
                raise ProviderFailure("request_context_limit")
        try:
            raw = self._client.chat.completions.with_raw_response.create(messages=messages, **params)
        except self._openai.APIStatusError as e:
            # Inspect the provider error in memory, and emit only a fixed classification.
            unsupported = (self.mode == "native" and e.status_code in {400, 422, 501} and re.search(
                r"(tool|function.call).{0,100}(unsupported|not supported|not implemented)|"
                r"(unsupported|not supported|not implemented).{0,100}(tool|function.call)", str(e), re.I
            ))
            self.attempts.append({"mode": self.mode, "http_status": e.status_code})
            raise ProviderFailure("native_tools_unsupported" if unsupported else "opendev_http_error", e.status_code) from None
        except self._openai.APIConnectionError:
            self.attempts.append({"mode": self.mode, "http_status": None})
            raise ProviderFailure("opendev_connection_error") from None
        self.attempts.append({"mode": self.mode, "http_status": raw.status_code})
        try:
            response = raw.parse()
            message = response.choices[0].message
        except (TypeError, AttributeError, ValueError, IndexError):
            raise ProviderFailure("opendev_invalid_response", raw.status_code) from None
        usage = {k: getattr(response.usage, k, None) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
        calls = []
        if self.mode == "native":
            assistant = {"role": "assistant", "content": None}
            raw_calls = []
            for call in message.tool_calls or []:
                if call.type != "function":
                    raise ProviderFailure("opendev_invalid_tool_call", raw.status_code)
                try:
                    args = json.loads(call.function.arguments)
                except (TypeError, ValueError):
                    args = None
                calls.append({"id": call.id, "name": call.function.name, "arguments": args})
                raw_calls.append({"id": call.id, "type": "function", "function": {
                    "name": call.function.name, "arguments": call.function.arguments,
                }})
            if raw_calls:
                assistant["tool_calls"] = raw_calls
            else:
                assistant["content"] = message.content or ""
        else:
            assistant = {"role": "assistant", "content": message.content or ""}
            try:
                action = json.loads(assistant["content"])
            except ValueError:
                action = None
            if not isinstance(action, dict) or set(action) != {"name", "arguments"}:
                action = {}
            if action != {"name": "finish", "arguments": {}}:
                calls.append({"id": uuid4().hex, "name": action.get("name"), "arguments": action.get("arguments")})
        return Turn(calls, assistant, usage, response.model, self.mode, raw.status_code)
