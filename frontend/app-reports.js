// ── 月報 ──────────────────────────────────────────────────────
// Report request identities (SPEC-109: owned here, the only script that uses them).
let reportLoadRequestId = 0;
let reportLoadController = null;
let reportGenerationRequestId = 0;
registerFeatureReset('monthly-reports', () => {
  reportLoadRequestId += 1;
  reportLoadController?.abort();
  reportLoadController = null;
  reportGenerationRequestId += 1;
  reportGenerationController?.abort();
  reportGenerationController = null;
  document.getElementById('report-content').textContent = '尚未選擇報告。';
  document.getElementById('report-content').classList.remove('is-streaming');
  document.getElementById('report-history').replaceChildren();
  setReportStatus('');
  setReportControlsDisabled(false);
  const button = document.getElementById('generate-report-btn');
  button.disabled = false;
  button.textContent = '產生報告';
});

function previousMonthValue(now = new Date()) {
  // 依服務的台灣日曆（SPEC-093）；當月尚未結束，預設回上個完整月
  const { year, month: currentMonth } = appCalendarDate(now);
  const month = currentMonth - 1; // 0-based
  const prevMonth = month === 0 ? 12 : month;
  const prevYear = month === 0 ? year - 1 : year;
  return prevYear + '-' + String(prevMonth).padStart(2, '0');
}

function formatLocalTimestamp(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value || '');
  return parsed.toLocaleString('zh-TW', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  });
}

function reportMonthLabel(value) {
  const parts = String(value || '').split('-');
  if (parts.length !== 2 || !parts[0] || !parts[1]) return '';
  return parts[0] + '年' + parseInt(parts[1], 10) + '月';
}

function selectedReportMonth() {
  return document.getElementById('report-month').value;
}

function reportMonthParts() {
  const month = selectedReportMonth();
  if (!month) return null;
  return month.split('-').map(Number);
}

function setReportStatus(text, state = 'error') {
  const status = document.getElementById('report-status');
  status.textContent = text || '';
  status.classList.toggle('is-error', Boolean(text) && state === 'error');
}

function renderReport(report) {
  const label = reportMonthLabel(report.year + '-' + String(report.month).padStart(2, '0'));
  document.getElementById('report-title').textContent = '報告內容 — ' + label;
  document.getElementById('report-content').innerHTML = renderMarkdown(report.content_md);
  const modelSelect = document.getElementById('report-model');
  if (report.model && [...modelSelect.options].some(option => option.value === report.model)) {
    modelSelect.value = report.model;
  }
  setReportStatus('已儲存報告 · 模型 ' + (report.model || '—') +
    ' · 更新於 ' + formatLocalTimestamp(report.updated_at), 'success');
}

async function loadReportHistory() {
  const session = captureAuthSession();
  const select = document.getElementById('report-history');
  try {
    const res = await authenticatedFetch(API_BASE + '/reports', { headers: authHeaders() });
    if (!res.ok) return;
    const rows = await readAuthenticatedBody(res);
    if (!isCurrentAuthSession(session)) return;
    select.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '選擇已儲存的月份…';
    select.appendChild(placeholder);
    rows.forEach(row => {
      const value = row.year + '-' + String(row.month).padStart(2, '0');
      const option = document.createElement('option');
      option.value = value;
      option.textContent = reportMonthLabel(value) + '（' + (row.model || 'AI') + '）';
      select.appendChild(option);
    });
  } catch (e) {
    if (e.name === 'AbortError' || !isCurrentAuthSession(session)) return;
    console.error('載入報告歷史失敗:', e);
  }
}

function onReportHistoryChange() {
  const value = document.getElementById('report-history').value;
  if (!value) return;
  document.getElementById('report-month').value = value;
  loadSavedReport();
}

async function loadSavedReport() {
  const parts = reportMonthParts();
  if (!parts) return;
  const requestedMonth = selectedReportMonth();
  const requestId = ++reportLoadRequestId;
  reportLoadController?.abort();
  const controller = new AbortController();
  reportLoadController = controller;
  setReportStatus('');
  const content = document.getElementById('report-content');
  document.getElementById('report-title').textContent = '報告內容 — ' + reportMonthLabel(requestedMonth);
  content.textContent = '載入中…';
  try {
    const res = await authenticatedFetch(API_BASE + '/reports/' + parts[0] + '/' + parts[1], {
      headers: authHeaders(),
      signal: controller.signal,
    });
    if (requestId !== reportLoadRequestId || selectedReportMonth() !== requestedMonth) return;
    if (res.status === 404) {
      content.textContent = '此月份尚無報告，按「產生報告」由 AI 生成。';
      return;
    }
    if (!res.ok) {
      content.textContent = '尚未選擇報告。';
      setReportStatus('讀取報告失敗（HTTP ' + res.status + '）');
      return;
    }
    const report = await readAuthenticatedBody(res);
    if (requestId !== reportLoadRequestId || selectedReportMonth() !== requestedMonth) return;
    renderReport(report);
  } catch (e) {
    if (e.name === 'AbortError' || requestId !== reportLoadRequestId) return;
    console.error('讀取報告失敗:', e);
    content.textContent = '尚未選擇報告。';
    setReportStatus('連線失敗，請確認後端服務已啟動。');
  } finally {
    if (requestId === reportLoadRequestId) reportLoadController = null;
  }
}

