/* V31 Kinetic Cinema: desktop-only pointer light and restrained card depth.
   No user data is collected or persisted; all values remain CSS custom properties. */
(() => {
  'use strict';
  const bodies = [...document.querySelectorAll('body.uc-body[data-theme], body.student-app-body[data-season]')].filter(body => !body.querySelector('.theme-page')); // Theme designer intentionally has no cursor-following light.
  if (!bodies.length) return;
  const motion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  const pointer = window.matchMedia ? window.matchMedia('(hover: hover) and (pointer: fine)') : null;
  const canAnimate = () => Boolean(pointer && pointer.matches && !(motion && motion.matches) && !document.hidden);
  if (!canAnimate()) return;

  const surfaces = [
    'body.uc-body .main :is(.card,.dashboard-card,.galaxy-tool,.mission-kpi,.galaxy-direction,.galaxy-stat,.stat-card,.direction-card,.panel,.notification-card,.calendar-shell)',
    'body.student-app-body #app :is(.command-next-card,.mission-today-tile,.command-metric,.account-tile,.student-announcement,.event-preview,.glass.card,.stat,.event,.dir-option)'
  ].join(',');
  let active = null;
  let pending = null;
  let frame = 0;
  const haloNodes = [];

  for (const body of bodies) {
    const field = body.querySelector(':scope > .cosmos-field');
    if (!field) continue;
    let halo = field.querySelector(':scope > .v31-light-halo');
    if (!halo) {
      halo = document.createElement('span');
      halo.className = 'v31-light-halo';
      halo.setAttribute('aria-hidden', 'true');
      field.appendChild(halo);
    }
    haloNodes.push(halo);
  }

  function clearActive() {
    if (!active) return;
    active.classList.remove('v31-depth-hover');
    ['--v31-rx', '--v31-ry'].forEach(name => active.style.removeProperty(name));
    active = null;
  }

  function paint() {
    frame = 0;
    if (!pending || !canAnimate()) return;
    const x = pending.x;
    const y = pending.y;
    const px = `${(x / Math.max(1, window.innerWidth) * 100).toFixed(2)}%`;
    const py = `${(y / Math.max(1, window.innerHeight) * 100).toFixed(2)}%`;
    bodies.forEach(body => {
      body.style.setProperty('--v31-pointer-x', px);
      body.style.setProperty('--v31-pointer-y', py);
    });
    haloNodes.forEach(halo => {
      halo.classList.add('v31-light-halo--active');
      halo.style.setProperty('--v31-pointer-x', px);
      halo.style.setProperty('--v31-pointer-y', py);
    });
    if (!active || !active.isConnected) return;
    const rect = active.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    const nx = Math.max(0, Math.min(1, (x - rect.left) / rect.width));
    const ny = Math.max(0, Math.min(1, (y - rect.top) / rect.height));
    active.style.setProperty('--v31-ry', `${((nx - .5) * 5).toFixed(2)}deg`);
    active.style.setProperty('--v31-rx', `${((.5 - ny) * 4).toFixed(2)}deg`);
  }

  function move(event) {
    if (!canAnimate() || event.pointerType === 'touch' || !(event.target instanceof Element)) return;
    const card = event.target.closest(surfaces);
    if (card !== active) {
      clearActive();
      active = card;
      if (active) active.classList.add('v31-depth-hover');
    }
    pending = { x: event.clientX, y: event.clientY };
    if (!frame) frame = window.requestAnimationFrame(paint);
  }

  function leave(event) {
    if (event.relatedTarget instanceof Node && document.documentElement.contains(event.relatedTarget)) return;
    clearActive();
    pending = null;
    haloNodes.forEach(halo => halo.classList.remove('v31-light-halo--active'));
  }

  function clear() {
    if (frame) window.cancelAnimationFrame(frame);
    frame = 0;
    pending = null;
    clearActive();
    haloNodes.forEach(halo => halo.classList.remove('v31-light-halo--active'));
    bodies.forEach(body => {
      body.style.removeProperty('--v31-pointer-x');
      body.style.removeProperty('--v31-pointer-y');
    });
  }

  document.addEventListener('pointermove', move, { passive: true });
  document.addEventListener('pointerout', leave, { passive: true });
  document.addEventListener('visibilitychange', () => { if (document.hidden) clear(); });
  window.addEventListener('pagehide', clear, { once: true });
  if (motion && motion.addEventListener) motion.addEventListener('change', clear);
  if (pointer && pointer.addEventListener) pointer.addEventListener('change', clear);
})();
