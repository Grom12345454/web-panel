(() => {
  'use strict';

  const mobileButton = document.querySelector('[data-mobile-nav]');
  const sidebar = document.querySelector('[data-sidebar]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const desktopQuery = window.matchMedia('(min-width: 821px)');
  let previouslyFocused = null;

  // Keep the sidebar's place within the current role + navigation section.
  // A single global scroll value made an archive page's deep position leak into
  // the administration menu after navigation and could hide the active link.
  if (sidebar) {
    const roleKey = [...document.body.classList].find((name) => name.startsWith('role-')) || 'role-unknown';
    const currentPageLink = sidebar.querySelector('a[aria-current="page"], a.nav-link.active, a.nav-sub-link.active');
    const currentPageSection = currentPageLink?.closest('.nav-section');
    const sectionContent = currentPageSection?.querySelector('[data-nav-section-content]');
    const sectionKey = sectionContent?.id || 'default';
    const scrollKey = `student-council:admin-sidebar-scroll:${roleKey}:${sectionKey}`;
    const saveSidebarScroll = () => {
      try { window.sessionStorage.setItem(scrollKey, String(sidebar.scrollTop)); } catch (_) { /* optional */ }
    };
    try {
      const savedScroll = Number(window.sessionStorage.getItem(scrollKey));
      requestAnimationFrame(() => {
        if (Number.isFinite(savedScroll) && savedScroll > 0) sidebar.scrollTop = savedScroll;
        // Keep the destination visible even when the saved position predates a
        // role permission change or a reorganization of the navigation tree.
        const activeLink = sidebar.querySelector('a[aria-current="page"], a.nav-link.active, a.nav-sub-link.active');
        if (activeLink) {
          const sidebarRect = sidebar.getBoundingClientRect();
          const linkRect = activeLink.getBoundingClientRect();
          const itemTop = sidebar.scrollTop + (linkRect.top - sidebarRect.top);
          const itemBottom = itemTop + linkRect.height;
          const viewTop = sidebar.scrollTop;
          const viewBottom = viewTop + sidebar.clientHeight;
          if (itemTop < viewTop || itemBottom > viewBottom) {
            sidebar.scrollTop = Math.max(0, itemTop - Math.max(24, Math.round(sidebar.clientHeight * 0.18)));
          }
        }
      });
    } catch (_) { /* Storage may be unavailable in embedded browsers. */ }
    // Persist once when leaving the page instead of writing sessionStorage on every scroll event.
    window.addEventListener('pagehide', saveSidebarScroll);
  }

  // Tiny tactile response for controls; no pointer tracking loop or layout polling.
  const pressableSelector = '.page .btn, .page button, .top-actions .alert-top-link, .top-actions .logout-btn';
  const reduceMotionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  document.addEventListener('pointerdown', (event) => {
    if (reduceMotionQuery?.matches) return;
    const element = event.target.closest?.(pressableSelector);
    if (!element || element.matches(':disabled')) return;
    element.classList.remove('ship-control-feedback');
    // Pulse only non-navigation controls; avoid a forced synchronous layout read.
    element.classList.add('ship-control-feedback');
  }, { passive: true });
  document.addEventListener('animationend', (event) => {
    if (event.animationName === 'ship-control-feedback') event.target.classList.remove('ship-control-feedback');
  });

  const setMenuOpen = (open) => {
    if (!sidebar || !mobileButton) return;
    sidebar.classList.toggle('is-open', open);
    backdrop?.classList.toggle('is-open', open);
    mobileButton.setAttribute('aria-expanded', String(open));
    mobileButton.setAttribute('aria-label', open ? 'Закрыть меню' : 'Открыть меню');
    mobileButton.textContent = open ? '×' : '☰';
    document.body.classList.toggle('nav-drawer-open', open);
    document.body.style.overflow = open ? 'hidden' : '';
    if (open) {
      previouslyFocused = document.activeElement;
      sidebar.querySelector('a.nav-link, button.nav-toggle')?.focus({ preventScroll: true });
    } else if (previouslyFocused instanceof HTMLElement) {
      previouslyFocused.focus({ preventScroll: true });
    }
  };

  // Collapsible navigation stays compact by default to keep the sidebar usable
  // without a nested scrollbar; only one submenu can be expanded at a time.
  document.querySelectorAll('[data-nav-toggle]').forEach((toggle) => {
    const group = toggle.closest('.nav-link-group');
    if (!group) return;

    const key = `student-council-nav:${toggle.dataset.navKey || 'group'}`;
    const openGroupStorageKey = 'student-council-nav:open-group';
    // Start compact: the sidebar's top-level destinations must fit without an inner scrollbar.
    // At most one submenu can be open, so the navigation remains predictable and bounded.
    let expanded = group.classList.contains('is-active-group');
    try {
      if (!expanded && window.innerHeight >= 760) expanded = window.localStorage.getItem(openGroupStorageKey) === key;
    } catch (_) { /* Storage can be unavailable. */ }

    const applyExpanded = (value) => {
      group.classList.toggle('is-collapsed', !value);
      toggle.setAttribute('aria-expanded', String(value));
    };
    applyExpanded(expanded);

    toggle.addEventListener('click', () => {
      expanded = toggle.getAttribute('aria-expanded') !== 'true';
      if (expanded) {
        document.querySelectorAll('[data-nav-toggle]').forEach((otherToggle) => {
          if (otherToggle === toggle) return;
          const otherGroup = otherToggle.closest('.nav-link-group');
          otherGroup?.classList.add('is-collapsed');
          otherToggle.setAttribute('aria-expanded', 'false');
        });
      }
      applyExpanded(expanded);
      try { window.localStorage.setItem(openGroupStorageKey, expanded ? key : ''); } catch (_) { /* Optional preference. */ }
    });
  });

  // Top-level navigation sections: one work category expanded at a time.
  const sectionToggles = [...document.querySelectorAll('[data-nav-section-toggle]')];
  // Prefer the section containing the actual current-page link over a stale or
  // overly broad server-side section flag. This keeps archive/report routes in
  // the work area rather than accidentally expanding administration.
  const currentNavLink = sidebar?.querySelector('a[aria-current="page"], a.nav-link.active, a.nav-sub-link.active');
  const currentRouteSection = currentNavLink?.closest('.nav-section');
  const serverMarkedSection = sectionToggles
    .map((toggle) => toggle.closest('.nav-section'))
    .find((section) => section?.classList.contains('is-active-section'));
  const preferredOpenSection = currentRouteSection || serverMarkedSection || null;

  sectionToggles.forEach((toggle) => {
    const section = toggle.closest('.nav-section');
    const content = section?.querySelector('[data-nav-section-content]');
    if (!section || !content) return;
    let expanded = section === preferredOpenSection;
    const applySectionState = (value) => {
      section.classList.toggle('is-collapsed-section', !value);
      content.classList.toggle('is-collapsed', !value);
      content.hidden = !value;
      toggle.setAttribute('aria-expanded', String(value));
    };
    // Exactly one section is open on first render. The current route wins;
    // otherwise retain the server's first active-section hint.
    section.classList.toggle('is-active-section', section === preferredOpenSection);
    applySectionState(expanded);
    toggle.addEventListener('click', () => {
      expanded = toggle.getAttribute('aria-expanded') !== 'true';
      if (expanded) {
        sectionToggles.forEach((other) => {
          if (other === toggle) return;
          const otherSection = other.closest('.nav-section');
          const otherContent = otherSection?.querySelector('[data-nav-section-content]');
          otherSection?.classList.add('is-collapsed-section');
          if (otherContent) {
            otherContent.classList.add('is-collapsed');
            otherContent.hidden = true;
          }
          other.setAttribute('aria-expanded', 'false');
        });
      }
      applySectionState(expanded);
    });
  });

  if (mobileButton && sidebar) {
    mobileButton.addEventListener('click', () => setMenuOpen(!sidebar.classList.contains('is-open')));
    backdrop?.addEventListener('click', () => setMenuOpen(false));
    sidebar.querySelectorAll('a.nav-link, a.nav-sub-link').forEach((link) => {
      link.addEventListener('click', () => setMenuOpen(false));
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && sidebar.classList.contains('is-open')) setMenuOpen(false);
    });
    const onBreakpointChange = (event) => { if (event.matches) setMenuOpen(false); };
    if (desktopQuery.addEventListener) desktopQuery.addEventListener('change', onBreakpointChange);
    else desktopQuery.addListener(onBreakpointChange);
  }

  // Card movement now uses compositor-friendly CSS only.
  // Keep click, keyboard and form interactions free from pointer tracking.

  // Flash messages are dismissed accessibly and leave no invisible overlay.
  document.querySelectorAll('[data-dismiss]').forEach((element) => {
    window.setTimeout(() => {
      element.style.opacity = '0';
      element.style.transform = 'translateY(6px)';
      window.setTimeout(() => element.remove(), 240);
    }, 5200);
  });

  document.querySelectorAll('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', (event) => {
      const message = form.getAttribute('data-confirm');
      if (message && !window.confirm(message)) event.preventDefault();
    });
  });
})();

