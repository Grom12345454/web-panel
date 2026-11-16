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
