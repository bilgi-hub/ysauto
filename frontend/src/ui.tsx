/**
 * Reusable Glassmorphism Components
 */
import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet, ViewStyle, TextStyle, ActivityIndicator, Platform } from 'react-native';
import { BlurView } from 'expo-blur';
import { Colors, Radius, Spacing, Typography } from './theme';

type GlassCardProps = {
  children: React.ReactNode;
  style?: ViewStyle | ViewStyle[];
  intensity?: number;
  highlight?: boolean;
};

export function GlassCard({ children, style, intensity = 30, highlight = false }: GlassCardProps) {
  return (
    <View style={[styles.glassWrapper, highlight && styles.glassHighlight, style]}>
      {Platform.OS !== 'web' ? (
        <BlurView intensity={intensity} tint="dark" style={StyleSheet.absoluteFill} />
      ) : (
        <View style={[StyleSheet.absoluteFill, styles.webGlassFallback]} />
      )}
      <View style={styles.glassContent}>{children}</View>
    </View>
  );
}

type GlassButtonProps = {
  title: string;
  onPress: () => void;
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  loading?: boolean;
  disabled?: boolean;
  icon?: React.ReactNode;
  style?: ViewStyle;
  textStyle?: TextStyle;
  testID?: string;
  size?: 'sm' | 'md' | 'lg';
};

export function GlassButton({ title, onPress, variant = 'primary', loading, disabled, icon, style, textStyle, testID, size = 'md' }: GlassButtonProps) {
  const heights = { sm: 40, md: 48, lg: 56 };
  const isDisabled = disabled || loading;

  const variantStyle: ViewStyle =
    variant === 'primary' ? { backgroundColor: Colors.brand.primary }
    : variant === 'danger' ? { backgroundColor: Colors.status.error }
    : variant === 'secondary' ? { backgroundColor: Colors.bg.glass, borderWidth: 1, borderColor: Colors.border.base }
    : { backgroundColor: 'transparent' };

  const txtColor = variant === 'ghost' ? Colors.text.primary : '#fff';

  return (
    <TouchableOpacity
      testID={testID}
      onPress={onPress}
      disabled={isDisabled}
      activeOpacity={0.8}
      style={[
        styles.btn,
        { height: heights[size] },
        variantStyle,
        isDisabled && { opacity: 0.5 },
        style,
      ]}
    >
      {loading ? (
        <ActivityIndicator color="#fff" />
      ) : (
        <View style={styles.btnRow}>
          {icon}
          <Text style={[styles.btnText, { color: txtColor, fontSize: size === 'sm' ? 13 : 15 }, textStyle]}>{title}</Text>
        </View>
      )}
    </TouchableOpacity>
  );
}

type StatusBadgeProps = {
  status: 'musait' | 'dolu' | 'bakim' | 'beklemede' | 'onaylandi' | 'aktif' | 'tamamlandi' | 'iptal';
  label?: string;
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const map: Record<string, { bg: string; color: string; text: string }> = {
    musait: { bg: 'rgba(52, 199, 89, 0.15)', color: Colors.status.success, text: 'Müsait' },
    dolu: { bg: 'rgba(255, 59, 48, 0.15)', color: Colors.status.error, text: 'Dolu' },
    bakim: { bg: 'rgba(255, 149, 0, 0.15)', color: Colors.status.warning, text: 'Bakımda' },
    beklemede: { bg: 'rgba(255, 149, 0, 0.15)', color: Colors.status.warning, text: 'Beklemede' },
    onaylandi: { bg: 'rgba(90, 200, 250, 0.15)', color: Colors.status.info, text: 'Onaylandı' },
    aktif: { bg: 'rgba(52, 199, 89, 0.15)', color: Colors.status.success, text: 'Aktif' },
    tamamlandi: { bg: 'rgba(160, 160, 160, 0.15)', color: Colors.text.secondary, text: 'Tamamlandı' },
    iptal: { bg: 'rgba(255, 59, 48, 0.15)', color: Colors.status.error, text: 'İptal' },
  };
  const cfg = map[status] || map.beklemede;
  return (
    <View style={[styles.badge, { backgroundColor: cfg.bg, borderColor: cfg.color + '40' }]}>
      <View style={[styles.badgeDot, { backgroundColor: cfg.color }]} />
      <Text style={[styles.badgeText, { color: cfg.color }]}>{label || cfg.text}</Text>
    </View>
  );
}

type SectionTitleProps = { title: string; subtitle?: string; right?: React.ReactNode };
export function SectionTitle({ title, subtitle, right }: SectionTitleProps) {
  return (
    <View style={styles.sectionTitleRow}>
      <View style={{ flex: 1 }}>
        <Text style={styles.sectionTitle}>{title}</Text>
        {subtitle ? <Text style={styles.sectionSubtitle}>{subtitle}</Text> : null}
      </View>
      {right}
    </View>
  );
}

type EmptyProps = { title: string; subtitle?: string; icon?: React.ReactNode };
export function Empty({ title, subtitle, icon }: EmptyProps) {
  return (
    <View style={styles.empty}>
      {icon}
      <Text style={styles.emptyTitle}>{title}</Text>
      {subtitle ? <Text style={styles.emptySubtitle}>{subtitle}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  glassWrapper: {
    borderRadius: Radius.lg,
    backgroundColor: Colors.bg.glass,
    borderWidth: 1,
    borderColor: Colors.border.base,
    overflow: 'hidden',
  },
  glassHighlight: {
    borderColor: Colors.border.accent,
    backgroundColor: Colors.bg.glassRed,
  },
  webGlassFallback: {
    backgroundColor: 'rgba(30, 30, 30, 0.6)',
  },
  glassContent: {
    padding: Spacing.lg,
    zIndex: 1,
  },
  btn: {
    borderRadius: Radius.pill,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: Spacing.lg,
  },
  btnRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  btnText: { ...Typography.bodyBold, fontWeight: '700' },
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: Spacing.md,
    paddingVertical: 5,
    borderRadius: Radius.pill,
    borderWidth: 1,
    alignSelf: 'flex-start',
  },
  badgeDot: { width: 6, height: 6, borderRadius: 3 },
  badgeText: { ...Typography.micro, fontWeight: '700' },
  sectionTitleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Spacing.xl,
    marginTop: Spacing.xl,
    marginBottom: Spacing.md,
  },
  sectionTitle: { ...Typography.h3, color: Colors.text.primary },
  sectionSubtitle: { ...Typography.caption, color: Colors.text.secondary, marginTop: 2 },
  empty: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: Spacing.xxxl,
    paddingHorizontal: Spacing.xl,
  },
  emptyTitle: { ...Typography.h4, color: Colors.text.primary, marginTop: Spacing.md, textAlign: 'center' },
  emptySubtitle: { ...Typography.caption, color: Colors.text.secondary, marginTop: 4, textAlign: 'center' },
});
