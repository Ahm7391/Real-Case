import argparse
import csv
import json
import logging
import random, re, shutil, tempfile, psutil, subprocess
import gzip, os, time, glob, platform
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
import pandas as pd
from difflib import SequenceMatcher
 
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import xml.etree.ElementTree as ET
import undetected_chromedriver as uc

# ── logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("tiket_scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)
 
# ── constants ──────────────────────────────────────────────────────────────────
SITEMAP_INDEX_URL = "https://www.tiket.com/sitemap/id-id/index.xml.gz"
BASE_URL          = "https://www.tiket.com"
LOCALE            = "id-id"
PAGE_TIMEOUT      = 20
MAX_PROPERTIES    = 20
DRIVER_RECYCLE_EVERY = 10
IS_VPS = True
 
# Child sitemap name patterns that contain property detail pages (PDP)
PDP_PATTERNS = {
    "hotel":     ["hotel-pdp"],
    "villa":     ["homes-villa"],
    "homes":     ["homes-pdp"],
    "glamping":  ["homes-glamping"],
    "cottage":   ["homes-cottage"],
    "apartment": ["homes-apartment"],
}

def ensure_virtual_display():
    """
    Start Xvfb virtual display if not already running.
    Sets DISPLAY env var so Chrome picks it up automatically.
    """
    display = ":99"

    # Check if Xvfb is already running on this display
    result = subprocess.run(
        ["pgrep", "-f", f"Xvfb {display}"],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        # Not running — start it
        log.info(f"Starting Xvfb on display {display}...")
        subprocess.Popen(
            ["Xvfb", display, "-screen", "0", "1920x1080x24"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
         # ── Wait until Xvfb socket actually exists, not just a fixed sleep ──
        socket_path = f"/tmp/.X11-unix/X{display.lstrip(':')}"
        for _ in range(20):          # up to 10s
            if os.path.exists(socket_path):
                log.info(f"Xvfb socket ready: {socket_path}")
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Xvfb did not start in time — socket never appeared")
    else:
        log.info(f"Xvfb already running on {display}")

    # CRITICAL: set DISPLAY so Chrome finds the virtual screen
    os.environ["DISPLAY"] = display
    log.info(f"DISPLAY set to {display}")

def wait_for_download(download_folder: str, timeout: int = 30) -> str:
    """Wait until a file finishes downloading, return its path."""
    print("Waiting for download to complete...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        # .crdownload = Chrome's temp file while still downloading
        files = glob.glob(os.path.join(download_folder, "*.gz"))
        tmp   = glob.glob(os.path.join(download_folder, "*.crdownload"))
        if files and not tmp:
            latest = max(files, key=os.path.getmtime)
            print(f"Download complete → {latest}")
            return latest
        time.sleep(1)
    raise TimeoutError("Download did not complete in time")

def get_chrome_version() -> int:
    """Auto-detect installed Chrome major version — no more hardcoding version_main."""
    try:
        # Try common Chrome binary names on Linux VPS
        for binary in ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                version_str = result.stdout.strip()  # e.g. "Google Chrome 136.0.7103.93"
                major = int(version_str.split()[-1].split(".")[0])
                log.info(f"Auto-detected Chrome: {version_str} → major version {major}")
                return major
    except Exception as e:
        log.warning(f"Could not auto-detect Chrome version: {e}")
    return None   # let UC figure it out itself

def build_driver(download_folder: str, headless: bool):
    # ── On VPS: spin up virtual display so Chrome runs headed ────────────────
    if IS_VPS:
        ensure_virtual_display()

    opts = uc.ChromeOptions()

    prefs = {
        "download.default_directory":         download_folder,
        "download.prompt_for_download":       False,
        "download.directory_upgrade":         True,
        "safebrowsing.enabled":               True,
        "plugins.always_open_pdf_externally": True,
        "intl.accept_languages":              "en-US,en",
    }
    opts.add_experimental_option("prefs", prefs)

    # ── Stability flags (still needed even in headed mode on VPS) ────────────
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")              # VPS still has no real GPU
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-background-networking")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--mute-audio")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--start-maximized")
    opts.add_argument("--lang=en-US,en")

    # ── NO --headless flag at all when using Xvfb ────────────────────────────
    # headless=False both here and in uc.Chrome() call

    # ── Temp profile in shared memory ────────────────────────────────────────
    # shm_available = os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK)
    # tmp_base = "/dev/shm" if shm_available else "/tmp"
    # tmp_profile = tempfile.mkdtemp(prefix="chrome_profile_", dir=tmp_base)
    # opts.add_argument(f"--user-data-dir={tmp_profile}")
    # log.info(f"Chrome profile dir: {tmp_profile}")

    chrome_version = get_chrome_version()

    try:
        driver_kwargs = {
            "options":  opts,
            "headless": False,   # True headed mode — Xvfb provides the display
        }
        if chrome_version:
            driver_kwargs["version_main"] = chrome_version

        driver = uc.Chrome(**driver_kwargs)
        log.info("UC Chrome started in headed mode via Xvfb")

    except Exception as e:
        log.error(f"UC Chrome failed: {e}")
        log.info("Falling back to standard Selenium...")
        # shutil.rmtree(tmp_profile, ignore_errors=True)

        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        std_opts = Options()
        std_opts.add_argument("--no-sandbox")
        std_opts.add_argument("--disable-dev-shm-usage")
        std_opts.add_argument("--disable-gpu")
        std_opts.add_argument("--window-size=1920,1080")
        if IS_VPS and not headless:
            pass   # Xvfb is already running, no --headless needed
        elif headless:
            std_opts.add_argument("--headless=new")
        std_opts.add_experimental_option("prefs", prefs)
        # std_opts.add_argument(
        #     "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        #     "AppleWebKit/537.36 (KHTML, like Gecko) "
        #     "Chrome/149.0.0.0 Safari/537.36"
        # )

        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=std_opts
        )
        log.info("Standard Selenium started")

    # driver._tmp_profile = tmp_profile
    return driver

# def build_driver(download_folder: str, headless: bool):
#     opts = uc.ChromeOptions()
#     # # tmp_profile = tempfile.mkdtemp()
#     # # opts.add_argument(f"--user-data-dir={tmp_profile}")
#     # # ── redirect all downloads to project folder ───────────────────────────────
#     prefs = {
#         "download.default_directory":        download_folder,
#         "download.prompt_for_download":      False,   # no "Save As" popup
#         "download.directory_upgrade":        True,
#         "safebrowsing.enabled":              True,
#         "plugins.always_open_pdf_externally": True,
#         "intl.accept_languages":              "en-US,en",  # language header
#     }
#     opts.add_experimental_option("prefs", prefs)

#     # # ── anti-bot ───────────────────────────────────────────────────────────────
#     # opts.add_argument("--disable-blink-features=AutomationControlled")
#     # opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
#     # opts.add_experimental_option("useAutomationExtension", False)

#     # opts.add_argument(
#     #     "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     #     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     #     "Chrome/136.0.0.0 Safari/537.36"
#     # )
#     opts.add_argument("--lang=en-US,en")
#     # opts.add_argument("--accept-lang=en-US,en")

#     # # ── VPS / headless safe flags ──────────────────────────────────────────────
#     # if headless:
#     #     opts.add_argument("--headless=new")
#     opts.add_argument("--no-sandbox")                  # required on VPS
#     opts.add_argument("--disable-dev-shm-usage")       # prevents memory crash on VPS
#     opts.add_argument("--disable-gpu")                 # no GPU on VPS
#     # opts.add_argument("--window-size=1280,900")
#     # opts.add_argument("--disable-extensions")
#     # opts.add_argument("--no-zygote")
#     # opts.add_argument("--disable-software-rasterizer")
#     # opts.add_argument("--disable-extensions")
#     # opts.add_argument("--disable-setuid-sandbox")
#     # # opts.add_argument("--disable-application-cache")   # NEW
#     # # opts.add_argument("--disable-cache")               # NEW
#     # # opts.add_argument("--aggressive-cache-discard")    # NEW
#     driver = uc.Chrome(
#         options=opts,
#         headless=headless,
#         version_main=149,      # match your installed Chrome version
#     )

#     # # opts.add_argument(
#     # #     "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     # #     "AppleWebKit/537.36 (KHTML, like Gecko) "
#     # #     "Chrome/124.0.0.0 Safari/537.36"
#     # # )
#     # opts.add_argument("--ignore-certificate-errors")
#     # opts.add_argument("--allow-running-insecure-content")

#     # driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),
#     #     # service=Service("/usr/local/bin/chromedriver/chromedriver"),
#     #     options=opts
#     # )

#     # driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
#     #     "source": STEALTH_JS
#     # })

#     # driver.execute_cdp_cmd("Network.setUserAgentOverride", {
#     #     "userAgent": (
#     #         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
#     #         "AppleWebKit/537.36 (KHTML, like Gecko) "
#     #         "Chrome/136.0.0.0 Safari/537.36"
#     #     ),
#     #     "acceptLanguage": "en-US,en;q=0.9",
#     #     "platform": "Win32",
#     # })

#     # ── allow downloads in headless mode (Chrome blocks by default) ────────────
#     if headless:
#         driver.execute_cdp_cmd(
#             "Page.setDownloadBehavior",
#             {"behavior": "allow", "downloadPath": download_folder},
#         )
#     # driver = uc.Chrome(headless=headless) 

#     return driver

# def recycle_driver(
#     driver: webdriver.Chrome | None,
#     tmp_profile: str | None
#     ) -> tuple[webdriver.Chrome, str]:
#     """Quit existing driver, wipe temp profile, spin up a fresh one."""
#     if driver:
#         try:
#             driver.quit()
#         except Exception as e:
#             log.warning(f"Error quitting driver during recycle: {e}")
#         log.info("Driver recycled — old instance closed.")
#     if tmp_profile:
#         shutil.rmtree(tmp_profile, ignore_errors=True)
#         log.info("Temp profile directory removed.")
#     time.sleep(3)   # let OS reclaim ports/file handles
#     new_driver, new_profile = build_driver(driver)
#     return new_driver, new_profile

def download_sitemap(url: str, download_folder: str, headless: bool = True) -> str:
    """
    Open Chrome, navigate to sitemap URL, let Chrome auto-download the .gz,
    wait for it, then return the local file path.
    """
    os.makedirs(download_folder, exist_ok=True)
    driver = build_driver(download_folder, headless=IS_VPS)

    try:
        # Visit homepage first so Cloudflare sets cookies
        log.info("Visiting homepage to warm up session...")
        driver.get("https://www.tiket.com")
        time.sleep(5)

        if not headless:
            # input(">>> Solve Cloudflare challenge if it appears, then press ENTER ...")
            time.sleep(10)

        # Trigger the download
        log.info(f"Downloading: {url}")
        driver.get(url)

        # Wait for Chrome to finish downloading
        gz_path = wait_for_download(download_folder)
        driver.quit()
        return gz_path

    finally:
        driver.quit()

def extract_gz(gz_path: str) -> str:
    """Decompress .gz file and save as .xml next to it. Returns xml path."""
    xml_path = gz_path.replace(".gz", "")
    print(f"Extracting {gz_path} → {xml_path}")
    with gzip.open(gz_path, "rb") as f_in:
        xml_text = f_in.read().decode("utf-8")
    with open(xml_path, "w", encoding="utf-8") as f_out:
        f_out.write(xml_text)
    os.remove(gz_path)  # cleanup the .gz after extraction
    print(f"Extracted → {xml_path}")
    return xml_path

def parse_locs(mode: int | None, xml_path: str) -> list[str]:
    """Parse all <loc> URLs from a sitemap XML file."""
    from bs4 import BeautifulSoup
    if mode == 1:
        with open(xml_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
    elif mode == 2:
        with open(xml_path, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f, "html.parser")
    urls = [tag.text.strip() for tag in soup.find_all("loc")]
    print(f"Found {len(urls)} URLs in {xml_path}")
    return urls

def trigger_download(driver, url: str, download_folder: str) -> str:
    """Navigate to a .gz URL, let Chrome auto-download it, return local path."""
    before = set(glob.glob(os.path.join(download_folder, "*.gz")))
    driver.get(url)
    # wait for NEW gz file to appear
    deadline = time.time() + 30
    while time.time() < deadline:
        after = set(glob.glob(os.path.join(download_folder, "*.gz")))
        tmp   = set(glob.glob(os.path.join(download_folder, "*.crdownload")))
        new   = after - before
        if new and not tmp:
            return max(new, key=os.path.getmtime)
        time.sleep(1)
    raise TimeoutError(f"Download timed out: {url}")

def parse_property_urls(xml_path: str, areas: list[str]) -> dict[str, list[str]]:
    """
    Parse a child sitemap XML file.
    - Only extract the id-id locale <loc> URL from each <url> block
    - Only keep URLs that contain /indonesia/
    - Filter by area slug
    """
    from bs4 import BeautifulSoup

    with open(xml_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    area_urls = {area: [] for area in areas}
    url_blocks = soup.find_all("url")
    log.info(f"  {len(url_blocks)} url blocks found in {os.path.basename(xml_path)}")

    for block in url_blocks:
        # Strategy: prefer xhtml:link with hreflang="id-id"
        # Fall back to main <loc> if not found
        id_id_tag = block.find("link", {"hreflang": "id-id"})

        if id_id_tag:
            url = id_id_tag.get("href", "").strip()
        else:
            loc = block.find("loc")
            url = loc.text.strip() if loc else ""

        if not url:
            continue

        # Only keep Indonesian properties
        if "/indonesia/" not in url.lower():
            continue

        # Filter by area slug
        url_lower = url.lower()
        for area in areas:
            area_slug = area.lower().replace(" ", "-")
            if area_slug in url_lower:
                area_urls[area].append(url)

    for area, urls in area_urls.items():
        if urls:
            log.info(f"  area '{area}': {len(urls)} properties")

    return area_urls

def scroll_to_explore(driver:webdriver.Chrome) -> None:
    # scroll to bottom to make sure we handle all lazy load elements
    last_height = driver.execute_script("return document.body.scrollHeight")
    current_position = 0

    while True:
        # Random chunk size (human scrolls vary between short and long flicks)
        chunk = random.randint(300, 700)
        current_position += chunk
        log.info(f"current_pos is : {current_position}")

        # Smooth scroll via JS scrollTo with 'smooth' behavior
        driver.execute_script(f"""
            window.scrollTo({{
                top: {current_position},
                behavior: 'smooth'
            }});
        """)

        # Random pause between scrolls (humans don't scroll at constant speed)
        time.sleep(random.uniform(0.4, 1.2))

        # Occasionally do a longer pause (like a human reading something)
        if random.random() < 0.2:   # 20% chance
            pause = random.uniform(1.5, 3.0)
            log.info(f"  [scroll] Natural reading pause: {pause:.1f}s")
            time.sleep(pause)

        # Occasionally scroll slightly back up (very human-like)
        if random.random() < 0.1:   # 10% chance
            scroll_back = random.randint(50, 150)
            log.info(f"  [scroll] Natural scroll back: {scroll_back:.1f}s")
            driver.execute_script(f"""
                window.scrollTo({{
                    top: {current_position - scroll_back},
                    behavior: 'smooth'
                }});
            """)
            time.sleep(random.uniform(0.3, 0.6))

        # Check if page height grew (new lazy content loaded)
        new_height = driver.execute_script("return document.body.scrollHeight")

        # If we've scrolled past current content bottom, check stability
        if current_position >= new_height:
            log.info(f"  [scroll] Scroll past current bottom")
            log.info(f"  [scroll] Current Position is : {current_position}")
            log.info(f"  [scroll] new_height 1 is : {new_height}")
            time.sleep(5)  # wait a beat for any final lazy loads
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                # One final slow scroll to absolute bottom
                log.info(f"  [scroll] Scroll make sure 3 times")
                for _ in range(3):
                    driver.execute_script("""
                        window.scrollTo({
                            top: document.body.scrollHeight,
                            behavior: 'smooth'
                        });
                    """)
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    time.sleep(5)
                last_height = new_height
                if new_height == last_height:
                    log.info("  [scroll] Reached stable bottom.")
                    break
            # Page grew — update and keep scrolling
            last_height = new_height

def sub_explorer(driver: webdriver.Chrome) -> list[str]:
    hrefs = []
    if os.path.exists("seen_url.json"):
        print("JSON Found")
        with open("seen_url.json", "r") as f:
            seen_url_ref = json.load(f)
    else:
        seen_url_ref = {}
        with open("seen_url.json", "w") as f:
            json.dump(seen_url_ref, f)
        log.info("Created fresh seen_url.json")

    cards = WebDriverWait(driver, PAGE_TIMEOUT).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, "a[data-testid='seo-card']"))
    )
    for card in cards:
        href = card.get_attribute("href")
        href_fix = re.sub(r'-\d+$', '', href)
        if href_fix not in seen_url_ref.keys():
            seen_url_ref[href_fix] = ""
            hrefs.append(href_fix)
        else:
            continue

    with open("seen_url.json", "w") as f:
        json.dump(seen_url_ref, f)
    
    # href_master_list.extend(hrefs)
    return hrefs

def scrape_sitemaps(url: str, driver) -> list[str]:
    if url == "" or url == None:
        return []

    try:
        # print("Visiting homepage to warm up session...")
        # driver.get("https://www.tiket.com")
        # time.sleep(10)

        # if not headless:
        #     input(">>> Solve Cloudflare challenge if it appears, then press ENTER ...")

        # Trigger the download
        driver.get(url)
        time.sleep(20)
        # Wait up to 10 seconds for the element to appear
        # property_card = WebDriverWait(driver, PAGE_TIMEOUT).until(
        #     EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='seo-additional-content']"))
        # )
        property_card = WebDriverWait(driver, PAGE_TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a[data-testid='seo-card']"))
        )
        log.info("property card found!!!")
    except Exception as e:
        log.info("Element not found within timeout:", e)
        property_card = None
    
    href_master_list = []
    if property_card:
        scroll_to_explore(driver)
        time.sleep(5)

        style1 = driver.find_element(
            By.CSS_SELECTOR, "div.main_pagination_container__gX6WA"
        )

        # STYLE2 COULD HAVE MULTIPLE sections
        style2 = driver.find_elements(
            By.CSS_SELECTOR, "div.SeoAdditionalContent_dots__MLHpe"
        )

        if style1:
            log.info("Style 1 found, locating next page buttons")
            potential_page = driver.find_elements(
                By.CSS_SELECTOR, "a.Pagination_button__xnJqp.Pagination_anchor__rX_07"
            )
            page_numbers = []
            for el in potential_page:
                text = el.text.strip()
                if text.isdigit():  # check if numeric
                    page_numbers.append(int(text))
            max_page = max(page_numbers) if page_numbers else None
            log.info(f"Found {max_page} potential pages.")

            if len(page_numbers) == 0: max_page = None

            for i in range(0, max_page):
                if i == max_page: 
                    log.info("We're reaching final page, breaking.")
                    break

                log.info(f"Exploring page {i+1} out of {max_page} pages")
                buffer_list = sub_explorer(driver)
                href_master_list.extend(buffer_list)
                log.info(f"[A] Successfully scrapped {len(buffer_list)} URL")
                log.info(f"[A] total collected URL is {len(href_master_list)} URL")

                button_inspectors = driver.find_elements(
                    By.CSS_SELECTOR, "a.Pagination_button__xnJqp.Pagination_anchor__rX_07"
                )
                # access the next page which usually located on the last sequence
                href_value = button_inspectors[-1].get_attribute("href")
                log.info("Moving to next page.")
                driver.get(href_value)
                time.sleep(5)

        if len(style2) > 0:
            log.info("Style 2 found, locating next page buttons")
            log.info(f"We have {len(style2)} sections.")
            wait = WebDriverWait(driver, PAGE_TIMEOUT)

            # for i in range(len(style2)):
            #     print(f"Processing section no {i}")
            time.sleep(5)
            buttons_style2 = wait.until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, "button[aria-label^='page-control-dot']")
                )
            )

            total = len(buttons_style2)
            for i in range(total):
                log.info(f"processing loop {i+1}")
                try:
                    # Re-fetch buttons every loop (IMPORTANT: avoid stale elements)
                    buttons = driver.find_elements(By.CSS_SELECTOR, "button[aria-label^='page-control-dot']")
                    
                    btn = buttons[i]

                    # Scroll into view (optional but useful)
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
                    time.sleep(5)
                    # Click using JS (more reliable for UI-heavy sites)
                    driver.execute_script("arguments[0].click();", btn)
                    time.sleep(3)
                    
                    # Wait for carousel state change
                    # Option 1: wait until this button becomes active
                    wait.until(lambda d: "SeoAdditionalContent_active__gpRv3" in btn.get_attribute("class"))

                    # Option 2 (better): wait for content to change (if identifiable)
                    # e.g. wait until image/src/text changes

                    time.sleep(1)  # small buffer (can replace with smarter wait)
                    buffer_list = sub_explorer(driver)
                    href_master_list.extend(buffer_list)
                    log.info(f"[B] Scraped {len(buffer_list)} URLs at Page {i+1}")
                    log.info(f"[B] total collected URL is {len(href_master_list)} URL")
                except Exception as e:
                    log.info(f"  error: {e}")
                    continue
    return href_master_list

