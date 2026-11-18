from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from typing import Any
import pandas as pd

@dataclass(frozen=True)
class Issue:
    table: str
    row: int  # physical Excel/CSV row, including header
    field: str
    code: str
    message: str
    severity: str = "error"

@dataclass
class NormalizedTable:
    data: pd.DataFrame
    issues: list[Issue]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


def money(value: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def product(a: Decimal, b: Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 60
        return a * b


def ratio(a: Decimal, b: Decimal) -> Decimal | None:
    if b == 0:
        return None
    with localcontext() as ctx:
        ctx.prec = 60
        return a / b


def json_safe(value: Any) -> Any:
    """Decimals stay decimal strings; JSON consumers never need binary floats."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def total(values) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 80
        return sum(values, Decimal("0.00"))
