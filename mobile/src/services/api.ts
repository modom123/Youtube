import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import { APP_URL } from '../constants';

const TOKEN_KEY = 'auth_session';
let sessionCookie: string | null = null;

export async function saveSession(cookie: string) {
  sessionCookie = cookie;
  if (Platform.OS !== 'web') {
    await SecureStore.setItemAsync(TOKEN_KEY, cookie);
  }
}

export async function getSession(): Promise<string | null> {
  if (sessionCookie) return sessionCookie;
  if (Platform.OS !== 'web') {
    sessionCookie = await SecureStore.getItemAsync(TOKEN_KEY);
  }
  return sessionCookie;
}

export async function clearSession() {
  sessionCookie = null;
  if (Platform.OS !== 'web') {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
  }
}

async function headers(): Promise<Record<string, string>> {
  const session = await getSession();
  const h: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Mobile-App': 'SocialOptimize/1.0',
  };
  if (session) h['Cookie'] = session;
  return h;
}

export async function api(path: string, opts: RequestInit = {}): Promise<any> {
  const h = await headers();
  const res = await fetch(`${APP_URL}${path}`, {
    ...opts,
    headers: { ...h, ...(opts.headers as Record<string, string> || {}) },
  });

  const setCookie = res.headers.get('set-cookie');
  if (setCookie) await saveSession(setCookie);

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }

  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    return res.json();
  }
  return res.text();
}

export async function login(email: string, password: string) {
  return api('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
}

export async function register(name: string, email: string, password: string) {
  return api('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ name, email, password }),
  });
}

export async function getProfile() {
  return api('/api/profile');
}

export async function getDashboard() {
  return api('/api/dashboard');
}

export async function getJobs() {
  return api('/api/jobs');
}

export async function getJobStatus(jobId: string) {
  return api(`/api/job/${jobId}`);
}

export async function createVideo(data: {
  topic: string;
  platform?: string;
  style?: string;
  duration?: string;
  voice?: string;
}) {
  return api('/api/create', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getStudios() {
  return api('/api/studios');
}

export async function getAnalytics() {
  return api('/api/analytics');
}

export async function getSettings() {
  return api('/settings/data');
}

export async function updateSettings(data: any) {
  return api('/settings/update', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function logout() {
  await api('/auth/logout', { method: 'POST' }).catch(() => {});
  await clearSession();
}
