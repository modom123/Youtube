import { App } from '@capacitor/app';
import { StatusBar, Style } from '@capacitor/status-bar';
import { SplashScreen } from '@capacitor/splash-screen';

async function initApp() {
  try {
    await StatusBar.setStyle({ style: Style.Dark });
    await StatusBar.setBackgroundColor({ color: '#0a0a0a' });
  } catch (_) {}

  App.addListener('backButton', ({ canGoBack }) => {
    if (canGoBack) {
      window.history.back();
    } else {
      App.exitApp();
    }
  });

  App.addListener('appStateChange', ({ isActive }) => {
    if (isActive) {
      checkNotifications();
    }
  });

  await SplashScreen.hide();
  startNotificationPoll();
}

let _notifInterval = null;

function startNotificationPoll() {
  checkNotifications();
  _notifInterval = setInterval(checkNotifications, 30000);
}

async function checkNotifications() {
  try {
    const resp = await fetch('/api/notifications');
    if (!resp.ok) return;
    const data = await resp.json();
    if (data.unread_count > 0) {
      updateBadge(data.unread_count);
    }
  } catch (_) {}
}

function updateBadge(count) {
  try {
    const badge = document.getElementById('notif-badge');
    if (badge) {
      badge.style.display = count > 0 ? 'block' : 'none';
      badge.textContent = count > 9 ? '9+' : count;
    }
  } catch (_) {}
}

window.mobileHeartbeat = async function() {
  try {
    const resp = await fetch('/health');
    return resp.ok;
  } catch (_) {
    return false;
  }
};

initApp();
