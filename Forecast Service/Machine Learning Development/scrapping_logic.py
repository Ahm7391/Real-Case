import requests, json, os, pickle, re
import pandas as pd
import numpy as np
import asyncio
from datetime import date, timedelta
from datetime import datetime

from requests.exceptions import (
    Timeout,
    ConnectionError,
    HTTPError,
    RequestException,
)

from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
    Error as PlaywrightError,
)

# URL LIST, CAUTION!!! IT MIGHT CHANGE SOMEDAY DEPENDS ON THE WEBSITE AVAILABILITY
# ALWAYS CHECK REGULARLY
url1 = "https://dayoffapi.vercel.app/api"
url2 = "https://thebaliguideline.com/events"
url3 = "https://bali.live/p/the-bali-authorities-released-the-calendar-of-events-for-2026"

# ========================================================================================
# ==================== FIRST SCRIPT LOOK FOR NATIONAL PUBLIC HOLIDAYS ====================
# ========================================================================================
try:
    print(f"[INFO] Sending request to {url1}")
    response = requests.get(url1, timeout=15)
    response.raise_for_status()  # catches 4xx / 5xx

    try:
        buffer_tank = response.json()
    except json.JSONDecodeError:
        raise RuntimeError(
            "[FATAL] API did not return valid JSON. "
            "Response format may have changed."
        )

    if not isinstance(buffer_tank, list):
        raise RuntimeError(
            "[FATAL] API response structure changed. "
            "Expected a list."
        )
    else:
        print(f"[INFO] Received {len(buffer_tank)} records from API")

    date_buffer = []
    event_buffer = []

    for idx, item in enumerate(buffer_tank):
        try:
            date_buffer.append(item["tanggal"])
            event_buffer.append(item["keterangan"])
        except KeyError as e:
            raise RuntimeError(
                f"[FATAL] Missing key {e} in API response at index {idx}. "
                "API contract changed."
            )

    summary_holiday = pd.DataFrame({
        "Date": date_buffer,
        "Event": event_buffer
    })
    print(f"[INFO] Dataframe shape : {summary_holiday.shape}")

    result_path = os.getcwd() + "/PKL/holiday_summary.pkl"
    try:
        with open(result_path, "wb") as f:
            pickle.dump(summary_holiday, f)
    except OSError as e:
        raise RuntimeError(
            f"[FATAL] Failed to write file: {result_path}. "
            f"OS error: {e}"
        )

    print(f"Success saving to {result_path}")

except Timeout:
    print("[FATAL] API request timed out.")
    print("[ACTION REQUIRED] Check API availability or increase timeout.")

except ConnectionError:
    print("[FATAL] Cannot connect to API (network / DNS issue).")

except HTTPError as e:
    print(f"[FATAL] API returned HTTP error: {e.response.status_code}")

except RequestException as e:
    print("[FATAL] Unexpected request error:", e)

except RuntimeError as e:
    print(str(e))
    print("[ACTION REQUIRED] Update API parsing logic.")

except Exception as e:
    print("[FATAL] Unexpected error:", e)

# ========================================================================================
# ==================== SECOND SCRIPT LOOK FOR OTHER EVENTS IN BALI =======================
# ========================================================================================

date_container = []
event_name_container = []
location_container = []