(() => {
  'use strict';
  const container = document.getElementById('quota-days');
  const addButton = document.getElementById('add-quota-day');
  const hint = document.getElementById('quota-days-hint');
  const form = document.getElementById('quota-create-form');
  if (!container || !addButton || !form) return;

  let nextIndex = 0;

  const updateHint = () => {
    const count = container.querySelectorAll('[data-quota-day]').length;
    if (hint) hint.textContent = `Добавлено дат: ${count}`;
    addButton.disabled = count >= 60;
  };

  const makeField = (labelText, name, type, value, min = null) => {
    const wrapper = document.createElement('label');
    wrapper.className = 'field';
    const label = document.createElement('span');
    label.className = 'quota-day-number';
    label.textContent = labelText;
    const input = document.createElement('input');
    input.className = 'input';
    input.name = name;
    input.type = type;
    input.value = value;
    input.required = true;
    if (min !== null) input.min = String(min);
    wrapper.append(label, input);
    return wrapper;
  };

  const addDay = (dateValue = '', placesValue = '') => {
    if (container.querySelectorAll('[data-quota-day]').length >= 60) return;
    const index = nextIndex++;
    const row = document.createElement('div');
    row.className = 'quota-day-row';
    row.dataset.quotaDay = '1';

    const dateField = makeField('Дата', `day_date_${index}`, 'date', dateValue);
    const placesField = makeField('Мест на дату', `day_places_${index}`, 'number', placesValue, 1);
    placesField.querySelector('input').placeholder = '20';

    const removeButton = document.createElement('button');
    removeButton.className = 'btn btn-soft btn-remove-day';
    removeButton.type = 'button';
    removeButton.textContent = 'Удалить';
    removeButton.setAttribute('aria-label', 'Удалить эту дату');
    removeButton.addEventListener('click', () => {
      row.remove();
      updateHint();
    });

    row.append(dateField, placesField, removeButton);
    container.appendChild(row);
    updateHint();
  };

  addButton.addEventListener('click', () => addDay());
  addDay(form.dataset.initialDate || '');

  form.addEventListener('submit', (event) => {
    if (!container.querySelector('[data-quota-day]')) {
      event.preventDefault();
      window.alert('Добавьте хотя бы одну дату мероприятия.');
      addButton.focus();
    }
  });
})();
