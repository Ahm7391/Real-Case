import pandas as pd
import numpy as np
import statsmodels.api as sm
import keras, json, os, requests, datetime, math
import tensorflow as tf
from statsmodels.tsa.seasonal import STL, seasonal_decompose
from datetime import timedelta

from zoneinfo import ZoneInfo
from tensorflow.keras import layers, models, backend as K
from sklearn.preprocessing import MinMaxScaler
from scipy.stats import wasserstein_distance
from sklearn.metrics import (mean_absolute_error,
                             mean_absolute_percentage_error,
                             root_mean_squared_log_error)
from sklearn.mixture import GaussianMixture
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('LOKAPRO_API_KEY')
COMPANY_API_URL = os.getenv("ANALYTIC_DATA_HOOK_URL")
WEBHOOK_URL = "https://webhook-test.com/8eff260496ba2d22dbfbf4304a972559"
API_URLS = "/workspaces/Ecommerce-Project/Machine Learning Development/buffer_customer"
FOLDER_PATH_COMPRATE = "/workspaces/Ecommerce-Project/Machine Learning Development/Comprate"
SAVE_FOLDER_LOC = "/workspaces/Ecommerce-Project/Machine Learning Development/buffer_model"
app = FastAPI()

@app.get("/")
def root():
    return {"message": "Training Session Started!!"}

class ZeroDataError(Exception):
    pass

###################################################################
######--------------MODEL ARCHITECTURE-----------------------######
###################################################################
forecast_horizon = 5
ENC_LEN = 20       # encoder input length
DEC_LEN = 5        # days to forecast per pass
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
def normalize_json_to_df(jsondata):
    with open(jsondata, "r") as f:
        data = json.load(f)  # Load entire JSON
        df = pd.json_normalize(data)  
    return df

def fetch_json_from_api(api_urls):
    main_df = pd.DataFrame()

    try:
        for filename in os.listdir(api_urls):
            if filename.lower().endswith(".json"):
                print(filename)
                final_form = os.path.join(api_urls, filename)
                df_temp = normalize_json_to_df(final_form)
                main_df = pd.concat([main_df, df_temp], ignore_index=True)

        if main_df.shape == (0, 0):
            raise ZeroDataError("Received zero value, cannot continue processing")
        
        print("Fetching success!!!")
        return main_df
    except ZeroDataError as e:
        error_summary = f"{type(e).__name__}: {e}"
        return error_summary
    
def chartjs_to_endpoint(data, use_company_api=False):
    # with open("check.json", "w") as f:
    #     json.dump(data, f, indent=4)
    try:
        if use_company_api:
            url = os.getenv("COMPANY_API_URL")
            headers = {"Content-Type": "application/json",
                       "Authorization": f"Bearer {API_KEY}"}
            # response = requests.post(WEBHOOK_URL, headers=headers, data=json.dumps(data))
            
        else:
            url = WEBHOOK_URL
            headers = {
                "Content-Type": "application/json"
            }

        response = requests.post(url, headers=headers, json=data)

        # For debugging
        if response.status_code == 200:
            print("ChartJS successfully sent!")
        else:
            print(f"Failed to send data. Status: {response.status_code}, Response: {response.text}")
        return response.status_code
    except Exception as e:
        print(f"Error sending ChartJS: {e}")
        raise

def generate_timestamp():
    timestamp = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y%m%d")
    return timestamp

