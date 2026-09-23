<?php

namespace App\Http\Controllers;

use App\Services\ScrapingDataService;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\View\View;

class ScrapingDashboardController extends Controller
{
    public function __construct(
        protected ScrapingDataService $scrapingDataService
    ) {}

    /**
     * Display the Scraping Service & Streaming Console page.
     *
     * @return \Illuminate\View\View
     */
    public function index(): View
    {
        $scraperServiceUrl = config('services.scraper.url', 'http://127.0.0.1:8003');
        $summary = $this->scrapingDataService->getSummaryStats();

        return view('scraping.index', [
            'scraperServiceUrl' => $scraperServiceUrl,
            'summary' => $summary,
        ]);
    }

    /**
     * Get JSON summary stats of scraped competitor and customer records.
     *
     * @return \Illuminate\Http\JsonResponse
     */
    public function summary(): JsonResponse
    {
        $stats = $this->scrapingDataService->getSummaryStats();

        return response()->json([
            'success' => true,
            'data' => $stats,
        ]);
    }

    /**
     * Retrieve filtered competitor scraped data.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function competitorData(Request $request): JsonResponse
    {
        $filters = [
            'competitor_id' => $request->input('competitor_id'),
            'room_type_id' => $request->input('room_type_id'),
            'ota_source' => $request->input('ota_source'),
            'target_date_from' => $request->input('target_date_from'),
            'target_date_to' => $request->input('target_date_to'),
        ];

        $perPage = (int) $request->input('per_page', 25);
        $paginator = $this->scrapingDataService->getFilteredCompetitorPrices($filters, $perPage);

        return response()->json([
            'success' => true,
            'data' => $paginator->items(),
            'pagination' => [
                'current_page' => $paginator->currentPage(),
                'last_page' => $paginator->lastPage(),
                'per_page' => $paginator->perPage(),
                'total' => $paginator->total(),
            ],
        ]);
    }

    /**
     * Retrieve filtered customer scraped data.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function customerData(Request $request): JsonResponse
    {
        $filters = [
            'customer_id' => $request->input('customer_id'),
            'room_type_id' => $request->input('room_type_id'),
            'ota_source' => $request->input('ota_source'),
            'target_date_from' => $request->input('target_date_from'),
            'target_date_to' => $request->input('target_date_to'),
        ];

        $perPage = (int) $request->input('per_page', 25);
        $paginator = $this->scrapingDataService->getFilteredCustomerPrices($filters, $perPage);

        return response()->json([
            'success' => true,
            'data' => $paginator->items(),
            'pagination' => [
                'current_page' => $paginator->currentPage(),
                'last_page' => $paginator->lastPage(),
                'per_page' => $paginator->perPage(),
                'total' => $paginator->total(),
            ],
        ]);
    }

    /**
     * Retrieve customer vs competitor price comparison data.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function comparisonData(Request $request): JsonResponse
    {
        $customerId = $request->input('customer_id');
        $targetDate = $request->input('target_date');

        $comparison = $this->scrapingDataService->getPriceComparisonMatrix($customerId, $targetDate);

        return response()->json([
            'success' => true,
            'data' => $comparison,
        ]);
    }

    /**
     * Display the OTA Scraping Price & Competitor Results page.
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\View\View
     */
    public function results(Request $request): View
    {
        $competitorId = $request->query('competitor_id');
        $customerId = $request->query('customer_id');

        return view('scraping.results', [
            'competitorId' => $competitorId,
            'customerId' => $customerId,
        ]);
    }

    /**
     * Get stratified price matrix data for table & line chart (+7d & +14d).
     *
     * @param  \Illuminate\Http\Request  $request
     * @return \Illuminate\Http\JsonResponse
     */
    public function stratifiedData(Request $request): JsonResponse
    {
        $competitorId = $request->input('competitor_id');
        $customerId = $request->input('customer_id');

        $data = $this->scrapingDataService->getStratifiedPriceMatrix($competitorId, $customerId);

        return response()->json($data);
    }
}

