/**
 * İletişim - Contact info from settings
 */
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, Linking, Alert, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { useFocusEffect } from 'expo-router';
import { customerApi, Settings } from '../../src/api';
import { Colors, Radius, Spacing, Typography } from '../../src/theme';
import { GlassCard, SectionTitle } from '../../src/ui';

export default function ContactScreen() {
  const [settings, setSettings] = useState<Settings>({});
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    try {
      const s = await customerApi.publicSettings();
      setSettings(s);
    } catch {}
    finally { setLoaded(true); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const tryOpen = async (url: string, fallback?: string) => {
    try {
      const can = await Linking.canOpenURL(url);
      if (can) await Linking.openURL(url);
      else if (fallback) Alert.alert('Bilgi', fallback);
    } catch {
      if (fallback) Alert.alert('Bilgi', fallback);
    }
  };

  const items = [
    { icon: 'call' as const, label: 'Telefon', value: settings.iletisim_telefon, action: () => settings.iletisim_telefon && tryOpen(`tel:${settings.iletisim_telefon.replace(/\s/g, '')}`) },
    { icon: 'logo-whatsapp' as const, label: 'WhatsApp', value: settings.whatsapp, action: () => settings.whatsapp && tryOpen(`https://wa.me/${settings.whatsapp.replace(/[^\d]/g, '')}`) },
    { icon: 'mail' as const, label: 'E-posta', value: settings.iletisim_email, action: () => settings.iletisim_email && tryOpen(`mailto:${settings.iletisim_email}`) },
    { icon: 'location' as const, label: 'Adres', value: settings.iletisim_adres, action: () => settings.iletisim_adres && tryOpen(`https://maps.google.com/?q=${encodeURIComponent(settings.iletisim_adres)}`) },
  ];

  return (
    <View style={{ flex: 1, backgroundColor: Colors.bg.base }}>
      <SafeAreaView style={{ flex: 1 }} edges={['top']}>
        <ScrollView contentContainerStyle={{ paddingBottom: 120 }}>
          <View style={styles.header}>
            <Text style={styles.title}>İletişim</Text>
            <Text style={styles.subtitle}>Bize ulaşın, biz buradayız</Text>
          </View>

          <View style={styles.heroWrap}>
            <GlassCard highlight style={{ padding: Spacing.xl, alignItems: 'center' }}>
              <View style={styles.heroIcon}>
                <Ionicons name="headset" size={32} color={Colors.brand.primary} />
              </View>
              <Text style={styles.heroTitle}>7/24 Destek</Text>
              <Text style={styles.heroSub}>Aracınızla ilgili sorularınız için</Text>
            </GlassCard>
          </View>

          <SectionTitle title="İletişim Kanalları" />

          <View style={{ paddingHorizontal: Spacing.xl, gap: Spacing.md }}>
            {items.map(it => (
              <Pressable key={it.label} testID={`contact-${it.label.toLowerCase()}`} onPress={it.action} style={({ pressed }) => [styles.item, pressed && { opacity: 0.7 }]}>
                <View style={styles.itemIcon}>
                  <Ionicons name={it.icon as any} size={22} color={Colors.brand.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.itemLabel}>{it.label}</Text>
                  <Text style={styles.itemValue} numberOfLines={2}>{it.value || '—'}</Text>
                </View>
                <Ionicons name="chevron-forward" size={20} color={Colors.text.secondary} />
              </Pressable>
            ))}
          </View>

        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { paddingHorizontal: Spacing.xl, paddingTop: Spacing.lg, paddingBottom: Spacing.sm },
  title: { ...Typography.h1, color: Colors.text.primary },
  subtitle: { ...Typography.caption, color: Colors.text.secondary, marginTop: 4 },
  heroWrap: { paddingHorizontal: Spacing.xl, marginTop: Spacing.lg },
  heroIcon: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: 'rgba(229, 9, 20, 0.15)',
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: Colors.border.accent, marginBottom: Spacing.md,
  },
  heroTitle: { ...Typography.h2, color: Colors.text.primary },
  heroSub: { ...Typography.caption, color: Colors.text.secondary, marginTop: 2 },
  item: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.md,
    padding: Spacing.lg, borderRadius: Radius.lg,
    backgroundColor: Colors.bg.surface,
    borderWidth: 1, borderColor: Colors.border.base,
  },
  itemIcon: {
    width: 44, height: 44, borderRadius: 22,
    backgroundColor: Colors.bg.glassRed,
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: Colors.border.accent,
  },
  itemLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' },
  itemValue: { ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 },
  bankRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  bankDivider: { height: 1, backgroundColor: Colors.border.base, marginVertical: Spacing.md },
});
