<?php

namespace App\Services;

use App\Models\ScrapedCompetitorPrice;
use App\Models\ScrapedCustomer;
use Carbon\Carbon;
use Illuminate\Contracts\Pagination\LengthAwarePaginator;
use Illuminate\Database\Eloquent\Collection;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;

class ScrapingDataService
{
    /**
     * Store or bulk-insert competitor scraped prices.
     *
     * @param  array<int, array<string, mixed>>  $items
     * @return array{success: bool, records_count: int, message: string}
     */
    public function storeCompetitorPrices(array $items): array
    {
        if (empty($items)) {
            return [
                'success' => false,
                'records_count' => 0,
                'message' => 'No competitor records provided.',
            ];
        }

        DB::beginTransaction();
        try {
            $recordsToInsert = [];
            $now = Carbon::now();

            foreach ($items as $item) {
                $competitorId = $item['property_name'] ?? $item['competitor_id'] ?? 'unknown';
                $roomTypeId = $item['room_type'] ?? $item['room_type_id'] ?? 'unknown';
                $otaSource = $item['ota_source'] ?? $item['ota'] ?? 'booking.com';

                $scrapedAt = !empty($item['scraped_at'])
                    ? $this->parseDateTime($item['scraped_at'])
                    : $now;

                $targetDate = !empty($item['target_date'])
                    ? $this->parseDateTime($item['target_date'])
                    : $scrapedAt;

                $recordsToInsert[] = [
                    'competitor_id' => (string) $competitorId,
                    'room_type_id' => (string) $roomTypeId,
                    'ota_source' => (string) $otaSource,
                    'price' => isset($item['price']) && $item['price'] !== '' && $item['price'] !== null ? (int) $item['price'] : null,
                    'perks' => !empty($item['perks']) ? (string) $item['perks'] : null,
                    'scraped_at' => $scrapedAt ? $scrapedAt->format('Y-m-d H:i:s') : $now->format('Y-m-d H:i:s'),
                    'target_date' => $targetDate ? $targetDate->format('Y-m-d H:i:s') : $now->format('Y-m-d H:i:s'),
                    'category' => isset($item['category']) && $item['category'] !== '' && $item['category'] !== null ? (int) $item['category'] : null,
                    'created_at' => $now,
                    'updated_at' => $now,
                ];
            }

            foreach (array_chunk($recordsToInsert, 500) as $chunk) {
                ScrapedCompetitorPrice::insert($chunk);
            }

            DB::commit();

            Log::info('[ScrapingDataService] Persisted scraped competitor records', [
                'count' => count($recordsToInsert),
            ]);

            return [
                'success' => true,
                'records_count' => count($recordsToInsert),
                'message' => 'Scraped competitor prices stored successfully.',
            ];
        } catch (\Throwable $e) {
            DB::rollBack();
            Log::error('[ScrapingDataService] Failed persisting competitor records: ' . $e->getMessage(), [
                'trace' => $e->getTraceAsString(),
            ]);

            throw $e;
        }
    }

    /**
     * Store or bulk-insert customer scraped prices.
     *
     * @param  array<int, array<string, mixed>>  $items
     * @return array{success: bool, records_count: int, message: string}
     */
    public function storeCustomerPrices(array $items): array
    {
        if (empty($items)) {
            return [
                'success' => false,
                'records_count' => 0,
                'message' => 'No customer records provided.',
            ];
        }

        DB::beginTransaction();
        try {
            $recordsToInsert = [];
            $now = Carbon::now();

            foreach ($items as $item) {
                $customerId = $item['property_name'] ?? $item['customer_id'] ?? 'unknown';
                $roomTypeId = $item['room_type'] ?? $item['room_type_id'] ?? 'unknown';
                $otaSource = $item['ota_source'] ?? $item['ota'] ?? 'booking.com';

                $scrapedAt = !empty($item['scraped_at'])
                    ? $this->parseDateTime($item['scraped_at'])
                    : $now;

                $targetDate = !empty($item['target_date'])
                    ? $this->parseDateTime($item['target_date'])
                    : $scrapedAt;

                $recordsToInsert[] = [
                    'customer_id' => (string) $customerId,
                    'room_type_id' => (string) $roomTypeId,
                    'ota_source' => (string) $otaSource,
                    'price' => isset($item['price']) && $item['price'] !== '' && $item['price'] !== null ? (int) $item['price'] : null,
                    'perks' => !empty($item['perks']) ? (string) $item['perks'] : null,
                    'scraped_at' => $scrapedAt ? $scrapedAt->format('Y-m-d H:i:s') : $now->format('Y-m-d H:i:s'),
                    'target_date' => $targetDate ? $targetDate->format('Y-m-d H:i:s') : $now->format('Y-m-d H:i:s'),
                    'category' => isset($item['category']) && $item['category'] !== '' && $item['category'] !== null ? (int) $item['category'] : null,
                    'created_at' => $now,
                    'updated_at' => $now,
                ];
            }

            foreach (array_chunk($recordsToInsert, 500) as $chunk) {
                ScrapedCustomer::insert($chunk);
            }

            DB::commit();

            Log::info('[ScrapingDataService] Persisted scraped customer records', [
                'count' => count($recordsToInsert),
            ]);

            return [
                'success' => true,
                'records_count' => count($recordsToInsert),
                'message' => 'Scraped customer prices stored successfully.',
            ];
        } catch (\Throwable $e) {
            DB::rollBack();
            Log::error('[ScrapingDataService] Failed persisting customer records: ' . $e->getMessage(), [
                'trace' => $e->getTraceAsString(),
            ]);

            throw $e;
        }
    }

