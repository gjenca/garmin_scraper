# garmin_scraper

Scrape a **public** Garmin Connect profile into a JSON or Excel document.

The profile page `https://connect.garmin.com/app/profile/<name>` is a single-page
app. The activity list is loaded by background API calls, and a **Show more**
button appends further pages. This tool drives a real headless browser
(Playwright), captures those JSON API responses directly (with a DOM-scraping
fallback), keeps clicking *Show more* / scrolling until everything is loaded, and
writes the result.

## Install

The package installs a `garmin-scraper` command. Playwright's browser binary is
**not** a Python package, so `playwright install chromium` is always a required
second step.

### As a tool (recommended)

```sh
pipx install git+https://github.com/gejza/garmin_scraper.git
pipx runpip garmin-scraper run playwright install chromium
```

### Into a virtualenv

```sh
python -m venv .venv
.venv/bin/pip install .            # or:  pip install git+https://github.com/gejza/garmin_scraper.git
.venv/bin/playwright install chromium
```

### For development

```sh
python -m venv .venv
.venv/bin/pip install -e .
.venv/bin/playwright install chromium
```

## Usage

Once installed, use the `garmin-scraper` command (equivalently
`python -m garmin_scraper`):

`PROFILE` below is the `<name>` from `connect.garmin.com/app/profile/<name>`.

```sh
# JSON (default) -> PROFILE.json
garmin-scraper PROFILE

# Excel -> PROFILE.xlsx  (sheet "activities" + sheet "profile")
garmin-scraper PROFILE --format xlsx

# Custom path (format inferred from extension), watch the browser
garmin-scraper PROFILE --out data/out.json --headful
```

Without installing, run the script directly: `python garmin_scraper.py PROFILE`
(needs `playwright` and `openpyxl` importable, e.g. via `requirements.txt`).

| Option         | Default | Meaning                                              |
| -------------- | ------- | ---------------------------------------------------- |
| `--format`     | inferred / `json` | `json` or `xlsx`                         |
| `--out`        | `<profile>.<ext>` | output file path                        |
| `--max-clicks` | `1000`  | safety cap on *Show more* clicks / scrolls          |
| `--timeout`    | `45`    | per-navigation timeout (seconds)                    |
| `--headful`    | off     | show the browser window (debugging)                 |

## Output

JSON shape:

```jsonc
{
  "profileName": "<name>",
  "profileUrl": "https://connect.garmin.com/app/profile/<name>",
  "profile": { /* social-profile fields Garmin returned, if any */ },
  "activityCount": 512,
  "activities": [
    { "activityId": 1234567890, "activityName": "...", "activityType": {...},
      "startTimeLocal": "2026-08-30 07:12:00", "distance": 5023.0,
      "duration": 1800.0, "elevationGain": 42.0, /* ... many more fields ... */ }
  ]
}
```

For `--format xlsx`, each activity is a flattened row (nested keys joined with
`.`, list values stored as JSON text) on the `activities` sheet; profile metadata
goes on the `profile` sheet.

## Notes

- Only **public** profiles work. If the profile's activities aren't public you'll
  get `activityCount: 0` and a warning — run with `--headful` to see the page.
- No Garmin login is used or required.
- Be polite: this hits Garmin's servers once per 10 activities.
- `requirements.txt` is kept for the plain-venv workflow; `pyproject.toml` is the
  source of truth for dependencies and the console entry point.
