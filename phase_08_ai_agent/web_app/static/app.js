/* AI Finance Analyst — Executive Dashboard (bilingual EN/AR, dark/light) */
let currentLogs = '';
let currentView = 'overview';
let dashboardState = null;
let selectedTrendMonths = 6;
let lastSnapshot = null;   // last session snapshot (re-rendered on language change)
let lastMessages = [];     // last chat messages (re-rendered on language change)

const $ = (id) => document.getElementById(id);
const t = (key, vars) => window.I18N.t(key, vars);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatNumber(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return Number(v).toLocaleString(window.I18N.locale(), { minimumFractionDigits: 0, maximumFractionDigits: digits });
}

function formatMoney(v, currency = 'USD', digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return `${formatNumber(v, digits)} ${currency}`;
}

function formatPercent(v, digits = 2) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return `${formatNumber(v, digits)}%`;
}

function formatX(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return '—';
  return `${formatNumber(v, 4)}x`;
}

function monthLabel(monthText) {
  if (!monthText) return '—';
  const [year, month] = monthText.split('-').map(Number);
  const d = new Date(year, month - 1, 1);
  return d.toLocaleDateString(window.I18N.locale(), { month: 'long', year: 'numeric' });
}

// Translate a data value (direction, flow role, analysis mode…) when we know it; otherwise show it as-is.
function tr(prefix, value, fallback) {
  const raw = String(value ?? '').trim();
  if (!raw) return fallback ?? '—';
  const keys = [`${prefix}.${raw}`, `${prefix}.${raw.toLowerCase()}`, `${prefix}.${raw.toUpperCase()}`];
  for (const k of keys) {
    const out = t(k);
    if (out !== k) return out;
  }
  return raw.replaceAll('_', ' ');
}

function renderAnswer(text) {
  let s = escapeHtml(text || '');
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  const lines = s.split(/\n/);
  let out = '';
  let inList = false;
  for (const line of lines) {
    const trimmed = line.trim();
    if (/^[-*]\s+/.test(trimmed)) {
      if (!inList) { out += '<ul dir="auto">'; inList = true; }
      out += `<li>${trimmed.replace(/^[-*]\s+/, '')}</li>`;
    } else {
      if (inList) { out += '</ul>'; inList = false; }
      if (!trimmed) out += '<div class="spacer"></div>';
      else out += `<div dir="auto">${trimmed}</div>`;
    }
  }
  if (inList) out += '</ul>';
  return out;
}

function setLoading(button, loading, labelHtml) {
  button.disabled = loading;
  if (loading) button.innerHTML = labelHtml;
}

