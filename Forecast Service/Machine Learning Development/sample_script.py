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
from datetime import datetime
from statsmodels.tsa.seasonal import STL
import optuna, traceback, pickle, gc, sys


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
from tensorflow.keras.callbacks import EarlyStopping

from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo
from keras.models import load_model
import warnings
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=pd.errors.SettingWithCopyWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

TASKS = {}

def task(fn):
    TASKS[fn.__name__] = fn
    return fn

@task
def pickup_rate_correction(check_df):
    try:
        check_df['booking_date'] = pd.to_datetime(check_df['booking_date'])
        check_df['check_in'] = pd.to_datetime(check_df['check_in'])

        daily_counts = check_df.groupby(['booking_date', 'check_in']).size().reset_index(name='daily_bookings')
        daily_counts['lead_days'] = (daily_counts['check_in'] - daily_counts['booking_date']).dt.days
        daily_counts['cumulative_bookings'] = daily_counts.groupby('check_in')['daily_bookings'].cumsum()
        daily_counts['daily_pickup'] = daily_counts.groupby('check_in')['cumulative_bookings'].diff()
        daily_counts['delta_lead_days'] = abs(daily_counts.groupby('check_in')['lead_days'].diff())
        first_day = daily_counts.groupby('check_in')['cumulative_bookings'].transform('first')
        first_lead_days = daily_counts.groupby('check_in')['lead_days'].transform('first')
        daily_counts['cumulative_pickup_rate'] = ((daily_counts['cumulative_bookings'] - first_day) / first_day.replace(0, pd.NA))
        daily_counts['booking_rate'] = (daily_counts['cumulative_bookings'] / abs(daily_counts['lead_days'] - first_lead_days))
        for i in range(len(daily_counts['booking_rate'])):
            if daily_counts['booking_rate'][i] == np.inf:
                daily_counts['booking_rate'][i] = (daily_counts['cumulative_bookings'][i] / daily_counts['lead_days'][i])
        daily_counts['booking_rate'] = daily_counts['booking_rate'].replace(np.inf, 0)

        counter_days = daily_counts['check_in'].min()
        max_date = daily_counts['check_in'].max()
        while counter_days <= max_date:
            inspection = daily_counts[daily_counts['check_in'] == counter_days]
            if len(inspection) > 0:
                if inspection["booking_date"].values[-1] < inspection["check_in"].values[-1]:
                    first_lead_days = inspection['lead_days'].values[0]
                    correction_rate = inspection["cumulative_bookings"].values[-1] / first_lead_days
                    daily_counts.loc[daily_counts['check_in'] == counter_days, 'booking_rate'] = correction_rate
            counter_days = counter_days + timedelta(days=1)
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
def continuous_occ_rate_correction(df_master, remaining_room, mem_buffer,
                                   mem_buffer_ckout, max_room_number, avail_percentage):
    try:
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
            avail_occupancy = int((avail_percentage / 100) * max_room_number)
            occupied_percentage = ((avail_occupancy - rooms_left) / avail_occupancy) * 100
            # occupancy_rate = occupied_percentage - 100
            occupancy_rate = occupied_percentage
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
    except KeyError as e:
        print("[continuous_occ_rate_correction] Missing column:", e)
        traceback.print_exc()
        raise

    except (TypeError, ValueError, IndexError, AttributeError) as e:
        print("[continuous_occ_rate_correction] Invalid DataFrame:", e)
        traceback.print_exc()
        raise

    except Exception as e:
        print("[continuous_occ_rate_correction] Unexpected critical error:", e)
        traceback.print_exc()
        raise

