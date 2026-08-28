// WellNest Unified Command Center
// All agent progress is driven by real-time SSE events from the backend.
// No fake delays. Every visual update comes from actual backend execution.

let activeResidentId = null;
let sseSource = null;       // broadcast SSE (persistent, receives events from any trigger)
let currentFilter = 'all';
let allLoggedEvents = [];
let vitalsPollingInterval = null;
let isHealthCheckRunning = false;
let broadcastReconnectTimer = null;

// Accumulated trajectory data from SSE events
let liveTrajectory = {
    sensory_guardian: { status: 'SKIPPED', output: '' },
    medical_compliance: { status: 'SKIPPED', output: '' },
    cognitive_companion: { status: 'SKIPPED', output: '' },
    care_coordinator: { status: 'SKIPPED', output: '' }
};

function getApiBaseUrl() {
    return localStorage.getItem("wellnest_api_url") || "";
}

// ============================================================
// INITIALIZATION
// ============================================================

document.addEventListener("DOMContentLoaded", () => {
    initResidents();
    initAlerts();
    checkConnection();
    setInterval(checkConnection, 8000);

    // Core actions
    document.getElementById("trigger-check-btn").addEventListener("click", triggerAgentCheck);
    document.getElementById("clear-btn").addEventListener("click", clearAlertTimeline);
    document.getElementById("modal-ack-btn").addEventListener("click", closeModal);

    // Backend config
    document.getElementById("config-backend-btn").addEventListener("click", openConfigModal);
    document.getElementById("config-close-btn").addEventListener("click", closeConfigModal);
    document.getElementById("config-reset-btn").addEventListener("click", resetConfigToLocal);
    document.getElementById("config-connect-btn").addEventListener("click", connectToBackend);

    // Toggle Mission Control / Alert Log section
    const toggleLogsBtn = document.getElementById("toggle-logs-btn");
    if (toggleLogsBtn) {
        toggleLogsBtn.addEventListener("click", () => {
            const grid = document.querySelector(".dashboard-grid");
            const panelRight = document.getElementById("panel-right");
            if (!panelRight) return;
            const isHidden = panelRight.classList.contains("hidden");
            if (isHidden) {
                panelRight.classList.remove("hidden");
                if (grid) grid.classList.add("logs-visible");
                document.getElementById("toggle-logs-text").textContent = "Hide Mission Control";
            } else {
                panelRight.classList.add("hidden");
                if (grid) grid.classList.remove("logs-visible");
                document.getElementById("toggle-logs-text").textContent = "Mission Control Log";
            }
        });
    }

    // Terminal tab switching
    document.querySelectorAll('.terminal-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.terminal-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.terminal-tab-content').forEach(c => c.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById('tab-' + tab.dataset.tab).classList.add('active');
        });
    });

    // Filter chips
    document.querySelectorAll('.filter-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
            chip.classList.add('active');
            currentFilter = chip.dataset.filter;
            applyLogFilter();
        });
    });
});

// ============================================================
// CONNECTION STATUS
// ============================================================

async function checkConnection() {
    const dot = document.getElementById('conn-dot');
    const text = document.getElementById('conn-text');
    try {
        const res = await fetch(getApiBaseUrl() + '/api/alerts');
        if (res.ok) {
            dot.classList.add('online');
            text.textContent = getApiBaseUrl() ? 'Cloud Run Connected' : 'Localhost Connected';
        } else { throw new Error(); }
    } catch {
        dot.classList.remove('online');
        text.textContent = 'Disconnected';
    }
}

// ============================================================
// BACKEND CONFIG MODAL
// ============================================================

function openConfigModal() {
    document.getElementById("input-backend-url").value = getApiBaseUrl();
    document.getElementById("config-status").innerText = "";
    document.getElementById("modal-config").classList.remove("hidden");
}

function closeConfigModal() {
    document.getElementById("modal-config").classList.add("hidden");
}

function resetConfigToLocal() {
    localStorage.removeItem("wellnest_api_url");
    document.getElementById("config-status").style.color = "var(--color-success)";
    document.getElementById("config-status").innerText = "Switched to Localhost backend!";
    setTimeout(() => { closeConfigModal(); window.location.reload(); }, 1000);
}

