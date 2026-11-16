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
