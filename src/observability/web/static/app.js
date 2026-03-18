/* ── WebSocket + live rendering ───────────────────────────────────────── */

const WS_URL   = `ws://${location.host}/ws/events`;
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
      animation: false,
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

  containers.forEach(c => {
    if (!cpuData[c.name]) cpuData[c.name] = [];
    cpuData[c.name].push(parseFloat(c.cpu_pct?.toFixed(1) ?? 0));
    if (cpuData[c.name].length > 20) cpuData[c.name].shift();
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
  cpuChart.update('none');
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
