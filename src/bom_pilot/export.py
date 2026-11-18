"""Create a standalone Excel decision report from recorded results."""
from pathlib import Path
import tempfile

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .workbench import CONSTRAINTS, ITEM_STATUS, cost_comparison


def allocation_text(orders):
    return " / ".join(f'{a["supplier"]} × {a["quantity"]}' for a in orders) or "无分配"


def export_result(run, source, directory: str | Path | None = None):
    if not run.report or not run.validation:
        raise ValueError("请先生成可供导出的采购方案。")
    report = run.report
    workbook = Workbook()
    workbook.remove(workbook.active)

    def sheet(name, headers, rows):
        ws = workbook.create_sheet(name)
        ws.append(headers)
        for row in rows:
            ws.append(["" if v is None else v for v in row])
            for cell in ws[ws.max_row]:
                if isinstance(cell.value, str):
                    # Imported fields must remain literal Excel text.
                    cell.data_type = "s"
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = ws.dimensions
        for col in ws.iter_cols():
            width = max((len(str(cell.value or "")) for cell in col), default=10)
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(52, max(14, width * 2 + 2))
        for cell in ws[1]:
            cell.fill = PatternFill("solid", fgColor="14394C")
            cell.font = Font(bold=True, color="FFFFFF")
            cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[1].height = 24

    orders = [a for item in report["proposal"]["items"] for a in item["allocations"]]
    sheet("采购建议", ["料号", "供应商", "报价编号", "报价日期", "数量", "单位", "单价", "金额", "币种", "MOQ", "库存"],
          [[a[k] for k in ("part_number", "supplier", "quote_id", "quote_date", "quantity", "unit", "unit_price",
                           "cost", "currency", "moq", "stock_qty")] for a in orders])
    sheet("成本对比", ["指标", "金额", "币种", "数据来源"], [
        [label, value, report["currency"], source] for label, value in cost_comparison(report)
    ] + [
        ["相对原采购变化率 (%)", report["cost_change_pct"], "", source],
        ["批量（台）", report["proposal"]["batch_size"], "", source],
        ["有效预算", run.validation["budget"], report["currency"], source],
        ["预算超额", run.validation["budget_overage"], report["currency"], source],
    ])
    sheet("未满足约束", ["约束", "判定"], [
        [CONSTRAINTS.get(key, key), "未满足"] for key, value in report["constraints"].items() if value is False
    ])
    gap_status = {i["part_number"]: i["status"] for i in report["exceptions"]}
    sheet("库存缺口", ["料号", "需求", "已分配", "缺口", "说明"], [
        [g["part_number"], g["required_qty"], g["allocated_qty"],
         None if gap_status.get(g["part_number"]) in {"search_limit", "unsupported_quantity_increment"} else g["gap_qty"],
         ITEM_STATUS.get(gap_status.get(g["part_number"]), "未满足需求")] for g in report["gaps"]
    ])
    pending_status = "待审批" if report["approval_status"] == "pending_review" else "受阻"
    sheet("待审批项", ["料号", "原采购分配", "建议采购分配", "审批状态"], [
        [item["part_number"], allocation_text(item["before"]), allocation_text(item["proposed"]), pending_status]
        for item in report["changes"]
    ])
    sheet("建议BOM", ["料号", "物料名称", "分类", "单机用量", "单位", "数据标识"], [
        [row[k] for k in ("part_number", "description", "category", "quantity_per_unit", "unit", "data_notice")]
        for row in report["proposed_bom"]
    ])
    path = Path(tempfile.mkdtemp(prefix="bom-pilot-", dir=directory)) / "BOM-Pilot-采购建议.xlsx"
    workbook.save(path)
    return str(path)
