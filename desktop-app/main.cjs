'use strict';

const {
  app,
  BrowserWindow,
  Menu,
  Tray,
  Notification,
  ipcMain,
  shell,
  nativeImage,
  dialog,
  session
} = require('electron');
const fs = require('node:fs');
const path = require('node:path');

const APP_ID = 'ru.studsovet.messenger';
const MESSENGER_PATH = '/messenger/desktop?native=1';
const DESKTOP_PARTITION = 'temp:studsovet-messenger';
const ICON_PNG = path.join(__dirname, 'assets', 'messenger.png');
const ICON_ICO = path.join(__dirname, 'assets', 'messenger.ico');

let mainWindow = null;
let setupWindow = null;
let tray = null;
let quitting = false;
let settings = {
  serverOrigin: '',
  notificationsEnabled: false,
  notificationCursor: 0,
  launchAtLogin: false
};

const settingsPath = () => path.join(app.getPath('userData'), 'desktop-settings.json');

function readSettings() {
  try {
    const stored = JSON.parse(fs.readFileSync(settingsPath(), 'utf8'));
    settings = { ...settings, ...stored };
  } catch (_) {
    // First launch or unreadable settings: use safe defaults.
  }
  if (typeof settings.serverOrigin !== 'string') settings.serverOrigin = '';
  settings.notificationsEnabled = Boolean(settings.notificationsEnabled);
  settings.notificationCursor = Number.isSafeInteger(Number(settings.notificationCursor)) ? Math.max(0, Number(settings.notificationCursor)) : 0;
  settings.launchAtLogin = Boolean(settings.launchAtLogin);
}

function saveSettings() {
  fs.mkdirSync(path.dirname(settingsPath()), { recursive: true });
  fs.writeFileSync(settingsPath(), JSON.stringify(settings, null, 2), { mode: 0o600 });
}

function normalizeServerOrigin(value) {
  const raw = String(value || '').trim();
  if (!raw) throw new Error('Укажите адрес сервера StudSovet.');
  let url;
  try { url = new URL(raw); } catch (_) { throw new Error('Проверьте адрес. Пример: http://192.168.1.10:5000'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Разрешены только адреса HTTP или HTTPS.');
  if (url.username || url.password || url.search || url.hash || (url.pathname !== '/' && url.pathname !== '')) {
    throw new Error('Укажите только адрес сервера без логина, пароля, пути и параметров.');
  }
  if (!url.hostname) throw new Error('В адресе не найден сервер.');
  return url.origin;
}

function messengerUrl(pathname = MESSENGER_PATH) {
  if (!settings.serverOrigin) throw new Error('Сервер ещё не настроен.');
  const value = pathname.startsWith('/') ? pathname : `/${pathname}`;
  return new URL(value, settings.serverOrigin).toString();
}

function isAllowedAppUrl(candidate) {
  try {
    const url = new URL(candidate);
    if (url.origin !== settings.serverOrigin) return false;
    const p = url.pathname;
    return p === '/messenger' || p.startsWith('/messenger/') ||
      p === '/staff-messenger' || p.startsWith('/staff-messenger/') ||
      p === '/auth' || p.startsWith('/auth/') ||
      p === '/static' || p.startsWith('/static/') ||
      p === '/api/visual-theme' || p === '/favicon.ico';
  } catch (_) { return false; }
}

function openExternal(candidate) {
  try {
    const url = new URL(candidate);
    if (url.protocol === 'https:' || url.protocol === 'mailto:') shell.openExternal(url.toString());
  } catch (_) { /* Ignore malformed or unsafe external URLs. */ }
}

function configureDesktopSession() {
  const desktopSession = session.fromPartition(DESKTOP_PARTITION);
  // Remote pages receive no browser permissions by default. Native Windows
  // notifications are shown only through the validated IPC bridge below.
  desktopSession.setPermissionRequestHandler((_webContents, _permission, callback) => callback(false));
  desktopSession.setPermissionCheckHandler(() => false);
  desktopSession.on('will-download', (event) => { event.preventDefault(); });
  desktopSession.webRequest.onBeforeSendHeaders((details, callback) => {
    const headers = { ...details.requestHeaders };
    try {
      if (settings.serverOrigin && new URL(details.url).origin === settings.serverOrigin) {
        headers['X-StudSovet-Desktop'] = '1';
      }
    } catch (_) { /* Ignore non-URL requests. */ }
    callback({ requestHeaders: headers });
  });
  return desktopSession;
}

function makePreloadOptions() {
  return {
    partition: DESKTOP_PARTITION,
    preload: path.join(__dirname, 'preload.cjs'),
    contextIsolation: true,
    nodeIntegration: false,
    sandbox: true,
    backgroundThrottling: false,
    webSecurity: true,
    allowRunningInsecureContent: false,
    webviewTag: false,
    devTools: process.argv.includes('--dev')
  };
}

function createTray() {
  if (tray || !fs.existsSync(ICON_PNG)) return;
  const source = nativeImage.createFromPath(ICON_PNG);
  const trayImage = source.isEmpty() ? nativeImage.createFromPath(ICON_ICO) : source;
  tray = new Tray(trayImage.resize({ width: 16, height: 16 }));
  tray.setToolTip('StudSovet Messenger');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Открыть StudSovet Messenger', click: showMainWindow },
    { type: 'separator' },
    {
      label: 'Запускать вместе с Windows',
      type: 'checkbox',
      checked: settings.launchAtLogin,
      click: (item) => setLaunchAtLogin(item.checked)
    },
    { label: 'Сменить сервер', click: openSetupWindow },
    { type: 'separator' },
    { label: 'Выйти из приложения', click: quitApplication }
  ]));
  tray.on('click', showMainWindow);
  tray.on('double-click', showMainWindow);
}

