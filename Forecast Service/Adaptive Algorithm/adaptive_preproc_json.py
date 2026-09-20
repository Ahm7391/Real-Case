# Backup/api_connect.py
import json, time, logging
import random, os, requests
from datetime import datetime, timedelta
import time, logging

from fastapi import FastAPI
from fastapi import HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

load_dotenv()

TRAINING_BUFFER_FILE = "training_mat.json"
INFERENCE_BUFFER_FILE = "inference_mat.json"
API_ENDPOINT = "http://localhost:8000/api/forecast-demo"
API_KEY = os.getenv("TOKEN_SERVER")
PREDICTION_PROGRESS_URL = os.getenv("PREDICTION_PROGRESS_URL", "http://127.0.0.1:8000/api/prediction-progress")
CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
FOLDER_PATH_COMPRATE = os.path.join(CURR_DIR, "Comprate")
MAX_DAYS_PER_REQUEST = 90

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

app = FastAPI(title='VPS Data Receiver')

@app.get("/")
def root():
    return {"message": "VPS API is running and ready to receive data"}

def report_progress(job_id: str, customer_id: int, progress_percent: int, stage_name: str, message: str, status: str = "running"):
    """
    Sends pipeline progress status to Laravel backend endpoint (prediction_progress).
    """
    payload = {
        "job_id": str(job_id),
        "customer_id": int(customer_id) if customer_id else None,
        "progress_percent": int(progress_percent),
        "stage_name": stage_name,
        "message": message,
        "status": status,
    }
    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}" if API_KEY else ""
        }
        response = requests.post(PREDICTION_PROGRESS_URL, json=payload, headers=headers, timeout=5)
        print(f"[PROGRESS {progress_percent}%] {stage_name}: {message} (Status: {response.status_code})")
    except Exception as e:
        print(f"[PROGRESS WARNING] Could not report progress ({progress_percent}%): {e}")

def error_logger(error_msg, customer_id=None):
    datetime_format_save = datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
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

    # Milestone 2: Data successfully aggregated into inference buffer (15% progress)
    req_info = load_id()
    if req_info:
        job_id = req_info.get("job_identification", "")
        cust_id = req_info.get("data", {}).get("customer_id")
        report_progress(
            job_id=job_id,
            customer_id=cust_id,
            progress_percent=15,
            stage_name="adaptive_data_buffered",
            message="Historical booking data successfully fetched and aggregated.",
            status="running"
        )

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
        "Content-Type": "application/json"
    }

    print("\nSending request to API...")
    try:
        response = requests.post(API_ENDPOINT, headers=headers, json=payload)
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
    
def fetch_data_bak():
    incoming_order = load_id()

    customer_name = incoming_order['data']['customer_id']
    start_date = datetime.today().date() - timedelta(days=365)
    end_date = datetime.today().date()
    try:
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
                result = send_request(payload)
                if not result:
                    logging.warning(f"No data found for {chunk_start} → {chunk_end}, skipping...")
                    continue
            
                elif isinstance(result, list):
                    aggregated_results.extend(result)
                else:
                    # If API returns non-list JSON, append raw
                    aggregated_results.append(result)

                logging.info(f"Added {len(result)} records from this chunk.")
            except requests.exceptions.RequestException as e:
                logging.error(f"Request failed for chunk {chunk_start} → {chunk_end}: {e}")
                continue
            except Exception as e:
                logging.error(f"Unknown error: {e}")
                continue

            # If there are more chunks, sleep before the next call
            if idx < total_chunks:
                time.sleep(2 + (time.time() % 1))  # sleep between 2 and 3 seconds

        # Save aggregated result to buffer
        if aggregated_results != []:
            buffer_data(aggregated_results)

        return {
            "status": "success",
            "message": "Data fetched and buffered successfully.",
            "buffer_file": INFERENCE_BUFFER_FILE,
            "api_response": result
        }
    except HTTPException as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        raise
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/fetch")
def fetch_endpoint():
    return fetch_data_bak()
