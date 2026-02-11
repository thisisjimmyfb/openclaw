---
name: jobsearch
description: Scrape job listings from LinkedIn, Ashby, Greenhouse, and Google Careers. Save results to Google Sheets via Apps Script webhook.
---

## Required information — ask before running if missing

- `--keywords`: job title/terms (e.g. `"machine learning engineer"`)
- `--location`: geographic filter (e.g. `"US"`, `"New York"`)
- `--remote`: remote-only filter — pass exactly `True` or `False`
- `--webhook`: Google Apps Script web app URL (required for any Sheets operation)
- `--sheetName`: sheet tab name to read from or write to (ask the user; required when targeting a specific tab)

---

## Step 1 (optional): Load existing jobs from Google Sheets

Load already-saved job URLs from the sheet and write them to an exclusion file. Pass this file to Step 2 via `--exclude` so the scraper skips jobs already in the sheet.

```bash
# Save sheet rows to a local JSON file
python skills/jobsearch/scripts/save_job_to_sheets.py \
  --load "$HOME/seen_jobs.json" \
  --webhook "https://script.google.com/macros/s/YOUR_ID/exec" \
  --sheetName "Jobs"
```

---

## Step 2: Scrape jobs

Run `jobsearch.py`. Always use `--format json` when results will be saved to Sheets. Omit `--exclude` if you skipped Step 1.

```bash
python skills/jobsearch/scripts/jobsearch.py \
  --keywords "software engineer" \
  --location "US" \
  --remote True \
  --results_wanted 15 \
  --format json \
  --output "$HOME/jobs.json" \
  --exclude "$HOME/seen_jobs.json"
```

### All options

| Flag               | Required | Default            | Description                                                                                                             |
| ------------------ | -------- | ------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| `--keywords`       | yes      | —                  | Job title / search terms                                                                                                |
| `--location`       | yes      | —                  | Geographic filter (used for LinkedIn)                                                                                   |
| `--remote`         | yes      | —                  | `True` or `False` — remote-only filter                                                                                  |
| `--output`         | no       | prints to console  | Output file path                                                                                                        |
| `--format`         | no       | `csv`              | `csv` or `json`                                                                                                         |
| `--results_wanted` | no       | `20`               | Target results per job board                                                                                            |
| `--companies`      | no       | ~36 built-in slugs | Comma-separated Ashby/Greenhouse/Google company slugs                                                                   |
| `--exclude`        | no       | —                  | Path to exclusion file — text (one URL per line), JSON array of URL strings, or JSON array of rows (output of `--load`) |

---

## Step 3: Save jobs to Google Sheets

Upload the JSON output from Step 2 to the target sheet tab.

```bash
python skills/jobsearch/scripts/save_job_to_sheets.py \
  --input "$HOME/jobs.json" \
  --webhook "https://script.google.com/macros/s/YOUR_ID/exec" \
  --sheetName "Jobs"
```

```powershell
python skills\jobsearch\scripts\save_job_to_sheets.py `
  --input "$HOME\jobs.json" `
  --webhook "https://script.google.com/macros/s/YOUR_ID/exec" `
  --sheetName "Jobs"
```

### All options

| Flag          | Required   | Description                                                                 |
| ------------- | ---------- | --------------------------------------------------------------------------- |
| `--input`     | yes (save) | Path to JSON file to upload                                                 |
| `--load`      | —          | Switch to load mode (Step 1); optional PATH saves to file instead of stdout |
| `--webhook`   | yes        | Google Apps Script web app URL                                              |
| `--sheetName` | no         | Sheet tab name (defaults to active sheet)                                   |
| `--debug`     | no         | Print raw request/response for troubleshooting                              |

---

## Google Sheets setup (one-time)

No Google Cloud account or API credentials needed — paste a script into your sheet once.

### Step A: Create the Apps Script

1. Open your Google Sheet
2. Click **Extensions → Apps Script**
3. Delete any existing code and paste this:

```javascript
function doGet(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheetName = e.parameter?.sheetName;
    const sheet = sheetName ? ss.getSheetByName(sheetName) : ss.getActiveSheet();

    if (!sheet) {
      return ContentService.createTextOutput(JSON.stringify([])).setMimeType(
        ContentService.MimeType.JSON,
      );
    }

    const lastRow = sheet.getLastRow();
    const lastCol = sheet.getLastColumn();
    if (lastRow < 2 || lastCol < 1) {
      return ContentService.createTextOutput(JSON.stringify([])).setMimeType(
        ContentService.MimeType.JSON,
      );
    }

    const rows = sheet.getRange(2, 1, lastRow - 1, lastCol).getValues();

    return ContentService.createTextOutput(JSON.stringify(rows)).setMimeType(
      ContentService.MimeType.JSON,
    );
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({ error: err.message })).setMimeType(
      ContentService.MimeType.JSON,
    );
  }
}

function doPost(e) {
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const sheetName = e.parameter?.sheetName;
    let sheet = sheetName ? ss.getSheetByName(sheetName) : ss.getActiveSheet();
    if (!sheet && sheetName) {
      sheet = ss.insertSheet(sheetName);
    }

    let rows;
    try {
      rows = JSON.parse(e.postData?.contents);
      if (!Array.isArray(rows)) throw new Error("Expected array of rows in POST body");
    } catch (parseErr) {
      throw new Error("Invalid JSON payload: " + parseErr.message);
    }

    if (sheet.getLastRow() === 0) {
      sheet.appendRow([
        "Fit Score",
        "Source",
        "Date Posted",
        "Title",
        "Company",
        "Location",
        "Remote",
        "URL",
        "Date Scraped",
        "Salary",
        "Description",
      ]);
    }

    if (rows.length > 0) {
      const startRow = sheet.getLastRow() + 1;
      const colCount = rows[0].length;
      const paddedRows = rows.map((row) => {
        const padded = [...row];
        while (padded.length < colCount) padded.push("");
        return padded.slice(0, colCount);
      });
      sheet.getRange(startRow, 1, paddedRows.length, colCount).setValues(paddedRows);
    }

    const lastRow = sheet.getLastRow();
    if (lastRow > 1) {
      const dataRange = sheet.getRange(2, 1, lastRow - 1, sheet.getLastColumn());
      dataRange.sort([
        { column: 1, ascending: false }, // Fit Score
        { column: 7, ascending: false }, // Remote
        { column: 5, ascending: true }, // Company
        { column: 3, ascending: false }, // Date Posted
      ]);
    }

    return ContentService.createTextOutput(
      JSON.stringify({ status: "ok", rows_added: rows.length }),
    ).setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(
      JSON.stringify({ status: "error", message: err.message }),
    ).setMimeType(ContentService.MimeType.JSON);
  }
}
```

4. Click **Save** (name the project anything, e.g. `SheetsWebhook`)

### Step B: Deploy as Web App

1. Click **Deploy → New deployment**
2. Click the gear icon next to "Select type" → choose **Web app**
3. Set **Execute as:** Me and **Who has access:** Anyone
4. Click **Deploy** → authorize when prompted
5. Copy the **Web app URL** — it looks like:
   `https://script.google.com/macros/s/YOUR_DEPLOYMENT_ID/exec`

---

# Requirements

- Python 3.10+
- `pip install -r skills/jobsearch/requirements.txt`
