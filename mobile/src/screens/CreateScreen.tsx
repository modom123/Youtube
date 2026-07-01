import React, { useState } from 'react';
import { View, Text, StyleSheet, Alert, ScrollView, TouchableOpacity } from 'react-native';
import { Screen } from '../components/Screen';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { Input } from '../components/Input';
import { createVideo } from '../services/api';
import { COLORS } from '../constants';
import { useRouter } from 'expo-router';
import * as Haptics from 'expo-haptics';

const PLATFORMS = [
  { id: 'tiktok', name: 'TikTok', icon: '🎵' },
  { id: 'youtube_shorts', name: 'YT Shorts', icon: '▶️' },
  { id: 'instagram_reels', name: 'IG Reels', icon: '📸' },
  { id: 'linkedin', name: 'LinkedIn', icon: '💼' },
  { id: 'facebook', name: 'Facebook', icon: '📘' },
  { id: 'x_twitter', name: 'X / Twitter', icon: '🐦' },
];

const STYLES = [
  { id: 'educational', name: 'Educational', icon: '📚' },
  { id: 'entertaining', name: 'Entertaining', icon: '🎭' },
  { id: 'promotional', name: 'Promotional', icon: '📢' },
  { id: 'storytelling', name: 'Storytelling', icon: '📖' },
  { id: 'tutorial', name: 'Tutorial', icon: '🔧' },
  { id: 'motivational', name: 'Motivational', icon: '💪' },
];

const DURATIONS = [
  { id: '15', name: '15s' },
  { id: '30', name: '30s' },
  { id: '60', name: '60s' },
  { id: '90', name: '90s' },
];

export function CreateScreen() {
  const navigation = useRouter();
  const [topic, setTopic] = useState('');
  const [platform, setPlatform] = useState('tiktok');
  const [style, setStyle] = useState('educational');
  const [duration, setDuration] = useState('30');
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    if (!topic.trim()) {
      Alert.alert('Topic Required', 'Please enter a topic for your video');
      return;
    }

    setLoading(true);
    try {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
      const result = await createVideo({ topic, platform, style, duration });
      Alert.alert(
        'Video Creating!',
        `Your video is being generated. Job ID: ${result.job_id || 'processing'}`,
        [
          { text: 'View Jobs', onPress: () => navigation.push('/(tabs)/jobs') },
          { text: 'Create Another', style: 'cancel' },
        ]
      );
      setTopic('');
    } catch (err: any) {
      Alert.alert('Error', err.message || 'Failed to create video');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen>
      <Text style={styles.title}>Create Video</Text>
      <Text style={styles.subtitle}>Describe your video and AI does the rest</Text>

      <Input
        label="What's your video about?"
        placeholder="e.g., 5 morning habits for productivity"
        value={topic}
        onChangeText={setTopic}
        multiline
        numberOfLines={3}
        style={{ minHeight: 80, textAlignVertical: 'top' }}
      />

      {/* Platform */}
      <Text style={styles.sectionLabel}>Platform</Text>
      <View style={styles.chipRow}>
        {PLATFORMS.map((p) => (
          <TouchableOpacity
            key={p.id}
            style={[styles.chip, platform === p.id && styles.chipActive]}
            onPress={() => { setPlatform(p.id); Haptics.selectionAsync(); }}
          >
            <Text style={styles.chipIcon}>{p.icon}</Text>
            <Text style={[styles.chipText, platform === p.id && styles.chipTextActive]}>{p.name}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Style */}
      <Text style={styles.sectionLabel}>Style</Text>
      <View style={styles.chipRow}>
        {STYLES.map((s) => (
          <TouchableOpacity
            key={s.id}
            style={[styles.chip, style === s.id && styles.chipActive]}
            onPress={() => { setStyle(s.id); Haptics.selectionAsync(); }}
          >
            <Text style={styles.chipIcon}>{s.icon}</Text>
            <Text style={[styles.chipText, style === s.id && styles.chipTextActive]}>{s.name}</Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Duration */}
      <Text style={styles.sectionLabel}>Duration</Text>
      <View style={styles.durationRow}>
        {DURATIONS.map((d) => (
          <TouchableOpacity
            key={d.id}
            style={[styles.durChip, duration === d.id && styles.durChipActive]}
            onPress={() => { setDuration(d.id); Haptics.selectionAsync(); }}
          >
            <Text style={[styles.durText, duration === d.id && styles.durTextActive]}>{d.name}</Text>
          </TouchableOpacity>
        ))}
      </View>

      <View style={{ marginTop: 24 }}>
        <Button title="Generate Video" onPress={handleCreate} loading={loading} size="large" />
      </View>

      {/* Quick Templates */}
      <Text style={[styles.sectionLabel, { marginTop: 32 }]}>Quick Templates</Text>
      {[
        { topic: '5 productivity hacks for entrepreneurs', platform: 'tiktok' },
        { topic: 'Behind the scenes of running a small business', platform: 'instagram_reels' },
        { topic: 'How AI is changing content creation in 2026', platform: 'youtube_shorts' },
        { topic: 'Customer testimonial showcase', platform: 'linkedin' },
      ].map((t, i) => (
        <Card key={i} onPress={() => { setTopic(t.topic); setPlatform(t.platform); }}>
          <Text style={styles.templateText}>{t.topic}</Text>
          <Text style={styles.templatePlatform}>{PLATFORMS.find(p => p.id === t.platform)?.name}</Text>
        </Card>
      ))}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 28, fontWeight: '800', color: COLORS.text, marginBottom: 4 },
  subtitle: { fontSize: 14, color: COLORS.muted, marginBottom: 24 },
  sectionLabel: { fontSize: 14, fontWeight: '700', color: COLORS.text, marginBottom: 10, marginTop: 16 },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  chip: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: COLORS.card, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 8,
    borderWidth: 1, borderColor: COLORS.border,
  },
  chipActive: { borderColor: COLORS.gold, backgroundColor: COLORS.gold + '15' },
  chipIcon: { fontSize: 16 },
  chipText: { fontSize: 12, fontWeight: '600', color: COLORS.muted },
  chipTextActive: { color: COLORS.gold },
  durationRow: { flexDirection: 'row', gap: 10 },
  durChip: {
    flex: 1, alignItems: 'center', paddingVertical: 12,
    backgroundColor: COLORS.card, borderRadius: 10, borderWidth: 1, borderColor: COLORS.border,
  },
  durChipActive: { borderColor: COLORS.gold, backgroundColor: COLORS.gold + '15' },
  durText: { fontSize: 15, fontWeight: '700', color: COLORS.muted },
  durTextActive: { color: COLORS.gold },
  templateText: { fontSize: 14, fontWeight: '600', color: COLORS.text },
  templatePlatform: { fontSize: 11, color: COLORS.muted, marginTop: 4 },
});
