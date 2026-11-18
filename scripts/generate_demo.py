"""Entirely FICTIONAL / 虚构数据. Run from project root. Never overwrite examples."""
from pathlib import Path
import pandas as pd

ROOT = Path("examples")
parts = [
    ("AI-001", "边缘 AI SoC 模组（虚构）", "算力", 1, 1800),
    ("AI-002", "16GB 内存", "存储", 2, 160),
    ("AI-003", "512GB NVMe SSD", "存储", 1, 240),
    ("AI-004", "载板 PCB", "主板", 1, 180),
    ("AI-005", "电源管理 IC", "电源", 2, 12),
    ("AI-006", "DC 电源适配器", "电源", 1, 85),
    ("AI-007", "散热器", "散热", 1, 48),
    ("AI-008", "PWM 风扇", "散热", 2, 18),
    ("AI-009", "导热垫", "散热", 1, 6),
    ("AI-010", "铝合金机壳", "结构", 1, 120),
    ("AI-011", "螺丝", "结构", 12, 0.15),
    ("AI-012", "Wi-Fi 模组", "连接", 1, 42),
    ("AI-013", "天线", "连接", 2, 5),
    ("AI-014", "以太网 PHY", "连接", 2, 15),
    ("AI-015", "RJ45 连接器", "连接", 2, 8),
    ("AI-016", "USB-C 连接器", "连接", 2, 3),
    ("AI-017", "HDMI 连接器", "连接", 1, 4),
    ("AI-018", "状态 LED", "辅料", 3, 0.2),
    ("AI-019", "包装盒", "包装", 1, 10),
    ("AI-020", "缓冲棉", "包装", 1, 3),
]

def generate():
    files = [ROOT / f for f in ["ai_box_bom.csv", "supplier_quotes.csv", "ai_box_demo.xlsx", "supplier_quotes_invalid.csv"]]
    if any(f.exists() for f in files):
        raise FileExistsError("Demo outputs exist; refusing to overwrite")
    ROOT.mkdir(exist_ok=True)
    bom = pd.DataFrame([dict(part_number=p, description=d, category=c, quantity_per_unit=q, unit="EA", data_notice="FICTIONAL / 虚构数据，非实际产品或报价") for p,d,c,q,_ in parts])
    quotes = []
    for index, (part, _, _, _, price) in enumerate(parts, 1):
        for day, factor in [("2026-10-01", 1.05), ("2026-11-01", 1.0)]:
            for supplier, multiplier in [("虚构供应商-A", 1.0), ("虚构供应商-B", 1.03)]:
                # Fan shortage at batch=100: demand=200; no vendor has enough stock.
                stock = 80 if part == "AI-008" else 100000
                for tier_min, tier_max, discount in [(1, 99, 1.0), (100, None, 0.9)]:
                    quotes.append(dict(quote_id=f"Q{len(quotes)+1:04}", part_number=part, supplier=supplier,
                                       quote_date=day, currency="CNY", unit="EA", unit_price=f"{price*factor*multiplier*discount:.6f}",
                                       min_qty=tier_min, max_qty="" if tier_max is None else tier_max, moq=1, stock_qty=stock,
                                       data_notice="FICTIONAL / 虚构数据，非真实商业报价"))
    valid_quotes = pd.DataFrame(quotes)
    # Deliberately missing-price quote; other suppliers still have valid offers.
    quotes.append(dict(quote_id="MISSING-PRICE", part_number="AI-019", supplier="虚构供应商-C", quote_date="2026-11-01", currency="CNY", unit="EA", unit_price="", min_qty=1, max_qty="", moq=1, stock_qty=500, data_notice="FICTIONAL / 故意设置的缺价案例"))
    quotes = pd.DataFrame(quotes)
    bom.to_csv(files[0], index=False, encoding="utf-8-sig", mode="x")
    quotes.to_csv(files[3], index=False, encoding="utf-8-sig", mode="x")
    valid_quotes.to_csv(files[1], index=False, encoding="utf-8-sig", mode="x")
    with files[2].open("xb") as stream, pd.ExcelWriter(stream, engine="openpyxl") as writer:
        bom.to_excel(writer, sheet_name="BOM", index=False)
        valid_quotes.to_excel(writer, sheet_name="Quotes", index=False)
        pd.DataFrame({"说明": ["全部数据均为虚构，仅供软件演示，不可用于采购。", "100 台需求中 AI-008 缺料；另附 invalid CSV 演示缺价校验。"]}).to_excel(writer, sheet_name="NOTICE", index=False)
    print(f"Created {len(bom)} fictional BOM items, {len(quotes)} quote tiers/history rows")

if __name__ == "__main__":
    generate()
