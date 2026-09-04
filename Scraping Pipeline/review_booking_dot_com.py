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
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import StaleElementReferenceException
from urllib.parse import urlparse, parse_qs, urlencode

# CONFIG AND ROBOTS.TXT RULES
LOG_FILE       = "scraper_comments.log"
MAX_PROPERTIES = 35          # max hotels to scrape per session
SLEEP_MIN      = 5           # seconds between requests (min)
SLEEP_MAX      = 7           # seconds between requests (max)
PAGE_TIMEOUT   = 20          # seconds to wait for DOM element
DRIVER_RECYCLE_EVERY = 10  

# Ubud search config
DEST_ID        = "-2701757"  # Ubud's stable Booking.com city ID
DEST_TYPE      = "city"
LANG           = "en-us"
ADULTS         = 1
ROOMS          = 1
CHILDREN       = 0

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

def simplify_booking_url(url: str, def_ckin=None, def_ckout=None) -> str:
    """
    Strip a Booking.com hotel URL down to only the essential params:
    aid, checkin, checkout, group_adults, req_adults, no_rooms
    """
    if def_ckin == None and def_ckout == None:
        date_ci, date_co = get_checkin_checkout()
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

def polite_sleep() -> None:
    """Sleep a random interval within the configured polite range."""
    duration = random.uniform(SLEEP_MIN, SLEEP_MAX)
    log.info(f"  Sleeping {duration:.1f}s …")
    time.sleep(duration)

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
                    print(f"Could not click Next on page {page}, stopping early. Reason: {e}")
                    break

        review_df = pd.DataFrame(card_master)
        return review_df
    except Exception as e:
        raise Exception("Error in finding review card!") from e
    
def scrape_hotel_reviews(
    driver: webdriver.Chrome,
    hotel_url: str,
) -> dict | None:
    """
    Visit a hotel page with date params and extract the displayed price.
    Returns a record dict or None if extraction fails.
    """

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

    ckin_dt, _ = get_checkin_checkout()
    hotel_url_new = simplify_booking_url(hotel_url)
    dt = datetime.strptime(ckin_dt, "%Y-%m-%d")  # use your actual format
    day_weekday = dt.strftime("%A")

    dt_now = datetime.today()
    dt_now_rev = dt_now.strftime("%Y-%m-%d")

    if not is_allowed(hotel_url):
        print(f"Blocked by robots.txt guard: {hotel_url}")
        return None
    
    print(f"  Scraping: {hotel_url_new}")

    property_name = None

    # wait for the container that holds the table
    date_avail = False
    only_once_pname = True
    new_ckin = ckin_dt
    trials_counter = 0

    while date_avail == False:
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
                        if trials_counter > 5:
                            time.sleep(5)
                            raise RuntimeError("Trials changing date exceeding limits (5) times.")

                        log.info("The availability on current date is not available, renew the date range.")
                        new_ckin, new_ckout = renew_checkin_checkout(new_ckin)
                        hotel_url_new = simplify_booking_url(hotel_url_new, def_ckin=new_ckin, def_ckout=new_ckout)
                        continue
                except (TimeoutException, NoSuchElementException):
                    print("Unknown exceptions, can't find any booking data at all, check actual conditions.")
                    return 0
                except RuntimeError as e:
                    print(f"Caught a runtime error: {e}")
                    return 0
                except Exception as e:
                    print(f"Caught Unknown error: {e} \nPlay safe and throing empty data instead!")
                    return 0
            except StaleElementReferenceException:
                log.warning("Row became stale, retrying...")
                continue
        except Exception as e:
            log.warning("Encountering unknown error probably due to long loaidng time, skipping this property!")
            return 0
        
        date_avail = True
        
    commentaries_df = scrape_commentaries(driver, hotel_url)
    if commentaries_df is not None and not commentaries_df.empty:
        safe_name = sanitize_filename(property_name)
        target_dir = os.path.join("property_reviews_new", f"reviews_property_{safe_name}.pkl")
        
        os.makedirs("property_reviews_new", exist_ok=True)  # create folder if missing
        commentaries_df.to_pickle(target_dir)
        log.info(f"Saved reviews to: {target_dir}")
    else:
        log.info(f"Skipping pickle save — empty DataFrame for: {property_name}")

