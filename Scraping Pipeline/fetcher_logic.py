import pickle, requests, time
import pandas as pd
import json, os, datetime

SCRAPING_RESULT_FEEDBACK = "http://localhost:8000/api/scraping-competitor"
CUSTOMER_SCRAPING_RESULT = "http://localhost:8000/api/scraping-customer"

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
FOLDER_PATH_TIKET = os.path.join(CURR_DIR,"scrap_tiket_com")
BATCH_ENTRY = 100

FOCUS_COMPETITOR = True

benchmark_format = {
    'property_name' : str | None,
    'room_type': str,
    'ota_source': str,
    'price': int | None, 
    'perks': str,
    'scraped_at': datetime.datetime,
    'target_date': datetime.datetime | None,
    'category': int | None
}

main_dat = {
    "competitor": ["scraping_database_lm_competitor.pkl", "scraping_database_eb_competitor.pkl"],
    "customer": ["scraping_database_lm_customer.pkl", "scraping_database_eb_customer.pkl"]
}

def to_pg_date(value):
    """Coerce any pandas/numpy/python date into 'YYYY-MM-DD' for a Postgres DATE, or None."""
    ts = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(ts) else ts.strftime("%Y-%m-%d")

def to_pg_timestamp(value):
    """Coerce any pandas/numpy/python datetime into ISO 8601 for a Postgres TIMESTAMP, or None."""
    ts = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(ts) else ts.isoformat()

def load_the_df(filename):
    if os.path.exists(filename):
        loaded_df = pd.read_pickle(filename)
    else:
        loaded_df = pd.DataFrame()
    return loaded_df

def json_wrapper(loaded_df):   
    loaded_df_copy = loaded_df.reset_index(drop=True)
    tempo_container = []
    tempo_container2 = []
    seen_names = set()
    for i in range(len(loaded_df_copy)):
        see_name = loaded_df_copy.loc[i, "property_name"]

        if see_name not in seen_names:
            seen_names.add(see_name)
            loaded_df_copy_lite = loaded_df_copy[(loaded_df_copy["property_name"] == see_name)]
            loaded_df_copy_lock = loaded_df_copy_lite.groupby("room_type")["price_details"].idxmin()
            res_df = loaded_df_copy_lite.loc[loaded_df_copy_lock].reset_index(drop=True)

            if len(res_df) > 0:
                for ii in range(len(res_df)):
                    batch_scrap = benchmark_format.copy()
                    batch_scrap["property_name"] = res_df.loc[ii, "property_name"]
                    batch_scrap["room_type"] = res_df.loc[ii, "room_type"]
                    batch_scrap["ota_source"] = res_df.loc[ii, "ota_source"]
                    batch_scrap["price"] = int(res_df.loc[ii, "price_details"]) 
                    batch_scrap["perks"] = res_df.loc[ii, "notes_details"]
                    batch_scrap["scraped_at"] = to_pg_timestamp(res_df.loc[ii, "date_scrapped"])
                    batch_scrap["target_date"] = to_pg_date(res_df.loc[ii, "target_date"])

                    if res_df.loc[ii, "category"] == "last-minute":
                        batch_scrap["category"] = 1
                    elif res_df.loc[ii, "category"] == "early-book":
                        batch_scrap["category"] = 2
                    else:
                        batch_scrap["category"] = None
                    tempo_container.append(batch_scrap)
            else:
                print("Data is empty, should be impossible, but for safety put all to NULL/NONE value.")
                continue
        else:
            continue
    return tempo_container

def data_to_endpoint(data, mode):
    try:
        if mode == "competitor":
            url = SCRAPING_RESULT_FEEDBACK
        elif mode == "customer":
            url = CUSTOMER_SCRAPING_RESULT
        else:
            raise RuntimeError("Data to endpoint mode is not recognized.")
        headers = {"Content-Type": "application/json"}

        print("reach here!!!!")
        response = requests.post(url, headers=headers, json=data)
        # For debugging
        if response.status_code == 200:
            print("Data successfully sent!")
        else:
            print(f"Failed to send data. Status: {response.status_code}, Response: {response.text}")
        return response.status_code
    except Exception as e:
        print(f"Error sending Data: {e}")

def run_fetching():
    for k, v in main_dat.items():
        for iii in v:
            print(f"Opening pickle file : {iii}")
            focus_df = load_the_df(iii)
            print(f"DF loaded with total data: {len(focus_df)}")
            container_hold = json_wrapper(focus_df)
            print("Successfully converted to list of dictionaries.")

            ctr = 0
            if len(container_hold) > 0:
                lower_bound = 0
                upper_bound = 0
                print(f"Recorded total entry is {len(container_hold)}")
                while ctr < len(container_hold):
                    holder1 = []
                    remaining = len(container_hold) - ctr
                    if remaining > BATCH_ENTRY:
                        print(f"Remaining data is {remaining}")
                        upper_bound += BATCH_ENTRY
                    else:
                        print(f"processing the rest from {lower_bound} to {len(container_hold)}")
                        upper_bound = len(container_hold)
                    print(f"Processing data from entry {lower_bound} to {upper_bound-1}")
                    for i in range(lower_bound, upper_bound):
                        holder1.append(container_hold[i])
                    lower_bound = upper_bound
                    print("Sending 1st Container")
                    data_to_endpoint(holder1, mode=k)
                    ctr += BATCH_ENTRY
                    time.sleep(3)
            else:
                print(f"Database {iii} still empty or not found!")
                continue

if __name__ == "__main__":
    run_fetching()