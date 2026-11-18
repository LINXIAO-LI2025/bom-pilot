"""Chinese Gradio Blocks interface for BOM Pilot."""
from decimal import Decimal
from html import escape
import json
from pathlib import Path
from zipfile import BadZipFile

import gradio as gr
import pandas as pd
import plotly.graph_objects as go
from openpyxl.utils.exceptions import InvalidFileException

from .export import allocation_text, export_result
from .workbench import (
    BOM_HEADERS, CONSTRAINTS, ERRORS, ISSUE_HEADERS, ITEM_STATUS, SCENARIOS, STATUS, TOOL_NAMES,
    cost_comparison, cost_view, display_money, load_dataset, load_demo, run_demo, run_task,
)
from .workbench_agent import MAX_OUTPUT_TOKENS, MAX_REPORTED_TOKENS, MAX_REQUESTS

CSS = """
.gradio-container {max-width:1400px!important; background:#f2f6f8!important;}
#hero {background:#102d3c; border-radius:18px; padding:30px 34px; color:#d7e8ee;
       display:flex; justify-content:space-between; align-items:center; gap:20px; margin-bottom:8px;}
#hero h1 {color:#fff; font-size:34px; margin:6px 0 9px; line-height:1.15; letter-spacing:-.02em;}
#hero p {margin:0; color:#c8dee5; font-size:14px;}
#hero .wordmark {color:#67dbc7; font-size:13px; font-weight:700; letter-spacing:.1em;}
#workspace-tabs .tab-nav {gap:8px; padding:2px 0 6px; flex-wrap:wrap;}
#workspace-tabs .tab-nav button {font-weight:650; padding:11px 15px;}
.section-title h2 {font-size:20px!important; letter-spacing:-.02em;}
.metrics {display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:12px;}
.metric {background:#fff; border:1px solid #d7e3e9; border-radius:12px; padding:15px 16px;
         min-height:92px; color:#102d3c; box-shadow:0 2px 4px rgba(12,44,63,.035);}
.metric .label {font-size:13px; color:#425f70; display:block;}
.metric strong {font-size:23px; display:block; margin-top:6px; font-variant-numeric:tabular-nums;
                overflow-wrap:anywhere;}
.metric small {color:#506978; display:block; margin-top:5px;}
@media(max-width:550px) {#hero {padding:22px;}
                      #hero h1 {font-size:27px;} .metrics {grid-template-columns:1fr 1fr;}}
"""

TRACE_COLUMNS = ["序号", "轮次", "工具", "输入摘要", "结果", "触发来源"]
ISSUE_COLUMNS = list(ISSUE_HEADERS.values())
GAP_COLUMNS = ["料号", "需求", "已分配", "缺口", "原因"]
APPROVAL_COLUMNS = ["料号", "原采购分配", "建议分配", "状态"]
CHECK_COLUMNS = ["约束", "验收结果"]


def grid(rows, columns):
    return pd.DataFrame(rows, columns=columns)


def metric_cards(cards):
    return '<div class="metrics">' + "".join(
        f'<div class="metric"><span class="label">{escape(label)}</span>'
        f'<strong>{escape(str(value))}</strong><small>{escape(hint)}</small></div>'
        for label, value, hint in cards
    ) + "</div>"


def load_action(bom_file, quote_file, batch, as_of, currency, *, demo=False):
    try:
        dataset = load_demo() if demo else load_dataset(bom_file, quote_file)
        return loaded_state(dataset, batch, as_of, currency)
    except (ValueError, OSError, BadZipFile, InvalidFileException) as exc:
        raise gr.Error(str(exc)) from None


