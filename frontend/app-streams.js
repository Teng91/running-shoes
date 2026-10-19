// Shared authenticated JSON/SSE transport. Features own only event presentation.
async function readJsonEventStream(response, { signal, isCurrent = () => true, onEvent }) {
  const session = authenticatedResponses.get(response);
  const guard = () => {
    requireAuthSession(session);
    if (signal?.aborted || !isCurrent()) throw new DOMException('串流已取消', 'AbortError');
  };
  guard();
  if (!response.ok) {
    const error = await readAuthenticatedError(response);
    guard();
    const detail = Array.isArray(error.detail)
      ? error.detail.map(item => item.msg || String(item)).join('；') : error.detail;
    throw new Error(typeof detail === 'string' ? detail : `請求失敗（HTTP ${response.status}）`);
  }
  if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) {
    throw new Error('伺服器回傳了非預期格式，請稍後再試。');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '', dataLines = [];
  let receivedDone = false, receivedError = false;
  const cancel = () => { reader.cancel().catch(() => {}); };
  signal?.addEventListener('abort', cancel, { once: true });
  const dispatch = () => {
    if (!dataLines.length) return;
    guard();
    let event;
    try { event = JSON.parse(dataLines.join('\n')); }
    catch { throw new Error('串流資料格式錯誤，內容可能不完整，請重試。'); }
    dataLines = [];
    if (!event || typeof event !== 'object') throw new Error('串流事件格式錯誤，請重試。');
    if (event.type === 'done') receivedDone = true;
    if (event.type === 'error') receivedError = true;
    onEvent(event);
  };
  const handleLine = line => {
    if (!line) dispatch();
    else if (line === 'data') dataLines.push('');
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
  };
  try {
    while (!receivedDone) {
      const { done, value } = await reader.read();
      guard();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let match;
      // A CR at a chunk boundary may be the first half of CRLF.
      while (!receivedDone && (match = /\r\n|\n|\r(?!$)/.exec(buffer))) {
        handleLine(buffer.slice(0, match.index));
        buffer = buffer.slice(match.index + match[0].length);
      }
      if (done) {
        // Keep compatibility with responses whose final event lacks a newline.
        if (!receivedDone && buffer) handleLine(buffer.replace(/\r$/, ''));
        if (!receivedDone) dispatch();
        break;
      }
    }
    return { completed: receivedDone && !receivedError, receivedDone, receivedError };
  } finally {
    signal?.removeEventListener('abort', cancel);
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
