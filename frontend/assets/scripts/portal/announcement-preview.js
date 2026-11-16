(() => {
  'use strict';
  const title = document.getElementById('announcement-title');
  const body = document.getElementById('announcement-body');
  const previewTitle = document.getElementById('announcement-preview-title');
  const previewBody = document.getElementById('announcement-preview-body');
  if (!title || !body || !previewTitle || !previewBody) return;
  title.addEventListener('input', () => {
    previewTitle.textContent = title.value || 'Заголовок объявления';
  });
  body.addEventListener('input', () => {
    previewBody.textContent = body.value || 'Текст объявления появится здесь.';
  });
})();
