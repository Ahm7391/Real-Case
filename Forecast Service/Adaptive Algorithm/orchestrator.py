import subprocess
import sys, os, json
import time
import logging
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, Request
from pydantic import BaseModel

app = FastAPI(title="Forecast Pipeline Orchestrator")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PIPELINES = [
    os.path.join(BASE_DIR, "adaptive_pipeline_infer.py"),
    os.path.abspath(os.path.join(BASE_DIR, "..", "Machine Learning Development", "mcl_pipeline_infer.py")),
]

def run_pipeline(script, job_id: str, customer_id: str):
    script_dir = os.path.dirname(os.path.abspath(script))
    logging.info(f"Running {script} for Job ID: {job_id}, Customer ID: {customer_id}...")
    subprocess.run([sys.executable, script, str(job_id), str(customer_id)], check=True, cwd=script_dir)
    logging.info(f"Finished {script} for Job ID: {job_id}")

def execute_forecast_sequence(job_id: str, customer_id: str):
    logging.info(f"=== Forecast Sequence STARTED for Job: {job_id}, Customer: {customer_id} ===")
    try:
        for pipeline in PIPELINES:
            run_pipeline(pipeline, job_id, customer_id)
        logging.info(f"=== Forecast Sequence COMPLETED for Job: {job_id} ===")
    except Exception as e:
        logging.error(f"Error executing pipeline sequence for Job {job_id}: {e}")

@app.api_route("/forecast-service-call", methods=["GET", "POST"])
async def forecast_service_call(
    request: Request,
    background_tasks: BackgroundTasks,
    job_id: Optional[str] = None,
    customer_id: Optional[str] = None,
    start_date: Optional[str] = None,
    finish_date: Optional[str] = None,
):
    payload_data = {}
    try:
        payload_data = await request.json()
    except Exception:
        pass

    if not isinstance(payload_data, dict):
        payload_data = {}

    query_params = dict(request.query_params)

    resolved_job_id = (
        payload_data.get("job_id")
        or query_params.get("job_id")
        or job_id
        or f"JOB_FC_{int(time.time())}"
    )
    resolved_customer_id = (
        payload_data.get("customer_id")
        or query_params.get("customer_id")
        or customer_id
        or "1"
    )

    logging.info(f"Received forecast trigger from Laravel: Job ID={resolved_job_id}, Customer ID={resolved_customer_id}")

    # Dispatch to background task so the FastAPI endpoint returns immediately within Laravel's 5s timeout
    background_tasks.add_task(execute_forecast_sequence, str(resolved_job_id), str(resolved_customer_id))

    return {
        "status": "success",
        "job_id": str(resolved_job_id),
        "customer_id": str(resolved_customer_id),
        "message": "Forecasting sequence dispatched to background worker."
    }

