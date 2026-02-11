#!/usr/bin/env python3
"""Save job search results to Google Sheets via Apps Script webhook."""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SHEET_HEADERS = ["Fit Score", "Source", "Date Posted", "Title", "Company", "Location", "Remote", "URL", "Date Scraped", "Salary", "Description"]


def load_rows(input_path: Path) -> list[list]:
    """Load job rows from a JSON file (list of dicts or list of lists)."""
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    for item in data:
        if isinstance(item, list):
            rows.append(item)
        elif isinstance(item, dict):
            rows.append([item.get(h, "") for h in SHEET_HEADERS])
    return rows


def _url_with_sheet(url: str, sheet_name: str | None) -> str:
    if not sheet_name:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sheetName={urllib.parse.quote(sheet_name)}"


def post_rows(rows: list[list], webhook_url: str, sheet_name: str | None = None, debug: bool = False) -> None:
    """POST job rows as JSON to a Google Apps Script webhook URL."""
    if not rows:
        print("No jobs to write to Google Sheets.")
        return

    url = _url_with_sheet(webhook_url, sheet_name)
    body = rows
    payload = json.dumps(body).encode("utf-8")

    if debug:
        print(f"POST {url}", file=sys.stderr)
        print(f"Body (first row): {json.dumps(rows[0]) if rows else '[]'}", file=sys.stderr)

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode("utf-8")
            if debug:
                print(f"Response status: {resp.status}", file=sys.stderr)
                print(f"Response body: {raw}", file=sys.stderr)
            try:
                result = json.loads(raw)
                if result.get('status') == 'error':
                    print(f"Webhook error: {result.get('message', 'unknown error')}", file=sys.stderr)
                    sys.exit(1)
                print(f"Wrote {result.get('rows_added', len(rows))} jobs to Google Sheet")
            except json.JSONDecodeError:
                print(f"Wrote {len(rows)} jobs to Google Sheet (response: {raw[:200]})")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        if debug:
            print(f"Response status: {e.code}", file=sys.stderr)
            print(f"Response body: {body}", file=sys.stderr)
        print(f"Webhook error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)


def fetch_rows(webhook_url: str, sheet_name: str | None = None) -> list:
    """GET the webhook to retrieve all rows from the sheet."""
    try:
        with urllib.request.urlopen(_url_with_sheet(webhook_url, sheet_name)) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"Error fetching rows: {e}", file=sys.stderr)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Save/load job search results to/from Google Sheets via webhook")
    parser.add_argument("--input", help="Path to JSON file to save")
    parser.add_argument("--load", nargs="?", const=True, metavar="PATH", help="Load existing rows from the sheet; optionally save to PATH instead of stdout")
    parser.add_argument("--webhook", required=True, metavar="URL", help="Google Apps Script webhook URL")
    parser.add_argument("--sheetName", metavar="NAME", help="Target sheet tab name (defaults to active sheet)")
    parser.add_argument("--debug", action="store_true", help="Print request URL and raw webhook response")
    args = parser.parse_args()

    sheet_name = getattr(args, 'sheetName', None)

    if args.load:
        data = fetch_rows(args.webhook, sheet_name)
        if isinstance(args.load, str):
            output_path = Path(args.load)
            output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"Saved {len(data)} rows to {output_path}")
        else:
            print(json.dumps(data, indent=2))
        return

    if not args.input:
        print("Error: --input is required when saving.", file=sys.stderr)
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    rows = load_rows(input_path)
    if not rows:
        print("No jobs found in input file.")
        return

    print(f"Found {len(rows)} jobs from {input_path}")
    post_rows(rows, args.webhook, sheet_name, debug=args.debug)


if __name__ == "__main__":
    main()
