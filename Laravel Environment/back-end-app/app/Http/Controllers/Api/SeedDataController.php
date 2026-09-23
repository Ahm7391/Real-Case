<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Models\MockupBookingData;
use Carbon\Carbon;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Validator;

class SeedDataController extends Controller
{
    /**
     * Handle incoming booking data insertion (supports single record or batch).
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function store(Request $request): JsonResponse
    {
        // Extract items: seeders_booking_data.py sends {"data": [...]}, but we also support raw array or single object
        $payload = $request->input('data', $request->json('data', $request->all()));

        if (empty($payload)) {
            return response()->json([
                'success' => false,
                'message' => 'No booking data provided.',
            ], 422);
        }

        // Normalize to a list of records
        $records = is_array($payload) && isset($payload[0]) ? $payload : (isset($payload['customer_id']) ? [$payload] : []);

        if (empty($records)) {
            return response()->json([
                'success' => false,
                'message' => 'Invalid or empty booking data provided.',
            ], 422);
        }

        // Validation rules for each record
        $validator = Validator::make(['items' => $records], [
            'items' => 'required|array|min:1',
            'items.*.customer_id' => 'required|integer',
            'items.*.booking_date' => 'required',
            'items.*.check_in' => 'required',
            'items.*.check_out' => 'required',
            'items.*.net_amount_stay' => 'required|numeric',
            'items.*.ota' => 'required|integer',
            'items.*.is_confirmed' => 'required',
            'items.*.room_type_id' => 'required'
        ]);

        if ($validator->fails()) {
            return response()->json([
                'success' => false,
                'message' => 'Validation error.',
                'errors' => $validator->errors(),
            ], 422);
        }

        $now = Carbon::now();
        $insertData = [];

        foreach ($records as $item) {
            $insertData[] = [
                'customer_id' => (int) $item['customer_id'],
                'booking_date' => Carbon::parse($item['booking_date'])->format('Y-m-d H:i:s'),
                'check_in' => Carbon::parse($item['check_in'])->format('Y-m-d H:i:s'),
                'check_out' => Carbon::parse($item['check_out'])->format('Y-m-d H:i:s'),
                'net_amount_stay' => (int) $item['net_amount_stay'],
                'ota' => (int) $item['ota'],
                'is_confirmed' => is_bool($item['is_confirmed'])
                    ? ($item['is_confirmed'] ? 'true' : 'false')
                    : (string) $item['is_confirmed'],
                'room_type_id' => (int) $item['room_type_id'],
                'created_at' => $now,
                'updated_at' => $now,
            ];
        }

        try {
            DB::transaction(function () use ($insertData) {
                // Chunk insertion for safe bulk operations
                foreach (array_chunk($insertData, 500) as $chunk) {
                    MockupBookingData::insert($chunk);
                }
            });

            return response()->json([
                'success' => true,
                'message' => 'Booking records stored successfully.',
                'inserted_count' => count($insertData),
            ], 201);
        } catch (\Throwable $e) {
            return response()->json([
                'success' => false,
                'message' => 'Failed to store booking data.',
                'error' => $e->getMessage(),
            ], 500);
        }
    }
}
