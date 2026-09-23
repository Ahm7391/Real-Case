# Laravel & Python Scraper Streaming Integration Guide

This document outlines the architecture, existing Python implementation, and remaining tasks required on the **Laravel** side to stream real-time scraping logs to the frontend and store the scraped data.

---

## 1. Architecture Overview

```
[ Laravel Frontend (Blade/Vue/React) ]
      │
      ├─ 1. User clicks "Start Scraping" -> opens SSE EventSource
      │     GET http://127.0.0.1:8000/scraping-service-call
      │
      ▼
[ FastAPI Service (scraping_demo.py) ]
      │
      ├─ 2. Spawns Scraper in background ThreadPool
      ├─ 3. Intercepts all `log.info(...)` calls via QueueLogHandler
      ├─ 4. Streams logs in real-time back to Frontend (SSE: `data: {"log": "...", "done": false}`)
      │
[ Selenium Scraper Pipeline ]
      │ (Executes competitor & customer property scraping)
      │
      ├─ 5. When scraping completes, triggers `run_fetching()` in fetcher_logic.py
      ▼
[ Laravel Backend API ]
      │ (Receives final JSON payloads)
      ├─ POST http://localhost:8000/api/scraping-competitor
      └─ POST http://localhost:8000/api/scraping-customer
```

---

## 2. What Has Been Implemented on the Python Side

In `Scraping Pipeline/scraping_demo.py` & `Scraping Pipeline/fetcher_logic.py`:

1. **FastAPI Application with CORS Enabled**:
   - `CORSMiddleware` configured to allow connections from Laravel frontend origins (`*` or local dev URLs).
2. **Asynchronous Queue Log Handler (`QueueLogHandler`)**:
   - Captures all `log.info`, `log.error`, and `log.warning` calls from the scraping pipeline in a thread-safe manner and enqueues them into an `asyncio.Queue`.
3. **Non-Blocking Execution (`ThreadPoolExecutor`)**:
   - The heavy synchronous Selenium scraper runs in a separate worker thread so it never freezes the FastAPI async event loop.
4. **SSE Streaming Endpoint**:
   - **Route**: `GET /scraping-service-call`
   - **Response Format**: `text/event-stream`
   - **Event Payload**:
     ```json
     data: {"log": "2026-09-22 17:00:00 [INFO] Scraping competitor.", "done": false}
     ```
   - **Termination Payload**:
     ```json
     data: {"log": "2026-09-22 17:05:00 [INFO] [STREAM_JOB_FINISHED]", "done": true}
     ```
5. **Post-Scrape Data Ingestion Trigger**:
   - Upon session completion, `scraping_demo.py` executes `run_fetching()` from `fetcher_logic.py`.
   - `fetcher_logic.py` packages the scraped data into batches and sends `POST` requests to Laravel endpoints.

---

## 3. Laravel Implementation Ideas & Code Examples

### A. Frontend UI (Live Log Terminal / Console)

Place this inside your Blade view (e.g., `resources/views/scraping/index.blade.php`), Vue, or React component:

```html
<div class="p-6 bg-white dark:bg-gray-900 rounded-xl shadow-md space-y-4">
    <div class="flex items-center justify-between">
        <h2 class="text-xl font-bold text-gray-800 dark:text-gray-100">Live Scraping Console</h2>
        <div class="space-x-2">
            <span id="scraping-status" class="px-2.5 py-1 text-xs rounded-full bg-gray-200 text-gray-700">Idle</span>
            <button id="btn-start-scrape" onclick="startScrapingStream()" class="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold rounded-lg shadow">
                Start Scraping
            </button>
        </div>
    </div>

    <!-- Terminal Box -->
    <div id="log-terminal" class="h-96 w-full bg-gray-950 text-green-400 font-mono text-xs p-4 rounded-lg overflow-y-auto border border-gray-800 shadow-inner space-y-1">
        <div class="text-gray-500">// Ready. Click "Start Scraping" to begin live process...</div>
    </div>
</div>

<script>
let eventSource = null;

function startScrapingStream() {
    const terminal = document.getElementById('log-terminal');
    const statusBadge = document.getElementById('scraping-status');
    const startBtn = document.getElementById('btn-start-scrape');

    // Reset UI state
    terminal.innerHTML = '';
    startBtn.disabled = true;
    startBtn.classList.add('opacity-50', 'cursor-not-allowed');
    statusBadge.textContent = 'Running';
    statusBadge.className = 'px-2.5 py-1 text-xs rounded-full bg-amber-100 text-amber-800';

    appendLog('[SYSTEM] Connecting to Python Scraping Pipeline (SSE)...', 'text-yellow-400');

    // 1. Connect to FastAPI SSE Endpoint
    // Note: Adjust host/port if Python runs on a different port (e.g. http://127.0.0.1:8000)
    eventSource = new EventSource('http://127.0.0.1:8000/scraping-service-call');

    // 2. Listen for incoming log chunks
    eventSource.onmessage = function (event) {
        try {
            const data = JSON.parse(event.data);
            appendLog(data.log);

            // 3. Handle Completion
            if (data.done) {
                appendLog('[SYSTEM] Scraping job finished successfully. Stream closed.', 'text-emerald-400 font-bold');
                statusBadge.textContent = 'Completed';
                statusBadge.className = 'px-2.5 py-1 text-xs rounded-full bg-emerald-100 text-emerald-800';
                cleanup();
            }
        } catch (e) {
            appendLog(event.data);
        }
    };

    // 4. Handle Errors / Disconnects
    eventSource.onerror = function (err) {
        appendLog('[ERROR] Connection lost or scraper error occurred.', 'text-red-400 font-bold');
        statusBadge.textContent = 'Failed';
        statusBadge.className = 'px-2.5 py-1 text-xs rounded-full bg-red-100 text-red-800';
        cleanup();
    };

    function cleanup() {
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        startBtn.disabled = false;
        startBtn.classList.remove('opacity-50', 'cursor-not-allowed');
    }

    function appendLog(text, customClass = '') {
        const line = document.createElement('div');
        line.textContent = text;
        if (customClass) {
            line.className = customClass;
        }
        terminal.appendChild(line);
        terminal.scrollTop = terminal.scrollHeight; // Auto-scroll to bottom
    }
}
</script>
```

