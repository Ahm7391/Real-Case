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
import xgboost as xgb

import keras, json, requests, math, datetime
from tensorflow.keras import layers, models, backend as K
from fastapi import FastAPI
from dotenv import load_dotenv
from sklearn.preprocessing import MinMaxScaler
from scipy.stats import wasserstein_distance
from scipy.interpolate import interp1d
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
API_KEY = os.getenv('TOKEN_SERVER')
COMPANY_API_URL = os.getenv("PREDICTIVE_DATA_HOOK_URL")
PARAMETERS_API_URL = os.getenv("PARAMETERS_DATABASE_URL")
ROOM_NUMBER_GET = os.getenv("TOTAL_ROOM_NUMBER_URL")
CONSTANTS_BY_USER = os.getenv("CONSTANT_BY_USER")
WEBHOOK_URL = "https://2f68b6cd-a59f-4429-af46-00f19a73248e.mock.pstmn.io/webhook"
CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
API_URLS = CURR_DIR
MAIN_FILE = Path(__file__).resolve().parents[1]
FOLDER_PATH_COMPRATE = os.path.join(API_URLS, "Comprate")
FOLDER_PATH_ADAPTIVE = os.path.join(CURR_DIR, "Long_Prediction")
FOLDER_PATH_DATABASE = os.path.join(MAIN_FILE, "DB-LM")
STEP_AHEAD = 7     # predict 5 days at a time
MAX_FUTURE = 30    # total prediction horizon
ENC_SEQ_LEN = 14   # encoder input length
N_FEATURES = 1
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

###################################################################
######--------------XGBoost MODEL-----------------------######
###################################################################
MIN_ROWS_FOR_XGB = 20
RANDOM_STATE = 42

