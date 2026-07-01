import React from 'react';
import { TouchableOpacity, Text, StyleSheet, ActivityIndicator, ViewStyle } from 'react-native';
import { COLORS } from '../constants';

interface ButtonProps {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'outline' | 'danger';
  loading?: boolean;
  disabled?: boolean;
  style?: ViewStyle;
  size?: 'small' | 'medium' | 'large';
}

export function Button({ title, onPress, variant = 'primary', loading, disabled, style, size = 'medium' }: ButtonProps) {
  const btnStyle = [
    styles.btn,
    styles[variant],
    styles[`size_${size}`],
    (disabled || loading) && styles.disabled,
    style,
  ];

  return (
    <TouchableOpacity style={btnStyle} onPress={onPress} disabled={disabled || loading} activeOpacity={0.7}>
      {loading ? (
        <ActivityIndicator color={variant === 'outline' ? COLORS.gold : '#000'} size="small" />
      ) : (
        <Text style={[styles.text, styles[`text_${variant}`], styles[`textSize_${size}`]]}>{title}</Text>
      )}
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  btn: {
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  primary: { backgroundColor: COLORS.gold },
  secondary: { backgroundColor: COLORS.card, borderWidth: 1, borderColor: COLORS.border },
  outline: { backgroundColor: 'transparent', borderWidth: 1, borderColor: COLORS.gold },
  danger: { backgroundColor: COLORS.red },
  disabled: { opacity: 0.5 },
  size_small: { paddingHorizontal: 16, paddingVertical: 8 },
  size_medium: { paddingHorizontal: 24, paddingVertical: 14 },
  size_large: { paddingHorizontal: 32, paddingVertical: 18 },
  text: { fontWeight: '700' },
  text_primary: { color: '#000' },
  text_secondary: { color: COLORS.text },
  text_outline: { color: COLORS.gold },
  text_danger: { color: '#fff' },
  textSize_small: { fontSize: 13 },
  textSize_medium: { fontSize: 15 },
  textSize_large: { fontSize: 17 },
} as any);
