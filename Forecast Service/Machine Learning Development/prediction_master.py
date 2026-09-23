import logging

logger = logging.getLogger(__name__)
logger.info("APPLICATION STARTED")

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

# ======================================================================================= #
import pandas as pd
import numpy as np
import statsmodels.api as sm
from datetime import timedelta
from datetime import datetime
from statsmodels.tsa.seasonal import STL
import optuna, traceback, pickle, gc, sys
from scipy import stats
from scipy.interpolate import interp1d

import keras, json, requests, math, datetime
from tensorflow.keras import layers, models, backend as K
from fastapi import FastAPI
from dotenv import load_dotenv
from sklearn.preprocessing import MinMaxScaler
from scipy.stats import wasserstein_distance
from sklearn.metrics import (mean_absolute_error,
                             mean_absolute_percentage_error,
                             root_mean_squared_log_error)
from sklearn.mixture import GaussianMixture
from sklearn.model_selection import train_test_split
from tensorflow.keras.callbacks import EarlyStopping
from pathlib import Path

from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo
from keras.models import load_model
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

load_dotenv()
COMPANY_API_URL = os.getenv("COMPANY_API_URL", "http://localhost:8000/api/prediction-result")
HOLIDAY_EVENTS_GET = "https://tanggalmerah.upset.dev/api/holidays?year=2026&type=holiday"
MAIN_FILE = Path(__file__).resolve().parents[1]
WEBHOOK_URL = "https://2f68b6cd-a59f-4429-af46-00f19a73248e.mock.pstmn.io/webhook"
CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
API_URLS = CURR_DIR
FOLDER_PATH_COMPRATE = os.path.join(API_URLS, "Comprate")
FOLDER_PATH_ADAPTIVE = os.path.join(CURR_DIR, "Long_Prediction")
FOLDER_PATH_DATABASE = os.path.join(MAIN_FILE, "EB-LM-Book/Routine-LM")
STEP_AHEAD = 7     # predict 5 days at a time
MAX_FUTURE = 30    # total prediction horizon
ENC_SEQ_LEN = 14   # encoder input length
N_FEATURES = 1

API_KEY = os.getenv("TOKEN_SERVER")
PREDICTION_PROGRESS_URL = os.getenv("PREDICTION_PROGRESS_URL", "http://localhost:8000/api/prediction-progress")

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

# OVERIDE_DEBUG_STAGE = True
# app = FastAPI()

# @app.get("/")
# def root():
#     return {"message": "Inference Session Started!!"}

TASKS = {}

def task(fn):
    TASKS[fn.__name__] = fn
    return fn

class ZeroDataError(Exception):
    pass

###################################################################
######--------------MODEL ARCHITECTURE-----------------------######
###################################################################
forecast_horizon = STEP_AHEAD
ENC_LEN = 20       # encoder input length
DEC_LEN = STEP_AHEAD        # days to forecast per pass
N_FEATURES = 1     # number of input features per day
ENC_UNITS = [256, 128]
DEC_UNITS = [128, 64]
DROPOUT = 0.1

class BahdanauAttention(layers.Layer):
    def __init__(self, units):
        super().__init__()
        self.W1 = keras.layers.Dense(units)
        self.W2 = keras.layers.Dense(units)
        self.V  = keras.layers.Dense(1)

    def call(self, query, values):
        query_with_time_axis = tf.expand_dims(query, 1)
        score = self.V(tf.nn.tanh(self.W1(values) + self.W2(query_with_time_axis)))
        attention_weights = tf.nn.softmax(score, axis=1)
        context_vector = attention_weights * values
        context_vector = tf.reduce_sum(context_vector, axis=1)  # (batch, hidden_enc)
        return context_vector, tf.squeeze(attention_weights, -1)

# --- Build encoder ---
enc_inputs = keras.layers.Input(shape=(None, N_FEATURES), name='encoder_input')
x = enc_inputs
for i, units in enumerate(ENC_UNITS):
    return_seq = True
    x = keras.layers.GRU(units, return_sequences=return_seq, return_state=True,
                   dropout=DROPOUT, name=f'encoder_gru_{i}')(x)[0]
encoder_outputs = x
encoder_final_state = keras.layers.GlobalAveragePooling1D()(encoder_outputs)  # (batch, hidden)

# --- Decoder ---
dec_inputs = keras.layers.Input(shape=(DEC_LEN, N_FEATURES), name='decoder_input')
enc_proj = keras.layers.Dense(DEC_UNITS[0], name="enc_proj")(encoder_outputs)

# --- Attention ---
attention = BahdanauAttention(units=DEC_UNITS[0])
context_vector, _ = attention(encoder_final_state, enc_proj)   # (batch, hidden)
context_tiled = keras.layers.RepeatVector(DEC_LEN, name="context_tiled")(context_vector)  # (batch, DEC_LEN, hidden)
decoder_combined_input = keras.layers.Concatenate(axis=-1, name="decoder_combined")([dec_inputs, context_tiled])

y = decoder_combined_input
for i, units in enumerate(DEC_UNITS):
    y = keras.layers.GRU(units, return_sequences=True, dropout=DROPOUT, name=f'decoder_gru_{i}')(y)

y = keras.layers.TimeDistributed(keras.layers.Dense(64, activation='relu'), name='td_dense')(y)
y = keras.layers.TimeDistributed(keras.layers.Dense(1), name='td_out')(y)  # shape (batch, DEC_LEN, 1)
decoder_outputs = keras.layers.Reshape((DEC_LEN,), name='decoder_outputs')(y)

model = keras.models.Model([enc_inputs, dec_inputs], decoder_outputs)
model.compile(optimizer=tf.keras.optimizers.Adam(1e-3),
              loss=tf.keras.losses.Huber(), metrics=[tf.keras.metrics.MeanAbsoluteError()])
# model.summary()
# ============================================= END SECTION MODEL ===============================================


