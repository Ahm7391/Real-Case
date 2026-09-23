<?php

namespace App\Http\Controllers;

use App\Models\ForecastResult;
use App\Models\MockupBookingData;
use App\Models\PredictionProgress;
use Carbon\Carbon;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Http;
use Illuminate\Support\Facades\Log;
use Illuminate\View\View;

class ForecastDashboardController extends Controller
{
    /**
     * Display the Forecast Service Demo page.
     *
     * @return \Illuminate\View\View
     */
    public function index(): View
    {
        $customerId = 1; // Default simulation customer
        $recentProgress = PredictionProgress::orderBy('id', 'desc')->take(5)->get();

        return view('forecast.index', compact('customerId', 'recentProgress'));
    }

    /**
     * Trigger the forecasting pipeline call to Python FastAPI endpoint (/forecast-service-call).
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function triggerForecast(Request $request): JsonResponse
    {
        $customerId = (int) $request->input('customer_id', 1);
        $startDate = $request->input('start_date', Carbon::now()->subDays(60)->format('Y-m-d'));
        $finishDate = $request->input('finish_date', Carbon::now()->format('Y-m-d'));

        // Generate unique Job ID
        $jobId = 'JOB_FC_' . strtoupper(bin2hex(random_bytes(4))) . '_' . time();

        // 1. Initialize PredictionProgress record
        PredictionProgress::updateOrCreate(
            ['job_id' => $jobId],
            [
                'customer_id' => $customerId,
                'progress_percent' => 0,
                'stage_name' => 'Initialization',
                'message' => 'Forecast job initialized. Connecting to forecasting pipeline...',
                'status' => 'pending',
            ]
        );

        // 2. Call Python FastAPI endpoint
        $pipelineBaseUrl = rtrim(config('services.forecast.url', env('FORECAST_SERVICE_URL', 'http://127.0.0.1:8002')), '/');
        $pipelineEndpoint = $pipelineBaseUrl . '/forecast-service-call';

        $payload = [
            'job_id' => $jobId,
            'customer_id' => (string) $customerId,
            'start_date' => (string) $startDate,
            'finish_date' => (string) $finishDate,
        ];

        try {
            $response = Http::timeout(5)->asJson()->get($pipelineEndpoint, $payload);

            if ($response->successful()) {
                Log::info("[ForecastDashboard] Signal sent successfully to Python FastAPI ({$pipelineEndpoint}) for Job {$jobId}");
                return response()->json([
                    'success' => true,
                    'job_id' => $jobId,
                    'message' => 'Forecast service signal dispatched successfully to Python pipeline.',
                    'pipeline_status' => 'online',
                ]);
            }

            Log::warning("[ForecastDashboard] Python FastAPI returned non-200 ({$response->status()}) for Job {$jobId}: " . $response->body());
            
            PredictionProgress::where('job_id' , $jobId)->update([
                'status' => 'running',
                'stage_name' => 'Signal Dispatched',
                'message' => "Pipeline response HTTP {$response->status()}. Awaiting async workers...",
            ]);

            return response()->json([
                'success' => true,
                'job_id' => $jobId,
                'message' => 'Signal sent. Awaiting async worker updates.',
                'pipeline_status' => 'warning',
            ]);
        } catch (\Throwable $e) {
            Log::warning("[ForecastDashboard] Could not reach Python FastAPI at {$pipelineEndpoint}: " . $e->getMessage());

            PredictionProgress::where('job_id', $jobId)->update([
                'status' => 'running',
                'stage_name' => 'Pending Workers',
                'message' => "Job {$jobId} registered. Waiting for Python service progress updates...",
            ]);

            return response()->json([
                'success' => true,
                'job_id' => $jobId,
                'message' => "Job {$jobId} initialized locally. Note: FastAPI server at {$pipelineEndpoint} was unreachable, job queued.",
                'pipeline_status' => 'offline',
            ]);
        }
    }

    /**
     * Display the Forecasted Price Trend Results page.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\View\View
     */
    public function previewResults(Request $request): View
    {
        $jobId = $request->query('job_id', '');
        $customerId = (int) $request->query('customer_id', 1);

        $progressRecord = null;
        if (!empty($jobId)) {
            $progressRecord = PredictionProgress::where('job_id', $jobId)->first();
        }

        // Build available months starting from current month up to the latest available prediction month
        $now = Carbon::now();
        $startMonth = $now->copy()->startOfMonth();

        $maxForecastDate = ForecastResult::where('customer_id', $customerId)
            ->where('forecast_date', '>=', $startMonth)
            ->max('forecast_date');

        if (!$maxForecastDate) {
            $anyMax = ForecastResult::where('customer_id', $customerId)->max('forecast_date');
            if ($anyMax && Carbon::parse($anyMax)->gt($startMonth)) {
                $maxForecastDate = $anyMax;
            } else {
                $maxForecastDate = $now->copy()->addMonths(2)->format('Y-m-d');
            }
        }

        $endMonth = Carbon::parse($maxForecastDate)->startOfMonth();
        if ($endMonth->lt($startMonth)) {
            $endMonth = $startMonth->copy();
        }

        $availableMonths = [];
        $cursor = $startMonth->copy();
        while ($cursor->lte($endMonth)) {
            $availableMonths[] = [
                'value' => $cursor->format('Y-m'),
                'text' => $cursor->format('F Y'),
                'is_current' => $cursor->isSameMonth($now),
            ];
            $cursor->addMonth();
        }

        return view('forecast.results', [
            'jobId' => $jobId,
            'customerId' => $customerId,
            'progressRecord' => $progressRecord,
            'availableMonths' => $availableMonths,
        ]);
    }

