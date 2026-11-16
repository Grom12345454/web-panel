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
