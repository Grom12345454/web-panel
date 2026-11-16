'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('studsovetDesktop', Object.freeze({
  getServerConfig: () => ipcRenderer.invoke('desktop:get-config'),
  connectToServer: (origin) => ipcRenderer.invoke('desktop:connect', String(origin || '')),
  getNotificationState: () => ipcRenderer.invoke('desktop:notifications-state'),
  getNotificationCursor: () => ipcRenderer.invoke('desktop:notifications-cursor'),
  saveNotificationCursor: (cursor) => ipcRenderer.invoke('desktop:notifications-cursor-save', Number(cursor)),
  enableNotifications: () => ipcRenderer.invoke('desktop:notifications-enable'),
  showNotification: (payload) => ipcRenderer.send('desktop:show-notification', payload),
  getVersion: () => ipcRenderer.invoke('desktop:version'),
  showMainWindow: () => ipcRenderer.send('desktop:show-window')
}));