    /**
     * Search properties / customers for the forecast autocomplete dropdown.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function searchProperties(Request $request): JsonResponse
    {
        $q = trim((string) $request->input('q', ''));

        // Collect distinct customer IDs from ForecastResult and MockupBookingData
        $customerIds = ForecastResult::select('customer_id')->distinct()->pluck('customer_id')
            ->merge(MockupBookingData::select('customer_id')->distinct()->pluck('customer_id'))
            ->push(1)
            ->unique()
            ->filter(fn($val) => $val !== null && $val !== '')
            ->values();

        $items = $customerIds->map(function ($id) {
            return [
                'id' => (int) $id,
                'text' => "Property {$id}",
            ];
        })->filter(function ($item) use ($q) {
            if ($q === '') return true;
            return stripos($item['text'], $q) !== false || stripos((string) $item['id'], $q) !== false;
        })->values()->all();

        return response()->json($items);
    }

    /**
     * Retrieve room types available for a specific property.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function searchRoomTypes(Request $request): JsonResponse
    {
        $propertyId = (int) $request->input('property_id', 1);

        $roomTypeIds = ForecastResult::where('customer_id', $propertyId)
            ->select('room_type_id')
            ->distinct()
            ->pluck('room_type_id')
            ->merge(
                MockupBookingData::where('customer_id', $propertyId)
                    ->select('room_type_id')
                    ->distinct()
                    ->pluck('room_type_id')
            )
            ->unique()
            ->values();

        if ($roomTypeIds->isEmpty()) {
            $roomTypeIds = collect([0, 1, 2]);
        }

        $items = $roomTypeIds->map(function ($id) {
            $num = (int) $id;
            $name = match ($num) {
                0 => 'All / Standard Room',
                1 => 'Deluxe Room Type 1',
                2 => 'Executive Suite 2',
                default => 'Room Type ' . $num,
            };
            return [
                'id' => $num,
                'name' => $name,
            ];
        })->values()->all();

        return response()->json($items);
    }

    /**
     * Fetch forecast chart data (Baseline vs Suggested price curves & stats).
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function chartData(Request $request): JsonResponse
    {
        $propertyId = (int) $request->input('property_id', 1);
        $roomTypeId = $request->input('room_type_id');
        $month = $request->input('month'); // Format: YYYY-MM

        $query = ForecastResult::where('customer_id', $propertyId);

        if ($roomTypeId !== null && $roomTypeId !== '') {
            $query->where('room_type_id', (int) $roomTypeId);
        }

        if (!empty($month)) {
            try {
                $start = Carbon::parse($month . '-01')->startOfMonth();
                $end = Carbon::parse($month . '-01')->endOfMonth();
                $query->whereBetween('forecast_date', [$start, $end]);
            } catch (\Throwable $e) {
                // Ignore parsing errors
            }
        }

        $records = $query->orderBy('forecast_date', 'asc')->get();

        // Fallback to recent records if exact month has no data
        if ($records->isEmpty()) {
            $records = ForecastResult::where('customer_id', $propertyId)
                ->orderBy('forecast_date', 'asc')
                ->take(30)
                ->get();
        }

        $labels = [];
        $fullDates = [];
        $forecasted = [];
        $corrected = [];
        $correctionDetails = [];

        foreach ($records as $item) {
            $dateObj = Carbon::parse($item->forecast_date);
            $label = $dateObj->format('d M');
            $fullDate = $dateObj->format('Y-m-d');

            $fPrice = (float) $item->forecasted_price;
            $cPrice = (float) ($item->corrected_price > 0 ? $item->corrected_price : $item->forecasted_price);

            $labels[] = $label;
            $fullDates[] = $fullDate;
            $forecasted[] = $fPrice;
            $corrected[] = $cPrice;

            $isCorrected = ($item->corrected_price > 0 && abs($item->corrected_price - $item->forecasted_price) > 0.01);

            $correctionDetails[] = [
                'raw_date' => $fullDate,
                'baseline_price' => $fPrice,
                'suggested_price' => $fPrice,
                'user_corrected_price' => $cPrice,
                'is_corrected' => $isCorrected,
                'modified_by_name' => 'User / System',
                'corrected_at' => $item->updated_at ? $item->updated_at->format('Y-m-d H:i') : $fullDate,
            ];
        }

        $count = count($forecasted);
        $avgBaseline = $count > 0 ? array_sum($forecasted) / $count : 0;
        $avgCorrected = $count > 0 ? array_sum($corrected) / $count : 0;

        $diffs = [];
        for ($i = 0; $i < $count; $i++) {
            $diffs[] = $corrected[$i] - $forecasted[$i];
        }

        $maxGain = !empty($diffs) ? max(0, max($diffs)) : 0;
        $minDiff = !empty($diffs) ? min(0, min($diffs)) : 0;
        $maxDrop = abs($minDiff);
        $netDelta = $avgCorrected - $avgBaseline;

        $stats = [
            'avg_baseline' => round($avgBaseline),
            'avg_corrected' => round($avgCorrected),
            'max_gain' => round($maxGain),
            'max_drop' => round($maxDrop),
            'net_avg_delta' => round($netDelta),
        ];

        return response()->json([
            'labels' => $labels,
            'full_dates' => $fullDates,
            'forecasted' => $forecasted,
            'corrected' => $corrected,
            'stats' => $stats,
            'correction_details' => $correctionDetails,
        ]);
    }

    /**
     * Save user price correction for a specific date.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function saveCorrection(Request $request): JsonResponse
    {
        $customerId = (int) $request->input('customer_id', 1);
        $roomTypeId = (int) $request->input('room_type_id', 0);
        $correctedDate = $request->input('corrected_date');
        $price = (float) $request->input('user_corrected_price');

        if (!$correctedDate || $price < 0) {
            return response()->json([
                'success' => false,
                'message' => 'Invalid date or price provided.',
            ], 422);
        }

        $parsedDate = Carbon::parse($correctedDate)->startOfDay();

        $record = ForecastResult::where('customer_id', $customerId)
            ->where('room_type_id', $roomTypeId)
            ->whereDate('forecast_date', $parsedDate)
            ->first();

        if ($record) {
            $record->update([
                'corrected_price' => $price,
            ]);
        } else {
            ForecastResult::create([
                'customer_id' => $customerId,
                'room_type_id' => $roomTypeId,
                'forecast_date' => $parsedDate,
                'forecasted_price' => $price,
                'corrected_price' => $price,
                'status' => 'corrected',
            ]);
        }

        return response()->json([
            'success' => true,
            'message' => 'Price correction saved successfully.',
        ]);
    }

    /**
     * Delete user price correction and revert to baseline forecasted price.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function deleteCorrection(Request $request): JsonResponse
    {
        $customerId = (int) $request->input('customer_id', 1);
        $roomTypeId = (int) $request->input('room_type_id', 0);
        $correctedDate = $request->input('corrected_date');

        if (!$correctedDate) {
            return response()->json([
                'success' => false,
                'message' => 'Invalid date provided.',
            ], 422);
        }

        $parsedDate = Carbon::parse($correctedDate)->startOfDay();

        $record = ForecastResult::where('customer_id', $customerId)
            ->where('room_type_id', $roomTypeId)
            ->whereDate('forecast_date', $parsedDate)
            ->first();

        if ($record) {
            $record->update([
                'corrected_price' => $record->forecasted_price,
            ]);
        }

        return response()->json([
            'success' => true,
            'message' => 'Correction deleted and reverted to original suggested price.',
        ]);
    }
}
