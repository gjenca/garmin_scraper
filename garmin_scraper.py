#!/usr/bin/env python3
"""Scrape a public Garmin Connect profile into a JSON or Excel document.

The Garmin Connect profile page (https://connect.garmin.com/app/profile/<name>)
is a single-page app: the activity list is loaded by background XHR/fetch calls
and a "Show more" button appends further pages. This scraper drives a real
browser with Playwright, captures those JSON API responses directly (falling
back to DOM scraping if none are seen), keeps clicking "Show more" / scrolling
until everything is loaded, and writes the result out.

Usage
-----
    python garmin_scraper.py PROFILE
    python garmin_scraper.py PROFILE --format xlsx
    python garmin_scraper.py PROFILE --out data/out.json --headful
    python garmin_scraper.py PROFILE --max-clicks 500 --timeout 45

First-time setup
----------------
    pip install -r requirements.txt
    playwright install chromium
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
except ImportError:  # pragma: no cover - guidance only
    sys.exit(
        "Playwright is not installed.\n"
        "  pip install -r requirements.txt\n"
        "  playwright install chromium"
    )

PROFILE_URL = "https://connect.garmin.com/app/profile/{name}"

# Substrings identifying the background responses we want to harvest.
ACTIVITY_URL_HINTS = ("activitylist-service", "/activities/search")
PROFILE_URL_HINTS = (
    "userprofile-service/socialProfile",
    "profile-service/socialProfile",
    "userprofile-service/userprofile/public-profile",
)

# Things that look like a "load more" control, tried in order.
LOAD_MORE_SELECTORS = (
    "button:has-text('Show More')",
    "button:has-text('Show more')",
    "button:has-text('Load More')",
    "button:has-text('Load more')",
    "button:has-text('More')",
    "[class*='showMore'] button",
    "button[class*='showMore']",
    "button[class*='show-more']",
    "button[class*='load-more']",
    "a[class*='load-more']",
)

# Cookie / consent banners that can intercept clicks.
CONSENT_SELECTORS = (
    "#truste-consent-button",
    "button#onetrust-accept-btn-handler",
    "button:has-text('Accept All')",
    "button:has-text('Accept all')",
    "button:has-text('I Accept')",
    "button:has-text('Agree')",
    "button:has-text('Got it')",
)


def eprint(*args: Any) -> None:
    print(*args, file=sys.stderr, flush=True)


def as_activity_items(payload: Any) -> list[dict]:
    """Pull a list of activity dicts out of whatever shape Garmin returned."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("activityList", "activities", "results"):
            val = payload.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


def activity_key(item: dict) -> Any:
    return (
        item.get("activityId")
        or item.get("activityUUID")
        or item.get("uuidMsg")
        or json.dumps(item, sort_keys=True, default=str)
    )


def dismiss_consent(page) -> None:
    for sel in CONSENT_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def find_load_more(page):
    for sel in LOAD_MORE_SELECTORS:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible() and loc.is_enabled():
                return loc
        except Exception:
            continue
    return None


