export const APP_URL = 'https://social-money.onrender.com';

export const COLORS = {
  background: '#0a0a0a',
  card: '#141414',
  border: '#2a2a2a',
  gold: '#d4a017',
  text: '#f5f5f5',
  muted: '#666666',
  green: '#22c55e',
  red: '#e62020',
} as const;

export const NAV_ROUTES = [
  { name: 'Dashboard', path: '/dashboard', icon: 'flash' },
  { name: 'Create', path: '/create', icon: 'rocket' },
  { name: 'Jobs', path: '/jobs', icon: 'list' },
  { name: 'Analytics', path: '/analytics', icon: 'bar-chart' },
  { name: 'Settings', path: '/settings', icon: 'settings' },
] as const;
