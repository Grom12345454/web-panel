const persistedDashboard = loadView('dashboard', {
  filters: { safe: true, warn: true, danger: true },
  search: '',
  proto: 'all',
  level: 'all',
});

const dashboardState = {
  packets: loadTelemetry(),
  filters: persistedDashboard.filters,
  search: persistedDashboard.search,
  proto: persistedDashboard.proto,
  level: persistedDashboard.level,
  ai: [],
};

function dashboardMatches(packet) {
  const query = dashboardState.search.toLowerCase();
  const text = `${packet.src} ${packet.dst} ${packet.domain} ${packet.port} ${packet.protocol}`.toLowerCase();

  return Boolean(dashboardState.filters[packet.type])
    && (dashboardState.proto === 'all' || packet.protocol === dashboardState.proto)
    && (dashboardState.level === 'all' || packet.type === dashboardState.level)
    && (!query || text.includes(query));
}

function packetTone(type) {
  return type === 'danger' ? 'danger' : type === 'warn' ? 'warn' : 'safe';
}

function packetLabel(type) {
  return type === 'danger' ? 'THREAT' : type === 'warn' ? 'SUSPICIOUS' : 'NORMAL';
}

function packetById(index) {
  return dashboardState.packets[index];
}

function renderTrafficFeed() {
  const list = dashboardState.packets.filter(dashboardMatches).slice(0, 45);
  const feed = $('trafficFeed');

  feed.innerHTML = list.length
    ? list.map((packet) => {
        const index = dashboardState.packets.indexOf(packet);
        return `
          <button class="feedItem feedButton" data-packet-index="${index}">
            <span class="feedDot ${packetTone(packet.type)}"></span>
            <span>
              <b>${packetLabel(packet.type)} · <span class="blue">${esc(packet.domain || 'unknown')}</span></b>
              <p>
                <span class="mono">${esc(packet.src)}</span> →
                <span class="mono">${esc(packet.dst)}</span> ·
                ${esc(packet.protocol)}:${esc(packet.port)} · ${time(packet.time)}
                ${packet.blocked ? `<span class="blockedMark ${packet.type === 'danger' ? 'autoMark' : 'adminMark'}"> · ${packet.type === 'danger' ? 'AUTO-BLOCKED' : 'BLOCKED · ADMIN UNLOCK'}</span>` : ''}
              </p>
            </span>
          </button>
        `;
      }).join('')
    : '<div class="empty">Нет событий по текущему фильтру</div>';

  $('countSafe').textContent = dashboardState.packets.filter((packet) => packet.type === 'safe').length;
  $('countWarn').textContent = dashboardState.packets.filter((packet) => packet.type === 'warn').length;
  $('countDanger').textContent = dashboardState.packets.filter((packet) => packet.type === 'danger').length;

  qsa('.feedButton', feed).forEach((button) => {
    button.addEventListener('click', () => openDrawer(packetById(Number(button.dataset.packetIndex))));
  });
}

function renderDestinations() {
  const counts = {};
  dashboardState.packets.forEach((packet) => {
    const destination = packet.domain || packet.dst;
    counts[destination] = (counts[destination] || 0) + 1;
  });

  const top = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 7);

  $('destinations').innerHTML = top.length
    ? top.map(([destination, count]) => `
        <button class="feedItem feedButton" data-destination="${esc(destination)}">
          <span class="feedDot safe"></span>
          <span class="feedGrow">
            <b>${esc(destination)}</b>
            <p>${count} connections · latest observation in current session</p>
          </span>
          <strong class="blue">${count}</strong>
        </button>
      `).join('')
    : '<div class="empty">Ожидание соединений…</div>';

  qsa('[data-destination]', $('destinations')).forEach((button) => {
    button.addEventListener('click', () => openDrawer({
      title: button.dataset.destination,
      type: 'safe',
      dst: button.dataset.destination,
      protocol: 'observed',
      port: '—',
      sensor: 'sensor-unknown',
    }));
  });

  $('active').textContent = Object.keys(counts).length;
  $('sceneEdges').textContent = dashboardState.packets.length;
}