DOM_EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('a[href*="/activity/"]').forEach(a => {
    const m = (a.getAttribute('href') || '').match(/activity\/(\d+)/);
    if (!m) return;
    const id = m[1];
    if (seen.has(id)) return;
    seen.add(id);
    const row = a.closest('li, tr, article, [class*="activity"]') || a.parentElement;
    out.push({
      activityId: Number(id),
      activityName: (a.textContent || '').trim(),
      url: a.href,
      rowText: row ? (row.innerText || '').replace(/\s+/g, ' ').trim() : ''
    });
  });
  return out;
}
"""


def scrape(name: str, headful: bool, max_clicks: int, timeout_s: int) -> dict:
    timeout_ms = timeout_s * 1000
    activities: dict[Any, dict] = {}
    profile: dict[str, Any] = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headful)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            viewport={"width": 1400, "height": 1000},
        )
        page = context.new_page()

        def on_response(resp) -> None:
            url = resp.url
            try:
                if any(h in url for h in ACTIVITY_URL_HINTS):
                    items = as_activity_items(resp.json())
                    for it in items:
                        activities[activity_key(it)] = it
                    if items:
                        eprint(f"  captured {len(items):>4} activities  ({len(activities)} total)")
                elif any(h in url for h in PROFILE_URL_HINTS):
                    body = resp.json()
                    if isinstance(body, dict):
                        profile.update(body)
            except Exception:
                pass  # non-JSON body, request aborted, etc.

        page.on("response", on_response)

        url = PROFILE_URL.format(name=name)
        eprint(f"Opening {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(4000)  # let the SPA fire its first API calls
        dismiss_consent(page)

        stagnant = 0
        for i in range(max_clicks):
            before = len(activities)
            btn = find_load_more(page)
            if btn is not None:
                try:
                    btn.scroll_into_view_if_needed(timeout=3000)
                    btn.click(timeout=3000)
                except Exception:
                    page.mouse.wheel(0, 6000)
            else:
                page.mouse.wheel(0, 6000)

            try:
                page.wait_for_load_state("networkidle", timeout=3500)
            except PlaywrightTimeoutError:
                pass  # Garmin keeps analytics sockets open; idle rarely fires
            page.wait_for_timeout(1200)

            gained = len(activities) - before
            stagnant = stagnant + 1 if gained == 0 else 0
            if stagnant == 1 and btn is None:
                dismiss_consent(page)
            if stagnant >= 5:
                eprint("No new activities after several attempts - stopping.")
                break
        else:
            eprint(f"Reached --max-clicks ({max_clicks}); there may be more data.")

        if not activities:
            eprint("No API responses captured; falling back to DOM scraping.")
            for row in page.evaluate(DOM_EXTRACT_JS):
                activities[row["activityId"]] = row

        if not profile:
            profile = {"profileName": name, "profileUrl": url}

        context.close()
        browser.close()

    items = list(activities.values())
    items.sort(
        key=lambda a: str(
            a.get("startTimeLocal") or a.get("startTimeGMT") or a.get("activityId") or ""
        ),
        reverse=True,
    )
    return {
        "profileName": name,
        "profileUrl": PROFILE_URL.format(name=name),
        "profile": profile,
        "activityCount": len(items),
        "activities": items,
    }


def flatten(d: dict, parent: str = "", sep: str = ".") -> dict:
    out: dict[str, Any] = {}
    for k, v in d.items():
        nk = f"{parent}{sep}{k}" if parent else str(k)
        if isinstance(v, dict):
            out.update(flatten(v, nk, sep))
        else:
            out[nk] = v
    return out


def write_json(path: Path, result: dict) -> None:
    path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


_ILLEGAL_XLSX = {c: None for c in list(range(0x00, 0x09)) + [0x0B, 0x0C] + list(range(0x0E, 0x20))}


def _xlsx_safe(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, str):
        return value.translate(_ILLEGAL_XLSX)
    return value


def write_xlsx(path: Path, result: dict) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        sys.exit("openpyxl is required for --format xlsx:  pip install openpyxl")

    wb = Workbook()

    ws = wb.active
    ws.title = "activities"
    rows = [flatten(a) for a in result["activities"]]
    columns: list[str] = []
    for r in rows:
        for k in r:
            if k not in columns:
                columns.append(k)
    ws.append([_xlsx_safe(c) for c in columns])
    for r in rows:
        ws.append([_xlsx_safe(r.get(c)) for c in columns])

    ps = wb.create_sheet("profile")
    ps.append(["field", "value"])
    meta = {k: v for k, v in result.items() if k != "activities"}
    for k, v in flatten(meta).items():
        ps.append([k, _xlsx_safe(v)])

    wb.save(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape a public Garmin Connect profile to JSON or Excel."
    )
    parser.add_argument(
        "profile",
        help="Garmin Connect profile name (the <name> in "
        "connect.garmin.com/app/profile/<name>).",
    )
    parser.add_argument(
        "--format",
        choices=("json", "xlsx"),
        help="Output format (default: inferred from --out, else json).",
    )
    parser.add_argument("--out", type=Path, help="Output file path.")
    parser.add_argument(
        "--max-clicks",
        type=int,
        default=1000,
        help="Safety cap on 'Show more' clicks / scrolls (default: 1000).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="Per-navigation timeout in seconds (default: 45).",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Show the browser window (useful for debugging).",
    )
    args = parser.parse_args(argv)

    fmt = args.format
    if fmt is None and args.out is not None:
        fmt = "xlsx" if args.out.suffix.lower() in (".xlsx", ".xlsm") else "json"
    fmt = fmt or "json"

    out = args.out or Path(f"{args.profile}.{'xlsx' if fmt == 'xlsx' else 'json'}")
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)

    result = scrape(args.profile, args.headful, args.max_clicks, args.timeout)

    if result["activityCount"] == 0:
        eprint(
            "\nWarning: 0 activities collected. The profile may be private, the "
            "name may be wrong, or Garmin changed its page. Try --headful to watch."
        )

    if fmt == "xlsx":
        write_xlsx(out, result)
    else:
        write_json(out, result)

    eprint(f"\nWrote {result['activityCount']} activities -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