def preprocess_df(main_df):
    # main_df['net_amount_stay'] = main_df['net_amount_stay'] / 100
    main_df = main_df.drop(columns='id')
    
    main_df['booking_date'] = pd.to_datetime(main_df['booking_date'], dayfirst=True)
    main_df['check_in'] = pd.to_datetime(main_df['check_in'], dayfirst=True)
    main_df['check_out'] = pd.to_datetime(main_df['check_out'], dayfirst=True)

    main_df['lead_days'] = (main_df['check_in'] - main_df['booking_date']).dt.days

    main_df['booking_day'] = main_df['booking_date'].dt.day
    main_df['booking_month'] = main_df['booking_date'].dt.month
    main_df['booking_year'] = main_df['booking_date'].dt.year

    main_df['check_in_day'] = main_df['check_in'].dt.day
    main_df['check_in_month'] = main_df['check_in'].dt.month
    main_df['check_in_year'] = main_df['check_in'].dt.year
    main_df['check_in_weekday'] = main_df['check_in'].dt.day_name() 

    main_df['check_out_day'] = main_df['check_out'].dt.day
    main_df['check_out_month'] = main_df['check_out'].dt.month
    main_df['check_out_year'] = main_df['check_out'].dt.year

    main_df['stay_days'] = (main_df['check_out'] - main_df['check_in']).dt.days
    main_df['price_per_night'] = main_df['net_amount_stay'] / main_df['stay_days']

    no_net = []
    for i in range(len(main_df['net_amount_stay'])):
      if main_df.iloc[i, 5] == 0:
          no_net.append(0)
      else:
          no_net.append(1)
    main_df['net_amount_avail'] = no_net
    main_df['is_confirmed'] = main_df['is_confirmed'].replace({'t': True, 'f': False})
    main_df = main_df.loc[(main_df['lead_days'] >= 0) & 
                       (main_df['net_amount_avail'] == 1) &
                       (main_df['price_per_night'] <= 18000000) &
                       (main_df['net_amount_stay'] > 0), :]
    return main_df
# ============================================= END SECTION  ===============================================

###############################################################################################
############----------------ALGORITHMS AND HELPER FUNCTIONS-----------------------------#######
###############################################################################################

def outlier_fx(data, parameter):
    # data = data[data['ota_name'] != "Website Direct"]
    q1 = data[parameter].quantile(0.25)
    q3 = data[parameter].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    clean = data[(data[parameter] >= lower) & (data[parameter] <= upper)]
    return clean

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

def distribution_shift_adjust(sub_df):
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
    for i in emd_results['OTA']:
        if emd_results[(emd_results['OTA'] == i)]['EMD'].values >= upper_bound:
            filtering_master.append(i)
    print(f"to be filtered is: ", filtering_master)
    return filtering_master

def create_sliding_windows(data, seq_length=20, horizon=5, step=1):
    X, y = [], []
    for i in range(0, len(data) - seq_length - horizon + 1, step):
        X.append(data[i:i+seq_length])
        y.append(data[i+seq_length:i+seq_length+horizon])
    return np.array(X), np.array(y)

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

def pickup_rate_correction(check_df):
    check_df['booking_date'] = pd.to_datetime(check_df['booking_date'])
    check_df['check_in'] = pd.to_datetime(check_df['check_in'])

    daily_counts = check_df.groupby(['booking_date', 'check_in']).size().reset_index(name='daily_bookings')
    daily_counts['cumulative_bookings'] = daily_counts.groupby('check_in')['daily_bookings'].cumsum()
    daily_counts['daily_pickup'] = daily_counts.groupby('check_in')['cumulative_bookings'].diff()
    first_day = daily_counts.groupby('check_in')['cumulative_bookings'].transform('first')
    daily_counts['cumulative_pickup_rate'] = ((daily_counts['cumulative_bookings'] - first_day) / first_day.replace(0, pd.NA)) * 100
    daily_counts['lead_days'] = (daily_counts['check_in'] - daily_counts['booking_date']).dt.days
    return daily_counts

