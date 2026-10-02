const persistedTraffic = loadView('traffic', {
  search: '',
  proto: 'all',
  severity: 'all',
});

const trafficState = {
  events: loadTelemetry(),
  search: persistedTraffic.search,
  proto: persistedTraffic.proto,
  severity: persistedTraffic.severity,
};

function matchesTraffic(packet) {
  const query = trafficState.search.toLowerCase();
  const text = `${packet.src} ${packet.dst} ${packet.domain} ${packet.port} ${packet.protocol}`.toLowerCase();

  return (!query || text.includes(query))
    && (trafficState.proto === 'all' || packet.protocol === trafficState.proto)
    && (trafficState.severity === 'all' || packet.type === trafficState.severity);
}

function renderTraffic() {
  const list = trafficState.events.filter(matchesTraffic).slice(0, 100);

  $('rows').innerHTML = list.length
    ? list.map((packet) => `
        <tr class="clickableRow" data-packet-key="${esc(packet.blockKey || packet.no)}">
          <td class="mono">${time(packet.time)}</td>
          <td class="mono">${esc(packet.src)}</td>
          <td><b class="blue">${esc(packet.domain || 'unknown')}</b></td>
          <td class="mono">${esc(packet.dst)}</td>
          <td>${esc(packet.protocol)}</td>
          <td class="mono">${esc(packet.port)}</td>
          <td>
            <span class="badge ${packet.type === 'danger' ? 'critical' : packet.type === 'warn' ? 'warning' : 'safe'}">${packet.type}</span>
            ${packet.blocked ? `<span class="blockedMark ${packet.type === 'danger' ? 'autoMark' : 'adminMark'}">${packet.type === 'danger' ? 'BLOCKED' : 'BLOCKED · ADMIN'}</span>` : ''}
          </td>
        </tr>
      `).join('')
    : '<tr><td colspan="7" class="empty">Нет пакетов по фильтру</td></tr>';

  const byKey = new Map(trafficState.events.map((packet) => [String(packet.blockKey || packet.no), packet]));
  qsa('[data-packet-key]', $('rows')).forEach((row) => {
    row.addEventListener('click', () => openDrawer(byKey.get(row.dataset.packetKey)));
  });

  $('total').textContent = trafficState.events.length;
  $('https').textContent = trafficState.events.filter((packet) => packet.protocol === 'HTTPS').length;
  $('dns').textContent = trafficState.events.filter((packet) => packet.protocol === 'DNS').length;
  $('threat').textContent = trafficState.events.filter((packet) => packet.type === 'danger').length;
}

function saveTrafficView() {
  saveView('traffic', {
    search: trafficState.search,
    proto: trafficState.proto,
    severity: trafficState.severity,
  });
}

['search', 'proto', 'severity'].forEach((id) => {
  $(id).value = trafficState[id];
  $(id).addEventListener('input', (event) => {
    trafficState[id] = event.target.value;
    saveTrafficView();
    renderTraffic();
  });
});

$('saveView').addEventListener('click', () => {
  saveTrafficView();
  toast('Фильтр сохранён для текущей сессии');
});

document.addEventListener('telemetry', (event) => {
  trafficState.events.unshift(event.detail);
  trafficState.events = trafficState.events.slice(0, 250);
  $('streamState').textContent = '● LIVE';
  $('streamState').style.color = 'var(--green)';
  renderTraffic();
});

document.addEventListener('blockChanged', (event) => {
  const packet = event.detail;
  const index = trafficState.events.findIndex((item) => item.blockKey === packet.blockKey);
  if (index >= 0) trafficState.events[index] = { ...trafficState.events[index], ...packet };
  renderTraffic();
});

renderTraffic();


(async function hydrateTrafficFromLogs() {
  const logs = await loadServerLogs(300);
  const telemetry = logs.filter((entry) => entry.kind === 'telemetry' || !entry.kind);
  if (!telemetry.length) return;
  trafficState.events = telemetry.reverse().slice(0, 300);
  saveTelemetry(trafficState.events);
  renderTraffic();
})();
