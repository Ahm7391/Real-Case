<?php

use App\Http\Controllers\AnalyticsDashboardController;
use App\Http\Controllers\ForecastDashboardController;
use App\Http\Controllers\ScrapingDashboardController;
use Illuminate\Support\Facades\Route;

Route::get('/', function () {
    return view('landing');
})->name('home');

Route::get('/analytics-dashboard', [AnalyticsDashboardController::class, 'index'])->name('analytics.dashboard');
Route::post('/analytics-dashboard/request', [AnalyticsDashboardController::class, 'requestAnalytics'])->name('analytics.request');
Route::get('/analytics-dashboard/results/{keyId}', [AnalyticsDashboardController::class, 'previewResults'])->name('analytics.results');

# ROUTING FOR FORECAST SERVICE DEMO UI
Route::get('/forecast-service', [ForecastDashboardController::class, 'index'])->name('forecast.index');
Route::post('/forecast-service/trigger', [ForecastDashboardController::class, 'triggerForecast'])->name('forecast.trigger');
Route::get('/forecast-service/results', [ForecastDashboardController::class, 'previewResults'])->name('forecast.results');

# FORECAST CHART DATA & CORRECTION ENDPOINTS
Route::get('/forecast-service/search-properties', [ForecastDashboardController::class, 'searchProperties'])->name('forecast.search-properties');
Route::get('/forecast-service/search-room-types', [ForecastDashboardController::class, 'searchRoomTypes'])->name('forecast.search-room-types');
Route::get('/forecast-service/chart-data', [ForecastDashboardController::class, 'chartData'])->name('forecast.chart-data');
Route::post('/forecast-service/save-correction', [ForecastDashboardController::class, 'saveCorrection'])->name('forecast.save-correction');
Route::post('/forecast-service/delete-correction', [ForecastDashboardController::class, 'deleteCorrection'])->name('forecast.delete-correction');

# ALIASES FOR ECOMMERCE FORECAST SERVICE ROUTES
Route::get('/ecommerce/forecast-service/search-properties', [ForecastDashboardController::class, 'searchProperties'])->name('ecommerce.forecast-service.search-properties');
Route::get('/ecommerce/forecast-service/search-room-types', [ForecastDashboardController::class, 'searchRoomTypes'])->name('ecommerce.forecast-service.search-room-types');
Route::get('/ecommerce/forecast-service/chart-data', [ForecastDashboardController::class, 'chartData'])->name('ecommerce.forecast-service.chart-data');
Route::post('/ecommerce/forecast-service/save-correction', [ForecastDashboardController::class, 'saveCorrection'])->name('ecommerce.forecast-service.save-correction');
Route::post('/ecommerce/forecast-service/delete-correction', [ForecastDashboardController::class, 'deleteCorrection'])->name('ecommerce.forecast-service.delete-correction');

# ROUTING FOR SCRAPING SERVICE DATA FLOW & CONSOLE
Route::get('/scraping-service', [ScrapingDashboardController::class, 'index'])->name('scraping.index');
Route::get('/scraping-service/results', [ScrapingDashboardController::class, 'results'])->name('scraping.results');
Route::get('/scraping-service/stratified-data', [ScrapingDashboardController::class, 'stratifiedData'])->name('scraping.stratified-data');
Route::get('/scraping-service/summary', [ScrapingDashboardController::class, 'summary'])->name('scraping.summary');
Route::get('/scraping-service/competitor-data', [ScrapingDashboardController::class, 'competitorData'])->name('scraping.competitor-data');
Route::get('/scraping-service/customer-data', [ScrapingDashboardController::class, 'customerData'])->name('scraping.customer-data');
Route::get('/scraping-service/comparison', [ScrapingDashboardController::class, 'comparisonData'])->name('scraping.comparison');



