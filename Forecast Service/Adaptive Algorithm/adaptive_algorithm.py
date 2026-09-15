import os
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["TF_NUM_INTRAOP_THREADS"] = "1"
os.environ["TF_NUM_INTEROP_THREADS"] = "1"

import tensorflow as tf
tf.config.run_functions_eagerly(False)
tf.config.optimizer.set_jit(False)     # disable XLA

# ====================================================================
import pandas as pd
import numpy as np
import statsmodels.api as sm
from datetime import timedelta
from pathlib import Path
from datetime import datetime
from scipy import stats
from scipy.interpolate import interp1d

import keras, json, requests, pickle, traceback, math, gc, sys, logging
from tensorflow.keras import layers, backend as K
from tensorflow.keras.callbacks import EarlyStopping

# from fastapi import FastAPI
from dotenv import load_dotenv
from sklearn.preprocessing import MinMaxScaler
from scipy.stats import wasserstein_distance
from sklearn.mixture import GaussianMixture

from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo

import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

load_dotenv()
TOKEN_KEY = os.getenv('TOKEN_SERVER')
ROOM_NUMBER_GET = os.getenv("TOTAL_ROOM_NUMBER_URL")
PREDICTIVE_DATA_HOOK_URL = "http://localhost:8000/api/prediction-result"
API_TOKEN_CONSTANT = os.getenv("API_TOKEN_FOR_CONSTANTS")
API_ENDPOINT_CONSTANT = os.getenv("API_URL_FOR_CONSTANTS")
CONSTANT_SAVER = os.getenv("CONSTANT_SAVER_URL")
WEBHOOK_URL = "https://2f68b6cd-a59f-4429-af46-00f19a73248e.mock.pstmn.io/webhook"
CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
MAIN_FILE = Path(__file__).resolve().parents[1]
# API_URLS = "/workspaces/Ecommerce-Project/Machine Learning Development"
FOLDER_PATH_COMPRATE = os.path.join(CURR_DIR, "Comprate")
FOLDER_PATH_PREDICTIONS = os.path.join(CURR_DIR,"Predictions")
FOLDER_PATH_RECORDS = os.path.join(CURR_DIR,"Records")
FOLDER_PATH_SUGGESTION = os.path.join(CURR_DIR,"Suggestion")
FOLDER_PATH_RESULTS = os.path.join(MAIN_FILE, "Machine Learning Development/Long_Prediction")
FOLDER_PATH_DATABASE = os.path.join(MAIN_FILE, "EB-LM-Book/Routine-EB")
FOLDER_PATH_WEIGHTS = os.path.join(CURR_DIR,"Weights")
N_FEATURES = 1

TASKS = {}

def task(fn):
    TASKS[fn.__name__] = fn
    return fn

class ZeroDataError(Exception):
    pass

###################################################################
######--------------MODEL ARCHITECTURE-----------------------######
###################################################################
@task
def make_model(encoder_length, decoder_length):
    ENC_LEN_LT = encoder_length
    DEC_LEN_LT = decoder_length
    N_FEATURES = 1

    ENC_UNITS = [128, 64]
    DEC_UNITS = [96, 64]
    DROPOUT = 0.1

    # =========================
    # Encoder
    # =========================
    enc_inputs_lt = keras.layers.Input(
        shape=(ENC_LEN_LT, N_FEATURES),
        name="encoder_input"
    )

    x_lt = enc_inputs_lt
    encoder_states_lt = []

    for i, units in enumerate(ENC_UNITS):
        x_lt, state = keras.layers.GRU(
            units,
            return_sequences=True,
            return_state=True,
            dropout=DROPOUT,
            name=f"encoder_gru_{i}"
        )(x_lt)
        encoder_states_lt.append(state)

    encoder_final_state_lt = encoder_states_lt[-1]  # (batch, 64)

    # =========================
    # Decoder input (teacher forcing)
    # =========================
    dec_inputs_lt = keras.layers.Input(
        shape=(DEC_LEN_LT, N_FEATURES),
        name="decoder_input"
    )

    # =========================
    # State projection (CRITICAL FIX)
    # =========================
    decoder_init_state_0 = keras.layers.Dense(
        DEC_UNITS[0],
        activation="tanh",
        name="decoder_init_proj_0"
    )(encoder_final_state_lt)

    decoder_init_state_1 = keras.layers.Dense(
        DEC_UNITS[1],
        activation="tanh",
        name="decoder_init_proj_1"
    )(decoder_init_state_0)

    # =========================
    # Decoder (simple GRU)
    # =========================
    y_lt = dec_inputs_lt

    y_lt = keras.layers.GRU(
        DEC_UNITS[0],
        return_sequences=True,
        dropout=DROPOUT,
        name="decoder_gru_0"
    )(y_lt, initial_state=decoder_init_state_0)

    y_lt = keras.layers.GRU(
        DEC_UNITS[1],
        return_sequences=True,
        dropout=DROPOUT,
        name="decoder_gru_1"
    )(y_lt, initial_state=decoder_init_state_1)

    # =========================
    # Output layers
    # =========================
    y_lt = keras.layers.TimeDistributed(
        keras.layers.Dense(64, activation="relu"),
        name="td_dense"
    )(y_lt)

    y_lt = keras.layers.TimeDistributed(
        keras.layers.Dense(1),
        name="td_out"
    )(y_lt)

    decoder_outputs_lt = keras.layers.Reshape(
        (DEC_LEN_LT,),
        name="decoder_outputs"
    )(y_lt)

    # =========================
    # Model
    # =========================
    model_longterm = keras.models.Model(
        inputs=[enc_inputs_lt, dec_inputs_lt],
        outputs=decoder_outputs_lt
    )

    model_longterm.compile(
        optimizer=tf.keras.optimizers.Adam(1e-3),
        loss=tf.keras.losses.Huber(),
        metrics=[tf.keras.metrics.MeanAbsoluteError()]
    )

    model_longterm.summary()
    return model_longterm
# ============================================= END SECTION MODEL ===============================================

###############################################################################################
############----------------EXTRACTION AND LOADING FUNCTIONS----------------------------#######
###############################################################################################
@task
def chartjs_to_endpoint(data, customer_id, error_msg=None, use_company_api=True):
    # with open("check.json", "w") as f:
    #     json.dump(data, f, indent=4)
    try:
        if use_company_api:
            url = PREDICTIVE_DATA_HOOK_URL
            headers = {"Content-Type": "application/json"}
        else:
            url = WEBHOOK_URL
            headers = {
                "Content-Type": "application/json"
            }

        response = requests.post(url, headers=headers, json=data)
        date_format_save = datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
        with open(f"internal_logger_{date_format_save}.txt", 'a') as f:
            if len(data) > 0:
                f.write("Adaptive Pipeline ")
                f.write(f"Date: {datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
                f.write(f"Property ID: {customer_id}")
                f.write("\nStatus: SENT. DATA NOT BLANK.\n")
                print("ChartJS successfully sent!")
            elif len(data) == 0:
                f.write("Adaptive Pipeline ")
                f.write(f"Date: {datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
                f.write(f"Property ID: {customer_id}")
                f.write("\nStatus: SENT. DATA BLANK OR ERROR OCCURED.\n")
                if error_msg:
                    f.write(f"Error due to : {error_msg}")
                print("ChartJS successfully sent with NOTE!")

        # For debugging
        # if response.status_code == 200:
        #     print("ChartJS successfully sent!")
        # else:
        #     print(f"Failed to send data. Status: {response.status_code}, Response: {response.text}")
        # return response.status_code
    except Exception as e:
        print(f"Error sending ChartJS: {e}")
        raise

@task
def load_id():
    charts = {
        "key_id": "",
        "datetime_push":"",
        "status_code":"",
        "status_message":"",
        "customer_id":"",
        "date_start":"",
        "date_end":"",
        "result":[],
    }
    # LOAD_ID IS FOR JOB NAMING IDENTIFICATIONS AND ALSO INFORMING SERVER IF THE DATA IS NOT AVAILABLE
    if not os.path.exists("cust_request.json"):
        print(f"WARNING: data not found. Starting with empty buffer.")
        return {}
    else:
        try:
            with open("cust_request.json", "r") as f:
                data = json.load(f)
                customer_id = data["data"]["customer_id"]
                job_id_num = data["job_identification"]
            # with open('total_room.txt', 'r') as file:
            #     content = file.read()
            #     content = int(content)
            # return customer_id, job_id_num, content

            print("Let's check the total room number.")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {TOKEN_KEY}"
            }

            print("Requesting total_room_number.....")
            try:
                response = requests.get(ROOM_NUMBER_GET, headers=headers)
                response.raise_for_status()  # Raises HTTPError for bad status codes   
                incoming_data = response.json()
                total_room_number = 0
                area_identifier = 0
                for v in range(len(incoming_data["data"])):
                    if incoming_data["data"][v]["id"] == int(customer_id):
                        total_room_number = incoming_data["data"][v]["number_of_rooms"]
                        print(f"total room number is: {total_room_number}")
                        area_identifier = incoming_data["data"][v]["area_id"]
                        print(f"area id number is: {area_identifier}")
                        break

            except requests.exceptions.Timeout:
                raise RuntimeError("Request timed out. The server may be slow or unavailable.")
            except requests.exceptions.HTTPError as e:
                raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"Request failed: {e}")

            return customer_id, job_id_num, total_room_number
        except FileNotFoundError as e:
            print(f"[FILE NOT FOUND] Empty incoming data!")
            charts["key_id"] = job_id_num
            charts["datetime_push"] = datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
            charts["status_code"] = 3
            charts["status_message"] = "[FILE NOT FOUND] Empty incoming data!"
            charts["date_start"] = ""
            charts["date_end"] = ""
            charts["result"] = [{
                "model_version": "v1.0.0",
                "customer_id": customer_id,
                "currency_id": "",
                "forecasts": []
            }]
            error_summary = f"{type(e).__name__}: {e}"
            chartjs_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
            traceback.print_exc()
            raise
        except Exception as e:
            print(f"[ERROR] Unexpected error while reading file cust_request.json or total_room.txt!")
            error_summary = f"{type(e).__name__}: {e}"
            charts["key_id"] = job_id_num
            charts["datetime_push"] = datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
            charts["status_code"] = 3
            charts["status_message"] = error_summary
            charts["date_start"] = ""
            charts["date_end"] = ""
            charts["result"] = [{
                "model_version": "v1.0.0",
                "customer_id": customer_id,
                "currency_id": "",
                "forecasts": []
            }]
            error_summary = f"{type(e).__name__}: {e}"
            chartjs_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
            traceback.print_exc()
            raise

@task
def normalize_json_to_df(jsondata):
    with open(jsondata, "r") as f:
        data = json.load(f)  # Load entire JSON
        df = pd.json_normalize(data)  
    return df

# def fetch_json_from_api(api_urls):
#     main_df = pd.DataFrame()

#     try:
#         for filename in os.listdir(api_urls):
#             if filename.lower().endswith("inference_mat.json"):
#                 print(filename)
#                 filename = os.path.join(api_urls, filename)
#                 df_temp = normalize_json_to_df(filename)
#                 main_df = pd.concat([main_df, df_temp], ignore_index=True)

#         if main_df.shape == (0, 0):
#             raise ZeroDataError("Received zero value, cannot continue processing")
        
#         print("Fetching success!!!")
#         return main_df
#     except ZeroDataError as e:
#         error_summary = f"{type(e).__name__}: {e}"
#         return error_summary

@task
def fetch_json_from_api(api_urls):
    try:
        df_tempor = pd.DataFrame()
        name_list = []
        booking_date = []
        check_in = []
        check_out = []
        is_confirmed_list = []
        country_id = []
        currency_id = []
        net_amount_stay = []
        room_type_id = []
        room_type_name = []
        ota_id = []
        ota_name = []
        lokapro_room_id = []

        for filename in os.listdir(api_urls):
            if filename.lower().endswith("inference_mat.json"):
                filename = os.path.join(api_urls, filename)
                df_tempor = normalize_json_to_df(filename)
                # print(f"df_temp is \n{df_temp}\n")
        for i in range(len(df_tempor)):
            name_list.append(df_tempor.iloc[i, 1])
            booking_date.append(df_tempor.iloc[i, 2])
            check_in.append(df_tempor.iloc[i, 3])
            check_out.append(df_tempor.iloc[i, 4])
            is_confirmed_list.append(df_tempor.iloc[i, 5])
            country_id.append(df_tempor.iloc[i, 6])
            currency_id.append(df_tempor.iloc[i, 7])
            ota_id.append(df_tempor.iloc[i, 8])
            ota_name.append(df_tempor.iloc[i, 9])
            net_amount_stay.append(df_tempor.iloc[i, 10])
            room_type_id.append(df_tempor.iloc[i, 11])
            room_type_name.append(df_tempor.iloc[i, 14])
            lokapro_room_id.append(int(df_tempor.iloc[i, 13]) if not (pd.isna(df_tempor.iloc[i, 13])) else 0)
        
        main_df = pd.DataFrame({
            'customer_name': name_list,
            'booking_date': booking_date,
            'check_in': check_in,
            'check_out': check_out,
            'is_confirmed': is_confirmed_list,
            'country_id': country_id,
            'currency_id': currency_id,
            'ota_id' : ota_id,
            'ota_name': ota_name,
            'net_amount_stay': net_amount_stay,
            'room_type_id': room_type_id,
            'room_type_name': room_type_name,
            'lokapro_room_id': lokapro_room_id
        })

        if main_df.shape == (0, 0):
            raise ZeroDataError("Received zero value, cannot continue processing")
        
        print("Fetching success!!!")
        return main_df
    except ZeroDataError as e:
        error_summary = f"{type(e).__name__}: {e}"
        return error_summary

