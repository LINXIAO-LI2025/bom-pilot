from decimal import Decimal
import json
from pathlib import Path
import pandas as pd
import pytest
from openpyxl import Workbook
from bom_pilot import calculate, compare_prices, normalize_bom, normalize_quotes, read_table, load_workbook
from bom_pilot.models import money

ROOT = Path(__file__).resolve().parents[1]


def bframe(**kwargs):
    return pd.DataFrame([dict(part_number="001", description="模块", category="算力", quantity_per_unit="2", unit="EA", **kwargs)])


def qrow(**kwargs):
    return dict(dict(quote_id="Q1", part_number="001", supplier="A", quote_date="2026-10-01", currency="CNY", unit="EA", unit_price="1.005", min_qty="0", max_qty="", moq="1", stock_qty="1000"), **kwargs)


def run(b=None, q=None, **kwargs):
    return calculate(normalize_bom(b if b is not None else bframe()), normalize_quotes(pd.DataFrame(q if q is not None else [qrow()])), **kwargs)


def test_exact_cost_and_composition_reconciliation():
    r = run(batch_size=3)
    assert r["complete"]
    assert r["total_cost"] == "6.03"
    assert r["equivalent_unit_cost"] == "2.01"
    line = r["lines"][0]
    assert money(Decimal(line["required_qty"]) * Decimal(line["unit_price"])) == Decimal(line["line_cost"])
    assert sum(Decimal(x["priced_subtotal"]) for x in r["composition"]) == Decimal(r["total_cost"])
    json.dumps(r, allow_nan=False)


def test_tiers_inclusive_and_latest_snapshot():
    q = [qrow(quote_id="OLD", unit_price="0.01"), qrow(quote_id="SMALL", quote_date="2026-11-01", min_qty="0", max_qty="9", unit_price="3"), qrow(quote_id="BIG", quote_date="2026-11-01", min_qty="10", unit_price="2")]
    assert run(q=q, batch_size=4)["lines"][0]["quote_id"] == "SMALL"
    assert run(q=q, batch_size=5)["total_cost"] == "20.00"
    assert run(q=q, batch_size=5, as_of="2026-10-01")["total_cost"] == "0.10"


def test_stock_fallback_and_shortage_no_partial_total():
    q = [qrow(stock_qty="1", unit_price="0.1"), qrow(quote_id="Q2", supplier="B", unit_price="2", stock_qty="2")]
    assert run(q=q)["lines"][0]["supplier"] == "B"
    r = run(q=q, batch_size=2)
    assert not r["complete"] and r["total_cost"] is None
    assert r["lines"][0]["status"] == "shortage"
    assert r["lines"][0]["shortage_qty"] == "2"


@pytest.mark.parametrize("changes,expected", [({"moq": "3"}, "below_moq"), ({"min_qty": "3"}, "outside_tier"), ({"max_qty": "1"}, "outside_tier"), ({"currency": "USD"}, "currency_mismatch"), ({"unit": "M"}, "unit_mismatch")])
def test_ineligible_quotes(changes, expected):
    r = run(q=[qrow(**changes)])
    assert r["total_cost"] is None
    assert expected in r["lines"][0]["candidate_audit"][0]["rejections"]


def test_missing_and_future_quotes():
    for q in [[qrow(part_number="OTHER")], [qrow(quote_date="2027-01-01")]]:
        assert run(q=q)["lines"][0]["status"] == "missing_quote"


def test_duplicate_parts_are_all_excluded():
    b = pd.concat([bframe(), bframe()], ignore_index=True)
    b.loc[1, "part_number"] = " ００１ "
    r = run(b=b)
    assert not r["complete"] and r["lines"] == []
    assert [i["row"] for i in r["issues"] if i["code"] == "duplicate_part"] == [2, 3]


@pytest.mark.parametrize("value", ["", "-1", "0", "NaN", "Infinity", "1,000", "abc", "0.0000001", "1000000001"])
def test_invalid_bom_quantity(value):
    b = bframe()
    b.loc[0, "quantity_per_unit"] = value
    assert not run(b=b)["input_valid"]


