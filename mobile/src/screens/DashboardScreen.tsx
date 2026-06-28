import React, { useState, useEffect, useCallback } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity } from 'react-native';
import { Screen } from '../components/Screen';
import { Card, StatCard } from '../components/Card';
import { Button } from '../components/Button';
import { useAuth } from '../context/AuthContext';
import { getDashboard, getJobs } from '../services/api';
import { COLORS } from '../constants';
import { useRouter } from 'expo-router';

interface Job {
  id: number;
  topic: string;
  status: string;
  platform: string;
  created_at: string;
}

export function DashboardScreen() {
  const navigation = useRouter();
  const { user } = useAuth();
  const [stats, setStats] = useState<any>(null);
  const [recentJobs, setRecentJobs] = useState<Job[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [dash, jobs] = await Promise.all([
        getDashboard().catch(() => null),
        getJobs().catch(() => []),
      ]);
      if (dash) setStats(dash);
      if (Array.isArray(jobs)) setRecentJobs(jobs.slice(0, 5));
      else if (jobs?.jobs) setRecentJobs(jobs.jobs.slice(0, 5));
    } catch {}
  }, []);

  useEffect(() => { load(); }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const tier = user?.subscription_tier || 'free';
  const tierColors: Record<string, string> = {
    free: '#6b7280', starter: '#3b82f6', creator: '#8b5cf6', agency: '#d4a017',
  };

  return (
    <Screen refreshing={refreshing} onRefresh={onRefresh}>
      {/* Welcome */}
      <View style={styles.welcome}>
        <View>
          <Text style={styles.greeting}>Welcome back,</Text>
          <Text style={styles.name}>{user?.name || 'Creator'}</Text>
        </View>
        <View style={[styles.tierBadge, { backgroundColor: tierColors[tier] + '22', borderColor: tierColors[tier] }]}>
          <Text style={[styles.tierText, { color: tierColors[tier] }]}>{tier.toUpperCase()}</Text>
        </View>
      </View>

      {/* Stats */}
      <View style={styles.statsRow}>
        <StatCard label="Videos" value={user?.videos_used ?? 0} color={COLORS.gold} />
        <StatCard label="Credits" value={user?.credits_used ?? 0} color={COLORS.green} />
        <StatCard
          label="Plan"
          value={tier === 'free' ? 'Free' : `$${tier === 'starter' ? 29 : tier === 'creator' ? 79 : 199}`}
          sub="/month"
        />
      </View>

      {/* Quick Create */}
      <Card>
        <Text style={styles.cardTitle}>Quick Create</Text>
        <Text style={styles.cardSub}>Create an AI video in under 2 minutes</Text>
        <View style={styles.quickActions}>
          <Button title="Create Video" onPress={() => navigation.push('/(tabs)/create')} size="medium" />
          <Button title="Studios" onPress={() => navigation.push('/(tabs)/studios')} variant="secondary" size="medium" />
        </View>
      </Card>

      {/* Recent Jobs */}
      <Text style={styles.sectionTitle}>Recent Videos</Text>
      {recentJobs.length === 0 ? (
        <Card>
          <Text style={styles.emptyText}>No videos yet. Create your first one!</Text>
        </Card>
      ) : (
        recentJobs.map((job) => (
          <Card key={job.id} onPress={() => navigation.push('/(tabs)/jobs')}>
            <View style={styles.jobRow}>
              <View style={styles.jobInfo}>
                <Text style={styles.jobTopic} numberOfLines={1}>{job.topic}</Text>
                <Text style={styles.jobMeta}>{job.platform} · {timeAgo(job.created_at)}</Text>
              </View>
              <StatusBadge status={job.status} />
            </View>
          </Card>
        ))
      )}

      {/* Studios Grid */}
      <Text style={styles.sectionTitle}>AI Studios</Text>
      <View style={styles.studiosGrid}>
        {[
          { name: 'Hollywood', icon: '🎬', desc: 'Cinematic AI videos' },
          { name: 'Music', icon: '🎵', desc: 'Beat generation' },
          { name: 'Commercial', icon: '📺', desc: 'Brand advertisements' },
          { name: 'Editing', icon: '✂️', desc: 'AI video editing' },
        ].map((s) => (
          <TouchableOpacity key={s.name} style={styles.studioCard} onPress={() => navigation.push('/(tabs)/studios')}>
            <Text style={styles.studioIcon}>{s.icon}</Text>
            <Text style={styles.studioName}>{s.name}</Text>
            <Text style={styles.studioDesc}>{s.desc}</Text>
          </TouchableOpacity>
        ))}
      </View>
    </Screen>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    done: COLORS.green, processing: '#f59e0b', queued: '#3b82f6', error: COLORS.red,
  };
  return (
    <View style={[styles.badge, { backgroundColor: (colors[status] || COLORS.muted) + '22' }]}>
      <Text style={[styles.badgeText, { color: colors[status] || COLORS.muted }]}>
        {status.toUpperCase()}
      </Text>
    </View>
  );
}

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const styles = StyleSheet.create({
  welcome: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 },
  greeting: { fontSize: 14, color: COLORS.muted },
  name: { fontSize: 24, fontWeight: '800', color: COLORS.text },
  tierBadge: { paddingHorizontal: 12, paddingVertical: 4, borderRadius: 8, borderWidth: 1 },
  tierText: { fontSize: 11, fontWeight: '700', letterSpacing: 1 },
  statsRow: { flexDirection: 'row', gap: 10, marginBottom: 16 },
  cardTitle: { fontSize: 18, fontWeight: '700', color: COLORS.text, marginBottom: 4 },
  cardSub: { fontSize: 13, color: COLORS.muted, marginBottom: 16 },
  quickActions: { flexDirection: 'row', gap: 12 },
  sectionTitle: { fontSize: 18, fontWeight: '700', color: COLORS.text, marginBottom: 12, marginTop: 8 },
  jobRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  jobInfo: { flex: 1, marginRight: 12 },
  jobTopic: { fontSize: 15, fontWeight: '600', color: COLORS.text },
  jobMeta: { fontSize: 12, color: COLORS.muted, marginTop: 2 },
  badge: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8 },
  badgeText: { fontSize: 10, fontWeight: '700', letterSpacing: 0.5 },
  emptyText: { color: COLORS.muted, textAlign: 'center', padding: 20, fontSize: 14 },
  studiosGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  studioCard: {
    backgroundColor: COLORS.card, borderRadius: 12, padding: 16,
    borderWidth: 1, borderColor: COLORS.border, width: '48%', flexGrow: 1,
  },
  studioIcon: { fontSize: 28, marginBottom: 8 },
  studioName: { fontSize: 14, fontWeight: '700', color: COLORS.text },
  studioDesc: { fontSize: 11, color: COLORS.muted, marginTop: 2 },
});
