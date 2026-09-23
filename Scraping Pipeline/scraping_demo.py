import time
import random
import os, re, json, asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode
from concurrent.futures import ThreadPoolExecutor
from fetcher_logic import run_fetching
 
import pandas as pd
import numpy as np
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException
from webdriver_manager.chrome import ChromeDriverManager

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)

app = FastAPI(title="Scraping Demo pipeline")

# Enable CORS so frontend (Laravel / Blade / React / Vue) can establish SSE connection
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=2)

class QueueLogHandler(logging.Handler):
    """Custom log handler that forwards log records to an asyncio.Queue."""
    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.queue = queue
        self.loop = loop

    def emit(self, record):
        try:
            msg = self.format(record)
            self.loop.call_soon_threadsafe(self.queue.put_nowait, msg)
        except Exception:
            self.handleError(record)

DEST_ID        = "-2701757"  # Ubud's stable Booking.com city ID
DEST_TYPE      = "city"
LANG           = "en-us"
LOG_FILE       = "scraper.log"
ADULTS         = 2
ROOMS          = 1
CHILDREN       = 0
SLEEP_MIN      = 3           # seconds between requests (min)
SLEEP_MAX      = 5           # seconds between requests (max)
PAGE_TIMEOUT   = 10          # seconds to wait for DOM element

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
def is_allowed(url: str):
    path = urlparse(url).path
    if any(path.startswith(p) for p in DISALLOWED_PATH_PREFIXES):
        return False
    if any(path.startswith(p) for p in ALLOWED_PATH_PREFIXES):
        return True
    # Default: disallow anything not explicitly in our allowed list
    return False

import sys

def build_driver():
    options = Options()
    options.page_load_strategy = 'eager'
    
    # Enable headless mode in Linux / container environments or if HEADLESS is set
    if os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes") or sys.platform != "win32":
        options.add_argument("--headless=new")

    chrome_bin = os.getenv("CHROME_BIN")
    if chrome_bin and os.path.exists(chrome_bin):
        options.binary_location = chrome_bin

    options.add_argument("--disable-gpu")        # required on some VPS
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

    chromedriver_path = os.getenv("CHROMEDRIVER_PATH")
    if chromedriver_path and os.path.exists(chromedriver_path):
        service = Service(chromedriver_path)
    else:
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(
        service=service,
        options=options
    )
    driver.execute_cdp_cmd("Network.enable", {})
    driver.set_page_load_timeout(30)
    log.info("Chrome driver initialised.")
    return driver

def get_checkin_checkout(offset_days: int = 1):
    checkin  = datetime.today() + timedelta(days=offset_days)
    checkout = checkin + timedelta(days=1)
    return checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d")

def renew_checkin_checkout(cur_date, increment_day: int = 1):
    cur_date_clean = datetime.strptime(cur_date, "%Y-%m-%d")
    checkin  = cur_date_clean + timedelta(days=increment_day)
    checkout = checkin + timedelta(days=1)
    return checkin.strftime("%Y-%m-%d"), checkout.strftime("%Y-%m-%d")

def build_search_url(target_city: str, checkin: str, checkout: str):
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

def simplify_booking_url(url: str, def_ckin=None, def_ckout=None, offset_day=1):
    if def_ckin == None and def_ckout == None:
        date_ci, date_co = get_checkin_checkout(offset_days=offset_day)
    else:
        date_ci = def_ckin
        date_co = def_ckout
    KEEP_PARAMS = {"aid", "checkin", "checkout", "group_adults", "req_adults", "no_rooms"}

    parsed   = urlparse(url)
    params   = parse_qs(parsed.query, keep_blank_values=True)

    # parse_qs wraps values in lists e.g. {"aid": ["304142"]}
    # flatten back to single values
    filtered = {k: v[0] for k, v in params.items() if k in KEEP_PARAMS}
    filtered['checkin'] = date_ci
    filtered['checkout'] = date_co

    clean_url = parsed._replace(query=urlencode(filtered)).geturl()
    return clean_url

def polite_sleep():
    duration = random.uniform(SLEEP_MIN, SLEEP_MAX)
    log.info(f"  Sleeping {duration:.1f}s …")
    time.sleep(duration)

