# Google Scholar BibTeX Scraper

`scholar_scraper.py` is a small Selenium script that searches Google Scholar for
paper titles and saves first-result BibTeX entries to a local bibliography file.

It is meant for small, careful batches. Google Scholar is not a public scraping
API, and the script does not bypass captchas or temporary traffic blocks.

Last verified working: `2026-05-28 00:34:30 -07:00`

If something does not work, message `@pat_pat.` on Discord.

## Quick Setup

```powershell
uv --version
uv run scholar_scraper.py --help
uv run scholar_scraper.py
```

If `uv --version` fails, install `uv` first.

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS/Linux:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then reopen your terminal and run:

```powershell
uv run scholar_scraper.py --limit 3 --delay 6 --timeout 40
```

## What It Does

- Reads one Google Scholar search per line from `queries.txt`.
- Opens a visible supported browser with Selenium.
- Searches Google Scholar.
- Uses the first result by default.
- Clicks **Cite**, then **BibTeX**.
- Reads the BibTeX entry from the BibTeX page.
- Appends new entries to `bib.txt`.
- Skips duplicates by citation key or matching entry text.
- Records failed queries in `misses.txt`.

## Files

Tracked project files:

- `scholar_scraper.py`: the scraper.
- `README.md`: these instructions.
- `.gitignore`: ignores local data, caches, and browser logs.
- `LICENSE`: friends-only private-use license.

Local generated files:

- `queries.txt`: your input searches.
- `bib.txt`: collected BibTeX entries.
- `misses.txt`: failed query log.

`queries.txt`, `bib.txt`, and `misses.txt` are ignored by git because they are
local working data. If `queries.txt` is missing, the script creates a starter
template and exits.

## Setup From Scratch

### 1. Install a Browser

Install at least one supported browser:

- Windows: Edge, Chrome, Firefox, or Brave.
- macOS: Chrome, Edge, Firefox, Brave, or Safari.
- Linux: Chrome/Chromium, Edge, Firefox, or Brave.

Chrome, Edge, and Firefox are the simplest choices.

### 2. Install `uv`

`uv` is the recommended Python runner for this script. It can download the
right Python version and install Selenium automatically, so most users do not
need to install Python separately.

First check whether `uv` is already installed:

```powershell
uv --version
```

If that prints a version, skip to step 3.

On Windows PowerShell, install `uv` with:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

On macOS or Linux, install `uv` with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then close and reopen the terminal, or follow the installer message to refresh
your PATH. Check again:

```powershell
uv --version
```

Official uv installation docs:

```text
https://docs.astral.sh/uv/getting-started/installation/
```

### 3. Get the Project Files

Put these files in one folder:

```text
scholar_scraper.py
README.md
.gitignore
```

Open a terminal in that folder.

On Windows PowerShell:

```powershell
cd path\to\scholar-bib-scraper
```

On macOS or Linux:

```bash
cd path/to/scholar-bib-scraper
```

### 4. Verify Python and Selenium

Run:

```powershell
uv run python --version
```

This should print a Python version. If Python is not already available, `uv`
may download one for this script.

Then check the scraper CLI:

```powershell
uv run scholar_scraper.py --help
```

You do not need to run `pip install selenium` when using `uv run`.

### 5. Create `queries.txt`

Run the scraper once:

```powershell
uv run scholar_scraper.py
```

If `queries.txt` does not exist, the script creates a starter template and
exits. Open `queries.txt`, add one Google Scholar search per line, then run the
script again.

### 6. Run a Small Test

Start with a small batch:

```powershell
uv run scholar_scraper.py --limit 3 --delay 6 --timeout 40
```

If that works, run more items:

```powershell
uv run scholar_scraper.py --delay 6 --timeout 40
```

### Optional: Installing Python Manually

Manual Python installation is optional if you use `uv`.

If you do want a normal system Python, install Python 3.10 through 3.13 from
python.org. On Windows, check **Add python.exe to PATH** during installation.

Then verify:

```powershell
python --version
```

Still run this scraper with `uv run` unless you know you want to manage packages
yourself.

## Browser Support

Default behavior:

```powershell
uv run scholar_scraper.py --browser auto
```

`auto` tries the operating system's default browser first. If that browser is
not supported by Selenium, it falls back to installed supported browsers.

Supported browser choices:

- `auto`
- `edge`
- `chrome`
- `firefox`
- `safari`
- `brave`

Examples:

```powershell
uv run scholar_scraper.py --browser chrome
uv run scholar_scraper.py --browser firefox
uv run scholar_scraper.py --browser edge
```

