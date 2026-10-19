// ── 月報 ──────────────────────────────────────────────────────

function previousMonthValue(now = new Date()) {
  const year = now.getFullYear();
  const month = now.getMonth(); // 0-based；當月尚未結束，預設回上個完整月
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

function setReportStatus(text) {
  document.getElementById('report-status').textContent = text || '';
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
    ' · 更新於 ' + (report.updated_at || '').replace('T', ' ').slice(0, 16));
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
  const btn = document.getElementById('generate-report-btn');
  const content = document.getElementById('report-content');
  const requestedMonth = selectedReportMonth();
  const requestId = ++reportGenerationRequestId;
  reportLoadRequestId += 1;
  reportLoadController?.abort();
  reportLoadController = null;
  const controller = new AbortController();
  reportGenerationController = controller;
  btn.disabled = true;
  btn.textContent = '產生中...';
  setReportControlsDisabled(true);
  setReportStatus('');
  document.getElementById('report-title').textContent = '報告內容 — ' + reportMonthLabel(requestedMonth);
  let fullText = '';
  let receivedDone = false;
  let receivedError = false;
  let markdownFrame = null;

  const scheduleMarkdownRender = () => {
    if (markdownFrame !== null) return;
    markdownFrame = requestAnimationFrame(() => {
      markdownFrame = null;
      if (requestId !== reportGenerationRequestId || !isCurrentAuthSession(session)) return;
      content.innerHTML = renderMarkdown(fullText);
    });
  };

  try {
    content.classList.add('is-streaming');
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
    if (requestId !== reportGenerationRequestId || !isCurrentAuthSession(session)) return;
    if (!res.ok) {
      let message = '報告請求失敗（HTTP ' + res.status + '）';
      try {
        const errorBody = await readAuthenticatedBody(res);
        if (typeof errorBody.detail === 'string') {
          message = errorBody.detail;
        } else if (Array.isArray(errorBody.detail)) {
          message = errorBody.detail.map(item => item.msg || String(item)).join('；');
        }
      } catch {}
      throw new Error(message);
    }
    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('text/event-stream') || !res.body) {
      throw new Error('伺服器回傳了非預期格式，請稍後再試。');
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const handleSseLine = (line) => {
      if (requestId !== reportGenerationRequestId) return;
      if (!line.startsWith('data: ')) return;
      const data = line.slice(6).trim();
      if (!data) return;
      try {
        const event = JSON.parse(data);
        if (event.type === 'token') {
          fullText += event.text;
          // marked 可以處理尚未完成的 Markdown；每個畫面幀最多重繪一次，
          // 讓標題、清單與表格在串流期間逐步成形而不造成過度重排。
          scheduleMarkdownRender();
        } else if (event.type === 'error') {
          receivedError = true;
          fullText += '\n\n⚠️ ' + event.text;
          scheduleMarkdownRender();
          setReportStatus('報告未儲存：' + event.text);
        } else if (event.type === 'done') {
          receivedDone = true;
          content.innerHTML = renderMarkdown(fullText);
          setReportStatus('報告已儲存 · 模型 ' + (event.model || '—') +
            ' · ' + formatLocalTimestamp(event.updated_at));
        }
      } catch (e) {
        console.error('解析 SSE 事件失敗:', e);
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (requestId !== reportGenerationRequestId || !isCurrentAuthSession(session)) return;
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      lines.forEach(handleSseLine);
    }
    // Flush any bytes held by TextDecoder (for example, a split UTF-8 code point)
    // and process a final SSE line even if the connection omitted its trailing newline.
    buffer += decoder.decode();
    if (buffer) handleSseLine(buffer);
    if (fullText) {
      // 連線中斷時保留已收到的內容，但要明確告知使用者並未儲存。
      content.innerHTML = renderMarkdown(fullText);
    }
    if (!receivedDone && !receivedError) {
      setReportStatus('連線在報告儲存前中斷，目前內容不完整且未儲存，請重新產生。');
    }
    await loadReportHistory();
  } catch (e) {
    if (e.name === 'AbortError' || requestId !== reportGenerationRequestId) return;
    const message = e instanceof TypeError
      ? '連線失敗，請確認後端服務已啟動。'
      : (e.message || '報告請求失敗，請稍後再試。');
    content.textContent = '⚠️ ' + message;
    console.error('報告請求失敗:', e);
  } finally {
    if (markdownFrame !== null) cancelAnimationFrame(markdownFrame);
    if (requestId !== reportGenerationRequestId) return;
    reportGenerationController = null;
    content.classList.remove('is-streaming');
    btn.disabled = false;
    btn.textContent = '產生報告';
    setReportControlsDisabled(false);
  }
}

