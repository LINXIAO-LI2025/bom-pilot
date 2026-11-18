import argparse
import json
from pathlib import Path
from .io import read_table, load_workbook
from .normalize import normalize_bom, normalize_quotes
from .engine import calculate, compare_prices


def main():
    p = argparse.ArgumentParser(description="BOM Pilot local auditable cost engine; no model calls")
    inputs = p.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--workbook")
    inputs.add_argument("--bom")
    p.add_argument("--quotes")
    p.add_argument("--batch", type=int, default=1)
    p.add_argument("--as-of", required=True)
    p.add_argument("--compare-from")
    p.add_argument("--currency", default="CNY")
    p.add_argument("--output", help="New JSON file only; existing files are never overwritten")
    args = p.parse_args()
    if args.workbook:
        b, q = load_workbook(args.workbook)
    else:
        if not args.quotes:
            p.error("--quotes is required with --bom")
        b, q = read_table(args.bom), read_table(args.quotes, "Quotes")
    bom, quotes = normalize_bom(b), normalize_quotes(q)
    result = {"single_unit": calculate(bom, quotes, 1, args.as_of, args.currency),
              "batch": calculate(bom, quotes, args.batch, args.as_of, args.currency)}
    if args.compare_from:
        result["price_changes"] = compare_prices(bom, quotes, args.compare_from, args.as_of, args.batch, args.currency)
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        with Path(args.output).open("x", encoding="utf-8") as f:
            f.write(payload + "\n")
    else:
        print(payload)
    return 0

if __name__ == "__main__":
    main()