def extract_indonesia_urls(xml_file):
    bali_area = ["bali", "ubud", "seminyak", "canggu", "kintamani", "denpasar", "tabanan", "sidemen",
                 "karangasem", "lovina", "bedugul", "nusa-dua", "nusa dua", "nusadua", "sanur", "kuta", 
                 "menjangan", "buyan", "batur", "malang", "bandung", "ciawi", "lembang", "yogyakarta",
                 "pengalengan", "sentul", "megamendung", "ciawi", "sukabumi"]
    tree = ET.parse(xml_file)
    root = tree.getroot()

    namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    target_prefix = "https://www.tiket.com/id-id/homes/indonesia"

    results = []
    if os.path.exists("seen_url.json"):
        log.info("JSON Found")
        with open("seen_url.json", "r") as f:
            seen_url_ref = json.load(f)
    else:
        seen_url_ref = {}
        with open("seen_url.json", "w") as f:
            json.dump(seen_url_ref, f)
        log.info("Created fresh seen_url.json")

    for url in root.findall("ns:url", namespace):
        loc = url.find("ns:loc", namespace)
        if loc is not None:
            link = loc.text.strip()
            link_fix = re.sub(r'-\d+$', '', link)
            filter_url = any(keyword in link_fix for keyword in bali_area)
            if filter_url and (link_fix.startswith(target_prefix)) and (
                link_fix not in seen_url_ref.keys()):
                seen_url_ref[link_fix] = ""
                results.append(link_fix)

    with open("seen_url.json", "w") as f:
        json.dump(seen_url_ref, f)
    return results

