"""Workbench services shared by Gradio and automated checks."""
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import pandas as pd

from .agent import DecisionLog, DecisionRun
from .agent_cli import demo_context
from .decision_tools import DecisionContext, DecisionTools
from .engine import calculate
from .io import load_workbook, read_table
from .models import NormalizedTable
from .normalize import BOM_COLUMNS, QUOTE_COLUMNS, normalize_bom, normalize_quotes
from .workbench_agent import run_live

DEMO_BOOK = Path(__file__).resolve().parents[2] / "examples" / "ai_box_demo.xlsx"
SCENARIOS = {"A": "涨价 20%", "B": "100 台缺料", "C": "降本 8%"}
BOM_HEADERS = dict(zip(BOM_COLUMNS, ("料号", "物料名称", "分类", "单机用量", "单位")))
ISSUE_HEADERS = {"table": "表", "row": "行号", "field": "字段", "code": "问题", "message": "说明"}
CONSTRAINTS = {
    "inputs_valid": "输入数据有效", "demand_met": "足量覆盖生产需求",
    "quotes_and_orders_valid": "报价、阶梯、MOQ 与库存有效", "locked_allocations_preserved": "保留锁定采购分配",
    "reported_cost_matches": "采购金额独立复算一致", "budget_met": "预算或降本目标达成",
    "reduction_baseline_available": "存在可用的降本基准",
}
STATUS = {
    "pending_review": "独立验收通过 · 待审批",
    "constraints_not_met": "目标未达成",
    "provider_error": "模型调用中止",
    "clarification_required": "目标或约束需要补充",
    "no_proposal": "模型未生成采购方案",
    "incomplete": "尚未生成采购方案",
}
ERRORS = {
    "opendev_secret_unavailable": "工作台尚未绑定 OpenDev Secret。",
    "request_context_limit": "达到单次请求上下文限制。",
    "request_usage_limit": "达到本次运行用量限制。",
    "opendev_http_error": "OpenDev 返回 HTTP 错误。",
    "opendev_connection_error": "无法连接 OpenDev。",
    "opendev_invalid_response": "OpenDev 返回无法解析的响应。",
}
TOOL_NAMES = {
    "analyze_bom": "分析 BOM", "find_supplier_options": "查询供应商报价",
    "simulate_disruption": "模拟供应中断", "calculate_procurement_plan": "计算采购方案",
    "validate_plan": "独立验收", "generate_change_report": "生成变更报告",
    "request_clarification": "请求澄清",
}
ITEM_STATUS = {
    "search_limit": "超出求解范围，缺口未判定", "unsupported_quantity_increment": "需求不符合采购数量步长",
    "supply_gap": "库存或起订量限制", "no_compatible_quote": "缺少匹配报价",
    "tier_or_moq_unavailable": "阶梯或最低起订量不满足", "locked_allocation_unavailable": "锁定分配无法满足",
}


@dataclass
class Dataset:
    bom: NormalizedTable
    quotes: NormalizedTable
    source: str
    demo: bool = False
    raw_bom_rows: int = 0
    raw_quote_rows: int = 0


def load_dataset(bom_file, quote_file=None, *, demo=False):
    if demo:
        raw_bom, raw_quotes = load_workbook(DEMO_BOOK)
    else:
        if not bom_file:
            raise ValueError("请选择 BOM 文件或加载虚构演示数据。")
        raw_bom = read_table(bom_file)
        if quote_file:
            raw_quotes = read_table(quote_file, "Quotes")
        elif Path(bom_file).suffix.lower() == ".xlsx":
            try:
                raw_quotes = read_table(bom_file, "Quotes")
            except ValueError as exc:
                if str(exc) != "Missing sheet: Quotes":
                    raise
                raw_quotes = pd.DataFrame(columns=QUOTE_COLUMNS)
        else:
            raw_quotes = pd.DataFrame(columns=QUOTE_COLUMNS)
    if len(raw_bom) > 500 or len(raw_quotes) > 10000:
        raise ValueError("工作台支持最多 500 行物料与 10,000 行报价。")
    bom, quotes = normalize_bom(raw_bom), normalize_quotes(raw_quotes)
    fictional = any("fictional" in value.lower() or "虚构" in value
                    for table in (bom, quotes) for value in table.data["data_notice"])
    source = "虚构 AI BOX 演示数据" if demo else ("上传快照 · 含虚构数据标识" if fictional else "上传快照")
    return Dataset(bom, quotes, source, demo, len(raw_bom), len(raw_quotes))


