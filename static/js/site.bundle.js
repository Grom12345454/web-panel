/* GENERATED FILE — site.bundle.js. Edit frontend/assets/scripts/ and rebuild. */

/* ===== BEGIN frontend/assets/scripts/shared/performance-budget-2026.js ===== */
/* Adaptive visual-performance budget shared by the portal and Student App.
 * This is intentionally capability-based: it never guesses a device model.
 * It only selects lighter visual defaults; navigation and app functionality stay intact.
 */
(() => {
  'use strict';
  const body = document.body;
  if (!body) return;

  const motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const touchQuery = window.matchMedia ? window.matchMedia('(pointer: coarse), (max-width: 760px)') : null;
  const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection || null;

  function applyBudget() {
    const cores = Number(navigator.hardwareConcurrency) || 0;
    const memory = Number(navigator.deviceMemory) || 0;
    const effectiveType = String(connection && connection.effectiveType || '').toLowerCase();
    const saveData = Boolean(connection && connection.saveData);
    const constrainedNetwork = saveData || effectiveType === 'slow-2g' || effectiveType === '2g';
    // Older phones and office laptops with four threads / 4 GB RAM are
    // common in campus deployments; give them the lighter visual tier too.
    const economy = constrainedNetwork || (cores > 0 && cores <= 4) || (memory > 0 && memory <= 4);
    const reduced = Boolean(motionQuery && motionQuery.matches);
    const touch = Boolean(touchQuery && touchQuery.matches);

    body.classList.toggle('perf-economy', economy);
    body.classList.toggle('perf-balanced', !economy);
    body.classList.toggle('perf-touch', touch);
    body.classList.toggle('perf-reduced-motion', reduced);
    body.dataset.performanceTier = economy ? 'economy' : 'balanced';
  }

  function syncVisibility() {
    body.classList.toggle('perf-page-hidden', document.visibilityState === 'hidden');
  }

  applyBudget();
  syncVisibility();
  document.addEventListener('visibilitychange', syncVisibility, { passive: true });
  window.addEventListener('pageshow', syncVisibility, { passive: true });

  if (motionQuery) {
    if (motionQuery.addEventListener) motionQuery.addEventListener('change', applyBudget);
    else if (motionQuery.addListener) motionQuery.addListener(applyBudget);
  }
  if (touchQuery) {
    if (touchQuery.addEventListener) touchQuery.addEventListener('change', applyBudget);
    else if (touchQuery.addListener) touchQuery.addListener(applyBudget);
  }
  if (connection && connection.addEventListener) connection.addEventListener('change', applyBudget);
})();

/* ===== END frontend/assets/scripts/shared/performance-budget-2026.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/app.js ===== */
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