    /**
     * Get aggregated summary statistics of all scraped data.
     *
     * @return array<string, mixed>
     */
    public function getSummaryStats(): array
    {
        $totalCompetitorRecords = ScrapedCompetitorPrice::count();
        $totalCustomerRecords = ScrapedCustomer::count();

        $latestCompetitorScrape = ScrapedCompetitorPrice::max('scraped_at');
        $latestCustomerScrape = ScrapedCustomer::max('scraped_at');

        $competitorOtas = ScrapedCompetitorPrice::select('ota_source', DB::raw('count(*) as count'))
            ->groupBy('ota_source')
            ->pluck('count', 'ota_source')
            ->toArray();

        $customerOtas = ScrapedCustomer::select('ota_source', DB::raw('count(*) as count'))
            ->groupBy('ota_source')
            ->pluck('count', 'ota_source')
            ->toArray();

        $distinctCompetitors = ScrapedCompetitorPrice::distinct('competitor_id')->count('competitor_id');
        $distinctCustomers = ScrapedCustomer::distinct('customer_id')->count('customer_id');

        return [
            'total_records' => $totalCompetitorRecords + $totalCustomerRecords,
            'competitor' => [
                'total_records' => $totalCompetitorRecords,
                'distinct_properties' => $distinctCompetitors,
                'latest_scraped_at' => $latestCompetitorScrape,
                'ota_breakdown' => $competitorOtas,
            ],
            'customer' => [
                'total_records' => $totalCustomerRecords,
                'distinct_properties' => $distinctCustomers,
                'latest_scraped_at' => $latestCustomerScrape,
                'ota_breakdown' => $customerOtas,
            ],
        ];
    }

    /**
     * Query competitor prices with optional filters and pagination.
     *
     * @param  array<string, mixed>  $filters
     * @param  int  $perPage
     * @return \Illuminate\Contracts\Pagination\LengthAwarePaginator
     */
    public function getFilteredCompetitorPrices(array $filters = [], int $perPage = 25): LengthAwarePaginator
    {
        $query = ScrapedCompetitorPrice::query();

        if (!empty($filters['competitor_id'])) {
            $query->where('competitor_id', 'like', '%' . $filters['competitor_id'] . '%');
        }

        if (!empty($filters['room_type_id'])) {
            $query->where('room_type_id', $filters['room_type_id']);
        }

        if (!empty($filters['ota_source'])) {
            $query->where('ota_source', $filters['ota_source']);
        }

        if (!empty($filters['target_date_from'])) {
            $query->whereDate('target_date', '>=', $filters['target_date_from']);
        }

        if (!empty($filters['target_date_to'])) {
            $query->whereDate('target_date', '<=', $filters['target_date_to']);
        }

        return $query->orderBy('target_date', 'desc')
            ->orderBy('id', 'desc')
            ->paginate($perPage);
    }

