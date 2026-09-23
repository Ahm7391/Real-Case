# Comprehensive Dockerization & Multi-Service Architecture Guide

This document outlines the architecture, step-by-step implementation, service configuration, and execution lifecycle for running the entire demo pipeline on any machine using Docker & Docker Compose.

---

## 1. System Architecture Overview

The system consists of **5 interconnected services** orchestrated via Docker Compose:

```
                                  ┌────────────────────────────────────────┐
                                  │      User Browser (Host Machine)       │
                                  └───────────────────┬────────────────────┘
                                                      │ http://localhost:8000
                                                      ▼
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ Docker Network: `demo_pipeline_network`                                                          │
│                                                                                                  │
│  ┌──────────────────────┐   SQL Query / ORM    ┌──────────────────────┐                          │
│  │   PostgreSQL 16      │ ◄─────────────────── │     Laravel App      │ (Port 8000)              │
│  │  (postgres:5432)     │                      │   (landing.blade)    │                          │
│  └──────────────────────┘                      └──────────┬───────────┘                          │
│                                                           │                                      │
│                ┌──────────────────────────────────────────┼──────────────────────────────┐       │
│                │ Internal REST calls                      │                              │       │
│                ▼                                          ▼                              ▼       │
│  ┌───────────────────────────┐         ┌───────────────────────────┐         ┌─────────────────┐ │
│  │     Analytics Service     │         │     Forecast Service      │         │ Scraping Service│ │
│  │  (FastAPI on Port 8001)   │         │ (FastAPI on Port 8002)    │         │(FastAPI on 8003)│ │
│  │   - main_pipeline.py      │         │  - orchestrator.py        │         │-scraping_demo.py│ │
│  │   - main.py               │         │  - adaptive_pipeline      │         │-fetcher_logic.py│ │
│  │   - api_connect_fetch.py  │         │  - mcl_pipeline (TF/Keras)│         │-Headless Chrome │ │
│  └─────────────┬─────────────┘         └─────────────┬─────────────┘         └────────┬────────┘ │
│                │                                     │                                │          │
│                └─────────────────────────────────────┴────────────────────────────────┘          │
│                                   Post Data Back / Progress Status                               │
│                                (POST http://laravel-app:8000/api/...)                            │
└──────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Bootstrapping & Seeding Lifecycle

When `docker compose up --build` is executed:

1. **Database Initialization (`db`)**:
   - PostgreSQL 16 image spins up and creates the initial `laravel` database.
   - A healthcheck `pg_isready -U postgres` validates database readiness.
2. **Laravel Migration & Startup (`laravel-app`)**:
   - Waits for the `db` healthcheck to pass.
   - Generates application key if not set (`php artisan key:generate`).
   - Executes all 11 database schema migrations (`php artisan migrate --force`).
   - Serves the Laravel application on `0.0.0.0:8000`.
3. **Data Seeding (`seeder-runner`)**:
   - An ephemeral worker container runs `seeders_booking_data.py`.
   - Sends batch requests to `http://laravel-app:8000/api/dummy-bookings`.
   - Seeds 1-year historical hotel booking data + 180-day future demand simulation for `customer_id = 1` into table `mockup_booking_data`.
4. **Python FastAPI Services**:
   - `analytics-service` starts Uvicorn on `0.0.0.0:8001`.
   - `forecast-service` starts Uvicorn on `0.0.0.0:8002`.
   - `scraping-service` starts Uvicorn on `0.0.0.0:8003`.
5. **Ready for User Interaction**:
   - User navigates to `http://localhost:8000` which opens `landing.blade.php`.
   - All three interactive demo buttons are fully connected to their respective backend services.

---

## 3. Demo Flow Breakdown

### Demo 1: Analytics Dashboard
- **Route / UI**: `GET /analytics-dashboard` (`resources/views/analytics/dashboard.blade.php`)
- **Action**: User selects date range and clicks calculation request.
- **Backend Flow**:
  1. `AnalyticsDashboardController::requestAnalytics()` dispatches a POST request to `http://analytics-service:8001/receive-data`.
  2. `main_pipeline.py` starts background task `main_sequence`.
  3. `api_connect_fetch.py` fetches data chunks from `http://laravel-app:8000/api/analytics-demo`.
  4. `main.py` computes statistics, aggregations, and trends, then posts calculated metrics to `http://laravel-app:8000/api/dummy-records`.
  5. Laravel stores calculated chart results in `analytics_chart_results` and updates status in `analytics_result`.

