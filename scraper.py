#!/usr/bin/env python3
"""AV Job Watcher — polls Greenhouse, Lever, and Ashby job boards for A1 /
audio / live-event engineering roles in the NYC metro area.

Reads companies.json, fetches each board, filters by title keywords and
location, then diffs against seen.json. Current matches go to matches.json
(for the dashboard); brand-new matches go to new_matches.json (the GitHub
Action opens one issue per new match).

Stdlib only — no dependencies to install.
"""
import datetime
import html
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent

TECH_RE = re.compile(
    r"engineer|\ba-?1\b|\bfoh\b|\bv-?1\b|technician|supervisor|specialist",
    re.IGNORECASE,
)
CONTEXT_RE = re.compile(
    r"audio|sound|\bav\b|audiovisual|broadcast|live event|\brf\b|"
    r"entertainment technology",
    re.IGNORECASE,
)
EXCLUDE_RE = re.compile(
    r"intern|sales|marketing|coordinator|general manager|director of operations",
    re.IGNORECASE,
)
LOCATION_RE = re.compile(
    r"new york|nyc|manhattan|brooklyn|queens|bronx|staten island|"
    r"new jersey|\bhudson\b|\bnj\b|hoboken|jersey city|secaucus|white plains|"
    r"edison|parsippany|remote",
    re.IGNORECASE,
)

GH_API = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
LEVER_API = "https://api.lever.co/v0/postings/{board}?mode=json"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{board}"


def fetch_json(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": "av-job-watcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code} for {url}", file=sys.stderr)
    except Exception as e:  # network hiccups, bad JSON, etc.
        print(f"  error fetching {url}: {e}", file=sys.stderr)
    return None


def fetch_greenhouse(board):
    data = fetch_json(GH_API.format(board=board))
    if not data:
        return []
    jobs = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        jobs.append(
            {
                "key": f"gh:{board}:{j['id']}",
                "title": j.get("title", ""),
                "company_board": board,
                "location": loc,
                "url": j.get("absolute_url", ""),
            }
        )
    return jobs


def fetch_lever(board):
    data = fetch_json(LEVER_API.format(board=board))
    if not data:
        return []
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        loc = cats.get("location", "") or ""
        if isinstance(loc, list):
            loc = ", ".join(loc)
        jobs.append(
            {
                "key": f"lv:{board}:{j['id']}",
                "title": j.get("text", ""),
                "company_board": board,
                "location": loc,
                "url": j.get("hostedUrl") or j.get("applyUrl", ""),
                "description": j.get("description") or j.get("descriptionHtml") or "",
            }
        )
    return jobs


def fetch_ashby(board):
    data = fetch_json(ASHBY_API.format(board=board))
    if not data:
        return []
    jobs = []
    for j in data.get("jobs", []):
        loc = j.get("location") or ""
        for extra in j.get("secondaryLocations") or []:
            name = extra.get("location") if isinstance(extra, dict) else extra
            if name and name not in loc:
                loc = f"{loc}; {name}" if loc else name
        jobs.append(
            {
                "key": f"ab:{board}:{j.get('id')}",
                "title": j.get("title", ""),
                "company_board": board,
                "location": loc,
                "url": j.get("jobUrl", ""),
                "description": j.get("descriptionHtml")
                or j.get("descriptionPlain")
                or "",
                # Ashby often publishes a comp summary separately.
                "pay_hint": j.get("compensationTierSummary") or "",
            }
        )
    return jobs


def fetch_greenhouse_detail(board, job_id):
    """Full posting (with description HTML) for one Greenhouse job."""
    data = fetch_json(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
        "?questions=true"
    )
    return (data or {}).get("content", "")


