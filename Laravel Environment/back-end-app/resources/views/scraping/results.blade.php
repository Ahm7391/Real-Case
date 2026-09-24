<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Competitor Price Results | Smart Property Analytics System</title>
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

        /* Stratified Periods Table Styles */
        .lm-header { background: #F59E0B; color: #fff; text-align: center; font-weight: bold; border: 1px solid #D97706; }
        .lm-subhdr { background: #FCD34D; color: #1f2937; text-align: center; font-weight: 600; border: 1px solid #D97706; }
        .lm-cell   { background: #FEF3C7; text-align: right; padding: 8px 14px; border: 1px solid #D97706; }
        
        .eb-header { background: #06B6D4; color: #fff; text-align: center; font-weight: bold; border: 1px solid #0891B2; }
        .eb-subhdr { background: #A5F3FC; color: #1f2937; text-align: center; font-weight: 600; border: 1px solid #0891B2; }
        .eb-cell   { background: #CFFAFE; text-align: right; padding: 8px 14px; border: 1px solid #0891B2; }
        
        .name-hdr  { background: #f9fafb; font-weight: bold; border: 1px solid #d1d5db; padding: 8px 12px; }
        .name-cell { background: #fff; font-weight: 600; padding: 8px 12px; border: 1px solid #d1d5db; white-space: nowrap; }

        .chart-container {
            position: relative;
            height: 220px;
            width: 100%;
        }

        .accordion-button:not(.collapsed) {
            color: #009ef7;
            background-color: #f1faff;
            box-shadow: inset 0 -1px 0 rgba(0, 0, 0, 0.125);
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
            <span class="brand-badge">Competitor Rate Analysis</span>
        </div>
        <div class="d-flex gap-2">
            <a href="{{ route('scraping.index') }}" class="btn-custom-light">
                <i class="bi bi-terminal"></i>
                <span>Scraping Console</span>
            </a>
            <a href="{{ route('home') }}" class="btn-custom-light">
                <i class="bi bi-arrow-left"></i>
                <span>Back to Menu</span>
            </a>
        </div>
    </header>

    <!-- Main Content Container -->
    <main class="container py-4 my-auto" style="max-width: 1140px;">
        
        <div class="card invoice-page-card mb-4">
            <div class="card-header border-0 pt-3 d-flex justify-content-between align-items-center flex-wrap gap-2">
                <div>
                    <h3 class="card-title fw-bolder fs-3 text-dark mb-1">Competitor Price</h3>
                    <span id="competitor_table_subtitle" class="text-muted fw-bold fs-7">Loading price data...</span>
                </div>
                <div>
                    <button type="button" class="btn btn-sm btn-light-primary fw-semibold" onclick="loadCompetitorData()">
                        <i class="bi bi-arrow-clockwise me-1"></i> Refresh Data
                    </button>
                </div>
            </div>

            <div class="card-body pt-3" style="position: relative;">
                <!-- Main Container for Accordions, Charts & Tables -->
                <div id="competitor_table_wrap">
                    <div class="text-center text-gray-400 py-10">
                        <div class="spinner-border text-primary mb-2" role="status"></div>
                        <div>Loading competitor & customer scraped prices...</div>
                    </div>
                </div>

                <!-- Overlay Loader -->
                <div id="competitor_table_loader" class="d-none position-absolute top-0 start-0 w-100 h-100 bg-white bg-opacity-75 d-flex justify-content-center align-items-center" style="z-index: 10;">
                    <div class="spinner-border text-primary" role="status">
                        <span class="visually-hidden">Loading...</span>
                    </div>
                </div>
            </div>
        </div>

    </main>

    <!-- Bootstrap Bundle & Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>

    <script>
        const dataUrl = "{{ route('scraping.stratified-data') }}";

        function escapeHtml(s) {
            if (s == null) return '';
            return String(s).replace(/[&<>"']/g, function (c) {
                return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
            });
        }

        function formatPrice(val) {
            if (val === null || val === undefined) return null;
            return Number(val).toLocaleString();
        }

        function trendHtml(current, previous) {
            if (current === null || previous === null) return '';
            if (current > previous) return ' <span style="color:#16a34a;font-weight:bold;">&#x2191;</span>';
            if (current < previous) return ' <span style="color:#dc2626;font-weight:bold;">&#x2193;</span>';
            return ' <span style="color:#6b7280;">&#x3d;</span>';
        }

        function showLoader(show) {
            const loader = document.getElementById('competitor_table_loader');
            if (loader) {
                loader.classList.toggle('d-none', !show);
            }
        }

        async function loadCompetitorData() {
            showLoader(true);
            const wrap = document.getElementById('competitor_table_wrap');
            const subTitle = document.getElementById('competitor_table_subtitle');

            try {
                const response = await fetch(dataUrl, {
                    headers: { 'Accept': 'application/json' }
                });

                const res = await response.json();
                showLoader(false);

                if (subTitle) {
                    subTitle.textContent = res.as_of ? 'As of ' + res.as_of : '';
                }

                if (!res.available) {
                    wrap.innerHTML = `<div class="text-center text-danger fw-bold py-10">${escapeHtml(res.message || 'No Scraped Data Available')}</div>`;
                    return;
                }

                renderAccordionSections(res);
            } catch (err) {
                showLoader(false);
                console.error('Error fetching competitor data:', err);
                wrap.innerHTML = `<div class="text-center text-danger fw-bold py-10">Failed to load competitor scraped data. Please ensure the backend is running.</div>`;
            }
        }

        function renderAccordionSections(data) {
            const wrap = document.getElementById('competitor_table_wrap');
            const sections = data.competitor_sections || [];

            if (sections.length === 0) {
                wrap.innerHTML = `<div class="text-center text-muted fw-bold py-10">No competitor data found.</div>`;
                return;
            }

            let accordionHtml = `<div class="accordion" id="competitor_accordion">`;

            sections.forEach((section, index) => {
                const uid = section.competitor_id || ('comp_' + index);
                const headId = 'acc_head_' + uid;
                const bodyId = 'acc_body_' + uid;

                // Unique rooms map for filter dropdown
                const uniqueRoomsMap = {};
                (section.ota_tables || []).forEach(ot => {
                    (ot.rows || []).forEach(r => {
                        if (r.room_name) uniqueRoomsMap[r.room_name] = true;
                    });
                });

                const sortedRooms = Object.keys(uniqueRoomsMap).sort();

                // Build Room Filter Dropdown HTML
                let filterHtml = `<div class="d-flex align-items-center gap-2 mb-4 flex-wrap">`;
                if (sortedRooms.length > 0) {
                    filterHtml += `
                        <div class="dropdown">
                            <button class="btn btn-sm btn-light dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false" data-bs-auto-close="outside">
                                <i class="bi bi-funnel me-1"></i> Filter Rooms
                            </button>
                            <div class="dropdown-menu p-3 shadow" style="min-width: 250px; max-height: 300px; overflow-y: auto;">
                                <div class="form-check form-check-custom form-check-solid mb-2">
                                    <input class="form-check-input js-room-select-all" type="checkbox" data-uid="${uid}" id="chk_selectall_${uid}" checked>
                                    <label class="form-check-label text-dark fw-bold" for="chk_selectall_${uid}" style="cursor:pointer;">Select All</label>
                                </div>
                                <div class="border-bottom mb-2 pb-1"></div>
                    `;

                    sortedRooms.forEach((room, rIndex) => {
                        const chkId = `chk_${uid}_${rIndex}`;
                        filterHtml += `
                            <div class="form-check form-check-custom form-check-solid mb-2">
                                <input class="form-check-input js-room-check" type="checkbox" value="${escapeHtml(room)}" data-uid="${uid}" id="${chkId}" checked>
                                <label class="form-check-label text-gray-700" for="${chkId}" style="cursor:pointer;">${escapeHtml(room)}</label>
                            </div>
                        `;
                    });

                    filterHtml += `</div></div>`;
                }
                filterHtml += `</div>`;

                // Build Table Body Content
                const bodyContent = buildCombinedTableHtml(section, uid);

                accordionHtml += `
                    <div class="accordion-item border mb-3 rounded">
                        <h2 class="accordion-header" id="${headId}">
                            <button class="accordion-button fw-bold fs-6" type="button" data-bs-toggle="collapse" data-bs-target="#${bodyId}" aria-expanded="true" aria-controls="${bodyId}">
                                <i class="bi bi-building me-2 text-primary"></i> ${escapeHtml(section.competitor_name)}
                            </button>
                        </h2>
                        <div id="${bodyId}" class="accordion-collapse collapse show" aria-labelledby="${headId}">
                            <div class="accordion-body pt-4">
                                ${filterHtml}
                                ${bodyContent}
                            </div>
                        </div>
                    </div>
                `;
            });

            accordionHtml += `</div>`;
            wrap.innerHTML = accordionHtml;

            // Initialize Charts and Event Listeners
            sections.forEach(section => {
                const uid = section.competitor_id;
                const canvasEl = document.getElementById('chart_' + uid);
                if (canvasEl) {
                    initCompetitorChart(canvasEl, section);
                }
            });

            bindFilterEvents();
        }

        function buildCombinedTableHtml(section, uid) {
            let combinedRows = [];

            (section.ota_tables || []).forEach(ot => {
                const otaName = ot.ota_name;
                (ot.rows || []).forEach(row => {
                    combinedRows.push({
                        room_name: row.room_name,
                        prices: row.prices || [null, null],
                        otaName: otaName
                    });
                });
            });

            if (combinedRows.length === 0) {
                return `<div class="text-center text-gray-400 py-5 border border-dashed rounded">No room type data available for this competitor.</div>`;
            }

            // Separate active and inactive rows
            const activeRows = [];
            const inactiveRows = [];

            combinedRows.forEach(row => {
                const hasPrice = (row.prices || []).some(p => p !== null && p > 0);
                if (hasPrice) activeRows.push(row);
                else inactiveRows.push(row);
            });

            const finalRows = activeRows.concat(inactiveRows);

            const canvasId = 'chart_' + uid;
            let html = `
                <div class="chart-container mb-4">
                    <canvas id="${canvasId}"></canvas>
                </div>
                <hr style="border: 0; border-top: 2px dashed #eff2f5; margin: 20px 0;" />
                <div class="table-responsive">
                    <table class="table mb-0" style="border-collapse:collapse;width:100%;">
                        <thead>
                            <tr>
                                <th rowspan="2" class="name-hdr align-middle">Room Type</th>
                                <th class="lm-header">Last Minute</th>
                                <th class="eb-header">Early Book</th>
                            </tr>
                            <tr>
                                <th class="lm-subhdr">+7 Days</th>
                                <th class="eb-subhdr">+14 Days</th>
                            </tr>
                        </thead>
                        <tbody>
            `;

            finalRows.forEach(row => {
                const rNameEsc = escapeHtml(row.room_name);
                const otaNameEsc = escapeHtml(row.otaName);
                const price7 = row.prices[0];
                const price14 = row.prices[1];

                html += `
                    <tr class="js-room-row" data-room="${rNameEsc}">
                        <td class="name-cell">
                            ${rNameEsc}
                            <div class="fs-8 mt-1" style="font-size: 0.75rem; font-weight: normal; color: #3699ff;">
                                <i class="bi bi-tag-fill me-1"></i> ${otaNameEsc}
                            </div>
                        </td>
                        <td class="lm-cell">
                            ${price7 !== null ? `<span class="fw-bold">${formatPrice(price7)}</span>` : '<span class="text-muted">N/A</span>'}
                        </td>
                        <td class="eb-cell">
                            ${price14 !== null ? `<span class="fw-bold">${formatPrice(price14)}</span>` + trendHtml(price14, price7) : '<span class="text-muted">N/A</span>'}
                        </td>
                    </tr>
                `;
            });

            html += `</tbody></table></div>`;
            return html;
        }

        function initCompetitorChart(canvasEl, section) {
            // Compute competitor lowest price across rooms for +7d and +14d
            const competitorPrices = [null, null];
            for (let i = 0; i < 2; i++) {
                let minVal = null;
                (section.ota_tables || []).forEach(otaTable => {
                    (otaTable.rows || []).forEach(row => {
                        const p = row.prices && row.prices[i];
                        if (p !== null && p !== undefined && p > 0) {
                            if (minVal === null || p < minVal) {
                                minVal = p;
                            }
                        }
                    });
                });
                competitorPrices[i] = minVal;
            }

            // Compute customer price for +7d and +14d
            const customerPrices = [null, null];
            for (let i = 0; i < 2; i++) {
                let minCust = null;
                (section.ota_tables || []).forEach(otaTable => {
                    const cp = otaTable.customer_prices && otaTable.customer_prices[i];
                    if (cp !== null && cp !== undefined && cp > 0) {
                        if (minCust === null || cp < minCust) {
                            minCust = cp;
                        }
                    }
                });
                customerPrices[i] = minCust;
            }

            const labels = ['+7 Days (Last Minute)', '+14 Days (Early Book)'];

            const ctx = canvasEl.getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [
                        {
                            label: 'Competitor Price',
                            data: competitorPrices,
                            borderColor: '#181c32',
                            backgroundColor: 'transparent',
                            borderWidth: 2.5,
                            borderDash: [6, 4],
                            tension: 0,
                            stepped: true,
                            pointRadius: 5,
                            pointHoverRadius: 7,
                            pointBackgroundColor: '#181c32',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2,
                        },
                        {
                            label: 'Customer Price',
                            data: customerPrices,
                            borderColor: '#009ef7',
                            backgroundColor: 'transparent',
                            borderWidth: 2.5,
                            tension: 0,
                            stepped: true,
                            pointRadius: 5,
                            pointHoverRadius: 7,
                            pointBackgroundColor: '#009ef7',
                            pointBorderColor: '#ffffff',
                            pointBorderWidth: 2,
                            fill: {
                                target: 0,
                                above: 'rgba(241, 65, 108, 0.3)', // Red when customer > competitor (overpriced)
                                below: 'rgba(11, 183, 131, 0.3)'  // Green when customer < competitor (competitive)
                            }
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
                    plugins: {
                        legend: {
                            display: true,
                            position: 'top',
                            labels: {
                                boxWidth: 20,
                                font: { size: 12, weight: '600', family: 'Plus Jakarta Sans' },
                                color: '#5e6278'
                            }
                        },
                        tooltip: {
                            backgroundColor: '#1e1e2d',
                            titleColor: '#ffffff',
                            bodyColor: '#cdcdde',
                            borderColor: '#3f4254',
                            borderWidth: 1,
                            cornerRadius: 8,
                            padding: 10,
                            callbacks: {
                                label: function(item) {
                                    const index = item.dataIndex;
                                    const compVal = competitorPrices[index];
                                    const custVal = customerPrices[index];

                                    const compStr = compVal !== null && compVal !== undefined ? 'Rp ' + Number(compVal).toLocaleString() : 'N/A';
                                    const custStr = custVal !== null && custVal !== undefined ? 'Rp ' + Number(custVal).toLocaleString() : 'N/A';

                                    if (item.datasetIndex === 0) {
                                        return '■ Competitor Price: ' + compStr;
                                    } else {
                                        return '■ Customer Price: ' + custStr;
                                    }
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: {
                                color: '#5e6278',
                                font: { size: 11, weight: '600', family: 'Plus Jakarta Sans' }
                            }
                        },
                        y: {
                            grid: {
                                color: '#eff2f5',
                                drawBorder: false,
                            },
                            ticks: {
                                color: '#a1a5b7',
                                font: { size: 10, family: 'Plus Jakarta Sans' },
                                callback: function(v) {
                                    return Number(v).toLocaleString();
                                }
                            },
                            beginAtZero: false
                        }
                    }
                }
            });
        }

        function bindFilterEvents() {
            // Select All Checkbox Handler
            document.querySelectorAll('.js-room-select-all').forEach(selectAllEl => {
                selectAllEl.addEventListener('change', function () {
                    const uid = this.getAttribute('data-uid');
                    const checked = this.checked;
                    const checkboxes = document.querySelectorAll(`.js-room-check[data-uid="${uid}"]`);
                    checkboxes.forEach(cb => { cb.checked = checked; });
                    applyRoomFilter(uid);
                });
            });

            // Individual Room Checkbox Handler
            document.querySelectorAll('.js-room-check').forEach(chkEl => {
                chkEl.addEventListener('change', function () {
                    const uid = this.getAttribute('data-uid');
                    applyRoomFilter(uid);
                    syncSelectAll(uid);
                });
            });
        }

        function applyRoomFilter(uid) {
            const checkedValues = {};
            document.querySelectorAll(`.js-room-check[data-uid="${uid}"]:checked`).forEach(cb => {
                checkedValues[cb.value] = true;
            });

            const bodyEl = document.getElementById('acc_body_' + uid);
            if (!bodyEl) return;

            bodyEl.querySelectorAll('.js-room-row').forEach(row => {
                const roomName = row.getAttribute('data-room');
                row.style.display = checkedValues[roomName] ? '' : 'none';
            });
        }

        function syncSelectAll(uid) {
            const all = document.querySelectorAll(`.js-room-check[data-uid="${uid}"]`);
            const checked = document.querySelectorAll(`.js-room-check[data-uid="${uid}"]:checked`);
            const selectEl = document.querySelector(`.js-room-select-all[data-uid="${uid}"]`);
            if (!selectEl) return;

            if (checked.length === 0) {
                selectEl.checked = false;
                selectEl.indeterminate = false;
            } else if (checked.length === all.length) {
                selectEl.checked = true;
                selectEl.indeterminate = false;
            } else {
                selectEl.checked = false;
                selectEl.indeterminate = true;
            }
        }

        // Initialize on page load
        document.addEventListener('DOMContentLoaded', loadCompetitorData);
    </script>
</body>
</html>
