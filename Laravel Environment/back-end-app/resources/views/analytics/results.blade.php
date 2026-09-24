<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analytics Preview | Job #{{ $keyId }}</title>
    <link rel="icon" type="image/svg+xml" href="{{ asset('favicon.svg') }}">
    <link rel="alternate icon" href="{{ asset('favicon.ico') }}">
    
    <!-- Google Fonts & Bootstrap 5 Icons -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    
    <!-- ApexCharts CDN -->
    <script src="https://cdn.jsdelivr.net/npm/apexcharts"></script>

    <style>
        :root {
            --bs-body-font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            --bs-body-bg: #f8f9fa;
            --bs-body-color: #181c32;
            --bs-primary: #009ef7;
            --bs-primary-active: #0095e8;
            --bs-primary-light: #f1faff;
            --bs-success: #50cd89;
            --bs-info: #7239ea;
            --bs-warning: #ffc700;
        }

        body {
            font-family: var(--bs-body-font-family);
            background-color: #f8f9fa;
            color: #181c32;
            min-height: 100vh;
        }

        /* Top Header Navbar */
        .top-navbar {
            background-color: #ffffff;
            border-bottom: 1px solid #eff2f5;
            padding: 1rem 2rem;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .brand-text {
            font-weight: 700;
            font-size: 1.15rem;
            color: #181c32;
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 0.6rem;
        }

        .brand-badge {
            background-color: #e8fff3;
            color: #50cd89;
            border: 1px solid #b4f1cd;
            font-size: 0.72rem;
            font-weight: 700;
            padding: 0.2rem 0.6rem;
            border-radius: 4px;
            letter-spacing: 0.04em;
        }

        /* Metronic Cards */
        .analytics-card {
            background: #ffffff;
            border-radius: 0.75rem;
            border: 1px solid #eff2f5;
            box-shadow: 0 1px 3px rgba(82, 63, 105, 0.04);
            transition: all 0.2s ease;
        }

        .analytics-card:hover {
            box-shadow: 0 4px 14px rgba(82, 63, 105, 0.07);
        }

        .analytics-card .card-header {
            background: transparent;
            padding: 1.25rem 1.5rem 0.5rem;
            border-bottom: none;
        }

        .analytics-card .card-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #181c32;
            margin-bottom: 0;
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .analytics-card .card-body {
            padding: 1rem 1.5rem 1.5rem;
        }

        /* KPI Cards */
        .kpi-card {
            border-radius: 0.75rem;
            border: none;
            padding: 1.5rem;
            color: #ffffff;
            position: relative;
            overflow: hidden;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .kpi-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.08);
        }

        .kpi-card-primary {
            background: linear-gradient(135deg, #009ef7 0%, #0077c5 100%);
        }

        .kpi-card-success {
            background: linear-gradient(135deg, #50cd89 0%, #359b64 100%);
        }

        .kpi-card-info {
            background: linear-gradient(135deg, #7239ea 0%, #5323b6 100%);
        }

        .kpi-card-warning {
            background: linear-gradient(135deg, #f1416c 0%, #c41e48 100%);
        }

        .kpi-icon-wrap {
            width: 46px;
            height: 46px;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.4rem;
            color: #ffffff;
        }

        .kpi-title {
            font-size: 0.85rem;
            font-weight: 600;
            opacity: 0.9;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        .kpi-value {
            font-size: 1.85rem;
            font-weight: 800;
            line-height: 1.2;
            margin-top: 0.75rem;
        }

        .section-header {
            font-size: 1.15rem;
            font-weight: 800;
            color: #181c32;
            margin-bottom: 1.25rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        /* Action Buttons */
        .btn-custom-light {
            background-color: #f5f8fa;
            color: #7e8299;
            font-weight: 600;
            font-size: 0.875rem;
            padding: 0.5rem 1rem;
            border-radius: 0.475rem;
            border: 1px solid #e4e6ef;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            transition: all 0.2s ease;
        }

        .btn-custom-light:hover {
            background-color: #eef3f7;
            color: #3f4254;
        }

        .btn-custom-primary {
            background-color: #009ef7;
            color: #ffffff;
            font-weight: 600;
            font-size: 0.875rem;
            padding: 0.5rem 1rem;
            border-radius: 0.475rem;
            border: none;
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            transition: all 0.2s ease;
        }

        .btn-custom-primary:hover {
            background-color: #0095e8;
            color: #ffffff;
            box-shadow: 0 4px 12px rgba(0, 158, 247, 0.25);
        }

        /* Filter Selector Pill in Card Headers */
        .btn-filter-select {
            background-color: #f5f8fa;
            border: 1px solid #e4e6ef;
            color: #5e6278;
            font-size: 0.8rem;
            font-weight: 600;
            padding: 0.35rem 0.75rem;
            border-radius: 0.4rem;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
        }

        .btn-filter-select:hover,
        .btn-filter-select:focus {
            background-color: #ffffff;
            border-color: #009ef7;
            color: #009ef7;
        }

        .dropdown-menu-custom {
            border-radius: 0.5rem;
            border: 1px solid #eff2f5;
            box-shadow: 0 8px 24px rgba(82, 63, 105, 0.12);
            padding: 0.5rem;
            max-height: 280px;
            overflow-y: auto;
        }

        .dropdown-item-custom {
            padding: 0.45rem 0.85rem;
            border-radius: 0.35rem;
            font-size: 0.82rem;
            font-weight: 600;
            color: #5e6278;
            transition: all 0.15s ease;
        }

        .dropdown-item-custom:hover,
        .dropdown-item-custom.active {
            background-color: #f1faff;
            color: #009ef7;
        }

        .info-popover-icon {
            color: #b5b5c3;
            cursor: pointer;
            font-size: 0.9rem;
            transition: color 0.15s ease;
        }

        .info-popover-icon:hover {
            color: #009ef7;
        }

        .chart-subtitle {
            font-size: 0.82rem;
            color: #7e8299;
            font-weight: 600;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
        }

        /* Print styles */
        @media print {
            .top-navbar, .no-print {
                display: none !important;
            }
            body {
                background: #ffffff;
            }
            .analytics-card {
                box-shadow: none !important;
                border: 1px solid #e4e6ef !important;
                page-break-inside: avoid;
            }
        }
    </style>
</head>
<body>

    <!-- Top Navigation -->
    <header class="top-navbar d-flex justify-content-between align-items-center">
        <div class="d-flex align-items-center gap-3">
            <a href="{{ route('analytics.dashboard') }}" class="brand-text">
                <i class="bi bi-bar-chart-fill text-primary fs-4"></i>
                <span>Analytics Dashboard Preview</span>
            </a>
            <span class="brand-badge">
                <i class="bi bi-check-circle-fill me-1"></i> STATUS: SUCCESS
            </span>
        </div>
        <div class="d-flex align-items-center gap-2">
            <button type="button" class="btn-custom-light no-print" onclick="window.print()">
                <i class="bi bi-printer"></i>
                <span>Print / Save PDF</span>
            </button>
            <a href="{{ route('analytics.dashboard') }}" class="btn-custom-primary no-print">
                <i class="bi bi-arrow-left"></i>
                <span>Back to History</span>
            </a>
        </div>
    </header>

    <!-- Main Container -->
    <main class="container-fluid px-4 py-4" style="max-width: 1400px;">
        
        <!-- Job Metadata Card -->
        <div class="card analytics-card mb-4">
            <div class="card-body py-3 px-4">
                <div class="row align-items-center">
                    <div class="col-lg-3 col-md-6 mb-2 mb-lg-0">
                        <small class="text-muted text-uppercase fw-bold" style="font-size: 0.7rem; letter-spacing: 0.05em;">Job ID Key</small>
                        <div class="font-monospace fw-bold text-dark fs-6 mt-1">
                            <i class="bi bi-hash text-primary"></i> {{ $keyId }}
                        </div>
                    </div>
                    <div class="col-lg-3 col-md-6 mb-2 mb-lg-0">
                        <small class="text-muted text-uppercase fw-bold" style="font-size: 0.7rem; letter-spacing: 0.05em;">Customer / Property</small>
                        <div class="fw-bold text-dark fs-6 mt-1">
                            <i class="bi bi-building text-secondary me-1"></i> Customer {{ $chartPayload['customer_id'] ?? 1 }}
                        </div>
                    </div>
                    <div class="col-lg-3 col-md-6 mb-2 mb-lg-0">
                        <small class="text-muted text-uppercase fw-bold" style="font-size: 0.7rem; letter-spacing: 0.05em;">Calculated Period</small>
                        <div class="fw-bold text-dark fs-6 mt-1">
                            <i class="bi bi-calendar-check text-success me-1"></i>
                            {{ $chartPayload['date_start'] ? \Carbon\Carbon::parse($chartPayload['date_start'])->format('d M Y') : 'N/A' }} — 
                            {{ $chartPayload['date_end'] ? \Carbon\Carbon::parse($chartPayload['date_end'])->format('d M Y') : 'N/A' }}
                        </div>
                    </div>
                    <div class="col-lg-3 col-md-6 text-lg-end">
                        <span class="badge bg-light-success text-success border border-success-subtle px-3 py-2 fw-bold" style="font-size: 0.8rem; background-color: #e8fff3; border-color: #b4f1cd !important;">
                            <i class="bi bi-lightning-charge-fill me-1"></i> Python Calculation Ready
                        </span>
                    </div>
                </div>
            </div>
        </div>

        <!-- SECTION 1: KPI OVERVIEW (4 Cards matching chartreport.vue) -->
        <div class="section-header">
            <i class="bi bi-speedometer2 text-primary"></i>
            <span>KPI Overview</span>
        </div>

        <div class="row g-4 mb-5">
            <!-- Total Booking -->
            <div class="col-xl-3 col-md-6">
                <div class="kpi-card kpi-card-primary">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="kpi-title">Total Booking</span>
                        <div class="kpi-icon-wrap">
                            <i class="bi bi-journal-bookmark-fill"></i>
                        </div>
                    </div>
                    <div class="kpi-value">
                        {{ number_format($chartPayload['kpi_summary']['total_booking'] ?? 0) }}
                    </div>
                    <small class="d-block mt-1 opacity-75" style="font-size: 0.75rem;">Total bookings in selected period</small>
                </div>
            </div>

            <!-- Total Net per Stay -->
            <div class="col-xl-3 col-md-6">
                <div class="kpi-card kpi-card-success">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="kpi-title">Total Net per Stay</span>
                        <div class="kpi-icon-wrap">
                            <i class="bi bi-wallet2"></i>
                        </div>
                    </div>
                    <div class="kpi-value" id="kpi_total_net_display">
                        Rp {{ number_format($chartPayload['kpi_summary']['total_net_per_stay'] ?? 0) }}
                    </div>
                    <small class="d-block mt-1 opacity-75" style="font-size: 0.75rem;">Combined revenue across all stays</small>
                </div>
            </div>

            <!-- Typical Lead Days -->
            <div class="col-xl-3 col-md-6">
                <div class="kpi-card kpi-card-info">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="kpi-title">Typical Lead Days</span>
                        <div class="kpi-icon-wrap">
                            <i class="bi bi-clock-history"></i>
                        </div>
                    </div>
                    <div class="kpi-value">
                        {{ $chartPayload['kpi_summary']['typical_lead_days'] ?? 0 }} <span class="fs-6 fw-normal">Days</span>
                    </div>
                    <small class="d-block mt-1 opacity-75" style="font-size: 0.75rem;">Average lead time before check-in</small>
                </div>
            </div>

            <!-- Average Stay Days -->
            <div class="col-xl-3 col-md-6">
                <div class="kpi-card kpi-card-warning">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="kpi-title">Average Stay Days</span>
                        <div class="kpi-icon-wrap">
                            <i class="bi bi-calendar3"></i>
                        </div>
                    </div>
                    <div class="kpi-value">
                        {{ number_format((float) ($chartPayload['kpi_summary']['average_stay_days'] ?? 0), 2) }} <span class="fs-6 fw-normal">Days</span>
                    </div>
                    <small class="d-block mt-1 opacity-75" style="font-size: 0.75rem;">Length of stay per booking</small>
                </div>
            </div>
        </div>

        <!-- SECTION 2: PERFORMANCE DASHBOARD (8 Charts) -->
        <div class="section-header">
            <i class="bi bi-grid-1x2-fill text-primary"></i>
            <span>Performance Dashboard</span>
        </div>

        <!-- ROW 1: Monthly Check-in & Day of Week Check-in -->
        <div class="row g-4 mb-4">
            <!-- Chart 1: Total Check-in per Month -->
            <div class="col-xl-6">
                <div class="card analytics-card h-100">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span>{{ $chartPayload['total_check_in_monthly']['notes']['judul'] ?? 'Total Check-in per Month' }}</span>
                            <i class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['total_check_in_monthly']['notes']['desc'] ?? 'Jumlah Check in per bulan pada periode terpilih.' }}"></i>
                        </h3>
                    </div>
                    <div class="card-body">
                        <div id="chart_checkin_monthly" style="min-height: 350px;"></div>
                    </div>
                </div>
            </div>

            <!-- Chart 2: Total Check-in per Weekday -->
            <div class="col-xl-6">
                <div class="card analytics-card h-100">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span>{{ $chartPayload['total_check_in_dayofweek']['notes']['judul'] ?? 'Total Check-in per Weekday' }}</span>
                            <i class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['total_check_in_dayofweek']['notes']['desc'] ?? 'Jumlah Check in harian pada periode terpilih.' }}"></i>
                        </h3>
                    </div>
                    <div class="card-body">
                        <div id="chart_checkin_dayofweek" style="min-height: 350px;"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ROW 2: Price Range per Month (with Selector) & OTA Composition (with Selector) -->
        <div class="row g-4 mb-4">
            <!-- Chart 3: Price Range per Month -->
            <div class="col-xl-6">
                <div class="card analytics-card h-100">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span id="price_range_title">{{ $chartPayload['price_range_per_month']['chart_data']['January']['notes']['judul'] ?? 'Price Range per Month' }}</span>
                            <i id="price_range_info_icon" class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['price_range_per_month']['chart_data']['January']['notes']['desc'] ?? 'Jumlah booking pada harga tertentu dalam satu bulan.' }}"></i>
                        </h3>
                        <div class="dropdown">
                            <button class="btn btn-filter-select dropdown-toggle" type="button" id="monthDropdownBtn" data-bs-toggle="dropdown" aria-expanded="false">
                                <i class="bi bi-funnel-fill text-primary"></i>
                                <span id="selected_month_label">January</span>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end dropdown-menu-custom" aria-labelledby="monthDropdownBtn">
                                @foreach($chartPayload['price_range_per_month']['filter_selector'] as $selector)
                                    <li>
                                        <a class="dropdown-item dropdown-item-custom month-filter-item {{ $loop->first ? 'active' : '' }}" href="#" data-month="{{ $selector['key'] }}">
                                            {{ $selector['label'] }}
                                        </a>
                                    </li>
                                @endforeach
                            </ul>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="chart-subtitle">
                            <i class="bi bi-calendar2-month text-primary me-2"></i>
                            <span id="price_range_subtitle">Viewing: January</span>
                        </div>
                        <div id="chart_price_range_monthly" style="min-height: 330px;"></div>
                    </div>
                </div>
            </div>

            <!-- Chart 4: OTA Composition -->
            <div class="col-xl-6">
                <div class="card analytics-card h-100">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span id="ota_comp_title">{{ $chartPayload['ota_composition_overview']['chart_data']['15']['notes']['judul'] ?? 'Komposisi jumlah booking' }}</span>
                            <i id="ota_comp_info_icon" class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['ota_composition_overview']['chart_data']['15']['notes']['desc'] ?? 'Menunjukan jumlah booking per OTA berdasarkan rentang lead-days.' }}"></i>
                        </h3>
                        <div class="dropdown">
                            <button class="btn btn-filter-select dropdown-toggle" type="button" id="otaTimeframeDropdownBtn" data-bs-toggle="dropdown" aria-expanded="false">
                                <i class="bi bi-funnel-fill text-primary"></i>
                                <span id="selected_timeframe_label">1 - 5 Days</span>
                            </button>
                            <ul class="dropdown-menu dropdown-menu-end dropdown-menu-custom" aria-labelledby="otaTimeframeDropdownBtn">
                                @foreach($chartPayload['ota_composition_overview']['filter_selector'] as $selector)
                                    <li>
                                        <a class="dropdown-item dropdown-item-custom ota-filter-item {{ $loop->first ? 'active' : '' }}" href="#" data-timeframe="{{ $selector['key'] }}" data-label="{{ $selector['label'] }}">
                                            {{ $selector['label'] }}
                                        </a>
                                    </li>
                                @endforeach
                            </ul>
                        </div>
                    </div>
                    <div class="card-body">
                        <div class="chart-subtitle">
                            <i class="bi bi-calendar-range text-primary me-2"></i>
                            <span id="ota_comp_subtitle">Lead Days: 1 - 5 Days</span>
                        </div>
                        <div id="chart_ota_composition" style="min-height: 330px;"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ROW 3: Daily ARR Price & ARR Price Trend -->
        <div class="row g-4 mb-4">
            <!-- Chart 5: Daily ARR Price -->
            <div class="col-xl-6">
                <div class="card analytics-card h-100">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span>{{ $chartPayload['daily_arr_price']['notes']['judul'] ?? 'Daily ARR Price' }}</span>
                            <i class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['daily_arr_price']['notes']['desc'] ?? 'Menunjukkan nilai historikal ARR properti setiap harinya.' }}"></i>
                        </h3>
                    </div>
                    <div class="card-body">
                        <div id="chart_daily_arr_price" style="min-height: 350px;"></div>
                    </div>
                </div>
            </div>

            <!-- Chart 6: ARR Price Trend -->
            <div class="col-xl-6">
                <div class="card analytics-card h-100">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span>{{ $chartPayload['arr_trend']['notes']['judul'] ?? 'ARR Price Trend' }}</span>
                            <i class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['arr_trend']['notes']['desc'] ?? 'Menunjukkan trend ARR properti.' }}"></i>
                        </h3>
                    </div>
                    <div class="card-body">
                        <div id="chart_arr_trend" style="min-height: 350px;"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ROW 4: ARR Seasonal Pattern (Full Width) -->
        <div class="row g-4 mb-4">
            <div class="col-xl-12">
                <div class="card analytics-card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span>{{ $chartPayload['arr_seasonal_pattern']['notes']['judul'] ?? 'ARR Seasonal Pattern' }}</span>
                            <i class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['arr_seasonal_pattern']['notes']['desc'] ?? 'Menunjukkan pola berulang dalam periode tertentu.' }}"></i>
                        </h3>
                    </div>
                    <div class="card-body">
                        <div id="chart_arr_seasonal_pattern" style="min-height: 350px;"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- ROW 5: OTA Price Distribution (Boxplot, Full Width) -->
        <div class="row g-4 mb-5">
            <div class="col-xl-12">
                <div class="card analytics-card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h3 class="card-title">
                            <span>{{ $chartPayload['ota_price_distribution_overview']['notes']['judul'] ?? 'Distribusi harga per malam.' }}</span>
                            <i class="bi bi-info-circle-fill info-popover-icon" data-bs-toggle="tooltip" data-bs-placement="top" title="{{ $chartPayload['ota_price_distribution_overview']['notes']['desc'] ?? 'Menunjukan distribusi harga per malam sebuah kamar untuk setiap OTA.' }}"></i>
                        </h3>
                    </div>
                    <div class="card-body">
                        <div class="chart-subtitle">
                            <i class="bi bi-bar-chart-steps text-primary me-2"></i>
                            <span>5-Number Summary Distribution per OTA (Min, Q1, Median, Q3, Max)</span>
                        </div>
                        <div id="chart_ota_price_distribution" style="min-height: 380px;"></div>
                    </div>
                </div>
            </div>
        </div>

    </main>

    <!-- Bootstrap Bundle JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>

    <!-- Raw Data and Chart Rendering Logic -->
    <script>
        // Initialize tooltips
        const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
        const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));

        // Injected Payload Data from Backend
        const analyticsData = {!! json_encode($chartPayload) !!};

        // Number abbreviation helper matching chartreport.vue
        function abbreviateNumber(num) {
            var n = Number(num) || 0;
            const absNum = Math.abs(n);
            const fmt = (v) => v.toFixed(1).replace(/\.0$/, '');
            let formatted;

            if (absNum >= 1e12) {
                formatted = fmt(n / 1e12) + 'T';
            } else if (absNum >= 1e9) {
                formatted = fmt(n / 1e9) + 'B';
            } else if (absNum >= 1e6) {
                formatted = fmt(n / 1e6) + 'M';
            } else if (absNum >= 1e3) {
                formatted = fmt(n / 1e3) + 'k';
            } else {
                formatted = absNum.toString();
            }

            return (n < 0 ? '-' : '') + formatted;
        }

        // Shared ApexCharts Theme Options
        const sharedColors = ['#009ef7', '#50cd89', '#7239ea', '#ffc700', '#f1416c', '#00d2d3', '#5f27cd'];
        const fontFam = "'Plus Jakarta Sans', -apple-system, sans-serif";

        // =========================================================================
        // CHART 1: Total Check-in per Month (Bar / Column)
        // =========================================================================
        const checkinMonthlySeries = analyticsData.total_check_in_monthly ? analyticsData.total_check_in_monthly.series : [];
        const chartCheckinMonthlyOptions = {
            series: checkinMonthlySeries,
            chart: {
                fontFamily: fontFam,
                height: 350,
                type: 'bar',
                toolbar: { show: false }
            },
            colors: ['#009ef7'],
            plotOptions: {
                bar: {
                    horizontal: false,
                    columnWidth: '55%',
                    borderRadius: 4
                }
            },
            dataLabels: { enabled: false },
            stroke: { show: true, width: 2, colors: ['transparent'] },
            xaxis: {
                title: { text: 'Month', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: { style: { colors: '#7e8299', fontSize: '12px' } }
            },
            yaxis: {
                title: { text: 'Count', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '12px' },
                    formatter: (val) => Number(val).toLocaleString()
                }
            },
            tooltip: {
                y: { formatter: (val) => Number(val).toLocaleString() + ' check-ins' }
            },
            grid: { borderColor: '#eff2f5', strokeDashArray: 4 }
        };
        const chartCheckinMonthly = new ApexCharts(document.querySelector("#chart_checkin_monthly"), chartCheckinMonthlyOptions);
        chartCheckinMonthly.render();


        // =========================================================================
        // CHART 2: Total Check-in per Weekday (Bar / Column)
        // =========================================================================
        const checkinDayOfWeekSeries = analyticsData.total_check_in_dayofweek ? analyticsData.total_check_in_dayofweek.series : [];
        const chartCheckinDayOfWeekOptions = {
            series: checkinDayOfWeekSeries,
            chart: {
                fontFamily: fontFam,
                height: 350,
                type: 'bar',
                toolbar: { show: false }
            },
            colors: ['#50cd89'],
            plotOptions: {
                bar: {
                    horizontal: false,
                    columnWidth: '55%',
                    borderRadius: 4
                }
            },
            dataLabels: { enabled: false },
            stroke: { show: true, width: 2, colors: ['transparent'] },
            xaxis: {
                title: { text: 'Day of Week', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: { style: { colors: '#7e8299', fontSize: '12px' } }
            },
            yaxis: {
                title: { text: 'Count', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '12px' },
                    formatter: (val) => Number(val).toLocaleString()
                }
            },
            tooltip: {
                y: { formatter: (val) => Number(val).toLocaleString() + ' check-ins' }
            },
            grid: { borderColor: '#eff2f5', strokeDashArray: 4 }
        };
        const chartCheckinDayOfWeek = new ApexCharts(document.querySelector("#chart_checkin_dayofweek"), chartCheckinDayOfWeekOptions);
        chartCheckinDayOfWeek.render();


        // =========================================================================
        // CHART 3: Price Range per Month (with Interactive Month Filter)
        // =========================================================================
        const priceRangeData = analyticsData.price_range_per_month ? analyticsData.price_range_per_month.chart_data : {};
        let currentMonth = 'January';
        if (analyticsData.price_range_per_month && analyticsData.price_range_per_month.filter_selector.length > 0) {
            currentMonth = analyticsData.price_range_per_month.filter_selector[0].key;
        }

        const initialPriceRangeSeries = priceRangeData[currentMonth] ? priceRangeData[currentMonth].series : [];

        const chartPriceRangeOptions = {
            series: initialPriceRangeSeries,
            chart: {
                fontFamily: fontFam,
                height: 330,
                type: 'bar',
                toolbar: { show: false }
            },
            colors: ['#7239ea'],
            plotOptions: {
                bar: {
                    horizontal: false,
                    columnWidth: '50%',
                    borderRadius: 4
                }
            },
            dataLabels: { enabled: false },
            xaxis: {
                title: { text: 'Price Range (IDR)', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '11px' },
                    rotate: -45,
                    rotateAlways: true,
                    formatter: function (val) {
                        if (!val) return '';
                        const parts = String(val).split("-");
                        if (parts.length === 2) {
                            return "(" + abbreviateNumber(parts[0]) + " - " + abbreviateNumber(parts[1]) + ")";
                        }
                        return String(val);
                    }
                }
            },
            yaxis: {
                title: { text: 'Booking Count', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '12px' },
                    formatter: (val) => Number(val).toFixed(0)
                }
            },
            tooltip: {
                y: { formatter: (val) => Number(val).toLocaleString() + ' bookings' }
            },
            grid: { borderColor: '#eff2f5', strokeDashArray: 4 }
        };
        const chartPriceRange = new ApexCharts(document.querySelector("#chart_price_range_monthly"), chartPriceRangeOptions);
        chartPriceRange.render();

        // Month filter switcher
        document.querySelectorAll('.month-filter-item').forEach(item => {
            item.addEventListener('click', function (e) {
                e.preventDefault();
                document.querySelectorAll('.month-filter-item').forEach(el => el.classList.remove('active'));
                this.classList.add('active');

                const selectedMonth = this.getAttribute('data-month');
                document.getElementById('selected_month_label').innerText = selectedMonth;
                document.getElementById('price_range_subtitle').innerText = 'Viewing: ' + selectedMonth;

                if (priceRangeData[selectedMonth]) {
                    chartPriceRange.updateSeries(priceRangeData[selectedMonth].series);
                    if (priceRangeData[selectedMonth].notes) {
                        document.getElementById('price_range_title').innerText = priceRangeData[selectedMonth].notes.judul || 'Price Range per Month';
                    }
                }
            });
        });


        // =========================================================================
        // CHART 4: OTA Composition (with Interactive Timeframe Filter)
        // =========================================================================
        const otaCompData = analyticsData.ota_composition_overview ? analyticsData.ota_composition_overview.chart_data : {};
        let currentTimeframe = '15';
        if (analyticsData.ota_composition_overview && analyticsData.ota_composition_overview.filter_selector.length > 0) {
            currentTimeframe = analyticsData.ota_composition_overview.filter_selector[0].key;
        }

        const initialOtaDataset = otaCompData[currentTimeframe] ? otaCompData[currentTimeframe].series : [];
        const chartOtaCompOptions = {
            series: initialOtaDataset.map(d => Number(d.data)),
            labels: initialOtaDataset.map(d => 'OTA ' + d.name),
            chart: {
                fontFamily: fontFam,
                height: 330,
                type: 'donut'
            },
            colors: sharedColors,
            legend: {
                position: 'bottom',
                fontFamily: fontFam,
                fontSize: '12px'
            },
            dataLabels: {
                enabled: true,
                formatter: (val) => val.toFixed(1) + '%'
            },
            tooltip: {
                y: { formatter: (val) => Number(val).toLocaleString() + ' bookings' }
            },
            responsive: [{
                breakpoint: 480,
                options: {
                    chart: { width: 300 },
                    legend: { position: 'bottom' }
                }
            }]
        };
        const chartOtaComp = new ApexCharts(document.querySelector("#chart_ota_composition"), chartOtaCompOptions);
        chartOtaComp.render();

        // Timeframe filter switcher
        document.querySelectorAll('.ota-filter-item').forEach(item => {
            item.addEventListener('click', function (e) {
                e.preventDefault();
                document.querySelectorAll('.ota-filter-item').forEach(el => el.classList.remove('active'));
                this.classList.add('active');

                const selectedTimeframe = this.getAttribute('data-timeframe');
                const label = this.getAttribute('data-label');
                document.getElementById('selected_timeframe_label').innerText = label;
                document.getElementById('ota_comp_subtitle').innerText = 'Lead Days: ' + label;

                if (otaCompData[selectedTimeframe]) {
                    const dataset = otaCompData[selectedTimeframe].series;
                    chartOtaComp.updateOptions({
                        labels: dataset.map(d => 'OTA ' + d.name),
                        series: dataset.map(d => Number(d.data))
                    });
                }
            });
        });


        // =========================================================================
        // CHART 5: Daily ARR Price (Line / Area with Datetime)
        // =========================================================================
        const dailyArrSeries = analyticsData.daily_arr_price ? analyticsData.daily_arr_price.series : [];
        const chartDailyArrOptions = {
            series: dailyArrSeries,
            chart: {
                fontFamily: fontFam,
                height: 350,
                type: 'area',
                toolbar: { show: false },
                zoom: { enabled: false }
            },
            colors: ['#009ef7'],
            fill: {
                type: 'gradient',
                gradient: {
                    shadeIntensity: 1,
                    opacityFrom: 0.35,
                    opacityTo: 0.05,
                    stops: [0, 95, 100]
                }
            },
            dataLabels: { enabled: false },
            stroke: { curve: 'smooth', width: 2 },
            xaxis: {
                type: 'datetime',
                labels: { style: { colors: '#7e8299', fontSize: '11px' } }
            },
            yaxis: {
                title: { text: 'Net per Stay (IDR)', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '12px' },
                    formatter: (val) => abbreviateNumber(val)
                }
            },
            tooltip: {
                x: { format: 'dd MMM yyyy' },
                y: { formatter: (val) => 'Rp ' + Number(val).toLocaleString(undefined, { maximumFractionDigits: 0 }) }
            },
            grid: { borderColor: '#eff2f5', strokeDashArray: 4 }
        };
        const chartDailyArr = new ApexCharts(document.querySelector("#chart_daily_arr_price"), chartDailyArrOptions);
        chartDailyArr.render();


        // =========================================================================
        // CHART 6: ARR Price Trend (Line with Periods)
        // =========================================================================
        const arrTrendSeries = analyticsData.arr_trend ? analyticsData.arr_trend.series : [];
        const chartArrTrendOptions = {
            series: arrTrendSeries,
            chart: {
                fontFamily: fontFam,
                height: 350,
                type: 'line',
                toolbar: { show: false },
                zoom: { enabled: false }
            },
            colors: ['#50cd89'],
            stroke: { curve: 'smooth', width: 3 },
            markers: { size: 4, colors: ['#ffffff'], strokeColors: '#50cd89', strokeWidth: 2 },
            xaxis: {
                type: 'datetime',
                labels: { style: { colors: '#7e8299', fontSize: '11px' } }
            },
            yaxis: {
                title: { text: 'Net per Stay (IDR)', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '12px' },
                    formatter: (val) => abbreviateNumber(val)
                }
            },
            tooltip: {
                x: { format: 'dd MMM yyyy' },
                y: { formatter: (val) => 'Rp ' + Number(val).toLocaleString(undefined, { maximumFractionDigits: 0 }) }
            },
            grid: { borderColor: '#eff2f5', strokeDashArray: 4 }
        };
        const chartArrTrend = new ApexCharts(document.querySelector("#chart_arr_trend"), chartArrTrendOptions);
        chartArrTrend.render();


        // =========================================================================
        // CHART 7: ARR Seasonal Pattern (Line with Positive/Negative Fluctuations)
        // =========================================================================
        const arrSeasonalSeries = analyticsData.arr_seasonal_pattern ? analyticsData.arr_seasonal_pattern.series : [];
        const chartArrSeasonalOptions = {
            series: arrSeasonalSeries,
            chart: {
                fontFamily: fontFam,
                height: 350,
                type: 'line',
                toolbar: { show: false },
                zoom: { enabled: false }
            },
            colors: ['#ffc700'],
            stroke: { curve: 'straight', width: 2 },
            markers: { size: 3, colors: ['#ffffff'], strokeColors: '#ffc700', strokeWidth: 2 },
            xaxis: {
                type: 'datetime',
                labels: { style: { colors: '#7e8299', fontSize: '11px' } }
            },
            yaxis: {
                title: { text: 'Seasonal Fluctuation (IDR)', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '12px' },
                    formatter: (val) => (val >= 0 ? '+' : '') + abbreviateNumber(val)
                }
            },
            tooltip: {
                x: { format: 'dd MMM yyyy' },
                y: { formatter: (val) => (val >= 0 ? '+' : '') + 'Rp ' + Number(val).toLocaleString(undefined, { maximumFractionDigits: 0 }) }
            },
            grid: {
                borderColor: '#eff2f5',
                strokeDashArray: 4,
                yaxis: { lines: { show: true } }
            },
            annotations: {
                yaxis: [{
                    y: 0,
                    borderColor: '#7e8299',
                    strokeDashArray: 2,
                    label: {
                        borderColor: '#7e8299',
                        style: { color: '#ffffff', background: '#7e8299', fontSize: '10px' },
                        text: 'Baseline (0)'
                    }
                }]
            }
        };
        const chartArrSeasonal = new ApexCharts(document.querySelector("#chart_arr_seasonal_pattern"), chartArrSeasonalOptions);
        chartArrSeasonal.render();


        // =========================================================================
        // CHART 8: OTA Price Distribution (ApexCharts BoxPlot: 5-number summary)
        // =========================================================================
        const otaBoxplotRaw = analyticsData.ota_price_distribution_overview ? analyticsData.ota_price_distribution_overview.series : [];
        
        // Transform raw boxplot series [{ name: "3", data: [min, q1, med, q3, max] }] to ApexCharts boxPlot format
        const boxPlotFormattedData = otaBoxplotRaw.map(item => {
            return {
                x: 'OTA ' + item.name,
                y: item.data.map(v => Math.round(Number(v)))
            };
        });

        const chartOtaBoxplotOptions = {
            series: [{
                name: 'Price Range Boxplot',
                type: 'boxPlot',
                data: boxPlotFormattedData
            }],
            chart: {
                fontFamily: fontFam,
                type: 'boxPlot',
                height: 380,
                toolbar: { show: false }
            },
            colors: ['#009ef7', '#50cd89'],
            plotOptions: {
                boxPlot: {
                    colors: {
                        upper: '#009ef7',
                        lower: '#50cd89'
                    }
                }
            },
            xaxis: {
                title: { text: 'Online Travel Agent (OTA)', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: { style: { colors: '#7e8299', fontSize: '12px', fontWeight: 600 } }
            },
            yaxis: {
                title: { text: 'Price Distribution (IDR)', style: { fontWeight: 600, fontSize: '12px', color: '#7e8299' } },
                labels: {
                    style: { colors: '#7e8299', fontSize: '12px' },
                    formatter: (val) => abbreviateNumber(val)
                }
            },
            tooltip: {
                shared: false,
                intersect: true,
                y: {
                    formatter: function(val) {
                        return 'Rp ' + Number(val).toLocaleString();
                    }
                }
            },
            grid: { borderColor: '#eff2f5', strokeDashArray: 4 }
        };
        const chartOtaBoxplot = new ApexCharts(document.querySelector("#chart_ota_price_distribution"), chartOtaBoxplotOptions);
        chartOtaBoxplot.render();
    </script>
</body>
</html>
