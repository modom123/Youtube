import React, { useRef } from 'react';
import { View, Text, StyleSheet, TouchableOpacity, Platform } from 'react-native';
import { Screen } from '../components/Screen';
import { Card } from '../components/Card';
import { COLORS, APP_URL } from '../constants';

const WebView: any = Platform.OS !== 'web' ? require('react-native-webview').WebView : null;

const STUDIOS = [
  {
    id: 'hollywood',
    name: 'Hollywood AI Studio',
    icon: '🎬',
    desc: 'Create cinematic short films with AI actors, scenes, and professional production quality.',
    path: '/hollywood',
    color: '#8b5cf6',
    features: ['AI Actors', 'Scene Generation', 'Cinematic Quality', 'Full Production'],
  },
  {
    id: 'music',
    name: 'Music Studio',
    icon: '🎵',
    desc: 'Generate beats, background music, and full audio tracks with AI composition.',
    path: '/music-studio',
    color: '#ec4899',
    features: ['Beat Generation', 'AI Composition', 'Audio Library', 'Custom Tracks'],
  },
  {
    id: 'commercial',
    name: 'Commercial Studio',
    icon: '📺',
    desc: 'Create professional brand advertisements and promotional content.',
    path: '/commercial-studio',
    color: '#f59e0b',
    features: ['Brand Ads', 'Product Demos', 'Social Ads', 'Templates'],
  },
  {
    id: 'editing',
    name: 'Editing Room',
    icon: '✂️',
    desc: 'AI-powered video editing with smart cuts, transitions, and effects.',
    path: '/editing-room',
    color: '#10b981',
    features: ['Smart Cuts', 'Transitions', 'Effects', 'Color Grading'],
  },
];

export function StudiosScreen() {
  const [activeStudio, setActiveStudio] = React.useState<string | null>(null);
  const webViewRef = useRef<any>(null);

  if (activeStudio && Platform.OS !== 'web') {
    const studio = STUDIOS.find(s => s.id === activeStudio)!;
    return (
      <View style={{ flex: 1, backgroundColor: COLORS.background }}>
        <View style={styles.studioHeader}>
          <TouchableOpacity onPress={() => setActiveStudio(null)} style={styles.backBtn}>
            <Text style={styles.backText}>← Back</Text>
          </TouchableOpacity>
          <Text style={styles.studioHeaderTitle}>{studio.icon} {studio.name}</Text>
          <View style={{ width: 60 }} />
        </View>
        <WebView
          ref={webViewRef}
          source={{ uri: `${APP_URL}${studio.path}` }}
          style={{ flex: 1, backgroundColor: COLORS.background }}
          javaScriptEnabled
          domStorageEnabled
          injectedJavaScript={`
            (function() {
              var style = document.createElement('style');
              style.textContent = '.sidebar{display:none!important}.main{margin-left:0!important}.layout{grid-template-columns:1fr!important}';
              document.head.appendChild(style);
            })(); true;
          `}
        />
      </View>
    );
  }

  return (
    <Screen>
      <Text style={styles.title}>AI Studios</Text>
      <Text style={styles.subtitle}>Professional creative tools powered by AI</Text>

      {STUDIOS.map((studio) => (
        <TouchableOpacity
          key={studio.id}
          style={[styles.studioCard, { borderLeftColor: studio.color }]}
          onPress={() => setActiveStudio(studio.id)}
          activeOpacity={0.7}
        >
          <View style={styles.studioTop}>
            <View style={[styles.iconBox, { backgroundColor: studio.color + '22' }]}>
              <Text style={styles.studioIcon}>{studio.icon}</Text>
            </View>
            <View style={styles.studioInfo}>
              <Text style={styles.studioName}>{studio.name}</Text>
              <Text style={styles.studioDesc}>{studio.desc}</Text>
            </View>
          </View>
          <View style={styles.featureRow}>
            {studio.features.map((f) => (
              <View key={f} style={[styles.featureChip, { backgroundColor: studio.color + '15' }]}>
                <Text style={[styles.featureText, { color: studio.color }]}>{f}</Text>
              </View>
            ))}
          </View>
        </TouchableOpacity>
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 28, fontWeight: '800', color: COLORS.text, marginBottom: 4 },
  subtitle: { fontSize: 14, color: COLORS.muted, marginBottom: 24 },
  studioCard: {
    backgroundColor: COLORS.card, borderRadius: 16, padding: 16, marginBottom: 14,
    borderWidth: 1, borderColor: COLORS.border, borderLeftWidth: 4,
  },
  studioTop: { flexDirection: 'row', gap: 14, marginBottom: 12 },
  iconBox: { width: 52, height: 52, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  studioIcon: { fontSize: 28 },
  studioInfo: { flex: 1 },
  studioName: { fontSize: 17, fontWeight: '700', color: COLORS.text, marginBottom: 4 },
  studioDesc: { fontSize: 13, color: COLORS.muted, lineHeight: 18 },
  featureRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
  featureChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 6 },
  featureText: { fontSize: 11, fontWeight: '600' },
  studioHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    padding: 16, paddingTop: 50, backgroundColor: COLORS.card, borderBottomWidth: 1, borderBottomColor: COLORS.border,
  },
  studioHeaderTitle: { fontSize: 16, fontWeight: '700', color: COLORS.text },
  backBtn: { padding: 4 },
  backText: { color: COLORS.gold, fontSize: 15, fontWeight: '600' },
});
