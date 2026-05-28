# /// script
# requires-python = ">=3.10,<3.14"
# dependencies = [
#   "selenium>=4.21",
# ]
# ///

from __future__ import annotations

import argparse
import platform
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCHOLAR_HOME = "https://scholar.google.com/?hl=en"
ENTRY_KEY_RE = re.compile(r"@\w+\s*[{(]\s*([^,\s]+)", re.IGNORECASE)
ENTRY_START_RE = re.compile(r"@\w+\s*[{(]", re.IGNORECASE)


class ScholarError(RuntimeError):
    """Raised when a query cannot produce a BibTeX entry."""


class ScholarBlockedError(ScholarError):
    """Raised when Scholar temporarily blocks further automated requests."""


@dataclass(frozen=True)
class FetchResult:
    entry: str
    key: str | None


@dataclass
class BibStore:
    path: Path
    keys: set[str]
    normalized_entries: set[str]

    @classmethod
    def load(cls, path: Path) -> "BibStore":
        if not path.exists():
            return cls(path=path, keys=set(), normalized_entries=set())

        text = path.read_text(encoding="utf-8-sig")
        entries = list(iter_bibtex_entries(text))
        keys = {
            key.lower()
            for entry in entries
            if (key := extract_bibtex_key(entry)) is not None
        }
        normalized_entries = {normalize_bibtex(entry) for entry in entries}
        return cls(path=path, keys=keys, normalized_entries=normalized_entries)

    def append_if_new(self, entry: str) -> tuple[bool, str | None]:
        entry = entry.strip()
        key = extract_bibtex_key(entry)
        normalized = normalize_bibtex(entry)

        if key and key.lower() in self.keys:
            return False, key
        if normalized in self.normalized_entries:
            return False, key

        self.path.parent.mkdir(parents=True, exist_ok=True)
        needs_blank_line = self.path.exists() and self.path.stat().st_size > 0
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            if needs_blank_line:
                handle.write("\n\n")
            handle.write(entry)
            handle.write("\n")

        if key:
            self.keys.add(key.lower())
        self.normalized_entries.add(normalized)
        return True, key


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.input.exists():
        create_queries_template(args.input)
        print(
            f"Created {args.input}. Add one Google Scholar search per line, "
            "then run the script again."
        )
        return 0

    try:
        queries = read_queries(args.input)
    except OSError as exc:
        print(f"Could not read {args.input}: {exc}", file=sys.stderr)
        return 2

    if not queries:
        print(f"No queries found in {args.input}. Add one search per line.", file=sys.stderr)
        return 2

    total_queries = len(queries)
    if args.start > total_queries:
        print(
            f"--start {args.start} is past the end of {args.input} "
            f"({total_queries} quer{'y' if total_queries == 1 else 'ies'}).",
            file=sys.stderr,
        )
        return 2

    indexed_queries = list(enumerate(queries, start=1))[args.start - 1 :]
    if args.limit is not None:
        indexed_queries = indexed_queries[: args.limit]

    store = BibStore.load(args.output)
    driver = build_driver(browser=args.browser, timeout=args.timeout)

    added = 0
    duplicates = 0
    missed = 0
    resume_index = args.start

    try:
        for position, (index, query) in enumerate(indexed_queries, start=1):
            resume_index = index
            print(f"[{index}/{total_queries}] Searching: {query}")

            try:
                result = fetch_bibtex_for_query(
                    driver=driver,
                    query=query,
                    timeout=args.timeout,
                    max_results=args.max_results,
                )
            except ScholarBlockedError as exc:
                missed += 1
                record_miss(args.misses, query, str(exc))
                print(f"  blocked: {exc}")
                print_resume_hint(index, total_queries, args)
                return 3
            except ScholarError as exc:
                missed += 1
                record_miss(args.misses, query, str(exc))
                print(f"  miss: {exc}")
            else:
                was_added, key = store.append_if_new(result.entry)
                display_key = key or result.key or "no citation key"
                if was_added:
                    added += 1
                    print(f"  added: {display_key}")
                else:
                    duplicates += 1
                    print(f"  duplicate skipped: {display_key}")

            resume_index = index + 1
            if position < len(indexed_queries):
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        print_resume_hint(resume_index, total_queries, args, stream=sys.stderr)
        return 130
    except Exception:
        print_resume_hint(resume_index, total_queries, args, stream=sys.stderr)
        raise
    finally:
        driver.quit()

    if resume_index <= total_queries:
        print_resume_hint(resume_index, total_queries, args)
    else:
        print("All input queries in this run were processed.")
 
    print(
        f"Done. Added {added}, skipped {duplicates} duplicate(s), "
        f"recorded {missed} miss(es)."
    )
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Search Google Scholar for queries and append first-result BibTeX "
            "entries to a local file."
        )
    )
    parser.add_argument("--input", type=Path, default=Path("queries.txt"))
    parser.add_argument("--output", type=Path, default=Path("bib.txt"))
    parser.add_argument("--misses", type=Path, default=Path("misses.txt"))
    parser.add_argument("--delay", type=positive_float, default=6.0)
    parser.add_argument("--timeout", type=positive_float, default=20.0)
    parser.add_argument(
        "--browser",
        choices=("auto", "edge", "chrome", "firefox", "safari", "brave"),
        default="auto",
        help=(
            "Browser to drive with Selenium. auto uses the OS default when it "
            "is supported, then falls back to installed supported browsers."
        ),
    )
    parser.add_argument("--max-results", type=positive_int, default=1)
    parser.add_argument(
        "--limit",
        type=positive_int,
        help="Only process the first N queries from the input file.",
    )
    parser.add_argument(
        "--start",
        type=positive_int,
        default=1,
        help="Start at this 1-based query number from the input file.",
    )
    return parser.parse_args(argv)


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def print_resume_hint(
    resume_index: int,
    total_queries: int,
    args: argparse.Namespace,
    *,
    stream=sys.stdout,
) -> None:
    if resume_index > total_queries:
        print("Nothing left to resume; all input queries were processed.", file=stream)
        return

    command = ["uv", "run", Path(sys.argv[0]).name]
    if args.input != Path("queries.txt"):
        command.extend(["--input", str(args.input)])
    if args.output != Path("bib.txt"):
        command.extend(["--output", str(args.output)])
    if args.misses != Path("misses.txt"):
        command.extend(["--misses", str(args.misses)])
    command.extend(["--start", str(resume_index)])
    if args.max_results != 1:
        command.extend(["--max-results", str(args.max_results)])
    if args.delay != 6.0:
        command.extend(["--delay", str(args.delay)])
    if args.timeout != 20.0:
        command.extend(["--timeout", str(args.timeout)])
    if args.browser != "auto":
        command.extend(["--browser", args.browser])

    print(f"Resume with: {format_command(command)}", file=stream)