def continuous_occ_rate_correction(df_master, remaining_room, mem_buffer,
                                   mem_buffer_ckout, max_room_number, avail_percentage):
    start_range = df_master['booking_date'].max() + timedelta(days=1)
    end_range = df_master['check_in'].max()
    mov_days = start_range

    rooms_left = remaining_room
    memory_buffer = mem_buffer
    memory_buffer_ckout = mem_buffer_ckout
    collected_date = []
    occ_rate = []
    track_room = []
    counter = 0
    delta_date = end_range - start_range
    delta_date = int(delta_date.days)
    while mov_days <= end_range:
        # print(f"Booking date start from {mov_days}")
        resampling = df_master[(df_master['booking_date'] >= mov_days) &
                        (df_master['booking_date'] <= end_range)]
        resampling = resampling.loc[(resampling['booking_date'] == mov_days),
                                    ['check_in', 'check_out', 'booking_date', 'price_per_night']]
        count_occur_ckin = resampling.groupby('check_in')['check_in'].count()
        count_occur_ckout = resampling.groupby('check_out')['check_out'].count()

        for i in range(len(count_occur_ckin)):
            ckin_record = count_occur_ckin.index[i]
            delta = int(count_occur_ckin.values[i])
            if ckin_record not in memory_buffer:
                memory_buffer[ckin_record] = [delta, ckin_record]
                # print(f"added Check-in : {memory_buffer[ckin_record]}")
            elif ckin_record in memory_buffer:
                memory_buffer[ckin_record][0] = delta + memory_buffer[ckin_record][0]
                # print(f"Day {mov_days} updated +{abs(delta)} bookings")

        for i in range(len(count_occur_ckout)):
            ckout_record = count_occur_ckout.index[i]
            delta = int(count_occur_ckout.values[i])
            if ckout_record not in memory_buffer_ckout:
                memory_buffer_ckout[ckout_record] = [delta, ckout_record]
                # print(f"added Check-in : {memory_buffer_ckout[ckout_record]}")
            elif ckout_record in memory_buffer_ckout:
                memory_buffer_ckout[ckout_record][0] = delta + memory_buffer_ckout[ckout_record][0]
                # print(f"Check out Day {memory_buffer_ckout[ckout_record][1]} updated +{abs(delta)} bookings")
        try:
            if mov_days in memory_buffer:
                if mov_days == memory_buffer[mov_days][1]:
                    rooms_left = rooms_left - memory_buffer[mov_days][0]
                    # print(f"Added rooms occupied : {memory_buffer[mov_days][0]}")
            if mov_days in memory_buffer_ckout:
                if mov_days == memory_buffer_ckout[mov_days][1]:
                    rooms_left = rooms_left + memory_buffer_ckout[mov_days][0]
                    # print(f"Freed occupied rooms : {memory_buffer_ckout[mov_days][0]}")
        except Exception as e:
            print(f"[ERROR] details: {e}")

        if counter % 30 == 0:
            progress_calculation = (counter / delta_date) * 100
            print(f"Progress (Extension steps): {progress_calculation:.2f}%")
            print(f"Total rooms at day {mov_days} is {rooms_left}")
        occupied_percentage = ((max_room_number - rooms_left) / max_room_number) * 100
        occupancy_rate = occupied_percentage - avail_percentage
        collected_date.append(mov_days)
        occ_rate.append(occupancy_rate)
        track_room.append(rooms_left)
        # print(memory_buffer)
        # print(memory_buffer_ckout, "\n")
        counter = counter + 1
        mov_days = mov_days + timedelta(days=1)

    continuous_occ_rate = pd.DataFrame({
        "Dates":collected_date,
        "Occupancy Rate":occ_rate,
        "Rooms Left":track_room
    })
    return continuous_occ_rate, memory_buffer

