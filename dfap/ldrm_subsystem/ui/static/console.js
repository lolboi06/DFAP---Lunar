// Shared console helpers. The token is held in memory and sessionStorage only;
// it is never written to a URL, so it cannot leak through a Referer header or
// a server access log.
const api = {
  token: sessionStorage.getItem('ldrm_token') || '',
  base: '/api/v1/ldrm',
  setToken(value) { this.token = value.trim(); sessionStorage.setItem('ldrm_token', this.token); },
  async call(method, path, body) {
    const response = await fetch(this.base + path, {
      method,
      headers: {
        'Content-Type': 'application/json',
        ...(this.token ? { Authorization: 'Bearer ' + this.token } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await response.text();
    let payload;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = { detail: text }; }
    if (!response.ok) {
      const detail = (payload && (payload.detail || payload.message)) || response.statusText;
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return payload;
  },
  get(p) { return this.call('GET', p); },
  post(p, b) { return this.call('POST', p, b === undefined ? {} : b); },
  put(p, b) { return this.call('PUT', p, b); },
};

function toast(message, kind = '') {
  const host = document.getElementById('toast');
  const node = document.createElement('div');
  node.className = 'msg ' + kind;
  node.textContent = message;
  host.appendChild(node);
  setTimeout(() => node.remove(), 7000);
}

const escapeHtml = (value) =>
  String(value ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function pill(text, kind = '') {
  return `<span class="pill ${kind}">${escapeHtml(text)}</span>`;
}

const STATUS_KIND = {
  PRODUCTION_ACTIVE: 'bad', REVOKED: 'bad', SUSPENDED: 'warn', EXPIRED: 'warn',
  DRAFT: '', CONTRACT_TESTED: 'ok', SECURITY_REVIEWED: 'ok',
  AGENCY_APPROVED: 'ok', PROVIDER_APPROVED: 'ok', SANDBOX_CONFIGURED: 'ok',
};
const ENV_KIND = { MOCK: 'mock', SANDBOX: 'warn', PRODUCTION: 'bad' };

async function renderModeBanners(target) {
  try {
    const health = await fetch('/health').then((r) => r.json());
    const parts = [];
    if (health.demonstration_mode) {
      parts.push('<div class="banner demo">DEMONSTRATION MODE — synthetic providers, cases and identities only. No real provider is contacted.</div>');
    }
    parts.push(health.production_dispatch_enabled
      ? '<div class="banner prod-on">PRODUCTION DISPATCH: ENABLED — every PRODUCTION_ACTIVE integration is live</div>'
      : '<div class="banner prod-off">PRODUCTION DISPATCH: DISABLED</div>');
    target.innerHTML = parts.join('');
  } catch { /* the banner is advisory; its absence must not break the console */ }
}

function tokenBar(onReady) {
  const bar = document.getElementById('tokenbar');
  bar.innerHTML = `
    <input id="token" type="password" placeholder="Bearer token" style="max-width:340px"
           value="${escapeHtml(api.token)}" autocomplete="off">
    <button id="connect" class="primary">Connect</button>`;
  document.getElementById('connect').onclick = () => {
    api.setToken(document.getElementById('token').value);
    onReady();
  };
  if (api.token) onReady();
}
