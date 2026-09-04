import pandas as pd
import pickle, time
import json, os, datetime

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
PARENT_DIR = os.path.dirname(CURR_DIR)
FOLDER_PATH_TIKET = os.path.join(PARENT_DIR, "customer_scraping_tiket")
DATABASE_TIKET_EB = os.path.join(FOLDER_PATH_TIKET, "scraping_customer_tiket_eb.pkl")
DATABASE_TIKET_LM = os.path.join(FOLDER_PATH_TIKET, "scraping_customer_tiket_lm.pkl")

main_dat = {
    "database_booking_dot_com": ["scraping_customer_lm.pkl", "scraping_customer_eb.pkl"],
    "database_tiket_dot_com": [DATABASE_TIKET_LM, DATABASE_TIKET_EB]
}

# OBJECTIVE TO PRUNE DATABASE BASED ON TARGET DATE OR SCRAPED DATE BEFORE
# TODAY -3 DAYS BEHIND
# THERE'S A TWEAKABLE VARIABLE CALLED REF_DATE, IN WHICH YOU CAN CHANGE TO "TARGET_DATE"
# SO REMOVAL WILL COMPARED BASED ON TARGET_DATE COLUMN, AND "DATE_SCRAPPED" BASED ON DATE_SCRAPPED COLUMN
def prune_database(file_target, ref_date="date_scrapped"):
    print("Start pruning database")
    df_target = pd.read_pickle(file_target)
    df_target["target_date"] = pd.to_datetime(df_target["target_date"])
    df_target["date_scrapped"] = pd.to_datetime(df_target["date_scrapped"])
    cutoff_date = pd.Timestamp.today().normalize() - pd.Timedelta(days=3)
    print(f"Cutoff date is : {cutoff_date}")
    print(f"Before cutoff your data has {len(df_target)} entries.")
    df_target = df_target[df_target[ref_date] >= cutoff_date]
    print(f"After cutoff your data has {len(df_target)} entries.")
    return df_target

def run():
    for _, v in main_dat.items():
        for iii in v:
            print(f"Opening pickle file : {iii}")
            result_df = prune_database(iii)
            result_df.to_pickle(iii)
            print(f"Succesfully pruning data {iii}")

if __name__ == "__main__":
    run()