---

### B. Laravel Backend Endpoints for Storing Data

`fetcher_logic.py` posts data back to Laravel via:
- `POST /api/scraping-competitor`
- `POST /api/scraping-customer`

#### 1. Define Routes in `routes/api.php`
```php
use App\Http\Controllers\ScrapingDataController;

Route::post('/scraping-competitor', [ScrapingDataController::class, 'storeCompetitorData']);
Route::post('/scraping-customer', [ScrapingDataController::class, 'storeCustomerData']);
```

#### 2. Create Controller `App\Http\Controllers\ScrapingDataController.php`
```php
namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;

class ScrapingDataController extends Controller
{
    /**
     * Ingest competitor price data sent by fetcher_logic.py
     */
    public function storeCompetitorData(Request $request)
    {
        $payload = $request->all(); // List of hotel records

        if (empty($payload) || !is_array($payload)) {
            return response()->json(['message' => 'Invalid data format'], 400);
        }

        try {
            DB::transaction(function () use ($payload) {
                foreach ($payload as $item) {
                    DB::table('competitor_scraped_prices')->updateOrInsert(
                        [
                            'property_name' => $item['property_name'] ?? null,
                            'target_date'   => $item['target_date'] ?? null,
                            'room_type'     => $item['room_type'] ?? null,
                            'ota_source'    => $item['ota_source'] ?? 'booking.com',
                        ],
                        [
                            'price'       => $item['price'] ?? null,
                            'perks'       => $item['perks'] ?? null,
                            'category'    => $item['category'] ?? null,
                            'scraped_at'  => $item['scraped_at'] ?? now(),
                            'updated_at'  => now(),
                        ]
                    );
                }
            });

            return response()->json(['status' => 'success', 'records_processed' => count($payload)], 200);
        } catch (\Exception $e) {
            Log::error('Error saving competitor scraped data: ' . $e->getMessage());
            return response()->json(['status' => 'error', 'message' => $e->getMessage()], 500);
        }
    }

    /**
     * Ingest customer hotel data sent by fetcher_logic.py
     */
    public function storeCustomerData(Request $request)
    {
        $payload = $request->all();

        if (empty($payload) || !is_array($payload)) {
            return response()->json(['message' => 'Invalid data format'], 400);
        }

        try {
            DB::transaction(function () use ($payload) {
                foreach ($payload as $item) {
                    DB::table('customer_scraped_prices')->updateOrInsert(
                        [
                            'property_name' => $item['property_name'] ?? null,
                            'target_date'   => $item['target_date'] ?? null,
                            'room_type'     => $item['room_type'] ?? null,
                            'ota_source'    => $item['ota_source'] ?? 'booking.com',
                        ],
                        [
                            'price'       => $item['price'] ?? null,
                            'perks'       => $item['perks'] ?? null,
                            'category'    => $item['category'] ?? null,
                            'scraped_at'  => $item['scraped_at'] ?? now(),
                            'updated_at'  => now(),
                        ]
                    );
                }
            });

            return response()->json(['status' => 'success', 'records_processed' => count($payload)], 200);
        } catch (\Exception $e) {
            Log::error('Error saving customer scraped data: ' . $e->getMessage());
            return response()->json(['status' => 'error', 'message' => $e->getMessage()], 500);
        }
    }
}
```

---

## 4. Remaining Tasks to Complete on Laravel Side

- [ ] **1. Create / Verify Database Tables**:
  - Ensure tables (e.g. `competitor_scraped_prices` and `customer_scraped_prices`) have the columns expected by `benchmark_format` in `fetcher_logic.py`:
    - `property_name` (string)
    - `room_type` (string)
    - `ota_source` (string)
    - `price` (integer/bigint, nullable)
    - `perks` (text/string, nullable)
    - `scraped_at` (timestamp)
    - `target_date` (date/timestamp, nullable)
    - `category` (integer, nullable)
- [ ] **2. Register Ingestion API Endpoints**:
  - Verify routes in `routes/api.php` for `POST /api/scraping-competitor` and `POST /api/scraping-customer`.
  - Disable CSRF verification for these API routes (default behavior for `routes/api.php` in Laravel).
- [ ] **3. Embed the Frontend Log Terminal**:
  - Add the `EventSource` JavaScript logic to the admin dashboard / scraping management page.
  - Test opening the stream and verify that `log.info` messages render smoothly in real time.
- [ ] **4. Configure Ports / URLs in `.env`**:
  - If Python FastAPI runs on port `8001` (to avoid conflicting with Laravel on port `8000`), update:
    - In `fetcher_logic.py`: update `SCRAPING_RESULT_FEEDBACK` & `CUSTOMER_SCRAPING_RESULT` to point to Laravel's actual URL/port (e.g., `http://localhost:8000`).
    - In Frontend JS: update `new EventSource("http://127.0.0.1:8001/scraping-service-call")`.
