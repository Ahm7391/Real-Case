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
# import fcntl  # LINUX ONLY (Uncomment for Linux/production)
import msvcrt   # WINDOWS ONLY (Comment out before pushing to Linux/production)
import uuid

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
LOCK_FILE = "analytics_pipeline.lock"

app = FastAPI(title="Adaptive Pricing Demonstration")
load_dotenv()
jobs = {}

API_KEY = os.getenv("TOKEN_SERVER")
PREDICTION_PROGRESS_URL = os.getenv("PREDICTION_PROGRESS_URL", "http://127.0.0.1:8000/api/prediction-progress")

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
MAIN_FILE = Path(__file__).resolve().parents[1]
FOLDER_PATH_CP = os.path.join(MAIN_FILE, "Machine Learning Development/Checkpoint")

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

# ==============================================================================
# LINUX LOCKING MECHANISM (Uncomment when deploying/pushing to Linux)
# ==============================================================================

# def acquire_lock():
#     fd = open(LOCK_FILE, "w")
#     try:
#         fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
#         return fd
#     except BlockingIOError as e:
#         fd.close()
#         error_summary = f"{type(e).__name__}: {e}"
#         error_logger(error_summary)
#         return None

# def release_lock(fd):
#     try:
#         fcntl.flock(fd, fcntl.LOCK_UN)
#     finally:
#         fd.close()
# ==============================================================================
# WINDOWS LOCKING MECHANISM (Active for Windows local testing)
# ==============================================================================
def acquire_lock():
    try:
        fd = open(LOCK_FILE, "w")
        msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
        return fd
    except (IOError, OSError) as e:
        if 'fd' in locals() and not fd.closed:
            fd.close()
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        return None

def release_lock(fd):
    try:
        if fd and not fd.closed:
            fd.seek(0)
            msvcrt.locking(fd.fileno(), msvcrt.LK_UNLCK, 1)
    except (IOError, OSError) as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
    finally:
        if fd and not fd.closed:
            fd.close()

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

def data_onboarding(key_id, cust_id, job_sched=None):
    try:
        if job_sched == 1:
            payload = {
                "customer_id":cust_id,
            }

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

def enqueue_and_run_analytics(job_ident, payload):
    QUEUE_DIR = os.path.join(CURR_DIR, "Queue")
    os.makedirs(QUEUE_DIR, exist_ok=True)

    job_id = f"{time.time_ns()}_{uuid.uuid4().hex}.job"
    job_path = os.path.join(QUEUE_DIR, job_id)

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
            
            # Milestone 1: Data onboarding completed, starting main sequence (2% progress)
            report_progress(
                job_id=job_payload["job_id"],
                customer_id=job_payload["customer_id"],
                progress_percent=2,
                stage_name="adaptive_onboarding_completed",
                message="Data onboarding completed. Initializing adaptive forecasting sequence...",
                status="running"
            )

            main_sequence()
    finally:
        release_lock(lock_fd)

def adaptive_active():
    jobID = generate_tag_id()

    try:
        # Step 1: Handle onboarding (blocking)
        # onboarding_result = data_onboarding(jobID, request.customer_id, job_sched=0)
        onboarding_result = data_onboarding(jobID, 1, job_sched=0)
        # background_tasks.add_task(data_onboarding, jobID, request.customer_id, request.customer_name)
        # Step 2: Schedule `main_sequence` to run in the background
        # background_tasks.add_task(enqueue_and_run_analytics, onboarding_result["key_id"], request)
        enqueue_and_run_analytics(onboarding_result["key_id"], 1)
        # Step 3: Immediately return success response
        return onboarding_result
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id=1)
        return onboarding_result
  
if __name__ == "__main__":
    adaptive_active()