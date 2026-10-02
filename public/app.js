const STORAGE_KEY = 'w-ai-admin-state-v2';
const SETTINGS_KEY = 'w-ai-admin-settings';
const AUTH_KEY = 'w-ai-admin-token';

const $ = (id) => document.getElementById(id);
const qsa = (selector, root = document) => [...root.querySelectorAll(selector)];

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

function time(value) {
  try {
    return new Date(value).toLocaleTimeString('ru-RU');
  } catch {
    return value;
  }
}

function loadAppState() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
  } catch {
    return {};
  }
}

function saveAppState(patch) {
  try {
    const next = { ...loadAppState(), ...patch };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    return next;
  } catch {
    return {};
  }
}

function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}');
  } catch {
    return {};
  }
}

function saveSetting(key, value) {
  const settings = loadSettings();
  settings[key] = value;
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function loadTelemetry() {
  const state = loadAppState();
  return Array.isArray(state.packets) ? state.packets : [];
}

function saveTelemetry(packets) {
  saveAppState({ packets: packets.slice(0, 200) });
}

function loadView(page, fallback = {}) {
  const state = loadAppState();
  return { ...fallback, ...((state.views || {})[page] || {}) };
}

function saveView(page, view) {
  const state = loadAppState();
  saveAppState({ views: { ...(state.views || {}), [page]: view } });
}

function toast(message) {
  const element = $('toast');
  if (!element) return;

  element.textContent = message;
  element.classList.add('show');
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => element.classList.remove('show'), 1800);
}

function setConnectionState(text, color) {
  qsa('.conn').forEach((element) => {
    element.innerHTML = `<i></i> ${text}`;
    element.style.color = color;
  });
}

function toggle(element) {
  const enabled = element.classList.toggle('on');
  saveSetting(element.dataset.key, enabled);
  toast(enabled ? 'Настройка включена' : 'Настройка выключена');
}

function initCommon() {
  const clock = $('clock');
  if (clock) {
    const updateClock = () => {
      clock.textContent = new Date().toLocaleTimeString('ru-RU');
    };
    updateClock();
    setInterval(updateClock, 1000);
  }

  const settings = loadSettings();
  qsa('.toggle').forEach((element) => {
    if (settings[element.dataset.key] === true) element.classList.add('on');
    element.addEventListener('click', () => toggle(element));
  });

  qsa('[data-toast]').forEach((button) => {
    button.addEventListener('click', () => toast(button.dataset.toast));
  });

  const shade = $('drawerShade');
  const drawer = $('drawer');
  const closeDrawer = () => {
    shade?.classList.remove('open');
    drawer?.classList.remove('open');
  };

  qsa('[data-close-drawer]').forEach((button) => button.addEventListener('click', closeDrawer));
  shade?.addEventListener('click', closeDrawer);
}

async function postAction(path, payload) {
  try {
    const token = localStorage.getItem(AUTH_KEY) || '';
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['X-Admin-Token'] = token;
    const response = await fetch(path, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || 'Action failed');
    return data;
  } catch (error) {
    toast(`Ошибка: ${error.message}`);
    return null;
  }
}

function updateStoredPacket(packet) {
  const packets = loadTelemetry();
  const index = packets.findIndex((item) => item.blockKey === packet.blockKey);
  if (index >= 0) packets[index] = { ...packets[index], ...packet };
  saveTelemetry(packets);
}

async function blockIncident(packet) {
  if (!packet?.blockKey) {
    toast('Для события нет ключа блокировки');
    return;
  }

  const result = await postAction('/api/block', { key: packet.blockKey });
  if (!result) return;

  const updated = { ...packet, blocked: true, blockStatus: 'blocked' };
  updateStoredPacket(updated);
  toast(packet.type === 'danger' ? 'Угроза заблокирована автоматически' : 'Подозрительный адрес заблокирован');
  document.dispatchEvent(new CustomEvent('blockChanged', { detail: updated }));
  openDrawer(updated);
}

async function adminUnblock(packet) {
  if (!packet || packet.type !== 'warn' || !packet.blockKey) {
    toast('Разблокировка доступна только для жёлтых событий');
    return;
  }

  const result = await postAction('/api/unblock', { key: packet.blockKey });
  if (!result) return;

  const updated = { ...packet, blocked: false, blockStatus: 'unblocked' };
  updateStoredPacket(updated);
  toast('Администратор снял блокировку');
  document.dispatchEvent(new CustomEvent('blockChanged', { detail: updated }));
  openDrawer(updated);
}

function renderDrawerActions(packet) {
  const buttons = [];

  if (packet.blocked) {
    buttons.push(`
      <span class="badge ${packet.type === 'danger' ? 'critical' : 'warning'}">
        ${packet.type === 'danger' ? 'AUTO-BLOCKED' : 'BLOCKED · ADMIN CONTROL'}
      </span>
    `);
  } else {
    buttons.push('<button class="btn primary" id="drawerBlock">BLOCK NOW</button>');
  }

  if (packet.type === 'warn' && packet.blocked) {
    buttons.push('<button class="btn" id="drawerUnblock">ADMIN UNBLOCK</button>');
  }

  buttons.push('<button class="btn" data-toast="Событие помечено как reviewed">MARK REVIEWED</button>');
  buttons.push('<button class="btn" data-toast="Примечание сохранено локально">ADD NOTE</button>');

  return buttons.join('');
}

