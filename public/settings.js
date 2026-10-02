function setToggle(id, enabled) {
  const el = $(id); if (!el) return;
  el.classList.toggle('on', Boolean(enabled));
}
fetch('/api/config').then(r => r.json()).then(({config}) => {
  const ai = config.ai || {}, sec = config.security || {};
  $('aiModel').value = ai.model || 'qwen2.5:7b';
  $('aiUrl').value = ai.url || 'http://127.0.0.1:11434/api/generate';
  $('aiTimeout').value = ai.timeout_seconds || 30;
  setToggle('aiEnabled', ai.enabled !== false);
  setToggle('virusEnabled', sec.virus_scan_enabled !== false);
  setToggle('quarantineEnabled', sec.quarantine_enabled === true);
  setToggle('reviewGate', sec.review_gate !== false);
}).catch(() => WA.toast('Не удалось загрузить config'));

$('adminToken')?.addEventListener('change', () => localStorage.setItem(WA.AUTH_KEY, $('adminToken').value.trim()));
['aiEnabled','virusEnabled','quarantineEnabled','reviewGate'].forEach(id => $(id)?.addEventListener('click', () => $(id).classList.toggle('on')));

$('saveAll')?.addEventListener('click', async () => {
  const result = await WA.postAction('/api/config', {
    ai: { enabled: $('aiEnabled').classList.contains('on'), model: $('aiModel').value.trim(), url: $('aiUrl').value.trim(), timeout_seconds: Number($('aiTimeout').value || 30) },
    security: { virus_scan_enabled: $('virusEnabled').classList.contains('on'), quarantine_enabled: $('quarantineEnabled').classList.contains('on'), review_gate: $('reviewGate').classList.contains('on') }
  });
  if (result) WA.toast('Политика сохранена');
});