def loaded_state(dataset, batch, as_of, currency):
    normalized = dataset.bom.data[list(BOM_HEADERS)].rename(columns=BOM_HEADERS).astype(str)
    issues = [[getattr(issue, key) for key in ISSUE_HEADERS] for issue in dataset.bom.issues + dataset.quotes.issues]
    quoted = set(dataset.quotes.data["part_number"])
    issues.extend(["BOM", row["source_row"], "part_number", "无有效报价", row["part_number"]]
                  for row in dataset.bom.data.to_dict("records") if row["part_number"] not in quoted)
    title = f"**{dataset.source}** · {dataset.raw_bom_rows} 项物料 · {dataset.raw_quote_rows} 条报价"
    cards, category, drivers, exceptions = cost_action(dataset, batch, as_of, currency)
    return dataset, title, normalized, grid(issues, ISSUE_COLUMNS), cards, category, drivers, exceptions


def chart(labels, values, title, axis_title):
    figure = go.Figure(go.Bar(x=values, y=labels, orientation="h", marker_color="#117e79",
                             hovertemplate="%{y}<br>%{x:,.2f}<extra></extra>"))
    figure.update_layout(template="plotly_white", title=title, height=320, margin=dict(l=14, r=24, t=56, b=52),
                         font=dict(color="#18384b", size=13), paper_bgcolor="#ffffff",
                         xaxis_title=axis_title, yaxis=dict(autorange="reversed", automargin=True))
    return figure


def cost_action(dataset, batch, as_of, currency):
    try:
        unit, bulk = cost_view(dataset, batch, as_of, currency)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    cur = bulk["currency"]
    cards = metric_cards([
        ("单机完整成本", display_money(unit["total_cost"], cur), "单台采购" if unit["complete"] else "输入或报价不完整"),
        ("批量完整成本", display_money(bulk["total_cost"], cur), f'{bulk["batch_size"]:,} 台' if bulk["complete"] else "批量未足量定价"),
        ("批量折合单机" if bulk["complete"] else "批量已定价小计（部分）",
         display_money(bulk["equivalent_unit_cost"] if bulk["complete"] else bulk["priced_subtotal"], cur),
         f'{bulk["priced_lines"]} 项已定价 · {bulk["unpriced_lines"]} 项未定价'),
    ])
    groups = sorted(bulk["composition"], key=lambda r: -Decimal(r["priced_subtotal"]))
    largest = sorted((l for l in bulk["lines"] if l["line_cost"] is not None),
                     key=lambda l: -Decimal(l["line_cost"]))[:8]
    composition = chart([g["category"] for g in groups], [float(g["priced_subtotal"]) for g in groups],
                        "已定价成本构成", cur)
    leaders = chart([f'{l["part_number"]} · {l["description"][:20]}' for l in largest],
                    [float(l["line_cost"]) for l in largest], "主要成本物料", cur)
    invalid = {"shortage": "供应商库存不足", "no_eligible_quote": "MOQ、阶梯、单位或币种不匹配",
               "missing_quote": "指定日期无有效报价"}
    exceptions = grid([[r["part_number"], r["required_qty"], invalid[r["status"]]]
                       for r in bulk["lines"] if r["status"] in invalid], ["料号", "需求量", "批量未定价原因"])
    return cards, composition, leaders, exceptions


def brief(log):
    d = log.data
    r = d["result"]
    name = d["name"]
    if r.get("error"):
        return f'动作未执行 · {r["error"]}'
    if name == "analyze_bom":
        return f'{r["part_count"]} 项物料 · {len(r["data_quality"])} 条数据质量问题'
    if name == "find_supplier_options":
        return f'{len(r["options"])} 条录入报价 · {len(r["parts_without_quotes"])} 项无报价'
    if name == "simulate_disruption":
        return f'{len(r["events"])} 条报价阶梯被模拟调整'
    if name == "calculate_procurement_plan":
        suffix = "完整成本" if r["complete"] else "已分配小计（部分）"
        return f'{r["plan_id"]} · {suffix} {display_money(r["subtotal"], r["currency"])}'
    if name == "validate_plan":
        failed = "、".join(CONSTRAINTS.get(key, key) for key, val in r["constraints"].items() if val is False)
        return "通过独立验收" if r["accepted"] else f"未通过 · {failed or '需进一步核对'}"
    if name == "generate_change_report":
        return f'{len(r["changes"])} 项分配变更 · {len(r["gaps"])} 项缺口'
    return "需要补充结构化约束"


