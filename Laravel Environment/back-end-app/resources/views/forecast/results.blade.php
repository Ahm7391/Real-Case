<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Forecast Price Trend Analysis | Smart Property Analytics System</title>
    
    <!-- Google Fonts & Bootstrap 5 -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    
    <!-- Chart.js v4 -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>

    <style>
        :root {
            --bs-body-font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            --bs-body-bg: #f8f9fa;
            --bs-body-color: #181c32;
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

        /* Filter Card (Themed according to Invoice/Forecast page) */
        .forecast-filter-card {
            background: #ffffff;
            border-radius: 0.75rem;
            border: 1px solid #eff2f5;
            box-shadow: 0 1px 3px rgba(82, 63, 105, 0.04);
            padding: 1.25rem 1.5rem 1.5rem;
            margin-bottom: 24px;
        }

        .forecast-form-label {
            font-size: 0.75rem;
            font-weight: 700;
            color: #a1a5b7;
            margin-bottom: 0.35rem;
        }

        .forecast-form-control,
        .forecast-form-select {
            border-radius: 0.475rem !important;
            border: 1px solid #e4e6ef !important;
            background-color: #f9f9f9 !important;
            font-size: 0.875rem !important;
            color: #5e6278 !important;
            padding: 0.6rem 0.85rem;
            transition: all 0.2s ease;
        }

        .forecast-form-control:focus,
        .forecast-form-select:focus {
            border-color: #009ef7 !important;
            background-color: #ffffff !important;
            box-shadow: 0 0 0 0.2rem rgba(0, 158, 247, 0.15) !important;
            color: #181c32 !important;
        }

        /* Autocomplete dropdown */
        .autocomplete-wrapper {
            position: relative;
        }

        .autocomplete-list {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            z-index: 1050;
            background: #ffffff;
            border: 1px solid #e4e6ef;
            border-top: none;
            border-radius: 0 0 0.475rem 0.475rem;
            max-height: 260px;
            overflow-y: auto;
            display: none;
            box-shadow: 0 8px 24px rgba(0,0,0,.08);
        }

        .autocomplete-list.show {
            display: block;
        }

        .autocomplete-item {
            padding: 10px 16px;
            cursor: pointer;
            font-size: 0.875rem;
            color: #5e6278;
            transition: background .15s;
        }

        .autocomplete-item:hover,
        .autocomplete-item.active {
            background: #f1f3f9;
            color: #3f4254;
        }

        .autocomplete-item.no-result {
            color: #a1a5b7;
            cursor: default;
        }

        /* Chart card */
        .chart-card {
            background: #ffffff;
            border-radius: 0.75rem;
            border: 1px solid #eff2f5;
            box-shadow: 0 1px 3px rgba(82, 63, 105, 0.04);
            padding: 1.25rem 1.5rem 1.5rem;
        }

        .chart-card .chart-header {
            margin-bottom: 16px;
        }

        .chart-card .chart-title {
            font-size: 20px;
            font-weight: 700;
            color: #181c32;
        }

        .chart-card .chart-subtitle {
            font-size: 13px;
            color: #a1a5b7;
            margin-top: 2px;
        }

        .chart-canvas-wrapper {
            position: relative;
            width: 100%;
            height: 420px;
        }

        /* Stats row */
        .stats-row {
            display: flex;
            flex-wrap: wrap;
            gap: 16px;
            margin-top: 24px;
        }

        .stat-card {
            flex: 1 1 160px;
            background: #ffffff;
            border-radius: 0.625rem;
            border: 1px solid #eff2f5;
            padding: 1.25rem 1.5rem;
            box-shadow: 0 1px 3px rgba(82, 63, 105, 0.04);
            text-align: center;
        }

        .stat-card .stat-label {
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.5px;
            text-transform: uppercase;
            color: #a1a5b7;
            margin-bottom: 6px;
        }

        .stat-card .stat-value {
            font-size: 22px;
            font-weight: 800;
            color: #181c32;
        }

        .stat-card .stat-value.text-success { color: #0bb783 !important; }
        .stat-card .stat-value.text-danger  { color: #f1416c !important; }

        /* Empty state */
        .chart-empty-state {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 380px;
            color: #a1a5b7;
            font-size: 15px;
            flex-direction: column;
            gap: 8px;
        }

        .chart-empty-state svg {
            width: 48px;
            height: 48px;
            opacity: .4;
        }

        /* Legend */
        .chart-legend {
            display: flex;
            flex-wrap: wrap;
            gap: 18px;
            margin-bottom: 12px;
        }

        .chart-legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            font-weight: 600;
            color: #5e6278;
        }

        .chart-legend-swatch {
            width: 28px;
            height: 4px;
            border-radius: 2px;
        }

        .chart-legend-swatch.baseline {
            background: #7239ea;
        }

        .chart-legend-swatch.corrected {
            background: #009ef7;
            border-top: 2px dashed #009ef7;
            height: 0;
            border-bottom: none;
        }

        .chart-legend-swatch-box {
            width: 14px;
            height: 14px;
            border-radius: 3px;
        }

        .chart-legend-swatch-box.upward   { background: rgba(11, 183, 131, 0.3); }
        .chart-legend-swatch-box.downward { background: rgba(241, 65, 108, 0.3); }

        /* Correction Modal Styling */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(24, 28, 50, 0.4);
            backdrop-filter: blur(4px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 9999;
            opacity: 0;
            transition: opacity 0.25s ease-in-out;
        }

        .modal-overlay.show {
            opacity: 1;
        }

        .correction-modal-card {
            background: #ffffff;
            border-radius: 0.75rem;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1);
            width: 100%;
            max-width: 450px;
            padding: 1.5rem;
            border: 1px solid #eff2f5;
            transform: scale(0.9);
            transition: transform 0.25s ease-in-out;
        }

        .modal-overlay.show .correction-modal-card {
            transform: scale(1);
        }

        .correction-modal-title {
            font-size: 0.95rem;
            font-weight: 700;
            color: #181c32;
            text-transform: uppercase;
            margin-bottom: 1rem;
        }

        /* Buttons */
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

        .code-pill {
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            background: #f1f1f4;
            color: #181c32;
            padding: 0.15rem 0.45rem;
            border-radius: 4px;
            font-size: 0.8rem;
        }

        @media print {
            .top-navbar, .no-print {
                display: none !important;
            }
            body {
                background: #ffffff;
            }
            .chart-card, .forecast-filter-card {
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
            <a href="{{ route('forecast.index') }}" class="brand-text">
                <i class="bi bi-graph-up-arrow text-primary fs-4"></i>
                <span>Forecast Price Trend Analysis</span>
            </a>
            <span class="brand-badge">
                <i class="bi bi-check-circle-fill me-1"></i> STATUS: FORECAST READY
            </span>
        </div>
        <div class="d-flex align-items-center gap-2">
            <button type="button" class="btn-custom-light no-print" onclick="window.print()">
                <i class="bi bi-printer"></i>
                <span>Print / PDF</span>
            </button>
            <a href="{{ route('forecast.index') }}" class="btn-custom-light no-print">
                <i class="bi bi-arrow-repeat"></i>
                <span>Forecast Demo</span>
            </a>
            <a href="{{ route('home') }}" class="btn-custom-primary no-print">
                <i class="bi bi-house-door-fill"></i>
                <span>Main Menu</span>
            </a>
        </div>
    </header>

    <!-- Main Container -->
    <main class="container-fluid px-4 py-4" style="max-width: 1360px;">
        
        <!-- Job Metadata Banner if available -->
        @if(!empty($jobId))
        <div class="card forecast-filter-card mb-4 py-3" style="background: #fafbfc;">
            <div class="d-flex flex-wrap justify-content-between align-items-center gap-2">
                <div class="d-flex align-items-center gap-2">
                    <span class="badge bg-primary text-white px-2 py-1">Job ID</span>
                    <code class="code-pill fs-6">{{ $jobId }}</code>
                    <span class="badge bg-light-success text-success border border-success-subtle ms-2 px-2 py-1" style="background: #e8fff3;">
                        <i class="bi bi-check2-circle me-1"></i> 100% Pipeline Processed
                    </span>
                </div>
                <div class="text-muted small">
                    <i class="bi bi-clock-history me-1"></i> {{ $progressRecord ? $progressRecord->updated_at?->diffForHumans() : 'Just now' }}
                </div>
            </div>
        </div>
        @endif

        <!-- Filter Bar -->
        <div class="forecast-filter-card">
            <div class="row g-4 align-items-end">
                
                <!-- Property Search (Locked simulation) -->
                <div class="col-lg-5 col-md-6">
                    <label class="forecast-form-label">
                        Property
                        <i class="bi bi-lock-fill text-muted ms-1" title="Locked simulation property"></i>
                    </label>
                    <div class="autocomplete-wrapper" id="propertyWrapper">
                        <input type="text"
                               class="form-control forecast-form-control"
                               id="propertySearch"
                               value="Property {{ $customerId ?? 1 }}"
                               readonly
                               disabled />
                        <input type="hidden" id="propertyId" value="{{ $customerId ?? 1 }}" />
                    </div>
                </div>

                <!-- Room Type -->
                <div class="col-lg-3 col-md-4">
                    <label class="forecast-form-label">Room Type</label>
                    <select class="form-select forecast-form-select" id="roomTypeSelect" disabled>
                        <option value="">Loading room types…</option>
                    </select>
                </div>

                <!-- Month -->
                <div class="col-lg-2 col-md-3">
                    <label class="forecast-form-label">Month</label>
                    <select class="form-select forecast-form-select" id="monthSelect">
                        @if(!empty($availableMonths))
                            @foreach ($availableMonths as $m)
                                <option value="{{ $m['value'] }}" {{ $m['is_current'] ? 'selected' : '' }}>
                                    {{ $m['text'] }}
                                </option>
                            @endforeach
                        @else
                            <option value="{{ now()->format('Y-m') }}" selected>{{ now()->format('F Y') }}</option>
                        @endif
                    </select>
                </div>

                <!-- Load button -->
                <div class="col-lg-2 col-md-3">
                    <button class="btn btn-custom-primary fw-bold w-100 justify-content-center py-2" id="btnLoadChart">
                        <span class="indicator-label">
                            <i class="bi bi-bar-chart-line me-1"></i> Load Chart
                        </span>
                        <span class="indicator-progress d-none">
                            Loading… <span class="spinner-border spinner-border-sm align-middle ms-1"></span>
                        </span>
                    </button>
                </div>
            </div>
        </div>

        <!-- Chart Area -->
        <div class="chart-card" id="chartCard">
            <div class="chart-header d-flex justify-content-between align-items-start flex-wrap gap-3">
                <div>
                    <div class="chart-title" id="chartTitle">Price Trend Analysis</div>
                    <div class="chart-subtitle" id="chartSubtitle">Comparing baseline forecast vs suggested ML prices</div>
                </div>
                <div class="chart-legend" id="chartLegend" style="display:none;">
                    <div class="chart-legend-item">
                        <span class="chart-legend-swatch baseline"></span> Baseline
                    </div>
                    <div class="chart-legend-item">
                        <span class="chart-legend-swatch corrected"></span> Suggested
                    </div>
                    <div class="chart-legend-item">
                        <span class="chart-legend-swatch-box upward"></span> Upward
                    </div>
                    <div class="chart-legend-item">
                        <span class="chart-legend-swatch-box downward"></span> Downward
                    </div>
                </div>
            </div>

            <!-- Empty state (shown before data is loaded) -->
            <div class="chart-empty-state" id="chartEmptyState">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M21 21H3V3"/><path d="M21 9l-7.5 5.5-4-4L3 17"/>
                </svg>
                <span>No data to display. Please click "Load Chart" above.</span>
            </div>

            <!-- Canvas (hidden until data is loaded) -->
            <div class="chart-canvas-wrapper" id="chartCanvasWrapper" style="display:none;">
                <canvas id="forecastChart"></canvas>
            </div>
        </div>

        <!-- Stats Cards -->
        <div class="stats-row" id="statsRow" style="display:none;">
            <div class="stat-card">
                <div class="stat-label">Avg Baseline</div>
                <div class="stat-value" id="statAvgBaseline">—</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Avg Suggested</div>
                <div class="stat-value" id="statAvgCorrected">—</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Max Gain</div>
                <div class="stat-value text-success" id="statMaxGain">—</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Max Drop</div>
                <div class="stat-value text-danger" id="statMaxDrop">—</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Net Avg Δ</div>
                <div class="stat-value" id="statNetDelta">—</div>
            </div>
        </div>

        <!-- Price Correction Modal -->
        <div id="correctionModal" class="modal-overlay" style="display: none;">
            <div class="correction-modal-card">
                <div class="correction-modal-header">
                    <div class="correction-modal-title">MASUKAN HARGA KOREKSI UNTUK TANGGAL <span id="modalCorrectedDate" class="text-primary"></span>:</div>
                </div>
                <div class="correction-modal-body">
                    <div class="input-group mb-3">
                        <input type="number" id="correctionPriceInput" class="form-control forecast-form-control" placeholder="Correction Price" min="0" oninput="this.value = this.value.replace(/[^0-9]/g, '')">
                        <span class="input-group-text bg-light text-dark border fw-bold">IDR</span>
                    </div>
                    <div class="form-text text-muted mb-4" style="font-size: 0.75rem; color: #a1a5b7 !important;">masukan angka tanpa titik koma</div>
                </div>
                <div class="correction-modal-footer d-flex justify-content-end gap-2">
                    <button type="button" id="btnDeleteCorrection" class="btn btn-danger fw-bold" style="display: none; background-color: #f1416c;">Delete</button>
                    <button type="button" id="btnCancelCorrection" class="btn btn-secondary fw-bold text-dark" style="background-color: #eff2f5; border: none;">Cancel</button>
                    <button type="button" id="btnSaveCorrection" class="btn btn-custom-primary fw-bold">Save</button>
                </div>
            </div>
        </div>

    </main>

    <!-- Bootstrap Bundle JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>

    <script>
    document.addEventListener('DOMContentLoaded', () => {
        // ───────────────── Helpers ─────────────────
        const fmt = new Intl.NumberFormat('id-ID');
        const formatNum = n => fmt.format(n ?? 0);
        const signedNum = n => (n > 0 ? '+' : '') + formatNum(n);

        const debounce = (fn, ms = 300) => {
            let t;
            return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
        };

        // ───────────────── DOM refs ─────────────────
        const propertyInput   = document.getElementById('propertySearch');
        const propertyIdInput = document.getElementById('propertyId');
        const propertyDrop    = document.getElementById('propertyDropdown');
        const roomTypeSelect  = document.getElementById('roomTypeSelect');
        const monthSelect     = document.getElementById('monthSelect');
        const btnLoad         = document.getElementById('btnLoadChart');

        const chartCard        = document.getElementById('chartCard');
        const chartEmptyState  = document.getElementById('chartEmptyState');
        const chartCanvasWrap  = document.getElementById('chartCanvasWrapper');
        const chartLegend      = document.getElementById('chartLegend');
        const chartTitleEl     = document.getElementById('chartTitle');
        const chartSubtitleEl  = document.getElementById('chartSubtitle');
        const statsRow         = document.getElementById('statsRow');

        let chartInstance = null;
        let selectedPropertyName = 'Property {{ $customerId ?? 1 }}';
        let currentChartData = null;

        // Set initial property input & automatically load room types
        if (propertyInput) {
            propertyInput.value = 'Property {{ $customerId ?? 1 }}';
        }
        loadRoomTypes(propertyIdInput ? (propertyIdInput.value || 1) : 1);

        // ───────────────── Room types ─────────────────
        async function loadRoomTypes(propertyId) {
            roomTypeSelect.disabled  = true;
            roomTypeSelect.innerHTML = '<option value="">Loading…</option>';
            btnLoad.disabled = true;

            try {
                const res = await fetch(`{{ route('forecast.search-room-types') }}?property_id=${propertyId}`, {
                    headers: { Accept: 'application/json' }
                });
                const data = await res.json();

                roomTypeSelect.innerHTML = '';
                data.forEach(rt => {
                    const opt = document.createElement('option');
                    opt.value = rt.id;
                    opt.text  = rt.name;
                    roomTypeSelect.appendChild(opt);
                });
                roomTypeSelect.disabled = false;
                btnLoad.disabled = false;
            } catch (e) {
                roomTypeSelect.innerHTML = '<option value="">Error loading</option>';
                console.error(e);
            }
        }

        roomTypeSelect.addEventListener('change', () => {
            btnLoad.disabled = !roomTypeSelect.value;
        });

        // ───────────────── Load Chart ─────────────────
        btnLoad.addEventListener('click', loadChartData);

        async function loadChartData() {
            const propertyId  = propertyIdInput.value || 1;
            const roomTypeId  = roomTypeSelect.value;
            const month       = monthSelect.value;

            // Show loading state
            btnLoad.querySelector('.indicator-label').classList.add('d-none');
            btnLoad.querySelector('.indicator-progress').classList.remove('d-none');
            btnLoad.disabled = true;

            try {
                const url = `{{ route('forecast.chart-data') }}?property_id=${propertyId}&room_type_id=${encodeURIComponent(roomTypeId || '')}&month=${month}`;
                const res = await fetch(url, { headers: { Accept: 'application/json' } });
                const data = await res.json();

                currentChartData = data;
                renderChart(data);
            } catch (e) {
                console.error(e);
                alert('Failed to load chart data. Please try again.');
            } finally {
                btnLoad.querySelector('.indicator-label').classList.remove('d-none');
                btnLoad.querySelector('.indicator-progress').classList.add('d-none');
                btnLoad.disabled = false;
            }
        }

        // ───────────────── Chart.js custom plugin — area fill between two datasets ─────────────────
        const areaFillPlugin = {
            id: 'areaFillBetween',
            beforeDatasetsDraw(chart) {
                const { ctx, scales: { x, y }, data } = chart;

                const baselineMeta  = chart.getDatasetMeta(0);
                const correctedMeta = chart.getDatasetMeta(1);

                if (!baselineMeta.data.length || !correctedMeta.data.length) return;

                const baselineData  = data.datasets[0].data;
                const correctedData = data.datasets[1].data;

                ctx.save();

                // Walk through each pair of points and fill the area between
                for (let i = 0; i < baselineMeta.data.length - 1; i++) {
                    const x0 = baselineMeta.data[i].x;
                    const x1 = baselineMeta.data[i + 1].x;

                    const bY0 = baselineMeta.data[i].y;
                    const bY1 = baselineMeta.data[i + 1].y;
                    const cY0 = correctedMeta.data[i].y;
                    const cY1 = correctedMeta.data[i + 1].y;

                    const b0 = baselineData[i];
                    const b1 = baselineData[i + 1];
                    const c0 = correctedData[i];
                    const c1 = correctedData[i + 1];

                    // Skip segments where both values are 0 (no data)
                    if (b0 === 0 && c0 === 0 && b1 === 0 && c1 === 0) continue;

                    // Determine if lines cross in this segment
                    const diff0 = c0 - b0;
                    const diff1 = c1 - b1;
                    const cross = diff0 * diff1 < 0; // sign change = crossing

                    if (cross) {
                        const t = diff0 / (diff0 - diff1);
                        const ix = x0 + t * (x1 - x0);
                        const iy = bY0 + t * (bY1 - bY0);

                        // First half
                        drawFillSegment(ctx, x0, bY0, cY0, ix, iy, iy, diff0 > 0);
                        // Second half
                        drawFillSegment(ctx, ix, iy, iy, x1, bY1, cY1, diff1 > 0);
                    } else {
                        const upward = (c0 + c1) >= (b0 + b1);
                        drawFillSegment(ctx, x0, bY0, cY0, x1, bY1, cY1, upward);
                    }
                }

                ctx.restore();
            }
        };

        function drawFillSegment(ctx, x0, bY0, cY0, x1, bY1, cY1, isUpward) {
            ctx.beginPath();
            ctx.moveTo(x0, bY0);
            ctx.lineTo(x1, bY1);
            ctx.lineTo(x1, cY1);
            ctx.lineTo(x0, cY0);
            ctx.closePath();
            ctx.fillStyle = isUpward
                ? 'rgba(11, 183, 131, 0.3)'   // green — corrected > baseline
                : 'rgba(241, 65, 108, 0.3)';  // red   — corrected < baseline
            ctx.fill();
        }

        // ───────────────── Render / update chart ─────────────────
        function renderChart(data) {
            const { labels, forecasted, corrected, stats } = data;

            if (!labels || labels.length === 0) {
                chartEmptyState.style.display = 'flex';
                chartCanvasWrap.style.display = 'none';
                chartLegend.style.display     = 'none';
                statsRow.style.display        = 'none';
                return;
            }

            // Show canvas, hide empty state
            chartEmptyState.style.display = 'none';
            chartCanvasWrap.style.display = 'block';
            chartLegend.style.display     = 'flex';

            // Update header
            const roomName = roomTypeSelect.options[roomTypeSelect.selectedIndex]?.text || 'All Rooms';
            chartTitleEl.textContent   = 'Price Trend Analysis';
            chartSubtitleEl.textContent = `${selectedPropertyName} — ${roomName} — ${monthSelect.options[monthSelect.selectedIndex]?.text || ''}`;

            // Destroy old chart
            if (chartInstance) {
                chartInstance.destroy();
                chartInstance = null;
            }

            const canvas = document.getElementById('forecastChart');
            const ctx    = canvas.getContext('2d');

            chartInstance = new Chart(ctx, {
                type: 'line',
                plugins: [areaFillPlugin],
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Baseline',
                            data: forecasted,
                            borderColor: '#7239ea',
                            backgroundColor: '#7239ea',
                            borderWidth: 2.5,
                            tension: 0.35,
                            pointRadius: 3,
                            pointHoverRadius: 6,
                            pointBackgroundColor: '#7239ea',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2,
                            order: 1,
                        },
                        {
                            label: 'Suggested',
                            data: corrected,
                            borderColor: '#009ef7',
                            backgroundColor: '#009ef7',
                            borderWidth: 2.5,
                            borderDash: [6, 4],
                            tension: 0.35,
                            pointRadius: 4,
                            pointHoverRadius: 7,
                            pointBackgroundColor: '#009ef7',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2,
                            pointStyle: 'circle',
                            order: 0,
                        }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        mode: 'index',
                        intersect: false,
                    },
                    onClick: (event, elements, chart) => {
                        const points = chart.getElementsAtEventForMode(event, 'nearest', { intersect: true }, true);
                        if (points.length) {
                            const firstPoint = points[0];
                            if (firstPoint.datasetIndex === 1) {
                                openCorrectionModal(firstPoint.index);
                            }
                        }
                    },
                    onHover: (event, elements) => {
                        if (elements.length && elements[0].datasetIndex === 1) {
                            event.chart.canvas.style.cursor = 'pointer';
                        } else {
                            event.chart.canvas.style.cursor = 'default';
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: '#1e1e2d',
                            titleColor: '#ffffff',
                            bodyColor: '#cdcdde',
                            borderColor: '#3f4254',
                            borderWidth: 1,
                            cornerRadius: 8,
                            padding: 14,
                            titleFont: { size: 13, weight: '700' },
                            bodyFont: { size: 12 },
                            callbacks: {
                                title(items) {
                                    return items[0]?.label || '';
                                },
                                label(item) {
                                    const index = item.dataIndex;
                                    const detail = currentChartData && currentChartData.correction_details ? currentChartData.correction_details[index] : null;
                                    const val = formatNum(item.raw);

                                    if (detail && detail.is_corrected) {
                                        if (item.datasetIndex === 0) {
                                            return `■  Baseline Price: Rp ${formatNum(detail.baseline_price)}`;
                                        } else if (item.datasetIndex === 1) {
                                            return [
                                                `■  Suggested Price (Original): Rp ${formatNum(detail.suggested_price)}`,
                                                `■  Price Corrected by User: Rp ${formatNum(detail.user_corrected_price)}`,
                                                `■  Modified By: ${detail.modified_by_name}`,
                                                `■  Modified At: ${detail.corrected_at}`
                                            ];
                                        }
                                    }

                                    if (item.datasetIndex === 0) return `■  Baseline Price: Rp ${val}`;
                                    if (item.datasetIndex === 1) return `■  Suggested Price: Rp ${val}`;
                                    return val;
                                },
                                afterBody(items) {
                                    if (items.length < 2) return '';
                                    const index = items[0].dataIndex;
                                    const detail = currentChartData && currentChartData.correction_details ? currentChartData.correction_details[index] : null;
                                    if (detail && detail.is_corrected) {
                                        return '';
                                    }

                                    const bItem = items.find(i => i.datasetIndex === 0);
                                    const cItem = items.find(i => i.datasetIndex === 1);
                                    if (!bItem || !cItem) return '';
                                    
                                    const baseline  = bItem.raw;
                                    const corrected = cItem.raw;
                                    if (baseline === 0 && corrected === 0) return '';
                                    
                                    const diff = corrected - baseline;
                                    const pct  = baseline !== 0 ? ((diff / baseline) * 100).toFixed(1) : '—';
                                    const arrow = diff > 0 ? '▲' : (diff < 0 ? '▼' : '▬');
                                    
                                    return `\n${arrow}  Δ Rp ${signedNum(diff)}  (${diff > 0 ? '+' : ''}${pct}%)`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: {
                                color: '#a1a5b7',
                                font: { size: 11 },
                                maxRotation: 45,
                                autoSkip: true,
                                maxTicksLimit: 16,
                            }
                        },
                        y: {
                            grid: {
                                color: '#eff2f5',
                                drawBorder: false,
                            },
                            ticks: {
                                color: '#a1a5b7',
                                font: { size: 11 },
                                callback: v => 'Rp ' + formatNum(v),
                            },
                            beginAtZero: false,
                        }
                    }
                }
            });

            // ── Update stats ──
            if (stats) {
                statsRow.style.display = 'flex';
                document.getElementById('statAvgBaseline').textContent  = 'Rp ' + formatNum(stats.avg_baseline);
                document.getElementById('statAvgCorrected').textContent = 'Rp ' + formatNum(stats.avg_corrected);
                document.getElementById('statMaxGain').textContent      = 'Rp ' + signedNum(stats.max_gain);
                document.getElementById('statMaxDrop').textContent      = 'Rp ' + signedNum(stats.max_drop);

                const deltaEl = document.getElementById('statNetDelta');
                deltaEl.textContent = 'Rp ' + signedNum(stats.net_avg_delta);
                deltaEl.classList.remove('text-success', 'text-danger');
                if (stats.net_avg_delta > 0) deltaEl.classList.add('text-success');
                else if (stats.net_avg_delta < 0) deltaEl.classList.add('text-danger');
            } else {
                statsRow.style.display = 'none';
            }
        }

        // ───────────────── Correction Modal Handlers ─────────────────
        let currentSelectedIndex = null;

        function openCorrectionModal(index) {
            currentSelectedIndex = index;
            const rawDate = currentChartData.full_dates[index];
            const detail = currentChartData.correction_details[index];

            document.getElementById('modalCorrectedDate').textContent = rawDate;
            const input = document.getElementById('correctionPriceInput');
            const btnDelete = document.getElementById('btnDeleteCorrection');

            if (detail && detail.is_corrected) {
                input.value = detail.user_corrected_price;
                btnDelete.style.display = 'inline-block';
            } else {
                input.value = '';
                btnDelete.style.display = 'none';
            }

            const modal = document.getElementById('correctionModal');
            modal.style.display = 'flex';
            modal.offsetHeight; // force reflow
            modal.classList.add('show');
        }

        function closeCorrectionModal() {
            const modal = document.getElementById('correctionModal');
            modal.classList.remove('show');
            setTimeout(() => {
                modal.style.display = 'none';
            }, 250);
        }

        document.getElementById('btnCancelCorrection').addEventListener('click', closeCorrectionModal);

        // Save correction
        document.getElementById('btnSaveCorrection').addEventListener('click', async () => {
            const input = document.getElementById('correctionPriceInput');
            const priceVal = input.value.trim();

            if (priceVal === '') {
                alert('Please enter a correction price.');
                return;
            }

            const price = parseInt(priceVal.replace(/[^0-9]/g, ''), 10);
            if (isNaN(price) || price < 0) {
                alert('Please enter a valid price without periods or commas.');
                return;
            }

            const propertyId = propertyIdInput.value || 1;
            const roomTypeId = roomTypeSelect.value || 0;
            const rawDate = currentChartData.full_dates[currentSelectedIndex];

            try {
                const res = await fetch(`{{ route('forecast.save-correction') }}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRF-TOKEN': '{{ csrf_token() }}'
                    },
                    body: JSON.stringify({
                        customer_id: propertyId,
                        room_type_id: roomTypeId,
                        corrected_date: rawDate,
                        user_corrected_price: price
                    })
                });

                const data = await res.json();
                if (res.ok) {
                    closeCorrectionModal();
                    await loadChartData();
                } else {
                    alert(data.message || 'Failed to save correction.');
                }
            } catch (e) {
                console.error(e);
                alert('An error occurred while saving.');
            }
        });

        // Delete correction
        document.getElementById('btnDeleteCorrection').addEventListener('click', async () => {
            if (!confirm('Are you sure you want to delete this correction and revert to the original suggested price?')) {
                return;
            }

            const propertyId = propertyIdInput.value || 1;
            const roomTypeId = roomTypeSelect.value || 0;
            const rawDate = currentChartData.full_dates[currentSelectedIndex];

            try {
                const res = await fetch(`{{ route('forecast.delete-correction') }}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'X-CSRF-TOKEN': '{{ csrf_token() }}'
                    },
                    body: JSON.stringify({
                        customer_id: propertyId,
                        room_type_id: roomTypeId,
                        corrected_date: rawDate
                    })
                });

                const data = await res.json();
                if (res.ok) {
                    closeCorrectionModal();
                    await loadChartData();
                } else {
                    alert(data.message || 'Failed to delete correction.');
                }
            } catch (e) {
                console.error(e);
                alert('An error occurred while deleting.');
            }
        });

        // Auto load initial room types and chart
        loadRoomTypes(propertyIdInput.value || 1).then(() => {
            loadChartData();
        });
    });
    </script>
</body>
</html>
