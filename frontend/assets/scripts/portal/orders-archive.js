/* Accessible upload modal and client-side filter for the private order archive. */
(() => {
  'use strict';

  const initOrdersArchive = () => {
    const root = document.querySelector('[data-orders-archive]');
    const modal = document.querySelector('[data-order-modal]');
    if (!root || !modal || modal.dataset.initialized === 'true') return;
    modal.dataset.initialized = 'true';

    const dialog = modal.querySelector('[role="dialog"]');
    const openers = Array.from(root.querySelectorAll('[data-order-modal-open]'));
    const closers = Array.from(modal.querySelectorAll('[data-order-modal-close]'));
    const fileInput = modal.querySelector('[data-order-file]');
    const fileSelected = modal.querySelector('[data-order-file-selected]');
    const form = modal.querySelector('[data-order-upload-form]');
    const submitButton = modal.querySelector('[data-order-submit]');
    const search = root.querySelector('[data-order-search]');
    const rows = Array.from(root.querySelectorAll('[data-order-row]'));
    const noResults = root.querySelector('[data-order-no-results]');
    let returnFocus = null;
    let priorOverflow = '';

    const focusable = () => Array.from(dialog.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((node) => !node.hasAttribute('hidden') && node.getAttribute('aria-hidden') !== 'true');

    const openModal = (trigger) => {
      if (modal.hidden) {
        returnFocus = trigger || document.activeElement;
        priorOverflow = document.body.style.overflow;
        modal.hidden = false;
        modal.setAttribute('aria-hidden', 'false');
        document.body.style.overflow = 'hidden';
        const first = modal.querySelector('#orders-target-id:not([disabled])') || closers[0] || dialog;
        window.requestAnimationFrame(() => first.focus());
      }
    };

    const closeModal = () => {
      if (modal.hidden) return;
      modal.hidden = true;
      modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = priorOverflow;
      if (returnFocus && typeof returnFocus.focus === 'function') returnFocus.focus();
    };

    openers.forEach((button) => button.addEventListener('click', () => openModal(button)));
    closers.forEach((button) => button.addEventListener('click', closeModal));
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeModal();
    });

    document.addEventListener('keydown', (event) => {
      if (modal.hidden) return;
      if (event.key === 'Escape') {
        event.preventDefault();
        closeModal();
        return;
      }
      if (event.key !== 'Tab') return;
      const elements = focusable();
      if (!elements.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });

    if (fileInput && fileSelected) {
      fileInput.addEventListener('change', () => {
        const file = fileInput.files && fileInput.files[0];
        if (!file) {
          fileSelected.textContent = 'Файл не выбран';
          return;
        }
        const sizeMb = file.size / (1024 * 1024);
        fileSelected.textContent = `${file.name} · ${sizeMb.toFixed(2)} МБ`;
        const extensionOk = /\.(pdf|docx)$/i.test(file.name);
        if (!extensionOk) {
          fileSelected.textContent += ' — разрешены только PDF и DOCX';
        } else if (file.size > 8 * 1024 * 1024) {
          fileSelected.textContent += ' — размер больше 8 МБ';
        }
      });
    }

    if (form && submitButton) {
      form.addEventListener('submit', (event) => {
        if (!form.reportValidity()) {
          event.preventDefault();
          return;
        }
        const file = fileInput && fileInput.files && fileInput.files[0];
        if (file && (!/\.(pdf|docx)$/i.test(file.name) || file.size > 8 * 1024 * 1024)) {
          event.preventDefault();
          if (fileSelected) {
            fileSelected.textContent = !/\.(pdf|docx)$/i.test(file.name)
              ? 'Разрешены только файлы PDF и DOCX.'
              : 'Файл больше 8 МБ. Выберите файл меньшего размера.';
          }
          if (fileInput) fileInput.focus();
          return;
        }
        // Frontend convenience only; server-side format/size validation remains authoritative.
        submitButton.disabled = true;
        submitButton.setAttribute('aria-busy', 'true');
        submitButton.textContent = 'Загрузка…';
      });
    }

    const filterRows = () => {
      if (!search || !rows.length) return;
      const query = search.value.trim().toLocaleLowerCase('ru-RU');
      let visible = 0;
      rows.forEach((row) => {
        const haystack = (row.dataset.orderSearch || row.textContent).toLocaleLowerCase('ru-RU');
        const match = !query || haystack.includes(query);
        row.hidden = !match;
        if (match) visible += 1;
      });
      if (noResults) noResults.hidden = visible !== 0;
    };
    if (search) search.addEventListener('input', filterRows);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initOrdersArchive, { once: true });
  } else {
    initOrdersArchive();
  }
})();
