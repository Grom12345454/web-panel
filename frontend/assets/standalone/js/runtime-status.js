/* Live admin diagnostics. Never returns or renders secret values. */
(() => {
  const root = document.querySelector('.pro-runtime[data-runtime-url]');
  if (!root) return;
  const button = root.querySelector('[data-runtime-refresh]');
  const read = (key) => root.querySelector(`[data-runtime-${key}]`);
  const labels = {running:'Активна', restarting:'Перезапуск', cooldown:'Пауза защиты', stopped:'Остановлена', pending:'Запуск'};
  const stamp = () => new Intl.DateTimeFormat('ru-RU', { hour:'2-digit', minute:'2-digit', second:'2-digit' }).format(new Date());
  const formatDuration = (value) => {
    let seconds = Math.max(0, Math.floor(Number(value) || 0));
    const days = Math.floor(seconds / 86400); seconds %= 86400;
    const hours = Math.floor(seconds / 3600); seconds %= 3600;
    const minutes = Math.floor(seconds / 60); seconds %= 60;
    if (days) return `${days} д ${hours} ч`;
    if (hours) return `${hours} ч ${minutes} мин`;
    if (minutes) return `${minutes} мин ${seconds} с`;
    return `${seconds} с`;
  };
  const setText = (key, value) => {
    const target = read(key);
    if (target) target.textContent = value == null || value === '' ? '—' : String(value);
  };
  let busy = false;
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    if (button) button.disabled = true;
    try {
      const response = await fetch(root.dataset.runtimeUrl, {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data.ok || !Array.isArray(data.workers) || !Array.isArray(data.database_checks)) throw new Error('Некорректный ответ');

      const banner = read('health-banner');
      if (banner && data.health) {
        const state = data.health.state || 'attention';
        banner.dataset.state = state;
        const mark = banner.querySelector('.pro-runtime-health-mark');
        if (mark) mark.textContent = state === 'ok' ? '✓' : (state === 'attention' ? '!' : '×');
      }
      setText('health-label', data.health?.label);
      setText('health-detail', data.health?.detail);
      setText('checked', data.checked_at || stamp());
      setText('worker-checked', data.checked_at || stamp());
      setText('db-healthy', `${data.databases_healthy ?? 0}/${data.databases_total ?? data.database_checks.length}`);
      const running = data.workers.filter(item => item.state === 'running').length;
      setText('workers-running', `${running}/${data.workers.length}`);
      setText('uptime', formatDuration(data.process?.uptime_seconds));
      setText('server-errors', data.http_metrics?.server_errors_24h ?? 0);
      setText('server-errors-detail', data.http_metrics?.server_errors_24h ?? 0);
      setText('delivery-pending', data.queue_metrics?.pending ?? 0);
      setText('restarts', data.workers.reduce((sum, item) => sum + (Number(item.restarts) || 0), 0));

      (data.database_checks || []).forEach(database => {
        const card = root.querySelector(`.pro-runtime-db-card[data-db-bind="${CSS.escape(database.bind)}"]`);
        if (!card) return;
        const status = card.querySelector('[data-db-state]');
        if (status) {
          status.dataset.state = database.state || 'error';
          status.textContent = database.status_label || (database.state === 'ok' ? 'Доступна' : 'Ошибка подключения');
        }
        const latency = card.querySelector('[data-db-latency]');
        if (latency) latency.textContent = Number.isFinite(Number(database.latency_ms)) ? `${database.latency_ms} мс` : '—';
        const size = card.querySelector('[data-db-size]');
        if (size) size.textContent = database.size_mb == null ? 'Не определён' : `${database.size_mb} МБ`;
        const error = card.querySelector('[data-db-error]');
        if (error) error.textContent = database.error_type || 'Нет';
      });

      data.workers.forEach(worker => {
        const card = [...root.querySelectorAll('[data-worker]')].find(row => row.dataset.worker === worker.name);
        if (!card) return;
        ['restarts','started_at','last_failure_at','last_error_type','thread_alive','state'].forEach(key => {
          const target = card.querySelector(`[data-field="${key}"]`);
          if (!target) return;
          if (key === 'state') {
            target.textContent = labels[worker.state] || worker.state || 'Неизвестно';
            target.dataset.state = worker.state || 'stopped';
          } else if (key === 'thread_alive') {
            target.textContent = worker.thread_alive ? 'Да' : 'Нет';
          } else {
            target.textContent = worker[key] ?? '—';
          }
        });
      });

      (data.integrations || []).forEach(integration => {
        const card = root.querySelector(`[data-integration="${CSS.escape(integration.key)}"]`);
        if (!card) return;
        const status = card.querySelector('[data-integration-status]');
        const detail = card.querySelector('[data-integration-detail]');
        if (status) {
          status.dataset.state = integration.configured ? 'ok' : 'stopped';
          status.textContent = integration.status_label || (integration.configured ? 'Конфигурация задана' : 'Не настроен');
        }
        if (detail) detail.textContent = integration.detail || '';
      });

      const http = data.http_metrics || {};
      setText('http-availability', http.available ? 'Данные доступны' : 'Данные недоступны');
      setText('audit-requests', http.requests_24h ?? '—');
      setText('audit-staff', http.staff_actions_24h ?? '—');
      setText('client-errors', http.client_errors_24h ?? '—');
      const queue = data.queue_metrics || {};
      setText('queue-availability', queue.available === false ? 'Данные недоступны' : 'Данные доступны');
      setText('queue-pending', queue.pending ?? '—');
      setText('queue-sending', queue.sending ?? '—');
      setText('queue-failed', queue.failed ?? '—');
      setText('queue-blocked', queue.blocked ?? '—');
      setText('queue-delivered', queue.delivered ?? '—');
      Object.entries(data.queue_statuses || {}).forEach(([state, count]) => {
        const row = root.querySelector(`[data-queue-row="${CSS.escape(state)}"] [data-queue-value]`);
        if (row) row.textContent = String(count);
      });

      setText('mode', data.process?.mode || '—');
      const debug = read('debug');
      if (debug) {
        debug.textContent = data.process?.debug_enabled ? 'Включён' : 'Выключен';
        debug.dataset.state = data.process?.debug_enabled ? 'attention' : 'ok';
      }
      const secret = read('secret');
      if (secret) {
        secret.textContent = data.process?.secret_key_configured ? 'Задан надёжный ключ' : 'Не задан в .env; используется локальный fallback';
        secret.dataset.state = data.process?.secret_key_configured ? 'ok' : 'attention';
      }
      setText('disk-free', data.disk_metrics?.available ? `${data.disk_metrics.free_gb} из ${data.disk_metrics.total_gb} ГБ` : 'Не удалось проверить');
      const logState = read('log-state');
      if (logState) {
        logState.textContent = data.log_metrics?.status_label || 'Неизвестно';
        logState.dataset.state = data.log_metrics?.available ? 'ok' : 'attention';
      }
      setText('log-size', data.log_metrics?.size_mb == null ? '—' : `${data.log_metrics.size_mb} МБ`);
      setText('log-modified', data.log_metrics?.modified_at || '—');
    } catch (_) {
      setText('checked', `Нет связи · ${stamp()}`);
      setText('worker-checked', 'Не удалось обновить данные');
    } finally {
      busy = false;
      if (button) button.disabled = false;
    }
  }
  button?.addEventListener('click', refresh);
  refresh();
  const interval = window.setInterval(refresh, 20000);
  window.addEventListener('pagehide', () => window.clearInterval(interval), {once:true});
})();
