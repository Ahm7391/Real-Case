<?php

namespace App\Http\Controllers\Api;

use App\Http\Controllers\Controller;
use App\Services\ScrapingDataService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;
use Illuminate\Support\Facades\Validator;

class ScrapingServiceController extends Controller
{
    public function __construct(
        protected ScrapingDataService $scrapingDataService
    ) {}

    /**
     * Receive scraped competitor price result from Python scraping pipeline
     * and persist to the scraped_competitor_price table.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function scrapCompetitorResult(Request $request): JsonResponse
    {
        $payload = $request->all();

        // Normalize payload: accept single object, list of objects, or wrapped objects ('data', 'records', 'items')
        $items = $this->normalizePayload($payload);

        if (empty($items)) {
            return response()->json([
                'success' => false,
                'message' => 'Empty payload received',
            ], 422);
        }

        $validator = Validator::make(['items' => $items], [
            'items' => 'required|array',
            'items.*.property_name' => 'nullable|string',
            'items.*.competitor_id' => 'nullable|string',
            'items.*.room_type' => 'nullable|string',
            'items.*.room_type_id' => 'nullable|string',
            'items.*.ota_source' => 'nullable|string',
            'items.*.ota' => 'nullable|string',
            'items.*.price' => 'nullable|numeric',
            'items.*.perks' => 'nullable|string',
            'items.*.scraped_at' => 'nullable',
            'items.*.target_date' => 'nullable',
            'items.*.category' => 'nullable|integer',
        ]);

        if ($validator->fails()) {
            Log::warning('[ScrapingService] Invalid competitor scraping payload received', [
                'errors' => $validator->errors()->toArray(),
            ]);

            return response()->json([
                'success' => false,
                'message' => 'Validation error',
                'errors' => $validator->errors(),
            ], 422);
        }

        try {
            $result = $this->scrapingDataService->storeCompetitorPrices($items);

            return response()->json([
                'success' => true,
                'message' => $result['message'],
                'records_count' => $result['records_count'],
            ], 200);

        } catch (\Throwable $e) {
            return response()->json([
                'success' => false,
                'message' => 'Internal server error while saving competitor price records',
                'error' => $e->getMessage(),
            ], 500);
        }
    }

    /**
     * Receive scraped customer property price result from Python scraping pipeline
     * and persist to the scraped_customer table.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function scrapCustomerResult(Request $request): JsonResponse
    {
        $payload = $request->all();

        // Normalize payload: accept single object, list of objects, or wrapped objects ('data', 'records', 'items')
        $items = $this->normalizePayload($payload);

        if (empty($items)) {
            return response()->json([
                'success' => false,
                'message' => 'Empty payload received',
            ], 422);
        }

        $validator = Validator::make(['items' => $items], [
            'items' => 'required|array',
            'items.*.property_name' => 'nullable|string',
            'items.*.customer_id' => 'nullable|string',
            'items.*.room_type' => 'nullable|string',
            'items.*.room_type_id' => 'nullable|string',
            'items.*.ota_source' => 'nullable|string',
            'items.*.ota' => 'nullable|string',
            'items.*.price' => 'nullable|numeric',
            'items.*.perks' => 'nullable|string',
            'items.*.scraped_at' => 'nullable',
            'items.*.target_date' => 'nullable',
            'items.*.category' => 'nullable|integer',
        ]);

        if ($validator->fails()) {
            Log::warning('[ScrapingService] Invalid customer scraping payload received', [
                'errors' => $validator->errors()->toArray(),
            ]);

            return response()->json([
                'success' => false,
                'message' => 'Validation error',
                'errors' => $validator->errors(),
            ], 422);
        }

        try {
            $result = $this->scrapingDataService->storeCustomerPrices($items);

            return response()->json([
                'success' => true,
                'message' => $result['message'],
                'records_count' => $result['records_count'],
            ], 200);

        } catch (\Throwable $e) {
            return response()->json([
                'success' => false,
                'message' => 'Internal server error while saving customer price records',
                'error' => $e->getMessage(),
            ], 500);
        }
    }

    /**
     * Normalize payload into an array of items.
     *
     * @param  mixed  $payload
     * @return array<int, array<string, mixed>>
     */
    private function normalizePayload(mixed $payload): array
    {
        if (!is_array($payload)) {
            return [];
        }

        if (isset($payload['data']) && is_array($payload['data'])) {
            return $payload['data'];
        }

        if (isset($payload['records']) && is_array($payload['records'])) {
            return $payload['records'];
        }

        if (isset($payload['items']) && is_array($payload['items'])) {
            return $payload['items'];
        }

        if (array_is_list($payload)) {
            return $payload;
        }

        return [$payload];
    }
}
