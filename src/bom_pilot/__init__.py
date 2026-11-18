"""Pure local data engine. No model, network, credentials or UI dependencies."""
from .io import read_table, load_workbook
from .normalize import normalize_bom, normalize_quotes
from .engine import calculate, compare_prices

__all__ = ["read_table", "load_workbook", "normalize_bom", "normalize_quotes", "calculate", "compare_prices"]