def constraint_table(run):
    if run.validation is None:
        return grid([], CHECK_COLUMNS)
    statuses = {True: "满足", False: "未满足", None: "未判定或未设置"}
    return grid([[CONSTRAINTS.get(key, key), statuses[val]] for key, val in run.validation["constraints"].items()],
                CHECK_COLUMNS)


def render_run(run, source, execution):
    trace = []
    entries = []
    usage = [0, 0, 0]
    stopped = []
    origins = {"model": "模型", "controller": "控制器", "local_workflow": "本地演示流程"}
    models = set()
    for log in run.log:
        d = log.data
        if log.kind == "model_turn":
            usage[0] += 1
            usage[1] += d["usage"].get("prompt_tokens") or 0
            usage[2] += d["usage"].get("completion_tokens") or 0
            models.add(d["model"])
        elif log.kind == "tool_call":
            trace.append([len(trace) + 1, "初始" if log.round == 0 else f"重规划 {log.round}",
                          TOOL_NAMES.get(d["name"], d["name"]),
                          json.dumps(d["arguments"], ensure_ascii=False), brief(log), origins.get(d["source"], d["source"])])
            entries.append(log)
        elif log.kind == "provider_error":
            reason = ERRORS.get(d["code"], "无法完成模型调用。")
            stopped.append(reason + (f' HTTP {d["http_status"]}' if d["http_status"] else ""))
    status = f'**{STATUS.get(run.status, run.status)}** · {source} · {execution} · 重规划 {run.replans} 次'
    if usage[0]:
        status += f'  \n{", ".join(sorted(models))} · {usage[0]} 个模型响应 · 输入 {usage[1]:,} / 输出 {usage[2]:,} Token'
    if stopped:
        status += "  \n" + " ".join(stopped)
    report = run.report
    cards, gaps, approvals = "", [], []
    if report:
        proposal = report["proposal"]
        status += f'  \n批量 {proposal["batch_size"]:,} 台 · 报价时点 {proposal["as_of"]}'
        cur = report["currency"]
        cards = metric_cards([(label, display_money(value, cur), "该指标暂无完整值" if value is None else "")
                              for label, value in cost_comparison(report)])
        reasons = {i["part_number"]: i["status"] for i in report["exceptions"]}
        for g in report["gaps"]:
            reason = reasons.get(g["part_number"])
            gap = "未判定" if reason in {"search_limit", "unsupported_quantity_increment"} else g["gap_qty"]
            gaps.append([g["part_number"], g["required_qty"], g["allocated_qty"], gap, ITEM_STATUS.get(reason, "未满足需求")])
        approval = "待审批" if report["approval_status"] == "pending_review" else "受阻"
        approvals = [[c["part_number"], allocation_text(c["before"]), allocation_text(c["proposed"]), approval]
                     for c in report["changes"]]
        if report["budget_overage"] is not None and Decimal(report["budget_overage"]) > 0:
            status += f'  \n预算超出 **{display_money(report["budget_overage"], cur)}**。'
        if report["cost_change_pct"] is not None:
            pct = Decimal(report["cost_change_pct"])
            status += f'  \n相对原采购成本变化 **{pct:+.2f}%**。'
        if gaps:
            status += f'  \n**{len(gaps)} 项物料未满足需求**，完整成本与节省金额不可用。'
    return ((run, source, entries), status, grid(trace, TRACE_COLUMNS),
            gr.update(choices=[(f'{i+1} · {TOOL_NAMES.get(entry.data["name"], entry.data["name"])}', i)
                               for i, entry in enumerate(entries)], value=None),
            None, status, cards, constraint_table(run), grid(gaps, GAP_COLUMNS),
            grid(approvals, APPROVAL_COLUMNS), gr.update(interactive=bool(report)), None)


def inspect_tool(state, index):
    if state is None or index is None:
        return None
    return state[2][int(index)].data


