const DEVICES = [
  ['Gateway', '192.168.1.1', 'Network', 'now', '18.4 MB/s', 'safe', 'online'],
  ['Workstation-15', '192.168.1.15', 'Client', 'now', '4.8 MB/s', 'safe', 'online'],
  ['Workstation-20', '192.168.1.20', 'Client', '12 sec', '3.2 MB/s', 'warning', 'watch'],
  ['Lab-PC-07', '10.0.0.7', 'Lab', '22 sec', '2.1 MB/s', 'safe', 'online'],
  ['Unknown-22', '10.0.0.22', 'Unknown', '1 min', '780 KB/s', 'warning', 'watch'],
  ['Isolated-31', '10.0.0.31', 'Quarantine', '3 min', '0 KB/s', 'critical', 'isolated'],
];

let deviceFilter = loadView('devices', { filter: 'all' }).filter || 'all';

function renderDevices() {
  const rows = DEVICES.filter((device) => deviceFilter === 'all' || device[5] === deviceFilter);

  $('devicesTable').innerHTML = rows.map((device, index) => `
    <tr class="clickableRow" data-device-index="${index}">
      <td><b>${esc(device[0])}</b></td>
      <td class="mono">${esc(device[1])}</td>
      <td>${esc(device[2])}</td>
      <td>${esc(device[3])}</td>
      <td>${esc(device[4])}</td>
      <td><span class="badge ${device[5] === 'critical' ? 'critical' : device[5] === 'warning' ? 'warning' : 'safe'}">${device[5].toUpperCase()}</span></td>
      <td><span class="badge ${device[5] === 'critical' ? 'critical' : device[5] === 'warning' ? 'warning' : 'safe'}">${device[6].toUpperCase()}</span></td>
    </tr>
  `).join('');

  qsa('[data-device-index]', $('devicesTable')).forEach((row) => {
    row.addEventListener('click', () => {
      const device = rows[Number(row.dataset.deviceIndex)];
      openDrawer({
        title: device[0],
        type: device[5] === 'critical' ? 'danger' : device[5] === 'warning' ? 'warn' : 'safe',
        src: device[1],
        dst: 'asset',
        protocol: 'inventory',
        port: '—',
        sensor: 'asset-inventory',
      });
    });
  });
}

qsa('.tab').forEach((tab) => {
  tab.classList.toggle('active', tab.dataset.filter === deviceFilter);
  tab.addEventListener('click', () => {
    qsa('.tab').forEach((item) => item.classList.remove('active'));
    tab.classList.add('active');
    deviceFilter = tab.dataset.filter;
    saveView('devices', { filter: deviceFilter });
    renderDevices();
  });
});

renderDevices();