@task
def occupancy_rate_correction(occ, avail_room, avail_percentage):
    try:
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
            avail_occupancy = int((avail_percentage / 100) * avail_room)
            occupied_percentage = ((avail_occupancy - rooms_left) / avail_occupancy) * 100
            # occupancy_rate = occupied_percentage - 100
            occupancy_rate = occupied_percentage
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
def segmentation_step(sub_dfa, customer_name):
    sub_dfb = sub_dfa[sub_dfa['customer_name'] == customer_name]
    sub_dfb = outlier_fx(sub_dfb, 'price_per_night')
    best_k_val = segmentation_data(sub_dfb)
    best_gmm = GaussianMixture(n_components=best_k_val, random_state=0).fit(sub_dfb[['price_per_night']])
    labels = best_gmm.predict(sub_dfb[['price_per_night']])
    sub_dfb['cluster'] = labels
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
                          buff_p, buffer_date, y_pred_master, comprate_calc, booking_rt):
    try:
        pairing = zip(buffer_date.values[-len(y_pred_master):], y_pred_master)
        min_date = buffer_date.values[-len(y_pred_master):].min() - pd.Timedelta(days=365)

        alpha = master_lib['corr_constant'][0]
        beta = master_lib['corr_constant'][1]
        gamma = master_lib['corr_constant'][2]
        delta = master_lib['corr_constant'][3]
        epsilon = master_lib['corr_constant'][4]
        zeta = master_lib['corr_constant'][5]
        caged = {}
        for i in pairing:
            if i[0] in aggregate.index:
                corr_price = i[1] * (1 + (alpha * (aggregate.loc[i[0]] / 100)))
            else:
                corr_price = i[1] * (1 + (alpha * 0))

            if i[0] in comprate_calc['Date'].values:
                if (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values != 0) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values == 0):
                    print("Adjusting competitor rate based on last minute but using standard pricing.")
                    extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value']
                    corr_price = corr_price * (1 + epsilon * extracted_pct)
                elif (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values == 0) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values != 0):
                    print("Adjusting competitor rate based on last minute but using lowest rate pricing.")
                    if corr_price <= comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values:
                        corr_price = comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values
                    else:
                        corr_price = corr_price
                else:
                    print("Adjusting competitor rate using lowest standard pricing.")
                    extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value'].values
                    corr_price = corr_price * (1 + epsilon * extracted_pct)
                    # print(f"Competitor rate corrected price at date {i[0]}, with percentage {extracted_pct}%")

            if i[0] in booking_rt['check_in'].values:
                extracted_brate = float(booking_rt.loc[(booking_rt['check_in'] == i[0]), 'booking_rate'].values)
                corr_price = corr_price * (1 + (zeta * extracted_brate))

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
                          buff_p, ts_data, y_pred_master, comprate_calc, booking_rt):
    print("Applying correction")
    try:
        pairing = zip(ts_data.index[-len(y_pred_master):], y_pred_master)
        min_date = ts_data.index[-len(y_pred_master):].min() - timedelta(days=365)

        alpha = master_lib['corr_constant'][0]
        beta = master_lib['corr_constant'][1]
        gamma = master_lib['corr_constant'][2]
        delta = master_lib['corr_constant'][3]
        epsilon = master_lib['corr_constant'][4]
        zeta = master_lib['corr_constant'][5]
        caged = {}
        print(pairing)
        for i in pairing:
            if i[0] in aggregate.index:
                corr_price = i[1] * (1 + (alpha * (aggregate.loc[i[0]] / 100)))
            else:
                corr_price = i[1] * (1 + (alpha * 0))

            if i[0] in comprate_calc['Date'].values:
                if (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values != 0) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values == 0):
                    print("Adjusting competitor rate based on last minute but using standard pricing.")
                    extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value']
                    corr_price = corr_price * (1 + epsilon * extracted_pct)
                elif (comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Lead Days"].values < 7) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Average Value"].values == 0) and (
                    comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values != 0):
                    print("Adjusting competitor rate based on last minute but using lowest rate pricing.")
                    if corr_price <= comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values:
                        corr_price = comprate_calc.loc[(comprate_calc["Date"] == i[0]), "Min Value"].values
                    else:
                        corr_price = corr_price
                else:
                    print("Adjusting competitor rate using lowest standard pricing.")
                    extracted_pct = comprate_calc.loc[(comprate_calc['Date'] == i[0]), 'Average Value'].values
                    corr_price = corr_price * (1 + epsilon * extracted_pct)
                    # print(f"Competitor rate corrected price at date {i[0]}, with percentage {extracted_pct}%")

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
        occ_data_buffer_infer, _ = occupancy_rate_correction(segment_n, avail_room, avail_percentage)
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
# ============================================= END SECTION  ===============================================

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
def prediction_sequence(df_input, correction_active=True, optuna_active=True, adaptive_standby=True):
    loaded_model = model
    # debug_model = model
    forecast_horizon = 7
    customer_id_num, joblib_id, delta_days, total_room = load_id() 
    start_search = str(df_input['booking_date'].min())
    end_search = str(df_input['booking_date'].max())
    MAX_FUTURE = delta_days 

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
        "customer_id":customer_id_num,
        "date_start":start_search,
        "date_end":end_search,
        "result":[],
        "comprate_early_booking": [],
        "comprate_last_minute": []
    }
    try:
        for j in df_input['customer_name'].unique():
            print(f"===========PROCESSING CUSTOMER {j}================")
            only_once_active = True
            print("Extracting necessary constants library.")
            master_lib = load_constants("reserved_for_test")
            master_lib["total_room"] = total_room

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
                # starting_date = segment_n['booking_date'].max() - timedelta(days=365)
                starting_date = segment_n['booking_date'].min()
                algo_df = segment_n[segment_n['booking_date'] >= starting_date]
                # max_booking_date = segment_n['booking_date'].max()
                max_booking_date = datetime.datetime.now().strftime("%Y-%m-%d")
                print(f"check segment_n before process: {segment_n.shape}")
                if len(segment_n) < 50:
                    print("CAUTION: NOT ENOUGH DATA TO PROCESS THIS SEGMENT, SKIPPING THIS CLUSTER!!!")
                    continue

                main_storage[n] = adaptive_price_storage.copy()
                infer_main_storage[n] = adaptive_price_storage_infer.copy()

                X, y = [], []
                segment_n['check_in'] = pd.to_datetime(segment_n['check_in'])
                ts = segment_n[segment_n['check_in'] <= pd.to_datetime(max_booking_date)] # clipping for model
                ts = ts.groupby('check_in')['price_per_night'].mean()
                ts_monthly = ts.resample('D').mean()
                ts_monthly = ts_monthly.dropna()

                lowess = sm.nonparametric.lowess
                lowess_value = []
                lowess_value = lowess(ts_monthly.values, ts_monthly.index, frac=0.02)[:,1]
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

                upper_sub_dat = []
                if X.shape[0] >= 90:
                    print("Data is sufficient enough, continuing!")
                    n_samples = len(X)
                    train_size = int(n_samples * 0.85)

                    X_train, X_test = X[:train_size], X[train_size:]
                    y_train, y_test = y[:train_size], y[train_size:]

                    if extra_steps == True:
                        print("Dataset is less than 500, applying mixup.")
                        X_train, y_train = mixup(X_train, y_train, alpha=0.4, augment_factor=1.2)
                        # X, y = mixup(X, y, alpha=0.4, augment_factor=1.2)
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

                    print("decoder_train:", X_decoder_train.shape)
                    # print("validation_train:  ", X_decoder_val.shape)
                    print("Test_enc_dec : ", X_decoder_test.shape)
                    print("Main X size: ", X_decoder.shape)

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
                        occ_data_buffer, _ = occupancy_rate_correction(algo_df, avail_room, avail_percentage)
                        ckin_data_buffer = pickup_rate_correction(algo_df)
                        buffer_pred_debug = occ_data_buffer[(occ_data_buffer['Dates'] >= ts_monthly.index[-len(y_pred_mean):].min()) &
                                    (occ_data_buffer['Dates'] <= ts_monthly.index[-len(y_pred_mean):].max())]
                        comprate_factor = comprate_correction(occ_rate=buffer_pred_debug, cust_name=j, master_lib=master_lib, job_sched=2)
                        aggregated_ckin = ckin_data_buffer.groupby('check_in')['cumulative_pickup_rate'].max()
                        aggregated_ckin.resample('D').max()
                        booking_rate = ckin_data_buffer.groupby('check_in')['booking_rate'].last()
                        booking_rate.resample('D').last()
                        booking_rate = booking_rate.reset_index(drop=False)
                        booking_rate['check_in'] = pd.to_datetime(booking_rate['check_in'])

                        result_caged_debug = correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred_debug,
                                                            ts_monthly, y_pred_mean, comprate_factor, booking_rate)
                        custom_error_mae = mean_absolute_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                        custom_error_mape = mean_absolute_percentage_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                        print(f'This model has performance with mape: {100 * custom_error_mape:.2f} %')
                        print(f'This model has performance with mae: {custom_error_mae}')

                    if optuna_active == True:
                        print("Optuna algorithm is active.")
                        corrections = optuna_algorithm(segment_n, ts_monthly, y_pred_mean,
                                                        aggregated_ckin, buffer_pred_debug, booking_rate, comprate_factor)
                        pointer = 0
                        for k, v in corrections.items():
                            master_lib["corr_constant"][pointer] = v
                            pointer += 1
                        result_caged_debug = correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred_debug,
                                                            ts_monthly, y_pred_mean, comprate_factor, booking_rate)
                        print(f"Optuna correction has been applied, the latest performance result is: ")
                        custom_error_mae = mean_absolute_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                        custom_error_mape = mean_absolute_percentage_error(ts_monthly.values[-len(y_pred_mean):], result_caged_debug.values)
                        print(f'This model has performance with mape: {100 * custom_error_mape:.2f} %')
                        print(f'This model has performance with mae: {custom_error_mae}')

                    # debug_aa_dictionaries = feeder_adaptive_algorithm(dates_buffer=dates_buffer, y_pred_mean=y_pred_mean, 
                    #                                                   y_test_mean=y_test_mean, ckin_data_buffer=ckin_data_buffer, 
                    #                                                   booking_rate=booking_rate, occ_data_buffer=occ_data_buffer, job_sched=1, n=n)  
                    
                    print("=====================INFERENCE STEP=========================")
                    print(f"===========UPDATING BATCH {j}===================")
                    early_stop = EarlyStopping(
                        monitor='loss',
                        patience=3,
                        restore_best_weights=True
                    )

                    reduce_lr = keras.callbacks.ReduceLROnPlateau(
                        factor=0.5, patience=3, monitor='loss', verbose=1
                    )

                    loaded_model.fit([X, X_decoder], y, epochs=30,
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
                    max_date = mod_date + timedelta(days=(MAX_FUTURE + offset_time))
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
                        # occ_data_buffer, _ = occupancy_rate_correction(algo_df, avail_room, avail_percentage)
                        # ckin_data_buffer = pickup_rate_correction(algo_df)
                        buffer_pred = occ_data_buffer[(occ_data_buffer['Dates'] >= buffer_date.values.min()) &
                                    (occ_data_buffer['Dates'] <= buffer_date.values.max())]
                        comprate_factor = comprate_correction(occ_rate=buffer_pred, cust_name=j, master_lib=master_lib, job_sched=2)
                        # aggregated_ckin = ckin_data_buffer.groupby('check_in')['cumulative_pickup_rate'].max()
                        # aggregated_ckin.resample('D').max()
                        booking_rate = ckin_data_buffer.groupby('check_in')['booking_rate'].last()
                        booking_rate.resample('D').last()
                        booking_rate = booking_rate.reset_index(drop=False)
                        booking_rate['check_in'] = pd.to_datetime(booking_rate['check_in'])

                        result_caged = inference_correction_applicator(segment_n, "reserved_for_test", master_lib, aggregated_ckin, buffer_pred, 
                                                            buffer_date, future_pred, comprate_factor, booking_rate)
                        print(f"type of buffer_date: {type(buffer_date.values[-len(future_pred):])}")
                        sub_dat = {
                            "type": "line_chart",
                            "chart_slug_name":"forecast_result",
                            "pred_res":[int(i[0]) for i in result_caged.values],
                            "baseline_pred":future_pred.flatten().tolist(),
                            "x_axis":pd.to_datetime(buffer_date.values[-len(future_pred):]).strftime('%Y-%m-%d').tolist(),
                            "mape":f"{100 * custom_error_mape:.2f} %",
                            "mae":custom_error_mae,
                            "description": "Hasil prediksi selama rentang waktu yang dipilih. Garis merah menunjukkan koreksi dynamic pricing."
                        }

                    adaptive_dat = {
                        "type": "line-and-scatter",
                        "chart_slug_name" : "abnormal-market-activities"
                    }
                    if adaptive_standby == True:
                        adaptive_dat_copy = adaptive_dat.copy()
                        full_path_suggestions = os.path.join(FOLDER_PATH_ADAPTIVE, f"results_{customer_id_num}.pkl")
                        print("Checking if there's any adaptive correction available.")
                        if os.path.exists(full_path_suggestions):
                            print("Correction data found.")
                            with open(full_path_suggestions, "rb") as x:
                                data_pkl = pickle.load(x)
                                if n < len(data_pkl["result"]):
                                    extracted_data = data_pkl["result"][n]
                                else:
                                    print(f"Data {n} not found, perhaps update needed by adaptive pipeline!")
                                    extracted_data = {
                                        "x-axis": [],
                                        "Price Baseline": [],
                                        "Recommended Price": []
                                    }

                            adaptive_df = pd.DataFrame({
                                "date_data":extracted_data["x-axis"],
                                "price_baseline":extracted_data["Price Baseline"],
                                "recommended_price":extracted_data["Recommended Price"]
                            })
                            if len(extracted_data["x-axis"]) > 0:
                                adaptive_df["date_data"] = pd.to_datetime(adaptive_df["date_data"])
                                adaptive_df = adaptive_df.loc[(adaptive_df["date_data"] >= max_date), :]
                                # adaptive_dat_copy["x-axis"] = adaptive_df["date_data"].values.strftime('%Y-%m-%d')
                                adaptive_dat_copy["x-axis"] = adaptive_df["date_data"].dt.strftime("%Y-%m-%d").tolist()
                                adaptive_dat_copy["baseline_price"] = adaptive_df["price_baseline"].values.tolist()
                                adaptive_dat_copy["adapted_price"] = adaptive_df["recommended_price"].values.tolist()
                                adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."
                            else:
                                print("No correction/abnormalities detected.")
                                adaptive_dat_copy["x-axis"] = []
                                adaptive_dat_copy["baseline_price"] = []
                                adaptive_dat_copy["adapted_price"] = []
                                adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."
                        else:
                            print("Correction data not found.")
                            adaptive_dat_copy["x-axis"] = []
                            adaptive_dat_copy["baseline_price"] = []
                            adaptive_dat_copy["adapted_price"] = []
                            adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."

                    # PRICE ADAPTIVE SYSTEM, KEMUNGKINAN INI BISA DIHAPUS
                    # prediction_pairing = pd.DataFrame({
                    #     "Dates":buffer_date.values[-len(future_pred):],
                    #     "Prediction":future_pred.flatten()
                    # })
                    # infer_aa_dictionaries = feeder_adaptive_algorithm(avail_room=avail_room,
                    #                                            avail_percentage=avail_percentage,
                    #                                            segment_n=segment_n,
                    #                                            pred_df=prediction_pairing,
                    #                                            job_sched=2, n=n)
                    upper_sub_dat.append(sub_dat)
                    upper_sub_dat.append(adaptive_dat_copy)
                elif X.shape[0] < 90:
                    adaptive_dat_copy = adaptive_dat.copy()
                    print("Data is not sufficient enough")
                    print("Skipping the segment, but in the future as the data sufficient enough, it might be able to be predicted.")
                    sub_dat = {
                        "type": "line_chart",
                        "chart_slug_name":"forecast_result",
                        "pred_res":[],
                        "baseline_pred":[],
                        "x_axis":[],
                        "mape":"",
                        "mae":"",
                        "description": "Hasil prediksi selama rentang waktu yang dipilih. Garis merah menunjukkan koreksi dynamic pricing."
                        
                    }
                    adaptive_dat_copy["x-axis"] = []
                    adaptive_dat_copy["baseline_price"] = []
                    adaptive_dat_copy["adapted_price"] = []
                    adaptive_dat_copy["description"] = "Berisikan rekomendasi harga berdasarkan deteksi kenaikan/penurunan bookingan, dimana nilai biru merupakan acuan dasar sedangkan titik merah adalah saran koreksi harga."
                    upper_sub_dat.append(sub_dat)
                    upper_sub_dat.append(adaptive_dat_copy)
                sub_details_dat[n] = upper_sub_dat
                gc.collect()
            charts["result"].append(sub_details_dat)
            charts["datetime_push"] = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
            charts["status_code"] = 2
            charts["status_message"] = "Data successfully processed!"
            if only_once_active == True:
                display_comprate, display_comprate_lm = comprate_display(occ_rate=buffer_pred, cust_name=j, master_lib=master_lib)
                charts["comprate_early_booking"] = display_comprate
                charts["comprate_last_minute"] = display_comprate_lm
                only_once_active = False
        chartjs_to_endpoint(charts, use_company_api=False)
        K.clear_session()
        del loaded_model
        del X_train
        del X_test
        del X_decoder_train
        del X_decoder
        del X_decoder_test
        del y_train
        del y_test
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
        charts["datetime_push"] = datetime.datetime.now(ZoneInfo("Asia/Makassar")).strftime("%Y-%m-%d %H:%M:%S")
        charts["status_code"] = 3
        charts["status_message"] = error_summary
        charts["date_start"] = ""
        charts["date_end"] = ""
        charts["result"] = []
        charts["comprate_early_booking"] = []
        charts["comprate_last_minute"] = []
        chartjs_to_endpoint(charts, use_company_api=False)
        K.clear_session()
        del loaded_model
        del X_train
        del X_test
        del X_decoder_train
        del X_decoder
        del X_decoder_test
        del y_train
        del y_test
        del segment_n, sub_df, algo_df, ts, ts_monthly
        gc.collect()
        raise
# ============================================= END SECTION  ===============================================