async def scrapper1():
    print(f"[INFO] Starting scrapper for {url2}")
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                response = await page.goto(url2, timeout=60_000, wait_until="networkidle")
                if not response or not response.ok:
                    raise RuntimeError(
                        f"[FATAL] URL unreachable or returned bad status: "
                        f"{response.status if response else 'NO RESPONSE'}"
                    )
                else:
                    print(f"[INFO] Page loaded with status {response.status}")
            except PlaywrightTimeoutError:
                raise RuntimeError("[FATAL] Page load timeout – URL may be invalid or blocked")

            try:
                print(f"[INFO] Waiting for 'a.group.block' selector")
                await page.wait_for_selector("a.group.block", timeout=15_000)
            except PlaywrightTimeoutError:
                raise RuntimeError(
                    "[FATAL] Required selector 'a.group.block' not found. "
                    "Page structure likely changed."
                )

            cards = await page.query_selector_all("a.group.block")

            if not cards:
                raise RuntimeError(
                    "[FATAL] Page loaded but no cards found. "
                    "Scraping logic likely outdated."
                )

            print(f"[INFO] Found {len(cards)} cards")

            print(f"[INFO] Extracting data from cards")
            for i, card in enumerate(cards, start=1):
                date_el = await card.query_selector("div.text-sm.font-bold")
                name_el = await card.query_selector("h3.font-bold.text-lg")
                loc_el = await card.query_selector("div.absolute")

                if date_el:
                    date_text = (await date_el.inner_text()).strip()
                    date_container.append(date_text)
                else:
                    print(f"[WARN] Card {i}: Date not found")

                if name_el:
                    name_text = (await name_el.inner_text()).strip()
                    event_name_container.append(name_text)
                else:
                    print(f"[WARN] Card {i}: Event name not found")

                if loc_el:
                    loc_text = (await loc_el.inner_text()).strip()
                    location_container.append(loc_text)
                else:
                    print(f"[WARN] Card {i}: Location not found")

            print(f"[INFO] Scraped {len(event_name_container)} events")
            await browser.close()
        summary_events = {
            "Events Name": event_name_container,
            "Date": date_container,
            "Location": location_container
        }

        summary_events_df = pd.DataFrame(summary_events)
        summary_path = os.getcwd() + "/PKL/events_summary.pkl"  
        with open(summary_path, "wb") as f:
            pickle.dump(summary_events_df, f)
            print(f"success saving to {summary_path}")

    except RuntimeError as e:
        # Developer-facing alerts
        print(str(e))
        print("[ACTION REQUIRED] Please update URL or selectors.")
        return

    except PlaywrightError as e:
        print("[FATAL] Playwright internal error:", e)
        return

    except Exception as e:
        print("[FATAL] Unexpected error:", e)
        return

# ========================================================================================
# ================== THIRD SCRIPT LOOK FOR ADDITIONAL EVENTS IN BALI =====================
# ========================================================================================

async def scrapper2():
    try:
        print(f"[INFO] Starting scrapper for {url3}")
        keyword_extended_events = ["festival", "marathon", "exhibition", "running"]
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # ---- PAGE LOAD ----
            try:
                response = await page.goto(url3, timeout=60_000, wait_until="networkidle")
                if not response or not response.ok:
                    raise RuntimeError(
                        f"[FATAL] URL unreachable or returned bad status: "
                        f"{response.status if response else 'NO RESPONSE'}"
                    )
                else:
                    print(f"[INFO] Page loaded with status {response.status}")
            except PlaywrightTimeoutError:
                raise RuntimeError("[FATAL] Page load timeout – URL may be invalid or blocked")

            await page.wait_for_load_state("domcontentloaded")

            # ---- REQUIRED ROOT CONTAINER ----
            try:
                print(f"[INFO] Waiting for 'div.article__content' selector")
                await page.wait_for_selector(
                    "div.article__content",
                    state="attached",
                    timeout=30_000
                )
            except PlaywrightTimeoutError:
                raise RuntimeError(
                    "[FATAL] 'div.article__content' not found. "
                    "Page structure likely changed."
                )

            # ---- MONTH HEADERS ----
            print(f"[INFO] Extracting month headers and events")
            month_headers = page.locator("div.article__content h3")
            count = await month_headers.count()

            if count == 0:
                raise RuntimeError(
                    "[FATAL] No month <h3> headers found. "
                    "Scraping logic outdated."
                )

            results = {}

            print(f"[INFO] Found {count} month headers")
            for i in range(count):
                h3 = month_headers.nth(i)
                month = (await h3.inner_text()).strip()

                # FIRST ul after h3
                ul = h3.locator("xpath=following-sibling::ul[1]")
                if await ul.count() == 0:
                    # Non-fatal: some h3 may not be months
                    continue

                li_items = ul.locator("li")
                li_count = await li_items.count()

                if li_count == 0:
                    # Non-fatal but suspicious
                    print(f"[WARN] Month '{month}' has empty event list")
                    continue

                events = []
                for j in range(li_count):
                    text = (await li_items.nth(j).inner_text()).strip()
                    if text:
                        # filtering only take sentence that contains keyword keyword_extended_events
                        # print(f"[DEBUG] Processing event text: {text}")
                        # for sentence in text:
                        s = text.lower()
                        # print(f"[DEBUG] Lowercase event text: {s}")
                        if any(word in s for word in keyword_extended_events):
                            events.append(text)
                results[month] = events

            print(f"[INFO] Scraped events for {len(results)} months")
            await browser.close()

            # ---- DEBUG OUTPUT ----
            for month, events in results.items():
                print(f"\n{month}")
                for e in events:
                    print("-", e)

            extra_events_path = os.getcwd() + "/PKL/extra_events.pkl"  
            with open(extra_events_path, "wb") as f:
                pickle.dump(results, f)
                print(f"success saving to {extra_events_path}")

    except RuntimeError as e:
        # Developer-facing alert
        print(str(e))
        print("[ACTION REQUIRED] Update URL or scraping selectors.")
        return

    except PlaywrightError as e:
        print("[FATAL] Playwright internal error:", e)
        return

    except Exception as e:
        print("[FATAL] Unexpected error:", e)
        return