def live_action(dataset, goal, batch, as_of, currency, budget, reduction, locks, share):
    try:
        run = run_task(dataset, goal, batch, as_of, currency, budget, reduction, locks, share)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None
    return render_run(run, dataset.source, "OpenDev 决策")


def download_action(state, cache_directory):
    if state is None:
        raise gr.Error("请先计算方案。")
    try:
        cache = Path(cache_directory)
        cache.mkdir(parents=True, exist_ok=True)
        return export_result(state[0], state[1], cache)
    except ValueError as exc:
        raise gr.Error(str(exc)) from None


def build_app():
    with gr.Blocks(title="BOM Pilot | 采购决策工作台", delete_cache=(600, 3600)) as app:
        data = gr.State(time_to_live=3600)
        decision = gr.State(time_to_live=3600)
        gr.HTML('<header id="hero"><div><span class="wordmark">BOM PILOT</span><h1>采购决策工作台</h1>'
                '<p>AI 硬件物料、成本与供应约束分析</p></div></header>')
        source = gr.Markdown("选择文件或加载虚构 AI BOX 演示数据。")
        with gr.Row():
            batch = gr.Number(label="生产批量（台）", value=10, minimum=1, maximum=10000, precision=0)
            as_of = gr.Textbox(label="报价时点（YYYY-MM-DD）", value="2026-11-18")
            currency = gr.Textbox(label="币种", value="CNY", max_lines=1)
        with gr.Tabs(elem_id="workspace-tabs", selected="cost") as tabs:
            with gr.Tab("BOM 管理", id="bom"):
                with gr.Row():
                    bom_file = gr.File(label="上传 BOM · Excel 或 CSV", elem_id="bom-upload", file_types=[".xlsx", ".csv"], height=108)
                    quotes_file = gr.File(label="单独报价表 · 可选", elem_id="quote-upload", file_types=[".xlsx", ".csv"], height=108)
                with gr.Row():
                    load_files = gr.Button("读取并校验", variant="primary")
                    load_sample = gr.Button("加载虚构 AI BOX 演示数据")
                gr.Markdown("Excel 可合并 BOM 和 Quotes 两张表。CSV 物料与报价分别上传。")
                gr.Markdown("## 物料清单", elem_classes="section-title")
                bom_grid = gr.Dataframe(headers=list(BOM_HEADERS.values()), interactive=False, max_height=340)
                gr.Markdown("## 数据质量", elem_classes="section-title")
                issue_grid = gr.Dataframe(headers=ISSUE_COLUMNS, interactive=False, max_height=265)
            with gr.Tab("成本分析", id="cost"):
                recalculate = gr.Button("按当前批量和时点计算", variant="primary")
                cost_cards = gr.HTML()
                with gr.Row():
                    category = gr.Plot(show_label=False)
                    drivers = gr.Plot(show_label=False)
                cost_exceptions = gr.Dataframe(headers=["料号", "需求量", "批量未定价原因"],
                                               label="未定价物料", interactive=False, max_height=280)
            with gr.Tab("Agent 决策室", id="agent"):
                gr.Markdown("## 快捷演示", elem_classes="section-title")
                gr.Markdown("使用虚构 AI BOX 案例，本地运行实际工具，独立于当前上传的数据。")
                with gr.Row():
                    demo_buttons = {key: gr.Button(label) for key, label in SCENARIOS.items()}
                gr.Markdown("## 自定义决策", elem_classes="section-title")
                goal = gr.Textbox(label="采购目标", placeholder="例如：采购 10 台所需物料，优先压低成本。", lines=3)
                with gr.Accordion("结构化约束", open=False):
                    with gr.Row():
                        budget = gr.Textbox(label="总预算（可选）", placeholder="例如 31000")
                        reduction = gr.Textbox(label="降本目标 %（可选）", placeholder="例如 8")
                        locks = gr.Textbox(label="锁定料号（以逗号分隔）", placeholder="例如 AI-004")
                share = gr.Checkbox(label="允许向 OpenDev 发送本次任务和必要的数据摘要")
                with gr.Row():
                    run_model = gr.Button("运行 OpenDev 决策", variant="primary")
                    view_report = gr.Button("查看方案对比")
                gr.Markdown(f"每次最多 {MAX_REQUESTS} 个请求，请求输出上限 {MAX_OUTPUT_TOKENS} Token，"
                            f"累计报告用量达到 {MAX_REPORTED_TOKENS:,} Token 后停止追加请求。")
                run_status = gr.Markdown("执行后显示真实工具和验收记录。", elem_id="run-status")
                trace_grid = gr.Dataframe(headers=TRACE_COLUMNS, label="工具执行顺序", interactive=False, max_height=390)
                with gr.Accordion("查看工具输入与计算证据", open=False):
                    selected = gr.Dropdown(label="选择工具记录", choices=[])
                    detail = gr.JSON(label="工具记录")
            with gr.Tab("方案对比", id="compare"):
                compare_status = gr.Markdown("先运行本地演示或 OpenDev 决策。")
                decision_cards = gr.HTML()
                with gr.Row():
                    validation = gr.Dataframe(headers=CHECK_COLUMNS, label="独立验收约束", interactive=False)
                    gaps = gr.Dataframe(headers=GAP_COLUMNS, label="库存缺口与未满足需求", interactive=False)
                approvals = gr.Dataframe(headers=APPROVAL_COLUMNS, label="待审批或受阻变更", interactive=False)
                export_button = gr.Button("生成 Excel", variant="primary", interactive=False)
                exported = gr.File(label="下载采购建议与验收报告", interactive=False)

        base_outputs = [data, source, bom_grid, issue_grid, cost_cards, category, drivers, cost_exceptions]
        decision_outputs = [decision, run_status, trace_grid, selected, detail, compare_status, decision_cards,
                            validation, gaps, approvals, export_button, exported]

        def clear_decision():
            return (None, "执行后显示真实工具和验收记录。", grid([], TRACE_COLUMNS),
                    gr.update(choices=[], value=None), None, "先运行本地演示或 OpenDev 决策。", "",
                    grid([], CHECK_COLUMNS), grid([], GAP_COLUMNS), grid([], APPROVAL_COLUMNS),
                    gr.update(interactive=False), None)

        def load_files_action(*args):
            return (*load_action(*args), *clear_decision())

        def load_sample_action(batch, as_of, currency):
            return (*load_action(None, None, batch, as_of, currency, demo=True), *clear_decision())

        job_options = {"concurrency_id": "workbench", "concurrency_limit": 1}
        load_files.click(load_files_action, [bom_file, quotes_file, batch, as_of, currency],
                         base_outputs + decision_outputs, api_name="load_bom", **job_options)
        load_sample.click(load_sample_action, [batch, as_of, currency], base_outputs + decision_outputs,
                          api_name="load_demo", **job_options)
        app.load(load_sample_action, [batch, as_of, currency], base_outputs + decision_outputs,
                 api_visibility="private", **job_options)
        recalculate.click(cost_action, [data, batch, as_of, currency],
                          [cost_cards, category, drivers, cost_exceptions], api_name="analyze_cost", **job_options)

        def demo_callback(key):
            def callback():
                return render_run(run_demo(key), "虚构 AI BOX 演示数据", f"本地工具演示 · {SCENARIOS[key]}")
            return callback

        for key, button in demo_buttons.items():
            button.click(demo_callback(key), outputs=decision_outputs, api_name=f"scenario_{key.lower()}", **job_options)
        run_model.click(live_action, [data, goal, batch, as_of, currency, budget, reduction, locks, share],
                        decision_outputs, api_name="run_decision", **job_options)
        selected.change(inspect_tool, [decision, selected], detail, api_visibility="private", queue=False)
        view_report.click(lambda: gr.update(selected="compare"), outputs=tabs, api_visibility="private", queue=False)
        def export_session(state):
            return download_action(state, exported.GRADIO_CACHE)

        export_button.click(export_session, decision, exported, api_name="export_excel", **job_options)
    return app.queue(max_size=16)