async function connectToBackend() {
    let url = document.getElementById("input-backend-url").value.trim();
    if (!url) {
        document.getElementById("config-status").style.color = "var(--color-danger)";
        document.getElementById("config-status").innerText = "URL cannot be empty.";
        return;
    }
    if (url.endsWith("/")) url = url.slice(0, -1);

    document.getElementById("config-status").style.color = "var(--color-info)";
    document.getElementById("config-status").innerText = "Validating connection...";

    try {
        const res = await fetch(url + "/api/residents");
        if (res.ok) {
            localStorage.setItem("wellnest_api_url", url);
            document.getElementById("config-status").style.color = "var(--color-success)";
            document.getElementById("config-status").innerText = "Connected successfully!";
            setTimeout(() => { closeConfigModal(); window.location.reload(); }, 1000);
        } else {
            throw new Error("Endpoint returned status " + res.status);
        }
    } catch (err) {
        document.getElementById("config-status").style.color = "var(--color-danger)";
        document.getElementById("config-status").innerText = "Failed to connect. Ensure URL is correct and CORS is enabled.";
    }
}

// ============================================================
// RESIDENT DIRECTORY
// ============================================================

async function initResidents() {
    try {
        const res = await fetch(getApiBaseUrl() + "/api/residents");
        const residents = await res.json();

        const listContainer = document.getElementById("residents-list");
        listContainer.innerHTML = "";

        if (residents.length === 0) {
            listContainer.innerHTML = "<p class='placeholder-text'>No residents configured.</p>";
            return;
        }

        residents.forEach((r, idx) => {
            const card = document.createElement("div");
            card.className = `resident-card glass-panel-inner ${idx === 0 ? "active" : ""}`;
            card.dataset.id = r.id;
            card.innerHTML = `
                <div class="res-header">
                    <span class="res-name">${r.name}</span>
                    <span class="res-age">Age ${r.age}</span>
                </div>
                <div class="res-meta">${r.conditions.slice(0, 2).join(", ")}</div>
            `;
            card.addEventListener("click", () => selectResident(r.id));
            listContainer.appendChild(card);
        });

        if (residents.length > 0) selectResident(residents[0].id);
    } catch (e) {
        console.error("Error loading residents:", e);
        document.getElementById("residents-list").innerHTML = "<p class='status-pill status-failed'>Failed to connect to backend.</p>";
    }
}

async function selectResident(residentId) {
    activeResidentId = residentId;

    document.querySelectorAll(".resident-card").forEach(card => {
        card.classList.toggle("active", card.dataset.id === residentId);
    });

    resetAgentWorkspace();

    // Open the persistent broadcast channel for this resident.
    // Any /trigger call from ANY device (mobile, API, desktop) will now
    // stream events directly into this dashboard in real-time.
    subscribeToBroadcast(residentId);

    try {
        const res = await fetch(getApiBaseUrl() + `/api/residents/${residentId}`);
        const data = await res.json();
        const p = data.profile;
        const v = data.vitals;

        document.getElementById("selected-resident-profile").classList.remove("hidden");
        document.getElementById("prof-name").innerText = p.name;
        document.getElementById("prof-age").innerText = p.age;
        document.getElementById("prof-cond").innerText = p.conditions.join(", ");

        const medsList = document.getElementById("prof-meds-list");
        medsList.innerHTML = "";
        p.medications.forEach(m => {
            const li = document.createElement("li");
            li.innerHTML = `<strong>${m.name}</strong> (${m.dose})<br><span style='color: var(--color-text-muted)'>${m.frequency}</span>`;
            medsList.appendChild(li);
        });

        updateVitalsDOM(v);
        startVitalsPolling();
    } catch (e) {
        console.error("Error fetching resident details:", e);
    }
}