def extract_pay(content_html):
    """Pull a pay snippet like '$55/hour ...' or '$80,000 - $90,000'
    from a job description. Returns None when no pay is listed."""
    if not content_html:
        return None
    # Unescape repeatedly: some boards double-encode entities (&amp;nbsp;)
    text, prev = content_html, None
    while text != prev:
        prev, text = text, html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    def clean(val):
        # Cut off when the next labeled field begins ("... Location: NYC")
        val = re.split(r"\s+[A-Z][A-Za-z]*\s*:", val, maxsplit=1)[0]
        return val.strip(" -\u2013\u2014")[:160].strip()

    # "Salary Min: $80,000  Salary Max: $90,000" style
    m = re.search(
        r"(?i)salary\s*min\s*:\s*(\$[\d,]+(?:\.\d{2})?)"
        r"\s*salary\s*max\s*:\s*(\$[\d,]+(?:\.\d{2})?)",
        text,
    )
    if m:
        return f"{m.group(1)} - {m.group(2)}"
    # Labeled pay lines: Rate: / Salary: / Pay: / Compensation:
    m = re.search(
        r"(?i)\b(pay\s*rate|hourly\s*rate|rate|salary|compensation|pay\s*range|pay)"
        r"\s*:\s*([^.]{3,160})",
        text,
    )
    if m:
        val = clean(m.group(2))
        if "$" in val or re.search(r"\d", val):
            return val
    # Fallback: $ amount (with optional range) + time unit, or a bare $ range
    m = re.search(
        r"\$[\d,]+(?:\.\d{2})?(?:\s*[-\u2013\u2014]\s*\$?[\d,]+(?:\.\d{2})?)?\+?"
        r"\s*(?:/\s*|per\s+)?(hour|hr|year|yr|week|day|month|annual(?:ly)?)",
        text,
        re.I,
    )
    if m:
        return m.group(0).strip()
    m = re.search(
        r"\$[\d,]+(?:\.\d{2})?\s*[-\u2013\u2014]\s*\$[\d,]+(?:\.\d{2})?",
        text,
    )
    if m:
        return m.group(0).strip()
    return None


def is_match(job):
    title = job["title"] or ""
    if EXCLUDE_RE.search(title):
        return False
    if not TECH_RE.search(title):
        return False
    if not CONTEXT_RE.search(title):
        return False
    loc = job["location"] or ""
    return bool(LOCATION_RE.search(loc))


def main():
    companies = json.loads((BASE / "companies.json").read_text())
    seen_path = BASE / "seen.json"
    seen = json.loads(seen_path.read_text()) if seen_path.exists() else {}

    board_names = {}
    all_jobs = []
    for c in companies:
        name, platform, board = c["name"], c["platform"], c["board"]
        board_names[f"{platform}:{board}"] = name
        print(f"Fetching {name} ({platform}:{board})...")
        if platform == "greenhouse":
            all_jobs.extend(fetch_greenhouse(board))
        elif platform == "lever":
            all_jobs.extend(fetch_lever(board))
        elif platform == "ashby":
            all_jobs.extend(fetch_ashby(board))
        else:
            print(f"  unknown platform {platform}", file=sys.stderr)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    matches, new_matches = [], []
    platform_for_prefix = {"gh": "greenhouse", "lv": "lever", "ab": "ashby"}
    for job in all_jobs:
        if not is_match(job):
            continue
        prefix, _, rest = job["key"].partition(":")
        board = rest.split(":")[0]
        platform = platform_for_prefix.get(prefix, prefix)
        job["company"] = board_names.get(
            f"{platform}:{board}", job["company_board"]
        )
        job["scraped_at"] = now
        # Pay lives in the full posting description; fetch it for each match.
        # Ashby boards sometimes carry a comp summary on the listing itself.
        pay = job.pop("pay_hint", None) or None
        if prefix == "gh":
            job_id = rest.split(":")[1]
            pay = pay or extract_pay(fetch_greenhouse_detail(board, job_id))
        elif job.get("description"):
            pay = pay or extract_pay(job["description"])
        job["pay"] = pay
        if job["key"] not in seen:
            job["first_seen"] = now
            new_matches.append(job)
        else:
            job["first_seen"] = seen[job["key"]].get("first_seen", now)
        seen[job["key"]] = {
            "title": job["title"],
            "company": job["company"],
            "url": job["url"],
            "first_seen": job["first_seen"],
        }
        matches.append(job)

    matches.sort(key=lambda m: (m["company"].lower(), m["title"].lower()))
    (BASE / "seen.json").write_text(json.dumps(seen, indent=2) + "\n")
    (BASE / "matches.json").write_text(
        json.dumps(
            {"scraped_at": now, "count": len(matches), "matches": matches}, indent=2
        )
        + "\n"
    )
    (BASE / "new_matches.json").write_text(json.dumps(new_matches, indent=2) + "\n")

    print(f"\n{len(all_jobs)} jobs scanned, {len(matches)} matches, "
          f"{len(new_matches)} new.")
    for m in new_matches:
        print(f"  NEW: {m['company']} — {m['title']} ({m['location']})")


if __name__ == "__main__":
    main()
