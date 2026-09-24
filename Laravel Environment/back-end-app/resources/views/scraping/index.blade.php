<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OTA Scraping Demo | Smart Property Analytics System</title>
    <link rel="icon" type="image/svg+xml" href="{{ asset('favicon.svg') }}">
    <link rel="alternate icon" href="{{ asset('favicon.ico') }}">
    
    <!-- Google Fonts & Bootstrap 5 -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
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

        /* Top Header Navbar matching forecast & analytics */
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

        /* Card Styles */
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
        .btn-scrape-start {
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

        .btn-scrape-start:hover:not(:disabled) {
            background-color: #0095e8;
            color: #ffffff;
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 158, 247, 0.35);
        }

        .btn-scrape-start:disabled {
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

        /* Terminal Log Box Section */
        .terminal-box-card {
            background: #0f172a;
            border: 1px solid #1e293b;
            border-radius: 0.75rem;
            overflow: hidden;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
            transition: all 0.3s ease;
        }

        .terminal-header {
            background-color: #1e293b;
            padding: 0.75rem 1.25rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #334155;
        }

        .terminal-dots {
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .terminal-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            display: inline-block;
        }

        .terminal-dot.red { background-color: #ef4444; }
        .terminal-dot.yellow { background-color: #f59e0b; }
        .terminal-dot.green { background-color: #10b981; }

        .terminal-body {
            font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
            font-size: 0.82rem;
            line-height: 1.6;
            color: #e2e8f0;
            padding: 1.25rem;
            height: 380px;
            overflow-y: auto;
            background-color: #090d16;
            scrollbar-width: thin;
            scrollbar-color: #334155 #090d16;
        }

        .terminal-body::-webkit-scrollbar {
            width: 6px;
        }

        .terminal-body::-webkit-scrollbar-track {
            background: #090d16;
        }

        .terminal-body::-webkit-scrollbar-thumb {
            background-color: #334155;
            border-radius: 3px;
        }

        .terminal-line {
            word-break: break-all;
            white-space: pre-wrap;
            margin-bottom: 0.25rem;
        }

        .log-info { color: #38bdf8; }
        .log-success { color: #4ade80; font-weight: 600; }
        .log-warning { color: #facc15; }
        .log-error { color: #f87171; font-weight: 600; }
        .log-system { color: #c084fc; font-style: italic; }
        .log-muted { color: #64748b; }

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
            <span class="brand-badge">Scraping Service</span>
        </div>
        <div>
            <a href="{{ route('home') }}" class="btn-custom-light">
                <i class="bi bi-arrow-left"></i>
                <span>Back to Menu</span>
            </a>
        </div>
    </header>

    <!-- Main Content Container -->
    <main class="container py-5 my-auto" style="max-width: 920px;">
        
        <div class="card invoice-page-card">
            <div class="card-header text-center">
                <div class="invoice-section-title">OTA Competitor & Customer Scraping</div>
                <h2 class="h4 fw-bold text-dark mb-1">Live Scraping Streaming Pipeline</h2>
                <p class="text-muted small mb-0">Trigger the Python Selenium scraper to collect real-time OTA rates and stream execution logs live to this console.</p>
            </div>
            
            <div class="card-body pt-4 text-center">
                
                <!-- Action Button in the Middle -->
                <div class="my-4 py-2">
                    <button type="button" id="btn_start_scrape" class="btn-scrape-start" onclick="startScrapingDemo()">
                        <i class="bi bi-play-circle-fill fs-5" id="btn_icon"></i>
                        <span id="btn_text">Start Scraping Demo</span>
                    </button>
                </div>

                <!-- Live Log Terminal Container (Shown upon clicking Start) -->
                <div id="log_container" class="terminal-box-card text-start mt-4 d-none">
                    
                    <!-- Terminal Top Bar -->
                    <div class="terminal-header">
                        <div class="d-flex align-items-center gap-3">
                            <div class="terminal-dots">
                                <span class="terminal-dot red"></span>
                                <span class="terminal-dot yellow"></span>
                                <span class="terminal-dot green"></span>
                            </div>
                            <span class="text-light small fw-semibold font-monospace">
                                <i class="bi bi-terminal me-1 text-info"></i> scraping-service-console
                            </span>
                        </div>

                        <div class="d-flex align-items-center gap-2">
                            <span id="scraping_status_badge" class="stage-badge bg-warning-subtle text-warning border border-warning-subtle">
                                <span class="pulsing-dot"></span>
                                <span id="scraping_status_text">Connecting</span>
                            </span>
                            <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2 text-white-50 border-0" onclick="clearLogTerminal()" title="Clear console">
                                <i class="bi bi-trash3"></i>
                            </button>
                        </div>
                    </div>

                    <!-- Terminal Log Stream Body -->
                    <div id="log_terminal" class="terminal-body">
                        <div class="terminal-line log-muted">// Ready. Awaiting initial SSE stream connection...</div>
                    </div>

                    <!-- Terminal Bottom Info Bar -->
                    <div class="px-3 py-2 bg-slate-900 border-top border-secondary border-opacity-25 d-flex justify-content-between align-items-center text-muted small" style="background-color: #0f172a; font-size: 0.78rem;">
                        <div class="d-flex align-items-center gap-2 text-truncate" style="max-width: 70%;">
                            <span class="text-secondary">Source:</span>
                            <code class="text-info font-monospace">{{ $scraperServiceUrl }}/scraping-service-call</code>
                        </div>
                        <div class="text-end">
                            <span id="log_line_counter" class="text-secondary">0 lines received</span>
                        </div>
                    </div>
                </div>

            </div>
        </div>

    </main>

    <!-- Bootstrap Bundle JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    
    <script>
        let eventSource = null;
        let lineCount = 0;
        const scraperUrl = "{{ rtrim($scraperServiceUrl, '/') }}/scraping-service-call";

        function startScrapingDemo() {
            const btn = document.getElementById('btn_start_scrape');
            const btnText = document.getElementById('btn_text');
            const btnIcon = document.getElementById('btn_icon');
            const logContainer = document.getElementById('log_container');
            const logTerminal = document.getElementById('log_terminal');
            const statusBadge = document.getElementById('scraping_status_badge');
            const statusText = document.getElementById('scraping_status_text');
            const lineCounter = document.getElementById('log_line_counter');

            // 1. Update button state to "Processing..."
            btn.disabled = true;
            btnIcon.className = 'spinner-border spinner-border-sm';
            btnText.textContent = 'Processing...';

            // 2. Reveal log container and reset terminal state
            logContainer.classList.remove('d-none');
            logTerminal.innerHTML = '';
            lineCount = 0;
            lineCounter.textContent = '0 lines received';

            statusBadge.className = 'stage-badge bg-warning-subtle text-warning border border-warning-subtle';
            statusText.textContent = 'Running';

            appendTerminalLine('[SYSTEM] Initializing SSE connection to ' + scraperUrl + '...', 'log-system');

            // 3. Close existing connection if any
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }

            // 4. Open SSE EventSource connection to Python FastAPI
            try {
                eventSource = new EventSource(scraperUrl);

                // Listen for incoming log chunks
                eventSource.onmessage = function (event) {
                    try {
                        const payload = JSON.parse(event.data);
                        
                        if (payload.log) {
                            classifyAndAppendLog(payload.log);
                        }

                        // Check for completion signal
                        if (payload.done === true) {
                            appendTerminalLine('[SYSTEM] Scraping pipeline completed successfully. Ingestion triggered.', 'log-success');
                            finishScrapingState(true);
                        }
                    } catch (err) {
                        // Fallback if data is raw text
                        classifyAndAppendLog(event.data);
                    }
                };

                // Handle stream errors / disconnection
                eventSource.onerror = function (err) {
                    console.warn('EventSource disconnected or error:', err);
                    
                    // If stream closed after running, verify state
                    if (eventSource.readyState === EventSource.CLOSED) {
                        appendTerminalLine('[SYSTEM] Stream connection closed by server.', 'log-muted');
                    } else {
                        appendTerminalLine('[ERROR] Connection lost or Python scraping server unreachable at ' + scraperUrl, 'log-error');
                        finishScrapingState(false);
                    }
                };

            } catch (ex) {
                console.error('Failed to initialize EventSource:', ex);
                appendTerminalLine('[ERROR] Exception connecting to scraper service: ' + ex.message, 'log-error');
                finishScrapingState(false);
            }
        }

        function classifyAndAppendLog(rawText) {
            let lineClass = 'log-info';
            const upper = rawText.toUpperCase();

            if (upper.includes('[ERROR]') || upper.includes('EXCEPTION') || upper.includes('FAILED')) {
                lineClass = 'log-error';
            } else if (upper.includes('[WARNING]') || upper.includes('WARN')) {
                lineClass = 'log-warning';
            } else if (upper.includes('[SUCCESS]') || upper.includes('COMPLETED') || upper.includes('[STREAM_JOB_FINISHED]')) {
                lineClass = 'log-success';
            } else if (upper.includes('[SYSTEM]') || upper.includes('[START]')) {
                lineClass = 'log-system';
            }

            appendTerminalLine(rawText, lineClass);
        }

        function appendTerminalLine(text, customClass = '') {
            const terminal = document.getElementById('log_terminal');
            const lineCounter = document.getElementById('log_line_counter');

            const lineEl = document.createElement('div');
            lineEl.className = 'terminal-line ' + customClass;
            lineEl.textContent = text;

            terminal.appendChild(lineEl);
            terminal.scrollTop = terminal.scrollHeight; // Auto scroll to bottom

            lineCount++;
            lineCounter.textContent = lineCount + ' lines received';
        }

        function finishScrapingState(isSuccess) {
            const btn = document.getElementById('btn_start_scrape');
            const btnText = document.getElementById('btn_text');
            const btnIcon = document.getElementById('btn_icon');
            const statusBadge = document.getElementById('scraping_status_badge');
            const statusText = document.getElementById('scraping_status_text');

            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }

            btn.disabled = false;

            if (isSuccess) {
                statusBadge.className = 'stage-badge bg-success-subtle text-success border border-success-subtle';
                statusText.textContent = 'Completed';

                btn.style.backgroundColor = '#50cd89';
                btn.style.borderColor = '#50cd89';
                btn.style.cursor = 'pointer';
                btn.style.boxShadow = '0 4px 14px rgba(80, 205, 137, 0.35)';
                btnIcon.className = 'bi bi-arrow-right-circle-fill fs-5';
                btnText.textContent = 'View Result';
                btn.onclick = () => {
                    window.location.href = "{{ route('scraping.results') }}";
                };
            } else {
                statusBadge.className = 'stage-badge bg-danger-subtle text-danger border border-danger-subtle';
                statusText.textContent = 'Failed';

                btn.style.backgroundColor = '#009ef7';
                btn.style.borderColor = '#009ef7';
                btnIcon.className = 'bi bi-arrow-clockwise fs-5';
                btnText.textContent = 'Retry Scraping Demo';
                btn.onclick = startScrapingDemo;
            }
        }

        function clearLogTerminal() {
            const logTerminal = document.getElementById('log_terminal');
            const lineCounter = document.getElementById('log_line_counter');
            logTerminal.innerHTML = '<div class="terminal-line log-muted">// Console cleared.</div>';
            lineCount = 0;
            lineCounter.textContent = '0 lines received';
        }
    </script>
</body>
</html>