def occupancy_rate_correction(occ, avail_room, avail_percentage):
    occ['booking_date'] = pd.to_datetime(occ['booking_date'])
    occ['check_in'] = pd.to_datetime(occ['check_in'])
    occ['check_out'] = pd.to_datetime(occ['check_out'])
    start_range = occ['booking_date'].min()
    end_range = occ['booking_date'].max()
    # end_range = start_range + timedelta(days=60)

    memory_buffer = {}
    memory_buffer_ckout = {}
    collected_date = []
    occ_rate = []
    track_room = []
    focus = occ.sort_values(by='booking_date')
    offset_days = start_range
    rooms_left = avail_room
    counter = 0
    delta_date = end_range - start_range
    delta_date = int(delta_date.days)
    # counter = 0
    while offset_days <= end_range:
        # print(f"Booking date start from {offset_days}")
        resampling = focus[(focus['booking_date'] >= offset_days) &
                        (focus['booking_date'] <= end_range)]
        resampling = resampling.loc[(resampling['booking_date'] == offset_days),
                                    ['check_in', 'check_out', 'booking_date', 'price_per_night']]
        count_occur_ckin = resampling.groupby('check_in')['check_in'].count()
        count_occur_ckout = resampling.groupby('check_out')['check_out'].count()

        for i in range(len(count_occur_ckin)):
            ckin_record = count_occur_ckin.index[i]
            delta = int(count_occur_ckin.values[i])
            if ckin_record not in memory_buffer:
                memory_buffer[ckin_record] = [delta, ckin_record]
                # print(f"added Check-in : {memory_buffer[ckin_record]}")
            elif ckin_record in memory_buffer:
                memory_buffer[ckin_record][0] = delta + memory_buffer[ckin_record][0]
                # print(f"Day {offset_days} updated +{abs(delta)} bookings")

        for i in range(len(count_occur_ckout)):
            ckout_record = count_occur_ckout.index[i]
            delta = int(count_occur_ckout.values[i])
            if ckout_record not in memory_buffer_ckout:
                memory_buffer_ckout[ckout_record] = [delta, ckout_record]
                # print(f"added Check-out : {memory_buffer_ckout[ckout_record]}")
            elif ckout_record in memory_buffer_ckout:
                memory_buffer_ckout[ckout_record][0] = delta + memory_buffer_ckout[ckout_record][0]
                # print(f"Check out Day {memory_buffer_ckout[ckout_record][1]} updated +{abs(delta)} bookings")

        try:
            if offset_days in memory_buffer:
                if offset_days == memory_buffer[offset_days][1]:
                    rooms_left = rooms_left - memory_buffer[offset_days][0]
                    # print(f"Added rooms occupied : {memory_buffer[offset_days][0]}")

            if offset_days in memory_buffer_ckout:
                if offset_days == memory_buffer_ckout[offset_days][1]:
                    rooms_left = rooms_left + memory_buffer_ckout[offset_days][0]
                    # print(f"Freed occupied rooms : {memory_buffer_ckout[offset_days][0]}")
        except Exception as e:
            print(f"[ERROR] details: {e}")
        if counter % 30 == 0:
            progress_calculation = (counter / delta_date) * 100
            print(f"Progress: {progress_calculation:.2f}%")
            print(f"Total rooms at day {offset_days} is {rooms_left}")
        occupied_percentage = ((avail_room - rooms_left) / avail_room) * 100
        occupancy_rate = occupied_percentage - avail_percentage
        collected_date.append(offset_days)
        occ_rate.append(occupancy_rate)
        track_room.append(rooms_left)
        counter = counter + 1
        # print(memory_buffer)
        # print(memory_buffer_ckout, "\n")
        offset_days = offset_days + timedelta(days=1)

    summary_occ = pd.DataFrame({
        "Dates":collected_date,
        "Occupancy Rate":occ_rate,
        "Rooms Left":track_room
    })
    next_prediction, memory_buffer = continuous_occ_rate_correction(occ, rooms_left, memory_buffer,
                                                                    memory_buffer_ckout, avail_room, avail_percentage)
    summary_occ = pd.concat([summary_occ, next_prediction], ignore_index=True)
    return summary_occ, memory_buffer

def seasonal_correction(master_df, mn_date, mode="mean"):
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
    seasonal_df['Pct_Change'] = seasonal_df['Seasonal_Pattern'].pct_change() * 100  # multiply by 100 to get percentage
    # Optional: round to 2 decimal places for readability
    seasonal_df['Pct_Change'] = seasonal_df['Pct_Change'].round(2)
    return seasonal_df

def segmentation_step(sub_dfa, customer_name):
    sub_dfb = sub_dfa[sub_dfa['customer_name'] == customer_name]
    sub_dfb = outlier_fx(sub_dfb, 'price_per_night')
    best_k_val = segmentation_data(sub_dfb)
    best_gmm = GaussianMixture(n_components=best_k_val, random_state=0).fit(sub_dfb[['price_per_night']])
    labels = best_gmm.predict(sub_dfb[['price_per_night']])
    sub_dfb['cluster'] = labels
    return sub_dfb, best_k_val

