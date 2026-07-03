# ruff: noqa: E501
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD_HTML)


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InferX Live Ops Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #070b16;
      --panel: #101827;
      --panel-2: #0c1322;
      --border: #263244;
      --muted: #94a3b8;
      --text: #e5e7eb;
      --green: #10b981;
      --blue: #60a5fa;
      --orange: #f97316;
      --red: #ef4444;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: radial-gradient(circle at top left, rgba(59,130,246,0.18), transparent 34%), var(--bg);
      color: var(--text);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main { width: min(1320px, calc(100vw - 40px)); margin: 24px auto; }
    header {
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      gap: 16px;
      margin-bottom: 20px;
    }
    h1 { margin: 0; font-size: 34px; letter-spacing: -0.04em; }
    .sub { color: var(--muted); margin-top: 6px; }
    .pill {
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: rgba(16,24,39,0.8);
      color: #cbd5e1;
      font-size: 13px;
    }
    .grid { display: grid; gap: 16px; }
    .metrics { grid-template-columns: repeat(6, 1fr); }
    .two { grid-template-columns: 1.1fr 0.9fr; margin-top: 16px; }
    .card {
      background: linear-gradient(180deg, rgba(17,24,39,0.96), rgba(12,19,34,0.96));
      border: 1px solid var(--border);
      border-radius: 18px;
      box-shadow: 0 18px 50px rgba(0,0,0,0.25);
      overflow: hidden;
    }
    .metric { padding: 18px; min-height: 112px; }
    .label {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .value { margin-top: 12px; font-size: 28px; font-weight: 800; letter-spacing: -0.03em; }
    .hint { margin-top: 8px; color: var(--muted); font-size: 13px; }
    .card h2 { margin: 0; padding: 18px 20px 0; font-size: 18px; }
    .content { padding: 18px 20px 20px; }
    .bar-row { display: grid; grid-template-columns: 130px 1fr 72px; align-items: center; gap: 12px; margin: 12px 0; }
    .bar-label { color: #cbd5e1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .track { height: 14px; background: #1f2937; border-radius: 999px; overflow: hidden; }
    .fill { height: 100%; min-width: 2px; border-radius: 999px; background: linear-gradient(90deg, var(--blue), var(--green)); }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 11px 10px; text-align: left; border-bottom: 1px solid #1f2937; font-size: 14px; }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.08em; }
    tr:last-child td { border-bottom: none; }
    .status { display: inline-flex; align-items: center; gap: 8px; }
    .dot { width: 9px; height: 9px; border-radius: 99px; background: var(--green); }
    .dot.bad { background: var(--red); }
    .score { font-weight: 800; }
    .muted { color: var(--muted); }
    .error { color: #fecaca; }
    @media (max-width: 1100px) {
      .metrics { grid-template-columns: repeat(3, 1fr); }
      .two { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <div>
        <h1>InferX Live Ops</h1>
        <div class="sub">Adaptive routing, cache, and streaming telemetry for the live demo.</div>
      </div>
      <div class="pill" id="last-updated">Waiting for metrics…</div>
    </header>

    <section class="grid metrics">
      <div class="card metric"><div class="label">Requests/sec</div><div class="value" id="rps">—</div><div class="hint">Provider attempts</div></div>
      <div class="card metric"><div class="label">Latency</div><div class="value" id="latency">—</div><div class="hint">Avg provider attempt</div></div>
      <div class="card metric"><div class="label">Error Rate</div><div class="value" id="error-rate">—</div><div class="hint">Provider errors</div></div>
      <div class="card metric"><div class="label">Cache Hit %</div><div class="value" id="cache-hit">—</div><div class="hint">Exact + semantic</div></div>
      <div class="card metric"><div class="label">Streaming</div><div class="value" id="streams">—</div><div class="hint">Active sessions</div></div>
      <div class="card metric"><div class="label">Logged Usage</div><div class="value" id="logged">—</div><div class="hint">Recent DB rows</div></div>
    </section>

    <section class="grid two">
      <div class="card">
        <h2>Provider Usage Split</h2>
        <div class="content" id="provider-split"></div>
      </div>
      <div class="card">
        <h2>Adaptive Provider Scores</h2>
        <div class="content">
          <table>
            <thead>
              <tr>
                <th>Provider</th>
                <th>Score</th>
                <th>Latency</th>
                <th>Error</th>
                <th>Circuit</th>
              </tr>
            </thead>
            <tbody id="score-table"></tbody>
          </table>
        </div>
      </div>
    </section>
  </main>

  <script>
    const state = { previous: null, previousAt: null };

    async function tick() {
      try {
        const [analyticsResponse, metricsResponse] = await Promise.all([
          fetch('/v1/analytics?window_seconds=300', { cache: 'no-store' }),
          fetch('/metrics', { cache: 'no-store' }),
        ]);
        if (!analyticsResponse.ok) throw new Error(`/v1/analytics ${analyticsResponse.status}`);
        if (!metricsResponse.ok) throw new Error(`/metrics ${metricsResponse.status}`);
        const analytics = await analyticsResponse.json();
        const metrics = parsePrometheus(await metricsResponse.text());
        const now = performance.now() / 1000;
        const computed = computeLiveMetrics(metrics, state.previous, now - (state.previousAt || now));
        render(analytics, computed);
        state.previous = metrics;
        state.previousAt = now;
      } catch (error) {
        document.getElementById('last-updated').innerHTML = `<span class="error">${escapeHtml(error.message)}</span>`;
      }
    }

    function parsePrometheus(text) {
      const samples = [];
      for (const line of text.split('\\n')) {
        if (!line || line.startsWith('#')) continue;
        const match = line.match(/^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\\{([^}]*)\\})?\\s+([-+0-9.eE]+)$/);
        if (!match) continue;
        samples.push({
          name: match[1],
          labels: parseLabels(match[2] || ''),
          value: Number(match[3]),
        });
      }
      return samples;
    }

    function parseLabels(raw) {
      const labels = {};
      const pattern = /([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\\\.|[^"])*)"/g;
      let match;
      while ((match = pattern.exec(raw)) !== null) {
        labels[match[1]] = match[2].replace(/\\\\"/g, '"');
      }
      return labels;
    }

    function sumMetric(samples, name, predicate = () => true) {
      return samples
        .filter((sample) => sample.name === name && predicate(sample.labels))
        .reduce((total, sample) => total + sample.value, 0);
    }

    function rate(current, previous, seconds, name, predicate = () => true) {
      if (!previous || seconds <= 0) return null;
      const delta = sumMetric(current, name, predicate) - sumMetric(previous, name, predicate);
      return Math.max(0, delta / seconds);
    }

    function computeLiveMetrics(current, previous, seconds) {
      const totalRate = rate(current, previous, seconds, 'inferx_provider_requests_total');
      const errorRate = rate(current, previous, seconds, 'inferx_provider_requests_total', (labels) => labels.status === 'error');
      const latencySumRate = rate(current, previous, seconds, 'inferx_provider_request_latency_seconds_sum');
      const latencyCountRate = rate(current, previous, seconds, 'inferx_provider_request_latency_seconds_count');
      const cacheHitRate = rate(current, previous, seconds, 'inferx_cache_events_total', (labels) => labels.result === 'hit');
      const cacheTotalRate = rate(current, previous, seconds, 'inferx_cache_events_total');
      const cumulativeTotal = sumMetric(current, 'inferx_provider_requests_total');
      const cumulativeErrors = sumMetric(current, 'inferx_provider_requests_total', (labels) => labels.status === 'error');
      const cumulativeLatencySum = sumMetric(current, 'inferx_provider_request_latency_seconds_sum');
      const cumulativeLatencyCount = sumMetric(current, 'inferx_provider_request_latency_seconds_count');
      const cumulativeCacheHits = sumMetric(current, 'inferx_cache_events_total', (labels) => labels.result === 'hit');
      const cumulativeCacheTotal = sumMetric(current, 'inferx_cache_events_total');

      return {
        rps: totalRate ?? 0,
        latencyMs: latencyCountRate > 0 ? (latencySumRate / latencyCountRate) * 1000 : (cumulativeLatencyCount ? (cumulativeLatencySum / cumulativeLatencyCount) * 1000 : null),
        errorPercent: totalRate > 0 ? (errorRate / totalRate) * 100 : (cumulativeTotal ? (cumulativeErrors / cumulativeTotal) * 100 : 0),
        cacheHitPercent: cacheTotalRate > 0 ? (cacheHitRate / cacheTotalRate) * 100 : (cumulativeCacheTotal ? (cumulativeCacheHits / cumulativeCacheTotal) * 100 : 0),
        activeStreams: sumMetric(current, 'inferx_active_streaming_sessions'),
        providerTotals: providerTotals(current),
      };
    }

    function providerTotals(samples) {
      const totals = new Map();
      for (const sample of samples) {
        if (sample.name !== 'inferx_provider_requests_total') continue;
        const provider = sample.labels.provider || 'unknown';
        totals.set(provider, (totals.get(provider) || 0) + sample.value);
      }
      return [...totals.entries()].sort((a, b) => b[1] - a[1]);
    }

    function render(analytics, metrics) {
      document.getElementById('rps').textContent = metrics.rps.toFixed(2);
      document.getElementById('latency').textContent = metrics.latencyMs === null ? '—' : `${metrics.latencyMs.toFixed(1)}ms`;
      document.getElementById('error-rate').textContent = `${metrics.errorPercent.toFixed(1)}%`;
      document.getElementById('cache-hit').textContent = `${metrics.cacheHitPercent.toFixed(1)}%`;
      document.getElementById('streams').textContent = String(metrics.activeStreams.toFixed(0));
      document.getElementById('logged').textContent = String(analytics.request_count);
      document.getElementById('last-updated').textContent = `Updated ${new Date().toLocaleTimeString()} · ${analytics.window_seconds}s window`;
      renderProviderSplit(metrics.providerTotals, analytics.provider_usage);
      renderScores(analytics.provider_scores);
    }

    function renderProviderSplit(metricTotals, usageRows) {
      const rows = metricTotals.length
        ? metricTotals.map(([provider, count]) => ({ provider, count }))
        : usageRows.map((row) => ({ provider: row.provider, count: row.request_count }));
      const total = rows.reduce((sum, row) => sum + row.count, 0);
      const container = document.getElementById('provider-split');
      if (!rows.length || total === 0) {
        container.innerHTML = '<div class="muted">No provider traffic yet.</div>';
        return;
      }
      container.innerHTML = rows.map((row) => {
        const percent = (row.count / total) * 100;
        return `<div class="bar-row">
          <div class="bar-label">${escapeHtml(row.provider)}</div>
          <div class="track"><div class="fill" style="width:${Math.max(2, percent).toFixed(1)}%"></div></div>
          <div class="muted">${percent.toFixed(1)}%</div>
        </div>`;
      }).join('');
    }

    function renderScores(scores) {
      const body = document.getElementById('score-table');
      if (!scores.length) {
        body.innerHTML = '<tr><td colspan="5" class="muted">Provider scorer has no snapshots yet.</td></tr>';
        return;
      }
      body.innerHTML = scores.map((score) => `
        <tr>
          <td><span class="status"><span class="dot ${score.healthy ? '' : 'bad'}"></span>${escapeHtml(score.provider)}</span></td>
          <td class="score">${Number(score.score).toFixed(2)}</td>
          <td>${score.latency_ms === null ? '—' : `${Number(score.latency_ms).toFixed(1)}ms`}</td>
          <td>${(Number(score.error_rate) * 100).toFixed(1)}%</td>
          <td>${escapeHtml(score.circuit_state)}</td>
        </tr>
      `).join('');
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    tick();
    setInterval(tick, 3000);
  </script>
</body>
</html>
"""
