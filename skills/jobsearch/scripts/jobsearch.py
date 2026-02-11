#!/usr/bin/env python3
"""Job search scraper using jobspy, Ashby, and Greenhouse."""

import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

try:
    from jobspy import scrape_jobs
except ImportError:
    print("jobspy not installed. Attempting to install...", file=sys.stderr)
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "python-jobspy", "-q"])
        from jobspy import scrape_jobs
    except Exception as e:
        print(f"Error: Failed to install jobspy. Run: pip install python-jobspy", file=sys.stderr)
        sys.exit(1)


SHEET_HEADERS = ["Fit Score", "Source", "Date Posted", "Title", "Company", "Location", "Remote", "URL", "Date Scraped", "Salary", "Description"]
URL_COL      = SHEET_HEADERS.index("URL")
LOCATION_COL = SHEET_HEADERS.index("Location")

# Known software engineering companies on Ashby or Greenhouse.
# The script tries Ashby, Greenhouse, and Google per slug and skips 404s automatically.
DEFAULT_COMPANIES = [
    # Ashby
    "anthropic", "brex", "cohere", "cursor", "linear", "mercury",
    "mistral", "notion", "perplexity", "ramp", "replit", "retool",
    "rippling", "scaleai", "supabase", "vercel",
    # Greenhouse
    "airbnb", "cloudflare", "coinbase", "databricks", "datadog",
    "doordash", "dropbox", "elastic", "figma", "hashicorp",
    "hubspot", "lyft", "mongodb", "nvidia", "pinterest", "reddit",
    "robinhood", "snowflake", "stripe", "twilio", "zendesk",
    # Google Careers
    "google",
]


def format_job(job: dict) -> str:
    lines = [
        f"  Source: {job['source']}",
        f"  Title: {job['title']}",
        f"  Company: {job['company']}",
        f"  Location: {job['location']}",
        f"  Salary: {job['salary']}",
        f"  Date Posted: {job.get('date_posted', 'N/A')}",
        f"  URL: {job['job_url']}",
        f"  Description: {job['description'][:150]}..."
    ]
    return "\n".join(lines)


def jobs_to_rows(jobs) -> list[list]:
    """Convert a jobspy DataFrame to a list of rows (no header)."""
    try:
        import pandas as pd
        if isinstance(jobs, pd.DataFrame):
            rows = []
            for _, row in jobs.iterrows():
                compensation = row.get('compensation', {})
                min_amount = compensation.get('min_amount', '?') if isinstance(compensation, dict) else '?'
                max_amount = compensation.get('max_amount', '?') if isinstance(compensation, dict) else '?'
                location_str = str(row.get('location', ''))
                location_lower = location_str.lower()
                is_remote = bool(row.get('is_remote')) or any(kw in location_lower for kw in ("remote", "anywhere", "work from home", "wfh"))
                rows.append([
                    "",
                    str(row.get('site_name', '')),
                    str(row.get('date_posted', '')),
                    str(row.get('title', '')),
                    str(row.get('company', '')),
                    location_str,
                    is_remote,
                    str(row.get('job_url', '')),
                    date.today().isoformat(),
                    f"{min_amount} - {max_amount}",
                    str(row.get('description', ''))[:500],
                ])
            return rows
    except ImportError:
        pass
    return []


def _keywords_match(text: str, keywords_lower: list[str]) -> bool:
    """Return True if any keyword appears in text (case-insensitive)."""
    return not keywords_lower or any(kw in text.lower() for kw in keywords_lower)


def scrape_ashby(slug: str, keywords_lower: list[str]) -> list[list]:
    url = f"https://api.ashbyhq.com/posting-api/job-board?organizationHostedJobsPageName={slug}"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    postings = data.get("jobPostings", [])
    rows = []
    for job in postings:
        title = job.get("title", "")
        description = job.get("descriptionPlain", "") or ""
        if not _keywords_match(title + " " + description, keywords_lower):
            continue
        is_remote = bool(job.get("isRemote"))
        location = "Remote" if is_remote else (job.get("locationName", "") or job.get("location", ""))
        job_url = job.get("jobUrl", "") or f"https://jobs.ashbyhq.com/{slug}/{job.get('id', '')}"
        rows.append([
            "",
            "ashby",
            job.get("publishedDate", ""),
            title,
            job.get("organizationName", slug),
            location,
            is_remote,
            job_url,
            date.today().isoformat(),
            "",
            description[:500],
        ])
    return rows