    /**
     * Query customer prices with optional filters and pagination.
     *
     * @param  array<string, mixed>  $filters
     * @param  int  $perPage
     * @return \Illuminate\Contracts\Pagination\LengthAwarePaginator
     */
    public function getFilteredCustomerPrices(array $filters = [], int $perPage = 25): LengthAwarePaginator
    {
        $query = ScrapedCustomer::query();

        if (!empty($filters['customer_id'])) {
            $query->where('customer_id', 'like', '%' . $filters['customer_id'] . '%');
        }

        if (!empty($filters['room_type_id'])) {
            $query->where('room_type_id', $filters['room_type_id']);
        }

        if (!empty($filters['ota_source'])) {
            $query->where('ota_source', $filters['ota_source']);
        }

        if (!empty($filters['target_date_from'])) {
            $query->whereDate('target_date', '>=', $filters['target_date_from']);
        }

        if (!empty($filters['target_date_to'])) {
            $query->whereDate('target_date', '<=', $filters['target_date_to']);
        }

        return $query->orderBy('target_date', 'desc')
            ->orderBy('id', 'desc')
            ->paginate($perPage);
    }

    /**
     * Build price comparison metrics between customer hotel and competitor set.
     *
     * @param  string|null  $customerId
     * @param  string|null  $targetDate
     * @return array<string, mixed>
     */
    public function getPriceComparisonMatrix(?string $customerId = null, ?string $targetDate = null): array
    {
        $custQuery = ScrapedCustomer::query();
        $compQuery = ScrapedCompetitorPrice::query();

        if (!empty($customerId)) {
            $custQuery->where('customer_id', $customerId);
        }

        if (!empty($targetDate)) {
            $custQuery->whereDate('target_date', $targetDate);
            $compQuery->whereDate('target_date', $targetDate);
        }

        $customerPrices = $custQuery->orderBy('target_date', 'desc')->take(50)->get();
        $competitorPrices = $compQuery->orderBy('target_date', 'desc')->take(100)->get();

        $avgCustomerPrice = $customerPrices->avg('price');
        $avgCompetitorPrice = $competitorPrices->avg('price');

        return [
            'customer_avg_price' => $avgCustomerPrice ? round($avgCustomerPrice, 2) : 0,
            'competitor_avg_price' => $avgCompetitorPrice ? round($avgCompetitorPrice, 2) : 0,
            'price_difference' => ($avgCustomerPrice && $avgCompetitorPrice) ? round($avgCustomerPrice - $avgCompetitorPrice, 2) : 0,
            'customer_sample_count' => $customerPrices->count(),
            'competitor_sample_count' => $competitorPrices->count(),
            'customer_records' => $customerPrices,
            'competitor_records' => $competitorPrices,
        ];
    }

