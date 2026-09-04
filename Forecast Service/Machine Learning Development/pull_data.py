import json, time, logging
import random, os, requests
from datetime import datetime, timedelta
import time, logging

from fastapi import FastAPI
from fastapi import HTTPException

app = FastAPI(title='VPS Training Data Aggregator')
CUSTOMER_REQUEST = "https://lokapro.ecommerceloka.net/api/xcustomendpoint/production-booking/option"
API_ENDPOINT = "https://lokapro.ecommerceloka.net/api/xcustomendpoint/production-booking"
API_TOKEN = "sGAqwd5xhzkJ6X8mDrLntTYyk0RRvu1R"
FOLDER_PATH = "/workspaces/Ecommerce-Project/Machine Learning Development/buffer_customer"
MAX_DAYS_PER_REQUEST = 90

@app.get("/")
def root():
    return {"message": "VPS API is running and ready to receive data"}

def build_payload(customer_id, start_date, end_date):
    return {
        "customer_id": customer_id,
        "day_start": start_date,
        "day_end": end_date,
        "data_search_type": "booking_date"
    }

def buffer_data(data, CUSTOMER_ID):
    os.makedirs(FOLDER_PATH, exist_ok=True)
    cust_name_json = os.path.join(FOLDER_PATH, f"{CUSTOMER_ID}.json")
    with open(cust_name_json, "w") as f:
        json.dump(data, f, indent=4)
    print(f"Response buffered to {cust_name_json}")

def chunk_date_range(start_date: datetime, end_date: datetime, max_days: int = MAX_DAYS_PER_REQUEST):
    chunks = []
    current_start = start_date

    while current_start <= end_date:
        current_end = min(current_start + timedelta(days=max_days - 1), end_date)
        chunks.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    return chunks

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

def aggregator_data(cust_name, start_date, end_date):
    print("DEBUG: Starting data aggregator.")
    dt_start = datetime.strptime(start_date, "%Y-%m-%d").date()
    dt_end = datetime.strptime(end_date, "%Y-%m-%d").date()
    try:
        if dt_start > dt_end:
            raise HTTPException(status_code=400, detail="Start date cannot be after end date.")
        
        # Split into 90-day chunks
        date_chunks = chunk_date_range(dt_start, dt_end)
        aggregated_results = []
        total_chunks = len(date_chunks)
        print("Date length collected.")

        for idx, (chunk_start, chunk_end) in enumerate(date_chunks, start=1):
            payload = build_payload(
                customer_id=cust_name,
                start_date=chunk_start.strftime("%Y-%m-%d"),
                end_date=chunk_end.strftime("%Y-%m-%d")
            )

            try:
                result2 = send_request(payload)
                result = result2['booking_data']
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
            buffer_data(aggregated_results, cust_name)

        return {
            "status": "success",
            "message": "Data fetched and buffered successfully.",
            "buffer_file": f"{cust_name}.json",
            "api_response": result
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return 0