(() => {
  'use strict';

  const root = document.querySelector('[data-summary-url]');
  if (!root) return;

  const endpoint = root.dataset.summaryUrl;
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const visibleInterval = 45_000;
  const hiddenInterval = 120_000;
  let timer = 0;
  let activeController = null;
  let inFlight = false;
  let stopped = false;

  const updateTotals = (totals) => {
    const values = {
      ...totals,
      events_total: Number(totals.event_signups || 0) + Number(totals.declines || 0),
    };
    document.querySelectorAll('[data-live-total]').forEach((node) => {
      const next = String(values[node.dataset.liveTotal] ?? 0);
      if (node.textContent.trim() === next) return;
      node.textContent = next;
      if (!reduceMotion) {
        node.classList.remove('live-value-changed');
        void node.offsetWidth;
        node.classList.add('live-value-changed');
      }
    });
  };

  const ensureEmptyState = (key, list) => {
    const panel = list.closest('.bot-panel');
    if (!panel) return null;
    let empty = panel.querySelector('.bot-empty');
    if (empty) return empty;

    empty = document.createElement('div');
    empty.className = 'bot-empty';
    const icon = document.createElement('span');
    icon.textContent = '◌';
    const title = document.createElement('strong');
    title.textContent = key === 'directions' ? 'Заявок пока нет' : 'Записей пока нет';
    const message = document.createElement('p');
    message.textContent = key === 'directions'
      ? 'Заявки появятся после выбора направления студентом в боте или личном кабинете.'
      : 'Когда студенты запишутся на даты мероприятий, статистика появится здесь.';
    empty.append(icon, title, message);
    panel.insertBefore(empty, list);
    return empty;
  };

  const renderRanking = (key, values, isQuota) => {
    const list = document.querySelector(`[data-live-ranking="${key}"]`);
    if (!list || !Array.isArray(values)) return;

    const empty = ensureEmptyState(key, list);
    const hasValues = values.length > 0;
    list.hidden = !hasValues;
    if (empty) empty.hidden = hasValues;

    if (!hasValues) {
      list.replaceChildren();
      return;
    }

    const max = Math.max(1, ...values.map((item) => Number(item.count || 0)));
    const fragment = document.createDocumentFragment();
    values.forEach((item, index) => {
      const row = document.createElement('div');
      row.className = 'bot-ranked-item';
      const top = document.createElement('div');
      top.className = 'bot-ranked-top';
      const label = document.createElement('span');
      label.textContent = `${String(index + 1).padStart(2, '0')} · ${item.name || 'Без названия'}`;
      const count = document.createElement('strong');
      count.textContent = String(item.count ?? 0);
      top.append(label, count);

      const track = document.createElement('div');
      track.className = `bot-bar-track${isQuota ? ' bot-bar-purple' : ''}`;
      const bar = document.createElement('span');
      const width = Math.max(0, Math.min(100, Number(item.count || 0) / max * 100));
      bar.style.width = `${width}%`;
      track.appendChild(bar);
      row.append(top, track);
      fragment.appendChild(row);
    });
    list.replaceChildren(fragment);
  };

  const schedule = (delay) => {
    window.clearTimeout(timer);
    if (stopped || inFlight) return;
    timer = window.setTimeout(pollSummary, delay);
  };

  const pollSummary = async () => {
    if (stopped || inFlight) return;
    if (document.visibilityState !== 'visible' || !navigator.onLine) {
      schedule(hiddenInterval);
      return;
    }

    inFlight = true;
    const controller = new AbortController();
    activeController = controller;
    const timeout = window.setTimeout(() => controller.abort(), 8_000);
    try {
      const response = await fetch(endpoint, {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
        signal: controller.signal,
      });
      if (response.status === 401 || response.status === 403) {
        stopped = true;
        return;
      }
      if (!response.ok) throw new Error('summary unavailable');
      const data = await response.json();
      if (!data?.ok) throw new Error('invalid response');
      updateTotals(data.totals || {});
      renderRanking('directions', data.top_directions || [], false);
      renderRanking('quotas', data.top_quotas || [], true);
    } catch (_) {
      // Temporary network errors should not flash into the UI; retry with backoff.
    } finally {
      window.clearTimeout(timeout);
      inFlight = false;
      if (activeController === controller) activeController = null;
      if (!stopped) schedule(document.visibilityState === 'visible' ? visibleInterval : hiddenInterval);
    }
  };

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && !inFlight) schedule(300);
  });
  window.addEventListener('online', () => schedule(300));
  window.addEventListener('pagehide', () => {
    stopped = true;
    window.clearTimeout(timer);
    activeController?.abort();
  }, { once: true });

  schedule(800);
})();
