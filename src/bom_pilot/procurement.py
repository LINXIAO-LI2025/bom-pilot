"""Exact procurement search and independent acceptance checks."""
from collections import defaultdict
from dataclasses import asdict
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import re

from .models import NormalizedTable, json_safe, money, product, total

MAX_TICKS = 50_000
MAX_TRANSITIONS = 2_000_000
STEPS = {"EA": Decimal(1), "SET": Decimal(1), "M": Decimal("0.001"), "KG": Decimal("0.001")}


def latest_quotes(quotes: NormalizedTable, as_of: str) -> list[dict]:
    day = date.fromisoformat(as_of)
    if day.isoformat() != as_of:
        raise ValueError("as_of must use YYYY-MM-DD")
    latest = {}
    for quote in quotes.data.to_dict("records"):
        if quote["quote_date"] <= day:
            key = (quote["part_number"], quote["supplier"])
            latest.setdefault(key, []).append(quote)
    result = []
    for key in sorted(latest):
        rows = latest[key]
        newest = max(q["quote_date"] for q in rows)
        result.extend(sorted((q for q in rows if q["quote_date"] == newest), key=lambda q: q["min_qty"]))
    return result


def allocation(quote: dict, qty: Decimal) -> dict:
    return {
        **{key: quote[key] for key in ("part_number", "supplier", "quote_id", "currency", "unit",
                                       "unit_price", "min_qty", "max_qty", "moq", "stock_qty", "source_row")},
        "quote_date": quote["quote_date"].isoformat(),
        "quantity": qty,
        "cost": money(product(qty, quote["unit_price"])),
    }


def decimal_value(value, name: str) -> Decimal:
    # Use plain decimal strings/integers at external boundaries.
    if not re.fullmatch(r"[0-9]{1,40}(?:\.[0-9]{1,24})?", str(value)):
        raise ValueError(f"{name} must be a nonnegative decimal")
    return Decimal(str(value))


def fits(q: dict, qty: Decimal, part: dict, currency: str) -> bool:
    return (
        q["part_number"] == part["part_number"] and q["unit"] == part["unit"]
        and q["currency"] == currency and qty > 0
        and max(q["moq"], q["min_qty"]) <= qty <= q["stock_qty"]
        and (q["max_qty"] is None or qty <= q["max_qty"])
    )


def supplier_quantities(allocations: list[dict]) -> dict[str, Decimal]:
    return {a["supplier"]: Decimal(str(a["quantity"])) for a in allocations}


def tick_range(quote, step, needed):
    lower = max(1, int((max(quote["moq"], quote["min_qty"]) / step).to_integral_value(rounding=ROUND_CEILING)))
    upper_qty = quote["stock_qty"]
    if quote["max_qty"] is not None:
        upper_qty = min(upper_qty, quote["max_qty"])
    upper = min(needed, int((upper_qty / step).to_integral_value(rounding=ROUND_FLOOR)))
    return lower, upper