function renderAi() {
  $('ai').innerHTML = dashboardState.ai.length
    ? dashboardState.ai.map((packet, index) => `
        <button class="feedItem feedButton" data-ai-index="${index}">
          <span class="feedDot ${packetTone(packet.type)}"></span>
          <span>
            <b class="${packetTone(packet.type)}">${packet.type === 'danger' ? 'CRITICAL' : 'WARNING'} · ${esc(packet.domain || 'network event')}</b>
            <p>${packet.type === 'danger'
              ? 'Potential high-priority connection requiring analyst review.'
              : 'Unusual activity compared with the current baseline.'} · ${time(packet.time)}</p>
          </span>
        </button>
      `).join('')
    : '<div class="empty">AI-журнал пока пуст</div>';

  qsa('[data-ai-index]', $('ai')).forEach((button) => {
    button.addEventListener('click', () => openDrawer(dashboardState.ai[Number(button.dataset.aiIndex)]));
  });
}

function updateRisk() {
  const warnings = dashboardState.packets.filter((packet) => packet.type === 'warn').length;
  const threats = dashboardState.packets.filter((packet) => packet.type === 'danger').length;
  const score = Math.min(98, 24 + warnings * 1.2 + threats * 4);
  const rounded = Math.round(score);
  const gaugeColor = score > 65 ? 'red' : 'yellow';

  $('riskScore').textContent = rounded;
  $('gauge').style.background = `conic-gradient(var(--${gaugeColor}) 0 ${score}%, #1a2539 ${score}% 100%)`;
  $('sceneNodes').textContent = Math.min(28, new Set(dashboardState.packets.flatMap((packet) => [packet.src, packet.dst])).size);
}

function updateDashboard() {
  renderTrafficFeed();
  renderDestinations();
  renderAi();
  updateRisk();

  $('warnings').textContent = dashboardState.packets.filter((packet) => packet.type === 'warn').length;
  $('critical').textContent = dashboardState.packets.filter((packet) => packet.type === 'danger').length;
  $('pps').textContent = Math.max(1, Math.round(2 + Math.random() * 8));
}

function addPacket(packet) {
  dashboardState.packets.unshift(packet);
  dashboardState.packets = dashboardState.packets.slice(0, 200);

  if (packet.type !== 'safe') {
    dashboardState.ai.unshift(packet);
    dashboardState.ai = dashboardState.ai.slice(0, 18);
  }

  updateDashboard();
}

function clearAI() {
  dashboardState.ai = [];
  renderAi();
  toast('AI-журнал очищен');
}

function saveDashboardView() {
  saveView('dashboard', {
    filters: dashboardState.filters,
    search: dashboardState.search,
    proto: dashboardState.proto,
    level: dashboardState.level,
  });
}

function initDashboardFilters() {
  ['search', 'proto', 'level'].forEach((id) => {
    $(id).value = dashboardState[id];
    $(id).addEventListener('input', (event) => {
      dashboardState[id] = event.target.value;
      saveDashboardView();
      renderTrafficFeed();
    });
  });

  qsa('.filter').forEach((button) => {
    button.classList.toggle('active', dashboardState.filters[button.dataset.filter]);
    button.addEventListener('click', () => {
      const filter = button.dataset.filter;
      dashboardState.filters[filter] = !dashboardState.filters[filter];
      button.classList.toggle('active', dashboardState.filters[filter]);
      saveDashboardView();
      renderTrafficFeed();
    });
  });
}

