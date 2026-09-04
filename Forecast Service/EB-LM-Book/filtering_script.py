import subprocess
import sys, os, json
import time
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRIORITY_THRESHOLD = 0.25 # 25 PERCENT OF TOTAL ROOM SO PREDICTION CAN PRIORITIZE

PIPELINE1 = [
    # "/home/ubuntu/Ecommerce-Project/Ecommerce-Project/EB-LM-Book/Early-Bird/adaptive_pipeline_infer.py",
    # "/home/ubuntu/Ecommerce-Project/Ecommerce-Project/EB-LM-Book/Last-Minute/mcl_pipeline_infer.py",
    # "/home/antoniohazman8855/Ecommerce-Project/EB-LM-Book/Early-Bird/adaptive_pipeline_infer.py",
    # "/home/antoniohazman8855/Ecommerce-Project/EB-LM-Book/Last-Minute/mcl_pipeline_infer.py"
    # "/root/Ecommerce-Project/Ready-Production/EB-LM-Book/Early-Bird/adaptive_pipeline_infer.py",
    # "/root/Ecommerce-Project/Ready-Production/EB-LM-Book/Last-Minute/mcl_pipeline_infer.py",
    "/home/gecko/ecommerce-project/Ready-Production/EB-LM-Book/Early-Bird/adaptive_pipeline_infer.py",
    "/home/gecko/ecommerce-project/Ready-Production/EB-LM-Book/Last-Minute/mcl_pipeline_infer.py",
]

PIPELINE2 = [
    # "/home/ubuntu/Ecommerce-Project/Ecommerce-Project/Machine Learning Development/mcl_pipeline_infer.py",
    "/home/gecko/ecommerce-project/Ready-Production/EB-LM-Book/Early-Bird/adaptive_pipeline_infer.py"
]

def run_pipeline(script):
    script_dir = os.path.dirname(os.path.abspath(script))
    logging.info(f"Running {script}...")
    subprocess.run([sys.executable, script], check=True, cwd=script_dir)
    logging.info(f"Finished {script}")

def sub_categories_threshold(target_dict, see_data_dict):
    # check total room number of that property and decide if it's need to be updated urgently
    # this is to set threshold limit that if passed must be prioritize
    threshold_list = {}
    with open("customers_main_data.json", "r") as f:
        highlight_data = json.load(f)
    
    # Check if the queued items also contained in master list and extract number of rooms data
    for k, v in see_data_dict.items():
        for vii in range(len(highlight_data["data"])):
            if k == str(highlight_data["data"][vii]["id"]):
                threshold_list[k] = highlight_data["data"][vii]["number_of_rooms"]

    # For all listed item, filter if it's necessary to be processed -> if pass threshold values
    process_list = []
    for key, val in threshold_list.items():
        if key in see_data_dict.keys() and len(target_dict[key]) / val >= PRIORITY_THRESHOLD:
            print(f"Identified urgent job for customer ID: {key}")
            process_list.append(key)
        else:
            continue

    print(f"Process list is {process_list}")
    if len(process_list) > 0:
        return process_list
    else:
        return []

