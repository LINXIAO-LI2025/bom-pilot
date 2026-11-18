"""Session tools for read-only procurement decisions."""
from dataclasses import asdict, dataclass
from decimal import Decimal
from itertools import chain

from .engine import calculate
from .models import NormalizedTable, json_safe, money, product, ratio
from .normalize import BOM_COLUMNS, text
from .procurement import calculate_procurement_plan, decimal_value, latest_quotes, supplier_quantities, validate_plan


@dataclass(frozen=True)
class Disruption:
    kind: str
    part_number: str
    supplier: str
    value: str  # price increase percentage or new inventory cap

    def __post_init__(self):
        if self.kind not in {"price_increase_pct", "stock_cap"}:
            raise ValueError("Unsupported disruption")
        object.__setattr__(self, "part_number", text(self.part_number).upper())
        object.__setattr__(self, "supplier", text(self.supplier).upper())
        value = decimal_value(self.value, "event value")
        if not self.part_number or not self.supplier or value > Decimal("1000000000"):
            raise ValueError("Invalid disruption scope or value")


@dataclass(frozen=True)
class DecisionContext:
    goal: str
    batch_size: int
    as_of: str
    currency: str = "CNY"
    budget: str | None = None
    reduction_pct: str | None = None
    locked_parts: tuple[str, ...] = ()
    disruptions: tuple[Disruption, ...] = ()

    def __post_init__(self):
        if not self.goal.strip():
            raise ValueError("A business goal is required")
        if self.budget is not None:
            decimal_value(self.budget, "budget")
        if self.reduction_pct is not None and decimal_value(self.reduction_pct, "reduction_pct") > 100:
            raise ValueError("reduction_pct must be <= 100")
        object.__setattr__(self, "locked_parts", tuple(sorted({text(p).upper() for p in self.locked_parts})))


def simulate_disruption(quotes: NormalizedTable, as_of: str, disruptions: tuple[Disruption, ...]):
    data = quotes.data.copy(deep=True)
    current = {(r["part_number"], r["supplier"]): r["quote_date"] for r in latest_quotes(quotes, as_of)}
    updates = []
    for event in disruptions:
        active = current.get((event.part_number, event.supplier))
        if active is None:
            raise ValueError("Disruption references no current supplier quote")
        mask = ((data["part_number"] == event.part_number) & (data["supplier"] == event.supplier)
                & (data["quote_date"] == active))
        value = decimal_value(event.value, "event value")
        for index in data.index[mask]:
            field = "unit_price" if event.kind == "price_increase_pct" else "stock_qty"
            before = data.at[index, field]
            after = product(before, 1 + value / 100) if field == "unit_price" else min(before, value)
            data.at[index, field] = after
            updates.append({"quote_id": data.at[index, "quote_id"], "field": field, "before": before, "after": after,
                            "source": "user_supplied_simulation"})
    return NormalizedTable(data, list(quotes.issues)), json_safe(updates)


def generate_change_report(before, after, acceptance, baseline_after_disruption, events):
    old, new = before["total_cost"], acceptance["recomputed_total"]
    delta = Decimal(new) - Decimal(old) if old is not None and new is not None else None
    previous = {i["part_number"]: i for i in before["items"]}
    changes = []
    for item in after["items"]:
        orig = previous[item["part_number"]]
        if orig["allocations"] != item["allocations"] or orig["status"] != item["status"]:
            changes.append({"part_number": item["part_number"], "before": orig["allocations"],
                            "proposed": item["allocations"], "status": "pending_review"})
    return json_safe({
        "approval_status": "pending_review" if acceptance["accepted"] else "blocked",
        "before_total": old, "after_total": new, "currency": before["currency"], "delta": delta,
        "cost_change_pct": product(ratio(delta, Decimal(old)), Decimal(100)) if delta is not None and Decimal(old) else None,
        "scenario_incumbent_subtotal": baseline_after_disruption["subtotal"],
        "scenario_incumbent_total": baseline_after_disruption["total_cost"],
        "scenario_incumbent_viable": baseline_after_disruption["complete"],
        "before_subtotal": before["subtotal"], "after_subtotal": acceptance["recomputed_subtotal"],
        "gaps": acceptance["gaps"], "constraints": acceptance["constraints"],
        "budget_overage": acceptance["budget_overage"], "events": events, "changes": changes,
        "bom_changes": [], "substitution_candidates": [], "proposal": after,
        "exceptions": [{k: i[k] for k in ("part_number", "status", "gap_qty")}
                       for i in after["items"] if i["status"] != "filled"],
    })


