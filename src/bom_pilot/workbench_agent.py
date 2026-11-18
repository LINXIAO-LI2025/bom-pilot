"""Request and context limits for the interactive JSON Schema Agent."""
import json

from .agent import DecisionAgent, DecisionLog, DecisionRun, ProviderFailure, feedback
from .decision_tools import DecisionTools
from .opendev import OpenDevProvider

MAX_REQUESTS = 7
MAX_OUTPUT_TOKENS = 512
MAX_REPORTED_TOKENS = 45_000
MAX_REQUEST_BYTES = 12_000
HISTORY_MESSAGES = 4


def compact_feedback(name, result):
    if name == "find_supplier_options":
        rows = result["options"]
        per_part = {}
        for row in rows:
            part = per_part.setdefault(row["part_number"], {"quotes": 0, "suppliers": set()})
            part["quotes"] += 1
            part["suppliers"].add(row["supplier"])
        sample = sorted(rows, key=lambda r: (r["part_number"], r["supplier"], r["min_qty"]))
        keys = ("part_number", "supplier", "currency", "unit", "unit_price", "min_qty", "max_qty", "moq", "stock_qty")
        return {"quote_count": len(rows),
                "parts": {part: {"quotes": info["quotes"], "supplier_count": len(info["suppliers"])}
                          for part, info in list(per_part.items())[:6]},
                "tier_examples": [{key: row[key] for key in keys} for row in sample[:4]],
                "omitted_tiers": max(0, len(rows) - 4),
                "unknown_parts": result["unknown_parts"][:4], "parts_without_quotes": result["parts_without_quotes"][:4]}
    summary = feedback(name, result).copy()
    for key, value in tuple(summary.items()):
        if isinstance(value, list) and len(value) > 5:
            summary[key] = value[:5]
            summary[f"{key}_omitted"] = len(value) - 5
    return summary


class WorkbenchProvider:
    def __init__(self, transport):
        self.transport = transport
        self.requests = 0
        self.reported_tokens = 0

    def next_turn(self, messages):
        if self.requests >= MAX_REQUESTS or self.reported_tokens >= MAX_REPORTED_TOKENS:
            raise ProviderFailure("request_usage_limit")
        system = {**messages[0], "content": messages[0]["content"] + (
            "\nKeep actions concise. The history is a rolling window. For straightforward requests, calculate, validate, "
            "and report the result promptly. Only request supplier details for specific decisions."
        )}
        recent = []
        for msg in messages[2:][-HISTORY_MESSAGES:]:
            content = msg["content"] or ""
            if len(content.encode("utf-8")) > 1200:
                if msg["role"] == "user" and content.startswith("Tool result ("):
                    label, _, raw = content.partition(": ")
                    try:
                        result = json.loads(raw)
                    except ValueError:
                        result = {}
                    keys = ("plan_id", "strategy", "total_cost", "complete", "accepted", "constraints",
                            "budget_overage", "quote_count", "part_count", "approval_status", "error")
                    compact = {key: result[key] for key in keys if key in result}
                    content = label + ": " + json.dumps({**compact, "details_omitted": True}, ensure_ascii=False)
                else:
                    content = "[Previous message exceeds the workbench context limit]"
            recent.append({**msg, "content": content})
        self.requests += 1
        turn = self.transport.next_turn([system, messages[1], *recent])
        usage = turn.usage.get("total_tokens")
        if not isinstance(usage, int):
            usage = sum(turn.usage.get(k) or 0 for k in ("prompt_tokens", "completion_tokens"))
        self.reported_tokens += max(0, usage)
        return turn


def run_live(tools: DecisionTools) -> DecisionRun:
    try:
        transport = OpenDevProvider(mode="json_schema", max_output_tokens=MAX_OUTPUT_TOKENS,
                                    timeout=35.0, max_request_bytes=MAX_REQUEST_BYTES)
    except ProviderFailure as exc:
        return DecisionRun("provider_error", [DecisionLog("provider_error", 0, {
            "code": exc.code, "http_status": exc.status,
        })])
    try:
        return DecisionAgent(WorkbenchProvider(transport), max_turns=MAX_REQUESTS,
                             summarize=compact_feedback, stop_after_report=True).run(tools)
    finally:
        transport.close()