def overtaking_job(): 
    if os.path.exists(os.path.join(BASE_DIR,"request_queue.json")):
        try:
            with open(os.path.join(BASE_DIR,"request_queue.json"), "r") as f:
                see_data = json.load(f)
        except json.JSONDecodeError:
            return [], [], {}, {}

        # before processing data, let's delete expired dates data
        print("Checking any expired dates in request_queue.json.")
        for v in see_data.values():
            to_remove = []
            for i in v:
                if datetime.strptime(i, "%Y-%m-%d") <= datetime.now():
                    to_remove.append(i)
            for ii in range(len(to_remove)):
                if to_remove[ii] in v:
                    v.remove(to_remove[ii])

        # Now let's classify which scope it has to predict early_bird (urgent_eb) or last_minute(update_lm) 
        # Then we append to each category for later to be count if it pass the threshold or not
        print("Starting classification job.")
        urgent_eb, urgent_lm = {}, {}
        for k, v in see_data.items():
            # check threshold first 
            lm_arr = []
            eb_arr = []
            for ix in v:
                today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                delta_days = (datetime.strptime(ix, "%Y-%m-%d") - today).days
                if delta_days <= 7:
                    lm_arr.append(ix)
                else:
                    eb_arr.append(ix)
            urgent_lm[k] = lm_arr
            urgent_eb[k] = eb_arr

        urgent_lm_list, urgent_eb_list = [], []
        if len(urgent_lm.keys()) > 0:
            print(f"urgent_lm has {len(urgent_lm.keys())} data")
            urgent_lm_list = sub_categories_threshold(urgent_lm, see_data)
        if len(urgent_eb.keys()) > 0:
            print(f"urgent_eb has {len(urgent_eb.keys())} data")
            urgent_eb_list = sub_categories_threshold(urgent_eb, see_data)
        return urgent_lm_list, urgent_eb_list, urgent_lm, urgent_eb
    else:
        # print("[DEBUG] No request_queue recorded.")
        return [], [], {}, {}

def exec_overtaking(priority_job, crosscheck_dict, pipeline_sel):
    if os.path.exists(os.path.join(BASE_DIR,"checkpoint_save.txt")):
        # original_cp = 0
        # print("Checkpoint record found, it will be overtaken.")
        # # Save the looping sequence checkpoint first
        # with open(os.path.join(BASE_DIR,"checkpoint_save.txt"), "r") as f:
        #     first_line = f.readline().strip()
        #     customer_id = int(first_line)
        #     original_cp = customer_id
        
        # Begin the priority job overtaking
        print("================ Priority Job will begin =================")
        for i in range(len(priority_job)):
            print(f"[PRIORITY] Processing customer {priority_job[i]}")
            with open(os.path.join(BASE_DIR,"checkpoint_save.txt"), "w") as f:
                f.write(str(priority_job[i]))
            for pipeline in pipeline_sel:
                run_pipeline(pipeline) 

        # Return the original checkpoint value to checkpoint_save.txt
        # with open(os.path.join(BASE_DIR,"checkpoint_save.txt"), "w") as f:
        #     f.write(str(original_cp))

        # Delete that particular date for that customer ID from request_queue.json because already processed
        with open(os.path.join(BASE_DIR,"request_queue.json"), "r") as f:
            see_data = json.load(f)
        
        will_remove_keys = []
        for k, v in see_data.items():
            will_remove = []
            if k in priority_job:
                for xii in range(len(see_data[k])):
                    if see_data[k][xii] in crosscheck_dict[k]:
                        will_remove.append(see_data[k][xii])

            for iii in range(len(will_remove)):
                if will_remove[iii] in see_data[k]:
                    see_data[k].remove(will_remove[iii])

            if len(see_data[k]) == 0:
                will_remove_keys.append(k)

        if len(will_remove_keys) > 0:
            for xiv in range(len(will_remove_keys)):
                del see_data[will_remove_keys[xiv]]
        
        with open(os.path.join(BASE_DIR,"request_queue.json"), "w") as f:
            json.dump(see_data, f)
    else:
        # maybe checkpoint do the first time check
        print("[ERROR] No checkpoint_save.txt ever found.")

def main():
    cycle = 0
    main_counter = 0

    # So loop untill all queued process emptied
    while True:
        priority_job_lm, priority_job_eb, lm_dict, eb_dict = overtaking_job()
        # Prioritize last_minute request first
        if len(priority_job_lm) > 0:
            print("starting last minute urgent job.")
            exec_overtaking(priority_job_lm, lm_dict, PIPELINE1)
        # Then early_bird request later
        if len(priority_job_eb) > 0:
            print("starting early bird urgent job.")
            exec_overtaking(priority_job_eb, eb_dict, PIPELINE2)
        # This need evaltuations in the future to see if it's suitable to use multithreading technique
        time.sleep(3)

if __name__ == "__main__":
    main()