def get_checkin_checkout(offset_days: int = 1) -> tuple[str, str]:
    """
    Return (checkin, checkout) as ISO strings.
    Default: tomorrow → day after tomorrow (1-night stay).
    """
    checkin  = datetime.today() + timedelta(days=offset_days)
    checkout = checkin + timedelta(days=1)
    return checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d")

def renew_checkin_checkout(cur_date, increment_day: int = 1) -> tuple[str, str]:
    """
    Return new (checkin, checkout) as ISO strings.
    Renew dates due to availability problem.
    """
    cur_date_clean = datetime.strptime(cur_date, "%Y-%m-%d")
    checkin  = cur_date_clean + timedelta(days=increment_day)
    checkout = checkin + timedelta(days=1)
    return checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d")

def build_search_url(incoming_url, checkin: str, checkout: str) -> str:
    """Build minimal, tracking-free tiket.com search URL."""
    base = incoming_url
    params = (
        # f"&dest_type={DEST_TYPE}"
        f"?checkin={checkin}"
        f"&checkout={checkout}"
        f"&adult=2"
        f"&room=1"
        f"&night=1"
    )
    # f"&dest_id={DEST_ID}"
    return base + params

def scrape_agoda(target_url, tiket_address, mode_main):
    """
    target_url = nama hotel,
    tiket_address = alamat hotel dari tiket.com buat crosscheck,
    mode_main =  ada 2 yaitu "eb" untuk early-book dan "lm" untuk last-minute,
    beda di logic timedatenya aja nanti
    """
    PAGE_TIMEOUT = 20
    CURR_DIR = os.path.dirname(os.getcwd())

    # ── Config ──────────────────────────────────────────────────────────────────
    TARGET_QUERY   = target_url
    COUNTRY_FILTER = "Indonesia"
    # CHECK_ADDRESS = 
    THRESHOLD      = 0.50   # 50% minimum similarity to be included
    MATCH_THRESHOLD  = 0.70 # 70% threshold for Type 1 search result

    # ================================== HELPER FUNCTIONS =======================================
    def tokenize(text: str) -> set[str]:
        """Lowercase and split into word tokens."""
        return set(re.findall(r'\w+', text.lower()))

    def token_overlap_score(query: str, candidate: str) -> float:
        q_tokens = tokenize(query)
        c_tokens = tokenize(candidate)
        if not q_tokens:
            return 0.0
        matched = 0
        for qt in q_tokens:
            best = max(
                SequenceMatcher(None, qt, ct).ratio()
                for ct in c_tokens
            )
            if best >= 0.75:
                matched += 1
        return matched / len(q_tokens)

    def shift_checkin_checkout(url: str) -> str:
        """
        Replaces checkIn and checkOut in the URL with:
        - checkIn  = tomorrow
        - checkOut = tomorrow + 1 day (1 night stay)
        All other parameters are left untouched.
        """
        # ── Parse URL into components ─────────────────────────────────────────
        parsed = urlparse(url)
    
        # parse_qs preserves all params; keep_blank_values keeps empty ones too
        params = parse_qs(parsed.query, keep_blank_values=True)
    
        # ── Compute new dates ─────────────────────────────────────────────────
        tomorrow   = datetime.today() + timedelta(days=1)
        # day_after  = tomorrow + timedelta(days=1)
    
        params["checkIn"]  = [tomorrow.strftime("%Y-%m-%d")]
        # params["checkOut"] = [day_after.strftime("%Y-%m-%d")]
        params["los"] = ["1"]
    
        # ── Rebuild query string ──────────────────────────────────────────────
        # doseq=True handles list values from parse_qs correctly
        new_query = urlencode(params, doseq=True)
    
        # ── Reconstruct full URL ──────────────────────────────────────────────
        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        return new_url

    def shortened_date(driver, todays_date):
        capture_url = driver.current_url
        parsed_capture = urlparse(capture_url)
        params = parse_qs(parsed_capture.query, keep_blank_values=True)

        day_after  = todays_date + timedelta(days=0)

        params["checkIn"]  = [todays_date.strftime("%Y-%m-%d")]
        # params["checkOut"] = [day_after.strftime("%Y-%m-%d")]
        params["los"] = ["1"]
        new_query = urlencode(params, doseq=True)
        clean_url = urlunparse((
            parsed_capture.scheme,
            parsed_capture.netloc,
            parsed_capture.path,
            parsed_capture.params,
            new_query,
            parsed_capture.fragment
        ))
        # focus_url = clean_url + f"?checkin={todays_date.strftime("%Y-%m-%d")}" + f"?los=1"
        focus_url = clean_url 
        print(f"switching 1 {focus_url}")
        return focus_url

    def parse_properties_selenium(driver) -> list[dict]:
        wait = WebDriverWait(driver, 10)

        # Wait until the autocomplete dropdown list is visible
        # one cycle to refresh to current date
        for i in range(2):
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "li.InterstitialList__item")
            ))
            if i == 0:
                refresh_url = shift_checkin_checkout(driver.current_url)
                print(f"Refreshing URL : {refresh_url}")
                driver.get(refresh_url)

        items = driver.find_elements(By.CSS_SELECTOR, "li.InterstitialList__item")

        results = []
        for item in items:
            try:
                name = item.find_element(
                    By.CSS_SELECTOR, "h3.InterstitialList__title > span:first-child"
                ).text.strip()
            except:
                name = ""

            try:
                address = item.find_element(
                    By.CSS_SELECTOR, "p.InterstitialList__address"
                ).text.strip()
            except:
                address = ""

            try:
                link = item.find_element(
                    By.CSS_SELECTOR, "a.InterstitialList__container"
                ).get_attribute("href")
            except:
                link = ""

            results.append({"name": name, "address": address, "link": link})

        return results

    def extract_offer_details(offer_el) -> dict:
        """
        Scrape a single offer block (one pricing column inside a room card).
        Returns a dict of all offer-level fields.
        """
        # ====================== HELPER FUNCTIONS SECTIONS ==================================
        def clean_price(raw: str) -> int | None:
            digits = re.sub(r'[^\d]', '', raw)
            return int(digits) if digits else None
        # ====================== END OF HELPER FUNCTIONS SECTIONS ==================================

        details = {
            "adults":              None,
            "children_policy":     None,
            "breakfast":           None,
            "cancellation_policy": None,
            "payment_condition":   None,
            "wifi":                False,
            "original_price":      None,
            "discounted_price":    None,
            "discount_pct":        None,
        }

        # ── All <li> policy rows ───────────────────────────────────────────────
        try:
            items = offer_el.find_elements(By.CSS_SELECTOR, "ul li p")
            for item in items:
                text = item.text.strip()
                text_lower = text.lower()

                if "breakfast" in text_lower:
                    details["breakfast"] = text
                elif "non-refundable" in text_lower or "cancellation" in text_lower:
                    details["cancellation_policy"] = text
                elif "book and pay" in text_lower or "pay later" in text_lower:
                    details["payment_condition"] = text
                elif "wifi" in text_lower or "wi-fi" in text_lower:
                    details["wifi"] = True
                elif "kid" in text_lower or "child" in text_lower:
                    details["children_policy"] = text
        except NoSuchElementException:
            pass

        # ── Prices ────────────────────────────────────────────────────────────
        try:
            original_el = offer_el.find_element(
                By.CSS_SELECTOR, '[data-element-name="fpc-cor-price"]'
            )
            details["original_price"] = clean_price(original_el.text)
        except NoSuchElementException:
            pass

        try:
            discounted_el = offer_el.find_element(
                By.CSS_SELECTOR, '[data-element-name="fpc-room-price"]'
            )
            details["discounted_price"] = clean_price(discounted_el.text)
        except NoSuchElementException:
            pass

        try:
            discount_pct_el = offer_el.find_element(
                By.CSS_SELECTOR, '[class*="wYKJw"]'   # discount % badge
            )
            details["discount_pct"] = discount_pct_el.text.strip()
        except NoSuchElementException:
            pass

        return details

    def get_cheapest_offer(offers: list[dict]) -> dict:
        """
        From a list of offer dicts, return the one with the lowest discounted_price.
        Falls back to original_price if no discounted price exists.
        """
        def price_key(o):
            return o.get("discounted_price") or o.get("original_price") or float("inf")
        return min(offers, key=price_key)

    def scroll_to_bottom_until_stable(driver: webdriver.Chrome) -> None:
        """
        Scroll down smoothly in variable chunks with random pauses,
        mimicking human-like browsing behavior.
        """
        last_height = driver.execute_script("return document.body.scrollHeight")
        current_position = 0

        while True:
            # Random chunk size (human scrolls vary between short and long flicks)
            chunk = random.randint(300, 700)
            current_position += chunk
            log.info(f"current_pos is : {current_position}")

            # Smooth scroll via JS scrollTo with 'smooth' behavior
            driver.execute_script(f"""
                window.scrollTo({{
                    top: {current_position},
                    behavior: 'smooth'
                }});
            """)

            # Random pause between scrolls (humans don't scroll at constant speed)
            time.sleep(random.uniform(0.4, 1.2))

            # Occasionally do a longer pause (like a human reading something)
            if random.random() < 0.2:   # 20% chance
                pause = random.uniform(1.5, 3.0)
                print(f"  [scroll] Natural reading pause: {pause:.1f}s")
                time.sleep(pause)

            # Occasionally scroll slightly back up (very human-like)
            if random.random() < 0.1:   # 10% chance
                scroll_back = random.randint(50, 150)
                print(f"  [scroll] Natural scroll back: {scroll_back:.1f}s")
                driver.execute_script(f"""
                    window.scrollTo({{
                        top: {current_position - scroll_back},
                        behavior: 'smooth'
                    }});
                """)
                time.sleep(random.uniform(0.3, 0.6))

            # Check if page height grew (new lazy content loaded)
            new_height = driver.execute_script("return document.body.scrollHeight")

            # If we've scrolled past current content bottom, check stability
            if current_position >= new_height:
                log.info(f"  [scroll] Scroll past current bottom")
                log.info(f"  [scroll] Current Position is : {current_position}")
                log.info(f"  [scroll] new_height 1 is : {new_height}")
                time.sleep(5)  # wait a beat for any final lazy loads
                new_height = driver.execute_script("return document.body.scrollHeight")
                if new_height == last_height:
                    # One final slow scroll to absolute bottom
                    log.info(f"  [scroll] Scroll make sure 3 times")
                    for _ in range(3):
                        driver.execute_script("""
                            window.scrollTo({
                                top: document.body.scrollHeight,
                                behavior: 'smooth'
                            });
                        """)
                        new_height = driver.execute_script("return document.body.scrollHeight")
                        time.sleep(5)
                    last_height = new_height
                    if new_height == last_height:
                        log.info("  [scroll] Reached stable bottom.")
                        break
                # Page grew — update and keep scrolling
                last_height = new_height

    def clean_tokens(text: str) -> list[str]:
        """Strip punctuation, lowercase, split into tokens."""
        text = re.sub(r'[.,\-/]', ' ', text.lower())
        return [t for t in text.split() if t]

    def best_token_score(query: str, token_list: list[str]) -> tuple[float, str]:
        """Return (best_score, best_matching_token) for query against token_list."""
        if not token_list:
            return 0.0, ""
        scored = [(SequenceMatcher(None, query, t).ratio(), t) for t in token_list]
        return max(scored, key=lambda x: x[0])

    def extract_city_tokens(address: str) -> list[str]:
        """
        Split address by comma, clean each segment, drop noise.
        Returns a flat list of meaningful city-level tokens.
        """
        PLUS_CODE_PATTERN = re.compile(r'^[A-Z0-9]{4}\+[A-Z0-9]{2,}$', re.IGNORECASE)
        POSTAL_PATTERN    = re.compile(r'^\d{4,6}$')
        NOISE_WORDS = {
            "kec", "kecamatan", "kabupaten", "kab",
            "kota", "provinsi", "prov", "di", "indonesia"
        }

        segments = address.split(",")
        city_tokens = []

        for seg in segments:
            # Strip punctuation and whitespace
            seg = re.sub(r'[.\-/]', ' ', seg).strip()

            # Split segment into individual words
            words = seg.lower().split()

            # Drop whole segment if it's a Plus Code
            if len(words) == 1 and PLUS_CODE_PATTERN.match(words[0]):
                continue

            for word in words:
                if not word:
                    continue
                if POSTAL_PATTERN.match(word):       # postal code
                    continue
                if word in NOISE_WORDS:              # administrative noise
                    continue
                city_tokens.append(word)

        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for tok in city_tokens:
            if tok not in seen:
                seen.add(tok)
                deduped.append(tok)

        return deduped

    # ================================== END OF HELPER FUNCTIONS =======================================
    # ================================== CORE FUNCTIONS ================================================
    def scrape_agoda_info(wait_specs, driver, url_tgt, address, mode):
        focus_url = url_tgt
        todays_date = datetime.today()
        check_result = False
        mismatch_address = False
        REFERENCE_ADDRESS = address

        # FILTER TO CHECK AVAILABILITY 
        for ii in range(3):
            driver.get(focus_url)
            if ii == 0:
                print("refreshing url!")
                if mode == "eb":
                    todays_date  = todays_date + timedelta(days=60)
                elif mode == "lm":
                    todays_date = todays_date + timedelta(days=1)
                else:
                    raise RuntimeError("[AGODA SCRAPE] Mode Error!")
                focus_url = shortened_date(driver, todays_date)
                driver.get(focus_url)
                time.sleep(10)
            wait_specs.until(EC.presence_of_element_located(
                (By.ID, "property-dateless-roomgrid")
            ))
            detect_sold_out = False

            # ── Layer 1: data-testid (most stable selector) ───────────────────────
            try:
                print("Filtering with data_testid")
                driver.find_element(By.CSS_SELECTOR, '[data-testid="sold-out-page"]')
                detect_sold_out = True
            except NoSuchElementException:
                print("NO PASS data_testid")
                pass

            # ── Layer 2: data-element-name (also developer-maintained) ───────────
            try:
                print("Filtering with data-element-name")
                driver.find_element(By.CSS_SELECTOR, '[data-element-name="mob-property-sold-out-all"]')
                detect_sold_out = True
            except NoSuchElementException:
                print("NO PASS data-element-name")
                pass

            # ── Layer 3: h2 text content fallback ────────────────────────────────
            try:
                print("Filtering with h2")
                headings = driver.find_elements(By.TAG_NAME, "h2")
                for h2 in headings:
                    if "sold out" in h2.text.strip().lower():
                        detect_sold_out = True
            except NoSuchElementException:
                print("NO PASS Filtering with h2")
                pass
            
            # TODO: CHECK THE ADDRESS THIS IS THE FINAL CHECK IF NOT SUCCEED STOP EXECUTION TO PREVENT MISLEADING
            try:
                addr_el = wait_specs.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-selenium="hotel-address-map"]')
                ))
                extracted_address = addr_el.text.strip()
                print(f"Extracted address is : {extracted_address}")
                print(f"While reference address is : {REFERENCE_ADDRESS}")
            except TimeoutException:
                print("Can't find address for crosschecking, quiting!")
                return 0

            # ── Score city and country independently ─────────────────────────────────────
            ref_tokens   = extract_city_tokens(extracted_address)
            ext_tokens  = extract_city_tokens(REFERENCE_ADDRESS)

            # ── Match each ref token against extracted tokens ────────────────────────────
            print(f"{'Ref Token':<16} {'Best Match':<20} {'Score':>7}")
            print("-" * 46)

            total_score = 0.0
            for ref_tok in ref_tokens:
                score, matched = best_token_score(ref_tok, ext_tokens)
                total_score += score
                print(f"{ref_tok:<16} {matched:<20} {score*100:>6.1f}%")

            final_score = total_score / len(ref_tokens) if ref_tokens else 0.0

            print()
            if final_score >= MATCH_THRESHOLD:
                print(f"[✓] ADDRESS MATCH ({final_score*100:.1f}%) — city confirmed")
            else:
                mismatch_address = True
                print(
                    f"[✗] Address mismatch — "
                    f"{final_score*100:.1f}% < {MATCH_THRESHOLD*100:.0f}% threshold\n"
                    f"    Ref tokens : {ref_tokens}\n"
                    f"    Ext tokens : {ext_tokens}"
                )
                break

            if detect_sold_out == True: 
                print(f"[WARNING] No room detected, this is your trial no {ii+1}/3")
                todays_date = todays_date + timedelta(days=1)
                focus_url = shortened_date(driver, todays_date)
                time.sleep(20)
            else:
                check_result = True
                break # WE FOUND SOMETHING WE CAN BREAK AND CONTINUE SCRAP

        if check_result == False or mismatch_address == True:
            print(f"Leaving this property, all availability confirmed to be not exist or address mismatched.")
            return 0
        else:
            print("Next inspection stage!!!")
            # wait_specs.until(EC.presence_of_element_located(
            #     (By.ID, "roomGridContent")
            # ))
            scroll_to_bottom_until_stable(driver)
            try:
                wait_specs.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '[data-testid="room-grid-element"]')
                ))
            except Exception as e:
                print(f"Fucking error due to {e}, fucking quitting!!!!")
                return 0
            
            time.sleep(5)
            # room_cards = wait_specs.until(EC.presence_of_all_elements_located(
            #     (By.CSS_SELECTOR, '[data-element-name="mob-room-group"]')
            # ))
            try:
                room_cards = driver.find_elements(By.CSS_SELECTOR, '[data-element-name="mob-room-group"]')
                print(f"Found {len(room_cards)} room type(s)")
                if len(room_cards) == 0:
                    print("For some reason the fucking room is motherfucking empty don't know why!!!!! Fuck quitting this shit!!!!")
                    return 0
            except Exception as e:
                print(f"Fucking error due to {e}, fucking quitting!!!!")
                return 0
            
            all_rooms = []
            room_data = {
                "room_name":           None,
                "children_policy":     None,
                "breakfast":           None,
                "cancellation_policy": None,
                "payment_condition":   None,
                "wifi":                False,
                "original_price":      None,
                "discounted_price":    None,
                "discount_pct":        None,
                "is_sold_out":         False,
                "target_date": None,
                "category": None,
            }
            time.sleep(5)
            for card in room_cards:
                room_data["target_date"] = todays_date.strftime("%Y-%m-%d")
                if mode == "eb":
                    room_data["category"] = "early-book"
                if mode == "lm":
                    room_data["category"] = "last-minute"
                # ── Room name ──────────────────────────────────────────────────────
                try:
                    room_data["room_name"] = card.find_element(
                        By.CSS_SELECTOR, '[data-testid="room-name"] h4, [data-testid="room-name"] h2'
                    ).text.strip()
                except NoSuchElementException:
                    pass

                # ── Sold out room type (individual room, not whole property) ───────
                try:
                    card.find_element(By.CSS_SELECTOR, '[data-testid="soldout-room-offer"]')
                    room_data["is_sold_out"] = True
                    all_rooms.append(room_data)
                    print(f"  [{room_data['room_name']}] → SOLD OUT, skipping offers")
                    continue
                except NoSuchElementException:
                    pass

                # ── Click "Show more offers" if present ────────────────────────────
                try:
                    show_more_btn = card.find_element(
                        By.CSS_SELECTOR, '[data-element-name="mob-room-group-show-more"]'
                    )
                    driver.execute_script("arguments[0].click();", show_more_btn)
                    print(f"  [{room_data['room_name']}] → Clicked 'Show more offers'")

                    # Wait for extra offers to appear
                    wait_specs.until(EC.presence_of_element_located(
                        (By.CSS_SELECTOR, '[data-element-name="mob-room-group-show-less"]')
                    ))
                except (NoSuchElementException, TimeoutException):
                    pass   # No extra offers — that's fine

                # ── Collect all offers for this room ───────────────────────────────
                offer_els = card.find_elements(
                    By.CSS_SELECTOR, '[data-testid="room-offer"]'
                )

                print(f"  [{room_data['room_name']}] → {len(offer_els)} offer(s) found")

                offers = [extract_offer_details(o) for o in offer_els]
                if offers:
                    best = get_cheapest_offer(offers)
                    room_data.update(best)

                all_rooms.append(room_data)
        return all_rooms
    # ======================================= END OF CORE FUNCTIONS ==========================================

    BASE_URL = "https://www.agoda.com/"
    agoda_driver = build_driver(CURR_DIR, headless=IS_VPS)
    agoda_wait = WebDriverWait(agoda_driver, PAGE_TIMEOUT)
    agoda_driver.get(BASE_URL)
    try:
        property_name = TARGET_QUERY
        name_input = agoda_wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'input[data-selenium="textInput"]'))
        )
        name_input.clear()
        name_input.click()
        for i in property_name:
            name_input.send_keys(i)
            time.sleep(random.uniform(0.2, 0.9))
        
        button = agoda_wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[data-element-name="search-button"]'))
        )
        agoda_driver.execute_script("arguments[0].click();", button)
        time.sleep(10)
        try:
            type_1 = agoda_wait.until(EC.presence_of_element_located((By.ID, "contentContainer")))
            content_exists = True
            print("[✓] contentContainer found")
        except TimeoutException:
            content_exists = False
            print("[✗] contentContainer not found")

        if content_exists == True:
            print("It's type 1 search results format.")
            def tokenize(text):
                return set(re.findall(r'\w+', text.lower()))
    
            agoda_wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-selenium="hotel-item"]')
            ))
    
            hotel_items = agoda_driver.find_elements(By.CSS_SELECTOR, '[data-selenium="hotel-item"]')
            print(f"[✓] {len(hotel_items)} hotel(s) found on page\n")
    
            hotels = []
            for item in hotel_items:
                try:
                    name_el = item.find_element(By.CSS_SELECTOR, '[data-testid="property-name-link"]')
                    name    = name_el.text.strip()
                    url     = name_el.get_attribute("href")
                    hotels.append({"name": name, "url": url})
                except NoSuchElementException:
                    continue   # lazy-loaded cards not yet rendered — skip silently
    
            best_match  = None
            best_score  = 0.0
    
            for i, hotel in enumerate(hotels):
                    # Token overlap (handles word order differences)
                q_tokens = tokenize(TARGET_QUERY)
                c_tokens = tokenize(hotel["name"])
                matched  = sum(
                    1 for qt in q_tokens
                    if max((SequenceMatcher(None, qt, ct).ratio() for ct in c_tokens), default=0) >= 0.80
                )
                token_score = matched / len(q_tokens) if q_tokens else 0
    
                # Full string similarity (handles small variations)
                full_score = SequenceMatcher(
                    None,
                    TARGET_QUERY.lower(),
                    hotel["name"].lower()
                ).ratio()
    
                # Combined: weight token overlap more heavily
                score = (token_score * 0.7) + (full_score * 0.3)
    
                print(f"{i+1:<4} {hotel['name']:<55} {score*100:>6.1f}%")
    
                if score > best_score:
                    best_score  = score
                    best_match  = hotel
    
            if best_score >= MATCH_THRESHOLD:
                print(f"\n[✓] MATCH FOUND  : '{best_match['name']}' ({best_score*100:.1f}%)")
                print(f"    URL          : {best_match['url']}")
                scrape_res = scrape_agoda_info(agoda_wait, agoda_driver, best_match["url"], tiket_address, mode=mode_main)
                print(f"scrape_res is: \n{scrape_res}")
            else:
                print("Threshold score not passed")
                return 0
        elif content_exists == False: # TYPE 2 SEARCH RESULTS FUCK AGODA!!!!
            print("It's type 2 search results format.")
            # Filter 1: Country
            all_props = parse_properties_selenium(agoda_driver)
            in_country = [
                p for p in all_props
                if COUNTRY_FILTER.lower() in p["address"].lower()
            ]
            print(f"[Filter 1] {len(in_country)} properties found in {COUNTRY_FILTER}")
    
            # Filter 2: Fuzzy name match
            scored = []
            for p in in_country:
                score = token_overlap_score(property_name, p["name"])
                scored.append({**p, "score": round(score * 100, 1)})
    
            focus_list = [p for p in scored if p["score"] >= THRESHOLD * 100]
            focus_list.sort(key=lambda x: x["score"], reverse=True)
            print(f"[Filter 2] {len(focus_list)} properties above {int(THRESHOLD*100)}% threshold\n")
    
            link_list = []
            for p in focus_list:
                link_list.append(p["link"])
    
            if len(link_list) > 0: # Skip if nothing detected, duh!!!
                print(f"Potential link that we found: {len(link_list)}")
                for i in link_list:
                    print(f"Exploring {i}")
                    scrape_res = scrape_agoda_info(agoda_wait, agoda_driver, i, tiket_address, mode=mode_main)
                    print(f"scrape_res is: \n{scrape_res}")
            else:
                print("Cannot find that property on Agoda!")
                agoda_driver.quit()
                return 0

        agoda_driver.quit()
        return scrape_res
    except Exception as e:
        agoda_driver.quit()
        print("Error:", e)
        return 0

