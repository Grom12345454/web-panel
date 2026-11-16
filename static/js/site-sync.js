(() => {
  'use strict';

  // A conservative refresh policy for authenticated portal pages. Never reload
  // while a form is dirty, an editor has focus, a dialog is open, or the user is active.
  if (!document.querySelector('.app-shell') || document.body.dataset.autoRefresh === 'off' || location.protocol === 'file:') return;

  const intervalMs = 60_000;
  const idleBeforeRefreshMs = 12_000;
  const snapshotMaxAgeMs = 2 * 60_000;
  const pageKey = `site-sync:${location.pathname}${location.search}`;
  const fields = () => [...document.querySelectorAll('input:not([type="password"]), textarea, select')]
    .filter((element) => element.type !== 'hidden' && !element.disabled);

  const readValue = (element) => {
    if (element.type === 'checkbox' || element.type === 'radio') {
      return { checked: element.checked, value: element.value };
    }
    if (element.tagName === 'SELECT' && element.multiple) {
      return { selected: [...element.options].map((option) => option.selected) };
    }
    return { value: String(element.value ?? '') };
  };

  const fieldSnapshot = () => fields().map((element, index) => ({
    index,
    name: element.name || '',
    id: element.id || '',
    tag: element.tagName,
    type: element.type || '',
    data: readValue(element),
  }));

  const restoreState = () => {
    try {
      const raw = sessionStorage.getItem(pageKey);
      if (!raw) return;
      sessionStorage.removeItem(pageKey);
      const snapshot = JSON.parse(raw);
      if (!snapshot.savedAt || Date.now() - snapshot.savedAt > snapshotMaxAgeMs) return;

      const elements = fields();
      (snapshot.fields || []).forEach((item) => {
        const element = elements[item.index];
        if (!element || element.name !== item.name || element.id !== item.id || element.tagName !== item.tag) return;
        const data = item.data || {};
        if (element.type === 'checkbox' || element.type === 'radio') {
          element.checked = Boolean(data.checked);
        } else if (element.tagName === 'SELECT' && element.multiple && Array.isArray(data.selected)) {
          [...element.options].forEach((option, index) => { option.selected = Boolean(data.selected[index]); });
        } else if (Object.prototype.hasOwnProperty.call(data, 'value')) {
          element.value = data.value;
        }
        element.dispatchEvent(new Event('input', { bubbles: true }));
        element.dispatchEvent(new Event('change', { bubbles: true }));
      });
      if (Number.isFinite(snapshot.scrollY)) window.scrollTo(0, snapshot.scrollY);
      const sidebar = document.querySelector('[data-sidebar-nav]');
      if (sidebar && Number.isFinite(snapshot.sidebarScrollTop)) sidebar.scrollTop = snapshot.sidebarScrollTop;
    } catch (_) {
      // Session storage can be unavailable; site functionality should continue.
    }
  };

  restoreState();

  const writeControls = [...document.querySelectorAll('form')]
    .filter((form) => String(form.method || 'get').toLowerCase() === 'post')
    .flatMap((form) => [...form.querySelectorAll('input, textarea, select')]);
  const baseline = new WeakMap();
  writeControls.forEach((element) => baseline.set(element, JSON.stringify(readValue(element))));

  let submitting = false;
  let lastInteraction = Date.now();
  const markInteraction = () => { lastInteraction = Date.now(); };
  const isDirty = () => writeControls.some((element) =>
    element.isConnected && JSON.stringify(readValue(element)) !== baseline.get(element));
  const isEditing = () => {
    const active = document.activeElement;
    return Boolean(active && active.matches('input, textarea, select, [contenteditable="true"]'));
  };
  const hasTransientUi = () => Boolean(document.querySelector(
    'dialog[open], [role="dialog"], [aria-busy="true"], .is-saving, .is-loading'
  ));

  ['input', 'change', 'keydown', 'click', 'pointerdown', 'wheel', 'touchstart'].forEach((eventName) => {
    document.addEventListener(eventName, markInteraction, { capture: true, passive: true });
  });

  document.querySelectorAll('form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      submitting = true;
      // If another handler cancels submission (for example, a confirmation
      // dialog), allow the page to return to its normal refresh lifecycle.
      window.setTimeout(() => { if (event.defaultPrevented) submitting = false; }, 0);
    }, { capture: true });
  });

  const saveState = () => {
    try {
      const sidebar = document.querySelector('[data-sidebar-nav]');
      sessionStorage.setItem(pageKey, JSON.stringify({
        savedAt: Date.now(),
        fields: fieldSnapshot(),
        scrollY: window.scrollY,
        sidebarScrollTop: sidebar ? sidebar.scrollTop : 0,
      }));
    } catch (_) {
      // State restoration is a convenience, not a dependency.
    }
  };

  const refreshIfSafe = () => {
    if (document.visibilityState !== 'visible' || !navigator.onLine || submitting) return;
    if (isDirty() || isEditing() || hasTransientUi()) return;
    if (Date.now() - lastInteraction < idleBeforeRefreshMs) return;
    saveState();
    window.location.reload();
  };

  window.setInterval(refreshIfSafe, intervalMs);
})();
