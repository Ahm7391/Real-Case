<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Analytics Dashboard | Smart Property Analytics System</title>
    
    <!-- Google Fonts & Bootstrap 5 Icons -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    
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
            background-color: #f1f1f4;
            color: #5e6278;
            font-size: 0.72rem;
            font-weight: 600;
            padding: 0.2rem 0.5rem;
            border-radius: 4px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
        }

        /* Invoice & Card Styles derived from views/invoices/new.blade.php */
        .invoice-page-card {
            background: #ffffff;
            border-radius: 0.75rem;
            border: 1px solid #eff2f5;
            box-shadow: 0 1px 3px rgba(82, 63, 105, 0.04);
            transition: box-shadow 0.2s ease;
        }

        .invoice-page-card:hover {
            box-shadow: 0 4px 12px rgba(82, 63, 105, 0.06);
        }

        .invoice-page-card .card-header {
            background: transparent;
            padding: 1.25rem 1.5rem 0;
            border-bottom: none;
        }

        .invoice-page-card .card-body {
            padding: 1.25rem 1.5rem 1.5rem;
        }

        .invoice-section-title {
            font-size: 0.7rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            color: #a1a5b7;
            margin-bottom: 1rem;
        }

        .invoice-form-label {
            font-size: 0.75rem;
            font-weight: 700;
            color: #a1a5b7;
            margin-bottom: 0.35rem;
            display: block;
        }

        .invoice-form-control,
        .invoice-form-select {
            border-radius: 0.475rem !important;
            border: 1px solid #e4e6ef !important;
            background-color: #f9f9f9 !important;
            font-size: 0.875rem !important;
            color: #5e6278 !important;
            padding: 0.6rem 0.85rem;
            transition: all 0.2s ease;
        }

        .invoice-form-control:focus,
        .invoice-form-select:focus {
            border-color: #009ef7 !important;
            background-color: #ffffff !important;
            box-shadow: 0 0 0 0.2rem rgba(0, 158, 247, 0.15) !important;
            color: #181c32 !important;
        }

        .invoice-form-control:disabled,
        .invoice-form-control[readonly] {
            background-color: #f1f1f4 !important;
            color: #7e8299 !important;
            cursor: not-allowed;
        }

        /* Items / History Table derived from Metronic & new.blade.php */
        .invoice-table-wrap {
            border-radius: 0.625rem;
            overflow-x: auto;
            border: 1px solid #eff2f5;
            background: #ffffff;
        }

        .invoice-items-table {
            width: 100%;
            margin-bottom: 0;
            vertical-align: middle;
        }

        .invoice-items-table thead th {
            background-color: #f9f9f9;
            font-size: 0.7rem;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            color: #a1a5b7;
            white-space: nowrap;
            border-bottom: 1px solid #eff2f5;
            padding: 0.85rem 1rem;
            font-weight: 700;
        }

        .invoice-items-table tbody td {
            padding: 0.85rem 1rem;
            border-bottom: 1px solid #f1f1f4;
            color: #5e6278;
            font-size: 0.875rem;
            font-variant-numeric: tabular-nums;
        }

        .invoice-items-table tbody tr:last-child td {
            border-bottom: none;
        }

        .invoice-items-table tbody tr:hover td {
            background-color: #fafbfc;
        }

        /* Status Badges */
        .badge-status {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.35rem 0.65rem;
            border-radius: 0.4rem;
            letter-spacing: 0.02em;
        }

        .badge-status-1 {
            background-color: #fff8dd;
            color: #f1416c;
            color: #cd6200;
            border: 1px solid #ffe69c;
        }

        .badge-status-2 {
            background-color: #e8fff3;
            color: #50cd89;
            border: 1px solid #b4f1cd;
        }

        .badge-status-3 {
            background-color: #fff5f8;
            color: #f1416c;
            border: 1px solid #fcced9;
        }

        .badge-status-sm {
            padding: 0.15rem 0.45rem !important;
            font-size: 0.68rem !important;
            line-height: 1.15 !important;
            border-radius: 0.3rem !important;
        }

        .btn-see-results {
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
            background-color: #009ef7;
            color: #ffffff;
            font-size: 0.72rem;
            font-weight: 600;
            padding: 0.2rem 0.5rem;
            border-radius: 0.35rem;
            text-decoration: none;
            transition: all 0.2s ease;
            box-shadow: 0 1px 3px rgba(0, 158, 247, 0.2);
            white-space: nowrap;
            line-height: 1.2;
        }

        .btn-see-results:hover {
            background-color: #0095e8;
            color: #ffffff;
            box-shadow: 0 2px 6px rgba(0, 158, 247, 0.35);
            transform: translateY(-1px);
        }

        /* Pulsing Dot for In Progress */
        .pulsing-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background-color: currentColor;
            display: inline-block;
            animation: pulse-dot 1.5s infinite;
        }

        @keyframes pulse-dot {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.3; transform: scale(0.7); }
            100% { opacity: 1; transform: scale(1); }
        }

        /* Action Buttons */
        .btn-custom-primary {
            background-color: #009ef7;
            color: #ffffff;
            font-weight: 600;
            font-size: 0.875rem;
            padding: 0.6rem 1.25rem;
            border-radius: 0.475rem;
            border: none;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 0.4rem;
        }

        .btn-custom-primary:hover {
            background-color: #0095e8;
            color: #ffffff;
            box-shadow: 0 4px 12px rgba(0, 158, 247, 0.25);
        }

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

        /* Helper code box */
        .code-pill {
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            background: #f1f1f4;
            color: #181c32;
            padding: 0.15rem 0.4rem;
            border-radius: 4px;
            font-size: 0.8rem;
        }
    </style>
