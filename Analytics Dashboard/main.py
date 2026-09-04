from fastapi import FastAPI
from dotenv import load_dotenv
from datetime import timedelta
import pandas as pd
import json, os, copy, calendar, math, re
import numpy as np
import statsmodels.api as sm
from statsmodels.tsa.seasonal import seasonal_decompose

from fastapi.responses import JSONResponse
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo
import requests, datetime

# --- CONFIG ---
# API_URLS = [
#     "https://api.github.com/repos/AntonioHazman8855/Dashboard-Preparation/contents/"
# ]
# GITHUB_TOKEN = ""
load_dotenv()
API_KEY = os.getenv('LOKAPRO_API_KEY')
COMPANY_API_URL = os.getenv("ANALYTIC_DATA_HOOK_URL")
DEBUG_STAT = False

CURR_FILE = os.path.abspath(__file__)
CURR_DIR = os.path.dirname(CURR_FILE)
# MAIN_DIR = os.path.dirname(CURR_DIR)
UPLOAD_FILENAME  = 'processed_data.json'
WEBHOOK_URL = "https://2f68b6cd-a59f-4429-af46-00f19a73248e.mock.pstmn.io/webhook"
app = FastAPI()

@app.get("/")
def root():
    return {"message": "Simulation API running"}

class ZeroDataError(Exception):
    pass

def load_id():
    if not os.path.exists("buffer.json"):
        print(f"WARNING: data not found. Starting with empty buffer.")
        return {}
    else:
        with open("buffer.json", "r") as f:
            data = json.load(f)
            customer_id = data["data"]["customer_id"]
            job_id_num = data["job_identification"]
        return customer_id, job_id_num

def normalize_json_to_df(jsondata):
    with open(jsondata, "r") as f:
        data = json.load(f)  # Load entire JSON
        # df = pd.json_normalize(data["data"]["booking_data"])  
        df = pd.json_normalize(data) 
    return df

def fetch_json_from_api(main_dir):
    main_df = pd.DataFrame()

    try:
        for filename in os.listdir(main_dir):
            if filename.lower().endswith("cust_details.json"):
                print(filename)
                df_temp = normalize_json_to_df(filename)
                main_df = pd.concat([main_df, df_temp], ignore_index=True)

        if main_df.shape == (0, 0):
            raise ZeroDataError("Received zero value, cannot continue processing")
        
        print("Fetching success!!!")
        return main_df
    except ZeroDataError as e:
        error_summary = f"{type(e).__name__}: {e}"
        return error_summary

def preprocess_df(main_df):
    # main_df['net_amount_stay'] = main_df['net_amount_stay'] / 100
    # main_df = main_df.drop(columns='id')
    
    main_df['booking_date'] = pd.to_datetime(main_df['booking_date'], format='mixed', dayfirst=True)
    main_df['check_in'] = pd.to_datetime(main_df['check_in'], format='mixed', dayfirst=True)
    main_df['check_out'] = pd.to_datetime(main_df['check_out'], format='mixed', dayfirst=True)

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
                       (main_df['net_amount_stay'] > 0) &
                       (main_df['price_per_night'] >= 50000), :]
    return main_df
    
def chartjs_to_endpoint(data, use_company_api=True):
    # with open("check.json", "w") as f:
    #     json.dump(data, f, indent=4)
    try:
        if use_company_api:
            url = COMPANY_API_URL
            headers = {"Content-Type": "application/json",
                       "X-API-KEY": API_KEY}
            # response = requests.post(WEBHOOK_URL, headers=headers, data=json.dumps(data))
            
        else:
            url = WEBHOOK_URL
            headers = {
                "Content-Type": "application/json"
            }

        response = requests.post(url, headers=headers, json=data, verify=True)
        # For debugging
        if response.status_code == 200:
            print("✅ ChartJS successfully sent!")
        else:
            print(f"⚠️ Failed to send data. Status: {response.status_code}, Response: {response.text}")
        return response.status_code
    except Exception as e:
        print(f"❌ Error sending ChartJS: {e}")
        raise

def outlier_fx(data, parameter):
    # data = data[data['ota_name'] != "Website Direct"]
    q1 = data[parameter].quantile(0.25)
    q3 = data[parameter].quantile(0.75)
    iqr = q3 - q1
    lower = q1 - 1.5 * iqr
    upper = q3 + 1.5 * iqr
    print(f"Before clipping outlier shape: {data.shape}")
    clean = data[(data[parameter] >= lower) & (data[parameter] <= upper)]
    print(f"After clipping outlier shape: {clean.shape}")
    return clean