def format_command(parts: list[str]) -> str:
    return " ".join(quote_command_part(part) for part in parts)


def quote_command_part(part: str) -> str:
    if not part:
        return "''"
    if not re.search(r"[\s'\"`]", part):
        return part
    return "'" + part.replace("'", "''") + "'"


def create_queries_template(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Add one Google Scholar search per line.\n"
        "# Lines starting with # are ignored.\n"
        "# Example:\n"
        "# Cyclical learning rates for training neural networks Smith\n",
        encoding="utf-8",
        newline="\n",
    )


def read_queries(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    return [
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    ]


def build_driver(*, browser: str, timeout: float):
    candidates = browser_candidates(browser)
    errors: list[str] = []

    for candidate in candidates:
        try:
            driver = create_webdriver(candidate)
        except Exception as exc:
            errors.append(f"{candidate}: {exc}")
            continue

        driver.set_page_load_timeout(max(timeout + 15, 30))
        print(f"Using browser: {candidate}")
        return driver

    details = "\n  ".join(errors) if errors else "no supported browser candidates found"
    raise RuntimeError(f"Could not start a Selenium browser.\n  {details}")


def browser_candidates(requested: str) -> list[str]:
    if requested != "auto":
        return [requested]

    candidates: list[str] = []
    default_browser = detect_default_browser()
    if default_browser:
        candidates.append(default_browser)

    for browser in platform_browser_order():
        if browser not in candidates and browser_installed(browser):
            candidates.append(browser)

    if not candidates:
        for browser in platform_browser_order():
            if browser not in candidates:
                candidates.append(browser)

    return candidates


def platform_browser_order() -> list[str]:
    system = platform.system().lower()
    if system == "darwin":
        return ["chrome", "edge", "brave", "firefox", "safari"]
    if system == "linux":
        return ["chrome", "edge", "brave", "firefox"]
    return ["edge", "chrome", "brave", "firefox"]


def detect_default_browser() -> str | None:
    system = platform.system().lower()
    if system == "windows":
        return detect_windows_default_browser()
    if system == "darwin":
        return detect_macos_default_browser()
    if system == "linux":
        return detect_linux_default_browser()
    return None


def detect_windows_default_browser() -> str | None:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice",
        ) as key:
            prog_id, _ = winreg.QueryValueEx(key, "ProgId")
    except Exception:
        return None

    return browser_from_identifier(str(prog_id))