@pytest.mark.parametrize("field,value", [("unit_price", ""), ("unit_price", "-1"), ("stock_qty", "-2"), ("min_qty", "x"), ("moq", "0"), ("max_qty", "-1"), ("quote_date", "2026/11/01"), ("currency", "人民币"), ("unit", "box")])
def test_invalid_quotes_block_complete_totals(field, value):
    r = run(q=[qrow(**{field: value})])
    assert not r["input_valid"] and r["total_cost"] is None
    assert r["issues"]


def test_invalid_tier_invalidates_entire_snapshot():
    q = [qrow(quote_id="A", max_qty="9"), qrow(quote_id="B", min_qty="10", unit_price="")]
    result = normalize_quotes(pd.DataFrame(q))
    assert result.data.empty
    assert {i.code for i in result.issues} == {"missing_price", "invalid_snapshot"}


@pytest.mark.parametrize("changes", [{"min_qty": "1"}, {"min_qty": "10", "stock_qty": "5"}])
def test_overlapping_or_inconsistent_tiers(changes):
    q = [qrow(quote_id="A", max_qty="9"), qrow(quote_id="B", **changes)]
    assert normalize_quotes(pd.DataFrame(q)).data.empty


def test_duplicate_quote_id():
    r = run(q=[qrow(), qrow(supplier="B")])
    assert any(i["code"] == "duplicate_quote" for i in r["issues"])


def test_normalization_aliases_zero_price_and_leading_zero():
    b = bframe().rename(columns={"part_number": "料号", "quantity_per_unit": "单机用量"})
    b.loc[0, "unit"] = "pcs"
    q = [qrow(part_number=" ００１ ", unit_price="0")]
    r = run(b=b, q=q)
    assert r["total_cost"] == "0.00" and r["lines"][0]["part_number"] == "001"
    assert r["composition"][0]["share_of_priced_subtotal"] is None


def test_price_comparison_switch_and_zero_base():
    q = [qrow(unit_price="0"), qrow(quote_id="Q2", quote_date="2026-11-01", unit_price="2")]
    r = compare_prices(normalize_bom(bframe()), normalize_quotes(pd.DataFrame(q)), "2026-10-01", "2026-11-01")
    assert r["total_delta"] == "4.00" and r["changes"][0]["percent_change"] is None
    q[0]["unit_price"] = "1"
    r = compare_prices(normalize_bom(bframe()), normalize_quotes(pd.DataFrame(q)), "2026-10-01", "2026-11-01")
    assert Decimal(r["changes"][0]["percent_change"]) == 100


@pytest.mark.parametrize("size", [0, -1, 1.5, True, 1000000001])
def test_invalid_batch(size):
    with pytest.raises(ValueError):
        run(batch_size=size)


def test_deterministic_supplier_ties_and_no_input_mutation():
    b = bframe()
    before = b.copy(deep=True)
    q = [qrow(supplier="B"), qrow(quote_id="Q2", supplier="A")]
    assert run(b=b, q=q)["lines"][0]["supplier"] == "A"
    first, second = run(q=q), run(q=list(reversed(q)))
    assert first["total_cost"] == second["total_cost"]
    assert first["lines"][0]["quote_id"] == second["lines"][0]["quote_id"]
    pd.testing.assert_frame_equal(b, before)


def test_fractional_quantity_and_round_per_line():
    b = bframe()
    b.loc[0, "quantity_per_unit"] = "0.5"
    b.loc[0, "unit"] = "M"
    assert run(b=b, q=[qrow(unit="M", moq="0.1", unit_price="0.01")])["total_cost"] == "0.01"


def test_demo_csv_excel_and_known_numbers():
    b, q = load_workbook(ROOT / "examples/ai_box_demo.xlsx")
    csv_b, csv_q = read_table(ROOT / "examples/ai_box_bom.csv"), read_table(ROOT / "examples/supplier_quotes.csv")
    assert len(b) == 20 and len(q) == 160
    r = run(b, q.to_dict("records"))
    assert r == run(csv_b, csv_q.to_dict("records"))
    assert r["complete"] and r["total_cost"] == "2982.40"
    batch = run(b, q.to_dict("records"), batch_size=100)
    assert batch["unpriced_lines"] == 1
    fan = next(l for l in batch["lines"] if l["part_number"] == "AI-008")
    assert fan["status"] == "shortage" and fan["shortage_qty"] == "120"
    assert batch["total_cost"] is None
    assert all("虚构" in str(x) for x in b["data_notice"])


