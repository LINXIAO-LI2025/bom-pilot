from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from itertools import product
import json
from pathlib import Path
import random

import pandas as pd
import pytest

from bom_pilot import load_workbook, normalize_bom, normalize_quotes
from bom_pilot.agent import DecisionAgent, Turn
from bom_pilot.agent_cli import demo_context
from bom_pilot.decision_tools import DecisionContext, DecisionTools, Disruption
from bom_pilot.procurement import calculate_procurement_plan, validate_plan

PARAMS = {"batch_size": 10, "as_of": "2026-11-18"}
BOOK = Path(__file__).resolve().parents[1] / "examples/ai_box_demo.xlsx"


def fixture(rows):
    bom = normalize_bom(pd.DataFrame([{
        "part_number": "P", "description": "Example", "category": "Module",
        "quantity_per_unit": "1", "unit": "EA",
    }]))
    quotes = normalize_quotes(pd.DataFrame([{
        "quote_id": f"Q{i}", "part_number": "P", "supplier": name, "quote_date": "2026-11-01",
        "currency": "CNY", "unit": "EA", "unit_price": price,
        "min_qty": lower, "max_qty": upper, "stock_qty": stock, "moq": moq,
    } for i, (name, price, lower, upper, stock, moq) in enumerate(rows)]))
    return bom, quotes


def test_exact_split_and_moq_make_greedy_allocation_suboptimal():
    bom, quotes = fixture([("A", "1", 1, "", 8, 1), ("B", "3", 1, "", 10, 4)])
    plan = calculate_procurement_plan(bom, quotes, **PARAMS)
    assert [(a["supplier"], a["quantity"]) for a in plan["items"][0]["allocations"]] == [("A", "6"), ("B", "4")]
    assert plan["total_cost"] == "18.00"
    assert validate_plan(bom, quotes, plan, **PARAMS, budget=Decimal("18"))["accepted"]


def test_solver_can_use_non_greedy_discount_tier():
    bom, quotes = fixture([("A", "4", 1, 5, 8, 1), ("A", "1", 6, "", 8, 1),
                           ("B", "2", 1, "", 5, 1)])
    plan = calculate_procurement_plan(bom, quotes, **PARAMS)
    assert plan["total_cost"] == "12.00"
    assert plan["items"][0]["allocations"][0]["quote_id"] == "Q1"


@pytest.mark.parametrize("rows,status,gap", [
    ([("A", "1", 1, "", 4, 1), ("B", "1", 1, "", 3, 1)], "supply_gap", 3),
    ([("A", "1", 1, "", 10, 11)], "tier_or_moq_unavailable", 10),
    ([("A", "", 1, "", 10, 1)], "no_compatible_quote", 10),
    ([("A", "1", 1, "", 7, 7), ("B", "1", 1, "", 4, 4)], "supply_gap", 3),
])
def test_infeasible_supply_cases(rows, status, gap):
    bom, quotes = fixture(rows)
    result = calculate_procurement_plan(bom, quotes, **PARAMS)
    assert result["total_cost"] is None
    assert result["items"][0]["status"] == status
    assert Decimal(result["items"][0]["gap_qty"]) == gap
    assert not validate_plan(bom, quotes, result, **PARAMS)["accepted"]


def test_search_cap_is_not_reported_as_proven_stock_shortage(monkeypatch):
    import bom_pilot.procurement as engine
    monkeypatch.setattr(engine, "MAX_TRANSITIONS", 0)
    bom, quotes = fixture([("A", "1", 1, "", 10, 1), ("B", "1", 1, "", 10, 1)])
    result = calculate_procurement_plan(bom, quotes, **PARAMS)
    assert result["items"][0]["status"] == "search_limit"
    assert result["items"][0]["gap_qty"] is None


def test_validate_detects_fabricated_values_and_duplicate_supplier_orders():
    bom, quotes = fixture([("A", "1", 1, 5, 10, 1), ("A", "1", 6, "", 10, 1)])
    plan = calculate_procurement_plan(bom, quotes, **PARAMS)
    tampered = deepcopy(plan)
    order = tampered["items"][0]["allocations"][0]
    order["cost"] = "0"
    order["unit_price"] = "0"
    assert validate_plan(bom, quotes, tampered, **PARAMS)["order_errors"][0]["code"] == "order_metadata_or_cost_mismatch"
    order["quote_id"] = "MADE-UP"
    assert not validate_plan(bom, quotes, tampered, **PARAMS)["constraints"]["demand_met"]
    duplicate = deepcopy(plan)
    duplicate["items"][0]["allocations"] *= 2
    assert not validate_plan(bom, quotes, duplicate, **PARAMS)["constraints"]["quotes_and_orders_valid"]
    assert not validate_plan(bom, quotes, plan, **PARAMS, locked_allocations={"P": {"B": Decimal(10)}})["accepted"]


def test_stock_event_only_changes_active_copy_and_preserves_locks():
    bom, quotes = fixture([("A", "1", 1, "", 10, 1), ("B", "2", 1, "", 10, 1)])
    ctx = DecisionContext("Lock P while simulating A's shortage", **PARAMS, locked_parts=("P",),
                          disruptions=(Disruption("stock_cap", "P", "A", "4"),))
    tools = DecisionTools(bom, quotes, ctx)
    assert quotes.data.iloc[0]["stock_qty"] == 10
    assert tools.simulate_disruption()["events"][0]["after"] == "4"
    plan = tools.calculate_procurement_plan("split")
    assert not tools.validate_plan(plan["plan_id"])["constraints"]["locked_allocations_preserved"]
    flexible = DecisionTools(bom, quotes, replace(ctx, locked_parts=()))
    plan = flexible.calculate_procurement_plan("split")
    assert plan["total_cost"] == "16.00"


