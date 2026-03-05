// app.js - Dashboard Frontend Logic

// 接続先の自動判定:
//   FastAPI サーバー（ポート8000）経由の場合 → /api/state
//   Live Server / ファイル直接表示の場合   → projects/latest_state.json を直接読む
const IS_FASTAPI = (location.port === '8000' || location.pathname.startsWith('/'));
const API_URL = IS_FASTAPI && location.port === '8000'
    ? '/api/state'
    : '../projects/latest_state.json';

let lastTurnStr = null;
let lastPhaseStr = null;

// DOM Elements
const statusText = document.getElementById('statusText');
const globalStatus = document.getElementById('globalStatus');
const phaseBadge = document.getElementById('phaseBadge');
const projectBrief = document.getElementById('projectBrief');
const progressFill = document.getElementById('progressFill');
const turnCounter = document.getElementById('turnCounter');
const agentsList = document.getElementById('agentsList');
const logContainer = document.getElementById('logContainer');

async function fetchState() {
    try {
        const response = await fetch(API_URL);
        if (!response.ok) throw new Error('Network response was not ok');
        const data = await response.json();
        updateDashboard(data);
    } catch (error) {
        console.error('Failed to fetch state:', error);
        globalStatus.classList.add('error');
        statusText.textContent = 'API Disconnected';
        document.querySelector('.status-dot').classList.remove('pulsing');
    }
}

function updateDashboard(data) {
    if (data.status === "No active project") return;

    // 1. Header & Status
    globalStatus.classList.remove('error');
    statusText.textContent = data.status || 'Running';
    document.querySelector('.status-dot').classList.add('pulsing');
    
    // 2. Project Info
    projectBrief.textContent = data.project_brief;
    const currentPhase = data.current_phase ? data.current_phase.toUpperCase() : 'IDLE';
    phaseBadge.textContent = 'PHASE: ' + currentPhase;
    
    // Progress Bar (Simple calc based on turns)
    const turn = data.turn || 0;
    const max = data.max_turns || 12;
    const pct = Math.min(100, Math.round((turn / max) * 100));
    progressFill.style.width = `${pct}%`;
    turnCounter.textContent = `${turn} / ${max}`;

    // 3. Agents List
    updateAgents(data.roles, data.current_speaker);

    // 4. Log Update (only if turn or phase changed)
    const currentTurnStr = `${data.current_phase}-${data.turn}`;
    if (currentTurnStr !== lastTurnStr) {
        lastTurnStr = currentTurnStr;
        renderLogs(data.history);
    }
}

function updateAgents(rolesObj, currentSpeakerObj) {
    if (!rolesObj || Object.keys(rolesObj).length === 0) {
        agentsList.innerHTML = '<div class="empty-state">No agents deployed.</div>';
        return;
    }
    
    const currentSpeakerName = currentSpeakerObj ? currentSpeakerObj.name : '';
    
    let html = '';
    for (const [key, role] of Object.entries(rolesObj)) {
        const actualName = typeof role.name === 'object' ? role.name.name : role.name;
        const actualEmoji = typeof role.name === 'object' ? role.name.emoji : role.emoji;
        const isActive = actualName === currentSpeakerName ? 'active' : '';
        html += `
            <div class="agent-card ${isActive}">
                <div class="agent-emoji">${actualEmoji || '🤖'}</div>
                <div class="agent-name">${actualName}</div>
            </div>
        `;
    }
    agentsList.innerHTML = html;
}

function renderLogs(history) {
    if (!history || history.length === 0) {
        logContainer.innerHTML = '<div class="empty-state">Awaiting discussion...</div>';
        return;
    }

    let html = '';
    // Reverse array to show newest at bottom, or just iterate normally
    history.forEach((entry, idx) => {
        const isNew = idx === history.length - 1; // highlight last entry
        html += `
            <div class="log-entry ${isNew ? 'new-entry' : ''}">
                <div class="log-meta">
                    <span class="log-speaker">${typeof entry.speaker === 'object' ? entry.speaker.name : entry.speaker}</span>
                    <span>Turn ${entry.turn}</span>
                </div>
                <div class="log-message">${escapeHtml(entry.message)}</div>
            </div>
        `;
    });
    
    logContainer.innerHTML = html;
    // Scroll to bottom
    logContainer.scrollTop = logContainer.scrollHeight;
}

function escapeHtml(unsafe) {
    return unsafe
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

// Poll every 2 seconds
setInterval(fetchState, 2000);
fetchState(); // initial load
