/*
 * Competitor price table — Stratified Periods approach.
 *
 * All assigned competitors are shown simultaneously, one Bootstrap accordion
 * item per competitor. Each item expands/collapses independently on click.
 * Inside each accordion body: one sub-table per OTA channel, stacked vertically.
 *
 * OTAs are derived from all channels that have ever been scraped (global).
 * Sub-tables with no data for a competitor still render with all N/A cells.
 *
 * Four non-overlapping date windows (anchored to today):
 *   Last Minute  +3 Days  : today      → today+3
 *   Last Minute  +7 Days  : today+4    → today+7
 *   Early Book  +14 Days  : today+8    → today+14
 *   Early Book  +30 Days  : today+15   → today+30
 *
 * Price per cell = lowest non-zero price scraped in that window, multiplied
 * by the competitor's multiplier_rate (default 1.0 = no change).
 * Trend vs previous column: ↑ green / ↓ red / = gray / blank if N/A.
 *
 * At the very bottom of the wrap sits #competitor_ai_insight — ONE market-wide
 * LLM note covering every competitor, fetched separately once the accordion has
 * painted. It is NOT inside any accordion item.
 *
 * The note is generated ASYNCHRONOUSLY. The request below does not wait for
 * it; the pipeline posts the finished prose back via a callback. Nothing polls.
 *
 * Table refreshes after Insert Competitor modal saves/deletes.
 *
 * "More Info" per slot: sets multiplier_rate + OTA URLs on
 * properties_id_for_scrapingdb (looked up by unique_id).
 *
 * "Add New Property": when lookup returns nothing, the user may register an
 * entirely new competitor row in properties_id_for_scrapingdb and assign it
 * to the active slot in one step.
 */
