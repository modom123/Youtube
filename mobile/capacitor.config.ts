import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.socialoptimize.app',
  appName: 'Social Optimize',
  webDir: 'www',
  server: {
    url: 'https://socialoptimize.online',
    cleartext: false,
  },
  android: {
    backgroundColor: '#0a0a0a',
    allowMixedContent: false,
    overScrollMode: 'never',
  },
  plugins: {
    SplashScreen: {
      launchAutoHide: true,
      launchFadeOutDuration: 300,
      backgroundColor: '#0a0a0a',
      showSpinner: true,
      spinnerColor: '#d4af37',
    },
    StatusBar: {
      style: 'DARK',
      backgroundColor: '#0a0a0a',
    },
  },
};

export default config;