function updateVitalsDOM(v) {
    document.getElementById("vital-hr").innerText = v.telemetry.heart_rate_bpm;
    document.getElementById("base-hr").innerText = v.baselines.heart_rate_bpm;
    document.getElementById("vital-bp").innerText = `${v.telemetry.bp_systolic}/${v.telemetry.bp_diastolic}`;
    document.getElementById("bp-deviation").innerText = `Baseline: ${v.baselines.bp_systolic}/${v.baselines.bp_diastolic}`;
    document.getElementById("vital-gait").innerText = v.telemetry.gait_speed_ms;
    document.getElementById("gait-deviation").innerText = `Baseline: ${v.baselines.gait_speed_ms} m/s`;
    document.getElementById("vital-sleep").innerText = v.telemetry.sleep_hours;
    document.getElementById("base-sleep").innerText = v.baselines.sleep_hours;
    document.getElementById("vital-occupancy").innerText = v.telemetry.room_occupancy.replace('_', ' ').toUpperCase();

    const bpCard = document.getElementById("card-bp");
    const gaitCard = document.getElementById("card-gait");
    bpCard.classList.remove("anomaly-alert");
    gaitCard.classList.remove("anomaly-alert");

    if (v.status === "ANOMALY_DETECTED") {
        if (v.telemetry.bp_systolic >= 140 || v.telemetry.bp_systolic <= 100) bpCard.classList.add("anomaly-alert");
        if (v.gait_change_percent <= -15.0) gaitCard.classList.add("anomaly-alert");
    }
}

function startVitalsPolling() {
    stopVitalsPolling();
    vitalsPollingInterval = setInterval(async () => {
        if (!activeResidentId || isHealthCheckRunning) return;
        try {
            const res = await fetch(getApiBaseUrl() + `/api/residents/${activeResidentId}`);
            if (!res.ok) return;
            const data = await res.json();
            updateVitalsDOM(data.vitals);
        } catch (e) {
            console.error("Polling error:", e);
        }
    }, 2000);
}

function stopVitalsPolling() {
    if (vitalsPollingInterval) {
        clearInterval(vitalsPollingInterval);
        vitalsPollingInterval = null;
    }
}
// ============================================================
// AGENT WORKSPACE
// ============================================================

function resetAgentWorkspace() {
    const agents = ["sensory", "compliance", "companion", "coordinator"];
    agents.forEach(a => {
        const col = document.getElementById(`agent-${a}`);
        col.querySelector(".status-pill").className = "status-pill status-waiting";
        col.querySelector(".status-pill").innerText = "Waiting";
        const box = col.querySelector(".agent-output-box");
        if (a === "sensory") box.innerHTML = "<p class='placeholder-text'>Waiting to ingest vital telemetry streams...</p>";
        if (a === "compliance") box.innerHTML = "<p class='placeholder-text'>Waiting for sensory anomaly escalation...</p>";
        if (a === "companion") box.innerHTML = "<p class='placeholder-text'>Waiting for clinical findings check-in draft...</p>";
        if (a === "coordinator") box.innerHTML = "<p class='placeholder-text'>Waiting to dispatch A2A cryptographic alerts...</p>";
    });

    // Reset empathy section
    document.getElementById("empathy-content").innerHTML =
        "<p class='empathy-placeholder'>The Cognitive Companion will speak here after the clinical consensus completes.</p>";

    // Reset trajectory
    liveTrajectory = {
        sensory_guardian: { status: 'SKIPPED', output: '' },
        medical_compliance: { status: 'SKIPPED', output: '' },
        cognitive_companion: { status: 'SKIPPED', output: '' },
        care_coordinator: { status: 'SKIPPED', output: '' }
    };
}

function setAgentStatus(agentKey, statusText, statusClass) {
    const col = document.getElementById(`agent-${agentKey}`);
    const pill = col.querySelector(".status-pill");
    pill.className = `status-pill ${statusClass}`;
    pill.innerText = statusText;
}

function setAgentOutput(agentKey, html) {
    const col = document.getElementById(`agent-${agentKey}`);
    const box = col.querySelector(".agent-output-box");
    box.innerHTML = `<div style='animation: fadeIn 0.4s ease'>${html}</div>`;
}

// ============================================================
// SSE-DRIVEN HEALTH CHECK (THE CORE UNIFICATION)
// ============================================================

// Called when local "Run" button is pressed OR from any other source
function triggerAgentCheck() {
    if (!activeResidentId || isHealthCheckRunning) return;

    const btn = document.getElementById("trigger-check-btn");
    btn.disabled = true;
    btn.innerText = "Agents Running...";

    // POST to /trigger — agents start on GCP, broadcast SSE will deliver events
    // We do NOT await the JSON response immediately because this request 
    // intentionally blocks for 60-90s to keep Cloud Run CPU alive.
    fetch(getApiBaseUrl() + `/api/residents/${activeResidentId}/check/trigger`, { method: 'POST' })
        .catch(err => {
            console.log('Trigger fetch closed/timeout (expected):', err);
        });
}

