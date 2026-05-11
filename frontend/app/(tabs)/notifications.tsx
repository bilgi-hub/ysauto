/**
 * Bildirimler
 */
import React, { useCallback, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable, ActivityIndicator } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { customerApi, AppNotification } from '../../src/api';
import { Colors, Radius, Spacing, Typography } from '../../src/theme';
import { GlassCard, Empty, GlassButton } from '../../src/ui';

function fmtRel(s: string) {
  try {
    const d = new Date(s);
    const diff = (Date.now() - d.getTime()) / 1000;
    if (diff < 60) return 'şimdi';
    if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} saat önce`;
    if (diff < 86400 * 7) return `${Math.floor(diff / 86400)} gün önce`;
    return d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' });
  } catch { return ''; }
}

export default function NotificationsScreen() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const data = await customerApi.notifications();
      setItems(data);
    } catch (e: any) {
      console.warn('notif error', e?.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onMarkAll = async () => {
    try { await customerApi.markAllRead(); load(); } catch {}
  };

  const onPress = async (n: AppNotification) => {
    if (!n.okundu) {
      try { await customerApi.markRead(n.id); } catch {}
      setItems(prev => prev.map(x => x.id === n.id ? { ...x, okundu: true } : x));
    }
    // Deep link varsa hedef sayfaya yönlendir (örn /review/{rid})
    if (n.deep_link) {
      try { router.push(n.deep_link as any); } catch {}
    }
  };

  const unread = items.filter(i => !i.okundu).length;

  return (
    <View style={{ flex: 1, backgroundColor: Colors.bg.base }}>
      <SafeAreaView style={{ flex: 1 }} edges={['top']}>
        <ScrollView
          contentContainerStyle={{ paddingBottom: 120 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.brand.primary} />}
        >
          <View style={styles.header}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Bildirimler</Text>
              <Text style={styles.subtitle}>{unread > 0 ? `${unread} okunmamış` : 'Hepsi okundu'}</Text>
            </View>
            {unread > 0 && (
              <Pressable testID="mark-all-read" onPress={onMarkAll} style={styles.markAllBtn}>
                <Ionicons name="checkmark-done" size={18} color={Colors.brand.primary} />
                <Text style={styles.markAllText}>Tümünü Oku</Text>
              </Pressable>
            )}
          </View>

          {loading ? (
            <View style={{ paddingVertical: 60, alignItems: 'center' }}>
              <ActivityIndicator color={Colors.brand.primary} />
            </View>
          ) : items.length === 0 ? (
            <Empty
              title="Henüz bildirim yok"
              subtitle="Yeni bildirimler burada görünecek"
              icon={<Ionicons name="notifications-off-outline" size={48} color={Colors.text.tertiary} />}
            />
          ) : (
            <View style={{ paddingHorizontal: Spacing.xl, gap: Spacing.md }}>
              {items.map(n => (
                <Pressable key={n.id} testID={`notif-${n.id}`} onPress={() => onPress(n)}>
                  <View style={[styles.notif, !n.okundu && styles.notifUnread]}>
                    <View style={[styles.notifIcon, !n.okundu && styles.notifIconUnread]}>
                      <Ionicons name={n.okundu ? 'mail-open-outline' : 'mail'} size={20} color={n.okundu ? Colors.text.secondary : Colors.brand.primary} />
                    </View>
                    <View style={{ flex: 1 }}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                        <Text style={[styles.notifTitle, !n.okundu && { fontWeight: '700' }]}>{n.baslik}</Text>
                        {!n.okundu && <View style={styles.unreadDot} />}
                      </View>
                      <Text style={styles.notifMsg} numberOfLines={3}>{n.mesaj}</Text>
                      <Text style={styles.notifTime}>{fmtRel(n.tarih)}</Text>
                    </View>
                  </View>
                </Pressable>
              ))}
            </View>
          )}
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: Spacing.xl, paddingTop: Spacing.lg, paddingBottom: Spacing.sm },
  title: { ...Typography.h1, color: Colors.text.primary },
  subtitle: { ...Typography.caption, color: Colors.text.secondary, marginTop: 4 },
  markAllBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    paddingHorizontal: Spacing.md, paddingVertical: 8,
    backgroundColor: Colors.bg.glassRed, borderRadius: Radius.pill,
    borderWidth: 1, borderColor: Colors.border.accent,
  },
  markAllText: { ...Typography.micro, color: Colors.brand.primary, fontWeight: '700' },
  notif: {
    flexDirection: 'row', gap: Spacing.md,
    padding: Spacing.lg, borderRadius: Radius.lg,
    backgroundColor: Colors.bg.surface,
    borderWidth: 1, borderColor: Colors.border.base,
  },
  notifUnread: { borderColor: Colors.border.accent, backgroundColor: Colors.bg.glassRed },
  notifIcon: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: Colors.bg.surface2,
    alignItems: 'center', justifyContent: 'center',
  },
  notifIconUnread: { backgroundColor: Colors.bg.glassRed },
  notifTitle: { ...Typography.bodyBold, color: Colors.text.primary, flex: 1 },
  notifMsg: { ...Typography.caption, color: Colors.text.secondary, marginTop: 4, lineHeight: 18 },
  notifTime: { ...Typography.micro, color: Colors.text.tertiary, marginTop: 6 },
  unreadDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: Colors.brand.primary, marginLeft: Spacing.sm },
});
