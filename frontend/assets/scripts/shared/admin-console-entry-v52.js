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