class HotelResidualForecaster:
    def __init__(self):
        self.model = None
        self.mode = "seq2seq_only"
        self.features = None

    def engineer_features(self, df):
        df = df.copy()

        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        # calendar
        df["dow"] = df["date"].dt.dayofweek
        df["month"] = df["date"].dt.month
        df["day"] = df["date"].dt.day
        df["weekofyear"] = df["date"].dt.isocalendar().week.astype(int)
        df["is_weekend"] = (df["dow"] >= 5).astype(int)

        # cyclic
        df["dow_sin"] = np.sin(2*np.pi*df["dow"]/7)
        df["dow_cos"] = np.cos(2*np.pi*df["dow"]/7)

        df["month_sin"] = np.sin(2*np.pi*df["month"]/12)
        df["month_cos"] = np.cos(2*np.pi*df["month"]/12)

        # irregular spacing
        df["days_since_prev"] = df["date"].diff().dt.days.fillna(0)

        return df

    def fit(self, df_hist, seq2seq_hist):
        df = self.engineer_features(df_hist)
        # Align seq2seq_hist to df's dates — xgb_active may return fewer rows
        # than the full prediction set due to date intersection filtering
        matched_seq2seq = seq2seq_hist.loc[
            seq2seq_hist.index.strftime('%Y-%m-%d').isin(df['date'].dt.strftime('%Y-%m-%d'))
        ]
        df["seq2seq_pred"] = matched_seq2seq.values
        df["residual"] = df["price_per_night"] - df["seq2seq_pred"]

        if len(df) < MIN_ROWS_FOR_XGB:
            print('Not passing threshold for at least minimum 20 entries!')
            self.mode = "seq2seq_only"
            return

        self.mode = "hybrid"
        self.features = [
            "occupancy_rate",
            "booking_rate",
            "seq2seq_pred",
            "dow",
            "month",
            "day",
            "weekofyear",
            "is_weekend",
            "dow_sin",
            "dow_cos",
            "month_sin",
            "month_cos",
            "days_since_prev"
        ]

        X = df[self.features]
        y = df["residual"]

        print("==================== CHECK THE PERFORMANCE FIRST ==================")
        X_train1, X_test1, y_train1, y_test1 = train_test_split(X, y, test_size=0.30, random_state=42)
        print(X_train1)
        print(X_test1)
        print(y_train1)
        print(y_test1)

        self.model = xgb.XGBRegressor(
            n_estimators=300,
            learning_rate=0.05,
            max_depth=35,
            subsample=0.8,
            colsample_bytree=0.8,
            objective="reg:squarederror",
            random_state=RANDOM_STATE,
            verbosity=3
        )

        self.model.fit(X_train1, y_train1)
        y_pred1 = self.model.predict(X_test1)
        MAE_1 = mean_absolute_error(y_test1, y_pred1)
        MAPE_1 = np.sum(np.abs(y_test1 - y_pred1)) / np.sum(np.abs(y_test1))
        print(f"Performance -> MAE: {MAE_1}, with MAPE: {MAPE_1}")

        if MAPE_1 > 0.12:
            print(f"MAPE value not passing threshold 12%. Performance -> MAE: {MAE_1}, with MAPE: {MAPE_1}")
            self.mode = "seq2seq_only"
            return
        
        print("==================== MODEL NOW WILL LEARN FULL DATA ==================")
        self.model.fit(X, y)

    def predict(self, future_df, seq2seq_future):
        future = self.engineer_features(future_df)
        # values_buffer_list = []
        # for i in range(len(seq2seq_future)):
        #     print(f"date format is: {seq2seq_future.index[i].strftime('%Y-%m-%d')}")
        #     if seq2seq_future.index[i].strftime('%Y-%m-%d') in future_df['date'].values:
        #         values_buffer_list.append(seq2seq_future.values[i])
        # future["seq2seq_pred"] = values_buffer_list
        # Align seq2seq_future to future's dates to prevent length mismatch
        future_date_strs = set(future['date'].dt.strftime('%Y-%m-%d'))
        matched_seq2seq = seq2seq_future.loc[
            seq2seq_future.index.strftime('%Y-%m-%d').isin(future_date_strs)
        ]
        future["seq2seq_pred"] = matched_seq2seq.values

        if self.mode == "seq2seq_only":
            future["predicted_price"] = future["seq2seq_pred"]
            return future[["date", "predicted_price"]]

        X_future = future[self.features]
        correction = self.model.predict(X_future)
        future["predicted_price"] = (
            future["seq2seq_pred"] + correction
        )

        return future[["date", "predicted_price"]]
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
            # url = COMPANY_API_URL
            # headers = {"Content-Type": "application/json",
            #            "Authorization": f"Bearer {API_KEY}"}
            # response = requests.post(WEBHOOK_URL, headers=headers, data=json.dumps(data))
            # Instead of uploading to Company hook, we save it to JSON so it can be processed
            # into DataFrame
            save_file_path = os.path.join(FOLDER_PATH_DATABASE, f"database_last_minute{customer_id}.json")
            with open(save_file_path, "w") as f:
                json.dump(data, f)
            print("Saved data to JSON.")

        else:
            url = WEBHOOK_URL
            headers = {
                "Content-Type": "application/json"
            }

        print("reach here!!!!")
        # response = requests.post(url, headers=headers, json=data, verify=False)
        date_format_save = datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d')
        with open(f"internal_logger_{date_format_save}.txt", 'a') as f:
            if len(data["forecasts"]) > 0:
                f.write("Predictive Pipeline ")
                f.write(f"Date: {datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
                f.write(f"Property ID: {customer_id}")
                f.write("\nStatus: SENT. DATA NOT BLANK.\n")
                print("Success saving status A.")
                print("ChartJS successfully sent!")
            else:
                f.write("Predictive Pipeline ")
                f.write(f"Date: {datetime.datetime.now(ZoneInfo('Asia/Makassar')).strftime('%Y-%m-%d %H:%M:%S')} ")
                f.write(f"Property ID: {customer_id}")
                f.write("\nStatus: ERROR OCCURED, DATA MIGHT NOT BE SENT.\n")
                print("Success saving status B.")
                if error_msg:
                    f.write(f"Error due to : {error_msg}")
                print("ChartJS successfully sent with NOTE")

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
        "result":[{
                "model_version": "v1.0.0",
                "customer_id": "",
                "currency_id": "",
                "forecasts": []
            }],
        "comprate_early_booking": [],
        "comprate_last_minute": []
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
                delta_days = data["data"]["predict_days"]
                job_id_num = data["job_identification"]
            # with open('total_room.txt', 'r') as file:
            #     content = file.read()
            #     content = int(content)
            # return customer_id, job_id_num, delta_days, content

            print("Let's check the total room number.")
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {API_KEY}"
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

            return customer_id, job_id_num, delta_days, total_room_number
        except FileNotFoundError as e:
            print(f"[FILE NOT FOUND] Empty incoming data!")
            error_summary = f"{type(e).__name__}: {e}"
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
            chartjs_to_endpoint(charts["result"][0], customer_id, error_msg=error_summary)
            traceback.print_exc()
            raise
        except Exception as e:
            print(f"[ERROR] Unexpected error while reading file cust_request.json or total_room.txt!")
            error_summary = f"{type(e).__name__}: {e}"
            charts["key_id"] = job_id_num
            charts["datetime_push"] = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
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
                print(f"df_temp is \n{df_tempor}\n")
                # print(f"df_temp shape is {df_tempor.shape}\n")
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
    main_df['is_confirmed'] = main_df['is_confirmed'].replace({'t': True, 'f': False})

    cancellation_df = main_df[main_df['is_confirmed'] == False]
    if len(main_df) > 0:
        cancellation_rate = len(cancellation_df) / len(main_df)
    else:
        cancellation_rate = 0
    currency_id_data = int(main_df['currency_id'].values[0])

    # no_net = []
    # for i in range(len(main_df['net_amount_stay'])):
    #   if main_df.iloc[i, 5] == 0:
    #       no_net.append(0)
    #   else:
    #       no_net.append(1)
    # main_df['net_amount_avail'] = no_net
    main_df['net_amount_avail'] = (main_df['net_amount_stay'] != 0).astype(int)
    
    main_df = main_df.loc[(main_df['lead_days'] >= 0) & 
                       (main_df['net_amount_avail'] == 1) &
                       (main_df['price_per_night'] <= 18000000) &
                       (main_df['net_amount_stay'] > 0) &
                       (main_df['ota_name'] != "Hotel Direct Booking"), :]
    return main_df, cancellation_rate, currency_id_data
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
#                                    mem_buffer_ckout, max_room_number, avail_percentage, cancel):
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
#             # print(f"[DEBUG] continuous resampling is: \n{resampling}\n")
#             count_occur_ckin = resampling.groupby('check_in')['check_in'].count()
#             count_occur_ckout = resampling.groupby('check_out')['check_out'].count()
#             # print(f"[DEBUG] continuous count_occur_ckin is: \n{count_occur_ckin}\n")
#             # print(f"[DEBUG] continuous count_occur_ckout is: \n{count_occur_ckout}\n")

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

#             if counter % 30 == 0:
#                 progress_calculation = (counter / delta_date) * 100
#                 print(f"Progress (Extension steps): {progress_calculation:.2f}%")
#                 print(f"Total rooms at day {mov_days} is {rooms_left}")
#             avail_occupancy = int((1-cancel) * (avail_percentage / 100) * max_room_number)
            
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
    #         # print(f"[DEBUG] resampling is: \n{resampling}\n")
    #         # print(f"[DEBUG] main dataframe is : \n{occ}\n")
    #         # print(f"[DEBUG] specific chek at booking_date 2025-03-25 : \n{occ[occ['booking_date'] == '2025-03-25']}\n")
    #         count_occur_ckin = resampling.groupby('check_in')['check_in'].count()
    #         count_occur_ckout = resampling.groupby('check_out')['check_out'].count()
    #         # print(f"[DEBUG] count_occur_ckin is: \n{count_occur_ckin}\n")
    #         # print(f"[DEBUG] count_occur_ckout is: \n{count_occur_ckout}\n")

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
    #         avail_occupancy = int((1-cancel) * (avail_percentage / 100) * avail_room)
            
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
    #                                                                     memory_buffer_ckout, avail_room, avail_percentage, cancel)
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
        lokapro_room_mapper = {}
        counter = 1

        for i in (sub_dfb['room_type_id'].value_counts().index):
            room_type_mapper[i] = counter

            # MAP BNL Room ID from value_counts() to lokapro room id and label
            # list is [lokapro_room_label, lokapro_room_id]
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
def comprate_correction(occ_rate, cust_name, master_lib, api_urls=FOLDER_PATH_COMPRATE, job_sched=2):
    #################### ----------- SUPPORTING FUNCTION ------------ ####################
    class ZeroDataError(Exception):
        pass

    def normalize_json_to_df(jsondata):
        with open(jsondata, "r") as f:
            data = json.load(f)  # Load entire JSON
        return data

    def percentage_calculation(comprate_df, lastmin_df, occ_rate, master_lib):
        average_val = []
        min_threshold = []

        percentage_res = pd.DataFrame()
        limit_res = pd.DataFrame()
        percentage_res['Date'] = comprate_df['Date']
        limit_res['Date'] = lastmin_df['Date']
        percentage_res['Date'] = pd.to_datetime(percentage_res['Date'])
        limit_res['Date'] = pd.to_datetime(limit_res['Date'])
        for i in range(1, len(comprate_df.columns)):
            calc_result = []
            delta_date = []
            for j in range(1, len(comprate_df)):
                date_calculation = percentage_res.iloc[j-1,0] - datetime.datetime.now()
                date_calculation = (date_calculation.days)
                if comprate_df.iloc[j-1,i] != 0:
                    delta_range = (comprate_df.iloc[j,i] - comprate_df.iloc[j-1,i]) / comprate_df.iloc[j-1,i]
                else:
                    delta_range = 0
                calc_result.append(delta_range)
                delta_date.append(date_calculation)
            calc_result.insert(0,0)
            date_calculation = percentage_res.iloc[j-1,0] - datetime.datetime.now() + timedelta(days=1)
            date_calculation = (date_calculation.days)
            delta_date.append(date_calculation)
            percentage_res[f"{comprate_df.columns[i]}_diff"] = calc_result
            limit_res[f"{comprate_df.columns[i]}_lead_days"] = delta_date

        for i in range(len(percentage_res)):
            min_pct = percentage_res.iloc[i, 1:].min()
            max_pct = percentage_res.iloc[i, 1:].max()
            if percentage_res.iloc[i, 0] in occ_rate["Dates"].values:
                if limit_res.iloc[i, 1] < 7: # lead days less than 7 days
                    print("Lead days less than 7 days.")
                    mid_point = (-master_lib[cust_name]["avail_percentage"]) + (100 - abs(master_lib[cust_name]["avail_percentage"])) / 2
                    if occ_rate[(occ_rate["Dates"] == percentage_res.iloc[i, 0]), "Occupancy Rate"] < mid_point: # check the occupancy pct less than half
                        calculation_avg = (min_pct + max_pct) / 2
                        average_val.append(calculation_avg)
                        min_threshold.append(0)
                    else:
                        # occupancy more than 50%, it's high demand so follow last minute price
                        average_val.append(0)
                        min_value = np.min(lastmin_df[(lastmin_df["Date"] == percentage_res.iloc[i, 0])].values)
                        min_threshold.append(min_value)
                else: # lead days more than 7 days follow averaged slope
                    print("More than 7 days.")
                    calculation_avg = (min_pct + max_pct) / 2
                    average_val.append(calculation_avg)
                    min_threshold.append(0)
            else:
                if percentage_res.iloc[i, 0] in lastmin_df["Date"].values:
                    min_value = np.min(lastmin_df[(lastmin_df["Date"] == percentage_res.iloc[i, 0])].values)
                else:
                    min_value = 0
                min_threshold.append(min_value)
                average_val.append(0)

        percentage_res['Average Value'] = average_val
        percentage_res["Min Value"] =  min_threshold
        percentage_res['Lead Days'] = limit_res[f"{comprate_df.columns[1]}_lead_days"].values # soalnya tanggalnya sama aja
        percentage_res['Date'] = pd.to_datetime(percentage_res['Date'])
        return percentage_res
    #################### ----------- END OF SUPPORTING FUNCTION ------------ ####################

    comprate_df = pd.DataFrame()
    lastmin_df = pd.DataFrame()
    try:
        name_dict = ["Date"]
        date_dict = []
        price_dict = []
        for filename in os.listdir(api_urls):
            if filename.lower().endswith("main_data_complete.json"):
                filename = os.path.join(api_urls, filename)
                df_temp = normalize_json_to_df(filename)

                for i in range(len(df_temp)):
                    name_dict.append(df_temp[i]['name'])
                    date_dict = [i for i in df_temp[i]['data'].keys()]
                    price_dict = [i for i in df_temp[i]['data'].values()]
                    temporary_df = pd.DataFrame({
                        'date': date_dict,
                        f'price{i}': price_dict
                    })
                    if i == 0:
                        comprate_df = temporary_df
                    else:
                        comprate_df = comprate_df.join(temporary_df.set_index('date'), on='date', how='outer')
        if comprate_df.shape == (0, 0):
            raise ZeroDataError("Received zero value, cannot continue processing")

        name_dict_lastmin = ["Date"]
        date_dict_lastmin = []
        price_dict_lastmin = []
        for filename in os.listdir(api_urls):
            if filename.lower().endswith("last_min_rate.json"):
                filename = os.path.join(api_urls, filename)
                df_temp = normalize_json_to_df(filename)

                for i in range(len(df_temp)):
                    name_dict_lastmin.append(df_temp[i]['name'])
                    date_dict_lastmin = [i for i in df_temp[i]['data'].keys()]
                    price_dict_lastmin = [i for i in df_temp[i]['data'].values()]
                    temporary_df = pd.DataFrame({
                        'date': date_dict_lastmin,
                        f'price{i}': price_dict_lastmin
                    })
                    if i == 0:
                        lastmin_df = temporary_df
                    else:
                        lastmin_df = lastmin_df.join(temporary_df.set_index('date'), on='date', how='outer')
        if lastmin_df.shape == (0, 0):
            raise ZeroDataError("Received zero value, cannot continue processing")

        print("Fetching success!!!")
    except ZeroDataError as e:
        error_summary = f"{type(e).__name__}: {e}"
        print(error_summary)
    comprate_df.columns = name_dict
    comprate_df = comprate_df.replace(0, np.nan).ffill()
    comprate_df = comprate_df.fillna(0)
    # percentage_valdf = percentage_calculation(comprate_df)

    lastmin_df.columns = name_dict_lastmin
    lastmin_df = lastmin_df.replace(0, np.nan).ffill()
    lastmin_df = lastmin_df.fillna(0)
    if job_sched == 1:
        return comprate_df, lastmin_df
    elif job_sched == 2:
        percentage_lm_valdf = percentage_calculation(comprate_df, lastmin_df, occ_rate, master_lib)
        # print(lastmin_df)
        return percentage_lm_valdf

import warnings
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
@task
def inference_correction_applicator(sub_dfa, customer_name, master_lib, aggregate,
                          buff_p, buffer_date, y_pred_master, booking_rt, pri_date, second_date, comprate_calc=None):
    national_holiday_constant = 1.025 # 2.5% increase for primary date can be adjusted
    local_holiday_constant = 1.015 # 1.5% increase for secondary date can be adjusted
    pri_date = [pd.Timestamp(iv) for iv in pri_date]
    pri_date = [iv.to_datetime64() for iv in pri_date]
    pri_date = [iv.astype('datetime64[D]') for iv in pri_date]

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
            if i[0] in aggregate.index:
                corr_price = i[1] * (1 + (alpha * (aggregate.loc[i[0]] / 100)))
            else:
                corr_price = i[1] * (1 + (alpha * 0))

            # if i[0] in comprate_calc['Date'].values:
            #     if (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values != 0) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values == 0):
            #         print("Adjusting competitor rate based on last minute but using standard pricing.")
            #         extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value']
            #         corr_price = corr_price * (1 + epsilon * extracted_pct)
            #     elif (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values == 0) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values != 0):
            #         print("Adjusting competitor rate based on last minute but using lowest rate pricing.")
            #         if corr_price <= comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values:
            #             corr_price = comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values
            #         else:
            #             corr_price = corr_price
            #     else:
            #         print("Adjusting competitor rate using lowest standard pricing.")
            #         extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value'].values
            #         corr_price = corr_price * (1 + epsilon * extracted_pct)
            #         # print(f"Competitor rate corrected price at date {i[0]}, with percentage {extracted_pct}%")

            if i[0] in booking_rt['check_in'].values:
                extracted_brate = float(booking_rt.loc[(booking_rt['check_in'] == i[0]), 'booking_rate'].values)
                corr_price = corr_price * (1 + (zeta * extracted_brate))

            if np.datetime64(i[0]).astype('datetime64[D]') in pri_date:
                corr_price = corr_price * national_holiday_constant
                print(f"Applied national holiday correction for date {i[0]}")
            if np.datetime64(i[0]).astype('datetime64[D]') in second_date:
                corr_price = corr_price * local_holiday_constant
                print(f"Applied local holiday correction for date {i[0]}")
  
            if i[0] in buff_p['Dates'].values:
                corr_price =  corr_price * ((1 + (beta * buff_p.loc[(buff_p['Dates'] == i[0]), 'Occupancy Rate'])).tolist()[0])
            
            preview_seasonal_a = seasonal_correction(sub_dfa, min_date, mode="mean")
            lower_bound = preview_seasonal_a.loc[(pd.to_datetime(preview_seasonal_a['Dates']) <= (i[0] - pd.Timedelta(days=365))), :]
            # lower_bound = lower_bound[pd.notna(lower_bound['Pct_Change'])].reset_index(drop=True)
            lower_bound = lower_bound.fillna(0).reset_index(drop=True)
            lower_focus = lower_bound.iloc[-1:, :]
            if len(lower_focus['Pct_Change']) > 0:
                if abs(lower_focus['Pct_Change'].values) < 1000:
                    corr_price = corr_price * (1 + (gamma * lower_focus['Pct_Change'].values)[0])
                else:
                    if lower_focus['Pct_Change'].values > 0:
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
            if i[0] in aggregate.index:
                corr_price = i[1] * (1 + (alpha * (aggregate.loc[i[0]] / 100)))
            else:
                corr_price = i[1] * (1 + (alpha * 0))

            # if i[0] in comprate_calc['Date'].values:
            #     if (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values != 0) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values == 0):
            #         print("Adjusting competitor rate based on last minute but using standard pricing.")
            #         extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value']
            #         corr_price = corr_price * (1 + epsilon * extracted_pct)
            #     elif (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values == 0) and (
            #         comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values != 0):
            #         print("Adjusting competitor rate based on last minute but using lowest rate pricing.")
            #         if corr_price <= comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values:
            #             corr_price = comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values
            #         else:
            #             corr_price = corr_price
            #     else:
            #         print("Adjusting competitor rate using lowest standard pricing.")
            #         extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value'].values
            #         corr_price = corr_price * (1 + epsilon * extracted_pct)
            #         # print(f"Competitor rate corrected price at date {i[0]}, with percentage {extracted_pct}%")

            if i[0] in booking_rt['check_in'].values:
                extracted_brate = float(booking_rt.loc[(booking_rt['check_in'] == i[0]), 'booking_rate'].iloc[0])
                corr_price = corr_price * (1 + (zeta * extracted_brate))

            if i[0] in buff_p['Dates'].values:
                corr_price =  corr_price * ((1 + (beta * buff_p.loc[(buff_p['Dates'] == i[0]), 'Occupancy Rate'])).tolist()[0])
            preview_seasonal_a = seasonal_correction(sub_dfa, min_date, mode="mean")
            lower_bound = preview_seasonal_a.loc[(preview_seasonal_a['Dates'] <= (i[0] - timedelta(days=365)).strftime('%Y-%m-%d')), :]
            # lower_bound = lower_bound[pd.notna(lower_bound['Pct_Change'])].reset_index(drop=True)
            lower_bound = lower_bound.fillna(0).reset_index(drop=True)
            lower_focus = lower_bound.iloc[-1:, :]
            if len(lower_focus['Pct_Change']) > 0:
                if abs(lower_focus['Pct_Change'].values) < 1000:
                    corr_price = corr_price * (1 + (gamma * lower_focus['Pct_Change'].values)[0])
                else:
                    if lower_focus['Pct_Change'].values > 0:
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
def comprate_display(occ_rate, cust_name, master_lib, api_urls=FOLDER_PATH_COMPRATE):
    placeholder_df, placeholder_lm_df = comprate_correction(occ_rate, cust_name, master_lib, api_urls, job_sched=1)
    placeholder_df.columns = [col.replace(" ", "_") for col in placeholder_df.columns]
    placeholder_df.columns = [col.replace("_diff", "") for col in placeholder_df.columns]
    placeholder_df['Date'] = pd.to_datetime(placeholder_df['Date']).dt.strftime("%Y-%m-%d")

    placeholder_lm_df.columns = [col.replace(" ", "_") for col in placeholder_lm_df.columns]
    placeholder_lm_df.columns = [col.replace("_diff", "") for col in placeholder_lm_df.columns]
    placeholder_lm_df['Date'] = pd.to_datetime(placeholder_lm_df['Date']).dt.strftime("%Y-%m-%d")

    comprate_box = []
    comprate_box_lm = []
    comprate_json = {
        "name": "",
        "list_rate": []
    }
    for i in range(1, len(placeholder_df.columns)):
        if (placeholder_df.columns.values[i] == 'Average_Value') or (placeholder_df.columns.values[i] == 'Min_Value') or (
            placeholder_df.columns.values[i] == 'Lead_Days'):
            continue
        else:
            placeholder_dict = comprate_json.copy()
            placeholder_dict["name"] = placeholder_df.columns.values[i]
            rate_array = []
            for j in range(len(placeholder_df[placeholder_df.columns.values[i]])):
                sub_file_comprate = {
                    "date": placeholder_df.iloc[j, 0],
                    "value": int(placeholder_df.iloc[j, i])
                }
                rate_array.append(sub_file_comprate)
            placeholder_dict["list_rate"] = rate_array
            comprate_box.append(placeholder_dict)

    for i in range(1, len(placeholder_lm_df.columns)):
        if (placeholder_lm_df.columns.values[i] == 'Average_Value') or (placeholder_lm_df.columns.values[i] == 'Min_Value') or (
            placeholder_lm_df.columns.values[i] == 'Lead_Days'):
            continue
        else:
            placeholder_dict = comprate_json.copy()
            placeholder_dict["name"] = placeholder_lm_df.columns.values[i]
            rate_array = []
            for j in range(len(placeholder_lm_df[placeholder_lm_df.columns.values[i]])):
                sub_file_comprate = {
                    "date": placeholder_lm_df.iloc[j, 0],
                    "value": int(placeholder_lm_df.iloc[j, i])
                }
                rate_array.append(sub_file_comprate)
            placeholder_dict["list_rate"] = rate_array
            comprate_box_lm.append(placeholder_dict)
    return comprate_box, comprate_box_lm

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
        occ_data_buffer_infer, _ = occupancy_rate_correction(segment_n, avail_room, avail_percentage, cancel)
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

def property_holiday_match(customer_id):
    with open("converted_cust_list.json", "r") as f:
        json_file = json.load(f)

    if str(customer_id) in json_file:
        if json_file[str(customer_id)]["in_Bali"] == "In Bali":
            with open("JSON/holiday_summary.json", "r") as f:
                national_holidays = json.load(f)
            with open("JSON/extra_events.json", "r") as f:
                extra_bali_events = json.load(f)
            with open("JSON/religious_events.json", "r") as f:
                religious_events = json.load(f)
            local_events_combined = sorted(set(extra_bali_events + religious_events))
            return national_holidays, local_events_combined
            
        else:
            with open("JSON/holiday_summary.json", "r") as f:
                national_holidays = json.load(f)
            return national_holidays, []
    else:
        print(f"Customer ID {customer_id} not found in data.\n Returning with default National Holidays.")
        with open("JSON/holiday_summary.json", "r") as f:
            national_holidays = json.load(f)
        return national_holidays, []

def adaptive_correction(room_type, customer_id_num):
    print("Starting adaptive correction fetcher.")
    adaptive_dat = {
        "type": "line-and-scatter",
        "chart_slug_name" : "abnormal-market-activities",
        "Data": []
    }
    adaptive_dat_copy = adaptive_dat.copy()
    full_path_suggestions = os.path.join(FOLDER_PATH_ADAPTIVE, f"results_{customer_id_num}.pkl")
    print("Checking if there's any adaptive correction available.")
    if os.path.exists(full_path_suggestions):
        print("Correction data found.")
        with open(full_path_suggestions, "rb") as x:
            data_pkl = pickle.load(x)
            if room_type < len(data_pkl["result"]) + 1: #because room type is in numerical
                extracted_data = data_pkl["result"][room_type-1]

                adaptive_df = pd.DataFrame({
                    "date_data": [extracted_data["Data"][d]["Date"] for d in range(len(extracted_data["Data"]))],
                    "price_baseline": [extracted_data["Data"][d]["Price Baseline"] for d in range(len(extracted_data["Data"]))],
                    "recommended_price": [extracted_data["Data"][d]["Recommended Price"] for d in range(len(extracted_data["Data"]))],
                    "out_of_limit": [extracted_data["Data"][d]["Out of limit"] for d in range(len(extracted_data["Data"]))],
                    "rate_change": [extracted_data["Data"][d]["Rate Change"] for d in range(len(extracted_data["Data"]))],
                    "remarks": [extracted_data["Data"][d]["Remarks"] for d in range(len(extracted_data["Data"]))]
                })
            else:
                print(f"Data {room_type} not found, perhaps update needed by adaptive pipeline!")
                extracted_data = {
                    "x-axis": [],
                    "Price Baseline": [],
                    "Recommended Price": [],
                    "Data": []
                }
       
        print(f"length of extracted data is: {len(extracted_data['Data'])}")
        if len(extracted_data["Data"]) > 0:
            print("Adaptive correction data found, processing...")
            return adaptive_df
        #     adaptive_df["date_data"] = pd.to_datetime(adaptive_df["date_data"])
        #     adaptive_df = adaptive_df.loc[(adaptive_df["date_data"] >= max_date), :]
        #     adaptive_dat_copy["x-axis"] = adaptive_df["date_data"].values.strftime('%Y-%m-%d')
        #     for iii in range(len(adaptive_df)):
        #         sub_process_dict = {
        #             "Date": np.datetime_as_string(adaptive_df["date_data"].values[iii], unit="D"),
        #             "Price Baseline": float(adaptive_df["price_baseline"].values[iii]),
        #             "Recommended Price": float(adaptive_df["recommended_price"].values[iii]),
        #             "Out of Limit": bool(adaptive_df["out_of_limit"].values[iii])
        #         }
        #         adaptive_dat_copy["Data"].append(sub_process_dict)            
        #     adaptive_dat_copy["x-axis"] = adaptive_df["date_data"].dt.strftime("%Y-%m-%d").tolist()
        #     adaptive_dat_copy["baseline_price"] = adaptive_df["price_baseline"].values.tolist()
        #     adaptive_dat_copy["adapted_price"] = adaptive_df["recommended_price"].values.tolist()
        #     adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."
        else:
            print("No adaptive correction data available after processing.")
            return pd.DataFrame({}) # return empty dataframe
        #     print("No correction/abnormalities detected.")
        #     adaptive_dat_copy["x-axis"] = []
        #     adaptive_dat_copy["baseline_price"] = []
        #     adaptive_dat_copy["adapted_price"] = []
        #     adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."
    else:
        print("Adaptive correction data not found.")
        return pd.DataFrame({}) # return empty dataframe
        # print("Correction data not found.")
        # adaptive_dat_copy["x-axis"] = []
        # adaptive_dat_copy["baseline_price"] = []
        # adaptive_dat_copy["adapted_price"] = []
        # adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."

def get_parameters(customer_id):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    print("\nRequesting property constants by user...")
    try:
        response = requests.get(CONSTANTS_BY_USER, headers=headers)
        response.raise_for_status()  # Raises HTTPError for bad status codes  
    except requests.exceptions.Timeout:
        raise RuntimeError("Request timed out. The server may be slow or unavailable.")
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(f"HTTP error occurred: {e} - Response: {response.text}")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")

    constant_data = response.json()
    # print(f"response is : {constant_data}")
    cust_def_const = False

    for i in range(len(constant_data["data"])):
        print(f"processing : {constant_data['data'][i]['customer_id']}")
        if constant_data["data"][i]["customer_id"] == customer_id:
            print("found")
            _high_pos = constant_data["data"][i]["high_season_positive_multiplier_rate"]
            _all_pos = constant_data["data"][i]["all_season_positive_multiplier_rate"]
            _all_neg = constant_data["data"][i]["all_season_negative_multiplier_rate"]
            _high_neg = constant_data["data"][i]["high_season_negative_multiplier_rate"]
            cust_def_const = False # NOT ACTIVE FOR NOW
            break

    if cust_def_const:
        print(f"[DEBUG] _high_pos is : {_high_pos}, _all_pos is : {_all_pos}")
        print(f"[DEBUG] _high_neg is : {_high_neg}, _all_neg is : {_all_neg}")
        return _high_pos, _all_pos, _all_neg, _high_neg, cust_def_const
    else:
        print("NOTHING FOUND")
        return None, None, None, None, cust_def_const

@task 
def xgb_active(occ_data_args, ckin_data_args, ts_month_args, algo_df, pred_test):
    date_source = ts_month_args[-len(pred_test):].index
    date_a = occ_data_args['Dates'].dt.strftime("%Y-%m-%d").values
    date_b = ckin_data_args['check_in'].dt.strftime("%Y-%m-%d").values

    print(f"ckin_data_args is: \n{ckin_data_args}")
    aggregated_ckin_pickup_rates = ckin_data_args.groupby('check_in')['booking_rate'].last().rename(index=lambda x: x.strftime("%Y-%m-%d"))
    date_select = []
    occ_rate = []
    pu_rate = []
    price_rate_list = []
    source_length = 0

    if len(date_a) > len(date_b):
        print("Step one selected.")
        source_length = len(date_a)
        for i in range(source_length):
            if date_a[i] in date_b and date_a[i] in date_source:
                date_select.append(date_a[i])
                # Extract scalar from numpy array returned by .values
                occ_rate.append(float(occ_data_args.loc[occ_data_args['Dates'].dt.strftime("%Y-%m-%d") == date_a[i], 'Occupancy Rate'].values[0]))
                # Lookup in the pre-aggregated series
                if date_a[i] in aggregated_ckin_pickup_rates.index:
                    pu_rate.append(float(aggregated_ckin_pickup_rates.loc[date_a[i]]))
                else:
                    pu_rate.append(0.0) # Default if no pickup rate found for the date
                price_rate_list.append(algo_df.loc[algo_df['check_in'].dt.strftime("%Y-%m-%d") == date_a[i], 'price_per_night'].values.mean())
    else:
        print("Step two selected.")
        source_length = len(date_b)
        for i in range(source_length):
            if date_b[i] in date_a and date_b[i] in date_source:
                date_select.append(date_b[i])
                # Extract scalar from numpy array returned by .values
                occ_rate.append(float(occ_data_args.loc[occ_data_args['Dates'].dt.strftime("%Y-%m-%d") == date_b[i], 'Occupancy Rate'].values[0]))
                # Lookup in the pre-aggregated series
                if date_b[i] in aggregated_ckin_pickup_rates.index:
                    pu_rate.append(float(aggregated_ckin_pickup_rates.loc[date_b[i]]))
                else:
                    pu_rate.append(0.0) # Default if no pickup rate found for the date
                price_rate_list.append(algo_df.loc[algo_df['check_in'].dt.strftime("%Y-%m-%d") == date_b[i], 'price_per_night'].values.mean())

    experiment_df = pd.DataFrame({
        "date": date_select,
        "occupancy_rate": occ_rate,
        "booking_rate": pu_rate,
        "price_per_night": price_rate_list
    })
    experiment_df.drop_duplicates(inplace=True)
    experiment_df = experiment_df.sort_values(by='date', ascending=True)
    return experiment_df

@task
def inference_xgboost(xgboost_mdl, buffer_date, y_pred_master, occ_data_args, ckin_data_args, pri_date, second_date):
    try:
        national_holiday_constant = 1.025 # 2.5% increase for primary date can be adjusted
        local_holiday_constant = 1.015 # 1.5% increase for secondary date can be adjusted
        pri_date = [pd.Timestamp(iv) for iv in pri_date]
        pri_date = [iv.to_datetime64() for iv in pri_date]
        pri_date = [iv.astype('datetime64[D]') for iv in pri_date]

        pairing = zip(buffer_date.values[-len(y_pred_master):], y_pred_master)
        date_a = occ_data_args['Dates'].dt.strftime("%Y-%m-%d").values
        date_b = ckin_data_args['check_in'].dt.strftime("%Y-%m-%d").values

        aggregated_ckin_pickup_rates = ckin_data_args.groupby('check_in')['booking_rate'].last().rename(index=lambda x: x.strftime("%Y-%m-%d"))
        caged = {}
        date_select = []
        occ_rate = []
        pu_rate = []
        # pred_res_list = []
        
        # MAKE DATAFRAME FIRST TO AGREGATE THE OCCUPANCY RATE AND PICKUP RATE ON PREDICTION DATE 
        for i in pairing:
            dt64 = np.datetime64(i[0])
            date_str = str(dt64.astype('datetime64[D]'))
            if date_str in date_a and date_str in date_b:
                obtained_occ_rate = occ_data_args.loc[occ_data_args['Dates'].dt.strftime("%Y-%m-%d") == date_str, 'Occupancy Rate'].values
                obtained_pu_rate = aggregated_ckin_pickup_rates.loc[date_str]
                date_select.append(date_str)
                occ_rate.append(obtained_occ_rate)
                pu_rate.append(obtained_pu_rate)
                # pred_res_list.append(i[1])
            else:
                date_select.append(date_str)
                occ_rate.append(0.0)
                pu_rate.append(0.0)

        aggregate_exp_df = pd.DataFrame({
            "date": date_select,
            "occupancy_rate": occ_rate,
            "booking_rate": pu_rate,
            # "Predicted Value": pred_res_list
        })
        y_pred_master = [i[0] for i in y_pred_master]

        # PREDICT THE RESIDUAL TARGET WITH XGBOOST
        seq2seq_buffer = pd.Series(data=y_pred_master, index=buffer_date[-len(y_pred_master):].values, name='seq2seq_results')
        xgboost_pred = xgboost_mdl.predict(aggregate_exp_df, seq2seq_buffer)

        # APPLY ADDITIONAL CORRECTION
        for i in range(len(xgboost_pred)):
            select_row = xgboost_pred.iloc[i]
            select_date = select_row['date']
            select_value = select_row['predicted_price']
            if select_date in pri_date:
                select_value = select_value * national_holiday_constant
                print(f"Applied national holiday correction for date {select_date}")
            if select_date in second_date:
                select_value = select_value * local_holiday_constant
                print(f"Applied local holiday correction for date {select_date}")
            else:
                select_value = select_value
            caged[select_date] = select_value
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

        # if i[0] in comp_rate_placeholder['Date'].values:
        #     extracted_pct = comp_rate_placeholder.loc[(comp_rate_placeholder['Date'] == i[0]), 'Average Value']
        #     if not extracted_pct.empty:
        #         colected_vals_5.append(float(extracted_pct.item()))
        #     else:
        #         colected_vals_5.append(0.0)
        # else:
        #     colected_vals_5.append(0.0)

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
            # + w["comp"] * factors["comp"]
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
            # "comp": trial.suggest_float("comprate_weight",-0.001, 0.001),
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
            # "comp": data_property["competitor_rate"],
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
            # "comp": study.best_params["comprate_weight"],
            "bookrt": study.best_params["bookrate_weight"]
        }
        return optimal_weights

    data_property = {
            "actual_price_values": ts_monthly.values[-len(y_pred_mean):], # Corrected: use values instead of index
            "actual_occupancy": np.array(colected_vals), #alpha aggregated_ckin
            "occupancy_rate": np.array(colected_vals_2), #buffer_pred_debug
            "seasonal_factor": np.array(colected_vals_3),
            "bias_adjust": np.array(colected_vals_4),
            # "competitor_rate": np.array(colected_vals_5),
            "booking_rate": np.array(colected_vals_6)
    }
    optimal_weights = optimize_constants_for_property(data_property)
    return optimal_weights

