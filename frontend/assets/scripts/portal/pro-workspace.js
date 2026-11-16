/* Dashboard depth is handled by GPU-friendly CSS hover/focus transitions.
   No pointermove listeners or per-frame layout measurement on cards. */
(() => {
  'use strict';
  const cards = document.querySelectorAll('.galaxy-dashboard .mission-kpi, .galaxy-dashboard .galaxy-tool, .galaxy-dashboard .galaxy-direction');
  cards.forEach(card => card.classList.add('depth-card-2026'));
})();