###############################################################################################
############----------------EXTRACTION AND LOADING FUNCTIONS----------------------------#######
###############################################################################################
@task
def data_to_endpoint(data, customer_id, error_msg=None, use_company_api=True):
    try:
        if use_company_api:
            url = COMPANY_API_URL
            headers = {"Content-Type": "application/json"}

        else:
            url = WEBHOOK_URL
            headers = {
                "Content-Type": "application/json"
            }

        response = requests.post(url, headers=headers, json=data, verify=False)
        date_format_save = datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
        with open(f"internal_logger_{date_format_save}.txt", 'a') as f:
            if len(data["forecasts"]) > 0:
                f.write("Predictive Pipeline ")
                f.write(f"Date: {datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
                f.write(f"Property ID: {customer_id}")
                f.write("\nStatus: SENT. DATA NOT BLANK.\n")
                print("Success saving status A.")
                print("Prediction Package successfully sent!")
            else:
                f.write("Predictive Pipeline ")
                f.write(f"Date: {datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
                f.write(f"Property ID: {customer_id}")
                f.write("\nStatus: ERROR OCCURED, DATA MIGHT NOT BE SENT.\n")
                print("Success saving status B.")
                if error_msg:
                    f.write(f"Error due to : {error_msg}")
                print("Prediction Package successfully sent with NOTE!")

    except Exception as e:
        print(f"Error sending prediction package due to: {e}")
        raise

@task
def load_id(): 
    charts = {
        "result":[],
    }

    # LOAD_ID IS FOR JOB NAMING IDENTIFICATIONS
    if not os.path.exists("cust_request.json"):
        print(f"WARNING: data not found. Starting with empty buffer.")
        return {}
    else:
        try:
            with open("cust_request.json", "r") as f:
                data = json.load(f)
                customer_id = data["data"]["customer_id"]
                job_id = data.get("job_identification", "")
            total_room_number = 15

            return customer_id, total_room_number, job_id
        except FileNotFoundError as e:
            print(f"[FILE NOT FOUND] Empty incoming data!")
            error_summary = f"{type(e).__name__}: {e}"
            charts["result"] = [{
                "status": f"failed due to {e}",
                "customer_id": customer_id,
                "forecasts": []
            }]
            data_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
            traceback.print_exc()
            raise
        except Exception as e:
            print(f"[ERROR] Unexpected error while reading file cust_request.json or total_room.txt!")
            error_summary = f"{type(e).__name__}: {e}"
            charts["result"] = [{
                "model_version": f"failed due to {e}",
                "customer_id": customer_id,
                "forecasts": []
            }]
            data_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
            traceback.print_exc()
            raise

@task
def normalize_json_to_df(jsondata):
    with open(jsondata, "r") as f:
        data = json.load(f)  # Load entire JSON
        df = pd.json_normalize(data)  
    return df

@task
def fetch_json_from_api(api_urls):
    try:
        df_tempor = pd.DataFrame()
        for filename in os.listdir(api_urls):
            if filename.lower().endswith("inference_mat.json"):
                filename = os.path.join(api_urls, filename)
                df_tempor = normalize_json_to_df(filename)
        if df_tempor.empty:
            raise ZeroDataError("Received zero value, cannot continue processing")
        
        main_df = pd.DataFrame()
        main_df['customer_name'] = df_tempor['customer_name'] if 'customer_name' in df_tempor.columns else df_tempor.iloc[:, 0]
        main_df['booking_date'] = df_tempor['booking_date'] if 'booking_date' in df_tempor.columns else df_tempor.iloc[:, 1]
        main_df['check_in'] = df_tempor['check_in'] if 'check_in' in df_tempor.columns else df_tempor.iloc[:, 2]
        main_df['check_out'] = df_tempor['check_out'] if 'check_out' in df_tempor.columns else df_tempor.iloc[:, 3]
        main_df['net_amount_stay'] = df_tempor['net_amount_stay'] if 'net_amount_stay' in df_tempor.columns else df_tempor.iloc[:, 4]
        
        if 'ota_name' in df_tempor.columns:
            main_df['ota_name'] = df_tempor['ota_name']
            main_df['ota_id'] = df_tempor['ota_id'] if 'ota_id' in df_tempor.columns else df_tempor['ota_name']
        elif 'ota_id' in df_tempor.columns:
            main_df['ota_id'] = df_tempor['ota_id']
            main_df['ota_name'] = df_tempor['ota_id'].astype(str)
        else:
            main_df['ota_id'] = df_tempor.iloc[:, 5] if df_tempor.shape[1] > 5 else "unknown"
            main_df['ota_name'] = main_df['ota_id'].astype(str)
            
        main_df['is_confirmed'] = df_tempor['is_confirmed'] if 'is_confirmed' in df_tempor.columns else (df_tempor.iloc[:, 6] if df_tempor.shape[1] > 6 else True)
        
        if 'room_type_id' in df_tempor.columns:
            main_df['room_type_id'] = df_tempor['room_type_id']
        elif df_tempor.shape[1] > 7:
            main_df['room_type_id'] = df_tempor.iloc[:, 7]

        print("Fetching success!!!")
        return main_df
    except ZeroDataError:
        raise
    except Exception as e:
        print(f"[fetch_json_from_api] Error: {e}")
        raise

@task
def preprocess_df(main_df):
    main_df = main_df.drop(columns='customer_name', errors='ignore')
    main_df = main_df.dropna()
    
    main_df['booking_date'] = pd.to_datetime(main_df['booking_date'], format='mixed',
                                            dayfirst=True)
    main_df['check_in'] = pd.to_datetime(main_df['check_in'], format='mixed',
                                            dayfirst=True)
    main_df['check_out'] = pd.to_datetime(main_df['check_out'], format='mixed',
                                            dayfirst=True)

    main_df['lead_days'] = (main_df['check_in'] - main_df['booking_date']).dt.days
    main_df['stay_days'] = (main_df['check_out'] - main_df['check_in']).dt.days
    main_df['price_per_night'] = main_df['net_amount_stay'] / main_df['stay_days']
    main_df['is_confirmed'] = main_df['is_confirmed'].replace({'t': True, 'f': False})

    cancellation_df = main_df[main_df['is_confirmed'] == False]
    if len(main_df) > 0:
        cancellation_rate = len(cancellation_df) / len(main_df)
    else:
        cancellation_rate = 0

    main_df['net_amount_avail'] = (main_df['net_amount_stay'] != 0).astype(int)
    
    main_df = main_df.loc[(main_df['lead_days'] >= 0) & 
                       (main_df['net_amount_avail'] == 1) &
                       (main_df['price_per_night'] <= 18000000) &
                       (main_df['net_amount_stay'] > 0) &
                       (main_df['ota_name'] != "Hotel Direct Booking"), :]
    return main_df, cancellation_rate
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
    lower = q1 - 0.25 * iqr
    upper = q3 + 0.25 * iqr
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
    print(f"Best cluster number: {best_k}") # keluarnya total (mis. langsung 2)
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
                matching_emd = emd_results[(emd_results['OTA'] == i)]['EMD'].values
                if len(matching_emd) > 0 and matching_emd[0] >= upper_bound:
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
def mixup(X, y, sample_weights=None, alpha=0.2, augment_factor=1.0):
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
    
    if sample_weights is not None:
        sw_mix = lam * sample_weights[idx_a] + (1 - lam) * sample_weights[idx_b]
        sw_aug = np.concatenate([sample_weights, sw_mix])
        return X_aug, y_aug, sw_aug
        
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
def seasonal_correction(master_df, mn_date, mode="mean"):
    try:
        master_df['booking_date'] = pd.to_datetime(master_df['booking_date'])
        if mode == "min":
            groupby_df = master_df.groupby('booking_date')['price_per_night'].min()
            df_weekly = groupby_df.resample('W').min()
        elif mode == "mean":
            groupby_df = master_df.groupby('booking_date')['price_per_night'].mean()
            df_weekly = groupby_df.resample('W').mean()
        elif mode == "max":
            groupby_df = master_df.groupby('booking_date')['price_per_night'].max()
            df_weekly = groupby_df.resample('W').max()
        df_weekly = df_weekly.dropna()

        df_weekly_filtered = [i.strftime("%Y-%m-%d") for i in df_weekly.index if i.strftime("%Y-%m-%d") >= mn_date.strftime("%Y-%m-%d")]
        stl = STL(df_weekly.values, period=52)  # 52 weeks in a year
        res = stl.fit()
        seasonal_pattern = res.seasonal[-len(df_weekly_filtered):]
        seasonal_df = pd.DataFrame({
            'Dates': df_weekly_filtered,
            'Seasonal_Pattern': seasonal_pattern
        })
        # Calculate percentage change compared to one week before
        percent_change = []
        for i in range(0, len(seasonal_df)):
            if i == 0:
                percent_change.append(0)
            else:
                percent_change_calc = (abs(seasonal_df['Seasonal_Pattern'][i] - seasonal_df['Seasonal_Pattern'][i-1]) / abs(seasonal_df['Seasonal_Pattern'][i-1])) * 100
                if seasonal_df['Seasonal_Pattern'][i] < seasonal_df['Seasonal_Pattern'][i-1]:
                    percent_change.append(-1 * percent_change_calc)
                elif seasonal_df['Seasonal_Pattern'][i] > seasonal_df['Seasonal_Pattern'][i-1]:
                    percent_change.append(percent_change_calc)
                else:
                    percent_change.append(0)
        # seasonal_df['Pct_Change'] = seasonal_df['Seasonal_Pattern'].pct_change() * 100  # multiply by 100 to get percentage
        seasonal_df['Pct_Change'] = percent_change
        # Optional: round to 2 decimal places for readability
        seasonal_df['Pct_Change'] = seasonal_df['Pct_Change'].round(2)
        return seasonal_df
    except KeyError as e:
        print("[seasonal_correction] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[seasonal_correction] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[seasonal_correction] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def segmentation_step(sub_dfa, is_room_type_avail):
    # sub_dfb = sub_dfa[sub_dfa['customer_name'] == customer_name]
    if is_room_type_avail == False:
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
        counter = 1

        for i in (sub_dfb['room_type_id'].value_counts().index):
            room_type_mapper[i] = counter
            counter += 1
        print(f"room_type_mapper is : {room_type_mapper}")

        sub_dfb['cluster'] = sub_dfb['room_type_id'].map(room_type_mapper)
    return sub_dfb, best_k_val

import warnings
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
@task
def inference_correction_applicator(sub_dfa, customer_name, master_lib, aggregate,
                          buff_p, buffer_date, y_pred_master, booking_rt, pri_date, comprate_calc=None):
    national_holiday_constant = 1.1 # 10% increase for demo
    pri_date_strs = set([pd.to_datetime(iv).strftime('%Y-%m-%d') for iv in pri_date])

    try:
        pairing = zip(buffer_date.values[-len(y_pred_master):], y_pred_master)
        min_date = buffer_date.values[-len(y_pred_master):].min() - pd.Timedelta(days=365)

        alpha = master_lib['corr_constant'][0]
        beta = master_lib['corr_constant'][1]
        gamma = master_lib['corr_constant'][2]
        delta = master_lib['corr_constant'][3]
        # epsilon = master_lib['corr_constant'][4]
        zeta = master_lib['corr_constant'][4]
        caged = {}
        
        for i in pairing:
            base_val = float(np.asarray(i[1]).ravel()[0])
            if i[0] in aggregate.index:
                corr_price = base_val * (1 + (alpha * (aggregate.loc[i[0]] / 100)))
            else:
                corr_price = base_val * (1 + (alpha * 0))

            if i[0] in booking_rt['check_in'].values:
                brate_rows = booking_rt.loc[(booking_rt['check_in'] == i[0]), 'booking_rate'].values
                extracted_brate = float(brate_rows[0]) if len(brate_rows) > 0 else 0.0
                corr_price = corr_price * (1 + (zeta * extracted_brate))

            i_date_str = pd.to_datetime(i[0]).strftime('%Y-%m-%d')
            if i_date_str in pri_date_strs:
                corr_price = corr_price * national_holiday_constant
                print(f"Applied national holiday correction for date {i[0]}")
  
            if i[0] in buff_p['Dates'].values:
                corr_price = corr_price * ((1 + (beta * buff_p.loc[(buff_p['Dates'] == i[0]), 'Occupancy Rate'])).tolist()[0])
            
            preview_seasonal_a = seasonal_correction(sub_dfa, min_date, mode="mean")
            preview_seasonal_a['Dates'] = pd.to_datetime(preview_seasonal_a['Dates'])
            lower_bound = preview_seasonal_a.loc[(preview_seasonal_a['Dates'] <= (pd.to_datetime(i[0]) - pd.Timedelta(days=365))), :]
            # lower_bound = lower_bound[pd.notna(lower_bound['Pct_Change'])].reset_index(drop=True)
            lower_bound = lower_bound.fillna(0).reset_index(drop=True)
            lower_focus = lower_bound.iloc[-1:, :]
            if len(lower_focus['Pct_Change']) > 0:
                pct_change_val = lower_focus['Pct_Change'].values[0]
                if abs(pct_change_val) < 1000:
                    corr_price = corr_price * (1 + (gamma * pct_change_val))
                else:
                    if pct_change_val > 0:
                        corr_price = corr_price * (1 + (gamma * 1000))
                    else:
                        corr_price = corr_price * (1 + (gamma * -1000))
            else:
                corr_price = corr_price
            corr_price = corr_price * (1 + delta)
            caged[i[0]] = corr_price
        caged_series = pd.Series(caged)
        return caged_series
    except KeyError as e:
        print("[inference_correction_applicator] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[inference_correction_applicator] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[inference_correction_applicator] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def correction_applicator(sub_dfa, customer_name, master_lib, aggregate,
                          buff_p, ts_data, y_pred_master, booking_rt, comprate_calc=None):
    print("Applying correction")
    try:
        pairing = zip(ts_data.index[-len(y_pred_master):], y_pred_master)
        min_date = ts_data.index[-len(y_pred_master):].min() - timedelta(days=365)

        alpha = master_lib['corr_constant'][0]
        beta = master_lib['corr_constant'][1]
        gamma = master_lib['corr_constant'][2]
        delta = master_lib['corr_constant'][3]
        # epsilon = master_lib['corr_constant'][4]
        zeta = master_lib['corr_constant'][4]
        caged = {}
        print(pairing)
        for i in pairing:
            base_val = float(np.asarray(i[1]).ravel()[0])
            if i[0] in aggregate.index:
                corr_price = base_val * (1 + (alpha * (aggregate.loc[i[0]] / 100)))
            else:
                corr_price = base_val * (1 + (alpha * 0))

            if i[0] in booking_rt['check_in'].values:
                brate_rows = booking_rt.loc[(booking_rt['check_in'] == i[0]), 'booking_rate'].values
                extracted_brate = float(brate_rows[0]) if len(brate_rows) > 0 else 0.0
                corr_price = corr_price * (1 + (zeta * extracted_brate))

            if i[0] in buff_p['Dates'].values:
                corr_price = corr_price * ((1 + (beta * buff_p.loc[(buff_p['Dates'] == i[0]), 'Occupancy Rate'])).tolist()[0])
            preview_seasonal_a = seasonal_correction(sub_dfa, min_date, mode="mean")
            preview_seasonal_a['Dates'] = pd.to_datetime(preview_seasonal_a['Dates'])
            lower_bound = preview_seasonal_a.loc[(preview_seasonal_a['Dates'] <= (pd.to_datetime(i[0]) - timedelta(days=365))), :]
            # lower_bound = lower_bound[pd.notna(lower_bound['Pct_Change'])].reset_index(drop=True)
            lower_bound = lower_bound.fillna(0).reset_index(drop=True)
            lower_focus = lower_bound.iloc[-1:, :]
            if len(lower_focus['Pct_Change']) > 0:
                pct_change_val = lower_focus['Pct_Change'].values[0]
                if abs(pct_change_val) < 1000:
                    corr_price = corr_price * (1 + (gamma * pct_change_val))
                else:
                    if pct_change_val > 0:
                        corr_price = corr_price * (1 + (gamma * 1000))
                    else:
                        corr_price = corr_price * (1 + (gamma * -1000))
            else:
                corr_price = corr_price
            corr_price = corr_price * (1 + delta)
            caged[i[0]] = corr_price
        caged_series = pd.Series(caged)
        return caged_series
    except KeyError as e:
        print("[correction_applicator] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[correction_applicator] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[correction_applicator] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def feeder_adaptive_algorithm(cancel, dates_buffer=None, y_pred_mean=None, y_test_mean=None, 
                              ckin_data_buffer=None, booking_rate=None,
                              occ_data_buffer=None, avail_room=None, avail_percentage=100,
                              segment_n=None, pred_df=None, job_sched=1, n=None):
    adaptive_price_storage = {
        "dates_buffer":"",
        "y_pred_mean":"",
        "y_test_mean":"",
        "ckin_data_buffer":"",
        "booking_rate":"",
        "occ_data_buffer":""
    }
    main_storage = {}
    infer_main_storage = {}
    adaptive_price_storage_infer = adaptive_price_storage.copy()
    main_storage[n] = adaptive_price_storage.copy()
    infer_main_storage[n] = adaptive_price_storage_infer.copy()

    if job_sched == 1:
        must_contain = [dates_buffer, y_pred_mean, y_test_mean, ckin_data_buffer, booking_rate,
                        occ_data_buffer]
        pointer = 0
        
        for k in adaptive_price_storage.keys():
            main_storage[n][k] = must_contain[pointer]
            pointer += 1
        return main_storage

    elif job_sched == 2:
        concise = segment_n[["check_in", "price_per_night"]]
        filtered_df = concise[concise["check_in"].isin(pred_df["Dates"])]
        filtered_df["check_in"] = pd.to_datetime(filtered_df["check_in"])
        filtered_df = filtered_df.groupby("check_in")["price_per_night"].mean()
        filtered_df = filtered_df.resample('D').mean()
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
        booking_rate_infer = booking_rate_infer.resample('D').last()
        booking_rate_infer = booking_rate_infer.reset_index(drop=False)
        booking_rate_infer['check_in'] = pd.to_datetime(booking_rate_infer['check_in'])
        occ_data_buffer_infer = occupancy_rate_correction(segment_n, avail_room, avail_percentage)
        must_contain = [filtered_df2["Dates"].values, value_capture, filtered_df.values,
                        ckin_data_buffer_infer, booking_rate_infer, occ_data_buffer_infer]
        pointer = 0
        for k in adaptive_price_storage_infer.keys():
            infer_main_storage[n][k] = must_contain[pointer]
            pointer += 1
        return infer_main_storage
    else:
        print("Job Scheduled entered is not correct! Choose 1 for debugging schedule, \n",
              "and 2 for inference schedule.")
        raise RuntimeError("[CAUTION] Error in job scheduling Adaptive Algorithm!")

# NEED SCRIPT TO SEED HOLIDAY EVENTS NATIONALLY
def property_holiday_match():
    try:
        url = HOLIDAY_EVENTS_GET
        headers = {"Content-Type": "application/json"}

        print(f"Request update on holiday events from {url}")
        response = requests.get(url, headers=headers)
        res_json = response.json()

        national_holidays = []
        data_list = res_json.get("data", []) if isinstance(res_json, dict) else res_json
        for i in data_list:
            if isinstance(i, dict) and "date" in i:
                national_holidays.append(i["date"])
            elif isinstance(i, str):
                national_holidays.append(i)

        return national_holidays
    except Exception as e:
        print(f"Error fetching holiday events due to: {e}")
        return []

def adaptive_correction(room_type, customer_id_num):
    print("Starting adaptive correction fetcher.")
    adaptive_dat = {
        "type": "line-and-scatter",
        "chart_slug_name" : "abnormal-market-activities",
        "Data": []
    }
    adaptive_df = pd.DataFrame({})
    full_path_suggestions = os.path.join(FOLDER_PATH_ADAPTIVE, f"results_{customer_id_num}.pkl")
    print("Checking if there's any adaptive correction available.")
    if os.path.exists(full_path_suggestions):
        print("Correction data found.")
        with open(full_path_suggestions, "rb") as x:
            data_pkl = pickle.load(x)
            result_list = data_pkl.get("result", []) if isinstance(data_pkl, dict) else []
            if isinstance(result_list, list) and 0 < room_type <= len(result_list):
                extracted_data = result_list[room_type - 1]
                if isinstance(extracted_data, dict) and "Data" in extracted_data and len(extracted_data["Data"]) > 0:
                    adaptive_df = pd.DataFrame({
                        "date_data": [extracted_data["Data"][d]["Date"] for d in range(len(extracted_data["Data"]))],
                        "price_baseline": [extracted_data["Data"][d]["Price Baseline"] for d in range(len(extracted_data["Data"]))],
                        "recommended_price": [extracted_data["Data"][d]["Recommended Price"] for d in range(len(extracted_data["Data"]))],
                        "out_of_limit": [extracted_data["Data"][d]["Out of limit"] for d in range(len(extracted_data["Data"]))],
                        "rate_change": [extracted_data["Data"][d]["Rate Change"] for d in range(len(extracted_data["Data"]))],
                        "remarks": [extracted_data["Data"][d]["Remarks"] for d in range(len(extracted_data["Data"]))]
                    })
                    print("Adaptive correction data found, processing...")
                    return adaptive_df
        print("No adaptive correction data available after processing.")
        return pd.DataFrame({})
    else:
        print("Adaptive correction data not found.")
        return pd.DataFrame({})



# ============================================= END SECTION  ===============================================

###################################################################
##########---------OPTUNA HYPERPARAMETER ALGORITHM--------#########
###################################################################
@task
def optuna_algorithm(main_df, ts_monthly, y_pred_mean, aggregated_ckin, 
                    buffer_pred, booking_rate, comp_rate_placeholder=None):
    pairing = zip(ts_monthly.index[-len(y_pred_mean):], y_pred_mean)
    min_date = ts_monthly.index[-len(y_pred_mean):].min() - timedelta(days=365)
    sub_dfa = main_df

    colected_vals = []
    colected_vals_2 = []
    colected_vals_3 = []
    colected_vals_4 = []
    # colected_vals_5 = []
    colected_vals_6 = []
    for i in pairing:
        if i[0] in aggregated_ckin.index:
            colected_vals.append(aggregated_ckin.loc[i[0]] / 100.0)
        else:
            colected_vals.append(0.0) # Ensure float type for consistency

        if i[0] in buffer_pred["Dates"].values:
            colected_vals_2.append(buffer_pred.loc[(buffer_pred["Dates"] == i[0]),
                                                        "Occupancy Rate"].values[0] / 100.0)
        else:
            colected_vals_2.append(0.0) 

        preview_seasonal_a = seasonal_correction(sub_dfa, min_date, mode="mean")
        preview_seasonal_a['Dates'] = pd.to_datetime(preview_seasonal_a['Dates'])
        lower_bound = preview_seasonal_a.loc[(preview_seasonal_a['Dates'] <= (i[0] - timedelta(days=365))), :]
        lower_bound = lower_bound.fillna(0).reset_index(drop=True)
        lower_focus = lower_bound.iloc[-1:, :]

        if not lower_focus.empty and lower_focus['Pct_Change'].values.size > 0:
            pct_change_val = lower_focus['Pct_Change'].values[0]
            if abs(pct_change_val) < 1000:
                colected_vals_3.append(pct_change_val)
            else:
                if pct_change_val > 0:
                    colected_vals_3.append(pct_change_val * 1000)
                else:
                    colected_vals_3.append(pct_change_val * -1000)
        else:
            colected_vals_3.append(0.0) 
        colected_vals_4.append(1e-3) # adjust bias

        if i[0] in booking_rate['check_in'].values:
            extracted_brate = float(booking_rate.loc[(booking_rate['check_in'] == i[0]), 'booking_rate'].values[0])
            colected_vals_6.append(extracted_brate)
        else:
            colected_vals_6.append(0.0)

    def apply_dynamic_pricing(baseline, factors, w):
        adjusted = (
            np.array(baseline)
            + w["occ"]    * factors["occ"]
            + w["pickup"] * factors["pickup"]
            + w["season"] * factors["season"]
            + w["bias"] * factors["bias"]
            + w["bookrt"] * factors["bookrt"]
        )
        return adjusted

    def evaluate_reward(adjusted_price, data_property):
        actual = data_property["actual_price_values"]
        error = np.mean(np.abs(adjusted_price - actual))
        reward = np.exp(-error)
        return reward

    def objective(trial, baseline, factors, data_property):
        w = {
            "occ": trial.suggest_float("occ_weight",-0.01, 0.01),
            "pickup": trial.suggest_float("pickup_weight",-0.0001, 0.0001),
            "season": trial.suggest_float("season_weight",-0.0001, 0.0001),
            "bias": trial.suggest_float("bias_weight",-0.0001, 0.0001),
            "bookrt": trial.suggest_float("bookrate_weight",-0.01, 0.01),
        }
        adjusted = apply_dynamic_pricing(baseline, factors, w)
        reward = evaluate_reward(adjusted, data_property)
        return reward

    def optimize_constants_for_property(data_property):
        baseline = y_pred_mean
        factors = {
            "occ":    data_property["occupancy_rate"],
            "pickup": data_property["actual_occupancy"],
            "season": data_property["seasonal_factor"],
            "bias": data_property["bias_adjust"],
            "bookrt": data_property["booking_rate"],
        }

        study = optuna.create_study(direction="maximize")
        study.optimize(
            lambda trial: objective(trial, baseline, factors, data_property),
            n_trials=900,
        )
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        print("Best reward:", study.best_value)
        print("Best parameters:", study.best_params)
        optimal_weights = {
            "occ":    study.best_params["occ_weight"],
            "pickup": study.best_params["pickup_weight"],
            "season": study.best_params["season_weight"],
            "bias": study.best_params["bias_weight"],
            "bookrt": study.best_params["bookrate_weight"]
        }
        return optimal_weights

    data_property = {
            "actual_price_values": ts_monthly.values[-len(y_pred_mean):], # Corrected: use values instead of index
            "actual_occupancy": np.array(colected_vals), #alpha aggregated_ckin
            "occupancy_rate": np.array(colected_vals_2), #buffer_pred_debug
            "seasonal_factor": np.array(colected_vals_3),
            "bias_adjust": np.array(colected_vals_4),
            "booking_rate": np.array(colected_vals_6)
    }
    optimal_weights = optimize_constants_for_property(data_property)
    return optimal_weights

# ============================================= END SECTION  ===============================================

###################################################################
######--------------PREDICTION ALGORITHM---------------------######
###################################################################
@task
def load_constants(): 
    # This is for demo only
    constant_return = {
        "total_room":15,
        "avail_percentage":100,
        "corr_constant":[0, 0, 0, 0, 0]
    }
    return constant_return

adaptive_price_storage = {
    "dates_buffer":"",
    "y_pred_mean":"",
    "y_test_mean":"",
    "ckin_data_buffer":"",
    "booking_rate":"",
    "occ_data_buffer":""
}
main_storage = {}
infer_main_storage = {}
adaptive_price_storage_infer = adaptive_price_storage.copy()

@task
def prediction_sequence(df_input, cancellation_number,
                         correction_active=True, optuna_active=True, adaptive_standby=True):
    loaded_model = model
    # debug_model = model
    forecast_horizon = 7
    customer_id_num, total_room, job_id = load_id() 
    # customer_id_num, joblib_id, delta_days = load_id() 
    start_search = str(df_input['booking_date'].min())
    end_search = str(df_input['booking_date'].max())
    MAX_FUTURE = 30
    counter_roomtype = False
    date_aggregator = []

    # CHECK IF ROOM TYPE DESCRIPTION AVAILABLE OR NOT TO DEBUG WE CAN EFORCE BOOL FALSE OR TRUE HERE TOO
    if "room_type_id" in df_input.columns:
        room_type_avail = True
    else:        
        room_type_avail = False

    tf.config.optimizer.set_experimental_options({
        "layout_optimizer": False,
        "constant_folding": True,
        "shape_optimization": False,
        "remapping": False,
        "dependency_optimization": False,
        "loop_optimization": False,
    })
    
    charts = {
        "result":{
                "status": "",
                "customer_id": customer_id_num,
                "forecasts": []
            }
    }
    try:
        print(f"===========PROCESSING CUSTOMER {customer_id_num}================")
        only_once_active = True
        print("Extracting necessary constants library.")
        master_lib = load_constants()
        master_lib["total_room"] = total_room
        sub_df, n_cluster = segmentation_step(df_input, room_type_avail)

        sub_details_dat = {}
        upper_sub_dat = []
        print(f"To be processed: {n_cluster} segment.")
        for n in range(1, n_cluster + 1):
            print(f"processing cluster no {n}")
            segment_n = sub_df[sub_df['cluster'] == n]
            will_be_filter = distribution_shift_adjust(segment_n)
            segment_n_check = segment_n[~segment_n['ota_name'].isin(will_be_filter)]
            if len(segment_n_check) > 0:
                    segment_n = segment_n_check
            else:
                print("Cleanup data resulting in small dataset, switching to auto-fill.")
            segment_n = capped_outlier_fx(segment_n, 'price_per_night')
            starting_date = segment_n['booking_date'].min()
            algo_df = segment_n[segment_n['booking_date'] >= starting_date]
            max_booking_date = datetime.datetime.now().strftime("%Y-%m-%d")
            print(f"check segment_n before process: {segment_n.shape}")
            if len(segment_n) < 50:
                print("CAUTION: NOT ENOUGH DATA TO PROCESS THIS SEGMENT, SKIPPING THIS CLUSTER!!!")

            main_storage[n] = adaptive_price_storage.copy()
            infer_main_storage[n] = adaptive_price_storage_infer.copy()

            X, y = [], []
            segment_n['check_in'] = pd.to_datetime(segment_n['check_in'])
            ts = segment_n[segment_n['check_in'] <= pd.to_datetime(max_booking_date)] # clipping for model
            ts = ts.groupby('check_in')['price_per_night'].mean()
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
            extra_steps = True
            scaler = MinMaxScaler()
            lowess_scaled = scaler.fit_transform(lowess_value.reshape(-1, 1))
            print("Raw data length is: ", len(lowess_scaled))

            sequence_length = 14
            if len(lowess_scaled) >= 500:
                # sequence_length = 20
                extra_steps = False
            else:
                # sequence_length = 15
                extra_steps = True

            for i in range(len(lowess_scaled) - sequence_length - forecast_horizon + 1):
                # Input window (20 timesteps)
                X.append(lowess_scaled[i : i + sequence_length])
                # Output window (next 10 timesteps)
                y.append(lowess_scaled[i + sequence_length : i + sequence_length + forecast_horizon])

            X = np.array(X).reshape(-1, sequence_length, 1)  # (samples, 20, 1)
            y = np.array(y).reshape(-1, forecast_horizon, 1)    # (samples, 10)
            print(f"Total X data that will be used for this models : {X.shape}")
            print(f"Total y data that will be used for this models : {y.shape}")

            # Strategy 3: Calculate sample weights — downweight windows spanning gaps
            sample_weights = np.ones(X.shape[0], dtype=np.float32)
            for sw_i in range(X.shape[0]):
                window_end = sw_i + sequence_length + forecast_horizon
                window_gap_count = gap_mask_array[sw_i:window_end].sum()
                gap_ratio = window_gap_count / (sequence_length + forecast_horizon)
                sample_weights[sw_i] = max(0.3, 1.0 - gap_ratio)
            n_downweighted = (sample_weights < 1.0).sum()
            print(f"[SAMPLE-WEIGHT] {n_downweighted}/{len(sample_weights)} windows "
                  f"downweighted (span gap regions)")

            if X.shape[0] >= 90 and len(segment_n) > 50:
                print("Data is sufficient enough, continuing!")
                n_samples = len(X)
                train_size = int(n_samples * 0.85)

                X_train, X_test = X[:train_size], X[train_size:]
                y_train, y_test = y[:train_size], y[train_size:]
                sample_weights_train = sample_weights[:train_size]

                if extra_steps == True:
                    print("Dataset is less than 500, applying mixup.")
                    X_train, y_train, sample_weights_train = mixup(X_train, y_train, sample_weights_train, alpha=0.4, augment_factor=1.2)
                    X, y, sample_weights = mixup(X, y, sample_weights, alpha=0.4, augment_factor=1.2)
                    extra_steps = False

                def make_decoder_input(y):
                    start_token = np.zeros_like(y[:, :1, :])  # shape (batch, 1, 1)
                    return np.concatenate([start_token, y[:, :-1, :]], axis=1)

                X_decoder_train = make_decoder_input(y_train).astype(np.float32)
                X_decoder_test  = make_decoder_input(y_test).astype(np.float32)
                X_decoder  = make_decoder_input(y).astype(np.float32)
                print("Train:", X_train.shape, y_train.shape)
                print("Test: ", X_test.shape, y_test.shape)
                print("Main X is: ", X.shape)

                print("decoder_train:", X_decoder_train.shape)
                print("Test_enc_dec : ", X_decoder_test.shape)
                print("Decoder X size: ", X_decoder.shape, y.shape)

                print("===========EXPECTED ACCURACY MEASUREMENT===================")
                early_stop = EarlyStopping(
                    monitor='loss',
                    patience=7,
                    restore_best_weights=True
                )

                reduce_lr = keras.callbacks.ReduceLROnPlateau(
                    factor=0.5, patience=3, monitor='loss', verbose=1
                )

                loaded_model.fit([X_train, X_decoder_train], y_train, epochs=30,
                                    sample_weight=sample_weights_train,
                                    callbacks=[reduce_lr, early_stop])
                loaded_model.evaluate([X_test, X_decoder_test], y_test)

                # ================FOR DEBUG ONLY=============================
                y_pred = loaded_model.predict([X_test, X_decoder_test])
                pred_scaled = scaler.inverse_transform(y_pred)
                y_test = np.squeeze(y_test, axis=-1)
                pred_test = scaler.inverse_transform(y_test)

                # Average across the 5 steps
                y_pred_mean = np.mean(pred_scaled, axis=1)
            
                try:
                    rmsle = root_mean_squared_log_error(pred_test, pred_scaled)
                    mae = mean_absolute_error(pred_test, pred_scaled)
                    print(f'print rmsle: {100 * rmsle:.2f} %')
                    print(f'print mae: {mae}')
                except Exception as e:
                    print(f"Error in calculating error value, due to : {e}")

                if optuna_active == True:
                    # restarting all constant before finding optimal one from Optuna
                    master_lib['corr_constant'] = [0 for _ in master_lib['corr_constant']]

                if correction_active == True:
                    avail_room = master_lib['total_room']
                    avail_percentage = master_lib['avail_percentage']
                    occ_data_buffer = occupancy_rate_correction(algo_df, avail_room, avail_percentage)
                    ckin_data_buffer = pickup_rate_correction(algo_df)
                    buffer_pred_debug = occ_data_buffer[(occ_data_buffer['Dates'] >= ts_monthly.index[-len(y_pred_mean):].min()) &
                                (occ_data_buffer['Dates'] <= ts_monthly.index[-len(y_pred_mean):].max())]
                    aggregated_ckin = ckin_data_buffer.groupby('check_in')['cumulative_pickup_rate'].max()
                    aggregated_ckin = aggregated_ckin.resample('D').max()
                    booking_rate = ckin_data_buffer.groupby('check_in')['booking_rate'].last()
                    booking_rate = booking_rate.resample('D').last()
                    booking_rate = booking_rate.reset_index(drop=False)
                    booking_rate['check_in'] = pd.to_datetime(booking_rate['check_in'])

                    # applying vanilla correction applicator without optuna correction
                    result_caged_debug = correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred_debug,
                                                        ts_monthly, y_pred_mean, booking_rate)
                    custom_error_mae = mean_absolute_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    custom_error_mape = mean_absolute_percentage_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    print(f'This model has performance with mape: {100 * custom_error_mape:.2f} %')
                    print(f'This model has performance with mae: {custom_error_mae}')


                if optuna_active == True:
                    print("Optuna algorithm is active.")
                    corrections = optuna_algorithm(segment_n, ts_monthly, y_pred_mean,
                                                    aggregated_ckin, buffer_pred_debug, booking_rate)
                    pointer = 0
                    for k, v in corrections.items():
                        master_lib["corr_constant"][pointer] = v
                        pointer += 1

                    # applying correction applicator with updated constants from optuna
                    result_caged_debug = correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred_debug,
                                                        ts_monthly, y_pred_mean, booking_rate)
                    print(f"Optuna correction has been applied, the latest performance result is: ")
                    custom_error_mae = mean_absolute_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    custom_error_mape = mean_absolute_percentage_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    print(f'This model has performance with mape: {100 * custom_error_mape:.2f} %')
                    print(f'This model has performance with mae: {custom_error_mae}')


                print("=====================INFERENCE STEP=========================")
                print(f"===========UPDATING BATCH ===================")
                early_stop = EarlyStopping(
                    monitor='loss',
                    patience=3,
                    restore_best_weights=True
                )

                reduce_lr = keras.callbacks.ReduceLROnPlateau(
                    factor=0.5, patience=3, monitor='loss', verbose=1
                )

                loaded_model.fit([X, X_decoder], y, epochs=30,
                                sample_weight=sample_weights,
                                callbacks=[reduce_lr, early_stop])

                last_window = lowess_scaled[-ENC_SEQ_LEN:].reshape(1, ENC_SEQ_LEN, N_FEATURES)
                dec_input = last_window[:, -STEP_AHEAD:, :]  # (1, 5, 1) as starting point
                offset_time = datetime.datetime.now() - ts_monthly.index.max()
                offset_time = offset_time.days
                print(f"offset days is {offset_time}")

                steps = (MAX_FUTURE + offset_time + STEP_AHEAD - 1) // STEP_AHEAD
                future_pred_scaled = np.zeros((steps * STEP_AHEAD, 1), dtype=np.float32)

                idx = 0
                for _ in range(steps):
                    pred_scaled = loaded_model.predict([last_window, dec_input], verbose=0)
                    future_pred_scaled[idx:idx+STEP_AHEAD, 0] = pred_scaled.reshape(-1)
                    idx += STEP_AHEAD
                future_pred = scaler.inverse_transform(future_pred_scaled)
                
                print(f"size of future_pred is: {len(future_pred)}")
                print(f"after processing the size of future_pred is: {len(future_pred)}")

                mod_date = datetime.datetime.now()
                buffer_box = [mod_date + timedelta(days=i) for i in range(1, MAX_FUTURE + 1)]
                buffer_date = ts_monthly.index.union(buffer_box)
                buffer_date = pd.to_datetime(buffer_date, format="%Y-%m-%d")
                future_pred = future_pred[-len(buffer_box):]
                # buffer_date = buffer_date.tolist()
                buffer_date = pd.Series(buffer_date)

                if correction_active == True:
                    avail_room = master_lib['total_room']
                    avail_percentage = master_lib['avail_percentage']
                    buffer_pred = occ_data_buffer[(occ_data_buffer['Dates'] >= buffer_date.values.min()) &
                                (occ_data_buffer['Dates'] <= buffer_date.values.max())]
                    booking_rate = ckin_data_buffer.groupby('check_in')['booking_rate'].last()
                    booking_rate = booking_rate.resample('D').last()
                    booking_rate = booking_rate.reset_index(drop=False)
                    booking_rate['check_in'] = pd.to_datetime(booking_rate['check_in'])

                    primary_date = property_holiday_match()
                    if len(primary_date) > 0:
                        # convert strings inside array to datetime that can be processed by inference_correction_applicator function
                        primary_date = [pd.to_datetime(date_str) for date_str in primary_date]

                    result_caged = inference_correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred, 
                                                        buffer_date, future_pred, booking_rate, primary_date)

                    print(f"type of buffer_date: {type(buffer_date.values[-len(future_pred):])}")

                    if adaptive_standby == True:
                        adaptive_df_compare = adaptive_correction(n, customer_id_num)
                    else:
                        adaptive_df_compare = pd.DataFrame({})
                    
                    sub_dat_tempo = pd.DataFrame({
                        "pred_res": [int(np.asarray(i).ravel()[0]) for i in result_caged.values],
                        "baseline_pred": future_pred.flatten().tolist(),
                        "x_axis": pd.to_datetime(buffer_date.values[-len(future_pred):]).date
                    })

                    # date_aggregator.append(sub_dat_tempo["x_axis"].values)
                    date_aggregator.extend(sub_dat_tempo["x_axis"])
                    # clean out duplicate date in date_aggregator then sort
                    date_aggregator = sorted(set(date_aggregator))

                    sub_process_dict = {
                        "property_id": int,
                        "room_type_id": int,
                        "forecast_date": datetime,
                        "forecasted_price": int,
                        "corrected_price": int
                    }

                    if not adaptive_df_compare.empty:
                        adaptive_df_compare['date_data'] = pd.to_datetime(adaptive_df_compare['date_data']).dt.date

                    for iii in range(len(sub_dat_tempo)):
                        sub_process_dict_copy = sub_process_dict.copy()
                        sub_process_dict_copy["forecast_date"] = pd.to_datetime(sub_dat_tempo["x_axis"].values[iii]).strftime("%Y-%m-%d %H:%M:%S")
                        sub_process_dict_copy["property_id"] = customer_id_num

                        if room_type_avail == True:
                            sub_process_dict_copy["room_type_id"] = int(algo_df['room_type_id'].values[0]) if ('room_type_id' in algo_df.columns and len(algo_df['room_type_id']) > 0) else 0

                        if not adaptive_df_compare.empty:
                            if sub_dat_tempo["x_axis"].values[iii] in adaptive_df_compare['date_data'].values:
                                # print(f"[DEBUG]Adaptive correction applied for date {sub_dat_tempo['x_axis'].values[iii]}")
                                adaptive_price = adaptive_df_compare.loc[
                                    (adaptive_df_compare['date_data'] == sub_dat_tempo["x_axis"].values[iii]),
                                    'recommended_price'
                                ].values[0]
                                rate_value = adaptive_df_compare.loc[
                                    (adaptive_df_compare['date_data'] == sub_dat_tempo["x_axis"].values[iii]),
                                    'rate_change'
                                ].values[0]
                                remarks = adaptive_df_compare.loc[
                                    (adaptive_df_compare['date_data'] == sub_dat_tempo["x_axis"].values[iii]),
                                    'remarks'].values[0]

                                if rate_value > 0:
                                    if (adaptive_price > sub_dat_tempo["pred_res"].values[iii]) and (
                                        adaptive_price < sub_dat_tempo["baseline_pred"].values[iii] * 1.15):
                                        print("[DEBUG] Applying adaptive price within limits.")
                                        sub_process_dict_copy["corrected_price"] = adaptive_price
                                    elif (adaptive_price > sub_dat_tempo["pred_res"].values[iii]) and (
                                        adaptive_price >= sub_dat_tempo["baseline_pred"].values[iii] * 1.15):
                                        print("[DEBUG] Capping adaptive price to 15% above baseline.")
                                        sub_process_dict_copy["corrected_price"] = sub_dat_tempo["baseline_pred"].values[iii] * 1.15         
                                    else:
                                        print("[DEBUG] No adaptive price applied, using baseline prediction.")
                                        sub_process_dict_copy["corrected_price"] = int(sub_dat_tempo["pred_res"].values[iii])

                                elif rate_value < 0:
                                    if (adaptive_price < sub_dat_tempo["pred_res"].values[iii]) and (
                                        adaptive_price > sub_dat_tempo["baseline_pred"].values[iii] * 0.85):
                                        print("[DEBUG] Applying adaptive price within limits.")
                                        sub_process_dict_copy["corrected_price"] = adaptive_price
                                    elif (adaptive_price < sub_dat_tempo["pred_res"].values[iii]) and (
                                        adaptive_price <= sub_dat_tempo["baseline_pred"].values[iii] * 0.85):
                                        print("[DEBUG] Capping adaptive price to 15% below baseline.")
                                        sub_process_dict_copy["corrected_price"] = sub_dat_tempo["baseline_pred"].values[iii] * 0.85
                                    else:
                                        print("[DEBUG] No adaptive price applied, using baseline prediction.")
                                        sub_process_dict_copy["corrected_price"] = int(sub_dat_tempo["pred_res"].values[iii])

                                else:
                                    print("No rate value detected.")
                                    sub_process_dict_copy["corrected_price"] = int(sub_dat_tempo["pred_res"].values[iii])

                                sub_process_dict_copy["forecasted_price"] = int(sub_dat_tempo["pred_res"].values[iii])
                                upper_sub_dat.append(sub_process_dict_copy)
                            else:
                                print(f"[DEBUG] No adaptive correction for date {sub_dat_tempo['x_axis'].values[iii]}, using baseline prediction.")
                                sub_process_dict_copy["corrected_price"] = int(sub_dat_tempo["pred_res"].values[iii])
                                sub_process_dict_copy["forecasted_price"] = int(sub_dat_tempo["pred_res"].values[iii])
                                upper_sub_dat.append(sub_process_dict_copy)
                        else:
                            print(f"[DEBUG] Adaptive correction dataframe is empty, using baseline prediction for date {sub_dat_tempo['x_axis'].values[iii]}.")
                            sub_process_dict_copy["corrected_price"] = int(sub_dat_tempo["pred_res"].values[iii])
                            sub_process_dict_copy["forecasted_price"] = int(sub_dat_tempo["pred_res"].values[iii])
                            upper_sub_dat.append(sub_process_dict_copy)
            else:
                print("Data is not sufficient enough")
                print("Skipping the segment, but in the future as the data sufficient enough, it might be able to be predicted.")
                print("[CAUTION]System will do auto-fill on empty field due to unreliable predictions.")

                sub_process_dict = {
                    "property_id": int,
                    "room_type_id": int,
                    "forecast_date": datetime,
                    "forecasted_price": int,
                    "corrected_price": int
                }

                mod_date = datetime.datetime.now()
                buffer_box = [mod_date + timedelta(days=i) for i in range(1, MAX_FUTURE + 1)]
                buffer_date = ts_monthly.index.union(buffer_box)
                buffer_date = pd.to_datetime(buffer_date, format="%Y-%m-%d")
                # buffer_date = buffer_date.tolist()
                buffer_date = pd.Series(buffer_date)
                buffer_date_processed = pd.to_datetime(buffer_date.values[-MAX_FUTURE:]).date

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

                for xi in range(len(buffer_date_processed)):
                    sub_process_dict_copy = sub_process_dict.copy()
                    sub_process_dict_copy["forecasted_price"] = sel_value 
                    sub_process_dict_copy["corrected_price"] = sel_value 
                    sub_process_dict_copy["room_type_id"] = int(algo_df['room_type_id'].values[0]) if ('room_type_id' in algo_df.columns and len(algo_df['room_type_id']) > 0) else 0
                    # sub_process_dict_copy["room_type_name"] = algo_df['lpro_room_name'].values[0]
                    sub_process_dict_copy["property_id"] = customer_id_num
                    sub_process_dict_copy["forecast_date"] = pd.to_datetime(buffer_date_processed[xi]).strftime("%Y-%m-%d %H:%M:%S")
                    upper_sub_dat.append(sub_process_dict_copy)

            gc.collect()
        charts["result"]["forecasts"] = upper_sub_dat
        # charts["result"]["tempo_adaptive"] = sub_details_dat
        charts["result"]["status"] = "Data successfully processed!"
        
        if room_type_avail == False:
            print("[DEBUG] Modifying the results forecast.")
            upper_sub_dat = []

            sub_process_dict = {
                "property_id": int,
                "room_type_id": int,
                "forecast_date": datetime,
                "forecasted_price": int,
                "corrected_price": int
            }

            def to_float(val):
                try:
                    return float(val) if val is not None else 0
                except (ValueError, TypeError):
                    return 0

            # print(f"[DEBUG] date_aggregator is {date_aggregator}")
            for iv in date_aggregator:
                price_list = []
                sub_process_dict_copy = sub_process_dict.copy()
                sub_process_dict_copy["room_type_id"] = 0
                sub_process_dict_copy["property_id"] = customer_id_num
                sub_process_dict_copy["forecast_date"] = pd.to_datetime(iv).strftime("%Y-%m-%d %H:%M:%S")
                for v in range(len(charts["result"]["forecasts"])):
                    if pd.to_datetime(charts["result"]["forecasts"][v]["forecast_date"]).date() == pd.to_datetime(iv).date():
                        print(f"reprocessing data {pd.to_datetime(charts['result']['forecasts'][v]['forecast_date']).date()} in {pd.to_datetime(iv).date()}")
                        price_list.append(to_float(charts["result"]["forecasts"][v]["forecasted_price"]))

                if price_list:
                    print("[DEBUG] Price list exists.")
                    non_zero_prices = [p for p in price_list if p != 0]
                    min_price = min(non_zero_prices) if non_zero_prices else 0
                    max_price = max(price_list)
                    median_price = np.median(non_zero_prices) if non_zero_prices else 0
                    if non_zero_prices:
                        sub_process_dict_copy["corrected_price"] = min_price 
                        sub_process_dict_copy["forecasted_price"] = min_price 
                    else:
                        sub_process_dict_copy["corrected_price"] = 0
                        sub_process_dict_copy["forecasted_price"] = 0

                    upper_sub_dat.append(sub_process_dict_copy)
            # Replace the original forecasts with the aggregated ones when room type is not available
            charts["result"]["forecasts"] = upper_sub_dat

        # [MILESTONE UPDATE] Milestone 9: Model Inference Done (85% progress)
        report_progress(
            job_id=job_id,
            customer_id=customer_id_num,
            progress_percent=85,
            stage_name="prediction_model_inference_completed",
            message="Model inference and prediction post-processing completed. Packaging results...",
            status="running"
        )

        data_to_endpoint(charts["result"], customer_id_num)
        K.clear_session()
        for var_name in ['loaded_model', 'segment_n', 'sub_df', 'algo_df', 'ts', 'ts_monthly']:
            if var_name in locals():
                try:
                    del locals()[var_name]
                except Exception:
                    pass
        gc.collect()

    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        print('error triggered')
        charts["result"] = [{
                "status": f"error due to {e}",
                "customer_id": customer_id_num,
                "forecasts": []
            }]
        data_to_endpoint(charts["result"][0], customer_id_num, error_msg=error_summary)
        K.clear_session()
        for var_name in ['loaded_model', 'segment_n', 'sub_df', 'algo_df', 'ts', 'ts_monthly']:
            if var_name in locals():
                try:
                    del locals()[var_name]
                except Exception:
                    pass
        gc.collect()
        raise