# ============================================= END SECTION  ===============================================

###################################################################
######--------------PREDICTION ALGORITHM---------------------######
###################################################################
@task
def load_constants(cust_name): 
    if not os.path.exists("constants_list.json"):
        print(f"WARNING: constants data not found.")
        return {}
    else:
        with open("constants_list.json", "r") as f:
            data = json.load(f)
            constant_return = data[cust_name]
            print(constant_return)
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
                         correction_active=True, optuna_active=True, adaptive_standby=True, currency_info=None):
    loaded_model = model
    # debug_model = model
    forecast_horizon = 7
    customer_id_num, joblib_id, delta_days, total_room = load_id() 
    # customer_id_num, joblib_id, delta_days = load_id() 
    start_search = str(df_input['booking_date'].min())
    end_search = str(df_input['booking_date'].max())
    MAX_FUTURE = delta_days
    counter_roomtype = False
    date_aggregator = []
    # MAX_FUTURE = 30 

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
        "key_id":joblib_id,
        "datetime_push":"",
        "status_code":"",
        "status_message":"",
        "date_start":start_search,
        "date_end":end_search,
        "result":{
                "model_version": "v1.0.0",
                "customer_id": customer_id_num,
                "currency_id": currency_info,
                "forecasts": []
            },
        "comprate_early_booking": [],
        "comprate_last_minute": []
    }
    try:
        print(f"===========PROCESSING CUSTOMER {customer_id_num}================")
        only_once_active = True
        print("Extracting necessary constants library.")
        master_lib = load_constants("reserved_for_test")
        master_lib["total_room"] = total_room
        # master_lib["total_room"] = 200
        sub_df, n_cluster = segmentation_step(df_input, room_type_avail)

        sub_details_dat = {}
        upper_sub_dat = []
        print(f"To be processed: {n_cluster} segment.")
        for n in range(1, n_cluster + 1):
            print(f"processing cluster no {n}")
            segment_n = sub_df[sub_df['cluster'] == n]
            # print(f"with shape: {segment_n.shape}")
            # print(f"segment_n check: \n{segment_n.head(50)}")
            # print(f"segment_n further check: \n{segment_n.tail(50)}")
            will_be_filter = distribution_shift_adjust(segment_n)
            segment_n_check = segment_n[~segment_n['ota_name'].isin(will_be_filter)]
            if len(segment_n_check) > 0:
                    segment_n = segment_n_check
            else:
                print("Cleanup data resulting in small dataset, switching to auto-fill.")
            segment_n = capped_outlier_fx(segment_n, 'price_per_night')
            # print(f"segment_n check: \n{segment_n.head(50)}")
            # print(f"segment_n further check: \n{segment_n.tail(50)}")
            # starting_date = segment_n['booking_date'].max() - timedelta(days=365)
            starting_date = segment_n['booking_date'].min()
            algo_df = segment_n[segment_n['booking_date'] >= starting_date]
            # max_booking_date = segment_n['booking_date'].max()
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
            # ts_monthly = ts.resample('D').mean()
            # ts_monthly = ts_monthly.dropna()

            # Strategy 1: Fit LOWESS on raw irregular timestamps
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

            # upper_sub_dat = []
            # adaptive_sub_dat = []
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

                # FOR DEBUG ONLY, IN INFERENCE STEP THERE SHOULD BE NO VAL, NOR TEST STEP
                # IN INFERENCE STEP, WE WANT THE MODEL LEARNS UNTILL ALL THE END OF PERIODS 
                # FORECAST THE UNKNOWN DATA IN THE FUTURE
                # split train into 85% train, 15% validation
                # n_train = len(X_train)
                # val_size = int(n_train * 0.15)

                # X_val, X_train = X_train[-val_size:], X_train[:-val_size]
                # y_val, y_train = y_train[-val_size:], y_train[:-val_size]

                def make_decoder_input(y):
                    start_token = np.zeros_like(y[:, :1, :])  # shape (batch, 1, 1)
                    return np.concatenate([start_token, y[:, :-1, :]], axis=1)

                X_decoder_train = make_decoder_input(y_train).astype(np.float32)
                # X_decoder_val   = make_decoder_input(y_val)
                X_decoder_test  = make_decoder_input(y_test).astype(np.float32)
                X_decoder  = make_decoder_input(y).astype(np.float32)
                print("Train:", X_train.shape, y_train.shape)
                # print("Val:  ", X_val.shape, y_val.shape)
                print("Test: ", X_test.shape, y_test.shape)
                print("Main X is: ", X.shape)

                print("decoder_train:", X_decoder_train.shape)
                # print("validation_train:  ", X_decoder_val.shape)
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
                    occ_data_buffer, _ = occupancy_rate_correction(algo_df, avail_room, avail_percentage, cancellation_number)
                    ckin_data_buffer = pickup_rate_correction(algo_df)
                    buffer_pred_debug = occ_data_buffer[(occ_data_buffer['Dates'] >= ts_monthly.index[-len(y_pred_mean):].min()) &
                                (occ_data_buffer['Dates'] <= ts_monthly.index[-len(y_pred_mean):].max())]
                    # comprate_factor = comprate_correction(occ_rate=buffer_pred_debug, cust_name=j, master_lib=master_lib, job_sched=2)
                    aggregated_ckin = ckin_data_buffer.groupby('check_in')['cumulative_pickup_rate'].max()
                    aggregated_ckin.resample('D').max()
                    booking_rate = ckin_data_buffer.groupby('check_in')['booking_rate'].last()
                    booking_rate.resample('D').last()
                    booking_rate = booking_rate.reset_index(drop=False)
                    booking_rate['check_in'] = pd.to_datetime(booking_rate['check_in'])

                    result_caged_debug = correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred_debug,
                                                        ts_monthly, y_pred_mean, booking_rate)
                    custom_error_mae = mean_absolute_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    custom_error_mape = mean_absolute_percentage_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    print(f'This model has performance with mape: {100 * custom_error_mape:.2f} %')
                    print(f'This model has performance with mae: {custom_error_mae}')
                    print('Checking performance with XGBoost')
                    print('[NOTES] This is an experimental version! \nIf MAPE less than 12%, it will replace Optuna.')
                    experimental_xgb_df = xgb_active(occ_data_buffer, ckin_data_buffer, ts_monthly, algo_df, pred_test=y_pred_mean)
                    date_source = ts_monthly[-len(pred_test):].index
                    seq2seq_series = pd.Series(y_pred_mean, index=date_source, name='price_per_night')
                    model_xgb_eperiments = HotelResidualForecaster()
                    print(f"Check experimental df first: \n{experimental_xgb_df}")
                    print(f"Check seq_2seq series first: \n{seq2seq_series}")
                    model_xgb_eperiments.fit(experimental_xgb_df, seq2seq_series)
                    if model_xgb_eperiments.mode == "seq2seq_only":
                        optuna_active = True
                    else:
                        optuna_active = False

                if optuna_active == True:
                    print("Optuna algorithm is active.")
                    corrections = optuna_algorithm(segment_n, ts_monthly, y_pred_mean,
                                                    aggregated_ckin, buffer_pred_debug, booking_rate)
                    pointer = 0
                    for k, v in corrections.items():
                        master_lib["corr_constant"][pointer] = v
                        pointer += 1
                    result_caged_debug = correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred_debug,
                                                        ts_monthly, y_pred_mean, booking_rate)
                    print(f"Optuna correction has been applied, the latest performance result is: ")
                    custom_error_mae = mean_absolute_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    custom_error_mape = mean_absolute_percentage_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                    print(f'This model has performance with mape: {100 * custom_error_mape:.2f} %')
                    print(f'This model has performance with mae: {custom_error_mae}')
                else:
                    print("Optuna algorithm is not active, replaced by XGBoost!")

                # debug_aa_dictionaries = feeder_adaptive_algorithm(cancellation_number, dates_buffer=dates_buffer, y_pred_mean=y_pred_mean, 
                #                                                   y_test_mean=y_test_mean, ckin_data_buffer=ckin_data_buffer, 
                #                                                   booking_rate=booking_rate, occ_data_buffer=occ_data_buffer, job_sched=1, n=n)  
                
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

                # future_pred_scaled = []
                # for _ in range(0, (MAX_FUTURE + offset_time), STEP_AHEAD):
                #     pred_scaled = loaded_model.predict([last_window, dec_input], verbose=0)  # (1, 5)
                #     pred_scaled = pred_scaled.reshape(1, STEP_AHEAD, N_FEATURES)
                #     future_pred_scaled.append(pred_scaled.squeeze())
                #     # Extend encoder window with new predictions 
                #     last_window = np.concatenate([last_window[:, STEP_AHEAD:, :], pred_scaled], axis=1)
                #     # Decoder input becomes the latest predicted segment
                #     dec_input = pred_scaled

                # future_pred_scaled = np.concatenate(future_pred_scaled, axis=0).reshape(-1, 1)  # shape (30, 1)
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

                # mod_date = ts_monthly.index.max()
                mod_date = datetime.datetime.now()
                max_date = mod_date + timedelta(days=(MAX_FUTURE))
                curr_date = mod_date

                buffer_box = []
                while(curr_date <= max_date):
                    curr_date = curr_date + timedelta(days=1)
                    buffer_box.append(curr_date)
                buffer_date = ts_monthly.index.union(buffer_box)
                buffer_date = pd.to_datetime(buffer_date, format="%Y-%m-%d")
                future_pred = future_pred[-len(buffer_box):]
                # buffer_date = buffer_date.tolist()
                buffer_date = pd.Series(buffer_date)

                if correction_active == True:
                    avail_room = master_lib['total_room']
                    avail_percentage = master_lib['avail_percentage']
                    # occ_data_buffer, _ = occupancy_rate_correction(algo_df, avail_room, avail_percentage, cancellation_number)
                    # ckin_data_buffer = pickup_rate_correction(algo_df)
                    buffer_pred = occ_data_buffer[(occ_data_buffer['Dates'] >= buffer_date.values.min()) &
                                (occ_data_buffer['Dates'] <= buffer_date.values.max())]
                    # comprate_factor = comprate_correction(occ_rate=buffer_pred, cust_name=j, master_lib=master_lib, job_sched=2)
                    # aggregated_ckin = ckin_data_buffer.groupby('check_in')['cumulative_pickup_rate'].max()
                    # aggregated_ckin.resample('D').max()
                    booking_rate = ckin_data_buffer.groupby('check_in')['booking_rate'].last()
                    booking_rate.resample('D').last()
                    booking_rate = booking_rate.reset_index(drop=False)
                    booking_rate['check_in'] = pd.to_datetime(booking_rate['check_in'])

                    primary_date, secondary_date = property_holiday_match(customer_id_num)
                    if len(primary_date) > 0:
                        # convert strings inside array to datetime that can be processed by inference_correction_applicator function
                        primary_date = [pd.to_datetime(date_str) for date_str in primary_date]
                    if len(secondary_date) > 0:
                        secondary_date = [pd.to_datetime(date_str) for date_str in secondary_date]

                    if optuna_active == True:
                        result_caged = inference_correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred, 
                                                            buffer_date, future_pred, booking_rate, primary_date, secondary_date)
                    else:
                        print("Inference using XGBoost algorithm.")
                        result_caged = inference_xgboost(model_xgb_eperiments, buffer_date, future_pred, 
                                                        occ_data_buffer, ckin_data_buffer, primary_date, secondary_date)


                    print(f"type of buffer_date: {type(buffer_date.values[-len(future_pred):])}")
                    # sub_dat = {
                    #     "type": "line_chart",
                    #     "chart_slug_name":"forecast_result",
                    #     "pred_res":[int(i[0]) for i in result_caged.values],
                    #     "baseline_pred":future_pred.flatten().tolist(),
                    #     "x_axis":pd.to_datetime(buffer_date.values[-len(future_pred):]).strftime('%Y-%m-%d').tolist(),
                    #     "mape":f"{100 * custom_error_mape:.2f} %",
                    #     "mae":custom_error_mae,
                    #     "description": "Hasil prediksi selama rentang waktu yang dipilih. Garis merah menunjukkan koreksi dynamic pricing."
                    # }

                    if adaptive_standby == True:
                        adaptive_df_compare = adaptive_correction(n, customer_id_num)
                    else:
                        adaptive_df_compare = pd.DataFrame({})
                    
                    if optuna_active == True:
                        sub_dat_tempo = pd.DataFrame({
                            "pred_res":[int(i[0]) for i in result_caged.values],
                            "baseline_pred":future_pred.flatten().tolist(),
                            "x_axis": pd.to_datetime(buffer_date.values[-len(future_pred):]).date
                        })
                    else:
                        sub_dat_tempo = pd.DataFrame({
                            "pred_res":[int(i) for i in result_caged.values],
                            "baseline_pred":future_pred.flatten().tolist(),
                            "x_axis": pd.to_datetime(buffer_date.values[-len(future_pred):]).date
                        })

                    # date_aggregator.append(sub_dat_tempo["x_axis"].values)
                    date_aggregator.extend(sub_dat_tempo["x_axis"])
                    # clean out duplicate date in date_aggregator then sort
                    date_aggregator = sorted(set(date_aggregator))
                    
                    # sub_process_dict = {
                    #     "room_type_id": "",
                    #     "room_type_name": "",
                    #     "forecast_date": "",
                    #     "forecasted_price": "",
                    #     "high_season_positive_multiplier_rate": "",
                    #     "all_season_positive_multiplier_rate": "",
                    #     "high_season_negative_multiplier_rate": "",
                    #     "all_season_negative_multiplier_rate": "",
                    #     "all_room_types_min_forecasted_price": "" ,
                    #     "all_room_types_median_forecasted_price": "",
                    #     "all_room_types_max_forecasted_price": ""
                    # }

                    sub_process_dict = {
                        "property_id": int,
                        "room_type_id": int,
                        "forecast_date": datetime,
                        "forecasted_price": int,
                        "corrected_price": int
                    }

                    # current_constant_usage = {
                    #     "customer_id": customer_id_num,
                    #     "high_season_positive_multiplier_rate": "",
                    #     "all_season_positive_multiplier_rate": "",
                    #     "high_season_negative_multiplier_rate": "",
                    #     "all_season_negative_multiplier_rate": ""
                    # }
                    if not adaptive_df_compare.empty:
                        adaptive_df_compare['date_data'] = pd.to_datetime(adaptive_df_compare['date_data']).dt.date

                    # high_pos, all_pos, all_neg, high_neg, cust_def_avail = get_parameters(customer_id_num)

                    for iii in range(len(sub_dat_tempo)):
                        sub_process_dict_copy = sub_process_dict.copy()
                        # if room_type_avail == False:
                        #     sub_process_dict_copy["forecast_date"] = sub_dat_tempo["x_axis"].values[iii]
                        # else:
                        #     sub_process_dict_copy["forecast_date"] = str(sub_dat_tempo["x_axis"].values[iii])
                        sub_process_dict_copy["forecast_date"] = sub_dat_tempo["x_axis"].values[iii].strftime("%Y-%m-%d %H:%M:%S")
                        sub_process_dict_copy["property_id"] = customer_id_num

                        if room_type_avail == True:
                            sub_process_dict_copy["room_type_id"] = int(algo_df['lpro_room_numid'].values[0])
                            # sub_process_dict_copy["room_type_name"] = algo_df['lpro_room_name'].values[0]

                        # if cust_def_avail:
                        #     sub_process_dict_copy["high_season_positive_multiplier_rate"] = high_pos
                        #     sub_process_dict_copy["all_season_positive_multiplier_rate"] = all_pos
                        #     sub_process_dict_copy["high_season_negative_multiplier_rate"] = high_neg
                        #     sub_process_dict_copy["all_season_negative_multiplier_rate"] = all_neg
                        # else:
                        #     sub_process_dict_copy["high_season_positive_multiplier_rate"] = 0
                        #     sub_process_dict_copy["all_season_positive_multiplier_rate"] = 0
                        #     sub_process_dict_copy["high_season_negative_multiplier_rate"] = 0
                        #     sub_process_dict_copy["all_season_negative_multiplier_rate"] = 0

                        if not adaptive_df_compare.empty:
                            # print(f"sub_dat_tempo['x_axis'].values[iii] is {sub_dat_tempo['x_axis'].values[iii]}")
                            # print(f"adaptive_df_compare['date_data'].values is {adaptive_df_compare['date_data'].values}")

                            # print(f"type sub_dat_tempo['x_axis'].values[iii] is {type(sub_dat_tempo['x_axis'].values[iii])}")
                            # print(f"type adaptive_df_compare['date_data'].values is {type(adaptive_df_compare['date_data'].values[0])}")
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

                                    # if cust_def_avail and high_pos:
                                    #     print("Applying price based on user specified constant (high_pos).")
                                    #     sub_process_dict_copy["corrected_price"] = sub_process_dict_copy["forecasted_price"] * (1 + high_pos)
                                    # elif cust_def_avail and all_pos:
                                    #     print("Applying price based on user specified constant (all_pos).")
                                    #     sub_process_dict_copy["forecasted_price"] = sub_process_dict_copy["forecasted_price"] * (1 + all_pos)
                                    # else:
                                    #     sub_process_dict_copy["forecasted_price"] = sub_process_dict_copy["forecasted_price"]

                                    # if remarks == "surge" and not cust_def_avail:
                                    #     sub_process_dict_copy["high_season_positive_multiplier_rate"] = rate_value
                                    # elif remarks == "mild_increase" and not cust_def_avail:
                                    #     sub_process_dict_copy["all_season_positive_multiplier_rate"] = rate_value
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
                                        sub_process_dict_copy["corrected_price"] = float(sub_dat_tempo["pred_res"].values[iii])

                                    # if cust_def_avail and high_neg:
                                    #     print("Applying price based on user specified constant (high_neg).")
                                    #     sub_process_dict_copy["forecasted_price"] = sub_process_dict_copy["forecasted_price"] * (1 - high_neg)
                                    # elif cust_def_avail and all_neg:
                                    #     print("Applying price based on user specified constant (all_neg).")
                                    #     sub_process_dict_copy["forecasted_price"] = sub_process_dict_copy["forecasted_price"] * (1 - all_neg)
                                    # else:
                                    #     sub_process_dict_copy["forecasted_price"] = sub_process_dict_copy["forecasted_price"]

                                    # if remarks == "mild_drop" and not cust_def_avail:
                                    #     sub_process_dict_copy["all_season_negative_multiplier_rate"] = rate_value
                                    # elif remarks == "drop_demand" and not cust_def_avail:
                                    #     sub_process_dict_copy["high_season_negative_multiplier_rate"] = rate_value
                                else:
                                    print("No rate value detected.")
                                    sub_process_dict_copy["corrected_price"] = float(sub_dat_tempo["pred_res"].values[iii]) 

                                # each rroom type will get information on what constant that they use today
                                # but since we don't have specific room type (will be updated later by backend devs)
                                # we will take one as reference/place holder, thus we create variable counter_roomtype
                                # and when it at one, we will store the constant used, and won't be used again
                                # TODO: DON'T FORGET TO UPDATE THIS WHEN THE ROOM TYPE ID IS AVAILABLE   
                                # if not counter_roomtype:
                                #     print("[DEBUG] Storing current constant usage for this room type.")
                                #     current_constant_usage["high_season_positive_multiplier_rate"] = sub_process_dict_copy["high_season_positive_multiplier_rate"]
                                #     current_constant_usage["all_season_positive_multiplier_rate"] = sub_process_dict_copy["all_season_positive_multiplier_rate"]
                                #     current_constant_usage["high_season_negative_multiplier_rate"] = sub_process_dict_copy["high_season_negative_multiplier_rate"]
                                #     current_constant_usage["all_season_negative_multiplier_rate"] = sub_process_dict_copy["all_season_negative_multiplier_rate"]
                                #     counter_roomtype = True

                                    # TODO: for now directly update to database. if room type available in the future
                                    # TODO: aggregate first before updating to database
                                    # print("[DEBUG] Updating current constant usage to remote database.")
                                    # url = PARAMETERS_API_URL
                                    # headers = {"Content-Type": "application/json",
                                    #         "Authorization": f"Bearer {API_KEY}"}

                                    # response = requests.post(url, json=current_constant_usage, headers=headers, verify=False)
                                    # if response.status_code == 200:
                                    #     print("[DEBUG] Successfully updated current constant usage to remote database.")
                                    # else:
                                    #     print(f"[ERROR] Failed to update current constant usage to remote database. Status code: {response.status_code}")
                                sub_process_dict_copy["forecasted_price"] = int(sub_dat_tempo["pred_res"].values[iii]) 
                                upper_sub_dat.append(sub_process_dict_copy)
                            else:
                                print(f"[DEBUG] No adaptive correction for date {sub_dat_tempo['x_axis'].values[iii]}, using baseline prediction.")
                                sub_process_dict_copy["corrected_price"] = int(sub_dat_tempo["pred_res"].values[iii]) 
                                sub_process_dict_copy["forecasted_price"] = int(sub_dat_tempo["pred_res"].values[iii]) 
                        else:
                            print(f"[DEBUG] Adaptive correction dataframe is empty, using baseline prediction for date {sub_dat_tempo['x_axis'].values[iii]}.")
                            sub_process_dict_copy["corrected_price"] = int(sub_dat_tempo["pred_res"].values[iii]) 
                            sub_process_dict_copy["forecasted_price"] = int(sub_dat_tempo["pred_res"].values[iii])
                            upper_sub_dat.append(sub_process_dict_copy)

                # prediction_pairing = pd.DataFrame({
                #     "Dates":buffer_date.values[-len(future_pred):],
                #     "Prediction":future_pred.flatten()
                # })
                # upper_sub_dat.append(sub_dat)
                # adaptive_sub_dat.append(adaptive_dat_copy)
            else:
                # adaptive_dat_copy = adaptive_dat.copy()
                print("Data is not sufficient enough")
                print("Skipping the segment, but in the future as the data sufficient enough, it might be able to be predicted.")
                print("[CAUTION]System will do auto-fill on empty field due to unreliable predictions.")

                # sub_process_dict = {
                #     "room_type_id": "",
                #     "room_type_name": "",
                #     "forecast_date": "",
                #     "forecasted_price": "",
                #     "high_season_positive_multiplier_rate": 0,
                #     "all_season_positive_multiplier_rate": 0,
                #     "high_season_negative_multiplier_rate": 0,
                #     "all_season_negative_multiplier_rate": 0,
                #     "all_room_types_min_forecasted_price": None,
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

                mod_date = datetime.datetime.now()
                max_date = mod_date + timedelta(days=(30))
                curr_date = mod_date

                buffer_box = []
                while(curr_date <= max_date):
                    curr_date = curr_date + timedelta(days=1)
                    buffer_box.append(curr_date)
                buffer_date = ts_monthly.index.union(buffer_box)
                buffer_date = pd.to_datetime(buffer_date, format="%Y-%m-%d")
                # buffer_date = buffer_date.tolist()
                buffer_date = pd.Series(buffer_date)
                buffer_date_processed = pd.to_datetime(buffer_date.values[-31:]).date

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
                    sub_process_dict_copy["room_type_id"] = str(algo_df['lpro_room_numid'].values[0])
                    # sub_process_dict_copy["room_type_name"] = algo_df['lpro_room_name'].values[0]
                    sub_process_dict_copy["property_id"] = customer_id_num
                    sub_process_dict_copy["forecast_date"] = buffer_date_processed[xi].strftime("%Y-%m-%d %H:%M:%S")
                    upper_sub_dat.append(sub_process_dict_copy)

                # adaptive_dat_copy["Data"] = []
                # adaptive_dat_copy["x-axis"] = []
                # adaptive_dat_copy["baseline_price"] = []
                # adaptive_dat_copy["adapted_price"] = []
                # adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."
                # upper_sub_dat.append(sub_dat)
                # upper_sub_dat.append(adaptive_dat_copy)
                # adaptive_sub_dat.append(adaptive_dat_copy)
            # sub_details_dat[n] = adaptive_sub_dat
            gc.collect()
        charts["result"]["forecasts"] = upper_sub_dat
        # charts["result"]["tempo_adaptive"] = sub_details_dat
        charts["datetime_push"] = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
        charts["status_code"] = 2
        charts["status_message"] = "Data successfully processed!"
        
        if room_type_avail == False:
            print("[DEBUG] Modifying the results forecast.")
            upper_sub_dat = []
            # sub_process_dict = {
            #     "room_type_id": "",
            #     "room_type_name": "",
            #     "forecast_date": "",
            #     "forecasted_price": "",
            #     "high_season_positive_multiplier_rate": "",
            #     "all_season_positive_multiplier_rate": "",
            #     "high_season_negative_multiplier_rate": "",
            #     "all_season_negative_multiplier_rate": "",
            #     "all_room_types_min_forecasted_price": "",
            #     "all_room_types_median_forecasted_price": "",
            #     "all_room_types_max_forecasted_price": ""
            # }

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
                # _highpos_rate_list = []
                # _allpos_rate_list = []
                # _highneg_rate_list = []
                # _allneg_rate_list = []
                sub_process_dict_copy = sub_process_dict.copy()
                sub_process_dict_copy["room_type_id"] = 0
                sub_process_dict_copy["property_id"] = customer_id_num
                sub_process_dict_copy["forecast_date"] = iv.date().strftime("%Y-%m-%d %H:%M:%S")
                for v in range(len(charts["result"]["forecasts"])):
                    if pd.to_datetime(charts["result"]["forecasts"][v]["forecast_date"]).date() == iv:
                        print(f"reprocessing data {pd.to_datetime(charts['result']['forecasts'][v]['forecast_date']).date()} in {pd.to_datetime(iv).date()}")
                        price_list.append(to_float(charts["result"]["forecasts"][v]["forecasted_price"]))
                        # _highpos_rate_list.append((charts["result"]["forecasts"][v]["high_season_positive_multiplier_rate"]))
                        # _allpos_rate_list.append((charts["result"]["forecasts"][v]["all_season_positive_multiplier_rate"]))
                        # _highneg_rate_list.append((charts["result"]["forecasts"][v]["high_season_negative_multiplier_rate"]))
                        # _allneg_rate_list.append((charts["result"]["forecasts"][v]["all_season_negative_multiplier_rate"]))
                
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

                    # _highpos_rate = max(_highpos_rate_list) 
                    # _allpos_rate = max(_allpos_rate_list) 
                    # _highneg_rate = min(_highneg_rate_list)
                    # _allneg_rate = min(_allneg_rate_list) 
                    # print(f"_highpos_rate is : {_highpos_rate}")
                    # print(f"_allpos_rate is : {_allpos_rate}")
                    # print(f"_highneg_rate : {_highneg_rate}")
                    # print(f"_allneg_rate : {_allneg_rate}")
                    # for v in range(len(charts["result"]["forecasts"])):
                    #     if pd.to_datetime(charts["result"]["forecasts"][v]["forecast_date"]).date() == pd.to_datetime(iv).date():
                    # sub_process_dict_copy["forecast_date"] = iv.strftime("%Y-%m-%d")
                    # sub_process_dict_copy["all_room_types_min_forecasted_price"] = min_price
                    # # sub_process_dict_copy["all_room_types_max_forecasted_price"] = max_price
                    # sub_process_dict_copy["all_room_types_max_forecasted_price"] = ""
                    # # sub_process_dict_copy["all_room_types_median_forecasted_price"] = median_price
                    # sub_process_dict_copy["all_room_types_median_forecasted_price"] = ""
                    # sub_process_dict_copy["high_season_positive_multiplier_rate"] = _highpos_rate
                    # sub_process_dict_copy["all_season_positive_multiplier_rate"] = _allpos_rate
                    # sub_process_dict_copy["high_season_negative_multiplier_rate"] = _highneg_rate
                    # sub_process_dict_copy["all_season_negative_multiplier_rate"] = _allneg_rate
                    upper_sub_dat.append(sub_process_dict_copy)
            # Replace the original forecasts with the aggregated ones when room type is not available
            charts["result"]["forecasts"] = upper_sub_dat

        # if only_once_active == True:
        #     display_comprate, display_comprate_lm = comprate_display(occ_rate=buffer_pred, cust_name=j, master_lib=master_lib)
        #     charts["comprate_early_booking"] = display_comprate
        #     charts["comprate_last_minute"] = display_comprate_lm
        #     only_once_active = False
        chartjs_to_endpoint(charts["result"], customer_id_num)
        K.clear_session()
        del loaded_model
        # del X_train
        # del X_test
        # del X_decoder_train
        # del X_decoder
        # del X_decoder_test
        # del y_train
        # del y_test
        del segment_n, sub_df, algo_df, ts, ts_monthly
        gc.collect()
        # with open("historical_record.pkl", "wb") as f:
        #     pickle.dump(debug_aa_dictionaries, f)
        #     print(f"success saving to historical_record.pkl")   

        # with open("additional_record.pkl", "wb") as f:
        #     pickle.dump(infer_aa_dictionaries, f)
        #     print(f"success saving to additional_record.pkl")

    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        print('error triggered')
        charts["datetime_push"] = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
        charts["status_code"] = 3
        charts["status_message"] = error_summary
        charts["date_start"] = ""
        charts["date_end"] = ""
        charts["result"] = [{
                "model_version": "v1.0.0",
                "customer_id": customer_id_num,
                "currency_id": currency_info,
                "forecasts": []
            }]
        charts["comprate_early_booking"] = []
        charts["comprate_last_minute"] = []
        chartjs_to_endpoint(charts["result"][0], customer_id_num, error_msg=error_summary)
        K.clear_session()
        del loaded_model
        # del X_train
        # del X_test
        # del X_decoder_train
        # del X_decoder
        # del X_decoder_test
        # del y_train
        # del y_test
        del segment_n, sub_df, algo_df, ts, ts_monthly
        gc.collect()
        raise
