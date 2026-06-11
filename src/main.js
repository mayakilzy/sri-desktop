import { app, BrowserWindow } from 'electron';
import path from 'node:path';
import { spawn } from 'node:child_process';
import started from 'electron-squirrel-startup';

if (started) app.quit();

let backendProcess = null;
let mainWindow = null;

function startBackend() {
  const resourcesPath = app.isPackaged
    ? process.resourcesPath
    : path.join(app.getAppPath(), '..', 'resources');

  const isWin = process.platform === 'win32';
  const pythonExe = isWin ? 'python' : 'python3';
  const backendScript = path.join(resourcesPath, 'backend', 'run.py');

  console.log('Starting backend with:', pythonExe, backendScript);

  backendProcess = spawn(pythonExe, [backendScript], {
    env: {
      ...process.env,
      DATABASE_URL: `sqlite:///${path.join(app.getPath('userData'), 'sri.db')}`,
      LOG_DIR: path.join(app.getPath('userData'), 'logs'),
      PYTHONUNBUFFERED: '1',
    }
  });

  backendProcess.stdout?.on('data', d => console.log('[Backend]', d.toString().trim()));
  backendProcess.stderr?.on('data', d => console.error('[Backend ERR]', d.toString().trim()));
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    title: 'Smart Review Intelligence',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  setTimeout(() => {
    mainWindow.loadURL('http://localhost:3011');
  }, 4000);

  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (backendProcess) { backendProcess.kill(); backendProcess = null; }
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  if (backendProcess) backendProcess.kill();
});
