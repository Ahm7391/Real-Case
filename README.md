# Smart Property Analytics & ML Forecasting System

A comprehensive multi-service demo pipeline combining **Laravel 11**, **PostgreSQL 16**, and **Python FastAPI microservices** for hospitality revenue management, demand forecasting, adaptive pricing, and automated OTA scraping.

---

## Architecture Overview

```
User Browser (http://localhost:8000)
       │
       ▼
┌───────────────────────────────────────────────────────────────────────────┐
│ Docker Compose Network                                                    │
│                                                                           │
│   PostgreSQL 16 ◄─── Laravel App (Landing & REST API on Port 8000)        │
│                             │                                             │
│       ┌─────────────────────┼─────────────────────┐                       │
│       ▼                     ▼                     ▼                       │
│  Analytics Service    Forecast Service      Scraping Service              │
│ (FastAPI Port 8001)  (FastAPI Port 8002)   (FastAPI Port 8003)            │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## Quick Start (Run Locally on Any Machine)

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows, macOS, or Linux)

### 1-Step Execution

1. Clone the repository and navigate to the project directory:
   ```bash
   git clone <REPO_URL>
   cd <REPO_FOLDER>
   ```

2. Build and start all services:
   ```bash
   docker compose up --build
   ```

3. Open your browser at:
   **[http://localhost:8000](http://localhost:8000)**

---

## Interactive Feature Demos

| Demo Feature | Description | Architecture / Stack |
| :--- | :--- | :--- |
| **1. Analytics Dashboard** | Historical booking data aggregation, revenue metrics, cancellation ratios, and performance analytics. | Laravel UI ⟷ Python FastAPI (Port 8001) |
| **2. Forecasting Pipeline** | Machine learning demand prediction, Multi-Armed Bandit (MAB) adaptive pricing, and interactive rate adjustment. | Laravel UI ⟷ Python FastAPI (Port 8002) + TensorFlow / Keras |
| **3. OTA Scraping Demo** | Headless automated scraping of OTA rates with real-time log streaming directly to the browser console via Server-Sent Events (SSE). | Laravel UI ⟷ Python FastAPI (Port 8003) + Chromium Headless |

---

## Project Structure

```
├── Analytics Dashboard/              # Python analytics calculation pipeline & seeders
├── Forecast Service/                 # ML forecasting and adaptive pricing algorithms
│   ├── Adaptive Algorithm/           # MAB adaptive pricing orchestrator & workers
│   └── Machine Learning Development/ # Neural network models (TensorFlow/Keras)
├── Laravel Environment/              # Laravel 11 backend & UI dashboard
│   └── back-end-app/
├── Scraping Pipeline/                # Headless Chromium OTA scraper & fetcher
├── docker/                           # Container entrypoint & lifecycle scripts
├── Dockerfile.laravel                # PHP 8.2 Alpine image definition
├── Dockerfile.python                 # Python 3.11 ML environment
├── Dockerfile.scraper                # Python 3.11 with Chromium & Chromedriver
├── docker-compose.yml                # Multi-container orchestration
└── requirements.txt                  # Python dependencies
```
