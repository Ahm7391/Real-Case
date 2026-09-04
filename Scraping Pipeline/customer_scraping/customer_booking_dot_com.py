import time
import random, tempfile
import os, json, re, shutil
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse
 
import pandas as pd
import numpy as np
from selenium import webdriver
from selenium.webdriver.common.timeouts import Timeouts
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import StaleElementReferenceException, ElementClickInterceptedException
from match_url import main_processing

from urllib.parse import urlparse, parse_qs, urlencode, urlunparse 
from difflib import SequenceMatcher

# CONFIG AND ROBOTS.TXT RULES
PKL_FILE       = "ubud_hotels.pkl"
LOG_FILE       = "scraper.log"
MAX_PROPERTIES = 30           # max hotels to scrape per session
SLEEP_MIN      = 5           # seconds between requests (min)
SLEEP_MAX      = 7           # seconds between requests (max)
PAGE_TIMEOUT   = 20          # seconds to wait for DOM element
DRIVER_RECYCLE_EVERY = 10   
 
# Ubud search config
DEST_ID        = "-2701757"  # Ubud's stable Booking.com city ID
DEST_TYPE      = "city"
LANG           = "en-us"
ADULTS         = 2
ROOMS          = 1
CHILDREN       = 0

DEBUG_SCREENSHOT = 1

# Manual-scrape location gateway: a matched property PASSES only if its address
# contains ANY of these keywords (case-insensitive substring match). Tweak
# freely — add a country, province, city, or area to broaden/narrow acceptance.
ALLOWED_LOCATIONS = ["Indonesia"]
 
# Robots.txt allowed paths
ALLOWED_PATH_PREFIXES = [
    "/searchresults.html",
    "/hotel/id/",
]
DISALLOWED_PATH_PREFIXES = [
    "/book.html", "/mybooking.html", "/confirmation.html",
    "/reviewlist.", "/photo.", "/general.", "/s/",
    "/hotelsonmap.", "/anysearch.", "/flexiproduct",
    "/fragment.", "/markers_on_map", "/track",
]

# LOGGING
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger(__name__)

# CHECKING ROBOTS.TXT 
def is_allowed(url: str) -> bool:
    """Return True if URL path is within robots.txt allowed scope."""
    path = urlparse(url).path
    if any(path.startswith(p) for p in DISALLOWED_PATH_PREFIXES):
        return False
    if any(path.startswith(p) for p in ALLOWED_PATH_PREFIXES):
        return True
    # Default: disallow anything not explicitly in our allowed list
    return False

def build_driver() -> tuple[webdriver.Chrome, str]:
    """Initialise a polite, fingerprint-masked Chrome driver."""
    options = Options()
    options.page_load_strategy = 'eager'
    tmp_profile = tempfile.mkdtemp()
    options.add_argument(f"--user-data-dir={tmp_profile}")
    # options.binary_location = "/opt/chrome/chrome-linux64/chrome"
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")        # required on some VPS
    
    # options.add_argument("--single-process")
    options.add_argument("--no-zygote")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-application-cache")   # NEW
    options.add_argument("--disable-cache")               # NEW
    options.add_argument("--aggressive-cache-discard")    # NEW
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        # service=Service("/usr/local/bin/chromedriver/chromedriver"),
        options=options
    )
    driver.execute_cdp_cmd("Network.enable", {})
    driver.set_page_load_timeout(30)
    
    # driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
    #     "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    # })
    log.info("Chrome driver initialised.")
    return driver, tmp_profile

def recycle_driver(
    driver: webdriver.Chrome | None,
    tmp_profile: str | None
    ) -> tuple[webdriver.Chrome, str]:
    """Quit existing driver, wipe temp profile, spin up a fresh one."""
    if driver:
        try:
            driver.quit()
        except Exception as e:
            log.warning(f"Error quitting driver during recycle: {e}")
        log.info("Driver recycled — old instance closed.")
    if tmp_profile:
        shutil.rmtree(tmp_profile, ignore_errors=True)
        log.info("Temp profile directory removed.")
    time.sleep(3)   # let OS reclaim ports/file handles
    new_driver, new_profile = build_driver()
    return new_driver, new_profile

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

def build_search_url(target_city: str, checkin: str, checkout: str) -> str:
    """Build minimal, tracking-free Booking.com search URL for Ubud."""
    base = "https://www.booking.com/searchresults.html"
    # params = (
    #     f"?ss=Ubud"
    #     f"&dest_type={DEST_TYPE}"
    #     f"&checkin={checkin}"
    #     f"&checkout={checkout}"
    #     f"&group_adults={ADULTS}"
    #     f"&no_rooms={ROOMS}"
    #     f"&group_children={CHILDREN}"
    #     f"&lang={LANG}"
    # )
    params = (
        f"?ss={target_city}"
        # f"&dest_type={DEST_TYPE}"
        f"&checkin={checkin}"
        f"&checkout={checkout}"
    )
    # f"&dest_id={DEST_ID}"
    return base + params

def simplify_booking_url(url: str, def_ckin=None, def_ckout=None, offset_day=1) -> str:
    """
    Strip a Booking.com hotel URL down to essential params:
    aid, checkin, checkout, group_adults, req_adults, no_rooms, group_children.
    Ensures checkin/checkout dates and room details (adults, rooms, children)
    are appended properly for URLs with or without extension (e.g. .id.html, .html).
    """
    if def_ckin is None and def_ckout is None:
        date_ci, date_co = get_checkin_checkout(offset_days=offset_day)
    else:
        date_ci = def_ckin
        date_co = def_ckout
    KEEP_PARAMS = {"aid", "checkin", "checkout", "group_adults", "req_adults", "no_rooms", "group_children"}

    parsed   = urlparse(url)
    params   = parse_qs(parsed.query, keep_blank_values=True)

    # parse_qs wraps values in lists e.g. {"aid": ["304142"]}
    # flatten back to single values
    filtered = {k: v[0] for k, v in params.items() if k in KEEP_PARAMS}
    filtered['checkin'] = date_ci
    filtered['checkout'] = date_co

    # Ensure room details parameters are included even if missing in original URL
    if 'group_adults' not in filtered:
        filtered['group_adults'] = str(ADULTS)
    if 'req_adults' not in filtered:
        filtered['req_adults'] = str(ADULTS)
    if 'no_rooms' not in filtered:
        filtered['no_rooms'] = str(ROOMS)
    if 'group_children' not in filtered:
        filtered['group_children'] = str(CHILDREN)

    clean_url = parsed._replace(query=urlencode(filtered)).geturl()
    return clean_url


def load_dataframe() -> pd.DataFrame:
    """Load existing scraped data or return empty DataFrame."""
    if os.path.exists(PKL_FILE):
        df = pd.read_pickle(PKL_FILE)
        log.info(f"Loaded existing PKL: {len(df)} records.")
        return df
    log.info("No existing PKL found — starting fresh.")
    return pd.DataFrame(columns=[
        "hotel_id",
        "name",
        "url",
        "price_raw",
        "currency",
        "checkin",
        "checkout",
        "scraped_at",
    ])

def save_dataframe(df: pd.DataFrame) -> None:
    """Persist DataFrame to PKL file."""
    df.to_pickle(PKL_FILE)
    log.info(f"Saved {len(df)} records to {PKL_FILE}.")

def get_unseen_urls(candidate_urls: list[str], df: pd.DataFrame) -> list[str]:
    """Filter out hotel URLs already present in the PKL (dedup by URL)."""
    seen = set(df["url"].tolist()) if not df.empty else set()
    fresh = [u for u in candidate_urls if u not in seen]
    log.info(f"Dedup: {len(candidate_urls)} found → {len(fresh)} new.")
    return fresh

def polite_sleep() -> None:
    """Sleep a random interval within the configured polite range."""
    duration = random.uniform(SLEEP_MIN, SLEEP_MAX)
    log.info(f"  Sleeping {duration:.1f}s …")
    time.sleep(duration)

def extract_hotel_id(url: str) -> str:
    """Pull a simple hotel identifier from its URL path."""
    # e.g. /hotel/id/some-hotel-name.en-us.html or /hotel/id/some-hotel-name.id.html → some-hotel-name
    path = urlparse(url).path
    filename = path.split("/")[-1]           # e.g. villa-casa-natura-15-2-brv-with-private-pool-15-mins-to-ubud.id.html
    filename = re.sub(r'(\.[a-z]{2}(-[a-z]{2})?)?\.html$', '', filename, flags=re.IGNORECASE)
    return filename