def detect_macos_default_browser() -> str | None:
    try:
        result = subprocess.run(
            [
                "defaults",
                "read",
                "com.apple.LaunchServices/com.apple.launchservices.secure",
                "LSHandlers",
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    for block in re.findall(r"\{[^{}]*LSHandlerURLScheme = https;[^{}]*\}", result.stdout):
        match = re.search(r"LSHandlerRoleAll = \"?([^\";\n]+)\"?;", block)
        if match:
            return browser_from_identifier(match.group(1))
    return None


def detect_linux_default_browser() -> str | None:
    commands = (
        ("xdg-settings", "get", "default-web-browser"),
        ("xdg-mime", "query", "default", "x-scheme-handler/https"),
    )
    for command in commands:
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except Exception:
            continue
        if result.returncode == 0 and result.stdout.strip():
            browser = browser_from_identifier(result.stdout.strip())
            if browser:
                return browser
    return None


def browser_from_identifier(identifier: str) -> str | None:
    value = identifier.lower()
    if "microsoft" in value or "msedge" in value or "edge" in value:
        return "edge"
    if "chrome" in value or "chromium" in value:
        return "chrome"
    if "firefox" in value or "mozilla" in value:
        return "firefox"
    if "safari" in value:
        return "safari"
    if "brave" in value:
        return "brave"
    return None


def browser_installed(browser: str) -> bool:
    return find_browser_binary(browser) is not None


def find_browser_binary(browser: str) -> str | None:
    system = platform.system().lower()
    if system == "windows":
        return find_windows_browser_binary(browser)
    if system == "darwin":
        return find_macos_browser_binary(browser)
    if system == "linux":
        return find_linux_browser_binary(browser)
    return None


def find_windows_browser_binary(browser: str) -> str | None:
    local_app_data = Path.home() / "AppData" / "Local"
    program_files = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        local_app_data,
    ]
    paths = {
        "edge": [
            root / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            for root in program_files
        ],
        "chrome": [
            root / "Google" / "Chrome" / "Application" / "chrome.exe"
            for root in program_files
        ],
        "brave": [
            root / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"
            for root in program_files
        ],
        "firefox": [
            root / "Mozilla Firefox" / "firefox.exe"
            for root in program_files
        ],
        "safari": [],
    }

    for path in paths.get(browser, []):
        if path.exists():
            return str(path)

    executable_names = {
        "edge": ("msedge.exe", "msedge"),
        "chrome": ("chrome.exe", "chrome"),
        "brave": ("brave.exe", "brave"),
        "firefox": ("firefox.exe", "firefox"),
    }
    for name in executable_names.get(browser, ()):
        if resolved := shutil.which(name):
            return resolved

    return None


def find_macos_browser_binary(browser: str) -> str | None:
    paths = {
        "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "brave": "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
        "firefox": "/Applications/Firefox.app/Contents/MacOS/firefox",
        "safari": "/Applications/Safari.app/Contents/MacOS/Safari",
    }
    path = paths.get(browser)
    if path and Path(path).exists():
        return path

    executable_names = {
        "edge": ("Microsoft Edge", "msedge"),
        "chrome": ("Google Chrome", "google-chrome", "chrome"),
        "brave": ("Brave Browser", "brave-browser", "brave"),
        "firefox": ("firefox",),
        "safari": ("safari",),
    }
    for name in executable_names.get(browser, ()):
        if resolved := shutil.which(name):
            return resolved
    return None


def find_linux_browser_binary(browser: str) -> str | None:
    executable_names = {
        "edge": ("microsoft-edge", "microsoft-edge-stable", "msedge"),
        "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
        "brave": ("brave-browser", "brave-browser-stable", "brave"),
        "firefox": ("firefox",),
        "safari": (),
    }
    for name in executable_names.get(browser, ()):
        if resolved := shutil.which(name):
            return resolved
    return None


def create_webdriver(browser: str):
    from selenium import webdriver

    if browser == "edge":
        from selenium.webdriver.edge.options import Options

        options = Options()
        return webdriver.Edge(options=options)

    if browser == "chrome":
        from selenium.webdriver.chrome.options import Options

        options = Options()
        return webdriver.Chrome(options=options)

    if browser == "brave":
        from selenium.webdriver.chrome.options import Options

        binary = find_browser_binary("brave")
        if not binary:
            raise RuntimeError("Brave executable was not found")
        options = Options()
        options.binary_location = binary
        return webdriver.Chrome(options=options)

    if browser == "firefox":
        from selenium.webdriver.firefox.options import Options

        options = Options()
        return webdriver.Firefox(options=options)

    if browser == "safari":
        return webdriver.Safari()

    raise RuntimeError(f"unsupported browser: {browser}")


def fetch_bibtex_for_query(
    *,
    driver,
    query: str,
    timeout: float,
    max_results: int,
) -> FetchResult:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait

    wait = WebDriverWait(driver, timeout)

    driver.get(SCHOLAR_HOME)
    wait_for_page_ready(driver, timeout)
    ensure_no_manual_check(driver)

    search_box = wait.until(lambda d: d.find_element(By.NAME, "q"))
    search_box.clear()
    search_box.send_keys(query)
    search_box.send_keys(Keys.ENTER)

    wait_for_page_ready(driver, timeout)
    ensure_no_manual_check(driver)

    results = find_search_results(driver, wait)
    if not results:
        raise ScholarError("no search results found")

    candidates = results[:max_results]
    last_reason = "no Cite link found"
    for result_index, result in enumerate(candidates, start=1):
        cite_link = find_cite_link(result)
        if cite_link is None:
            cite_link = find_cite_link_by_result_index(driver, result_index)
        if cite_link is None:
            last_reason = "first result has no Cite link"
            continue

        open_citation_modal(driver, wait, cite_link)
        href = find_bibtex_href(driver, wait)
        if not href:
            last_reason = "citation modal has no BibTeX link"
            close_citation_modal(driver)
            continue

        driver.get(href)
        wait_for_page_ready(driver, timeout)
        ensure_no_manual_check(driver)

        entry = read_bibtex_page(driver, wait)
        key = extract_bibtex_key(entry)
        return FetchResult(entry=entry, key=key)

    if max_results == 1:
        raise ScholarError(last_reason)
    raise ScholarError(f"no BibTeX entry found in first {max_results} results")


def wait_for_page_ready(driver, timeout: float) -> None:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait

    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
    except TimeoutException as exc:
        raise ScholarError("timed out waiting for the page to finish loading") from exc


def ensure_no_manual_check(driver) -> None:
    while True:
        if is_temporary_traffic_block(driver):
            raise ScholarBlockedError(
                "Google Scholar temporarily blocked requests from this network"
            )

        reason = manual_check_reason(driver)
        if reason is None:
            return

        print(
            "  Google Scholar is asking for manual verification. "
            "Handle it in the open browser, then press Enter here."
        )
        input()
        time.sleep(1)


def manual_check_reason(driver) -> str | None:
    url = driver.current_url.lower()
    title = driver.title.lower()
    source = driver.page_source.lower()

    if "sorry/index" in url:
        return "unusual traffic page"
    if "unusual traffic" in source:
        return "unusual traffic page"
    if "not a robot" in source or "are you a robot" in source:
        return "robot verification page"
    if "g-recaptcha" in source or 'id="captcha"' in source:
        return "captcha page"
    if "captcha" in title:
        return "captcha page"
    return None


def is_temporary_traffic_block(driver) -> bool:
    url = driver.current_url.lower()
    source = driver.page_source.lower()
    return (
        "sorry/index" in url
        and "our systems have detected unusual traffic" in source
        and "please try your request again later" in source
    )


def find_search_results(driver, wait) -> list:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By

    try:
        wait.until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "#gs_res_ccl_mid .gs_r")
            or d.find_elements(By.CSS_SELECTOR, "#gs_res_ccl")
        )
    except TimeoutException as exc:
        if is_temporary_traffic_block(driver):
            raise ScholarBlockedError(
                "Google Scholar temporarily blocked requests from this network"
            ) from exc
        if reason := manual_check_reason(driver):
            raise ScholarError(f"Google Scholar requires manual verification: {reason}") from exc
        raise ScholarError("timed out waiting for search results") from exc

    results = driver.find_elements(By.CSS_SELECTOR, "#gs_res_ccl_mid .gs_r")
    return [
        result
        for result in results
        if result.find_elements(By.CSS_SELECTOR, ".gs_rt")
    ]


