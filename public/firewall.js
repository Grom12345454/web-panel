function csv(value) { return value.split(',').map(x => x.trim()).filter(Boolean); }
function policy() {
  return { block_tcp_ports: csv($('tcpPorts').value).map(Number).filter(Boolean), block_udp_ports: csv($('udpPorts').value).map(Number).filter(Boolean), block_protocols: csv($('protocols').value), management_ssh_port: Number($('sshPort').value || 22) };
}
async function preview() {
  const data = await fetch('/api/firewall/preview').then(r => r.json());
  $('rulesPreview').textContent = data.rules || data.error || 'No rules';
}
$('previewFirewall')?.addEventListener('click', preview);
$('applyFirewall')?.addEventListener('click', async () => {
  const result = await WA.postAction('/api/firewall/apply', { dryRun: false });
  if (result) { $('firewallState').textContent = 'APPLIED'; WA.toast('Firewall policy применена'); }
});
$('saveFirewall')?.addEventListener('click', async () => {
  const result = await WA.postAction('/api/config', { firewall: policy() });
  if (result) { WA.toast('Firewall policy сохранена'); preview(); }
});
fetch('/api/config').then(r => r.json()).then(({config}) => {
  const f = config.firewall || {};
  $('tcpPorts').value = (f.block_tcp_ports || []).join(','); $('udpPorts').value = (f.block_udp_ports || []).join(','); $('protocols').value = (f.block_protocols || []).join(','); $('sshPort').value = f.management_ssh_port || 22;
  preview();
});