function initTopology() {
  const canvas = $('topology');
  const context = canvas.getContext('2d');
  let points = [];
  let timeValue = 0;
  let mouseX = 0;
  let mouseY = 0;

  function resize() {
    const ratio = window.devicePixelRatio || 1;
    canvas.width = canvas.clientWidth * ratio;
    canvas.height = canvas.clientHeight * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function seed() {
    points = Array.from({ length: 28 }, (_, index) => {
      const angle = Math.random() * Math.PI * 2;
      const radius = 85 + Math.random() * 170;
      return {
        x: Math.cos(angle) * radius,
        y: (Math.random() - 0.5) * 100,
        z: Math.sin(angle) * radius,
        type: index % 10 === 0 ? 'danger' : index % 4 === 0 ? 'warn' : 'safe',
        phase: Math.random() * 6,
      };
    });
  }

  function draw() {
    timeValue += 0.014;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    const centerX = width / 2 + mouseX * 25;
    const centerY = height / 2 + mouseY * 12;
    const projected = [];

    context.clearRect(0, 0, width, height);

    for (const point of points) {
      const angle = timeValue * 0.55 + point.phase * 0.04;
      const rotatedX = point.x * Math.cos(angle) - point.z * Math.sin(angle);
      const rotatedZ = point.x * Math.sin(angle) + point.z * Math.cos(angle);
      const depth = 1 / (1 + rotatedZ / 500);

      projected.push({
        x: centerX + rotatedX * depth,
        y: centerY + point.y * depth,
        size: 3.2 * depth + 1.1,
        z: rotatedZ,
        type: point.type,
      });
    }

    projected.sort((a, b) => a.z - b.z);
    context.globalCompositeOperation = 'lighter';

    for (let index = 0; index < projected.length; index += 1) {
      const point = projected[index];
      const color = point.type === 'danger' ? '#ff5e7a' : point.type === 'warn' ? '#ffd25e' : '#59e9ff';

      context.fillStyle = `${color}22`;
      context.beginPath();
      context.arc(point.x, point.y, point.size * 4, 0, Math.PI * 2);
      context.fill();

      context.fillStyle = color;
      context.beginPath();
      context.arc(point.x, point.y, point.size, 0, Math.PI * 2);
      context.fill();

      if (index % 2 === 0) {
        context.strokeStyle = `${color}30`;
        context.lineWidth = 0.7;
        context.beginPath();
        context.moveTo(centerX, centerY);
        context.lineTo(point.x, point.y);
        context.stroke();
      }
    }

    context.strokeStyle = '#59e9ff16';
    context.lineWidth = 1;
    for (let radius = 55; radius < 230; radius += 35) {
      context.beginPath();
      context.ellipse(centerX, centerY, radius, radius * 0.34, 0, 0, Math.PI * 2);
      context.stroke();
    }

    context.fillStyle = '#59e9ff12';
    context.beginPath();
    context.arc(centerX, centerY, 42, 0, Math.PI * 2);
    context.fill();

    context.strokeStyle = '#59e9ff77';
    context.beginPath();
    context.arc(centerX, centerY, 32, 0, Math.PI * 2);
    context.stroke();

    context.fillStyle = '#59e9ff';
    context.shadowBlur = 22;
    context.shadowColor = '#59e9ff';
    context.beginPath();
    context.arc(centerX, centerY, 7, 0, Math.PI * 2);
    context.fill();
    context.shadowBlur = 0;

    requestAnimationFrame(draw);
  }

  canvas.addEventListener('pointermove', (event) => {
    const rect = canvas.getBoundingClientRect();
    mouseX = (event.clientX - rect.left - rect.width / 2) / rect.width;
    mouseY = (event.clientY - rect.top - rect.height / 2) / rect.height;
  });

  window.addEventListener('resize', resize);
  seed();
  resize();
  draw();
}

$('clearAI').addEventListener('click', clearAI);
$('systemStatus').addEventListener('click', () => openDrawer({
  title: 'System status',
  type: 'safe',
  src: 'local-console',
  dst: 'python-backend',
  protocol: 'SSE',
  port: '8787',
  sensor: 'admin-console',
}));

initDashboardFilters();
initTopology();
updateDashboard();

document.addEventListener('telemetry', (event) => {
  $('liveState').textContent = '● LIVE';
  $('liveState').style.color = 'var(--green)';
  addPacket(event.detail);
});

document.addEventListener('blockChanged', (event) => {
  const packet = event.detail;
  const index = dashboardState.packets.findIndex((item) => item.blockKey === packet.blockKey);
  if (index >= 0) dashboardState.packets[index] = { ...dashboardState.packets[index], ...packet };
  updateDashboard();
});


(async function hydrateDashboardFromLogs() {
  const logs = await loadServerLogs(300);
  const telemetry = logs.filter((entry) => entry.kind === 'telemetry' || !entry.kind);
  if (!telemetry.length) return;
  dashboardState.packets = telemetry.reverse().slice(0, 250);
  dashboardState.ai = dashboardState.packets.filter((packet) => packet.type !== 'safe').slice(0, 18);
  saveTelemetry(dashboardState.packets);
  updateDashboard();
})();