def soft_scroll(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    current_position = 0

    while True:
        # Random chunk size (human scrolls vary between short and long flicks)
        chunk = random.randint(500, 1000)
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
        time.sleep(random.uniform(0.1, 0.7))

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
                log.info(f"  [scroll] Scroll make sure 1 times")
                for _ in range(1):
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

def collect_hotel_urls(driver: webdriver.Chrome, search_url: str) -> list[str]:
    """
    Load Ubud search results and return hotel detail page URLs.
    NOTE: CSS selectors below are placeholders — update after inspecting
          the live DOM with DevTools (Elements tab).
    """
    if not is_allowed(search_url):
        log.warning(f"Blocked by robots.txt guard: {search_url}")
        return []
 
    log.info(f"Loading search page: {search_url}")
    driver.set_page_load_timeout(30)
    driver.execute_cdp_cmd("Page.setLifecycleEventsEnabled", {"enabled": True})
    try:
        driver.get(search_url)
    except TimeoutException:
        # Page load timed out but page might still be usable
        log.warning("Page load timed out — continuing anyway...")
        pass
    except Exception as e:
        log.error(f"driver.get() failed: {e}")
        return []
    time.sleep(5)
    print("driver_get clicked")

    # driver.save_screenshot("debug_search_page.png")
    # print("Screenshot saved!")

    # print(f"Page title: {driver.title}")
    # print(f"Current URL: {driver.current_url}")
    # print(f"Page source length: {len(driver.page_source)}")

    all_urls  = []
    seen_urls = set()
    page      = 1

    if os.path.exists("seen_url.json"):
        print("JSON Found")
        with open("seen_url.json", "r") as f:
            seen_url_ref = json.load(f)
    else:
        seen_url_ref = {}
        with open("seen_url.json", "w") as f:
            json.dump(seen_url_ref, f)
        log.info("Created fresh seen_url.json")

    try:
        limit = WebDriverWait(driver, PAGE_TIMEOUT).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "h1[aria-live='assertive'] span")
            )
        )
        print(f"limit is: {limit.text}")
        match = re.search(r'([\d,]+)', limit.text)
        number = int(match.group(1).replace(",", "")) if match else 200
    except TimeoutException:
        log.warning("Could not find result count element — defaulting number to 999")
        number = 200
    except Exception as e:
        log.warning(f"Unexpected error finding limit: {e} — defaulting to 999")
        number = 200  
    catch_up = 0
    half_total_length = int(0.3 * number) #SOFTSTART DULU LAH

    while catch_up <= half_total_length:
        log.info(f"We're at steps page {page}")
        try:
            # ⚠️  PLACEHOLDER SELECTOR — inspect real DOM and update this
            # Look for anchor tags inside hotel card elements
            WebDriverWait(driver, PAGE_TIMEOUT).until(
                EC.presence_of_all_elements_located(
                    (By.CSS_SELECTOR, '[data-testid="property-card"]')
                )
            )
        except TimeoutException:
            log.warning("Timed out waiting for hotel cards on search page.")
            return []
        
        scroll_to_bottom_until_stable(driver)
        print("Sleep 10 secs")
        time.sleep(10)
        # ⚠️  PLACEHOLDER SELECTOR — update after DOM inspection
        anchors = driver.find_elements(
            By.CSS_SELECTOR,
            '[data-testid="property-card-container"] a[href*="/hotel/id/"]'
        )
    
        page_urls = []
        for a in anchors:
            href = a.get_attribute("href")
            if href and "/hotel/id/" in href:
                # clean = href.split("?")[0]
                clean = href
                checker = href.split("?")[0]
                # if clean not in seen_urls:
                #     seen_urls.add(clean)
                #     page_urls.append(clean)
                if checker not in seen_url_ref.keys():
                    seen_urls.add(clean)
                    page_urls.append(clean)
                    seen_url_ref[checker] = ""
                else:
                    continue

        all_urls.extend(page_urls)
        log.info(f"  Page {page}: {len(page_urls)} new URLs (total: {len(all_urls)})")
        with open("seen_url.json", "w") as f:
            json.dump(seen_url_ref, f)

        try:
            print("Sleep 10 secs")
            time.sleep(10)
            load_more_btn = WebDriverWait(driver, PAGE_TIMEOUT).until(
                EC.presence_of_element_located(
                    # ⚠️ PLACEHOLDER — update span text if it differs in your locale
                    (By.XPATH, '//span[contains(text(), "Load more results")]')
                )
            )
            log.info(f"  'Load more results' detected. Waiting 10s before clicking …")
            time.sleep(10)  # polite pause before paginating

            # Scroll button into view then click
            driver.execute_script("arguments[0].scrollIntoView(true);", load_more_btn)
            time.sleep(5)
            try:
                cookie_btn = driver.find_element(
                    By.CSS_SELECTOR, 
                    'button[id*="accept"], button[id*="cookie"], div.bbe73dce14 button'
                )
                cookie_btn.click()
                log.info("  Dismissed overlay/cookie banner.")
                time.sleep(2)
            except NoSuchElementException:
                pass  # no overlay, continue

            # ← Use JavaScript click instead of .click() to bypass overlays
            driver.execute_script("arguments[0].click();", load_more_btn)
            log.info("  Button clicked via JS! now sleep for 20 seconds")
            # load_more_btn.click()
            # print("Button clicked! sleeping 20 seconds")
            time.sleep(20)
            print("Wake the fuck up Samurai, we got city to burn!")
            page += 1
            catch_up = catch_up + len(page_urls)
            print(f"Updated database difference is: {catch_up}")
            # SAFE GUARD DELETE AFTER SYSTEM PROOFEN AT VPS:
            if page > 8: break

        except TimeoutException:
            log.info("  No 'Load more results' button found — reached last page.")
            break

    final = all_urls
    log.info(f"Collection complete: {len(final)} hotel URLs.")
    return final

def scrape_commentaries(driver: webdriver.Chrome,
    hotel_url: str,
    ):
    log.info(f"  Scraping comment of : {hotel_url}")
    # driver.get(hotel_url)
    try:
        for i in range(3):
            try:
                button = WebDriverWait(driver, PAGE_TIMEOUT).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-testid='fr-read-all-reviews']"))
                )
                driver.execute_script("arguments[0].click();", button)
                log.info("Button clicked successfully.")
                break
            except TimeoutException:
                log.warning(f"[WARNING] Unresponsive, this is your trial to scrape commentaries {i+1}/3!")
                continue

    except Exception as e:
        log.warning("Button with specified data-testid not found or not clickable within timeout.")
        log.warning("Returning empt DataFrame instead.")
        dummy = pd.DataFrame()
        return dummy
    
    time.sleep(10)
    try:
        page_buttons = WebDriverWait(driver, PAGE_TIMEOUT).until(
            EC.presence_of_all_elements_located((
                By.CSS_SELECTOR, "div[role='navigation'] ol.a81722b979 li button"
            ))
        )
        page_numbers = []
        for btn in page_buttons:
            text = btn.text.strip()
            if text.isdigit():
                page_numbers.append(int(text))
        
        # total_pages = max(page_numbers) if page_numbers else 1
        total_pages = 8 if max(page_numbers) > 5 else max(page_numbers)
        log.info(f"Total review pages found: {total_pages}")
    except Exception as e:
        log.info(f"Could not determine page count, defaulting to 1. Reason: {e}")
        total_pages = 1

    card_master = []
    time.sleep(5)
    try:
        for page in range(1, total_pages + 1):
            log.info(f"Scraping review page {page}/{total_pages}...")
            time.sleep(15)
            review_cards = driver.find_elements(
                By.CSS_SELECTOR, "div[data-testid='review-card']"
            )
            counter = 0
            for card in review_cards:
                if counter > 8 : break
                # Name and nationality scrap
                try:
                    raw_text = card.find_element(By.CSS_SELECTOR, "div[data-testid='review-avatar']").text
                    text_list = [t.strip() for t in raw_text.split("\n") if t.strip()]
                    log.info(f"Name and country: {text_list}")
                except NoSuchElementException as e:
                    log.info("No reviewer name and avatar.")
                    text_list = []
                time.sleep(10)

                # staying details
                try:
                    staying_cards = card.find_element(By.CSS_SELECTOR, "div[data-testid='review-stay-info']").text
                    staying_text_list = [t.strip() for t in staying_cards.split("\n") if t.strip()]
                    log.info(f"Staying details data: {staying_text_list}")
                except NoSuchElementException as e:
                    log.info("No stay details.")
                    staying_text_list = []
                time.sleep(10)

                # positive comments
                try:
                    positive_cards = card.find_element(By.CSS_SELECTOR, "div[data-testid='review-positive-text']").text
                    log.info(f"Postive comments data: {positive_cards}")
                except NoSuchElementException as e:
                    log.info("No positive comments detected.")
                    positive_cards = []

                # negative comments
                try:
                    negative_cards = card.find_element(By.CSS_SELECTOR, "div[data-testid='review-negative-text']").text
                    log.info(f"Negative comments data: {negative_cards}")
                except NoSuchElementException as e:
                    log.info("No negative comments detected.")
                    negative_cards = []

                card_master.append({
                    "basic_info": text_list,
                    "staying_details": staying_text_list,
                    "positive_comments": positive_cards,
                    "negative_comments": negative_cards
                })
                counter += 1

            if page < total_pages:
                try:
                    next_button = WebDriverWait(driver, PAGE_TIMEOUT).until(
                        EC.element_to_be_clickable((
                            By.CSS_SELECTOR, "button[aria-label='Next page']"
                        ))
                    )
                    driver.execute_script("arguments[0].scrollIntoView(true);", next_button)
                    next_button.click()
                except Exception as e:
                    log.warning(f"Could not click Next on page {page}, stopping early. Reason: {e}")
                    break

        review_df = pd.DataFrame(card_master)
        return review_df
    except Exception as e:
        raise Exception("Error in finding review card!") from e

