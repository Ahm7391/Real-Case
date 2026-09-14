# Backup/api_connect.py
import json
import random, string, os
from datetime import datetime
from fastapi import HTTPException

BUFFER_FILE = "buffer.json"

def load_id():
    if not os.path.exists("buffer.json"):
        return {}
    else:
        with open("buffer.json", "r") as f:
            data = json.load(f)
            customer_id = data["data"]["customer_id"]
        return customer_id

def save_incoming_data(work_id, payload: dict):
    # Validate required keys
    if "customer_id" not in payload or "day_start" not in payload or "day_end" not in payload:
        raise HTTPException(status_code=400, detail="Invalid payload format")
    
    # if "data_search_type" not in payload:
    #     raise HTTPException(status_code=400, detail="Invalid payload format")

    # # Validate data_request is a list
    # if not isinstance(payload["booking_data"], list):
    #     raise HTTPException(status_code=400, detail="'booking_data' must be a list")

    # Save to buffer.json
    data_to_save = {
        "job_identification":work_id,
        "received_at": datetime.utcnow().isoformat(),
        "data": payload
    }

    with open(BUFFER_FILE, "w") as f:
        json.dump(data_to_save, f, indent=4)

    return load_id()