### Demo 2: Forecasting Pipeline
- **Route / UI**: `GET /forecast-service` (`resources/views/forecast/index.blade.php`)
- **Action**: User triggers the forecasting pipeline for property and room types.
- **Backend Flow**:
  1. `ForecastDashboardController::triggerForecast()` creates a pending `prediction_progress` record and signals `http://forecast-service:8002/forecast-service-call`.
  2. `orchestrator.py` launches `adaptive_pipeline_infer.py` and `mcl_pipeline_infer.py` in the background.
  3. The workers report real-time training/inference progress back to `http://laravel-app:8000/api/prediction-progress`.
  4. Once complete, predictions and dynamic pricing weights are posted to `http://laravel-app:8000/api/prediction-result`.
  5. User views interactive graphs and overrides recommendations at `GET /forecast-service/results`.

### Demo 3: OTA Scraping Demo & Console
- **Route / UI**: `GET /scraping-service` (`resources/views/scraping/index.blade.php`)
- **Action**: User starts the live scraping simulation or views real-time console streaming.
- **Backend Flow**:
  1. Frontend establishes a Server-Sent Events (SSE) stream with `http://localhost:8003/scraping-service-call`.
  2. `scraping_demo.py` manages headless Chromium webdriver and streams terminal logs back to the frontend console in real time.
  3. `fetcher_logic.py` transforms and sends competitor prices to `http://laravel-app:8000/api/scraping-competitor` and customer records to `http://laravel-app:8000/api/scraping-customer`.
  4. Data is stored in `scraped_competitor_price` and `scraped_customer` tables for comparative analytics.

---

## 4. Required Docker Files & Structure

```
project_root/
├── DOCKER_CONTAINERIZATION_GUIDE.md
├── requirements.txt
├── Dockerfile.laravel
├── Dockerfile.python
├── Dockerfile.scraper
├── docker-compose.yml
├── docker/
│   └── entrypoint-laravel.sh
├── Analytics Dashboard/
│   ├── main_pipeline.py
│   ├── main.py
│   ├── api_connect.py
│   ├── api_connect_fetch.py
│   └── seeders_booking_data.py
├── Forecast Service/
│   ├── Adaptive Algorithm/
│   │   ├── orchestrator.py
│   │   └── adaptive_pipeline_infer.py
│   └── Machine Learning Development/
│       └── mcl_pipeline_infer.py
├── Laravel Environment/
│   └── back-end-app/
│       ├── app/
│       ├── config/
│       ├── database/migrations/
│       └── ...
└── Scraping Pipeline/
    ├── scraping_demo.py
    └── fetcher_logic.py
```

---

## 5. Codebase Adjustments Checklist (Step-by-Step)

Before running the containers, the following adjustments need to be applied across the repository:

1. **Cross-Platform Lock Handler** (`adaptive_pipeline_infer.py` & `mcl_pipeline_infer.py`):
   - Replace Windows-only `msvcrt` with a platform check supporting `fcntl` on Linux and `msvcrt` on Windows.
2. **Dynamic Endpoint Resolution in Python**:
   - Update `seeders_booking_data.py`, `fetcher_logic.py`, `api_connect_fetch.py`, `main.py`, and `prediction_master.py` to read backend URLs from environment variables (`LARAVEL_API_URL`, `COMPANY_API_URL`, etc.) with fallback to `http://localhost:8000`.
3. **Dynamic Service URLs in Laravel**:
   - Update `ForecastDashboardController.php` to use `env('FORECAST_SERVICE_URL', 'http://forecast-service:8002')` instead of the hardcoded `127.0.0.1:8005`.
   - Update `config/services.php` to map all microservice URLs.
4. **Headless Chrome Options in Scraping**:
   - Ensure `scraping_demo.py` passes `--headless=new`, `--no-sandbox`, and `--disable-dev-shm-usage` when running in containerized environments.

---

## 6. How to Run the Project

```bash
# 1. Clone or navigate to the repository directory
cd /path/to/project

# 2. Build and start all services in detached mode
docker compose up --build

# 3. Open your browser and go to:
http://localhost:8000

# 4. View logs for any specific service (optional)
docker compose logs -f laravel-app
docker compose logs -f forecast-service
docker compose logs -f scraping-service

# 5. Stop all services when finished
docker compose down
```
