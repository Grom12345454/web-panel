async function loadAnalysis() {
  const list = $('aiList');
  try {
    const response = await fetch('/api/analysis');
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'analysis failed');
    const a = data.analysis || {};
    $('aiProvider').textContent = `${a.provider || 'rule-engine'} / ${a.model || 'fallback'}`;
    $('aiSummary').textContent = a.summary || 'Нет summary.';
    list.innerHTML = (a.findings || []).map((item) => `
      <div class="rowCard"><div><b class="${item.severity === 'high' ? 'danger' : 'warn'}">${esc(item.severity || 'info').toUpperCase()} · ${esc(item.title || 'Finding')}</b><small>${esc(item.evidence || `Обнаружено: ${item.count || 0}`)}</small></div><span class="badge ${item.severity === 'high' ? 'critical' : 'warning'}">REVIEW</span></div>
    `).join('') || '<div class="pad">Существенных findings нет.</div>';
    $('topRules').innerHTML = (a.topRules || []).map(x => `<div class="kv"><span>${esc(x.rule)}</span><b>${x.count}</b></div>`).join('');
    $('recommendations').innerHTML = (a.recommendations || []).map(x => `<li>${esc(x)}</li>`).join('');
  } catch (error) {
    list.innerHTML = `<div class="pad">${esc(error.message)}</div>`;
  }
}
$('refreshAI')?.addEventListener('click', loadAnalysis);
loadAnalysis();
setInterval(loadAnalysis, 30000);
