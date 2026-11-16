/* Lightweight count refresh and unobtrusive on-site system notification toast. */
(() => {
  'use strict';
  const counter = document.querySelector('[data-notification-count]');
  if (!counter) return;
  let previousCount = null;
  let toastTimer;
  const toast = (count) => {
    if (document.querySelector('[data-system-toast]')) document.querySelector('[data-system-toast]').remove();
    const item = document.createElement('div');
    item.className = 'system-notification-toast';
    item.dataset.systemToast = '';
    item.setAttribute('role', 'status');
    const text = document.createElement('span');
    text.textContent = `Есть новые уведомления. Непрочитанных: ${count}`;
    const link = document.createElement('a');
    link.href = '/notifications';
    link.textContent = 'Открыть';
    const close = document.createElement('button');
    close.type = 'button';
    close.textContent = '×';
    close.setAttribute('aria-label', 'Закрыть уведомление');
    close.addEventListener('click', () => { item.remove(); });
    item.append(text, link, close);
    document.body.append(item);
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => { item.remove(); }, 6500);
  };
  const syncBadge = (count) => {
    counter.textContent = count > 99 ? '99+' : String(count);
    counter.hidden = count === 0;
    counter.closest('a')?.setAttribute('aria-label', `Уведомления: ${count} непрочитанных`);
  };
  document.addEventListener('notifications:read', (event) => {
    const count = Math.max(0, Number(event.detail?.unread) || 0);
    syncBadge(count);
    previousCount = count; // An acknowledgement should not trigger a "new" toast.
  });
  let updateInFlight = false;
  let activeController = null;
  let pollingTimer = 0;
  const update = async () => {
    if (document.visibilityState === 'hidden' || navigator.onLine === false || updateInFlight) return;
    updateInFlight = true;
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    activeController = controller;
    const timeout = controller ? window.setTimeout(() => controller.abort(), 8000) : 0;
    try {
      const response = await fetch('/notifications/api/unread', {
        credentials: 'same-origin', cache: 'no-store',
        ...(controller ? {signal: controller.signal} : {}),
      });
      if (!response.ok) return;
      const data = await response.json();
      if (!data.ok) return;
      const count = Math.max(0, Number(data.unread) || 0);
      syncBadge(count);
      if (previousCount !== null && count > previousCount) toast(count);
      previousCount = count;
    } catch (_) { /* Offline tabs continue to render normally. */ }
    finally {
      if (timeout) window.clearTimeout(timeout);
      if (activeController === controller) activeController = null;
      updateInFlight = false;
    }
  };
  const startPolling = () => {
    if (document.visibilityState === 'hidden' || navigator.onLine === false) return;
    if (!pollingTimer) {
      void update();
      pollingTimer = window.setInterval(update, 45000);
    }
  };
  const stopPolling = () => {
    if (pollingTimer) window.clearInterval(pollingTimer);
    pollingTimer = 0;
    activeController?.abort();
  };
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') stopPolling();
    else startPolling();
  });
  window.addEventListener('offline', stopPolling);
  window.addEventListener('online', () => {
    startPolling();
    if (document.visibilityState !== 'hidden') void update();
  });
  startPolling();
})();

/* Personal read receipts: no full-page refresh, with an ordinary POST fallback. */
(() => {
  'use strict';
  const center = document.querySelector('[data-notifications-center]');
  if (!center || !window.fetch || !window.FormData) return;
  const stateFilter = new URLSearchParams(window.location.search).get('state');
  const status = document.querySelector('[data-notification-status]');
  const stat = document.querySelector('.alerts-stat');
  const bulkForm = document.querySelector('[data-notification-read-all]');
  const empty = document.querySelector('[data-notifications-empty]');
  let busy = false;

  const showMessage = (message, error = false) => {
    if (!status) return;
    status.hidden = false;
    status.textContent = message;
    status.classList.toggle('is-error', error);
  };
  const markItem = (item) => {
    if (!item) return;
    item.classList.remove('is-unread');
    item.querySelector('.alert-new-label')?.remove();
    const form = item.querySelector('[data-notification-read]');
    if (form) {
      const label = document.createElement('span');
      label.className = 'alert-read-confirmation';
      label.textContent = '✓ Прочитано';
      form.replaceWith(label);
    }
    if (stateFilter === 'unread') item.remove();
  };
  const syncPage = (unread) => {
    if (stat) stat.textContent = `${unread} непрочитанных`;
    document.dispatchEvent(new CustomEvent('notifications:read', { detail: { unread } }));
    if (bulkForm && !center.querySelector('.is-unread')) bulkForm.hidden = true;
    if (empty && !center.querySelector('[data-notification-item]')) empty.hidden = false;
  };
  if (bulkForm && !center.querySelector('.is-unread')) bulkForm.hidden = true;

  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!form.matches?.('[data-notification-read], [data-notification-read-all]')) return;
    if (busy) { event.preventDefault(); return; }
    event.preventDefault();
    busy = true;
    const button = form.querySelector('button[type=submit]');
    const original = button?.textContent;
    if (button) { button.disabled = true; button.textContent = 'Сохраняю…'; }
    form.setAttribute('aria-busy', 'true');
    if (status) status.hidden = true;
    try {
      const response = await fetch(form.action, {
        method: 'POST', credentials: 'same-origin',
        headers: { Accept: 'application/json' }, body: new FormData(form),
      });
      if (!response.ok || response.redirected) throw new Error('HTTP error');
      const result = await response.json();
      if (!result.ok || !Number.isFinite(Number(result.unread))) throw new Error('Invalid response');
      if (form.matches('[data-notification-read-all]')) {
        center.querySelectorAll('[data-notification-item].is-unread').forEach(markItem);
      } else {
        markItem(form.closest('[data-notification-item]'));
      }
      syncPage(Math.max(0, Number(result.unread)));
      showMessage('Статус уведомлений сохранён для вашего аккаунта.');
    } catch (_) {
      showMessage('Не удалось сохранить статус. Проверьте соединение и повторите.', true);
    } finally {
      if (button?.isConnected) { button.disabled = false; button.textContent = original; }
      form.removeAttribute('aria-busy');
      busy = false;
    }
  });
})();

