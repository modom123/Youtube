import React, { useState } from 'react';
import { View, Text, StyleSheet, Alert, Switch, TouchableOpacity, Linking } from 'react-native';
import { Screen } from '../components/Screen';
import { Card } from '../components/Card';
import { Button } from '../components/Button';
import { useAuth } from '../context/AuthContext';
import { COLORS, APP_URL } from '../constants';

export function SettingsScreen() {
  const { user, logout } = useAuth();
  const [notifications, setNotifications] = useState(true);
  const [darkMode, setDarkMode] = useState(true);

  const handleLogout = () => {
    Alert.alert('Sign Out', 'Are you sure you want to sign out?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Sign Out', style: 'destructive', onPress: logout },
    ]);
  };

  const handleUpgrade = () => {
    Linking.openURL(`${APP_URL}/pricing`);
  };

  const tier = user?.subscription_tier || 'free';
  const tierInfo: Record<string, { price: string; videos: string; next: string }> = {
    free: { price: 'Free', videos: '3/mo', next: 'Starter ($9.99/mo)' },
    starter: { price: '$9.99/mo', videos: '10/mo', next: 'Creator ($29/mo)' },
    creator: { price: '$29/mo', videos: '30/mo', next: 'Pro ($79/mo)' },
    pro: { price: '$79/mo', videos: '100/mo', next: 'Agency ($199/mo)' },
    agency: { price: '$199/mo', videos: '200/mo', next: '' },
  };

  return (
    <Screen>
      <Text style={styles.title}>Settings</Text>

      {/* Profile */}
      <Card>
        <View style={styles.profileRow}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{(user?.name || 'U')[0].toUpperCase()}</Text>
          </View>
          <View style={styles.profileInfo}>
            <Text style={styles.profileName}>{user?.name || 'User'}</Text>
            <Text style={styles.profileEmail}>{user?.email}</Text>
          </View>
        </View>
      </Card>

      {/* Subscription */}
      <Text style={styles.sectionTitle}>Subscription</Text>
      <Card>
        <View style={styles.subRow}>
          <View>
            <Text style={styles.subTier}>{tier.charAt(0).toUpperCase() + tier.slice(1)} Plan</Text>
            <Text style={styles.subDetail}>{tierInfo[tier]?.price} · {tierInfo[tier]?.videos} videos</Text>
          </View>
          {tier !== 'agency' && (
            <Button title="Upgrade" onPress={handleUpgrade} size="small" />
          )}
        </View>
        <View style={styles.usageBar}>
          <View style={[styles.usageFill, { width: `${Math.min((user?.videos_used || 0) / (tier === 'free' ? 3 : tier === 'starter' ? 15 : tier === 'creator' ? 50 : 125) * 100, 100)}%` }]} />
        </View>
        <Text style={styles.usageText}>
          {user?.videos_used || 0} / {tier === 'free' ? 3 : tier === 'starter' ? 15 : tier === 'creator' ? 50 : 125} videos used
        </Text>
      </Card>

      {/* Preferences */}
      <Text style={styles.sectionTitle}>Preferences</Text>
      <Card>
        <SettingRow label="Push Notifications" value={notifications} onToggle={setNotifications} />
        <SettingRow label="Dark Mode" value={darkMode} onToggle={setDarkMode} />
      </Card>

      {/* Links */}
      <Text style={styles.sectionTitle}>Support</Text>
      <Card>
        <LinkRow label="Help Center" onPress={() => Linking.openURL(`${APP_URL}/help`)} />
        <LinkRow label="Privacy Policy" onPress={() => Linking.openURL(`${APP_URL}/privacy`)} />
        <LinkRow label="Terms of Service" onPress={() => Linking.openURL(`${APP_URL}/terms`)} />
        <LinkRow label="Contact Support" onPress={() => Linking.openURL('mailto:support@socialoptimize.online')} />
      </Card>

      {/* Account */}
      <Text style={styles.sectionTitle}>Account</Text>
      <Card>
        <LinkRow label="Manage Subscription" onPress={() => Linking.openURL(`${APP_URL}/settings`)} />
        <LinkRow label="Connected Accounts" onPress={() => Linking.openURL(`${APP_URL}/accounts`)} />
      </Card>

      <View style={{ marginTop: 24 }}>
        <Button title="Sign Out" onPress={handleLogout} variant="danger" size="large" />
      </View>

      <Text style={styles.version}>Social Optimize v1.0.0</Text>
    </Screen>
  );
}

function SettingRow({ label, value, onToggle }: { label: string; value: boolean; onToggle: (v: boolean) => void }) {
  return (
    <View style={styles.settingRow}>
      <Text style={styles.settingLabel}>{label}</Text>
      <Switch
        value={value}
        onValueChange={onToggle}
        trackColor={{ false: COLORS.border, true: COLORS.gold + '66' }}
        thumbColor={value ? COLORS.gold : COLORS.muted}
      />
    </View>
  );
}

function LinkRow({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.linkRow} onPress={onPress}>
      <Text style={styles.linkText}>{label}</Text>
      <Text style={styles.linkArrow}>›</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 28, fontWeight: '800', color: COLORS.text, marginBottom: 16 },
  sectionTitle: { fontSize: 14, fontWeight: '700', color: COLORS.muted, textTransform: 'uppercase', letterSpacing: 1, marginTop: 20, marginBottom: 10 },
  profileRow: { flexDirection: 'row', alignItems: 'center', gap: 16 },
  avatar: { width: 56, height: 56, borderRadius: 28, backgroundColor: COLORS.gold, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontSize: 24, fontWeight: '800', color: '#000' },
  profileInfo: {},
  profileName: { fontSize: 18, fontWeight: '700', color: COLORS.text },
  profileEmail: { fontSize: 13, color: COLORS.muted, marginTop: 2 },
  subRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 },
  subTier: { fontSize: 16, fontWeight: '700', color: COLORS.text },
  subDetail: { fontSize: 13, color: COLORS.muted, marginTop: 2 },
  usageBar: { height: 6, backgroundColor: COLORS.border, borderRadius: 3, overflow: 'hidden', marginBottom: 6 },
  usageFill: { height: '100%', backgroundColor: COLORS.gold, borderRadius: 3 },
  usageText: { fontSize: 12, color: COLORS.muted },
  settingRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 8 },
  settingLabel: { fontSize: 15, color: COLORS.text },
  linkRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: COLORS.border },
  linkText: { fontSize: 15, color: COLORS.text },
  linkArrow: { fontSize: 20, color: COLORS.muted },
  version: { textAlign: 'center', color: COLORS.muted, fontSize: 12, marginTop: 24, marginBottom: 16 },
});
