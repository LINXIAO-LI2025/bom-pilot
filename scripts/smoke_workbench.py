"""Exercise the running workbench in Chromium. Add --live for an OpenDev run."""
import argparse
from pathlib import Path

from openpyxl import load_workbook
from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:7860")
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--artifacts", type=Path, default=Path("outputs/workbench-smoke"))
    args = parser.parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1050}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.url)
        expect(page.get_by_text("20 项物料 · 160 条报价")).to_be_visible(timeout=20_000)
        for name in ("BOM 管理", "成本分析", "Agent 决策室", "方案对比"):
            expect(page.get_by_role("tab", name=name)).to_be_visible()
        page.get_by_role("tab", name="成本分析").click()
        expect(page.get_by_text("CNY 2,982.40", exact=True)).to_be_visible()
        expect(page.get_by_text("已定价成本构成", exact=True)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("主要成本物料", exact=True)).to_be_visible()
        page.screenshot(path=args.artifacts / "成本分析.png", full_page=True)

        page.get_by_role("tab", name="BOM 管理").click()
        page.locator("#bom-upload input[type=file]").set_input_files("examples/ai_box_bom.csv")
        expect(page.locator("#bom-upload").get_by_text("ai_box_bom", exact=False).first).to_be_visible()
        page.locator("#quote-upload input[type=file]").set_input_files("examples/supplier_quotes_invalid.csv")
        expect(page.locator("#quote-upload").get_by_text("supplier_quotes_invalid", exact=False).first).to_be_visible()
        page.get_by_role("button", name="读取并校验").click()
        expect(page.get_by_text("上传快照")).to_be_visible(timeout=20_000)
        expect(page.get_by_role("gridcell", name="missing_price", exact=True)).to_be_visible()
        page.get_by_role("button", name="加载虚构 AI BOX 演示数据").click()
        expect(page.get_by_text("20 项物料 · 160 条报价")).to_be_visible(timeout=20_000)

        page.reload()
        expect(page.get_by_text("20 项物料 · 160 条报价")).to_be_visible(timeout=20_000)
        page.get_by_role("tab", name="BOM 管理").click()
        page.locator("#bom-upload input[type=file]").set_input_files("examples/ai_box_demo.xlsx")
        expect(page.locator("#bom-upload").get_by_text("ai_box_demo", exact=False).first).to_be_visible()
        page.get_by_role("button", name="读取并校验").click()
        expect(page.get_by_text("上传快照 · 含虚构数据标识", exact=False)).to_be_visible(timeout=20_000)
        expect(page.get_by_text("20 项物料 · 160 条报价")).to_be_visible()
        page.get_by_role("button", name="加载虚构 AI BOX 演示数据").click()
        expect(page.get_by_text("虚构 AI BOX 演示数据", exact=True)).to_be_visible(timeout=20_000)

        agent = page.get_by_role("tab", name="Agent 决策室")
        agent.click()
        page.get_by_role("button", name="涨价 20%").click()
        expect(page.get_by_text("独立验收通过 · 待审批", exact=False).first).to_be_visible(timeout=20_000)
        page.get_by_role("button", name="查看方案对比").click()
        expect(page.get_by_text("CNY 3,468.00", exact=True)).to_be_visible()

        agent.click()
        page.get_by_role("button", name="100 台缺料").click()
        expect(page.get_by_text("重规划 1 次", exact=False).first).to_be_visible(timeout=20_000)
        expect(page.get_by_role("gridcell", name="本地演示流程", exact=True).first).to_be_visible()
        page.get_by_role("button", name="查看工具输入与计算证据").click()
        page.get_by_role("combobox", name="选择工具记录").press("ArrowDown")
        page.get_by_role("option", name="3 · 独立验收", exact=True).click()
        expect(page.get_by_text("recomputed_subtotal", exact=False).last).to_be_visible(timeout=10_000)
        page.get_by_role("button", name="查看方案对比").click()
        expect(page.get_by_text("建议方案已分配小计（部分）", exact=True)).to_be_visible()
        expect(page.get_by_text("CNY 268,099.20", exact=True)).to_be_visible()
        expect(page.get_by_role("gridcell", name="40.00", exact=True)).to_be_visible()
        page.screenshot(path=args.artifacts / "缺料方案对比.png", full_page=True)
        page.get_by_role("button", name="生成 Excel").click()
        download_link = page.locator('a[href*="BOM-Pilot-"]').last
        expect(download_link).to_be_visible(timeout=20_000)
        with page.expect_download() as event:
            download_link.click()
        filename = args.artifacts / "BOM-Pilot-采购建议.xlsx"
        event.value.save_as(filename)
        with filename.open("rb") as stream:
            workbook = load_workbook(stream, read_only=True)
            assert {"采购建议", "成本对比", "未满足约束", "库存缺口", "待审批项"} <= set(workbook.sheetnames)
            assert workbook["库存缺口"]["D2"].value == "40.00"
            workbook.close()

        agent.click()
        page.get_by_role("button", name="降本 8%").click()
        expect(page.get_by_text("预算超出", exact=False).first).to_be_visible(timeout=20_000)
        if args.live:
            page.get_by_role("textbox", name="采购目标").fill(
                "用拆单计算当前 10 台的最低成本。先计算采购方案，再独立验收，最后生成变更报告。"
            )
            page.get_by_role("checkbox", name="允许向 OpenDev 发送本次任务和必要的数据摘要").check()
            page.get_by_role("button", name="运行 OpenDev 决策").click()
            status = page.locator("#run-status")
            expect(status).to_contain_text("OpenDev 决策", timeout=250_000)
            print(status.inner_text(), flush=True)
            expect(status).to_contain_text("个模型响应")
            expect(page.get_by_text("独立验收通过 · 待审批", exact=False).first).to_be_visible()
            expect(page.get_by_role("gridcell", name="模型", exact=True).first).to_be_visible()
            page.screenshot(path=args.artifacts / "OpenDev决策.png", full_page=True)
        assert not errors, errors
        browser.close()
    print("Chromium smoke passed")


if __name__ == "__main__":
    main()