// Open (or reopen) the persistent broadcast SSE channel for the active resident.
// This is called whenever a new resident is selected.
// ALL events from ANY trigger source (mobile, desktop, API) arrive here.
function subscribeToBroadcast(residentId) {
    // Close existing connection
    if (sseSource) {
        sseSource.close();
        sseSource = null;
    }
    if (broadcastReconnectTimer) {
        clearTimeout(broadcastReconnectTimer);
    }

    const baseUrl = getApiBaseUrl();
    const url = `${baseUrl}/api/residents/${residentId}/check/broadcast`;
    sseSource = new EventSource(url);

    sseSource.onmessage = (event) => {
        try {
            const evt = JSON.parse(event.data);

            // Handshake — connection confirmed, reset UI to ready state
            if (evt.event_type === 'BROADCAST_CONNECTED') {
                isHealthCheckRunning = false;
                const btn = document.getElementById("trigger-check-btn");
                if (btn) { btn.disabled = false; btn.innerText = "Run Multi-Agent Health Check"; }
                document.getElementById('terminal-status').textContent = `wellnest://broadcast/${residentId}`;
                appendLogRow(evt);
                return;
            }

            // First real agent event — mark check as running
            if (!isHealthCheckRunning && evt.event_type !== 'COMPLETE') {
                isHealthCheckRunning = true;
                stopVitalsPolling();
                resetAgentWorkspace();
                clearTerminalLogs();
                allLoggedEvents = [];

                // Switch to terminal tab
                document.querySelectorAll('.terminal-tab').forEach(t => t.classList.remove('active'));
                document.querySelectorAll('.terminal-tab-content').forEach(c => c.classList.remove('active'));
                document.querySelector('[data-tab="terminal"]').classList.add('active');
                document.getElementById('tab-terminal').classList.add('active');
                document.getElementById('terminal-status').textContent = `wellnest://running/${residentId}`;

                // Show running in button
                const btn = document.getElementById("trigger-check-btn");
                if (btn) { btn.disabled = true; btn.innerText = "Agents Running..."; }

                setAgentStatus("sensory", "Analyzing Vitals", "status-running");
            }

            allLoggedEvents.push(evt);
            if (currentFilter === 'all' || evt.agent === currentFilter) {
                appendLogRow(evt);
            }
            processAgentEvent(evt);

            // COMPLETE sentinel
            if (evt.event_type === 'COMPLETE') {
                isHealthCheckRunning = false;
                startVitalsPolling();
                initAlerts();
                triggerModalAlert();
                document.getElementById('terminal-status').textContent = `wellnest://complete/${residentId}`;
                const btn = document.getElementById("trigger-check-btn");
                if (btn) { btn.disabled = false; btn.innerText = "Run Multi-Agent Health Check"; }
            }
        } catch (e) {
            console.error("Broadcast SSE parse error:", e);
        }
    };

    sseSource.onerror = () => {
        // Auto-reconnect after 4 seconds
        sseSource.close();
        sseSource = null;
        broadcastReconnectTimer = setTimeout(() => {
            if (activeResidentId === residentId) {
                subscribeToBroadcast(residentId);
            }
        }, 4000);
    };
}

