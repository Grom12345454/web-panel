(() => {
  'use strict';
  const root = document.querySelector('.journal-shell');
  if (!root) return;
  const checkUrl = root.dataset.journalCheck;
  const baseline = Number(root.dataset.journalLatest || 0);
  const status = document.getElementById('journal-check-status');
  const notice = document.getElementById('journal-new');
  const auto = document.getElementById('journal-auto');
  const refresh = () => location.reload();
  document.getElementById('journal-refresh')?.addEventListener('click', refresh);
  document.getElementById('journal-show-new')?.addEventListener('click', refresh);
  let inflight = false;
  async function check() {
    if (!auto?.checked || inflight || document.hidden) return;
    inflight = true;
    try {
      const response = await fetch(checkUrl, { credentials: 'same-origin', cache: 'no-store' });
      if (!response.ok) throw new Error('network');
      const data = await response.json();
      if (!data.ok) throw new Error('invalid');
      if (status) status.textContent = 'Подключено · проверено только что';
      if (Number(data.latest_id) > baseline) {
        if (notice) notice.hidden = false;
        // Never discard search fields or the user's place in a paginated list.
        if (status) status.textContent = 'Есть новые записи';
      }
    } catch (_) {
      if (status) status.textContent = 'Связь с журналом временно недоступна';
    } finally {
      inflight = false;
    }
  }
  const ticker = window.setInterval(check, 20000);
  window.addEventListener('pagehide', () => window.clearInterval(ticker), { once: true });
})();