# ========================================================================================
# =============================== RELIGIOUS EVENTS ===================================
# ========================================================================================
async def scrapper3():
    summary_events = {}
    try:
        for x in range(1, 13):
            URL4 = f"https://m.kalenderbali.org/?tg=1&bl={x}&th=2026&ok=OK"
            async with async_playwright() as p:
                print(f"[INFO] Starting scrapper for {URL4}")
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                try:
                    response = await page.goto(URL4, timeout=60_000, wait_until="networkidle")
                    if not response or not response.ok:
                        raise RuntimeError(
                            f"[FATAL] URL unreachable or returned bad status: "
                            f"{response.status if response else 'NO RESPONSE'}"
                        )
                except PlaywrightTimeoutError:
                    raise RuntimeError("[FATAL] Page load timeout – URL may be invalid or blocked")

                try:
                    print(f"[INFO] Waiting for 'div.foredaftar' selector")
                    await page.wait_for_selector(
                        "div.foredaftar",
                        timeout=30_000
                    )
                except PlaywrightTimeoutError:
                    raise RuntimeError(
                        "[FATAL] 'div.foredaftar' not found. "
                        "Page structure likely changed."
                    )

                rows = page.locator("div.foredaftar li")
                count = await rows.count()
                print(f"[INFO] Found {count} <li> items for month {x}")

                if count == 0:
                    raise RuntimeError(
                        "[FATAL] No month <li> headers found. "
                        "Scraping logic outdated."
                    )

                collected_days = []
                for i in range(count):
                    li = rows.nth(i)
                    text = (await li.inner_text()).strip()
                    collected_days.append(text)
                summary_events[x] = collected_days
                print(f"Month {x}: {collected_days}")
                await browser.close()

        religius_events_path = os.getcwd() + "/PKL/religius_events.pkl"  
        with open(religius_events_path, "wb") as f:
            pickle.dump(summary_events, f)
            print(f"success saving to {religius_events_path}")
        
    except RuntimeError as e:
        # Developer-facing alert
        print(str(e))
        print("[ACTION REQUIRED] Update URL or scraping selectors.")
        return

    except PlaywrightError as e:
        print("[FATAL] Playwright internal error:", e)
        return

    except Exception as e:
        print("[FATAL] Unexpected error:", e)
        return

# RUN THE ASYNC SCRAPPERS
async def main():
    print("[INFO] Starting asynchronous scrapers")
    await scrapper1()
    await scrapper2()
    await scrapper3()

if __name__ == "__main__":
    asyncio.run(main())

# ========================================================================================
# =============================== LOADING AND CLEANING ===================================
# ========================================================================================
# Dataframe format
result_path = os.getcwd() + "/PKL/holiday_summary.pkl"
with open(result_path, 'rb') as file:
    loaded_data_hs = pickle.load(file)
    print(f"[INFO] Loaded holiday summary with shape {loaded_data_hs.shape}")

# Dataframe format
summary_path = os.getcwd() + "/PKL/events_summary.pkl" 
with open(summary_path, 'rb') as file:
    loaded_data_es = pickle.load(file)
    print(f"[INFO] Loaded events summary with shape {loaded_data_es.shape}")

# Dictionaries format
extra_events_path = os.getcwd() + "/PKL/extra_events.pkl" 
with open(extra_events_path, 'rb') as file:
    loaded_data_ep = pickle.load(file)
    print(f"[INFO] Loaded extra events.")

# Dictionaries format
religious_event_path = os.getcwd() + "/PKL/religius_events.pkl"
with open(religious_event_path, 'rb') as file:
    loaded_data_re = pickle.load(file)

# EXTRACT THE NATIONAL HOLIDAY DATES =======================================
print(f"[INFO] Extracting dates from holiday summary")
date_container = loaded_data_hs['Date'].tolist()

# EXTRACT THE ADDITIONAL EVENTS DATES =======================================
print(f"[INFO] Extracting and cleaning dates from events summary")
pattern = r'(\d{1,2})-([A-Z]{3})'
month_map = {
    'JAN': '01', 'FEB': '02', 'MAR': '03',
    'APR': '04', 'MAY': '05', 'JUN': '06',
    'JUL': '07', 'AUG': '08', 'SEP': '09',
    'OCT': '10', 'NOV': '11', 'DEC': '12'
}
date_container_2 = loaded_data_es['Date'].tolist()