def scrape_greenhouse(slug: str, keywords_lower: list[str]) -> list[list]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    jobs = data.get("jobs", [])
    rows = []
    for job in jobs:
        title = job.get("title", "")
        raw_content = job.get("content", "") or ""
        description = re.sub(r"<[^>]+>", " ", raw_content).strip()
        if not _keywords_match(title + " " + description, keywords_lower):
            continue
        location = (job.get("location") or {}).get("name", "")
        job_url = job.get("absolute_url", "")
        posted_at = (job.get("updated_at") or "")[:10]
        company_name = job.get("company", {}).get("name", slug) if isinstance(job.get("company"), dict) else slug
        rows.append([
            "",
            "greenhouse",
            posted_at,
            title,
            company_name,
            location,
            "remote" in location.lower(),
            job_url,
            date.today().isoformat(),
            "",
            description[:500],
        ])
    return rows


def load_excluded_urls(path: str) -> set[str]:
    """Load a set of job URLs to exclude from a text file (one per line) or JSON list."""
    p = Path(path)
    if not p.exists():
        print(f"Warning: exclude file '{path}' not found.", file=sys.stderr)
        return set()
    text = p.read_text(encoding="utf-8").strip()
    if p.suffix.lower() == ".json":
        data = json.loads(text)
        if data and isinstance(data[0], list):
            url_col = next((i for i, cell in enumerate(data[0]) if str(cell).startswith("http")), URL_COL)
            return {row[url_col] for row in data if len(row) > url_col and row[url_col]}
        return set(data)
    return {line.strip() for line in text.splitlines() if line.strip()}


def scrape_companies(
    company_slugs: list[str],
    keywords: str,
    location: str = "",
    is_remote: bool = False,
    target: int = 0,
    excluded_urls: set[str] = frozenset(),
) -> list[list]:
    """Try each slug against both Ashby and Greenhouse; silently skip if not found on a platform.

    Filters rows by is_remote, location, and excluded_urls, and stops once target rows are
    collected (0 = no limit). Excluded jobs are skipped and do not count toward the target,
    so the search continues until the target is met or all companies are exhausted.
    """
    keywords_lower = keywords.lower().split() if keywords else []
    location_lower = location.lower() if location else ""
    rows: list[list] = []
    seen_urls: set[str] = set()

    def _matches_filters(row: list) -> bool:
        url = row[URL_COL]
        if url in excluded_urls:
            return False
        if url in seen_urls:
            return False
        job_location = row[LOCATION_COL].lower()
        if is_remote and "remote" not in job_location:
            return False
        if location_lower and location_lower not in job_location:
            return False
        return True

    for slug in company_slugs:
        if target and len(rows) >= target:
            break
        slug = slug.strip()
        for platform, fn in [("Ashby", scrape_ashby), ("Greenhouse", scrape_greenhouse), ("Google", scrape_google)]:
            if target and len(rows) >= target:
                break
            try:
                found = fn(slug, keywords_lower)
                filtered = [r for r in found if _matches_filters(r)]
                if filtered:
                    if target:
                        remaining = target - len(rows)
                        filtered = filtered[:remaining]
                    print(f"  {platform}/{slug}: {len(filtered)} matching jobs.")
                    for r in filtered:
                        seen_urls.add(r[URL_COL])
                    rows.extend(filtered)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    pass  # company not on this platform
                else:
                    print(f"  {platform}/{slug}: HTTP {e.code} — skipping.", file=sys.stderr)
            except Exception as e:
                print(f"  {platform}/{slug}: {e} — skipping.", file=sys.stderr)
    return rows


def scrape_google(slug: str, keywords_lower: list[str]) -> list[list]:
    """Scrape Google Careers via their public JSON search API. Only runs for slug 'google'."""
    if slug.lower() != "google":
        return []
    params = urllib.parse.urlencode({
        "q": " ".join(keywords_lower),
        "page_size": 100,
        "hl": "en_US",
    })
    url = f"https://careers.google.com/api/jobs/jobs-v1/search/?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    rows = []
    for job in data.get("jobs") or []:
        title = job.get("title", "")
        summary_html = job.get("summary", "") or ""
        description = re.sub(r"<[^>]+>", " ", summary_html).strip()
        if not _keywords_match(title + " " + description, keywords_lower):
            continue
        locations = job.get("locations") or []
        job_location = ", ".join(locations) if locations else ""
        job_url = job.get("apply_url", "")
        if not job_url:
            continue
        published = (job.get("publish_date") or {}).get("seconds")
        date_posted = ""
        if published:
            from datetime import datetime, timezone
            date_posted = datetime.fromtimestamp(int(published), tz=timezone.utc).strftime("%Y-%m-%d")
        rows.append([
            "",
            "google",
            date_posted,
            title,
            job.get("company_name", "Google"),
            job_location,
            "remote" in job_location.lower(),
            job_url,
            date.today().isoformat(),
            "",
            description[:500],
        ])
    return rows