/* Compose modal: native dialog provides focus trapping and Escape behavior. */
(() => {
  'use strict';
  const dialog = document.getElementById('broadcast-dialog');
  const openButton = document.querySelector('[data-open-broadcast]');
  if (!dialog || !openButton) return;
  const form = dialog.querySelector('#broadcast-form');
  const options = [...form.querySelectorAll('input[name="channels"]')];
  const hint = dialog.querySelector('[data-broadcast-hint]');
  const siteOnlyFields = [...form.querySelectorAll('[data-site-audience],[data-site-severity]')];
  const submitButton = form.querySelector('[data-broadcast-submit]');
  const globalToggle = form.querySelector('[data-broadcast-global]');
  const directionChecks = [...form.querySelectorAll('input[name="direction_ids"]')];
  const directionList = form.querySelector('[data-broadcast-direction-list]');
  const syncScope = () => {
    if (directionList) directionList.hidden = Boolean(globalToggle?.checked);
    directionChecks.forEach(check => {check.disabled = Boolean(globalToggle?.checked);});
  };
  globalToggle?.addEventListener('change', syncScope);
  syncScope();
  const update = () => {
    const selected = new Set(options.filter(input => input.checked).map(input => input.value));
    const siteEnabled = selected.has('site');
    siteOnlyFields.forEach(field => {field.hidden = !siteEnabled;});
    const parts = [];
    if (siteEnabled) parts.push('на сайте');
    if (selected.has('chats')) parts.push('в чатах Telegram');
    if (selected.has('dm')) parts.push('в личных сообщениях Telegram');
    if (selected.has('vk_chats')) parts.push('в чатах VK');
    if (selected.has('vk_dm')) parts.push('в личных сообщениях VK');
    if (selected.has('max_chats')) parts.push('в чатах MAX');
    if (selected.has('max_dm')) parts.push('в личных сообщениях MAX');
    if (selected.has('staff_dm')) parts.push('сотрудникам в Telegram');
    hint.textContent = parts.length ? `Публикация ${parts.join(', ')}. Фильтры ниже ограничат получателей.` : 'Выберите хотя бы один способ доставки.';
    submitButton.disabled = !parts.length;
    submitButton.textContent = [...selected].some(channel => channel !== 'site') ? 'Отправить через ботов' : 'Опубликовать на сайте';
  };
  openButton.addEventListener('click', () => {
    if (typeof dialog.showModal === 'function') dialog.showModal();
    else dialog.setAttribute('open', '');
    update();
    form.querySelector('[name="title"]')?.focus();
  });
  dialog.querySelectorAll('[data-close-broadcast]').forEach(button => button.addEventListener('click', () => {
    if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open');
    openButton.focus();
  }));
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => openButton.focus());
  const selectThreeChats = dialog.querySelector('[data-select-three-chats]');
  selectThreeChats?.addEventListener('click', () => {
    const chatValues = new Set(['chats','vk_chats','max_chats']);
    options.forEach(input => { if (chatValues.has(input.value)) input.checked = true; });
    update();
  });
  options.forEach(input => input.addEventListener('change', update));
  form.addEventListener('submit', (event) => {
    if (!globalToggle?.checked && !directionChecks.some(input => input.checked)) {
      event.preventDefault();
      hint.textContent = 'Выберите направления рассылки.';
      directionChecks[0]?.focus();
      return;
    }
    if (!options.some(input => input.checked)) {
      event.preventDefault();
      hint.textContent = 'Необходимо выбрать способ доставки.';
      options[0].focus();
      return;
    }
    submitButton.disabled = true;
    submitButton.textContent = 'Отправка…';
  });
  update();
})();

/* Read an alert in a modal without leaving the workflow. */
(() => {
 const dialog=document.getElementById('notification-details-dialog');if(!dialog)return;
 document.addEventListener('click',e=>{const trigger=e.target.closest('[data-alert-open]');if(trigger){dialog.querySelector('[data-alert-modal-title]').textContent=trigger.dataset.alertTitle||'';dialog.querySelector('[data-alert-modal-body]').textContent=trigger.dataset.alertBody||'';dialog.querySelector('[data-alert-modal-date]').textContent=trigger.dataset.alertDate||'';dialog.showModal();}else if(e.target.closest('[data-alert-modal-close]'))dialog.close();});
 dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close()});
})();

(() => {
 const expire=()=>document.querySelectorAll('[data-notification-item][data-expires-at]').forEach(item=>{
  if(Date.parse(item.dataset.expiresAt)<=Date.now())item.remove();
 });
 expire();window.setInterval(expire,60000);
})();