def scrape_hotel_price(
    driver: webdriver.Chrome,
    hotel_url: str,
    period_days: int,
    property_id: int,
    trial_seed: int
) -> dict | None:
    """
    Visit a hotel page with date params and extract the displayed price.
    Returns a record dict or None if extraction fails.
    """
    log.info("Scraping last minute mode.")
    # HELPER FUNCTION ONLY -----------------------------------------------------------------
    def sanitize_filename(name: str) -> str:
        """Remove/replace characters illegal in filenames."""
        if not name:
            return "unknown_property"
        name = name.strip()
        name = re.sub(r'[\\/*?:"<>|\n\r\t]', "_", name)  # replace illegal chars
        name = re.sub(r'\s+', "_", name)                  # spaces to underscores
        name = re.sub(r'_+', "_", name)                   # collapse multiple underscores
        return name[:100]  # cap length for safety
    # END OF HELPER FUNCTION ---------------------------------------------------------------

    ckin_dt, _ = get_checkin_checkout(offset_days=period_days)
    hotel_url_new = simplify_booking_url(hotel_url, offset_day=period_days)
    # dt = datetime.strptime(ckin_dt, "%Y-%m-%d")  # use your actual format
    # day_weekday = dt.strftime("%A")

    dt_now = datetime.today() 
    dt_now_rev = dt_now.strftime("%Y-%m-%d")

    # if not is_allowed(hotel_url):
    #     print(f"Blocked by robots.txt guard: {hotel_url}")
    #     return None
    
    log.info(f"  Visiting: {hotel_url}")
    # driver.get(hotel_url)
    # wait = WebDriverWait(driver, PAGE_TIMEOUT)

    property_name = None

    # wait for the container that holds the table
    date_avail = False
    only_once_pname = True
    new_ckin = ckin_dt
    trials_counter = 0
    while date_avail == False:
        driver.get(hotel_url_new)
        log.info(f"[DEBUG] Specific URL 1: {hotel_url_new}")
        try:
            wait = WebDriverWait(driver, PAGE_TIMEOUT)
            time.sleep(5)
            for i in range(3):
                try:
                    wait.until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    break
                except TimeoutException:
                    log.warning(f"[WARNING] Unresponsive, this is your trial {i+1}/3!")
                    continue

            if only_once_pname == True:
                try:
                    for _ in range(3):
                        try:
                            # property_name = wait.until(
                            #     EC.visibility_of_element_located(
                            #         (By.CSS_SELECTOR, "div#hp_hotel_name h2")
                            #     )
                            # ).text.strip()
                            property_name = property_id
                            try:
                                quality_btn = wait.until(
                                    EC.presence_of_element_located(
                                        (By.CSS_SELECTOR, 'button[data-testid="quality-rating"]')
                                    )
                                )
                                rating_span = quality_btn.find_element(
                                    By.CSS_SELECTOR, 'span[data-testid]'
                                )
                                # 1 = hotel (rating-stars), 2 = villa/apartment (rating-squares)
                                villa_or_hotel = (
                                    1 if rating_span.get_attribute('data-testid') == 'rating-stars'
                                    else 2
                                )
                                aria_label = quality_btn.get_attribute('aria-label')
                                rating = int(aria_label.split()[0])
                                log.info(f"villa/hotel = {villa_or_hotel} and rating is: {rating}")
                            except Exception as e:
                                villa_or_hotel = None
                                rating = None
                                log.info("No hotel/villa info and rating info!")
                            break

                        except StaleElementReferenceException:
                            time.sleep(1)
                            continue
                    else:
                        property_name = property_id
                        villa_or_hotel = None
                        rating = None
                except (TimeoutException, NoSuchElementException):
                    property_name = property_id
                    villa_or_hotel = None
                    rating = None
                only_once_pname = False

            # CHECK IF DATE AVAILABLE OR NOT
            try:
                container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.hprt-container")))
            except (TimeoutException, NoSuchElementException):
                try:
                    check_available = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.bui-alert__description")))
                    if check_available:
                        trials_counter += 1
                        if trials_counter > trial_seed:
                            time.sleep(5)
                            raise RuntimeError("Trials changing date exceeding limits (3) times.")

                        log.info("The availability on current date is not available, renew the date range.")
                        new_ckin, new_ckout = renew_checkin_checkout(new_ckin)
                        hotel_url_new = simplify_booking_url(hotel_url_new, def_ckin=new_ckin, def_ckout=new_ckout)
                        continue
                except (TimeoutException, NoSuchElementException):
                    log.warning("Unknown exceptions, can't find any booking data at all, check actual conditions.")
                    results = []
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'last-minute'}
                    results.append(data)
                    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}
                except RuntimeError as e:
                    log.warning(f"Caught a runtime error: {e}")
                    results = []
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'last-minute'}
                    results.append(data)
                    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}
                except Exception as e:
                    log.warning(f"Caught Unknown error: {e} \nPlay safe and throing empty data instead!")
                    results = []
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'last-minute'}
                    results.append(data)
                    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}
            except StaleElementReferenceException:
                log.warning("Row became stale, retrying...")
                continue
        except Exception as e:
            log.warning("Encountering unknown error probably due to long loaidng time, skipping this property!")
            log.warning(f"error detail is {e}")
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'last-minute'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": None, "rating": None, "total_rows": 0, "rows": results}

        # find tbody inside the container
        # try:
        #     tbody = container.find_element(By.TAG_NAME, "tbody")
        # except NoSuchElementException:
        #     # sometimes table rows are direct children; fallback to container
        #     print("NoSuchElementException (main) triggered!!!")
        #     tbody = container

        time.sleep(5)
        log.info(f"  Scraping : {hotel_url_new}")
        # rows = tbody.find_elements(By.TAG_NAME, "tr")
        # total_rows = len(rows)
        total_rows = len(
            container.find_element(By.TAG_NAME, "tbody")
                    .find_elements(By.TAG_NAME, "tr")
        )
        log.info(f"Total <tr> rows found: {total_rows}")

        results = []
        # for _, row in enumerate(rows, start=1):
        for idx in range(total_rows):
            tbody = container.find_element(By.TAG_NAME, "tbody")
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            row = rows[idx]
            # ^^^^^^^^^^^^^^^^^^^^^^^ NEW ADDITION ^^^^^^^^^^^^^^^^^^^^^^
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'last-minute'}
            try:
                # Room type: <th> -> <a class="hprt-roomtype-link">
                th = row.find_element(By.TAG_NAME, "th")
                room_link = th.find_element(By.CSS_SELECTOR, "a.hprt-roomtype-link")
                log.info("room_link found")
                data["room_type"] = room_link.text.strip()
                log.info(f"room_type is {room_link.text.strip()}")
            except NoSuchElementException:
                log.info("NoSuchElementException (1) triggered!!!")
                data["room_type"] = None
            time.sleep(2)

            try:
                # second <td> (index 1) with price span.prco-valign-middle-helper
                tds = row.find_elements(By.TAG_NAME, "td")
                # log.info(f"[DEBUG] how many td detected? {len(tds)}")
                # log.info(f"[DEBUG] apa isinya sih 0? {tds[0].text.strip()}")
                # log.info(f"[DEBUG] apa isinya sih 1? {tds[1].text.strip()}")
                # log.info(f"[DEBUG] apa isinya sih 2? {tds[2].text.strip()}")
                if len(tds) > 0:
                    price_td = tds[1]
                    # log.info(f"[DEBUG] apa isinya sih? {price_td.text.strip()}")
                    log.info("trigger scrolling to fight lazy loader")
                    soft_scroll(driver)
                    stage_pass = False
                    try:
                        # price_span = price_td.find_element(By.CSS_SELECTOR, "span.prco-valign-middle-helper")
                        price_span = wait.until(
                            lambda d: price_td.find_element(
                                By.CSS_SELECTOR, "span.prco-valign-middle-helper"
                            )
                        )
                        log.info("price_span found")
                        stage_pass = True
                        data["price"] = price_span.text.strip()
                        log.info(f"price is {price_span.text.strip()}")
                    except (TimeoutException, NoSuchElementException):
                        log.info("Price extraction method 1 not succeed, trying second method")
                        # price_span = price_td.find_element(By.CSS_SELECTOR, "span.prco-valign-middle-helper")
                        for el in price_td.find_elements(By.CSS_SELECTOR, "span.bui-u-sr-only"):
                            text = el.get_attribute("textContent").replace("\xa0", " ")
                            match = re.search(r"Rp\s[\d,.]+", text)
                            if match:
                                data["price"] = match.group()
                                log.info(f"price is {match.group()}")
                                stage_pass = True
                                break
                            else:
                                log.info("Shit can't find anything, got one more trick on the sleeve to try.")

                        if stage_pass == False:
                            for i in [0, 2]:
                                text_check = tds[i].text.strip()
                                match = re.search(r"Rp\s[\d,.]+", text_check)
                                if match:
                                    data["price"] = match.group()
                                    log.info(f"KUNG-FU WORKS!!!! price is {match.group()}")
                                    break
                                else:
                                    log.info("Shit can't find anything, this is so strange yo!!!")
            except Exception as e:
                log.info(f"Exception (2) triggered!!! NOTES: {e}")
                data["price"] = None
            time.sleep(2)

            try:
                # third <td> (index 2) and collect any sentences under <span>
                if len(tds) > 2:
                    notes_td = tds[2]
                    spans = notes_td.find_elements(By.TAG_NAME, "span")
                    log.info("span found")
                    notes_texts = [s.text.strip() for s in spans if s.text.strip()]
                    data["notes"] = " ".join(notes_texts) if notes_texts else None
                    log.info(f"room info {notes_texts}")
            except NoSuchElementException:
                log.info("NoSuchElementException (3) triggered!!!")
                data["notes"] = None
            time.sleep(10)
            results.append(data)
        date_avail = True

    # WE DEACTIVATE THE COMMENT SCRAPPING FOR NOW!!! IT'S ONLY DEMO 
    # WE WILL ACTIVATE LATER UNTIL FURTHER COMMAND
    # commentaries_df = scrape_commentaries(driver, hotel_url)
    # if commentaries_df is not None and not commentaries_df.empty:
    #     safe_name = sanitize_filename(property_name)
    #     target_dir = os.path.join("property_reviews", f"reviews_property_{safe_name}.pkl")
        
    #     os.makedirs("property_reviews", exist_ok=True)  # create folder if missing
    #     commentaries_df.to_pickle(target_dir)
    #     log.info(f"Saved reviews to: {target_dir}")
    # else:
    #     log.info(f"Skipping pickle save — empty DataFrame for: {property_name}")
    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": total_rows, "rows": results}

