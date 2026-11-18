"""Only tabular input is read. Nothing executes spreadsheet formulas/macros."""
from pathlib import Path
import pandas as pd
from openpyxl import load_workbook as open_xlsx


def read_table(path: str | Path, sheet_name: str = "BOM") -> pd.DataFrame:
    path = Path(path)
    if path.suffix.lower() == ".csv":
        # header=None preserves duplicate headers for explicit rejection later.
        raw = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig", header=None)
    elif path.suffix.lower() == ".xlsx":
        book = open_xlsx(path, read_only=True, data_only=False)
        try:
            if sheet_name not in book.sheetnames:
                raise ValueError(f"Missing sheet: {sheet_name}")
            for row in book[sheet_name].iter_rows():
                for cell in row:
                    if cell.data_type == "f":
                        raise ValueError(f"Formula cells unsupported: {sheet_name}!{cell.coordinate}")
        finally:
            book.close()
        raw = pd.read_excel(path, sheet_name=sheet_name, dtype=str, keep_default_na=False, header=None, engine="openpyxl")
    else:
        raise ValueError("Only UTF-8 CSV and .xlsx are supported")
    if raw.empty:
        raise ValueError("Input table is empty")
    frame = raw.iloc[1:].copy()
    frame.columns = raw.iloc[0].tolist()
    return frame.reset_index(drop=True)


def load_workbook(path: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return read_table(path, "BOM"), read_table(path, "Quotes")
