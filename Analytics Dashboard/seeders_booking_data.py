#!/usr/bin/env python3
"""
Dummy Booking Generator and Seeder for Laravel Microservice.

Generates realistic hotel booking data for customer_id = 1 from 2024-01-01 to 2025-01-01
under a strict 10-room capacity constraint, then injects data into Laravel via REST API.
"""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import random
import sys
import numpy as np
import requests

# ==============================================================================
# CONFIGURATION
# ==============================================================================
CUSTOMER_ID = 1
TOTAL_ROOMS = 10
START_DATE = date(2024, 1, 1)
END_DATE = date(2025, 1, 1)

# Laravel API endpoint (Change port or path as needed)
LARAVEL_API_URL = "http://localhost:8000/api/dummy-bookings"
BATCH_SIZE = 80  # Number of records per API POST payload


# ==============================================================================
# DISTRIBUTION HELPERS
# ==============================================================================
def sample_lead_time_days() -> int:
    """
    Lead time: 0 to 30 days, median around 5 days.
    Modeled using a log-normal distribution.
    """
    val = np.random.lognormal(mean=np.log(5), sigma=0.6)
    return int(np.clip(round(val), 0, 30))


def sample_stay_days() -> int:
    """
    Stay duration: 1 to 10 days, median around 3 days.
    Modeled using a log-normal distribution.
    """
    val = np.random.lognormal(mean=np.log(3), sigma=0.5)
    return int(np.clip(round(val), 1, 10))


def sample_ota() -> int:
    """
    OTA channels 1-5, normal distribution centered at mean = 3.
    """
    val = np.random.normal(loc=3.0, scale=1.0)
    return int(np.clip(round(val), 1, 5))


def sample_room_type() -> int:
    """
    Samples room_type_id according to distribution:
    - 50% Room Type 3 (Standard Room - cheapest)
    - 30% Room Type 2 (Suite Room - most expensive)
    - 20% Room Type 1 (Family Room - mid-tier)
    """
    return int(np.random.choice([3, 2, 1], p=[0.50, 0.30, 0.20]))


def sample_price_per_night(room_type_id: int) -> int:
    """
    Price per night based on room_type_id with Gaussian noise and occasional outliers (~5% chance).
    - Room Type 2 (Suite): Most expensive (~850k base)
    - Room Type 1 (Family): Mid-tier (~500k base)
    - Room Type 3 (Standard): Cheapest (~280k base)
    """
    price_profiles = {
        3: {  # Standard (Cheapest)
            "regular": (280000, 30000, 180000, 380000),
            "high_outlier": (550000, 50000, 420000, 750000),
            "low_outlier": (110000, 20000, 60000, 160000),
        },
        1: {  # Family (Mid-tier)
            "regular": (500000, 45000, 350000, 650000),
            "high_outlier": (950000, 80000, 750000, 1250000),
            "low_outlier": (250000, 30000, 180000, 320000),
        },
        2: {  # Suite (Most expensive)
            "regular": (850000, 70000, 650000, 1100000),
            "high_outlier": (1500000, 150000, 1200000, 2000000),
            "low_outlier": (450000, 50000, 350000, 550000),
        },
    }

    profile = price_profiles.get(room_type_id, price_profiles[3])
    rand = random.random()

    if rand < 0.03:
        # High outlier (~3%)
        loc, scale, low, high = profile["high_outlier"]
    elif rand < 0.05:
        # Low outlier (~2%)
        loc, scale, low, high = profile["low_outlier"]
    else:
        # Regular price (~95%)
        loc, scale, low, high = profile["regular"]

    val = np.random.normal(loc=loc, scale=scale)
    return int(np.clip(round(val), low, high))