# ============================================= END SECTION  ===============================================

# @app.get("/inference-pipeline")
@task
def inference_pipeline():
    print("DEBUG: inference session STARTED")
    customer_id, total_room, job_id = load_id()
    df = fetch_json_from_api(API_URLS)
    print("Combined dataframe shape:", df.shape)
    if df.empty:
        return JSONResponse({"error": "No JSON files found in GitHub repo"}, status_code=404)
    print("Combined dataframe shape:", df.shape)
    df, cancel_rate = preprocess_df(df)
    print("After preprocess shape:", df.shape)

    # [MILESTONE UPDATE] Milestone 8: STL / Feature Prep Done (75% progress)
    report_progress(
        job_id=job_id,
        customer_id=customer_id,
        progress_percent=75,
        stage_name="prediction_feature_prep_completed",
        message="Data preprocessing and feature preparation completed. Starting model inference sequence...",
        status="running"
    )

    try:
        prediction_sequence(df, cancel_rate, correction_active=True)

        # [MILESTONE UPDATE] Milestone 10: Pipeline Completed (100% progress)
        report_progress(
            job_id=job_id,
            customer_id=customer_id,
            progress_percent=100,
            stage_name="prediction_pipeline_completed",
            message="Forecasting and prediction pipeline completed successfully.",
            status="completed"
        )

        print("Process Finished, may add dictionaries of details in the future")
        file_path = ["inference_mat.json", "cust_request.json"]  # Replace with the actual file path
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

if __name__ == "__main__":
    task_name = sys.argv[1]

    if task_name not in TASKS:
        raise ValueError(f"Unknown task: {task_name}")

    TASKS[task_name]()