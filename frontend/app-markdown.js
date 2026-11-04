// Untrusted LLM Markdown rendering; independent of chat requests.
// Allowlisted HTML tags that marked may emit. Anything else (script, iframe,
// svg, event handlers, javascript: URLs, etc.) is stripped to keep LLM output
// from injecting markup.
const MARKDOWN_ALLOWED_TAGS = new Set([
  'p', 'br', 'hr', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'strong', 'em', 'del', 'a',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'span', 'div',
]);

// Attributes are allowlisted too: ids, names and classes from untrusted text
// could clobber globals or reuse application styles.
const MARKDOWN_ALLOWED_ATTRIBUTES = new Set(['href', 'title', 'colspan', 'rowspan', 'align', 'start']);

function sanitizeMarkdownHtml(raw) {
  // Parse in an inert document. Assigning innerHTML on an element owned by the
  // live document starts resource loads (e.g. <img onerror>) before scrubbing.
  const parsed = new DOMParser().parseFromString(String(raw), 'text/html');
  const root = parsed.body;
  const scrub = (el) => {
    for (const attr of [...el.attributes]) {
      if (!MARKDOWN_ALLOWED_ATTRIBUTES.has(attr.name.toLowerCase())) el.removeAttribute(attr.name);
    }
    if (el.hasAttribute('href')) {
      if (el.tagName !== 'A') {
        el.removeAttribute('href');
        return;
      }
      // Only allow http(s) links; neutralise javascript: etc.
      try {
        const u = new URL(el.getAttribute('href'), window.location.origin);
        if (u.protocol !== 'http:' && u.protocol !== 'https:') {
          el.removeAttribute('href');
        } else {
          el.setAttribute('rel', 'noopener noreferrer');
        }
      } catch { el.removeAttribute('href'); }
    }
  };
  for (const el of [...root.querySelectorAll('*')]) {
    if (!el.isConnected) continue;
    if (!MARKDOWN_ALLOWED_TAGS.has(el.tagName.toLowerCase())) {
      // Replace disallowed elements with their text content.
      el.replaceWith(parsed.createTextNode(el.textContent));
    } else {
      scrub(el);
    }
  }
  return root.innerHTML;
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