def scrape_hotel_price_early_book(
    driver: webdriver.Chrome,
    hotel_url: str,
    period_days: int,
    property_id: int,
    trial_seed: int
) -> dict | None:
    """
    Visit a hotel page with date params and extract the displayed price.
    Returns a record dict or None if extraction fails.
    """
    log.info("Scraping Early Book Mode")
    # HELPER FUNCTION ONLY -----------------------------------------------------------------
    def sanitize_filename(name: str) -> str:
        """Remove/replace characters illegal in filenames."""
        if not name:
            return "unknown_property"
        name = name.strip()
        name = re.sub(r'[\\/*?:"<>|\n\r\t]', "_", name)  # replace illegal chars
        name = re.sub(r'\s+', "_", name)                  # spaces to underscores
        name = re.sub(r'_+', "_", name)                   # collapse multiple underscores
        return name[:100]  # cap length for safety
    # END OF HELPER FUNCTION ---------------------------------------------------------------

    ckin_dt, _ = get_checkin_checkout(offset_days=period_days)
    # ckin_dt_true = datetime.strptime(ckin_dt, "%Y-%m-%d")
    # ckin_dt_true = ckin_dt_true + timedelta(days=60)
    # ckout_dt = ckin_dt_true + timedelta(days=1)
    # hotel_url_new = simplify_booking_url(hotel_url, def_ckin=ckin_dt_true, def_ckout=ckout_dt)
    hotel_url_new = simplify_booking_url(hotel_url, offset_day=period_days)
    # dt = datetime.strptime(ckin_dt, "%Y-%m-%d")  # use your actual format
    # day_weekday = dt.strftime("%A")

    dt_now = datetime.today() 
    dt_now_rev = dt_now.strftime("%Y-%m-%d")

    # if not is_allowed(hotel_url):
    #     print(f"Blocked by robots.txt guard: {hotel_url}")
    #     return None
    
    log.info(f"  Visiting: {hotel_url}")
    # driver.get(hotel_url)
    # wait = WebDriverWait(driver, PAGE_TIMEOUT)

    property_name = property_id
    villa_or_hotel = None  # 1 = hotel (rating-stars), 2 = villa/apartment (rating-squares)
    rating = None

    # wait for the container that holds the table
    date_avail = False
    only_once_pname = True
    # new_ckin = ckin_dt_true.strftime("%Y-%m-%d")
    new_ckin = ckin_dt
    trials_counter = 0
    while date_avail == False:
        log.info(f"[DEBUG] Specific URL 2: {hotel_url_new}")
        driver.get(hotel_url_new)
        # if DEBUG_SCREENSHOT == 1:
        #     driver.save_screenshot("/home/gecko/debug/screenshot.png")
        try:
            wait = WebDriverWait(driver, PAGE_TIMEOUT)
            time.sleep(5)
            for i in range(3):
                try:
                    wait.until(
                        lambda d: d.execute_script("return document.readyState") == "complete"
                    )
                    break
                except TimeoutException:
                    log.warning(f"[WARNING] Unresponsive, this is your trial {i+1}/3!")
                    continue

            if only_once_pname == True:
                # try:
                #     for _ in range(3):
                #         try:
                #             property_name = wait.until(
                #                 EC.visibility_of_element_located(
                #                     (By.CSS_SELECTOR, "div#hp_hotel_name h2")
                #                 )
                #             ).text.strip()
                #             break

                #         except StaleElementReferenceException:
                #             time.sleep(1)
                #             continue
                #     else:
                #         property_name = None
                # except (TimeoutException, NoSuchElementException):
                #     property_name = None
                property_name = property_id
                only_once_pname = False

            # CHECK IF DATE AVAILABLE OR NOT
            try:
                container = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.hprt-container")))
            except (TimeoutException, NoSuchElementException):
                try:
                    check_available = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.bui-alert__description")))
                    if check_available:
                        trials_counter += 1
                        if trials_counter > trial_seed:
                            time.sleep(5)
                            raise RuntimeError("Trials changing date exceeding limits (5) times.")

                        log.info("The availability on current date is not available, renew the date range.")
                        new_ckin, new_ckout = renew_checkin_checkout(new_ckin)
                        hotel_url_new = simplify_booking_url(hotel_url_new, def_ckin=new_ckin, def_ckout=new_ckout)
                        continue
                except (TimeoutException, NoSuchElementException):
                    log.warning("Unknown exceptions, can't find any booking data at all, check actual conditions.")
                    results = []
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'early-book'}
                    results.append(data)
                    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}
                except RuntimeError as e:
                    log.warning(f"Caught a runtime error: {e}")
                    results = []
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'early-book'}
                    results.append(data)
                    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}
                except Exception as e:
                    log.warning(f"Caught Unknown error: {e} \nPlay safe and throing empty data instead!")
                    results = []
                    data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'early-book'}
                    results.append(data)
                    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}
            except StaleElementReferenceException:
                log.warning("Row became stale, retrying...")
                continue
        except Exception as e:
            log.warning("Encountering unknown error probably due to long loaidng time, skipping this property!")
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'early-book'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}

        # find tbody inside the container
        # try:
        #     tbody = container.find_element(By.TAG_NAME, "tbody")
        # except NoSuchElementException:
        #     # sometimes table rows are direct children; fallback to container
        #     print("NoSuchElementException (main) triggered!!!")
        #     tbody = container

        time.sleep(5)
        log.info(f"  Scraping : {hotel_url_new}")
        # rows = tbody.find_elements(By.TAG_NAME, "tr")
        # total_rows = len(rows)
        total_rows = len(
            container.find_element(By.TAG_NAME, "tbody")
                    .find_elements(By.TAG_NAME, "tr")
        )
        log.info(f"Total <tr> rows found: {total_rows}")

        results = []
        # for _, row in enumerate(rows, start=1):
        for idx in range(total_rows):
            tbody = container.find_element(By.TAG_NAME, "tbody")
            rows = tbody.find_elements(By.TAG_NAME, "tr")
            row = rows[idx]
            # ^^^^^^^^^^^^^^^^^^^^^^^ NEW ADDITION ^^^^^^^^^^^^^^^^^^^^^^
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'early-book'}
            try:
                # Room type: <th> -> <a class="hprt-roomtype-link">
                th = row.find_element(By.TAG_NAME, "th")
                room_link = th.find_element(By.CSS_SELECTOR, "a.hprt-roomtype-link")
                log.info("room_link found")
                data["room_type"] = room_link.text.strip()
                log.info(f"room type info eb : {room_link.text.strip()}")
            except NoSuchElementException:
                log.info("NoSuchElementException (1) triggered!!!")
                data["room_type"] = None
            time.sleep(2)

            try:
                # second <td> (index 1) with price span.prco-valign-middle-helper
                tds = row.find_elements(By.TAG_NAME, "td")
                # log.info(f"[DEBUG] how many td detected? {len(tds)}")
                # log.info(f"[DEBUG] apa isinya sih 0? {tds[0].text.strip()}")
                # log.info(f"[DEBUG] apa isinya sih 1? {tds[1].text.strip()}")
                # log.info(f"[DEBUG] apa isinya sih 2? {tds[2].text.strip()}")
                if len(tds) > 0:
                    price_td = tds[1]
                    # log.info(f"[DEBUG] apa isinya sih? {price_td.text.strip()}")
                    log.info("trigger scrolling to fight lazy loader")
                    soft_scroll(driver)
                    stage_pass = False
                    try:
                        # price_span = price_td.find_element(By.CSS_SELECTOR, "span.prco-valign-middle-helper")
                        price_span = wait.until(
                            lambda d: price_td.find_element(
                                By.CSS_SELECTOR, "span.prco-valign-middle-helper"
                            )
                        )
                        log.info("price_span found")
                        stage_pass = True
                        data["price"] = price_span.text.strip()
                        log.info(f"price is {price_span.text.strip()}")
                    except (TimeoutException, NoSuchElementException):
                        log.info("Price extraction method 1 not succeed, trying second method")
                        # price_span = price_td.find_element(By.CSS_SELECTOR, "span.prco-valign-middle-helper")
                        for el in price_td.find_elements(By.CSS_SELECTOR, "span.bui-u-sr-only"):
                            text = el.get_attribute("textContent").replace("\xa0", " ")
                            match = re.search(r"Rp\s[\d,.]+", text)
                            if match:
                                data["price"] = match.group()
                                log.info(f"price is {match.group()}")
                                stage_pass = True
                                break
                            else:
                                log.info("Shit can't find anything, got one more trick on the sleeve to try.")
                                
                        if stage_pass == False:
                            for i in [0, 2]:
                                text_check = tds[i].text.strip()
                                match = re.search(r"Rp\s[\d,.]+", text_check)
                                if match:
                                    data["price"] = match.group()
                                    log.info(f"KUNG FU WORKS !!!! price is {match.group()}")
                                    break
                                else:
                                    log.info("Shit can't find anything, this is so strange yo!!!")
            except Exception as e:
                log.info(f"Exception (2) triggered!!! due to {e}")
                data["price"] = None
            time.sleep(2)

            try:
                # third <td> (index 2) and collect any sentences under <span>
                if len(tds) > 2:
                    notes_td = tds[2]
                    spans = notes_td.find_elements(By.TAG_NAME, "span")
                    log.info("span found")
                    notes_texts = [s.text.strip() for s in spans if s.text.strip()]
                    data["notes"] = " ".join(notes_texts) if notes_texts else None
                    log.info(f"notes info eb : {notes_texts}")
            except NoSuchElementException:
                log.info("NoSuchElementException (3) triggered!!!")
                data["notes"] = None
            time.sleep(10)
            results.append(data)
        date_avail = True

    # WE DEACTIVATE THE COMMENT SCRAPPING FOR NOW!!! IT'S ONLY DEMO 
    # WE WILL ACTIVATE LATER UNTIL FURTHER COMMAND
    # commentaries_df = scrape_commentaries(driver, hotel_url)
    # if commentaries_df is not None and not commentaries_df.empty:
    #     safe_name = sanitize_filename(property_name)
    #     target_dir = os.path.join("property_reviews", f"reviews_property_{safe_name}.pkl")
        
    #     os.makedirs("property_reviews", exist_ok=True)  # create folder if missing
    #     commentaries_df.to_pickle(target_dir)
    #     log.info(f"Saved reviews to: {target_dir}")
    # else:
    #     log.info(f"Skipping pickle save — empty DataFrame for: {property_name}")
    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": total_rows, "rows": results}