def scrape_hotel_price(
    driver: webdriver.Chrome,
    hotel_url: str,
) -> dict | None:
    """
    Visit a hotel page with date params and extract the displayed price.
    Returns a record dict or None if extraction fails.
    """
    # SUPPORTING FUNCTIONS ======================================
    def safe_text(parent, by, selector):
        """
        Safely extract text from element.
        Return None if element is not found.
        """
        try:
            return parent.find_element(by, selector).text.strip()
        except NoSuchElementException:
            return None

    def safe_texts(parent, by, selector):
        """
        Safely extract multiple texts from elements.
        Return None if elements are not found.
        """
        try:
            elements = parent.find_elements(by, selector)
            texts = [el.text.strip() for el in elements if el.text.strip()]
            return texts if texts else None
        except:
            return None
    # END OF SUPPORTING FUNCTIONS =====================================
    ckin_dt, ckout_dt = get_checkin_checkout()
    hotel_url_new = build_search_url(hotel_url, ckin_dt, ckout_dt)
    # dt = datetime.strptime(ckin_dt, "%Y-%m-%d")  # use your actual format
    # day_weekday = dt.strftime("%A")

    dt_now = datetime.today()
    dt_now_rev = dt_now.strftime("%Y-%m-%d")

    log.info(f"  Visiting: {hotel_url_new}")
    property_name = None
    villa_or_hotel = None  # 1 = hotel (star rating), 2 = villa/apartment (NHA rating)
    rating = None

    date_avail = False
    only_once_pname = True
    new_ckin = ckin_dt
    trials_counter = 0
    while date_avail == False:
        driver.get(hotel_url_new)
        print(f"[DEBUG] Specific URL 1: {hotel_url_new}")
        wait = WebDriverWait(driver, PAGE_TIMEOUT)

        # ── FIX 1: Wait for full page load before doing anything ──────────────
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except TimeoutException:
            log.warning("Page readyState timeout — continuing anyway")

        # ── FIX 2: Wait for body to be non-empty (catches blank headless loads) ─
        try:
            wait.until(lambda d: len(d.find_elements(By.TAG_NAME, "h1")) > 0
                       or len(d.find_elements(By.TAG_NAME, "h2")) > 0)
        except TimeoutException:
            log.warning("Page body appears empty — possible bot block or slow render")

        if only_once_pname == True: # FIND PROPERTY NAME
            # ── FIX 3: Scroll slightly before looking for elements ────────────
            # VPS headless sometimes doesn't trigger lazy-render without scroll
            driver.execute_script("window.scrollTo(0, 300);")
            time.sleep(2)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)

            try:
                hotel_name_elem = wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.HotelInfo_property_name__qba65 h1[data-testid='name']")
                    )
                )
                property_name = hotel_name_elem.text.strip() or None
                log.info(f"property name is: {property_name}")
                try:
                    # Try hotel structure first (5s timeout); 1 = hotel, 2 = villa/apartment
                    try:
                        hotel_rating_div = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "div.HotelInfo_hotel_rating__zJcU7")
                            )
                        )
                        villa_or_hotel = 1
                        rating = len(hotel_rating_div.find_elements(
                            By.CSS_SELECTOR, 'svg[data-testid="hotel-star-rating-full"]'
                        ))
                    except TimeoutException:
                        # Hotel structure absent — try villa/NHA structure
                        try:
                            nha_div = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, '[data-testid="nha-star-rating"]')
                                )
                            )
                            villa_or_hotel = 2
                            rating = len(nha_div.find_elements(
                                By.CSS_SELECTOR, '[data-testid="nha-star-rating-icon-full"]'
                            ))
                        except TimeoutException:
                            # Neither structure found — page likely did not load properly
                            villa_or_hotel = None
                            rating = None
                            log.warning("Neither hotel nor villa rating structure found — page may not have loaded")
                except (TimeoutException, NoSuchElementException):
                    villa_or_hotel = None
                    rating = None
                    log.warning("Could not determine property type or rating")
            except (TimeoutException, NoSuchElementException):
                # ── FIX 4: Fallback selectors for property name ───────────────
                for fallback_sel in [
                    "h1[data-testid='name']",
                    "[class*='HotelInfo_property_name'] h1",
                    "[class*='property_name'] h1",
                    "h1",
                ]:
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, fallback_sel)
                        if el.text.strip():
                            property_name = el.text.strip()
                            log.info(f"property name (fallback) is: {property_name}")
                            break
                    except NoSuchElementException:
                        continue

                if not property_name:
                    log.warning("Could not find property name — page may not have loaded properly")

                # property_name = None
            only_once_pname = False

        # CHECK IF DATE AVAILABLE OR NOT
        try:
            try:
                container = wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.RoomListErrorView_wrapper__jy94T")
                    )
                )
                if container:
                    trials_counter += 1
                    if trials_counter > 3:
                        time.sleep(5)
                        raise RuntimeError("Trials changing date exceeding limits (3) times.")

                    log.info("The availability on current date is not available, renew the date range.")
                    new_ckin, new_ckout = renew_checkin_checkout(new_ckin)
                    hotel_url_new = build_search_url(hotel_url_new, checkin=new_ckin, checkout=new_ckout)
                    time.sleep(7)
                    continue
            except (TimeoutException, NoSuchElementException):
                log.info("Room may be available!!!!")
        except (TimeoutException, NoSuchElementException):
            log.info("Unknown exceptions, can't find any booking data at all, check actual conditions.")
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'last_minute'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}, {}
        except RuntimeError as e:
            log.info(f"Caught a runtime error: {e}, later we will check with Agoda.")
            tiket_address = None
            try:
                addr_el = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '.LocationSection_address__zx77F')
                ))
                tiket_address = addr_el.text.strip()
                log.info(f"Address: {tiket_address}")
            except Exception as addr_err:
                log.info(f"Could not retrieve address element (page in error state): {addr_err.__class__.__name__}")
            pending_dict = ({'property_name': property_name, 'address':tiket_address}) # APPEND FOR LATER SEARCH WITH AGODA
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'last_minute'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}, pending_dict

            # try:
                # agoda_scrape = scrape_agoda(property_name, tiket_address)
                # results = []
                # print(f"Agoda scrape detail is : {agoda_scrape}")
                # data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'last_minute'}
                # if type(agoda_scrape) != int:
                #     for k in agoda_scrape:
                #         data["room_type"] = k["room_name"]
                #         data["price"] = str(k["discounted_price"])
                #         data["notes"] = [k["breakfast"], k["cancellation_policy"], k["payment_condition"]]
                #         results.append(data)
                #     return {"property_name": property_name, "total_rows": len(results), "rows": results}
                # else:
                #     print("Scrape didn't found any records")
                #     results = []
                #     data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'last_minute'}
                #     results.append(data)
                #     return {"property_name": property_name, "total_rows": 0, "rows": results}

            # except TimeoutException:
            #     print("[✗] Address element not found")
            #     results = []
            #     data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'last_minute'}
            #     results.append(data)
            #     return {"property_name": property_name, "total_rows": 0, "rows": results}

        # find section with room informations
        # try:
        #     driver.find_element(
        #         By.CSS_SELECTOR,
        #         "div.MainRoomGroupLists_room_group_lists_container__04n19"
        #     )
        # except NoSuchElementException:
        #     # sometimes table rows are direct children; fallback to container
        #     log.info("NoSuchElementException (main) triggered!!! Fallback to sending just NaN")
        #     results = []
        #     data = {"room_type": None, "price": None, "notes": None, "weekday": day_weekday, "date_scrapped": dt_now_rev}
        #     results.append(data)
        #     return {"property_name": property_name, "total_rows": 0, "rows": results}
        
        # ── FIND ROOM CONTAINER ───────────────────────────────────────────────
        # ── FIX 6: Scroll page to trigger lazy-load BEFORE looking for rooms ──
        log.info("Scrolling to trigger lazy-load before room scan...")
        for scroll_pos in [300, 600, 900, 1200]:
            driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
            time.sleep(1.5)

        # ── FIX 7: Explicit wait for room container instead of find_element ───
        ROOM_CONTAINER_SELECTORS = [
            "div.MainRoomGroupLists_room_group_lists_container__04n19",
            "[class*='MainRoomGroupLists_room_group_lists_container']",
            "[class*='room_group_lists_container']",
        ]

        room_container_found = False
        for sel in ROOM_CONTAINER_SELECTORS:
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                room_container_found = True
                log.info(f"Room container found via: {sel}")
                break
            except TimeoutException:
                log.warning(f"Room container not found with selector: {sel}")
                continue

        if not room_container_found:
            log.warning("NoSuchElementException (main) triggered — fallback to NaN")
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'last_minute'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}, {}


        time.sleep(5)
        rows = driver.find_elements(By.CSS_SELECTOR, "section[data-testid='room-group-item-section']")
        log.info(f"Total room rows found: {len(rows)}")

        # Wait until ALL room title containers appear
        # title_containers = WebDriverWait(driver, 10).until(
        #     EC.presence_of_element_located((
        #         By.CSS_SELECTOR,
        #         "div.FacilitiesNudges_mobile_room_group_expanded_title__EmlX5"
        #     ))
        # )

        results = []
        for _, row in enumerate(rows, start=1):
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'last_minute'}
            try:
                room_cards = row.find_element(
                    By.CSS_SELECTOR,
                    "div.RoomGroupItem_room_group_lists_main_container__CZ7DL"
                )
                time.sleep(5)
                # ROOM TYPE -----------------------------------------------------------------------
                room_type = None
                try:
                    room_type = row.text.split("\n")[0]
                except Exception as e:
                    print(f"Error due to {e}")
                
                log.info(f"room_type name is: {room_type}")
                time.sleep(5)
                # FEATURES -----------------------------------------------------------------------
                features = []

                # Bed type
                bed_type = safe_text(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.BedTypesContent_bed_types_main_content_wrapper__c8T0W span"
                )
                if bed_type:
                    features.append(bed_type)
                log.info(f"bed_type name is: {bed_type}")

                # Room nudges/features
                extra_features = safe_texts(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.FacilitiesNudges_room_group_variables_info_item__io0wb span"
                )
                if extra_features:
                    features.extend(extra_features)
                log.info(f"extra_features name is: {extra_features}")

                # Breakfast labels
                breakfast = safe_texts(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.FeatureLabels_feature_labels_container__6SJTk span"
                )
                if breakfast:
                    features.extend(breakfast)
                log.info(f"breakfast name is: {breakfast}")

                # Cancellation policy
                cancellation = safe_text(
                    room_cards,
                    By.CSS_SELECTOR,
                    "span[data-testid='cancellation-policies-title']"
                )
                if cancellation:
                    features.append(cancellation)

                # Value-added section
                bonuses = safe_texts(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.ValueAddedSection_value_added_section_container__812zf span"
                )
                if bonuses:
                    features.extend(bonuses)

                # # Remove duplicates
                # if features:
                #     features = list(dict.fromkeys(features))
                # else:
                #     features = None
                # time.sleep(5)

                # # DISCOUNTED PRICE -----------------------------------------------------------------------
                # discounted_price = safe_text(
                #     room_cards,
                #     By.CSS_SELECTOR,
                #     "div.RatePlanPrice_final_price_wrapper__t1r9i div.Text_variant_price__wu_WD"
                # )
                # time.sleep(5)
                # log.info(f"discounted_price is: {discounted_price}")

                features = list(dict.fromkeys(features)) if features else None

                # ── FIX 9: Scroll price into view before reading it ───────────
                try:
                    price_el = row.find_element(By.CSS_SELECTOR,
                        "div.RatePlanPrice_final_price_wrapper__t1r9i div.Text_variant_price__wu_WD")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", price_el)
                    time.sleep(1.5)
                    discounted_price = price_el.text.strip()
                except NoSuchElementException:
                    discounted_price = None
                log.info(f"discounted_price is: {discounted_price}")

                # STORE RESULT ---------------------------------------------------------------------------
                data["room_type"] = room_type
                data["price"] = discounted_price
                data["notes"] = features
                results.append(data)
            except Exception as e:
                print(f" [A] error: {e}")
                continue
        date_avail = True
    
    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": len(rows), "rows": results}, {}

