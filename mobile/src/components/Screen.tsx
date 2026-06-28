import React from 'react';
import { View, StyleSheet, ScrollView, RefreshControl } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { COLORS } from '../constants';

interface ScreenProps {
  children: React.ReactNode;
  scrollable?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  noPadding?: boolean;
}

export function Screen({ children, scrollable = true, refreshing, onRefresh, noPadding }: ScreenProps) {
  const content = scrollable ? (
    <ScrollView
      style={styles.scroll}
      contentContainerStyle={[styles.content, noPadding && { padding: 0 }]}
      showsVerticalScrollIndicator={false}
      refreshControl={onRefresh ? (
        <RefreshControl refreshing={refreshing ?? false} onRefresh={onRefresh} tintColor={COLORS.gold} />
      ) : undefined}
    >
      {children}
    </ScrollView>
  ) : (
    <View style={[styles.content, noPadding && { padding: 0 }]}>{children}</View>
  );

  return <SafeAreaView style={styles.container} edges={['top']}>{content}</SafeAreaView>;
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  scroll: { flex: 1 },
  content: { padding: 16, paddingBottom: 32 },
});