def comprate_correction(api_urls=FOLDER_PATH_COMPRATE):
    #################### ----------- SUPPORTING FUNCTION ------------ ####################
    class ZeroDataError(Exception):
        pass

    def normalize_json_to_df(jsondata):
        with open(jsondata, "r") as f:
            data = json.load(f)  # Load entire JSON
        return data

    def percentage_calculation(comprate_df):
        average_val = []
        percentage_res = pd.DataFrame()
        percentage_res['Date'] = comprate_df['Date']
        for i in range(1, len(comprate_df.columns)):
            calc_result = []
            for j in range(1, len(comprate_df)):
                if comprate_df.iloc[j-1,i] != 0:
                    delta_range = (comprate_df.iloc[j,i] - comprate_df.iloc[j-1,i]) / comprate_df.iloc[j-1,i]
                else:
                    delta_range = 0
                calc_result.append(delta_range)
            calc_result.insert(0,0)
            percentage_res[f"{comprate_df.columns[i]}_diff"] = calc_result

        for i in range(len(percentage_res)):
            min_pct = percentage_res.iloc[i, 1:].min()
            max_pct = percentage_res.iloc[i, 1:].max()
            calculation_avg = (min_pct + max_pct) / 2
            average_val.append(calculation_avg)
        percentage_res['Average Value'] = average_val
        percentage_res['Date'] = pd.to_datetime(percentage_res['Date'])
        return percentage_res
    #################### ----------- END OF SUPPORTING FUNCTION ------------ ####################

    comprate_df = pd.DataFrame()
    try:
        name_dict = ["Date"]
        date_dict = []
        price_dict = []
        for filename in os.listdir(api_urls):
            if filename.lower().endswith(".json"):
                print(filename)
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
        print("Fetching success!!!")
    except ZeroDataError as e:
        error_summary = f"{type(e).__name__}: {e}"
        print(error_summary)
    comprate_df.columns = name_dict
    comprate_df = comprate_df.replace(0, np.nan).ffill()
    comprate_df = comprate_df.fillna(0)
    percentage_valdf = percentage_calculation(comprate_df)
    return percentage_valdf

import warnings
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
def correction_applicator(sub_dfa, customer_name, master_lib, aggregate, 
                          buff_p, ts_data, y_pred_master, comprate_calc):
    pairing = zip(ts_data.index[-len(y_pred_master):], y_pred_master)
    min_date = ts_data.index[-len(y_pred_master):].min() - timedelta(days=365)
    alpha = master_lib["reserved_for_test"]['corr_constant'][0]
    beta = master_lib["reserved_for_test"]['corr_constant'][1]
    gamma = master_lib["reserved_for_test"]['corr_constant'][2]
    delta = master_lib["reserved_for_test"]['corr_constant'][3]
    epsilon = master_lib['reserved_for_test']['corr_constant'][4]
    caged = {}
    for i in pairing:
        if i[0] in aggregate.index:
            corr_price = i[1] * (1 + (alpha * (aggregate.loc[i[0]] / 100)))
        else:
            corr_price = i[1] * (1 + (alpha * 0))

        if i[0] in comprate_calc['Date'].values:
            extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value']
            corr_price = corr_price * (1 + epsilon * extracted_pct)
            print(f"Competitor rate corrected price at date {i[0]}, with percentage {extracted_pct}%")

        if i[0] in buff_p['Dates'].values:
            corr_price =  corr_price * ((1 + (beta * buff_p.loc[(buff_p['Dates'] == i[0]), 'Occupancy Rate'])).tolist()[0])
        preview_seasonal_a = seasonal_correction(sub_dfa, min_date, mode="mean")
        lower_bound = preview_seasonal_a.loc[(preview_seasonal_a['Dates'] <= (i[0] - timedelta(days=365)).strftime('%Y-%m-%d')), :]
        # lower_bound = lower_bound[pd.notna(lower_bound['Pct_Change'])].reset_index(drop=True)
        lower_bound = lower_bound.fillna(0).reset_index(drop=True)
        lower_focus = lower_bound.iloc[-1:, :]
        if lower_focus['Pct_Change'].values.size > 0:
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

# ============================================= END SECTION  ===============================================

###################################################################
######--------------TRAINING ALGORITHM-----------------------######
###################################################################

# THIS PROPERTY LIBRARY SHOULD BE SEPARATED JSON LATER
property_library = {
    "Daun Lebar Villa": {
        "total_room":12,
        "avail_percentage":75,
        "corr_constant": [5e-3, 3e-4, 0, 3e-3]
    },
    "Meruhdani Boutique Hotel Ubud": {
        "total_room":23,
        "avail_percentage":75,
        "corr_constant": [4e-3, -5e-4, 1e-5, 1e-5]
    },
    "Puri Canggu Villas & Room": {
        "total_room":15,
        "avail_percentage":75,
        "corr_constant": [1e-2, -5e-4, 0, -1e-3]
    },
    "reserved_for_test": {
        "total_room":100,
        "avail_percentage":75,
        "corr_constant":[0, 0, 0, 0]
    }
}

