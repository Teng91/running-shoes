// ====== Agent / Chat ======
let agentHistory = [];
let agentRequestId = 0;
let agentController = null;
let agentRetryHistory = [];

registerFeatureReset('agent-chat', resetAgentChat);

const AGENT_GREETING = '你好！我是跑鞋助手，可以幫你查詢跑鞋資料、分析跑量、推薦新鞋。有什麼想問的嗎？';
// SPEC-059: completed turns live in this tab's sessionStorage, so a reload (including an
// automatic update) keeps the conversation. Closing the tab, logging out or switching
// account removes them; other tabs never see them.
const AGENT_CHAT_STORAGE_KEY = 'agent-chat';
const AGENT_CHAT_STORED_TURNS = 20;

// 清空對話（登出/切換帳號時呼叫）：重設上下文陣列 + 還原畫面為初始問候語，
// 避免前一個使用者的對話殘留給下一位（隱私）。
function resetAgentChat() {
  agentRequestId += 1;
  agentController?.abort();
  agentController = null;
  lastUserText = '';
  agentHistory = [];
  agentRetryHistory = [];
  saveAgentChat();
  document.getElementById('agent-input').value = '';
  setAgentLoading(false);
  const container = document.getElementById('agent-messages');
  if (container) {
    container.innerHTML =
      '<div class="agent-message bot"><div class="agent-msg-content">' +
      AGENT_GREETING + '</div></div>';
  }
}

function saveAgentChat() {
  try {
    if (!agentHistory.length || !currentUser) sessionStorage.removeItem(AGENT_CHAT_STORAGE_KEY);
    else sessionStorage.setItem(AGENT_CHAT_STORAGE_KEY, JSON.stringify({
      user: currentUser, history: agentHistory.slice(-AGENT_CHAT_STORED_TURNS),
    }));
  } catch {}
}