def average_room_rate(occ):
    occ['booking_date'] = pd.to_datetime(occ['booking_date'])
    occ['check_in'] = pd.to_datetime(occ['check_in'])
    occ['check_out'] = pd.to_datetime(occ['check_out'])
    start_range = occ['check_in'].min()
    end_range = occ['check_in'].max()

    collected_date = []
    daily_arr = []
    focus = occ.sort_values(by='check_in')
    offset_days = start_range
    sum_room = 0
    sum_price = 0
    counter = 0
    delta_date = end_range - start_range
    delta_date = int(delta_date.days)

    keep_track = pd.DataFrame()
    while offset_days <= end_range:
        resampling = focus[(focus['check_in'] >= offset_days) &
                        (focus['check_in'] <= end_range)]
        resampling = resampling.loc[(resampling['check_in'] == offset_days),
                                    ['check_in', 'check_out', 'price_per_night']]
        
        for i in range(len(resampling)):
            ckin_record = [resampling.iloc[i, 0]]
            ckout_record = [resampling.iloc[i, 1]]
            price_track = [resampling.iloc[i, 2]]
            # id_input = [resampling.iloc[i, 3]]

            new_df_ckin = pd.DataFrame({
                "ckin_date": ckin_record,
                "ckout_date": ckout_record,
                "price":price_track
            })
            keep_track = pd.concat([keep_track, new_df_ckin])
            
        try:
            # FIRST UPDATE KEEP TRACK BIN WITH CHECK IN DATA -> ADD OCCUPIED ROOM AND ADD MONEY IN THE POT
            ckin_groupby = keep_track.loc[(keep_track["ckin_date"] == offset_days), :]
            sum_room = sum_room + len(ckin_groupby)
            sum_price = sum_price + ckin_groupby["price"].sum()

            # SEEK ANY CHECK OUT IN KEEP TRACK BIN -> IF ANY RETURN OCCUPIED ROOM AND DEDUCT MONEY IN THE POT
            ckout_groupby = keep_track.loc[(keep_track["ckout_date"] == offset_days), :]
            sum_room = sum_room - len(ckout_groupby)
            sum_price = sum_price - ckout_groupby["price"].sum()

            # LASTLY, IF THERE IS CHECK OUT, UPDATE KEEP TRACK DF SO ALL ORDER THAT HAS CHECKED OUT CLEARED FROM THE DF
            keep_track = keep_track[~keep_track['ckout_date'].isin([offset_days])]
        except Exception as e:
            print(f"[ERROR] details: {e}")
        if counter % 30 == 0:
            progress_calculation = (counter / delta_date) * 100
            print(f"Progress: {progress_calculation:.2f}%")
            print(f"Total rooms at day {offset_days} is {sum_room}")
        if sum_room != 0:
            daily_arr_formula = sum_price / sum_room
        else:
            daily_arr_formula = 0
        collected_date.append(offset_days)
        daily_arr.append(daily_arr_formula)
        counter += 1
        offset_days = offset_days + timedelta(days=1)

    summary_arr = pd.DataFrame({
        "Dates":collected_date,
        "Average Room Rate":daily_arr,
    })
    return summary_arr