// Map SSE trace events to visual agent card updates
function processAgentEvent(evt) {
    const agent = evt.agent;
    const type = evt.event_type;
    const data = evt.data || {};

    // ORCHESTRATOR stage events control agent card transitions
    if (agent === 'ORCHESTRATOR') {
        if (type === 'STAGE' || type === 'START') {
            if (evt.message.includes('Sensory Guardian')) {
                setAgentStatus('sensory', 'Analyzing Vitals', 'status-running');
            }
        }
        if (type === 'HANDOFF') {
            if (evt.message.includes('Medical Compliance')) {
                setAgentStatus('compliance', 'Running FDA Lookups', 'status-running');
            }
            if (evt.message.includes('Cognitive Companion')) {
                setAgentStatus('companion', 'Composing Dialogue', 'status-running');
            }
            if (evt.message.includes('Care Coordinator')) {
                setAgentStatus('coordinator', 'Routing A2A', 'status-running');
            }
        }
        if (type === 'COMPLETE') {
            // Everything is done
        }
    }

    // Agent LLM_RESPONSE events populate the agent output cards
    if (type === 'LLM_RESPONSE' && data.response) {
        if (agent === 'SENSORY_GUARDIAN') {
            setAgentStatus('sensory', 'Completed', 'status-completed');
            setAgentOutput('sensory', formatMarkdown(data.response));
            liveTrajectory.sensory_guardian = { status: 'COMPLETED', output: data.response };
        }
        if (agent === 'MEDICAL_COMPLIANCE') {
            setAgentStatus('compliance', 'Completed', 'status-completed');
            setAgentOutput('compliance', formatMarkdown(data.response));
            liveTrajectory.medical_compliance = { status: 'COMPLETED', output: data.response };
        }
        if (agent === 'COGNITIVE_COMPANION') {
            setAgentStatus('companion', 'Completed', 'status-completed');
            setAgentOutput('companion', `<strong>Empathetic Dialogue:</strong><br><br><em>"${data.response}"</em>`);
            liveTrajectory.cognitive_companion = { status: 'COMPLETED', output: data.response };

            // Populate the empathy dialogue section
            document.getElementById("empathy-content").innerHTML = `
                <div class="empathy-bubble">
                    <div class="empathy-speaker">
                        <div class="empathy-speaker-dot"></div>
                        <span class="empathy-speaker-name">Cognitive Companion</span>
                    </div>
                    <p class="empathy-text">"${escapeHtml(data.response)}"</p>
                </div>
            `;
        }
        if (agent === 'CARE_COORDINATOR') {
            setAgentStatus('coordinator', 'Completed', 'status-completed');
            setAgentOutput('coordinator', formatMarkdown(data.response));
            liveTrajectory.care_coordinator = { status: 'COMPLETED', output: data.response };
        }
    }

    // Handle TOOL_CALL events
    if (type === 'TOOL_CALL') {
        if (agent === 'SENSORY_GUARDIAN') setAgentStatus('sensory', 'Calling Tools', 'status-running');
        if (agent === 'MEDICAL_COMPLIANCE') setAgentStatus('compliance', 'Calling Tools', 'status-running');
        if (agent === 'CARE_COORDINATOR') setAgentStatus('coordinator', 'Calling Tools', 'status-running');
    }

    // Handle ERROR events -- display transparent error state with details
    if (type === 'ERROR') {
        const errorDetail = `<p style="color:var(--color-danger);font-weight:600;font-size:12px;">[ERROR] ${escapeHtml(evt.message)}</p>`;
        if (agent === 'SENSORY_GUARDIAN' || evt.message.includes('Sensory')) {
            setAgentStatus('sensory', 'Error', 'status-failed');
            setAgentOutput('sensory', errorDetail);
        }
        if (agent === 'MEDICAL_COMPLIANCE' || evt.message.includes('Medical')) {
            setAgentStatus('compliance', 'Error', 'status-failed');
            setAgentOutput('compliance', errorDetail);
        }
        if (agent === 'COGNITIVE_COMPANION' || evt.message.includes('Companion')) {
            setAgentStatus('companion', 'Error', 'status-failed');
            setAgentOutput('companion', errorDetail);
        }
        if (agent === 'CARE_COORDINATOR' || evt.message.includes('Coordinator')) {
            setAgentStatus('coordinator', 'Error', 'status-failed');
            setAgentOutput('coordinator', errorDetail);
        }
    }
}

// ============================================================
// TERMINAL LOG PANEL
// ============================================================

function clearTerminalLogs() {
    document.getElementById('terminal-logs').innerHTML = '';
}

function appendLogRow(evt) {
    const container = document.getElementById('terminal-logs');
    const row = document.createElement('div');
    row.className = 'log-row';

    let dataBlock = '';
    if (evt.data && Object.keys(evt.data).length > 0) {
        const truncated = JSON.stringify(evt.data, null, 2);
        if (truncated.length > 10) {
            dataBlock = `<div class="log-data-block">${escapeHtml(truncated.substring(0, 300))}${truncated.length > 300 ? '...' : ''}</div>`;
        }
    }

    row.innerHTML = `
        <span class="log-time">${evt.timestamp_str}</span>
        <span class="log-agent agent-${evt.agent}">${evt.agent}</span>
        <span class="log-event">${evt.event_type}</span>
        <span class="log-msg">${escapeHtml(evt.message)}${dataBlock}</span>
    `;

    container.appendChild(row);
    container.scrollTop = container.scrollHeight;
}

