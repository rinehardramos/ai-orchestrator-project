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
  if ((temporal?.failed ?? 0) > 0) wfFailed += temporal.failed;
  document.getElementById('wf-failed').textContent = wfFailed;
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

document.addEventListener('DOMContentLoaded', () => {
  initChart();
  connect();
});
