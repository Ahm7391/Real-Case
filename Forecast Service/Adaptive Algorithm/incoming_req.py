from fastapi import FastAPI, HTTPException, BackgroundTasks, Header, Request
import datetime, json, os
from dotenv import load_dotenv
from pydantic import BaseModel

app = FastAPI(title="Aggregate and Queue incoming dynamic data")
load_dotenv()
RECEIVE_COMPANY_API_KEY = os.getenv("AUTHENTICATION_API_KEY")

class DynamicReq(BaseModel):
    booking_id: str
    customer_id: int
    booking_date: str
    check_in: str
    check_out: str
    is_confirmed: bool
    country_id: int
    currency_id: int
    ota_id: int
    ota_name: str
    net_amount_stay: int
    room_id: str
    sub_room_id: str
    room_type_id: int
    room_type_name: str

#TODO: INI NANTI HARUS DITAMBAHIN TANGGAL LOH JADI BIAR BISA KECEK UDAH KELEWAT ATAU BELUM
def queueing_process(cust_id, check_in_date):
    if os.path.exists("request_queue.json"):
        with open("request_queue.json", "r") as f:
            queue_list = json.load(f)
        if str(cust_id) not in queue_list.keys():
            container_box = []
            container_box.append(check_in_date)
            queue_list[str(cust_id)] = container_box
        else:
            # temp_val = queue_list[str(cust_id)] + 1
            queue_list[str(cust_id)].append(check_in_date)
            queue_list[str(cust_id)].sort()
        with open("request_queue.json", "w") as f:
            json.dump(queue_list, f)
    else:
        queue_list = {}
        container_box = []
        container_box.append(check_in_date)
        queue_list[str(cust_id)] = container_box

        with open("request_queue.json", "w") as f:
            json.dump(queue_list, f)

@app.post("/request-incoming")
def request_incoming(request: DynamicReq, 
                       x_api_key):
    if not x_api_key or x_api_key != RECEIVE_COMPANY_API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key"
        )
    
    queueing_process(request.customer_id, request.check_in)
    return 0



