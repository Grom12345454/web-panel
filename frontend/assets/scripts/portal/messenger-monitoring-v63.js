/* Super-admin messenger monitoring: privacy-safe, bounded polling. */
(() => {
  'use strict';
  const root = document.querySelector('[data-messenger-monitoring]');
  if (!root) return;

  const endpoint = root.dataset.snapshotUrl;
  const refreshButton = root.querySelector('[data-mm-refresh]');
  const updatedLabel = root.querySelector('[data-mm-updated]');
  let inFlight = false;
  let lastRefresh = 0;

  const setText = (node, value) => {
    if (node) node.textContent = value == null || value === '' ? '—' : String(value);
  };
  const formatDate = (value) => {
    if (!value) return 'Нет записей';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Нет записей';
    return new Intl.DateTimeFormat('ru-RU', {
      day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: 'UTC'
    }).format(date) + ' UTC';
  };

  async function refresh() {
    if (inFlight || document.visibilityState === 'hidden' || !endpoint) return;
    inFlight = true;
    if (refreshButton) refreshButton.disabled = true;
    try {
      const response = await fetch(endpoint, {
        method: 'GET', credentials: 'same-origin', cache: 'no-store',
        headers: { Accept: 'application/json', 'X-Requested-With': 'XMLHttpRequest' }
      });
      if (response.status === 401 || response.status === 403) {
        window.location.assign('/auth/login');
        return;
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || data.ok !== true || !Array.isArray(data.platforms)) throw new Error('Invalid monitoring response');

      Object.entries(data.totals || {}).forEach(([key, value]) => {
        setText(root.querySelector(`[data-mm-total="${key}"]`), value);
      });
      Object.entries(data.student_summary || {}).forEach(([key, value]) => {
        setText(root.querySelector(`[data-mm-student-total="${key}"]`), value);
      });
      data.platforms.forEach((platform) => {
        const card = root.querySelector(`[data-mm-platform="${platform.platform}"]`);
        if (!card) return;
        setText(card.querySelector('[data-mm-value="events_24h"]'), platform.events_24h);
        setText(card.querySelector('[data-mm-value="success_24h"]'), platform.success_24h);
        setText(card.querySelector('[data-mm-value="errors_24h"]'), platform.errors_24h);
        setText(card.querySelector('[data-mm-value="average_duration_ms"]'), `${platform.average_duration_ms || 0} мс`);
        setText(card.querySelector('[data-mm-value="queue_active"]'), platform.queue_active);
        setText(card.querySelector('[data-mm-value="last_event"]'), formatDate(platform.last_event));
        setText(card.querySelector('[data-mm-value="last_send"]'), formatDate(platform.last_send));
        setText(card.querySelector('[data-mm-queue="blocked"]'), platform.queue?.blocked || 0);
        setText(card.querySelector('[data-mm-queue="failed"]'), platform.queue?.failed || 0);

        const state = card.querySelector('[data-mm-platform-state]');
        const dot = card.querySelector('[data-mm-status-dot]');
        const errors = Number(platform.errors_24h || 0);
        const events = Number(platform.events_24h || 0);
        setText(state, errors ? 'Есть ошибки в журнале' : events ? 'Есть события за 24 ч' : 'Нет записей за 24 ч');
        if (dot) {
          dot.classList.toggle('is-warning', errors > 0);
          dot.classList.toggle('is-active', errors === 0 && events > 0);
          dot.classList.toggle('is-idle', errors === 0 && events === 0);
        }
      });
      setText(updatedLabel, `Обновлено ${formatDate(data.generated_at)}`);
      lastRefresh = Date.now();
      root.dataset.refreshState = 'success';
    } catch (error) {
      root.dataset.refreshState = 'error';
      if (updatedLabel) updatedLabel.textContent = 'Не удалось обновить · показаны последние данные';
      // No recurring console noise; the next scheduled poll will retry.
    } finally {
      inFlight = false;
      if (refreshButton) refreshButton.disabled = false;
    }
  }

  refreshButton?.addEventListener('click', refresh);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && Date.now() - lastRefresh > 5000) refresh();
  });
  refresh();
  window.setInterval(() => {
    if (document.visibilityState === 'visible') refresh();
  }, 45000);
})();