def scrape_linkedin(
    keywords: str,
    location: str,
    is_remote: bool,
    target: int,
    excluded_urls: set[str] = frozenset(),
) -> list[list]:
    """Scrape LinkedIn jobs, returning deduplicated, non-excluded results up to target count.

    Excluded jobs are skipped and do not count toward the target, so the search retries
    with larger batches until the target is met or retries are exhausted.
    """
    seen_urls: set[str] = set()
    linkedin_rows: list[list] = []

    for attempt, batch_size in enumerate([target, target * 2, target * 3], start=1):
        still_needed = target - len(linkedin_rows)
        if still_needed <= 0:
            break
        print(f"Scraping LinkedIn batch {attempt}: requesting {batch_size} jobs ({still_needed} still needed)...")

        jobs = scrape_jobs(
            site_name=["linkedin"],
            search_term=keywords,
            location=location,
            is_remote=is_remote,
            job_type="fulltime",
            results_wanted=batch_size,
            hours_old=72,
            linkedin_fetch_description=True,
            description_format="markdown",
            verbose=0,
        )

        rows = jobs_to_rows(jobs)
        if not rows:
            print("No results returned from LinkedIn.", file=sys.stderr)
            break

        for row in rows:
            url = row[URL_COL]
            if url and url not in seen_urls and url not in excluded_urls:
                seen_urls.add(url)
                linkedin_rows.append(row)

        print(f"  LinkedIn total so far: {len(linkedin_rows)}/{target}")

        if len(linkedin_rows) >= target:
            break

    return linkedin_rows[:target]


def write_rows_csv(rows: list[list], output_path: Path) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(SHEET_HEADERS)
        writer.writerows(rows)
    print(f"Saved {len(rows)} jobs to {output_path}")


def write_rows_json(rows: list[list], output_path: Path) -> None:
    data = [dict(zip(SHEET_HEADERS, row)) for row in rows]
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(rows)} jobs to {output_path}")


def print_rows(rows: list[list]) -> None:
    print(f"\n{len(rows)} new jobs found:")
    for row in rows:
        job = dict(zip(["source", "date_posted", "title", "company", "location", "is_remote", "job_url", "date_scraped", "salary", "description"], row))
        print("\n" + format_job(job))


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description="Search jobs from LinkedIn, Ashby, Greenhouse, and Google Careers")
    parser.add_argument("--keywords", required=True, help="Job keywords to search")
    parser.add_argument("--location", required=True, help="Job location (used for LinkedIn)")
    parser.add_argument("--remote", type=bool, default=False, help="Filter for remote jobs only (LinkedIn)")
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format (default: csv)")
    parser.add_argument("--results_wanted", type=int, default=20, help="Target number of LinkedIn jobs (default: 20)")
    parser.add_argument("--companies", help="Comma-separated company slugs for Ashby/Greenhouse (default: built-in list of ~36 companies)")
    parser.add_argument("--exclude", help="Path to a file of job URLs to exclude (text file with one URL per line, or a JSON list). Excluded jobs are skipped and the scraper keeps searching until the target count is met.")

    args = parser.parse_args()

    excluded_urls: set[str] = load_excluded_urls(args.exclude) if args.exclude else set()
    if excluded_urls:
        print(f"Loaded {len(excluded_urls)} excluded job URLs.")

    slugs = [s.strip() for s in args.companies.split(",") if s.strip()] if args.companies else DEFAULT_COMPANIES

    print(f"Scraping Ashby and Greenhouse for {len(slugs)} companies...")
    company_rows = scrape_companies(
        company_slugs=slugs,
        keywords=args.keywords,
        location=args.location,
        is_remote=args.remote,
        target=args.results_wanted,
        excluded_urls=excluded_urls,
    )

    print(f"Scraping LinkedIn...")
    linkedin_rows = scrape_linkedin(
        keywords=args.keywords,
        location=args.location,
        is_remote=args.remote,
        target=args.results_wanted,
        excluded_urls=excluded_urls,
    )

    seen_urls: set[str] = set()
    all_rows: list[list] = []
    for row in company_rows + linkedin_rows:
        url = row[URL_COL]
        if url and url not in seen_urls:
            seen_urls.add(url)
            all_rows.append(row)

    if not all_rows:
        print("No jobs found.")
        return

    print_rows(all_rows)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if args.format == "csv":
            write_rows_csv(all_rows, output_path)
        else:
            write_rows_json(all_rows, output_path)


if __name__ == "__main__":
    main()
