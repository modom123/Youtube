import React, { useRef, useState, useCallback } from 'react';
import {
  StyleSheet,
  View,
  Text,
  TouchableOpacity,
  ActivityIndicator,
  Platform,
  SafeAreaView,
  BackHandler,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { useFocusEffect, Redirect } from 'expo-router';
import { COLORS, APP_URL, NAV_ROUTES } from '../src/constants';

// WebView is native-only; on web we redirect to the real app
const WebView: any = Platform.OS !== 'web'
  ? require('react-native-webview').WebView
  : null;

export default function MainScreen() {
  // On web platform, redirect to the full web app
  if (Platform.OS === 'web') {
    if (typeof window !== 'undefined') {
      window.location.replace(APP_URL + '/dashboard');
    }
    return null;
  }
  const webViewRef = useRef<WebView>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const [canGoBack, setCanGoBack] = useState(false);
  const [activeRoute, setActiveRoute] = useState('/dashboard');

  // Hardware back button (Android)
  useFocusEffect(
    useCallback(() => {
      const handler = BackHandler.addEventListener('hardwareBackPress', () => {
        if (canGoBack) {
          webViewRef.current?.goBack();
          return true;
        }
        return false;
      });
      return () => handler.remove();
    }, [canGoBack])
  );

  const navigate = (path: string) => {
    setActiveRoute(path);
    webViewRef.current?.injectJavaScript(
      `window.location.href = '${APP_URL}${path}'; true;`
    );
  };

  const handleNavigationStateChange = (navState: any) => {
    setCanGoBack(navState.canGoBack);
    const path = navState.url.replace(APP_URL, '') || '/';
    setActiveRoute(path);
  };

  if (hasError) {
    return (
      <SafeAreaView style={styles.errorContainer}>
        <StatusBar style="light" />
        <View style={styles.logo}>
          <Text style={styles.logoText}>S</Text>
        </View>
        <Text style={styles.errorTitle}>Connection Error</Text>
        <Text style={styles.errorSub}>
          Could not reach the Social Optimize Machine server.{'\n'}
          Please check your internet connection.
        </Text>
        <TouchableOpacity
          style={styles.retryBtn}
          onPress={() => { setHasError(false); webViewRef.current?.reload(); }}
        >
          <Text style={styles.retryText}>Retry</Text>
        </TouchableOpacity>
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.container}>
      <StatusBar style="light" backgroundColor={COLORS.background} />

      {/* WebView */}
      <WebView
        ref={webViewRef}
        source={{ uri: `${APP_URL}/dashboard` }}
        style={styles.webview}
        onLoadStart={() => setIsLoading(true)}
        onLoadEnd={() => setIsLoading(false)}
        onError={() => setHasError(true)}
        onHttpError={(e) => {
          if (e.nativeEvent.statusCode >= 500) setHasError(true);
        }}
        onNavigationStateChange={handleNavigationStateChange}
        javaScriptEnabled
        domStorageEnabled
        allowsBackForwardNavigationGestures={Platform.OS === 'ios'}
        pullToRefreshEnabled
        startInLoadingState={false}
        // Inject CSS to hide the sidebar and adjust for mobile
        injectedJavaScript={`
          (function() {
            var style = document.createElement('style');
            style.textContent = \`
              @media (max-width: 768px) {
                .sidebar { display: none !important; }
                .main { margin-left: 0 !important; }
                .layout { grid-template-columns: 1fr !important; }
              }
            \`;
            document.head.appendChild(style);
          })();
          true;
        `}
        userAgent={`SOMApp/${Platform.OS} ReactNative`}
      />

      {/* Loading indicator */}
      {isLoading && (
        <View style={styles.loadingOverlay}>
          <ActivityIndicator size="large" color={COLORS.gold} />
        </View>
      )}

      {/* Bottom navigation bar */}
      <SafeAreaView style={styles.navbar}>
        {NAV_ROUTES.map((route) => {
          const isActive = activeRoute.startsWith(route.path);
          return (
            <TouchableOpacity
              key={route.path}
              style={styles.navItem}
              onPress={() => navigate(route.path)}
              accessibilityLabel={route.name}
            >
              <NavIcon name={route.icon} active={isActive} />
              <Text style={[styles.navLabel, isActive && styles.navLabelActive]}>
                {route.name}
              </Text>
            </TouchableOpacity>
          );
        })}
      </SafeAreaView>
    </View>
  );
}

function NavIcon({ name, active }: { name: string; active: boolean }) {
  const color = active ? COLORS.gold : COLORS.muted;
  const icons: Record<string, string> = {
    flash: '⚡', rocket: '🚀', list: '📋', 'bar-chart': '📊', settings: '⚙️',
  };
  return <Text style={{ fontSize: 20, marginBottom: 2 }}>{icons[name] ?? '●'}</Text>;
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  webview: {
    flex: 1,
    backgroundColor: COLORS.background,
  },
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: COLORS.background,
    alignItems: 'center',
    justifyContent: 'center',
  },
  navbar: {
    flexDirection: 'row',
    backgroundColor: COLORS.card,
    borderTopWidth: 1,
    borderTopColor: COLORS.border,
  },
  navItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    paddingTop: 12,
  },
  navLabel: {
    fontSize: 10,
    color: COLORS.muted,
    marginTop: 2,
    fontWeight: '500',
  },
  navLabelActive: {
    color: COLORS.gold,
    fontWeight: '700',
  },
  errorContainer: {
    flex: 1,
    backgroundColor: COLORS.background,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  logo: {
    width: 80,
    height: 80,
    backgroundColor: COLORS.gold,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 24,
  },
  logoText: {
    fontSize: 40,
    fontWeight: '900',
    color: COLORS.background,
  },
  errorTitle: {
    fontSize: 20,
    fontWeight: '700',
    color: COLORS.text,
    marginBottom: 12,
  },
  errorSub: {
    fontSize: 14,
    color: COLORS.muted,
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 32,
  },
  retryBtn: {
    backgroundColor: COLORS.gold,
    paddingHorizontal: 32,
    paddingVertical: 14,
    borderRadius: 12,
  },
  retryText: {
    color: COLORS.background,
    fontWeight: '700',
    fontSize: 16,
  },
});
