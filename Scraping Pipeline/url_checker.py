from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
import datetime, json, os, requests
from dotenv import load_dotenv
from pydantic import BaseModel

app = FastAPI(title="Check new URL in Database")
load_dotenv()

RECEIVE_COMPANY_API_KEY = os.getenv("AUTHENTICATION_API_KEY")
CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)

FOUND_URL_BOOKING = os.path.join(CURR_DIR, "found_url.json")
FOUND_URL_TIKET = os.path.join(CURR_DIR, "scrap_tiket_com", "found_url.json")

WEBHOOK_URL_LATER = os.getenv("POSTMAN_URL")
LOKAPRO_SERVER_REQUEST = os.getenv("LOKAPRO_SERVER_REQUEST")
API_KEY = os.getenv("SCRAPING_API_KEY")

class DynamicReq(BaseModel):
    property_name: str 
    url_tiket: str | None
    url_booking: str | None

def _load_json_file(file_path: str) -> list:
    """Helper to safely read a JSON array file."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError):
            return []
    return []
def _save_json_file(file_path: str, data: list):
    """Helper to safely write a JSON array file."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def library_update(payload_list: list):
    tiket_data = _load_json_file(FOUND_URL_TIKET)
    booking_data = _load_json_file(FOUND_URL_BOOKING)
    
    tiket_updated = False
    booking_updated = False
    for i in payload_list:
        prop_name = i.get("property_name", "")
        url_tiket = i.get("url_tiket")
        url_booking = i.get("url_booking")
        if url_tiket:
            master_format_tiket = {
                "properties_name": prop_name,
                "competitor_id": "",
                "slug": "",
                "match": "",
                "score": "",
                "url": url_tiket
            }
            tiket_data.append(master_format_tiket)
            tiket_updated = True
        if url_booking:
            master_format_booking = {
                "properties_name": prop_name,
                "competitor_id": "",
                "slug": "",
                "match": "",
                "score": "",
                "url": url_booking
            }
            booking_data.append(master_format_booking)
            booking_updated = True
    if tiket_updated:
        _save_json_file(FOUND_URL_TIKET, tiket_data)
        print("\n--- [Tiket] Last Entries Preview ---")
        print(json.dumps(tiket_data[-3:], indent=4))
    if booking_updated:
        _save_json_file(FOUND_URL_BOOKING, booking_data)
        print("\n--- [Booking.com] Last Entries Preview ---")
        print(json.dumps(booking_data[-3:], indent=4))

def request_by_system(focus_ota, use_company_api=True):
    """Trigger update request back to Laravel."""
    try:
        if use_company_api:
            url = LOKAPRO_SERVER_REQUEST
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {API_KEY}"
            }
        else:
            url = WEBHOOK_URL_LATER
            headers = {
                "Content-Type": "application/json"
            }
        
        data = {"content": "request update"}
        print(f"Sending request update to {url}...")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        # Fixed: status_code and text attributes
        if response.status_code == 200:
            print("Data successfully sent!")
        else:
            print(f"Failed to send data. Status: {response.status_code}, Response: {response.text}")
        # return response.json()
        raw_json = response.json()
        tiket_updated = False
        booking_updated = False

        booking_data = _load_json_file(FOUND_URL_BOOKING)
        tiket_data = _load_json_file(FOUND_URL_TIKET)
        for i in raw_json:
            prop_name = i.get("property_name", "")
            url_tiket = i.get("url_tiket")
            url_booking = i.get("url_booking")
            if focus_ota == "booking":
                booking_container = {
                    "properties_name": prop_name,
                    "competitor_id": "",
                    "slug": "",
                    "match": "",
                    "score": "",
                    "url":url_booking
                }
                booking_data.append(booking_container)
                booking_updated = True
            elif focus_ota == "tiket":
                tiket_container = {
                    "properties_name": prop_name,
                    "competitor_id": "",
                    "slug": "",
                    "match": "",
                    "score": "",
                    "url":url_tiket
                }
                tiket_data.append(tiket_container)
                tiket_updated = True
        
        if tiket_updated:
            _save_json_file(FOUND_URL_TIKET, tiket_data)
            print("\n--- [Tiket] Last Entries Preview ---")
            print(json.dumps(tiket_data[-3:], indent=4))
        if booking_updated:
            _save_json_file(FOUND_URL_BOOKING, booking_data)
            print("\n--- [Booking.com] Last Entries Preview ---")
            print(json.dumps(booking_data[-3:], indent=4))
            
    except Exception as e:
        print(f"Error sending Data: {e}")
        return None
        
@app.post("/url-probing")
def url_probing(
    request: list[dict], 
    background_tasks: BackgroundTasks,
    x_api_key: str = Header(None)
):
    if not x_api_key or x_api_key != RECEIVE_COMPANY_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key"
        )
    # Process updating found_url in the background
    background_tasks.add_task(library_update, request)
    return {
        "status": "success",
        "message": f"Received {len(request)} items for URL probing.",
        "count": len(request)
    }

    