function setLaunchAtLogin(enabled) {
  settings.launchAtLogin = Boolean(enabled);
  saveSettings();
  if (process.platform === 'win32') {
    app.setLoginItemSettings({ openAtLogin: settings.launchAtLogin, name: 'StudSovet Messenger' });
  }
  createTray();
}

function showMainWindow() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function loadMessenger(route = MESSENGER_PATH) {
  if (!mainWindow || !settings.serverOrigin) return;
  let url;
  try {
    const target = new URL(route, settings.serverOrigin);
    if (!isAllowedAppUrl(target.toString()) || !target.pathname.startsWith('/messenger')) {
      target.pathname = '/messenger/desktop';
      target.search = '?native=1';
    }
    url = target.toString();
  } catch (_) {
    url = messengerUrl(MESSENGER_PATH);
  }
  mainWindow.loadURL(url).catch(async (error) => {
    console.warn('Messenger load failed:', error.message);
    await dialog.showMessageBox(mainWindow, {
      type: 'warning',
      title: 'Нет подключения к StudSovet',
      message: 'Не удалось подключиться к серверу мессенджера.',
      detail: `Проверьте, что сервер запущен и доступен по адресу ${settings.serverOrigin}.`,
      buttons: ['Настроить сервер', 'Закрыть'],
      defaultId: 0
    }).then(({ response }) => { if (response === 0) openSetupWindow(); });
  });
}