def test_missing_price_fixture():
    b = read_table(ROOT / "examples/ai_box_bom.csv")
    q = read_table(ROOT / "examples/supplier_quotes_invalid.csv")
    r = run(b, q.to_dict("records"))
    assert r["priced_lines"] == 20 and not r["complete"]
    assert any(i["code"] == "missing_price" for i in r["issues"])


def test_input_schema_and_formula_rejection(tmp_path):
    with pytest.raises(ValueError, match="missing columns"):
        normalize_bom(pd.DataFrame({"part_number": ["001"]}))
    path = tmp_path / "duplicate.csv"
    path.write_text("料号,part_number\na,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_bom(read_table(path))
    xlsx = tmp_path / "formula.xlsx"
    book = Workbook()
    book.active.title = "BOM"
    book.active.append(["part_number"])
    book.active.append(["=1+1"])
    book.save(xlsx)
    with pytest.raises(ValueError, match="Formula"):
        read_table(xlsx)


def test_csv_literal_na_and_zero_prefix(tmp_path):
    p = tmp_path / "bom.csv"
    p.write_text("part_number,description,category,quantity_per_unit,unit\n001,NA,test,1,EA\n", encoding="utf-8")
    b = normalize_bom(read_table(p))
    assert b.data.iloc[0]["part_number"] == "001" and b.data.iloc[0]["description"] == "NA"


def test_empty_tables_never_complete():
    b = bframe().iloc[:0]
    assert not run(b=b)["complete"]


def test_large_amounts_keep_cents():
    b = bframe()
    b.loc[0, "quantity_per_unit"] = "999999999.999999"
    q = [qrow(unit_price="999999999.999999", stock_qty="1000000000")]
    r = run(b=b, q=q)
    assert r["total_cost"] == "999999999999998000.00"


def test_cli_export_no_overwrite(tmp_path):
    import subprocess
    import sys
    out = tmp_path / "result.json"
    command = [sys.executable, "-m", "bom_pilot.cli", "--workbook", str(ROOT / "examples/ai_box_demo.xlsx"), "--batch", "100", "--as-of", "2026-11-18", "--compare-from", "2026-10-01", "--output", str(out)]
    subprocess.run(command, check=True, capture_output=True)
    data = json.loads(out.read_text())
    assert data["single_unit"]["total_cost"] == "2982.40"
    assert data["single_unit"]["data_notices"] and all("虚构" in s for s in data["single_unit"]["data_notices"])
    assert data["batch"]["total_cost"] is None
    original = out.read_bytes()
    assert subprocess.run(command, capture_output=True).returncode != 0
    assert out.read_bytes() == original


def test_single_no_inventory_reservation_and_batch_recompute():
    q = [qrow(stock_qty="10", max_qty="9", unit_price="2"), qrow(quote_id="Q2", min_qty="10", stock_qty="10", unit_price="1")]
    assert run(q=q)["total_cost"] == "4.00"
    assert run(q=q, batch_size=5)["total_cost"] == "10.00"
    assert run(q=q, batch_size=6)["total_cost"] is None


def test_invalid_latest_snapshot_is_always_provisional():
    q = [qrow(), qrow(quote_id="BAD", quote_date="2026-11-01", unit_price="")]
    r = run(q=q)
    assert r["total_cost"] is None and not r["input_valid"]


def test_price_change_missing_side_is_not_zero():
    q = [qrow(quote_date="2026-11-01")]
    r = compare_prices(normalize_bom(bframe()), normalize_quotes(pd.DataFrame(q)), "2026-10-01", "2026-11-01")
    assert not r["complete"] and r["total_delta"] is None
    assert r["changes"][0]["delta"] is None


def test_demo_complete_batch10_and_composition():
    b, q = load_workbook(ROOT / "examples/ai_box_demo.xlsx")
    r = run(b, q.to_dict("records"), batch_size=10)
    assert r["complete"] and r["total_cost"] == "29822.20"
    assert sum(Decimal(c["priced_subtotal"]) for c in r["composition"]) == Decimal("29822.20")
    assert sum(Decimal(l["line_cost"]) for l in r["lines"]) == Decimal("29822.20")