@task
def load_constant(customer_id): # return dalam bentuk dictionaries
    payload = {
        "customer_id": customer_id,
        "type": ""
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN_CONSTANT}"
    }
    print("\nRequesting Property constant...")

    try:
        response = requests.post(API_ENDPOINT_CONSTANT, headers=headers, json=payload, timeout=15, verify=False)
        response.raise_for_status()  # Raises HTTPError for bad status codes
        if response.status_code == 404:
            logging.error(f"Error 404 received!!!")     
        return response.json()
    except requests.exceptions.Timeout:
        raise RuntimeError("Request timed out. The server may be slow or unavailable.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")

@task
def preprocess_df(main_df):
    # main_df['net_amount_stay'] = main_df['net_amount_stay'] / 100
    # main_df = main_df.drop(columns='id')
    main_df = main_df.drop(columns='customer_name')
    main_df = main_df.dropna()
    # main_df = main_df.fillna('unknown')
    
    main_df['booking_date'] = pd.to_datetime(main_df['booking_date'], format='mixed',
                                            dayfirst=True)
    main_df['check_in'] = pd.to_datetime(main_df['check_in'], format='mixed',
                                            dayfirst=True)
    main_df['check_out'] = pd.to_datetime(main_df['check_out'], format='mixed',
                                            dayfirst=True)

    main_df['lead_days'] = (main_df['check_in'] - main_df['booking_date']).dt.days
    # main_df['booking_day'] = main_df['booking_date'].dt.day
    # main_df['booking_month'] = main_df['booking_date'].dt.month
    # main_df['booking_year'] = main_df['booking_date'].dt.year

    # main_df['check_in_day'] = main_df['check_in'].dt.day
    # main_df['check_in_month'] = main_df['check_in'].dt.month
    # main_df['check_in_year'] = main_df['check_in'].dt.year
    # main_df['check_in_weekday'] = main_df['check_in'].dt.day_name() 

    # main_df['check_out_day'] = main_df['check_out'].dt.day
    # main_df['check_out_month'] = main_df['check_out'].dt.month
    # main_df['check_out_year'] = main_df['check_out'].dt.year

    main_df['stay_days'] = (main_df['check_out'] - main_df['check_in']).dt.days
    main_df['price_per_night'] = main_df['net_amount_stay'] / main_df['stay_days']
    currency_id_data = int(main_df['currency_id'].values[0])

    # no_net = []
    # for i in range(len(main_df['net_amount_stay'])):
    #   if main_df.iloc[i, 5] == 0:
    #       no_net.append(0)
    #   else:
    #       no_net.append(1)
    # main_df['net_amount_avail'] = no_net
    main_df['net_amount_avail'] = (main_df['net_amount_stay'] != 0).astype(int)
    main_df['is_confirmed'] = main_df['is_confirmed'].replace({'t': True, 'f': False})
    main_df = main_df.loc[(main_df['lead_days'] >= 0) & 
                       (main_df['net_amount_avail'] == 1) &
                       (main_df['price_per_night'] <= 18000000) &
                       (main_df['net_amount_stay'] > 0) &
                       (main_df['ota_name'] != "Hotel Direct Booking"), :] 
    return main_df, currency_id_data
# ============================================= END SECTION  ===============================================

###############################################################################################
############----------------ALGORITHMS AND HELPER FUNCTIONS-----------------------------#######
###############################################################################################
@task
def outlier_fx(data, parameter):
    # data = data[data['ota_name'] != "Website Direct"]
    q1 = data[parameter].quantile(0.25)
    q3 = data[parameter].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    clean = data[(data[parameter] >= lower) & (data[parameter] <= upper)]
    return clean

@task
def capped_outlier_fx(data, parameter):
    q1 = data[parameter].quantile(0.25)
    q3 = data[parameter].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 0.25 * iqr
    upper = q3 + 0.25 * iqr
    capped = data.copy()
    print(f"lower is {lower}")
    print(f"upper is {upper}")
    capped[parameter] = capped[parameter].clip(lower, upper)
    print(f"after clipping, lower is {lower}")
    print(f"after clipping, upper is {upper}")
    if math.isnan(lower) or math.isnan(upper):
        return data
    else:
        return capped

@task
def adaptive_capped_outlier_fx(data, parameter):
    capped = data.copy()
    skew = data[parameter].skew()
    print(f"Skew value is {skew}")

    if abs(skew) <= 1:
        mean = data[parameter].mean()
        std = data[parameter].std()
        lower = mean - 2 * std
        upper = mean + 2 * std
        method = "2σ (standard deviation)"
        print(f"Detected outside of upper 2 sigma: {data[data[parameter] > upper].count()}")
        print(f"Detected outside of lower 2 sigma: {data[data[parameter] < lower].count()}")
    else:
        # Use IQR capping for skewed data
        q1 = data[parameter].quantile(0.25)
        q3 = data[parameter].quantile(0.75)
        iqr = q3 - q1
        lower = q1 - 0.25 * iqr
        upper = q3 + 0.25 * iqr
        method = "IQR"

    capped[parameter] = capped[parameter].clip(lower, upper)
    print(f"'{parameter}' skewness = {skew:.3f} → using {method} capping.")
    print(f"Capping range: [{lower:.3f}, {upper:.3f}]")
    return capped

@task
def segmentation_data(sub_df):
    sub_df['booking_date'] = pd.to_datetime(sub_df['booking_date'], format='mixed')
    short_ = sub_df[['booking_date','price_per_night']]
    short_['Year'] = short_['booking_date'].dt.year
    short_['Month'] = short_['booking_date'].dt.to_period('M')

    bin_size = 100000
    price_min = 100000
    price_max = 5000000
    bins = np.arange(price_min, price_max + bin_size, bin_size)
    short_['PriceBin'] = pd.cut(short_['price_per_night'], bins=bins, right=False)

    short_copy = short_.copy()
    lowest_bic = np.inf
    best_k = None
    bic_scores = []

    for k in range(1, 4):  # test 1 to 5 clusters
        gmm = GaussianMixture(n_components=k, random_state=42, init_params="k-means++")
        gmm.fit(short_[['price_per_night']])
        bic = gmm.bic(short_[['price_per_night']])
        bic_scores.append(bic)
        if bic < lowest_bic:
            lowest_bic = bic
            best_k = k
    print(f"Best cluster number: {best_k}")
    return best_k