function createMainWindow() {
  if (mainWindow) {
    showMainWindow();
    loadMessenger();
    return;
  }
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 940,
    minHeight: 650,
    show: false,
    title: 'StudSovet Messenger',
    backgroundColor: '#07111b',
    autoHideMenuBar: true,
    icon: process.platform === 'win32' ? ICON_ICO : ICON_PNG,
    webPreferences: makePreloadOptions()
  });
  mainWindow.setTitle('StudSovet Messenger');
  mainWindow.webContents.on('will-attach-webview', (event) => event.preventDefault());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isAllowedAppUrl(url)) {
      setImmediate(() => { if (mainWindow) mainWindow.loadURL(url); });
    } else {
      openExternal(url);
    }
    return { action: 'deny' };
  });
  const keepInsideMessenger = (event, candidate) => {
    if (isAllowedAppUrl(candidate)) return;
    event.preventDefault();
    try {
      const url = new URL(candidate);
      if (url.origin !== settings.serverOrigin) openExternal(candidate);
    } catch (_) { /* Ignore malformed navigation. */ }
    if (mainWindow && !mainWindow.isDestroyed()) setImmediate(() => loadMessenger());
  };
  mainWindow.webContents.on('will-navigate', keepInsideMessenger);
  mainWindow.webContents.on('will-attach-webview', (event) => event.preventDefault());
  mainWindow.webContents.on('will-redirect', keepInsideMessenger);
  mainWindow.webContents.on('did-finish-load', () => {
    if (mainWindow && !mainWindow.isVisible()) mainWindow.show();
  });
  mainWindow.on('page-title-updated', (event) => {
    event.preventDefault();
    mainWindow.setTitle('StudSovet Messenger');
  });
  mainWindow.on('close', (event) => {
    // Keep the Electron process and its temporary authenticated session alive
    // while the user closes the window. The tray menu contains the explicit
    // Quit command; only that command (or OS shutdown) ends this run.
    if (!quitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
  mainWindow.on('closed', () => { mainWindow = null; });
  createTray();
  loadMessenger();
}

function openSetupWindow() {
  if (setupWindow) {
    setupWindow.focus();
    return;
  }
  setupWindow = new BrowserWindow({
    width: 610,
    height: 640,
    minWidth: 560,
    minHeight: 560,
    resizable: true,
    title: 'Настройка StudSovet Messenger',
    backgroundColor: '#07111b',
    autoHideMenuBar: true,
    icon: process.platform === 'win32' ? ICON_ICO : ICON_PNG,
    webPreferences: makePreloadOptions()
  });
  setupWindow.loadFile(path.join(__dirname, 'setup.html'));
  setupWindow.on('closed', () => {
    setupWindow = null;
    if (!mainWindow && !quitting) app.quit();
  });
}

async function testServer(origin) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 9000);
  try {
    const response = await fetch(`${origin}/auth/login`, {
      method: 'GET',
      redirect: 'follow',
      signal: controller.signal,
      headers: { 'User-Agent': `StudSovetMessenger/${app.getVersion()}` }
    });
    if (!response.ok) throw new Error(`Сервер ответил кодом ${response.status}.`);
    return true;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Сервер не ответил за 9 секунд. Проверьте адрес и сеть.');
    if (error.message.startsWith('Сервер ответил')) throw error;
    throw new Error('Не удалось связаться с сервером. Проверьте адрес, порт и доступность сервера.');
  } finally {
    clearTimeout(timeout);
  }
}