function openDrawer(packet = {}) {
  const shade = $('drawerShade');
  const drawer = $('drawer');
  if (!shade || !drawer) return;

  saveAppState({ selectedIncident: packet });

  const typeClass = packet.type === 'danger' ? 'critical' : packet.type === 'warn' ? 'warning' : 'safe';
  const typeLabel = String(packet.type || 'info').toUpperCase();

  drawer.innerHTML = `
    <div class="drawerHead">
      <div>
        <div class="label">INCIDENT FOCUS</div>
        <h3>${esc(packet.domain || packet.title || packet.dst || 'Security event')}</h3>
        <div class="subline">${esc(packet.time ? time(packet.time) : 'just now')} · ${typeLabel}</div>
      </div>
      <button class="drawerClose" data-close-drawer aria-label="Close">×</button>
    </div>

    <div class="rowCard drawerRisk">
      <div>
        <b>Risk classification</b>
        <small>Telemetry label; production telemetry</small>
      </div>
      <span class="badge ${typeClass}">${esc(packet.type || 'info')}</span>
    </div>

    <div class="drawerDetails">
      <div class="kv"><span>Source IP</span><b class="mono">${esc(packet.src || '—')}</b></div>
      <div class="kv"><span>Destination IP</span><b class="mono">${esc(packet.dst || '—')}</b></div>
      <div class="kv"><span>Website / Host</span><b class="blue">${esc(packet.domain || '—')}</b></div>
      <div class="kv"><span>Protocol / Port</span><b>${esc(packet.protocol || '—')}:${esc(packet.port || '—')}</b></div>
      <div class="kv"><span>Sensor</span><b>${esc(packet.sensor || 'sensor-unknown')}</b></div>
    </div>

    <div class="cardHead drawerSectionHead">
      <h3>Event timeline</h3>
      <span>ANALYST VIEW</span>
    </div>

    <div class="timeline">
      <div class="timeItem">
        <i></i>
        <div>
          <b>Telemetry captured</b>
          <p>Сетевое событие поступило из live SSE-потока.</p>
        </div>
      </div>
      <div class="timeItem">
        <i></i>
        <div>
          <b>Normalized</b>
          <p>Источник, назначение, протокол и порт приведены к единому формату.</p>
        </div>
      </div>
      <div class="timeItem">
        <i></i>
        <div>
          <b>Rule / AI review</b>
          <p>${packet.type === 'danger'
            ? 'Событие отмечено как требующее приоритетного просмотра.'
            : 'Событие доступно для проверки по базовым правилам.'}</p>
        </div>
      </div>
    </div>

    <div class="drawerActions">${renderDrawerActions(packet)}</div>
  `;

  shade.classList.add('open');
  drawer.classList.add('open');

  drawer.querySelector('[data-close-drawer]')?.addEventListener('click', () => {
    shade.classList.remove('open');
    drawer.classList.remove('open');
  });
  drawer.querySelector('#drawerBlock')?.addEventListener('click', () => blockIncident(packet));
  drawer.querySelector('#drawerUnblock')?.addEventListener('click', () => adminUnblock(packet));
  drawer.querySelectorAll('[data-toast]').forEach((button) => {
    button.addEventListener('click', () => toast(button.dataset.toast));
  });
}

function startEventStream() {
  if (!window.EventSource || location.protocol === 'file:') return;

  const stream = new EventSource('/events');

  stream.onopen = () => setConnectionState('BACKEND CONNECTED', 'var(--green)');
  stream.onerror = () => setConnectionState('RECONNECTING', 'var(--yellow)');

  stream.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data);
      if (message.event !== 'packet') return;

      const current = loadTelemetry();
      current.unshift(message.data);
      saveTelemetry(current);
      document.dispatchEvent(new CustomEvent('telemetry', { detail: message.data }));
    } catch {
      // Ignore malformed demo events.
    }
  };
}

document.addEventListener('DOMContentLoaded', () => {
  initCommon();
  startEventStream();
});

window.$ = $;
window.qsa = qsa;
window.esc = esc;
window.time = time;
window.toast = toast;
window.loadSettings = loadSettings;
window.saveSetting = saveSetting;
window.loadTelemetry = loadTelemetry;
window.saveTelemetry = saveTelemetry;
window.loadView = loadView;
window.saveView = saveView;
window.openDrawer = openDrawer;
window.blockIncident = blockIncident;
window.adminUnblock = adminUnblock;

async function loadServerLogs(limit = 300) {
  if (location.protocol === 'file:') return [];
  try {
    const response = await fetch(`/api/logs?limit=${limit}`, { cache: 'no-store' });
    const data = await response.json();
    return Array.isArray(data.logs) ? data.logs : [];
  } catch {
    return [];
  }
}

window.WA = { postAction, toast, loadSettings, saveSetting, AUTH_KEY };
