/**
 * Social Optimize — Electron Main Process
 * Supports macOS, Windows, and Linux.
 *
 * In development: starts a local Flask server on port 5001
 * In production: connects to the configured APP_URL
 */

const { app, BrowserWindow, shell, Menu, ipcMain, nativeTheme } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');

// ──────────────────────────────────────────────
// Configuration
// ──────────────────────────────────────────────
const isDev = process.env.APP_ENV === 'development' || !app.isPackaged;
const FLASK_PORT = 5001;
const LOCAL_URL = `http://127.0.0.1:${FLASK_PORT}`;
const PRODUCTION_URL = process.env.APP_URL || 'https://socialoptimize.online';
const APP_URL = isDev ? LOCAL_URL : PRODUCTION_URL;

let mainWindow = null;
let splashWindow = null;
let flaskProcess = null;

// ──────────────────────────────────────────────
// Flask server management (dev only)
// ──────────────────────────────────────────────
function startFlaskServer() {
  return new Promise((resolve, reject) => {
    if (!isDev) {
      resolve();
      return;
    }

    const rootDir = path.join(__dirname, '..');
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';

    flaskProcess = spawn(pythonCmd, ['-m', 'flask', 'run', '--port', FLASK_PORT], {
      cwd: rootDir,
      env: { ...process.env, FLASK_APP: 'app.py', FLASK_ENV: 'development' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    flaskProcess.stdout.on('data', (data) => {
      const msg = data.toString();
      if (msg.includes('Running on')) resolve();
    });

    flaskProcess.stderr.on('data', (data) => {
      const msg = data.toString();
      if (msg.includes('Running on')) resolve();
    });

    flaskProcess.on('error', reject);
    flaskProcess.on('exit', (code) => {
      if (code !== 0 && code !== null) console.error(`Flask exited with code ${code}`);
    });

    setTimeout(resolve, 4000);
  });
}

function stopFlaskServer() {
  if (flaskProcess) {
    flaskProcess.kill('SIGTERM');
    flaskProcess = null;
  }
}

// ──────────────────────────────────────────────
// Window polling — wait for server to respond
// ──────────────────────────────────────────────
function waitForServer(url, timeout = 30000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const check = () => {
      http.get(url, (res) => {
        if (res.statusCode < 500) resolve();
        else retry();
      }).on('error', retry);
    };
    const retry = () => {
      if (Date.now() - start > timeout) {
        reject(new Error('Server did not respond in time'));
      } else {
        setTimeout(check, 500);
      }
    };
    check();
  });
}

// ──────────────────────────────────────────────
// Splash screen
// ──────────────────────────────────────────────
function createSplashWindow() {
  splashWindow = new BrowserWindow({
    width: 400,
    height: 300,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    center: true,
    resizable: false,
    skipTaskbar: true,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });
  splashWindow.loadFile(path.join(__dirname, 'splash.html'));
}

// ──────────────────────────────────────────────
// Main window
// ──────────────────────────────────────────────
function createMainWindow() {
  let Store;
  try { Store = require('electron-store'); } catch {}
  const store = Store ? new Store() : null;

  const bounds = (store && store.get('windowBounds')) || { width: 1280, height: 820 };

  mainWindow = new BrowserWindow({
    ...bounds,
    minWidth: 900,
    minHeight: 600,
    title: 'Social Optimize',
    backgroundColor: '#0a0a0a',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    vibrancy: process.platform === 'darwin' ? 'under-window' : undefined,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      webSecurity: true,
    },
  });

  mainWindow.loadURL(APP_URL);

  mainWindow.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.destroy();
      splashWindow = null;
    }
    mainWindow.show();
    if (isDev) mainWindow.webContents.openDevTools({ mode: 'detach' });
  });

  mainWindow.on('close', () => {
    if (store) store.set('windowBounds', mainWindow.getBounds());
  });

  mainWindow.on('closed', () => { mainWindow = null; });

  // Open external links in the system browser
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  mainWindow.webContents.on('will-navigate', (event, url) => {
    const appHost = new URL(APP_URL).host;
    if (new URL(url).host !== appHost) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });
}

// ──────────────────────────────────────────────
// Application menu
// ──────────────────────────────────────────────
function buildMenu() {
  const isMac = process.platform === 'darwin';
  const template = [
    ...(isMac ? [{ label: app.name, submenu: [
      { role: 'about' },
      { type: 'separator' },
      { role: 'services' },
      { type: 'separator' },
      { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' },
      { type: 'separator' },
      { role: 'quit' },
    ]}] : []),
    { label: 'File', submenu: [
      { label: 'New Video', accelerator: 'CmdOrCtrl+N', click: () => mainWindow?.loadURL(`${APP_URL}/create`) },
      { type: 'separator' },
      isMac ? { role: 'close' } : { role: 'quit' },
    ]},
    { label: 'Edit', submenu: [
      { role: 'undo' }, { role: 'redo' }, { type: 'separator' },
      { role: 'cut' }, { role: 'copy' }, { role: 'paste' }, { role: 'selectAll' },
    ]},
    { label: 'View', submenu: [
      { label: 'Dashboard', accelerator: 'CmdOrCtrl+1', click: () => mainWindow?.loadURL(`${APP_URL}/dashboard`) },
      { label: 'Create Content', accelerator: 'CmdOrCtrl+2', click: () => mainWindow?.loadURL(`${APP_URL}/create`) },
      { label: 'Jobs', accelerator: 'CmdOrCtrl+3', click: () => mainWindow?.loadURL(`${APP_URL}/jobs`) },
      { label: 'Analytics', accelerator: 'CmdOrCtrl+4', click: () => mainWindow?.loadURL(`${APP_URL}/analytics`) },
      { type: 'separator' },
      { role: 'reload' }, { role: 'forceReload' },
      { type: 'separator' },
      { role: 'toggleDevTools' },
      { type: 'separator' },
      { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
    ]},
    { label: 'Window', submenu: [
      { role: 'minimize' }, { role: 'zoom' },
      ...(isMac ? [{ type: 'separator' }, { role: 'front' }] : [{ role: 'close' }]),
    ]},
    { label: 'Help', submenu: [
      { label: 'Open in Browser', click: () => shell.openExternal(PRODUCTION_URL) },
      { label: 'Report Issue', click: () => shell.openExternal('https://github.com/modom123/youtube/issues') },
    ]},
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ──────────────────────────────────────────────
// App lifecycle
// ──────────────────────────────────────────────
app.whenReady().then(async () => {
  nativeTheme.themeSource = 'dark';
  buildMenu();
  createSplashWindow();

  try {
    await startFlaskServer();
    await waitForServer(APP_URL);
  } catch (err) {
    console.warn('Local server unavailable, falling back to production URL');
    if (mainWindow) mainWindow.loadURL(PRODUCTION_URL);
  }

  createMainWindow();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    stopFlaskServer();
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
});

app.on('before-quit', stopFlaskServer);

// IPC: navigate from renderer
ipcMain.handle('navigate', (_event, path) => {
  mainWindow?.loadURL(`${APP_URL}${path}`);
});
