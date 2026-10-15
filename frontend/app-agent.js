// ====== Agent / Chat ======
let agentHistory = [];

const AGENT_GREETING = '你好！我是跑鞋助手，可以幫你查詢跑鞋資料、分析跑量、推薦新鞋。有什麼想問的嗎？';

// 清空對話（登出/切換帳號時呼叫）：重設上下文陣列 + 還原畫面為初始問候語，
// 避免前一個使用者的對話殘留給下一位（隱私）。
function resetAgentChat() {
  agentHistory = [];
  const container = document.getElementById('agent-messages');
  if (container) {
    container.innerHTML =
      '<div class="agent-message bot"><div class="agent-msg-content">' +
      AGENT_GREETING + '</div></div>';
  }
}

async function loadAgentModels() {
  try {
    const providers = await apiGet('/agent/providers');
    const orProv = providers.find(p => p.id === 'openrouter');
    if (!orProv) return;
    for (const selectId of ['agent-model', 'report-model']) {
      const modelSel = document.getElementById(selectId);
      const previous = modelSel.value;
      modelSel.replaceChildren();
      if (orProv.models.length) {
        orProv.models.forEach((model, index) => {
          const option = document.createElement('option');
          option.value = model.id;
          option.textContent = '#' + (index + 1) + ' ' + model.display;
          modelSel.appendChild(option);
        });
        if (orProv.models.some(model => model.id === previous)) {
          modelSel.value = previous;
        }
      } else {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = '今日沒有可用的熱門免費工具模型';
        modelSel.appendChild(option);
      }
      modelSel.disabled = !orProv.models.length;
    }
  } catch (e) {
    console.error('載入模型清單失敗:', e);
  }
}

