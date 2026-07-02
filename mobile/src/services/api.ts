import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';
import { APP_URL } from '../constants';

// The backend authenticates the mobile app with a signed bearer token
// (see mobile_auth.py), not the browser session cookie -- React Native's
// fetch doesn't reliably expose Set-Cookie to JS, so cookie-forwarding
// never actually worked here.
const TOKEN_KEY = 'auth_token';
let authToken: string | null = null;

export async function saveSession(token: string) {
  authToken = token;
  if (Platform.OS !== 'web') {
    await SecureStore.setItemAsync(TOKEN_KEY, token);
  }
}

export async function getSession(): Promise<string | null> {
  if (authToken) return authToken;
  if (Platform.OS !== 'web') {
    authToken = await SecureStore.getItemAsync(TOKEN_KEY);
  }
  return authToken;
}

export async function clearSession() {
  authToken = null;
  if (Platform.OS !== 'web') {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
  }
}

async function headers(): Promise<Record<string, string>> {
  const token = await getSession();
  const h: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Mobile-App': 'SocialOptimize/1.0',
  };
  if (token) h['Authorization'] = `Bearer ${token}`;
  return h;
}

export async function api(path: string, opts: RequestInit = {}): Promise<any> {
  const h = await headers();
  const res = await fetch(`${APP_URL}${path}`, {
    ...opts,
    headers: { ...h, ...(opts.headers as Record<string, string> || {}) },
  });

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
  const result = await api('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  if (result?.token) await saveSession(result.token);
  return result;
}

export async function register(name: string, email: string, password: string) {
  const result = await api('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ name, email, password }),
  });
  if (result?.token) await saveSession(result.token);
  return result;
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
  // /api/create expects "platforms" (an array) and "target_duration" (an
  // int, seconds) -- and its "style" field means thumbnail color style
  // (fire/clean/bold), not content tone, so the screen's content-style
  // chip (educational/funny/...) maps to "tone" instead. Sending the
  // screen's field names directly used to silently drop all three.
  return api('/api/create', {
    method: 'POST',
    body: JSON.stringify({
      topic: data.topic,
      platforms: data.platform ? [data.platform] : [],
      tone: data.style,
      target_duration: data.duration ? parseInt(data.duration, 10) : undefined,
      voice: data.voice,
    }),
  });
}

// NOTE: these four aren't called from any screen yet, and the backend
// doesn't have matching JSON routes (/api/studios, /api/analytics,
// /settings/data, /settings/update) -- add the routes before wiring these
// up to a screen, following the pattern used by /api/profile and
// /api/dashboard in app.py.
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
