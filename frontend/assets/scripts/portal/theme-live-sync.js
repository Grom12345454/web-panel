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
