/* ── WebSocket + live rendering ───────────────────────────────────────── */

const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL   = `${protocol}//${location.host}/ws/events`;
const MAX_LOGS = 60;

let ws;
let cpuChart;
let cpuData    = {};   // { containerName: [values] }
let cpuLabels  = [];   // timestamps
let wfFailed   = 0;

// ── Chart setup ────────────────────────────────────────────────────────────

function initChart() {
  const ctx = document.getElementById('cpu-chart').getContext('2d');
  cpuChart = new Chart(ctx, {
    type: 'line',
    data: { labels: [], datasets: [] },
    options: {
      animation: { duration: 400 },
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: '#64748b', font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: '#64748b', maxTicksLimit: 8 }, grid: { color: '#1f2d45' } },
        y: { ticks: { color: '#64748b' }, grid: { color: '#1f2d45' },
             min: 0, title: { display: true, text: 'CPU %', color: '#64748b' } }
      }
    }
  });
}

const COLORS = ['#3b82f6','#8b5cf6','#10b981','#f59e0b','#ef4444','#06b6d4'];

function updateCpuChart(containers) {
  const now = new Date().toLocaleTimeString();
  cpuLabels.push(now);
  if (cpuLabels.length > 20) cpuLabels.shift();
  cpuChart.data.labels = [...cpuLabels];

  // Update data map
  containers.forEach(c => {
    if (!cpuData[c.name]) cpuData[c.name] = new Array(cpuLabels.length - 1).fill(0);
    cpuData[c.name].push(parseFloat(c.cpu_pct?.toFixed(1) ?? 0));
    if (cpuData[c.name].length > 20) cpuData[c.name].shift();
  });

  // Handle containers that disappeared
  const currentNames = containers.map(c => c.name);
  Object.keys(cpuData).forEach(name => {
    if (!currentNames.includes(name)) {
        cpuData[name].push(0);
        if (cpuData[name].length > 20) cpuData[name].shift();
    }
  });

  cpuChart.data.datasets = Object.entries(cpuData).map(([name, vals], i) => ({
    label: name,
    data: vals,
    borderColor: COLORS[i % COLORS.length],
    backgroundColor: COLORS[i % COLORS.length] + '22',
    tension: 0.4,
    fill: true,
    pointRadius: 0,
    borderWidth: 2,
  }));
  cpuChart.update();
}

// ── Render helpers ─────────────────────────────────────────────────────────

function renderNodes(nodes) {
  const el = document.getElementById('nodes-grid');
  if (!nodes?.length) { el.innerHTML = '<p class="muted">No node data yet.</p>'; return; }
  el.innerHTML = nodes.map(n => `
    <div class="node-tile node-tile--${n.up ? 'up' : 'down'}">
      <div>
        <div class="node-name">${n.name}</div>
        <div class="node-role">${n.role} · ${n.host}</div>
      </div>
      <span class="node-badge node-badge--${n.up ? 'up' : 'down'}">${n.up ? '● UP' : '○ DOWN'}</span>
    </div>`).join('');
}

function renderWorkflows(temporal) {
  document.getElementById('wf-active').textContent = temporal?.active ?? '—';
  document.getElementById('wf-failed').textContent = temporal?.failed ?? '—';
}

function renderTasks(tasks) {
  const el = document.getElementById('tasks-table');
  if (!tasks?.length) { el.innerHTML = '<p class="muted">No recent tasks</p>'; return; }
  
  const statusMap = {
    '1': 'Running', '2': 'Completed', '3': 'Failed',
    '4': 'Canceled', '5': 'Terminated', '6': 'Continued as new', '7': 'Timed out'
  };

  el.innerHTML = `<table>
    <thead><tr><th style="width: 15%">ID</th><th style="width: 20%">Status</th><th>Description</th><th style="width: 15%">Details</th></tr></thead>
    <tbody>${tasks.map(t => {
      let rawStatus = t.status.toString().replace('WORKFLOW_EXECUTION_STATUS_', '');
      let statusText = statusMap[rawStatus] || (rawStatus.charAt(0).toUpperCase() + rawStatus.slice(1).toLowerCase().replace(/_/g, ' '));
      
      const isUp = rawStatus === 'COMPLETED' || rawStatus === '2';
      const isFailed = rawStatus === 'FAILED' || rawStatus === 'TIMED_OUT' || rawStatus === '3' || rawStatus === '7';
      const cls = isUp ? 'up' : (isFailed ? 'down' : 'pending');
      const action = isFailed ? `<a class="task-link" onclick="openTaskModal('${t.task_id}')" style="color: var(--red);">Failure Msg</a>` : `<a class="task-link" onclick="openTaskModal('${t.task_id}')">View Details</a>`;
      
      return `<tr>
        <td style="font-family: monospace; font-size: 0.85em;">
          <a class="task-link" onclick="openTaskModal('${t.task_id}')" title="${t.task_id}">${t.task_id.substring(0,8)}…</a>
        </td>
        <td><span class="node-badge node-badge--${cls}">${statusText}</span></td>
        <td style="max-width: 300px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${t.description.replace(/"/g, '&quot;')}">${t.description}</td>
        <td>${action}</td>
      </tr>`;
    }).join('')}
    </tbody></table>`;
}

function renderLLM(model_sel) {
  const el   = document.getElementById('llm-providers');
  const list = model_sel?.providers ?? [];
  if (!list.length) { el.innerHTML = '<span class="muted">No providers detected</span>'; return; }
  el.innerHTML = list.map(p => `
    <div class="provider-chip"><div class="provider-dot"></div>${p}</div>`).join('');
}