class DecisionTools:
    """One immutable-by-convention input snapshot and one what-if scenario per run."""

    def __init__(self, bom: NormalizedTable, quotes: NormalizedTable, context: DecisionContext):
        self.bom = NormalizedTable(bom.data.copy(deep=True), list(bom.issues))
        self.quotes = NormalizedTable(quotes.data.copy(deep=True), list(quotes.issues))
        self.context = context
        self.params = {"batch_size": context.batch_size, "as_of": context.as_of, "currency": context.currency}
        self.scenario_quotes, self.events = simulate_disruption(self.quotes, context.as_of, context.disruptions)
        self.before = calculate_procurement_plan(self.bom, self.quotes, **self.params, strategy="single")
        current = {i["part_number"]: supplier_quantities(i["allocations"]) for i in self.before["items"]}
        if set(context.locked_parts) - current.keys():
            raise ValueError("Locked parts must exist in the valid BOM")
        self.locks = {p: current[p] for p in context.locked_parts}
        self.incumbent = (calculate_procurement_plan(self.bom, self.scenario_quotes, **self.params,
                         locked_allocations=current, strategy="single") if self.events else self.before)
        constraints = []
        if context.budget is not None:
            constraints.append(decimal_value(context.budget, "budget"))
        self.target_available = context.reduction_pct is None or self.before["total_cost"] is not None
        if context.reduction_pct is not None and self.target_available:
            constraints.append(product(Decimal(self.before["total_cost"]),
                                       1 - decimal_value(context.reduction_pct, "reduction_pct") / 100))
        self.budget = min(constraints, default=None)
        self.plans, self.acceptances = {}, {}

    def analyze_bom(self):
        r = calculate(self.bom, self.scenario_quotes, **self.params)
        leading = sorted((l for l in r["lines"] if l["line_cost"] is not None),
                         key=lambda l: (-Decimal(l["line_cost"]), l["part_number"]))[:5]
        notices = sorted(set(filter(None, chain(self.bom.data["data_notice"], self.quotes.data["data_notice"]))))
        return {
            "data_notices": notices, "part_count": len(r["lines"]), "baseline_total": self.before["total_cost"],
            "scenario_incumbent_total": self.incumbent["total_cost"], "budget": json_safe(self.budget),
            "single_supplier_priced_subtotal": r["priced_subtotal"], "composition": r["composition"],
            "top_cost_items": [{k: line[k] for k in ("part_number", "description", "line_cost")} for line in leading],
            "data_quality": r["issues"], "unpriced": [{"part_number": l["part_number"], "status": l["status"]}
                                                      for l in r["lines"] if l["status"] != "priced"],
        }

    def find_supplier_options(self, part_numbers: list[str]):
        known = set(self.bom.data["part_number"])
        requested = sorted({text(p).upper() for p in part_numbers})
        rows = []
        for quote in latest_quotes(self.scenario_quotes, self.context.as_of):
            if quote["part_number"] in requested and quote["part_number"] in known:
                rows.append({**quote, "quote_date": quote["quote_date"].isoformat()})
        return json_safe({"options": rows, "unknown_parts": sorted(set(requested) - known),
                          "parts_without_quotes": sorted((set(requested) & known) - {r["part_number"] for r in rows}),
                          "source": "uploaded_quote_snapshot"})

    def calculate_procurement_plan(self, strategy: str):
        plan = calculate_procurement_plan(self.bom, self.scenario_quotes, **self.params,
                                          strategy=strategy, locked_allocations=self.locks)
        plan_id = f"plan-{len(self.plans) + 1}"
        self.plans[plan_id] = plan
        return {"plan_id": plan_id, **plan}

    def simulate_disruption(self):
        return {"events": self.events, "scenario_incumbent_total": self.incumbent["total_cost"],
                "scope": "user_supplied_events_applied_to_a_copy"}

    def validate_plan(self, plan_id: str):
        r = validate_plan(self.bom, self.scenario_quotes, self.plans[plan_id], **self.params,
                          budget=self.budget, locked_allocations=self.locks)
        r["constraints"]["reduction_baseline_available"] = self.target_available
        r["accepted"] = r["accepted"] and self.target_available
        self.acceptances[plan_id] = r
        return {"plan_id": plan_id, **r}

    def generate_change_report(self, plan_id: str):
        report = generate_change_report(self.before, self.plans[plan_id],
                                        self.acceptances[plan_id], self.incumbent, self.events)
        report["proposed_bom"] = json_safe(self.bom.data[BOM_COLUMNS + ["data_notice"]].to_dict("records"))
        return {"plan_id": plan_id, **report}
