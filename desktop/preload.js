/**
 * Electron preload — exposes a safe API to the renderer via contextBridge.
 * Only minimal surface area is exposed; no raw Node.js access.
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
  navigate: (path) => ipcRenderer.invoke('navigate', path),
  platform: process.platform,
  isElectron: true,
});