(function () {
    'use strict';

    var cfg = window.competitorChart || {};
    var $ = window.jQuery;
    var activeSlot = null;
    var activeMoreInfoUid = null;

    // Bumped on every table load. In-flight note requests whose token no
    // longer matches belong to a stale load and must not paint.
    var noteToken = 0;

    // ---- helpers ---------------------------------------------------------

    function el(id) { return document.getElementById(id); }

    function ajax(method, url, data) {
        return $.ajax({
            method: method,
            url: url,
            data: data,
            headers: { 'X-CSRF-TOKEN': cfg.csrf },
            dataType: 'json'
        });
    }

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

    function debounce(fn, ms) {
        var t;
        return function () {
            var args = arguments, ctx = this;
            clearTimeout(t);
            t = setTimeout(function () { fn.apply(ctx, args); }, ms);
        };
    }

    // ---- table styles ----------------------------------------------------

    var LM_HEADER = 'background:#F59E0B;color:#fff;text-align:center;font-weight:bold;border:1px solid #D97706;';
    var LM_SUBHDR = 'background:#FCD34D;color:#1f2937;text-align:center;font-weight:600;border:1px solid #D97706;';
    var LM_CELL   = 'background:#FEF3C7;text-align:right;padding:8px 14px;border:1px solid #D97706;';
    var EB_HEADER = 'background:#06B6D4;color:#fff;text-align:center;font-weight:bold;border:1px solid #0891B2;';
    var EB_SUBHDR = 'background:#A5F3FC;color:#1f2937;text-align:center;font-weight:600;border:1px solid #0891B2;';
    var EB_CELL   = 'background:#CFFAFE;text-align:right;padding:8px 14px;border:1px solid #0891B2;';
    var NAME_HDR  = 'background:#f9fafb;font-weight:bold;border:1px solid #d1d5db;padding:8px 12px;';
    var NAME_CELL = 'background:#fff;font-weight:600;padding:8px 12px;border:1px solid #d1d5db;white-space:nowrap;';

    var CELL_STYLES = [LM_CELL, LM_CELL, EB_CELL, EB_CELL];

    // ---- trend indicator -------------------------------------------------

    function trendHtml(current, previous) {
        if (current === null || previous === null) return '';
        if (current > previous) return ' <span style="color:#16a34a;font-weight:bold;">&#x2191;</span>';
        if (current < previous) return ' <span style="color:#dc2626;font-weight:bold;">&#x2193;</span>';
        return ' <span style="color:#6b7280;">&#x3d;</span>';
    }

    // ---- AI insight ------------------------------------------------------

    var INSIGHT_ID = 'competitor_ai_insight';

    function hasAnyPrice(otaTables) {
        return (otaTables || []).some(function (ot) {
            return (ot.rows || []).some(function (row) {
                return (row.prices || []).some(function (p) { return p !== null && p > 0; });
            });
        });
    }

    var NOTE_CARD = 'background:#F8FAFC;border:1px solid #E2E8F0;border-left:3px solid #06B6D4;' +
        'border-radius:6px;padding:14px 16px;';

    function renderNoteLoading() {
        var box = el(INSIGHT_ID);
        if (!box) return;
        box.innerHTML = '<div style="' + NOTE_CARD + '">' +
            '<span class="spinner-border spinner-border-sm text-primary me-2" role="status"></span>' +
            '<span class="text-gray-500 fs-7">Requesting AI insight...</span>' +
            '</div>';
    }

    function renderNotePending() {
        var box = el(INSIGHT_ID);
        if (!box) return;
        box.innerHTML = '<div style="' + NOTE_CARD + '">' +
            '<div class="d-flex align-items-center">' +
            '<span class="spinner-border spinner-border-sm text-primary me-2" role="status"></span>' +
            '<span class="text-gray-500 fs-7">Generating AI insight&hellip;</span>' +
            '</div>' +
            '<div class="text-gray-400 fs-8 mt-2">' +
            'This runs on the analysis server and usually takes a few minutes. ' +
            'Refresh this page to see it once it is ready.' +
            '</div>' +
            '</div>';
    }

    function renderNote(note) {
        var box = el(INSIGHT_ID);
        if (!box) return;
        if (!note) { box.innerHTML = ''; return; }

        var card = document.createElement('div');
        card.setAttribute('style', NOTE_CARD);

        var header = document.createElement('div');
        header.className = 'd-flex align-items-center mb-2';
        header.innerHTML = '<span class="badge badge-light-info fs-8 fw-bold">AI Insight</span>';
        card.appendChild(header);

        var body = document.createElement('div');
        body.className = 'text-gray-700 fs-7';
        body.style.whiteSpace = 'pre-line';
        body.textContent = note;
        card.appendChild(body);

        box.innerHTML = '';
        box.appendChild(card);
    }

    function loadNotes(sections) {
        if (!cfg.noteUrl) return;

        var anyPrice = (sections || []).some(function (s) { return hasAnyPrice(s.ota_tables); });
        if (!anyPrice) { renderNote(null); return; }

        var token = noteToken;
        renderNoteLoading();

        ajax('GET', cfg.noteUrl, { customerid: cfg.customerId })
            .done(function (res) {
                if (token !== noteToken) return;
                if (res && res.status === 'ready') { renderNote(res.note); return; }
                if (res && res.status === 'pending') { renderNotePending(); return; }
                renderNote(null);
            })
            .fail(function () {
                if (token !== noteToken) return;
                renderNote(null);
            });
    }

    // ---- single OTA sub-table HTML ---------------------------------------

    function buildCombinedTableHtml(section, multiplier, uid) {
        var mult = (multiplier && multiplier > 0) ? multiplier : 1;
        var combinedRows = [];

        (section.ota_tables || []).forEach(function (ot) {
            var otaName = ot.ota_name;
            var otaId = ot.ota_id;
            (ot.rows || []).forEach(function (row) {
                combinedRows.push({
                    room_name: row.room_name,
                    prices: row.prices,
                    user_defined_flags: row.user_defined_flags,
                    otaName: otaName,
                    otaId: otaId
                });
            });
        });

        if (combinedRows.length === 0) {
            return '<div class="text-center text-gray-400 py-5 border border-dashed rounded">' +
                'No room type data available for this competitor.</div>';
        }

        // Separate active and inactive rows
        var activeRows = [];
        var inactiveRows = [];

        combinedRows.forEach(function (row) {
            var hasPrice = (row.prices || []).some(function (p) {
                return p !== null && p > 0;
            });
            if (hasPrice) {
                activeRows.push(row);
            } else {
                inactiveRows.push(row);
            }
        });

        var finalRows = activeRows.concat(inactiveRows);

        // Add a canvas element for the chart (single chart per competitor)
        var canvasId = 'chart_' + uid;
        var html = '<div class="chart-container mb-4" style="position: relative; height: 180px; width: 100%;">' +
            '<canvas id="' + canvasId + '"></canvas>' +
            '</div>';
        
        // Add a stylish dashed line
        html += '<hr style="border: 0; border-top: 2px dashed #eff2f5; margin: 20px 0;" />';

        html += '<div class="table-responsive">' +
            '<table class="table mb-0" style="border-collapse:collapse;width:100%;">' +
            '<thead>' +
            '<tr>' +
            '<th rowspan="2" style="' + NAME_HDR + 'vertical-align:middle;">Room Type</th>' +
            '<th colspan="2" style="' + LM_HEADER + '">Last Minute</th>' +
            '<th colspan="2" style="' + EB_HEADER + '">Early Book</th>' +
            '</tr>' +
            '<tr>' +
            '<th style="' + LM_SUBHDR + '">+3 Days</th>' +
            '<th style="' + LM_SUBHDR + '">+7 Days</th>' +
            '<th style="' + EB_SUBHDR + '">+14 Days</th>' +
            '<th style="' + EB_SUBHDR + '">+30 Days</th>' +
            '</tr>' +
            '</thead>' +
            '<tbody>';

        finalRows.forEach(function (row) {
            var rNameEsc = escapeHtml(row.room_name);
            var otaNameEsc = escapeHtml(row.otaName);
            html += '<tr class="js-room-row" data-room="' + rNameEsc + '">';
            html += '<td style="' + NAME_CELL + '">' + 
                rNameEsc + 
                '<div class="fs-8 mt-1" style="font-size: 0.75rem; font-weight: normal; color: #3699ff;">' + otaNameEsc + '</div>' + 
                '</td>';

            // Apply multiplier and round to nearest integer for display.
            var displayPrices = (row.prices || []).map(function (p) {
                return p !== null ? Math.round(p * mult) : null;
            });
            var udFlags = row.user_defined_flags || [false, false, false, false];

            for (var i = 0; i < 4; i++) {
                var price = displayPrices[i];
                var prev  = i > 0 ? displayPrices[i - 1] : null;
                var cellStyle = CELL_STYLES[i];
                var isUd = udFlags[i] === true;

                if (price === null) {
                    html += '<td style="' + cellStyle + 'text-align:center;color:#9ca3af;">N/A</td>';
                } else if (isUd) {
                    html += '<td style="' + cellStyle + '">' +
                        '<span class="badge badge-light-primary text-primary fw-bolder me-1" title="User Defined Rate">!</span>' +
                        '<span class="fw-bold" style="color:#009ef7;">' + formatPrice(price) + '</span>' +
                        '</td>';
                } else {
                    html += '<td style="' + cellStyle + '">' +
                        '<span class="fw-bold">' + formatPrice(price) + '</span>' +
                        trendHtml(price, prev) +
                        '</td>';
                }
            }
            html += '</tr>';
        });

        html += '</tbody></table></div>';
        return html;
    }

    function initCompetitorChart(canvasEl, section, mult) {
        var competitorPrices = [null, null, null, null];
        
        for (var i = 0; i < 4; i++) {
            var minVal = null;
            (section.ota_tables || []).forEach(function (otaTable) {
                var rows = otaTable.rows || [];
                rows.forEach(function (row) {
                    var p = row.prices && row.prices[i];
                    if (p !== null && p !== undefined) {
                        var displayP = Math.round(p * mult);
                        if (minVal === null || displayP < minVal) {
                            minVal = displayP;
                        }
                    }
                });
            });
            competitorPrices[i] = minVal;
        }

        var customerPrices = [null, null, null, null];
        for (var i = 0; i < 4; i++) {
            var minCust = null;
            (section.ota_tables || []).forEach(function (otaTable) {
                var cp = otaTable.customer_prices && otaTable.customer_prices[i];
                if (cp !== null && cp !== undefined) {
                    if (minCust === null || cp < minCust) {
                        minCust = cp;
                    }
                }
            });
            customerPrices[i] = minCust;
        }

        var labels = ['+3 Days', '+7 Days', '+14 Days', '+30 Days'];

        var ctx = canvasEl.getContext('2d');
        new window.Chart(ctx, {
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
                        pointRadius: 4,
                        pointHoverRadius: 6,
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
                        pointRadius: 4,
                        pointHoverRadius: 6,
                        pointBackgroundColor: '#009ef7',
                        pointBorderColor: '#ffffff',
                        pointBorderWidth: 2,
                        fill: {
                            target: 0,
                            above: 'rgba(241, 65, 108, 0.3)', // red (when customer > competitor, 70% transparency)
                            below: 'rgba(11, 183, 131, 0.3)'  // green (when customer < competitor, 70% transparency)
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
                            font: { size: 11, weight: '600' },
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
                        titleFont: { size: 12, weight: '700' },
                        bodyFont: { size: 11 },
                        callbacks: {
                            title: function(items) {
                                return items[0] ? items[0].label : '';
                            },
                            label: function(item) {
                                var index = item.dataIndex;
                                var competitorVal = competitorPrices[index];
                                var customerVal = customerPrices[index];
                                
                                var compStr = competitorVal !== null && competitorVal !== undefined ? Number(competitorVal).toLocaleString() : 'N/A';
                                var custStr = customerVal !== null && customerVal !== undefined ? Number(customerVal).toLocaleString() : 'N/A';
                                
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
                            color: '#a1a5b7',
                            font: { size: 10, weight: '600' }
                        }
                    },
                    y: {
                        grid: {
                            color: '#eff2f5',
                            drawBorder: false,
                        },
                        ticks: {
                            color: '#a1a5b7',
                            font: { size: 10 },
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

    // ---- accordion render ------------------------------------------------

    function buildAccordionItem(section, index) {
        var uid  = section.competitor_id;
        var mult = section.multiplier_rate || 1;
        var headId = 'acc_head_' + uid;
        var bodyId = 'acc_body_' + uid;

        var multBadge = '';
        if (mult && mult !== 1) {
            multBadge = ' <span class="badge badge-light-warning fs-8 ms-2">&times;' +
                parseFloat(mult.toFixed(4)) + '</span>';
        }

        var uniqueRoomsMap = {};
        (section.ota_tables || []).forEach(function(ot) {
            (ot.rows || []).forEach(function(r) {
                if (r.room_name) uniqueRoomsMap[r.room_name] = true;
            });
        });
        
        var historyUrl = (window.competitorChart && window.competitorChart.historicalPriceUrlTemplate)
            ? window.competitorChart.historicalPriceUrlTemplate.replace(':id', encodeURIComponent(uid))
            : ('/ecommerce/properties/competitor/' + encodeURIComponent(uid) + '/historical-prices');

        var filterHtml = '<div class="d-flex align-items-center gap-2 mb-4 flex-wrap">';
        var sortedRooms = Object.keys(uniqueRoomsMap).sort();
        if (sortedRooms.length > 0) {
            filterHtml += '<div class="dropdown">';
            filterHtml += '<button class="btn btn-sm btn-light dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false" data-bs-auto-close="outside">Filter Rooms</button>';
            filterHtml += '<div class="dropdown-menu p-3 shadow" style="min-width: 250px; max-height: 300px; overflow-y: auto;">';

            // "Select All" checkbox
            var selectAllId = 'chk_selectall_' + uid;
            filterHtml += '<div class="form-check form-check-custom form-check-solid mb-2">';
            filterHtml += '<input class="form-check-input js-room-select-all" type="checkbox" data-uid="' + uid + '" id="' + selectAllId + '" checked>';
            filterHtml += '<label class="form-check-label text-gray-700 fw-bold" for="' + selectAllId + '" style="cursor:pointer;">Select All</label>';
            filterHtml += '</div>';
            filterHtml += '<div class="border-bottom mb-2 pb-1"></div>';

            sortedRooms.forEach(function (room, rIndex) {
                var chkId = 'chk_' + uid + '_' + rIndex;
                filterHtml += '<div class="form-check form-check-custom form-check-solid mb-2">';
                filterHtml += '<input class="form-check-input js-room-check" type="checkbox" value="' + escapeHtml(room) + '" data-uid="' + uid + '" id="' + chkId + '" checked>';
                filterHtml += '<label class="form-check-label text-gray-700" for="' + chkId + '" style="cursor:pointer;">' + escapeHtml(room) + '</label>';
                filterHtml += '</div>';
            });
            filterHtml += '</div></div>';
        }
        filterHtml += '<a href="' + historyUrl + '" class="btn btn-sm btn-primary">Historical Price</a>';
        filterHtml += '</div>';

        var bodyContent = buildCombinedTableHtml(section, mult, uid);

        var notePlaceholder = '<div class="invoice-section-title mb-3 text-muted fw-bold fs-7" style="font-size:0.7rem;font-weight:700;letter-spacing:0.05em;text-transform:uppercase;color:#a1a5b7;">NOTE: Tanda (!) menunjukkan harga sudah dikoreksi oleh konstanta pengkoreksi, untuk mengubahnya bisa dilakukan di \'Add and Edit Competitor\'</div>';

        return '<div class="accordion-item border mb-3 rounded">' +
            '<h2 class="accordion-header" id="' + headId + '">' +
            '<button class="accordion-button collapsed fw-bold fs-6" type="button"' +
            ' data-bs-toggle="collapse" data-bs-target="#' + bodyId + '"' +
            ' aria-expanded="false" aria-controls="' + bodyId + '">' +
            escapeHtml(section.competitor_name) + multBadge +
            '</button>' +
            '</h2>' +
            '<div id="' + bodyId + '" class="accordion-collapse collapse"' +
            ' aria-labelledby="' + headId + '">' +
            '<div class="accordion-body pt-4">' +
            notePlaceholder +
            filterHtml +
            bodyContent +
            '</div>' +
            '</div>' +
            '</div>';
    }

    // ---- full page render ------------------------------------------------

    function renderTable(data) {
        var wrap = el('competitor_table_wrap');

        var sub = el('competitor_table_subtitle');
        if (sub) {
            sub.textContent = data.as_of ? 'As of ' + data.as_of : '';
        }

        if (!data.available) {
            wrap.innerHTML = '<div class="text-center text-danger fw-bold py-10">' +
                escapeHtml(data.message || 'Competitor Price Not Available on this Property') + '</div>';
            return;
        }

        var sections = data.competitor_sections || [];

        if (sections.length === 0) {
            wrap.innerHTML = '<div class="text-center text-gray-500 fw-bold py-10">' +
                escapeHtml(data.message || 'No competitor assigned to this property yet. Use "Edit and Add Competitor" to add one.') +
                '</div>';
            return;
        }

        var accordionHtml = '<div class="accordion" id="competitor_accordion">';
        sections.forEach(function (section, index) {
            accordionHtml += buildAccordionItem(section, index);
        });
        accordionHtml += '</div>';

        accordionHtml += '<div id="' + INSIGHT_ID + '" class="mt-6"></div>';

        wrap.innerHTML = accordionHtml;

        // Initialize the charts
        sections.forEach(function (section) {
            var uid = section.competitor_id;
            var mult = section.multiplier_rate || 1;
            var canvasId = 'chart_' + uid;
            var canvasEl = el(canvasId);
            if (canvasEl) {
                initCompetitorChart(canvasEl, section, mult);
            }
        });

        loadNotes(sections);
    }

    // ---- load table from API --------------------------------------------

    function showTableLoader(show) {
        var loader = el('competitor_table_loader');
        if (loader) loader.classList.toggle('d-none', !show);
    }

    function loadTable() {
        if (!el('competitor_table_wrap')) return;
        showTableLoader(true);
        noteToken++;

        ajax('GET', cfg.tableUrl, { customerid: cfg.customerId })
            .done(function (res) {
                showTableLoader(false);
                renderTable(res);
            })
            .fail(function () {
                showTableLoader(false);
                var wrap = el('competitor_table_wrap');
                if (wrap) wrap.innerHTML = '<div class="text-center text-danger fw-bold py-10">Failed to load competitor prices.</div>';
            });
    }

    // ---- modal: alerts --------------------------------------------------

    function modalAlert(type, msg) {
        var box = el('competitor_modal_alert');
        if (!box) return;
        if (!msg) { box.className = 'alert d-none mb-5'; box.textContent = ''; return; }
        box.className = 'alert alert-' + type + ' mb-5';
        box.textContent = msg;
    }

    function otaUrlAlert(type, msg) {
        var box = el('ota_url_modal_alert') || el('more_info_modal_alert');
        if (!box) return;
        if (!msg) { box.className = 'alert d-none mb-5'; box.textContent = ''; return; }
        box.className = 'alert alert-' + type + ' mb-5';
        box.textContent = msg;
    }

    function rateEditAlert(type, msg) {
        var box = el('rate_edit_modal_alert');
        if (!box) return;
        if (!msg) { box.className = 'alert d-none mb-5'; box.textContent = ''; return; }
        box.className = 'alert alert-' + type + ' mb-5';
        box.textContent = msg;
    }

    function addPropertyAlert(type, msg) {
        var box = el('add_property_modal_alert');
        if (!box) return;
        if (!msg) { box.className = 'alert d-none mb-5'; box.textContent = ''; return; }
        box.className = 'alert alert-' + type + ' mb-5';
        box.textContent = msg;
    }

    // ---- modal: assigned competitor slots --------------------------------

    function renderSlots(competitors) {
        var body = el('competitor_slots_body');
        if (!body) return;
        body.innerHTML = '';

        if (!competitors || competitors.length === 0) {
            var emptyTr = document.createElement('tr');
            emptyTr.innerHTML = '<td colspan="3" class="text-center text-gray-500 py-6">' +
                '<div class="mb-3">No competitors assigned to this property yet.</div>' +
                '<button type="button" class="btn btn-sm btn-primary js-open-add-modal">+ Add Competitor</button>' +
                '</td>';
            body.appendChild(emptyTr);
            return;
        }

        competitors.forEach(function (comp, idx) {
            var tr = document.createElement('tr');

            var tdNum = document.createElement('td');
            tdNum.className = 'fw-bold text-gray-700';
            tdNum.textContent = comp.number || (idx + 1);
            tr.appendChild(tdNum);

            var tdName = document.createElement('td');
            var uId = comp.unique_id || comp.id;
            tdName.innerHTML = '<span class="fw-bold">' + escapeHtml(comp.name) +
                '</span> <span class="text-muted fs-8">#' + uId + '</span>';
            tr.appendChild(tdName);

            var tdAct = document.createElement('td');
            tdAct.className = 'text-end text-nowrap';
            tdAct.innerHTML =
                '<button class="btn btn-sm btn-light-info me-1 js-slot-ota-url"' +
                ' data-uid="' + uId + '"' +
                ' data-name="' + escapeHtml(comp.name) + '">OTA Url</button>' +
                '<button class="btn btn-sm btn-light-primary me-1 js-slot-rate-edit"' +
                ' data-uid="' + uId + '"' +
                ' data-name="' + escapeHtml(comp.name) + '">Rate Edit</button>' +
                '<button class="btn btn-sm btn-light-danger js-slot-delete"' +
                ' data-uid="' + uId + '">Delete</button>';
            tr.appendChild(tdAct);

            body.appendChild(tr);
        });

        var addRow = document.createElement('tr');
        addRow.className = 'bg-light-subtle';
        addRow.innerHTML = '<td colspan="3" class="text-center py-3">' +
            '<button type="button" class="btn btn-sm btn-light-primary fw-bold js-open-add-modal">' +
            '+ Add Competitor' +
            '</button>' +
            '</td>';
        body.appendChild(addRow);
    }

    function loadSlots() {
        modalAlert(null);
        var body = el('competitor_slots_body');
        if (!body) return;
        body.innerHTML = '<tr><td colspan="3" class="text-center text-gray-400 py-6">Loading...</td></tr>';

        ajax('GET', cfg.listUrl, { customerid: cfg.customerId }).done(function (res) {
            if (!res.available) {
                body.innerHTML = '<tr><td colspan="3" class="text-center text-danger py-6">' +
                    escapeHtml(res.message || 'Not available') + '</td></tr>';
                return;
            }
            renderSlots(res.competitors);
        }).fail(function () {
            body.innerHTML = '<tr><td colspan="3" class="text-center text-danger py-6">Failed to load.</td></tr>';
        });
    }

    function openSearchModal() {
        modalAlert(null);
        var input = el('competitor_lookup_input');
        if (input) input.value = '';
        var results = el('competitor_lookup_results');
        if (results) { results.innerHTML = ''; results.classList.add('d-none'); }
        var modalEl = el('competitor_search_modal');
        if (modalEl) new bootstrap.Modal(modalEl).show();
    }

    // ---- modal: live lookup ---------------------------------------------

    function doLookup(q) {
        var results = el('competitor_lookup_results');
        if (!results) return;
        if (!q) { results.innerHTML = ''; results.classList.add('d-none'); return; }

        ajax('GET', cfg.lookupUrl, { q: q }).done(function (res) {
            results.classList.remove('d-none');
            if (!res.found || !res.results || res.results.length === 0) {
                results.innerHTML = '<div class="p-3 text-center text-muted fs-7">' +
                    'Not Found. <a href="#" class="fw-bold text-primary js-add-new-property">Add New Property</a></div>';
                return;
            }

            var html = '';
            res.results.forEach(function (r) {
                html += '<div class="p-2 border-bottom hover-bg-light cursor-pointer js-lookup-pick" data-uid="' + r.unique_id + '">' +
                    '<span class="fw-bold text-gray-800">' + escapeHtml(r.property_string_name) + '</span>' +
                    ' <span class="text-muted fs-8">#' + r.unique_id + '</span>' +
                    '</div>';
            });
            results.innerHTML = html;
        }).fail(function () {
            results.classList.remove('d-none');
            results.innerHTML = '<div class="p-3 text-center text-danger fs-7">Error searching property.</div>';
        });
    }

    function assignCompetitor(uniqueId) {
        modalAlert(null);
        ajax('POST', cfg.saveUrl, {
            customerid: cfg.customerId,
            competitor_unique_id: uniqueId
        }).done(function (res) {
            var searchModal = bootstrap.Modal.getInstance(el('competitor_search_modal'));
            if (searchModal) searchModal.hide();

            loadSlots();
            loadTable();
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Failed to assign competitor.';
            modalAlert('danger', msg);
        });
    }

    function deleteCompetitor(uniqueId) {
        if (!confirm('Are you sure you want to remove this competitor?')) return;
        ajax('POST', cfg.deleteUrl, {
            customerid: cfg.customerId,
            competitor_unique_id: uniqueId
        }).done(function () {
            loadSlots();
            loadTable();
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Failed to delete competitor.';
            alert(msg);
        });
    }

    // ---- modal: OTA URL -------------------------------------------------

    var activeMoreInfoUid = null;
    var activeRateEditUid = null;

    function openOtaUrl(uid, name) {
        activeMoreInfoUid = uid;
        otaUrlAlert(null);

        var label = el('ota_url_competitor_label') || el('more_info_competitor_label');
        if (label) label.textContent = 'Property: ' + (name || ('#' + uid));

        if (el('more_info_url_tiket'))   el('more_info_url_tiket').value = '';
        if (el('more_info_url_booking')) el('more_info_url_booking').value = '';

        ajax('GET', cfg.moreInfoUrl, { competitor_unique_id: uid }).done(function (res) {
            if (!res.found) return;
            if (el('more_info_url_tiket'))   el('more_info_url_tiket').value   = res.url_tiket_com || '';
            if (el('more_info_url_booking')) el('more_info_url_booking').value = res.url_booking_com || '';
        });

        var modalEl = el('competitor_ota_url_modal') || el('competitor_more_info_modal');
        if (modalEl) new bootstrap.Modal(modalEl).show();
    }

    function saveOtaUrl() {
        if (!activeMoreInfoUid) return;
        otaUrlAlert(null);

        var tiketVal   = ((el('more_info_url_tiket')   || {}).value || '').trim();
        var bookingVal = ((el('more_info_url_booking') || {}).value || '').trim();

        var saveEndpoint = cfg.moreInfoSaveUrl || cfg.moreInfoUrl;
        ajax('POST', saveEndpoint, {
            competitor_unique_id: activeMoreInfoUid,
            url_tiket_com:    tiketVal  ? tiketVal  : null,
            url_booking_com:  bookingVal ? bookingVal : null
        }).done(function (res) {
            otaUrlAlert('success', res.message || 'Saved successfully.');
            setTimeout(function () {
                var m = bootstrap.Modal.getInstance(el('competitor_ota_url_modal') || el('competitor_more_info_modal'));
                if (m) m.hide();
            }, 800);
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Failed to save.';
            otaUrlAlert('danger', msg);
        });
    }

    // ---- modal: Rate Edit -----------------------------------------------

    var activeRateData = { rooms: [], otas: [], allRates: [] };

    function openRateEdit(uid, name) {
        activeRateEditUid = uid;
        rateEditAlert(null);

        var label = el('rate_edit_competitor_label');
        if (label) label.textContent = 'Property: ' + (name || ('#' + uid));

        var roomSel = el('rate_edit_room_select');
        var otaSel  = el('rate_edit_ota_select');
        if (roomSel) roomSel.innerHTML = '<option value="">Loading rooms...</option>';
        if (otaSel)  otaSel.innerHTML  = '<option value="">Loading OTAs...</option>';

        clearRateFormFields();

        var modalEl = el('competitor_rate_edit_modal');
        if (modalEl) new bootstrap.Modal(modalEl).show();

        ajax('GET', cfg.ratesGetUrl, { customerid: cfg.customerId, competitor_unique_id: uid }).done(function (res) {
            if (!res.found) {
                rateEditAlert('danger', 'Failed to load property details.');
                return;
            }
            activeRateData.rooms    = res.rooms || [];
            activeRateData.otas     = res.otas || [];
            activeRateData.allRates = res.all_rates || [];

            // Populate Room select
            var rHtml = '';
            activeRateData.rooms.forEach(function (r) {
                rHtml += '<option value="' + r.room_id + '">' + escapeHtml(r.room_name) + '</option>';
            });
            if (roomSel) roomSel.innerHTML = rHtml || '<option value="">No rooms found</option>';

            // Populate OTA select
            var oHtml = '';
            activeRateData.otas.forEach(function (o) {
                oHtml += '<option value="' + o.id + '">' + escapeHtml(o.name) + '</option>';
            });
            if (otaSel) otaSel.innerHTML = oHtml || '<option value="">No OTAs found</option>';

            syncRateFormFields();
        }).fail(function () {
            rateEditAlert('danger', 'Failed to load rate multiplier details.');
        });
    }

    function toggleWindowMultipliersState() {
        var globalVal = (el('rate_edit_global_rate') || {}).value;
        var hasGlobal = globalVal !== undefined && globalVal !== null && String(globalVal).trim() !== '';

        ['rate_edit_mult_3', 'rate_edit_mult_7', 'rate_edit_mult_14', 'rate_edit_mult_30'].forEach(function (id) {
            var f = el(id);
            if (f) {
                f.disabled = hasGlobal;
            }
        });
    }

    function clearRateFormFields() {
        ['rate_edit_global_rate', 'rate_edit_mult_3', 'rate_edit_mult_7', 'rate_edit_mult_14', 'rate_edit_mult_30'].forEach(function (id) {
            var f = el(id);
            if (f) {
                f.value = '';
                f.disabled = false;
            }
        });
    }

    function syncRateFormFields() {
        var roomVal = (el('rate_edit_room_select') || {}).value;
        var otaVal  = (el('rate_edit_ota_select') || {}).value;

        clearRateFormFields();
        if (!roomVal || !otaVal) return;

        var roomId = parseInt(roomVal, 10);
        var otaId  = parseInt(otaVal, 10);

        var match = activeRateData.allRates.find(function (r) {
            return parseInt(r.ref_room, 10) === roomId && parseInt(r.ota_ref, 10) === otaId;
        });

        if (match) {
            if (el('rate_edit_global_rate')) el('rate_edit_global_rate').value = match.global_rate !== null && match.global_rate !== undefined ? match.global_rate : '';
            if (el('rate_edit_mult_3'))      el('rate_edit_mult_3').value      = match.mult_3 !== null && match.mult_3 !== undefined ? match.mult_3 : '';
            if (el('rate_edit_mult_7'))      el('rate_edit_mult_7').value      = match.mult_7 !== null && match.mult_7 !== undefined ? match.mult_7 : '';
            if (el('rate_edit_mult_14'))     el('rate_edit_mult_14').value     = match.mult_14 !== null && match.mult_14 !== undefined ? match.mult_14 : '';
            if (el('rate_edit_mult_30'))     el('rate_edit_mult_30').value     = match.mult_30 !== null && match.mult_30 !== undefined ? match.mult_30 : '';
        }

        toggleWindowMultipliersState();
    }

    function saveRateEdit() {
        if (!activeRateEditUid) return;
        rateEditAlert(null);

        var roomVal = (el('rate_edit_room_select') || {}).value;
        var otaVal  = (el('rate_edit_ota_select') || {}).value;

        if (!roomVal) {
            rateEditAlert('danger', 'Please select a Room Type.');
            return;
        }
        if (!otaVal) {
            rateEditAlert('danger', 'Please select an OTA Channel.');
            return;
        }

        var parseNum = function (id) {
            var val = (el(id) || {}).value;
            return (val !== '' && val !== null && !isNaN(val)) ? parseFloat(val) : null;
        };

        var payload = {
            customerid:           cfg.customerId,
            competitor_unique_id: activeRateEditUid,
            ref_room:             parseInt(roomVal, 10),
            ota_ref:              parseInt(otaVal, 10),
            global_rate:          parseNum('rate_edit_global_rate'),
            mult_3:               parseNum('rate_edit_mult_3'),
            mult_7:               parseNum('rate_edit_mult_7'),
            mult_14:              parseNum('rate_edit_mult_14'),
            mult_30:              parseNum('rate_edit_mult_30')
        };

        ajax('POST', cfg.rateSaveUrl, payload).done(function (res) {
            rateEditAlert('success', res.message || 'Rate multipliers saved successfully.');

            var roomId = parseInt(roomVal, 10);
            var otaId  = parseInt(otaVal, 10);
            var match  = activeRateData.allRates.find(function (r) {
                return parseInt(r.ref_room, 10) === roomId && parseInt(r.ota_ref, 10) === otaId;
            });
            if (!match) {
                match = { ref_room: roomId, ota_ref: otaId };
                activeRateData.allRates.push(match);
            }
            match.global_rate = payload.global_rate;
            match.mult_3      = payload.mult_3;
            match.mult_7      = payload.mult_7;
            match.mult_14     = payload.mult_14;
            match.mult_30     = payload.mult_30;

            loadTable();
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Failed to save rate multipliers.';
            rateEditAlert('danger', msg);
        });
    }

    // ---- Add New Property modal -----------------------------------------

    function openAddProperty() {
        addPropertyAlert(null);

        var searchVal = (el('competitor_lookup_input') || {}).value || '';
        var fName    = el('add_property_name');
        var fTiket   = el('add_property_url_tiket');
        var fBooking = el('add_property_url_booking');

        if (fName)    fName.value    = searchVal.trim();
        if (fTiket)   fTiket.value   = '';
        if (fBooking) fBooking.value = '';

        var modalEl = el('competitor_add_property_modal');
        if (modalEl) new bootstrap.Modal(modalEl).show();
    }

    function saveAddProperty() {
        addPropertyAlert(null);

        var name       = ((el('add_property_name')        || {}).value || '').trim();
        var tiketVal   = ((el('add_property_url_tiket')   || {}).value || '').trim();
        var bookingVal = ((el('add_property_url_booking') || {}).value || '').trim();

        if (!name) {
            addPropertyAlert('danger', 'Property name is required.');
            return;
        }
        if (!tiketVal && !bookingVal) {
            addPropertyAlert('danger', 'At least one URL (Tiket.com or Booking.com) is required.');
            return;
        }

        ajax('POST', cfg.addPropertyUrl, {
            customerid:      cfg.customerId,
            property_name:   name,
            url_tiket_com:   tiketVal  || null,
            url_booking_com: bookingVal || null
        }).done(function (res) {
            addPropertyAlert('success', res.message || 'Property added and assigned.');

            setTimeout(function () {
                var addModal = bootstrap.Modal.getInstance(el('competitor_add_property_modal'));
                if (addModal) addModal.hide();

                var searchModal = bootstrap.Modal.getInstance(el('competitor_search_modal'));
                if (searchModal) searchModal.hide();

                if (el('competitor_lookup_input'))  el('competitor_lookup_input').value = '';
                if (el('competitor_lookup_results')) el('competitor_lookup_results').classList.add('d-none');

                loadSlots();
                loadTable();
            }, 800);
        }).fail(function (xhr) {
            var msg = (xhr.responseJSON && xhr.responseJSON.message) || 'Failed to add property.';
            addPropertyAlert('danger', msg);
        });
    }

    // ---- wiring ----------------------------------------------------------

    function init() {
        var hasChart = el('competitor_table_wrap');
        var hasSlots = el('competitor_slots_body');

        if (hasChart) {
            function applyRoomFilter(uid) {
                var checkedValues = {};
                var checkboxes = document.querySelectorAll('.js-room-check[data-uid="' + uid + '"]:checked');
                for (var i = 0; i < checkboxes.length; i++) {
                    checkedValues[checkboxes[i].value] = true;
                }

                var bodyEl = document.getElementById('acc_body_' + uid);
                if (!bodyEl) return;

                var rows = bodyEl.querySelectorAll('.js-room-row');
                for (var j = 0; j < rows.length; j++) {
                    var roomName = rows[j].getAttribute('data-room');
                    rows[j].style.display = checkedValues[roomName] ? '' : 'none';
                }
            }

            function syncSelectAll(uid) {
                var all      = document.querySelectorAll('.js-room-check[data-uid="' + uid + '"]');
                var checked  = document.querySelectorAll('.js-room-check[data-uid="' + uid + '"]:checked');
                var selectEl = document.querySelector('.js-room-select-all[data-uid="' + uid + '"]');
                if (!selectEl) return;

                if (checked.length === 0) {
                    selectEl.checked       = false;
                    selectEl.indeterminate = false;
                } else if (checked.length === all.length) {
                    selectEl.checked       = true;
                    selectEl.indeterminate = false;
                } else {
                    selectEl.checked       = false;
                    selectEl.indeterminate = true;
                }
            }

            $('#competitor_table_wrap').on('change', '.js-room-select-all', function () {
                var uid     = this.getAttribute('data-uid');
                var checked = this.checked;
                var boxes   = document.querySelectorAll('.js-room-check[data-uid="' + uid + '"]');
                for (var i = 0; i < boxes.length; i++) {
                    boxes[i].checked = checked;
                }
                this.indeterminate = false;
                applyRoomFilter(uid);
            });

            $('#competitor_table_wrap').on('change', '.js-room-check', function () {
                var uid = this.getAttribute('data-uid');
                applyRoomFilter(uid);
                syncSelectAll(uid);
            });

            loadTable();
        }

        if (hasSlots) {
            loadSlots();
        }

        $('#btn_open_search_modal').on('click', openSearchModal);

        $('#competitor_slots_body').on('click', '.js-open-add-modal', openSearchModal);

        $('#competitor_lookup_input').on('keyup', debounce(function () {
            doLookup(this.value.trim());
        }, 300));

        $('#competitor_slots_body').on('click', '.js-slot-delete', function () {
            var uid = parseInt(this.getAttribute('data-uid'), 10);
            deleteCompetitor(uid);
        });

        $('#competitor_slots_body').on('click', '.js-slot-ota-url', function () {
            var uid  = parseInt(this.getAttribute('data-uid'), 10);
            var name = this.getAttribute('data-name');
            openOtaUrl(uid, name);
        });

        $('#competitor_slots_body').on('click', '.js-slot-moreinfo', function () {
            var uid  = parseInt(this.getAttribute('data-uid'), 10);
            var name = this.getAttribute('data-name');
            openOtaUrl(uid, name);
        });

        $('#competitor_slots_body').on('click', '.js-slot-rate-edit', function () {
            var uid  = parseInt(this.getAttribute('data-uid'), 10);
            var name = this.getAttribute('data-name');
            openRateEdit(uid, name);
        });

        $('#competitor_lookup_results').on('click', '.js-lookup-pick', function () {
            assignCompetitor(parseInt(this.getAttribute('data-uid'), 10));
        });

        $('#competitor_lookup_results').on('click', '.js-add-new-property', function (e) {
            e.preventDefault();
            openAddProperty();
        });

        $('#rate_edit_room_select').on('change', syncRateFormFields);
        $('#rate_edit_ota_select').on('change', syncRateFormFields);
        $('#rate_edit_global_rate').on('input keyup change', toggleWindowMultipliersState);

        $('#more_info_save_btn').on('click', saveOtaUrl);
        $('#rate_edit_save_btn').on('click', saveRateEdit);

        $('#add_property_save_btn').on('click', saveAddProperty);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