function renderContainers(containers) {
  const el = document.getElementById('containers-table');
  if (!containers?.length) { el.innerHTML = '<p class="muted">No container data</p>'; return; }
  el.innerHTML = `<table>
    <thead><tr><th>Container</th><th>CPU %</th><th>Mem MB</th></tr></thead>
    <tbody>${containers.map(c => `
      <tr>
        <td>${c.name}</td>
        <td>${(c.cpu_pct ?? 0).toFixed(1)}</td>
        <td>${(c.mem_mb ?? 0).toFixed(0)}</td>
      </tr>`).join('')}
    </tbody></table>`;
}

function renderPerformance(perf) {
  if (!perf) return;
  
  const l1 = perf.l1_redis;
  const l2 = perf.l2_qdrant;
  const l3 = perf.l3_s3;

  const el1 = document.getElementById('perf-l1');
  const el2 = document.getElementById('perf-l2');
  const el3 = document.getElementById('perf-l3');

  if (l1) {
    el1.textContent = l1.latency_ms >= 0 ? `${l1.latency_ms} ms` : 'OFFLINE';
    el1.className = `perf-value ${l1.status === 'online' ? 'up' : 'down'}`;
  }
  if (l2) {
    el2.textContent = l2.latency_ms >= 0 ? `${l2.latency_ms} ms` : 'OFFLINE';
    el2.className = `perf-value ${l2.status === 'online' ? 'up' : 'down'}`;
  }
  if (l3) {
    el3.textContent = l3.latency_ms > 0 ? `${l3.latency_ms} ms` : (l3.status === 'unconfigured' ? '—' : 'OFFLINE');
    el3.className = `perf-value ${l3.status === 'online' ? 'up' : 'unconfigured'}`;
  }
}

function appendLog(event) {
  const feed = document.getElementById('log-feed');
  const ts   = new Date(event.ts).toLocaleTimeString();
  const nodes = (event.nodes ?? []).filter(n => !n.up).map(n => `⬤ ${n.name} DOWN`).join(' ');
  const wf    = event.temporal?.active != null ? `workflows=${event.temporal.active}` : '';
  const text  = [nodes, wf].filter(Boolean).join(' | ') || 'tick OK';
  const div   = document.createElement('div');
  div.className = 'log-entry';
  div.innerHTML = `<span class="log-ts">${ts}</span>${text}`;
  feed.appendChild(div);
  while (feed.children.length > MAX_LOGS) feed.removeChild(feed.firstChild);
  feed.scrollTop = feed.scrollHeight;
}

// ── Main render ────────────────────────────────────────────────────────────

function render(data) {
  renderNodes(data.nodes);
  renderWorkflows(data.temporal);
  renderTasks(data.temporal?.tasks);
  renderLLM(data.model_sel);
  renderContainers(data.containers);
  renderPerformance(data.performance);
  if (data.containers?.length) updateCpuChart(data.containers);
  appendLog(data);
  document.getElementById('last-update').textContent =
    'Updated ' + new Date(data.ts).toLocaleTimeString();
}

// ── WebSocket connection ───────────────────────────────────────────────────

function connect() {
  const indicator = document.getElementById('ws-indicator');
  const label     = document.getElementById('ws-label');

  ws = new WebSocket(WS_URL);

  ws.onopen = () => {
    indicator.className = 'status-dot live';
    label.textContent   = 'Live';
    appendLog({ ts: new Date().toISOString(), temporal: {}, nodes: [], containers: [],
                model_sel: { providers: [] } });
  };

  ws.onmessage = e => {
    try { render(JSON.parse(e.data)); } catch (_) {}
  };

  ws.onclose = () => {
    indicator.className = 'status-dot dead';
    label.textContent   = 'Reconnecting…';
    setTimeout(connect, 3000);
  };

  ws.onerror = () => ws.close();
}

// ── Boot ───────────────────────────────────────────────────────────────────

// ── Modal Handling ─────────────────────────────────────────────────────────

async function openTaskModal(id) {
  const modal = document.getElementById('task-modal');
  const body = document.getElementById('modal-body');
  document.getElementById('modal-title').innerText = 'Task: ' + id;
  body.innerHTML = '<p class="muted">Loading details from Temporal...</p>';
  modal.showModal();

  try {
    const res = await fetch('/api/tasks/' + id);
    const data = await res.json();
    if (data.error) {
      body.innerHTML = `<div class="error-box">Error fetching details: ${data.error}</div>`;
      return;
    }
    
    let html = `
      <p><strong>Status:</strong> <span class="node-badge" style="background: rgba(100,116,139,0.2);">${data.status}</span></p>
      <p><strong>Type:</strong> <span style="font-family: var(--mono);">${data.type}</span></p>
      <p><strong>Started:</strong> ${data.start_time || 'N/A'}</p>
      <p><strong>Closed:</strong> ${data.close_time || 'N/A'}</p>
    `;
    
    if (data.failure_message) {
      html += `<div class="error-box" style="margin-top: 16px;"><strong>Failure Traceback:</strong>\n<pre style="margin-top:8px; white-space: pre-wrap; font-family: var(--mono); font-size: 11px;">${data.failure_message}</pre></div>`;
    }
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = `<div class="error-box">Network Error: ${e.message}</div>`;
  }
}

document.addEventListener('DOMContentLoaded', () => {
  initChart();
  connect();
  
  const modal = document.getElementById('task-modal');
  const closeBtn = document.getElementById('modal-close');
  if(closeBtn && modal) {
    closeBtn.onclick = () => modal.close();
  }
});