def run():
    log.info("=" * 50)
    log.info("SESSION START")
    log.info("=" * 50)

    checkin, checkout = get_checkin_checkout()
    log.info(f"Date range: {checkin} → {checkout}")

    # df = load_dataframe()
    driver = None
    tmp_profile = None
    driver, tmp_profile = build_driver()

    def get_base_url(url):
        return url.strip().split('?')[0] + '?'
    
    try:
        new_urls = []
        debug_counter = 0
        allowed_proceed = False
        only_once = True
        break_signal = False
        if os.path.exists("checkpoint_review_save.txt"):
            with open("checkpoint_review_save.txt", "r") as f:
                cross_check = f.read()
                print(f"cross_check is : {cross_check}")

        with open("URL_text_list.txt", "r") as file:
            print(f"found url_text_list")
            lines = file.readlines()
            last_line = lines[-1].strip()

            i = 0
            while i < len(lines):
                # find starting point from last checkpoint
                # print(f"last_line is : {last_line}")
                # print(f"lines[i] is : {lines[i]}")
                # print(f"cross_check is : {cross_check}")
                cross_check_result = get_base_url(last_line) == get_base_url(cross_check)
                if lines[i].strip() == last_line or cross_check_result:
                    i = 0
                    break_signal = True

                # find starting point from last checkpoint
                if only_once == True and os.path.exists("checkpoint_review_save.txt"):
                    # pattern = re.escape(lines[i])
                    # print(f"pattern is : {pattern}")
                    # result = bool(re.search(pattern, cross_check))
                    # base_url = lines[i].strip().split('?')[0] + '?'
                    result = get_base_url(lines[i]) == get_base_url(cross_check)
                    if result == True:
                        print("Found last checkpoint!!!")
                        allowed_proceed = True
                        only_once = False
                        continue # GOT IT WE FOUND LAST CHECKPOINT, SKIP AND READ NEXT LINE!

                if allowed_proceed == True or not os.path.exists("checkpoint_review_save.txt"):
                    # print("We can continue!!!!")
                    # url_convert = simplify_booking_url(line)
                    # new_urls.append(url_convert)
                    # url_convert = simplify_booking_url(line)
                    new_urls.append(lines[i])
                    debug_counter += 1

                i += 1
                if break_signal == True or debug_counter > MAX_PROPERTIES: 
                    log.info("Safe guarding with 35 properties limiter, breaking algorithm now!")
                    break

        targets = new_urls[:MAX_PROPERTIES]
        log.info(f"Targeting {len(targets)} hotels this session.")

        BATCH_SIZE = 5
        batch = []
        processed = 0   # tracks hotels scraped since last recycle

        for idx, url in enumerate(targets, 1):
            # Recycle driver every N hotels (skip recycle on very first iteration
            # since we already have a fresh driver from build_driver() above)
            if processed > 0 and processed % DRIVER_RECYCLE_EVERY == 0:
                driver, tmp_profile = recycle_driver(driver, tmp_profile)

            log.info(f"[{idx}/{len(targets)}] Scraping …")
            record = scrape_hotel_reviews(driver, url)

            if record:
                batch.append(record)
                with open("checkpoint_review_save.txt", "w") as f:
                    f.write(f"{url}\n")

            processed += 1
            polite_sleep()

            # Flush batch to disk every BATCH_SIZE records
            if len(batch) >= BATCH_SIZE:
                log.info(f"Flushed batch of {len(batch)} records.")
                batch.clear()

        # Flush any remaining records
        if batch:
            log.info(f"Flushed final batch of {len(batch)} records.")

        log.info(f"[DEBUG] Session complete.")

    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
    finally:
        if driver:
            driver.quit()
        if tmp_profile:
            shutil.rmtree(tmp_profile, ignore_errors=True)
            log.info("Temp profile directory removed.")
        log.info("Driver shut down. Session END.")
        log.info("=" * 50)   
    
if __name__ == "__main__":
    run()