def find_cite_link(result):
    from selenium.webdriver.common.by import By

    selectors = (
        ".gs_or_cit",
        "a[aria-controls='gs_cit']",
        "a[onclick*='gs_ocit']",
        "a",
    )
    for selector in selectors:
        for link in result.find_elements(By.CSS_SELECTOR, selector):
            if is_cite_link(link):
                return link
    return None


def find_cite_link_by_result_index(driver, result_index: int):
    from selenium.webdriver.common.by import By

    selectors = (
        "#gs_res_ccl_mid a.gs_or_cit",
        "#gs_res_ccl_mid a[aria-controls='gs_cit']",
        "#gs_res_ccl_mid a[aria-haspopup='true']",
    )
    links = []
    seen = set()
    for selector in selectors:
        for link in driver.find_elements(By.CSS_SELECTOR, selector):
            element_id = link.id
            if element_id in seen:
                continue
            seen.add(element_id)
            if is_cite_link(link) and is_displayed(link):
                links.append(link)

    if len(links) >= result_index:
        return links[result_index - 1]
    return None


def is_cite_link(link) -> bool:
    text = (link.text or "").strip().lower()
    aria_label = (link.get_attribute("aria-label") or "").strip().lower()
    title = (link.get_attribute("title") or "").strip().lower()
    classes = (link.get_attribute("class") or "").strip().lower()
    aria_controls = (link.get_attribute("aria-controls") or "").strip().lower()

    return (
        "gs_or_cit" in classes
        or aria_controls == "gs_cit"
        or text == "cite"
        or aria_label == "cite"
        or title == "cite"
    )


