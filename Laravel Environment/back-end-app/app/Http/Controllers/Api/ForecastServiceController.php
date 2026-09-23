<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\ForecastResult;
use App\Models\MockupBookingData;
use App\Models\PredictionProgress;
use Carbon\Carbon;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Validator;

class ForecastServiceController extends Controller
{
    /**
     * Send mockup booking records within the specified date range to Python pipeline.
     *
     * Expected Request Payload:
     * {
     *     "customer_id": integer,
     *     "start_date": timestamp|string,
     *     "finish_date": timestamp|string
     * }
     *
     * Returns a list of dictionaries:
     * [
     *     {
     *         "customer_id": int,
     *         "booking_date": "Y-m-d H:i:s",
     *         "check_in": "Y-m-d H:i:s",
     *         "check_out": "Y-m-d H:i:s",
     *         "net_amount_stay": int,
     *         "ota": int,
     *         "is_confirmed": bool,
     *         "room_type_id": int
     *     },
     *     ...
     * ]
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function sendBack(Request $request): JsonResponse
    {
        $customerId = $request->input('customer_id');
        $rawStartDate = $request->input('start_date', $request->input('day_start', $request->input('date_start')));
        $rawFinishDate = $request->input('finish_date', $request->input('day_end', $request->input('date_end')));

        $startDate = $this->parseTimestamp($rawStartDate, false);
        $finishDate = $this->parseTimestamp($rawFinishDate, true);

        $query = MockupBookingData::query();

        if ($customerId !== null && $customerId !== '') {
            $query->where('customer_id', (int) $customerId);
        }

        if ($startDate && $finishDate) {
            $query->whereBetween('booking_date', [$startDate, $finishDate]);
        } elseif ($startDate) {
            $query->where('booking_date', '>=', $startDate);
        } elseif ($finishDate) {
            $query->where('booking_date', '<=', $finishDate);
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
                'is_confirmed' => filter_var($booking->is_confirmed, FILTER_VALIDATE_BOOLEAN),
                'room_type_id' => (int) $booking->room_type_id,
            ];
        })->values()->all();

        return response()->json($data);
    }

    public function predictionResult(Request $request): JsonResponse 
    {
        $validator = Validator::make($request->all(), [
            'status' => 'required|string',
            'customer_id' => 'nullable',
            'forecasts' => 'present|array',
            'forecasts.*.property_id' => 'nullable|integer',
            'forecasts.*.room_type_id' => 'nullable',
            'forecasts.*.forecast_date' => 'required|date',
            'forecasts.*.forecasted_price' => 'nullable|numeric',
            'forecasts.*.corrected_price' => 'nullable|numeric',
        ]);

        if ($validator->fails()) {
            Log::warning('[ForecastService] Invalid prediction payload received', [
                'errors' => $validator->errors()->toArray(),
            ]);
            return response()->json([
                'success' => false,
                'message' => 'Validation error',
                'errors' => $validator->errors(),
            ], 422);
        }

        $validated = $validator->validated();
        $status = $validated['status'];
        $customerId = $validated['customer_id'] ?? null;
        $forecasts = $validated['forecasts'];

        if (str_starts_with(strtolower($status), 'error') || str_starts_with(strtolower($status), 'failed')) {
            Log::error('[ForecastService] Python forecast pipeline reported an error', [
                'customer_id' => $customerId,
                'status' => $status,
            ]);
            return response()->json([
                'success' => false,
                'message' => 'Pipeline error received and logged',
                'pipeline_status' => $status,
            ], 200);
        }

        try {
            DB::beginTransaction();
            $recordsToInsert = [];
            $now = Carbon::now();
            foreach ($forecasts as $item) {
                $recordsToInsert[] = [
                    'customer_id' => (int) ($item['property_id'] ?? $customerId ?? 0),
                    'room_type_id' => (int) ($item['room_type_id'] ?? 0),
                    'forecast_date' => Carbon::parse($item['forecast_date'])->format('Y-m-d H:i:s'),
                    'forecasted_price' => isset($item['forecasted_price']) ? (float) $item['forecasted_price'] : 0,
                    'corrected_price' => isset($item['corrected_price']) ? (float) $item['corrected_price'] : 0,
                    'status' => $status,
                    'created_at' => $now,
                    'updated_at' => $now,
                ];
            }

            if (!empty($recordsToInsert)) {
                foreach (array_chunk($recordsToInsert, 500) as $chunk) {
                    ForecastResult::upsert(
                        $chunk,
                        ['customer_id', 'room_type_id', 'forecast_date'],
                        ['forecasted_price', 'corrected_price', 'status', 'updated_at']
                    );
                }
            }

            DB::commit();

            Log::info('[ForecastService] Forecast results stored successfully', [
                'customer_id' => $customerId,
                'count' => count($recordsToInsert),
            ]);
            return response()->json([
                'success' => true,
                'message' => 'Forecast data received and processed successfully',
                'records_count' => count($recordsToInsert),
            ], 200);
        } catch (\Throwable $e) {
            DB::rollBack();
            Log::error('[ForecastService] Failed storing forecast records: ' . $e->getMessage(), [
                'trace' => $e->getTraceAsString(),
            ]);
            return response()->json([
                'success' => false,
                'message' => 'Internal server error while saving forecast records',
                'error' => $e->getMessage(),
            ], 500);
        }
    }

    /**
     * Parse timestamp or date string into a Carbon instance.
     *
     * @param  mixed  $value
     * @param  bool  $isEnd
     * @return \Carbon\Carbon|null
     */
    private function parseTimestamp($value, bool $isEnd = false): ?Carbon
    {
        if ($value === null || $value === '') {
            return null;
        }

        try {
            if (is_numeric($value)) {
                $num = (int) $value;
                // Handle millisecond epoch if > 10 digits
                if (strlen((string) $num) > 10) {
                    $num = (int) ($num / 1000);
                }
                return Carbon::createFromTimestamp($num);
            }

            $date = Carbon::parse($value);

            // If format was date-only (e.g. '2026-09-10'), adjust boundaries
            if (preg_match('/^\d{4}-\d{2}-\d{2}$/', trim($value))) {
                $date = $isEnd ? $date->endOfDay() : $date->startOfDay();
            }

            return $date;
        } catch (\Throwable $e) {
            return null;
        }
    }