function applyLogFilter() {
    const container = document.getElementById('terminal-logs');
    container.innerHTML = '';
    allLoggedEvents.forEach(evt => {
        if (currentFilter === 'all' || evt.agent === currentFilter) {
            appendLogRow(evt);
        }
    });
}

// ============================================================
// CONSENSUS MODAL
// ============================================================

function triggerModalAlert() {
    const complianceText = liveTrajectory.medical_compliance.output || "";
    const companionText = liveTrajectory.cognitive_companion.output || "";
    const sensoryText = liveTrajectory.sensory_guardian.output || "";

    // Only show modal if we have real data
    if (!complianceText && !companionText) return;

    // 1. Dynamic Anomaly Extraction
    let observedAnomaly = "Ambient telemetry detected significant vitals deviation from baseline thresholds.";
    if (sensoryText) {
        const anomalyMatch = sensoryText.match(/\*\*(?:Observed Anomaly|Anomaly Description|Observed Anomaly Description).*?\*\*[:\s]+(.*?)(?=\n-|$)/is);
        if (anomalyMatch && anomalyMatch[1]) {
            observedAnomaly = anomalyMatch[1].trim();
        } else {
            const lines = sensoryText.split('\n');
            const anomalyLine = lines.find(l => l.includes('Anomaly') && (l.includes('speed') || l.includes('pressure') || l.includes('sleep')));
            if (anomalyLine) observedAnomaly = anomalyLine.replace(/^[-* ]*(.*?:)?\s*/i, '').trim();
        }
    }

    document.getElementById("modal-message").innerHTML = `
        <strong>Observed Anomaly:</strong> ${escapeHtml(observedAnomaly).replace(/\*\*/g, '')}<br><br>
        <strong>Empathy Guidance:</strong> "${escapeHtml(companionText).replace(/\*\*/g, '')}"
    `;

    // 2. Dynamic Correlation Findings
    let interaction = "Hypotensive risks associated with medication introduction. Advise standing slowly, hydration, and observation.";
    if (complianceText) {
        const findingsMatch = complianceText.match(/\*\*Correlation Findings.*?\*\*[:\s]+(.*?)(?=\n-|$)/is);
        if (findingsMatch && findingsMatch[1]) {
            interaction = findingsMatch[1].trim();
        } else {
            const lines = complianceText.split('\n');
            const findLine = lines.find(l => l.includes('Findings') || l.includes('Correlation'));
            if (findLine) {
                interaction = findLine.replace(/^[-* ]*(.*?:)?\s*/i, '').trim();
            } else {
                interaction = complianceText.substring(0, 300) + "...";
            }
        }
    }
    document.getElementById("modal-correlation").innerText = interaction.replace(/\*\*/g, '');

    // 3. Dynamic Action Interventions
    let actionsHtml = `
        <li>[!] Guide resident to hydrate immediately and stand up slowly</li>
        <li>[!] Notify family representative agent over active A2A node</li>
        <li>[!] Request primary care physician review pharmacological dosages</li>
    `;
    
    if (complianceText) {
        const advisoryMatch = complianceText.match(/\*\*Geriatric Advisory.*?\*\*[:\s]+(.*?)(?=\n-|$)/is);
        const actionsMatch = complianceText.match(/\*\*Recommended Care Actions.*?\*\*[:\s]+(.*?)(?=\n-|$)/is);
        
        let advices = [];
        if (advisoryMatch && advisoryMatch[1]) {
            let sentences = advisoryMatch[1].split('. ').filter(s => s.trim().length > 0);
            advices.push(...sentences);
        }
        if (actionsMatch && actionsMatch[1]) {
            advices.push(actionsMatch[1]);
        }
        
        if (advices.length > 0) {
            actionsHtml = advices.map(a => {
                let text = a.trim().replace(/\*\*/g, '');
                if (!text.endsWith('.')) text += '.';
                return `<li>[!] ${escapeHtml(text)}</li>`;
            }).join('');
        }
    }

    document.getElementById("modal-actions-list").innerHTML = actionsHtml;
    document.getElementById("modal-alert").classList.remove("hidden");
}