def optimize(quotes, demand, step, strategy, locked):
    if demand % step != 0:
        return "unsupported_quantity_increment", []
    suppliers = defaultdict(list)
    for quote in quotes:
        suppliers[quote["supplier"]].append(quote)
    if not suppliers:
        return "no_compatible_quote", []
    needed = int(demand / step)
    if locked is not None:
        chosen = []
        for supplier, qty in sorted(locked.items()):
            if qty % step:
                return "locked_allocation_unavailable", []
            ticks = int(qty / step)
            valid = []
            for quote in suppliers.get(supplier, []):
                lower, upper = tick_range(quote, step, needed)
                if lower <= ticks <= upper:
                    valid.append(quote)
            if not valid:
                return "locked_allocation_unavailable", []
            chosen.append(allocation(valid[0], qty))
        if total(a["quantity"] for a in chosen) != demand:
            return "locked_allocation_unavailable", chosen
        return "filled", chosen

    if strategy == "single" or len(suppliers) == 1:
        options = []
        for quote in quotes:
            lower, upper = tick_range(quote, step, needed)
            if lower <= upper:
                options.append(allocation(quote, upper * step))
        if not options:
            return "tier_or_moq_unavailable", []
        best = min(options, key=lambda a: (-a["quantity"], a["cost"], a["supplier"], a["quote_id"]))
        return ("filled" if best["quantity"] == demand else "supply_gap"), [best]

    if needed > MAX_TICKS:
        return "search_limit", []
    # Each supplier contributes zero or one tier. For each covered quantity, keep
    # only the lowest rounded cost. Quantities never exceed exact demand.
    states = {0: (0, ())}
    for supplier in sorted(suppliers):
        offers = []
        for q in suppliers[supplier]:
            lower, upper = tick_range(q, step, needed)
            if lower <= upper:
                offers.append((lower, upper, q))
        updated = states.copy()
        transitions = sum(upper - lower + 1 for lower, upper, _ in offers) * len(states)
        if transitions > MAX_TRANSITIONS:
            return "search_limit", []
        for lower, upper, q in offers:
            for ticks in range(lower, upper + 1):
                qty = ticks * step
                cents = int(money(product(qty, q["unit_price"])) * 100)
                for previous, (cost, selections) in states.items():
                    covered = previous + ticks
                    if covered <= needed and (covered not in updated or cost + cents < updated[covered][0]):
                        updated[covered] = (cost + cents, selections + ((q, qty),))
        states = updated
    covered = max(states)
    chosen = [allocation(q, qty) for q, qty in states[covered][1]]
    return ("filled" if covered == needed else "supply_gap" if covered else "tier_or_moq_unavailable"), chosen


def calculate_procurement_plan(bom: NormalizedTable, quotes: NormalizedTable, *, batch_size: int,
                               as_of: str, currency: str = "CNY", strategy: str = "split",
                               locked_allocations: dict | None = None) -> dict:
    if type(batch_size) is not int or not 1 <= batch_size <= 10**9:
        raise ValueError("Invalid batch_size")
    if not re.fullmatch(r"[A-Z]{3}", currency) or strategy not in {"single", "split"}:
        raise ValueError("Invalid currency or strategy")
    by_part = defaultdict(list)
    for quote in latest_quotes(quotes, as_of):
        by_part[quote["part_number"]].append(quote)
    items = []
    for part in bom.data.to_dict("records"):
        pn = part["part_number"]
        demand = product(part["quantity_per_unit"], Decimal(batch_size))
        options = [q for q in by_part[pn] if q["currency"] == currency and q["unit"] == part["unit"]]
        status, orders = optimize(options, demand, STEPS[part["unit"]], strategy,
                                  (locked_allocations or {}).get(pn))
        filled = total(a["quantity"] for a in orders)
        gap = None if status in {"search_limit", "unsupported_quantity_increment"} else demand - filled
        items.append({
            "part_number": pn, "description": part["description"], "category": part["category"],
            "unit": part["unit"], "required_qty": demand, "allocated_qty": filled, "gap_qty": gap,
            "status": status, "allocations": orders, "subtotal": total(a["cost"] for a in orders),
        })
    complete = bool(items) and not (bom.has_errors or quotes.has_errors) and all(i["status"] == "filled" for i in items)
    subtotal = total(i["subtotal"] for i in items)
    return json_safe({
        "batch_size": batch_size, "currency": currency, "as_of": as_of, "strategy": strategy,
        "complete": complete, "subtotal": subtotal, "total_cost": subtotal if complete else None,
        "items": items, "issues": [asdict(i) for i in bom.issues + quotes.issues],
    })