// Rebuild the saved turns for the same account after a reload; anything else is discarded.
function restoreAgentChat() {
  let saved = null;
  try { saved = JSON.parse(sessionStorage.getItem(AGENT_CHAT_STORAGE_KEY) || 'null'); } catch {}
  const turns = saved && saved.user === currentUser && Array.isArray(saved.history)
    ? saved.history.filter(turn => ['user', 'assistant'].includes(turn?.role) && typeof turn.content === 'string' && turn.content)
    : [];
  if (!turns.length) {
    try { sessionStorage.removeItem(AGENT_CHAT_STORAGE_KEY); } catch {}
    return;
  }
  agentHistory = turns.slice(-AGENT_CHAT_STORED_TURNS);
  turns.forEach(turn => addAgentMessage(turn.role === 'assistant' ? 'bot' : 'user', turn.content));
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

function agentHistoryForRequest(history = agentHistory) {
  const selected = [];
  let remaining = AGENT_HISTORY_CHAR_BUDGET;
  for (const turn of history.slice(-20).reverse()) {
    if (remaining <= 0) break;
    const content = String(turn.content || '').slice(0, 12000);
    if (!content) continue;
    const kept = content.length <= remaining ? content : content.slice(-remaining);
    selected.unshift({ role: turn.role, content: kept });
    remaining -= kept.length;
  }
  return selected;
}

// SPEC-086: free reasoning models think for a while before the first answer token.
// That thinking streams into a block above the answer — live while the model
// thinks, folded to「已思考 N 秒」once it answers or calls a tool — and the answer
// bubble counts the seconds while nothing has arrived yet. Reasoning is untrusted
// model text: it is only ever set as plain text, never rendered or saved.
function agentElapsedSeconds(startedAt, now = Date.now()) {
  return Math.max(0, Math.floor((now - startedAt) / 1000));
}

function agentThinkingLabel(startedAt, now = Date.now()) {
  const seconds = agentElapsedSeconds(startedAt, now);
  return seconds ? `思考中… ${seconds} 秒` : '思考中…';
}

// The time counts from the start of the model round (the request or the end of
// the last tool), not from the first reasoning fragment: free models spend most
// of a round before any reasoning arrives, so the block continues the seconds
// the waiting bubble already showed.
function createAgentReasoning(container, before, startedAt = Date.now(), now = () => Date.now()) {
  const block = document.createElement('details');
  block.className = 'agent-reasoning';
  block.open = true;
  const summary = document.createElement('summary');
  const body = document.createElement('div');
  body.className = 'agent-reasoning-text';
  const text = document.createTextNode('');
  body.appendChild(text);
  block.appendChild(summary);
  block.appendChild(body);
  container.insertBefore(block, before);
  let live = true;
  const view = {
    get live() { return live; },
    append(chunk) {
      text.appendData(chunk);
      if (live) body.scrollTop = body.scrollHeight;
    },
    tick() {
      if (live) summary.textContent = '💭 ' + agentThinkingLabel(startedAt, now());
    },
    finish() {
      if (!live) return;
      live = false;
      block.open = false;
      summary.textContent = `💭 已思考 ${Math.max(1, Math.round((now() - startedAt) / 1000))} 秒`;
    },
  };
  view.tick();
  return view;
}

async function sendAgentMessage(retryText) {
  if (agentController) return;
  const input = document.getElementById('agent-input');
  const text = retryText || input.value.trim();
  if (!text) return;
  const session = captureAuthSession();
  const requestId = ++agentRequestId;
  const controller = new AbortController();
  agentController = controller;
  const isCurrentRequest = () => requestId === agentRequestId && isCurrentAuthSession(session) && !controller.signal.aborted;
  const isRetry = !!retryText;
  const requestHistory = isRetry ? agentRetryHistory.slice() : agentHistory.slice();
  agentRetryHistory = requestHistory.slice();

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
    // A retry replaces the last attempt without duplicating its user turn.
    agentHistory = requestHistory.slice();
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
  let fullText = '';

  // SPEC-086: one reasoning block per model round, and a waiting label in the
  // still-empty answer bubble whenever no live reasoning shows the time.
  let reasoning = null;
  let waitStartedAt = Date.now();
  const waitLabel = document.createElement('span');
  waitLabel.className = 'agent-wait';
  const refreshWait = () => {
    reasoning?.tick();
    if (fullText || reasoning?.live) {
      waitLabel.remove();
      return;
    }
    if (waitLabel.parentNode !== botContent) {
      botContent.textContent = '';
      botContent.appendChild(waitLabel);
    }
    waitLabel.textContent = agentThinkingLabel(waitStartedAt);
  };
  let waitTimer = setInterval(refreshWait, 1000);
  const stopWaiting = () => {
    if (waitTimer !== null) clearInterval(waitTimer);
    waitTimer = null;
    reasoning?.finish();
    waitLabel.remove();
  };
  refreshWait();

  try {
    const res = await authenticatedFetch(API_BASE + '/agent/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken,
      },
      body: JSON.stringify({
        user_message: text,
        history: agentHistoryForRequest(requestHistory),
        provider: provider,
        model: model,
      }),
      signal: controller.signal,
    });
    if (!isCurrentRequest()) return;
    const result = await readJsonEventStream(res, {
      signal: controller.signal, isCurrent: isCurrentRequest,
      onEvent: event => {
        if (event.type === 'thinking') {
          if (typeof event.text !== 'string' || !event.text) return;
          if (!reasoning) {
            reasoning = createAgentReasoning(container, botDiv, waitStartedAt);
            // Later tools belong after this block, not in the group above it.
            toolStatusDiv = null;
          }
          reasoning.append(event.text);
          refreshWait();
          container.scrollTop = container.scrollHeight;
        } else if (event.type === 'tool') {
          reasoning?.finish();
          reasoning = null;
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
          waitStartedAt = Date.now();
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
          reasoning?.finish();
          reasoning = null;
          waitStartedAt = Date.now();
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
          refreshWait();
        } else if (event.type === 'token') {
          // First token — allow next reasoning round
          thinkingDiv = null;
          reasoning?.finish();
          fullText += event.text;
          // During streaming, use textContent to avoid broken partial markdown rendering
          botContent.textContent = fullText;
          container.scrollTop = container.scrollHeight;
        } else if (event.type === 'error') {
          reasoning?.finish();
          fullText += '\n\n⚠️ ' + event.text;
          botContent.textContent = fullText;
        } else if (event.type === 'source_summary') {
          sourceSummary = event;
        }
      },
    });

    if (!isCurrentRequest()) return;
    stopWaiting();
    botDiv.classList.remove('agent-typing');
    if (fullText) {
      botContent.innerHTML = renderMarkdown(fullText);
      appendAgentSourceStatus(
        botContent,
        sourceSummary,
        webSearchAttempted,
        webSearchSucceeded,
      );
      if (result.completed) {
        agentHistory = [...requestHistory, { role: 'user', content: text }, { role: 'assistant', content: fullText }];
        saveAgentChat();
      }
    } else {
      botContent.textContent = '（模型沒有回應，請再試一次或更換模型。）';
      appendAgentSourceStatus(
        botContent,
        sourceSummary,
        webSearchAttempted,
        webSearchSucceeded,
      );
    }
    if (!result.completed && !result.receivedError) {
      const warning = document.createElement('p');
      warning.textContent = '⚠️ 連線中斷，內容不完整，請重新產生。';
      botContent.appendChild(warning);
    }
    addRetryButton(); // 不管成功失敗都顯示重試
  } catch (e) {
    if (e.name === 'AbortError' || !isCurrentRequest()) return;
    stopWaiting();
    const message = e instanceof TypeError
      ? '連線失敗，請確認後端服務已啟動。'
      : (e.message || 'Agent 請求失敗，請稍後再試。');
    botContent.textContent = (fullText ? fullText + '\n\n' : '') + '⚠️ ' + message + (fullText ? '（內容不完整，請重試）' : '');
    botDiv.classList.remove('agent-typing');
    console.error('Agent 請求失敗:', e);
    addRetryButton();
  } finally {
    stopWaiting();
    if (isCurrentRequest()) {
      agentController = null;
      setAgentLoading(false);
    }
  }
}

