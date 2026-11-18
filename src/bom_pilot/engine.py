"""Deterministic, single-source-per-part planning (not a global optimizer)."""
from dataclasses import asdict
from datetime import date
from decimal import Decimal
import re
from .models import NormalizedTable, json_safe, money, product, ratio, total


def calculate(bom: NormalizedTable, quotes: NormalizedTable, batch_size: int = 1,
              as_of: str = "2026-11-18", currency: str = "CNY") -> dict:
    if type(batch_size) is not int or not 1 <= batch_size <= 10**9:
        raise ValueError("batch_size must be an integer in [1, 1e9]")
    day = date.fromisoformat(as_of)
    if day.isoformat() != as_of:
        raise ValueError("as_of must use YYYY-MM-DD")
    currency = currency.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("currency must be a three-letter code")
    issues = [asdict(i) for i in bom.issues + quotes.issues]
    lines = []
    for part in bom.data.to_dict("records"):
        demand = product(part["quantity_per_unit"], Decimal(batch_size))
        available = quotes.data[(quotes.data["part_number"] == part["part_number"]) & (quotes.data["quote_date"] <= day)]
        candidates, audit = [], []
        for _, rows in available.groupby("supplier", sort=True):
            # Do not use a cheaper stale offer when a newer snapshot exists.
            rows = rows[rows["quote_date"] == rows["quote_date"].max()]
            for quote in rows.to_dict("records"):
                reasons = []
                if quote["currency"] != currency:
                    reasons.append("currency_mismatch")
                if quote["unit"] != part["unit"]:
                    reasons.append("unit_mismatch")
                if demand < quote["moq"]:
                    reasons.append("below_moq")
                if demand < quote["min_qty"] or (quote["max_qty"] is not None and demand > quote["max_qty"]):
                    reasons.append("outside_tier")
                if quote["stock_qty"] < demand:
                    reasons.append("insufficient_stock")
                extended = money(product(demand, quote["unit_price"]))
                audit.append({**quote, "quote_date": quote["quote_date"].isoformat(), "rejections": reasons, "extended_cost": extended})
                if not reasons:
                    candidates.append((extended, quote["unit_price"], quote["supplier"], quote["quote_id"], quote))
        line = {**part, "required_qty": demand, "currency": currency, "candidate_audit": audit}
        if candidates:
            selected = min(candidates, key=lambda v: v[:4])[-1]
            cost = money(product(demand, selected["unit_price"]))
            line.update(status="priced", supplier=selected["supplier"], quote_id=selected["quote_id"],
                        quote_date=selected["quote_date"].isoformat(), unit_price=selected["unit_price"],
                        line_cost=cost, stock_qty=selected["stock_qty"], moq=selected["moq"],
                        min_qty=selected["min_qty"], max_qty=selected["max_qty"])
        else:
            # Quantity-feasible tiers with only stock failures identify shortages.
            shortages = [a for a in audit if a["rejections"] == ["insufficient_stock"]]
            status = "shortage" if shortages else ("no_eligible_quote" if audit else "missing_quote")
            line.update(status=status, supplier=None, quote_id=None, unit_price=None, line_cost=None)
            if shortages:
                line["best_available_stock"] = max(a["stock_qty"] for a in shortages)
                line["shortage_qty"] = demand - line["best_available_stock"]
        lines.append(line)
    priced = [line for line in lines if line["status"] == "priced"]
    subtotal = total(line["line_cost"] for line in priced)
    complete = bool(lines) and len(priced) == len(lines) and not bom.has_errors and not quotes.has_errors
    categories = sorted(set(line["category"] for line in lines))
    composition = []
    for category in categories:
        category_lines = [l for l in lines if l["category"] == category]
        cost = total(l["line_cost"] for l in category_lines if l["line_cost"] is not None)
        composition.append({"category": category, "priced_subtotal": cost,
                            "share_of_priced_subtotal": ratio(cost, subtotal),
                            "complete": all(l["status"] == "priced" for l in category_lines)})
    return json_safe({"schema_version": "1.0", "data_notices": sorted((set(bom.data["data_notice"]) | set(quotes.data["data_notice"])) - {""}), "batch_size": batch_size, "as_of": as_of, "currency": currency,
                     "complete": complete, "input_valid": not bom.has_errors and not quotes.has_errors,
                     "priced_subtotal": subtotal, "total_cost": subtotal if complete else None,
                     "equivalent_unit_cost": ratio(subtotal, Decimal(batch_size)) if complete else None,
                     "priced_lines": len(priced), "unpriced_lines": len(lines) - len(priced),
                     "issues": issues, "lines": lines, "composition": composition,
                     "policy": {"tier_bounds": "inclusive", "selection": "lowest rounded extended cost; ties: unit_price, supplier, quote_id",
                                "allocation": "one supplier per part, exact demand, no overbuy or stock reservation",
                                "rounding": "each line rounded to 0.01 ROUND_HALF_UP then summed",
                                "prices": "tax/freight treatment is as supplied; no FX conversion",
                                "history": "latest dated snapshot per supplier at or before as_of",
                                "errors": "any invalid input blocks complete totals; subtotal is partial/provisional"}})


def compare_prices(bom: NormalizedTable, quotes: NormalizedTable, before: str, after: str,
                   batch_size: int = 1, currency: str = "CNY") -> dict:
    if date.fromisoformat(before) >= date.fromisoformat(after):
        raise ValueError("before must precede after")
    old = calculate(bom, quotes, batch_size, before, currency)
    new = calculate(bom, quotes, batch_size, after, currency)
    old_lines = {l["part_number"]: l for l in old["lines"]}
    changes = []
    for line in new["lines"]:
        previous = old_lines[line["part_number"]]
        comparable = previous["line_cost"] is not None and line["line_cost"] is not None
        delta = total([Decimal(line["line_cost"]), -Decimal(previous["line_cost"])]) if comparable else None
        percent = product(ratio(delta, Decimal(previous["line_cost"])), Decimal(100)) if comparable and Decimal(previous["line_cost"]) != 0 else None
        changes.append({"part_number": line["part_number"], "before_status": previous["status"], "after_status": line["status"],
                        "before_quote_id": previous["quote_id"], "after_quote_id": line["quote_id"],
                        "before_supplier": previous["supplier"], "after_supplier": line["supplier"],
                        "before_unit_price": previous["unit_price"], "after_unit_price": line["unit_price"],
                        "before_cost": previous["line_cost"], "after_cost": line["line_cost"],
                        "delta": delta, "percent_change": percent})
    both = old["complete"] and new["complete"]
    delta = total([Decimal(new["total_cost"]), -Decimal(old["total_cost"])]) if both else None
    return json_safe({"before": before, "after": after, "batch_size": batch_size, "currency": currency,
                      "complete": both, "before_total": old["total_cost"], "after_total": new["total_cost"],
                      "total_delta": delta, "changes": changes,
                      "note": "Repriced at constant BOM and quantity; supplier switches, MOQ and stock changes may affect price. Not a market price index."})
