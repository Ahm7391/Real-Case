# Backup/api_connect.py
import json, time, logging
import random, os, requests
from datetime import datetime, timedelta
import time, logging

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

TRAINING_BUFFER_FILE = "training_mat.json"
INFERENCE_BUFFER_FILE = "inference_mat.json"
CUSTOMER_REQUEST = os.getenv("CUST_REQUEST_URL")
API_ENDPOINT = os.getenv("ENDPOINT_URL")
API_TOKEN = os.getenv("TOKEN_SERVER")
# CUSTOMER_LIST = "/customer_list_folder/customer_list.json"
CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
FOLDER_PATH_COMPRATE = os.path.join(CURR_DIR, "Comprate")
MAX_DAYS_PER_REQUEST = 90

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI(title='VPS Data Receiver')

@app.get("/")
def root():
    return {"message": "VPS API is running and ready to receive data"}

def error_logger(error_msg, customer_id=None):
    datetime_format_save = datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
    with open(f"runtime_error_logger_{datetime_format_save}.txt", 'a') as f:
        f.write(f"Date: {datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
        f.write("\nStatus: RUNTIME ERROR OCCURED..\n")
        if error_msg:
            f.write(f"Error due to : {error_msg}")
        if customer_id:
            f.write(f"Customer id is : {customer_id}")

# ============================= INCOMING REQUEST FROM SERVER =============================
def read_incoming_data(work_id, payload: dict):
    # Validate required keys
    if "customer_id" not in payload:
        raise HTTPException(status_code=400, detail="Invalid payload format: No customer_id")
    
    if "predict_days" not in payload:
        raise HTTPException(status_code=400, detail="Invalid payload format: No predict_days")
    
    # if payload["predict_days"] >= 31:
    #     raise HTTPException(status_code=400, detail="Prediction days only limitied up to 31 days.")

    cust_id = payload['customer_id']
    print(f"found customer id: {cust_id}")
    data_to_save = {
        "job_identification":work_id,
        "received_at": datetime.utcnow().isoformat(),
        "data": payload
    }
    print(data_to_save)

    with open("cust_request.json", "w") as f:
        json.dump(data_to_save, f, indent=4)

    return cust_id


# ============================= FETCHING WITH 1 YEAR DATABASE FOR PREDICTION =============================
# def load_customer_map():
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {API_TOKEN}"
#     }

#     payload_cust = {
#         "mode":"list_customer"
#     }
#     print("\nSending request customer_list to API...")
#     try:
#         response = requests.post(CUSTOMER_REQUEST, headers=headers, json=payload_cust, timeout=15)
#         response.raise_for_status()  # Raises HTTPError for bad status codes
#     except requests.exceptions.Timeout:
#         raise RuntimeError("Request timed out. The server may be slow or unavailable.")
#     except requests.exceptions.HTTPError as e:
#         raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
#     except requests.exceptions.RequestException as e:
#         raise RuntimeError(f"Request failed: {e}")

#     folder_path = "/workspaces/Ecommerce-Project/Machine Learning Development/customer_list_folder"
#     os.makedirs(folder_path, exist_ok=True)

#     file_path = os.path.join(folder_path, "customer_list.json")
#     with open(file_path, "w") as f:
#         json.dump(response.json(), f, indent=4)
#     print(f"Response buffered to {CUSTOMER_LIST}")

#     if not os.path.exists(file_path):
#         raise FileNotFoundError(f"Customer JSON file not found: {file_path}")
    
#     with open(file_path, "r") as f:
#         data = json.load(f)

#     # Build dictionary: {customer_name: customer_id}
#     return {item["customer_name"]: item["customer_id"] for item in data.get("data", [])}

# def select_customer(customer_map):
#     print("\nAvailable customers:")
#     for name in sorted(customer_map.keys()):
#         print(f" - {name}")

#     customer_name = input("\nEnter customer name: ").strip()
#     if customer_name not in customer_map:
#         raise ValueError(f"Customer '{customer_name}' not found in list.")
    
#     return customer_name, customer_map[customer_name]

# def get_date(prompt):
#     while True:
#         date_str = input(f"Enter {prompt} date (YYYY-MM-DD): ").strip()
#         try:
#             datetime.strptime(date_str, "%Y-%m-%d")
#             return date_str
#         except ValueError:
#             print("Invalid date format. Please use YYYY-MM-DD.")

def build_payload(customer_id, start_date, finish_date):
    return {
        "customer_id": customer_id,
        "start_date": start_date,
        "finish_date": finish_date
    }

def buffer_data(data):
    with open(INFERENCE_BUFFER_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print(f"Response buffered to {INFERENCE_BUFFER_FILE}")

def buffer_data_complete(data, last_min, total_room):
    os.makedirs(FOLDER_PATH_COMPRATE, exist_ok=True)
    cust_name_json = os.path.join(FOLDER_PATH_COMPRATE, f"main_data_complete.json")
    with open(cust_name_json, "w") as f:
        json.dump(data, f, indent=4)
    print(f"Response buffered to {cust_name_json}")

    last_min_json = os.path.join(FOLDER_PATH_COMPRATE, f"last_min_rate.json")
    with open(last_min_json, "w") as f:
        json.dump(last_min, f, indent=4)
    print(f"Response buffered to {last_min_json}")

    with open('total_room.txt', 'w') as file:
        file.write(str(total_room))
    print(f"Response buffered to total_room.txt")

def chunk_date_range(start_date: datetime, end_date: datetime, max_days: int = MAX_DAYS_PER_REQUEST):
    chunks = []
    current_start = start_date

    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=max_days - 1), end_date)
        chunks.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    return chunks

