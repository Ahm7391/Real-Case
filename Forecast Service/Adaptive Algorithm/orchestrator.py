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

LOOPS = 10
SLEEP_BETWEEN_CYCLES = 120  # seconds

PIPELINES = [
    # "/home/ubuntu/Ecommerce-Project/Ecommerce-Project/Adaptive Algorithm/adaptive_pipeline_infer.py",
    # "/home/ubuntu/Ecommerce-Project/Ecommerce-Project/Machine Learning Development/mcl_pipeline_infer.py",
    # "/home/antoniohazman8855/Ecommerce-Project/Adaptive Algorithm/adaptive_pipeline_infer.py",
    # "/home/antoniohazman8855/Ecommerce-Project/Machine Learning Development/mcl_pipeline_infer.py",
    "/home/gecko/ecommerce-project/Ready-Production/Adaptive Algorithm/adaptive_pipeline_infer.py",
    "/home/gecko/ecommerce-project/Ready-Production/Machine Learning Development/mcl_pipeline_infer.py",
]

def run_pipeline(script):
    script_dir = os.path.dirname(os.path.abspath(script))
    logging.info(f"Running {script}...")
    subprocess.run([sys.executable, script], check=True, cwd=script_dir)
    logging.info(f"Finished {script}")

def length_checker():
    if not os.path.exists(os.path.join(BASE_DIR, "customers_main_data.json")):
        print("No customers main data found, we need to create the data first.")
        print("Run the adaptive_pipeline_infer.py to update database.")
        return 0
    else:
        print("Checking total customer")
        with open(os.path.join(BASE_DIR,"customers_main_data.json"), "r") as f:
            content_check = json.load(f)
        length_of_data = len(content_check['data'])
        return length_of_data

def overtaking_job(): 
    print("Checking external priority job...")
    if os.path.exists(os.path.join(BASE_DIR,"request_queue.json")):
        print("Found Request Queue..")
        with open(os.path.join(BASE_DIR,"request_queue.json"), "r") as f:
            see_data = json.load(f)

        # before processing data, let's delete expired dates data
        for v in see_data.values():
            to_remove = []
            for i in v:
                if datetime.strptime(i, "%Y-%m-%d") <= datetime.now():
                    to_remove.append(i)
            for ii in range(len(to_remove)):
                if to_remove[ii] in v:
                    v.remove(to_remove[ii])

        urgent = 3 # this is to set threshold limit that if passed must be prioritize
        list_of_urgent = []
        for k, v in see_data.items():
            if len(v) >= urgent:
                print(f"Identified urgent job for customer ID: {k}")
                list_of_urgent.append(k)
        return list_of_urgent
    else:
        print("No request_queue recorded.")
        return []


def main():
    cycle = 0
    main_counter = 0
    total_seq = length_checker()
    while True:  
        cycle += 1
        logging.info(f"=== Cycle {cycle} START ===")
        logging.info(f"Curent main_counter is: {main_counter}")

        for pipeline in PIPELINES:
            run_pipeline(pipeline)  # serial: waits for each to finish
        main_counter += 1
        if main_counter > total_seq: break

        logging.info(f"=== Cycle {cycle} DONE — sleeping {SLEEP_BETWEEN_CYCLES}s ===")
        time.sleep(SLEEP_BETWEEN_CYCLES)
        if main_counter > total_seq: break

if __name__ == "__main__":
    main()