def plotly_preprocess(source_df, cust):
    print(f'processing customer {cust}')
    buffer_df = source_df.loc[(source_df['customer_id'] == cust), :]
    buffer_df = outlier_fx(buffer_df, 'price_per_night')
    # Date start counted as min() in booking_date, ane end counted as max()
    customer_id_num, joblib_id = load_id() 
    start_search = str(buffer_df['booking_date'].min())
    end_search = str(buffer_df['booking_date'].max())
    charts = {
        "key_id":joblib_id,
        "datetime_push":"",
        "status_code":"",
        "status_message":"",
        "customer_id":customer_id_num,
        "date_start":start_search,
        "date_end":end_search,
        "result":[]
    }

    import warnings
    warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
    warnings.simplefilter(action='ignore', category=FutureWarning)
    def to_serializable_list(seq):
        out = []
        for v in seq:
            # --- STEP 1: Handle NaN immediately ---
            if isinstance(v, float) and math.isnan(v):
                out.append(0)
                continue
            if isinstance(v, np.floating) and math.isnan(v):  # covers np.float32, np.float64
                out.append(0)
                continue

            # --- STEP 2: Numpy scalar (e.g., np.int64, np.float64) ---
            try:
                scalar_value = v.item()
                if isinstance(scalar_value, float) and math.isnan(scalar_value):
                    out.append(0)
                else:
                    out.append(scalar_value)
                continue
            except Exception:
                pass

            # --- STEP 3: Pandas Timestamp -> ISO format ---
            try:
                if hasattr(v, "isoformat"):
                    out.append(v.isoformat())
                else:
                    out.append(str(v))
                continue
            except Exception:
                pass

            # --- STEP 4: Fallback append ---
            out.append(v)

        # --- FINAL CLEANUP: Make sure absolutely no NaN slipped through ---
        final = []
        for val in out:
            if isinstance(val, float) and math.isnan(val):
                final.append(0)
            else:
                final.append(val)
        return final

    # CREATE FIRST ROW : KPI CARD ------------------------------------------------------------------------------------------------
    print("processing KPI section!!!")
    try:
        count_book = buffer_df.groupby('check_in')['check_in'].count()
        count_book = count_book.values.sum()
        total_nps = buffer_df.groupby('check_in')['net_amount_stay'].sum()
        total_nps = total_nps.values.sum() 
        typical_lead_days = buffer_df['lead_days'].median()
        average_stay_days = buffer_df['stay_days'].mean()

        source_data_kpi = {
            "type":"STANDARD_CSS_BOX_DISPLAY",
            "chart_slug_name": "kpi_summary",
            "dataset":{
                "total_booking":int(count_book),
                "total_net_per_stay":int(total_nps),
                "typical_lead_days":int(typical_lead_days),
                "average_stay_days":int(average_stay_days)
            }
        }          
        charts["result"].append(source_data_kpi)
        
        #  CREATE SECOND ROW ---------------------------------------------------------------------------------------------------------------
        #  OTA COUNT WITH PIE CHART, MONTHLY CHECK IN WITH BAR PLOR, DAILY CHECK IN WITH BAR PLOT
        print("processing performance section!!!")
        ota_count = buffer_df.groupby('ota_name')['ota_name'].count()
        month_check_in = buffer_df.groupby('check_in_month')['check_in_month'].count()
        day_check_in = buffer_df.groupby('check_in_weekday')['check_in_weekday'].count().sort_values(ascending=False)

        # HISTOGRAM FOR TOTAL PRICE RANGE PER MONTHLY AND YEARLY
        buffer_df['check_in'] = pd.to_datetime(buffer_df['check_in'], format='mixed')
        short_ = buffer_df[['check_in','price_per_night']]
        short_['Year'] = short_['check_in'].dt.year
        short_['Month'] = short_['check_in'].dt.month

        bin_size = 100000
        price_min = 100000
        price_max = short_['price_per_night'].max()
        if price_min < 100000:
            price_min = 100000
        bins = np.arange(price_min, price_max + bin_size, bin_size)
        short_['PriceBin'] = pd.cut(short_['price_per_night'], bins=bins, right=False)

        monthly_counts = short_.groupby(['Month', 'PriceBin']).size().reset_index(name='count')
        filter_price_df = pd.DataFrame()
        for i in range(1, len(monthly_counts['Month'].value_counts().index) + 1):
            monthly_counts_filtered = monthly_counts[monthly_counts['Month'] == i]
            X_data = [f"{int(interval.left)}-{int(interval.right)}" for interval in monthly_counts_filtered.PriceBin.values]
            Y_data = monthly_counts_filtered['count']
            name_array = ((f"price_range_per_month_{calendar.month_name[i]}" + ",") * len(Y_data)).split(",")
            del name_array[-1]
            sub_filter_price= pd.DataFrame({
                "name":name_array,
                "X_data": X_data,
                "Y_data": Y_data
            })
            filter_price_df = pd.concat([filter_price_df, sub_filter_price])

        # REVENUE, TOTAL REVENUE INCREMENT AND SEASONAL TRENDLINE
        # Setup for Seasonality and Trendline
        # ts = buffer_df.groupby('check_in')['net_amount_stay'].sum()
        # ts_monthly = ts.resample('D').sum()
        ts = average_room_rate(buffer_df)
        ts_monthly = ts

        lowess = sm.nonparametric.lowess
        lowess_value = []
        lowess_value = lowess(ts_monthly['Average Room Rate'], ts_monthly['Dates'], frac=0.02)[:,1]
        # lowess_value = [i for i in lowess_value if i > 0]

        # ts = ts.sort_index()
        ts_monthly = ts_monthly.set_index(ts_monthly["Dates"], drop=True)
        ts_monthly = ts_monthly.drop(columns='Dates')
        def dynamic_decompose(tsa): 
            def count_obs(freq):
                return len(tsa.resample(freq).sum().dropna())

            def dynamic_period(n_obs, desired_period, min_period=2):
                if n_obs < 2 * desired_period:
                    return max(min_period, n_obs // 2)
                return desired_period

            def log_info(level, freq, n_obs, period, extra=""):
                print(f"[INFO] Level={level} | Freq='{freq}' | Points={n_obs} | Period={period} {extra}")

            total_days = (tsa.index.max() - tsa.index.min()).days + 1
            if total_days < 4:
                print("[FAIL] Total dataset is too small (<4 days) for periodical analysis.")
                return None, tsa
            print(f"[INFO] Total Days={total_days}")

            freq = "M"
            desired_period = 12
            min_period = 2
            n_obs = count_obs(freq)
            print(f"n_obs is :{n_obs}")

            if n_obs >= 4:  # at least 4 months
                period = dynamic_period(n_obs, desired_period, min_period)
                log_info("Monthly", freq, n_obs, period)
                ts_resampled = tsa.resample(freq).sum()
                mode = "Monthly"
                print("Using Monthly!")
            
            else:
                freq = "W"
                desired_period = 8
                min_period = 2
                n_obs = count_obs(freq)

                if n_obs >= 4:  # at least 4 weeks
                    period = dynamic_period(n_obs, desired_period, min_period)
                    log_info("Weekly", freq, n_obs, period)
                    ts_resampled = tsa.resample(freq).sum()
                    mode = "Weekly"
                    print("Using Weekly!")
                
                else:
                    freq = "D"
                    ts_resampled = tsa.resample(freq).sum()
                    mode = "Daily"

                    # Segment into 3-day blocks
                    segment_size_1 = 3
                    segments_1 = max(1, total_days // segment_size_1)

                    if segments_1 >= 4:
                        desired_period = 5
                        min_period = 2
                        period = dynamic_period(segments_1, desired_period, min_period)
                        log_info("Daily-Level1", freq, segments_1, period, extra=f"(segment_size={segment_size_1} days)")

                    else:
                        # Segment into 2-day blocks
                        segment_size_2 = 2
                        segments_2 = max(1, total_days // segment_size_2)

                        if segments_2 >= 4:
                            desired_period = 3
                            min_period = 2
                            period = dynamic_period(segments_2, desired_period, min_period)
                            log_info("Daily-Level2", freq, segments_2, period, extra=f"(segment_size={segment_size_2} days)")
                        else:
                            # Final fallback on raw days
                            if total_days < 4:
                                print("[FAIL] Total dataset is too small (<4 days) for daily decomposition.")
                                return None, ts_resampled

                            desired_period = 4  # initial
                            min_period = 2
                            period = dynamic_period(total_days, desired_period, min_period)
                            log_info("Daily-Level3", freq, total_days, period, extra="(raw days)")

            try:
                result = seasonal_decompose(ts_resampled, model="additive", period=period)
                print("[SUCCESS] Seasonal decomposition completed successfully.")
                return result, ts_resampled
            except Exception as e:
                print(f"[ERROR] Seasonal decomposition failed: {e}")
                return math.nan, math.nan

        buffer_df['check_in'] = pd.to_datetime(buffer_df['check_in'])
        delta = buffer_df['check_in'].max() - buffer_df['check_in'].min()
        lower_date_lim = buffer_df['check_in'].min()
        upper_date_lim = buffer_df['check_in'].min()
        cur_delta = delta

        temp_buffer_index = []
        temp_buffer_values = []

        # result_mul.trend.values
        while upper_date_lim < buffer_df['check_in'].max():
            if cur_delta >= pd.Timedelta(days=31):
                add_days = pd.Timedelta(days=31)
            else:
                add_days = cur_delta

            upper_date_lim = lower_date_lim + add_days
            temp_ts_periods = buffer_df.loc[(buffer_df['check_in'] >= lower_date_lim) & (buffer_df['check_in'] <= upper_date_lim), :]
            ts_periodic = temp_ts_periods.groupby('check_in')['net_amount_stay'].sum()
            ts_per_case = ts_periodic.resample('D').sum()

            result_mul, ts_resampled = dynamic_decompose(ts_per_case)
            try:
                temp_buffer_index.append(result_mul.trend.index)
                temp_buffer_values.append(result_mul.trend.values)
            except Exception as e:
                error_summary = f"{type(e).__name__}: {e}"
                print(f"SKIPPING this due to {error_summary}")

            lower_date_lim = upper_date_lim
            cur_delta = buffer_df['check_in'].max() - upper_date_lim

        combined_dates = np.concatenate([d.values for d in temp_buffer_index])
        combined_values = np.concatenate(temp_buffer_values)

        buffer_df['check_in'] = pd.to_datetime(buffer_df['check_in'])
        lower_date_seasonal = buffer_df['check_in'].min()
        upper_date_seasonal = buffer_df['check_in'].min()
        cur_delta_seasonal = delta

        seasonal_index = []
        seasonal_values = []

        while upper_date_seasonal < buffer_df['check_in'].max():
            if cur_delta_seasonal >= pd.Timedelta(days=62):
                add_days = pd.Timedelta(days=62)
            else:
                add_days = cur_delta_seasonal

            upper_date_seasonal = lower_date_seasonal + add_days
            temp_ts_seasonal = buffer_df.loc[(buffer_df['check_in'] >= lower_date_seasonal) & (buffer_df['check_in'] <= upper_date_seasonal), :]
            ts_seasonal = temp_ts_seasonal.groupby('check_in')['net_amount_stay'].sum()
            ts_seasonal_case = ts_seasonal.resample('D').sum()

            result_mul, ts_resampled = dynamic_decompose(ts_seasonal_case)
            try:
                seasonal_index.append(result_mul.seasonal.index)
                seasonal_values.append(result_mul.seasonal.values)
            except Exception as e:
                error_summary = f"{type(e).__name__}: {e}"
                print(f"SKIPPING this due to {error_summary}")

            lower_date_seasonal = upper_date_seasonal
            cur_delta_seasonal = buffer_df['check_in'].max() - upper_date_seasonal

        combined_dates_seasonal = np.concatenate([d.values for d in seasonal_index])
        combined_values_seasonal = np.concatenate(seasonal_values)

        df_trendline = pd.DataFrame({
            'date': pd.to_datetime(combined_dates),
            'value': combined_values
        })

        df_seasonal = pd.DataFrame({
            'date_seasonal': pd.to_datetime(combined_dates_seasonal),
            'value_seasonal': combined_values_seasonal
        })

        df_trendline = df_trendline.dropna(subset=['value'])
        df_seasonal = df_seasonal.dropna(subset=['value_seasonal'])

        df_trendline = df_trendline.sort_values(by='date').reset_index(drop=True)
        df_seasonal = df_seasonal.sort_values(by='date_seasonal').reset_index(drop=True)

        final_dates = df_trendline['date'].dt.strftime('%Y-%m-%d').values
        final_values = df_trendline['value'].values

        final_dates_seasonal = df_seasonal['date_seasonal'].dt.strftime('%Y-%m-%d').values
        final_values_seasonal = df_seasonal['value_seasonal'].values

        # PLOT WITH CHART JS -------------------------------------------------------------------------------------------
        converted_month = [calendar.month_name[int(m)] for m in month_check_in.index.tolist()]
        source_data_bar = {
            1 : {
                "metatitle":"total_check_in_monthly",
                "xvalue":converted_month,
                "xlabel":"Month",
                "yvalue":month_check_in.values.tolist(),
                "ylabel":"Count",
                "popup":"",
                "headline":"Total Check-in",
                "title":"Total Check-in per Month",
                "desc":"Jumlah Check in per bulan pada periode terpilih."
            },
            2 : {
                "metatitle":"total_check_in_dayofweek",
                "xvalue":day_check_in.index.tolist(),
                "xlabel":"Weekday",
                "yvalue":day_check_in.values.tolist(),
                "ylabel":"Count",
                "popup":"",
                "headline":"Total Check-in",
                "title":"Total Check-in per Weekday",
                "desc":"Jumlah Check in harian pada periode terpilih."
            },
            3 : {
                "metatitle":"price_range_per_month",
                "xvalue":filter_price_df,
                "xlabel":"Price Range",
                "yvalue":filter_price_df,
                "ylabel":"Count",
                "popup":"",
                "headline":"Price Range",
                "title":"Price Range per Month",
                "desc":"Jumlah booking pada harga tertentu dalam satu bulan. Jumlah bookingan tiap rentang harga dirata-rata setiap bulan sepanjang periode terpilih."
            },
            # 4 : {
            #     "metatitle":"price_range_per_year",
            #     "xvalue":x_year,
            #     "xlabel":"Price Range",
            #     "yvalue":year_aggr.values.tolist(),
            #     "ylabel":"Count",
            #     "popup":"",
            #     "headline":"Price Range",
            #     "title":"Price Range per Year",
            #     "desc":"Jumlah booking pada harga tertentu dalam satu tahun. Jumlah bookingan tiap rentang harga dirata-rata setiap tahun sepanjang periode terpilih."
            # }
        }

        source_data_line = {
            0 : {
                "metatitle":"daily_arr_price",
                "xvalue":ts_monthly.index.strftime('%Y-%m-%d'),
                "xlabel":"Days",
                "yvalue":lowess_value,
                "ylabel":"ARR",
                "popup":"",
                "headline":"Price",
                "title":"Daily ARR Price",
                "desc":"Menujukkan nilai historikal ARR properti setiap harinya."
            },
            1 : {
                "metatitle":"arr_trend",
                "xvalue":final_dates,
                "xlabel":"Period",
                "yvalue":final_values,
                "ylabel":"ARR",
                "popup":"",
                "headline":"Price",
                "title":"ARR Price Trend",
                "desc":"Menunjukkan trend ARR properti, misal apabila minggu lalu total ARR 100 juta, dan minggu sekarang 200 juta, maka trend akan menunjukkan kenaikan 100 juta."
            },
            2 : {
                "metatitle":"arr_seasonal_pattern",
                "xvalue":final_dates_seasonal,
                "xlabel":"Period",
                "yvalue":final_values_seasonal,
                "ylabel":"ARR",
                "popup":"",
                "headline":"Price",
                "title":"ARR Seasonal Pattern",
                "desc":"Menunjukkan pola berulang dalam periode tertentu. Misalnya, rata-rata pendapatan mingguan adalah 100 juta. Jika pada hari Senin pendapatan adalah 120 juta, maka seasonality hari Senin adalah +20 juta. Jika hari Selasa hanya 80 juta, maka seasonality hari Selasa adalah –20 juta."
            },
            # 3 :  {
            #     "xvalue":result_mul.seasonal.index,
            #     "xlabel":"Smoothed Value",
            #     "yvalue":lowess_value,
            #     "ylabel":"Net per Stay",
            #     "popup":"",
            #     "title":"Smoothed Value"
            # }
        }

        # Chart.js JSON template for a single bar chart
        chart_template_bar = {
            "type": "bar",
            "chart_slug_name":"",
            "dataset": [
                {
                    "name": "",
                    "data":[]
                }
            ], 
            "notes":{
                "judul":"",
                "desc":""
            }
        }

        chart_template_line = {
            "type": "line",
            "chart_slug_name":"",
            "dataset": [
                {
                    "name": "",
                    "data":[]
                }
            ], 
            "notes":{
                "judul":"",
                "desc":""
            }
        }

        for i in range(1, 7):
            if i < 3:
                # deep copy the template so nested dicts aren't shared
                sub_mini_field = {"x":"", "y":""}
                mini_data_field = []
                chart = copy.deepcopy(chart_template_bar)
                src = source_data_bar[i]

                chart['chart_slug_name'] = src['metatitle']
                chart['dataset'][0]['name'] = src.get('headline', '')
                # normalize lists to plain Python scalars
                labels = to_serializable_list(src['xvalue'])
                values = to_serializable_list(src['yvalue'])

                # fill chart
                for k in range(len(labels)):
                    mini_field = copy.deepcopy(sub_mini_field)
                    mini_field["x"] = labels[k]
                    mini_field["y"] = values[k]
                    mini_data_field.append(mini_field)
                chart['dataset'][0]['data'] = mini_data_field

                chart['notes']['judul'] = src.get('title', '')
                chart['notes']['desc'] = src.get('desc', '')
                charts["result"].append(chart)
            if i == 3:
                src = source_data_bar[i]

                # new_dataset_array = []
                name_range_list = source_data_bar[i]["xvalue"]["name"].value_counts().index.tolist()
                for k in name_range_list:
                    chart = copy.deepcopy(chart_template_bar)
                    groupby_buffer = source_data_bar[i]["xvalue"].loc[(source_data_bar[i]["xvalue"]["name"] == k), :].reset_index(drop=True)
                    # content_new = {"name":"", "data":[]}
                    sub_content_new = {"x":"", "y":""}
                    sub_data_array = []
                    for j in range(len(groupby_buffer)):
                        sub_content_new_copy = copy.deepcopy(sub_content_new)
                        sub_content_new_copy["x"] = str(groupby_buffer.iloc[j, 1])
                        sub_content_new_copy["y"] = int(groupby_buffer.iloc[j, 2])
                        sub_data_array.append(sub_content_new_copy)
                    # content_new_copy = copy.deepcopy(content_new)
                    # content_new_copy["name"] = k
                    # content_new_copy["data"] = sub_data_array
                    # new_dataset_array.append(content_new_copy)
                    chart["chart_slug_name"] = k
                    chart["dataset"][0]["name"] = src.get('headline', '')
                    chart["dataset"][0]["data"] = sub_data_array
                    # chart['dataset'] = new_dataset_array
                    # chart['chart_slug_name'] = src['metatitle']
                    charts["result"].append(chart)
                    chart['notes']['judul'] = src.get('title', '')
                    chart['notes']['desc'] = src.get('desc', '')
            if i > 3:
                sub_mini_field = {"x":"", "y":""}
                mini_data_field = []
                chart = copy.deepcopy(chart_template_line)
                src = source_data_line[i-4]

                chart['chart_slug_name'] = src['metatitle']
                chart['dataset'][0]['name'] = src.get('headline', '')
                # normalize lists to plain Python scalars
                labels = to_serializable_list(src['xvalue'])
                values = to_serializable_list(src['yvalue'])

                # fill chart
                for k in range(len(labels)):
                    mini_field = copy.deepcopy(sub_mini_field)
                    mini_field["x"] = labels[k]
                    mini_field["y"] = values[k]
                    mini_data_field.append(mini_field)
                chart['dataset'][0]['data'] = mini_data_field

                chart['notes']['judul'] = src.get('title', '')
                chart['notes']['desc'] = src.get('desc', '')
                charts["result"].append(chart)
        
        # CREATE OTA COUNT DONUT CHART -------------------------------------------------------------------------------
        ota_count = buffer_df[['ota_name','lead_days','price_per_night']].reset_index(drop=True)
        bins_array = []

        name_dataset = {
            1: {"title":"ota_composition_overview_15"},
            2: {"title":"ota_composition_overview_67"},
            3: {"title":"ota_composition_overview_814"},
            4: {"title":"ota_composition_overview_1521"},
            5: {"title":"ota_composition_overview_2235"},
            6: {"title":"ota_composition_overview_3690"},
            7: {"title":"ota_composition_overview_90plus"}
        }
        for i in range(len(ota_count)):
            if 1 <= ota_count.iloc[i, 1] <= 5:
                bins_array.append(1)
            elif 6 <= ota_count.iloc[i, 1] <= 7:
                bins_array.append(2)
            elif 8 <= ota_count.iloc[i, 1] <= 14:
                bins_array.append(3)
            elif 15 <= ota_count.iloc[i, 1] <= 21:
                bins_array.append(4)
            elif 22 <= ota_count.iloc[i, 1] <= 35:
                bins_array.append(5)
            elif 36 <= ota_count.iloc[i, 1] <= 90:
                bins_array.append(6)
            else:
                bins_array.append(7)
        ota_count['categories_stay'] = bins_array
        major_donut_template = {
            "type":"doughnut",
            "chart_slug_name":"",
            "dataset":[],
            "notes":{
                "judul":"Komposisi jumlah booking",
                "desc": "Menunjukan jumlah booking per OTA berdasarkan rentang lead-days."
            }
        }
        
        for i in ota_count['categories_stay'].value_counts().index:
            donut_chart = copy.deepcopy(major_donut_template)
            tempo_buffer = ota_count[(ota_count['categories_stay'] == i)]
            sub_list_filter = []
            for k, v in tempo_buffer['ota_name'].value_counts().items():
                container_filter = {
                    "name": k,
                    "data": v
                }
                sub_list_filter.append(container_filter)
            donut_chart["chart_slug_name"] = name_dataset[i]["title"]
            donut_chart["dataset"] = sub_list_filter
            charts["result"].append(donut_chart)

        # CREATE "BOXPLOT" ---------------------------------------------------------------------------------------------------------------
        print("processing boxplot section!!!")
        major_boxplot_template = {
            "type":"boxplot",
            "chart_slug_name": "ota_price_distribution_overview",
            "dataset":[],
            "notes":{
                "judul":"Distribusi harga per malam.",
                "desc": "Menunjukan distribusi harga per malam sebuah kamar untuk setiap OTA. Rentang harga dalam kotak adalah yang paling sering muncul, dan garis tengah dalam kotak merupakan tipikal harga yang sering dipasang oleh OTA tersebut."
            }
        }
        chart_template_boxplot = []
        
        # charts2 = {}
        ota_list = [i for i in buffer_df['ota_name'].unique()]
        for i in range(len(ota_list)):
            temp = buffer_df.loc[(buffer_df['ota_name'] == ota_list[i]),:]
            median_val = temp['price_per_night'].median()
            Q1 = temp['price_per_night'].quantile(0.25)
            Q3 = temp['price_per_night'].quantile(0.75)
            IQR = Q3 - Q1
            min_val = Q1 - 1.5 * IQR
            max_val = Q3 + 1.5 * IQR

            subset_boxplot = {
                    "name":ota_list[i],
                    "data":[min_val, Q1, median_val, Q3, max_val]
                }
            chart_template_boxplot.append(subset_boxplot)
        major_boxplot_template["dataset"] = chart_template_boxplot
        charts["result"].append(major_boxplot_template)

        charts["datetime_push"] = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
        charts["status_code"] = 2
        charts["status_message"] = "Data successfully processed!"
        chartjs_to_endpoint(charts)
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        charts["datetime_push"] = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
        charts["status_code"] = 3
        charts["status_message"] = error_summary
        charts["date_start"] = ""
        charts["date_end"] = ""
        charts["result"] = []
        chartjs_to_endpoint(charts)

     # DEBUG PLOT ---------------------------------------------------------------------
    # folder_path_debug = "/workspaces/Ecommerce-Project/debug_plot"
    # os.makedirs(folder_path_debug, exist_ok=True)

    # file_path = os.path.join(folder_path_debug, "my_plot.json")
    # with open(file_path, "w") as f:
    #     f.write(json_data)

# @app.get("/process-data")
def process_data():
    try:
        print("DEBUG: process_data() STARTED")
        print(f"[DEBUG] CURR_DIR is: {CURR_DIR}")
        df = fetch_json_from_api(CURR_DIR)
        if isinstance(df, str):
            raise RuntimeError("DF is empty!")
        print("Combined dataframe shape:", df.shape)
        df = preprocess_df(df)
        print("After preprocess shape:", df.shape)
        # processed_data = df.to_dict(orient="records")
        client_name = [i for i in df['customer_id'].unique()]
        for j in client_name:
            plotly_preprocess(df, j)
        print("Process finished, check your Webhook please")

        file_path = ["cust_details.json", "buffer.json"]  # Replace with the actual file path
        for i in file_path:
            if os.path.exists(i):
                os.remove(i)
                print(f"File '{i}' deleted successfully.")
            else:
                print(f"File '{i}' does not exist.")

        return { 
            "status": "2 : Process Finished",
            "message": "Finished processing data, check the Endpoint to see JSON results"
        }
    except Exception as e:
        error_summary = f"{type(e).__name__}: {e}"
        customer_id_num, joblib_id = load_id() 
        charts = {
            "key_id":joblib_id,
            "datetime_push":datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S"),
            "status_code":"3",
            "status_message":error_summary,
            "customer_id":customer_id_num,
            "date_start":"",
            "date_end":"",
            "result":[]
        }
        chartjs_to_endpoint(charts)
        return error_summary

@app.get("/process-data")
def process_endpoint():
    return process_data()
