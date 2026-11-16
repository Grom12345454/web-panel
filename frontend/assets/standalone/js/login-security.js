/* Login-only progressive enhancement. Authentication and CSRF remain server-owned. */
(() => {
  'use strict';

  const form = document.querySelector('.premium-auth--single .premium-form');
  const passwordToggle = document.getElementById('password-visibility');
  const passwordInput = document.getElementById('login-password');

  if (passwordToggle && passwordInput) {
    passwordToggle.addEventListener('click', () => {
      const shouldReveal = passwordInput.type === 'password';
      passwordInput.type = shouldReveal ? 'text' : 'password';
      passwordToggle.textContent = shouldReveal ? 'Скрыть' : 'Показать';
      passwordToggle.setAttribute('aria-pressed', String(shouldReveal));
      passwordToggle.setAttribute('aria-label', shouldReveal ? 'Скрыть пароль' : 'Показать пароль');
      passwordInput.focus({ preventScroll: true });
    });
  }

  if (form) {
    form.addEventListener('submit', (event) => {
      if (form.dataset.submitting === 'true') {
        event.preventDefault();
        return;
      }
      const submit = form.querySelector('.premium-submit[type="submit"]');
      if (!submit) return;
      form.dataset.submitting = 'true';
      submit.disabled = true;
      submit.setAttribute('aria-busy', 'true');
      const label = submit.querySelector('span');
      if (label) label.textContent = 'Проверяем данные…';
    });
  }
})();