def scrape_hotel_price_early_book(
    driver: webdriver.Chrome,
    hotel_url: str,
) -> dict | None:
    """
    Visit a hotel page with date params and extract the displayed price.
    Returns a record dict or None if extraction fails.
    """
    # SUPPORTING FUNCTIONS ======================================
    def safe_text(parent, by, selector):
        """
        Safely extract text from element.
        Return None if element is not found.
        """
        try:
            return parent.find_element(by, selector).text.strip()
        except NoSuchElementException:
            return None

    def safe_texts(parent, by, selector):
        """
        Safely extract multiple texts from elements.
        Return None if elements are not found.
        """
        try:
            elements = parent.find_elements(by, selector)
            texts = [el.text.strip() for el in elements if el.text.strip()]
            return texts if texts else None
        except:
            return None
    # END OF SUPPORTING FUNCTIONS =====================================
    ckin_dt, _ = get_checkin_checkout()
    ckin_dt_true = datetime.strptime(ckin_dt, "%Y-%m-%d")
    ckin_dt_true = ckin_dt_true + timedelta(days=60)
    ckout_dt = ckin_dt_true + timedelta(days=1)
    hotel_url_new = build_search_url(hotel_url, checkin=ckin_dt_true, checkout=ckout_dt)
    # dt = datetime.strptime(ckin_dt, "%Y-%m-%d")  # use your actual format
    # day_weekday = dt.strftime("%A")

    dt_now = datetime.today()
    dt_now_rev = dt_now.strftime("%Y-%m-%d")

    log.info(f"  Visiting: {hotel_url_new}")
    property_name = None
    villa_or_hotel = None  # 1 = hotel (star rating), 2 = villa/apartment (NHA rating)
    rating = None

    date_avail = False
    only_once_pname = True
    new_ckin = ckin_dt_true.strftime("%Y-%m-%d")
    trials_counter = 0
    while date_avail == False:
        driver.get(hotel_url_new)
        print(f"[DEBUG] Specific URL 2: {hotel_url_new}")
        wait = WebDriverWait(driver, PAGE_TIMEOUT)

        # ── FIX 1: Wait for full page load before doing anything ──────────────
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except TimeoutException:
            log.warning("Page readyState timeout — continuing anyway")

        # ── FIX 2: Wait for body to be non-empty (catches blank headless loads) ─
        try:
            wait.until(lambda d: len(d.find_elements(By.TAG_NAME, "h1")) > 0
                       or len(d.find_elements(By.TAG_NAME, "h2")) > 0)
        except TimeoutException:
            log.warning("Page body appears empty — possible bot block or slow render")

        if only_once_pname == True: # FIND PROPERTY NAME
            # ── FIX 3: Scroll slightly before looking for elements ────────────
            # VPS headless sometimes doesn't trigger lazy-render without scroll
            driver.execute_script("window.scrollTo(0, 300);")
            time.sleep(2)
            driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)

            try:
                hotel_name_elem = wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.HotelInfo_property_name__qba65 h1[data-testid='name']")
                    )
                )
                property_name = hotel_name_elem.text.strip() or None
                log.info(f"property name is: {property_name}")
                try:
                    # Try hotel structure first (5s timeout); 1 = hotel, 2 = villa/apartment
                    try:
                        hotel_rating_div = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "div.HotelInfo_hotel_rating__zJcU7")
                            )
                        )
                        villa_or_hotel = 1
                        rating = len(hotel_rating_div.find_elements(
                            By.CSS_SELECTOR, 'svg[data-testid="hotel-star-rating-full"]'
                        ))
                    except TimeoutException:
                        # Hotel structure absent — try villa/NHA structure
                        try:
                            nha_div = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located(
                                    (By.CSS_SELECTOR, '[data-testid="nha-star-rating"]')
                                )
                            )
                            villa_or_hotel = 2
                            rating = len(nha_div.find_elements(
                                By.CSS_SELECTOR, '[data-testid="nha-star-rating-icon-full"]'
                            ))
                        except TimeoutException:
                            # Neither structure found — page likely did not load properly
                            villa_or_hotel = None
                            rating = None
                            log.warning("Neither hotel nor villa rating structure found — page may not have loaded")
                except (TimeoutException, NoSuchElementException):
                    villa_or_hotel = None
                    rating = None
                    log.warning("Could not determine property type or rating")
            except (TimeoutException, NoSuchElementException):
                # ── FIX 4: Fallback selectors for property name ───────────────
                for fallback_sel in [
                    "h1[data-testid='name']",
                    "[class*='HotelInfo_property_name'] h1",
                    "[class*='property_name'] h1",
                    "h1",
                ]:
                    try:
                        el = driver.find_element(By.CSS_SELECTOR, fallback_sel)
                        if el.text.strip():
                            property_name = el.text.strip()
                            log.info(f"property name (fallback) is: {property_name}")
                            break
                    except NoSuchElementException:
                        continue

                if not property_name:
                    log.warning("Could not find property name — page may not have loaded properly")

                # property_name = None
            only_once_pname = False

        # CHECK IF DATE AVAILABLE OR NOT
        try:
            try:
                container = wait.until(
                    EC.presence_of_element_located(
                        (By.CSS_SELECTOR, "div.RoomListErrorView_wrapper__jy94T")
                    )
                )
                if container:
                    trials_counter += 1
                    if trials_counter > 3:
                        time.sleep(5)
                        raise RuntimeError("Trials changing date exceeding limits (3) times.")
                    log.info("The availability on current date is not available, renew the date range.")

                    new_ckin, new_ckout = renew_checkin_checkout(new_ckin)
                    hotel_url_new = build_search_url(hotel_url_new, checkin=new_ckin, checkout=new_ckout)
                    time.sleep(7)
                    continue
            except (TimeoutException, NoSuchElementException):
                log.info("Room may be available!!!!")
        except (TimeoutException, NoSuchElementException):
            log.info("Unknown exceptions, can't find any booking data at all, check actual conditions.")
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'early-book'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}, {}
        except RuntimeError as e:
            log.info(f"Caught a runtime error: {e}, later we will check with Agoda.")
            tiket_address = None
            try:
                addr_el = wait.until(EC.presence_of_element_located(
                    (By.CSS_SELECTOR, '.LocationSection_address__zx77F')
                ))
                tiket_address = addr_el.text.strip()
                log.info(f"Address: {tiket_address}")
            except Exception as addr_err:
                log.info(f"Could not retrieve address element (page in error state): {addr_err.__class__.__name__}")
            pending_dict = ({'property_name': property_name, 'address':tiket_address}) # APPEND FOR LATER SEARCH WITH AGODA
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'early-book'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}, pending_dict

            # try:
            #     addr_el = wait.until(EC.presence_of_element_located(
            #         (By.CSS_SELECTOR, '.LocationSection_address__zx77F')
            #     ))
            #     tiket_address = addr_el.text.strip()
            #     print(f"Address: {tiket_address}")
            #     agoda_scrape = scrape_agoda(property_name, tiket_address)
            #     results = []
            #     print(f"Agoda scrape detail is : {agoda_scrape}")
            #     data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'early-book'}
            #     if type(agoda_scrape) != int:
            #         for k in agoda_scrape:
            #             data["room_type"] = k["room_name"]
            #             data["price"] = str(k["discounted_price"])
            #             data["notes"] = [k["breakfast"], k["cancellation_policy"], k["payment_condition"]]
            #             results.append(data)
            #         return {"property_name": property_name, "total_rows": len(results), "rows": results}
            #     else:
            #         print("Scrape didn't found any records")
            #         results = []
            #         data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'early-book'}
            #         results.append(data)
            #         return {"property_name": property_name, "total_rows": 0, "rows": results}

            # except TimeoutException:
            #     print("[✗] Address element not found")
            #     results = []
            #     data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'early-book'}
            #     results.append(data)
            #     return {"property_name": property_name, "total_rows": 0, "rows": results}

        # find section with room informations
        # try:
        #     driver.find_element(
        #         By.CSS_SELECTOR,
        #         "div.MainRoomGroupLists_room_group_lists_container__04n19"
        #     )
        # except NoSuchElementException:
        #     # sometimes table rows are direct children; fallback to container
        #     log.info("NoSuchElementException (main) triggered!!! Fallback to sending just NaN")
        #     results = []
        #     data = {"room_type": None, "price": None, "notes": None, "weekday": day_weekday, "date_scrapped": dt_now_rev}
        #     results.append(data)
        #     return {"property_name": property_name, "total_rows": 0, "rows": results}
        
        # ── FIND ROOM CONTAINER ───────────────────────────────────────────────
        # ── FIX 6: Scroll page to trigger lazy-load BEFORE looking for rooms ──
        log.info("Scrolling to trigger lazy-load before room scan...")
        for scroll_pos in [300, 600, 900, 1200]:
            driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
            time.sleep(1.5)

        # ── FIX 7: Explicit wait for room container instead of find_element ───
        ROOM_CONTAINER_SELECTORS = [
            "div.MainRoomGroupLists_room_group_lists_container__04n19",
            "[class*='MainRoomGroupLists_room_group_lists_container']",
            "[class*='room_group_lists_container']",
        ]

        room_container_found = False
        for sel in ROOM_CONTAINER_SELECTORS:
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                room_container_found = True
                log.info(f"Room container found via: {sel}")
                break
            except TimeoutException:
                log.warning(f"Room container not found with selector: {sel}")
                continue

        if not room_container_found:
            log.warning("NoSuchElementException (main) triggered — fallback to NaN")
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'early-book'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}, {}


        time.sleep(5)
        rows = driver.find_elements(By.CSS_SELECTOR, "section[data-testid='room-group-item-section']")
        log.info(f"Total room rows found: {len(rows)}")

        # Wait until ALL room title containers appear
        # title_containers = WebDriverWait(driver, 10).until(
        #     EC.presence_of_element_located((
        #         By.CSS_SELECTOR,
        #         "div.FacilitiesNudges_mobile_room_group_expanded_title__EmlX5"
        #     ))
        # )

        results = []
        for _, row in enumerate(rows, start=1):
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': new_ckin, 'category':'early-book'}
            try:
                room_cards = row.find_element(
                    By.CSS_SELECTOR,
                    "div.RoomGroupItem_room_group_lists_main_container__CZ7DL"
                )
                time.sleep(5)
                # ROOM TYPE -----------------------------------------------------------------------
                room_type = None
                try:
                    room_type = row.text.split("\n")[0]
                except Exception as e:
                    print(f"Error due to {e}")
                
                log.info(f"room_type name is: {room_type}")
                time.sleep(5)
                # FEATURES -----------------------------------------------------------------------
                features = []

                # Bed type
                bed_type = safe_text(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.BedTypesContent_bed_types_main_content_wrapper__c8T0W span"
                )
                if bed_type:
                    features.append(bed_type)
                log.info(f"bed_type name is: {bed_type}")

                # Room nudges/features
                extra_features = safe_texts(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.FacilitiesNudges_room_group_variables_info_item__io0wb span"
                )
                if extra_features:
                    features.extend(extra_features)
                log.info(f"extra_features name is: {extra_features}")

                # Breakfast labels
                breakfast = safe_texts(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.FeatureLabels_feature_labels_container__6SJTk span"
                )
                if breakfast:
                    features.extend(breakfast)
                log.info(f"breakfast name is: {breakfast}")

                # Cancellation policy
                cancellation = safe_text(
                    room_cards,
                    By.CSS_SELECTOR,
                    "span[data-testid='cancellation-policies-title']"
                )
                if cancellation:
                    features.append(cancellation)

                # Value-added section
                bonuses = safe_texts(
                    room_cards,
                    By.CSS_SELECTOR,
                    "div.ValueAddedSection_value_added_section_container__812zf span"
                )
                if bonuses:
                    features.extend(bonuses)

                # # Remove duplicates
                # if features:
                #     features = list(dict.fromkeys(features))
                # else:
                #     features = None
                # time.sleep(5)

                # # DISCOUNTED PRICE -----------------------------------------------------------------------
                # discounted_price = safe_text(
                #     room_cards,
                #     By.CSS_SELECTOR,
                #     "div.RatePlanPrice_final_price_wrapper__t1r9i div.Text_variant_price__wu_WD"
                # )
                # time.sleep(5)
                # log.info(f"discounted_price is: {discounted_price}")

                features = list(dict.fromkeys(features)) if features else None

                # ── FIX 9: Scroll price into view before reading it ───────────
                try:
                    price_el = row.find_element(By.CSS_SELECTOR,
                        "div.RatePlanPrice_final_price_wrapper__t1r9i div.Text_variant_price__wu_WD")
                    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", price_el)
                    time.sleep(1.5)
                    discounted_price = price_el.text.strip()
                except NoSuchElementException:
                    discounted_price = None
                log.info(f"discounted_price is: {discounted_price}")

                # STORE RESULT ---------------------------------------------------------------------------
                data["room_type"] = room_type
                data["price"] = discounted_price
                data["notes"] = features
                results.append(data)
            except Exception as e:
                print(f" [A] error: {e}")
                continue
        date_avail = True
    
    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": len(rows), "rows": results}, {}

