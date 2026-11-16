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
