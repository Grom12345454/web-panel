const ALERTS = [
  ['critical', 'Possible C2 communication', '192.168.1.15', '45.33.32.156', '2 min ago', 'SOC / AI'],
  ['critical', 'SMB connection to suspicious host', '192.168.1.20', '185.220.101.34', '5 min ago', 'SOC / AI'],
  ['warning', 'Unusual port 8080 activity', '10.0.0.7', '104.18.32.47', '8 min ago', 'Network Ops'],
  ['warning', 'Repeated DNS lookup pattern', '10.0.0.19', '1.1.1.1', '11 min ago', 'SOC Analyst'],
  ['warning', 'Traffic spike above baseline', '192.168.1.15', '151.101.1.69', '16 min ago', 'Network Ops'],
  ['warning', 'Unknown device fingerprint', '10.0.0.22', '104.16.132.229', '20 min ago', 'SOC Analyst'],
  ['warning', 'Policy mismatch', '10.0.0.31', '8.8.8.8', '25 min ago', 'Network Ops'],
];

let alertTab = loadView('alerts', { tab: 'all' }).tab || 'all';

function renderAlerts() {
  const rows = ALERTS.filter(([severity]) => alertTab === 'all' || severity === alertTab);

  $('alerts').innerHTML = rows.length
    ? rows.map((alert, index) => `
        <tr class="clickableRow" data-alert-index="${index}">
          <td><span class="badge ${alert[0] === 'critical' ? 'critical' : 'warning'}">${alert[0].toUpperCase()}</span></td>
          <td><b>${esc(alert[1])}</b></td>
          <td class="mono">${alert[2]}</td>
          <td class="mono">${alert[3]}</td>
          <td>${alert[4]}</td>
          <td>${alert[5]}</td>
          <td><button class="btn" data-review-index="${index}">REVIEW</button></td>
        </tr>
      `).join('')
    : '<tr><td colspan="7" class="empty">Очередь пуста</td></tr>';

  const visible = ALERTS.filter(([severity]) => alertTab === 'all' || severity === alertTab);
  qsa('[data-alert-index]', $('alerts')).forEach((row) => {
    row.addEventListener('click', (event) => {
      if (event.target.closest('button')) return;
      const alert = visible[Number(row.dataset.alertIndex)];
      openAlert(alert);
    });
  });

  qsa('[data-review-index]', $('alerts')).forEach((button) => {
    button.addEventListener('click', () => openAlert(visible[Number(button.dataset.reviewIndex)]));
  });
}

function openAlert(alert) {
  openDrawer({
    title: alert[1],
    type: alert[0] === 'critical' ? 'danger' : 'warn',
    src: alert[2],
    dst: alert[3],
    protocol: 'SMB/HTTP/DNS',
    port: 'review',
    sensor: 'demo-sensor-01',
  });
}

qsa('.tab').forEach((tab) => {
  tab.classList.toggle('active', tab.dataset.tab === alertTab);
  tab.addEventListener('click', () => {
    qsa('.tab').forEach((item) => item.classList.remove('active'));
    tab.classList.add('active');
    alertTab = tab.dataset.tab;
    saveView('alerts', { tab: alertTab });
    renderAlerts();
  });
});

$('ackAll').addEventListener('click', () => toast('Все демо-алерты отмечены как reviewed'));
renderAlerts();