function showToast(message) {
  const el = $('toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => el.classList.remove('show'), 2400);
}

function refreshHeader(snapshot) {
  $('modelName').textContent = snapshot.model || '—';
  $('providerName').textContent = snapshot.provider || 'Google';
  $('turnNumber').textContent = snapshot.turn ?? 0;
  const boundary = snapshot.data_boundary || {};
  $('boundaryRange').textContent = boundary.date_from && boundary.date_to
    ? `${boundary.date_from} → ${boundary.date_to}`
    : t('side.unavailable');
  $('analysisModeLabel').textContent = snapshot.analysis_mode
    ? tr('mode', snapshot.analysis_mode)
    : t('chat.mode');
}

function renderMessages(messages) {
  lastMessages = messages || [];
  const feed = $('chatFeed');
  feed.innerHTML = '';
  if (!lastMessages.length) {
    feed.innerHTML = `<div class="empty-state" style="margin:auto;text-align:center;max-width:520px;">${escapeHtml(t('chat.empty'))}</div>`;
    return;
  }
  for (const msg of lastMessages) {
    const wrap = document.createElement('div');
    wrap.className = `message ${msg.role === 'user' ? 'user' : msg.role === 'assistant' ? 'assistant' : 'error'}`;
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.setAttribute('dir', 'auto');
    bubble.innerHTML = msg.role === 'user' ? escapeHtml(msg.content) : renderAnswer(msg.content);
    wrap.appendChild(bubble);
    if (msg.analysis_mode) {
      const meta = document.createElement('div');
      meta.className = 'meta-line';
      meta.textContent = tr('mode', msg.analysis_mode);
      wrap.appendChild(meta);
    }
    feed.appendChild(wrap);
  }
  feed.scrollTop = feed.scrollHeight;
}

function renderKpis(payload) {
  const k = payload.kpis || {};
  const r = payload.ratios || {};
  const c = payload.comparison || {};
  const f = payload.forecast || {};
  const currency = payload.filters?.currency || 'USD';
  const net = Number(k.net_cash_flow);
  const success = Number(r.transaction_success_rate_percentage);
  const fee = Number(r.fee_rate_percentage);
  const forecast = Number(f.forecast_value);
  const trendChange = Number(c.percentage_change);

  const forecastDelta = (Number.isFinite(forecast) && Number.isFinite(net)) ? forecast - net : null;
  const forecastDeltaLabel = forecastDelta == null
    ? t('kpi.fcNA')
    : t('kpi.vsCurrent', { delta: `${forecastDelta >= 0 ? '+' : ''}${formatMoney(forecastDelta, currency)}` });
  const momLabel = (c.percentage_change == null || Number.isNaN(trendChange))
    ? t('kpi.noMom')
    : t('kpi.mom', { pct: `${trendChange >= 0 ? '+' : ''}${formatPercent(trendChange)}` });

  $('kpiGrid').innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">${escapeHtml(t('kpi.net'))}</div>
      <div class="kpi-value ${net < 0 ? 'bad' : 'good'}">${formatMoney(net, currency)}</div>
      <div class="kpi-delta ${trendChange < 0 ? 'bad' : trendChange > 0 ? 'good' : 'neutral'}">${escapeHtml(momLabel)}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">${escapeHtml(t('kpi.inflows'))}</div>
      <div class="kpi-value good">${formatMoney(k.total_inflows, currency)}</div>
      <div class="kpi-meta">${escapeHtml(t('kpi.inflowsMeta'))}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">${escapeHtml(t('kpi.outflows'))}</div>
      <div class="kpi-value ${Number(k.total_outflows) > Number(k.total_inflows) ? 'bad' : 'neutral'}">${formatMoney(k.total_outflows, currency)}</div>
      <div class="kpi-meta">${escapeHtml(t('kpi.outflowsMeta'))}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">${escapeHtml(t('kpi.success'))}</div>
      <div class="kpi-value ${success >= 95 ? 'good' : success >= 90 ? 'warn' : 'bad'}">${formatPercent(success, 3)}</div>
      <div class="kpi-meta">${escapeHtml(t('kpi.successMeta'))}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">${escapeHtml(t('kpi.fee'))}</div>
      <div class="kpi-value ${fee > 10 ? 'warn' : 'good'}">${formatPercent(fee)}</div>
      <div class="kpi-meta">${escapeHtml(t('kpi.feeMeta'))}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">${escapeHtml(t('kpi.forecast'))}</div>
      <div class="kpi-value ${forecast < 0 ? 'warn' : 'good'}">${formatMoney(forecast, currency)}</div>
      <div class="kpi-delta ${forecastDelta != null && forecastDelta >= 0 ? 'good' : 'bad'}">${escapeHtml(forecastDeltaLabel)}</div>
    </div>
  `;
}

function previousMonth(month) {
  if (!month) return null;
  const [year, mon] = month.split('-').map(Number);
  const d = new Date(year, mon - 2, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

function renderHero(payload) {
  const f = payload.filters || {};
  const c = payload.comparison || {};
  const trend = payload.trend || [];
  const currency = f.currency || 'USD';
  const month = f.month;
  const n = trend.length || f.trend_months || 6;
  $('selectedPeriodLabel').textContent = `${currency} · ${monthLabel(month)}`;
  $('selectedPeriodDescription').textContent = t('hero.desc', { n: formatNumber(n, 0) });
  $('currencyChip').textContent = currency;
  $('scopeChip').textContent = t('hero.actualForecast');
  $('modeChip').textContent = trend.length ? t('hero.execDash') : t('hero.verified');
  $('filterStatus').textContent = t('filter.current', { month: monthLabel(month), currency });
  $('trendRangeBadge').textContent = t('trend.months', { n: formatNumber(f.trend_months || trend.length || 6, 0) });
  $('driversSubtitle').textContent = t('drivers.vs', { a: monthLabel(month), b: monthLabel(previousMonth(month)) });
  $('comparisonDirection').textContent = c.direction ? tr('dir', c.direction) : '—';
}

function renderHealth(payload) {
  const k = payload.kpis || {};
  const r = payload.ratios || {};
  const anomalies = Number(payload.anomaly_count || 0);
  const net = Number(k.net_cash_flow);
  const ratio = Number(r.inflow_outflow_ratio);
  const success = Number(r.transaction_success_rate_percentage);
  const failed = Number(r.failed_transaction_rate_percentage);
  const pending = Number(r.pending_transaction_rate_percentage);
  const currency = payload.filters?.currency || 'USD';

  const cards = [
    {
      label: t('health.position'),
      value: net < 0 ? t('health.negative') : t('health.positive'),
      note: t('health.netNote', { v: formatMoney(net, currency) }),
      cls: net < 0 ? 'bad' : 'good',
    },
    {
      label: t('health.ratio'),
      value: formatX(ratio),
      note: ratio < 1 ? t('health.ratioLow') : t('health.ratioOk'),
      cls: ratio < 1 ? 'warn' : 'good',
    },
    {
      label: t('health.success'),
      value: formatPercent(success, 3),
      note: t('health.failedPending', { f: formatPercent(failed), p: formatPercent(pending) }),
      cls: success >= 95 ? 'good' : success >= 90 ? 'warn' : 'bad',
    },
    {
      label: t('health.anomaly'),
      value: anomalies === 0 ? t('health.noneDetected') : t('health.detected', { n: formatNumber(anomalies, 0) }),
      note: t('health.zNote', { t: formatNumber(payload.anomaly_threshold || 3.5, 1) }),
      cls: anomalies === 0 ? 'good' : 'bad',
    },
  ];

  $('healthGrid').innerHTML = cards.map(card => `
    <div class="health-card ${card.cls}">
      <div class="health-label">${escapeHtml(card.label)}</div>
      <div class="health-value">${escapeHtml(card.value)}</div>
      <div class="health-note">${escapeHtml(card.note)}</div>
    </div>
  `).join('');
}

function renderTrend(payload) {
  const data = payload.trend || [];
  const box = $('trendChart');
  if (!data.length) {
    box.innerHTML = `<div class="empty-state">${escapeHtml(t('trend.none'))}</div>`;
    return;
  }
  const currency = payload.filters?.currency || 'USD';
  const width = 980, height = 260;
  const padLeft = 48, padRight = 18, padTop = 18, padBottom = 34;
  const values = data.map(d => Number(d.value || 0));
  const minRaw = Math.min(...values);
  const maxRaw = Math.max(...values);
  const min = Math.min(minRaw, 0);
  const max = Math.max(maxRaw, 0);
  const range = (max - min) || 1;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const x = (i) => padLeft + (data.length === 1 ? plotW / 2 : i * plotW / (data.length - 1));
  const y = (v) => padTop + (max - v) / range * plotH;
  const points = data.map((d, i) => ({ x: x(i), y: y(Number(d.value || 0)), d }));
  const line = points.map(p => `${p.x},${p.y}`).join(' ');
  const baselineY = y(0);
  const area = `${padLeft},${baselineY} ${points.map(p => `${p.x},${p.y}`).join(' ')} ${width - padRight},${baselineY}`;
  const gridVals = [max, (max + min) / 2, min];

  box.innerHTML = `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(t('trend.aria'))}">
      <defs>
        <linearGradient id="areaGradient" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" style="stop-color:var(--accent)" stop-opacity=".35"/>
          <stop offset="100%" style="stop-color:var(--accent)" stop-opacity="0"/>
        </linearGradient>
      </defs>
      ${gridVals.map(v => `<line class="chart-gridline ${Math.abs(v) < 1e-9 ? 'chart-zero' : ''}" x1="${padLeft}" x2="${width - padRight}" y1="${y(v)}" y2="${y(v)}"/><text class="chart-axis-label" x="5" y="${y(v) + 3}">${formatNumber(v, 0)}</text>`).join('')}
      <polygon class="chart-area" points="${area}"/>
      <polyline class="chart-line" points="${line}"/>
      ${points.map(p => `<circle class="chart-point" cx="${p.x}" cy="${p.y}" r="4.2"><title>${escapeHtml(p.d.period)} · ${escapeHtml(formatMoney(p.d.value, currency))}</title></circle><text class="chart-axis-label" x="${p.x}" y="${height - 9}" text-anchor="middle">${escapeHtml(p.d.period)}</text>`).join('')}
    </svg>
    <div class="chart-note"><span>${escapeHtml(t('trend.low', { v: formatMoney(minRaw, currency) }))}</span><span>${escapeHtml(t('trend.high', { v: formatMoney(maxRaw, currency) }))}</span></div>
  `;
}

function renderDrivers(payload) {
  const rows = payload.drivers || [];
  const box = $('driversList');
  if (!rows.length) {
    box.innerHTML = `<div class="empty-state">${escapeHtml(t('drivers.none'))}</div>`;
    return;
  }
  const maxAbs = Math.max(...rows.map(r => Math.abs(Number(r.change || 0))), 1);
  const currency = payload.filters?.currency || 'USD';
  box.innerHTML = rows.slice(0, 8).map(r => {
    const change = Number(r.change || 0);
    const width = Math.min(100, Math.abs(change) / maxAbs * 100);
    const color = change < 0 ? 'var(--bad)' : 'var(--good)';
    const contribution = r.contribution_percentage == null ? '—' : formatPercent(r.contribution_percentage, 2);
    const role = tr('role', r.flow_role || 'OTHER');
    return `
      <div class="driver-row">
        <div class="driver-label">${escapeHtml(window.I18N.translateTxn(r.transaction_type || 'other'))}<span class="driver-role">${escapeHtml(role)}</span></div>
        <div class="driver-bar"><div class="driver-fill" style="width:${width}%;background:${color}"></div></div>
        <div class="driver-value" style="color:${color}">${change >= 0 ? '+' : ''}${escapeHtml(formatMoney(change, currency))}<span class="driver-role">${escapeHtml(t('drivers.contribution', { p: contribution }))}</span></div>
      </div>
    `;
  }).join('');

  const rec = payload.driver_reconciliation || payload.flow_reconciliation;
  if (rec) {
    const cls = rec.status === 'reconciled' ? 'good' : 'warn';
    // Server-provided messages are English; in Arabic mode we show a localized status line instead.
    const msg = (window.I18N.lang === 'ar' || !rec.message)
      ? t('drivers.reconStatus', { s: tr('recon', rec.status || 'unknown') })
      : rec.message;
    box.innerHTML += `<div class="reconciliation-note ${cls}">${escapeHtml(msg)}</div>`;
  }
}

function renderComparison(payload) {
  const c = payload.comparison || {};
  const box = $('comparisonDetails');
  if (!c.period_1 || !c.period_2) {
    box.innerHTML = `<div class="empty-state">${escapeHtml(t('cmp.none'))}</div>`;
    return;
  }
  const currency = payload.filters?.currency || 'USD';
  const p1 = c.period_1, p2 = c.period_2;
  const change = Number(c.absolute_change);
  const pct = Number(c.percentage_change);
  box.innerHTML = `
    <div class="compare-hero">
      <div class="compare-label">${escapeHtml(t('cmp.net'))}</div>
      <div class="compare-values">
        <div><div class="compare-period" dir="ltr">${escapeHtml(p1.date_from)} → ${escapeHtml(p1.date_to)}</div><div class="compare-number">${escapeHtml(formatMoney(p1.value, currency))}</div></div>
        <div class="compare-arrow">→</div>
        <div><div class="compare-period" dir="ltr">${escapeHtml(p2.date_from)} → ${escapeHtml(p2.date_to)}</div><div class="compare-number">${escapeHtml(formatMoney(p2.value, currency))}</div></div>
      </div>
      <div class="compare-change">
        <span>${escapeHtml(t('cmp.abs'))}</span><strong class="${change < 0 ? 'bad' : 'good'}" dir="ltr">${change >= 0 ? '+' : ''}${escapeHtml(formatMoney(change, currency))}</strong>
      </div>
      <div class="compare-change">
        <span>${escapeHtml(t('cmp.pct'))}</span><strong class="${pct < 0 ? 'bad' : 'good'}" dir="ltr">${pct >= 0 ? '+' : ''}${escapeHtml(formatPercent(pct))}</strong>
      </div>
    </div>
  `;
}

function renderRisk(payload) {
  const rows = payload.anomalies || [];
  const count = Number(payload.anomaly_count || 0);
  const observations = Number(payload.anomaly_observation_count || 0);
  $('anomalyBadge').textContent = t(count === 1 ? 'risk.badge.one' : 'risk.badge.many', { n: formatNumber(count, 0) });
  const box = $('riskDetails');
  box.innerHTML = `
    <div class="risk-summary">
      <div class="risk-stat"><span>${escapeHtml(t('risk.obs'))}</span><strong>${formatNumber(observations, 0)}</strong></div>
      <div class="risk-stat"><span>${escapeHtml(t('risk.anom'))}</span><strong class="${count ? 'bad' : 'good'}">${formatNumber(count, 0)}</strong></div>
      <div class="risk-stat"><span>${escapeHtml(t('risk.thr'))}</span><strong>${formatNumber(payload.anomaly_threshold || 3.5, 1)}</strong></div>
    </div>
  `;
  if (!rows.length) {
    box.innerHTML += `<div class="anomaly-empty"><strong>${escapeHtml(t('risk.emptyTitle'))}</strong><p>${escapeHtml(t('risk.emptyBody'))}</p></div>`;
    return;
  }
  const table = rows.slice(0, 15).map(r => `<tr><td dir="ltr">${escapeHtml(r.business_date)}</td><td>${escapeHtml(r.currency)}</td><td dir="ltr">${escapeHtml(formatNumber(r.observed_value))}</td><td dir="ltr">${escapeHtml(formatNumber(r.modified_z_score, 3))}</td><td>${escapeHtml(r.direction ? tr('dir', r.direction) : '')}</td></tr>`).join('');
  box.innerHTML += `<table class="anomaly-table"><thead><tr><th>${escapeHtml(t('risk.date'))}</th><th>${escapeHtml(t('risk.ccy'))}</th><th>${escapeHtml(t('risk.observed'))}</th><th>${escapeHtml(t('risk.z'))}</th><th>${escapeHtml(t('risk.dir'))}</th></tr></thead><tbody>${table}</tbody></table>`;
}

function renderForecast(payload) {
  const f = payload.forecast || {};
  const box = $('forecastDetails');
  if (!f || f.status !== 'success') {
    box.innerHTML = `<div class="empty-state">${escapeHtml(t('fc.none'))}</div>`;
    return;
  }
  const currency = f.currency || payload.filters?.currency || 'USD';
  const current = Number(payload.kpis?.net_cash_flow);
  const forecastValue = Number(f.forecast_value);
  const delta = Number.isFinite(current) && Number.isFinite(forecastValue) ? forecastValue - current : null;
  const history = (f.historical_periods || []).slice(-3).map(x => `
    <div class="history-box"><div class="period">${escapeHtml(x.period)}</div><div class="value">${escapeHtml(formatMoney(x.value, currency))}</div></div>
  `).join('');
  const deltaLine = delta == null ? '' : `<div class="kpi-delta ${delta >= 0 ? 'good' : 'bad'}">${escapeHtml(t(delta >= 0 ? 'fc.higher' : 'fc.lower', { v: formatMoney(Math.abs(delta), currency) }))}</div>`;
  box.innerHTML = `
    <div class="forecast-hero">
      <div class="forecast-period-label">${escapeHtml(monthLabel(String(f.forecast_period || '').slice(0, 7)))}</div>
      <div class="forecast-value ${forecastValue < 0 ? 'bad' : 'good'}">${escapeHtml(formatMoney(forecastValue, currency))}</div>
      <div class="forecast-meta">${escapeHtml(t('fc.meta', { method: f.method || 'Trailing Moving Average', n: formatNumber(f.lookback_months ?? 3, 0) }))}</div>
      ${deltaLine}
    </div>
    <div class="forecast-history">${history || `<div class="empty-state">${escapeHtml(t('fc.noHistory'))}</div>`}</div>
  `;
}

function renderSuggestions(snapshot) {
  const fallback = [t('sug.1'), t('sug.2'), t('sug.3'), t('sug.4')];
  let suggestions = snapshot.suggestions || [];
  // Agent suggestions come back in the language the agent answered with; in Arabic mode keep only Arabic ones.
  if (window.I18N.lang === 'ar') suggestions = suggestions.filter(s => /[\u0600-\u06FF]/.test(String(s)));
  const items = suggestions.length ? suggestions.slice(0, 4) : fallback;
  document.querySelectorAll('#suggestionStrip .suggestion').forEach((btn, i) => {
    btn.textContent = items[i] || '';
    btn.dataset.question = items[i] || '';
    btn.classList.toggle('hidden', !items[i]);
  });
}

function renderDashboard(snapshot) {
  lastSnapshot = snapshot || lastSnapshot;
  snapshot = lastSnapshot || {};
  dashboardState = snapshot.dashboard || null;
  refreshHeader(snapshot);
  renderSuggestions(snapshot);
  if (!dashboardState || !Object.keys(dashboardState).length) return;
  renderHero(dashboardState);
  renderKpis(dashboardState);
  renderHealth(dashboardState);
  renderTrend(dashboardState);
  renderDrivers(dashboardState);
  renderComparison(dashboardState);
  renderRisk(dashboardState);
  renderForecast(dashboardState);

  $('currencySelect').value = dashboardState.filters?.currency || 'USD';
  $('monthSelect').value = dashboardState.filters?.month || '';
  selectedTrendMonths = Number(dashboardState.filters?.trend_months || 6);
  document.querySelectorAll('#trendSelector button').forEach(btn => {
    btn.classList.toggle('active', Number(btn.dataset.months) === selectedTrendMonths);
  });
}

async function refreshDashboard() {
  const currency = $('currencySelect').value;
  const month = $('monthSelect').value || '';
  const status = $('filterStatus');
  const button = $('applyFilterBtn');
  setLoading(button, true, escapeHtml(t('common.loading')));
  status.textContent = t('filter.refreshing');
  try {
    const params = new URLSearchParams({ currency, trend_months: String(selectedTrendMonths) });
    if (month) params.set('month', month);
    const response = await fetch(`/api/dashboard?${params.toString()}`);
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Dashboard refresh failed');
    dashboardState = data.dashboard;
    renderDashboard(data.session || { dashboard: data.dashboard, data_boundary: data.dashboard.available_data, model: '—', provider: 'Google', turn: 0, suggestions: [] });
    showToast(t('toast.refreshed'));
  } catch (error) {
    status.textContent = t('filter.failed');
    showToast(error.message || t('toast.refreshFail'));
  } finally {
    setLoading(button, false);
    button.textContent = t('filter.apply');
  }
}

async function loadSession() {
  const response = await fetch('/api/session');
  const data = await response.json();
  renderMessages(data.messages || []);
  renderDashboard(data);
}

function sendButtonHtml() {
  return `<span>${escapeHtml(t('chat.send'))}</span> <span>↵</span>`;
}

async function sendQuestion(questionOverride = null) {
  const input = $('questionInput');
  const btn = $('sendBtn');
  const question = (questionOverride ?? input.value).trim();
  if (!question) return;
  btn.disabled = true;
  btn.innerHTML = escapeHtml(t('chat.analyzing'));
  if (!questionOverride) input.value = '';
  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // `lang` tells the Copilot which language to answer in (follows the UI language).
      body: JSON.stringify({ question, lang: window.I18N.lang }),
    });
    const data = await response.json();
    currentLogs = data.logs || '';
    if (!data.ok) throw new Error(data.error || 'Request failed');
    renderMessages(data.messages || []);
    renderDashboard(data.session || {});
    showToast(t('toast.done'));
  } catch (error) {
    showToast(error.message || t('toast.fail'));
  } finally {
    btn.disabled = false;
    btn.innerHTML = sendButtonHtml();
    input.focus();
  }
}

async function resetSession() {
  if (!confirm(t('confirm.clear'))) return;
  try {
    const response = await fetch('/api/reset', { method: 'POST' });
    const data = await response.json();
    currentLogs = '';
    renderMessages([]);
    renderDashboard(data.session || {});
    showToast(t('toast.cleared'));
  } catch (error) {
    showToast(error.message || t('toast.clearFail'));
  }
}

function activateView(name) {
  currentView = name;
  document.querySelectorAll('.nav-item').forEach(btn => btn.classList.toggle('active', btn.dataset.view === name));
  const panel = document.querySelector(`[data-panel="${name}"]`) || document.querySelector('.hero-summary');
  if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function openLog() {
  $('logContent').textContent = currentLogs || t('log.empty');
  $('logModal').classList.remove('hidden');
}

/* ---------- Language & theme ---------- */
function rerenderForLanguage() {
  window.I18N.applyStatic();
  renderMessages(lastMessages);
  if (lastSnapshot) renderDashboard(lastSnapshot);
  else renderSuggestions({});
  // re-render the trend selector labels & send button (static texts handled by applyStatic)
  $('sendBtn').innerHTML = sendButtonHtml();
  const langChip = $('languageEngineChip');
  if (langChip) langChip.textContent = t('chat.bilingual');
}

function toggleLanguage() {
  const next = window.I18N.lang === 'ar' ? 'en' : 'ar';
  window.I18N.setLang(next);
  rerenderForLanguage();
  showToast(t(next === 'ar' ? 'toast.langAr' : 'toast.langEn'));
}

function toggleTheme() {
  const next = window.I18N.theme === 'dark' ? 'light' : 'dark';
  window.I18N.setTheme(next);
  showToast(t(next === 'dark' ? 'toast.themeDark' : 'toast.themeLight'));
}

function init() {
  window.I18N.applyStatic();
  const langChip = $('languageEngineChip');
  if (langChip) langChip.textContent = t('chat.bilingual');
  renderSuggestions({});
  renderMessages([]);

  document.querySelectorAll('.nav-item').forEach(btn => btn.addEventListener('click', () => activateView(btn.dataset.view)));
  document.querySelectorAll('#trendSelector button').forEach(btn => btn.addEventListener('click', () => {
    selectedTrendMonths = Number(btn.dataset.months);
    document.querySelectorAll('#trendSelector button').forEach(x => x.classList.toggle('active', x === btn));
  }));
  $('applyFilterBtn').addEventListener('click', refreshDashboard);
  $('refreshDashboardBtn').addEventListener('click', refreshDashboard);
  $('sendBtn').addEventListener('click', () => sendQuestion());
  $('questionInput').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      sendQuestion();
    }
  });
  $('newAnalysisBtn').addEventListener('click', resetSession);
  $('resetBtn').addEventListener('click', resetSession);
  $('scrollBottomBtn').addEventListener('click', () => $('chatFeed').scrollTo({ top: $('chatFeed').scrollHeight, behavior: 'smooth' }));
  $('suggestionsBtn').addEventListener('click', () => $('suggestionStrip').scrollIntoView({ behavior: 'smooth', block: 'center' }));
  $('showLogsBtn').addEventListener('click', openLog);
  $('closeLogBtn').addEventListener('click', () => $('logModal').classList.add('hidden'));
  $('logBackdrop').addEventListener('click', () => $('logModal').classList.add('hidden'));
  $('langBtn').addEventListener('click', toggleLanguage);
  $('themeBtn').addEventListener('click', toggleTheme);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') $('logModal').classList.add('hidden'); });
  $('suggestionStrip').addEventListener('click', (event) => {
    const button = event.target.closest('.suggestion');
    if (!button || !button.dataset.question) return;
    sendQuestion(button.dataset.question);
  });
  loadSession().catch(() => showToast(t('toast.loadFail')));
}

document.addEventListener('DOMContentLoaded', init);