</head>
<body>

    <!-- Top Navigation -->
    <header class="top-navbar d-flex justify-content-between align-items-center">
        <div class="d-flex align-items-center gap-3">
            <a href="{{ route('home') }}" class="brand-text">
                <i class="bi bi-globe2 text-primary"></i>
                <span>Smart Property Analytics System</span>
            </a>
            <span class="brand-badge">Pipeline Demo</span>
        </div>
        <div>
            <a href="{{ route('home') }}" class="btn-custom-light">
                <i class="bi bi-arrow-left"></i>
                <span>Back to Menu</span>
            </a>
        </div>
    </header>

    <!-- Main Content Container -->
    <main class="container-fluid px-4 py-4" style="max-width: 1320px;">
        
        <!-- Page Title & Header Section -->
        <div class="d-flex flex-wrap justify-content-between align-items-center mb-4 pb-2">
            <div>
                <h1 class="h3 fw-bold text-dark mb-1">Analytics Dashboard</h1>
                <p class="text-muted small mb-0">Simulate date range requests to local Python FastAPI pipeline and track real-time job execution history.</p>
            </div>
            <div class="d-flex gap-2 mt-3 mt-md-0">
                <button type="button" class="btn-custom-light" onclick="window.location.reload();">
                    <i class="bi bi-arrow-clockwise"></i>
                    <span>Refresh History</span>
                </button>
            </div>
        </div>

        <!-- Flash Alerts -->
        @if (session('success'))
            <div class="alert alert-success alert-dismissible fade show border-0 shadow-sm mb-4" role="alert" style="border-radius: 0.625rem; background-color: #e8fff3; color: #50cd89;">
                <div class="d-flex align-items-center">
                    <i class="bi bi-check-circle-fill me-2 fs-5"></i>
                    <div>
                        <strong class="text-dark">Success!</strong> {{ session('success') }}
                    </div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        @endif

        @if (session('info'))
            <div class="alert alert-info alert-dismissible fade show border-0 shadow-sm mb-4" role="alert" style="border-radius: 0.625rem; background-color: #f1faff; color: #009ef7;">
                <div class="d-flex align-items-center">
                    <i class="bi bi-info-circle-fill me-2 fs-5"></i>
                    <div>
                        <strong class="text-dark">Notice:</strong> {{ session('info') }}
                    </div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        @endif

        @if (session('warning'))
            <div class="alert alert-warning alert-dismissible fade show border-0 shadow-sm mb-4" role="alert" style="border-radius: 0.625rem; background-color: #fff8dd; color: #f1416c;">
                <div class="d-flex align-items-center">
                    <i class="bi bi-exclamation-triangle-fill me-2 fs-5"></i>
                    <div>
                        <strong class="text-dark">Warning:</strong> {{ session('warning') }}
                    </div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        @endif

        @if ($errors->any())
            <div class="alert alert-danger alert-dismissible fade show border-0 shadow-sm mb-4" role="alert" style="border-radius: 0.625rem; background-color: #fff5f8; color: #f1416c;">
                <div class="d-flex align-items-start">
                    <i class="bi bi-x-circle-fill me-2 fs-5 mt-1"></i>
                    <div>
                        <strong class="text-dark">Validation Error:</strong>
                        <ul class="mb-0 mt-1 ps-3">
                            @foreach ($errors->all() as $error)
                                <li>{{ $error }}</li>
                            @endforeach
                        </ul>
                    </div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        @endif

        <!-- Request Generator Card (Style and Accent matching views/new.blade.php) -->
        <div class="card invoice-page-card mb-4">
            <div class="card-header">
                <div class="invoice-section-title">Request Property Analytics Calculation</div>
            </div>
            <div class="card-body pt-2">
                <form id="analytics_request_form" method="POST" action="{{ route('analytics.request') }}">
                    @csrf
                    
                    <div class="row g-3 align-items-end">
                        <!-- Customer ID (Locked for Simulation) -->
                        <div class="col-lg-3 col-md-6">
                            <label class="invoice-form-label" for="customer_id_display">
                                Customer / Property ID
                                <i class="bi bi-lock-fill text-muted ms-1" title="Locked simulation field"></i>
                            </label>
                            <input type="hidden" name="customer_id" value="1">
                            <input type="text" id="customer_id_display" class="form-control invoice-form-control"
                                   value="Customer 1" readonly disabled>
                            <small class="text-muted d-block mt-1" style="font-size: 0.72rem;">
                                <i class="bi bi-check2 text-success"></i> Locked to seeded simulation customer
                            </small>
                        </div>

                        <!-- Date Start -->
                        <div class="col-lg-3 col-md-6">
                            <label class="invoice-form-label" for="day_start">
                                Date Range Start (day_start)
                            </label>
                            <input type="date" id="day_start" name="day_start"
                                   value="{{ old('day_start', now()->subDays(30)->format('Y-m-d')) }}"
                                   min="{{ now()->subDays(365)->format('Y-m-d') }}"
                                   max="{{ now()->format('Y-m-d') }}"
                                   class="form-control invoice-form-control @error('day_start') is-invalid @enderror"
                                   required>
                        </div>

                        <!-- Date End -->
                        <div class="col-lg-3 col-md-6">
                            <label class="invoice-form-label" for="day_end">
                                Date Range End (day_end)
                            </label>
                            <input type="date" id="day_end" name="day_end"
                                   value="{{ old('day_end', now()->format('Y-m-d')) }}"
                                   min="{{ now()->subDays(365)->format('Y-m-d') }}"
                                   max="{{ now()->format('Y-m-d') }}"
                                   class="form-control invoice-form-control @error('day_end') is-invalid @enderror"
                                   required>
                        </div>

                        <!-- Submit Button -->
                        <div class="col-lg-3 col-md-6">
                            <button type="submit" id="submit_btn" class="btn-custom-primary w-100 justify-content-center py-2">
                                <i class="bi bi-send-fill"></i>
                                <span>Send to Python Pipeline</span>
                            </button>
                        </div>
                    </div>
                </form>
            </div>
        </div>

        <!-- Job-Request History Table Section -->
        <div class="card invoice-page-card">
            <div class="card-header d-flex flex-wrap justify-content-between align-items-center">
                <div class="invoice-section-title mb-0">Job-Request History & Status Monitor</div>
                <div class="d-flex gap-2">
                    <span class="badge bg-light text-dark border px-2 py-1" style="font-size: 0.75rem;">
                        Total Logged: {{ count($history) }}
                    </span>
                </div>
            </div>
            <div class="card-body pt-3">
                <div class="invoice-table-wrap">
                    <table class="invoice-items-table">
                        <thead>
                            <tr>
                                <th style="width: 18%;">Job ID Key</th>
                                <th style="width: 15%;">Customer</th>
                                <th style="width: 20%;">Status</th>
                                <th style="width: 25%;">Pipeline Message</th>
                                <th style="width: 22%;">Date Request</th>
                            </tr>
                        </thead>
                        <tbody>
                            @forelse ($history as $item)
                                <tr>
                                    <td>
                                        <div class="d-flex align-items-center gap-1 font-monospace fw-bold text-dark">
                                            <i class="bi bi-hash text-muted"></i>
                                            <span>{{ $item->job_id_key }}</span>
                                        </div>
                                    </td>
                                    <td>
                                        <span class="badge bg-light text-secondary border">
                                            Customer {{ $item->customer_id }}
                                        </span>
                                    </td>
                                    <td>
                                        @if ($item->status === 1)
                                            <span class="badge-status badge-status-1">
                                                <span class="pulsing-dot"></span>
                                                <span>1 [IN PROGRESS]</span>
                                            </span>
                                        @elseif ($item->status === 2)
                                            <div class="d-flex flex-column align-items-start gap-1">
                                                <span class="badge-status badge-status-2 badge-status-sm">
                                                    <i class="bi bi-check-circle"></i>
                                                    <span>2 [SUCCESS]</span>
                                                </span>
                                                <a href="{{ route('analytics.results', $item->job_id_key) }}" target="_blank" class="btn-see-results" title="Open analytics chart results in a new tab">
                                                    <i class="bi bi-bar-chart-line-fill"></i>
                                                    <span>See Results</span>
                                                    <i class="bi bi-box-arrow-up-right ms-1" style="font-size: 0.65rem;"></i>
                                                </a>
                                            </div>
                                        @elseif ($item->status === 3)
                                            <span class="badge-status badge-status-3">
                                                <i class="bi bi-x-circle"></i>
                                                <span>3 [FAULT]</span>
                                            </span>
                                        @else
                                            <span class="badge bg-secondary">
                                                {{ $item->status }}
                                            </span>
                                        @endif
                                    </td>
                                    <td>
                                        <div class="text-truncate" style="max-width: 320px;" title="{{ $item->message }}">
                                            {{ $item->message }}
                                        </div>
                                    </td>
                                    <td>
                                        <div class="d-flex flex-column" style="font-size: 0.82rem;">
                                            <span class="text-dark fw-semibold">
                                                {{ $item->date_request ? $item->date_request->format('Y-m-d H:i:s') : ($item->created_at ? $item->created_at->format('Y-m-d H:i:s') : '-') }}
                                            </span>
                                            <small class="text-muted" style="font-size: 0.72rem;">
                                                {{ $item->date_request ? $item->date_request->diffForHumans() : '' }}
                                            </small>
                                        </div>
                                    </td>
                                </tr>
                            @empty
                                <tr>
                                    <td colspan="5" class="text-center py-5">
                                        <div class="text-muted">
                                            <i class="bi bi-inbox fs-1 d-block mb-2 text-secondary opacity-50"></i>
                                            <p class="mb-1 fw-semibold">No analytics job requests recorded yet</p>
                                            <p class="small text-muted mb-0">Use the request form above to send your first calculation request to the Python FastAPI pipeline.</p>
                                        </div>
                                    </td>
                                </tr>
                            @endforelse
                        </tbody>
                    </table>
                </div>

                <!-- Pagination if available -->
                @if (method_exists($history, 'links') && $history->hasPages())
                    <div class="mt-4 d-flex justify-content-end">
                        {{ $history->links('pagination::bootstrap-5') }}
                    </div>
                @endif
            </div>
        </div>

    </main>

    <!-- Bootstrap Bundle JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Smooth form submission feedback
        const form = document.getElementById('analytics_request_form');
        const submitBtn = document.getElementById('submit_btn');

        if (form && submitBtn) {
            form.addEventListener('submit', function() {
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status"></span>Sending...';
            });
        }

        // Date range restriction & synchronization [now - 365 days : now]
        const dayStartInput = document.getElementById('day_start');
        const dayEndInput = document.getElementById('day_end');
        const minAllowedDate = '{{ now()->subDays(365)->format('Y-m-d') }}';
        const maxAllowedDate = '{{ now()->format('Y-m-d') }}';

        if (dayStartInput && dayEndInput) {
            dayStartInput.addEventListener('change', function() {
                if (this.value && this.value < minAllowedDate) this.value = minAllowedDate;
                if (this.value && this.value > maxAllowedDate) this.value = maxAllowedDate;
                dayEndInput.min = this.value || minAllowedDate;
                if (dayEndInput.value && dayEndInput.value < this.value) {
                    dayEndInput.value = this.value;
                }
            });

            dayEndInput.addEventListener('change', function() {
                if (this.value && this.value < minAllowedDate) this.value = minAllowedDate;
                if (this.value && this.value > maxAllowedDate) this.value = maxAllowedDate;
                dayStartInput.max = this.value || maxAllowedDate;
                if (dayStartInput.value && dayStartInput.value > this.value) {
                    dayStartInput.value = this.value;
                }
            });
        }
    </script>
</body>
</html>