function closeModal() {
    document.getElementById("modal-alert").classList.add("hidden");
}

// ============================================================
// A2A ALERTS TIMELINE
// ============================================================

async function initAlerts() {
    try {
        const res = await fetch(getApiBaseUrl() + "/api/alerts");
        const alerts = await res.json();

        const timeline = document.getElementById("alerts-timeline");
        timeline.innerHTML = "";

        if (alerts.length === 0) {
            timeline.innerHTML = `
                <div class="no-alerts-placeholder">
                    <span style="display:flex;align-items:center;justify-content:center;color:#475569;margin-bottom:0.8rem;">
                        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
                            <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
                        </svg>
                    </span>
                    <p>No active alerts dispatched. System running in baseline safety thresholds.</p>
                </div>
            `;
            return;
        }

        alerts.forEach(alert => {
            const item = document.createElement("div");
            const severityClass = alert.severity === "CRITICAL" ? "critical" : "warning";
            item.className = `alert-feed-item glass-panel-inner ${severityClass}`;

            const date = new Date(alert.timestamp);
            const timeStr = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            item.innerHTML = `
                <div class="alert-item-header">
                    <span class="alert-item-title">${alert.resident_name} (${alert.severity})</span>
                    <span class="alert-item-time">${timeStr}</span>
                </div>
                <div class="alert-item-msg">${alert.message}</div>
                ${alert.correlation ? `<div class="alert-item-msg" style="color:var(--color-danger);font-size:11px;margin-top:4px;font-weight:600;">[x] Correlation: ${alert.correlation.slice(0, 120)}...</div>` : ''}
                <div class="alert-item-tag">A2A DISPATCHED</div>
            `;
            timeline.appendChild(item);
        });
    } catch (e) {
        console.error("Error loading alert timeline:", e);
    }
}

async function clearAlertTimeline() {
    if (!confirm("Are you sure you want to clear the A2A alert log history?")) return;
    try {
        await fetch(getApiBaseUrl() + "/api/alerts/clear", { method: "POST" });
        initAlerts();
    } catch (e) {
        console.error(e);
    }
}

// ============================================================
// UTILITIES
// ============================================================

function formatMarkdown(text) {
    if (!text) return "";
    return escapeHtml(text)
        .replace(/\n/g, "<br>")
        .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.*?)\*/g, "<em>$1</em>")
        .replace(/### (.*?)(<br>|$)/g, "<h4 style='font-family:Outfit,sans-serif;font-size:13px;margin:8px 0 4px;color:var(--color-text-primary);'>$1</h4>")
        .replace(/## (.*?)(<br>|$)/g, "<h3 style='font-family:Outfit,sans-serif;font-size:15px;margin:12px 0 6px;color:var(--color-text-primary);'>$1</h3>");
}

function escapeHtml(text) {
    if (!text) return "";
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

document.getElementById('generate-pdf-btn')?.addEventListener('click', async () => { 
    if(!activeResidentId) return; 
    const btn = document.getElementById('generate-pdf-btn'); 
    const origText = btn.innerHTML; 
    btn.innerHTML = 'Generating...'; 
    
    // Open a blank tab immediately to bypass browser popup blocker
    const pdfTab = window.open('about:blank', '_blank');
    
    try { 
        const res = await fetch(getApiBaseUrl() + '/api/reports/generate', { 
            method: 'POST', 
            headers: {'Content-Type': 'application/json'}, 
            body: JSON.stringify({resident_id: activeResidentId}) 
        }); 
        const data = await res.json(); 
        if(data.status === 'success') { 
            // Also attempt to open the URL if it contains one
            const urlMatch = data.message.match(/URL:\s*(.*)/);
            if(urlMatch && urlMatch[1]) {
                let finalUrl = urlMatch[1].trim();
                if(finalUrl.startsWith('/')) {
                    finalUrl = getApiBaseUrl() + finalUrl;
                }
                pdfTab.location.href = finalUrl;
            } else {
                pdfTab.close();
                alert(data.message); 
            }
        } else { 
            pdfTab.close();
            alert('Error: ' + data.detail); 
        } 
    } catch(e) { 
        pdfTab.close();
        alert('Failed to generate PDF: ' + e); 
    } finally { 
        btn.innerHTML = origText; 
    } 
});
