<?php

namespace App\Http\Controllers;

use App\Models\AnalyticsChartResults;
use App\Models\AnalyticsResult;
use App\Models\MockupBookingData;
use Carbon\Carbon;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\RedirectResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Illuminate\View\View;

class AnalyticsDashboardController extends Controller
{
    /**
     * Enforce a maximum history limit of 3 records.
     * Deletes the oldest records from both database tables (analytics_result & analytics_chart_results).
     */
    private function trimJobHistory(int $limit = 3): void
    {
        $allIds = AnalyticsResult::orderBy('id', 'desc')->pluck('id');
        if ($allIds->count() > $limit) {
            $idsToDelete = $allIds->slice($limit);
            
            // Delete associated chart results if any
            $jobKeysToDelete = AnalyticsResult::whereIn('id', $idsToDelete)->pluck('job_id_key')->filter()->all();
            if (!empty($jobKeysToDelete)) {
                AnalyticsChartResults::whereIn('job_id_key', $jobKeysToDelete)->delete();
            }

            AnalyticsResult::whereIn('id', $idsToDelete)->delete();
        }
    }

    /**
     * Display the analytics dashboard page and job request history.
     *
     * @return \Illuminate\View\View
     */
    public function index(): View
    {
        $this->trimJobHistory(3);
        $customerId = 1; // Locked to customer_id = 1 for simulation
        $history = AnalyticsResult::orderBy('id', 'desc')->take(3)->get();

        return view('analytics.dashboard', compact('customerId', 'history'));
    }

    /**
     * Submit an analytics calculation request to the Python FastAPI pipeline.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\RedirectResponse
     */
    public function requestAnalytics(Request $request): RedirectResponse
    {
        $minDate = Carbon::now()->subDays(365)->format('Y-m-d');
        $maxDate = Carbon::now()->format('Y-m-d');

        $validated = $request->validate([
            'day_start' => "required|date_format:Y-m-d|after_or_equal:{$minDate}|before_or_equal:{$maxDate}",
            'day_end' => "required|date_format:Y-m-d|after_or_equal:day_start|before_or_equal:{$maxDate}",
        ]);

        $customerId = 1; // Enforce locked customer_id = 1
        $dayStart = $validated['day_start'];
        $dayEnd = $validated['day_end'];

        $pipelineBaseUrl = rtrim(config('services.analytics.url', env('PYTHON_PIPELINE_URL', 'http://127.0.0.1:8001')), '/');
        $pipelineEndpoint = $pipelineBaseUrl . '/receive-data';

        $payload = [
            'customer_id' => (string) $customerId,
            'day_start' => (string) $dayStart,
            'day_end' => (string) $dayEnd,
        ];

        try {
            // Send request to Python pipeline
            $response = Http::timeout(5)->asJson()->post($pipelineEndpoint, $payload);

            if ($response->successful()) {
                $data = $response->json();
                $keyId = (string) ($data['key_id'] ?? ('JOB_' . time()));
                $statusCode = (int) ($data['status_code'] ?? AnalyticsResult::STATUS_IN_PROGRESS);
                $statusMessage = (string) ($data['status_message'] ?? 'Transfer is done.');

                AnalyticsResult::create([
                    'job_id_key' => $keyId,
                    'customer_id' => $customerId,
                    'status' => $statusCode,
                    'message' => $statusMessage,
                    'date_request' => Carbon::now(),
                ]);

                $this->trimJobHistory(3);

                return redirect()->route('analytics.dashboard')->with('success', "Request sent successfully to Python pipeline. Job ID: {$keyId}");
            }

            // If Python pipeline returned a non-200 response
            $errorMsg = "Pipeline error (HTTP {$response->status()}): " . ($response->json('detail') ?? $response->body() ?? 'Unknown response');
            
            AnalyticsResult::create([
                'job_id_key' => 'JOB_ERR_' . time(),
                'customer_id' => $customerId,
                'status' => AnalyticsResult::STATUS_FAULT,
                'message' => substr($errorMsg, 0, 250),
                'date_request' => Carbon::now(),
            ]);

            $this->trimJobHistory(3);

            return redirect()->route('analytics.dashboard')->with('warning', $errorMsg);
        } catch (\Throwable $e) {
            Log::warning("Failed to connect to Python pipeline at {$pipelineEndpoint}: " . $e->getMessage());

            // Connection refused or offline
            $errorMsg = "FastAPI pipeline offline at {$pipelineEndpoint}. Request recorded locally.";
            $fallbackKeyId = 'JOB_SIM_' . time();

            AnalyticsResult::create([
                'job_id_key' => $fallbackKeyId,
                'customer_id' => $customerId,
                'status' => AnalyticsResult::STATUS_IN_PROGRESS,
                'message' => 'Simulated: ' . $errorMsg,
                'date_request' => Carbon::now(),
            ]);

            $this->trimJobHistory(3);

            return redirect()->route('analytics.dashboard')->with('info', "Job {$fallbackKeyId} created. Note: Python FastAPI endpoint ({$pipelineEndpoint}) was not reachable, so initial state was queued locally.");
        }
    }

