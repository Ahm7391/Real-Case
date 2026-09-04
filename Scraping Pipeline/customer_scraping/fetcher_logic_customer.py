import pickle, requests, time
import pandas as pd
import json, os, datetime
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("SCRAPING_API_KEY")
WEBHOOK_URL = os.getenv("CUSTOMER_INGEST_URL")
WEBHOOK_URL_2 = os.getenv("ADD_INFO_URL")
WEBHOOK_URL_LATER = os.getenv("POSTMAN_URL")

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
PARENT_DIR = os.path.dirname(CURR_DIR)
FOLDER_PATH_TIKET = os.path.join(PARENT_DIR, "customer_scraping_tiket")
DATABASE_TIKET_EB = os.path.join(FOLDER_PATH_TIKET, "scraping_customer_tiket_eb.pkl")
DATABASE_TIKET_LM = os.path.join(FOLDER_PATH_TIKET, "scraping_customer_tiket_lm.pkl")
BATCH_ENTRY = 50

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

benchmark_format2 = {
    'property_name' : str | None,
    'villa_or_hotel': int | None,
    'rating': int | None
}

main_dat = {
    "database_booking_dot_com": ["scraping_customer_lm.pkl", "scraping_customer_eb.pkl"],
    "database_tiket_dot_com": [DATABASE_TIKET_LM, DATABASE_TIKET_EB]
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

def load_allowed_property_names(filename="property_with_customer.json"):
    """Load the set of property names that have a competitor assigned.
    Returns an empty set (nothing allowed) if the file is missing or malformed,
    so a missing file fails safe instead of silently letting everything through."""
    if not os.path.exists(filename):
        print(f"[WARN] {filename} not found, no properties will be processed.")
        return set()
    try:
        with open(filename, "r", encoding="utf-8") as f:
            raw_list = json.load(f)
        allowed = {entry["properties_name"] for entry in raw_list if entry.get("properties_name")}
        print(f"Loaded {len(allowed)} allowed property names from {filename}")
        return allowed
    except Exception as e:
        print(f"[ERROR] Failed to load {filename}: {e}. No properties will be processed.")
        return set()

def json_wrapper(loaded_df, allowed_property_names=None):
    # if (allowed_property_names is None) and (FOCUS_COMPETITOR == True):
    #     allowed_property_names = load_allowed_property_names()
    
    loaded_df_copy = loaded_df.reset_index(drop=True)
    tempo_container = []
    tempo_container2 = []
    seen_names = set()
    for i in range(len(loaded_df_copy)):
        see_name = loaded_df_copy.loc[i, "property_name"]

        if see_name not in seen_names:
            seen_names.add(see_name)
            # if (see_name not in allowed_property_names) and (FOCUS_COMPETITOR == True):
            #     # Not tracked with a competitor assignment, skip entirely.
            #     print(f"[NOTE] property {see_name} is not located on allowed list. Skipping!")
            #     continue
            loaded_df_copy_lite = loaded_df_copy[(loaded_df_copy["property_name"] == see_name)]
            loaded_df_copy_lock = loaded_df_copy_lite.groupby("room_type")["price_details"].idxmin()
            res_df = loaded_df_copy_lite.loc[loaded_df_copy_lock].reset_index(drop=True)

            if len(res_df) > 0:
                for ii in range(len(res_df)):
                    batch_scrap = benchmark_format.copy()
                    batch_scrap2 = benchmark_format2.copy()
                    val_prop = res_df.loc[ii, "property_name"]
                    batch_scrap["property_name"] = int(val_prop) if not pd.isna(val_prop) else None
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

                    try:
                        if res_df.loc[ii, "villa_or_hotel"] != None:
                            batch_scrap2["villa_or_hotel"] = int(res_df.loc[ii, "villa_or_hotel"])
                        else:
                            batch_scrap2["villa_or_hotel"] = None
                    except Exception as e:
                        print(f"[ERROR] error due to {e}, Backup assigning to None.")
                        batch_scrap2["villa_or_hotel"] = None

                    try:
                        if res_df.loc[ii, "rating"] != None:
                            batch_scrap2["rating"] = int(res_df.loc[ii, "rating"])
                        else:
                            batch_scrap2["rating"] = None
                    except Exception as e:
                        print(f"[ERROR] error due to {e}, Backup assigning to None.")
                        batch_scrap2["rating"] = None

                    batch_scrap2["property_name"] = int(val_prop) if not pd.isna(val_prop) else None
                    # batch_scrap["category"] = loaded_df_copy.loc[ii, "category"]
                    tempo_container.append(batch_scrap)
                    tempo_container2.append(batch_scrap2)
            else:
                print("Data is empty, should be impossible, but for safety put all to NULL/NONE value.")
                # batch_scrap = benchmark_format.copy()
                # batch_scrap2 = benchmark_format2.copy()
                # batch_scrap["property_name"] = None
                # batch_scrap["room_type"] = None
                # batch_scrap["ota_source"] = None
                # batch_scrap["price"] = None
                # batch_scrap["perks"] = None
                # batch_scrap["scraped_at"] = None
                # batch_scrap["target_date"] = None
                # batch_scrap["category"] = None
                # batch_scrap2["villa_or_hotel"] = None
                # batch_scrap2["rating"] = None
                # tempo_container.append(batch_scrap)
                # tempo_container2.append(batch_scrap2)
                continue
            # name_memory = see_name
        else:
            continue
    return tempo_container, tempo_container2

# def json_wrapper_booking(loaded_df):
#     tempo_container = []
#     for i in range(len(loaded_df)):
#         batch_scrap = benchmark_format.copy()
#         batch_scrap["property_name"] = loaded_df.iloc[i, 0]
#         batch_scrap["room_type"] = loaded_df.iloc[i, 1]
#         batch_scrap["ota_source"] = loaded_df.iloc[i, 2]
#         batch_scrap["price"] = str(loaded_df.iloc[i, 3])
#         batch_scrap["perks"] = loaded_df.iloc[i, 4]
#         batch_scrap["scraped_at"] = loaded_df.iloc[i, 5]
#         try:
#             batch_scrap["target_date"] = loaded_df.iloc[i, 6].strftime("%Y-%m-%d")
#         except Exception as e:
#             print(f"Receive error {e} siwtching to secondary mode at iloc[i, 6]")
#             batch_scrap["target_date"] = loaded_df.iloc[i, 6]

#         batch_scrap["category"] = loaded_df.iloc[i, 7]
#         tempo_container.append(batch_scrap)
#     return tempo_container

# def json_wrapper_tiket(loaded_df):
#     tempo_container = []
#     for i in range(len(loaded_df)):
#         batch_scrap = benchmark_format.copy()
#         batch_scrap["property_name"] = loaded_df.iloc[i, 0]
#         batch_scrap["room_type"] = loaded_df.iloc[i, 1]
#         batch_scrap["ota_source"] = loaded_df.iloc[i, 2]
#         batch_scrap["price"] = str(loaded_df.iloc[i, 3])
#         batch_scrap["perks"] = str(loaded_df.iloc[i, 4])
#         batch_scrap["scraped_at"] = loaded_df.iloc[i, 5]
#         try:
#             batch_scrap["target_date"] = loaded_df.iloc[i, 7].strftime("%Y-%m-%d")
#         except Exception as e:
#             print(f"Receive error {e} siwtching to secondary mode at iloc[i, 7]")
#             batch_scrap["target_date"] = loaded_df.iloc[i, 7]

#         batch_scrap["category"] = loaded_df.iloc[i, 6]
#         tempo_container.append(batch_scrap)
#     return tempo_container

def chartjs_to_endpoint(data, use_company_api=True):
    try:
        if use_company_api:
            url = WEBHOOK_URL
            headers = {"Content-Type": "application/json",
                       "Accept": "application/json",
                       "Authorization": f"Bearer {API_KEY}"}
        else:
            url = WEBHOOK_URL_LATER
            headers = {
                "Content-Type": "application/json"
            }

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

def update_prop_data(data, use_company_api=True):
    try:
        if use_company_api:
            url = WEBHOOK_URL_2
            headers = {"Content-Type": "application/json",
                        "Accept": "application/json",
                        "Authorization": f"Bearer {API_KEY}"}
        else:
            url = WEBHOOK_URL_LATER
            headers = {
                "Content-Type": "application/json"
            }

        print("reach here!!!!")
        response = requests.post(url, headers=headers, json=data)
        # For debugging
        if response.status_code == 200:
            print("ChartJS successfully sent!")
        else:
            print(f"Failed to send data. Status: {response.status_code}, Response: {response.text}")
        return response.status_code
    except Exception as e:
        print(f"Error sending ChartJS: {e}")

def run():
    for _, v in main_dat.items():
        # if k == "database_booking_dot_com":
        #     for iii in v:
        #         print(f"Opening pickle file : {iii}")
        #         focus_df = load_the_df(iii)
        #         print(f"DF loaded with total data: {len(focus_df)}")
        #         container_hold = json_wrapper(focus_df)
        #         print("Successfully converted to list of dictionaries.")

        #         ctr = 0
        #         if len(container_hold) > 0:
        #             for ii in container_hold:
        #                 try_send = chartjs_to_endpoint(ii)
        #                 print(f"result sending data {ctr+1} is {try_send}")
        #                 ctr += 1
        #                 time.sleep(0.5)
        #         else:
        #             print(f"Database {iii} still empty or not found!")
        #             continue
        for iii in v:
            print(f"Opening pickle file : {iii}")
            focus_df = load_the_df(iii)
            print(f"DF loaded with total data: {len(focus_df)}")
            container_hold, container_hold2 = json_wrapper(focus_df)
            print("Successfully converted to list of dictionaries.")

            ctr = 0
            if len(container_hold) > 0:
                lower_bound = 0
                upper_bound = 0
                print(f"Recorded total entry is {len(container_hold)}")
                while ctr < len(container_hold):
                    holder1, holder2 = [], []
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
                        holder2.append(container_hold2[i])
                    lower_bound = upper_bound
                    print("Sending 1st Container")
                    chartjs_to_endpoint(holder1)
                    print("Sending 2nd Container")
                    update_prop_data(holder2)
                    ctr += BATCH_ENTRY
                    time.sleep(3)

                # for ii in range(len(container_hold)):
                #     try_send = chartjs_to_endpoint(container_hold[ii])
                #     print(f"result sending data {ctr+1}/{len(container_hold[ii])} is {try_send}")
                #     try_send2 = update_prop_data(container_hold2[ii])
                #     print(f"sending additional data {ctr+1}/{len(container_hold2[ii])} is {try_send2}")
                #     ctr += 1
                #     time.sleep(0.1)
            else:
                print(f"Database {iii} still empty or not found!")
                continue

if __name__ == "__main__":
    run()