def test_dp_matches_exhaustive_reference_for_small_cases():
    rng = random.Random(5)
    for _ in range(20):
        rows = [(f"S{i}", str(rng.randint(1, 9)), 1, "", rng.randint(1, 8), rng.randint(1, 5))
                for i in range(3)]
        bom, quotes = fixture(rows)
        all_quantities = [[0, *range(moq, stock + 1)] for _, _, _, _, stock, moq in rows]
        oracle = min((-sum(q), sum(x * int(row[1]) for x, row in zip(q, rows)))
                     for q in product(*all_quantities) if sum(q) <= 10)
        case = calculate_procurement_plan(bom, quotes, **PARAMS)["items"][0]
        assert Decimal(case["allocated_qty"]) == -oracle[0]
        assert Decimal(case["subtotal"]) == oracle[1]


class ScriptedTransport:
    """Offline protocol fixture. Only the transport is scripted; every tool is real."""
    def __init__(self, actions, mode="native"):
        self.actions = iter(actions)
        self.mode = mode
        self.observed = []

    def next_turn(self, messages):
        self.observed.append(deepcopy(messages))
        try:
            name, args = next(self.actions)
            calls = [{"name": name, "arguments": args, "id": f"fixture-{len(self.observed)}"}]
        except StopIteration:
            calls = []
        return Turn(calls, {"role": "assistant", "content": "TEST FIXTURE"}, {}, "offline_fixture", self.mode)


def action(name, **kwargs):
    return name, kwargs


@pytest.mark.parametrize("scenario,total,req_gap,expected", [
    ("A", "30434.20", None, "pending_review"),
    ("B", None, Decimal(40), "constraints_not_met"),
    ("C", "29822.20", None, "constraints_not_met"),
])
def test_end_to_end_offline(scenario, total, req_gap, expected):
    b, q = load_workbook(BOOK)
    steps = [action("analyze_bom"), action("find_supplier_options", part_numbers=["AI-001", "AI-008"])]
    if scenario == "A":
        steps += [action("simulate_disruption")]
    if scenario == "B":
        steps += [action("calculate_procurement_plan", strategy="single"), action("validate_plan", plan_id="plan-1")]
    final_id = "plan-2" if scenario == "B" else "plan-1"
    steps += [action("calculate_procurement_plan", strategy="split"),
              action("validate_plan", plan_id=final_id), action("generate_change_report", plan_id=final_id)]
    provider = ScriptedTransport(steps)
    run = DecisionAgent(provider).run(DecisionTools(normalize_bom(b), normalize_quotes(q), demo_context(scenario)))
    record = json.loads(json.dumps(run.to_dict(), allow_nan=False))
    assert run.status == expected
    assert record["validation"]["recomputed_total"] == total
    assert record["report"]["proposed_bom"][0]["data_notice"].startswith("FICTIONAL")
    assert [e["data"]["name"] for e in record["log"] if e["kind"] == "tool_call"] == [name for name, _ in steps]
    assert any(msg["role"] == "tool" for msg in provider.observed[-1])
    if req_gap:
        assert Decimal(run.validation["gaps"][0]["gap_qty"]) == req_gap
        assert run.replans == 1
    if scenario == "A":
        assert Decimal(run.report["scenario_incumbent_total"]) > Decimal(total)
        assert run.validation["constraints"]["locked_allocations_preserved"]
    if scenario == "C":
        assert run.validation["constraints"]["budget_met"] is False
        assert Decimal(run.validation["budget_overage"]) == Decimal("2385.776")


def test_failed_plans_replan_at_most_three_even_with_model_requesting_more():
    bom, quotes = fixture([("A", "1", 1, "", 7, 1)])
    tools = DecisionTools(bom, quotes, DecisionContext("Impossible constraint", **PARAMS))
    actions = []
    for i in range(4):
        actions.extend([action("calculate_procurement_plan", strategy="split"), action("validate_plan", plan_id=f"plan-{i+1}")])
    actions.extend([action("calculate_procurement_plan", strategy="split"), action("generate_change_report", plan_id="plan-4")])
    run = DecisionAgent(ScriptedTransport(actions, "json_schema")).run(tools)
    assert run.replans == 3 and len(tools.plans) == 4
    assert any(e.data.get("result") == {"error": "replan_limit_reached"} for e in run.log)


def test_out_of_schema_actions_and_unverified_report_do_not_execute():
    bom, quotes = fixture([("A", "1", 1, "", 10, 1)])
    tools = DecisionTools(bom, quotes, DecisionContext("Compute", **PARAMS))
    steps = [(["unexpected"], {}), action("calculate_procurement_plan", strategy="split"),
             action("generate_change_report", plan_id="plan-1")]
    run = DecisionAgent(ScriptedTransport(steps)).run(tools)
    errors = [e.data["result"]["error"] for e in run.log if e.kind == "tool_call" and "error" in e.data["result"]]
    assert errors == ["invalid_tool_arguments", "validate_before_reporting"]
    assert run.validation["accepted"]
    assert any(e.data.get("name") == "validate_plan" and e.data["source"] == "controller" for e in run.log)


def test_agent_can_withhold_a_proposal_pending_structured_constraints():
    bom, quotes = fixture([("A", "1", 1, "", 10, 1)])
    tools = DecisionTools(bom, quotes, DecisionContext("Do not change restricted suppliers", **PARAMS))
    r = DecisionAgent(ScriptedTransport([action("request_clarification", reason="missing_structured_constraint")])).run(tools)
    assert r.status == "clarification_required"
    assert r.report is None and not tools.plans