def manual_scrape(driver, prop_name):
    MATCH_THRESHOLD = 0.80   # 80%
    # =============== HELPER FUNCTION SECTION ======================
    def dismiss_blocking_popup(driver):
        """Booking.com shows a cookie/sign-in overlay (div.bbe73dce14) that can
        sit on top of the search box and intercept clicks. Close it the same way
        a user does. Harmless no-op if no overlay is present."""
        selectors = (
            '#onetrust-accept-btn-handler',                         # cookie consent (most common)
            'button[data-testid="cookie-banner-accept-button"]',    # newer cookie banner
            'div.bbe73dce14 button',                                # generic dismiss inside the banner
            'button[aria-label*="Dismiss"]',                        # sign-in nudge close (X)
        )
        for sel in selectors:
            try:
                btn = driver.find_element(By.CSS_SELECTOR, sel)
                if btn.is_displayed():
                    driver.execute_script("arguments[0].click();", btn)
                    log.info("Dismissed blocking popup via %s", sel)
                    time.sleep(1)
                    return True
            except NoSuchElementException:
                continue
        return False

    def set_checkin_dates(driver, wait):
        """
        Rewrite checkin = today+1 and checkout = today+2 on the current results URL,
        then reload so the page re-renders with the new dates.
        Returns the new URL, or None if the URL couldn't be processed.
        """
        checkin  = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        checkout = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")

        current_url = driver.current_url
        parsed = urlparse(current_url)
        params = parse_qs(parsed.query)

        # parse_qs gives lists; overwrite the date keys
        params["checkin"]  = [checkin]
        params["checkout"] = [checkout]

        # doseq=True flattens the single-item lists back to scalars
        new_query = urlencode(params, doseq=True)
        new_url = urlunparse(parsed._replace(query=new_query))

        log.info("Rewriting dates -> checkin=%s checkout=%s", checkin, checkout)
        driver.get(new_url)   # get() reloads with the new query, more reliable than refresh()

        # Wait for the results to come back after reload before scoring
        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-results-container="1"]')
            ))
        except TimeoutException:
            log.warning("Results did not reload after date change")
        return new_url

    def find_matching_property(driver, wait, target_name: str, top_n: int = 5):
        """
        Wait for the Booking.com search results, read the top `top_n` property
        names, and fuzzy-match them against `target_name`.

        Returns the matched property's URL (str) as soon as one scores
        >= MATCH_THRESHOLD, otherwise returns None.
        """
        def tokenize(text):
            return set(re.findall(r'\w+', text.lower()))

        # 1. Wait for the results list to actually load.
        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-results-container="1"]')
            ))
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, 'a[data-testid="title-link"]')
            ))
        except TimeoutException:
            log.warning("Search results never loaded for %r — treating as no match", target_name)
            return None

        # 2. Collect the top N (name, url) pairs from the title-link anchors.
        link_els = driver.find_elements(By.CSS_SELECTOR, 'a[data-testid="title-link"]')
        candidates = []
        for a in link_els[:top_n]:
            try:
                name = a.find_element(By.CSS_SELECTOR, 'div[data-testid="title"]').text.strip()
                url  = a.get_attribute("href")
                if name and url:
                    candidates.append({"name": name, "url": url})
            except (NoSuchElementException, StaleElementReferenceException):
                continue   # card not fully rendered — skip silently

        if not candidates:
            log.info("No property names found on results page for %r", target_name)
            return None

        # 3. Score each candidate (token overlap + full string ratio).
        q_tokens = tokenize(target_name)

        for i, cand in enumerate(candidates):
            c_tokens = tokenize(cand["name"])

            matched = sum(
                1 for qt in q_tokens
                if max((SequenceMatcher(None, qt, ct).ratio() for ct in c_tokens), default=0) >= 0.80
            )
            token_score = matched / len(q_tokens) if q_tokens else 0

            full_score = SequenceMatcher(None, target_name.lower(), cand["name"].lower()).ratio()

            score = (token_score * 0.7) + (full_score * 0.3)
            log.info("%-4d %-55s %6.1f%%", i + 1, cand["name"], score * 100)

            # 4. Break immediately on the first candidate over the threshold.
            if score >= MATCH_THRESHOLD:
                log.info("[OK] MATCH: %r (%.1f%%)", cand["name"], score * 100)
                return cand["url"]          # <-- return the URL now

        # 5. Nothing crossed the bar.
        log.info("[FAULT] No property >= %.0f%% for %r", MATCH_THRESHOLD * 100, target_name)
        return None

    def is_property_in_allowed_location(driver, wait, url, allowed=None):
        """Open the matched property page and check its address contains an
        allowed location keyword (case-insensitive substring match).

        `allowed` defaults to the module-level ALLOWED_LOCATIONS. Returns True if
        ANY keyword appears anywhere in the address string, else False. On ANY
        failure to read the address it returns False (fail-closed) so a foreign
        look-alike cannot slip through this gateway.
        """
        allowed = allowed or ALLOWED_LOCATIONS
        try:
            driver.get(url)
        except Exception as e:
            log.warning("[GATEWAY] could not load %s: %s", url, e)
            return False

        try:
            wrapper = wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-testid="PropertyHeaderAddressDesktop-wrapper"]')
            ))
            addr_el = wrapper.find_element(By.CSS_SELECTOR, "button div")
            # First line is the address; the nested div is a hidden disclaimer.
            address = addr_el.text.strip().split("\n")[0].strip()
        except (TimeoutException, NoSuchElementException, StaleElementReferenceException) as e:
            log.warning("[GATEWAY] address element not found for %s: %s", url, e)
            return False

        if not address:
            log.warning("[GATEWAY] empty address for %s", url)
            return False

        addr_lower = address.lower()
        ok = any(loc.lower() in addr_lower for loc in allowed)
        log.info("[GATEWAY] address=%r allowed=%s pass=%s", address, allowed, ok)
        return ok

    # =============== HELPER FUNCTION SECTION END ==================

    try:
        ms_wait = WebDriverWait(driver, PAGE_TIMEOUT)
        driver.get("https://www.booking.com/")

        time.sleep(10)
        name_input = ms_wait.until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, '[data-testid="destination-container"]')
            )
        )
        dest_input = ms_wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, '[data-testid="destination-container"] input[name="ss"]')
            )
        )

        # Clear any cookie/sign-in overlay BEFORE touching the box. Note:
        # element_to_be_clickable only checks visible+enabled, NOT obstruction,
        # so the wait above can pass while the overlay still covers the input.
        dismiss_blocking_popup(driver)

        # Click the box, retrying once if an overlay still intercepts the click.
        for _ in range(2):
            try:
                dest_input.click()
                break
            except ElementClickInterceptedException:
                log.warning("Search box click intercepted — dismissing overlay and retrying.")
                dismiss_blocking_popup(driver)
                time.sleep(1)

        # Booking persists the previous destination and re-fills this React
        # combobox, so .clear() alone doesn't stick (it resets the DOM value but
        # not React's state, which then restores it -> new text gets appended to
        # the old city). Select-all + Delete fires real key events the framework
        # registers, truly emptying the box.
        dest_input.send_keys(Keys.CONTROL, "a")
        dest_input.send_keys(Keys.DELETE)

        # Belt-and-suspenders: if a value somehow survived, wipe it via JS and
        # dispatch an input event so React registers the empty state.
        if dest_input.get_attribute("value"):
            driver.execute_script(
                "arguments[0].value = '';"
                "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));",
                dest_input,
            )

        for i in prop_name:
            dest_input.send_keys(i)
            time.sleep(random.uniform(0.2, 0.9))

        button = ms_wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'form[action] button[type="submit"]'))
        )
        driver.execute_script("arguments[0].click();", button)
        time.sleep(10)
        corrected_url = set_checkin_dates(driver, ms_wait)
        match = find_matching_property(driver, ms_wait, prop_name)

        # FINAL GATEWAY: reject name look-alikes whose address is outside the
        # allowed locations (see ALLOWED_LOCATIONS at the top of this module).
        if match and not is_property_in_allowed_location(driver, ms_wait, match):
            log.info("[GATEWAY] %r matched a property outside allowed locations - rejecting as Not Found.", prop_name)
            return None
        
        return match

    except Exception as e:
        log.error(f"[MANUAL SCRAPE ERROR] Error due to {e}")