/* ===== END frontend/assets/scripts/portal/app.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/space.js ===== */
(() => {
  const canvas = document.getElementById('starfield-canvas');
  if (!canvas) return;
  if (document.body.classList.contains('is-login-page') || document.body.classList.contains('is-dashboard-page')) return;
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return;
  const economyMode = document.body.classList.contains('perf-economy');
  const frameInterval = economyMode ? 88 : 55; // cap low-power devices near 11 fps, standard devices near 18 fps

  const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  // Follow the operating system preference; no removed 3D switch in storage.
  let reduceMotion = motionQuery.matches;

  let width = 0, height = 0, dpr = 1, stars = [], meteors = [];
  let raf = 0, frame = 0, lastTime = 0, nextMeteorAt = 0, lastDrawAt = 0;
  let parallaxX = 0, parallaxY = 0;
  const rand = (min, max) => min + Math.random() * (max - min);
  const clamp = (v, min, max) => Math.max(min, Math.min(max, v));

  function makeStar() {
    const depth = rand(0.18, 1);
    return {
      x: rand(0, width), y: rand(0, height),
      radius: rand(0.35, 1.55) * (0.55 + depth * 0.65),
      alpha: rand(0.2, 0.86), phase: rand(0, Math.PI * 2),
      pulse: rand(0.006, 0.026), drift: rand(0.025, 0.22) * depth,
      depth, blue: Math.random() < 0.28, cross: Math.random() < 0.045
    };
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, economyMode ? 1 : (window.innerWidth < 700 ? 1 : 1.15));
    width = Math.max(1, window.innerWidth);
    height = Math.max(1, window.innerHeight);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const area = width * height;
    const count = economyMode
      ? Math.round(clamp(area / (width < 700 ? 15000 : 13500), width < 700 ? 20 : 30, width < 700 ? 36 : 58))
      : Math.round(clamp(area / (width < 700 ? 9000 : 7600), width < 700 ? 32 : 55, width < 700 ? 65 : 110));
    stars = Array.from({ length: count }, makeStar);
    meteors = [];
    nextMeteorAt = performance.now() + rand(1800, 4800);
    draw(performance.now(), true);
  }

  function addMeteor(now) {
    if (reduceMotion || economyMode || width < 360 || meteors.length > 1 || now < nextMeteorAt) return;
    const fromLeft = Math.random() < 0.5;
    const startX = fromLeft ? rand(width * 0.08, width * 0.7) : rand(width * 0.3, width * 0.92);
    const startY = rand(-10, height * 0.36);
    const speed = rand(3.2, 6.2);
    meteors.push({ x: startX, y: startY, vx: fromLeft ? speed : -speed, vy: rand(1.7, 3.4),
      length: rand(65, width < 700 ? 115 : 175), life: 0, maxLife: rand(26, 42), alpha: rand(0.45, 0.8) });
    nextMeteorAt = now + rand(4200, 9000);
  }

  function draw(now = performance.now(), staticFrame = false) {
    if (!staticFrame && now - lastDrawAt < frameInterval) {
      raf = requestAnimationFrame(draw);
      return;
    }
    lastDrawAt = now;
    ctx.clearRect(0, 0, width, height);
    const delta = lastTime ? Math.min(2, (now - lastTime) / 16.67) : 1;
    lastTime = now;
    frame++;
    /* Stars stay fixed relative to the pointer; only slow drift is animated. */

    for (const s of stars) {
      const twinkle = reduceMotion ? 0 : Math.sin(frame * s.pulse + s.phase) * 0.28;
      const alpha = clamp(s.alpha + twinkle, 0.08, 1);
      const px = s.x + parallaxX * s.depth * 9;
      const py = s.y + parallaxY * s.depth * 7;
      ctx.beginPath();
      ctx.fillStyle = s.blue ? `rgba(151,190,255,${alpha})` : `rgba(236,245,255,${alpha})`;
      ctx.shadowBlur = 0;
      ctx.arc(px, py, s.radius, 0, Math.PI * 2);
      ctx.fill();

      if (!reduceMotion && s.cross && alpha > 0.66) {
        ctx.shadowBlur = 0;
        ctx.strokeStyle = `rgba(182,211,255,${alpha * 0.36})`;
        ctx.lineWidth = 0.55;
        ctx.beginPath();
        ctx.moveTo(px - 4.5, py); ctx.lineTo(px + 4.5, py);
        ctx.moveTo(px, py - 4.5); ctx.lineTo(px, py + 4.5);
        ctx.stroke();
      }
      if (!reduceMotion && !staticFrame) {
        s.y += s.drift * delta;
        if (s.y > height + 3) { s.y = -3; s.x = rand(0, width); }
      }
    }
    ctx.shadowBlur = 0;

    if (!reduceMotion && !staticFrame) {
      addMeteor(now);
      meteors = meteors.filter(m => m.life < m.maxLife);
      for (const m of meteors) {
        m.x += m.vx * delta; m.y += m.vy * delta; m.life += delta;
        const lifeRatio = m.life / m.maxLife;
        const fade = Math.min(1, lifeRatio * 5, (1 - lifeRatio) * 4) * m.alpha;
        const tailX = m.x - m.vx * (m.length / 7.2);
        const tailY = m.y - m.vy * (m.length / 7.2);
        const gradient = ctx.createLinearGradient(m.x, m.y, tailX, tailY);
        gradient.addColorStop(0, `rgba(235,248,255,${fade})`);
        gradient.addColorStop(0.22, `rgba(139,184,255,${fade * 0.65})`);
        gradient.addColorStop(1, 'rgba(118,145,255,0)');
        ctx.beginPath(); ctx.moveTo(m.x, m.y); ctx.lineTo(tailX, tailY);
        ctx.strokeStyle = gradient; ctx.lineWidth = 1.25; ctx.shadowBlur = 10;
        ctx.shadowColor = '#7aa8ff'; ctx.stroke();
        ctx.beginPath(); ctx.arc(m.x, m.y, 1.25, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255,255,255,${fade})`; ctx.fill();
      }
      ctx.shadowBlur = 0;
      raf = requestAnimationFrame(draw);
    }
  }

  function stop() { if (raf) cancelAnimationFrame(raf); raf = 0; }
  function start() { stop(); lastTime = 0; draw(performance.now()); }
  function motionChanged(event) {
    reduceMotion = event.matches;
    if (reduceMotion) { stop(); draw(performance.now(), true); }
    else if (!document.hidden) start();
  }

  window.addEventListener('resize', resize, { passive: true });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop();
    else if (!reduceMotion) start();
    else draw(performance.now(), true);
  });
  if (motionQuery.addEventListener) motionQuery.addEventListener('change', motionChanged);
  else if (motionQuery.addListener) motionQuery.addListener(motionChanged);

  resize();
  if (!reduceMotion && !document.hidden) start();
})();

/* ===== END frontend/assets/scripts/portal/space.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/site-sync.js ===== */
/* Stable console UX: no background full-page reloads during work.
   The notification counter and runtime status are refreshed independently. */
(() => {'use strict';document.body.dataset.autoRefresh='off';})();

/* ===== END frontend/assets/scripts/portal/site-sync.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/bot-activity-live.js ===== */
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

/* ===== END frontend/assets/scripts/portal/bot-activity-live.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/student-app-theme-designer.js ===== */
(() => {
  'use strict';
  const form = document.getElementById('student-app-theme-form');
  if (!form) return;
  const saveTitle = document.getElementById('theme-save-title');
  const liveStatus = document.getElementById('theme-live-status');
  const csrf = form.querySelector('input[name="csrf_token"]')?.value || '';
  let saveSequence = 0;
  function applySelection(input) {
    if (!input) return;
    const card = input.closest('.theme-card');
    if (!card) return;
    form.querySelectorAll('.theme-card').forEach((item) => {
      const radio = item.querySelector('input[type="radio"]');
      item.classList.toggle('is-selected', Boolean(radio && radio.checked));
    });
    const title = card.dataset.themeTitle || 'Выбранная тема';
    if (saveTitle) saveTitle.textContent = title;
    const preview = {'theme-preview-label':title,'theme-preview-description':card.dataset.themeDescription||'','theme-preview-emoji':card.dataset.themeEmoji||'','theme-preview-object':card.dataset.themeObject||'','theme-preview-season-title':title};
    Object.entries(preview).forEach(([id,value]) => { const node=document.getElementById(id); if(node) node.textContent=value; });
  }
  form.addEventListener('change', (event) => {
    if (!(event.target instanceof HTMLInputElement) || event.target.name !== 'season') return;
    applySelection(event.target);
    const url = form.dataset.liveUrl;
    if (!url) return;
    const sequence = ++saveSequence;
    if (liveStatus) liveStatus.textContent = 'Применяем тему…';
    const body = new URLSearchParams({season:event.target.value,csrf_token:csrf});
    fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-CSRF-Token':csrf,'X-Requested-With':'XMLHttpRequest'},body:body.toString()})
      .then(response => { if(!response.ok) throw new Error('save_failed'); return response.json(); })
      .then(result => { if(sequence===saveSequence && result.ok && liveStatus) liveStatus.textContent=`Тема «${result.label}» сохранена. Синхронизация запущена.`; })
      .catch(() => { if(sequence===saveSequence && liveStatus) liveStatus.textContent='Не удалось сохранить тему. Проверьте соединение и используйте кнопку «Применить тему».'; });
  });
  const initiallySelected=form.querySelector('input[name="season"]:checked');
  if(initiallySelected) applySelection(initiallySelected);
})();

/* ===== END frontend/assets/scripts/portal/student-app-theme-designer.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/theme-live-sync.js ===== */
/* Live theme propagation for already-open internal website tabs. */
(() => {
  'use strict';
  const body = document.body;
  // Theme polling is for the authenticated internal panel only. Avoid repeated
  // /api/visual-theme -> /auth/login redirects on login and OTP screens.
  if (!body || !body.classList.contains('uc-body') || body.dataset.authenticated !== '1') return;
  const reduceMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  let busy = false;
  let pollTimer = 0;
  const POLL_INTERVAL = 30000;
  function applyTheme(data) {
    if (!data || !/^[a-z0-9_]+$/.test(data.theme || '')) return;
    if (data.build && body.dataset.build && data.build !== body.dataset.build) {
      // Rebuilds are activated only when the server has published fingerprinted assets.
      window.location.reload();
      return;
    }
    const changed = body.dataset.theme !== data.theme || body.dataset.season !== data.theme;
    body.dataset.theme = data.theme;
    body.dataset.season = data.theme;
    const vars = {
      '--office-accent': data.accent,
      '--office-secondary': data.secondary,
      '--office-depth': data.depth,
      '--office-accent-rgb': data.accent_rgb,
      '--office-secondary-rgb': data.secondary_rgb,
      '--season-accent': data.accent,
      '--season-secondary': data.secondary
    };
    for (const [name, value] of Object.entries(vars)) {
      if (typeof value === 'string' && (/^#[0-9a-f]{6}$/i.test(value) || /^\d{1,3},\s*\d{1,3},\s*\d{1,3}$/.test(value))) {
        body.style.setProperty(name, value);
      }
    }
    // Messenger applies palette tokens directly; skip the full-page animation
    // and forced synchronous layout so its controls repaint immediately.
    if (changed && !reduceMotion() && !body.classList.contains('messenger-standalone')) {
      body.classList.remove('theme-changing');
      void body.offsetWidth;
      body.classList.add('theme-changing');
      window.setTimeout(() => body.classList.remove('theme-changing'), 1400);
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta && data.depth) meta.content = data.depth;
  }
  async function poll() {
    if (busy || document.visibilityState !== 'visible' || !navigator.onLine) return;
    busy = true;
    try {
      const response = await fetch('/api/visual-theme', {credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json'}});
      if (response.status === 401 || response.status === 403) return;
      if (!response.ok) return;
      applyTheme(await response.json());
    } catch (_) { /* Theme sync is progressive enhancement; never disrupt panel work. */ }
    finally { busy = false; }
  }
  const onLocalTheme = event => {
    const value = event && event.data;
    if (!value || value.type !== 'theme-save') return;
    applyTheme({
      theme: value.theme, accent: value.accent, secondary: value.secondary,
      depth: value.depth,
      accent_rgb: typeof value.accent === 'string' && /^#[0-9a-f]{6}$/i.test(value.accent)
        ? [1, 3, 5].map(index => parseInt(value.accent.slice(index, index + 2), 16)).join(', ') : undefined,
      secondary_rgb: typeof value.secondary === 'string' && /^#[0-9a-f]{6}$/i.test(value.secondary)
        ? [1, 3, 5].map(index => parseInt(value.secondary.slice(index, index + 2), 16)).join(', ') : undefined
    });
  };
  try {
    const channel = new BroadcastChannel('student-council-theme-v60');
    window.__portalThemeChannel = channel;
    channel.addEventListener('message', onLocalTheme);
  } catch (_) {
    window.addEventListener('storage', event => {
      if (event.key === 'student-council-theme-v60' && event.newValue) {
        try { onLocalTheme({data: JSON.parse(event.newValue)}); } catch (__) {}
      }
    });
  }

  if (body.classList.contains('theme-changing') && !reduceMotion()) {
    window.setTimeout(() => body.classList.remove('theme-changing'), 1400);
  }
  function schedulePoll(delay = POLL_INTERVAL) {
    if (pollTimer) window.clearTimeout(pollTimer);
    pollTimer = 0;
    if (document.visibilityState !== 'visible') return;
    pollTimer = window.setTimeout(async () => {
      pollTimer = 0;
      await poll();
      schedulePoll(POLL_INTERVAL);
    }, Math.max(0, delay));
  }
  schedulePoll(0);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') { if (pollTimer) window.clearTimeout(pollTimer); pollTimer = 0; }
    else schedulePoll(0);
  });
  window.addEventListener('online', () => schedulePoll(0));
})();

/* ===== END frontend/assets/scripts/portal/theme-live-sync.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/announcement-preview.js ===== */
(() => {
  'use strict';
  const title = document.getElementById('announcement-title');
  const body = document.getElementById('announcement-body');
  const previewTitle = document.getElementById('announcement-preview-title');
  const previewBody = document.getElementById('announcement-preview-body');
  if (!title || !body || !previewTitle || !previewBody) return;
  title.addEventListener('input', () => {
    previewTitle.textContent = title.value || 'Заголовок объявления';
  });
  body.addEventListener('input', () => {
    previewBody.textContent = body.value || 'Текст объявления появится здесь.';
  });
})();

/* ===== END frontend/assets/scripts/portal/announcement-preview.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/calendar.js ===== */
/* Unified calendar UI: accessible month and agenda views, filters and contextual actions. */
(() => {
  'use strict';
  const root = document.getElementById('staff-calendar');
  const dataNode = document.getElementById('calendar-data');
  if (!root || !dataNode) return;
  let events = [];
  try { events = JSON.parse(dataNode.textContent || '[]'); } catch (_) { events = []; }
  const $ = (selector) => root.querySelector(selector);
  const now = new Date();
  const dateKey = (date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const fromKey = (key) => { const [year, month, day] = String(key || '').slice(0, 10).split('-').map(Number); return new Date(year || now.getFullYear(), (month || 1) - 1, day || 1, 12, 0, 0, 0); };
  const eventDate = (event) => String(event.start || '').slice(0, 10);
  const monthStart = (date) => new Date(date.getFullYear(), date.getMonth(), 1, 12);
  const monthEndExclusive = (date) => new Date(date.getFullYear(), date.getMonth() + 1, 1, 12);
  const monthTitle = (date) => new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric' }).format(date);
  const longDate = (key) => new Intl.DateTimeFormat('ru-RU', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' }).format(fromKey(key));
  const capitalise = (value) => value ? value[0].toLocaleUpperCase('ru-RU') + value.slice(1) : value;
  const timePart = (value) => { const match = String(value || '').match(/T(\d{2}:\d{2})/); return match ? match[1] : ''; };
  const timeLabel = (event) => { if (event.allDay || !timePart(event.start)) return event.timeRange || 'Весь день'; const start = timePart(event.start); const end = timePart(event.end); return end ? `${start}–${end}` : start; };
  const typeLabel = (event) => event.type === 'lesson' ? 'Занятие' : (event.isAnnouncement ? 'Публикация в чаты' : 'Мероприятие');
  const make = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined && text !== null) node.textContent = String(text); return node; };
  const addMeta = (container, icon, text) => { if (!text) return; const row = make('div', 'calendar-detail-meta-row'); row.append(make('span', '', icon), make('span', '', text)); container.append(row); };
  const withCalendarDate = (href, date = selectedDay) => { if (!href) return href; const url = new URL(href, window.location.origin); if (url.origin === window.location.origin && url.searchParams.get('return_to') === 'calendar') url.searchParams.set('date', date); return `${url.pathname}${url.search}${url.hash}`; };
  const addActionLink = (container, label, href, variant = 'btn-soft') => { if (!href) return; const link = make('a', `btn ${variant}`, label); link.href = withCalendarDate(href); container.append(link); };
  const addActionForm = (container, label, href, danger = false, confirmText = '') => {
    if (!href) return;
    const form = make('form'); form.method = 'post'; form.action = href;
    if (confirmText) form.dataset.confirm = confirmText;
    const token = make('input'); token.type = 'hidden'; token.name = 'csrf_token'; token.value = root.dataset.csrfToken || '';
    const returnTo = make('input'); returnTo.type = 'hidden'; returnTo.name = 'return_to'; returnTo.value = 'calendar';
    const calendarDate = make('input'); calendarDate.type = 'hidden'; calendarDate.name = 'calendar_date'; calendarDate.value = selectedDay;
    const button = make('button', `btn ${danger ? 'btn-danger' : 'btn-primary'}`, label); button.type = 'submit';
    form.append(token, returnTo, calendarDate, button);
    form.addEventListener('submit', (event) => { if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) event.preventDefault(); });
    container.append(form);
  };
  const todayKey = dateKey(now);
  const requestedDate = /^\d{4}-\d{2}-\d{2}$/.test(root.dataset.initialDate || '') ? root.dataset.initialDate : todayKey;
  let currentMonth = monthStart(fromKey(requestedDate)), selectedDay = requestedDate, selectedEventId = '', view = 'month', activeEvents = [];
  const search = $('#calendar-search'), typeFilter = $('#calendar-type-filter'), directionFilter = $('#calendar-direction-filter');
  if (root.dataset.initialDirection) directionFilter.value = root.dataset.initialDirection;
  if (['lesson', 'event'].includes(root.dataset.initialKind)) typeFilter.value = root.dataset.initialKind;
  const monthGrid = $('#calendar-month-grid'), monthView = $('#calendar-month-view'), agendaView = $('#calendar-agenda-view'), agendaList = $('#calendar-agenda-list');
  const dayEventsNode = $('#calendar-day-events'), detailSection = $('#calendar-event-detail'), detailContent = $('#calendar-detail-content');
  const createLinks = [['[data-calendar-create-lesson]', 'lesson'], ['[data-calendar-create-lesson-side]', 'lesson'], ['[data-calendar-create-event]', 'event'], ['[data-calendar-create-event-side]', 'event']];

  function filteredEvents() {
    const term = (search.value || '').trim().toLocaleLowerCase('ru-RU'), type = typeFilter.value, direction = directionFilter.value;
    return events.filter((event) => {
      if (type !== 'all' && event.type !== type) return false;
      if (direction !== 'all') { const ids = Array.isArray(event.directionIds) ? event.directionIds.map(String) : [String(event.directionId || '')]; if (!ids.includes(direction)) return false; }
      if (term && ![event.title, event.direction, event.description, event.location, event.teacher].some((part) => String(part || '').toLocaleLowerCase('ru-RU').includes(term))) return false;
      return true;
    }).sort((a, b) => String(a.start).localeCompare(String(b.start)) || String(a.title).localeCompare(String(b.title), 'ru'));
  }
  function eventsInMonth(source = activeEvents) { const start = dateKey(monthStart(currentMonth)), end = dateKey(monthEndExclusive(currentMonth)); return source.filter((event) => eventDate(event) >= start && eventDate(event) < end); }
  function syncCreateLinks() {
    createLinks.forEach(([selector]) => { const link = $(selector); if (!link) return; const url = new URL(link.getAttribute('href'), window.location.origin); url.searchParams.set('date', selectedDay); url.searchParams.set('return_to', 'calendar'); link.href = `${url.pathname}${url.search}${url.hash}`; });
  }
  function updateSummary() { const inMonth = eventsInMonth(); const onDay = activeEvents.filter((event) => eventDate(event) === selectedDay); $('#calendar-count-day').textContent = String(onDay.length); $('#calendar-count-lessons').textContent = String(inMonth.filter((event) => event.type === 'lesson').length); $('#calendar-count-events').textContent = String(inMonth.filter((event) => event.type === 'event' && !event.isAnnouncement).length); }

  function renderMonth() {
    $('#calendar-month-title').textContent = capitalise(monthTitle(currentMonth)); monthGrid.replaceChildren();
    const first = monthStart(currentMonth), mondayOffset = (first.getDay() + 6) % 7;
    const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - mondayOffset, 12), byDate = new Map();
    activeEvents.forEach((event) => { const key = eventDate(event); if (!byDate.has(key)) byDate.set(key, []); byDate.get(key).push(event); });
    for (let index = 0; index < 42; index += 1) {
      const date = new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index, 12), key = dateKey(date), dayItems = byDate.get(key) || [];
      const cell = make('button', 'calendar-day-cell'); cell.type = 'button'; cell.dataset.date = key; cell.setAttribute('role', 'gridcell'); cell.setAttribute('aria-pressed', key === selectedDay ? 'true' : 'false'); cell.setAttribute('aria-label', `${longDate(key)}, событий: ${dayItems.length}`);
      if (date.getMonth() !== currentMonth.getMonth()) cell.classList.add('is-outside'); if (key === todayKey) cell.classList.add('is-today'); if (key === selectedDay) cell.classList.add('is-selected');
      cell.append(make('span', 'calendar-day-number', date.getDate()));
      dayItems.slice(0, 3).forEach((event) => { const chip = make('span', `calendar-event-chip calendar-event-chip--${event.type}${event.isAnnouncement ? ' is-announcement' : ''}`, `${timePart(event.start) ? `${timePart(event.start)} ` : ''}${event.title}`); chip.dataset.eventId = event.id; cell.append(chip); });
      if (dayItems.length > 3) cell.append(make('span', 'calendar-more-events', `+ ещё ${dayItems.length - 3}`));
      cell.addEventListener('click', (click) => { const chip = click.target.closest('[data-event-id]'); if (date.getMonth() !== currentMonth.getMonth()) currentMonth = monthStart(date); selectedDay = key; selectedEventId = chip ? chip.dataset.eventId : ''; render(); });
      monthGrid.append(cell);
    }
  }
  function renderAgenda() {
    agendaList.replaceChildren(); const list = eventsInMonth();
    if (!list.length) { agendaList.append(make('div', 'calendar-no-results', 'В этом месяце нет событий по выбранным фильтрам. Попробуйте изменить поиск или тип.')); return; }
    const byDate = new Map(); list.forEach((event) => { const key = eventDate(event); if (!byDate.has(key)) byDate.set(key, []); byDate.get(key).push(event); });
    [...byDate.keys()].sort().forEach((key) => {
      const group = make('section', 'calendar-agenda-group'); group.append(make('h3', 'calendar-agenda-date', capitalise(longDate(key))));
      byDate.get(key).forEach((event) => { const row = make('button', `calendar-agenda-item${event.id === selectedEventId ? ' is-selected' : ''}${event.isAnnouncement ? ' is-announcement' : ''}`); row.type = 'button'; row.append(make('span', 'calendar-agenda-time', timeLabel(event)), make('span', `calendar-agenda-mark is-${event.type}`)); const copy = make('span', 'calendar-agenda-copy'); copy.append(make('strong', '', event.title), make('small', '', `${event.direction || 'Без направления'}${event.location ? ` · ${event.location}` : ''}`)); row.append(copy); row.addEventListener('click', () => { selectedDay = key; selectedEventId = event.id; render(); }); group.append(row); });
      agendaList.append(group);
    });
  }
  function renderDayEvents() {
    dayEventsNode.replaceChildren(); const list = activeEvents.filter((event) => eventDate(event) === selectedDay);
    $('#calendar-selected-date').textContent = capitalise(new Intl.DateTimeFormat('ru-RU', { weekday: 'short', day: 'numeric', month: 'long' }).format(fromKey(selectedDay)));
    const countLabel = list.length === 1 ? 'событие' : (list.length > 1 && list.length < 5 ? 'события' : 'событий');
    $('#calendar-day-subtitle').textContent = list.length ? `${list.length} ${countLabel} в выбранный день` : 'На выбранную дату пока ничего не запланировано.';
    if (!list.length) { const empty = make('div', 'calendar-empty-day'); empty.append(make('div', 'calendar-empty-icon', '◷'), make('strong', '', 'Свободный день'), make('div', '', 'Здесь появятся новые занятия и мероприятия после создания.')); dayEventsNode.append(empty); return; }
    list.forEach((event) => { const button = make('button', `calendar-day-event${event.id === selectedEventId ? ' is-selected' : ''}${event.isAnnouncement ? ' is-announcement' : ''}`); button.type = 'button'; const mark = make('span', `calendar-day-event-mark is-${event.type}`); const copy = make('span', 'calendar-day-event-copy'); copy.append(make('strong', '', event.title), make('small', '', `${timeLabel(event)} · ${event.direction || 'Без направления'}${event.location ? ` · ${event.location}` : ''}`)); button.append(mark, copy); button.addEventListener('click', () => { selectedEventId = event.id; render(); }); dayEventsNode.append(button); });
  }
  function renderEventDetail() {
    const event = activeEvents.find((item) => item.id === selectedEventId && eventDate(item) === selectedDay);
    if (!event) { detailSection.hidden = true; dayEventsNode.hidden = false; return; }
    detailSection.hidden = false; dayEventsNode.hidden = true; detailContent.replaceChildren();
    detailContent.append(make('span', `calendar-detail-type is-${event.type}`, `${event.type === 'lesson' ? '●' : '◆'} ${typeLabel(event)}`), make('h3', 'calendar-detail-title', event.title));
    const meta = make('div', 'calendar-detail-meta');
    addMeta(meta, '◷', `${capitalise(longDate(selectedDay))} · ${timeLabel(event)}`);
    addMeta(meta, '◈', event.direction || 'Направление не указано');
    if (event.isAnnouncement) {
      addMeta(meta, '◉', event.status || 'Автопубликация запланирована');
      addMeta(meta, '✉', `Будет отправлено в: ${event.chatSummary || 'Чаты не выбраны'}`);
    } else {
      if (event.location) addMeta(meta, '⌖', event.location);
      if (event.type === 'lesson') { addMeta(meta, '♙', event.teacher ? `Ответственный: ${event.teacher}` : 'Ответственный не указан'); addMeta(meta, '◴', event.duration ? `Продолжительность: ${event.duration} мин.` : 'Продолжительность не указана'); if (event.capacity) addMeta(meta, '◎', `Мест: ${event.capacity}`); }
      else { addMeta(meta, '◎', `Мест на эту дату: ${event.capacity || 0}`); addMeta(meta, '◉', event.status || 'Статус не указан'); addMeta(meta, '✉', `Чаты объявления: ${event.chatSummary || 'Чаты не выбраны'}`); }
    }
    detailContent.append(meta); if (event.description) detailContent.append(make('p', 'calendar-detail-description', event.description));
    const actions = make('div', 'calendar-detail-actions');
    if (event.type === 'lesson') { if (event.editUrl) addActionLink(actions, 'Изменить занятие', event.editUrl, 'btn-primary'); if (event.publishUrl) addActionForm(actions, 'Отправить в TG / VK / MAX', event.publishUrl, false, 'Опубликовать объявление в чатах направления?'); if (event.deleteUrl) addActionForm(actions, 'Удалить', event.deleteUrl, true, 'Удалить занятие из расписания?'); }
    else if (event.isAnnouncement) { if (event.publishUrl) addActionForm(actions, 'Отправить сейчас', event.publishUrl, false, 'Отправить карточку мероприятия немедленно в выбранные чаты вместо ожидания запланированного времени?'); }
    else { if (event.participantsUrl) addActionLink(actions, 'Участники и посещаемость', withCalendarDate(event.participantsUrl), 'btn-primary'); if (event.publishUrl) addActionForm(actions, 'Отправить в выбранные чаты', event.publishUrl, false, 'Повторно отправить карточку мероприятия только в назначенные ему чаты?'); if (event.closeUrl) addActionForm(actions, 'Закрыть мероприятие', event.closeUrl, true, 'Закрыть мероприятие и зафиксировать статистику посещаемости?'); }
    if (event.detailUrl && !(event.type === 'lesson' && event.editUrl)) addActionLink(actions, 'Открыть раздел', event.detailUrl);
    if (actions.childNodes.length) detailContent.append(actions);
  }
  function render() {
    activeEvents = filteredEvents(); renderMonth(); renderAgenda(); renderDayEvents(); renderEventDetail(); updateSummary(); syncCreateLinks();
    monthView.hidden = view !== 'month'; agendaView.hidden = view !== 'agenda';
    root.querySelectorAll('[data-calendar-view]').forEach((button) => { const active = button.dataset.calendarView === view; button.classList.toggle('is-active', active); button.setAttribute('aria-pressed', active ? 'true' : 'false'); });
  }
  function moveMonth(delta) { currentMonth = new Date(currentMonth.getFullYear(), currentMonth.getMonth() + delta, 1, 12); selectedDay = dateKey(currentMonth); selectedEventId = ''; render(); }
  $('#calendar-prev').addEventListener('click', () => moveMonth(-1));
  $('#calendar-next').addEventListener('click', () => moveMonth(1));
  $('#calendar-today').addEventListener('click', () => { currentMonth = monthStart(now); selectedDay = todayKey; selectedEventId = ''; render(); });
  root.querySelectorAll('[data-calendar-view]').forEach((button) => button.addEventListener('click', () => { view = button.dataset.calendarView; render(); }));
  $('#calendar-back-to-day').addEventListener('click', () => { selectedEventId = ''; render(); });
  [search, typeFilter, directionFilter].forEach((element) => element.addEventListener(element === search ? 'input' : 'change', () => { selectedEventId = ''; render(); }));
  render();
})();

/* ===== END frontend/assets/scripts/portal/calendar.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/notifications.js ===== */
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

/* ===== END frontend/assets/scripts/portal/notifications.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/journal-ux.js ===== */
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

/* ===== END frontend/assets/scripts/portal/journal-ux.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/pro-workspace.js ===== */
/* Dashboard depth is handled by GPU-friendly CSS hover/focus transitions.
   No pointermove listeners or per-frame layout measurement on cards. */
(() => {
  'use strict';
  const cards = document.querySelectorAll('.galaxy-dashboard .mission-kpi, .galaxy-dashboard .galaxy-tool, .galaxy-dashboard .galaxy-direction');
  cards.forEach(card => card.classList.add('depth-card-2026'));
})();

/* ===== END frontend/assets/scripts/portal/pro-workspace.js ===== */

/* ===== BEGIN frontend/assets/scripts/shared/galaxy-depth-plus.js ===== */
/* Galaxy Depth Plus: theme designer uses fixed, non-pointer-reactive lighting. */
(() => {
  'use strict';
  const studio = document.querySelector('.theme-page');
  const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
  if (!studio) return;

  // Pointer tracking is deliberately disabled here. Hover styling is static,
  // predictable at every zoom level, and keyboard/touch friendly.
  // The CSS layer supplies the ambient artwork and respects reduced-motion.
  if (motion.matches) studio.classList.add('theme-reduced-motion');
})();

/* ===== END frontend/assets/scripts/shared/galaxy-depth-plus.js ===== */

/* ===== BEGIN frontend/assets/scripts/shared/cosmos-world-2026.js ===== */
/* Pause background effects when the document is hidden. CSS hover/focus
   provides responsive card motion without pointer tracking or RAF loops. */
(() => {
  'use strict';
  if (!document.querySelector('.cosmos-field')) return;
  const sync = () => document.documentElement.classList.toggle('cosmos-paused', document.hidden);
  document.addEventListener('visibilitychange', sync);
  window.addEventListener('pageshow', sync);
  sync();
})();

/* ===== END frontend/assets/scripts/shared/cosmos-world-2026.js ===== */

/* ===== BEGIN frontend/assets/scripts/shared/page-entry-motion.js ===== */
/* Short, staged spacecraft-console arrival for the login page and Student App.
   Animation is transform/opacity only. No media, forced reload, storage or render loop. */
(() => {
  'use strict';

  const motionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const reduceMotion = () => Boolean(motionQuery && motionQuery.matches);
  const LOGIN_STEPS = [
    ['.premium-visual', 0],
    ['.premium-story-top', 70],
    ['.premium-story-bottom', 150],
    ['.premium-story-footer', 220],
    ['.premium-auth', 140],
    ['.premium-welcome', 250],
    ['.premium-auth-steps', 320],
    ['.premium-form', 390],
    ['.premium-verify-note', 470],
    ['.premium-auth-bottom', 520]
  ];

  function reveal(element, delay = 0, duration = 660) {
    if (!element || reduceMotion()) return;
    element.style.setProperty('--ship-enter-delay', `${delay}ms`);
    element.style.setProperty('--ship-enter-duration', `${duration}ms`);
    const onEnd = event => {
      if (event.target !== element || !['ship-block-arrival', 'ship-scene-arrival', 'student-ship-arrival'].includes(event.animationName)) return;
      element.classList.remove('ship-entry-block');
      element.style.removeProperty('--ship-enter-delay');
      element.style.removeProperty('--ship-enter-duration');
      element.removeEventListener('animationend', onEnd);
    };
    element.addEventListener('animationend', onEnd);
    element.classList.add('ship-entry-block');
  }

  function loginTargets() {
    const result = [];
    LOGIN_STEPS.forEach(([selector, delay]) => {
      const node = document.querySelector(selector);
      if (node) result.push([node, delay, selector === '.premium-visual' ? 840 : 660]);
    });
    return result;
  }

  function studentTargets() {
    const app = document.getElementById('app');
    if (!app) return [];
    const result = [];
    const add = (node, delay, duration = 650) => { if (node) result.push([node, delay, duration]); };
    add(document.querySelector('.student-orbit-scene'), 0, 900);
    add(app.querySelector(':scope > .hero'), 70);
    add(app.querySelector(':scope > .nav'), 135);
    add(app.querySelector(':scope > .student-main'), 180);
    add(app.querySelector(':scope > .mission-bottom-nav'), 270);
    add(app.querySelector(':scope > .registration'), 120);

    const dashboard = app.querySelector('.command-dashboard');
    if (dashboard) {
      dashboard.querySelectorAll(':scope > .command-hero, :scope > .command-metrics, :scope > .command-next-row, :scope > .mission-student-today, :scope > .student-announcements, :scope > .command-section-header').forEach((node, index) => add(node, 230 + index * 72));
    } else {
      const main = app.querySelector(':scope > .student-main');
      if (main) main.querySelectorAll(':scope > :not(.mission-modal-backdrop):not(.student-notice-backdrop)').forEach((node, index) => add(node, 230 + Math.min(index, 5) * 68));
    }
    // Keep order unique if a future template wraps one of the entry targets.
    const seen = new Set();
    return result.filter(([node]) => {
      if (seen.has(node)) return false;
      seen.add(node);
      return true;
    });
  }

  function runSequence(targets) {
    if (reduceMotion()) {
      targets.forEach(([node]) => {
        if (!node) return;
        node.classList.remove('ship-entry-block');
        node.style.removeProperty('--ship-enter-delay');
        node.style.removeProperty('--ship-enter-duration');
      });
      return;
    }
    // Batch the single layout read needed to replay this sequence on BFCache restores.
    targets.forEach(([node]) => { if (node) node.classList.remove('ship-entry-block'); });
    targets.forEach(([node, delay, duration]) => {
      if (!node) return;
      node.style.setProperty('--ship-enter-delay', `${delay}ms`);
      node.style.setProperty('--ship-enter-duration', `${duration}ms`);
    });
    void document.body.offsetWidth;
    targets.forEach(([node, delay, duration]) => reveal(node, delay, duration));
  }

  function runLogin() {
    runSequence(loginTargets());
  }

  function runStudent() {
    const app = document.getElementById('app');
    if (!app) return;
    if (app.querySelector('.loading')) {
      // Wait for the first real render, but only observe this small app root.
      const observer = new MutationObserver(() => {
        if (!app.isConnected) { observer.disconnect(); return; }
        if (app.querySelector('.loading')) return;
        observer.disconnect();
        runSequence(studentTargets());
      });
      observer.observe(app, { childList: true, subtree: true });
      return;
    }
    runSequence(studentTargets());
  }

  let entryPlayed = false;
  function playEntry() {
    // The page-entry sequence owns entry motion exactly once per document.
    // Student App has its own first-render animation and must not be animated a second time here.
    if (entryPlayed) return;
    entryPlayed = true;
    if (reduceMotion()) return;
    if (document.body.classList.contains('is-login-page')) runLogin();
    // Student App is animated by student_app.js after its first successful render.
    // Admin routes are intentionally not animated as a whole: forms and navigation stay visually stable.
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', playEntry, { once: true });
  else playEntry();
  window.addEventListener('pageshow', event => { if (event.persisted) playEntry(); });
})();

/* ===== END frontend/assets/scripts/shared/page-entry-motion.js ===== */

/* ===== BEGIN frontend/assets/scripts/shared/admin-console-entry-v52.js ===== */
/* V52.1 · Short starfield arrival for admin panel and Student App. */
(() => {
  'use strict';
  const isStudent = document.body.classList.contains('student-app-body');
  const isAdmin = document.body.classList.contains('role-super_admin');
  if (!isStudent && !isAdmin) return;
  const sky = document.querySelector(isStudent ? '[data-student-entry-sky]' : '[data-admin-entry-sky]');
  if (!sky) return;
  const reduceMotion = Boolean(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  if (reduceMotion) { sky.remove(); return; }
  const seenKey = isStudent ? 'student-app-entry-sky-v52' : 'student-council-admin-entry-v52';
  let alreadyShown = false;
  try {
    alreadyShown = window.sessionStorage.getItem(seenKey) === '1';
    if (!alreadyShown) window.sessionStorage.setItem(seenKey, '1');
  } catch (_) { /* Storage is optional; effect is decorative. */ }
  if (alreadyShown) { sky.remove(); return; }
  window.requestAnimationFrame(() => sky.classList.add('is-live'));
  window.setTimeout(() => { if (sky.isConnected) sky.remove(); }, 2800);
})();

/* ===== END frontend/assets/scripts/shared/admin-console-entry-v52.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/orders-archive.js ===== */
/* Accessible upload modal and client-side filter for the private order archive. */
(() => {
  'use strict';

  const initOrdersArchive = () => {
    const root = document.querySelector('[data-orders-archive]');
    const modal = document.querySelector('[data-order-modal]');
    if (!root || !modal || modal.dataset.initialized === 'true') return;
    modal.dataset.initialized = 'true';

    const dialog = modal.querySelector('[role="dialog"]');
    const openers = Array.from(root.querySelectorAll('[data-order-modal-open]'));
    const closers = Array.from(modal.querySelectorAll('[data-order-modal-close]'));
    const fileInput = modal.querySelector('[data-order-file]');
    const fileSelected = modal.querySelector('[data-order-file-selected]');
    const form = modal.querySelector('[data-order-upload-form]');
    const submitButton = modal.querySelector('[data-order-submit]');
    const search = root.querySelector('[data-order-search]');
    const rows = Array.from(root.querySelectorAll('[data-order-row]'));
    const noResults = root.querySelector('[data-order-no-results]');
    let returnFocus = null;
    let priorOverflow = '';

    const focusable = () => Array.from(dialog.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((node) => !node.hasAttribute('hidden') && node.getAttribute('aria-hidden') !== 'true');

    const openModal = (trigger) => {
      if (modal.hidden) {
        returnFocus = trigger || document.activeElement;
        priorOverflow = document.body.style.overflow;
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        const first = modal.querySelector('#orders-target-id:not([disabled])') || closers[0] || dialog;
        window.requestAnimationFrame(() => first.focus());
      }
    };

    const closeModal = () => {
      if (modal.hidden) return;
      modal.hidden = true;
      modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = priorOverflow;
      if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
    };

    openers.forEach((button) => button.addEventListener('click', () => openModal(button)));
    closers.forEach((button) => button.addEventListener('click', closeModal));
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModal();
    });

    document.addEventListener('keydown', (event) => {
      if (modal.hidden) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        closeModal();
        return;
      }
      if (event.key !== 'Tab') return;
      const elements = focusable();
      if (!elements.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    if (fileInput && fileSelected) {
      fileInput.addEventListener('change', () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) {
          fileSelected.textContent = 'Файл не выбран';
          return;
        }
        const sizeMb = file.size / (1024 * 1024);
        fileSelected.textContent = `${file.name} · ${sizeMb.toFixed(2)} МБ`;
        const extensionOk = /\.(pdf|docx)$/i.test(file.name);
        if (!extensionOk) {
          fileSelected.textContent += ' — разрешены только PDF и DOCX';
        } else if (file.size > 8 * 1024 * 1024) {
          fileSelected.textContent += ' — размер больше 8 МБ';
        }
      });
    }

    if (form && submitButton) {
      form.addEventListener('submit', (event) => {
        if (!form.reportValidity()) {
          event.preventDefault();
          return;
        }
        const file = fileInput && fileInput.files && fileInput.files[0];
        if (file && (!/\.(pdf|docx)$/i.test(file.name) || file.size > 8 * 1024 * 1024)) {
          event.preventDefault();
          if (fileSelected) {
            fileSelected.textContent = !/\.(pdf|docx)$/i.test(file.name)
              ? 'Разрешены только файлы PDF и DOCX.'
              : 'Файл больше 8 МБ. Выберите файл меньшего размера.';
          }
          if (fileInput) fileInput.focus();
          return;
        }
        // Frontend convenience only; server-side format/size validation remains authoritative.
        submitButton.disabled = true;
        submitButton.setAttribute('aria-busy', 'true');
        submitButton.textContent = 'Загрузка…';
      });
    }

    const filterRows = () => {
      if (!search || !rows.length) return;
      const query = search.value.trim().toLocaleLowerCase('ru-RU');
      let visible = 0;
      rows.forEach((row) => {
        const haystack = (row.dataset.orderSearch || row.textContent).toLocaleLowerCase('ru-RU');
        const match = !query || haystack.includes(query);
        row.hidden = !match;
        if (match) visible += 1;
      });
      if (noResults) noResults.hidden = visible !== 0;
    };
    if (search) search.addEventListener('input', filterRows);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOrdersArchive, { once: true });
  } else {
    initOrdersArchive();
  }
})();

/* ===== END frontend/assets/scripts/portal/orders-archive.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/messenger-monitoring-v63.js ===== */
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

/* ===== END frontend/assets/scripts/portal/messenger-monitoring-v63.js ===== */

/* ===== BEGIN frontend/assets/scripts/portal/statistics-workspace-v1913.js ===== */
/* Professional statistics workspace: shared filters, fast tables and safe CSV export. */
(() => {
  'use strict';

  const normalize = (value) => String(value || '').toLocaleLowerCase('ru-RU').replace(/\s+/g, ' ').trim();
  const safeText = (row) => normalize(row.innerText || row.textContent || '');
  const getRows = (tbody) => Array.from(tbody.querySelectorAll('tr')).filter((row) => {
    return !row.id && !row.classList.contains('stats-table-empty-row') && !row.querySelector('.empty');
  });

  const datePeriod = document.getElementById('stats-period-select');
  const dateFrom = document.getElementById('stats-date-from');
  const dateTo = document.getElementById('stats-date-to');
  const updateDateControls = () => {
    if (!datePeriod || !dateFrom || !dateTo) return;
    const custom = datePeriod.value === 'custom';
    dateFrom.disabled = !custom;
    dateTo.disabled = !custom;
    dateFrom.setAttribute('aria-disabled', String(!custom));
    dateTo.setAttribute('aria-disabled', String(!custom));
  };
  if (datePeriod) {
    document.querySelectorAll('[data-stats-period]').forEach((button) => {
      button.addEventListener('click', () => {
        datePeriod.value = button.dataset.statsPeriod || 'all';
        if (dateFrom) dateFrom.value = '';
        if (dateTo) dateTo.value = '';
        updateDateControls();
        const filterForm = datePeriod.closest('form');
        if (!filterForm) return;
        if (typeof filterForm.requestSubmit === 'function') filterForm.requestSubmit();
        else filterForm.submit();
      });
    });
    datePeriod.addEventListener('change', updateDateControls);
    [dateFrom, dateTo].filter(Boolean).forEach((input) => input.addEventListener('change', () => {
      datePeriod.value = 'custom';
      updateDateControls();
    }));
    const form = datePeriod.closest('form');
    if (form) form.addEventListener('submit', (event) => {
      if (datePeriod.value !== 'custom') return;
      if ((!dateFrom || !dateFrom.value) && (!dateTo || !dateTo.value)) {
        event.preventDefault();
        datePeriod.focus();
        window.alert('Для собственного периода укажите хотя бы одну границу даты.');
        return;
      }
      if (dateFrom && dateTo && dateFrom.value && dateTo.value && dateFrom.value > dateTo.value) {
        event.preventDefault();
        window.alert('Дата «С» не может быть позже даты «По».');
      }
    });
    updateDateControls();
  }

  document.querySelectorAll('table[data-statistics-table]').forEach((table) => {
    const tbody = table.tBodies && table.tBodies[0];
    if (!tbody) return;
    let allRows = getRows(tbody);
    // Keep table rows visually consistent with the Active Students register:
    // uncluttered cells, exact numeric values and compact semantic badges.
    const originalEmptyRows = Array.from(tbody.querySelectorAll('tr')).filter((row) => row.querySelector('.empty'));
    originalEmptyRows.forEach((row) => { row.dataset.statsEmpty = '1'; });

    const shell = document.createElement('div');
    shell.className = 'stats-table-toolbar';
    shell.setAttribute('role', 'group');
    shell.setAttribute('aria-label', 'Инструменты таблицы');

    let search = null;
    if (table.id !== 'direction-statistics-table') {
      const searchWrap = document.createElement('label');
      searchWrap.className = 'stats-table-search';
      const searchLabel = document.createElement('span');
      searchLabel.textContent = 'Быстрый поиск';
      search = document.createElement('input');
      search.type = 'search';
      search.placeholder = 'Имя, название, группа…';
      search.autocomplete = 'off';
      search.setAttribute('aria-label', 'Поиск по строкам таблицы');
      searchWrap.append(searchLabel, search);
      shell.append(searchWrap);
    }

    const pageSizeLabel = document.createElement('label');
    pageSizeLabel.className = 'stats-table-page-size';
    const pageSizeText = document.createElement('span');
    pageSizeText.textContent = 'Строк на странице';
    const pageSize = document.createElement('select');
    pageSize.setAttribute('aria-label', 'Количество строк на странице');
    [10, 25, 50, 100].forEach((size) => {
      const option = document.createElement('option');
      option.value = String(size);
      option.textContent = String(size);
      if (size === 25) option.selected = true;
      pageSize.append(option);
    });
    pageSizeLabel.append(pageSizeText, pageSize);
    shell.append(pageSizeLabel);

    const count = document.createElement('span');
    count.className = 'stats-table-result-count';
    count.setAttribute('aria-live', 'polite');
    shell.append(count);

    const exportButton = document.createElement('button');
    exportButton.type = 'button';
    exportButton.className = 'btn btn-soft stats-table-export';
    exportButton.textContent = 'Экспорт CSV';
    exportButton.setAttribute('aria-label', 'Экспортировать отфильтрованные строки в CSV');
    shell.append(exportButton);

    const scroll = table.closest('.table-scroll') || table.parentElement;
    if (scroll && scroll.parentElement) scroll.parentElement.insertBefore(shell, scroll);

    const pager = document.createElement('div');
    pager.className = 'stats-table-pagination';
    const pagerInfo = document.createElement('span');
    pagerInfo.className = 'stats-table-pagination-info';
    pagerInfo.setAttribute('aria-live', 'polite');
    const prev = document.createElement('button');
    prev.type = 'button';
    prev.className = 'btn btn-soft';
    prev.textContent = '← Назад';
    const next = document.createElement('button');
    next.type = 'button';
    next.className = 'btn btn-soft';
    next.textContent = 'Вперёд →';
    pager.append(pagerInfo, prev, next);
    if (scroll && scroll.parentElement) scroll.parentElement.append(pager);

    const dynamicEmpty = document.createElement('tr');
    dynamicEmpty.className = 'stats-table-empty-row';
    const emptyCell = document.createElement('td');
    emptyCell.colSpan = Math.max(1, table.querySelectorAll('thead th').length);
    emptyCell.textContent = 'По выбранным условиям ничего не найдено. Измените поиск или фильтры.';
    dynamicEmpty.append(emptyCell);
    dynamicEmpty.hidden = true;
    tbody.append(dynamicEmpty);

    let page = 1;
    let pageRows = 25;
    let filteredRows = allRows.slice();
    let sortIndex = -1;
    let sortDirection = 1;

    const externalSearch = table.id === 'direction-statistics-table' ? document.getElementById('direction-search') : null;
    const directionMode = table.id === 'direction-statistics-table' ? document.getElementById('direction-filter') : null;
    const directionPresets = table.id === 'direction-statistics-table' ? Array.from(document.querySelectorAll('[data-direction-preset]')) : [];
    const directionSelect = table.id === 'event-statistics-table'
      ? document.getElementById('event-direction-filter')
      : (table.id === 'decline-statistics-table' ? document.getElementById('decline-direction-filter') : null);

    const matchesSpecificFilter = (row) => {
      if (table.id === 'direction-statistics-table' && directionMode) {
        const visits = Number(row.dataset.visits || 0);
        const events = Number(row.dataset.events || 0);
        const members = Number(row.dataset.members || 0);
        const mode = directionMode.value;
        if (mode === 'active' && visits <= 0 && events <= 0) return false;
        if (mode === 'inactive' && (visits > 0 || events > 0)) return false;
        if (mode === 'visits' && visits <= 0) return false;
        if (mode === 'no-visits' && visits > 0) return false;
        if (mode === 'events' && events <= 0) return false;
        if (mode === 'members' && members <= 0) return false;
      }
      if (directionSelect && directionSelect.value !== 'all') {
        const ids = String(row.dataset.directionIds || '').split(',').filter(Boolean);
        if (!ids.includes(directionSelect.value)) return false;
      }
      return true;
    };

    const parseValue = (value) => {
      const cleaned = String(value || '').replace(/\u00a0/g, ' ').replace(/[%\s]/g, '').replace(',', '.');
      if (cleaned && /^-?\d+(\.\d+)?$/.test(cleaned)) return Number(cleaned);
      return normalize(value);
    };

    const update = () => {
      const query = normalize(search ? search.value : (externalSearch ? externalSearch.value : ''));
      filteredRows = allRows.filter((row) => matchesSpecificFilter(row) && (!query || safeText(row).includes(query)));
      if (sortIndex >= 0) {
        filteredRows.sort((left, right) => {
          const a = parseValue(left.cells[sortIndex]?.textContent || '');
          const b = parseValue(right.cells[sortIndex]?.textContent || '');
          const cmp = typeof a === 'number' && typeof b === 'number' ? a - b : String(a).localeCompare(String(b), 'ru', { numeric: true, sensitivity: 'base' });
          return cmp * sortDirection;
        });
      }
      pageRows = Number(pageSize.value) || 25;
      const pages = Math.max(1, Math.ceil(filteredRows.length / pageRows));
      page = Math.min(Math.max(1, page), pages);
      allRows.forEach((row) => { row.hidden = true; });
      const offset = (page - 1) * pageRows;
      const visibleRows = filteredRows.slice(offset, offset + pageRows);
      visibleRows.forEach((row) => { row.hidden = false; tbody.insertBefore(row, dynamicEmpty); });
      // Keep the server-rendered empty state when the report has no directions;
      // use the interactive empty state only when filters/search hide real rows.
      originalEmptyRows.forEach((row) => { row.hidden = allRows.length > 0; });
      dynamicEmpty.hidden = allRows.length === 0 || filteredRows.length !== 0;
      count.textContent = `Найдено: ${filteredRows.length}`;
      const legacyCount = document.getElementById(table.id === 'direction-statistics-table' ? 'direction-filter-count' : (table.id === 'event-statistics-table' ? 'event-direction-filter-count' : (table.id === 'decline-statistics-table' ? 'decline-direction-filter-count' : '')));
      if (legacyCount) legacyCount.textContent = `Показано: ${filteredRows.length} из ${allRows.length}`;
      pagerInfo.textContent = filteredRows.length
        ? `${offset + 1}–${offset + visibleRows.length} из ${filteredRows.length}`
        : 'Нет строк';
      pager.hidden = filteredRows.length <= pageRows;
      prev.disabled = page <= 1;
      next.disabled = page >= pages;
      table.querySelectorAll('thead th').forEach((header, index) => {
        header.classList.toggle('stats-sort-active', index === sortIndex);
        header.setAttribute('aria-sort', index === sortIndex ? (sortDirection === 1 ? 'ascending' : 'descending') : 'none');
        const label = header.dataset.sortLabel || header.innerText.trim();
        header.title = `Сортировать по столбцу «${label}»`;
        header.setAttribute('aria-label', `${label}. Нажмите для сортировки`);
        header.tabIndex = 0;
        header.classList.add('stats-sortable');
      });
    };

    const sortBy = (index) => {
      if (sortIndex === index) sortDirection *= -1;
      else { sortIndex = index; sortDirection = 1; }
      page = 1;
      update();
    };
    table.querySelectorAll('thead th').forEach((header, index) => {
      header.addEventListener('click', () => sortBy(index));
      header.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); sortBy(index); }
      });
    });

    if (search) search.addEventListener('input', () => { page = 1; update(); });
    if (externalSearch) {
      externalSearch.addEventListener('input', () => { page = 1; update(); });
      externalSearch.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && externalSearch.value) {
          externalSearch.value = '';
          page = 1;
          update();
        }
      });
      document.addEventListener('keydown', (event) => {
        const target = event.target;
        const typing = target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
        if (event.key === '/' && !typing && !event.ctrlKey && !event.metaKey && !event.altKey) {
          event.preventDefault();
          externalSearch.focus();
        }
      });
    }
    if (pageSize) pageSize.addEventListener('change', () => { page = 1; update(); });
    const syncDirectionPresets = () => {
      if (!directionMode) return;
      directionPresets.forEach((button) => {
        const active = button.dataset.directionPreset === directionMode.value;
        button.classList.toggle('is-active', active);
        button.setAttribute('aria-pressed', String(active));
      });
    };
    if (directionMode) directionMode.addEventListener('change', () => { page = 1; syncDirectionPresets(); update(); });
    directionPresets.forEach((button) => button.addEventListener('click', () => {
      if (!directionMode) return;
      directionMode.value = button.dataset.directionPreset || 'all';
      page = 1;
      syncDirectionPresets();
      update();
    }));
    syncDirectionPresets();
    if (directionSelect) directionSelect.addEventListener('change', () => { page = 1; update(); });
    const localReset = table.id === 'direction-statistics-table' ? document.getElementById('direction-local-reset') : null;
    if (localReset) localReset.addEventListener('click', () => {
      if (externalSearch) externalSearch.value = '';
      if (directionMode) directionMode.value = 'all';
      syncDirectionPresets();
      page = 1;
      if (externalSearch) externalSearch.focus();
      update();
    });
    prev.addEventListener('click', () => { page -= 1; update(); });
    next.addEventListener('click', () => { page += 1; update(); });

    exportButton.addEventListener('click', () => {
      const headers = Array.from(table.querySelectorAll('thead th')).map((cell) => cell.innerText.trim());
      const csvCell = (value) => {
        let safe = String(value || '').replace(/\r?\n/g, ' ').trim();
        if (/^[\t ]*[=+@-]/.test(safe)) safe = `'${safe}`; // prevent spreadsheet formula injection
        return `"${safe.replace(/"/g, '""')}"`;
      };
      const lines = [headers.map(csvCell).join(';')];
      filteredRows.forEach((row) => lines.push(Array.from(row.cells).map((cell) => csvCell(cell.textContent)).join(';')));
      const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${table.id || 'statistics'}-${new Date().toISOString().slice(0, 10)}.csv`;
      document.body.append(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    });

    update();
  });
})();

/* ===== END frontend/assets/scripts/portal/statistics-workspace-v1913.js ===== */
