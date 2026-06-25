import { useRef, useState, useCallback } from 'react';
import type WebView from 'react-native-webview';

export function useWebView(baseUrl: string) {
  const webViewRef = useRef<WebView>(null);
  const [canGoBack, setCanGoBack] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [currentUrl, setCurrentUrl] = useState(baseUrl);

  const navigate = useCallback((path: string) => {
    webViewRef.current?.injectJavaScript(
      `window.location.href = '${baseUrl}${path}'; true;`
    );
  }, [baseUrl]);

  const goBack = useCallback(() => {
    if (canGoBack) webViewRef.current?.goBack();
  }, [canGoBack]);

  const reload = useCallback(() => {
    webViewRef.current?.reload();
  }, []);

  return {
    webViewRef,
    canGoBack,
    setCanGoBack,
    isLoading,
    setIsLoading,
    currentUrl,
    setCurrentUrl,
    navigate,
    goBack,
    reload,
  };
}