@task
def distribution_shift_adjust(sub_df):
    try:
        results = []
        EMD_data = []
        overall = sub_df["price_per_night"]
        for ota, group in sub_df.groupby("ota_name"):
            dist = wasserstein_distance(group["price_per_night"], overall)
            EMD_data.append(int(dist))
            results.append({"OTA": ota, "EMD": dist})

        emd_results = pd.DataFrame(results).sort_values("EMD", ascending=False)
        q1_master = emd_results['EMD'].quantile(0.25)
        q3_master = emd_results['EMD'].quantile(0.75)
        iqr_master = q3_master - q1_master
        lower_bound = q1_master - 1.5 * iqr_master
        upper_bound = q3_master + 1.5 * iqr_master
        print(f"Lower bound: {lower_bound}")
        print(f"Upper bound: {upper_bound}")

        filtering_master = []
        if lower_bound > 0 and upper_bound > 0:
            for i in emd_results['OTA']:
                if emd_results[(emd_results['OTA'] == i)]['EMD'].values >= upper_bound:
                    filtering_master.append(i)
            print(f"to be filtered is: ", filtering_master)
        else:
            filtering_master = []
        return filtering_master
    except KeyError as e:
        print("[distribution_shift_adjust] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[distribution_shift_adjust] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[distribution_shift_adjust] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def create_sliding_windows(data, seq_length=20, horizon=5, step=1):
    X, y = [], []
    for i in range(0, len(data) - seq_length - horizon + 1, step):
        X.append(data[i:i+seq_length])
        y.append(data[i+seq_length:i+seq_length+horizon])
    return np.array(X), np.array(y)

@task
def mixup(X, y, alpha=0.2, augment_factor=1.0):
    n_original = len(X)
    n_augmented = int(n_original * augment_factor)
    lam = np.random.beta(alpha, alpha, size=n_augmented)

    idx_a = np.random.randint(0, n_original, n_augmented)
    idx_b = np.random.randint(0, n_original, n_augmented)
    lam_X = lam.reshape(-1, 1, 1)
    lam_y = lam.reshape(-1, 1, 1)
    print(f"Total X before mixup : {X.shape}")
    print(f"Total y before mixup : {y.shape}")
    X_mix = lam_X * X[idx_a] + (1 - lam_X) * X[idx_b]
    y_mix = lam_y * y[idx_a] + (1 - lam_y) * y[idx_b]
    X_aug = np.vstack([X, X_mix])
    y_aug = np.vstack([y, y_mix])
    print(f"Total X after mixup : {X_aug.shape}")
    print(f"Total y after mixup : {y_aug.shape}")
    return X_aug, y_aug

@task
def pickup_rate_correction(check_df):
    try:
        check_df['booking_date'] = pd.to_datetime(check_df['booking_date'])
        check_df['check_in'] = pd.to_datetime(check_df['check_in'])

        daily_counts = check_df.groupby(['check_in', 'booking_date']).size().reset_index(name='daily_bookings')
        daily_counts['lead_days'] = (daily_counts['check_in'] - daily_counts['booking_date']).dt.days

        daily_counts['cumulative_bookings'] = daily_counts.groupby('check_in')['daily_bookings'].cumsum()
        daily_counts['daily_pickup'] = daily_counts.groupby('check_in')['cumulative_bookings'].diff()
        daily_counts['delta_lead_days'] = abs(daily_counts.groupby('check_in')['lead_days'].diff())
        first_day = daily_counts.groupby('check_in')['cumulative_bookings'].transform('first')
        first_lead_days = daily_counts.groupby('check_in')['lead_days'].transform('first')
        for i in range(len(daily_counts)):
            if pd.isna(daily_counts.loc[i, 'daily_pickup']):
                daily_counts.loc[i, 'daily_pickup'] = daily_counts.loc[i, 'cumulative_bookings']
            if pd.isna(daily_counts.loc[i, 'delta_lead_days']):
                daily_counts.loc[i, 'delta_lead_days'] = 1
        daily_counts['daily_pickup'] = daily_counts['daily_pickup'].astype(int)
        # YANG MAU DIUBAH ITU CUMULATIVE PU RATE SAJA
        daily_counts['cumulative_pickup_rate'] = daily_counts['cumulative_bookings'] / daily_counts['delta_lead_days']
        daily_counts['booking_rate'] = daily_counts['cumulative_pickup_rate']
    # try:
    #     check_df['booking_date'] = pd.to_datetime(check_df['booking_date'])
    #     check_df['check_in'] = pd.to_datetime(check_df['check_in'])

    #     daily_counts = check_df.groupby(['booking_date', 'check_in']).size().reset_index(name='daily_bookings')
    #     daily_counts['lead_days'] = (daily_counts['check_in'] - daily_counts['booking_date']).dt.days
    #     daily_counts['cumulative_bookings'] = daily_counts.groupby('check_in')['daily_bookings'].cumsum()
    #     daily_counts['daily_pickup'] = daily_counts.groupby('check_in')['cumulative_bookings'].diff()
    #     daily_counts['delta_lead_days'] = abs(daily_counts.groupby('check_in')['lead_days'].diff())
    #     first_day = daily_counts.groupby('check_in')['cumulative_bookings'].transform('first')
    #     first_lead_days = daily_counts.groupby('check_in')['lead_days'].transform('first')
    #     daily_counts['cumulative_pickup_rate'] = ((daily_counts['cumulative_bookings'] - first_day) / first_day.replace(0, pd.NA))
    #     daily_counts['booking_rate'] = (daily_counts['cumulative_bookings'] / abs(daily_counts['lead_days'] - first_lead_days))
    #     for i in range(len(daily_counts['booking_rate'])):
    #         if daily_counts['booking_rate'][i] == np.inf:
    #             daily_counts['booking_rate'][i] = (daily_counts['cumulative_bookings'][i] / daily_counts['lead_days'][i])
    #     daily_counts['booking_rate'] = daily_counts['booking_rate'].replace(np.inf, 0)

    #     counter_days = daily_counts['check_in'].min()
    #     max_date = daily_counts['check_in'].max()
    #     while counter_days <= max_date:
    #         inspection = daily_counts[daily_counts['check_in'] == counter_days]
    #         if len(inspection) > 0:
    #             if inspection["booking_date"].values[-1] < inspection["check_in"].values[-1]:
    #                 first_lead_days = inspection['lead_days'].values[0]
    #                 correction_rate = inspection["cumulative_bookings"].values[-1] / first_lead_days
    #                 daily_counts.loc[daily_counts['check_in'] == counter_days, 'booking_rate'] = correction_rate
    #         counter_days = counter_days + timedelta(days=1)
        return daily_counts
    except KeyError as e:
        print("[pickup_rate_correction] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[pickup_rate_correction] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[pickup_rate_correction] Unexpected critical error:", e)
        traceback.print_exc()
        raise

# @task
# def continuous_occ_rate_correction(df_master, remaining_room, mem_buffer,
#                                    mem_buffer_ckout, max_room_number, avail_percentage):
#     try:
#         start_range = df_master['booking_date'].max() + timedelta(days=1)
#         end_range = df_master['check_in'].max()
#         mov_days = start_range

#         rooms_left = remaining_room
#         memory_buffer = mem_buffer
#         memory_buffer_ckout = mem_buffer_ckout
#         collected_date = []
#         occ_rate = []
#         track_room = []
#         counter = 0
#         delta_date = end_range - start_range
#         delta_date = int(delta_date.days)
#         while mov_days <= end_range:
#             # print(f"Booking date start from {mov_days}")
#             resampling = df_master[(df_master['booking_date'] >= mov_days) &
#                             (df_master['booking_date'] <= end_range)]
#             resampling = resampling.loc[(resampling['booking_date'] == mov_days),
#                                         ['check_in', 'check_out', 'booking_date', 'price_per_night']]
#             count_occur_ckin = resampling.groupby('check_in')['check_in'].count()
#             count_occur_ckout = resampling.groupby('check_out')['check_out'].count()

#             for i in range(len(count_occur_ckin)):
#                 ckin_record = count_occur_ckin.index[i]
#                 delta = int(count_occur_ckin.values[i])
#                 if ckin_record not in memory_buffer:
#                     memory_buffer[ckin_record] = [delta, ckin_record]
#                     # print(f"added Check-in : {memory_buffer[ckin_record]}")
#                 elif ckin_record in memory_buffer:
#                     memory_buffer[ckin_record][0] = delta + memory_buffer[ckin_record][0]
#                     # print(f"Day {mov_days} updated +{abs(delta)} bookings")

#             for i in range(len(count_occur_ckout)):
#                 ckout_record = count_occur_ckout.index[i]
#                 delta = int(count_occur_ckout.values[i])
#                 if ckout_record not in memory_buffer_ckout:
#                     memory_buffer_ckout[ckout_record] = [delta, ckout_record]
#                     # print(f"added Check-in : {memory_buffer_ckout[ckout_record]}")
#                 elif ckout_record in memory_buffer_ckout:
#                     memory_buffer_ckout[ckout_record][0] = delta + memory_buffer_ckout[ckout_record][0]
#                     # print(f"Check out Day {memory_buffer_ckout[ckout_record][1]} updated +{abs(delta)} bookings")
#             try:
#                 if mov_days in memory_buffer:
#                     if mov_days == memory_buffer[mov_days][1]:
#                         rooms_left = rooms_left - memory_buffer[mov_days][0]
#                         # print(f"Added rooms occupied : {memory_buffer[mov_days][0]}")
#                 if mov_days in memory_buffer_ckout:
#                     if mov_days == memory_buffer_ckout[mov_days][1]:
#                         rooms_left = rooms_left + memory_buffer_ckout[mov_days][0]
#                         # print(f"Freed occupied rooms : {memory_buffer_ckout[mov_days][0]}")
#             except Exception as e:
#                 print(f"[ERROR] details: {e}")

#             if counter % 30 == 0 and delta_date > 0:
#                 progress_calculation = (counter / delta_date) * 100
#                 print(f"Progress (Extension steps): {progress_calculation:.2f}%")
#                 print(f"Total rooms at day {mov_days} is {rooms_left}")
#             avail_occupancy = int((avail_percentage / 100) * max_room_number)

#             if avail_occupancy != 0:
#                 occupied_percentage = ((avail_occupancy - rooms_left) / avail_occupancy) * 100
#             else:
#                 occupied_percentage = 100
#             # occupancy_rate = occupied_percentage - 100
#             occupancy_rate = occupied_percentage
#             collected_date.append(mov_days)
#             occ_rate.append(occupancy_rate)
#             track_room.append(rooms_left)
#             # print(memory_buffer)
#             # print(memory_buffer_ckout, "\n")
#             counter = counter + 1
#             mov_days = mov_days + timedelta(days=1)

#         continuous_occ_rate = pd.DataFrame({
#             "Dates":collected_date,
#             "Occupancy Rate":occ_rate,
#             "Rooms Left":track_room
#         })
#         return continuous_occ_rate, memory_buffer
#     except KeyError as e:
#         print("[continuous_occ_rate_correction] Missing column:", e)
#         traceback.print_exc()
#         raise

#     except (TypeError, ValueError, IndexError, AttributeError) as e:
#         print("[continuous_occ_rate_correction] Invalid DataFrame:", e)
#         traceback.print_exc()
#         raise

#     except Exception as e:
#         print("[continuous_occ_rate_correction] Unexpected critical error:", e)
#         traceback.print_exc()
#         raise

@task
def occupancy_rate_correction(occ, avail_room, avail_percentage):
    try:
        occ['booking_date'] = pd.to_datetime(occ['booking_date'])
        occ['check_in'] = pd.to_datetime(occ['check_in'])
        occ['check_out'] = pd.to_datetime(occ['check_out'])

        start_range = occ['check_out'].min()
        end_range = occ['check_out'].max()
        print(f"[DEBUG] start date is {start_range}")
        print(f"[DEBUG] end date is : {end_range}")
        offset_days = start_range
        track_room = []
        collected_date = []
        occ_rate = []

        avail_occupancy = int((avail_percentage / 100) * avail_room)
        if avail_occupancy == 0: avail_occupancy = 1
        counter = 0
        delta_date = end_range - start_range
        delta_date = int(delta_date.days)
        while offset_days <= end_range:
            occ_focus = occ[(occ['check_in'] <= offset_days) & (occ['check_out'] > offset_days)]
            occ_count = len(occ_focus)
            offset_days = offset_days + timedelta(days=1)
            occupied_percentage = (occ_count / avail_occupancy) * 100
            collected_date.append(offset_days)
            occ_rate.append(occupied_percentage)
            track_room.append((avail_occupancy - occ_count))
            if counter % 30 == 0:
                progress_calculation = (counter / delta_date) * 100
                print(f"Progress: {progress_calculation:.2f}%")
                print(f"Total rooms at day {offset_days} is {(avail_occupancy - occ_count)}")
            counter += 1

        summary_occ = pd.DataFrame({
            "Dates":collected_date,
            "Occupancy Rate":occ_rate,
            "Rooms Left":track_room
        })

        return summary_occ
    # try:
    #     occ['booking_date'] = pd.to_datetime(occ['booking_date'])
    #     occ['check_in'] = pd.to_datetime(occ['check_in'])
    #     occ['check_out'] = pd.to_datetime(occ['check_out'])
    #     start_range = occ['booking_date'].min()
    #     end_range = occ['booking_date'].max()
    #     # end_range = start_range + timedelta(days=60)

    #     memory_buffer = {}
    #     memory_buffer_ckout = {}
    #     collected_date = []
    #     occ_rate = []
    #     track_room = []
    #     focus = occ.sort_values(by='booking_date')
    #     offset_days = start_range
    #     rooms_left = avail_room
    #     counter = 0
    #     delta_date = end_range - start_range
    #     delta_date = int(delta_date.days)
    #     while offset_days <= end_range:
    #         # print(f"Booking date start from {offset_days}")
    #         resampling = focus[(focus['booking_date'] >= offset_days) &
    #                         (focus['booking_date'] <= end_range)]
    #         resampling = resampling.loc[(resampling['booking_date'] == offset_days),
    #                                     ['check_in', 'check_out', 'booking_date', 'price_per_night']]
    #         count_occur_ckin = resampling.groupby('check_in')['check_in'].count()
    #         count_occur_ckout = resampling.groupby('check_out')['check_out'].count()

    #         for i in range(len(count_occur_ckin)):
    #             ckin_record = count_occur_ckin.index[i]
    #             delta = int(count_occur_ckin.values[i])
    #             if ckin_record not in memory_buffer:
    #                 memory_buffer[ckin_record] = [delta, ckin_record]
    #                 # print(f"added Check-in : {memory_buffer[ckin_record]}")
    #             elif ckin_record in memory_buffer:
    #                 memory_buffer[ckin_record][0] = delta + memory_buffer[ckin_record][0]
    #                 # print(f"Day {offset_days} updated +{abs(delta)} bookings")

    #         for i in range(len(count_occur_ckout)):
    #             ckout_record = count_occur_ckout.index[i]
    #             delta = int(count_occur_ckout.values[i])
    #             if ckout_record not in memory_buffer_ckout:
    #                 memory_buffer_ckout[ckout_record] = [delta, ckout_record]
    #                 # print(f"added Check-out : {memory_buffer_ckout[ckout_record]}")
    #             elif ckout_record in memory_buffer_ckout:
    #                 memory_buffer_ckout[ckout_record][0] = delta + memory_buffer_ckout[ckout_record][0]
    #                 # print(f"Check out Day {memory_buffer_ckout[ckout_record][1]} updated +{abs(delta)} bookings")

    #         try:
    #             if offset_days in memory_buffer:
    #                 if offset_days == memory_buffer[offset_days][1]:
    #                     rooms_left = rooms_left - memory_buffer[offset_days][0]
    #                     # print(f"Added rooms occupied : {memory_buffer[offset_days][0]}")

    #             if offset_days in memory_buffer_ckout:
    #                 if offset_days == memory_buffer_ckout[offset_days][1]:
    #                     rooms_left = rooms_left + memory_buffer_ckout[offset_days][0]
    #                     # print(f"Freed occupied rooms : {memory_buffer_ckout[offset_days][0]}")
    #         except Exception as e:
    #             print(f"[ERROR] details: {e}")

    #         if counter % 30 == 0:
    #             progress_calculation = (counter / delta_date) * 100
    #             print(f"Progress: {progress_calculation:.2f}%")
    #             print(f"Total rooms at day {offset_days} is {rooms_left}")
    #         avail_occupancy = int((avail_percentage / 100) * avail_room)
    #         if avail_occupancy != 0:
    #             occupied_percentage = ((avail_occupancy - rooms_left) / avail_occupancy) * 100
    #         else:
    #             occupied_percentage = 100
    #         # occupancy_rate = occupied_percentage - 100
    #         occupancy_rate = occupied_percentage
    #         collected_date.append(offset_days)
    #         occ_rate.append(occupancy_rate)
    #         track_room.append(rooms_left)
    #         counter = counter + 1
    #         # print(memory_buffer)
    #         # print(memory_buffer_ckout, "\n")
    #         offset_days = offset_days + timedelta(days=1)

    #     summary_occ = pd.DataFrame({
    #         "Dates":collected_date,
    #         "Occupancy Rate":occ_rate,
    #         "Rooms Left":track_room
    #     })
    #     next_prediction, memory_buffer = continuous_occ_rate_correction(occ, rooms_left, memory_buffer,
    #                                                                     memory_buffer_ckout, avail_room, avail_percentage)
    #     summary_occ = pd.concat([summary_occ, next_prediction], ignore_index=True)
    #     return summary_occ, memory_buffer
    except KeyError as e:
        print("[occupancy_rate_correction] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[occupancy_rate_correction] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[occupancy_rate_correction] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def segmentation_step(sub_dfa, room_type_avail):
    # sub_dfb = sub_dfa[sub_dfa['customer_name'] == customer_name]
    if room_type_avail == False:
        print("Room type not available, performing segmentation based on price_per_night.")
        sub_dfb = outlier_fx(sub_dfa, 'price_per_night')
        best_k_val = segmentation_data(sub_dfb)
        best_gmm = GaussianMixture(n_components=best_k_val, random_state=0).fit(sub_dfb[['price_per_night']])
        labels = best_gmm.predict(sub_dfb[['price_per_night']])
        sub_dfb['cluster'] = labels + 1  # Start cluster labels from 1 instead of 0
    else:
        print("Room type available, performing segmentation based on room_type.")
        sub_dfb = outlier_fx(sub_dfa, 'price_per_night')
        best_k_val = sub_dfb['room_type_id'].nunique()

        room_type_mapper = {}
        lokapro_room_mapper = {}
        counter = 1

        for i in (sub_dfb['room_type_id'].value_counts().index):
            room_type_mapper[i] = counter

            take_room_label = sub_dfb.loc[(sub_dfb['room_type_id'] == i), :]
            lokapro_room_mapper[i] = [take_room_label.iloc[0, 10], take_room_label.iloc[0, 11]]
            counter += 1
        print(f"room_type_mapper is : {room_type_mapper}")

        cluster_index = []
        lpro_index_id = []
        lpro_index_num = []
        for i in range(len(sub_dfb)):
            current_room_type = str(sub_dfb.iloc[i, 9])
            current_room_name = str(sub_dfb.iloc[i, 10])
            lokapro_room_numid = str(sub_dfb.iloc[i, 11])
            cluster_index.append(room_type_mapper[current_room_type])
            lpro_index_id.append(current_room_name)
            lpro_index_num.append(lokapro_room_numid)
        sub_dfb['cluster'] = cluster_index
        sub_dfb['lpro_room_name'] = lpro_index_id
        sub_dfb['lpro_room_numid'] = lpro_index_num
    return sub_dfb, best_k_val

@task
def feeder_adaptive_algorithm(dates_buffer=None, y_pred_mean=None, y_test_mean=None, 
                              ckin_data_buffer=None, booking_rate=None,
                              occ_data_buffer=None, avail_room=None, avail_percentage=100,
                              segment_n=None, pred_df=None, job_sched=1, n=None):
    adaptive_price_storage = {
        "dates_buffer":"",
        "y_pred_mean":"",
        "y_test_mean":"",
        "ckin_data_buffer":"",
        "booking_rate":"",
        "occ_data_buffer":"",
    }
    main_storage = {}
    infer_main_storage = {}
    adaptive_price_storage_infer = adaptive_price_storage.copy()
    # main_storage[n] = adaptive_price_storage.copy()
    # infer_main_storage[n] = adaptive_price_storage_infer.copy()

    try:
        if job_sched == 1:
            must_contain = [dates_buffer, y_pred_mean, y_test_mean, ckin_data_buffer, booking_rate,
                            occ_data_buffer]
            pointer = 0
            
            for k in adaptive_price_storage.keys():
                main_storage[k] = must_contain[pointer]
                pointer += 1
            return main_storage

        elif job_sched == 2:
            concise = segment_n[["check_in", "price_per_night"]]
            filtered_df = concise[concise["check_in"].isin(pred_df["Dates"])]
            filtered_df["check_in"] = pd.to_datetime(filtered_df["check_in"])
            filtered_df = filtered_df.groupby("check_in")["price_per_night"].mean()
            filtered_df.resample('D')
            value_capture = [float(pred_df.iloc[i, 1]) for i in range(len(pred_df)) if pred_df.iloc[i, 0] in filtered_df.index]
            date_capture = [pred_df.iloc[i, 0] for i in range(len(pred_df)) if pred_df.iloc[i, 0] in filtered_df.index]
            filtered_df2 = pd.DataFrame({
                "Dates":date_capture,
                "Values":value_capture
            })
            filtered_df2["Dates"] = pd.to_datetime(filtered_df2["Dates"]).dt.strftime("%Y-%m-%d")

            pred_df['Dates'] = pd.to_datetime(pred_df['Dates']).dt.strftime("%Y-%m-%d")
            ckin_data_buffer_infer = pickup_rate_correction(segment_n)
            booking_rate_infer = ckin_data_buffer_infer.groupby('check_in')['booking_rate'].last()
            booking_rate_infer.resample('D').last()
            booking_rate_infer = booking_rate_infer.reset_index(drop=False)
            booking_rate_infer['check_in'] = pd.to_datetime(booking_rate_infer['check_in'])
            occ_data_buffer_infer = occupancy_rate_correction(segment_n, avail_room, avail_percentage)
            must_contain = [filtered_df2["Dates"].values, value_capture, filtered_df.values,
                            ckin_data_buffer_infer, booking_rate_infer, occ_data_buffer_infer]
            pointer = 0
            for k in adaptive_price_storage_infer.keys():
                infer_main_storage[k] = must_contain[pointer]
                pointer += 1
            return infer_main_storage
        else:
            print("Job Scheduled entered is not correct! Choose 1 for debugging schedule, \n",
                "and 2 for inference schedule.")
            raise RuntimeError("[CAUTION] Error in job scheduling Adaptive Algorithm!")
    except KeyError as e:
        print("[feeder_adaptive_algorithm] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[feeder_adaptive_algorithm] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[feeder_adaptive_algorithm] Unexpected critical error:", e)
        traceback.print_exc()
        raise
# ============================================= END SECTION  ===============================================

###################################################################
######--------------PREDICTION ALGORITHM---------------------######
###################################################################
@task
def prediction_sequence(df_input, customer_id, job_id_num, total_room, 
                        room_type_avail, currency_info, constants_list=None):
    # ENC_SEQ_LEN_LT = 90
    # STEP_AHEAD_LT = 60
    MAX_FUTURE_LT = 360
    infer_aa_dictionaries = {}
    prediction_database = {}
    need_prediction = False
    auto_fill = False

    tf.config.optimizer.set_experimental_options({
        "layout_optimizer": False,
        "constant_folding": True,
        "shape_optimization": False,
        "remapping": False,
        "dependency_optimization": False,
        "loop_optimization": False,
    })
    
    charts = {
        "key_id":job_id_num,
        "datetime_push":datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S"),
        "status_code":"",
        "status_message":"",
        "customer_id":customer_id,
        "date_start":"",
        "date_end":"",
        "result":[{
            "model_version": "v1.0.0",
            "customer_id": customer_id,
            "currency_id": "",
            "forecasts": []
        }]
    }

    try:
        # BASICALLY THIS IS JUST COOLDOWN
        if not os.path.exists(os.path.join(FOLDER_PATH_PREDICTIONS, f"longterm_{customer_id}_predictions.pkl")): # CHECK IF PREVIOUSLY WE HAVE TRAINED A MODEL BEFORE
            print("Data not exist creating new entry.")
            need_prediction = True
        else:
            with open(os.path.join(FOLDER_PATH_PREDICTIONS, f"longterm_{customer_id}_predictions.pkl"), "rb") as f:
                print("Data exist. Checking.")
                data = pickle.load(f)
                print(f"[DEBUG] data is : \n{data}")
                expired_check = datetime.now() - data[1]["date_update"]
                # expired_check = datetime.now() - datetime.strptime("2025-04-25", "%Y-%m-%d")
                expired_hours = expired_check.total_seconds() / 3600
                print(f"expired_check is: {expired_hours}")
            if expired_hours > 6.0:
                print("Database expired, and will be updated.")
                need_prediction = True
            else:
                print("Database still okay, continue.")
                need_prediction = False

        if os.path.exists(os.path.join(FOLDER_PATH_WEIGHTS, f"{customer_id}.meta.pkl")):
            print(f"model weight {customer_id} found, checking expired date.....")
            full_path_meta = os.path.join(FOLDER_PATH_WEIGHTS, f"{customer_id}.meta.pkl")
            with open(full_path_meta, "rb") as f:
                data_train = pickle.load(f)
                exp_model_check = (datetime.now() - data_train["timestap_train"]).days
                if exp_model_check > 14:
                    print(f"model weight {customer_id} expired (more than 2 weeks), and will be updated!")
                    trigger_load_weights = False
                else:
                    print(f"model weight {customer_id} still good (less than 2 weeks).")
                    trigger_load_weights = True
        else:
            print(f"model weight {customer_id} not found, and will be created!")
            trigger_load_weights = False

        forecast_horizon_lt = 30
        sequence_length_lt = 45
        ENC_SEQ_LEN_LT = sequence_length_lt
        STEP_AHEAD_LT = forecast_horizon_lt
        model_longterm: keras.Model = make_model(sequence_length_lt, forecast_horizon_lt)
        
        if need_prediction == True: 
            print(f"===========PROCESSING CUSTOMER {customer_id}================")
            sub_df, n_cluster = segmentation_step(df_input, room_type_avail)
            if len(df_input) < 120:
                # This will raise exceptions and fill all room type with 0 values
                raise RuntimeError("Can't proceed with data less than 120 entries!")
            print(f"To be processed: {n_cluster} segment.")

            for n in range(1, n_cluster + 1):
                print(f"processing cluster no {n}")
                segment_n = sub_df[sub_df['cluster'] == n]
                print(f"with shape: {segment_n.shape}")
                will_be_filter = distribution_shift_adjust(segment_n)
                segment_n_check = segment_n[~segment_n['ota_name'].isin(will_be_filter)]
                if len(segment_n_check) > 0:
                    segment_n = segment_n_check
                else:
                    raise RuntimeError("Cleanup data resulting in small dataset, switching to auto-fill.")
                segment_n = capped_outlier_fx(segment_n, 'price_per_night')
                # starting_date = segment_n['booking_date'].max() - timedelta(days=365)
                starting_date = segment_n['booking_date'].min()
                algo_df = segment_n[segment_n['booking_date'] >= starting_date]
                # max_booking_date = segment_n['booking_date'].max()
                max_booking_date = datetime.now().strftime("%Y-%m-%d")

                X, y = [], []
                segment_n['check_in'] = pd.to_datetime(segment_n['check_in'])
                print(f"max booking date is: {max_booking_date}")
                ts = segment_n[segment_n['check_in'] <= pd.to_datetime(max_booking_date)] # clipping for model
                ts = ts.groupby('check_in')['price_per_night'].mean()
                # print(ts.head(10))
                # print(ts.tail(10))
                # Strategy 1: Fit LOWESS on irregular timestamps, then re-grid to daily
                # This avoids time-axis compression from resample+dropna
                lowess = sm.nonparametric.lowess
                x_ordinal = ts.index.map(pd.Timestamp.toordinal).values.astype(float)
                lowess_result = lowess(ts.values, x_ordinal, frac=0.02)

                # Re-grid the LOWESS curve onto a complete daily axis
                full_date_range = pd.date_range(ts.index.min(), ts.index.max(), freq='D')
                full_ordinals = full_date_range.map(pd.Timestamp.toordinal).values.astype(float)
                lowess_interp_fn = interp1d(lowess_result[:, 0], lowess_result[:, 1],
                                            kind='linear', fill_value='extrapolate')
                lowess_value = lowess_interp_fn(full_ordinals)

                # Build gap mask for sample weighting (Strategy 3)
                ts_daily_raw = ts.reindex(full_date_range)
                gap_mask_array = ts_daily_raw.isna().values
                n_gap_days = gap_mask_array.sum()
                print(f"[GAP-FILL] {n_gap_days}/{len(full_date_range)} days "
                      f"({n_gap_days/len(full_date_range)*100:.1f}%) are gap days")

                ts_monthly = pd.Series(lowess_value, index=full_date_range)

                scaler = MinMaxScaler()
                lowess_scaled = scaler.fit_transform(lowess_value.reshape(-1, 1))
                print("Raw data length is: ", len(lowess_scaled))

                start_index = len(lowess_scaled) - 270
                if len(lowess_scaled) >= 270:
                    lowess_scaled = lowess_scaled[start_index:]
                    gap_mask_sliced = gap_mask_array[start_index:]
                else:
                    lowess_scaled = lowess_scaled
                    gap_mask_sliced = gap_mask_array
                print("Revised lowess_scaled is is: ", len(lowess_scaled))

                for i in range(len(lowess_scaled) - sequence_length_lt - forecast_horizon_lt + 1):
                    # Input window (20 timesteps)
                    X.append(lowess_scaled[i : i + sequence_length_lt])
                    # Output window (next 10 timesteps)
                    y.append(lowess_scaled[i + sequence_length_lt : i + sequence_length_lt + forecast_horizon_lt])

                X = np.array(X).reshape(-1, sequence_length_lt, 1)  # (samples, 20, 1)
                y = np.array(y).reshape(-1, forecast_horizon_lt, 1)    # (samples, 10)
                print(f"Total X data that will be used for this models : {X.shape}")
                print(f"Total y data that will be used for this models : {y.shape}")

                # Strategy 3: Calculate sample weights — downweight windows spanning gaps
                sample_weights = np.ones(X.shape[0], dtype=np.float32)
                for sw_i in range(X.shape[0]):
                    window_end = sw_i + sequence_length_lt + forecast_horizon_lt
                    window_gap_count = gap_mask_sliced[sw_i:window_end].sum()
                    gap_ratio = window_gap_count / (sequence_length_lt + forecast_horizon_lt)
                    sample_weights[sw_i] = max(0.3, 1.0 - gap_ratio)
                n_downweighted = (sample_weights < 1.0).sum()
                print(f"[SAMPLE-WEIGHT] {n_downweighted}/{len(sample_weights)} windows "
                      f"downweighted (span gap regions)")

                if X.shape[0] >= 10:
                    def make_decoder_input(target):
                        start_token = np.zeros_like(target[:, :1, :])  # shape (batch, 1, 1)
                        return np.concatenate([start_token, target[:, :-1, :]], axis=1)

                    X_decoder  = make_decoder_input(y)
                    print("Main X is: ", X.shape)
                    print("Decoder X size: ", X_decoder.shape, y.shape)

                    if not trigger_load_weights:
                        early_stop = EarlyStopping(
                            monitor='loss',
                            patience=3,
                            restore_best_weights=True
                        )
                        reduce_lr = keras.callbacks.ReduceLROnPlateau(
                            factor=0.5, patience=3, monitor='loss', verbose=1
                        )

                        model_longterm.fit([X, X_decoder], y, epochs=20,
                                            sample_weight=sample_weights,
                                            callbacks=[reduce_lr, early_stop])
                    else:
                        full_path_weights = os.path.join(FOLDER_PATH_WEIGHTS, f"{customer_id}.weights.h5")
                        if os.path.exists(full_path_weights):
                            model_longterm.load_weights(full_path_weights)

                    last_window_lt = lowess_scaled[-ENC_SEQ_LEN_LT:].reshape(1, ENC_SEQ_LEN_LT, 1)
                    dec_input_lt = last_window_lt[:, -STEP_AHEAD_LT:, :]  # (1, 5, 1) as starting point
                    offset_time = datetime.now() - ts_monthly.index.max()
                    offset_time = offset_time.days

                    # future_pred_scaled_lt = []
                    # for _ in range(0, (MAX_FUTURE_LT + offset_time), STEP_AHEAD_LT):
                    #     pred_scaled_lt = model_longterm.predict([last_window_lt, dec_input_lt], verbose=0)  # (1, 5)
                    #     pred_scaled_lt = pred_scaled_lt.reshape(1, STEP_AHEAD_LT, N_FEATURES)
                    #     future_pred_scaled_lt.append(pred_scaled_lt.squeeze())
                    #     # Extend encoder window with new predictions
                    #     last_window_lt = np.concatenate([last_window_lt[:, STEP_AHEAD_LT:, :], pred_scaled_lt], axis=1)
                    #     # Decoder input becomes the latest predicted segment
                    #     dec_input_lt = pred_scaled_lt

                    # future_pred_scaled_lt = np.concatenate(future_pred_scaled_lt, axis=0).reshape(-1, 1)  # shape (30, 1)
                    steps = (MAX_FUTURE_LT + offset_time + STEP_AHEAD_LT - 1) // STEP_AHEAD_LT
                    future_pred_scaled_lt = np.zeros((steps * STEP_AHEAD_LT, 1), dtype=np.float32)

                    idx = 0
                    for _ in range(steps):
                        pred_scaled_lt = model_longterm.predict([last_window_lt, dec_input_lt], verbose=0)
                        future_pred_scaled_lt[idx:idx+STEP_AHEAD_LT, 0] = pred_scaled_lt.reshape(-1)
                        idx += STEP_AHEAD_LT
                    future_pred_lt = scaler.inverse_transform(future_pred_scaled_lt)

                    mod_date_lt = ts_monthly.index.max()
                    # mod_date_lt = datetime.now()
                    max_date_lt = mod_date_lt + timedelta(days=(MAX_FUTURE_LT + offset_time))
                    curr_date_lt = mod_date_lt

                    buffer_box_lt = []
                    while(curr_date_lt <= max_date_lt):
                        curr_date_lt = curr_date_lt + timedelta(days=1)
                        buffer_box_lt.append(curr_date_lt)
                    buffer_date_lt = ts_monthly.index.union(buffer_box_lt)
                    buffer_date_lt = pd.to_datetime(buffer_date_lt, format="%Y-%m-%d")
                    # buffer_date = buffer_date.tolist()
                    future_pred_lt = future_pred_lt[(-len(buffer_box_lt) + offset_time):]
                    buffer_date_lt = pd.Series(buffer_date_lt)
                    # print("Pay attention this is buffer date looks like: ", buffer_date)

                    prediction_pairing_lt = pd.DataFrame({
                        "Dates":buffer_date_lt.values[-len(future_pred_lt):],
                        "Prediction":future_pred_lt.flatten()
                    })

                    avail_room = total_room
                    avail_percentage = 100
                    infer_aa_dictionaries[n] = feeder_adaptive_algorithm(avail_room=avail_room,
                                                    avail_percentage=avail_percentage,
                                                    segment_n=segment_n,
                                                    pred_df=prediction_pairing_lt,
                                                    job_sched=2)
                    
                    storage = {
                        "date_update":datetime.now(),
                        "date_data":buffer_date_lt.values[-len(future_pred_lt):],
                        "value_data":future_pred_lt.flatten(),
                        "shape_date":buffer_date_lt.values[-len(future_pred_lt):].shape,
                        "shape_value":future_pred_lt.flatten().shape,
                        "room_id_name":segment_n['lokapro_room_id'].values[0],
                        "room_name":segment_n['room_type_name'].values[0]
                    }
                    prediction_database[n] = storage
                elif X.shape[0] < 10:
                    print("[WARNING]Data is not sufficient enough (less than 10 dataset received)")
                    print("As the data will increase in future, this segment will be available to be predicted.")          
                    print("System will do auto-fill since no reliable prediction available.")
                    offset_time = datetime.now() - ts_monthly.index.max()
                    offset_time = offset_time.days

                    mod_date_lt = ts_monthly.index.max()
                    # mod_date_lt = datetime.now()
                    max_date_lt = mod_date_lt + timedelta(days=(MAX_FUTURE_LT + offset_time))
                    curr_date_lt = mod_date_lt

                    buffer_box_lt = []
                    while(curr_date_lt <= max_date_lt):
                        curr_date_lt = curr_date_lt + timedelta(days=1)
                        buffer_box_lt.append(curr_date_lt)
                    buffer_date_lt = ts_monthly.index.union(buffer_box_lt)
                    buffer_date_lt = pd.to_datetime(buffer_date_lt, format="%Y-%m-%d")
                    # buffer_date = buffer_date.tolist()
                    buffer_date_lt = pd.Series(buffer_date_lt)

                    stat, p_value = stats.shapiro(segment_n['price_per_night'])
                    print(f"Shapiro-Wilk Normality Test:")
                    print(f"W-statistic : {stat:.4f}")
                    print(f"p-value     : {p_value:.4f}")
                    if p_value > 0.05:
                        print("USING MODE AUTO-FILL")
                        print("Reason: Prices are normally distributed")
                        tempor_sel_value = segment_n['price_per_night'].mode()
                        sel_value = np.average(tempor_sel_value)
                        # if len(tempor_sel_value) > 1:
                        #     sel_value = np.average(tempor_sel_value)
                        # else:
                        #     sel_value = tempor_sel_value
                    else:
                        print("USING MEDIAN AUTO-FILL")
                        print("Reason: Prices are NOT normally distributed")
                        sel_value = segment_n['price_per_night'].median()
                        print(f"segment_n median is: \n{sel_value}")
                        print(f"segment_n is : \n{segment_n}")
                        print(f"segment_n price pper night is : \n{segment_n['price_per_night']}")
                    
                    storage = {
                        "date_update":datetime.now(),
                        "date_data":buffer_date_lt.values[-360:],
                        "value_data":[0 for _ in range(len(buffer_date_lt))],
                        "shape_date":"",
                        "shape_value":"",
                        "room_id_name":segment_n['lokapro_room_id'].values[0],
                        "room_name":segment_n['room_type_name'].values[0]
                    }
                    prediction_database[n] = storage
                    # print(f"segment {n} has content of {storage}")
                    # TODO: instead use 0 analyze data distribution and inject highest mode data
                    price_storage = {
                        "dates_buffer":buffer_date_lt.values[-360:],
                        "y_pred_mean":[sel_value for _ in range(len(buffer_date_lt.values[-360:]))],
                        "y_test_mean":[sel_value for _ in range(len(buffer_date_lt.values[-360:]))],
                        "ckin_data_buffer":[0 for _ in range(len(buffer_date_lt.values[-360:]))],
                        "booking_rate":[0 for _ in range(len(buffer_date_lt.values[-360:]))],
                        "occ_data_buffer":[0 for _ in range(len(buffer_date_lt.values[-360:]))]
                    }
                    infer_aa_dictionaries[n] = price_storage

                os.makedirs(FOLDER_PATH_PREDICTIONS, exist_ok=True)  
                full_path_predictions = os.path.join(FOLDER_PATH_PREDICTIONS, f"longterm_{customer_id}_predictions.pkl")
                with open(full_path_predictions, "wb") as f:
                    pickle.dump(prediction_database, f)
                    print(f"success saving to predictions.pkl")

                os.makedirs(FOLDER_PATH_RECORDS, exist_ok=True)
                full_path_records = os.path.join(FOLDER_PATH_RECORDS, f"additional_record_{customer_id}.pkl")  
                with open(full_path_records, "wb") as f:
                    pickle.dump(infer_aa_dictionaries, f)
                    print(f"success saving to additional_record.pkl")

        if not trigger_load_weights:
            print(f"This model weights will be saved!")
            
            os.makedirs(FOLDER_PATH_WEIGHTS, exist_ok=True)
            new_path_weights = os.path.join(FOLDER_PATH_WEIGHTS, f"{customer_id}.weights.h5")
            new_meta_path = os.path.join(FOLDER_PATH_WEIGHTS, f"{customer_id}.meta.pkl")
            model_longterm.save_weights(new_path_weights)

            records_training = {
                "customer_id": customer_id,
                "timestap_train":datetime.now(),
                "weights_path":new_path_weights
            }

            with open(new_meta_path, "wb") as f:
                pickle.dump(records_training, f)
                print(f"success saving to model_meta.pkl")   
        K.clear_session()
        # del model_longterm
        gc.collect()
    except RuntimeError as e:
        print("[CAUTION] System will auto-fill empty fields with 0 values since reliable prediction is not available.")
        max_booking_date = datetime.now().strftime("%Y-%m-%d")

        df_input['check_in'] = pd.to_datetime(df_input['check_in'])
        print(f"max booking date is: {max_booking_date}")
        ts = df_input[df_input['check_in'] <= pd.to_datetime(max_booking_date)] # clipping for model
        ts = ts.groupby('check_in')['price_per_night'].mean()
        ts_monthly = ts.resample('D').mean()
        ts_monthly = ts_monthly.dropna()
        offset_time = datetime.now() - ts_monthly.index.max()
        offset_time = offset_time.days

        mod_date_lt = ts_monthly.index.max()
        # mod_date_lt = datetime.now()
        max_date_lt = mod_date_lt + timedelta(days=(MAX_FUTURE_LT + offset_time))
        curr_date_lt = mod_date_lt

        buffer_box_lt = []
        while(curr_date_lt <= max_date_lt):
            curr_date_lt = curr_date_lt + timedelta(days=1)
            buffer_box_lt.append(curr_date_lt)
        buffer_date_lt = ts_monthly.index.union(buffer_box_lt)
        buffer_date_lt = pd.to_datetime(buffer_date_lt, format="%Y-%m-%d")
        # buffer_date = buffer_date.tolist()
        # future_pred_lt = future_pred_lt[(-len(buffer_box_lt) + offset_time):]
        buffer_date_lt = pd.Series(buffer_date_lt)

        presentation_charts = {
            "model_version": "v1.0.0",
            "customer_id": customer_id,
            "currency_id": currency_info,
            "forecasts": []
        }

        sub_process_dict = {
            "room_type_id": "",
            "room_type_name": "",
            "forecast_date": "",
            "forecasted_price": "",
            "high_season_positive_multiplier_rate": 0,
            "all_season_positive_multiplier_rate": 0,
            "high_season_negative_multiplier_rate": 0,
            "all_season_negative_multiplier_rate": 0,
            "all_room_types_min_forecasted_price": None ,
            "all_room_types_median_forecasted_price": None,
            "all_room_types_max_forecasted_price": None
        }

        for n in range(1, n_cluster + 1):
            highlight_room_type = sub_df[sub_df['cluster'] == n]
            sub_process_dict_copy = sub_process_dict.copy()

            stat, p_value = stats.shapiro(highlight_room_type['price_per_night'])
            print(f"Shapiro-Wilk Normality Test:")
            print(f"W-statistic : {stat:.4f}")
            print(f"p-value     : {p_value:.4f}")
            if p_value > 0.05:
                print("USING MODE AUTO-FILL")
                print("Reason: Prices are normally distributed")
                tempor_sel_value = segment_n['price_per_night'].mode()
                sel_value = np.average(tempor_sel_value)
                # if len(tempor_sel_value) > 1:
                #     sel_value = np.average(tempor_sel_value)
                # else:
                #     sel_value = tempor_sel_value
            else:
                print("USING MEDIAN AUTO-FILL")
                print("Reason: Prices are NOT normally distributed")
                sel_value = highlight_room_type['price_per_night'].median()
            # sub_df['room_id'] and sub_df['room_name']
            highlight_roomtype_name = highlight_room_type['lpro_room_name'].values[0]
            highlight_roomtype_numid = str(highlight_room_type['lpro_room_numid'].values[0])
            for y in range(len(buffer_date_lt)):
                sub_process_dict_copy['forecast_date'] = pd.Timestamp(buffer_date_lt.values[y]).strftime('%Y-%m-%d')
                sub_process_dict_copy['forecasted_price'] = sel_value
                sub_process_dict_copy['room_type_id'] = highlight_roomtype_numid
                sub_process_dict_copy['room_type_name'] = highlight_roomtype_name
                presentation_charts['forecasts'].append(sub_process_dict_copy)
        # print(f"type of pc : {type(presentation_charts['forecasts'])}")
        # print(f"content of pc : {presentation_charts['forecasts'][0]}")
        print("A section")
        chartjs_to_endpoint(presentation_charts, customer_id)
    except ZeroDataError as e:
        error_summary = f"{type(e).__name__}: {e}"
        print(error_summary)
        charts["status_message"] = error_summary
        charts["status_code"] = 3
        chartjs_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
        K.clear_session()
        del model_longterm
        gc.collect()
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        print(error_summary)
        charts["status_message"] = error_summary
        charts["status_code"] = 3
        chartjs_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
        K.clear_session()
        del model_longterm
        gc.collect()

# ============================================= END SECTION  ===============================================

def error_logger(error_msg, customer_id=None):
    datetime_format_save = datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
    with open(f"runtime_error_logger_{datetime_format_save}.txt", 'a') as f:
        f.write(f"Date: {datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
        f.write("\nStatus: RUNTIME ERROR OCCURED..\n")
        if error_msg:
            f.write(f"Error due to : {error_msg}")
        if customer_id:
            f.write(f"Customer id is : {customer_id}")

def get_user_defined_rate(customer_id, room_id):
    print("Sending request to server and check if there's any saved rates.")
    url = os.getenv("REQUEST_CORRECTED_PRICE")
    if not url:
        print("[WARNING] REQUEST_CORRECTED_PRICE env variable not set. Skipping user-defined rates.")
        return []
    headers = {"Content-Type": "application/json",
            "Authorization": f"Bearer {TOKEN_KEY}"}
    payload = {
        "customer_id":int(customer_id),
        "room_type_id":int(room_id)
    }
    try:
        response = requests.post(url, headers=headers, json=payload) # expected endpoint api/send-corrected-price
        response.raise_for_status()  # Raises HTTPError for bad status codes
        if response.status_code == 404:
            logging.error(f"Returned 404 (Payload Invalid).") 
            raise RuntimeError("[ERROR] Payload invalid or not available.")     
        return response.json()
    except requests.exceptions.Timeout as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id)
        raise RuntimeError("Request timed out. The server may be slow or unavailable.")
    except requests.exceptions.HTTPError as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id)
        raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
    except requests.exceptions.RequestException as e:
        error_summary = f"{type(e).__name__}: {e}"
        error_logger(error_summary, customer_id)
        raise RuntimeError(f"Request failed: {e}")

###############################################################################################
#################--------------PRICE RATE ADAPTIVE SYSTEM---------------------#################
###############################################################################################
@task
def preprocess_pairing(dates_buffer, y_pred_mean, y_test_mean, ckin_data_buffer,
                        booking_rate, occ_data_buffer, user_corrections=None):
    pickup_rate_box = []
    booking_rate_box = []
    occupancy_rate_box = []
    date_box = []

    try:
        pairing = pd.DataFrame({
            "Date":dates_buffer,
            "Baseline Value":y_pred_mean,
            "Actual Price":y_test_mean
        })

        # =========================================================================
        # [PLACEHOLDER] USER CORRECTED PRICES INJECTION - LAYER 1: PRICE ANCHORING
        # =========================================================================
        # Payload format from Laravel: [{"YYYY-MM-DD": corrected_price}, ...] or {"YYYY-MM-DD": corrected_price}
        corrections_dict = {}
        if user_corrections is not None and len(user_corrections) > 0:
            print(f"[INFO] user_corrections is not none proceeding...")
            if isinstance(user_corrections, list):
                for item in user_corrections:
                    if isinstance(item, dict):
                        for d, p in item.items():
                            corrections_dict[str(d)] = float(p)
            elif isinstance(user_corrections, dict):
                corrections_dict = {str(d): float(p) for d, p in user_corrections.items()}

        if len(corrections_dict) > 0:
            print(f"[INFO] Injecting {len(corrections_dict)} user corrected prices into pairing dataset...")
            for date_str, custom_price in corrections_dict.items():
                date_mask = (pairing["Date"] == str(date_str))
                if date_mask.any():
                    # 1. Update Baseline Value: Anchors BayesianLinTS & safety limits to user target price
                    pairing.loc[date_mask, "Baseline Value"] = float(custom_price)
                    # 2. Update Actual Price: Calibrates the day-to-day ±10% jump guardrail
                    pairing.loc[date_mask, "Actual Price"] = float(custom_price)
        # =========================================================================

        if not isinstance(ckin_data_buffer, list):
            print("Normal pairing")
            tempo = ckin_data_buffer.sort_values(by="check_in")
            tempo["check_in"] = pd.to_datetime(tempo["check_in"]).dt.strftime("%Y-%m-%d")
            booking_rate["check_in"] = pd.to_datetime(booking_rate["check_in"]).dt.strftime("%Y-%m-%d")
            occ_data_buffer["Dates"] = pd.to_datetime(occ_data_buffer["Dates"]).dt.strftime("%Y-%m-%d")
            # crossmatch_df = pd.DataFrame()
            for i in range(len(pairing)):
                true_a, true_b, true_c = False, False, False
                if pairing.iloc[i, 0] in tempo["check_in"].values:
                    value_plchldr = tempo.iloc[(tempo["check_in"].values == pairing.iloc[i, 0]), 7].values[0]
                    pickup_rate_box.append(value_plchldr)
                    true_a = True
                if pairing.iloc[i, 0] in booking_rate["check_in"].values:
                    value_plchldr = booking_rate.iloc[(booking_rate["check_in"].values == pairing.iloc[i, 0]), 1].values[0]
                    booking_rate_box.append(value_plchldr)
                    true_b = True
                if pairing.iloc[i, 0] in occ_data_buffer["Dates"].values:
                    value_plchldr = occ_data_buffer.iloc[(occ_data_buffer["Dates"].values == pairing.iloc[i, 0]), 1].values[0]
                    occupancy_rate_box.append(value_plchldr)
                    true_c = True
                if true_a == True and true_b == True and true_c == True:
                    date_plchldr = occ_data_buffer.iloc[i, 0]
                    date_box.append(date_plchldr)
                    true_a, true_b, true_c = False, False, False
            pairing['Pickup Rate'] = pickup_rate_box
            pairing['Booking Rate'] = booking_rate_box
            pairing['Occupancy Rate'] = occupancy_rate_box
            pairing = pairing.sort_values(by="Date")
        else:
            print("Contingency pairing")
            pickup_rate_box = [0 for _ in range(len(pairing['Date']))]
            booking_rate_box = [0 for _ in range(len(pairing['Date']))]
            occupancy_rate_box = [0 for _ in range(len(pairing['Date']))]
            pairing['Pickup Rate'] = pickup_rate_box
            pairing['Booking Rate'] = booking_rate_box
            pairing['Occupancy Rate'] = occupancy_rate_box
            pairing = pairing.sort_values(by="Date")
        return pairing
    except KeyError as e:
        print("[preprocess_pairing] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[preprocess_pairing] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[preprocess_pairing] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def classify_event(z_score):
    if z_score > 2.5:
        return "surge"
    elif 1 < z_score < 2.5:
        return "mild_increase"
    elif -2 < z_score < -1:
        return "mild_drop"
    elif z_score < -2:
        return "drop_demand"
    else:
        return "normal"

@task
def compute_signals(df: pd.DataFrame, last_date, window_days: int = 30, as_of: datetime = None):
    """
    df must have columns: 'Date' (datetime), 'Pickup Rate', 'Booking Rate', 'Occupancy Rate'
    Returns a dict with recent values, rolling mean/std on Occupancy Rate (you can change to pickup or booking)
    """
    try:
        if as_of is None:
            as_of = datetime.now()
        # ensure Date is datetime
        if not np.issubdtype(df["Date"].dtype, np.datetime64):
            df["Date"] = pd.to_datetime(df["Date"])

        recent = df[(df["Date"] > last_date - timedelta(days=window_days)) & (df["Date"] <= last_date)]

        # we aggregate per day (if there are multiple rows per date)
        daily_occ = recent.groupby(recent["Date"].dt.date)["Occupancy Rate"].max()
        daily_pcr = recent.groupby(recent["Date"].dt.date)["Pickup Rate"].max()
        # handle empty
        if len(daily_occ) == 0:
            mu_occ = 0.0
            sigma_occ = 1.0
        else:
            mu_occ = daily_occ.mean()
            sigma_occ = daily_occ.std(ddof=0) if daily_occ.std(ddof=0) != 0 else 1.0

        if len(daily_pcr) == 0:
            mu_pcr = 0.0
            sigma_pcr = 1.0
        else:
            mu_pcr = daily_pcr.mean()
            sigma_pcr = daily_pcr.std(ddof=0) if daily_pcr.std(ddof=0) != 0 else 1.0

        # last observed row values (most recent timestamp)
        if len(recent) > 0:
            last_row = recent.sort_values("Date").iloc[-1]
            pickup_last = float(last_row.get("Pickup Rate", 0.0))
            booking_last = float(last_row.get("Booking Rate", 0.0))
            occupancy_last = float(last_row.get("Occupancy Rate", 0.0))
        else:
            last_row = pd.DataFrame()
            pickup_last = 0.0
            booking_last = 0.0
            occupancy_last = 0.0

        # z-scores relative to occupancy window (you can easily change to pickup)
        z_score_occ = (occupancy_last - mu_occ) / sigma_occ
        z_score_pcr = (pickup_last - mu_pcr) / sigma_pcr
        # if last_date == datetime.strptime("2026-03-01", "%Y-%m-%d") and len(last_row) > 0:
        #     print(f"[DEBUG] last_row is: {last_row}")
        #     print(f"[DEBUG] date {last_date} : \n{recent}")
        #     print(f"[DEBUG] occupancy_last: {occupancy_last}")
        #     print(f"[DEBUG] average: {mu_occ}")
        #     print(f"[DEBUG] stdev: {sigma_occ}")

        if abs(z_score_occ) > abs(z_score_pcr):
            mu = mu_occ
            sigma = sigma_occ
            z_score = z_score_occ
        else:
            mu = mu_pcr
            sigma = sigma_pcr
            z_score = z_score_pcr

        return {
            "pickup_last": pickup_last,
            "booking_last": booking_last,
            "occupancy_last": occupancy_last,
            "rolling_mean_occ": mu,
            "rolling_std_occ": sigma,
            "z_score_occ": z_score,
            "classification": classify_event(z_score),
            "occupancy_rate": occupancy_last
        }
    except KeyError as e:
        print("[compute_signals] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[compute_signals] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[compute_signals] Unexpected critical error:", e)
        traceback.print_exc()
        raise

# compute_test = compute_signals(pairing, 30)
# compute_test

# ---------- 1) FEATURE ENGINEERING ----------
@task
def prepare_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"])

    # normalize occupancy: e.g. -67 (remaining rooms) -> occupancy rate
    # Assuming total units = 100 (update if you know the exact number)
    df["occ_norm"] = df["Occupancy Rate"] 
    # df["occ_norm"] = df["occ_norm"].clip(0, 1)

    # 7-day smoothing
    df["pickup_ma7"] = df["Pickup Rate"].rolling(7, min_periods=3).mean()
    df["booking_ma7"] = df["Booking Rate"].rolling(7, min_periods=3).mean()
    df["occ_ma7"] = df["occ_norm"].rolling(7, min_periods=3).mean()

    # z-scores for demand spikes
    df["pickup_z"] = (df["Pickup Rate"] - df["pickup_ma7"]) / (
        df["Pickup Rate"].rolling(14, min_periods=5).std() + 1e-6
    )
    df["occ_z"] = (df["occ_norm"] - df["occ_ma7"]) / (
        df["occ_norm"].rolling(14, min_periods=5).std() + 1e-6
    )

    return df.fillna(method="bfill").fillna(method="ffill")

# ---------- 2) BANDIT CORE ----------
class BayesianLinearTS:
    def __init__(self, n_arms, dim, v=1.0, ridge=50.0, seed=42):
        self.n_arms = n_arms
        self.dim = dim
        self.v = v
        self.rng = np.random.default_rng(seed)
        self.A = [ridge * np.eye(dim) for _ in range(n_arms)]
        self.b = [np.zeros(dim) for _ in range(n_arms)]

    def select_arm(self, x: np.ndarray) -> int:
        scores = []
        for i in range(self.n_arms):
            A_inv = np.linalg.inv(self.A[i])
            mu = A_inv.dot(self.b[i])
            cov = self.v**2 * A_inv
            theta_sample = self.rng.multivariate_normal(mu, cov)
            scores.append(np.dot(x, theta_sample))
        return int(np.argmax(scores))

    def update(self, arm, x, reward):
        self.A[arm] += np.outer(x, x)
        self.b[arm] += reward * x

FEATURES = ["pickup_ma7", "pickup_z", "booking_ma7", "occ_ma7", "occ_z"]

@task
def build_context_vector(row) -> np.ndarray:
    return np.array([float(row.get(f, 0)) for f in FEATURES], dtype=np.float32)

# ---------- 3) WARMSTART USING HISTORY ----------
@task
def warmstart(agent, df, action_grid, elasticity, user_corrections=None):
    baseline_price = df["Baseline Value"].iloc[-1]
    # print(f"Baseline price is : {baseline_price}")

    # Payload format from Laravel: [{"YYYY-MM-DD": corrected_price}, ...] or {"YYYY-MM-DD": corrected_price}
    corrections_dict = {}
    if user_corrections is not None and len(user_corrections) > 0:
        if isinstance(user_corrections, list):
            for item in user_corrections:
                if isinstance(item, dict):
                    for d, p in item.items():
                        corrections_dict[str(d)] = float(p)
        elif isinstance(user_corrections, dict):
            corrections_dict = {str(d): float(p) for d, p in user_corrections.items()}

    for _, row in df.iterrows():
        base_conv = row["Occupancy Rate"]
        context = build_context_vector(row)
        date_str = str(row["Date"])

        for arm_idx, delta in enumerate(action_grid):
            # Synthetic economic revenue simulation
            adj_conv = max(0, base_conv * (1 + elasticity * (delta * 100)))
            reward = adj_conv * baseline_price

            # =========================================================================
            # [PLACEHOLDER] USER CORRECTED PRICES INJECTION - LAYER 2: POLICY LEARNING (RLHF)
            # =========================================================================
            # If the user manually set a price on this historical date, give an extra
            # reward bonus to the arm (delta) that was closest to the user's chosen price.
            if len(corrections_dict) > 0 and date_str in corrections_dict and baseline_price > 0:
                print("We got a predicted price that almost close to user corrected price!!!!!")
                user_price = corrections_dict[date_str]
                user_delta = (user_price - baseline_price) / baseline_price
                # If this candidate arm is very close to the user's manual adjustment
                if abs(delta - user_delta) < 0.02:
                    print("Ding ding ding!!!!!! GOT BONUS!!!!!!!")
                    reward *= 1.30  # +30% reward bonus to reinforce human decision policy
            # =========================================================================

            agent.update(arm_idx, context, reward)

# ---------- 4) PRICE SUGGESTION ----------
@task
def suggest_price(agent, df: pd.DataFrame, last_date, action_grid, max_jump=0.10):
    try:
        out_of_limit = False

        df = prepare_features(df)
        # print(f"df is : {df}\n")
        # print(f"last-date is : {last_date}\n")
        filtering_date = df.loc[(df["Date"] <= last_date), :]
        # print(f"filtering_date is : {filtering_date}")
        if len(filtering_date) > 0:
            last = filtering_date.iloc[-1]
        else: # CUMAN NYALA PAS PERTAMA-TAMA AJA PAS DF FILTERING DATE MASIH KOSONG
            last = df.iloc[-1]

        baseline_price = last["Baseline Value"]
        last_price = last["Actual Price"]
        # agent = BayesianLinearTS(n_arms=len(action_grid), dim=len(FEATURES), ridge=80)
        # warmstart(agent, df, action_grid, elasticity)
        context = build_context_vector(last)
        chosen_arm = agent.select_arm(context)
        delta = action_grid[chosen_arm]
        raw_price = baseline_price * (1 + delta)

        # safety constraints
        safe_price = np.clip(
            raw_price,
            baseline_price * 0.6,
            baseline_price * 1.6
        )

        if (raw_price < baseline_price * 0.6) or (raw_price > baseline_price * 1.6):
            out_of_limit = True
        else:
            out_of_limit = False

        safe_price = np.clip(
            safe_price,
            last_price * (1 - max_jump),
            last_price * (1 + max_jump)
        )

        return {
            "chosen_arm": chosen_arm,
            "delta": delta,
            "raw_price": round(raw_price, 2),
            "safe_price": round(float(safe_price), 2),
            "baseline": baseline_price,
            "last_price": last_price,
            "context": context.tolist(),
            "out_of_limit": True if out_of_limit == True else False
        }
    except KeyError as e:
        print("[suggest_price] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[suggest_price] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[suggest_price] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def load_record_data(customer_id):
    full_path_predictions = os.path.join(FOLDER_PATH_PREDICTIONS, f"longterm_{customer_id}_predictions.pkl")
    with open(full_path_predictions, "rb") as f:
        data = pickle.load(f)

    full_path_records = os.path.join(FOLDER_PATH_RECORDS, f"additional_record_{customer_id}.pkl") 
    with open(full_path_records, "rb") as k:
        data2 = pickle.load(k)
    return data, data2

@task
def adaptive_calculation(joblib_id, customer_id, df_input, currency_id, room_type_avail):
    data, data2 = load_record_data(customer_id)
    adaptive_suggestion = {}
    start_search = str(df_input['booking_date'].min())
    end_search = str(df_input['booking_date'].max())

    # =========================================================================
    # [PLACEHOLDER] USER CORRECTED PRICES - INGESTION PLACEHOLDER
    # =========================================================================
    # If user_corrections is not provided via parameter, you can load it here from API or DB:
    # Example format: user_corrections = {"2026-09-01": 750000, "2026-09-02": 800000}
    # if user_corrections is None:
    #     user_corrections = fetch_user_corrections_from_laravel(customer_id)
    # =========================================================================

    charts = {
        "key_id":joblib_id,
        "datetime_push":"",
        "status_code":"",
        "status_message":"",
        "customer_id":customer_id,
        "date_start":start_search,
        "date_end":end_search,
        "result":[]
    }
    try:
        for k in data2.keys():
            print(f"Processing segment {k}...")
            if len(data2[k]['dates_buffer']) > 0:
                print(f"Current room name is : {data[k]['room_id_name']}")

                feature_name = [n for n in data2[k].keys()]
                focus_room_id = data[k]['room_id_name']
                # [PLACEHOLDER] Fetch or parse user-corrected prices from Laravel / incoming request JSON
                # user_corrections = load_user_corrections(customer_id)
                # expected received file format is list of dicts like this:
                # [{"YYYY-MM-DD": corrected_price}, {"YYYY-MM-DD": corrected_price}, ...]
                user_corrections = get_user_defined_rate(customer_id, focus_room_id) 

                preprocessing_df = preprocess_pairing(data2[k][feature_name[0]], data2[k][feature_name[1]],
                                                    data2[k][feature_name[2]], data2[k][feature_name[3]],
                                                    data2[k][feature_name[4]], data2[k][feature_name[5]],
                                                    user_corrections=user_corrections)

                # additional_data_df untuk menambah dataset buat bandit pelajari, bahkan untuk harga dimasa depan (kalo sudah ada datanya kenapa gak dioelajari juga)
                additional_data_df = preprocessing_df
                elasticity = -0.01
                # print(f"Additional_data_df is : {additional_data_df}")
                # cek pake occupancy rate dari tanggal ini sampai ke beberapa hari ke depan yang ada historikal cek innya
                occupancy_rate_df = data2[k][feature_name[5]]
                if not isinstance(occupancy_rate_df, list):
                    print("Normal calculations")
                    occupancy_rate_df["Dates"] = pd.to_datetime(occupancy_rate_df["Dates"])
                    future_dates = occupancy_rate_df.loc[(occupancy_rate_df["Dates"] >= datetime.now()), "Dates"].values
                else:
                    print("Contingency calculations")
                    future_dates = preprocessing_df.loc[(preprocessing_df["Date"] >= datetime.now()), "Date"].values
                
                # print(f"[DEBUG] crosscheck future_dates {future_dates}")

                date_box = []
                z_score_box = []
                remarks = []
                constant_selection = []
                price_baseline = []
                recommended_price = []
                ool_data = []
                room_label = []
                room_name = []
                for i in future_dates:
                    # print(f"Date on check is {i}")
                    append_signal = True
                    # Convert i (last_date) to pandas Timestamp before passing to compute_signals
                    signal = compute_signals(preprocessing_df, pd.Timestamp(i), 30) # RETURN BOOLEAN ANOMALY OR NOT ANOMALY
                    # print(f"Signal is {signal["classification"]}")
                    # print(f"z-score is : {signal["z_score_occ"]}")
                    if signal["classification"] == "surge":
                        print("SURGE DETECTED!!!")
                        action_grid = [0.0, 0.02, 0.04, 0.06, 0.08]
                    elif signal["classification"] == "mild_increase":
                        print("MILD INCREASE DETECTED!!!")
                        action_grid = [0.0, 0.01, 0.03, 0.05]
                    elif signal["classification"] == "mild_drop":
                        print("MILD DROP DETECTED!!!")
                        action_grid = [-0.05, -0.03, -0.01, 0.0]
                    elif signal["classification"] == "drop_demand":
                        print("DROP DEMAND DETECTED!!!")
                        action_grid = [-0.08, -0.06, -0.04, -0.02, 0.0]
                    else:
                        # append_signal = False
                        # print(f"Date {i} no anomaly detected!")
                        append_signal == True
                        action_grid = [0.0]
                        # continue

                    agent = BayesianLinearTS(n_arms=len(action_grid), dim=len(FEATURES), ridge=80)
                    warmstart(agent, additional_data_df, action_grid, elasticity, user_corrections=user_corrections)
                    suggestion = suggest_price(agent, preprocessing_df, i, action_grid)
                    # print(f"price suggestion analysis : \n{suggestion}\n")
                    if append_signal == True:
                        date_box.append(i)
                        z_score_box.append(signal["z_score_occ"])
                        remarks.append(signal["classification"])
                        constant_selection.append(suggestion["delta"])
                        price_baseline.append(suggestion["baseline"])
                        recommended_price.append(suggestion["safe_price"])
                        ool_data.append(suggestion["out_of_limit"])
                        room_label.append(data[k]['room_id_name'])
                        room_name.append(data[k]['room_name'])

                # THIS IS FOR DEBUGGING ONLY, USE DATAFRAME FOR VISUAL, AND JSON FOR METADATA
                # action_sum_df = pd.DataFrame({
                #     "Date":date_box,
                #     "Z-Score":z_score_box,
                #     "Remarks":remarks,
                #     "Constant Selection":constant_selection,
                #     "Price Baseline":price_baseline,
                #     "Recommended Price":recommended_price
                # })
                # action_sum_df = {
                #     "Date":pd.to_datetime(date_box).strftime("%Y-%m-%d").tolist(),
                #     "Z-Score":z_score_box,
                #     "Remarks":remarks,
                #     "Constant Selection":constant_selection,
                #     "Price Baseline":price_baseline,
                #     "Recommended Price":recommended_price
                # }
                # action_sum_df = {
                #     "type": "line_chart",
                #     "chart_slug_name":"adaptive_pricing",
                #     "x-axis": pd.to_datetime(date_box).strftime("%Y-%m-%d").tolist(),
                #     "Price Baseline": price_baseline,
                #     "Recommended Price": recommended_price,
                # }

                action_sum_df = {
                    "type": "line_chart",
                    "chart_slug_name":"adaptive_pricing",
                    "Data": []
                }
                
                date_converted = pd.to_datetime(date_box).strftime("%Y-%m-%d").tolist()
                for iii in range(len(price_baseline)):
                    sub_action_sum = {
                        "Date": date_converted[iii],
                        "Price Baseline": price_baseline[iii],
                        "Recommended Price": recommended_price[iii],
                        "Out of limit": ool_data[iii],
                        "Rate Change": constant_selection[iii],
                        "Remarks": remarks[iii],
                        "Room Id Num": room_label[iii],
                        "Room Id Name": room_name[iii]
                    }
                    action_sum_df["Data"].append(sub_action_sum)
                # print(f"action_sum_df['Data'] check : {action_sum_df['Data']}")

            else:
                print("[SKIPPED SEGMENT] Empty Data! Will be auto-filled with 0.")
                action_sum_df = {
                    "type": "line_chart",
                    "chart_slug_name":"adaptive_pricing",
                    "Data": []
                }
            adaptive_suggestion[k] = action_sum_df
            # json_records[k] = action_sum_df
            charts["result"].append(action_sum_df)
            charts["datetime_push"] = datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
            charts["status_code"] = 2
            charts["status_message"] = "Data successfully processed!"
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        charts["datetime_push"] = datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
        charts["status_code"] = 3
        charts["status_message"] = error_summary
        charts["date_start"] = ""
        charts["date_end"] = ""
        charts["result"] = [{
            "model_version": "v1.0.0",
            "customer_id": customer_id,
            "currency_id": currency_id,
            "forecasts": []
        }]
        chartjs_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
        raise

    # REPROCESS THE CHARTS SO FOR LONGER THAN 30 DAYS IT FOLLOWS THE SAME STANDARDIZE FORMAT
    # THIS NEW CHARTS FORMAT IS ONLY FOR FRONT-END PRESENTATION, THE INTERNAL DATA STILL FOLLOWS THE SAME FORMAT AS BEFORE
    content_data = charts["result"]

    presentation_charts = {
        "model_version": "v1.0.0",
        "customer_id": customer_id,
        "currency_id": currency_id,
        "forecasts": []
    }

    # Better make DataFrame from the content_data and then reformat it to the standardized format, because if we do it directly from the content_data it will be too nested and hard to manage
    date_adaptive = []
    price_baseline_adaptive = []
    recommended_price_adaptive = []
    rate_change_adaptive = []
    remarks_adaptive = []
    room_type_num_adaptive = []
    room_real_name_adaptive = []
    if len(content_data) > 0:
        # print(f"[DEBUG] content_data length: {len(content_data)}")
        for i in range(len(content_data)):
            if len(content_data[i]["Data"]) > 0:
                for j in range(len(content_data[i]["Data"])):
                    # print(f"[DEBUG] Processing content_data[{i}]['Data'][{j}]")
                    date_adaptive.append(content_data[i]["Data"][j]["Date"])
                    price_baseline_adaptive.append(content_data[i]["Data"][j]["Price Baseline"])
                    recommended_price_adaptive.append(content_data[i]["Data"][j]["Recommended Price"])
                    rate_change_adaptive.append(content_data[i]["Data"][j]["Rate Change"])
                    remarks_adaptive.append(content_data[i]["Data"][j]["Remarks"])
                    room_type_num_adaptive.append(content_data[i]["Data"][j]["Room Id Num"])
                    room_real_name_adaptive.append(content_data[i]["Data"][j]["Room Id Name"])

            else:
                print(f"[DEBUG] content_data[{i}] has empty Data, skipping...")
                continue

        adaptive_suggestion_df = pd.DataFrame({
            "Date": date_adaptive,
            "Price Baseline": price_baseline_adaptive,
            "Recommended Price": recommended_price_adaptive,
            "Rate Change": rate_change_adaptive,
            "Remarks": remarks_adaptive,
            "Room Type": room_type_num_adaptive,
            "Room Type Name": room_real_name_adaptive
        })

        # sub_process_dict = {
        #     "room_type_id": "",
        #     "room_type_name": "",
        #     "forecast_date": "",
        #     "forecasted_price": None,
        #     "high_season_positive_multiplier_rate": "",
        #     "all_season_positive_multiplier_rate": "",
        #     "high_season_negative_multiplier_rate": "",
        #     "all_season_negative_multiplier_rate": "",
        #     "all_room_types_min_forecasted_price": None ,
        #     "all_room_types_median_forecasted_price": None,
        #     "all_room_types_max_forecasted_price": None
        # }

        sub_process_dict = {
            "property_id": int,
            "room_type_id": int,
            "forecast_date": datetime,
            "forecasted_price": int,
            "corrected_price": int
        }

        if len(adaptive_suggestion_df) > 0:
            adaptive_suggestion_df["Date"] = pd.to_datetime(adaptive_suggestion_df["Date"])
        else:
            print('No adaptive correction available')
            
        date_bin_checker = []
        for i in range(len(adaptive_suggestion_df)):
            sub_process_dict_copy = sub_process_dict.copy()
            sub_process_dict_copy["property_id"] = int(customer_id)
            # print(f"[DEBUG] Reprocessing adaptive_suggestion_df row {i} with Date {adaptive_suggestion_df.iloc[i, 0]} and Room Type {adaptive_suggestion_df.iloc[i, 5]}")
            # sub_process_dict_copy["high_season_positive_multiplier_rate"] = 0
            # sub_process_dict_copy["all_season_positive_multiplier_rate"] = 0
            # sub_process_dict_copy["high_season_negative_multiplier_rate"] = 0
            # sub_process_dict_copy["all_season_negative_multiplier_rate"] = 0

            if adaptive_suggestion_df.iloc[i, 0] != "" and adaptive_suggestion_df.iloc[i, 0] > datetime.now() + timedelta(days=30):
                sub_process_dict_copy["forecast_date"] = adaptive_suggestion_df.iloc[i, 0].strftime("%Y-%m-%d %H:%M:%S")
            else:
                continue

            if room_type_avail == True:
                # print(f"[DEBUG] Room type available, processing with room type {adaptive_suggestion_df.iloc[i, 5]}")
                sub_process_dict_copy["room_type_id"] = int(adaptive_suggestion_df.iloc[i, 5])
                sub_process_dict_copy["forecasted_price"] = int(adaptive_suggestion_df.iloc[i, 1])
                # sub_process_dict_copy["room_type_name"] = adaptive_suggestion_df.iloc[i, 6]

                if adaptive_suggestion_df.iloc[i, 4] == "surge":
                    # sub_process_dict_copy["high_season_positive_multiplier_rate"] = adaptive_suggestion_df.iloc[i, 3]
                    sub_process_dict_copy["corrected_price"] = adaptive_suggestion_df.iloc[i, 2]
                elif adaptive_suggestion_df.iloc[i, 4] == "mild_increase":
                    # sub_process_dict_copy["all_season_positive_multiplier_rate"] = adaptive_suggestion_df.iloc[i, 3]
                    sub_process_dict_copy["corrected_price"] = adaptive_suggestion_df.iloc[i, 2]
                elif adaptive_suggestion_df.iloc[i, 4] == "mild_drop":
                    # sub_process_dict_copy["all_season_negative_multiplier_rate"] = adaptive_suggestion_df.iloc[i, 3]
                    sub_process_dict_copy["corrected_price"] = adaptive_suggestion_df.iloc[i, 2]
                elif adaptive_suggestion_df.iloc[i, 4] == "drop_demand":
                    # sub_process_dict_copy["high_season_negative_multiplier_rate"] = adaptive_suggestion_df.iloc[i, 3]
                    sub_process_dict_copy["corrected_price"] = adaptive_suggestion_df.iloc[i, 2]
                else:
                    sub_process_dict_copy["corrected_price"] = adaptive_suggestion_df.iloc[i, 2]

                presentation_charts["forecasts"].append(sub_process_dict_copy)
            else:
                # TODO: AMBIL NILAI MINIMUM SAJA
                print(f"Checking if date : {adaptive_suggestion_df.iloc[i, 0]} already on the list or not")
                sub_process_dict_copy["room_type_id"] = 0
                if adaptive_suggestion_df.iloc[i, 0] not in date_bin_checker:
                    # print("Okay no such date, processing data...")
                    # print(f"[DEBUG] Room type not available, aggregating data for date {adaptive_suggestion_df.iloc[i, 0]}")
                    # Uh oh we don't have exact room_type so we will aggregate all room type based on the same date, and set max, min and median prices
                    aggregate_data_tempo = adaptive_suggestion_df.loc[(adaptive_suggestion_df["Date"] == adaptive_suggestion_df.iloc[i, 0]), :]
                    sub_process_dict_copy["corrected_price"] = aggregate_data_tempo["Recommended Price"].min()
                    sub_process_dict_copy["forecasted_price"] = aggregate_data_tempo["Price Baseline"].min()
                    # max_price_adaptive = aggregate_data_tempo["Recommended Price"].max()
                    # min_price_adaptive = aggregate_data_tempo["Recommended Price"].min()
                    # median_price_adaptive = aggregate_data_tempo["Recommended Price"].median()

                    # _highpos_rate_change_max = aggregate_data_tempo.loc[aggregate_data_tempo["Remarks"] == "surge", "Rate Change"].max()
                    # _allpos_rate_change_max = aggregate_data_tempo.loc[aggregate_data_tempo["Remarks"] == "mild_increase", "Rate Change"].max()
                    # _highneg_rate_change_max = aggregate_data_tempo.loc[aggregate_data_tempo["Remarks"] == "drop_demand", "Rate Change"].min()
                    # _allneg_rate_change_max = aggregate_data_tempo.loc[aggregate_data_tempo["Remarks"] == "mild_drop", "Rate Change"].min()
                    # sub_process_dict_copy["all_room_types_max_forecasted_price"] = max_price_adaptive
                    # sub_process_dict_copy["all_room_types_min_forecasted_price"] = min_price_adaptive
                    # sub_process_dict_copy["all_room_types_median_forecasted_price"] = median_price_adaptive
                    # sub_process_dict_copy["high_season_positive_multiplier_rate"] = _highpos_rate_change_max if not np.isnan(_highpos_rate_change_max) else 0
                    # sub_process_dict_copy["all_season_positive_multiplier_rate"] = _allpos_rate_change_max if not np.isnan(_allpos_rate_change_max) else 0
                    # sub_process_dict_copy["high_season_negative_multiplier_rate"] = _highneg_rate_change_max if not np.isnan(_highneg_rate_change_max) else 0
                    # sub_process_dict_copy["all_season_negative_multiplier_rate"] = _allneg_rate_change_max if not np.isnan(_allneg_rate_change_max) else 0
                    date_bin_checker.append(adaptive_suggestion_df.iloc[i, 0])
                    presentation_charts["forecasts"].append(sub_process_dict_copy)
                else:
                    print("That date already processed. Skipping.")

    else:
        print("No data in content_data to reprocess for adaptive suggestion charts.")
    
    # print(f"type of presentation_chart Date : {type(presentation_charts["forecasts"][0]["forecast_date"])}")
    # print(f"type of room_type_id : {type(presentation_charts["forecasts"][0]["room_type_id"])}")
    # print(f"type of forecasted_price : {type(presentation_charts["forecasts"][0]["forecasted_price"])}")
    # print(f"type of high_season_positive_multiplier_rate : {type(presentation_charts["forecasts"][0]["high_season_positive_multiplier_rate"])}")
    # print(f"type of all_season_positive_multiplier_rate : {type(presentation_charts["forecasts"][0]["all_season_positive_multiplier_rate"])}")
    # print(f"type of high_season_negative_multiplier_rate : {type(presentation_charts["forecasts"][0]["high_season_negative_multiplier_rate"])}")
    # print(f"type of all_season_negative_multiplier_rate : {type(presentation_charts["forecasts"][0]["all_season_negative_multiplier_rate"])}")
    print("B section")
    chartjs_to_endpoint(presentation_charts, customer_id)
    os.makedirs(FOLDER_PATH_SUGGESTION, exist_ok=True)
    full_path_suggestions = os.path.join(FOLDER_PATH_SUGGESTION, f"suggestion_containers_{customer_id}.pkl")  
    with open(full_path_suggestions, "wb") as f:
        pickle.dump(adaptive_suggestion, f)
        print(f"success saving to suggestion_containers.pkl")

    os.makedirs(FOLDER_PATH_RESULTS, exist_ok=True)
    result_path = os.path.join(FOLDER_PATH_RESULTS, f"results_{customer_id}.pkl")  
    with open(result_path, "wb") as f:
        pickle.dump(charts, f)
        print(f"success saving to results.pkl")

# ============================================= END SECTION  ===============================================

# @app.get("/adaptive-algorithm")
@task
def adaptive_algorithm():
    try:
        print("DEBUG: inference session STARTED")
        customer_id, job_id, room_number = load_id()
        # required_constants = load_constant(customer_id)
        df = fetch_json_from_api(CURR_DIR)
        print("Combined dataframe shape:", df.shape)
        if df.empty:
            return JSONResponse({"error": "No JSON files found"}, status_code=404)
        print("Combined dataframe shape:", df.shape)
        df, currency_info = preprocess_df(df)
        print("After preprocess shape:", df.shape)
        if "room_type_id" in df.columns:
            room_type_avail = True
        else:        
            room_type_avail = False

        prediction_sequence(df, customer_id, job_id, total_room=room_number, room_type_avail=room_type_avail, 
                            currency_info=currency_info, constants_list=None)
        adaptive_calculation(job_id, customer_id, df, currency_info, room_type_avail=room_type_avail)
        print("Process Finished, may add dictionaries of details in the future")
        file_path = ["inference_mat.json", "cust_request.json", "total_room.txt"]  # Replace with the actual file path
        for i in file_path:
            if os.path.exists(i):
                os.remove(i)
                print(f"File '{i}' deleted successfully.")
                gc.collect()
            else:
                print(f"File '{i}' does not exist.")
                gc.collect()
        return 0
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        print(error_summary)
        return error_summary
    
if __name__ == "__main__":
    task_name = sys.argv[1]

    if task_name not in TASKS:
        raise ValueError(f"Unknown task: {task_name}")

    TASKS[task_name]()