def dataframe_processing(new_records):
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
            ota_source.append("Booking.com")
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
        sub_data['date_scrapped'] = dt_scrapped_list
        sub_data['target_date'] = target_date
        sub_data["category"] = category
        sub_data['villa_or_hotel'] = villa_or_hotel_list
        sub_data['rating'] = rating_list
        major_data = pd.DataFrame(sub_data)
        data_df = pd.concat([data_df, major_data])

    return data_df

def cleaning_data(data_df):
    data_df2 = data_df.copy()
    data_df2 = data_df2.ffill()
    data_df2 = data_df2.reset_index(drop=True)

    target_cols = ["room_type", "price_details", "notes_details"]

    # Replace empty string / whitespace with NaN
    data_df2[target_cols] = data_df2[target_cols].replace(r'^\s*$', np.nan, regex=True)

    # Fill missing values
    data_df2["room_type"] = data_df2["room_type"].fillna("Unknown Room")
    data_df2["notes_details"] = data_df2["notes_details"].fillna("No Notes")

    data_df2["price_details"] = (
        data_df2["price_details"]
        .astype(str)
        .str.replace("Rp", "", regex=False)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    # Replace invalid values with NaN then convert
    data_df2["price_details"] = pd.to_numeric(data_df2["price_details"], errors="coerce")

    # Optional: fill missing prices
    data_df2["price_details"] = data_df2["price_details"].fillna(0).astype(int)
    # print(f"[DEBUG] Check data_df2: \n{data_df2}")
    return data_df2

def save_load_database(focus_df):
    # data_df2 = pd.DataFrame()
    data_df2 = focus_df.copy()
    if os.path.exists("scraping_customer_lm.pkl"):
        loaded_df = pd.read_pickle("scraping_customer_lm.pkl")
        data_df2 = pd.concat([data_df2, loaded_df])
        data_df2 = data_df2.reset_index(drop=True)
        data_df2.to_pickle("scraping_customer_lm.pkl")

    else:
        data_df2.to_pickle("scraping_customer_lm.pkl")

def save_load_database_eb(focus_df):
    # data_df2 = pd.DataFrame()
    data_df2 = focus_df.copy()
    if os.path.exists("scraping_customer_eb.pkl"):
        loaded_df = pd.read_pickle("scraping_customer_eb.pkl")
        data_df2 = pd.concat([data_df2, loaded_df])
        data_df2 = data_df2.reset_index(drop=True)
        data_df2.to_pickle("scraping_customer_eb.pkl")

    else:
        data_df2.to_pickle("scraping_customer_eb.pkl")

# def all_properties_scrape(driver, tempo_prof):
#     new_urls = []
#     debug_counter = 0
#     allowed_proceed = False
#     only_once = True
#     break_signal = False

#     try:
#         if os.path.exists("checkpoint_save.txt"):
#             with open("checkpoint_save.txt", "r") as f:
#                 cross_check = f.read()
#                 log.info(f"cross_check is : {cross_check}")

#         def get_base_url(url):
#                 return url.strip().split('?')[0] + '?'

#         with open("URL_text_list.txt", "r") as file:
#             print(f"found url_text_list")
#             lines = file.readlines()
#             last_line = lines[-1].strip()

#             i = 0
#             while i < len(lines):
#                 # find starting point from last checkpoint
#                 # print(f"last_line is : {last_line}")
#                 # print(f"lines[i] is : {lines[i]}")
#                 # log.info(f"cross_check is : {cross_check}")
#                 cross_check_result = get_base_url(last_line) == get_base_url(cross_check)
#                 if lines[i].strip() == last_line or cross_check_result:
#                     i = 0
#                     break_signal = True

#                 # find starting point from last checkpoint
#                 if only_once == True and os.path.exists("checkpoint_save.txt"):
#                     # pattern = re.escape(lines[i])
#                     # print(f"pattern is : {pattern}")
#                     # result = bool(re.search(pattern, cross_check))
#                     # base_url = lines[i].strip().split('?')[0] + '?'
#                     result = get_base_url(lines[i]) == get_base_url(cross_check)
#                     if result == True:
#                         log.info("Found last checkpoint!!!")
#                         allowed_proceed = True
#                         only_once = False
#                         continue # GOT IT WE FOUND LAST CHECKPOINT, SKIP AND READ NEXT LINE!

#                 if allowed_proceed == True or not os.path.exists("checkpoint_save.txt"):
#                     # print("We can continue!!!!")
#                     # url_convert = simplify_booking_url(line)
#                     # new_urls.append(url_convert)
#                     # url_convert = simplify_booking_url(line)
#                     new_urls.append(lines[i])
#                     debug_counter += 1

#                 i += 1
#                 if break_signal == True or debug_counter > MAX_PROPERTIES: 
#                     log.info("Safe guarding with 35 properties limiter, breaking algorithm now!")
#                     break

#         targets = new_urls[:MAX_PROPERTIES]
#         log.info(f"Targeting {len(targets)} hotels this session.")

#         BATCH_SIZE = 5
#         batch = []
#         batch_eb = []
#         processed = 0   # tracks hotels scraped since last recycle

#         for idx, url in enumerate(targets, 1):
#             # Recycle driver every N hotels (skip recycle on very first iteration
#             # since we already have a fresh driver from build_driver() above)
#             if processed > 0 and processed % DRIVER_RECYCLE_EVERY == 0:
#                 driver, tempo_prof = recycle_driver(driver, tempo_prof)

#             log.info(f"[{idx}/{len(targets)}] Scraping …")
#             record = scrape_hotel_price(driver, url, 0, trial_seed=3)
#             record_eb = scrape_hotel_price_early_book(driver, url, 0, trial_seed=3)

#             if record:
#                 batch.append(record)
#                 with open("checkpoint_save.txt", "w") as f:
#                     f.write(f"{url}\n")

#             if record_eb:
#                 batch_eb.append(record_eb)

#             processed += 1
#             polite_sleep()

#             # Flush batch to disk every BATCH_SIZE records
#             if len(batch) >= BATCH_SIZE:
#                 df_batch = cleaning_data(dataframe_processing(batch))
#                 save_load_database(df_batch)
#                 log.info(f"Flushed batch of {len(batch)} records.")
#                 batch.clear()

#             if len(batch_eb) >= BATCH_SIZE:
#                 df_batch_eb = cleaning_data(dataframe_processing(batch_eb))
#                 save_load_database_eb(df_batch_eb)
#                 log.info(f"Flushed batch EB of {len(batch_eb)} records.")
#                 batch_eb.clear()

#         # Flush any remaining records
#         if batch:
#             df_batch = cleaning_data(dataframe_processing(batch))
#             save_load_database(df_batch)
#             log.info(f"Flushed final batch of {len(batch)} records.")

#         if batch_eb:
#             df_batch_eb = cleaning_data(dataframe_processing(batch_eb))
#             save_load_database_eb(df_batch_eb)
#             log.info(f"Flushed final batch of {len(batch)} records.")

#         log.info(f"[DEBUG] Session complete.")
#         # new_records = []
#         # for i, url in enumerate(targets, 1):
#         #     print(f"[{i}/{len(targets)}] Scraping …")
#         #     record = scrape_hotel_price(driver, url)
#         #     if record:
#         #         new_records.append(record)
#         #         with open("checkpoint_save.txt", "w") as f:
#         #             f.write(f"{url}\n")
#         #     polite_sleep()

#         # print(f"[DEBUG] scraping result: \n{len(new_records)}")

#         # df = dataframe_processing(new_records)
#         # df_cleaned = cleaning_data(df)
#         # save_load_database(df_cleaned)
#     except Exception as e:
#         log.error(f"Unexpected error: {e}", exc_info=True)
#     finally:
#         # if driver:
#         #     driver.quit()
#         # if tempo_prof:
#         #     shutil.rmtree(tempo_prof, ignore_errors=True)
#         #     log.info("Temp profile directory removed.")
#         log.info("Driver shut down. Session END.")
#         log.info("=" * 50)

#     # Hand the current (possibly recycled) driver + profile back to run()
#     # so the single owner closes exactly the live instance, not a stale one.
#     return driver, tempo_prof

def customer_only(driver, url_list, cust_list, tempo_prof, mode=1):
    # To make it flexible on search focusing, I create modes:
    # mode 1 focus competitor with URL list only
    # mode 2 focus competitor using name search or manual search only
    # mode 3 URL list and manual search run serially
    # change the argument accordingly to your needs whether to debug or running in production
    print(f"Current mode is : {mode}")
    if url_list and (mode == 1 or mode == 3):
        log.info("Searching through all URLs that available.")
        try:
            new_urls = []
            captured_id = []
            debug_counter = 0
            allowed_proceed = False
            only_once = True
            break_signal = False

            if os.path.exists("checkpoint_save_customer_url.txt"):
                with open("checkpoint_save_customer_url.txt", "r") as f:
                    cross_check = f.read()
                    log.info(f"cross_check is : {cross_check}")

            def get_base_url(url):
                return url.strip().split('?')[0] + '?'

            last_line = url_list[-1]["url"]
            i = 0
            while i < len(url_list):
                cross_check_result = get_base_url(last_line) == get_base_url(cross_check)
                if url_list[i]["url"].strip() == last_line or cross_check_result:
                    i = 0
                    break_signal = True

                # find starting point from last checkpoint
                if only_once == True and os.path.exists("checkpoint_save_customer_url.txt"):
                    result = get_base_url(url_list[i]["url"]) == get_base_url(cross_check)
                    if result == True:
                        log.info("Found last checkpoint!!!")
                        allowed_proceed = True
                        only_once = False
                        continue # GOT IT WE FOUND LAST CHECKPOINT, SKIP AND READ NEXT LINE!

                if allowed_proceed == True or not os.path.exists("checkpoint_save_customer_url.txt"):
                    # print("We can continue!!!!")
                    # url_convert = simplify_booking_url(line)
                    # new_urls.append(url_convert)
                    # url_convert = simplify_booking_url(line)
                    new_urls.append(url_list[i]["url"])
                    captured_id.append(url_list[i]["customer_id"])
                    debug_counter += 1

                i += 1
                if break_signal == True or debug_counter > MAX_PROPERTIES: 
                    log.info("Safe guarding with 35 properties limiter, breaking algorithm now!")
                    break

            targets = new_urls[:MAX_PROPERTIES]
            targets_id = captured_id[:MAX_PROPERTIES]
            log.info(f"Targeting {len(targets)} customer this session.")

            BATCH_SIZE = 5
            batch = []
            batch_eb = []
            processed = 0   # tracks hotels scraped since last recycle
            period_cycling = [3, 7, 14, 30]

            for idx, url in enumerate(targets, 1):
                # Recycle driver every N hotels (skip recycle on very first iteration
                # since we already have a fresh driver from build_driver() above)
                if processed > 0 and processed % DRIVER_RECYCLE_EVERY == 0:
                    driver, tempo_prof = recycle_driver(driver, tempo_prof)

                log.info(f"[{idx}/{len(targets)}] Scraping …")
                for vii in period_cycling:
                    log.info(f"Stratified sampling start at today + {vii} days")
                    if vii <= 7:
                        record = scrape_hotel_price(driver, url, vii, targets_id[idx-1], trial_seed=2)
                        if record:
                            batch.append(record)
                            with open("checkpoint_save_customer_url.txt", "w") as f:
                                f.write(f"{url}\n")
                    elif vii > 7:
                        record_eb = scrape_hotel_price_early_book(driver, url, vii, targets_id[idx-1], trial_seed=2)
                        if record_eb:
                            batch_eb.append(record_eb)
                            with open("checkpoint_save_customer_url.txt", "w") as f:
                                f.write(f"{url}\n")
                    polite_sleep()

                processed += 1
                if len(batch) >= BATCH_SIZE:
                    df_batch = cleaning_data(dataframe_processing(batch))
                    save_load_database(df_batch)
                    log.info(f"Flushed batch of {len(batch)} records.")
                    batch.clear()

                if len(batch_eb) >= BATCH_SIZE:
                    df_batch_eb = cleaning_data(dataframe_processing(batch_eb))
                    save_load_database_eb(df_batch_eb)
                    log.info(f"Flushed batch EB of {len(batch_eb)} records.")
                    batch_eb.clear()

            # Flush any remaining records
            if batch:
                df_batch = cleaning_data(dataframe_processing(batch))
                save_load_database(df_batch)
                log.info(f"Flushed final batch of {len(batch)} records.")

            if batch_eb:
                df_batch_eb = cleaning_data(dataframe_processing(batch_eb))
                save_load_database_eb(df_batch_eb)
                log.info(f"Flushed final batch of {len(batch)} records.")

            log.info(f"[CUSTOMER ONLY - URL LIST] Session complete.")
        except Exception as e:
            log.error(f"[CUSTOMER ONLY - URL LIST] Unexpected error: {e}", exc_info=True)
        finally:
                # if driver:
                #     driver.quit()
                # if tempo_prof:
                #     shutil.rmtree(tempo_prof, ignore_errors=True)
                #     log.info("Temp profile directory removed.")
                log.info("Finish processing URL listed competitor.")
                log.info("=" * 50)

    if cust_list and (mode == 2 or mode == 3):
        log.info("Searching manually through list.")
        try:
            new_urls = []
            debug_counter = 0
            allowed_proceed = False
            only_once = True
            break_signal = False

            if os.path.exists("checkpoint_save_customer_name.txt"):
                with open("checkpoint_save_customer_name.txt", "r") as f:
                    cross_check = f.read()
                    log.info(f"cross_check is : {cross_check}")

            def get_base_url(url):
                return url.strip().split('?')[0] + '?'

            last_line = cust_list[-1]
            for i in range(len(cust_list)):
                cross_check_result = get_base_url(last_line) == get_base_url(cross_check)
                if cust_list[i].strip() == last_line or cross_check_result:
                    i = 0
                    break_signal = True

                # find starting point from last checkpoint
                if only_once == True and os.path.exists("checkpoint_save_customer_name.txt"):
                    result = get_base_url(cust_list[i]) == get_base_url(cross_check)
                    if result == True:
                        log.info("Found last checkpoint!!!")
                        allowed_proceed = True
                        only_once = False
                        continue # GOT IT WE FOUND LAST CHECKPOINT, SKIP AND READ NEXT LINE!

                if allowed_proceed == True or not os.path.exists("checkpoint_save_customer_name.txt"):
                    # print("We can continue!!!!")
                    # url_convert = simplify_booking_url(line)
                    # new_urls.append(url_convert)
                    # url_convert = simplify_booking_url(line)
                    new_urls.append(cust_list[i])
                    debug_counter += 1

                if break_signal == True or debug_counter > MAX_PROPERTIES: 
                    log.info("Safe guarding with 35 properties limiter, breaking algorithm now!")
                    break

            targets = new_urls[:MAX_PROPERTIES]
            log.info(f"Targeting {len(targets)} customer MANUALLY this session.")

            BATCH_SIZE = 5
            batch = []
            batch_eb = []
            processed = 0   # tracks hotels scraped since last recycle
            # period_cycling = [3, 7, 14, 30]

            for idx, url in enumerate(targets, 1):
                if processed > 0 and processed % DRIVER_RECYCLE_EVERY == 0:
                    driver, tempo_prof = recycle_driver(driver, tempo_prof)

                log.info(f"[{idx}/{len(targets)}] Scraping …")
                obtained_url = manual_scrape(driver, url)
                if not obtained_url:
                    log.info("No Booking.com match for %r — skipping property.", url)
                    processed += 1
                    polite_sleep()
                    continue
                cleaned_obtained_url = simplify_booking_url(obtained_url)
                with open("checkpoint_save_customer_name.txt", "w") as f:
                    f.write(f"{url}\n")
                # TARGET OF OPPORTUNITIES, SAVING THE NEWLY FOUND PROPERTY TO URL TEXT LIST
                if os.path.exists("seen_url.json"):
                    print("JSON Found")
                    with open("seen_url.json", "r") as f:
                        seen_url_ref = json.load(f)

                else:
                    seen_url_ref = {}
                    with open("seen_url.json", "w") as f:
                        json.dump(seen_url_ref, f)
                    log.info("Created fresh seen_url.json")

                checker = cleaned_obtained_url.split("?")[0]
                log.info(f"Cleaning the URL to {checker}")
                if checker not in seen_url_ref.keys():
                    # page_urls.append(cleaned_obtained_url)
                    seen_url_ref[checker] = ""
                    with open("seen_url.json", "w") as f:
                        json.dump(seen_url_ref, f)
                    with open("URL_text_list.txt", "a") as f:
                        f.write(f"{cleaned_obtained_url}\n")
                else:
                    # Already listed in txt — skip scraping here (avoid duplicate
                    # work), but keep the recycle cadence + rate-limit consistent.
                    processed += 1
                    polite_sleep()
                    continue

            # DIRECT ACCESSING 
            #     for vii in period_cycling:
            #         log.info(f"Stratified sampling for MANUAL SEARCH start at today + {vii} days")
            #         if vii <= 7:
            #             record = scrape_hotel_price(driver, cleaned_obtained_url, vii, trial_seed=2)
            #             if record:
            #                 batch.append(record)
            #                 with open("checkpoint_save_customer_name.txt", "w") as f:
            #                     f.write(f"{url}\n")
            #         elif vii > 7:
            #             record_eb = scrape_hotel_price_early_book(driver, cleaned_obtained_url, vii, trial_seed=2)
            #             if record_eb:
            #                 batch_eb.append(record_eb)
            #                 with open("checkpoint_save_customer_name.txt", "w") as f:
            #                     f.write(f"{url}\n")
            #         polite_sleep()

            #     processed += 1
            #     if len(batch) >= BATCH_SIZE:
            #         df_batch = cleaning_data(dataframe_processing(batch))
            #         save_load_database(df_batch)
            #         log.info(f"Flushed batch of {len(batch)} records.")
            #         batch.clear()

            #     if len(batch_eb) >= BATCH_SIZE:
            #         df_batch_eb = cleaning_data(dataframe_processing(batch_eb))
            #         save_load_database_eb(df_batch_eb)
            #         log.info(f"Flushed batch EB of {len(batch_eb)} records.")
            #         batch_eb.clear()

            # # Flush any remaining records
            # if batch:
            #     df_batch = cleaning_data(dataframe_processing(batch))
            #     save_load_database(df_batch)
            #     log.info(f"Flushed final batch of {len(batch)} records.")

            # if batch_eb:
            #     df_batch_eb = cleaning_data(dataframe_processing(batch_eb))
            #     save_load_database_eb(df_batch_eb)
            #     log.info(f"Flushed final batch of {len(batch)} records.")

            # log.info(f"[CUSTOMER ONLY - MANUAL SEARCH] Session complete.")

        except Exception as e:
            log.error(f"[CUSTOMER ONLY - MANUAL SEARCH] Unexpected error: {e}", exc_info=True)
        finally:
                # if driver:
                #     driver.quit()
                # if tempo_prof:
                #     shutil.rmtree(tempo_prof, ignore_errors=True)
                #     log.info("Temp profile directory removed.")
                log.info("Finish processing URL listed competitor.")
                log.info("=" * 50)

    # Hand the current (possibly recycled) driver + profile back to run().
    return driver, tempo_prof

def run():
    FOCUS_CITIES = ["Ubud", "Canggu", "Tabanan", "Seminyak", "Kuta", "Denpasar", "Kintamani",
                    "Bedugul", "Karangasem", "Nusa Dua", "Sanur", "Lombok", "Mataram", "Banyuwangi",
                    "Malang", "Batu", "Tretes", "Bandung", "Bogor", "Lembang", "Ciwidey", "Pengalengan",
                    "Sentul", "Cisarua", "Megamendung", "Sidemen"]
    # FOCUS_CITIES = ["Ubud", "Canggu", "Tabanan", "Seminyak", "Kuta"]

    log.info("=" * 50)
    log.info("SESSION START")
    log.info("=" * 50)

    checkin, checkout = get_checkin_checkout()
    log.info(f"Date range: {checkin} to {checkout}")

    # df = load_dataframe()
    driver = None
    tmp_profile = None
    driver, tmp_profile = build_driver()
    competitor_scrape = True

    try:
        log.info("Scraping customer mode.")
        url_find, manual_find = main_processing(source="json")
        driver, tmp_profile = customer_only(driver, url_find, manual_find, tmp_profile)
        
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                log.warning(f"Error quitting driver at session end: {e}")
        if tmp_profile:
            shutil.rmtree(tmp_profile, ignore_errors=True)
            log.info("Temp profile directory removed.")
        log.info("Driver shut down. Session END.")
        log.info("=" * 50)
    
if __name__ == "__main__":
    run()