function setReportControlsDisabled(disabled) {
  ['report-month', 'report-history', 'report-model'].forEach(id => {
    const element = document.getElementById(id);
    if (element) element.disabled = disabled;
  });
}

async function generateReport() {
  if (reportGenerationController) return;
  const session = captureAuthSession();
  const parts = reportMonthParts();
  if (!parts) {
    setReportStatus('請先選擇報告月份。');
    return;
  }
  const reportModel = document.getElementById('report-model').value;
  if (!reportModel) {
    setReportStatus('目前沒有可用的本日免費模型，請稍後刷新再試。');
    return;
  }
  const report = startReportGeneration(session);
  const { controller } = report;
  try {
    report.content.classList.add('is-streaming');
    const res = await authenticatedFetch(API_BASE + '/reports/generate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken,
      },
      body: JSON.stringify({
        year: parts[0],
        month: parts[1],
        model: reportModel,
      }),
      signal: controller.signal,
    });
    if (!isCurrentReport(report)) return;
    const result = await readJsonEventStream(res, {
      signal: controller.signal,
      isCurrent: () => isCurrentReport(report),
      onEvent: event => handleReportEvent(report, event),
    });
    await finishReportStream(report, result);
  } catch (e) {
    if (e.name === 'AbortError' || report.requestId !== reportGenerationRequestId) return;
    showReportFailure(report, e);
  } finally {
    endReportGeneration(report);
  }
}

// SPEC-114: one report generation's state and steps. A newer generation, a saved-report load or
// another account makes it stale.
function startReportGeneration(session) {
  const requestId = ++reportGenerationRequestId;
  reportLoadRequestId += 1;
  reportLoadController?.abort();
  reportLoadController = null;
  const controller = new AbortController();
  reportGenerationController = controller;
  const btn = document.getElementById('generate-report-btn');
  btn.disabled = true;
  btn.textContent = '產生中...';
  setReportControlsDisabled(true);
  setReportStatus('');
  document.getElementById('report-title').textContent = '報告內容 — ' + reportMonthLabel(selectedReportMonth());
  return { session, requestId, controller, btn, content: document.getElementById('report-content'),
    fullText: '', receivedDone: false, receivedError: false, markdownFrame: null };
}

function isCurrentReport(report) {
  return report.requestId === reportGenerationRequestId && isCurrentAuthSession(report.session);
}

function scheduleReportMarkdown(report) {
  if (report.markdownFrame !== null) return;
  report.markdownFrame = requestAnimationFrame(() => {
    report.markdownFrame = null;
    if (!isCurrentReport(report)) return;
    report.content.innerHTML = renderMarkdown(report.fullText);
  });
}

function handleReportEvent(report, event) {
  if (event.type === 'token') {
    report.fullText += event.text;
    // marked 可以處理尚未完成的 Markdown；每個畫面幀最多重繪一次，
    // 讓標題、清單與表格在串流期間逐步成形而不造成過度重排。
    scheduleReportMarkdown(report);
  } else if (event.type === 'error') {
    report.receivedError = true;
    report.fullText += '\n\n⚠️ ' + event.text;
    scheduleReportMarkdown(report);
    setReportStatus('報告未儲存：' + event.text);
  } else if (event.type === 'done' && !report.receivedError) {
    report.receivedDone = true;
    report.content.innerHTML = renderMarkdown(report.fullText);
    setReportStatus('報告已儲存 · 模型 ' + (event.model || '—') +
      ' · ' + formatLocalTimestamp(event.updated_at), 'success');
  }
}

async function finishReportStream(report, result) {
  if (report.fullText) {
    // 連線中斷時保留已收到的內容，但要明確告知使用者並未儲存。
    report.content.innerHTML = renderMarkdown(report.fullText);
  }
  if (!report.receivedDone && !report.receivedError) {
    setReportStatus('連線在報告儲存前中斷，目前內容不完整且未儲存，請重新產生。');
  }
  if (result.completed) await loadReportHistory();
}

function showReportFailure(report, e) {
  const message = e instanceof TypeError
    ? '連線失敗，請確認後端服務已啟動。'
    : (e.message || '報告請求失敗，請稍後再試。');
  report.content.textContent = (report.fullText ? report.fullText + '\n\n' : '') + '⚠️ ' + message;
  setReportStatus('內容不完整且未確認儲存，請重新載入或產生報告。');
  console.error('報告請求失敗:', e);
}

function endReportGeneration(report) {
  if (report.markdownFrame !== null) cancelAnimationFrame(report.markdownFrame);
  if (report.requestId !== reportGenerationRequestId) return;
  reportGenerationController = null;
  report.content.classList.remove('is-streaming');
  report.btn.disabled = false;
  report.btn.textContent = '產生報告';
  setReportControlsDisabled(false);
}

// SPEC-101: opening the report tab loads the saved reports, only when signed in.
registerPanel('report', { enter: () => {
  if (!authToken) return;
  loadReportHistory();
  loadSavedReport();
} });

// SPEC-113: this feature's delegated UI actions; markup names them with data-click and the like.
registerUiActions({
  click: {
    'generate-report': () => generateReport(),
  },
  change: {
    'load-saved-report': () => loadSavedReport(),
    'report-history': () => onReportHistoryChange(),
  },
});
