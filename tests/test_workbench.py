from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path

import pytest
from openpyxl import load_workbook

from bom_pilot.agent import DecisionAgent, ProviderFailure, Turn
from bom_pilot.agent_cli import demo_context
from bom_pilot.decision_tools import DecisionTools
from bom_pilot.export import export_result
from bom_pilot.workbench import cost_comparison, cost_view, load_dataset, load_demo, run_demo, run_task
from bom_pilot.workbench_agent import (
    HISTORY_MESSAGES, MAX_REPORTED_TOKENS, MAX_REQUESTS, WorkbenchProvider, compact_feedback,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
AS_OF = "2026-11-18"


def test_excel_and_csv_import_preserve_phase_one_data_and_flags():
    sample = load_demo()
    csv = load_dataset(EXAMPLES / "ai_box_bom.csv", EXAMPLES / "supplier_quotes.csv")
    upload = load_dataset(EXAMPLES / "ai_box_demo.xlsx")
    for dataset in (sample, csv, upload):
        assert (dataset.raw_bom_rows, dataset.raw_quote_rows) == (20, 160)
        single, bulk = cost_view(dataset, 100, AS_OF, "cny")
        assert single["total_cost"] == "2982.40"
        assert bulk["total_cost"] is None
        assert bulk["priced_subtotal"] == "265176.00"
    assert sample.demo and not csv.demo
    bad = load_dataset(EXAMPLES / "ai_box_bom.csv", EXAMPLES / "supplier_quotes_invalid.csv")
    assert any(i.code == "missing_price" for i in bad.quotes.issues)
    bom_only = load_dataset(EXAMPLES / "ai_box_bom.csv")
    assert cost_view(bom_only, 10, AS_OF, "CNY")[0]["unpriced_lines"] == 20


@pytest.mark.parametrize("case,total,status", [
    ("A", "30434.20", "pending_review"), ("B", None, "constraints_not_met"),
    ("C", "29822.20", "constraints_not_met"),
])
def test_local_demo_executes_real_tools_and_records_independent_validation(case, total, status):
    run = run_demo(case)
    assert run.status == status
    tool_log = [e for e in run.log if e.kind == "tool_call"]
    assert all(e.data["source"] == "local_workflow" for e in tool_log)
    checks = [e.data["result"] for e in tool_log if e.data["name"] == "validate_plan"]
    assert checks[-1] == run.validation and run.validation["recomputed_total"] == total
    if case == "A":
        assert list(cost_comparison(run.report))[-1][1] == "3468.00"
    if case == "B":
        assert run.replans == 1 and len(checks) == 2
        assert [Decimal(check["gaps"][0]["gap_qty"]) for check in checks] == [120, 40]
        assert any(e.round == 1 and e.data["name"] == "calculate_procurement_plan" for e in tool_log)
        assert dict(cost_comparison(run.report))["建议采购完整成本"] is None
    if case == "C":
        assert Decimal(run.validation["budget_overage"]) == Decimal("2385.776")


def test_download_has_required_sheets_and_preserves_partial_cost_and_literal_inputs(tmp_path):
    run = run_demo("B")
    run.report["proposed_bom"][0]["description"] = "=1+1"
    workbook = load_workbook(export_result(run, "虚构演示", tmp_path))
    assert workbook.sheetnames == ["采购建议", "成本对比", "未满足约束", "库存缺口", "待审批项", "建议BOM"]
    costs = {row[0]: row[1] for row in workbook["成本对比"].iter_rows(min_row=2, values_only=True)}
    assert costs["建议采购完整成本"] in (None, "")
    assert costs["建议方案已分配小计（部分）"] == "268099.20"
    assert workbook["库存缺口"]["D2"].value == "40.00"
    assert workbook["未满足约束"]["B2"].value == "未满足"
    assert workbook["建议BOM"]["B2"].data_type == "s"
    workbook.close()


def test_known_data_is_queried_locally_and_only_compact_sample_passed_to_model():
    data = load_demo()
    tools = DecisionTools(data.bom, data.quotes, demo_context("A"))
    result = tools.find_supplier_options(list(data.bom.data["part_number"]))
    summary = compact_feedback("find_supplier_options", result)
    assert summary["quote_count"] == 80 and len(summary["tier_examples"]) == 4
    assert "source_row" not in summary["tier_examples"][0]
    assert "options" not in summary and summary["omitted_tiers"] == 76
    assert len(result["options"]) == 80


class Transport:
    def __init__(self, steps, usage=100):
        self.steps = iter(steps)
        self.usage = usage
        self.messages = []

    def next_turn(self, messages):
        self.messages.append(deepcopy(messages))
        name, parameters = next(self.steps)
        arguments = {"name": name, "arguments": parameters}
        return Turn([{"id": "fixture", **arguments}], {"role": "assistant", "content": json.dumps(arguments)},
                    {"total_tokens": self.usage}, "offline_fixture", "json_schema")


def test_context_retains_goal_bounds_history_and_stops_at_report():
    data = load_demo()
    tools = DecisionTools(data.bom, data.quotes, demo_context("A"))
    transport = Transport([
        ("analyze_bom", {}), ("simulate_disruption", {}),
        ("find_supplier_options", {"part_numbers": list(data.bom.data["part_number"])}),
        ("calculate_procurement_plan", {"strategy": "split"}), ("validate_plan", {"plan_id": "plan-1"}),
        ("generate_change_report", {"plan_id": "plan-1"}),
    ])
    provider = WorkbenchProvider(transport)
    run = DecisionAgent(provider, summarize=compact_feedback, stop_after_report=True).run(tools)
    assert run.status == "pending_review" and provider.requests == 6
    assert all(len(m) <= HISTORY_MESSAGES + 2 and "虚构演示" in m[1]["content"] for m in transport.messages)
    assert "source_row" not in json.dumps(transport.messages)
    assert len(next(log.data["result"]["options"] for log in run.log
                    if log.data.get("name") == "find_supplier_options")) == 80


def test_request_and_reported_usage_caps_prevent_additional_requests():
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "goal"}]
    transport = Transport([("analyze_bom", {})] * (MAX_REQUESTS + 1))
    providers = [WorkbenchProvider(transport)]
    high_usage = Transport([("analyze_bom", {})] * 2, MAX_REPORTED_TOKENS)
    providers.append(WorkbenchProvider(high_usage))
    for provider, cap in zip(providers, (MAX_REQUESTS, 1)):
        for _ in range(cap):
            provider.next_turn(messages)
        with pytest.raises(ProviderFailure, match="request_usage_limit"):
            provider.next_turn(messages)
        assert len(provider.transport.messages) == cap


