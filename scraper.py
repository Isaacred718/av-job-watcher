#!/usr/bin/env python3
"""AV Job Watcher — polls Greenhouse and Lever job boards for A1 / audio /
live-event engineering roles in the NYC metro area.

Reads companies.json, fetches each board, filters by title keywords and
location, then diffs against seen.json. Current matches go to matches.json
(for the dashboard); brand-new matches go to new_matches.json (the GitHub
Action opens one issue per new match).

Stdlib only — no dependencies to install.
"""
import datetime
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
            }
        )
    return jobs


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
        else:
            print(f"  unknown platform {platform}", file=sys.stderr)

    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    matches, new_matches = [], []
    for job in all_jobs:
        if not is_match(job):
            continue
        job["company"] = board_names.get(
            f"{job['key'].split(':')[0]}:{job['company_board']}", job["company_board"]
        )
        job["scraped_at"] = now
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