def load_demo():
    return load_dataset(None, demo=True)


def typed_batch(value):
    if value is None or not 1 <= value <= 10000 or int(value) != value:
        raise ValueError("生产批量须为 1 至 10,000 之间的整数。")
    return int(value)


def cost_view(dataset, batch_size, as_of, currency):
    if dataset is None:
        raise ValueError("请先加载 BOM。")
    params = {"as_of": as_of, "currency": (currency or "").strip().upper()}
    return (calculate(dataset.bom, dataset.quotes, 1, **params),
            calculate(dataset.bom, dataset.quotes, typed_batch(batch_size), **params))


def run_demo(scenario):
    """Deterministic local workflow. Every logged result comes from a real tool."""
    dataset = load_demo()
    tools = DecisionTools(dataset.bom, dataset.quotes, demo_context(scenario))
    log = [DecisionLog("context", 0, {"goal": tools.context.goal, "source": "local_workflow"})]

    def invoke(name, **args):
        result = getattr(tools, name)(**args)
        log.append(DecisionLog("tool_call", round_number, {
            "name": name, "arguments": args, "result": result, "source": "local_workflow", "call_id": None,
        }))
        return result

    round_number = 0
    invoke("analyze_bom")
    if scenario == "A":
        invoke("simulate_disruption")
        invoke("find_supplier_options", part_numbers=["AI-001", "AI-003"])
    if scenario == "B":
        candidate = invoke("calculate_procurement_plan", strategy="single")
        first = invoke("validate_plan", plan_id=candidate["plan_id"])
        if not first["accepted"]:
            round_number += 1
            invoke("find_supplier_options", part_numbers=[g["part_number"] for g in first["gaps"]])
    if scenario != "B" or not first["accepted"]:
        candidate = invoke("calculate_procurement_plan", strategy="split")
    validation = invoke("validate_plan", plan_id=candidate["plan_id"]) if scenario != "B" or not first["accepted"] else first
    report = invoke("generate_change_report", plan_id=candidate["plan_id"])
    status = "pending_review" if validation["accepted"] else "constraints_not_met"
    log.append(DecisionLog("finished", round_number, {"status": status}))
    return DecisionRun(status, log, validation, report, round_number)


def run_task(dataset, goal, batch_size, as_of, currency, budget, reduction, locks, share):
    if dataset is None:
        raise ValueError("请先加载 BOM。")
    if not share:
        raise ValueError("请确认允许向 OpenDev 发送当前任务及必要的数据摘要。")
    goal = (goal or "").strip()
    if not 1 <= len(goal) <= 800:
        raise ValueError("请输入 1 至 800 字的采购目标。")
    locked = tuple(p.strip() for p in (locks or "").replace("，", ",").split(",") if p.strip())
    if len(locked) > 20 or any(len(p) > 120 for p in locked):
        raise ValueError("最多填写 20 个锁定料号。")
    ctx = DecisionContext(goal, typed_batch(batch_size), as_of, (currency or "").strip().upper(),
                          (budget or "").strip() or None, (reduction or "").strip() or None, locked)
    return run_live(DecisionTools(dataset.bom, dataset.quotes, ctx))


def display_money(value, currency="CNY"):
    return "—" if value is None else f"{currency} {Decimal(value):,.2f}"


def cost_comparison(report):
    if not report:
        return []
    base = report["scenario_incumbent_total"] if report["events"] else report["before_total"]
    after = report["after_total"]
    saved = str(Decimal(base) - Decimal(after)) if base is not None and after is not None else None
    partial = after is None
    items = [
        ("原采购完整成本", report["before_total"]),
        ("建议采购完整成本", after),
        ("节省金额（相对" + ("扰动后维持原分配" if report["events"] else "原采购") + "）", saved),
    ]
    if report["events"]:
        items.insert(1, ("扰动后维持原分配的完整成本", base))
    if partial:
        items.append(("建议方案已分配小计（部分）", report["after_subtotal"]))
    return items
