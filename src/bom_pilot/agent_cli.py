"""Run the real model-driven workflow and export the audit trail."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .agent import DecisionAgent, ProviderFailure
from .decision_tools import DecisionContext, DecisionTools, Disruption
from .io import load_workbook
from .normalize import normalize_bom, normalize_quotes
from .opendev import DEFAULT_MODEL, OpenDevProvider


def demo_context(scenario):
    common = {"as_of": "2026-11-18"}
    if scenario == "A":
        return DecisionContext(
            "虚构演示：两项物料的 A 供应商报价上涨 20%。检查主要成本及受影响报价，找最低成本采购方案，"
            "锁定 AI-004 的原供应商和采购数量。比较原价、维持原采购分配的涨价后成本、新方案成本。",
            batch_size=10, locked_parts=("AI-004",), disruptions=(
                Disruption("price_increase_pct", "AI-001", "虚构供应商-A", "20"),
                Disruption("price_increase_pct", "AI-003", "虚构供应商-A", "20"),
            ), **common,
        )
    if scenario == "B":
        return DecisionContext(
            "虚构演示：生产 100 台。先验证单供应商分配，若失败尝试拆分供应商订单。"
            "即使仍缺料，也请说明可分配数量和剩余缺口，并输出变更报告。",
            batch_size=100, **common,
        )
    if scenario == "C":
        return DecisionContext(
            "虚构演示：生产 10 台，目标比原单供应商采购方案降低 8% 成本。"
            "验证可达到的最低成本。若未达目标，说明预算差额和原因。",
            batch_size=10, reduction_pct="8", **common,
        )
    raise ValueError("Unknown demo scenario")


def main():
    p = argparse.ArgumentParser(description="BOM Pilot OpenDev decision run")
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("--scenario", choices=("A", "B", "C"))
    choice.add_argument("--context", type=Path, help="DecisionContext JSON for a custom goal")
    p.add_argument("--workbook", type=Path, default=Path("examples/ai_box_demo.xlsx"))
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--mode", choices=("native", "json_schema"), default="native")
    p.add_argument("--output", type=Path, required=True, help="New JSON audit file")
    args = p.parse_args()
    if args.output.exists():
        p.error("Output already exists")
    try:
        provider = OpenDevProvider(args.model, args.mode)
    except ProviderFailure as e:
        print(json.dumps({"status": "provider_error", "code": e.code, "http_status": e.status}))
        return 1

    try:
        if args.scenario:
            context = demo_context(args.scenario)
        else:
            data = json.loads(args.context.read_text(encoding="utf-8"))
            data["disruptions"] = tuple(Disruption(**e) for e in data.get("disruptions", []))
            context = DecisionContext(**data)
        b, q = load_workbook(args.workbook)
        tools = DecisionTools(normalize_bom(b), normalize_quotes(q), context)
        run = DecisionAgent(provider).run(tools)
        payload = {"schema_version": "2.0", "scenario": args.scenario, "context": asdict(context),
                   "api_attempts": provider.attempts, **run.to_dict()}
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(payload, output, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({"status": run.status, "log": str(args.output),
                          "replans": run.replans, "requests": len(provider.attempts)}, ensure_ascii=False))
        return 1 if run.status in {"provider_error", "incomplete", "no_proposal", "clarification_required"} else 0
    finally:
        provider.close()


if __name__ == "__main__":
    raise SystemExit(main())