def is_displayed(element) -> bool:
    try:
        return element.is_displayed()
    except Exception:
        return False


def open_citation_modal(driver, wait, cite_link) -> None:
    from selenium.common.exceptions import ElementClickInterceptedException
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By

    driver.execute_script(
        "arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});",
        cite_link,
    )
    time.sleep(0.2)

    try:
        cite_link.click()
    except ElementClickInterceptedException:
        driver.execute_script("arguments[0].click();", cite_link)

    try:
        wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, "#gs_cit, #gs_citi"))
    except TimeoutException as exc:
        raise ScholarError("timed out waiting for citation modal") from exc


def find_bibtex_href(driver, wait) -> str | None:
    from selenium.webdriver.common.by import By

    selectors = (
        "#gs_citi a.gs_citi",
        "#gs_citi a[href*='scholar.bib']",
        "#gs_cit a[href*='scholar.bib']",
        "#gs_cit a",
    )

    def matching_links():
        found = []
        seen = set()
        for selector in selectors:
            for link in driver.find_elements(By.CSS_SELECTOR, selector):
                if link.id in seen:
                    continue
                seen.add(link.id)
                if is_bibtex_link(link):
                    found.append(link)
        return found

    try:
        links = wait.until(lambda _driver: matching_links())
    except Exception:
        links = matching_links()

    for link in links:
        href = link.get_attribute("href")
        if href:
            return href
    return None