    /**
     * Build Stratified Periods Price Matrix for the 2 Demo Windows (+7 Days & +14 Days).
     *
     * @param  string|null  $competitorId
     * @param  string|null  $customerId
     * @return array<string, mixed>
     */
    public function getStratifiedPriceMatrix(?string $competitorId = null, ?string $customerId = null): array
    {
        $compQuery = ScrapedCompetitorPrice::query();
        $custQuery = ScrapedCustomer::query();

        if (!empty($competitorId)) {
            $compQuery->where('competitor_id', $competitorId);
        }
        if (!empty($customerId)) {
            $custQuery->where('customer_id', $customerId);
        }

        $competitorRecords = $compQuery->orderBy('target_date', 'asc')->orderBy('id', 'desc')->get();
        $customerRecords = $custQuery->orderBy('target_date', 'asc')->orderBy('id', 'desc')->get();

        if ($competitorRecords->isEmpty() && $customerRecords->isEmpty()) {
            return [
                'available' => false,
                'message' => 'No scraped pricing data found. Please run the scraping demo first.',
                'competitor_sections' => [],
            ];
        }

        $latestScrape = ScrapedCompetitorPrice::max('scraped_at') ?? ScrapedCustomer::max('scraped_at');
        $asOf = $latestScrape ? Carbon::parse($latestScrape)->format('d M Y, H:i') : Carbon::now()->format('d M Y, H:i');

        // Determine customer prices per OTA and per window (0: +7d, 1: +14d)
        $customerOtaWindows = [];
        foreach ($customerRecords as $cr) {
            $ota = strtolower(trim((string) ($cr->ota_source ?: 'booking.com')));
            $windowIdx = $this->resolveWindowIndex($cr->target_date, $cr->scraped_at, $cr->category);
            
            if ($cr->price !== null && $cr->price > 0) {
                if (!isset($customerOtaWindows[$ota][$windowIdx]) || $cr->price < $customerOtaWindows[$ota][$windowIdx]) {
                    $customerOtaWindows[$ota][$windowIdx] = (int) $cr->price;
                }
            }
        }

        // Group competitor records by competitor_id
        $groupedCompetitors = $competitorRecords->groupBy('competitor_id');
        if ($groupedCompetitors->isEmpty()) {
            $groupedCompetitors = collect(['Competitor Hotel' => collect()]);
        }

        $sections = [];

        foreach ($groupedCompetitors as $compId => $records) {
            $compName = (string) $compId;
            if (empty($compName) || $compName === 'unknown') {
                $compName = 'Competitor Property';
            }

            // Group by OTA
            $groupedOtas = $records->groupBy('ota_source');
            if ($groupedOtas->isEmpty()) {
                $groupedOtas = collect(['booking.com' => collect()]);
            }

            $otaTables = [];

            foreach ($groupedOtas as $otaName => $otaRecords) {
                $otaKey = strtolower(trim((string) ($otaName ?: 'booking.com')));
                $custPrices = [
                    $customerOtaWindows[$otaKey][0] ?? $customerOtaWindows['booking.com'][0] ?? null,
                    $customerOtaWindows[$otaKey][1] ?? $customerOtaWindows['booking.com'][1] ?? null,
                ];

                // Group by room_type_id
                $roomRows = [];
                $groupedRooms = $otaRecords->groupBy('room_type_id');

                foreach ($groupedRooms as $roomTypeId => $roomRecords) {
                    $rName = (string) $roomTypeId;
                    if (empty($rName) || $rName === 'unknown') {
                        $rName = 'Standard Room';
                    }

                    $prices = [null, null]; // [0 => +7d (0-7 days lowest), 1 => +14d (8-14 days lowest)]

                    foreach ($roomRecords as $rr) {
                        $wIdx = $this->resolveWindowIndex($rr->target_date, $rr->scraped_at, $rr->category);
                        if ($rr->price !== null && $rr->price > 0) {
                            if ($prices[$wIdx] === null || $rr->price < $prices[$wIdx]) {
                                $prices[$wIdx] = (int) $rr->price;
                            }
                        }
                    }

                    $roomRows[] = [
                        'room_name' => $rName,
                        'prices' => $prices,
                    ];
                }

                $otaTables[] = [
                    'ota_name' => $otaKey,
                    'ota_id' => $otaKey,
                    'customer_prices' => $custPrices,
                    'rows' => $roomRows,
                ];
            }

            $sections[] = [
                'competitor_id' => (string) $compId,
                'competitor_name' => $compName,
                'ota_tables' => $otaTables,
            ];
        }

        return [
            'available' => true,
            'as_of' => $asOf,
            'windows' => ['+7 Days', '+14 Days'],
            'competitor_sections' => $sections,
        ];
    }

    /**
     * Map target_date and scraped_at into stratified window index:
     * - Window 0 (+7 Days / Last Minute): Lowest price between day 0 and day 7 (inclusive: 0 <= diffDays <= 7)
     * - Window 1 (+14 Days / Early Book): Lowest price between day 8 and day 14 (inclusive: 8 <= diffDays <= 14 or >= 8)
     *
     * @param  mixed  $targetDate
     * @param  mixed  $scrapedAt
     * @param  int|null  $category
     * @return int 0 for +7 Days, 1 for +14 Days
     */
    private function resolveWindowIndex(mixed $targetDate, mixed $scrapedAt, ?int $category = null): int
    {
        if (!empty($targetDate)) {
            try {
                $target = Carbon::parse($targetDate)->startOfDay();
                $base = !empty($scrapedAt) ? Carbon::parse($scrapedAt)->startOfDay() : Carbon::now()->startOfDay();
                $diffDays = $base->diffInDays($target, false);

                // Range 0 - 7 days (inclusive) -> Last Minute (+7 Days)
                if ($diffDays <= 7) {
                    return 0;
                }

                // Range 8 - 14 days (or beyond) -> Early Book (+14 Days)
                return 1;
            } catch (\Throwable $e) {
                // Ignore and fall back to category if any
            }
        }

        if ($category !== null) {
            $catNum = (int) $category;
            if ($catNum === 0 || $catNum === 1) {
                return 0; // +7 Days
            }
            if ($catNum === 2) {
                return 1; // +14 Days
            }
        }

        return 0;
    }

    /**
     * Parse date/time string or timestamp into a Carbon instance.
     *
     * @param  mixed  $value
     * @return \Carbon\Carbon|null
     */
    private function parseDateTime($value): ?Carbon
    {
        if ($value === null || $value === '') {
            return null;
        }

        try {
            if (is_numeric($value)) {
                $num = (int) $value;
                if (strlen((string) $num) > 10) {
                    $num = (int) ($num / 1000);
                }
                return Carbon::createFromTimestamp($num);
            }

            return Carbon::parse($value);
        } catch (\Throwable $e) {
            return null;
        }
    }
}