async function refreshAgentModels() {
  const btn = document.getElementById('agent-refresh-btn');
  btn.disabled = true;
  btn.textContent = '⏳';
  try {
    await apiPost('/agent/models/refresh', {});
    await loadAgentModels();
  } catch (e) {
    alert('刷新模型列表失敗：' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔄 刷新模型列表';
  }
}

// Allowlisted HTML tags that marked may emit. Anything else (script, iframe,
// svg, event handlers, javascript: URLs, etc.) is stripped to keep LLM output
// from injecting markup.
const MARKDOWN_ALLOWED_TAGS = new Set([
  'p', 'br', 'hr', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'del', 'a',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'div',
]);

function sanitizeMarkdownHtml(raw) {
  const div = document.createElement('div');
  div.innerHTML = raw;
  const scrub = (el) => {
    // Strip event-handler attributes (onclick, onerror, …) from every
    // allowed tag — marked passes raw HTML through unchanged.
    for (const attr of [...el.attributes]) {
      if (/^on/i.test(attr.name)) el.removeAttribute(attr.name);
    }
    if (el.tagName === 'A' && el.href) {
      // Only allow http(s) links; neutralise javascript: etc.
      try {
        const u = new URL(el.getAttribute('href'), window.location.origin);
        if (u.protocol !== 'http:' && u.protocol !== 'https:') {
          el.removeAttribute('href');
        }
      } catch { el.removeAttribute('href'); }
      el.removeAttribute('target');
    }
    el.removeAttribute('style');
  };
  const all = div.querySelectorAll('*');
  for (const el of all) {
    if (!MARKDOWN_ALLOWED_TAGS.has(el.tagName.toLowerCase())) {
      // Replace disallowed elements with their text content.
      const parent = el.parentNode;
      if (parent) parent.replaceChild(document.createTextNode(el.textContent), el);
    } else {
      scrub(el);
    }
  }
  return div.innerHTML;
}

function renderMarkdown(text) {
  if (typeof marked !== 'undefined' && marked.parse) {
    const raw = marked.parse(text, { breaks: true, gfm: true });
    return sanitizeMarkdownHtml(raw);
  }
  // fallback: escape HTML and preserve line breaks
  const esc = text.replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'})[c]);
  return esc.replace(/\n/g, '<br>');
}

function addAgentMessage(role, text) {
  const container = document.getElementById('agent-messages');
  const div = document.createElement('div');
  div.className = 'agent-message ' + role;
  const content = document.createElement('div');
  content.className = 'agent-msg-content';
  if (role === 'bot') {
    content.innerHTML = renderMarkdown(text);
  } else {
    content.textContent = text;
  }
  div.appendChild(content);
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return content;
}

function appendAgentSourceStatus(content, summary, attempted, succeeded) {
  const status = document.createElement('div');
  status.className = 'agent-source-status';
  const web = summary && summary.web;
  const state = web && typeof web.status === 'string'
    ? web.status
    : (succeeded ? 'live' : (attempted ? 'failed' : 'none'));
  const resultCount = web && Number.isInteger(web.result_count) ? web.result_count : 0;
  if (state === 'live') {
    status.classList.add('web-used');
    status.textContent = `🌐 本輪已即時搜尋（${resultCount} 個來源）`;
  } else if (state === 'cached') {
    status.classList.add('web-used');
    status.textContent = `🌐 本輪使用近期網路搜尋快取（${resultCount} 個來源）`;
  } else if (state === 'failed') {
    status.classList.add('web-failed');
    status.textContent = '⚠️ 網路搜尋失敗，本則回答沒有可驗證的即時網路資料';
  } else {
    status.textContent = '○ 本輪不需要網路搜尋';
  }

  const sources = web && Array.isArray(web.sources) ? web.sources : [];
  if (sources.length) {
    const list = document.createElement('div');
    list.className = 'agent-source-list';
    sources.forEach(source => {
      try {
        const url = new URL(source.url);
        if (url.protocol !== 'http:' && url.protocol !== 'https:') return;
        const link = document.createElement('a');
        link.className = 'agent-source-link';
        link.href = url.href;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        const sourceId = document.createElement('span');
        sourceId.className = 'agent-source-id';
        sourceId.textContent = `[${source.id || 'source'}]`;
        link.appendChild(sourceId);
        link.appendChild(document.createTextNode(source.title || source.domain || url.hostname));
        list.appendChild(link);
      } catch {}
    });
    status.appendChild(list);
  }
  content.appendChild(status);
}

function addRetryButton() {
  const container = document.getElementById('agent-messages');
  const btn = document.createElement('div');
  btn.className = 'agent-retry-btn';
  btn.innerHTML = '↻ 重新產生';
  btn.onclick = () => sendAgentMessage(lastUserText);
  container.appendChild(btn);
  container.scrollTop = container.scrollHeight;
}

function setAgentLoading(loading) {
  const btn = document.getElementById('agent-send-btn');
  const input = document.getElementById('agent-input');
  btn.disabled = loading;
  input.disabled = loading;
  if (loading) {
    btn.textContent = '思考中...';
  } else {
    btn.textContent = '送出';
  }
}

let lastUserText = '';
const AGENT_HISTORY_CHAR_BUDGET = 48000;

function agentHistoryForRequest() {
  const selected = [];
  let remaining = AGENT_HISTORY_CHAR_BUDGET;
  for (const turn of agentHistory.slice(-20).reverse()) {
    if (remaining <= 0) break;
    const content = String(turn.content || '').slice(0, 12000);
    if (!content) continue;
    const kept = content.length <= remaining ? content : content.slice(-remaining);
    selected.unshift({ role: turn.role, content: kept });
    remaining -= kept.length;
  }
  return selected;
}

async function sendAgentMessage(retryText) {
  const input = document.getElementById('agent-input');
  const text = retryText || input.value.trim();
  if (!text) return;
  const isRetry = !!retryText;

  // Store for retry
  lastUserText = text;

  // Clear retry buttons from previous failed attempts
  document.querySelectorAll('.agent-retry-btn').forEach(el => el.remove());

  if (!isRetry) {
    // Normal send: add user message, clear input
    addAgentMessage('user', text);
    input.value = '';
  } else {
    // Retry: remove everything after the last user message
    const container = document.getElementById('agent-messages');
    const userMsgs = container.querySelectorAll('.agent-message.user');
    const lastUser = userMsgs[userMsgs.length - 1];
    if (lastUser) {
      while (lastUser.nextElementSibling) {
        lastUser.nextElementSibling.remove();
      }
    }
    // Pop the last failed assistant response from history
    if (agentHistory.length >= 2 && agentHistory[agentHistory.length - 1].role === 'assistant') {
      agentHistory.pop();
    }
  }

  const container = document.getElementById('agent-messages');

  // Create tool status container (hidden until first tool event)
  let toolStatusDiv = null;
  let thinkingDiv = null;
  let webSearchAttempted = false;
  let webSearchSucceeded = false;
  let sourceSummary = null;

  // Create bot message placeholder
  const botDiv = document.createElement('div');
  botDiv.className = 'agent-message bot agent-typing';
  const botContent = document.createElement('div');
  botContent.className = 'agent-msg-content';
  botContent.innerHTML = '';
  botDiv.appendChild(botContent);
  container.appendChild(botDiv);

  setAgentLoading(true);

  const provider = 'openrouter';
  const model = document.getElementById('agent-model').value;

  try {
    const res = await fetch(API_BASE + '/agent/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken,
      },
      body: JSON.stringify({
        user_message: text,
        history: agentHistoryForRequest(),
        provider: provider,
        model: model,
      }),
    });

    if (res.status === 401) {
      clearAuth();
      showLoginView();
      throw new Error('登入已過期，請重新登入。');
    }
    if (!res.ok) {
      let message = `Agent 請求失敗（HTTP ${res.status}）`;
      try {
        const errorBody = await res.json();
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
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = line.slice(6).trim();
        if (!data) continue;

        try {
          const event = JSON.parse(data);
          if (event.type === 'tool') {
            if (event.name === 'web_search') webSearchAttempted = true;
            // Finalize current thinking bubble
            thinkingDiv = null;
            // Create a new tool group if needed (inserted after the thinking bubble)
            if (!toolStatusDiv) {
              toolStatusDiv = document.createElement('div');
              toolStatusDiv.className = 'agent-tools';
              container.insertBefore(toolStatusDiv, botDiv);
            }
            // Use a sequence counter so each tool item has a unique ID
            const seq = toolStatusDiv.children.length;
            const toolItem = document.createElement('div');
            toolItem.className = 'tool-item';
            toolItem.dataset.toolSeq = seq;
            const query = event.name === 'web_search' && event.args && event.args.query
              ? '：' + event.args.query
              : '';
            toolItem.innerHTML = '<span class="tool-icon">🔍</span> <span class="tool-name">' + esc((event.name || '查詢中') + query) + '</span>';
            toolStatusDiv.appendChild(toolItem);
            container.scrollTop = container.scrollHeight;
          } else if (event.type === 'tool_done') {
            if (event.name === 'web_search' && event.ok !== false) webSearchSucceeded = true;
            // 個別工具完成；執行完成不等於成功，搜尋失敗需明確顯示。
            const group = toolStatusDiv;
            if (group) {
              const pending = group.querySelector('.tool-item:not(.done):not(.failed)');
              if (pending) {
                const failed = event.ok === false;
                pending.classList.add(failed ? 'failed' : 'done');
                pending.querySelector('.tool-icon').textContent = failed ? '⚠️' : '✅';
                if (failed) {
                  const detail = document.createElement('span');
                  detail.className = 'tool-detail';
                  detail.textContent = '（' + (event.message || '執行失敗') + '）';
                  pending.appendChild(detail);
                  if (event.error) pending.title = event.error;
                }
              }
            }
          } else if (event.type === 'reasoning_start') {
            // 串流過程中發現 LLM 要呼叫工具 → 把已顯示的文字移到思考氣泡
            const reasoningText = typeof event.text === 'string' ? event.text : fullText;
            if (reasoningText) {
              thinkingDiv = document.createElement('div');
              thinkingDiv.className = 'agent-thinking';
              thinkingDiv.textContent = '💭 ' + reasoningText;
              container.insertBefore(thinkingDiv, botDiv);
              toolStatusDiv = null;
            }
            fullText = '';
            botContent.textContent = '';
          } else if (event.type === 'token') {
            // First token — allow next reasoning round
            thinkingDiv = null;
            fullText += event.text;
            // During streaming, use textContent to avoid broken partial markdown rendering
            botContent.textContent = fullText;
            container.scrollTop = container.scrollHeight;
          } else if (event.type === 'error') {
            fullText += '\n\n⚠️ ' + event.text;
            botContent.textContent = fullText;
          } else if (event.type === 'source_summary') {
            sourceSummary = event;
          }
        } catch (e) {
          console.error('解析 SSE 事件失敗:', e);
        }
      }
    }

    botDiv.classList.remove('agent-typing');
    if (fullText) {
      botContent.innerHTML = renderMarkdown(fullText);
      appendAgentSourceStatus(
        botContent,
        sourceSummary,
        webSearchAttempted,
        webSearchSucceeded,
      );
      if (!isRetry) agentHistory.push({ role: 'user', content: text });
      agentHistory.push({ role: 'assistant', content: fullText });
    } else {
      botContent.textContent = '（模型沒有回應，請再試一次或更換模型。）';
      appendAgentSourceStatus(
        botContent,
        sourceSummary,
        webSearchAttempted,
        webSearchSucceeded,
      );
      if (!isRetry) agentHistory.push({ role: 'user', content: text });
    }
    addRetryButton(); // 不管成功失敗都顯示重試
  } catch (e) {
    const message = e instanceof TypeError
      ? '連線失敗，請確認後端服務已啟動。'
      : (e.message || 'Agent 請求失敗，請稍後再試。');
    botContent.textContent = '⚠️ ' + message;
    botDiv.classList.remove('agent-typing');
    console.error('Agent 請求失敗:', e);
    addRetryButton();
  }

  setAgentLoading(false);
}

