/* Social Money — Global JS */

// ── Brand Progress Counter (spells "SOCIAL OPTIMIZE" as a job progresses) ─────
const SO_BRAND = 'SOCIAL OPTIMIZE';

function soBrandCounterHtml(pct) {
  pct = Math.max(0, Math.min(100, Math.round(pct || 0)));
  const total = SO_BRAND.length;
  const revealed = Math.min(total, Math.round((pct / 100) * total));
  let html = '';
  for (let i = 0; i < total; i++) {
    const ch = SO_BRAND[i];
    if (ch === ' ') { html += '<span class="so-brand-space">&nbsp;</span>'; continue; }
    html += '<span class="so-brand-letter' + (i < revealed ? ' revealed' : '') + '">' + ch + '</span>';
  }
  html += '<span class="so-brand-pct">' + pct + '%</span>';
  return html;
}

// Renders the brand counter into el (a DOM element or element id).
function soBrandCounterRender(el, pct) {
  const node = typeof el === 'string' ? document.getElementById(el) : el;
  if (node) node.innerHTML = soBrandCounterHtml(pct);
}

// ── Toast Notifications ───────────────────────────────────────────────────────
function toast(type, title, msg = '') {
  const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
  const container = document.getElementById('toastContainer');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `
    <div class="toast-icon">${icons[type] || 'ℹ️'}</div>
    <div class="toast-body">
      <div class="toast-title">${title}</div>
      ${msg ? `<div class="toast-msg">${msg}</div>` : ''}
    </div>
  `;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ── Modal Helpers ─────────────────────────────────────────────────────────────
function openModal(id) {
  document.getElementById(id).style.display = 'flex';
}

function closeModal(id) {
  document.getElementById(id).style.display = 'none';
}

function closeModalOutside(event, id) {
  if (event.target === document.getElementById(id)) closeModal(id);
}

// ── API Status Checker ────────────────────────────────────────────────────────
async function checkApiStatus() {
  try {
    const resp = await fetch('/api/settings/check');
    const data = await resp.json();
    const dot = document.getElementById('api-dot');
    const txt = document.getElementById('api-status-text');
    if (!dot || !txt) return;

    const allOk = Object.values(data).every(Boolean);
    const anyOk = Object.values(data).some(Boolean);

    if (allOk) {
      dot.className = 'status-dot green';
      txt.textContent = 'All APIs ready';
    } else if (anyOk) {
      dot.className = 'status-dot yellow';
      const missing = Object.entries(data).filter(([,v]) => !v).map(([k]) => k);
      txt.textContent = `${missing.length} keys missing`;
    } else {
      dot.className = 'status-dot red';
      txt.textContent = 'No API keys set';
    }
  } catch (_) {}
}

// ── Keyboard Shortcuts ────────────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay').forEach(m => m.style.display = 'none');
  }
  // Ctrl+N = New video
  if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
    e.preventDefault();
    window.location.href = '/create';
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkApiStatus();
});
