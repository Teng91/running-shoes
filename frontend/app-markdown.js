// Untrusted LLM Markdown rendering; independent of chat requests.
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
