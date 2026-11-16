(() => {
  'use strict';

  const mobileButton = document.querySelector('[data-mobile-nav]');
  const sidebar = document.querySelector('[data-sidebar]');
  const backdrop = document.querySelector('[data-sidebar-backdrop]');
  const desktopQuery = window.matchMedia('(min-width: 821px)');
  let previouslyFocused = null;

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

  // Collapsible navigation. The active destination is visible by default even
  // when the user previously collapsed this group on another page.
  document.querySelectorAll('[data-nav-toggle]').forEach((toggle) => {
    const group = toggle.closest('.nav-link-group');
    if (!group) return;

    const key = `student-council-nav:${toggle.dataset.navKey || 'group'}`;
    const hasActiveDestination = Boolean(group.querySelector('.nav-sub-link.active'));
    let expanded = toggle.getAttribute('aria-expanded') === 'true';

    let hasSavedPreference = false;
    try {
      const saved = window.localStorage.getItem(key);
      if (saved === 'true' || saved === 'false') {
        expanded = saved === 'true';
        hasSavedPreference = true;
      }
    } catch (_) {
      // Storage can be unavailable in private browsing.
    }
    // Open the active group on first visit; after the user chooses a state,
    // respect that preference even when the active page is inside the group.
    if (hasActiveDestination && !hasSavedPreference) expanded = true;

    const applyExpanded = (value) => {
      group.classList.toggle('is-collapsed', !value);
      toggle.setAttribute('aria-expanded', String(value));
    };
    applyExpanded(expanded);

    toggle.addEventListener('click', () => {
      expanded = toggle.getAttribute('aria-expanded') !== 'true';
      applyExpanded(expanded);
      try { window.localStorage.setItem(key, String(expanded)); } catch (_) { /* Optional preference. */ }
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

  // Decorative tilt is disabled in the v9 console; predictable controls take
  // priority over movement effects. data-tilt remains harmless on older pages.
  if (document.body.dataset.uiVersion !== '9' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.querySelectorAll('[data-tilt]').forEach((card) => {
      if (window.matchMedia('(pointer: coarse)').matches) return;
      let frame = 0;
      card.addEventListener('pointermove', (event) => {
        const rect = card.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const x = (event.clientX - rect.left) / rect.width - 0.5;
        const y = (event.clientY - rect.top) / rect.height - 0.5;
        cancelAnimationFrame(frame);
        frame = requestAnimationFrame(() => {
          card.style.transform = `perspective(1200px) rotateX(${(-y * 3).toFixed(2)}deg) rotateY(${(x * 4).toFixed(2)}deg) translate3d(0, -1px, 4px)`;
        });
      });
      card.addEventListener('pointerleave', () => {
        cancelAnimationFrame(frame);
        card.style.transform = '';
      });
    });
  }

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
  addDay();

  form.addEventListener('submit', (event) => {
    if (!container.querySelector('[data-quota-day]')) {
      event.preventDefault();
      window.alert('Добавьте хотя бы одну дату мероприятия.');
      addButton.focus();
    }
  });
})();
