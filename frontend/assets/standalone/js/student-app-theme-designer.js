(() => {
  'use strict';
  const form = document.getElementById('student-app-theme-form');
  if (!form) return;
  const saveTitle = document.getElementById('theme-save-title');
  const liveStatus = document.getElementById('theme-live-status');
  const csrf = form.querySelector('input[name="csrf_token"]')?.value || '';
  let saveSequence = 0;
  function applySelection(input) {
    if (!input) return;
    const card = input.closest('.theme-card');
    if (!card) return;
    form.querySelectorAll('.theme-card').forEach((item) => {
      const radio = item.querySelector('input[type="radio"]');
      item.classList.toggle('is-selected', Boolean(radio && radio.checked));
    });
    const title = card.dataset.themeTitle || 'Выбранная тема';
    if (saveTitle) saveTitle.textContent = title;
    const preview = {'theme-preview-label':title,'theme-preview-description':card.dataset.themeDescription||'','theme-preview-emoji':card.dataset.themeEmoji||'','theme-preview-object':card.dataset.themeObject||'','theme-preview-season-title':title};
    Object.entries(preview).forEach(([id,value]) => { const node=document.getElementById(id); if(node) node.textContent=value; });
  }
  form.addEventListener('change', (event) => {
    if (!(event.target instanceof HTMLInputElement) || event.target.name !== 'season') return;
    applySelection(event.target);
    const url = form.dataset.liveUrl;
    if (!url) return;
    const sequence = ++saveSequence;
    if (liveStatus) liveStatus.textContent = 'Применяем тему…';
    const body = new URLSearchParams({season:event.target.value,csrf_token:csrf});
    fetch(url,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/x-www-form-urlencoded;charset=UTF-8','X-CSRF-Token':csrf,'X-Requested-With':'XMLHttpRequest'},body:body.toString()})
      .then(response => { if(!response.ok) throw new Error('save_failed'); return response.json(); })
      .then(result => { if(sequence===saveSequence && result.ok && liveStatus) liveStatus.textContent=`Тема «${result.label}» сохранена. Синхронизация запущена.`; })
      .catch(() => { if(sequence===saveSequence && liveStatus) liveStatus.textContent='Не удалось сохранить тему. Проверьте соединение и используйте кнопку «Применить тему».'; });
  });
  const initiallySelected=form.querySelector('input[name="season"]:checked');
  if(initiallySelected) applySelection(initiallySelected);
})();