class FetchRequest(BaseModel):
    service: str
    customer_id: str
    customer_name: str

def send_request(payload):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}"
    }

    print("\nSending request to API...")
    try:
        response = requests.post(API_ENDPOINT, headers=headers, json=payload, timeout=15, verify=False)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        if response.status_code == 404:
            logging.error(f"❌ Chunk {payload['start_date']} → {payload['end_date']} returned 404 (out of range or not found). Skipping...")     
        return response.json()
    except requests.exceptions.Timeout as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        raise RuntimeError("Request timed out. The server may be slow or unavailable.")
    except requests.exceptions.HTTPError as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
    except requests.exceptions.RequestException as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        raise RuntimeError(f"Request failed: {e}")

def load_id():
    if not os.path.exists("cust_request.json"):
        print(f"WARNING: data not found. Starting with empty buffer.")
        return {}
    else:
        with open("cust_request.json", "r") as f:
            data = json.load(f)
        return data
    
# @app.get("/customers")
# def get_customers():
#     try:
#         customer_map = load_customer_map()
#         return {"customers": list(customer_map.keys())}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
    
# @app.post("/fetch")
def fetch_data_bak():
    incoming_order = load_id()

    customer_name = incoming_order['data']['customer_id']
    start_date = datetime.today().date() - timedelta(days=365)
    end_date = datetime.today().date()
    # start_date = datetime.strptime(incoming_order['data']['start_date'], "%Y-%m-%d")
    # end_date = datetime.strptime(incoming_order['data']['finish_date'], "%Y-%m-%d")
    # get_customers()
    # print("A")
    try:
        # Load customer map
        # customer_map = load_customer_map()
        # print("B")
        # if customer_name not in customer_map:
        #     raise HTTPException(status_code=404, detail="Customer not found.")

        # Validate date formats
        start_dt = start_date
        end_dt = end_date
        # print("C")
        if start_dt > end_dt:
            raise HTTPException(status_code=400, detail="Start date cannot be after end date.")
        
        # Split into 90-day chunks
        date_chunks = chunk_date_range(start_dt, end_dt)
        aggregated_results = []
        total_chunks = len(date_chunks)

        just_once = True
        for idx, (chunk_start, chunk_end) in enumerate(date_chunks, start=1):
            payload = build_payload(
                customer_id=customer_name,
                start_date=chunk_start.strftime("%Y-%m-%d"),
                finish_date=chunk_end.strftime("%Y-%m-%d")
            )

            try:
                result2 = send_request(payload)
                result3 = result2.copy()
                # result = result2['booking_data']
                result = result2['data']
                # with open("Tumbal.json", "w") as f:
                #     json.dump(result, f, indent=4)
                if not result:
                    logging.warning(f"No data found for {chunk_start} → {chunk_end}, skipping...")
                    continue
            
                elif isinstance(result, list):
                    aggregated_results.extend(result)
                else:
                    # If API returns non-list JSON, append raw
                    aggregated_results.append(result)

                # if just_once == True:
                #     early_book = result3['compset_latest_rate']['early_booking']
                #     last_min_book = result3['compset_latest_rate']['last_minute_booking']
                #     total_room = result3["customer"]["total_room"]
                #     just_once = False
                logging.info(f"Added {len(result)} records from this chunk.")
            except requests.exceptions.RequestException as e:
                logging.error(f"Request failed for chunk {chunk_start} → {chunk_end}: {e}")
                continue

            # If there are more chunks, sleep before the next call
            if idx < total_chunks:
                time.sleep(2 + (time.time() % 1))  # sleep between 2 and 3 seconds

        # Save aggregated result to buffer
        if aggregated_results != []:
            buffer_data(aggregated_results)
            # buffer_data_complete(early_book, last_min_book, total_room)

        return {
            "status": "success",
            "message": "Data fetched and buffered successfully.",
            "buffer_file": INFERENCE_BUFFER_FILE,
            "api_response": result
        }
    except HTTPException as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id=customer_name)
        raise
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id=customer_name)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/fetch")
def fetch_endpoint():
    return fetch_data_bak()