def validate_plan(bom: NormalizedTable, quotes: NormalizedTable, plan: dict, *, batch_size: int,
                  as_of: str, currency: str = "CNY", budget: Decimal | None = None,
                  locked_allocations: dict | None = None) -> dict:
    """Recompute from BOM and quote snapshot. Never use planner totals as evidence."""
    order_errors, gaps, lock_errors, costs = [], [], [], []
    parts = {p["part_number"]: p for p in bom.data.to_dict("records")}
    offers = {q["quote_id"]: q for q in latest_quotes(quotes, as_of)}
    items = defaultdict(list)
    for item in plan["items"]:
        items[item["part_number"]].append(item)
    if (plan.get("batch_size"), plan.get("as_of"), plan.get("currency")) != (batch_size, as_of, currency):
        order_errors.append({"code": "context_mismatch"})
    for key, rows in items.items():
        if key not in parts or len(rows) != 1:
            order_errors.append({"code": "unknown_or_duplicate_part", "part_number": key})
    for pn, part in parts.items():
        demand = product(part["quantity_per_unit"], Decimal(batch_size))
        used = {}
        row = items[pn][0] if len(items[pn]) == 1 else {}
        row_costs = []
        for order in row.get("allocations", []):
            supplier = order.get("supplier")
            quote = offers.get(order.get("quote_id"))
            try:
                qty = decimal_value(order.get("quantity"), "quantity")
            except ValueError:
                order_errors.append({"code": "invalid_quantity", "part_number": pn})
                continue
            if (quote is None or supplier != quote["supplier"] or order.get("part_number") != pn
                    or supplier in used or qty % STEPS[part["unit"]] != 0 or not fits(quote, qty, part, currency)):
                order_errors.append({"code": "ineligible_or_duplicate_order", "part_number": pn, "supplier": supplier})
                continue
            cost = money(product(qty, quote["unit_price"]))
            expected = json_safe(allocation(quote, qty))
            metadata = set(expected) - {"quantity", "cost", "unit_price"}
            try:
                correct_amounts = (decimal_value(order.get("cost"), "cost") == cost
                                   and decimal_value(order.get("unit_price"), "unit_price") == quote["unit_price"])
            except ValueError:
                correct_amounts = False
            if not correct_amounts or any(order.get(key) != expected[key] for key in metadata):
                order_errors.append({"code": "order_metadata_or_cost_mismatch", "part_number": pn, "supplier": supplier})
            costs.append(cost)
            row_costs.append(cost)
            used[supplier] = qty
        filled = total(used.values())
        if row:
            try:
                amounts_match = (decimal_value(row.get("required_qty"), "required_qty") == demand
                                 and decimal_value(row.get("allocated_qty"), "allocated_qty") == filled
                                 and decimal_value(row.get("subtotal"), "subtotal") == total(row_costs))
            except ValueError:
                amounts_match = False
            if row.get("unit") != part["unit"] or not amounts_match:
                order_errors.append({"code": "item_metadata_or_cost_mismatch", "part_number": pn})
        if filled != demand:
            gaps.append({"part_number": pn, "required_qty": demand, "allocated_qty": filled,
                         "gap_qty": max(Decimal(0), demand - filled), "excess_qty": max(Decimal(0), filled - demand)})
        if pn in (locked_allocations or {}) and used != locked_allocations[pn]:
            lock_errors.append(pn)
    invalid_locks = sorted(set(locked_allocations or {}) - parts.keys())
    lock_errors.extend(invalid_locks)
    subtotal = total(costs)
    valid_inputs = bool(parts) and not (bom.has_errors or quotes.has_errors)
    full = valid_inputs and not gaps and not order_errors
    cost_matches = True
    try:
        cost_matches = decimal_value(plan.get("subtotal"), "subtotal") == subtotal
        if full:
            cost_matches = cost_matches and decimal_value(plan.get("total_cost"), "total_cost") == subtotal
        else:
            cost_matches = cost_matches and plan.get("total_cost") is None
    except ValueError:
        cost_matches = False
    budget_met = None if budget is None else (subtotal <= budget if full else None)
    return json_safe({
        "accepted": full and not lock_errors and cost_matches and (budget is None or budget_met is True),
        "constraints": {"inputs_valid": valid_inputs, "demand_met": bool(parts) and not gaps,
                        "quotes_and_orders_valid": not order_errors, "locked_allocations_preserved": not lock_errors,
                        "reported_cost_matches": cost_matches, "budget_met": budget_met},
        "budget": budget, "recomputed_subtotal": subtotal, "recomputed_total": subtotal if full else None,
        "budget_overage": max(Decimal(0), subtotal - budget) if full and budget is not None else None,
        "gaps": gaps, "order_errors": order_errors, "locked_part_violations": lock_errors,
    })
