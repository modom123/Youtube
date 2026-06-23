# Social Optimize - Android App

Capacitor wrapper that loads the Social Optimize web app in a native Android WebView.

## Prerequisites

- Node.js 18+
- Android Studio (with SDK 34+)
- Java 17+

## Setup

```bash
cd mobile
npm install
npx cap sync android
```

## Development

Open in Android Studio:
```bash
npx cap open android
```

Or build a debug APK from the command line:
```bash
npm run cap:build
```

The APK will be at `android/app/build/outputs/apk/debug/app-debug.apk`.

## Release Build

```bash
npm run cap:release
```

Sign the release APK with your keystore before uploading to Google Play.

## Configuration

- **Server URL**: Set in `capacitor.config.ts` → `server.url`
- **App ID**: `com.socialoptimize.app`
- **Theme**: Dark (#0a0a0a) with gold (#d4af37) accent