Platform notes:

- Windows: Edge, Chrome, Brave, and Firefox are supported.
- macOS: Chrome, Edge, Brave, Firefox, and Safari are supported.
- Linux: Chrome/Chromium, Edge, Brave, and Firefox are supported.
- Safari requires macOS and Safari remote automation support. If Safari fails,
  use Chrome or Firefox instead.

## Input Format

Default input file:

```text
queries.txt
```

Use one search query per line:

```text
Cyclical learning rates for training neural networks Smith
A fully first-order method for stochastic bilevel optimization
```

Blank lines are ignored, so double-spaced lists are fine:

```text
Paper title one Smith

Paper title two Jones

Paper title three Wang
```

Lines whose first non-space character is `#` are comments and are ignored:

```text
# This is a comment
# This query will not be searched
Paper title that will be searched
```

Do not split one query across multiple real lines. Editor word wrapping is fine;
pressing Enter in the middle of a title creates two separate queries.

## Basic Usage

Run the full list:

```powershell
uv run scholar_scraper.py
```

Try only the first few items:

```powershell
uv run scholar_scraper.py --limit 3
```

Resume from a specific query number:

```powershell
uv run scholar_scraper.py --start 24
```

Use a slower delay and longer page timeout:

```powershell
uv run scholar_scraper.py --start 24 --delay 45 --timeout 40
```

## Options

- `--input queries.txt`: input file with one query per line.
- `--output bib.txt`: output file for collected BibTeX entries.
- `--misses misses.txt`: log file for failed queries.
- `--delay 6`: seconds to wait between queries.
- `--timeout 20`: seconds to wait for pages/buttons before giving up.
- `--browser auto`: use the OS default supported browser, with fallback.
- `--limit 3`: only process the first 3 queries in this run.
- `--start 24`: start at query number 24, using 1-based order after comments
  and blank lines are removed.
- `--max-results 1`: only use the first Scholar result by default.

## Output

### `bib.txt`

Successful BibTeX entries are appended to the end of `bib.txt`.

If `bib.txt` does not exist, it is created. If an entry is already present, the
script skips it instead of appending a duplicate.

### `misses.txt`

Failed queries are appended to `misses.txt` as tab-separated lines:

```text
timestamp    query    reason
```

Common reasons include:

- no search results found
- first result has no Cite link
- citation modal has no BibTeX link
- BibTeX page did not contain a BibTeX entry
- timed out waiting for search results
- Google Scholar temporarily blocked requests from this network

It is safe to delete `misses.txt` whenever you want a fresh failure log.

## Resuming

The script prints progress like:

```text
[24/37] Searching: Cyclical learning rates for training neural networks Smith
```

If it stops because of a Scholar traffic block, `Ctrl+C`, or an unexpected
error, it prints a resume command:

```powershell
Resume with: uv run scholar_scraper.py --start 24 --delay 45 --timeout 40
```

Use that command later to retry from the correct item.

## Avoiding Scholar Blocks

Google Scholar may temporarily block automated traffic.

Safer settings:

```powershell
uv run scholar_scraper.py --delay 45 --timeout 40
```

Small test batch:

```powershell
uv run scholar_scraper.py --limit 10 --delay 45 --timeout 40
```

Notes:

- `--delay` is the wait between searches.
- `--timeout` is how long Selenium waits for a page element.
- Avoid very short delays such as `--delay 2`.
- Do not use threads or multiple browsers for Scholar.
- If Scholar shows an unusual traffic page, stop and wait before resuming.

## Manual Recovery

If the remaining list is short, finishing by hand can be faster:

1. Search the title in Google Scholar.
2. Click **Cite**.
3. Click **BibTeX**.
4. Copy the BibTeX entry.
5. Paste it at the end of `bib.txt`.

The script can still be used afterward; it skips duplicates.

## Cleanup

Safe to delete:

```powershell
Remove-Item -Recurse -Force __pycache__
Remove-Item misses.txt
```

On macOS or Linux:

```bash
rm -rf __pycache__
rm -f misses.txt
```

Only delete `bib.txt` if you want to lose collected citations.

Only delete `queries.txt` if you want the script to recreate the starter
template.

Do not delete `scholar_scraper.py`.

## License

This project uses a friends-only private-use license. Authorized friends may
use, copy, privately fork, and modify it for personal, academic, or internal
non-commercial use.

Do not sell it, publish it, redistribute it, or share it with people who have
not been given access by Patrick. See `LICENSE`.