ipcMain.handle('desktop:get-config', (event) => {
  if (!setupWindow || event.sender !== setupWindow.webContents) throw new Error('Недоступно из этого окна.');
  return {
    serverOrigin: settings.serverOrigin,
    notificationsEnabled: settings.notificationsEnabled,
    launchAtLogin: settings.launchAtLogin
  };
});
ipcMain.handle('desktop:version', (event) => {
  if (!setupWindow || event.sender !== setupWindow.webContents) throw new Error('Недоступно из этого окна.');
  return app.getVersion();
});
ipcMain.handle('desktop:connect', async (event, value) => {
  if (!setupWindow || event.sender !== setupWindow.webContents) throw new Error('Настройка сервера разрешена только из окна подключения.');
  const origin = normalizeServerOrigin(value);
  await testServer(origin);
  settings.serverOrigin = origin;
  saveSettings();
  if (setupWindow) setupWindow.close();
  createMainWindow();
  return { ok: true, serverOrigin: origin };
});
ipcMain.handle('desktop:notifications-state', (event) => {
  if (!mainWindow || event.sender !== mainWindow.webContents) throw new Error('Недоступно из этого окна.');
  return Boolean(settings.notificationsEnabled);
});
ipcMain.handle('desktop:notifications-cursor', (event) => {
  if (!mainWindow || event.sender !== mainWindow.webContents) throw new Error('Недоступно из этого окна.');
  return settings.notificationCursor;
});
ipcMain.handle('desktop:notifications-cursor-save', (event, cursor) => {
  if (!mainWindow || event.sender !== mainWindow.webContents) throw new Error('Недоступно из этого окна.');
  const value = Number(cursor);
  if (!Number.isSafeInteger(value) || value < 0) return false;
  if (value > settings.notificationCursor) {
    settings.notificationCursor = value;
    saveSettings();
  }
  return true;
});
ipcMain.handle('desktop:notifications-enable', (event) => {
  if (!mainWindow || event.sender !== mainWindow.webContents) throw new Error('Недоступно из этого окна.');
  if (!Notification.isSupported()) return false;
  settings.notificationsEnabled = true;
  saveSettings();
  new Notification({
    title: 'StudSovet Messenger',
    body: 'Системные уведомления включены. Новые сообщения будут отображаться в Windows.'
  }).show();
  return true;
});
ipcMain.on('desktop:show-notification', (event, payload = {}) => {
  if (!mainWindow || event.sender !== mainWindow.webContents) return;
  if (!settings.notificationsEnabled || !Notification.isSupported()) return;
  const title = String(payload.title || 'StudSovet Messenger').slice(0, 120);
  const body = String(payload.body || 'Новое сообщение').slice(0, 240);
  const notice = new Notification({ title, body, icon: ICON_PNG, silent: false });
  notice.on('click', () => {
    showMainWindow();
    const route = String(payload.url || '/messenger/desktop?native=1');
    try {
      const target = new URL(route, settings.serverOrigin);
      if (isAllowedAppUrl(target.toString()) && target.pathname.startsWith('/messenger')) loadMessenger(`${target.pathname}${target.search}`);
    } catch (_) { loadMessenger(); }
  });
  notice.show();
});
ipcMain.on('desktop:show-window', (event) => {
  if (mainWindow && event.sender === mainWindow.webContents) showMainWindow();
});

function quitApplication() {
  quitting = true;
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.destroy();
  if (tray) { tray.destroy(); tray = null; }
  app.quit();
}

function buildAppMenu() {
  const template = [
    {
      label: 'StudSovet Messenger',
      submenu: [
        { label: 'Открыть мессенджер', click: showMainWindow },
        { label: 'Сменить сервер…', click: openSetupWindow },
        { type: 'separator' },
        {
          label: 'Запускать вместе с Windows',
          type: 'checkbox',
          checked: settings.launchAtLogin,
          click: (item) => setLaunchAtLogin(item.checked)
        },
        { type: 'separator' },
        { label: 'Выйти', click: quitApplication }
      ]
    },
    {
      label: 'Вид',
      submenu: [
        { role: 'reload', label: 'Обновить' },
        { role: 'resetZoom', label: 'Обычный масштаб' },
        { role: 'zoomIn', label: 'Увеличить' },
        { role: 'zoomOut', label: 'Уменьшить' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: 'Полный экран' },
        ...(process.argv.includes('--dev') ? [{ role: 'toggleDevTools', label: 'Инструменты разработчика' }] : [])
      ]
    }
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.quit();
else {
  app.on('second-instance', () => {
    if (setupWindow) setupWindow.focus();
    else showMainWindow();
  });
  app.whenReady().then(() => {
    app.setAppUserModelId(APP_ID);
    readSettings();
    configureDesktopSession();
    buildAppMenu();
    if (process.platform === 'win32') {
      app.setLoginItemSettings({ openAtLogin: settings.launchAtLogin, name: 'StudSovet Messenger' });
    }
    const image = nativeImage.createFromPath(ICON_PNG);
    if (!image.isEmpty()) app.dock?.setIcon(image);
    if (settings.serverOrigin) createMainWindow();
    else openSetupWindow();
  });
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      if (settings.serverOrigin) createMainWindow();
      else openSetupWindow();
    } else showMainWindow();
  });
  app.on('before-quit', () => { quitting = true; });
  app.on('window-all-closed', () => app.quit());
}

app.on('web-contents-created', (_event, contents) => {
  contents.on('will-attach-webview', (event) => event.preventDefault());
});
