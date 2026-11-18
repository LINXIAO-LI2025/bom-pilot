"""Recompute acceptance for a saved demo report, without API access."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from bom_pilot import load_workbook, normalize_bom, normalize_quotes
from bom_pilot.agent_cli import demo_context
from bom_pilot.decision_tools import DecisionTools
from bom_pilot.procurement import validate_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, nargs="+")
    parser.add_argument("--workbook", default="examples/ai_box_demo.xlsx")
    args = parser.parse_args()
    raw_bom, raw_quotes = load_workbook(args.workbook)
    bom, quotes = normalize_bom(raw_bom), normalize_quotes(raw_quotes)
    for path in args.report:
        result = json.loads(path.read_text(encoding="utf-8"))
        context = demo_context(result["scenario"])
        if result["context"] != json.loads(json.dumps(asdict(context))):
            raise ValueError(f"{path}: report context does not match the demo")
        tools = DecisionTools(bom, quotes, context)
        report = result["report"]
        acceptance = validate_plan(bom, tools.scenario_quotes, report["proposal"], **tools.params,
                                   budget=tools.budget, locked_allocations=tools.locks)
        acceptance["constraints"]["reduction_baseline_available"] = tools.target_available
        acceptance["accepted"] = acceptance["accepted"] and tools.target_available
        saved = {k: v for k, v in result["validation"].items() if k != "plan_id"}
        if acceptance != saved:
            raise ValueError(f"{path}: independently computed acceptance differs from the saved result")
        print(json.dumps({
            "scenario": result["scenario"], "status": result["status"], "acceptance_reproduced": True,
            "tool_sequence": [{k: e["data"][k] for k in ("name", "arguments", "source")}
                              for e in result["log"] if e["kind"] == "tool_call"],
            "constraints": acceptance["constraints"], "gaps": acceptance["gaps"],
            "budget_overage": acceptance["budget_overage"], "recomputed_total": acceptance["recomputed_total"],
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
