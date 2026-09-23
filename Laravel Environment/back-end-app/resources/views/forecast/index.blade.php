<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Forecast Service Demo | Smart Property Analytics System</title>
    
    <!-- Google Fonts & Bootstrap 5 -->
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
            display: flex;
            flex-direction: column;
        }

        /* Top Header Navbar matching analytics & Metronic */
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

        /* Card Styles matching views/invoices/new.blade.php */
        .invoice-page-card {
            background: #ffffff;
            border-radius: 0.75rem;
            border: 1px solid #eff2f5;
            box-shadow: 0 1px 3px rgba(82, 63, 105, 0.04);
            transition: box-shadow 0.2s ease;
        }

        .invoice-page-card .card-header {
            background: transparent;
            padding: 1.25rem 1.75rem 0;
            border-bottom: none;
        }

        .invoice-page-card .card-body {
            padding: 1.75rem;
        }

        .invoice-section-title {
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.05em;
            text-transform: uppercase;
            color: #a1a5b7;
            margin-bottom: 0.5rem;
        }

        /* Start Button & Controls */
        .btn-forecast-start {
            background-color: #009ef7;
            color: #ffffff;
            font-weight: 700;
            font-size: 1.05rem;
            padding: 0.9rem 2.5rem;
            border-radius: 0.55rem;
            border: none;
            transition: all 0.25s ease;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.6rem;
            box-shadow: 0 4px 14px rgba(0, 158, 247, 0.25);
            min-width: 260px;
            cursor: pointer;
        }

        .btn-forecast-start:hover:not(:disabled) {
            background-color: #0095e8;
            color: #ffffff;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 158, 247, 0.35);
        }

        .btn-forecast-start:disabled {
            background-color: #7239ea;
            opacity: 0.9;
            cursor: not-allowed;
            transform: none;
            box-shadow: none;
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

        /* Progress Section */
        .progress-box-card {
            background: #fafbfc;
            border: 1px solid #eff2f5;
            border-radius: 0.65rem;
            padding: 1.5rem;
            transition: all 0.3s ease;
        }

        .custom-progress-track {
            height: 18px;
            border-radius: 10px;
            background-color: #e4e6ef;
            overflow: hidden;
            box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.06);
        }

        .custom-progress-bar {
            background: linear-gradient(90deg, #009ef7 0%, #50cd89 100%);
            transition: width 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }

        .stage-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            font-size: 0.75rem;
            font-weight: 700;
            padding: 0.3rem 0.65rem;
            border-radius: 0.375rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        .pulsing-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background-color: currentColor;
            display: inline-block;
            animation: pulse-dot 1.4s infinite ease-in-out;
        }

        @keyframes pulse-dot {
            0% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.3; transform: scale(0.65); }
            100% { opacity: 1; transform: scale(1); }
        }

        .code-pill {
            font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            background: #f1f1f4;
            color: #181c32;
            padding: 0.15rem 0.45rem;
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
            <span class="brand-badge">Forecast Service</span>
        </div>
        <div>
            <a href="{{ route('home') }}" class="btn-custom-light">
                <i class="bi bi-arrow-left"></i>
                <span>Back to Menu</span>
            </a>
        </div>
    </header>

    <!-- Main Content Container (Centered simple page layout) -->
    <main class="container py-5 my-auto" style="max-width: 860px;">
        
        <div class="card invoice-page-card">
            <div class="card-header text-center">
                <div class="invoice-section-title">Forecasting Service Pipeline</div>
                <h2 class="h4 fw-bold text-dark mb-1">Adaptive & ML Pricing Forecasting</h2>
                <p class="text-muted small mb-0">Trigger the end-to-end Python forecasting pipeline and monitor real-time execution milestones.</p>
            </div>
            
            <div class="card-body pt-4 text-center">
                
                <!-- Action Button in the Middle -->
                <div class="my-4 py-2">
                    <button type="button" id="btn_start_forecast" class="btn-forecast-start" onclick="startForecastDemo()">
                        <i class="bi bi-play-circle-fill fs-5" id="btn_icon"></i>
                        <span id="btn_text">Start Forecast Demo</span>
                    </button>
                </div>

                <!-- Progress Container (Shown upon clicking Start) -->
                <div id="progress_container" class="progress-box-card text-start mt-4 d-none">
                    
                    <!-- Progress Header & Stage Details -->
                    <div class="d-flex flex-wrap justify-content-between align-items-center mb-2">
                        <div class="d-flex align-items-center gap-2">
                            <span id="stage_badge" class="stage-badge bg-primary-subtle text-primary border border-primary-subtle">
                                <span class="pulsing-dot"></span>
                                <span id="stage_name_text">Initializing</span>
                            </span>
                            <span class="text-muted small d-none d-sm-inline" id="job_id_wrap">
                                Job: <code class="code-pill" id="job_id_text">-</code>
                            </span>
                        </div>
                        <div>
                            <span id="progress_percent_text" class="h4 fw-bold text-dark mb-0 font-monospace">0%</span>
                        </div>
                    </div>

                    <!-- Progress Bar Track -->
                    <div class="custom-progress-track mb-3">
                        <div id="progress_bar" class="progress-bar progress-bar-striped progress-bar-animated custom-progress-bar" 
                             role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
                    </div>

                    <!-- Dynamic Message Box -->
                    <div class="d-flex align-items-start gap-2 text-muted" style="font-size: 0.86rem;">
                        <i class="bi bi-info-circle-fill text-primary mt-1"></i>
                        <span id="progress_message_text" class="text-dark">Connecting to Python FastAPI pipeline (<code class="code-pill">/forecast-service-call</code>)...</span>
                    </div>
                </div>

            </div>
        </div>

    </main>

    <!-- Bootstrap Bundle JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    
    <script>
        let pollerInterval = null;
        let activeJobId = null;

        async function startForecastDemo() {
            const btn = document.getElementById('btn_start_forecast');
            const btnText = document.getElementById('btn_text');
            const btnIcon = document.getElementById('btn_icon');
            const progressContainer = document.getElementById('progress_container');
            const progressBar = document.getElementById('progress_bar');
            const progressPercentText = document.getElementById('progress_percent_text');
            const stageNameText = document.getElementById('stage_name_text');
            const progressMessageText = document.getElementById('progress_message_text');
            const jobIdText = document.getElementById('job_id_text');

            // 1. Update button state to "Processing...."
            btn.disabled = true;
            btnIcon.className = 'spinner-border spinner-border-sm';
            btnText.textContent = 'Processing....';

            // 2. Show progress container & reset bars
            progressContainer.classList.remove('d-none');
            progressBar.style.width = '0%';
            progressPercentText.textContent = '0%';
            stageNameText.textContent = 'Initializing';
            progressMessageText.textContent = 'Sending signal to Python FastAPI endpoint (/forecast-service-call)...';

            try {
                // 3. Send signal to Laravel backend which dispatches to Python FastAPI
                const response = await fetch('{{ route('forecast.trigger') }}', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRF-TOKEN': '{{ csrf_token() }}',
                        'Accept': 'application/json'
                    },
                    body: JSON.stringify({
                        customer_id: 1
                    })
                });

                const data = await response.json();

                if (data.success && data.job_id) {
                    activeJobId = data.job_id;
                    jobIdText.textContent = activeJobId;
                    progressMessageText.textContent = data.message || 'Signal dispatched. Starting progress tracking...';

                    // 4. Start polling prediction progress endpoint every 1.5 seconds
                    if (pollerInterval) {
                        clearInterval(pollerInterval);
                    }
                    pollerInterval = setInterval(pollPredictionProgress, 1500);
                    // Immediate first poll
                    pollPredictionProgress();
                } else {
                    progressMessageText.textContent = 'Failed to initialize forecast job: ' + (data.message || 'Unknown error');
                    btn.disabled = false;
                    btnIcon.className = 'bi bi-play-circle-fill fs-5';
                    btnText.textContent = 'Start Forecast Demo';
                }
            } catch (error) {
                console.error('Error triggering forecast:', error);
                progressMessageText.textContent = 'Network error while connecting to server: ' + error.message;
                btn.disabled = false;
                btnIcon.className = 'bi bi-play-circle-fill fs-5';
                btnText.textContent = 'Start Forecast Demo';
            }
        }

        async function pollPredictionProgress() {
            if (!activeJobId) return;

            const btn = document.getElementById('btn_start_forecast');
            const btnText = document.getElementById('btn_text');
            const btnIcon = document.getElementById('btn_icon');
            const progressBar = document.getElementById('progress_bar');
            const progressPercentText = document.getElementById('progress_percent_text');
            const stageNameText = document.getElementById('stage_name_text');
            const stageBadge = document.getElementById('stage_badge');
            const progressMessageText = document.getElementById('progress_message_text');
            const lastUpdatedText = document.getElementById('last_updated_text');

            try {
                const response = await fetch(`/api/prediction-progress/${encodeURIComponent(activeJobId)}`, {
                    headers: {
                        'Accept': 'application/json'
                    }
                });

                if (!response.ok) {
                    return; // Job might be registering in DB
                }

                const json = await response.json();
                if (json.success && json.data) {
                    const item = json.data;
                    const percent = Math.min(100, Math.max(0, parseInt(item.progress_percent, 10) || 0));

                    // Update UI elements
                    progressBar.style.width = percent + '%';
                    progressPercentText.textContent = percent + '%';
                    stageNameText.textContent = item.stage_name || 'In Progress';
                    progressMessageText.textContent = item.message || 'Processing forecasting pipeline...';
                    if (lastUpdatedText) {
                        lastUpdatedText.textContent = new Date().toLocaleTimeString();
                    }

                    // Check status
                    const status = (item.status || '').toLowerCase();
                    if (status === 'completed' || percent >= 100) {
                        stageBadge.className = 'stage-badge bg-success-subtle text-success border border-success-subtle';
                        clearInterval(pollerInterval);
                        pollerInterval = null;

                        // Transition button to "Process Complete" and make it clickable
                        btn.disabled = false;
                        btn.style.backgroundColor = '#50cd89';
                        btn.style.borderColor = '#50cd89';
                        btn.style.cursor = 'pointer';
                        btn.style.boxShadow = '0 4px 14px rgba(80, 205, 137, 0.35)';
                        btnIcon.className = 'bi bi-check-circle-fill fs-5';
                        btnText.textContent = 'Process Complete';
                        btn.onclick = () => {
                            window.location.href = `{{ route('forecast.results') }}?job_id=${encodeURIComponent(activeJobId)}&customer_id=1`;
                        };
                    } else if (status === 'failed' || status === 'error') {
                        stageBadge.className = 'stage-badge bg-danger-subtle text-danger border border-danger-subtle';
                        clearInterval(pollerInterval);
                        pollerInterval = null;
                        btn.disabled = false;
                        btnIcon.className = 'bi bi-exclamation-triangle-fill fs-5';
                        btnText.textContent = 'Retry Forecast Demo';
                        btn.onclick = startForecastDemo;
                    } else {
                        stageBadge.className = 'stage-badge bg-primary-subtle text-primary border border-primary-subtle';
                    }
                }
            } catch (err) {
                console.warn('Error polling prediction progress:', err);
            }
        }
    </script>
</body>
</html>
