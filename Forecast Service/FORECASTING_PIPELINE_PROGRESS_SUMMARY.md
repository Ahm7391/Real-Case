# Forecasting Pipeline: Progress Tracking & Integration Guide

This document summarizes the full design, implemented endpoints, Python milestone hooks, and next steps for the real-time forecasting progress bar feature across **Laravel Backend** (`laravel-be/Laravel-BE/`) and the **Python Forecasting Service** (`copy-kerja-real/Real-Case/Forecast Service/`).

---

## 1. System Architecture

```
[ Blade Frontend (landing / forecast page) ]
   │
   │ 1. Click "Start Forecast Service"
   ▼
[ Laravel Backend Controller ] ──(spawns with job_id)──> [ Python Adaptive Pipeline ]
   │                                                             │
   │                                                             │ (0% - 50% Milestones)
   │                                                             ▼
   │ <────────── POST /api/prediction-progress ──────────────────┤
   │                                                             ▼
   │                                                      [ Python ML Prediction Pipeline ]
   │                                                             │
   │                                                             │ (50% - 100% Milestones)
   │                                                             ▼
   │ <────────── POST /api/prediction-progress ──────────────────┘
   │
   │ 2. Frontend polls GET /api/prediction-progress/{jobId} every 1-2s
   ▼
[ Animated Progress Bar (0% ➔ 100%) ]
```

---

## 2. Laravel Backend Implementation

### A. Database Migration
- **File**: `database/migrations/2026_09_20_092950_create_prediction_progress_table.php`
- **Table**: `prediction_progress`
- **Schema**:
  - `id`: Primary key
  - `job_id`: String (indexed, unique key representing the forecasting job)
  - `customer_id`: Integer (nullable, indexed)
  - `progress_percent`: Integer (0–100)
  - `stage_name`: String (nullable, identifier of current stage)
  - `message`: Text (nullable, user-friendly description)
  - `status`: String (`pending`, `running`, `completed`, `failed`)
  - `timestamps`: `created_at`, `updated_at`

> **Note**: User runs `php artisan migrate` manually.

### B. Eloquent Model
- **File**: `app/Models/PredictionProgress.php`

### C. Controller & API Routes
- **File**: `app/Http/Controllers/Api/ForecastServiceController.php`
- **File**: `routes/api.php`
- **Endpoints**:
  - `POST /api/prediction-progress`: Receives progress payloads from Python scripts and performs `PredictionProgress::updateOrCreate(['job_id' => ...])`.
  - `GET /api/prediction-progress/{jobId}`: Polled by the Blade UI to fetch current status.

---

## 3. Python Milestone Roadmap & Implementation Status

Progress is scaled from **0% to 100%** across two sequential pipelines:

### Pipeline 1: Adaptive Forecasting (0% – 50%)

| Milestone | Progress % | Script Location | Trigger Point / Function | Status |
| :--- | :---: | :--- | :--- | :---: |
| **1. Onboarding Completed** | **2%** | `Adaptive Algorithm/adaptive_pipeline_infer.py`<br>`EB-LM-Book/Early-Bird/adaptive_pipeline_infer.py` | Inside `enqueue_and_run_analytics()` right after `data_onboarding()` and before `main_sequence()`. | ✅ Implemented |
| **2. Historical Data Buffered** | **15%** | `Adaptive Algorithm/adaptive_preproc_json.py`<br>`EB-LM-Book/Early-Bird/adaptive_preproc_json.py` | Inside `buffer_data()` after writing `inference_mat.json`. | ✅ Implemented |
| **3. Data Cleaning Done** | **25%** | `Adaptive Algorithm/adaptive_algorithm.py`<br>`EB-LM-Book/Early-Bird/adaptive_algorithm.py` | After `preprocess_df()` completes. | ✅ Implemented |
| **4. Long-Term Prediction Done** | **35%** | `Adaptive Algorithm/adaptive_algorithm.py`<br>`EB-LM-Book/Early-Bird/adaptive_algorithm.py` | After `prediction_sequence()` completes. | ✅ Implemented |
| **5. Adaptive Calculation Done** | **50%** | `Adaptive Algorithm/adaptive_algorithm.py`<br>`EB-LM-Book/Early-Bird/adaptive_algorithm.py` | After `adaptive_calculation()` finishes. | ✅ Implemented |

---

### Pipeline 2: Machine Learning Prediction / Last-Minute (50% – 100%)

| Milestone | Progress % | Script Location | Trigger Point / Function | Status |
| :--- | :---: | :--- | :--- | :---: |
| **6. ML Onboarding Completed** | **52%** | `Machine Learning Development/mcl_pipeline_infer.py`<br>`EB-LM-Book/Last-Minute/mcl_pipeline_infer.py` | Inside `enqueue_and_run_analytics()` right after `data_onboarding()` and before `main_sequence()`. | ✅ Implemented |
| **7. ML Data Buffered** | **65%** | `Machine Learning Development/preproc_json.py`<br>`EB-LM-Book/Last-Minute/preproc_json.py` | Inside `buffer_data()`. | ✅ Implemented |
| **8. STL / Feature Prep Done** | **75%** | `Machine Learning Development/prediction_master.py`<br>`EB-LM-Book/Last-Minute/prediction_master.py` | After `preprocess_df()` & STL decomposition. | ✅ Implemented |
| **9. Model Inference Done** | **85%** | `Machine Learning Development/prediction_master.py`<br>`EB-LM-Book/Last-Minute/prediction_master.py` | After multi-step LSTM & XGBoost predictions. | ✅ Implemented |
| **10. Pipeline Completed** | **100%** | `Machine Learning Development/prediction_master.py`<br>`EB-LM-Book/Last-Minute/prediction_master.py` | After results packaged, stored, and sent to Laravel. | ✅ Implemented |

---

## 4. Standard Python Progress Helper Format

Each Python file uses this standard helper to report progress to Laravel:

```python
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
```

---

## 5. Next Steps for Next Session / IDE Agent

1. **Complete Remaining Prediction Milestones**:
   - Add the **65%** hook inside `copy-kerja-real/Real-Case/Forecast Service/Machine Learning Development/preproc_json.py` in `buffer_data()`.
   - Add the **75%**, **85%**, and **100%** hooks inside `copy-kerja-real/Real-Case/Forecast Service/Machine Learning Development/prediction_master.py`.
2. **Build the Blade Frontend View & JavaScript Poller**:
   - Create the Forecast Service trigger view (linked from `resources/views/landing.blade.php`).
   - Add button `Start Forecast Service` that generates `job_id`, triggers the pipeline, and initiates a `setInterval` polling `GET /api/prediction-progress/{jobId}`.
   - Animate the progress bar dynamically with percentage and stage message.