cleaned = []

for d in date_container_2:
    day, mon = re.search(pattern, d).groups()
    cleaned.append(f"2026-{month_map[mon]}-{int(day):02d}")

# EXTRACT EXTRA EVENTS NAME ==================================================
print(f"[INFO] Extracting and expanding dates from extra events")
month_map = {
    'January': 1, 'February': 2, 'March': 3, 'April': 4,
    'May': 5, 'June': 6, 'July': 7, 'August': 8,
    'September': 9, 'October': 10, 'November': 11, 'December': 12
}

date_pattern = re.compile(
    r'(\d{1,2})'                                  # start day
    r'(?:\s*[–—-]\s*(\d{1,2}))?'                  # optional end day
    r'\s+([A-Za-z]+)'                             # start month
    r'(?:\s*[–—-]\s*(\d{1,2})\s+([A-Za-z]+))?'    # optional cross-month
    r'\s+(\d{4})'                                 # year
)

def expand_dates(d1, d2):
    out = []
    while d1 <= d2:
        out.append(d1.isoformat())
        d1 += timedelta(days=1)
    return out

def extract_all_dates(events_dict):
    results = []

    for events in events_dict.values():
        for text in events:
            for m in date_pattern.finditer(text):
                d1, d2, m1, d3, m2, y = m.groups()
                y = int(y)

                start = date(y, month_map[m1], int(d1))

                if d2 and not m2:
                    # same-month range
                    end = date(y, month_map[m1], int(d2))
                elif d3 and m2:
                    # cross-month range
                    end = date(y, month_map[m2], int(d3))
                else:
                    # single date
                    end = start

                results.extend(expand_dates(start, end))

    return results

correct_dates = extract_all_dates(loaded_data_ep)
# all_dates = date_container + cleaned + correct_dates
# print(f"[INFO] Total extracted dates before deduplication: {len(all_dates)}")

def sorting_dates(date_list):
    unique_sorted_dates = sorted({
        datetime.strptime(d, "%Y-%m-%d").date().isoformat()
        for d in date_list
    })
    return unique_sorted_dates

# EXTRACT RELIGIOUS EVENTS ==================================================
lookout_words = ['galungan', 'kuningan']

def extract_matching_sentences(json_data, lookout_words):
    lookout = [w.lower() for w in lookout_words]
    matches = []

    for values in json_data.values():
        for sentence in values:
            s = sentence.lower()
            if any(word in s for word in lookout):
                matches.append(sentence)

    return matches

results = extract_matching_sentences(loaded_data_re, lookout_words)
date_pattern = re.compile(r'(\d{2}-\d{2}-\d{4})')
def extract_dates_from_sentences(sentences):
    dates = []
    for sentence in sentences:
        match = date_pattern.search(sentence)
        if match:
            dates.append(datetime.strptime(match.group(1), "%d-%m-%Y").date().isoformat())
    return dates
extracted_dates = extract_dates_from_sentences(results)

date_container_sorted = sorting_dates(date_container)
cleaned_sorted = sorting_dates(cleaned)
correct_dates_sorted = sorting_dates(correct_dates)
extracted_dates_sorted = sorting_dates(extracted_dates)

# ========================================================================================
# =============================== BACKUP AND SAVING FILE =================================
# ========================================================================================

# Dataframe format
result_path_json = os.getcwd() + "/JSON/holiday_summary.json"
with open(result_path_json, 'w') as file:
    json.dump(date_container_sorted, file, indent=4)
    print(f"[INFO] Saved holiday summary to JSON with shape {len(date_container_sorted)}")

# Dataframe format
summary_path_json = os.getcwd() + "/JSON/events_summary.json" 
with open(summary_path_json, 'w') as file:
    json.dump(cleaned_sorted, file, indent=4)
    print(f"[INFO] Saved events summary to JSON with shape {len(cleaned_sorted)}")

# Dictionaries format
extra_events_path_json = os.getcwd() + "/JSON/extra_events.json" 
with open(extra_events_path_json, 'w') as file:
    json.dump(correct_dates_sorted, file, indent=4)
    print(f"[INFO] Saved extra events to JSON with shape {len(correct_dates_sorted)}")

# Dictionaries format
religious_event_path_json = os.getcwd() + "/JSON/religious_events.json"
with open(religious_event_path_json, 'w') as file:
    json.dump(extracted_dates_sorted, file, indent=4)
    print(f"[INFO] Saved religious events to JSON with shape {len(extracted_dates_sorted)}")
