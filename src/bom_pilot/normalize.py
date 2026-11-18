"""Canonical fields, strict values, and row-level diagnostics. Never silently dedupe."""
from datetime import date
from decimal import Decimal, InvalidOperation
import re
import unicodedata
import pandas as pd
from .models import Issue, NormalizedTable

BOM_COLUMNS = ["part_number", "description", "category", "quantity_per_unit", "unit"]
QUOTE_COLUMNS = ["quote_id", "part_number", "supplier", "quote_date", "currency", "unit", "unit_price", "min_qty", "max_qty", "moq", "stock_qty"]
ALIASES = {
    "料号": "part_number", "物料名称": "description", "类别": "category", "单机用量": "quantity_per_unit",
    "单位": "unit", "报价编号": "quote_id", "供应商": "supplier", "报价日期": "quote_date", "币种": "currency",
    "单价": "unit_price", "阶梯起量": "min_qty", "阶梯上限": "max_qty", "最小起订量": "moq", "库存": "stock_qty",
}
UNITS = {"EA": "EA", "PCS": "EA", "PC": "EA", "个": "EA", "件": "EA", "M": "M", "米": "M", "KG": "KG", "千克": "KG", "SET": "SET", "套": "SET"}


def text(v) -> str:
    return "" if pd.isna(v) else unicodedata.normalize("NFKC", str(v)).strip()


def number(v, *, positive=False, optional=False) -> Decimal | None:
    value = text(v)
    if optional and not value:
        return None
    try:
        n = Decimal(value)
    except InvalidOperation:
        raise ValueError("Expected a plain decimal number") from None
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,6})?", value) or not n.is_finite() or n < 0 or n > Decimal("1000000000") or (positive and n == 0):
        raise ValueError("Expected nonnegative decimal <= 1e9, at most 6 decimal places" + (", strictly positive" if positive else ""))
    return n


def prepare(frame: pd.DataFrame, columns: list[str], table: str):
    df = frame.copy(deep=True).reset_index(drop=True)
    names = [ALIASES.get(text(c), text(c).lower()) for c in df.columns]
    if len(names) != len(set(names)):
        raise ValueError(f"{table}: duplicate/ambiguous column headers")
    df.columns = names
    required = set(columns) - ({"max_qty", "moq"} if table == "quotes" else set())
    missing = required - set(names)
    if missing:
        raise ValueError(f"{table}: missing columns {sorted(missing)}")
    for c in columns:
        if c not in df:
            df[c] = "1" if c == "moq" else ""
    return df, []


def normalize_bom(frame: pd.DataFrame) -> NormalizedTable:
    df, issues = prepare(frame, BOM_COLUMNS, "bom")
    records = []
    ids = df["part_number"].map(lambda v: text(v).upper())
    duplicates = set(ids[ids.duplicated(keep=False)]) - {""}
    for i, r in df.iterrows():
        row = i + 2
        record = {c: text(r[c]) for c in BOM_COLUMNS}
        record["part_number"] = ids.iloc[i]
        record["source_row"] = row
        record["data_notice"] = text(r.get("data_notice", ""))
        before = len(issues)
        for c in ["part_number", "description", "category"]:
            if not record[c]:
                issues.append(Issue("bom", row, c, "missing_value", "Required value is empty"))
        if record["part_number"] in duplicates:
            issues.append(Issue("bom", row, "part_number", "duplicate_part", "Duplicate normalized part number; all occurrences excluded"))
        try:
            record["quantity_per_unit"] = number(r["quantity_per_unit"], positive=True)
        except ValueError as e:
            issues.append(Issue("bom", row, "quantity_per_unit", "invalid_number", str(e)))
        record["unit"] = UNITS.get(text(r["unit"]).upper())
        if record["unit"] is None:
            issues.append(Issue("bom", row, "unit", "invalid_unit", "Unsupported unit"))
        if len(issues) == before:
            records.append(record)
    return NormalizedTable(pd.DataFrame(records, columns=BOM_COLUMNS + ["source_row", "data_notice"]), issues)


