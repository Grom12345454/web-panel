/* Lightweight Student App experience: CSS-only card motion.
   No JS tilt, no pointermove, no layout reads per mouse frame. */
(() => {
  'use strict';
  const onlineNotice = document.getElementById('pro-connectivity');
  function updateConnectivity() {
    if (onlineNotice) onlineNotice.hidden = navigator.onLine !== false;
  }
  window.addEventListener('online', updateConnectivity);
  window.addEventListener('offline', updateConnectivity);
  updateConnectivity();
})();
