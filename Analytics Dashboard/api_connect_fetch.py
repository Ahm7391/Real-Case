#!/usr/bin/env python3
import requests, logging
import json
from datetime import datetime, timedelta
import time, logging
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import time


# CONFIG ----------------------------------------------------------------- 
API_TOKEN = "analytics-demo-token"
BUFFER_FILE = "cust_details.json"
MAX_DAYS_PER_REQUEST = 90

# THIS IS TO RECEIVE DATA FETCHING FROM NEW ENDPOINT
API_ENDPOINT = "http://localhost:8000/api/analytics-demo"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
app = FastAPI(title='VPS Data Receiver')

@app.get("/")
def root():
    return {"message": "VPS API is running and ready to receive data"}

def get_date(prompt):
    while True:
        date_str = input(f"Enter {prompt} date (YYYY-MM-DD): ").strip()
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
            return date_str
        except ValueError:
            print("Invalid date format. Please use YYYY-MM-DD.")

def build_payload(customer_id, day_start, day_end):
    print(f"Customer id is {customer_id}, day_start is {day_start},"
                f" day end is {day_end}")
    return {
        "customer_id": customer_id,
        "start_date": day_start,
        "finish_date": day_end,
    }

def buffer_data(data):
    with open(BUFFER_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print(f"Response buffered to {BUFFER_FILE}")

def chunk_date_range(day_start: datetime, day_end: datetime, max_days: int = MAX_DAYS_PER_REQUEST):
    chunks = []
    current_start = day_start

    while current_start <= day_end:
        current_end = min(current_start + timedelta(days=max_days - 1), day_end)
        chunks.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    return chunks

class FetchRequest(BaseModel):
    customer_name: str
    numeric_id : int
    day_start: str
    day_end: str

def send_request(payload):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}"
    }

    print("\nSending request to API...")
    try:
        response = requests.post(API_ENDPOINT, headers=headers, json=payload, timeout=15)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        if response.status_code == 404:
            logging.error(f"❌ Chunk {payload['start_date']} → {payload['end_date']} returned 404 (out of range or not found). Skipping...")     
        return response.json()
    except requests.exceptions.Timeout:
        raise RuntimeError("Request timed out. The server may be slow or unavailable.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")
    
    
# @app.get("/customers")
# def get_customers():
#     try:
#         customer_map = load_customer_map()
#         return {"customers": list(customer_map.keys())}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=str(e))
    
# @app.post("/fetch")
def fetch_data_bak(request):
    # get_customers()
    try:
        # Load customer map
        # customer_map = load_customer_map()
        
        # if request.customer_id not in customer_map:
        #     raise HTTPException(status_code=404, detail="Customer not found.")
        # Validate date formats
        try:
            day_start = datetime.strptime(request.day_start, "%Y-%m-%d")
            day_end = datetime.strptime(request.day_end, "%Y-%m-%d")
            request_typ = request.data_search_type
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")

        if day_start > day_end:
            raise HTTPException(status_code=400, detail="Start date cannot be after end date.")

        # Split into 90-day chunks
        date_chunks = chunk_date_range(day_start, day_end)
        aggregated_results = []
        total_chunks = len(date_chunks)

        for idx, (chunk_start, chunk_end) in enumerate(date_chunks, start=1):
            payload = build_payload(
                # customer_id=customer_map[request.customer_id],
                customer_id=request.numeric_id,
                day_start=chunk_start.strftime("%Y-%m-%d"),
                day_end=chunk_end.strftime("%Y-%m-%d"),
                # data_search_type=request_typ
            )
            try:
                result2 = send_request(payload)
                result = result2['data']
                if not result:
                    logging.warning(f"No data found for {chunk_start.date()} → {chunk_end.date()}, skipping...")
                    continue
            
                elif isinstance(result, list):
                    aggregated_results.extend(result)
                else:
                    # If API returns non-list JSON, append raw
                    aggregated_results.append(result)
                logging.info(f"Added {len(result)} records from this chunk.")
            except requests.exceptions.RequestException as e:
                logging.error(f"Request failed for chunk {chunk_start.date()} → {chunk_end.date()}: {e}")
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
            "buffer_file": BUFFER_FILE,
            "api_response": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/fetch")
def fetch_endpoint(request: FetchRequest):
    return fetch_data_bak(request)