    /**
     * Update or record prediction pipeline progress from Python pipeline.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function predictionProgress(Request $request): JsonResponse
    {
        $validated = $request->validate([
            'job_id' => 'required|string',
            'customer_id' => 'nullable|integer',
            'progress_percent' => 'required|integer|min:0|max:100',
            'stage_name' => 'nullable|string',
            'message' => 'nullable|string',
            'status' => 'nullable|string',
        ]);

        $progress = PredictionProgress::updateOrCreate(
            ['job_id' => $validated['job_id']],
            [
                'customer_id' => $validated['customer_id'] ?? null,
                'progress_percent' => $validated['progress_percent'],
                'stage_name' => $validated['stage_name'] ?? null,
                'message' => $validated['message'] ?? null,
                'status' => $validated['status'] ?? 'running',
            ]
        );

        return response()->json([
            'success' => true,
            'message' => 'Progress updated successfully',
            'data' => $progress,
        ]);
    }

    /**
     * Retrieve the current progress of a forecasting job by job_id.
     *
     * @param  string  $jobId
     * @return \Illuminate\Http\JsonResponse
     */
    public function getProgress(string $jobId): JsonResponse
    {
        $progress = PredictionProgress::where('job_id', $jobId)->first();

        if (!$progress) {
            return response()->json([
                'success' => false,
                'message' => "Job with id '{$jobId}' not found",
            ], 404);
        }

        return response()->json([
            'success' => true,
            'data' => $progress,
        ]);
    }
}