def dataframe_processing(new_records, ota_name):
    data_df = pd.DataFrame()
    for i in new_records:
        room_type = []
        ota_source = []
        category = []
        price_details = []
        notes_details = []
        property_list = []
        dt_scrapped_list = []
        target_date = []
        villa_or_hotel_list = []
        rating_list = []
        sub_data = {}
        for ii in range(len(i['rows'])):
            property_list.append(i['property_name'])
            ota_source.append(ota_name)
            category.append(i['rows'][ii]['category'])
            dt_scrapped_list.append(i['rows'][ii]['date_scrapped'])
            villa_or_hotel_list.append(i['villa_or_hotel'])
            rating_list.append(i['rating'])
            if i['rows'][ii]['room_type'] is not None:
                room_type.append(i['rows'][ii]['room_type'])
            else:
                room_type.append(None)

            if i['rows'][ii]['price'] is not None:
                price_details.append(i['rows'][ii]['price'])
            else:
                price_details.append(None)

            if i['rows'][ii]['notes'] is not None:
                notes_details.append(i['rows'][ii]['notes'])
            else:
                notes_details.append(None)

            if i['rows'][ii]['target_date'] is not None:
                target_date.append(i['rows'][ii]['target_date'])
            else:
                target_date.append(None)
        sub_data['property_name'] = property_list
        sub_data['room_type'] = room_type
        sub_data["ota_source"] = ota_source
        sub_data['price_details'] = price_details
        sub_data['notes_details'] = notes_details
        sub_data['target_date'] = target_date
        sub_data["category"] = category
        sub_data['date_scrapped'] = dt_scrapped_list
        sub_data['villa_or_hotel'] = villa_or_hotel_list
        sub_data['rating'] = rating_list
        major_data = pd.DataFrame(sub_data)
        data_df = pd.concat([data_df, major_data])
    return data_df

