import datetime
import random
import string, json, subprocess, requests, sys
import os

from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
from pydantic import BaseModel
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from adaptive_preproc_json import read_incoming_data, fetch_data_bak, FetchRequest
from adaptive_algorithm import adaptive_algorithm

import time
import fcntl  # LINUX ONLY (Uncomment for Linux/production)
# import msvcrt   # WINDOWS ONLY (Comment out before pushing to Linux/production)
import uuid

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
LOCK_FILE = "analytics_pipeline.lock"

app = FastAPI(title="Ecommerce Adaptive Pricing")
load_dotenv()
jobs = {}

RECEIVE_COMPANY_API_KEY = os.getenv("PREDICTIVE_AUTH_API_KEY")
CUSTOMERS_LIST = os.getenv("TOTAL_ROOM_NUMBER_URL")
API_KEY = os.getenv("TOKEN_SERVER")

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
MAIN_FILE = Path(__file__).resolve().parents[1]
FOLDER_PATH_CP = os.path.join(MAIN_FILE, "Machine Learning Development/Checkpoint")

def error_logger(error_msg, customer_id=None):
    datetime_format_save = datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
    with open(f"runtime_error_logger_{datetime_format_save}.txt", 'a') as f:
        f.write(f"Date: {datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
        f.write("\nStatus: RUNTIME ERROR OCCURED..\n")
        if error_msg:
            f.write(f"Error due to : {error_msg}")
        if customer_id:
            f.write(f"Customer id is : {customer_id}")

# ==============================================================================
# LINUX LOCKING MECHANISM (Uncomment when deploying/pushing to Linux)
# ==============================================================================

def acquire_lock():
    fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError as e:
        fd.close()
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        return None

def release_lock(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        fd.close()
# ==============================================================================
# WINDOWS LOCKING MECHANISM (Active for Windows local testing)
# ==============================================================================
# def acquire_lock():
#     try:
#         fd = open(LOCK_FILE, "w")
#         msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
#         return fd
#     except (IOError, OSError) as e:
#         if 'fd' in locals() and not fd.closed:
#             fd.close()
#         error_summary = f"{type(e).__name__}: {e}"
#         error_logger(error_summary)
#         return None

# def release_lock(fd):
#     try:
#         if fd and not fd.closed:
#             fd.seek(0)
#             msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
#     except (IOError, OSError) as e:
#         error_summary = f"{type(e).__name__}: {e}"
#         error_logger(error_summary)
#     finally:
#         if fd and not fd.closed:
#             fd.close()

def generate_tag_id(random_length=4):
    timestamp = datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y%m%d%H%M")
    random_digits = "PRAA" + ''.join(random.choices(string.digits, k=random_length))
    return timestamp + random_digits

def update_job_status(job_id: str, status_code: int, message: str, customer_id: str = ""):
    jobs[job_id] = {
        "key_id": job_id,
        "customer_id": customer_id,
        "datetime_request": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "status_code": status_code,
        "status_message": message
    }

# THIS IS TEMPORARY SECTION TO CHECK CUSTOMER LIST FROM GET /CUSTOMERS ENDPOINT, THEN LOOP TO NEXT CUSTOMERS
# UNTIL CRON JOB EXHAUSTED THE LOOP. SAVE THE LAST CUSTOMER AS CHECKPOINT, SO WHEN THE CRON JOB COOLDOWN ENDED
# CRON WILL ACTIVATE AT LAST PROCESSED CUSTOMERS. THIS IS TEMPORARY BY THE WAY UNTIL UI FINISHED
def customers_data_updater():
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    print("Sending update requests....")
    try:
        response = requests.get(CUSTOMERS_LIST, headers=headers)
        response.raise_for_status()  # Raises HTTPError for bad status codes   
        incoming_data = response.json()
        incoming_data["last_update"] = datetime.now().strftime("%Y-%m-%d")
        with open("customers_main_data.json", "w") as f:
            json.dump(incoming_data, f, indent=4)
        print("Successfully saved the new database!")
            
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

def checkpoint_checker():
    if not os.path.exists("customers_main_data.json"):
        print("No customers main data found, we need to create the data.")
        customers_data_updater()
        customer_id = checkpoint_checker()

    else:
        print("Customer data found, checking its expired date.")
        with open("customers_main_data.json", "r") as f:
            content_check = json.load(f)
        
        delta_time_check = datetime.now() - datetime.strptime(content_check["last_update"], "%Y-%m-%d")  # remember to convert the content_check["last_update"] to timedate type
        if int(delta_time_check.days) >= 30:
            print("Last update was more than 30 days ago, we will update the database.")
            customers_data_updater()
            customer_id = checkpoint_checker()
        else:
            # get the latest checkpoint data
            print("Last update is okay, proceeding to check last checkpoint.")
            if os.path.exists("checkpoint_save.txt"):
                print("Last checkpoint record found.")
                with open("checkpoint_save.txt", "r") as f:
                    first_line = f.readline().strip()
                    customer_id = int(first_line)
                    print(f"customer id to be processed is : {customer_id}")
            else:
                # maybe checkpoint do the first time check
                print("No record found, start from the first customer_id on the database.")
                customer_id = content_check["data"][0]["id"]

            done_aggregating = False
            # save the next customer for processing
            for i in range(len(content_check["data"])):
                if content_check["data"][i]["id"] == customer_id:
                    if i == len(content_check["data"]) - 2:
                        seq = -1 # Reaching end of database cycle back to beginning
                    else:
                        seq = i # not yet reaching end, so normal cycling
                    print("Will save the checkpoint -> next customer_id")
                    with open("checkpoint_save.txt", "w") as f:
                        f.write(str(content_check["data"][seq+1]["id"]))
                    done_aggregating = True
                    print("Next customer_id will be processed")
                if done_aggregating:
                    break
    os.makedirs(FOLDER_PATH_CP, exist_ok=True)
    result_path = os.path.join(FOLDER_PATH_CP, f"checkpoint_details.txt")  
    with open(result_path, "w") as f:
        f.write(str(customer_id))
        print(f"success saving to Machine Learning Checkpoint")
    return customer_id                       

def data_onboarding(key_id, cust_id, job_sched=None):
    try:
        if job_sched == 1:
            payload = {
                "customer_id":cust_id,
            }
            # print(f"payload type is: {type(payload)}")
            # payload = json.dumps(payload, indent=4)
            # except Exception:
            #     raise HTTPException(status_code=400, detail="Invalid JSON format")
            # print(f"payload is: {payload}")

            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Payload must be a JSON object")
            intention = read_incoming_data(key_id, payload)

        return {
            "key_id": key_id,
            "customer_id": cust_id,
            "datetime_request": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "status_code": 2,
            "status_message": "Instructions Received."
        }
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id=cust_id)
        return {
            "key_id": key_id,
            "customer_id": "",
            "datetime_request": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "status_code": 3,
            "status_message": error_summary
        }
    
def main_sequence():
    try:
        print("DEBUG: inference step STARTED")
        fetch_data_bak()
        # adaptive_algorithm()
        subprocess.run([sys.executable, "adaptive_algorithm.py", "adaptive_algorithm"],
                       check=True)
        print("DEBUG: inference process COMPLETED")
        return {
            "stage": "Processing Data Stage",
            "status": "2 : Successfully processed!",
            "message": "Please check endpoint.",
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        print(f"DEBUG: process_data() FAILED - {e}")
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        return {
            "stage": "Processing Data Stage",
            "status": "3 : Failed",
            "message": error_summary,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

class InferenceReq(BaseModel):
    customer_id: str

# def enqueue_and_run_analytics(job_ident, payload: InferenceReq):
def enqueue_and_run_analytics(job_ident, payload):
    QUEUE_DIR = os.path.join(CURR_DIR, "Queue")
    os.makedirs(QUEUE_DIR, exist_ok=True)

    job_id = f"{time.time_ns()}_{uuid.uuid4().hex}.job"
    job_path = os.path.join(QUEUE_DIR, job_id)

    # job_payload = {
    #     "customer_id": payload.customer_id,
    #     "job_id": job_ident
    # }

    job_payload = {
        "customer_id": payload,
        "job_id": job_ident
    }

    with open(job_path, "w") as f:
        json.dump(job_payload, f)

    # try become worker
    lock_fd = acquire_lock()
    if lock_fd is None:
        return  # another worker is already running

    try:
        while True:
            queue_files = sorted(os.listdir(QUEUE_DIR))
            if not queue_files:
                break

            job_file = queue_files[0]
            job_path = os.path.join(QUEUE_DIR, job_file)

            with open(job_path, "r") as f:
                job_payload = json.load(f)

            os.remove(job_path)
            data_onboarding(job_payload["job_id"], job_payload["customer_id"], job_sched=1)
            main_sequence()
    finally:
        release_lock(lock_fd)

@app.post("/adaptive-active")
# async def adaptive_active(request: InferenceReq, 
#                        background_tasks : BackgroundTasks,
#                        x_api_key: str = Header(None)):
def adaptive_active():
    # Generate a unique Job ID
    jobID = generate_tag_id()
    # print("Incoming Headers:", dict(request.headers))
    # if not x_api_key or x_api_key != RECEIVE_COMPANY_API_KEY:
    #     raise HTTPException(
    #         status_code=401,
    #         detail={
    #             "key_id": jobID,
    #             "customer_id": "",
    #             "datetime_request": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    #             "status_code": 3,
    #             "status_message": "Invalid or missing API key. Please provide a valid X-API-KEY header."
    #         }
    #     )

    try:
        customer_tbp = checkpoint_checker()
        # Step 1: Handle onboarding (blocking)
        # onboarding_result = data_onboarding(jobID, request.customer_id, job_sched=0)
        onboarding_result = data_onboarding(jobID, customer_tbp, job_sched=0)
        # background_tasks.add_task(data_onboarding, jobID, request.customer_id, request.customer_name)
        # Step 2: Schedule `main_sequence` to run in the background
        # background_tasks.add_task(enqueue_and_run_analytics, onboarding_result["key_id"], request)
        enqueue_and_run_analytics(onboarding_result["key_id"], customer_tbp)
        # Step 3: Immediately return success response
        return onboarding_result
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id=customer_tbp)
        return onboarding_result
  
if __name__ == "__main__":
    adaptive_active()