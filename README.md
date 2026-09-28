# AV Job Watcher

Watches the public job boards (Greenhouse, Lever, and Ashby APIs) of NYC-area AV, production,
hospitality, and live-events companies for A1 / audio / live-event engineering roles,
and pings me when new ones post.

## How it works

1. **Scrape** — a scheduled GitHub Action (`.github/workflows/watch.yml`) runs
   `scraper.py` twice daily (~8:07 AM and ~6:07 PM Eastern).
2. **Match** — postings are filtered by title keywords (A1, FOH, audio engineer,
   sound engineer, AV engineer, broadcast engineer, live events, …) and NYC-metro
   location. Matches are compared against `seen.json` so only *new* postings alert.
3. **Notify** — each new match opens a GitHub issue labeled `new-match`, which
   sends an email + push notification. Close the issue once you've applied or
   ruled it out.
4. **Dashboard** — `index.html` (GitHub Pages) shows all currently live matches
   with a filter box.

## Add or remove a company

Edit `companies.json`:

```json
{ "name": "Company Name", "platform": "greenhouse", "board": "board-token" }
```

- `platform` is `greenhouse`, `lever`, or `ashby`.
- `board` is the token in the company's public job-board URL:
  `job-boards.greenhouse.io/<board>`, `jobs.lever.co/<board>`, or `jobs.ashbyhq.com/<board>`.

No code changes needed — the next scheduled run picks it up.

## Files

| File | Purpose |
|---|---|
| `scraper.py` | Board polling, keyword/location matching, state diffing (stdlib only) |
| `companies.json` | Watched company boards |
| `seen.json` | Every match ever seen (prevents repeat alerts) |
| `matches.json` | Currently live matches (powers the dashboard) |
| `new_matches.json` | Matches found on the latest run (used by the Action) |
| `index.html` | Dashboard (GitHub Pages) |
