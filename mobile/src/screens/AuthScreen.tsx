import React, { useState } from 'react';
import { View, Text, StyleSheet, KeyboardAvoidingView, Platform, Alert, Image } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Button } from '../components/Button';
import { Input } from '../components/Input';
import { useAuth } from '../context/AuthContext';
import { COLORS } from '../constants';

export function AuthScreen() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!email || !password) {
      Alert.alert('Error', 'Please fill in all fields');
      return;
    }
    if (mode === 'register' && !name) {
      Alert.alert('Error', 'Please enter your name');
      return;
    }

    setLoading(true);
    try {
      if (mode === 'login') {
        await login(email, password);
      } else {
        await register(name, email, password);
      }
    } catch (err: any) {
      Alert.alert('Error', err.message || 'Authentication failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.inner}
      >
        <View style={styles.header}>
          <View style={styles.logoBox}>
            <Text style={styles.logoText}>S</Text>
          </View>
          <Text style={styles.title}>Social Optimize</Text>
          <Text style={styles.subtitle}>AI-Powered Video Content Factory</Text>
        </View>

        <View style={styles.form}>
          {mode === 'register' && (
            <Input
              label="Full Name"
              placeholder="Your name"
              value={name}
              onChangeText={setName}
              autoCapitalize="words"
            />
          )}
          <Input
            label="Email"
            placeholder="you@example.com"
            value={email}
            onChangeText={setEmail}
            keyboardType="email-address"
            autoCapitalize="none"
            autoCorrect={false}
          />
          <Input
            label="Password"
            placeholder="Your password"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
          />

          <Button
            title={mode === 'login' ? 'Sign In' : 'Create Account'}
            onPress={handleSubmit}
            loading={loading}
            size="large"
          />

          <View style={styles.switchRow}>
            <Text style={styles.switchText}>
              {mode === 'login' ? "Don't have an account?" : "Already have an account?"}
            </Text>
            <Button
              title={mode === 'login' ? 'Sign Up' : 'Sign In'}
              onPress={() => setMode(mode === 'login' ? 'register' : 'login')}
              variant="outline"
              size="small"
            />
          </View>
        </View>

        <View style={styles.features}>
          <FeatureItem icon="🎬" text="AI video creation in 2 minutes" />
          <FeatureItem icon="📱" text="Publish to 8+ platforms" />
          <FeatureItem icon="🎵" text="Music, voiceover & captions" />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function FeatureItem({ icon, text }: { icon: string; text: string }) {
  return (
    <View style={styles.featureItem}>
      <Text style={styles.featureIcon}>{icon}</Text>
      <Text style={styles.featureText}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COLORS.background },
  inner: { flex: 1, padding: 24, justifyContent: 'center' },
  header: { alignItems: 'center', marginBottom: 40 },
  logoBox: {
    width: 72, height: 72, backgroundColor: COLORS.gold,
    borderRadius: 18, alignItems: 'center', justifyContent: 'center', marginBottom: 16,
  },
  logoText: { fontSize: 36, fontWeight: '900', color: '#000' },
  title: { fontSize: 28, fontWeight: '800', color: COLORS.text, marginBottom: 4 },
  subtitle: { fontSize: 14, color: COLORS.muted },
  form: {},
  switchRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'center', marginTop: 20, gap: 12 },
  switchText: { color: COLORS.muted, fontSize: 14 },
  features: { marginTop: 40, gap: 12 },
  featureItem: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  featureIcon: { fontSize: 20 },
  featureText: { color: COLORS.muted, fontSize: 13 },
});