# ==============================================================================
# DATA GENERATION WITH OCCUPANCY CONSTRAINT
# ==============================================================================
def generate_bookings() -> list[dict]:
    """
    Iterates through each booking day from START_DATE to END_DATE.
    Simulates incoming booking requests while respecting the max room limit.
    """
    # Track occupied rooms per calendar date: {date: occupied_rooms_count}
    occupancy = defaultdict(int)
    bookings = []

    current_booking_day = START_DATE
    total_days = (END_DATE - START_DATE).days + 1

    print(f"[*] Simulating bookings for {total_days} days (Max {TOTAL_ROOMS} rooms)...")

    while current_booking_day <= END_DATE:
        # Simulate 1 to 4 customer booking attempts per day
        daily_attempts = random.randint(1, 4)

        for _ in range(daily_attempts):
            lead_time = sample_lead_time_days()
            stay_days = sample_stay_days()

            check_in_date = current_booking_day + timedelta(days=lead_time)
            check_out_date = check_in_date + timedelta(days=stay_days)

            # Check if all nights of the stay have an available room (< TOTAL_ROOMS)
            stay_nights = [
                check_in_date + timedelta(days=d) for d in range(stay_days)
            ]
            can_book = all(occupancy[night] < TOTAL_ROOMS for night in stay_nights)

            if can_book:
                # Reserve room for each night of the stay
                for night in stay_nights:
                    occupancy[night] += 1

                # Sample room type and calculate monetary details
                room_type_id = sample_room_type()
                price_per_night = sample_price_per_night(room_type_id)
                net_amount_stay = price_per_night * stay_days

                # Generate realistic timestamps (check-in at 14:00, check-out at 12:00)
                random_booking_time = time(
                    random.randint(8, 22), random.randint(0, 59), random.randint(0, 59)
                )
                booking_timestamp = datetime.combine(
                    current_booking_day, random_booking_time
                ).isoformat()
                check_in_timestamp = datetime.combine(
                    check_in_date, time(14, 0, 0)
                ).isoformat()
                check_out_timestamp = datetime.combine(
                    check_out_date, time(12, 0, 0)
                ).isoformat()

                record = {
                    "customer_id": CUSTOMER_ID,
                    "booking_date": booking_timestamp,
                    "check_in": check_in_timestamp,
                    "check_out": check_out_timestamp,
                    "net_amount_stay": net_amount_stay,
                    "ota": sample_ota(),
                    "is_confirmed": "True",
                    "room_type_id": room_type_id,
                }
                bookings.append(record)

        current_booking_day += timedelta(days=1)

    print(f"Generated {len(bookings)} valid bookings without overbooking.")
    return bookings


# ==============================================================================
# SENDER / POST FUNCTION TO LARAVEL
# ==============================================================================
def send_to_laravel(bookings: list[dict], endpoint: str = LARAVEL_API_URL):
    """
    Sends generated booking records in chunks to the Laravel API endpoint.
    """
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    total_records = len(bookings)
    print(f"[*] Posting {total_records} bookings to {endpoint} in batches of {BATCH_SIZE}...")

    success_count = 0

    for i in range(0, total_records, BATCH_SIZE):
        batch = bookings[i : i + BATCH_SIZE]
        payload = {"data": batch}

        try:
            response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
            if response.status_code in (200, 201):
                success_count += len(batch)
                print(f"-> Sent batch {i // BATCH_SIZE + 1}: {len(batch)} records [HTTP {response.status_code}]")
            else:
                print(f"Batch failed [HTTP {response.status_code}]: {response.text}", file=sys.stderr)
        except requests.exceptions.RequestException as err:
            print(f"Connection Error: {err}", file=sys.stderr)
            print("Make sure your Laravel server is up (e.g., 'php artisan serve').")
            return

    print(f"\n Finished: Successfully seeded {success_count}/{total_records} records into Laravel.")


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
if __name__ == "__main__":
    # Generate data
    dataset = generate_bookings()

    # Optional: Preview first record
    if dataset:
        print("\n--- Example Generated Record ---")
        import json
        print(json.dumps(dataset[0], indent=2))
        print("--------------------------------\n")

    # Send to Laravel
    send_to_laravel(dataset)