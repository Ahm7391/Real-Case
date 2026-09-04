import datetime
import random
import string, json, subprocess, sys
import os

from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
from pydantic import BaseModel
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from preproc_json import read_incoming_data, fetch_data_bak, FetchRequest
from prediction_master import inference_pipeline

import time, fcntl
import uuid

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
LOCK_FILE = "analytics_pipeline.lock"
FOLDER_PATH_CP = os.path.join(CURR_DIR, "Checkpoint")

app = FastAPI(title="Ecommerce Machine Learning Section")
load_dotenv()
jobs = {}

RECEIVE_COMPANY_API_KEY = os.getenv("PREDICTIVE_AUTH_API_KEY")

def error_logger(error_msg, customer_id=None):
    datetime_format_save = datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
    with open(f"runtime_error_logger_{datetime_format_save}.txt", 'a') as f:
        f.write(f"Date: {datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
        f.write("\nStatus: RUNTIME ERROR OCCURED..\n")
        if error_msg:
            f.write(f"Error due to : {error_msg}")
        if customer_id:
            f.write(f"Customer id is : {customer_id}")

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

def generate_tag_id(random_length=4):
    timestamp = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y%m%d%H%M")
    random_digits = "MACL" + ''.join(random.choices(string.digits, k=random_length))
    return timestamp + random_digits

def update_job_status(job_id: str, status_code: int, message: str, customer_id: str = ""):
    jobs[job_id] = {
        "key_id": job_id,
        "customer_id": customer_id,
        "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "status_code": status_code,
        "status_message": message
    }

def receive_checkpoint():
    checkpoint_path = os.path.join(FOLDER_PATH_CP, "checkpoint_details.txt")
    if os.path.exists(checkpoint_path):
        print("Checkpoint details found!")
        with open(checkpoint_path, "r") as f:
            first_line = f.readline().strip()
            customer_id = int(first_line)
            print(f"customer id to be processed is : {customer_id}")
        return customer_id
    else:
        raise RuntimeError("FATAL ERROR: NO DATA AVAILABLE, PERHAPS NEED UPDATE FIRST BY ADAPTIVE PIPELINE.")

def data_onboarding(key_id, cust_id, predict_days, job_sched=None):
    try:
        # if predict_days >= 31:
        #     raise HTTPException(status_code=400, detail="Prediction days only limitied up to 31 days.")
        
        if job_sched == 1:
            payload = {
                "customer_id":cust_id,
                "predict_days":predict_days
            }
            # payload = json.dumps(payload, indent=4)
            # except Exception:
            #     raise HTTPException(status_code=400, detail="Invalid JSON format")

            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="Payload must be a JSON object")
            read_incoming_data(key_id, payload)

        return {
            "key_id": key_id,
            "customer_id": cust_id,
            "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "status_code": 2,
            "status_message": "Instructions Received."
        }
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id=cust_id)
        return {
            "key_id": key_id,
            "customer_id": "",
            "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            "status_code": 3,
            "status_message": error_summary
        }
    
def main_sequence():
    try:
        print("DEBUG: inference step STARTED")
        fetch_data_bak()
        # inference_pipeline()
        subprocess.run([sys.executable, "prediction_master.py", "inference_pipeline"],
                       check=True)
        print("DEBUG: inference process COMPLETED")
        return {
            "stage": "Processing Data Stage",
            "status": "2 : Successfully processed!",
            "message": "Please check endpoint.",
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        print(f"DEBUG: process_data() FAILED - {e}")
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary)
        return {
            "stage": "Processing Data Stage",
            "status": "3 : Failed",
            "message": error_summary,
            "timestamp": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        }

class InferenceReq(BaseModel):
    customer_id: str
    predict_days: int | None = None

# def enqueue_and_run_analytics(job_ident, payload: InferenceReq):
def enqueue_and_run_analytics(job_ident, payload):
    QUEUE_DIR = os.path.join(CURR_DIR, "Queue")
    os.makedirs(QUEUE_DIR, exist_ok=True)

    job_id = f"{time.time_ns()}_{uuid.uuid4().hex}.job"
    job_path = os.path.join(QUEUE_DIR, job_id)

    # job_payload = {
    #     "customer_id": payload.customer_id,
    #     "predict_days": payload.predict_days,
    #     "job_id": job_ident
    # }

    job_payload = {
        "customer_id": payload,
        "predict_days": 30,
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
            data_onboarding(job_payload["job_id"], job_payload["customer_id"], 
                            job_payload["predict_days"], job_sched=1)
            main_sequence()
    finally:
        release_lock(lock_fd)

# class MaintenanceReq(BaseModel):
#     # Konsepnya, untuk mengurangi jamming pada traffic server, pengambilan data untuk training
#     # tidak dapat dilakukan sekaligus, sehingga diciptakan 2 mode, mode pertama untuk menarik JSON 
#     # per properti saja berdasarkan rentang tanggal, mode kedua baru mengaktifkan script training sesungguhnya
#     # Mode 1 collect all data and stores JSON files
#     # Mode 2 start training
#     mode : int
#     customer_name : str | None = None
#     start_dt : str | None = None
#     end_dt : str | None = None


# @app.post("/training-step")
# def training_step(request: MaintenanceReq,
#                   background_tasks: BackgroundTasks):
#     try:
#         if request.mode == 1:
#             aggregator_data(request.customer_name, request.start_dt, request.end_dt)
#         elif request.mode == 2:
#             background_tasks.add_task(training_pipeline)
#         else:
#             print("Mode number is not between 1 and 2.")
#             raise HTTPException(status_code=500, detail="Mode number out of range.")
        
#         return {
#             "status": 2,
#             "message":"Instructions Received, VPS is processing now, you can disconnect."
#         }

#     except Exception as e:
#         error_summary = f"{type(e).__name__}: {e}"
#         print(f"[ERROR] due to: {error_summary}")

@app.post("/predict-step")
# async def predict_step(request: InferenceReq, 
#                        background_tasks : BackgroundTasks,
#                        x_api_key: str = Header(None)):
# async def predict_step():
def predict_step():
    # Generate a unique Job ID
    jobID = generate_tag_id()
    # print("Incoming Headers:", dict(request.headers))
    # if not x_api_key or x_api_key != RECEIVE_COMPANY_API_KEY:
    #     raise HTTPException(
    #         status_code=401,
    #         detail={
    #             "key_id": jobID,
    #             "customer_id": "",
    #             "datetime_request": datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    #             "status_code": 3,
    #             "status_message": "Invalid or missing API key. Please provide a valid X-API-KEY header."
    #         }
    #     )

    try:
        customer_tbp = receive_checkpoint()
        # Step 1: Handle onboarding (blocking)
        # onboarding_result = data_onboarding(jobID, request.customer_id, 
        #                                     request.predict_days, job_sched=0)
        onboarding_result = data_onboarding(jobID, customer_tbp, predict_days=28, job_sched=0)
        # background_tasks.add_task(data_onboarding, jobID, request.customer_id, request.customer_name)
        # Step 2: Schedule `main_sequence` to run in the background
        # background_tasks.add_task(main_sequence)
        # background_tasks.add_task(enqueue_and_run_analytics, onboarding_result["key_id"], request)
        enqueue_and_run_analytics(onboarding_result["key_id"], customer_tbp)
        # Step 3: Immediately return success response
        return onboarding_result
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id=customer_tbp)
        return onboarding_result

if __name__ == "__main__":
    predict_step()
