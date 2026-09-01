# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file CLI (`garmin_scraper.py`) that exports a **public** Garmin Connect
profile's activity history to JSON or Excel.

## Commands

```sh
# One-time setup (Arch/PEP-668 blocks system pip, so a venv is required)
python -m venv .venv
.venv/bin/pip install -e .                    # console script: garmin-scraper
.venv/bin/playwright install chromium         # downloads headless Chromium; not a pip dep

# Run (any of these are equivalent)
.venv/bin/garmin-scraper <profile>                 # -> <profile>.json
.venv/bin/python -m garmin_scraper <profile> --format xlsx
.venv/bin/python garmin_scraper.py <profile> --headful
```

`pyproject.toml` (flat single-module layout, `py-modules = ["garmin_scraper"]`)
is the source of truth for deps and the `garmin-scraper = "garmin_scraper:main"`
entry point. `requirements.txt` is kept only for the no-install script workflow.

Debug flags: `--max-clicks N` (cap pagination), `--timeout S`, `--headful`.

There is no build, lint, or test suite. `python -m py_compile garmin_scraper.py`
is the only static check. Verify changes by running against any public profile.
A full run takes a few minutes — roughly one API round-trip per 10 activities —
so during iteration cap it with `--max-clicks 3`.

## Architecture

The profile page (`connect.garmin.com/app/profile/<name>`) is a React SPA; a
plain HTTP GET returns no data. The scraper is built around one key idea:

**Drive a real browser, but harvest the SPA's own API responses rather than
scraping the DOM.** Flow in `scrape()`:

1. Playwright (sync API) launches headless Chromium and navigates to the profile.
2. A `page.on("response")` handler inspects every response. URLs containing
   `activitylist-service` / `/activities/search` are parsed as JSON and their
   activity dicts accumulated in a dict keyed by `activity_key()` (dedupes across
   overlapping pages). URLs matching `PROFILE_URL_HINTS` fill the `profile` dict.
   `as_activity_items()` normalizes the several response shapes Garmin uses
   (bare list, `{activityList: [...]}`, etc.).
3. A loop clicks the "Show more" control (`find_load_more()` tries many
   selectors) or scrolls if none is found, dismissing cookie banners
   (`dismiss_consent()`), until 5 consecutive iterations add no new activities.
4. If zero API responses were captured, `DOM_EXTRACT_JS` is the fallback: pull
   `activityId`s from `a[href*="/activity/"]` links.

Output: `write_json()` dumps the whole result; `write_xlsx()` uses `flatten()`
(dot-joined nested keys, lists → JSON strings) so each activity is one row on an
`activities` sheet, with metadata on a `profile` sheet. `_xlsx_safe()` strips
control chars openpyxl rejects.

## When Garmin changes their site

The fragile points, in order of likelihood: the `activitylist-service` URL
substring (`ACTIVITY_URL_HINTS`), the "Show more" selectors
(`LOAD_MORE_SELECTORS`), and the consent-banner selectors. Run with `--headful`
to see what the page is actually doing. Only public profiles work; a private one
yields `activityCount: 0` and a warning, which is expected behavior, not a bug.