def training_sequence(df_input, master_lib, correction_active=False):
    details_dat = {}
    for j in df_input['customer_name'].unique():
        print(f'Processing property {j}')
        sub_df, n_cluster = segmentation_step(df_input, j)
        sub_details_dat = {}
        print(f"To be processed: {n_cluster} segment.")
        for n in range(n_cluster):
            print(f"processing cluster no {n}")
            segment_n = sub_df[sub_df['cluster'] == n]
            print(f"with shape: {segment_n.shape}")
            will_be_filter = distribution_shift_adjust(segment_n)
            segment_n = segment_n[~segment_n['ota_name'].isin(will_be_filter)]
            segment_n = capped_outlier_fx(segment_n, 'price_per_night')
            starting_date = segment_n['booking_date'].max() - timedelta(days=365)
            algo_df = segment_n[segment_n['booking_date'] >= starting_date]
            max_booking_date = segment_n['booking_date'].max()

            print(f"check segment_n before process: {segment_n.shape}")
            if len(segment_n) < 50:
                print("CAUTION: NOT ENOUGH DATA TO PROCESS THIS SEGMENT, SKIPPING THIS CLUSTER!!!")
                continue
            X, y = [], []
            segment_n['check_in'] = pd.to_datetime(segment_n['check_in'])
            ts = segment_n[segment_n['check_in'] <= pd.to_datetime(max_booking_date)]
            ts = segment_n.groupby('check_in')['price_per_night'].mean()
            ts_monthly = ts.resample('D').mean()
            ts_monthly = ts_monthly.dropna()

            lowess = sm.nonparametric.lowess
            lowess_value = []
            lowess_value = lowess(ts_monthly.values, ts_monthly.index, frac=0.02)[:,1]
            extra_steps = False
            scaler = MinMaxScaler()
            lowess_scaled = scaler.fit_transform(lowess_value.reshape(-1, 1))
            print("Raw data length is: ", len(lowess_scaled))

            if len(lowess_scaled) >= 500:
                sequence_length = 20
            else:
                sequence_length = 15
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

            if X.shape[0] >= 90:
                print("Data is sufficient enough, continuing!")
                n_samples = len(X)
                train_size = int(n_samples * 0.85)

                X_train, X_test = X[:train_size], X[train_size:]
                y_train, y_test = y[:train_size], y[train_size:]

                if extra_steps == True:
                    X_train, y_train = mixup(X_train, y_train, alpha=0.2, augment_factor=1.2)
                    extra_steps = False

                # Split train into 85% train, 15% validation
                n_train = len(X_train)
                val_size = int(n_train * 0.15)

                X_val, X_train = X_train[-val_size:], X_train[:-val_size]
                y_val, y_train = y_train[-val_size:], y_train[:-val_size]

                def make_decoder_input(y):
                    start_token = np.zeros_like(y[:, :1, :])  # shape (batch, 1, 1)
                    return np.concatenate([start_token, y[:, :-1, :]], axis=1)

                X_decoder_train = make_decoder_input(y_train)
                X_decoder_val   = make_decoder_input(y_val)
                X_decoder_test  = make_decoder_input(y_test)
                print("Train:", X_train.shape, y_train.shape)
                print("Val:  ", X_val.shape, y_val.shape)
                print("Test: ", X_test.shape, y_test.shape)

                print("decoder_train:", X_decoder_train.shape)
                print("validation_train:  ", X_decoder_val.shape)
                print("Test_enc_dec : ", X_decoder_test.shape)

                print(f"===========TRAINING BATCH {j}===================")
                early_stop = EarlyStopping(
                    monitor='val_loss',
                    patience=7,
                    restore_best_weights=True
                )

                reduce_lr = keras.callbacks.ReduceLROnPlateau(
                    factor=0.5, patience=3, monitor='val_loss'
                )

                model.fit([X_train, X_decoder_train], y_train, epochs=70,
                        validation_data=([X_val, X_decoder_val], y_val),
                        callbacks=[reduce_lr, early_stop])
                model.evaluate([X_test, X_decoder_test], y_test)

                # # ================FOR DEBUG ONLY=============================
                y_pred = model.predict([X_test, X_decoder_test])
                pred_scaled = scaler.inverse_transform(y_pred)
                y_test = np.squeeze(y_test, axis=-1)
                pred_test = scaler.inverse_transform(y_test)
                print("Prediction shape:", pred_scaled.shape)

                # Average across the 5 steps
                y_pred_mean = np.mean(pred_scaled, axis=1)
                y_test_mean = np.mean(pred_test, axis=1)

                # residuals = y_test_mean - y_pred_mean
                # std_dev = np.std(residuals)
                # y_pred_upper = y_pred_mean + 2 * std_dev
                # y_pred_lower = y_pred_mean - 2 * std_dev
                dates_buffer = ts_monthly.index[-len(y_pred_mean):].strftime("%Y-%m-%d")
                try:
                    rmsle = root_mean_squared_log_error(pred_test, pred_scaled)
                    mae = mean_absolute_error(pred_test, pred_scaled)

                    print(f'print rmsle: {100 * rmsle:.2f} %')
                    print(f'print mae: {mae}')
                except Exception as e:
                    print(f"[ERROR] Can't measure error: {e}")

                if correction_active == True:
                    avail_room = master_lib["reserved_for_test"]['total_room']
                    avail_percentage = master_lib["reserved_for_test"]['avail_percentage']
                    comprate_factor = comprate_correction()
                    occ_data_buffer, _ = occupancy_rate_correction(algo_df, avail_room, avail_percentage)
                    ckin_data_buffer = pickup_rate_correction(algo_df)
                    buffer_pred = occ_data_buffer[(occ_data_buffer['Dates'] >= ts_monthly.index[-len(y_pred_mean):].min()) &
                                (occ_data_buffer['Dates'] <= ts_monthly.index[-len(y_pred_mean):].max())]
                    aggregated_ckin = ckin_data_buffer.groupby('check_in')['cumulative_pickup_rate'].max()
                    aggregated_ckin.resample('D').max()
                    
                    result_caged = correction_applicator(segment_n, j, master_lib, aggregated_ckin, buffer_pred, 
                                                        ts_monthly, y_pred_mean, comprate_factor)
                    custom_error_mae = mean_absolute_error(ts_monthly.values[-len(y_pred_mean):], result_caged.values)
                    custom_error_mape = mean_absolute_percentage_error(ts_monthly.values[-len(y_pred_mean):], result_caged.values)
                    
                    sub_dat = {
                        "pred_res":result_caged.values.tolist(),
                        "baseline_pred":y_pred_mean.tolist(),
                        "x_axis":dates_buffer.tolist(),
                        "real_data":y_test_mean.tolist(),
                        "rmsle":custom_error_mape,
                        "mae":custom_error_mae
                    }
                else:
                    sub_dat = {
                        "pred_res":"",
                        "baseline_pred":y_pred_mean.tolist(),
                        "x_axis":dates_buffer.tolist(),
                        "real_data":y_test_mean.tolist(),
                        "rmsle":"",
                        "mae":""
                    }
                
            elif X.shape[0] < 90:
                print("Data is not sufficient enough")
                print("Switching to SARIMAX and LOWESS method.")
                sub_dat = {}
            sub_details_dat[n] = sub_dat
        details_dat[j] = sub_details_dat

    chartjs_to_endpoint(details_dat, use_company_api=False)
    os.makedirs(SAVE_FOLDER_LOC, exist_ok=True)
    mod_version = "Generalized_model_" + generate_timestamp()

    model_path = os.path.join(SAVE_FOLDER_LOC, f"{mod_version}.h5")
    model.save(model_path)
    print(f"Model saved to {model_path}")

@app.get("/training-pipeline")
def training_pipeline():
    print("DEBUG: training session STARTED")
    df = fetch_json_from_api(API_URLS)
    print("Combined dataframe shape:", df.shape)
    if df.empty:
        return JSONResponse({"error": "No JSON files found in GitHub repo"}, status_code=404)
    print("Combined dataframe shape:", df.shape)
    df = preprocess_df(df)
    print("After preprocess shape:", df.shape)
  
    try:
        training_sequence(df, property_library, correction_active=True)
        print("Process Finished, may add dictionaries of details in the future")
        return 0
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        print(error_summary)