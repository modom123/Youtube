import React, { useState, useEffect, useCallback } from 'react';
import { View, Text, StyleSheet, FlatList, TouchableOpacity, Alert, Share } from 'react-native';
import { Screen } from '../components/Screen';
import { Card } from '../components/Card';
import { getJobs, getJobStatus } from '../services/api';
import { COLORS, APP_URL } from '../constants';

interface Job {
  id: number;
  topic: string;
  status: string;
  platform: string;
  style: string;
  video_url: string | null;
  created_at: string;
  progress: number;
}

export function JobsScreen() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<string>('all');

  const load = useCallback(async () => {
    try {
      const data = await getJobs();
      const list = Array.isArray(data) ? data : data?.jobs || [];
      setJobs(list);
    } catch {}
  }, []);

  useEffect(() => { load(); }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const handleShare = async (job: Job) => {
    if (!job.video_url) return;
    try {
      await Share.share({
        message: `Check out my AI-generated video: ${job.topic}`,
        url: job.video_url.startsWith('http') ? job.video_url : `${APP_URL}${job.video_url}`,
      });
    } catch {}
  };

  const filtered = filter === 'all' ? jobs : jobs.filter(j => j.status === filter);

  const filters = ['all', 'done', 'processing', 'queued', 'error'];

  return (
    <Screen refreshing={refreshing} onRefresh={onRefresh}>
      <Text style={styles.title}>My Videos</Text>
      <Text style={styles.subtitle}>{jobs.length} total videos</Text>

      {/* Filters */}
      <View style={styles.filterRow}>
        {filters.map((f) => (
          <TouchableOpacity
            key={f}
            style={[styles.filterChip, filter === f && styles.filterActive]}
            onPress={() => setFilter(f)}
          >
            <Text style={[styles.filterText, filter === f && styles.filterTextActive]}>
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {filtered.length === 0 ? (
        <Card>
          <Text style={styles.emptyText}>No videos found</Text>
        </Card>
      ) : (
        filtered.map((job) => (
          <JobCard key={job.id} job={job} onShare={() => handleShare(job)} />
        ))
      )}
    </Screen>
  );
}

function JobCard({ job, onShare }: { job: Job; onShare: () => void }) {
  const statusColors: Record<string, string> = {
    done: COLORS.green, processing: '#f59e0b', queued: '#3b82f6', error: COLORS.red,
  };
  const color = statusColors[job.status] || COLORS.muted;

  return (
    <Card>
      <View style={styles.jobHeader}>
        <View style={styles.jobInfo}>
          <Text style={styles.jobTopic} numberOfLines={2}>{job.topic}</Text>
          <View style={styles.jobMetaRow}>
            <Text style={styles.jobMeta}>{job.platform}</Text>
            {job.style ? <Text style={styles.jobMeta}> · {job.style}</Text> : null}
            <Text style={styles.jobMeta}> · {timeAgo(job.created_at)}</Text>
          </View>
        </View>
        <View style={[styles.statusBadge, { backgroundColor: color + '22' }]}>
          <View style={[styles.statusDot, { backgroundColor: color }]} />
          <Text style={[styles.statusText, { color }]}>{job.status}</Text>
        </View>
      </View>

      {job.status === 'processing' && (
        <View style={styles.progressBar}>
          <View style={[styles.progressFill, { width: `${(job.progress || 50)}%` }]} />
        </View>
      )}

      {job.status === 'done' && (
        <View style={styles.actions}>
          <TouchableOpacity style={styles.actionBtn} onPress={onShare}>
            <Text style={styles.actionIcon}>📤</Text>
            <Text style={styles.actionText}>Share</Text>
          </TouchableOpacity>
          {job.video_url && (
            <TouchableOpacity style={styles.actionBtn}>
              <Text style={styles.actionIcon}>▶️</Text>
              <Text style={styles.actionText}>Play</Text>
            </TouchableOpacity>
          )}
          <TouchableOpacity style={styles.actionBtn}>
            <Text style={styles.actionIcon}>📥</Text>
            <Text style={styles.actionText}>Download</Text>
          </TouchableOpacity>
        </View>
      )}
    </Card>
  );
}

function timeAgo(dateStr: string) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const styles = StyleSheet.create({
  title: { fontSize: 28, fontWeight: '800', color: COLORS.text, marginBottom: 4 },
  subtitle: { fontSize: 14, color: COLORS.muted, marginBottom: 16 },
  filterRow: { flexDirection: 'row', gap: 8, marginBottom: 16, flexWrap: 'wrap' },
  filterChip: {
    paddingHorizontal: 14, paddingVertical: 6, borderRadius: 8,
    backgroundColor: COLORS.card, borderWidth: 1, borderColor: COLORS.border,
  },
  filterActive: { borderColor: COLORS.gold, backgroundColor: COLORS.gold + '15' },
  filterText: { fontSize: 12, fontWeight: '600', color: COLORS.muted },
  filterTextActive: { color: COLORS.gold },
  emptyText: { color: COLORS.muted, textAlign: 'center', padding: 20, fontSize: 14 },
  jobHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' },
  jobInfo: { flex: 1, marginRight: 12 },
  jobTopic: { fontSize: 15, fontWeight: '700', color: COLORS.text, marginBottom: 4 },
  jobMetaRow: { flexDirection: 'row' },
  jobMeta: { fontSize: 12, color: COLORS.muted },
  statusBadge: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 10, paddingVertical: 5, borderRadius: 8, gap: 6 },
  statusDot: { width: 6, height: 6, borderRadius: 3 },
  statusText: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase' },
  progressBar: { height: 4, backgroundColor: COLORS.border, borderRadius: 2, marginTop: 12, overflow: 'hidden' },
  progressFill: { height: '100%', backgroundColor: '#f59e0b', borderRadius: 2 },
  actions: { flexDirection: 'row', gap: 16, marginTop: 12, paddingTop: 12, borderTopWidth: 1, borderTopColor: COLORS.border },
  actionBtn: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  actionIcon: { fontSize: 16 },
  actionText: { fontSize: 13, fontWeight: '600', color: COLORS.gold },
});
