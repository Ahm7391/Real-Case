import datetime, asyncio
import random
import string
import os

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, Header
from zoneinfo import ZoneInfo
from api_connect import save_incoming_data, load_id
from api_connect_fetch import fetch_data_bak
from main import process_data
from pydantic import BaseModel

app = FastAPI(title="Analytics Dashboard System")
jobs = {}

TESTING_KEY = "ANALYTICS_DASHBOARD"

def generate_tag_id(random_length=4):
    timestamp = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y%m%d%H%M")
    random_digits = ''.join(random.choices(string.digits, k=random_length))
    return timestamp + random_digits

def update_job_status(job_id: str, status_code: int, message: str, customer_id: str = ""):
    jobs[job_id] = {
        "key_id": job_id,
        "customer_id": customer_id,
        "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "status_code": status_code,
        "status_message": message
    }

def data_onboarding(key_id, cust_id, day_start, day_end):
    try:
        # payload = await request.json()
        # except Exception:
        #     raise HTTPException(status_code=400, detail="Invalid JSON format")

        # if not isinstance(payload, dict):
        #     raise HTTPException(status_code=400, detail="Payload must be a JSON object")

        # FOR DEMO THE DATA WILL BE LIMITED FROM 01-01-2024 TO 01-01-2025
        payload = {
            "customer_id":cust_id,
            "day_start":day_start,
            "day_end": day_end
        }
        cust_num = save_incoming_data(key_id, payload)

        return {
            "key_id": key_id,
            "customer_id": cust_num,
            "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "status_code": 1,
            "status_message": "Transfer is done."
        }
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        return {
            "key_id": key_id,
            "customer_id": "",
            "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "status_code": 3,
            "status_message": error_summary
        }

def data_pushback():
    # print(f"data push_back is started")
    try:
        extract_custname = load_id()
        # print(f"data push_back is finished")
        return extract_custname
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        return error_summary

def main_sequence(request):
    try:
        print("DEBUG: fetch_data_bak STARTED")
        fetch_data_bak(request)
        print("DEBUG: fetch_data_bak COMPLETED")
        print("DEBUG: process_data() STARTED")
        process_data()
        print("DEBUG: process_data() COMPLETED")
        return {
            "stage": "Processing Data Stage",
            "status": "1 : Successfully processed!",
            "message": "Please check endpoint.",
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        print(f"DEBUG: process_data() FAILED - {e}")
        error_summary = f"{type(e).__name__}: {e}"
        return {
            "stage": "Processing Data Stage",
            "status": "3 : Failed",
            "message": error_summary,
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

class InitRequest(BaseModel):
    customer_id: str
    day_start: str
    day_end: str

@app.post("/receive-data")
async def receive_data(request: InitRequest, 
                       background_tasks: BackgroundTasks):
    # Generate a unique Job ID
    jobID = generate_tag_id()

    # Since we don't demonstrate API key checking inside .env, we don't need this
    # All system in closed loop and for demonstration only
    # if not x_api_key or x_api_key != TESTING_KEY:
    #     raise HTTPException(
    #         status_code=401,
    #         detail={
    #             "key_id": jobID,
    #             "customer_id": "",
    #             "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    #             "status_code": 3,
    #             "status_message": "Invalid or missing API key."
    #         }
    #     )

    onboarding_result = data_onboarding(jobID, request.customer_id, 
                                        request.day_start, request.day_end)
    background_tasks.add_task(data_pushback)
    background_tasks.add_task(main_sequence, request)

    return onboarding_result

@app.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    return jobs[job_id]  