# ============================================= END SECTION  ===============================================

# @app.get("/inference-pipeline")
@task
def inference_pipeline():
    print("DEBUG: inference session STARTED")
    df = fetch_json_from_api(API_URLS)
    print("Combined dataframe shape:", df.shape)
    if df.empty:
        return JSONResponse({"error": "No JSON files found in GitHub repo"}, status_code=404)
    print("Combined dataframe shape:", df.shape)
    # print(f"[DEBUG] this is the dataframe before preproc : \n{df}")
    # print(f"[DEBUG] specific check on booking_date 2025-03-25 : \n{df[df['booking_date'] == '2025-03-25']}")
    df, cancel_rate, currency_info = preprocess_df(df)
    print("After preprocess shape:", df.shape)
    # print(f"[DEBUG] this is the dataframe after preproc : \n{df}")
    # print(f"[DEBUG] specific check on booking_date 2025-03-25 : \n{df[df['booking_date'] == '2025-03-25']}")
    # print(f"[DEBUG] cancellation rate is {cancel_rate}")

    try:
        prediction_sequence(df, cancel_rate, correction_active=True, currency_info=currency_info)
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

# FAILED CASE CUSTOMER 181
# {'16171': 1, '16172': 2}
# ERROR SUKA MUNCUL UnboundLocalError: cannot access local variable 'future_pred_lt' where it is not associated with a value

# FAILED CASE CUSTOMER 16
# Processing segment 2...
# Current room name is : 228
# Contingency pairing
# Contingency calculations
# Processing segment 3...
# Current room name is : 231
# Contingency pairing
# Contingency calculations
# Processing segment 4...
# Current room name is : 230
# Contingency pairing
# Contingency calculations
# Failed to send data. Status: 422, Response: {"success":false,"message":"Validation failed","errors":{"forecasts":["The forecasts field is required."]}}
# ValueError: Length of values (5) does not match length of index (1)