def cleaning_data(data_df):
    data_df2 = data_df.copy()
    data_df2 = data_df2.reset_index(drop=True)

    data_df2["price_details"] = (
        data_df2["price_details"]
        .astype(str)
        .str.replace("IDR", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.strip()
    )

    data_df2["price_details"] = pd.to_numeric(data_df2["price_details"], errors="coerce")
    data_df2["price_details"] = data_df2["price_details"].fillna(0).astype(int)
    return data_df2

def save_load_database(focus_df):
    # data_df2 = pd.DataFrame()
    data_df2 = focus_df.copy()
    if os.path.exists("scraping_database_tiket_lm.pkl"):
        loaded_df = pd.read_pickle("scraping_database_tiket_lm.pkl")
        data_df2 = pd.concat([data_df2, loaded_df])
        data_df2 = data_df2.reset_index(drop=True)
        data_df2.to_pickle("scraping_database_tiket_lm.pkl")

    else:
        data_df2.to_pickle("scraping_database_tiket_lm.pkl")

def save_load_database_eb(focus_df):
    # data_df2 = pd.DataFrame()
    data_df2 = focus_df.copy()
    if os.path.exists("scraping_database_tiket_eb.pkl"):
        loaded_df = pd.read_pickle("scraping_database_tiket_eb.pkl")
        data_df2 = pd.concat([data_df2, loaded_df])
        data_df2 = data_df2.reset_index(drop=True)
        data_df2.to_pickle("scraping_database_tiket_eb.pkl")

    else:
        data_df2.to_pickle("scraping_database_tiket_eb.pkl")


# ── main pipeline ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    areas = ["Ubud", "Canggu", "Tabanan", "Seminyak", "Kuta", "Denpasar", "Kintamani",
            "Bedugul", "Karangasem", "Nusa Dua", "Sanur", "Lombok", "Mataram", "Malang", "Batu", 
            "Tretes", "Lembang", "Ciwidey", "Bogor", "Pengalengan"]
    # areas = ["Ubud", "Canggu", "Tabanan", "Seminyak", "Kuta", "Kintamani",
    #         "Bedugul", "Karangasem"]

    PROJECT_FOLDER   = os.path.join(os.getcwd(), "sitemaps")
    CHILD_FOLDER     = os.path.join(os.getcwd(), "child-sitemaps")
    OTHER_CHILD_FOLDER = os.path.join(os.getcwd(), "other-child-sitemaps")
    CURR_DIR         = os.path.dirname(os.getcwd())
    SITEMAP_INDEX    = "https://www.tiket.com/sitemap/id-id/index.xml.gz"

    # Auto-detect VPS (Linux without display) → force headless
    # IS_VPS = platform.system() == "Linux" and not os.environ.get("DISPLAY")
    
    print(f"Running in {'headless (VPS)' if IS_VPS else 'headed (local)'} mode")
    aggregate_url = False #ACTIVATE IF YOU WANT TO UPDATE URL LISTS
    tmp_profile = None
    def get_base_url(url):
        return url.strip().split('?')[0] + '?'

    if aggregate_url == True:
        # Step 1 — download index.xml.gz
        gz_path = download_sitemap(SITEMAP_INDEX, PROJECT_FOLDER, headless=IS_VPS)

        # Step 2 — extract gz → xml
        xml_path = extract_gz(gz_path)

        # Step 3 — parse child sitemap URLs
        child_urls = parse_locs(1, xml_path)

        # Step 4 — filter & print (replace with your next pipeline step)
        PDP_KEYWORDS = ["hotel-pdp", "homes-pdp", "homes-villa", "homes-glamping", "homes-cottage"]
        relevant = [u for u in child_urls if any(k in u for k in PDP_KEYWORDS)]
        log.info(f"\nRelevant child sitemaps: {len(relevant)}")
        for u in relevant:
            print(f"  {u}")

        # There will be 2 possibilities: sitemaps that have "...area.xml" or "...city.xml" or "...region.xml"
        # will be scrapped traditionally by using scrolling and click
        # However, sites that doesn't contain those elements already have ready to access url
        
        log.info("\n[Step 3] Downloading child sitemaps...")
        debug_counter = 0
        second_filter = ["area", "city", "region"]
        aggregate_url = []
        for i, child_url in enumerate(relevant, 1):
            debug_counter += 1
            property_urls = {area: [] for area in areas}
            if debug_counter > 15: break
            log.info(f"  [{i}/{len(relevant)}] {child_url.split('/')[-1]}")
            try:
                filter_url = any(keyword in child_url for keyword in second_filter)
                if filter_url:
                    # print(f"[DEBUG] Skipping filtered sections and move on to villas-pdp section.")
                    # continue
                    gz_child = download_sitemap(child_url, CHILD_FOLDER, headless=IS_VPS)
                    xml_child = extract_gz(gz_child)
                    locs_child = parse_locs(2, xml_child)

                    found = parse_property_urls(xml_child, areas)
                    for area in areas:
                        property_urls[area].extend(found[area])

                    # step 5 - ikutin pipeline booking.com -> eksplorasi 
                    driver_next = build_driver(CURR_DIR, headless=IS_VPS)
                    for k, v in property_urls.items():
                        log.info(f"Focusing search on area {k}")
                        log.info(f"With URL {v}")
                        if len(v) > 0:
                            list_properties = scrape_sitemaps(v[0], driver_next)
                        else:
                            list_properties = []
                        aggregate_url.extend(list_properties)
                        log.info(f"Total URL captured is {len(aggregate_url)} URL")

                    if os.path.exists("URL_pool_list.txt"):
                        for i in aggregate_url:
                            with open("URL_pool_list.txt", "a") as file:
                                file.write(f"{i}\n")
                    else:
                        raise RuntimeError("No URL_pool_list.txt found, make it first please.")
                    driver_next.quit()
                else:
                    gz_child = download_sitemap(child_url, OTHER_CHILD_FOLDER, headless=IS_VPS)
                    xml_child = extract_gz(gz_child)
                    log.info(f"[DEBUG] xml child is : {xml_child}")
                    locs_child = extract_indonesia_urls(xml_child)
                    log.info(f"[DEBUG] locs child is : {locs_child[0]}")
                    log.info(f"[DEBUG] locs child length is : {len(locs_child)}")
                    # WE ALREADY GOT THE URL SO JUST DIRECTLY PUT IT TO TXT FILE!!!
                    if os.path.exists("URL_pool_list.txt"):
                        for i in locs_child:
                            with open("URL_pool_list.txt", "a") as file:
                                file.write(f"{i}\n")
            except Exception as e:
                log.info(f" [A] error: {e}")
                continue

    # ----- OPEN THE URL_POOL_LIST.TXT AND START OPENING ONE BY ONE
    try:
        driver = build_driver(CURR_DIR, headless=IS_VPS)
        new_urls = []
        debug_counter = 0
        allowed_proceed = False
        only_once = True
        break_signal = False
        if os.path.exists("checkpoint_save.txt"):
            with open("checkpoint_save.txt", "r") as f:
                cross_check = f.read()
                log.info(f"cross_check is : {cross_check}")

        with open("URL_pool_list.txt", "r") as file:
            lines = file.readlines()
            last_line = lines[-1].strip()
            print(f"[DEBUG] last_line is {last_line}")

            i = 0
            while i < len(lines):
                # print(f"[DEBUG] lines[i] is {lines[i]}")
                cross_check_result = get_base_url(last_line) == get_base_url(cross_check)
                if lines[i].strip() == last_line or cross_check_result:
                    i = 0
                    break_signal = True
                
                if only_once == True and os.path.exists("checkpoint_save.txt"):
                    # result = bool(re.search(str(lines[i]), str(cross_check)))
                    # print(f"[DEBUG] result is {result}")
                    result = get_base_url(lines[i]) == get_base_url(cross_check)
                    if result == True:
                        log.info("Found last checkpoint!!!")
                        allowed_proceed = True
                        only_once = False
                        continue

                if allowed_proceed == True or not os.path.exists("checkpoint_save.txt"):
                    new_urls.append(lines[i])
                    debug_counter += 1

                i += 1
                if break_signal == True or debug_counter > MAX_PROPERTIES: 
                    log.info("Safe guarding with 15 properties limiter, breaking algorithm now!")
                    break

        targets = new_urls[:MAX_PROPERTIES]
        print(f"Targeting {len(targets)} hotels this session.")

        # BATCH_SIZE = 5
        # batch = []

        new_records = []
        new_records_eb = []
        pending_list_lm = []
        pending_list_eb = []
        for i, url in enumerate(targets, 1):
            log.info(f"[{i}/{len(targets)}] Scraping …")
            record, pending_lm = scrape_hotel_price(driver, url)
            record_eb, pending_eb = scrape_hotel_price_early_book(driver, url)
            time.sleep(3)
            if record:
                new_records.append(record)
                with open("checkpoint_save.txt", "w") as f:
                    f.write(f"{url}\n")

            if record_eb:
                new_records_eb.append(record_eb)

            if pending_lm:
                pending_list_lm.append(pending_lm)

            if pending_eb:
                pending_list_eb.append(pending_eb)
            time.sleep(5)   

        # Flush any remaining records
        # if batch:
        #     df_batch = cleaning_data(dataframe_processing(batch))
        #     save_load_database(df_batch)
        #     log.info(f"Flushed final batch of {len(batch)} records.")
        log.info(f"[DEBUG] Session complete.")

        # print(f"[DEBUG] check scraping result: \n{new_records}")
        df = dataframe_processing(new_records, "tiket.com")
        df_cleaned = cleaning_data(df)
        save_load_database(df_cleaned)

        df_eb = dataframe_processing(new_records_eb, "tiket.com")
        df_cleaned_eb = cleaning_data(df_eb)
        save_load_database_eb(df_cleaned_eb)
        if driver:
            driver.quit()

        # TIKET.COM PIPELINE DONE NOW CHECK N/A ROOM WITH AGODA
        log.info(f"[DEBUG] TIKET.COM SESSION IS DONE, LET'S CHECK PENDING LIST PROPERTY ON AGODA")
        if len(pending_list_eb) > 0:
            print(f"Early book booking type to be checked by Agoda, list exist with {len(pending_list_eb)} elements detected")
            dt_now = datetime.today()
            dt_now_rev = dt_now.strftime("%Y-%m-%d")
            for elem in pending_list_eb:
                if elem:
                    agoda_scrape = scrape_agoda(elem["property_name"], elem["address"], "eb")
                    results = []
                    print(f"Agoda scrape detail is : {agoda_scrape}")
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': None, 'category':'early-book'}
                    if type(agoda_scrape) != int:
                        for k in agoda_scrape:
                            data["room_type"] = k["room_name"]
                            data["price"] = str(k["discounted_price"])
                            data["notes"] = [k["breakfast"], k["cancellation_policy"], k["payment_condition"]]
                            data["target_date"] = k["target_date"]
                            results.append(data)
                        to_be_continued_eb = [{"property_name": elem["property_name"], "total_rows": len(results), "rows": results}]

                        df_agoda_eb = dataframe_processing(to_be_continued_eb, "Agoda")
                        df_cleaned_agoda_eb = cleaning_data(df_agoda_eb)
                        if os.path.exists("scraping_database_agoda_eb.pkl"):
                            loaded_df = pd.read_pickle("scraping_database_agoda_eb.pkl")
                            df_cleaned_agoda_eb = pd.concat([df_cleaned_agoda_eb, loaded_df])
                            df_cleaned_agoda_eb = df_cleaned_agoda_eb.reset_index(drop=True)
                            df_cleaned_agoda_eb.to_pickle("scraping_database_agoda_eb.pkl")

                        else:
                            df_agoda_eb.to_pickle("scraping_database_agoda_eb.pkl")
                else:
                    print("No element Early Book detected, skipping!")
        else:
            print("No Early book booking type to be checked by Agoda!")

        if len(pending_list_lm) > 0:
            print(f"Last Minute booking type to be checked by Agoda, list exist with {len(pending_list_lm)} elements detected")
            dt_now = datetime.today()
            dt_now_rev = dt_now.strftime("%Y-%m-%d")
            for elem in pending_list_lm:
                if elem:
                    agoda_scrape = scrape_agoda(elem["property_name"], elem["address"], "lm")
                    results = []
                    print(f"Agoda scrape detail is : {agoda_scrape}")
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date': None, 'category':'last-minute'}
                    if type(agoda_scrape) != int:
                        for k in agoda_scrape:
                            data["room_type"] = k["room_name"]
                            data["price"] = str(k["discounted_price"])
                            data["notes"] = [k["breakfast"], k["cancellation_policy"], k["payment_condition"]]
                            data["target_date"] = k["target_date"]
                            results.append(data)
                        to_be_continued_lm = [{"property_name": elem["property_name"], "total_rows": len(results), "rows": results}]

                        df_agoda_lm = dataframe_processing(to_be_continued_lm, "Agoda")
                        df_cleaned_agoda_lm = cleaning_data(df_agoda_lm)
                        if os.path.exists("scraping_database_agoda_lm.pkl"):
                            loaded_df = pd.read_pickle("scraping_database_agoda_lm.pkl")
                            df_cleaned_agoda_lm = pd.concat([df_cleaned_agoda_lm, loaded_df])
                            df_cleaned_agoda_lm = df_cleaned_agoda_lm.reset_index(drop=True)
                            df_cleaned_agoda_lm.to_pickle("scraping_database_agoda_lm.pkl")

                        else:
                            df_cleaned_agoda_lm.to_pickle("scraping_database_agoda_lm.pkl")
                else:
                    print("No element Last Minute detected, skipping!")
        else:
            print("No Last Minute booking type to be checked by Agoda!")

    except Exception as e:
        log.info(f" [A] error: {e}")
    finally:
        if driver:
            driver.quit()
        log.info("Driver shut down. Session END.")
        log.info("=" * 50)   