def soft_scroll(driver):
    last_height = driver.execute_script("return document.body.scrollHeight")
    current_position = 0

    while True:
        # Random chunk size (human scrolls vary between short and long flicks)
        chunk = random.randint(500, 1000)
        current_position += chunk

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
            time.sleep(2)  # wait a beat for any final lazy loads
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
                    time.sleep(1)
                last_height = new_height
                if new_height == last_height:
                    log.info("  [scroll] Reached stable bottom.")
                    break
            # Page grew — update and keep scrolling
            last_height = new_height

def scrape_hotel_price(
    driver: webdriver.Chrome,
    hotel_url: str,
    period_days: int,
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
    # dt = datetime.strptime(ckin_dt, "%Y-%m-%d") 
    # day_weekday = dt.strftime("%A")

    dt_now = datetime.today() 
    dt_now_rev = dt_now.strftime("%Y-%m-%d")

    if not is_allowed(hotel_url):
        print(f"Blocked by robots.txt guard: {hotel_url}")
        return None
    
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
                            property_name = wait.until(
                                EC.visibility_of_element_located(
                                    (By.CSS_SELECTOR, "div#hp_hotel_name h2")
                                )
                            ).text.strip()
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
                            except (TimeoutException, NoSuchElementException):
                                villa_or_hotel = None
                                rating = None
                                log.info("No hotel/villa info and rating info!")
                            break

                        except StaleElementReferenceException:
                            time.sleep(1)
                            continue
                    else:
                        property_name = None
                        villa_or_hotel = None
                        rating = None
                except (TimeoutException, NoSuchElementException):
                    property_name = None
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
            results = []
            data = {"room_type": None, "price": None, "notes": None, "date_scrapped": dt_now_rev, 'target_date':new_ckin, 'category': 'last-minute'}
            results.append(data)
            return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": 0, "rows": results}

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
                if len(tds) > 0:
                    price_td = tds[1]
                    # log.info(f"[DEBUG] apa isinya sih? {price_td.text.strip()}")
                    log.info("trigger scrolling to fight lazy loader")
                    if idx == 0: 
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
                                log.info("Secondary methods not working! Switching to tertiary method.")

                        if stage_pass == False:
                            for i in [0, 2]:
                                text_check = tds[i].text.strip()
                                match = re.search(r"Rp\s[\d,.]+", text_check)
                                if match:
                                    data["price"] = match.group()
                                    log.info(f"Tertiary method is working, price is {match.group()}")
                                    break
                                else:
                                    log.info("Tertiary method fails, need to check the actual website.")
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
    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": total_rows, "rows": results}

def scrape_hotel_price_early_book(
    driver: webdriver.Chrome,
    hotel_url: str,
    period_days: int,
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
    hotel_url_new = simplify_booking_url(hotel_url, offset_day=period_days)
    # dt = datetime.strptime(ckin_dt, "%Y-%m-%d")  
    # day_weekday = dt.strftime("%A")

    dt_now = datetime.today() 
    dt_now_rev = dt_now.strftime("%Y-%m-%d")

    if not is_allowed(hotel_url):
        print(f"Blocked by robots.txt guard: {hotel_url}")
        return None
    
    log.info(f"  Visiting: {hotel_url}")
    # driver.get(hotel_url)
    # wait = WebDriverWait(driver, PAGE_TIMEOUT)

    property_name = None
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
                            property_name = wait.until(
                                EC.visibility_of_element_located(
                                    (By.CSS_SELECTOR, "div#hp_hotel_name h2")
                                )
                            ).text.strip()
                            break

                        except StaleElementReferenceException:
                            time.sleep(1)
                            continue
                    else:
                        property_name = None
                except (TimeoutException, NoSuchElementException):
                    property_name = None
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
                if len(tds) > 0:
                    price_td = tds[1]
                    # log.info(f"[DEBUG] apa isinya sih? {price_td.text.strip()}")
                    log.info("trigger scrolling to fight lazy loader")
                    if idx == 0 :
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
                                log.info("Secondary methods not working! Switching to tertiary method.")
                                
                        if stage_pass == False:
                            for i in [0, 2]:
                                text_check = tds[i].text.strip()
                                match = re.search(r"Rp\s[\d,.]+", text_check)
                                if match:
                                    data["price"] = match.group()
                                    log.info(f"Tertiary method is working, price is {match.group()}")
                                    break
                                else:
                                    log.info("tertiary method also fails, need to check the actual website!")
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
    return {"property_name": property_name, "villa_or_hotel": villa_or_hotel, "rating": rating, "total_rows": total_rows, "rows": results}
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

def save_load_database(focus_df, scope):
    # data_df2 = pd.DataFrame()
    data_df2 = focus_df.copy()
    if os.path.exists(f"scraping_database_lm_{scope}.pkl"):
        loaded_df = pd.read_pickle(f"scraping_database_lm_{scope}.pkl")
        data_df2 = pd.concat([data_df2, loaded_df])
        data_df2 = data_df2.reset_index(drop=True)
        data_df2.to_pickle(f"scraping_database_lm_{scope}.pkl")

    else:
        data_df2.to_pickle(f"scraping_database_lm_{scope}.pkl")

def save_load_database_eb(focus_df, scope):
    # data_df2 = pd.DataFrame()
    data_df2 = focus_df.copy()
    if os.path.exists(f"scraping_database_eb_{scope}.pkl"):
        loaded_df = pd.read_pickle(f"scraping_database_eb_{scope}.pkl")
        data_df2 = pd.concat([data_df2, loaded_df])
        data_df2 = data_df2.reset_index(drop=True)
        data_df2.to_pickle(f"scraping_database_eb_{scope}.pkl")

    else:
        data_df2.to_pickle(f"scraping_database_eb_{scope}.pkl")

def master_scrape_flow(driver, targets, prop_scope):
    try:
        log.info(f"Targeting {len(targets)} properties this session.")

        batch = []
        batch_eb = []
        period_cycling = [7, 14]

        for idx, url in enumerate(targets, 1):
            log.info(f"[{idx}/{len(targets)}] Scraping …")
            for vii in period_cycling:
                log.info(f"Stratified sampling start at today + {vii} days")
                if vii <= 7:
                    record = scrape_hotel_price(driver, url, vii, trial_seed=2)
                    if record:
                        batch.append(record)
                elif vii > 7:
                    record_eb = scrape_hotel_price_early_book(driver, url, vii, trial_seed=2)
                    if record_eb:
                        batch_eb.append(record_eb)
                polite_sleep()

        if batch:
            df_batch = cleaning_data(dataframe_processing(batch))
            save_load_database(df_batch, scope=prop_scope)
            log.info(f"Flushed final batch of {len(batch)} records.")

        if batch_eb:
            df_batch_eb = cleaning_data(dataframe_processing(batch_eb))
            save_load_database_eb(df_batch_eb, scope=prop_scope)
            log.info(f"Flushed final batch of {len(batch)} records.")

        log.info(f"[URL LIST SCRAPING] Session complete.")
    except Exception as e:
        log.error(f"[URL LIST SCRAPING] Unexpected error: {e}", exc_info=True)
    finally:
            log.info("Finish processing URL listed competitor.")
            log.info("=" * 50)
    return driver

def execute_scraping_job():
    driver = build_driver()
    url_find_competitor = ["https://www.booking.com/hotel/id/oyo-491-coconut.html?aid=304142&checkin=2026-05-30&checkout=2026-05-31&group_adults=2&req_adults=2&no_rooms=1"]
    url_find_customer = ["https://www.booking.com/hotel/id/oyo-221-pratisarawirya.html?aid=304142&checkin=2026-05-30&checkout=2026-05-31&group_adults=2&req_adults=2&no_rooms=1"]
    try:
        log.info("Scraping competitor.")
        driver = master_scrape_flow(driver, url_find_competitor, prop_scope="competitor")
        log.info("Scraping customer")
        driver = master_scrape_flow(driver, url_find_customer, prop_scope="customer")
        log.info("Scraping is done, now we will send back the data to Laravel.")
        run_fetching()
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        if driver:
            try:
                driver.quit()
            except Exception as e:
                log.warning(f"Error quitting driver at session end: {e}")
        log.info("Driver shut down. Session END.")
        log.info("=" * 50)
        log.info("[STREAM_JOB_FINISHED]")

@app.get("/scraping-service-call")
async def run():
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    # Attach QueueLogHandler to root logger to capture all module logs
    handler = QueueLogHandler(queue, loop)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)

    # Dispatch synchronous scraping task to ThreadPoolExecutor
    loop.run_in_executor(executor, execute_scraping_job)

    async def event_generator():
        try:
            while True:
                msg = await queue.get()
                if "[STREAM_JOB_FINISHED]" in msg:
                    yield f"data: {json.dumps({'log': msg, 'done': True})}\n\n"
                    break
                yield f"data: {json.dumps({'log': msg, 'done': False})}\n\n"
        finally:
            root_logger.removeHandler(handler)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000)