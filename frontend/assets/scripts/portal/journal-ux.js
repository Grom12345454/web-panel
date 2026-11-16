/* Lightweight progressive enhancements for technical diagnostics. */
(() => {
  'use strict';
  const report = document.querySelector('[data-audit-copy-feedback]');
  document.addEventListener('click', async (event) => {
    const button = event.target.closest?.('[data-copy-request-id]');
    if (!button) return;
    const value = button.dataset.copyRequestId || '';
    if (!/^[a-zA-Z0-9_.-]{1,64}$/.test(value)) return;
    let copied = false;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
        copied = true;
      }
    } catch (_) { /* Some intranet origins restrict clipboard access. */ }
    if (!copied) {
      const fallback = document.createElement('textarea');
      fallback.value = value;
      fallback.style.cssText = 'position:fixed;left:-9999px;top:0';
      document.body.appendChild(fallback);
      fallback.select();
      try { copied = document.execCommand('copy'); } catch (_) { /* Unsupported */ }
      fallback.remove();
    }
    if (report) report.textContent = copied ? `ID ${value} скопирован` : `ID запроса: ${value}`;
    button.textContent = copied ? 'Скопировано' : 'Выделить ID';
    if (!copied) {
      const selection = window.getSelection();
      const idCode = button.parentElement?.querySelector('code');
      if (idCode && selection) {
        const range = document.createRange();
        range.selectNodeContents(idCode);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }
  });
  document.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
      const search = document.querySelector('#audit-query, #bot-journal-query');
      if (search) { event.preventDefault(); search.focus(); search.select?.(); }
    }
  });
})();

/* Opt-in compact density and non-disruptive live new-record indication. */
(() => {
  'use strict';
  const workspace = document.querySelector('[data-log-workspace]');
  if (!workspace) return;
  const button = workspace.querySelector('[data-log-density]');
  const notice = workspace.querySelector('[data-log-update]');
  const key = 'staff-logs-compact';
  let compact = false;
  try { compact = localStorage.getItem(key) === '1'; } catch (_) { /* private browsing */ }
  function applyDensity() {
    workspace.classList.toggle('pro-log-compact', compact);
    if (button) {
      button.setAttribute('aria-pressed', compact ? 'true' : 'false');
      button.textContent = compact ? 'Обычный вид' : 'Компактный вид';
    }
  }
  button?.addEventListener('click', () => {
    compact = !compact;
    try { localStorage.setItem(key, compact ? '1' : '0'); } catch (_) { /* optional */ }
    applyDensity();
  });
  applyDensity();
  const checkUrl = workspace.dataset.logCheck;
  const baseline = {
    actions: Number(workspace.dataset.lastActions || 0),
    http: Number(workspace.dataset.lastHttp || 0),
  };
  let inFlight = false;
  async function check() {
    if (document.hidden || inFlight || !checkUrl) return;
    inFlight = true;
    try {
      const response = await fetch(checkUrl, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) return;
      const data = await response.json();
      if (data.ok && (Number(data.actions) > baseline.actions || Number(data.http) > baseline.http)) {
        if (notice) notice.hidden = false;
      }
    } catch (_) { /* A temporary network loss must not interrupt investigation. */ }
    finally { inFlight = false; }
  }
  const interval = window.setInterval(check, 45000);
  window.addEventListener('pagehide', () => window.clearInterval(interval), { once: true });
})();


/* Pointer-based 3D tilt for diagnostic cards, disabled on touch and reduced-motion. */
(() => {
  'use strict';
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
  const cards = [...document.querySelectorAll('[data-tilt-card]')];
  if (!cards.length || !window.matchMedia?.('(hover: hover) and (pointer: fine)').matches) return;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  for (const card of cards) {
    let frame = 0;
    const layer = card.querySelector('.pro-depth-card-front') || card;
    function reset() {
      card.classList.remove('is-hovered');
      layer.style.transform = 'rotateX(0deg) rotateY(0deg) translateZ(0)';
    }
    card.addEventListener('pointermove', (event) => {
      const rect = card.getBoundingClientRect();
      const px = (event.clientX - rect.left) / rect.width;
      const py = (event.clientY - rect.top) / rect.height;
      const rotateY = clamp((px - 0.5) * 14, -7, 7);
      const rotateX = clamp((0.5 - py) * 14, -7, 7);
      card.classList.add('is-hovered');
      if (frame) window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(() => {
        layer.style.transform = `rotateX(${rotateX}deg) rotateY(${rotateY}deg) translateZ(10px)`;
      });
    });
    card.addEventListener('pointerleave', reset);
    card.addEventListener('pointercancel', reset);
    card.addEventListener('blur', reset, true);
  }
})();