def test_live_requires_consent_and_handles_missing_secret(monkeypatch):
    data = load_demo()
    args = (data, "计算批量采购", 10, AS_OF, "CNY", None, None, None)
    with pytest.raises(ValueError, match="OpenDev"):
        run_task(*args, False)
    monkeypatch.delenv("OPENDEV_API_KEY", raising=False)
    run = run_task(*args, True)
    assert run.status == "provider_error"
    assert run.log[0].data["code"] == "opendev_secret_unavailable"
    assert run.report is None


def test_gradio_renders_unmet_scenario_as_partial_not_full():
    pytest.importorskip("gradio")
    pytest.importorskip("plotly")
    from bom_pilot.ui import render_run
    outputs = render_run(run_demo("B"), "虚构 AI BOX", "本地演示")
    assert "目标未达成" in outputs[1] and "重规划 1 次" in outputs[1]
    assert "建议方案已分配小计（部分）" in outputs[6]
    assert "40.00" in outputs[8]["缺口"].tolist()


def test_oversize_model_request_is_rejected_before_http(monkeypatch):
    pytest.importorskip("openai")
    from bom_pilot.opendev import OpenDevProvider
    monkeypatch.setenv("OPENDEV_API_KEY", "fixture-placeholder")
    transport = OpenDevProvider(mode="json_schema", max_request_bytes=4000)
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "测试" * 3000}]
    try:
        with pytest.raises(ProviderFailure, match="request_context_limit"):
            transport.next_turn(messages)
        assert transport.attempts == []
    finally:
        transport.close()