def normalize_quotes(frame: pd.DataFrame) -> NormalizedTable:
    df, issues = prepare(frame, QUOTE_COLUMNS, "quotes")
    # One supplier/part/date is one inventory snapshot, including all quantity tiers.
    records, bad_groups = [], set()
    ids = df["quote_id"].map(lambda v: text(v).upper())
    duplicates = set(ids[ids.duplicated(keep=False)]) - {""}
    for i, r in df.iterrows():
        row = i + 2
        d = {c: text(r[c]) for c in QUOTE_COLUMNS}
        for c in ["part_number", "supplier", "quote_id", "currency"]:
            d[c] = d[c].upper()
        group = (d["part_number"], d["supplier"], d["quote_date"])
        d["source_row"] = row
        d["data_notice"] = text(r.get("data_notice", ""))
        before = len(issues)
        for c in ["quote_id", "part_number", "supplier"]:
            if not d[c]:
                issues.append(Issue("quotes", row, c, "missing_value", "Required value is empty"))
        if d["quote_id"] in duplicates:
            issues.append(Issue("quotes", row, "quote_id", "duplicate_quote", "Quote ID must be unique"))
        try:
            parsed = date.fromisoformat(d["quote_date"])
            if parsed.isoformat() != d["quote_date"]:
                raise ValueError()
            d["quote_date"] = parsed
        except ValueError:
            issues.append(Issue("quotes", row, "quote_date", "invalid_date", "Use YYYY-MM-DD"))
        if not re.fullmatch(r"[A-Z]{3}", d["currency"]):
            issues.append(Issue("quotes", row, "currency", "invalid_currency", "Use a three-letter currency code"))
        d["unit"] = UNITS.get(d["unit"].upper())
        if d["unit"] is None:
            issues.append(Issue("quotes", row, "unit", "invalid_unit", "Unsupported unit"))
        for c in ["unit_price", "min_qty", "max_qty", "moq", "stock_qty"]:
            try:
                if c == "unit_price" and not text(r[c]):
                    issues.append(Issue("quotes", row, c, "missing_price", "Price is missing; never treated as zero"))
                    continue
                d[c] = number(r[c], positive=c == "moq", optional=c == "max_qty")
            except ValueError as e:
                issues.append(Issue("quotes", row, c, "invalid_number", str(e)))
        if len(issues) == before and d["max_qty"] is not None and d["max_qty"] < d["min_qty"]:
            issues.append(Issue("quotes", row, "max_qty", "invalid_range", "max_qty < min_qty"))
        if len(issues) != before:
            bad_groups.add(group)
        else:
            records.append(d)
    valid = []
    for d in records:
        key = (d["part_number"], d["supplier"], d["quote_date"].isoformat())
        if key in bad_groups:
            issues.append(Issue("quotes", d["source_row"], "quote_id", "invalid_snapshot", "Another tier in this snapshot is invalid"))
        else:
            valid.append(d)
    data = pd.DataFrame(valid, columns=QUOTE_COLUMNS + ["source_row", "data_notice"])
    bad_rows = set()
    for _, group in data.groupby(["part_number", "supplier", "quote_date"], sort=False):
        inconsistent = any(len(set(group[c])) != 1 for c in ["stock_qty", "currency", "unit", "moq"])
        ordered = group.sort_values("min_qty").to_dict("records")
        overlap = any(a["max_qty"] is None or a["max_qty"] >= b["min_qty"] for a, b in zip(ordered, ordered[1:]))
        if inconsistent or overlap:
            for d in ordered:
                bad_rows.add(d["source_row"])
                issues.append(Issue("quotes", d["source_row"], "min_qty", "invalid_snapshot", "Overlapping tiers or inconsistent inventory/currency/unit/MOQ"))
    data = data[~data["source_row"].isin(bad_rows)].reset_index(drop=True)
    return NormalizedTable(data, issues)