    /**
     * Handle asynchronous callback from Python pipeline to update job status.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function updateStatusFromPipeline(Request $request): JsonResponse
    {
        $keyId = $request->input('key_id', $request->input('job_id_key'));
        $statusCode = $request->input('status_code', $request->input('status'));
        $message = $request->input('status_message', $request->input('message', 'Status updated by Python pipeline.'));

        if (!$keyId || $statusCode === null) {
            return response()->json([
                'success' => false,
                'message' => 'Missing key_id or status_code.',
            ], 422);
        }

        $record = AnalyticsResult::where('job_id_key', (string) $keyId)->latest()->first();

        if (!$record) {
            return response()->json([
                'success' => false,
                'message' => "Job with key_id '{$keyId}' not found.",
            ], 404);
        }

        $record->update([
            'status' => (int) $statusCode,
            'message' => (string) $message,
        ]);

        return response()->json([
            'success' => true,
            'message' => "Job {$keyId} status updated successfully.",
            'data' => [
                'job_id_key' => $record->job_id_key,
                'status' => $record->status,
                'status_label' => $record->status_label,
                'message' => $record->message,
            ],
        ]);
    }

    /**
     * Send mockup booking information to the Python pipeline.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function sendBack(Request $request): JsonResponse
    {
        $customerId = $request->input('customer_id');
        $startDate = $request->input('start_date', $request->input('day_start'));
        $finishDate = $request->input('finish_date', $request->input('day_end'));

        $query = MockupBookingData::query();

        if ($customerId !== null && $customerId !== '') {
            $query->where('customer_id', $customerId);
        }

        if ($startDate && $finishDate) {
            $start = Carbon::parse($startDate)->startOfDay();
            $finish = Carbon::parse($finishDate)->endOfDay();
            $query->whereBetween('booking_date', [$start, $finish]);
        } elseif ($startDate) {
            $start = Carbon::parse($startDate)->startOfDay();
            $query->where('booking_date', '>=', $start);
        } elseif ($finishDate) {
            $finish = Carbon::parse($finishDate)->endOfDay();
            $query->where('booking_date', '<=', $finish);
        }

        $records = $query->orderBy('booking_date', 'asc')->get();

        $data = $records->map(function ($booking) {
            return [
                'customer_id' => (int) $booking->customer_id,
                'booking_date' => $booking->booking_date ? Carbon::parse($booking->booking_date)->format('Y-m-d H:i:s') : null,
                'check_in' => $booking->check_in ? Carbon::parse($booking->check_in)->format('Y-m-d H:i:s') : null,
                'check_out' => $booking->check_out ? Carbon::parse($booking->check_out)->format('Y-m-d H:i:s') : null,
                'net_amount_stay' => (int) $booking->net_amount_stay,
                'ota' => (int) $booking->ota,
                'is_confirmed' => (string) $booking->is_confirmed,
            ];
        })->values()->all();

        return response()->json([
            'status' => 'success',
            'data' => $data,
            'booking_data' => $data,
        ]);
    }

    /**
     * Process incoming analytics result payload from Python pipeline.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function recordsProcess(Request $request): JsonResponse
    {
        $keyId = $request->input('key_id');
        $statusCode = $request->input('status_code');
        $statusMessage = $request->input('status_message');
        $customerId = $request->input('customer_id');
        $dateStart = $request->input('date_start');
        $dateEnd = $request->input('date_end');
        $result = $request->input('result');

        if (!$keyId) {
            return response()->json([
                'success' => false,
                'message' => 'Missing key_id in request payload.',
            ], 422);
        }

        // 1. Update analytics_result if matched with job_id_key
        $analyticsRecord = AnalyticsResult::where('job_id_key', (string) $keyId)->latest()->first();
        if ($analyticsRecord) {
            $updateData = [];
            if ($statusCode !== null) {
                $updateData['status'] = (int) $statusCode;
            }
            if ($statusMessage !== null) {
                $updateData['message'] = (string) $statusMessage;
            }
            if (!empty($updateData)) {
                $analyticsRecord->update($updateData);
            }
        }

        // 2. Process result array: if non-empty list, save to analytics_chart_results
        $chartRecord = null;
        if (is_array($result) && count($result) > 0) {
            $parsedDateStart = null;
            if (!empty($dateStart)) {
                try {
                    $parsedDateStart = is_numeric($dateStart)
                        ? Carbon::createFromTimestamp($dateStart)
                        : Carbon::parse($dateStart);
                } catch (\Throwable $e) {
                    $parsedDateStart = null;
                }
            }

            $parsedDateEnd = null;
            if (!empty($dateEnd)) {
                try {
                    $parsedDateEnd = is_numeric($dateEnd)
                        ? Carbon::createFromTimestamp($dateEnd)
                        : Carbon::parse($dateEnd);
                } catch (\Throwable $e) {
                    $parsedDateEnd = null;
                }
            }

            $chartRecord = AnalyticsChartResults::create([
                'job_id_key' => (string) $keyId,
                'customer_id' => $customerId !== null ? (int) $customerId : ($analyticsRecord?->customer_id ?? 1),
                'date_start' => $parsedDateStart,
                'date_end' => $parsedDateEnd,
                'result' => $result,
            ]);
        }

        return response()->json([
            'success' => true,
            'message' => 'Payload processed successfully.',
            'data' => [
                'job_id_key' => $keyId,
                'status_updated' => (bool) $analyticsRecord,
                'chart_results_saved' => (bool) $chartRecord,
            ],
        ]);
    }

    /**
     * Preview calculated analytics charts for a specific job ID.
     *
     * @param  string  $keyId
     * @return \Illuminate\View\View|\Illuminate\Http\RedirectResponse
     */
    public function previewResults(string $keyId)
    {
        $chartRecord = AnalyticsChartResults::where('job_id_key', $keyId)->latest()->first();
        $analyticsRecord = AnalyticsResult::where('job_id_key', $keyId)->latest()->first();

        // If not found in DB, redirect back with warning
        if (!$chartRecord) {
            return redirect()->route('analytics.dashboard')
                ->with('warning', "No chart calculation results found for Job ID: {$keyId}. Please ensure the job status is SUCCESS.");
        }

        $rawResults = is_array($chartRecord->result) ? $chartRecord->result : json_decode($chartRecord->result, true) ?? [];

        // Parse result items into organized sections matching chartreport.vue requirements
        $kpiSummary = [
            'total_booking' => 0,
            'total_net_per_stay' => 0,
            'typical_lead_days' => 0,
            'average_stay_days' => 0,
        ];

        $totalCheckinMonthly = null;
        $totalCheckinDayOfWeek = null;
        $priceRangePerMonth = [
            'filter_selector' => [],
            'chart_data' => [],
        ];
        $dailyArrPrice = null;
        $arrTrend = null;
        $arrSeasonalPattern = null;
        $otaCompositionOverview = [
            'filter_selector' => [],
            'chart_data' => [],
        ];
        $otaPriceDistributionOverview = null;

        $timeframeLabels = [
            '15' => '1 - 5 Days',
            '67' => '6 - 7 Days',
            '814' => '8 - 14 Days',
            '1521' => '15 - 21 Days',
            '2235' => '22 - 35 Days',
            '90plus' => '90+ Days',
        ];

        foreach ($rawResults as $item) {
            $slug = $item['chart_slug_name'] ?? '';
            $type = $item['type'] ?? '';
            $dataset = $item['dataset'] ?? [];
            $notes = $item['notes'] ?? ['judul' => '', 'desc' => ''];

            if ($slug === 'kpi_summary') {
                $kpiSummary = array_merge($kpiSummary, (array) $dataset);
            } elseif ($slug === 'total_check_in_monthly') {
                $totalCheckinMonthly = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            } elseif ($slug === 'total_check_in_dayofweek') {
                $totalCheckinDayOfWeek = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            } elseif (str_starts_with($slug, 'price_range_per_month_')) {
                $monthName = str_replace('price_range_per_month_', '', $slug);
                $priceRangePerMonth['filter_selector'][] = [
                    'key' => $monthName,
                    'label' => $monthName,
                ];
                $priceRangePerMonth['chart_data'][$monthName] = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            } elseif ($slug === 'daily_arr_price') {
                $dailyArrPrice = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            } elseif ($slug === 'arr_trend') {
                $arrTrend = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            } elseif ($slug === 'arr_seasonal_pattern') {
                $arrSeasonalPattern = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            } elseif (str_starts_with($slug, 'ota_composition_overview_')) {
                $timeframeKey = str_replace('ota_composition_overview_', '', $slug);
                $label = $timeframeLabels[$timeframeKey] ?? ($timeframeKey . ' Days');
                $otaCompositionOverview['filter_selector'][] = [
                    'key' => $timeframeKey,
                    'label' => $label,
                ];
                $otaCompositionOverview['chart_data'][$timeframeKey] = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            } elseif ($slug === 'ota_price_distribution_overview') {
                $otaPriceDistributionOverview = [
                    'notes' => $notes,
                    'series' => $dataset,
                ];
            }
        }

        $chartPayload = [
            'key_id' => $chartRecord->job_id_key,
            'customer_id' => $chartRecord->customer_id,
            'date_start' => $chartRecord->date_start ? $chartRecord->date_start->format('Y-m-d H:i:s') : null,
            'date_end' => $chartRecord->date_end ? $chartRecord->date_end->format('Y-m-d H:i:s') : null,
            'kpi_summary' => $kpiSummary,
            'total_check_in_monthly' => $totalCheckinMonthly,
            'total_check_in_dayofweek' => $totalCheckinDayOfWeek,
            'price_range_per_month' => $priceRangePerMonth,
            'daily_arr_price' => $dailyArrPrice,
            'arr_trend' => $arrTrend,
            'arr_seasonal_pattern' => $arrSeasonalPattern,
            'ota_composition_overview' => $otaCompositionOverview,
            'ota_price_distribution_overview' => $otaPriceDistributionOverview,
        ];

        return view('analytics.results', [
            'chartRecord' => $chartRecord,
            'analyticsRecord' => $analyticsRecord,
            'chartPayload' => $chartPayload,
            'keyId' => $keyId,
        ]);
    }
}