def is_bibtex_link(link) -> bool:
    label = " ".join(
        value
        for value in (
            link.text,
            link.get_attribute("textContent"),
            link.get_attribute("innerText"),
            link.get_attribute("href"),
            link.get_attribute("aria-label"),
            link.get_attribute("class"),
        )
        if value
    ).lower()
    return "bibtex" in label or "scholar.bib" in label


def close_citation_modal(driver) -> None:
    from selenium.webdriver.common.by import By

    for selector in ("#gs_cit-x", "#gs_cit button[aria-label='Close']"):
        buttons = driver.find_elements(By.CSS_SELECTOR, selector)
        if buttons:
            try:
                buttons[0].click()
            except Exception:
                pass
            return


def read_bibtex_page(driver, wait) -> str:
    from selenium.common.exceptions import TimeoutException
    from selenium.webdriver.common.by import By

    pre_elements = driver.find_elements(By.TAG_NAME, "pre")
    if pre_elements:
        text = pre_elements[0].get_attribute("textContent") or pre_elements[0].text
    else:
        try:
            body = wait.until(lambda d: d.find_element(By.TAG_NAME, "body"))
        except TimeoutException as exc:
            raise ScholarError("timed out waiting for BibTeX page content") from exc
        text = body.get_attribute("textContent") or body.text

    entry = extract_bibtex_entry(text)
    if not entry:
        raise ScholarError("BibTeX page did not contain a BibTeX entry")
    return entry


def extract_bibtex_entry(text: str) -> str | None:
    text = text.strip()
    match = ENTRY_START_RE.search(text)
    if not match:
        return None

    entry = extract_balanced_entry(text, match.start())
    if not entry:
        return None
    return unwrap_bibtex_page_text(entry)


def extract_balanced_entry(text: str, start: int) -> str | None:
    opener_index = next(
        (
            index
            for index in range(start, len(text))
            if text[index] in "{("
        ),
        None,
    )
    if opener_index is None:
        return None

    opener = text[opener_index]
    closer = "}" if opener == "{" else ")"
    depth = 0
    for index in range(opener_index, len(text)):
        char = text[index]
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1].strip()
    return text[start:].strip()


def unwrap_bibtex_page_text(entry: str) -> str:
    entry = entry.strip()
    if len(entry) >= 2 and entry[0] == entry[-1] and entry[0] in {"'", '"'}:
        return entry[1:-1].strip()
    return entry


def extract_bibtex_key(entry: str) -> str | None:
    match = ENTRY_KEY_RE.search(entry)
    if not match:
        return None
    return match.group(1).strip()


def normalize_bibtex(entry: str) -> str:
    return re.sub(r"\s+", " ", entry.strip()).lower()


def iter_bibtex_entries(text: str) -> Iterable[str]:
    starts = list(ENTRY_START_RE.finditer(text))
    for index, start_match in enumerate(starts):
        start = start_match.start()
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        yield text[start:end].strip()


def record_miss(path: Path, query: str, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{timestamp}\t{query}\t{reason}\n")


if __name__ == "__main__":
    raise SystemExit(main())
