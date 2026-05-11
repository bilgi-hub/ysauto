/**
 * Admin Panel - Web/Mobile dashboard for management
 * Tabs: Dashboard, Müşteriler, Araçlar, Rezervasyonlar, Bildirim, Ayarlar
 */
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, Pressable, TextInput, Alert, ActivityIndicator, RefreshControl, Modal, Image, Platform } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useFocusEffect } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import { adminApi, auth } from '../src/api';
import { Colors, Radius, Spacing, Typography } from '../src/theme';
import { GlassCard, GlassButton, StatusBadge, SectionTitle, Empty } from '../src/ui';
import ZoomableImage from '../src/ZoomableImage';
import { Stars } from '../src/Stars';

import { DateTimeField } from '../src/DateTimeField';

// ===== Module-level admin lists cache (anlık render için) =====
// Tab değişimi sırasında veri kaybolmaz, arka planda sessizce yenilenir.
const _adminCache: Record<string, any> = {
  vehicles: null as any[] | null,
  reservations: null as any[] | null,
  customers: null as any[] | null,
};

type AdminTab = 'dashboard' | 'earnings' | 'customers' | 'reservations' | 'vehicles' | 'reviews' | 'notifications' | 'topups' | 'services' | 'holidays' | 'settings' | 'muhasebe' | 'admins';

export default function AdminPanel() {
  const router = useRouter();
  const [tab, setTab] = useState<AdminTab>('dashboard');
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    (async () => {
      const stored = await auth.getStored();
      if (!stored || stored.user.role !== 'admin') {
        router.replace('/login');
      } else {
        setUser(stored.user);
      }
    })();
  }, []);

  const tabs: { key: AdminTab; label: string; icon: any }[] = [
    { key: 'dashboard', label: 'Özet', icon: 'stats-chart' },
    { key: 'earnings', label: 'Kazanç', icon: 'wallet' },
    { key: 'customers', label: 'Müşteriler', icon: 'people' },
    { key: 'reservations', label: 'Rezervasyon', icon: 'calendar' },
    { key: 'vehicles', label: 'Araçlar', icon: 'car-sport' },
    { key: 'reviews', label: 'Yorumlar', icon: 'star' },
    { key: 'notifications', label: 'Bildirim', icon: 'megaphone' },
    { key: 'topups', label: 'Bakiye', icon: 'cash' },
    { key: 'services', label: 'Hizmetler', icon: 'pricetag' },
    { key: 'holidays', label: 'Tatiller', icon: 'today' },
    { key: 'settings', label: 'Ayarlar', icon: 'settings' },
    { key: 'admins', label: 'Kullanıcılar', icon: 'shield-checkmark' },
    { key: 'muhasebe', label: 'Muhasebe', icon: 'calculator' },
  ];

  return (
    <View style={styles.bg}>
      <SafeAreaView style={{ flex: 1 }} edges={['top']}>
        <View style={styles.topBar}>
          <View style={{ flex: 1 }}>
            <Text style={styles.adminTitle}>YS Admin</Text>
            <Text style={styles.adminSub}>{user?.ad || 'Yönetici'}</Text>
          </View>
          <Pressable testID="admin-logout" onPress={async () => { await auth.logout(); router.replace('/login'); }} style={styles.logoutBtn}>
            <Ionicons name="log-out-outline" size={20} color={Colors.text.primary} />
          </Pressable>
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabBar} contentContainerStyle={{ paddingHorizontal: Spacing.xl, gap: 8 }}>
          {tabs.map(t => (
            <Pressable key={t.key} testID={`admin-tab-${t.key}`} onPress={() => setTab(t.key)} style={[styles.tabBtn, tab === t.key && styles.tabBtnActive]}>
              <Ionicons name={t.icon} size={16} color={tab === t.key ? '#fff' : Colors.text.secondary} />
              <Text style={[styles.tabBtnText, tab === t.key && styles.tabBtnTextActive]}>{t.label}</Text>
            </Pressable>
          ))}
        </ScrollView>

        <View style={{ flex: 1 }}>
          {tab === 'dashboard' && <DashboardTab />}
          {tab === 'earnings' && <EarningsTab />}
          {tab === 'customers' && <CustomersTab />}
          {tab === 'vehicles' && <VehiclesTab />}
          {tab === 'reservations' && <ReservationsTab />}
          {tab === 'topups' && <TopupsTab />}
          {tab === 'services' && <ServicesTab />}
          {tab === 'holidays' && <HolidaysTab />}
          {tab === 'notifications' && <NotificationsTab />}
          {tab === 'reviews' && <ReviewsTab />}
          {tab === 'settings' && <SettingsTab />}
          {tab === 'admins' && <AdminsTab currentUserId={user?.id} />}
          {tab === 'muhasebe' && <MuhasebeTab />}
        </View>
      </SafeAreaView>
    </View>
  );
}

// ===== Dashboard =====
function DashboardTab() {
  const [stats, setStats] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const load = useCallback(async () => {
    try { setStats(await adminApi.dashboard()); } catch {} finally { setRefreshing(false); }
  }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));
  if (!stats) return <ActivityIndicator color={Colors.brand.primary} style={{ marginTop: 40 }} />;
  const cards = [
    { label: 'Müşteri', val: stats.musteri_sayisi, icon: 'people' as const, color: Colors.status.info },
    { label: 'Engelli', val: stats.engelli_musteri, icon: 'ban' as const, color: Colors.status.error },
    { label: 'Araç', val: stats.arac_sayisi, icon: 'car-sport' as const, color: Colors.brand.primary },
    { label: 'Aktif Rez.', val: stats.aktif_rezervasyon, icon: 'calendar' as const, color: Colors.status.success },
    { label: 'Bekleyen', val: stats.bekleyen_rezervasyon, icon: 'hourglass' as const, color: Colors.status.warning },
    { label: 'Tamamlanan', val: stats.tamamlanan_rezervasyon, icon: 'checkmark-done' as const, color: Colors.text.secondary },
  ];
  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.brand.primary} />}>
      <View style={styles.statsGrid}>
        {cards.map(c => (
          <GlassCard key={c.label} style={styles.statCard}>
            <View style={[styles.statIcon, { backgroundColor: c.color + '22', borderColor: c.color + '55' }]}>
              <Ionicons name={c.icon} size={20} color={c.color} />
            </View>
            <Text style={styles.statVal}>{c.val}</Text>
            <Text style={styles.statLabel}>{c.label}</Text>
          </GlassCard>
        ))}
      </View>
      <GlassCard highlight={stats.bot_online}>
        <View style={{ flexDirection: 'row', alignItems: 'center', gap: Spacing.md }}>
          <View style={[styles.statIcon, { backgroundColor: stats.bot_online ? Colors.status.success + '22' : Colors.status.error + '22', borderColor: (stats.bot_online ? Colors.status.success : Colors.status.error) + '55' }]}>
            <Ionicons name={stats.bot_online ? 'wifi' : 'wifi-outline'} size={20} color={stats.bot_online ? Colors.status.success : Colors.status.error} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>GPS Bot {stats.bot_online ? 'Online' : 'Offline'}</Text>
            <Text style={{ ...Typography.caption, color: Colors.text.secondary, marginTop: 2 }}>
              {stats.bot_online ? 'Araç KM verisi canlı çekiliyor' : 'Bot API erişilemiyor (port 8081). Açıldığında otomatik bağlanır.'}
            </Text>
          </View>
        </View>
      </GlassCard>
    </ScrollView>
  );
}

// ===== Kazanç / Muhasebe (Gelir & Gider) — Faz 1 + Kasa Ayrımı + Araç Performansı =====
function EarningsTab() {
  const [data, setData] = useState<any>(null);
  const [cashflow, setCashflow] = useState<any>(null);
  const [pending, setPending] = useState<any>(null);
  const [vehiclePerf, setVehiclePerf] = useState<any>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState<'all' | 'this_month' | 'last_month' | 'this_year'>('this_month');
  const [kasa, setKasa] = useState<'tum' | 'rentcar' | 'eticaret'>('tum');
  const [view, setView] = useState<'gelir' | 'gider'>('gelir');

  // Modals
  const [formOpen, setFormOpen] = useState(false);
  const [formType, setFormType] = useState<'gelir' | 'gider'>('gider');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<{ tarih: string; kategori: string; aciklama: string; tutar: string; kasa: 'rentcar' | 'eticaret' | '' }>({ tarih: '', kategori: '', aciklama: '', tutar: '', kasa: '' });
  const [catSuggestions, setCatSuggestions] = useState<string[]>([]);

  const range = useCallback((): { start?: string; end?: string } => {
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    if (period === 'all') return {};
    if (period === 'this_month') {
      const s = new Date(now.getFullYear(), now.getMonth(), 1);
      const e = new Date(now.getFullYear(), now.getMonth() + 1, 0);
      return { start: fmt(s), end: fmt(e) };
    }
    if (period === 'last_month') {
      const s = new Date(now.getFullYear(), now.getMonth() - 1, 1);
      const e = new Date(now.getFullYear(), now.getMonth(), 0);
      return { start: fmt(s), end: fmt(e) };
    }
    if (period === 'this_year') {
      return { start: `${now.getFullYear()}-01-01`, end: `${now.getFullYear()}-12-31` };
    }
    return {};
  }, [period]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { start, end } = range();
      const kasaParam = kasa === 'tum' ? undefined : kasa;
      const [earn, cf, pr, vp] = await Promise.all([
        adminApi.earnings(start, end, kasaParam),
        adminApi.cashflow(kasaParam).catch(() => null),
        kasa === 'eticaret' ? Promise.resolve(null) : adminApi.pendingRevenue().catch(() => null),
        kasa === 'eticaret' ? Promise.resolve(null) : adminApi.vehiclePerformance(start, end).catch(() => null),
      ]);
      setData(earn);
      setCashflow(cf);
      setPending(pr);
      setVehiclePerf(vp);
    } catch (e: any) {
      Alert.alert('Hata', e.message || 'Veri yüklenemedi');
    } finally { setLoading(false); setRefreshing(false); }
  }, [range, kasa]);
  useEffect(() => { load(); }, [load]);

  const openForm = async (type: 'gelir' | 'gider', existing?: any) => {
    setFormType(type);
    setEditingId(existing?.id || null);
    if (existing) {
      setForm({
        tarih: isoToTrDate(existing.tarih) || '',
        kategori: existing.kategori || '',
        aciklama: existing.aciklama || '',
        tutar: String(existing.tutar || ''),
        kasa: (existing.kasa as any) || '',
      });
    } else {
      const today = new Date();
      const p = (n: number) => String(n).padStart(2, '0');
      // Default kasa: current filter
      const defaultKasa: 'rentcar' | 'eticaret' | '' = kasa === 'rentcar' ? 'rentcar' : (kasa === 'eticaret' ? 'eticaret' : '');
      setForm({
        tarih: `${p(today.getDate())}.${p(today.getMonth() + 1)}.${today.getFullYear()}`,
        kategori: '',
        aciklama: '',
        tutar: '',
        kasa: defaultKasa,
      });
    }
    try {
      const cats = await adminApi.earningCategories(type);
      setCatSuggestions(cats);
    } catch { setCatSuggestions([]); }
    setFormOpen(true);
  };

  const saveForm = async () => {
    try {
      const iso = trDateToIso(form.tarih);
      if (!iso) { Alert.alert('Hata', 'Tarih formatı: GG.AA.YYYY'); return; }
      if (!form.kategori.trim()) { Alert.alert('Hata', 'Kategori zorunlu'); return; }
      if (!form.kasa) { Alert.alert('Hata', 'Kasa seçmelisiniz (Rentcar veya E-Ticaret)'); return; }
      const tutar = parseFloat((form.tutar || '').replace(/[^\d.,]/g, '').replace(',', '.') || '0');
      if (tutar <= 0) { Alert.alert('Hata', 'Tutar 0\'dan büyük olmalı'); return; }
      const payload: any = { tarih: iso, kategori: form.kategori.trim(), aciklama: form.aciklama, tutar, kasa: form.kasa };
      if (editingId) {
        if (formType === 'gelir') await adminApi.updateManualIncome(editingId, payload);
        else await adminApi.updateExpense(editingId, payload);
      } else {
        if (formType === 'gelir') await adminApi.createManualIncome(payload);
        else await adminApi.createExpense(payload);
      }
      setFormOpen(false);
      setEditingId(null);
      load();
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const removeItem = (item: any, type: 'gelir' | 'gider') => {
    const label = type === 'gelir' ? 'Gelir' : 'Gider';
    Alert.alert(`${label} silinsin mi?`, `${item.kategori} - ${item.tutar.toLocaleString('tr-TR')} ₺`, [
      { text: 'Vazgeç' },
      { text: 'Sil', style: 'destructive', onPress: async () => {
        try {
          if (type === 'gelir') await adminApi.deleteManualIncome(item.id);
          else await adminApi.deleteExpense(item.id);
          load();
        } catch (er: any) { Alert.alert('Hata', er.message); }
      } }
    ]);
  };

  const periods: { key: typeof period; label: string }[] = [
    { key: 'this_month', label: 'Bu Ay' },
    { key: 'last_month', label: 'Geçen Ay' },
    { key: 'this_year', label: 'Bu Yıl' },
    { key: 'all', label: 'Tümü' },
  ];

  const kasaOptions: { key: typeof kasa; label: string; icon: any; color: string }[] = [
    { key: 'tum', label: 'Tümü', icon: 'apps', color: Colors.brand.primary },
    { key: 'rentcar', label: 'Rentcar 🚗', icon: 'car-sport', color: Colors.status.info },
    { key: 'eticaret', label: 'E-Ticaret 🛒', icon: 'cart', color: '#9333ea' },
  ];

  return (
    <ScrollView
      contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 80 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.brand.primary} />}
    >
      {/* Kasa Selector */}
      <View style={{ flexDirection: 'row', gap: 6 }}>
        {kasaOptions.map(k => (
          <Pressable
            key={k.key}
            onPress={() => setKasa(k.key)}
            style={[
              styles.miniBtn,
              { flex: 1, flexDirection: 'row', justifyContent: 'center', gap: 4, paddingVertical: 10 },
              kasa === k.key && { backgroundColor: k.color, borderColor: k.color }
            ]}
          >
            <Text style={[styles.miniBtnText, kasa === k.key && { color: '#fff' }, { fontWeight: '700' }]}>{k.label}</Text>
          </Pressable>
        ))}
      </View>

      {/* Period filter */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ flexDirection: 'row', gap: 6 }}>
          {periods.map(p => (
            <Pressable key={p.key} onPress={() => setPeriod(p.key)} style={[styles.miniBtn, period === p.key && styles.miniBtnActive]}>
              <Text style={[styles.miniBtnText, period === p.key && { color: '#fff' }]}>{p.label}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>

      {loading || !data ? (
        <ActivityIndicator color={Colors.brand.primary} style={{ marginTop: 40 }} />
      ) : (
        <>
          {/* NET KAZANÇ ana kart */}
          <GlassCard highlight style={{ padding: 16 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 }}>
              <Ionicons name="trending-up" size={18} color={data.net >= 0 ? Colors.status.success : Colors.status.error} />
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700' }}>
                NET KAZANÇ • {kasaOptions.find(k => k.key === kasa)?.label} • {periods.find(p => p.key === period)?.label}
              </Text>
            </View>
            <Text style={{ ...Typography.h2, color: data.net >= 0 ? Colors.status.success : Colors.status.error, fontWeight: '900' }}>
              {data.net.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺
            </Text>
            <View style={{ flexDirection: 'row', gap: 12, marginTop: 8 }}>
              <View>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>Gelir</Text>
                <Text style={{ ...Typography.bodyBold, color: Colors.status.success }}>{data.toplam_gelir.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺</Text>
              </View>
              <View>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>Gider</Text>
                <Text style={{ ...Typography.bodyBold, color: Colors.status.error }}>{data.toplam_gider.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺</Text>
              </View>
            </View>
            {kasa === 'tum' && (
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 6 }}>
                Rezervasyon: {data.rezervasyon_gelir.toLocaleString('tr-TR')} ₺  •  E-Ticaret: {data.manuel_gelir.toLocaleString('tr-TR')} ₺
              </Text>
            )}
          </GlassCard>

          {/* BEKLEYEN GELİR — sadece Rentcar/Tümü */}
          {kasa !== 'eticaret' && pending && pending.toplam > 0 && (
            <GlassCard style={{ padding: 14, borderLeftWidth: 3, borderLeftColor: Colors.status.warning }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                <Ionicons name="hourglass" size={16} color={Colors.status.warning} />
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700' }}>BEKLEYEN GELİR (Aktif/Onaylı Rezervasyonlar)</Text>
              </View>
              <Text style={{ ...Typography.h3, color: Colors.status.warning, fontWeight: '900' }}>
                {pending.toplam.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺
              </Text>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 }}>
                {pending.aktif_adet} aktif ({pending.aktif_total.toLocaleString('tr-TR')} ₺)  •  {pending.onaylandi_adet} onaylı ({pending.onaylandi_total.toLocaleString('tr-TR')} ₺)
              </Text>
            </GlassCard>
          )}

          {/* KASA DURUMU - Net Kar görünümü */}
          {cashflow && (
            <GlassCard style={{ padding: 14, borderLeftWidth: 3, borderLeftColor: Colors.status.info }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <Ionicons name="wallet" size={16} color={Colors.status.info} />
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700' }}>
                  KASA DURUMU • {kasaOptions.find(k => k.key === kasa)?.label}
                </Text>
              </View>

              {/* Negatif kalemler (sadece varsa ve rentcar/tümü görünümünde) */}
              {cashflow.musteri_bakiye_borcu > 0 && (
                <CashflowRow label="Müşterilere Borç (Bakiyeler)" value={cashflow.musteri_bakiye_borcu} sign={-1} icon="people" hint="müşterilerin cüzdanlarında duran para" />
              )}
              {cashflow.bekleyen_havaleler > 0 && (
                <CashflowRow label="Bekleyen Havaleler" value={cashflow.bekleyen_havaleler} sign={-1} icon="hourglass" hint={`${cashflow.bekleyen_havale_adet} adet onay bekliyor`} />
              )}
              {cashflow.bloke_provizyonlar > 0 && (
                <CashflowRow label="Bloke Provizyonlar" value={cashflow.bloke_provizyonlar} sign={-1} icon="lock-closed" />
              )}
              {cashflow.gider_total > 0 && (
                <CashflowRow label="Giderler (Tüm Zamanlar)" value={cashflow.gider_total} sign={-1} icon="arrow-up-circle" />
              )}

              <View style={{ height: 1, backgroundColor: Colors.border.base, marginVertical: 8 }} />

              {/* Kasa Bazlı Kazanç Satırları */}
              {(kasa === 'tum' || kasa === 'rentcar') && (
                <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 4 }}>
                  <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <Ionicons name="car-sport" size={14} color={Colors.status.info} />
                    <Text style={{ ...Typography.caption, color: Colors.text.primary, fontWeight: '600' }}>🚗 Rentcar Kasa</Text>
                  </View>
                  <Text style={{ ...Typography.caption, fontWeight: '800', color: cashflow.rentcar_kasa >= 0 ? Colors.status.success : Colors.status.error }}>
                    {cashflow.rentcar_kasa.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺
                  </Text>
                </View>
              )}

              {(kasa === 'tum' || kasa === 'eticaret') && (
                <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 4 }}>
                  <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                    <Ionicons name="cart" size={14} color={'#9333ea'} />
                    <Text style={{ ...Typography.caption, color: Colors.text.primary, fontWeight: '600' }}>🛒 E-Ticaret Kasa</Text>
                  </View>
                  <Text style={{ ...Typography.caption, fontWeight: '800', color: cashflow.eticaret_kasa >= 0 ? Colors.status.success : Colors.status.error }}>
                    {cashflow.eticaret_kasa.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺
                  </Text>
                </View>
              )}

              <View style={{ height: 2, backgroundColor: Colors.brand.primary, marginVertical: 8, opacity: 0.4 }} />

              {/* NET KAR */}
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                <View>
                  <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, fontSize: 15 }}>NET KAR</Text>
                  <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>Cebimdeki tutar</Text>
                </View>
                <Text style={{ fontWeight: '900', color: cashflow.net_kar >= 0 ? Colors.status.success : Colors.status.error, fontSize: 22 }}>
                  {cashflow.net_kar.toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺
                </Text>
              </View>

              {/* Belirsiz uyarısı - sadece Tümü'de */}
              {kasa === 'tum' && (cashflow.belirsiz_gelir > 0 || cashflow.belirsiz_gider > 0) && (
                <View style={{ marginTop: 10, padding: 8, backgroundColor: Colors.bg.surface, borderRadius: 6, borderWidth: 1, borderColor: Colors.status.warning }}>
                  <Text style={{ ...Typography.micro, color: Colors.status.warning, fontWeight: '700' }}>⚪ KASASIZ KAYITLAR (hesaba dahil değil)</Text>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 2 }}>
                    Gelir: +{cashflow.belirsiz_gelir.toLocaleString('tr-TR')} ₺  •  Gider: -{cashflow.belirsiz_gider.toLocaleString('tr-TR')} ₺  •  Net: {cashflow.belirsiz_net.toLocaleString('tr-TR')} ₺
                  </Text>
                  <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 2, fontStyle: 'italic' }}>
                    Bu kayıtların kasasını belirlemek için düzenleyin (Gelir/Gider listesinden ✏️)
                  </Text>
                </View>
              )}
            </GlassCard>
          )}

          {/* View toggle */}
          <View style={{ flexDirection: 'row', gap: 6, marginTop: 4 }}>
            <Pressable onPress={() => setView('gelir')} style={[styles.miniBtn, view === 'gelir' && styles.miniBtnActive, { flex: 1, flexDirection: 'row', justifyContent: 'center', gap: 4 }]}>
              <Ionicons name="arrow-down-circle" size={14} color={view === 'gelir' ? '#fff' : Colors.status.success} />
              <Text style={[styles.miniBtnText, view === 'gelir' && { color: '#fff' }]}>Gelir ({data.gelir_kalemleri.length})</Text>
            </Pressable>
            <Pressable onPress={() => setView('gider')} style={[styles.miniBtn, view === 'gider' && styles.miniBtnActive, { flex: 1, flexDirection: 'row', justifyContent: 'center', gap: 4 }]}>
              <Ionicons name="arrow-up-circle" size={14} color={view === 'gider' ? '#fff' : Colors.status.error} />
              <Text style={[styles.miniBtnText, view === 'gider' && { color: '#fff' }]}>Gider ({data.gider_kalemleri.length})</Text>
            </Pressable>
          </View>

          {/* GELİR LİSTESİ */}
          {view === 'gelir' && (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' }}>Gelir Kalemleri</Text>
                <Pressable onPress={() => openForm('gelir')} style={[styles.fab, { height: 36, width: 'auto' as any, flexDirection: 'row', gap: 4, paddingHorizontal: 12 }]}>
                  <Ionicons name="add" size={16} color="#fff" />
                  <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12 }}>Manuel Gelir</Text>
                </Pressable>
              </View>
              {data.gelir_kalemleri.length === 0 ? (
                <Empty title="Gelir kaydı yok" icon={<Ionicons name="cash-outline" size={36} color={Colors.text.tertiary} />} />
              ) : data.gelir_kalemleri.map((g: any) => (
                <GlassCard key={`${g.kaynak}-${g.id}`} style={{ padding: 12 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <View style={{ flex: 1 }}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{g.kategori || '—'}</Text>
                        <KasaBadge kasa={g.kasa} kaynak={g.kaynak} />
                      </View>
                      {g.aciklama ? <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 2 }}>{g.aciklama}</Text> : null}
                      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 }}>
                        {g.kaynak === 'rezervasyon' ? `${g.musteri} • ` : ''}{isoToTrDate(g.tarih)}
                      </Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={{ ...Typography.bodyBold, color: Colors.status.success }}>+{g.tutar.toLocaleString('tr-TR')} ₺</Text>
                      {g.editable && (
                        <View style={{ flexDirection: 'row', gap: 4, marginTop: 4 }}>
                          <Pressable onPress={() => openForm('gelir', g)} style={styles.iconBtn}>
                            <Ionicons name="pencil" size={13} color={Colors.text.primary} />
                          </Pressable>
                          <Pressable onPress={() => removeItem(g, 'gelir')} style={styles.iconBtn}>
                            <Ionicons name="trash" size={13} color={Colors.status.error} />
                          </Pressable>
                        </View>
                      )}
                    </View>
                  </View>
                </GlassCard>
              ))}
            </>
          )}

          {/* GİDER LİSTESİ */}
          {view === 'gider' && (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' }}>Gider Kalemleri</Text>
                <Pressable onPress={() => openForm('gider')} style={[styles.fab, { width: 'auto' as any, height: 36, flexDirection: 'row', gap: 4, paddingHorizontal: 12 }]}>
                  <Ionicons name="add" size={16} color="#fff" />
                  <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12 }}>Gider Ekle</Text>
                </Pressable>
              </View>
              {data.gider_kalemleri.length === 0 ? (
                <Empty title="Gider kaydı yok" icon={<Ionicons name="receipt-outline" size={36} color={Colors.text.tertiary} />} />
              ) : data.gider_kalemleri.map((e: any) => (
                <GlassCard key={e.id} style={{ padding: 12 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <View style={{ flex: 1 }}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{e.kategori}</Text>
                        <KasaBadge kasa={e.kasa} />
                      </View>
                      {e.aciklama ? <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 2 }}>{e.aciklama}</Text> : null}
                      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 }}>{isoToTrDate(e.tarih)}</Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={{ ...Typography.bodyBold, color: Colors.status.error }}>-{e.tutar.toLocaleString('tr-TR')} ₺</Text>
                      <View style={{ flexDirection: 'row', gap: 4, marginTop: 4 }}>
                        <Pressable onPress={() => openForm('gider', e)} style={styles.iconBtn}>
                          <Ionicons name="pencil" size={13} color={Colors.text.primary} />
                        </Pressable>
                        <Pressable onPress={() => removeItem(e, 'gider')} style={styles.iconBtn}>
                          <Ionicons name="trash" size={13} color={Colors.status.error} />
                        </Pressable>
                      </View>
                    </View>
                  </View>
                </GlassCard>
              ))}
            </>
          )}

          {/* ARAÇ PERFORMANSI - sadece Tümü/Rentcar görünümünde */}
          {kasa !== 'eticaret' && vehiclePerf && vehiclePerf.araclar && vehiclePerf.araclar.length > 0 && (
            <>
              <View style={{ marginTop: 12, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                <Ionicons name="car-sport" size={16} color={Colors.brand.primary} />
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', fontWeight: '700' }}>
                  Araç Performansı ({vehiclePerf.arac_adet} araç • Toplam: {vehiclePerf.toplam_kazanc.toLocaleString('tr-TR')} ₺)
                </Text>
              </View>
              {vehiclePerf.araclar.map((a: any) => (
                <VehiclePerfCard key={a.vehicle_id} a={a} maxKazanc={vehiclePerf.araclar[0]?.toplam_kazanc || 1} />
              ))}
            </>
          )}
        </>
      )}

      {/* Form Modal */}
      <Modal visible={formOpen} animationType="slide" transparent onRequestClose={() => setFormOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text style={styles.modalTitle}>
                {editingId ? 'Düzenle' : 'Yeni'}: {formType === 'gelir' ? 'Manuel Gelir' : 'Gider'}
              </Text>
              <Pressable onPress={() => setFormOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>

            <ScrollView style={{ maxHeight: 560 }}>
              {/* KASA SEÇİMİ - 2 büyük buton */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 8, marginBottom: 6, fontWeight: '700' }}>Hangi Kasaya?</Text>
              <View style={{ flexDirection: 'row', gap: 8, marginBottom: 8 }}>
                <Pressable
                  onPress={() => setForm({ ...form, kasa: 'rentcar' })}
                  style={[
                    { flex: 1, padding: 14, borderRadius: Radius.md, borderWidth: 2, alignItems: 'center', gap: 4 },
                    form.kasa === 'rentcar'
                      ? { backgroundColor: Colors.status.info, borderColor: Colors.status.info }
                      : { backgroundColor: Colors.bg.surface, borderColor: Colors.border.base }
                  ]}
                >
                  <Ionicons name="car-sport" size={22} color={form.kasa === 'rentcar' ? '#fff' : Colors.status.info} />
                  <Text style={{ ...Typography.caption, color: form.kasa === 'rentcar' ? '#fff' : Colors.text.primary, fontWeight: '800' }}>RENTCAR 🚗</Text>
                  <Text style={{ ...Typography.micro, color: form.kasa === 'rentcar' ? '#fff' : Colors.text.tertiary, textAlign: 'center' }}>Araç Kiralama</Text>
                </Pressable>
                <Pressable
                  onPress={() => setForm({ ...form, kasa: 'eticaret' })}
                  style={[
                    { flex: 1, padding: 14, borderRadius: Radius.md, borderWidth: 2, alignItems: 'center', gap: 4 },
                    form.kasa === 'eticaret'
                      ? { backgroundColor: '#9333ea', borderColor: '#9333ea' }
                      : { backgroundColor: Colors.bg.surface, borderColor: Colors.border.base }
                  ]}
                >
                  <Ionicons name="cart" size={22} color={form.kasa === 'eticaret' ? '#fff' : '#9333ea'} />
                  <Text style={{ ...Typography.caption, color: form.kasa === 'eticaret' ? '#fff' : Colors.text.primary, fontWeight: '800' }}>E-TİCARET 🛒</Text>
                  <Text style={{ ...Typography.micro, color: form.kasa === 'eticaret' ? '#fff' : Colors.text.tertiary, textAlign: 'center' }}>Ürün/Satış</Text>
                </Pressable>
              </View>

              <Field label="Tarih (GG.AA.YYYY)" v={form.tarih} on={(x) => setForm({ ...form, tarih: maskTrDate(x) })} kb="number-pad" />

              {/* Hibrit Kategori */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 8, marginBottom: 4 }}>Kategori (sık kullanılanlar)</Text>
              <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 6 }}>
                <View style={{ flexDirection: 'row', gap: 4 }}>
                  {catSuggestions.map(c => (
                    <Pressable key={c} onPress={() => setForm({ ...form, kategori: c })} style={[styles.miniBtn, form.kategori === c && styles.miniBtnActive]}>
                      <Text style={[styles.miniBtnText, form.kategori === c && { color: '#fff' }]}>{c}</Text>
                    </Pressable>
                  ))}
                </View>
              </ScrollView>
              <Field label="veya yaz (yeni kategori)" v={form.kategori} on={(x) => setForm({ ...form, kategori: x })} />

              <Field label="Açıklama (opsiyonel)" v={form.aciklama} on={(x) => setForm({ ...form, aciklama: x })} multi />
              <Field label="Tutar (₺)" v={form.tutar} on={(x) => setForm({ ...form, tutar: x })} kb="decimal-pad" />
            </ScrollView>
            <GlassButton title={editingId ? 'KAYDET' : (formType === 'gelir' ? 'GELİR EKLE' : 'GİDER EKLE')} onPress={saveForm} />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// Kasa Badge — eski kayıtlar 'belirsiz' gibi gösterilir
function KasaBadge({ kasa, kaynak }: { kasa?: string | null; kaynak?: string }) {
  if (kaynak === 'rezervasyon') {
    return (
      <View style={{ paddingHorizontal: 6, paddingVertical: 1, backgroundColor: Colors.brand.primary, borderRadius: 4 }}>
        <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900' }}>REZERVASYON</Text>
      </View>
    );
  }
  if (kasa === 'rentcar') {
    return (
      <View style={{ paddingHorizontal: 6, paddingVertical: 1, backgroundColor: Colors.status.info, borderRadius: 4 }}>
        <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900' }}>🚗 RENTCAR</Text>
      </View>
    );
  }
  if (kasa === 'eticaret') {
    return (
      <View style={{ paddingHorizontal: 6, paddingVertical: 1, backgroundColor: '#9333ea', borderRadius: 4 }}>
        <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900' }}>🛒 E-TİCARET</Text>
      </View>
    );
  }
  // Belirsiz (eski kayıt)
  return (
    <View style={{ paddingHorizontal: 6, paddingVertical: 1, backgroundColor: Colors.text.tertiary, borderRadius: 4 }}>
      <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900' }}>⚪ BELİRSİZ</Text>
    </View>
  );
}

// Araç Performans Kartı
function VehiclePerfCard({ a, maxKazanc }: { a: any; maxKazanc: number }) {
  const [expanded, setExpanded] = useState(false);
  const pct = maxKazanc > 0 ? Math.max(5, Math.round((a.toplam_kazanc / maxKazanc) * 100)) : 0;
  return (
    <GlassCard style={{ padding: 12 }}>
      <Pressable onPress={() => setExpanded(!expanded)}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          {a.foto_url ? (
            <Image source={{ uri: a.foto_url }} style={{ width: 44, height: 44, borderRadius: 8, marginRight: 10, backgroundColor: Colors.bg.surface }} />
          ) : (
            <View style={{ width: 44, height: 44, borderRadius: 8, marginRight: 10, backgroundColor: Colors.bg.surface, alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name="car-sport" size={22} color={Colors.text.tertiary} />
            </View>
          )}
          <View style={{ flex: 1 }}>
            <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{a.marka} {a.model}</Text>
            <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 1 }}>{a.plaka} • {a.kiralama_gun} gün • {a.rezervasyon_adet} rez.</Text>
          </View>
          <View style={{ alignItems: 'flex-end' }}>
            <Text style={{ ...Typography.bodyBold, color: Colors.status.success }}>{a.toplam_kazanc.toLocaleString('tr-TR')} ₺</Text>
            <Ionicons name={expanded ? 'chevron-up' : 'chevron-down'} size={14} color={Colors.text.tertiary} style={{ marginTop: 2 }} />
          </View>
        </View>
        {/* Progress bar */}
        <View style={{ height: 4, backgroundColor: Colors.bg.surface, borderRadius: 2, marginTop: 8, overflow: 'hidden' }}>
          <View style={{ height: '100%', width: `${pct}%`, backgroundColor: Colors.brand.primary }} />
        </View>
      </Pressable>
      {expanded && (
        <View style={{ marginTop: 10, paddingTop: 10, borderTopWidth: 1, borderTopColor: Colors.border.base, gap: 4 }}>
          <PerfRow icon="car" label="Kiralanan Gün" value={`${a.kiralama_gun} gün`} />
          <PerfRow icon="cash" label="Araç Geliri" value={`${a.arac_gelir.toLocaleString('tr-TR')} ₺`} />
          <PerfRow icon="pricetag" label="Ek Hizmet Geliri" value={`${a.hizmet_gelir.toLocaleString('tr-TR')} ₺`} />
          <PerfRow icon="speedometer" label="Ek KM Geliri" value={`${a.km_gelir.toLocaleString('tr-TR')} ₺`} />
          <View style={{ height: 1, backgroundColor: Colors.border.base, marginVertical: 4 }} />
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text style={{ ...Typography.caption, color: Colors.text.primary, fontWeight: '700' }}>TOPLAM KAZANÇ</Text>
            <Text style={{ ...Typography.bodyBold, color: Colors.status.success }}>{a.toplam_kazanc.toLocaleString('tr-TR')} ₺</Text>
          </View>
        </View>
      )}
    </GlassCard>
  );
}

function PerfRow({ icon, label, value }: { icon: any; label: string; value: string }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Ionicons name={icon} size={12} color={Colors.text.tertiary} />
        <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{label}</Text>
      </View>
      <Text style={{ ...Typography.caption, color: Colors.text.primary, fontWeight: '600' }}>{value}</Text>
    </View>
  );
}

// Kasa satırı (Cashflow row)
function CashflowRow({ label, value, sign, icon, hint, muted }: { label: string; value: number; sign: 1 | -1; icon: any; hint?: string; muted?: boolean }) {
  const color = muted ? Colors.text.secondary : (sign > 0 ? Colors.status.success : Colors.status.error);
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: 4 }}>
      <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 6 }}>
        <Ionicons name={icon} size={13} color={color} />
        <View style={{ flex: 1 }}>
          <Text style={{ ...Typography.caption, color: Colors.text.primary }}>{label}</Text>
          {hint ? <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>{hint}</Text> : null}
        </View>
      </View>
      <Text style={{ ...Typography.caption, fontWeight: '700', color }}>
        {sign > 0 ? '' : '-'}{Math.abs(value).toLocaleString('tr-TR', { maximumFractionDigits: 0 })} ₺
      </Text>
    </View>
  );
}


// ===== Muhasebe (Faz A: Aylık Özet + Giden/Gelen Faturalar + Ayarlar) =====
function MuhasebeTab() {
  const [subTab, setSubTab] = useState<'aylik' | 'gecici' | 'yillik' | 'giden' | 'gelen' | 'ayarlar'>('aylik');
  const [yil, setYil] = useState<number>(new Date().getFullYear());
  const [years, setYears] = useState<number[]>([new Date().getFullYear()]);
  const [monthly, setMonthly] = useState<any>(null);
  const [quarterly, setQuarterly] = useState<any>(null);
  const [annual, setAnnual] = useState<any>(null);
  const [invoices, setInvoices] = useState<any[]>([]);
  const [settings, setSettings] = useState<{ kdv_orani: number; gecici_vergi_orani: number; gunluk_birim_fiyat_net: number }>({ kdv_orani: 20, gecici_vergi_orani: 20, gunluk_birim_fiyat_net: 500 });
  const [loading, setLoading] = useState(true);
  // Gelen fatura formu
  const [gelenOpen, setGelenOpen] = useState(false);
  const [editingGelen, setEditingGelen] = useState<any>(null);
  const [gelenForm, setGelenForm] = useState<any>({ tarih: '', tedarikci: '', fatura_no_dis: '', kategori: '', aciklama: '', birim: 'Adet', miktar: '1', birim_fiyat_net: '', kdv_orani: '20' });

  const loadYears = useCallback(async () => {
    try { const ys = await adminApi.accountingYears(); setYears(ys.length ? ys : [new Date().getFullYear()]); } catch {}
  }, []);

  const loadMonthly = useCallback(async () => {
    setLoading(true);
    try { setMonthly(await adminApi.accountingMonthly(yil)); } catch (e: any) { Alert.alert('Hata', e.message); } finally { setLoading(false); }
  }, [yil]);

  const loadQuarterly = useCallback(async () => {
    setLoading(true);
    try { setQuarterly(await adminApi.accountingQuarterly(yil)); } catch (e: any) { Alert.alert('Hata', e.message); } finally { setLoading(false); }
  }, [yil]);

  const loadAnnual = useCallback(async () => {
    setLoading(true);
    try { setAnnual(await adminApi.accountingAnnual()); } catch (e: any) { Alert.alert('Hata', e.message); } finally { setLoading(false); }
  }, []);

  const loadInvoices = useCallback(async (tip: 'giden' | 'gelen') => {
    setLoading(true);
    try { setInvoices(await adminApi.listInvoices(tip, yil)); } catch (e: any) { Alert.alert('Hata', e.message); } finally { setLoading(false); }
  }, [yil]);

  const loadSettings = useCallback(async () => {
    try { setSettings(await adminApi.accountingSettings()); } catch {}
  }, []);

  useEffect(() => { loadYears(); loadSettings(); }, [loadYears, loadSettings]);
  useEffect(() => {
    if (subTab === 'aylik') loadMonthly();
    else if (subTab === 'gecici') loadQuarterly();
    else if (subTab === 'yillik') loadAnnual();
    else if (subTab === 'giden') loadInvoices('giden');
    else if (subTab === 'gelen') loadInvoices('gelen');
  }, [subTab, yil, loadMonthly, loadQuarterly, loadAnnual, loadInvoices]);

  const regenerate = async () => {
    try {
      const r = await adminApi.regenerateInvoices();
      Alert.alert('Tamam', `${r.created} fatura oluşturuldu, ${r.skipped} mevcut.`);
      if (subTab === 'aylik') loadMonthly();
      else if (subTab === 'giden') loadInvoices('giden');
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const openGelenForm = (existing?: any) => {
    setEditingGelen(existing || null);
    if (existing) {
      setGelenForm({
        tarih: isoToTrDate(existing.tarih) || '',
        tedarikci: existing.tedarikci || '',
        fatura_no_dis: existing.fatura_no_dis || '',
        kategori: existing.kategori || '',
        aciklama: existing.aciklama || '',
        birim: existing.birim || 'Adet',
        miktar: String(existing.miktar || 1),
        birim_fiyat_net: String(existing.birim_fiyat_net || ''),
        kdv_orani: String(existing.kdv_orani || 20),
      });
    } else {
      const today = new Date();
      const p = (n: number) => String(n).padStart(2, '0');
      setGelenForm({
        tarih: `${p(today.getDate())}.${p(today.getMonth() + 1)}.${today.getFullYear()}`,
        tedarikci: '', fatura_no_dis: '', kategori: '', aciklama: '', birim: 'Adet', miktar: '1', birim_fiyat_net: '', kdv_orani: String(settings.kdv_orani || 20),
      });
    }
    setGelenOpen(true);
  };

  const saveGelen = async () => {
    try {
      const iso = trDateToIso(gelenForm.tarih);
      if (!iso) { Alert.alert('Hata', 'Tarih GG.AA.YYYY formatında olmalı'); return; }
      if (!gelenForm.tedarikci.trim() || !gelenForm.kategori.trim()) { Alert.alert('Hata', 'Tedarikçi ve kategori zorunlu'); return; }
      const miktar = parseFloat((gelenForm.miktar || '').replace(',', '.') || '0');
      const fiyat = parseFloat((gelenForm.birim_fiyat_net || '').replace(',', '.') || '0');
      if (miktar <= 0 || fiyat <= 0) { Alert.alert('Hata', 'Miktar ve birim fiyat 0\'dan büyük olmalı'); return; }
      const payload = {
        tarih: iso,
        tedarikci: gelenForm.tedarikci.trim(),
        fatura_no_dis: gelenForm.fatura_no_dis.trim(),
        kategori: gelenForm.kategori.trim(),
        aciklama: gelenForm.aciklama,
        birim: gelenForm.birim || 'Adet',
        miktar,
        birim_fiyat_net: fiyat,
        kdv_orani: parseFloat((gelenForm.kdv_orani || '20').replace(',', '.')) || 20,
        kasa: 'rentcar',
      };
      if (editingGelen) await adminApi.updateGelenFatura(editingGelen.id, payload);
      else await adminApi.createGelenFatura(payload);
      setGelenOpen(false);
      setEditingGelen(null);
      loadInvoices('gelen');
      loadYears();
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const deleteInvoice = (inv: any) => {
    const isGiden = inv.tip === 'giden';
    Alert.alert(
      isGiden ? 'Giden fatura silinsin mi?' : 'Gelen fatura silinsin mi?',
      `${inv.no} • ${inv.toplam_tutar?.toLocaleString('tr-TR')} ₺${isGiden ? '\n(Rezervasyon kaydı SİLİNMEZ, sadece muhasebe faturası silinir)' : ''}`,
      [{ text: 'Vazgeç' }, { text: 'Sil', style: 'destructive', onPress: async () => {
        try { await adminApi.deleteInvoice(inv.id); loadInvoices(isGiden ? 'giden' : 'gelen'); } catch (e: any) { Alert.alert('Hata', e.message); }
      } }]);
  };

  const saveSettings = async () => {
    try {
      const k = parseFloat(String(settings.kdv_orani || 0));
      const g = parseFloat(String(settings.gecici_vergi_orani || 0));
      const b = parseFloat(String(settings.gunluk_birim_fiyat_net || 0));
      await adminApi.updateAccountingSettings({ kdv_orani: k, gecici_vergi_orani: g, gunluk_birim_fiyat_net: b });
      Alert.alert('Tamam', 'Ayarlar kaydedildi.\n\nMevcut giden faturalar eski birim fiyatla kaldı. Yenisi için "Eski Faturaları Tekrar Üret" butonunu kullanın.');
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const forceRegenerate = () => {
    Alert.alert(
      'Tüm Giden Faturaları Yeniden Üret',
      'Mevcut otomatik giden faturalar SİLİNECEK ve güncel ayarlarla yeniden üretilecek.\n\nFatura numaraları yeniden atanır. Devam etmek istiyor musunuz?',
      [
        { text: 'Vazgeç' },
        { text: 'Yeniden Üret', style: 'destructive', onPress: async () => {
          try {
            const r = await adminApi.regenerateInvoices(true);
            Alert.alert('Tamam', `${r.created} fatura yeniden üretildi.`);
            if (subTab === 'aylik') loadMonthly();
            else if (subTab === 'giden') loadInvoices('giden');
          } catch (e: any) { Alert.alert('Hata', e.message); }
        } }
      ]);
  };

  const subTabs: { key: typeof subTab; label: string; icon: any }[] = [
    { key: 'aylik', label: 'Aylık Özet', icon: 'stats-chart' },
    { key: 'gecici', label: 'Geçici Vergi', icon: 'cash' },
    { key: 'yillik', label: 'Yıllık Özet', icon: 'calendar' },
    { key: 'giden', label: 'Giden Faturalar', icon: 'arrow-up-circle' },
    { key: 'gelen', label: 'Gelen Faturalar', icon: 'arrow-down-circle' },
    { key: 'ayarlar', label: 'Ayarlar', icon: 'settings' },
  ];

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 80 }}>
      {/* Yıl seçici + sub-tabs */}
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <View style={{ flex: 1 }}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View style={{ flexDirection: 'row', gap: 6 }}>
              {subTabs.map(st => (
                <Pressable key={st.key} onPress={() => setSubTab(st.key)} style={[styles.miniBtn, subTab === st.key && styles.miniBtnActive, { flexDirection: 'row', gap: 4 }]}>
                  <Ionicons name={st.icon} size={12} color={subTab === st.key ? '#fff' : Colors.text.secondary} />
                  <Text style={[styles.miniBtnText, subTab === st.key && { color: '#fff' }]}>{st.label}</Text>
                </Pressable>
              ))}
            </View>
          </ScrollView>
        </View>
      </View>

      {/* Yıl dropdown */}
      {subTab !== 'ayarlar' && subTab !== 'yillik' && (
        <View style={{ flexDirection: 'row', gap: 6, alignItems: 'center' }}>
          <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700' }}>YIL:</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View style={{ flexDirection: 'row', gap: 4 }}>
              {years.map(y => (
                <Pressable key={y} onPress={() => setYil(y)} style={[styles.miniBtn, yil === y && styles.miniBtnActive]}>
                  <Text style={[styles.miniBtnText, yil === y && { color: '#fff' }]}>{y}</Text>
                </Pressable>
              ))}
            </View>
          </ScrollView>
        </View>
      )}

      {loading ? <ActivityIndicator color={Colors.brand.primary} style={{ marginTop: 30 }} /> : (
        <>
          {/* Aylık Özet */}
          {subTab === 'aylik' && monthly && (
            <>
              {/* 4 özet kart */}
              <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
                <SummaryCard label="Toplam Gelir" value={monthly.toplam_gelir} color={Colors.status.success} icon="arrow-down-circle" />
                <SummaryCard label="Toplam Gider" value={monthly.toplam_gider} color={Colors.status.error} icon="arrow-up-circle" />
                <SummaryCard label="Ödenecek KDV" value={monthly.toplam_odenecek_kdv} color={Colors.status.warning} icon="receipt" />
                <SummaryCard label="Net Kâr" value={monthly.toplam_net_kar} color={monthly.toplam_net_kar >= 0 ? Colors.status.success : Colors.status.error} icon="trending-up" />
              </View>

              <Pressable onPress={regenerate} style={[styles.miniBtn, { alignSelf: 'flex-start', flexDirection: 'row', gap: 4 }]}>
                <Ionicons name="sync" size={12} color={Colors.text.secondary} />
                <Text style={styles.miniBtnText}>Eksik Faturaları Üret</Text>
              </Pressable>

              {/* Aylık tablo */}
              <GlassCard style={{ padding: 0, overflow: 'hidden' }}>
                <ScrollView horizontal>
                  <View>
                    {/* Header */}
                    <View style={{ flexDirection: 'row', backgroundColor: Colors.bg.surface, paddingVertical: 8, paddingHorizontal: 6 }}>
                      <TblCell text="Ay" w={70} bold />
                      <TblCell text="Gelir" w={90} bold align="right" />
                      <TblCell text="Gider" w={90} bold align="right" />
                      <TblCell text="Hesaplanan KDV" w={110} bold align="right" />
                      <TblCell text="İndirilecek KDV" w={110} bold align="right" />
                      <TblCell text="Ödenecek KDV" w={110} bold align="right" />
                      <TblCell text="Net Kâr" w={100} bold align="right" />
                    </View>
                    {monthly.aylar.map((a: any, i: number) => (
                      <View key={a.ay} style={{ flexDirection: 'row', paddingVertical: 8, paddingHorizontal: 6, borderTopWidth: 1, borderTopColor: Colors.border.base, backgroundColor: i % 2 === 0 ? 'transparent' : Colors.bg.surface }}>
                        <TblCell text={a.ay_adi} w={70} />
                        <TblCell text={`${a.gelir.toLocaleString('tr-TR')}`} w={90} align="right" color={a.gelir > 0 ? Colors.status.success : Colors.text.tertiary} />
                        <TblCell text={`${a.gider.toLocaleString('tr-TR')}`} w={90} align="right" color={a.gider > 0 ? Colors.status.error : Colors.text.tertiary} />
                        <TblCell text={`${a.hesaplanan_kdv.toLocaleString('tr-TR')}`} w={110} align="right" />
                        <TblCell text={`${a.indirilecek_kdv.toLocaleString('tr-TR')}`} w={110} align="right" />
                        <TblCell text={`${a.odenecek_kdv.toLocaleString('tr-TR')}`} w={110} align="right" color={a.odenecek_kdv > 0 ? Colors.status.warning : Colors.text.tertiary} bold />
                        <TblCell text={`${a.net_kar.toLocaleString('tr-TR')}`} w={100} align="right" color={a.net_kar >= 0 ? Colors.status.success : Colors.status.error} bold />
                      </View>
                    ))}
                    {/* Toplam satır */}
                    <View style={{ flexDirection: 'row', paddingVertical: 10, paddingHorizontal: 6, borderTopWidth: 2, borderTopColor: Colors.brand.primary, backgroundColor: Colors.bg.surface }}>
                      <TblCell text="TOPLAM" w={70} bold />
                      <TblCell text={`${monthly.toplam_gelir.toLocaleString('tr-TR')}`} w={90} align="right" bold color={Colors.status.success} />
                      <TblCell text={`${monthly.toplam_gider.toLocaleString('tr-TR')}`} w={90} align="right" bold color={Colors.status.error} />
                      <TblCell text={`${monthly.toplam_hesaplanan_kdv.toLocaleString('tr-TR')}`} w={110} align="right" bold />
                      <TblCell text={`${monthly.toplam_indirilecek_kdv.toLocaleString('tr-TR')}`} w={110} align="right" bold />
                      <TblCell text={`${monthly.toplam_odenecek_kdv.toLocaleString('tr-TR')}`} w={110} align="right" bold color={Colors.status.warning} />
                      <TblCell text={`${monthly.toplam_net_kar.toLocaleString('tr-TR')}`} w={100} align="right" bold color={monthly.toplam_net_kar >= 0 ? Colors.status.success : Colors.status.error} />
                    </View>
                  </View>
                </ScrollView>
              </GlassCard>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, fontStyle: 'italic' }}>
                * Tüm tutarlar KDV HARİÇ. Gelir = Rezervasyonların günlük kira ücreti (ek hizmet ve ek km hariç). Tarih: Rezervasyon başlangıç tarihi.
              </Text>
            </>
          )}

          {/* Geçici Vergi (Quarterly) */}
          {subTab === 'gecici' && quarterly && (
            <>
              <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
                <SummaryCard label={`Vergi Oranı`} value={quarterly.oran} color={Colors.brand.primary} icon="pricetag" suffix="%" />
                <SummaryCard label="Yıllık Net Kâr" value={quarterly.donemler[3]?.kumulatif_net_kar || 0} color={(quarterly.donemler[3]?.kumulatif_net_kar || 0) >= 0 ? Colors.status.success : Colors.status.error} icon="trending-up" />
                <SummaryCard label="Yıllık Vergi" value={quarterly.donemler[3]?.kumulatif_vergi || 0} color={Colors.status.warning} icon="cash" />
              </View>

              <GlassCard style={{ padding: 0, overflow: 'hidden' }}>
                <ScrollView horizontal>
                  <View>
                    <View style={{ flexDirection: 'row', backgroundColor: Colors.bg.surface, paddingVertical: 8, paddingHorizontal: 6 }}>
                      <TblCell text="Dönem" w={120} bold />
                      <TblCell text="Gelir" w={90} bold align="right" />
                      <TblCell text="Gider" w={90} bold align="right" />
                      <TblCell text="Net Kâr (Dönem)" w={110} bold align="right" />
                      <TblCell text="Kümülatif Kâr" w={110} bold align="right" />
                      <TblCell text="Kümülatif Vergi" w={110} bold align="right" />
                      <TblCell text="Ödenecek Vergi" w={110} bold align="right" />
                    </View>
                    {quarterly.donemler.map((d: any, i: number) => (
                      <View key={d.key} style={{ flexDirection: 'row', paddingVertical: 8, paddingHorizontal: 6, borderTopWidth: 1, borderTopColor: Colors.border.base, backgroundColor: i % 2 === 0 ? 'transparent' : Colors.bg.surface }}>
                        <TblCell text={d.ad} w={120} bold />
                        <TblCell text={`${d.donem_gelir.toLocaleString('tr-TR')}`} w={90} align="right" color={d.donem_gelir > 0 ? Colors.status.success : Colors.text.tertiary} />
                        <TblCell text={`${d.donem_gider.toLocaleString('tr-TR')}`} w={90} align="right" color={d.donem_gider > 0 ? Colors.status.error : Colors.text.tertiary} />
                        <TblCell text={`${d.donem_net_kar.toLocaleString('tr-TR')}`} w={110} align="right" color={d.donem_net_kar >= 0 ? Colors.status.success : Colors.status.error} />
                        <TblCell text={`${d.kumulatif_net_kar.toLocaleString('tr-TR')}`} w={110} align="right" />
                        <TblCell text={`${d.kumulatif_vergi.toLocaleString('tr-TR')}`} w={110} align="right" color={Colors.text.secondary} />
                        <TblCell text={`${d.odenecek_vergi.toLocaleString('tr-TR')}`} w={110} align="right" color={d.odenecek_vergi > 0 ? Colors.status.warning : Colors.text.tertiary} bold />
                      </View>
                    ))}
                  </View>
                </ScrollView>
              </GlassCard>

              {/* Dönem kartları (mobilde okunabilirlik için) */}
              {quarterly.donemler.map((d: any) => (
                <GlassCard key={`card-${d.key}`} style={{ padding: 12 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                    <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{d.ad}</Text>
                    <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>Ay: {d.aylar.join(', ')}</Text>
                  </View>
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', marginTop: 8, gap: 4 }}>
                    <KV k="Dönem Geliri" v={`${d.donem_gelir.toLocaleString('tr-TR')} ₺`} c={Colors.status.success} />
                    <KV k="Dönem Gideri" v={`${d.donem_gider.toLocaleString('tr-TR')} ₺`} c={Colors.status.error} />
                    <KV k="Dönem Net Kâr" v={`${d.donem_net_kar.toLocaleString('tr-TR')} ₺`} c={d.donem_net_kar >= 0 ? Colors.status.success : Colors.status.error} />
                    <KV k="Kümülatif Net Kâr" v={`${d.kumulatif_net_kar.toLocaleString('tr-TR')} ₺`} c={Colors.text.primary} />
                    <KV k={`Kümülatif Vergi (%${quarterly.oran})`} v={`${d.kumulatif_vergi.toLocaleString('tr-TR')} ₺`} c={Colors.text.secondary} />
                    <KV k="Bu Dönem Ödenecek" v={`${d.odenecek_vergi.toLocaleString('tr-TR')} ₺`} c={d.odenecek_vergi > 0 ? Colors.status.warning : Colors.text.tertiary} bold />
                  </View>
                  {d.info ? (
                    <View style={{ marginTop: 8, padding: 8, backgroundColor: Colors.bg.surface, borderRadius: 6 }}>
                      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, fontStyle: 'italic' }}>ℹ️ {d.info}</Text>
                    </View>
                  ) : null}
                </GlassCard>
              ))}

              <View style={{ marginTop: 6, padding: 10, backgroundColor: Colors.bg.surface, borderRadius: 8 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700', marginBottom: 4 }}>ℹ️ GEÇİCİ VERGİ HAKKINDA</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Hesap kümülatiftir: Yıl başından dönem sonuna kadar olan net kâr × oran.</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Önceki dönemlerde ödenen mahsup edilir → bu dönem ödenecek tutar.</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Oran "Ayarlar" sekmesinden değiştirilebilir (varsayılan: %20).</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• 4. dönem (Ekim-Aralık) bilgilendirme amaçlıdır; resmi olarak yıllık beyan ile birleştirilir.</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Bu tablo bilgi amaçlıdır, resmi beyan için mali müşavirinize danışınız.</Text>
              </View>
            </>
          )}

          {/* Yıllık Özet */}
          {subTab === 'yillik' && annual && (
            <>
              <View style={{ flexDirection: 'row', gap: 6, flexWrap: 'wrap' }}>
                <SummaryCard label="Toplam Gelir" value={annual.toplam.gelir} color={Colors.status.success} icon="arrow-down-circle" />
                <SummaryCard label="Toplam Gider" value={annual.toplam.gider} color={Colors.status.error} icon="arrow-up-circle" />
                <SummaryCard label="Toplam Net Kâr" value={annual.toplam.net_kar} color={annual.toplam.net_kar >= 0 ? Colors.status.success : Colors.status.error} icon="trending-up" />
                <SummaryCard label="Toplam Vergi" value={annual.toplam.tahmini_yillik_vergi} color={Colors.status.warning} icon="cash" />
              </View>

              {annual.yillar.length === 0 ? (
                <Empty title="Henüz veri yok" icon={<Ionicons name="document-outline" size={36} color={Colors.text.tertiary} />} />
              ) : (
                <>
                  <GlassCard style={{ padding: 0, overflow: 'hidden' }}>
                    <ScrollView horizontal>
                      <View>
                        <View style={{ flexDirection: 'row', backgroundColor: Colors.bg.surface, paddingVertical: 8, paddingHorizontal: 6 }}>
                          <TblCell text="Yıl" w={70} bold />
                          <TblCell text="Gelir" w={100} bold align="right" />
                          <TblCell text="Gider" w={100} bold align="right" />
                          <TblCell text="Ödenecek KDV" w={110} bold align="right" />
                          <TblCell text="Net Kâr" w={100} bold align="right" />
                          <TblCell text={`Yıllık Vergi (%${annual.oran})`} w={140} bold align="right" />
                        </View>
                        {annual.yillar.map((y: any, i: number) => (
                          <View key={y.yil} style={{ flexDirection: 'row', paddingVertical: 8, paddingHorizontal: 6, borderTopWidth: 1, borderTopColor: Colors.border.base, backgroundColor: i % 2 === 0 ? 'transparent' : Colors.bg.surface }}>
                            <TblCell text={String(y.yil)} w={70} bold />
                            <TblCell text={`${y.gelir.toLocaleString('tr-TR')}`} w={100} align="right" color={Colors.status.success} />
                            <TblCell text={`${y.gider.toLocaleString('tr-TR')}`} w={100} align="right" color={Colors.status.error} />
                            <TblCell text={`${y.odenecek_kdv.toLocaleString('tr-TR')}`} w={110} align="right" color={y.odenecek_kdv > 0 ? Colors.status.warning : Colors.text.tertiary} />
                            <TblCell text={`${y.net_kar.toLocaleString('tr-TR')}`} w={100} align="right" bold color={y.net_kar >= 0 ? Colors.status.success : Colors.status.error} />
                            <TblCell text={`${y.tahmini_yillik_vergi.toLocaleString('tr-TR')}`} w={140} align="right" bold color={Colors.status.warning} />
                          </View>
                        ))}
                        {/* Toplam */}
                        <View style={{ flexDirection: 'row', paddingVertical: 10, paddingHorizontal: 6, borderTopWidth: 2, borderTopColor: Colors.brand.primary, backgroundColor: Colors.bg.surface }}>
                          <TblCell text="TOPLAM" w={70} bold />
                          <TblCell text={`${annual.toplam.gelir.toLocaleString('tr-TR')}`} w={100} align="right" bold color={Colors.status.success} />
                          <TblCell text={`${annual.toplam.gider.toLocaleString('tr-TR')}`} w={100} align="right" bold color={Colors.status.error} />
                          <TblCell text={`${annual.toplam.odenecek_kdv.toLocaleString('tr-TR')}`} w={110} align="right" bold color={Colors.status.warning} />
                          <TblCell text={`${annual.toplam.net_kar.toLocaleString('tr-TR')}`} w={100} align="right" bold color={annual.toplam.net_kar >= 0 ? Colors.status.success : Colors.status.error} />
                          <TblCell text={`${annual.toplam.tahmini_yillik_vergi.toLocaleString('tr-TR')}`} w={140} align="right" bold color={Colors.status.warning} />
                        </View>
                      </View>
                    </ScrollView>
                  </GlassCard>

                  {/* Yıl kartları */}
                  {annual.yillar.map((y: any) => (
                    <GlassCard key={`year-${y.yil}`} style={{ padding: 12 }}>
                      <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 6 }}>{y.yil} Yılı</Text>
                      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 4 }}>
                        <KV k="Gelir" v={`${y.gelir.toLocaleString('tr-TR')} ₺`} c={Colors.status.success} />
                        <KV k="Gider" v={`${y.gider.toLocaleString('tr-TR')} ₺`} c={Colors.status.error} />
                        <KV k="Net Kâr" v={`${y.net_kar.toLocaleString('tr-TR')} ₺`} c={y.net_kar >= 0 ? Colors.status.success : Colors.status.error} bold />
                        <KV k="Ödenecek KDV" v={`${y.odenecek_kdv.toLocaleString('tr-TR')} ₺`} c={Colors.status.warning} />
                        <KV k={`Yıllık Vergi (%${annual.oran})`} v={`${y.tahmini_yillik_vergi.toLocaleString('tr-TR')} ₺`} c={Colors.status.warning} bold />
                      </View>
                    </GlassCard>
                  ))}
                </>
              )}

              <View style={{ marginTop: 6, padding: 10, backgroundColor: Colors.bg.surface, borderRadius: 8 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700', marginBottom: 4 }}>ℹ️ NOTLAR</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Yıllık vergi tahmini = Net Kâr × Geçici Vergi Oranı (basitleştirilmiş).</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Gerçek beyan; gider kabul edilen kalemler, indirimler, KKEG vs. ile farklı çıkar.</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Resmi beyan için mali müşavirinize danışınız.</Text>
              </View>
            </>
          )}

          {/* Giden Faturalar */}
          {subTab === 'giden' && (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' }}>Giden Faturalar ({invoices.length})</Text>
                <Pressable onPress={regenerate} style={[styles.miniBtn, { flexDirection: 'row', gap: 4 }]}>
                  <Ionicons name="sync" size={12} color={Colors.text.secondary} />
                  <Text style={styles.miniBtnText}>Eksik Faturaları Üret</Text>
                </Pressable>
              </View>
              {invoices.length === 0 ? (
                <Empty title="Bu yıl için giden fatura yok" icon={<Ionicons name="document-outline" size={36} color={Colors.text.tertiary} />} />
              ) : invoices.map(inv => (
                <GlassCard key={inv.id} style={{ padding: 12 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <View style={{ flex: 1 }}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                        <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{inv.no}</Text>
                        <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>{isoToTrDate(inv.tarih)}</Text>
                      </View>
                      <Text style={{ ...Typography.caption, color: Colors.text.primary, marginTop: 3 }}>{inv.plaka} {inv.marka_model}</Text>
                      <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 1 }}>{inv.miktar} {inv.birim} × {inv.birim_fiyat_net.toLocaleString('tr-TR')} ₺ • {inv.customer_ad}</Text>
                      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 1 }}>KDV Hariç: {inv.kdv_haric_tutar.toLocaleString('tr-TR')} ₺ + KDV ({inv.kdv_orani}%): {inv.kdv_tutar.toLocaleString('tr-TR')} ₺</Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={{ ...Typography.bodyBold, color: Colors.status.success }}>{inv.toplam_tutar.toLocaleString('tr-TR')} ₺</Text>
                      <Pressable onPress={() => deleteInvoice(inv)} style={[styles.iconBtn, { marginTop: 6 }]}>
                        <Ionicons name="trash" size={13} color={Colors.status.error} />
                      </Pressable>
                    </View>
                  </View>
                </GlassCard>
              ))}
            </>
          )}

          {/* Gelen Faturalar */}
          {subTab === 'gelen' && (
            <>
              <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' }}>Gelen Faturalar ({invoices.length})</Text>
                <Pressable onPress={() => openGelenForm()} style={[styles.fab, { height: 36, width: 'auto' as any, flexDirection: 'row', gap: 4, paddingHorizontal: 12 }]}>
                  <Ionicons name="add" size={16} color="#fff" />
                  <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12 }}>Fatura Ekle</Text>
                </Pressable>
              </View>
              {invoices.length === 0 ? (
                <Empty title="Bu yıl için gelen fatura yok" icon={<Ionicons name="document-outline" size={36} color={Colors.text.tertiary} />} />
              ) : invoices.map(inv => (
                <GlassCard key={inv.id} style={{ padding: 12 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center' }}>
                    <View style={{ flex: 1 }}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                        <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{inv.no}</Text>
                        <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>{isoToTrDate(inv.tarih)}</Text>
                        {inv.fatura_no_dis ? <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Dış No: {inv.fatura_no_dis}</Text> : null}
                      </View>
                      <Text style={{ ...Typography.caption, color: Colors.text.primary, marginTop: 3 }}>{inv.tedarikci} — {inv.kategori}</Text>
                      <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 1 }}>{inv.miktar} {inv.birim} × {inv.birim_fiyat_net.toLocaleString('tr-TR')} ₺</Text>
                      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 1 }}>KDV Hariç: {inv.kdv_haric_tutar.toLocaleString('tr-TR')} ₺ + KDV ({inv.kdv_orani}%): {inv.kdv_tutar.toLocaleString('tr-TR')} ₺</Text>
                    </View>
                    <View style={{ alignItems: 'flex-end' }}>
                      <Text style={{ ...Typography.bodyBold, color: Colors.status.error }}>{inv.toplam_tutar.toLocaleString('tr-TR')} ₺</Text>
                      <View style={{ flexDirection: 'row', gap: 4, marginTop: 6 }}>
                        <Pressable onPress={() => openGelenForm(inv)} style={styles.iconBtn}>
                          <Ionicons name="pencil" size={13} color={Colors.text.primary} />
                        </Pressable>
                        <Pressable onPress={() => deleteInvoice(inv)} style={styles.iconBtn}>
                          <Ionicons name="trash" size={13} color={Colors.status.error} />
                        </Pressable>
                      </View>
                    </View>
                  </View>
                </GlassCard>
              ))}
            </>
          )}

          {/* Ayarlar */}
          {subTab === 'ayarlar' && (
            <GlassCard style={{ padding: 14 }}>
              <Text style={{ ...Typography.h4, color: Colors.text.primary, marginBottom: 12 }}>Muhasebe Ayarları</Text>

              <Field
                label="Günlük Kira Birim Fiyatı (KDV HARİÇ ₺)"
                v={String(settings.gunluk_birim_fiyat_net)}
                on={(x) => setSettings({ ...settings, gunluk_birim_fiyat_net: parseFloat(x.replace(',', '.')) || 0 })}
                kb="decimal-pad"
              />
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: -8, marginBottom: 8 }}>
                Otomatik giden faturalarda her gün için bu fiyat baz alınır (rezervasyon ücretinden bağımsız). Örn: 500 ₺ → 2 gün rezervasyon = 1.000 ₺ + KDV.
              </Text>

              <Field label="KDV Oranı (%)" v={String(settings.kdv_orani)} on={(x) => setSettings({ ...settings, kdv_orani: parseFloat(x.replace(',', '.')) || 0 })} kb="decimal-pad" />
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: -8, marginBottom: 8 }}>Türkiye standart: %20</Text>

              <Field label="Geçici Vergi Oranı (%)" v={String(settings.gecici_vergi_orani)} on={(x) => setSettings({ ...settings, gecici_vergi_orani: parseFloat(x.replace(',', '.')) || 0 })} kb="decimal-pad" />
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: -8, marginBottom: 12 }}>Şahıs şirketi standart: %20 (muhasebeciniz farklı söylediyse değiştirebilirsiniz)</Text>

              <GlassButton title="AYARLARI KAYDET" onPress={saveSettings} />

              <View style={{ height: 1, backgroundColor: Colors.border.base, marginVertical: 16 }} />

              <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 6 }}>Mevcut Faturaları Yeniden Üret</Text>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginBottom: 10 }}>
                Birim fiyat veya KDV oranını değiştirdiyseniz, mevcut otomatik giden faturalar eski değerlerle kaldı. Aşağıdaki butonla hepsini güncel ayarlarla yeniden üretebilirsiniz.
              </Text>
              <Pressable onPress={forceRegenerate} style={[styles.miniBtn, { backgroundColor: Colors.status.warning, borderColor: Colors.status.warning, alignSelf: 'flex-start', flexDirection: 'row', gap: 6, paddingHorizontal: 12, paddingVertical: 10 }]}>
                <Ionicons name="refresh" size={14} color="#fff" />
                <Text style={{ color: '#fff', fontWeight: '700' }}>Tüm Giden Faturaları Yeniden Üret</Text>
              </Pressable>

              <View style={{ marginTop: 16, padding: 10, backgroundColor: Colors.bg.surface, borderRadius: 8 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700', marginBottom: 4 }}>ℹ️ NOTLAR</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Birim fiyatlar KDV HARİÇ olarak kabul edilir.</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Rezervasyon başlangıç tarihinde otomatik fatura kesilir.</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Sadece günlük kira hesabı baz alınır (ek hizmet ve ek km hariç).</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>• Eski (Muhasebe öncesi) rezervasyonlar için "Eksik Faturaları Üret" butonunu kullanın.</Text>
              </View>
            </GlassCard>
          )}
        </>
      )}

      {/* Gelen Fatura Modal */}
      <Modal visible={gelenOpen} animationType="slide" transparent onRequestClose={() => setGelenOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text style={styles.modalTitle}>{editingGelen ? 'Gelen Fatura Düzenle' : 'Yeni Gelen Fatura'}</Text>
              <Pressable onPress={() => setGelenOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <ScrollView style={{ maxHeight: 540 }}>
              <Field label="Tarih (GG.AA.YYYY)" v={gelenForm.tarih} on={(x) => setGelenForm({ ...gelenForm, tarih: maskTrDate(x) })} kb="number-pad" />
              <Field label="Tedarikçi (Şirket adı)" v={gelenForm.tedarikci} on={(x) => setGelenForm({ ...gelenForm, tedarikci: x })} />
              <Field label="Fatura No (Tedarikçinin numarası)" v={gelenForm.fatura_no_dis} on={(x) => setGelenForm({ ...gelenForm, fatura_no_dis: x })} />
              <Field label="Kategori (örn: Yakıt, Bakım, Sigorta)" v={gelenForm.kategori} on={(x) => setGelenForm({ ...gelenForm, kategori: x })} />
              <Field label="Açıklama (opsiyonel)" v={gelenForm.aciklama} on={(x) => setGelenForm({ ...gelenForm, aciklama: x })} multi />
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <View style={{ flex: 1 }}><Field label="Birim" v={gelenForm.birim} on={(x) => setGelenForm({ ...gelenForm, birim: x })} /></View>
                <View style={{ flex: 1 }}><Field label="Miktar" v={gelenForm.miktar} on={(x) => setGelenForm({ ...gelenForm, miktar: x })} kb="decimal-pad" /></View>
              </View>
              <Field label="Birim Fiyat KDV HARİÇ (₺)" v={gelenForm.birim_fiyat_net} on={(x) => setGelenForm({ ...gelenForm, birim_fiyat_net: x })} kb="decimal-pad" />
              <Field label="KDV Oranı (%)" v={gelenForm.kdv_orani} on={(x) => setGelenForm({ ...gelenForm, kdv_orani: x })} kb="decimal-pad" />
              {/* Önizleme */}
              {(() => {
                const m = parseFloat((gelenForm.miktar || '0').replace(',', '.')) || 0;
                const f = parseFloat((gelenForm.birim_fiyat_net || '0').replace(',', '.')) || 0;
                const k = parseFloat((gelenForm.kdv_orani || '20').replace(',', '.')) || 0;
                const haric = m * f;
                const kdvT = haric * k / 100;
                const top = haric + kdvT;
                return (
                  <View style={{ marginTop: 4, padding: 10, backgroundColor: Colors.bg.surface, borderRadius: 8 }}>
                    <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginBottom: 4 }}>ÖNİZLEME</Text>
                    <Text style={{ ...Typography.caption, color: Colors.text.primary }}>KDV Hariç: {haric.toLocaleString('tr-TR', { maximumFractionDigits: 2 })} ₺</Text>
                    <Text style={{ ...Typography.caption, color: Colors.text.primary }}>KDV ({k}%): {kdvT.toLocaleString('tr-TR', { maximumFractionDigits: 2 })} ₺</Text>
                    <Text style={{ ...Typography.bodyBold, color: Colors.status.error, marginTop: 2 }}>Genel Toplam: {top.toLocaleString('tr-TR', { maximumFractionDigits: 2 })} ₺</Text>
                  </View>
                );
              })()}
            </ScrollView>
            <GlassButton title={editingGelen ? 'KAYDET' : 'FATURA EKLE'} onPress={saveGelen} />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

function SummaryCard({ label, value, color, icon, suffix }: { label: string; value: number; color: string; icon: any; suffix?: string }) {
  return (
    <GlassCard style={{ flexGrow: 1, flexBasis: '47%', padding: 12, minWidth: 140 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <Ionicons name={icon} size={14} color={color} />
        <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700' }}>{label}</Text>
      </View>
      <Text style={{ fontSize: 18, fontWeight: '900', color }}>{value.toLocaleString('tr-TR', { maximumFractionDigits: 2 })} {suffix || '₺'}</Text>
    </GlassCard>
  );
}

function KV({ k, v, c, bold }: { k: string; v: string; c?: string; bold?: boolean }) {
  return (
    <View style={{ flexBasis: '48%', flexGrow: 1, paddingVertical: 4, paddingHorizontal: 6, backgroundColor: Colors.bg.surface, borderRadius: 6 }}>
      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, fontSize: 10 }}>{k}</Text>
      <Text style={{ fontSize: 13, fontWeight: bold ? '800' : '700', color: c || Colors.text.primary, marginTop: 2 }}>{v}</Text>
    </View>
  );
}

function TblCell({ text, w, bold, align, color }: { text: string; w: number; bold?: boolean; align?: 'left' | 'right'; color?: string }) {
  return (
    <Text style={{ width: w, fontSize: 11, fontWeight: bold ? '800' : '500', color: color || Colors.text.primary, textAlign: align || 'left', paddingHorizontal: 4 }}>
      {text}
    </Text>
  );
}

// ===== Helpers: TR datetime parser/formatter (07.11.1992 19:00 ↔ ISO) =====
function trDtToIso(s: string): string | null {
  // Accepts: "DD.MM.YYYY HH:MM" or "DD.MM.YYYY HH:MM:SS"
  const m = (s || '').trim().match(/^(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!m) return null;
  const [, dd, mo, yy, hh, mi, ss] = m;
  const d = new Date(parseInt(yy), parseInt(mo) - 1, parseInt(dd), parseInt(hh), parseInt(mi), ss ? parseInt(ss) : 0);
  if (isNaN(d.getTime())) return null;
  return d.toISOString();
}

function isoToTrDt(iso?: string | null): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    const p = (n: number) => String(n).padStart(2, '0');
    return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  } catch { return ''; }
}

// Bakım & Yasal Takip
// TR date helpers — DD.MM.YYYY ↔ ISO YYYY-MM-DD (date only, no time)
function trDateToIso(s: string): string | null {
  const m = (s || '').trim().match(/^(\d{2})\.(\d{2})\.(\d{4})$/);
  if (!m) return null;
  const [, dd, mo, yy] = m;
  const d = new Date(parseInt(yy), parseInt(mo) - 1, parseInt(dd));
  if (isNaN(d.getTime())) return null;
  // Manuel ISO format YYYY-MM-DD (gün ofseti hatalarını engelle)
  return `${yy}-${mo}-${dd}`;
}

function isoToTrDate(iso?: string | null): string {
  if (!iso) return '';
  // ISO YYYY-MM-DD veya tam ISO datetime kabul et
  const m = (iso || '').match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return '';
  return `${m[3]}.${m[2]}.${m[1]}`;
}

// Tarih maskesi: kullanıcı sadece rakam yazar, biz arasına nokta atarız
// "12052026" → "12.05.2026" / "120" → "12.0"
function maskTrDate(input: string): string {
  const digits = (input || '').replace(/\D/g, '').slice(0, 8);
  if (digits.length <= 2) return digits;
  if (digits.length <= 4) return `${digits.slice(0, 2)}.${digits.slice(2)}`;
  return `${digits.slice(0, 2)}.${digits.slice(2, 4)}.${digits.slice(4)}`;
}

// Şallow + iç içe array/obje karşılaştırma — base64 array'leri için JSON.stringify yeterli ama büyük dosyalar için pahalı.
// Fotoğraflar gibi büyük string array'leri için referans + uzunluk + ilk/son hash kıyaslaması kullanılır.
function _deepEqual(a: any, b: any): boolean {
  if (a === b) return true;
  if (a == null || b == null) return a === b;
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a)) {
    if (!Array.isArray(b)) return false;
    if (a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!_deepEqual(a[i], b[i])) return false;
    return true;
  }
  if (typeof a === 'object') {
    const ak = Object.keys(a), bk = Object.keys(b);
    if (ak.length !== bk.length) return false;
    for (const k of ak) if (!_deepEqual(a[k], b[k])) return false;
    return true;
  }
  return false;
}

// Bakım/Tarih uyarı yardımcısı
// Return: { days, severity } or null
function daysUntil(isoDate?: string | null): { days: number; severity: 'red' | 'yellow' | null } | null {
  if (!isoDate) return null;
  try {
    const d = new Date(isoDate);
    if (isNaN(d.getTime())) return null;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const target = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const diff = Math.round((target.getTime() - today.getTime()) / 86400000);
    let sev: 'red' | 'yellow' | null = null;
    if (diff < 0) sev = 'red';
    else if (diff <= 10) sev = 'red';
    else if (diff <= 30) sev = 'yellow';
    return { days: diff, severity: sev };
  } catch { return null; }
}

// KM bakım uyarısı (yağ): yaklaşan eşik = 1500 km
function kmUntilService(mevcut?: number | null, hedef?: number | null): { kalan: number; severity: 'red' | 'yellow' | null } | null {
  if (mevcut == null || hedef == null) return null;
  const kalan = hedef - mevcut;
  let sev: 'red' | 'yellow' | null = null;
  if (kalan <= 0) sev = 'red';
  else if (kalan <= 500) sev = 'red';
  else if (kalan <= 1500) sev = 'yellow';
  return { kalan, severity: sev };
}

function MaintWarning({ icon, label, color }: { icon: any; label: string; color: string }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 10, backgroundColor: color + '22', borderWidth: 1, borderColor: color + '66' }}>
      <Ionicons name={icon} size={11} color={color} />
      <Text style={{ fontSize: 10, color, fontWeight: '700' }}>{label}</Text>
    </View>
  );
}

// ===== Customers =====
function CustomersTab() {
  const [list, setList] = useState<any[]>([]);
  const [counts, setCounts] = useState<{ tum: number; bireysel: number; kurumsal: number; engelli: number }>({ tum: 0, bireysel: 0, kurumsal: 0, engelli: 0 });
  const [q, setQ] = useState('');
  const [filtre, setFiltre] = useState<'tum' | 'bireysel' | 'kurumsal' | 'engelli'>('tum');
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const emptyForm = { ad: '', soyad: '', tc: '', telefon: '', email: '', notlar: '', adres: '', tip: 'bireysel', firma_adi: '', vergi_no: '', yetkili: '' };
  const [form, setForm] = useState<any>(emptyForm);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const f = filtre === 'tum' ? undefined : filtre;
      const [docs, cnt] = await Promise.all([
        adminApi.customers(q || undefined, f as any),
        adminApi.customerCounts().catch(() => ({ tum: 0, bireysel: 0, kurumsal: 0, engelli: 0 })),
      ]);
      setList(docs);
      setCounts(cnt as any);
    } catch {} finally { setLoading(false); }
  }, [q, filtre]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      if (!form.ad?.trim() || !form.soyad?.trim()) { Alert.alert('Hata', 'Ad ve soyad zorunlu'); return; }
      if (editing) {
        // TC değiştirilemez (PUT body'de yok zaten); diğer alanları yolla
        const upd: any = { ad: form.ad, soyad: form.soyad, telefon: form.telefon, email: form.email, notlar: form.notlar, adres: form.adres, tip: form.tip, firma_adi: form.firma_adi, vergi_no: form.vergi_no, yetkili: form.yetkili };
        await adminApi.updateCustomer(editing.id, upd);
      } else {
        if (!form.tc || form.tc.length !== 11) { Alert.alert('Hata', 'TC 11 haneli olmalı'); return; }
        if (!form.telefon?.trim()) { Alert.alert('Hata', 'Telefon zorunlu'); return; }
        await adminApi.createCustomer(form);
      }
      setOpen(false);
      setEditing(null);
      setForm(emptyForm);
      load();
    } catch (e: any) {
      Alert.alert('Hata', e.message);
    }
  };

  const toggleBlock = async (c: any) => {
    try {
      await adminApi.updateCustomer(c.id, {
        blocked: !c.blocked,
        block_reason: !c.blocked ? 'Yönetici tarafından askıya alındı' : null,
      });
      load();
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const remove = (c: any) => {
    Alert.alert('Sil?', `${c.ad} ${c.soyad} silinecek`, [
      { text: 'Vazgeç' }, { text: 'Sil', style: 'destructive', onPress: async () => { try { await adminApi.deleteCustomer(c.id); load(); } catch (e: any) { Alert.alert('Hata', e.message); } } }
    ]);
  };

  const filterTabs: { key: typeof filtre; label: string; icon: any; count: number }[] = [
    { key: 'tum', label: 'Tümü', icon: 'list', count: counts.tum },
    { key: 'bireysel', label: 'Bireysel', icon: 'person', count: counts.bireysel },
    { key: 'kurumsal', label: 'Kurumsal', icon: 'business', count: counts.kurumsal },
    { key: 'engelli', label: 'Engelli', icon: 'ban', count: counts.engelli },
  ];

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <TextInput placeholder="Ara: isim, TC, firma, telefon..." placeholderTextColor={Colors.text.tertiary} style={[styles.input, { flex: 1 }]} value={q} onChangeText={setQ} />
        <Pressable onPress={() => { setEditing(null); setForm(emptyForm); setOpen(true); }} style={styles.fab} testID="add-customer">
          <Ionicons name="add" size={24} color="#fff" />
        </Pressable>
      </View>

      {/* Filter Tabs */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ flexDirection: 'row', gap: 6 }}>
          {filterTabs.map(ft => (
            <Pressable key={ft.key} onPress={() => setFiltre(ft.key)} style={[styles.miniBtn, filtre === ft.key && styles.miniBtnActive, { flexDirection: 'row', gap: 4 }]}>
              <Ionicons name={ft.icon} size={12} color={filtre === ft.key ? '#fff' : Colors.text.secondary} />
              <Text style={[styles.miniBtnText, filtre === ft.key && { color: '#fff' }]}>{ft.label} ({ft.count})</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>

      {loading ? <ActivityIndicator color={Colors.brand.primary} /> : list.length === 0 ? <Empty title="Müşteri yok" icon={<Ionicons name="people-outline" size={36} color={Colors.text.tertiary} />} /> : list.map(c => (
        <GlassCard key={c.id}>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{c.ad} {c.soyad}</Text>
                {c.tip === 'kurumsal' && (
                  <View style={{ paddingHorizontal: 6, paddingVertical: 2, backgroundColor: Colors.status.info, borderRadius: 4 }}>
                    <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900' }}>KURUMSAL</Text>
                  </View>
                )}
                {c.blocked && (
                  <View style={{ paddingHorizontal: 6, paddingVertical: 2, backgroundColor: Colors.status.error, borderRadius: 4 }}>
                    <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900' }}>ENGELLİ</Text>
                  </View>
                )}
              </View>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>TC: {c.tc_norm || c.tc_masked} • {c.telefon}</Text>
              {c.firma_adi ? <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 }}>🏢 {c.firma_adi}{c.vergi_no ? ` • VKN: ${c.vergi_no}` : ''}</Text> : null}
              {c.adres ? <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 }} numberOfLines={1}>📍 {c.adres}</Text> : null}
              <Text style={{ ...Typography.micro, color: Colors.brand.primaryLight, marginTop: 2 }}>Bakiye: {(c.bakiye || 0).toLocaleString('tr-TR')} ₺</Text>
            </View>
            <View style={{ flexDirection: 'row', gap: 4 }}>
              <Pressable onPress={() => toggleBlock(c)} style={[styles.iconBtn, c.blocked && { backgroundColor: Colors.status.error + '33' }]}><Ionicons name={c.blocked ? 'lock-open' : 'lock-closed'} size={16} color={c.blocked ? Colors.status.error : Colors.text.primary} /></Pressable>
              <Pressable onPress={() => { setEditing(c); setForm({ ad: c.ad, soyad: c.soyad, tc: c.tc_norm, telefon: c.telefon, email: c.email || '', notlar: c.notlar || '', adres: c.adres || '', tip: c.tip || 'bireysel', firma_adi: c.firma_adi || '', vergi_no: c.vergi_no || '', yetkili: c.yetkili || '' }); setOpen(true); }} style={styles.iconBtn}><Ionicons name="pencil" size={16} color={Colors.text.primary} /></Pressable>
              <Pressable onPress={() => remove(c)} style={styles.iconBtn}><Ionicons name="trash" size={16} color={Colors.status.error} /></Pressable>
            </View>
          </View>
        </GlassCard>
      ))}

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text style={styles.modalTitle}>{editing ? 'Müşteriyi Düzenle' : 'Yeni Müşteri'}</Text>
              <Pressable onPress={() => setOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <ScrollView style={{ maxHeight: 520 }}>
              {/* Tip seçimi */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 8, marginBottom: 6 }}>Müşteri Tipi</Text>
              <View style={{ flexDirection: 'row', gap: 6 }}>
                <Pressable onPress={() => setForm({ ...form, tip: 'bireysel' })} style={[styles.miniBtn, form.tip === 'bireysel' && styles.miniBtnActive, { flex: 1, flexDirection: 'row', gap: 4 }]}>
                  <Ionicons name="person" size={14} color={form.tip === 'bireysel' ? '#fff' : Colors.text.secondary} />
                  <Text style={[styles.miniBtnText, form.tip === 'bireysel' && { color: '#fff' }]}>BİREYSEL</Text>
                </Pressable>
                <Pressable onPress={() => setForm({ ...form, tip: 'kurumsal' })} style={[styles.miniBtn, form.tip === 'kurumsal' && styles.miniBtnActive, { flex: 1, flexDirection: 'row', gap: 4 }]}>
                  <Ionicons name="business" size={14} color={form.tip === 'kurumsal' ? '#fff' : Colors.text.secondary} />
                  <Text style={[styles.miniBtnText, form.tip === 'kurumsal' && { color: '#fff' }]}>KURUMSAL</Text>
                </Pressable>
              </View>

              <Field label={form.tip === 'kurumsal' ? 'Yetkili Ad' : 'Ad'} v={form.ad} on={(x) => setForm({ ...form, ad: x })} />
              <Field label={form.tip === 'kurumsal' ? 'Yetkili Soyad' : 'Soyad'} v={form.soyad} on={(x) => setForm({ ...form, soyad: x })} />
              <Field label="TC Kimlik No" v={form.tc} on={(x) => setForm({ ...form, tc: x.replace(/\D/g, '').slice(0, 11) })} kb="number-pad" />
              <Field label="Telefon" v={form.telefon} on={(x) => setForm({ ...form, telefon: x })} kb="phone-pad" />
              <Field label="E-posta (Ops.)" v={form.email} on={(x) => setForm({ ...form, email: x })} />
              <Field label="Adres" v={form.adres} on={(x) => setForm({ ...form, adres: x })} multi />

              {form.tip === 'kurumsal' && (
                <>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 4 }}>Kurumsal Bilgiler</Text>
                  <Field label="Firma Adı" v={form.firma_adi} on={(x) => setForm({ ...form, firma_adi: x })} />
                  <Field label="Vergi No" v={form.vergi_no} on={(x) => setForm({ ...form, vergi_no: x })} kb="number-pad" />
                </>
              )}

              <Field label="Notlar" v={form.notlar} on={(x) => setForm({ ...form, notlar: x })} multi />
            </ScrollView>
            <GlassButton title={editing ? 'KAYDET' : 'EKLE'} onPress={save} size="lg" />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// ===== Vehicles =====
function VehiclesTab() {
  // İlk render anında önceki tab'dan kalan veri varsa onu göster (donma engellenir)
  const [list, setList] = useState<any[]>(() => _adminCache.vehicles || []);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [form, setForm] = useState<any>({ plaka: '', marka: '', model: '', yil: 2024, renk: '', vites: 'Otomatik', yakit: 'Benzin', foto_url: '', fotograflar: [], gunluk_fiyat: 0, gunluk_km: 250, aciklama: '', manuel_durum: null, gunluk_fiyat_kademeleri: [], km_kademeleri: [], km_asim_fiyat: null, km_asim_kademeleri: [] });
  const [photoBusy, setPhotoBusy] = useState(false);

  const pickVehiclePhoto = async (source: 'camera' | 'library') => {
    try {
      let perm;
      if (source === 'camera') {
        perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) { Alert.alert('İzin Gerekli', 'Kamera izni verilmedi'); return; }
      } else {
        perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) { Alert.alert('İzin Gerekli', 'Galeri izni verilmedi'); return; }
      }
      const result = source === 'camera'
        ? await ImagePicker.launchCameraAsync({ quality: 0.55, base64: true, allowsEditing: true, aspect: [16, 10], mediaTypes: ['images'] })
        : await ImagePicker.launchImageLibraryAsync({ quality: 0.55, base64: true, allowsEditing: true, aspect: [16, 10], mediaTypes: ['images'] });
      if (result.canceled || !result.assets?.[0]) return;
      const b64 = result.assets[0].base64;
      if (!b64) { Alert.alert('Hata', 'Fotoğraf okunamadı'); return; }
      if (b64.length > 4 * 1024 * 1024) { Alert.alert('Hata', 'Fotoğraf çok büyük (~3MB). Daha küçük seçin.'); return; }
      setPhotoBusy(true);
      const dataUri = `data:image/jpeg;base64,${b64}`;
      // Tek foto: mevcut fotoğrafı değiştir
      setForm((f: any) => ({ ...f, fotograflar: [dataUri], foto_url: dataUri }));
    } catch (e: any) { Alert.alert('Hata', e?.message || 'Fotoğraf eklenemedi'); }
    finally { setPhotoBusy(false); }
  };

  const removeVehiclePhoto = () => {
    setForm((f: any) => ({ ...f, fotograflar: [], foto_url: '' }));
  };

  const load = useCallback(async () => { try { const data = await adminApi.vehicles(); _adminCache.vehicles = data; setList(data); } catch {} }, []);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Sıralamayı değiştir: index'i delta kadar kaydır (yukarı: delta=-1, aşağı: delta=+1)
  const move = useCallback(async (idx: number, delta: number) => {
    const newIdx = idx + delta;
    if (newIdx < 0 || newIdx >= list.length) return;
    // Anında UI güncelle (optimistik)
    const next = [...list];
    const [moved] = next.splice(idx, 1);
    next.splice(newIdx, 0, moved);
    // Yeni siralama değerleri (1, 2, 3, ...)
    const orders = next.map((v, i) => ({ id: v.id, siralama: i + 1 }));
    const withOrder = next.map((v, i) => ({ ...v, siralama: i + 1 }));
    setList(withOrder);
    _adminCache.vehicles = withOrder;
    try {
      await adminApi.reorderVehicles(orders);
    } catch (e: any) {
      // Hata olursa eski sıraya dön
      setList(list);
      _adminCache.vehicles = list;
      Alert.alert('Hata', e?.message || 'Sıralama kaydedilemedi');
    }
  }, [list]);

  const save = async () => {
    try {
      // Tarih TR formatından ISO'ya dönüştür (boş ise null)
      const sb = (form.sigorta_bitis_tr ?? '').trim();
      const mb = (form.muayene_bitis_tr ?? '').trim();
      // Geçici alanları temizleyip clean form oluştur
      const cleanForm: any = { ...form };
      delete cleanForm.sigorta_bitis_tr;
      delete cleanForm.muayene_bitis_tr;
      // Tarih validasyon + ISO
      if (form.sigorta_bitis_tr !== undefined) {
        if (sb === '') cleanForm.sigorta_bitis = null;
        else {
          const iso = trDateToIso(sb);
          if (!iso) { Alert.alert('Hata', 'Sigorta tarihi formatı GG.AA.YYYY (örn. 20.05.2026)'); return; }
          cleanForm.sigorta_bitis = iso;
        }
      }
      if (form.muayene_bitis_tr !== undefined) {
        if (mb === '') cleanForm.muayene_bitis = null;
        else {
          const iso = trDateToIso(mb);
          if (!iso) { Alert.alert('Hata', 'Muayene tarihi formatı GG.AA.YYYY (örn. 20.05.2026)'); return; }
          cleanForm.muayene_bitis = iso;
        }
      }

      if (editing) {
        // DELTA: sadece değişen alanları gönder. Büyük base64 fotoğraf array'i değişmediyse boşa upload edilmesin.
        const delta: any = {};
        const SKIP_KEYS = new Set(['id', 'created_at', 'durum', 'canli_km']); // backend tarafından yönetilen / read-only alanlar
        for (const k of Object.keys(cleanForm)) {
          if (SKIP_KEYS.has(k)) continue;
          if (!_deepEqual(cleanForm[k], editing[k])) {
            delta[k] = cleanForm[k];
          }
        }
        if (Object.keys(delta).length === 0) {
          // Hiçbir şey değişmemiş
          setOpen(false); setEditing(null);
          return;
        }
        await adminApi.updateVehicle(editing.id, delta);
      } else {
        await adminApi.createVehicle(cleanForm);
      }
      setOpen(false); setEditing(null);
      load();
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const setStatus = async (v: any, status: string | null) => {
    try { await adminApi.updateVehicle(v.id, { manuel_durum: status }); load(); } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const toggleMotorBlokaj = (v: any) => {
    const currentlyLocked = !!v.motor_blokaj_aktif || !!v.manuel_motor_blokaj;
    const willLock = !currentlyLocked;
    Alert.alert(
      willLock ? 'Motor Kilitle?' : 'Motor Aç?',
      `${v.plaka} ${v.marka} ${v.model} aracının motorunu ${willLock ? 'KİTLEMEK' : 'AÇMAK'} istediğinize emin misiniz?`,
      [
        { text: 'Vazgeç' },
        {
          text: willLock ? 'Kilitle' : 'Aç',
          style: willLock ? 'destructive' : 'default',
          onPress: async () => {
            try {
              const r = await adminApi.setMotorBlokaj(v.id, willLock);
              const botOk = (r as any)?.bot_responded;
              Alert.alert(
                'İşlem Tamamlandı',
                `${v.plaka}: Motor ${willLock ? 'kilitlendi' : 'açıldı'}.\n${botOk ? '✅ Bot komutu başarılı' : '⚠️ Bot endpoint henüz hazır değil (UI/DB güncellendi, kullanıcıya bildirim gitti)'}`
              );
              load();
            } catch (e: any) {
              Alert.alert('Hata', e.message);
            }
          },
        },
      ]
    );
  };

  const remove = (v: any) => {
    Alert.alert('Sil?', `${v.plaka} silinecek`, [{ text: 'Vazgeç' }, { text: 'Sil', style: 'destructive', onPress: async () => { await adminApi.deleteVehicle(v.id); load(); } }]);
  };

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <Pressable onPress={() => { setEditing(null); setForm({ plaka: '', marka: '', model: '', yil: 2024, renk: '', vites: 'Otomatik', yakit: 'Benzin', foto_url: '', gunluk_fiyat: 0, gunluk_km: 250, aciklama: '', manuel_durum: null, gunluk_fiyat_kademeleri: [], km_kademeleri: [], km_asim_fiyat: null, km_asim_kademeleri: [] }); setOpen(true); }} style={[styles.fab, { width: '100%', height: 48, borderRadius: Radius.pill, flexDirection: 'row', gap: 6 }]} testID="add-vehicle">
        <Ionicons name="add" size={20} color="#fff" />
        <Text style={{ color: '#fff', fontWeight: '700' }}>YENİ ARAÇ</Text>
      </Pressable>
      {list.map((v, idx) => {
        const wSigorta = daysUntil(v.sigorta_bitis);
        const wMuayene = daysUntil(v.muayene_bitis);
        const wYag = kmUntilService(v.canli_km ?? v.mevcut_km, v.sonraki_yag_bakim_km);
        const warns: { icon: any; label: string; color: string }[] = [];
        const sevColor = (s: 'red' | 'yellow' | null) => s === 'red' ? Colors.status.error : s === 'yellow' ? Colors.status.warning : '';
        if (wSigorta?.severity) warns.push({ icon: 'shield-checkmark-outline', label: `Sigorta ${wSigorta.days < 0 ? Math.abs(wSigorta.days) + 'g geçti' : wSigorta.days + 'g'}`, color: sevColor(wSigorta.severity) });
        if (wMuayene?.severity) warns.push({ icon: 'construct-outline', label: `Muayene ${wMuayene.days < 0 ? Math.abs(wMuayene.days) + 'g geçti' : wMuayene.days + 'g'}`, color: sevColor(wMuayene.severity) });
        if (wYag?.severity) warns.push({ icon: 'water-outline', label: wYag.kalan <= 0 ? `Yağ ${Math.abs(wYag.kalan).toLocaleString('tr-TR')} km geçti` : `Yağ ~${wYag.kalan.toLocaleString('tr-TR')} km`, color: sevColor(wYag.severity) });
        const isFirst = idx === 0;
        const isLast = idx === list.length - 1;
        return (
        <GlassCard key={v.id}>
          <View style={{ flexDirection: 'row', gap: Spacing.md }}>
            {/* Sıralama butonları */}
            <View style={{ justifyContent: 'center', alignItems: 'center', gap: 4 }}>
              <Pressable
                onPress={() => move(idx, -1)}
                disabled={isFirst}
                style={[styles.orderBtn, isFirst && { opacity: 0.3 }]}
                testID={`veh-up-${v.id}`}
              >
                <Ionicons name="chevron-up" size={16} color={Colors.text.primary} />
              </Pressable>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, fontWeight: '700' }}>{idx + 1}</Text>
              <Pressable
                onPress={() => move(idx, 1)}
                disabled={isLast}
                style={[styles.orderBtn, isLast && { opacity: 0.3 }]}
                testID={`veh-down-${v.id}`}
              >
                <Ionicons name="chevron-down" size={16} color={Colors.text.primary} />
              </Pressable>
            </View>
            {v.foto_url ? <Image source={{ uri: v.foto_url }} style={{ width: 60, height: 60, borderRadius: 8, backgroundColor: Colors.bg.surface2 }} /> : <View style={{ width: 60, height: 60, borderRadius: 8, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center' }}><Ionicons name="car-sport" size={28} color={Colors.text.tertiary} /></View>}
            <View style={{ flex: 1 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{v.marka} {v.model}</Text>
                <StatusBadge status={v.durum} />
              </View>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{v.plaka} • {v.gunluk_fiyat.toLocaleString('tr-TR')}₺/gün</Text>
              {(v.canli_km != null || v.motor_durumu) && (
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4, alignItems: 'center' }}>
                  {v.canli_km != null && (
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 3 }}>
                      <Ionicons name="speedometer-outline" size={12} color={Colors.brand.primary} />
                      <Text style={{ ...Typography.micro, color: Colors.text.primary, fontWeight: '700' }}>
                        {Number(v.canli_km).toLocaleString('tr-TR')} km
                      </Text>
                      {v.bot_son_guncelleme && (
                        <Text style={{ ...Typography.micro, color: '#22c55e', marginLeft: 2 }}>● LIVE</Text>
                      )}
                    </View>
                  )}
                  {v.motor_durumu && (
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 3 }}>
                      <Ionicons
                        name={v.motor_durumu === 'calisiyor' ? 'flash' : 'flash-off'}
                        size={12}
                        color={v.motor_durumu === 'calisiyor' ? Colors.status.success : Colors.text.tertiary}
                      />
                      <Text style={{ ...Typography.micro, color: v.motor_durumu === 'calisiyor' ? Colors.status.success : Colors.text.tertiary }}>
                        {v.motor_durumu === 'calisiyor' ? 'Kontak Açık' : 'Kontak Kapalı'}
                      </Text>
                    </View>
                  )}
                </View>
              )}
              {warns.length > 0 && (
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                  {warns.map((w, i) => (
                    <MaintWarning key={i} icon={w.icon} label={w.label} color={w.color} />
                  ))}
                </View>
              )}
              <View style={{ flexDirection: 'row', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                <Pressable onPress={() => setStatus(v, null)} style={[styles.miniBtn, !v.manuel_durum && styles.miniBtnActive]}><Text style={[styles.miniBtnText, !v.manuel_durum && { color: '#fff' }]}>Otomatik</Text></Pressable>
                <Pressable onPress={() => setStatus(v, 'musait')} style={[styles.miniBtn, v.manuel_durum === 'musait' && styles.miniBtnActive]}><Text style={[styles.miniBtnText, v.manuel_durum === 'musait' && { color: '#fff' }]}>Müsait</Text></Pressable>
                <Pressable onPress={() => setStatus(v, 'bakim')} style={[styles.miniBtn, v.manuel_durum === 'bakim' && styles.miniBtnActive]}><Text style={[styles.miniBtnText, v.manuel_durum === 'bakim' && { color: '#fff' }]}>Bakım</Text></Pressable>
                <Pressable
                  onPress={() => toggleMotorBlokaj(v)}
                  style={[
                    styles.miniBtn,
                    (v.motor_blokaj_aktif || v.manuel_motor_blokaj) ? { backgroundColor: Colors.status.error, borderColor: Colors.status.error } : { backgroundColor: 'rgba(34,197,94,0.15)', borderColor: 'rgba(34,197,94,0.4)' },
                  ]}
                  testID={`motor-blokaj-${v.id}`}
                >
                  <Ionicons
                    name={(v.motor_blokaj_aktif || v.manuel_motor_blokaj) ? 'lock-closed' : 'lock-open'}
                    size={12}
                    color={(v.motor_blokaj_aktif || v.manuel_motor_blokaj) ? '#fff' : '#22c55e'}
                  />
                  <Text style={[styles.miniBtnText, { marginLeft: 3 }, (v.motor_blokaj_aktif || v.manuel_motor_blokaj) ? { color: '#fff' } : { color: '#22c55e' }]}>
                    {(v.motor_blokaj_aktif || v.manuel_motor_blokaj) ? 'Motor Kilitli' : 'Motor Açık'}
                  </Text>
                </Pressable>
                <Pressable onPress={() => { setEditing(v); setForm({ ...v, mevcut_km: v.mevcut_km ?? v.canli_km ?? null, sigorta_bitis_tr: isoToTrDate(v.sigorta_bitis), muayene_bitis_tr: isoToTrDate(v.muayene_bitis) }); setOpen(true); }} style={styles.iconBtn}><Ionicons name="pencil" size={14} color={Colors.text.primary} /></Pressable>
                <Pressable onPress={() => remove(v)} style={styles.iconBtn}><Ionicons name="trash" size={14} color={Colors.status.error} /></Pressable>
              </View>
            </View>
          </View>
        </GlassCard>
        );
      })}

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={styles.modalTitle}>{editing ? 'Aracı Düzenle' : 'Yeni Araç'}</Text>
              <Pressable onPress={() => setOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <ScrollView style={{ maxHeight: 500 }}>
              <Field label="Plaka" v={form.plaka} on={(x) => setForm({ ...form, plaka: x.toUpperCase() })} />
              <Field label="Marka" v={form.marka} on={(x) => setForm({ ...form, marka: x })} />
              <Field label="Model" v={form.model} on={(x) => setForm({ ...form, model: x })} />
              <Field label="Yıl" v={String(form.yil)} on={(x) => setForm({ ...form, yil: parseInt(x.replace(/\D/g, '') || '0', 10) })} kb="number-pad" />
              <Field label="Renk" v={form.renk} on={(x) => setForm({ ...form, renk: x })} />
              <Field label="Vites" v={form.vites} on={(x) => setForm({ ...form, vites: x })} />
              <Field label="Yakıt" v={form.yakit} on={(x) => setForm({ ...form, yakit: x })} />
              <Field label="Günlük Fiyat (₺) — Varsayılan" v={String(form.gunluk_fiyat)} on={(x) => setForm({ ...form, gunluk_fiyat: parseFloat(x.replace(/[^\d.]/g, '') || '0') })} kb="decimal-pad" />

              <View style={{ marginTop: 12, padding: Spacing.md, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 4 }}>💵 Günlük Fiyat Kademesi (Süreye Göre)</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginBottom: 8 }}>
                  Örn: 1-7 gün → 2500₺/gün, 8-14 gün → 2000₺/gün. Boş bırakılırsa yukarıdaki varsayılan tüm sürelere uygulanır. Uzatma yapıldığında yeni günler, yeni toplam gün için geçerli kademe fiyatından hesaplanır.
                </Text>
                <PriceBracketEditor
                  rows={form.gunluk_fiyat_kademeleri || []}
                  onChange={(rows) => setForm({ ...form, gunluk_fiyat_kademeleri: rows })}
                />
              </View>

              <Field label="Varsayılan Günlük KM Limiti" v={String(form.gunluk_km)} on={(x) => setForm({ ...form, gunluk_km: parseInt(x.replace(/\D/g, '') || '0', 10) })} kb="number-pad" />

              <View style={{ marginTop: 12, padding: Spacing.md, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 4 }}>📏 Dinamik Günlük KM Limiti (Süreye Göre)</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginBottom: 8 }}>
                  Örn: 1-7 gün → 250 km/gün, 8-30 gün → 120 km/gün. Boş bırakılırsa yukarıdaki varsayılan tüm sürelere uygulanır.
                </Text>
                <KmBracketEditor
                  rows={form.km_kademeleri || []}
                  onChange={(rows) => setForm({ ...form, km_kademeleri: rows })}
                />
              </View>

              <View style={{ marginTop: 12, padding: Spacing.md, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 4 }}>🛣️ KM Aşım Ücreti (₺/km)</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginBottom: 8 }}>
                  Bu araç için ek KM satın alma fiyatı. Kademe tanımlanmadıysa aşağıdaki varsayılan tüm sürelere uygulanır.
                </Text>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginBottom: 4 }}>Varsayılan</Text>
                <TextInput
                  value={form.km_asim_fiyat == null ? '' : String(form.km_asim_fiyat)}
                  onChangeText={(x) => {
                    const clean = x.replace(/[^\d.]/g, '');
                    setForm({ ...form, km_asim_fiyat: clean === '' ? null : parseFloat(clean) });
                  }}
                  placeholder="örn. 12"
                  placeholderTextColor={Colors.text.tertiary}
                  keyboardType="decimal-pad"
                  style={styles.input}
                />
                <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 4 }}>Süreye Göre Kademe (Opsiyonel)</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginBottom: 6, fontStyle: 'italic' }}>
                  Örn: 1-7 gün → 12₺/km, 8+ gün → 10₺/km. Müşterinin toplam kira günü için geçerli kademe uygulanır.
                </Text>
                <KmAsimBracketEditor
                  rows={form.km_asim_kademeleri || []}
                  onChange={(rows) => setForm({ ...form, km_asim_kademeleri: rows })}
                />
              </View>

              {/* Bakım & Yasal Takip */}
              <View style={{ marginTop: 12, padding: Spacing.md, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 4 }}>🛡️ Bakım & Yasal Takip</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginBottom: 8 }}>
                  Sigorta, muayene bitiş tarihleri ve yağ bakım KM'si. Tarihler GG.AA.YYYY formatında (örn. 20.05.2026). Yaklaşan tarihler/KM'ler liste kartında uyarı ikonu olarak gösterilir.
                </Text>
                <Field
                  label="🛡️ Sigorta Bitiş (örn. 20.05.2026)"
                  v={form.sigorta_bitis_tr ?? isoToTrDate(form.sigorta_bitis)}
                  on={(x) => setForm({ ...form, sigorta_bitis_tr: maskTrDate(x) })}
                  kb="number-pad"
                />
                <Field
                  label="🔧 Muayene Bitiş (örn. 20.05.2026)"
                  v={form.muayene_bitis_tr ?? isoToTrDate(form.muayene_bitis)}
                  on={(x) => setForm({ ...form, muayene_bitis_tr: maskTrDate(x) })}
                  kb="number-pad"
                />
                <Field label="🛢️ Sonraki Yağ Bakım KM (örn. 75000)" v={form.sonraki_yag_bakim_km == null ? '' : String(form.sonraki_yag_bakim_km)} on={(x) => { const c = x.replace(/\D/g, ''); setForm({ ...form, sonraki_yag_bakim_km: c === '' ? null : parseInt(c, 10) }); }} kb="number-pad" />
                <Field label="📍 Mevcut KM (GPS bot offline ise manuel girin — bot canlıyken otomatik dolar)" v={form.mevcut_km == null ? '' : String(form.mevcut_km)} on={(x) => { const c = x.replace(/\D/g, ''); setForm({ ...form, mevcut_km: c === '' ? null : parseInt(c, 10) }); }} kb="number-pad" />
                <Field label="🚨 Hız Limiti (km/h) — Aşılırsa müşteriye ve admin'e push bildirim. Boş = 120 (varsayılan)" v={form.hiz_limit == null ? '' : String(form.hiz_limit)} on={(x) => { const c = x.replace(/\D/g, ''); setForm({ ...form, hiz_limit: c === '' ? null : parseInt(c, 10) }); }} kb="number-pad" />
              </View>

              {/* Tek Araç Fotoğrafı (Kamera + Galeri) */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12 }}>Araç Fotoğrafı</Text>
              <View style={{ flexDirection: 'row', gap: 8, marginTop: 6 }}>
                <Pressable onPress={() => pickVehiclePhoto('camera')} disabled={photoBusy} style={[styles.fab, { flex: 1, height: 40, borderRadius: Radius.md, flexDirection: 'row', gap: 6, opacity: photoBusy ? 0.5 : 1 }]}>
                  <Ionicons name="camera" size={16} color="#fff" />
                  <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12 }}>KAMERA</Text>
                </Pressable>
                <Pressable onPress={() => pickVehiclePhoto('library')} disabled={photoBusy} style={[styles.fab, { flex: 1, height: 40, borderRadius: Radius.md, flexDirection: 'row', gap: 6, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, opacity: photoBusy ? 0.5 : 1 }]}>
                  <Ionicons name="images" size={16} color={Colors.text.primary} />
                  <Text style={{ color: Colors.text.primary, fontWeight: '700', fontSize: 12 }}>GALERİ</Text>
                </Pressable>
              </View>
              {photoBusy && <ActivityIndicator color={Colors.brand.primary} style={{ marginTop: 6 }} />}
              {!!form.foto_url && (
                <View style={{ marginTop: 8, position: 'relative', alignSelf: 'flex-start' }}>
                  <Image source={{ uri: form.foto_url }} style={{ width: 140, height: 90, borderRadius: Radius.sm, backgroundColor: Colors.bg.surface2 }} />
                  <Pressable onPress={removeVehiclePhoto} style={{ position: 'absolute', top: 4, right: 4, width: 26, height: 26, borderRadius: 13, backgroundColor: 'rgba(0,0,0,0.7)', alignItems: 'center', justifyContent: 'center' }}>
                    <Ionicons name="close" size={14} color={Colors.status.error} />
                  </Pressable>
                </View>
              )}
              <Field label="Açıklama" v={form.aciklama} on={(x) => setForm({ ...form, aciklama: x })} multi />
            </ScrollView>
            <GlassButton title={editing ? 'KAYDET' : 'EKLE'} onPress={save} size="lg" />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// ===== Reservations =====
function ReservationsTab() {
  // Önceki ziyaretten kalan veri varsa hemen göster (lag/donma engellenir)
  const [list, setList] = useState<any[]>(() => _adminCache.reservations || []);
  const [filter, setFilter] = useState<string>('');
  const [editOpen, setEditOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const [editForm, setEditForm] = useState<any>({});
  // Teslim Fotoğrafları
  const [photoOpen, setPhotoOpen] = useState(false);
  const [photoRez, setPhotoRez] = useState<any>(null);
  const [photos, setPhotos] = useState<any[]>([]);
  const [photoLoading, setPhotoLoading] = useState(false);
  const [photoCaption, setPhotoCaption] = useState('');
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  // Boş Araçlar / Müsait Araçlar paneli
  const [vehicles, setVehicles] = useState<any[]>(() => _adminCache.vehicles || []);
  const [showFree, setShowFree] = useState(false);
  // Manuel Rezervasyon
  const [manualOpen, setManualOpen] = useState(false);
  const [customers, setCustomers] = useState<any[]>(() => _adminCache.customers || []);
  const [manualForm, setManualForm] = useState<any>({
    mode: 'existing' as 'existing' | 'new',
    customer_id: '',
    new_ad: '', new_soyad: '', new_tc: '', new_telefon: '',
    customer_search: '',
    vehicle_id: '',
    baslangic_tarihi_tr: '',
    bitis_tarihi_tr: '',
    telefon: '',
    odeme_durumu: 'beklemede',
    iskonto_yuzde: 0,
    selected_services: {} as Record<string, number>, // service_id -> adet
    paket_km_override: '',
    toplam_tutar_override: '',
    odenen_ucret: '',
  });
  const [manualServices, setManualServices] = useState<any[]>([]);
  const [manualServicesLoading, setManualServicesLoading] = useState(false);

  // Araç değiştiğinde o araca uygun hizmetleri yükle
  useEffect(() => {
    if (!manualOpen || !manualForm.vehicle_id) { setManualServices([]); return; }
    let cancelled = false;
    (async () => {
      setManualServicesLoading(true);
      try {
        const allSvcs = await adminApi.services();
        if (cancelled) return;
        // Araca uygun hizmetleri filtrele: aktif olanlar ve (arac_ids boşsa hepsi için VEYA bu araç idsi listede)
        const filtered = (allSvcs || []).filter((s: any) => {
          if (!s.aktif) return false;
          if (!s.arac_ids || s.arac_ids.length === 0) return true;
          return s.arac_ids.includes(manualForm.vehicle_id);
        }).sort((a: any, b: any) => (a.siralama || 0) - (b.siralama || 0));
        setManualServices(filtered);
        // Zorunlu hizmetleri otomatik seçili yap
        const auto: Record<string, number> = { ...(manualForm.selected_services || {}) };
        filtered.forEach((s: any) => {
          if (s.zorunlu && !auto[s.id]) auto[s.id] = 1;
        });
        setManualForm((f: any) => ({ ...f, selected_services: auto }));
      } catch { if (!cancelled) setManualServices([]); }
      finally { if (!cancelled) setManualServicesLoading(false); }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manualOpen, manualForm.vehicle_id]);

  const load = useCallback(async () => {
    try {
      const data = await adminApi.reservations(filter || undefined);
      _adminCache.reservations = data;
      setList(data);
    } catch {}
    try {
      const [vs, cs] = await Promise.all([adminApi.vehicles(), adminApi.customers()]);
      _adminCache.vehicles = vs;
      _adminCache.customers = cs;
      setVehicles(vs); setCustomers(cs);
    } catch {}
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  const submitManual = async () => {
    try {
      let cid = manualForm.customer_id;
      // Yeni müşteri ise önce oluştur
      if (manualForm.mode === 'new') {
        if (!manualForm.new_ad || !manualForm.new_soyad || !manualForm.new_tc) {
          Alert.alert('Hata', 'Ad, soyad ve TC zorunlu');
          return;
        }
        if (!/^\d{11}$/.test(manualForm.new_tc.trim())) {
          Alert.alert('Hata', 'TC 11 haneli olmalı');
          return;
        }
        try {
          const cust = await adminApi.createCustomer({
            ad: manualForm.new_ad.trim(),
            soyad: manualForm.new_soyad.trim(),
            tc: manualForm.new_tc.trim(),
            telefon: manualForm.new_telefon.trim() || null,
            tip: 'bireysel',
          });
          cid = cust.id;
        } catch (e: any) { Alert.alert('Hata', 'Müşteri oluşturma: ' + e.message); return; }
      }
      if (!cid) { Alert.alert('Hata', 'Müşteri seçin/oluşturun'); return; }
      if (!manualForm.vehicle_id) { Alert.alert('Hata', 'Araç seçin'); return; }
      const bIso = trDtToIso(manualForm.baslangic_tarihi_tr);
      const eIso = trDtToIso(manualForm.bitis_tarihi_tr);
      if (!bIso || !eIso) { Alert.alert('Hata', 'Tarih formatı: 07.11.1992 19:00'); return; }
      const payload: any = {
        customer_id: cid,
        vehicle_id: manualForm.vehicle_id,
        baslangic_tarihi: bIso,
        bitis_tarihi: eIso,
        telefon: manualForm.telefon || (manualForm.mode === 'new' ? manualForm.new_telefon : ''),
        secilen_hizmetler: Object.entries(manualForm.selected_services || {})
          .filter(([_, adet]) => Number(adet) > 0)
          .map(([service_id, adet]) => ({ service_id, adet: Number(adet) })),
        odeme_durumu: manualForm.odeme_durumu,
        iskonto_yuzde: parseFloat(String(manualForm.iskonto_yuzde)) || 0,
      };
      // Opsiyonel override'lar
      const tt = parseFloat(String(manualForm.toplam_tutar_override || '').replace(',', '.'));
      if (!isNaN(tt) && tt >= 0) payload.toplam_tutar_override = tt;
      const pkm = parseInt(String(manualForm.paket_km_override || ''), 10);
      if (!isNaN(pkm) && pkm >= 0) payload.paket_km_override = pkm;
      const od = parseFloat(String(manualForm.odenen_ucret || '').replace(',', '.'));
      if (!isNaN(od) && od > 0) payload.odenen_ucret = od;

      await adminApi.manualReservation(payload);
      setManualOpen(false);
      setManualForm({ mode: 'existing', customer_id: '', new_ad: '', new_soyad: '', new_tc: '', new_telefon: '', customer_search: '', vehicle_id: '', baslangic_tarihi_tr: '', bitis_tarihi_tr: '', telefon: '', odeme_durumu: 'beklemede', iskonto_yuzde: 0, selected_services: {}, paket_km_override: '', toplam_tutar_override: '', odenen_ucret: '' });
      setManualServices([]);
      load();
      Alert.alert('OK', 'Rezervasyon oluşturuldu. Müşteriye bildirim gönderildi.');
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const filteredManualCustomers = customers.filter((c: any) => {
    const q = (manualForm.customer_search || '').toLowerCase().trim();
    if (!q) return true;
    return (
      (c.ad || '').toLowerCase().includes(q) ||
      (c.soyad || '').toLowerCase().includes(q) ||
      (c.telefon || '').toLowerCase().includes(q) ||
      (c.tc_norm || c.tc || '').toLowerCase().includes(q)
    );
  });

  const freeVehicles = vehicles.filter(v => v.durum === 'musait');

  const setStatus = async (r: any, durum: string) => {
    try { await adminApi.setReservationStatus(r.id, durum); load(); } catch (e: any) { Alert.alert('Hata', e.message); }
  };
  const setPay = async (r: any, p: string) => {
    try { await adminApi.setPaymentStatus(r.id, p); load(); } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const openEdit = (r: any) => {
    setEditing(r);
    setEditForm({
      // TR datetime format: "07.11.1992 19:00"
      baslangic_tarihi_tr: isoToTrDt(r.baslangic_tarihi),
      bitis_tarihi_tr: isoToTrDt(r.bitis_tarihi),
      telefon: r.telefon || '',
      durum: r.durum,
      odenen_ucret: String(r.odenen_ucret ?? 0),
      toplam_tutar: String(r.toplam_tutar ?? 0),
      paket_km: String(r.paket_km ?? 0),
      alis_km: String(r.alis_km ?? ''),
      odeme_durumu: r.odeme_durumu || 'beklemede',
      notlar: r.notlar || '',
      musteri_ad: r.musteri?.ad || '',
      musteri_soyad: r.musteri?.soyad || '',
      customer_id: r.customer_id,
    });
    setEditOpen(true);
  };

  const saveEdit = async () => {
    if (!editing) return;
    try {
      // Tarih payload
      const payload: any = {};
      if (editForm.baslangic_tarihi_tr) {
        const iso = trDtToIso(editForm.baslangic_tarihi_tr);
        if (!iso) { Alert.alert('Hata', 'Başlangıç tarihi formatı: 07.11.1992 19:00'); return; }
        payload.baslangic_tarihi = iso;
      }
      if (editForm.bitis_tarihi_tr) {
        const iso = trDtToIso(editForm.bitis_tarihi_tr);
        if (!iso) { Alert.alert('Hata', 'Bitiş tarihi formatı: 07.11.1992 19:00'); return; }
        payload.bitis_tarihi = iso;
      }
      if (editForm.telefon) payload.telefon = editForm.telefon;
      if (editForm.durum) payload.durum = editForm.durum;
      const odenen = parseFloat(editForm.odenen_ucret); if (!isNaN(odenen)) payload.odenen_ucret = odenen;
      const toplam = parseFloat(editForm.toplam_tutar); if (!isNaN(toplam)) payload.toplam_tutar = toplam;
      const pkm = parseInt(editForm.paket_km, 10); if (!isNaN(pkm)) payload.paket_km = pkm;
      if (editForm.alis_km !== '') { const akm = parseInt(editForm.alis_km, 10); if (!isNaN(akm)) payload.alis_km = akm; }
      if (editForm.odeme_durumu) payload.odeme_durumu = editForm.odeme_durumu;
      if (editForm.notlar !== undefined) payload.notlar = editForm.notlar;

      // Müşteri ad/soyad güncellendi mi? — ayrı customer endpoint'i ile güncelle
      const adChanged = (editForm.musteri_ad || '').trim() !== (editing.musteri?.ad || '').trim();
      const soyChanged = (editForm.musteri_soyad || '').trim() !== (editing.musteri?.soyad || '').trim();
      if ((adChanged || soyChanged) && editForm.customer_id) {
        try {
          await adminApi.updateCustomer(editForm.customer_id, {
            ad: (editForm.musteri_ad || '').trim(),
            soyad: (editForm.musteri_soyad || '').trim(),
          });
        } catch (e: any) {
          Alert.alert('Uyarı', 'Müşteri ad/soyad güncellenemedi: ' + (e?.message || ''));
        }
      }

      await adminApi.editReservation(editing.id, payload);
      setEditOpen(false); setEditing(null);
      load();
      Alert.alert('OK', 'Rezervasyon güncellendi');
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const remove = (r: any) => {
    Alert.alert(
      'Rezervasyonu Sil',
      `${r.musteri?.ad || ''} ${r.musteri?.soyad || ''} - ${r.vehicle_snapshot?.plaka || ''}\n\nÖdenen tutar (${(r.odenen_ucret || 0).toLocaleString('tr-TR')} ₺) müşteri bakiyesine iade edilsin mi?`,
      [
        { text: 'Vazgeç', style: 'cancel' },
        { text: 'İADE ETMEDEN SİL', style: 'destructive', onPress: async () => {
          try { await adminApi.deleteReservation(r.id, false); load(); Alert.alert('OK', 'Rezervasyon silindi'); }
          catch (e: any) { Alert.alert('Hata', e.message); }
        }},
        { text: 'İADE EDEREK SİL', onPress: async () => {
          try { await adminApi.deleteReservation(r.id, true); load(); Alert.alert('OK', 'Rezervasyon silindi, bakiye iade edildi'); }
          catch (e: any) { Alert.alert('Hata', e.message); }
        }},
      ]
    );
  };

  // ===== Teslim Fotoğrafları =====
  const openPhotos = async (r: any) => {
    setPhotoRez(r);
    setPhotoOpen(true);
    setPhotoCaption('');
    await reloadPhotos(r.id);
  };

  const reloadPhotos = async (rid: string) => {
    setPhotoLoading(true);
    try { setPhotos(await adminApi.listTeslimFoto(rid)); }
    catch (e: any) { Alert.alert('Hata', e.message); }
    finally { setPhotoLoading(false); }
  };

  const pickAndUpload = async (source: 'camera' | 'library') => {
    if (!photoRez) return;
    try {
      let perm;
      if (source === 'camera') {
        perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) { Alert.alert('İzin Gerekli', 'Kamera izni verilmedi'); return; }
      } else {
        perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (!perm.granted) { Alert.alert('İzin Gerekli', 'Galeri izni verilmedi'); return; }
      }
      const result = source === 'camera'
        ? await ImagePicker.launchCameraAsync({ quality: 0.6, base64: true, allowsEditing: false, mediaTypes: ['images'] })
        : await ImagePicker.launchImageLibraryAsync({ quality: 0.6, base64: true, allowsEditing: false, mediaTypes: ['images'] });
      if (result.canceled || !result.assets?.[0]) return;
      const asset = result.assets[0];
      const b64 = asset.base64;
      if (!b64) { Alert.alert('Hata', 'Fotoğraf okunamadı'); return; }
      // Boyut kontrol (kabaca)
      if (b64.length > 8 * 1024 * 1024) { Alert.alert('Hata', 'Fotoğraf çok büyük. Lütfen daha düşük kalite seçin.'); return; }
      const dataUri = `data:image/jpeg;base64,${b64}`;
      setPhotoLoading(true);
      try {
        await adminApi.addTeslimFoto(photoRez.id, dataUri, photoCaption);
        setPhotoCaption('');
        await reloadPhotos(photoRez.id);
      } catch (e: any) { Alert.alert('Hata', e.message); }
      finally { setPhotoLoading(false); }
    } catch (e: any) { Alert.alert('Hata', e?.message || 'Fotoğraf eklenemedi'); }
  };

  const removePhoto = (fid: string) => {
    if (!photoRez) return;
    Alert.alert('Fotoğraf Sil?', 'Bu fotoğraf silinecek', [
      { text: 'Vazgeç' },
      { text: 'Sil', style: 'destructive', onPress: async () => {
        try { await adminApi.deleteTeslimFoto(photoRez.id, fid); await reloadPhotos(photoRez.id); }
        catch (e: any) { Alert.alert('Hata', e.message); }
      }},
    ]);
  };

  const fmtTr = (iso?: string) => iso ? new Date(iso).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—';

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      {/* Üst butonlar: Manuel Rezervasyon + Boş Araçlar */}
      <View style={{ flexDirection: 'row', gap: 8 }}>
        <Pressable onPress={() => setManualOpen(true)} style={[styles.fab, { flex: 1, height: 44, borderRadius: Radius.pill, flexDirection: 'row', gap: 6 }]}>
          <Ionicons name="add-circle" size={18} color="#fff" />
          <Text style={{ color: '#fff', fontWeight: '700', fontSize: 12 }}>MANUEL REZERVASYON</Text>
        </Pressable>
        <Pressable onPress={() => setShowFree(s => !s)} style={[styles.fab, { flex: 1, height: 44, borderRadius: Radius.pill, flexDirection: 'row', gap: 6, backgroundColor: showFree ? Colors.status.success : Colors.bg.surface2, borderWidth: 1, borderColor: showFree ? Colors.status.success : Colors.border.base }]}>
          <Ionicons name="car-sport" size={18} color={showFree ? '#fff' : Colors.text.primary} />
          <Text style={{ color: showFree ? '#fff' : Colors.text.primary, fontWeight: '700', fontSize: 12 }}>BOŞ ARAÇLAR ({freeVehicles.length})</Text>
        </Pressable>
      </View>

      {/* Boş Araçlar Listesi (toggle) */}
      {showFree && (
        <GlassCard>
          <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 8 }}>🟢 Şu an müsait olan araçlar</Text>
          {freeVehicles.length === 0 ? (
            <Text style={{ ...Typography.caption, color: Colors.text.tertiary }}>Boş araç yok</Text>
          ) : freeVehicles.map(v => (
            <View key={v.id} style={{ flexDirection: 'row', alignItems: 'center', paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: Colors.border.base, gap: 8 }}>
              {v.foto_url ? <Image source={{ uri: v.foto_url }} style={{ width: 40, height: 40, borderRadius: 6, backgroundColor: Colors.bg.surface2 }} /> : <View style={{ width: 40, height: 40, borderRadius: 6, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center' }}><Ionicons name="car-sport" size={20} color={Colors.text.tertiary} /></View>}
              <View style={{ flex: 1 }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{v.plaka}</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{v.marka} {v.model} • {v.gunluk_fiyat.toLocaleString('tr-TR')}₺/gün</Text>
              </View>
              <Pressable onPress={() => { setManualForm({ ...manualForm, vehicle_id: v.id }); setManualOpen(true); }} style={[styles.miniBtn, styles.miniBtnActive]}>
                <Text style={{ color: '#fff', fontSize: 10, fontWeight: '700' }}>REZERVE ET</Text>
              </Pressable>
            </View>
          ))}
        </GlassCard>
      )}

      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ flexDirection: 'row', gap: 6 }}>
          {['', 'beklemede', 'onaylandi', 'aktif', 'tamamlandi', 'iptal'].map(f => (
            <Pressable key={f} onPress={() => setFilter(f)} style={[styles.miniBtn, filter === f && styles.miniBtnActive]}>
              <Text style={[styles.miniBtnText, filter === f && { color: '#fff' }]}>{f || 'Tümü'}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>

      {list.length === 0 ? <Empty title="Rezervasyon yok" /> : list.map(r => {
        const kalan = Math.max(0, (r.toplam_tutar || 0) - (r.odenen_ucret || 0));
        return (
          <GlassCard key={r.id} highlight={r.durum === 'beklemede'} style={{ padding: 0, overflow: 'hidden' }}>
            {/* Üst Bant — Durum + Plaka */}
            <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, paddingHorizontal: 12, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: Colors.border.base }}>
              <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <View style={{ width: 32, height: 32, borderRadius: 16, backgroundColor: Colors.brand.primary + '22', alignItems: 'center', justifyContent: 'center' }}>
                  <Ionicons name="person" size={16} color={Colors.brand.primary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }} numberOfLines={1}>{r.musteri?.ad || ''} {r.musteri?.soyad || ''}</Text>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary }} numberOfLines={1}>{r.musteri?.telefon || r.telefon || '—'}</Text>
                </View>
              </View>
              <StatusBadge status={r.durum} />
            </View>

            {/* Orta — Araç bilgileri */}
            <View style={{ flexDirection: 'row', padding: 12, gap: 10, alignItems: 'center' }}>
              {r.vehicle_snapshot?.foto_url ? (
                <Image source={{ uri: r.vehicle_snapshot.foto_url }} style={{ width: 64, height: 48, borderRadius: 6, backgroundColor: Colors.bg.surface2 }} />
              ) : (
                <View style={{ width: 64, height: 48, borderRadius: 6, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center' }}><Ionicons name="car-sport" size={22} color={Colors.text.tertiary} /></View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }} numberOfLines={1}>{r.vehicle_snapshot.marka} {r.vehicle_snapshot.model}</Text>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 }}>
                  <View style={{ paddingHorizontal: 6, paddingVertical: 1, backgroundColor: Colors.bg.surface, borderRadius: 4, borderWidth: 1, borderColor: Colors.border.base }}>
                    <Text style={{ ...Typography.micro, color: Colors.text.primary, fontWeight: '700' }}>{r.vehicle_snapshot.plaka}</Text>
                  </View>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{r.gun_sayisi} gün</Text>
                </View>
              </View>
            </View>

            {/* Tarihler */}
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 12, paddingBottom: 8 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                <Ionicons name="calendar" size={12} color={Colors.brand.primary} />
                <Text style={{ ...Typography.micro, color: Colors.text.primary, fontWeight: '600' }}>{fmtTr(r.baslangic_tarihi)}</Text>
              </View>
              <Ionicons name="arrow-forward" size={12} color={Colors.text.tertiary} />
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                <Ionicons name="calendar-outline" size={12} color={Colors.brand.primary} />
                <Text style={{ ...Typography.micro, color: Colors.text.primary, fontWeight: '600' }}>{fmtTr(r.bitis_tarihi)}</Text>
              </View>
            </View>

            {/* KM bilgileri — Toplam KM Hakkı + Kullanılan (canlı bot senkron) + Kalan */}
            {!!r.paket_km && (() => {
              const kullan = Number((r as any).kullanilan_km ?? 0);
              const paket = Number(r.paket_km ?? 0) + Number((r as any).ek_km_satin ?? 0);
              const kalan = paket - kullan;
              const kalanColor = kalan <= 0 ? Colors.status.error : kalan <= 50 ? Colors.status.warning : '#22c55e';
              const motorLocked = !!(r as any).motor_kilitli;
              return (
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', paddingHorizontal: 12, paddingBottom: 10, gap: 6 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: Colors.brand.primary + '15', borderWidth: 1, borderColor: Colors.brand.primary + '44' }}>
                    <Ionicons name="speedometer" size={11} color={Colors.brand.primary} />
                    <Text style={{ ...Typography.micro, color: Colors.brand.primary, fontWeight: '700' }}>Paket: {paket.toLocaleString('tr-TR')} km</Text>
                  </View>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base }}>
                    <Ionicons name="navigate" size={11} color={Colors.text.secondary} />
                    <Text style={{ ...Typography.micro, color: Colors.text.primary, fontWeight: '600' }}>Kullanılan: {kullan.toLocaleString('tr-TR')} km</Text>
                  </View>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: kalanColor + '20', borderWidth: 1, borderColor: kalanColor + '66' }}>
                    <Ionicons name={kalan <= 0 ? 'alert-circle' : kalan <= 50 ? 'warning' : 'checkmark-circle'} size={11} color={kalanColor} />
                    <Text style={{ ...Typography.micro, color: kalanColor, fontWeight: '700' }}>Kalan: {kalan.toLocaleString('tr-TR')} km</Text>
                  </View>
                  {motorLocked && (
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 6, backgroundColor: Colors.status.error + '20', borderWidth: 1, borderColor: Colors.status.error + '66' }}>
                      <Ionicons name="lock-closed" size={11} color={Colors.status.error} />
                      <Text style={{ ...Typography.micro, color: Colors.status.error, fontWeight: '700' }}>Motor Kilitli</Text>
                    </View>
                  )}
                </View>
              );
            })()}

            {/* Ödeme satırı */}
            <View style={{ flexDirection: 'row', backgroundColor: Colors.bg.surface2, paddingHorizontal: 12, paddingVertical: 8, gap: 8 }}>
              <View style={{ flex: 1 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>Toplam</Text>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{(r.toplam_tutar || 0).toLocaleString('tr-TR')}₺</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>Ödenen</Text>
                <Text style={{ ...Typography.bodyBold, color: Colors.status.success }}>{(r.odenen_ucret || 0).toLocaleString('tr-TR')}₺</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>Kalan</Text>
                <Text style={{ ...Typography.bodyBold, color: kalan > 0 ? Colors.status.warning : Colors.text.tertiary }}>{kalan.toLocaleString('tr-TR')}₺</Text>
              </View>
            </View>

            {/* Aksiyonlar */}
            <View style={{ flexDirection: 'row', gap: 6, padding: 10, flexWrap: 'wrap' }}>
              {r.durum === 'beklemede' && <Pressable onPress={() => setStatus(r, 'onaylandi')} style={[styles.miniBtn, { backgroundColor: Colors.status.info }]}><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>ONAYLA</Text></Pressable>}
              {r.durum === 'onaylandi' && <Pressable onPress={() => setStatus(r, 'aktif')} style={[styles.miniBtn, { backgroundColor: Colors.status.success }]}><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>AKTİF YAP</Text></Pressable>}
              {r.durum === 'aktif' && <Pressable onPress={() => setStatus(r, 'tamamlandi')} style={[styles.miniBtn, { backgroundColor: Colors.text.secondary }]}><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>TAMAMLA</Text></Pressable>}
              {r.durum !== 'iptal' && r.durum !== 'tamamlandi' && <Pressable onPress={() => setStatus(r, 'iptal')} style={[styles.miniBtn, { backgroundColor: Colors.status.error }]}><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>İPTAL</Text></Pressable>}
              <View style={{ flex: 1 }} />
              <Pressable onPress={() => openPhotos(r)} style={[styles.iconBtn, (r.teslim_fotograflari?.length || 0) > 0 && { backgroundColor: Colors.brand.primary + '33' }]}>
                <Ionicons name="images" size={14} color={(r.teslim_fotograflari?.length || 0) > 0 ? Colors.brand.primary : Colors.text.primary} />
              </Pressable>
              <Pressable onPress={() => openEdit(r)} style={styles.iconBtn}><Ionicons name="pencil" size={14} color={Colors.text.primary} /></Pressable>
              <Pressable onPress={() => remove(r)} style={styles.iconBtn}><Ionicons name="trash" size={14} color={Colors.status.error} /></Pressable>
            </View>
          </GlassCard>
        );
      })}

      {/* Edit Modal */}
      <Modal visible={editOpen} animationType="slide" transparent onRequestClose={() => setEditOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text style={styles.modalTitle}>Rezervasyon Düzenle</Text>
              <Pressable onPress={() => setEditOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            {editing && (
              <Text style={{ ...Typography.caption, color: Colors.text.secondary, marginBottom: 8 }}>
                {editing.musteri?.ad} {editing.musteri?.soyad} • {editing.vehicle_snapshot?.plaka}
              </Text>
            )}
            <ScrollView style={{ maxHeight: 520 }}>
              {/* Müşteri Ad/Soyad — düzenlenebilir */}
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <View style={{ flex: 1 }}><Field label="Müşteri Adı" v={editForm.musteri_ad} on={(x) => setEditForm({ ...editForm, musteri_ad: x })} /></View>
                <View style={{ flex: 1 }}><Field label="Müşteri Soyadı" v={editForm.musteri_soyad} on={(x) => setEditForm({ ...editForm, musteri_soyad: x })} /></View>
              </View>
              <DateTimeField label="Başlangıç Tarihi & Saati" value={editForm.baslangic_tarihi_tr} onChange={(x) => setEditForm({ ...editForm, baslangic_tarihi_tr: x })} />
              <DateTimeField label="Bitiş Tarihi & Saati" value={editForm.bitis_tarihi_tr} onChange={(x) => setEditForm({ ...editForm, bitis_tarihi_tr: x })} />
              <Field label="Telefon" v={editForm.telefon} on={(x) => setEditForm({ ...editForm, telefon: x })} kb="phone-pad" />

              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 6 }}>Durum</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
                {['beklemede', 'onaylandi', 'aktif', 'tamamlandi', 'iptal'].map(d => (
                  <Pressable key={d} onPress={() => setEditForm({ ...editForm, durum: d })} style={[styles.miniBtn, editForm.durum === d && styles.miniBtnActive]}>
                    <Text style={[styles.miniBtnText, editForm.durum === d && { color: '#fff' }]}>{d}</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 6 }}>Ödeme Durumu</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
                {['beklemede', 'on_odeme_alindi', 'tam_odeme_alindi'].map(d => (
                  <Pressable key={d} onPress={() => setEditForm({ ...editForm, odeme_durumu: d })} style={[styles.miniBtn, editForm.odeme_durumu === d && styles.miniBtnActive]}>
                    <Text style={[styles.miniBtnText, editForm.odeme_durumu === d && { color: '#fff' }]}>{d === 'on_odeme_alindi' ? '%20' : d === 'tam_odeme_alindi' ? 'TAM' : 'BEKLEMEDE'}</Text>
                  </Pressable>
                ))}
              </View>

              <View style={{ flexDirection: 'row', gap: 8 }}>
                <View style={{ flex: 1 }}><Field label="Toplam Tutar (₺)" v={editForm.toplam_tutar} on={(x) => setEditForm({ ...editForm, toplam_tutar: x })} kb="decimal-pad" /></View>
                <View style={{ flex: 1 }}><Field label="Ödenen (₺)" v={editForm.odenen_ucret} on={(x) => setEditForm({ ...editForm, odenen_ucret: x })} kb="decimal-pad" /></View>
              </View>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <View style={{ flex: 1 }}><Field label="Paket KM" v={editForm.paket_km} on={(x) => setEditForm({ ...editForm, paket_km: x })} kb="number-pad" /></View>
                <View style={{ flex: 1 }}><Field label="Alış KM" v={editForm.alis_km} on={(x) => setEditForm({ ...editForm, alis_km: x })} kb="number-pad" /></View>
              </View>
              <Field label="Notlar" v={editForm.notlar} on={(x) => setEditForm({ ...editForm, notlar: x })} multi />
            </ScrollView>
            <GlassButton title="KAYDET" onPress={saveEdit} size="lg" />
          </View>
        </View>
      </Modal>

      {/* Teslim Fotoğrafları Modal */}
      <Modal visible={photoOpen} animationType="slide" transparent onRequestClose={() => setPhotoOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalTitle}>📷 Teslim Fotoğrafları</Text>
                {photoRez && <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{photoRez.musteri?.ad} {photoRez.musteri?.soyad} • {photoRez.vehicle_snapshot?.plaka}</Text>}
              </View>
              <Pressable onPress={() => setPhotoOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>

            <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 8 }}>
              Aracı teslim ederken çekilen fotoğraflar müşteri tarafında "Aktif Kiralama" sayfasında görünür. Olası hasar/çizik anlaşmazlıklarını önler.
            </Text>

            <View style={{ marginTop: 12 }}>
              <Field label="Açıklama (Ops.)" v={photoCaption} on={setPhotoCaption} />
              <View style={{ flexDirection: 'row', gap: 8, marginTop: 8 }}>
                <Pressable onPress={() => pickAndUpload('camera')} disabled={photoLoading} style={[styles.fab, { flex: 1, height: 44, borderRadius: Radius.md, flexDirection: 'row', gap: 6, opacity: photoLoading ? 0.5 : 1 }]}>
                  <Ionicons name="camera" size={18} color="#fff" />
                  <Text style={{ color: '#fff', fontWeight: '700' }}>KAMERA</Text>
                </Pressable>
                <Pressable onPress={() => pickAndUpload('library')} disabled={photoLoading} style={[styles.fab, { flex: 1, height: 44, borderRadius: Radius.md, flexDirection: 'row', gap: 6, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, opacity: photoLoading ? 0.5 : 1 }]}>
                  <Ionicons name="images" size={18} color={Colors.text.primary} />
                  <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>GALERİ</Text>
                </Pressable>
              </View>
              {photoLoading && <ActivityIndicator color={Colors.brand.primary} style={{ marginTop: 8 }} />}
            </View>

            <ScrollView style={{ maxHeight: 380, marginTop: 12 }}>
              {photos.length === 0 && !photoLoading ? (
                <View style={{ alignItems: 'center', padding: 24 }}>
                  <Ionicons name="camera-outline" size={48} color={Colors.text.tertiary} />
                  <Text style={{ ...Typography.caption, color: Colors.text.tertiary, marginTop: 8 }}>Henüz fotoğraf yok</Text>
                </View>
              ) : (
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
                  {photos.map((p) => (
                    <View key={p.id} style={{ width: '48%', position: 'relative' }}>
                      <Pressable onPress={() => setPreviewUrl(p.url)}>
                        <Image source={{ uri: p.url }} style={{ width: '100%', aspectRatio: 1, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2 }} />
                      </Pressable>
                      {!!p.aciklama && <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 4 }} numberOfLines={2}>{p.aciklama}</Text>}
                      <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>{new Date(p.uploaded_at).toLocaleString('tr-TR')}</Text>
                      <Pressable onPress={() => removePhoto(p.id)} style={{ position: 'absolute', top: 4, right: 4, backgroundColor: 'rgba(0,0,0,0.7)', borderRadius: 16, padding: 6 }}>
                        <Ionicons name="trash" size={14} color={Colors.status.error} />
                      </Pressable>
                    </View>
                  ))}
                </View>
              )}
            </ScrollView>
          </View>
          {/* Pinch-Zoom Preview — NESTED inside photoOpen Modal as absolute overlay (iki Modal üst üste yerine) */}
          {!!previewUrl && (
            <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.95)', alignItems: 'center', justifyContent: 'center', zIndex: 100 }}>
              <ZoomableImage uri={previewUrl} onClose={() => setPreviewUrl(null)} />
              <View style={{ position: 'absolute', top: 50, right: 20 }}>
                <Pressable onPress={() => setPreviewUrl(null)} style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' }}>
                  <Ionicons name="close" size={28} color="#fff" />
                </Pressable>
              </View>
              <View style={{ position: 'absolute', bottom: 40, alignSelf: 'center', paddingHorizontal: 14, paddingVertical: 6, backgroundColor: 'rgba(255,255,255,0.1)', borderRadius: 14 }}>
                <Text style={{ color: '#fff', fontSize: 11 }}>İki parmakla yakınlaştırın • Çift dokunma ile sıfırla</Text>
              </View>
            </View>
          )}
        </View>
      </Modal>

      {/* Manuel Rezervasyon Modal */}
      <Modal visible={manualOpen} animationType="slide" transparent onRequestClose={() => setManualOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text style={styles.modalTitle}>Manuel Rezervasyon Oluştur</Text>
              <Pressable onPress={() => setManualOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <ScrollView style={{ maxHeight: 560 }}>
              {/* Müşteri modu */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 8, marginBottom: 4 }}>Müşteri</Text>
              <View style={{ flexDirection: 'row', gap: 6 }}>
                <Pressable onPress={() => setManualForm({ ...manualForm, mode: 'existing' })} style={[styles.miniBtn, manualForm.mode === 'existing' && styles.miniBtnActive, { flex: 1 }]}><Text style={[styles.miniBtnText, manualForm.mode === 'existing' && { color: '#fff' }]}>MEVCUT</Text></Pressable>
                <Pressable onPress={() => setManualForm({ ...manualForm, mode: 'new' })} style={[styles.miniBtn, manualForm.mode === 'new' && styles.miniBtnActive, { flex: 1 }]}><Text style={[styles.miniBtnText, manualForm.mode === 'new' && { color: '#fff' }]}>YENİ KAYIT</Text></Pressable>
              </View>
              {manualForm.mode === 'existing' ? (
                <>
                  <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.sm, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 10, marginTop: 6 }}>
                    <Ionicons name="search" size={14} color={Colors.text.tertiary} />
                    <TextInput value={manualForm.customer_search} onChangeText={(x) => setManualForm({ ...manualForm, customer_search: x })} placeholder="Ad, soyad, telefon veya TC ara…" placeholderTextColor={Colors.text.tertiary} style={{ flex: 1, color: Colors.text.primary, paddingVertical: 8, paddingHorizontal: 6, fontSize: 13 }} />
                  </View>
                  <ScrollView style={{ maxHeight: 160, marginTop: 6 }}>
                    {filteredManualCustomers.length === 0 ? (
                      <Text style={{ ...Typography.caption, color: Colors.text.tertiary, textAlign: 'center', padding: 12 }}>Müşteri yok</Text>
                    ) : filteredManualCustomers.map(c => (
                      <Pressable key={c.id} onPress={() => setManualForm({ ...manualForm, customer_id: c.id, telefon: c.telefon || '' })} style={[styles.checkRow, manualForm.customer_id === c.id && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                        <Ionicons name={manualForm.customer_id === c.id ? 'radio-button-on' : 'radio-button-off'} size={18} color={manualForm.customer_id === c.id ? Colors.brand.primary : Colors.text.secondary} />
                        <View style={{ flex: 1 }}>
                          <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>{c.ad} {c.soyad}</Text>
                          <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{c.telefon || '—'} • TC: {c.tc_norm || c.tc || '—'}</Text>
                        </View>
                      </Pressable>
                    ))}
                  </ScrollView>
                </>
              ) : (
                <>
                  <View style={{ flexDirection: 'row', gap: 8 }}>
                    <View style={{ flex: 1 }}><Field label="Ad" v={manualForm.new_ad} on={(x) => setManualForm({ ...manualForm, new_ad: x })} /></View>
                    <View style={{ flex: 1 }}><Field label="Soyad" v={manualForm.new_soyad} on={(x) => setManualForm({ ...manualForm, new_soyad: x })} /></View>
                  </View>
                  <Field label="TC (11 hane)" v={manualForm.new_tc} on={(x) => setManualForm({ ...manualForm, new_tc: x.replace(/\D/g, '').slice(0, 11) })} kb="number-pad" />
                  <Field label="Telefon" v={manualForm.new_telefon} on={(x) => setManualForm({ ...manualForm, new_telefon: x })} kb="phone-pad" />
                </>
              )}

              {/* Araç */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 4 }}>Araç</Text>
              <ScrollView style={{ maxHeight: 180 }}>
                {vehicles.map(v => (
                  <Pressable key={v.id} onPress={() => setManualForm({ ...manualForm, vehicle_id: v.id })} style={[styles.checkRow, manualForm.vehicle_id === v.id && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                    <Ionicons name={manualForm.vehicle_id === v.id ? 'radio-button-on' : 'radio-button-off'} size={18} color={manualForm.vehicle_id === v.id ? Colors.brand.primary : Colors.text.secondary} />
                    <View style={{ flex: 1 }}>
                      <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>{v.plaka}</Text>
                      <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{v.marka} {v.model} • {v.gunluk_fiyat.toLocaleString('tr-TR')}₺/gün • {v.durum}</Text>
                    </View>
                  </Pressable>
                ))}
              </ScrollView>

              {/* Tarihler */}
              <DateTimeField label="Başlangıç Tarihi & Saati" value={manualForm.baslangic_tarihi_tr} onChange={(x) => setManualForm({ ...manualForm, baslangic_tarihi_tr: x })} />
              <DateTimeField label="Bitiş Tarihi & Saati" value={manualForm.bitis_tarihi_tr} onChange={(x) => setManualForm({ ...manualForm, bitis_tarihi_tr: x })} />

              {/* Ek Hizmetler */}
              {manualForm.vehicle_id ? (
                <>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 4 }}>Ek Hizmetler</Text>
                  {manualServicesLoading ? (
                    <ActivityIndicator color={Colors.brand.primary} style={{ marginVertical: 8 }} />
                  ) : manualServices.length === 0 ? (
                    <Text style={{ ...Typography.caption, color: Colors.text.tertiary, padding: 8 }}>Bu araç için hizmet yok</Text>
                  ) : (
                    <View style={{ gap: 4 }}>
                      {manualServices.map((s: any) => {
                        const selected = !!(manualForm.selected_services?.[s.id]);
                        const locked = !!s.zorunlu;
                        return (
                          <Pressable
                            key={s.id}
                            onPress={() => {
                              if (locked) return;
                              const sel = { ...(manualForm.selected_services || {}) };
                              if (selected) delete sel[s.id]; else sel[s.id] = 1;
                              setManualForm({ ...manualForm, selected_services: sel });
                            }}
                            style={[styles.checkRow, selected && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }, locked && { opacity: 0.85 }]}
                          >
                            <Ionicons name={selected ? 'checkbox' : 'square-outline'} size={18} color={selected ? Colors.brand.primary : Colors.text.secondary} />
                            <View style={{ flex: 1 }}>
                              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                                <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>{s.isim}</Text>
                                {locked && <Text style={{ ...Typography.micro, color: Colors.status.warning, fontWeight: '700' }}>ZORUNLU</Text>}
                              </View>
                              <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>
                                {Number(s.fiyat).toLocaleString('tr-TR')}₺ {s.tip === 'gunluk' ? '/gün' : '(tek seferlik)'}
                              </Text>
                            </View>
                          </Pressable>
                        );
                      })}
                    </View>
                  )}
                </>
              ) : null}

              {/* Ödeme tipi */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 4 }}>Ödeme Durumu</Text>
              <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
                {[
                  { k: 'beklemede', l: 'BEKLEMEDE' },
                  { k: 'on_odeme_alindi', l: 'KAPORA ALINDI' },
                  { k: 'tam_odeme_alindi', l: 'TAM ÖDEME' },
                ].map(d => (
                  <Pressable key={d.k} onPress={() => setManualForm({ ...manualForm, odeme_durumu: d.k })} style={[styles.miniBtn, manualForm.odeme_durumu === d.k && styles.miniBtnActive]}>
                    <Text style={[styles.miniBtnText, manualForm.odeme_durumu === d.k && { color: '#fff' }]}>{d.l}</Text>
                  </Pressable>
                ))}
              </View>

              <Field label="İskonto %" v={String(manualForm.iskonto_yuzde)} on={(x) => setManualForm({ ...manualForm, iskonto_yuzde: x })} kb="decimal-pad" />

              {/* Admin Override'lar */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 4 }}>Manuel Ayarlar (Opsiyonel)</Text>
              <View style={{ flexDirection: 'row', gap: 8 }}>
                <View style={{ flex: 1 }}>
                  <Field
                    label="Paket KM Override"
                    v={String(manualForm.paket_km_override || '')}
                    on={(x) => setManualForm({ ...manualForm, paket_km_override: x.replace(/[^0-9]/g, '') })}
                    kb="number-pad"
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Field
                    label="Toplam Tutar Override (₺)"
                    v={String(manualForm.toplam_tutar_override || '')}
                    on={(x) => setManualForm({ ...manualForm, toplam_tutar_override: x.replace(/[^0-9.,]/g, '') })}
                    kb="decimal-pad"
                  />
                </View>
              </View>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: -8, marginBottom: 8 }}>
                Boş bırakırsanız otomatik hesaplanır.
              </Text>

              <Field
                label="Peşin Ödenen Ücret (₺)"
                v={String(manualForm.odenen_ucret || '')}
                on={(x) => setManualForm({ ...manualForm, odenen_ucret: x.replace(/[^0-9.,]/g, '') })}
                kb="decimal-pad"
              />
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: -8, marginBottom: 4 }}>
                Müşteriden peşin alındıysa girin. Ödeme durumu otomatik güncellenir.
              </Text>

              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 12, fontStyle: 'italic' }}>
                ℹ️ Rezervasyon onaylı durumunda oluşturulacak ve müşteriye bildirim gönderilecektir.
              </Text>
            </ScrollView>
            <GlassButton title="REZERVASYON OLUŞTUR" onPress={submitManual} size="lg" style={{ marginTop: 8 }} />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// ===== Notifications =====
function NotificationsTab() {
  const [list, setList] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState<any>({ baslik: '', mesaj: '', hedef_type: 'tum', hedef_customer_ids: [] });
  const [search, setSearch] = useState('');

  const load = useCallback(async () => { try { setList(await adminApi.notifications()); } catch {} }, []);
  useEffect(() => { load(); (async () => { try { setCustomers(await adminApi.customers()); } catch {} })(); }, [load]);

  const send = async () => {
    if (!form.baslik || !form.mesaj) { Alert.alert('Hata', 'Başlık ve mesaj zorunlu'); return; }
    try {
      await adminApi.sendNotification(form);
      setOpen(false);
      setForm({ baslik: '', mesaj: '', hedef_type: 'tum', hedef_customer_ids: [] });
      setSearch('');
      load();
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const toggleId = (id: string) => {
    setForm((f: any) => ({ ...f, hedef_customer_ids: f.hedef_customer_ids.includes(id) ? f.hedef_customer_ids.filter((x: string) => x !== id) : [...f.hedef_customer_ids, id] }));
  };

  const filteredCustomers = customers.filter((c: any) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase().trim();
    return (
      (c.ad || '').toLowerCase().includes(q) ||
      (c.soyad || '').toLowerCase().includes(q) ||
      (c.telefon || '').toLowerCase().includes(q) ||
      (c.tc_norm || c.tc || '').toLowerCase().includes(q)
    );
  });

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <Pressable onPress={() => setOpen(true)} style={[styles.fab, { width: '100%', height: 48, borderRadius: Radius.pill, flexDirection: 'row', gap: 6 }]} testID="send-notif">
        <Ionicons name="megaphone" size={20} color="#fff" />
        <Text style={{ color: '#fff', fontWeight: '700' }}>BİLDİRİM GÖNDER</Text>
      </Pressable>
      {list.map(n => (
        <GlassCard key={n.id}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <View style={{ flex: 1 }}>
              <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{n.baslik}</Text>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary, marginTop: 4 }}>{n.mesaj}</Text>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 6 }}>
                {n.hedef_type === 'tum' ? '👥 Tüm müşteriler' : n.hedef_type === 'admin' ? '🛡️ Yönetici (otomatik)' : `${(n.hedef_customer_ids || []).length} müşteri`} • {(n.okuyanlar || []).length} okudu
              </Text>
            </View>
            <Pressable onPress={async () => { await adminApi.deleteNotification(n.id); load(); }} style={styles.iconBtn}>
              <Ionicons name="trash" size={16} color={Colors.status.error} />
            </Pressable>
          </View>
        </GlassCard>
      ))}

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={styles.modalTitle}>Bildirim Gönder</Text>
              <Pressable onPress={() => setOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <Field label="Başlık" v={form.baslik} on={(x) => setForm({ ...form, baslik: x })} />
            <Field label="Mesaj" v={form.mesaj} on={(x) => setForm({ ...form, mesaj: x })} multi />
            <View style={{ flexDirection: 'row', gap: 6, marginTop: 8 }}>
              <Pressable onPress={() => setForm({ ...form, hedef_type: 'tum' })} style={[styles.miniBtn, form.hedef_type === 'tum' && styles.miniBtnActive, { flex: 1 }]}>
                <Text style={[styles.miniBtnText, form.hedef_type === 'tum' && { color: '#fff' }]}>👥 TÜM MÜŞTERİLER</Text>
              </Pressable>
              <Pressable onPress={() => setForm({ ...form, hedef_type: 'secili' })} style={[styles.miniBtn, form.hedef_type === 'secili' && styles.miniBtnActive, { flex: 1 }]}>
                <Text style={[styles.miniBtnText, form.hedef_type === 'secili' && { color: '#fff' }]}>✓ SEÇİLİ</Text>
              </Pressable>
            </View>
            {form.hedef_type === 'secili' && (
              <>
                <View style={{ marginTop: 8, marginBottom: 4 }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.sm, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 10 }}>
                    <Ionicons name="search" size={14} color={Colors.text.tertiary} />
                    <TextInput value={search} onChangeText={setSearch} placeholder="Ad, soyad, telefon veya TC ara…" placeholderTextColor={Colors.text.tertiary} style={{ flex: 1, color: Colors.text.primary, paddingVertical: 8, paddingHorizontal: 6, fontSize: 13 }} />
                    {!!search && (
                      <Pressable onPress={() => setSearch('')}>
                        <Ionicons name="close-circle" size={16} color={Colors.text.tertiary} />
                      </Pressable>
                    )}
                  </View>
                </View>
                <ScrollView style={{ maxHeight: 200, marginTop: 4 }}>
                  {filteredCustomers.length === 0 ? (
                    <Text style={{ ...Typography.caption, color: Colors.text.tertiary, textAlign: 'center', padding: 12 }}>Eşleşen müşteri yok</Text>
                  ) : filteredCustomers.map(c => (
                    <Pressable key={c.id} onPress={() => toggleId(c.id)} style={[styles.checkRow, form.hedef_customer_ids.includes(c.id) && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                      <Ionicons name={form.hedef_customer_ids.includes(c.id) ? 'checkbox' : 'square-outline'} size={20} color={form.hedef_customer_ids.includes(c.id) ? Colors.brand.primary : Colors.text.secondary} />
                      <View style={{ flex: 1 }}>
                        <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>{c.ad} {c.soyad}</Text>
                        <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{c.telefon || '—'}</Text>
                      </View>
                    </Pressable>
                  ))}
                </ScrollView>
              </>
            )}
            <GlassButton title="GÖNDER" onPress={send} size="lg" style={{ marginTop: 12 }} />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// ===== Reviews / Yorumlar Yönetimi =====
function ReviewsTab() {
  const [list, setList] = useState<any[]>([]);
  const [durum, setDurum] = useState<string>('');
  const [replyOpen, setReplyOpen] = useState(false);
  const [replyTarget, setReplyTarget] = useState<any>(null);
  const [replyText, setReplyText] = useState('');

  const load = useCallback(async () => {
    try { setList(await adminApi.listReviews(durum || undefined)); } catch {}
  }, [durum]);
  useEffect(() => { load(); }, [load]);

  const setStatus = async (r: any, newDurum: string) => {
    try { await adminApi.updateReview(r.id, { durum: newDurum }); load(); }
    catch (e: any) { Alert.alert('Hata', e.message); }
  };
  const remove = async (r: any) => {
    Alert.alert('Sil', 'Bu yorumu silmek istediğinize emin misiniz?', [
      { text: 'Vazgeç' },
      { text: 'Sil', style: 'destructive', onPress: async () => {
        try { await adminApi.deleteReview(r.id); load(); } catch (e: any) { Alert.alert('Hata', e.message); }
      } },
    ]);
  };
  const submitReply = async () => {
    if (!replyTarget) return;
    try { await adminApi.updateReview(replyTarget.id, { admin_cevap: replyText.trim() }); setReplyOpen(false); setReplyTarget(null); setReplyText(''); load(); }
    catch (e: any) { Alert.alert('Hata', e.message); }
  };

  const filters: { k: string; l: string }[] = [
    { k: '', l: 'Tümü' },
    { k: 'beklemede', l: 'Onay Bekleyen' },
    { k: 'onaylandi', l: 'Onaylı' },
    { k: 'gizli', l: 'Gizli' },
  ];

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ flexDirection: 'row', gap: 6 }}>
          {filters.map(f => (
            <Pressable key={f.k} onPress={() => setDurum(f.k)} style={[styles.miniBtn, durum === f.k && styles.miniBtnActive]}>
              <Text style={[styles.miniBtnText, durum === f.k && { color: '#fff' }]}>{f.l}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>

      {list.length === 0 ? <Empty title="Yorum yok" /> : list.map(r => (
        <GlassCard key={r.id} highlight={r.durum === 'beklemede'}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <View style={{ flex: 1 }}>
              <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{r.customer_display}</Text>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{r.vehicle_snapshot?.marka} {r.vehicle_snapshot?.model} • {r.vehicle_snapshot?.plaka}</Text>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>{new Date(r.tarih).toLocaleString('tr-TR')}</Text>
            </View>
            <StatusBadge status={r.durum} />
          </View>
          <View style={{ flexDirection: 'row', gap: 14, marginTop: 6 }}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Araç:</Text>
              <Stars value={r.arac_puan} size={12} />
              <Text style={{ ...Typography.micro, color: Colors.text.primary, fontWeight: '700' }}>{r.arac_puan}/5</Text>
            </View>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
              <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Servis:</Text>
              <Stars value={r.servis_puan} size={12} />
              <Text style={{ ...Typography.micro, color: Colors.text.primary, fontWeight: '700' }}>{r.servis_puan}/5</Text>
            </View>
          </View>
          {!!r.yorum && <Text style={{ ...Typography.body, color: Colors.text.primary, marginTop: 8, fontStyle: 'italic' }}>"{r.yorum}"</Text>}
          {!!r.admin_cevap && (
            <View style={{ marginTop: 8, paddingLeft: 10, borderLeftWidth: 2, borderLeftColor: Colors.brand.primary }}>
              <Text style={{ ...Typography.micro, color: Colors.brand.primary, fontWeight: '700' }}>YS AUTO Cevabı</Text>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary, marginTop: 2 }}>{r.admin_cevap}</Text>
            </View>
          )}
          <View style={{ flexDirection: 'row', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
            {r.durum !== 'onaylandi' && <Pressable onPress={() => setStatus(r, 'onaylandi')} style={[styles.miniBtn, { backgroundColor: Colors.status.success }]}><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>ONAYLA</Text></Pressable>}
            {r.durum !== 'gizli' && <Pressable onPress={() => setStatus(r, 'gizli')} style={[styles.miniBtn, { backgroundColor: Colors.text.secondary }]}><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>GİZLE</Text></Pressable>}
            <Pressable onPress={() => { setReplyTarget(r); setReplyText(r.admin_cevap || ''); setReplyOpen(true); }} style={[styles.miniBtn, { backgroundColor: Colors.brand.primary }]}><Text style={{ color: '#fff', fontSize: 11, fontWeight: '700' }}>{r.admin_cevap ? 'CEVAP DÜZENLE' : 'CEVAP YAZ'}</Text></Pressable>
            <View style={{ flex: 1 }} />
            <Pressable onPress={() => remove(r)} style={styles.iconBtn}><Ionicons name="trash" size={14} color={Colors.status.error} /></Pressable>
          </View>
        </GlassCard>
      ))}

      <Modal visible={replyOpen} animationType="slide" transparent onRequestClose={() => setReplyOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={styles.modalTitle}>Yoruma Cevap Yaz</Text>
              <Pressable onPress={() => setReplyOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <Text style={{ ...Typography.caption, color: Colors.text.secondary, marginTop: 8 }}>"{replyTarget?.yorum || (replyTarget ? `${replyTarget.arac_puan}⭐ araç / ${replyTarget.servis_puan}⭐ servis` : '')}"</Text>
            <TextInput
              value={replyText}
              onChangeText={setReplyText}
              placeholder="Müşteriye nazik bir cevap yazın..."
              placeholderTextColor={Colors.text.tertiary}
              multiline
              numberOfLines={4}
              maxLength={500}
              style={{ marginTop: 12, minHeight: 100, color: Colors.text.primary, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base, padding: 12, textAlignVertical: 'top', fontSize: 14 }}
            />
            <GlassButton title="CEVABI KAYDET" onPress={submitReply} size="lg" style={{ marginTop: 12 }} />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// ===== Settings (genişletilmiş) =====
function SettingsTab() {
  const [s, setS] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => { try { setS(await adminApi.settings()); } catch {} finally { setLoading(false); } }, []);
  useEffect(() => { load(); }, [load]);
  const save = async () => { try { await adminApi.updateSettings(s); Alert.alert('Kaydedildi'); } catch (e: any) { Alert.alert('Hata', e.message); } };
  if (loading) return <ActivityIndicator color={Colors.brand.primary} style={{ marginTop: 40 }} />;

  const toggleWeekday = (i: number) => {
    const cur: number[] = s.tatil_haftaici_gunler || [6];
    const next = cur.includes(i) ? cur.filter(x => x !== i) : [...cur, i];
    setS({ ...s, tatil_haftaici_gunler: next });
  };
  const wdNames = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <SectionTitle title="IBAN & Banka" />
      <GlassCard>
        <Field label="IBAN" v={s.iban} on={(x) => setS({ ...s, iban: x })} />
        <Field label="Banka" v={s.banka} on={(x) => setS({ ...s, banka: x })} />
        <Field label="Hesap Sahibi" v={s.hesap_sahibi} on={(x) => setS({ ...s, hesap_sahibi: x })} />
      </GlassCard>

      <SectionTitle title="İletişim" />
      <GlassCard>
        <Field label="Telefon" v={s.iletisim_telefon} on={(x) => setS({ ...s, iletisim_telefon: x })} />
        <Field label="E-posta" v={s.iletisim_email} on={(x) => setS({ ...s, iletisim_email: x })} />
        <Field label="Adres" v={s.iletisim_adres} on={(x) => setS({ ...s, iletisim_adres: x })} multi />
        <Field label="WhatsApp" v={s.whatsapp} on={(x) => setS({ ...s, whatsapp: x })} />
      </GlassCard>

      <SectionTitle title="Mesai Saatleri" subtitle="Bu saatler dışında rezervasyon teslim/iade yapılamaz" />
      <GlassCard>
        <View style={{ flexDirection: 'row', gap: 8 }}>
          <View style={{ flex: 1 }}><Field label="Başlangıç (HH:MM)" v={s.mesai_baslangic} on={(x) => setS({ ...s, mesai_baslangic: x })} /></View>
          <View style={{ flex: 1 }}><Field label="Bitiş (HH:MM)" v={s.mesai_bitis} on={(x) => setS({ ...s, mesai_bitis: x })} /></View>
        </View>
      </GlassCard>

      <SectionTitle title="Bloklu Günler" subtitle="Haftada hangi günler kapalı?" />
      <GlassCard>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
          {wdNames.map((n, i) => {
            const active = (s.tatil_haftaici_gunler || [6]).includes(i);
            return (
              <Pressable key={n} onPress={() => toggleWeekday(i)} style={[styles.miniBtn, active && styles.miniBtnActive]}>
                <Text style={[styles.miniBtnText, active && { color: '#fff' }]}>{n}</Text>
              </Pressable>
            );
          })}
        </View>
      </GlassCard>

      <SectionTitle title="Kart Ödeme Ücretleri" />
      <GlassCard>
        <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginBottom: 8 }}>
          Müşteri kart ile bakiye yüklediğinde, girdiği tutardan KDV ve komisyon düşülerek cüzdana net miktar geçer.
        </Text>
        <Field label="KDV (%)" v={String(s.kart_kdv_yuzde ?? 20)} on={(x) => setS({ ...s, kart_kdv_yuzde: parseFloat(x.replace(/[^\d.]/g, '') || '0') })} kb="decimal-pad" />
        <Field label="Komisyon (%)" v={String(s.kart_komisyon_yuzde ?? 5)} on={(x) => setS({ ...s, kart_komisyon_yuzde: parseFloat(x.replace(/[^\d.]/g, '') || '0') })} kb="decimal-pad" />
        <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 6, fontStyle: 'italic' }}>
          Örnek: 1000₺ giriş, KDV %{s.kart_kdv_yuzde ?? 20} ({Math.round((1000 * (s.kart_kdv_yuzde ?? 20) / 100))}₺), Komisyon %{s.kart_komisyon_yuzde ?? 5} ({Math.round((1000 * (s.kart_komisyon_yuzde ?? 5) / 100))}₺) → Net cüzdana: {1000 - Math.round((1000 * ((s.kart_kdv_yuzde ?? 20) + (s.kart_komisyon_yuzde ?? 5)) / 100))}₺
        </Text>
      </GlassCard>

      <GlassButton title="AYARLARI KAYDET" onPress={save} size="lg" />
    </ScrollView>
  );
}

// ===== Services (Ek Hizmetler CRUD) =====
// İkon picker — popüler Ionicons isimleri
const ICON_OPTIONS = [
  'pricetag-outline', 'shield-checkmark-outline', 'person-add-outline',
  'umbrella-outline', 'card-outline', 'flash-outline', 'gift-outline',
  'star-outline', 'medical-outline', 'snow-outline', 'wifi-outline',
  'navigate-outline', 'bicycle-outline', 'cafe-outline', 'cube-outline',
  'briefcase-outline', 'paw-outline', 'happy-outline', 'lock-closed-outline',
  'time-outline', 'speedometer-outline', 'bonfire-outline', 'cash-outline',
];

function ServicesTab() {
  const [list, setList] = useState<any[]>([]);
  const [vehicles, setVehicles] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [iconOpen, setIconOpen] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  const empty = { isim: '', aciklama: '', fiyat: 0, tip: 'gunluk', icon: 'pricetag-outline', aktif: true, zorunlu: false, arac_ids: [] as string[], siralama: 0 };
  const [form, setForm] = useState<any>(empty);

  const load = useCallback(async () => {
    try {
      setList(await adminApi.services());
      setVehicles(await adminApi.vehicles());
    } catch {}
  }, []);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    try {
      if (editing) await adminApi.updateService(editing.id, form);
      else await adminApi.createService(form);
      setOpen(false); setEditing(null); setForm(empty);
      load();
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };
  const remove = (svc: any) => Alert.alert('Sil?', svc.isim, [{ text: 'Vazgeç' }, { text: 'Sil', style: 'destructive', onPress: async () => { await adminApi.deleteService(svc.id); load(); } }]);

  const toggleVehicle = (vid: string) => {
    const cur = form.arac_ids || [];
    setForm({ ...form, arac_ids: cur.includes(vid) ? cur.filter((x: string) => x !== vid) : [...cur, vid] });
  };

  const allVehiclesSelected = !form.arac_ids || form.arac_ids.length === 0;

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <Pressable onPress={() => { setEditing(null); setForm(empty); setOpen(true); }} style={[styles.fab, { width: '100%', height: 48, borderRadius: Radius.pill, flexDirection: 'row', gap: 6 }]}>
        <Ionicons name="add" size={20} color="#fff" />
        <Text style={{ color: '#fff', fontWeight: '700' }}>YENİ HİZMET</Text>
      </Pressable>
      {list.length === 0 ? <Empty title="Henüz hizmet yok" /> : list.map(svc => {
        const aracSayisi = (svc.arac_ids || []).length;
        return (
          <GlassCard key={svc.id}>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <Ionicons name={svc.icon as any} size={22} color={Colors.brand.primary} />
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{svc.isim}</Text>
                  {!svc.aktif && <Text style={{ color: Colors.text.tertiary }}>🔒</Text>}
                  {svc.zorunlu && (
                    <View style={{ paddingHorizontal: 6, paddingVertical: 2, backgroundColor: Colors.brand.primary, borderRadius: 4 }}>
                      <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900' }}>ZORUNLU</Text>
                    </View>
                  )}
                </View>
                <Text style={{ ...Typography.caption, color: Colors.text.secondary }} numberOfLines={1}>{svc.aciklama}</Text>
                <Text style={{ ...Typography.micro, color: Colors.brand.primaryLight, marginTop: 2 }}>
                  {svc.fiyat.toLocaleString('tr-TR')}₺ • {svc.tip === 'gunluk' ? 'günlük' : 'tek seferlik'} • {aracSayisi === 0 ? 'TÜM araçlar' : `${aracSayisi} araç`}
                </Text>
              </View>
              <Pressable onPress={() => { setEditing(svc); setForm({ ...empty, ...svc, arac_ids: svc.arac_ids || [] }); setOpen(true); }} style={styles.iconBtn}><Ionicons name="pencil" size={14} color={Colors.text.primary} /></Pressable>
              <Pressable onPress={() => remove(svc)} style={styles.iconBtn}><Ionicons name="trash" size={14} color={Colors.status.error} /></Pressable>
            </View>
          </GlassCard>
        );
      })}

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={styles.modalTitle}>{editing ? 'Hizmet Düzenle' : 'Yeni Hizmet'}</Text>
              <Pressable onPress={() => setOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <ScrollView style={{ maxHeight: 560 }}>
              <Field label="İsim" v={form.isim} on={(x) => setForm({ ...form, isim: x })} />
              <Field label="Açıklama" v={form.aciklama} on={(x) => setForm({ ...form, aciklama: x })} multi />
              <Field label="Fiyat (₺)" v={String(form.fiyat)} on={(x) => setForm({ ...form, fiyat: parseFloat(x.replace(/[^\d.]/g, '') || '0') })} kb="decimal-pad" />

              <View style={{ flexDirection: 'row', gap: 6, marginTop: 8 }}>
                <Pressable onPress={() => setForm({ ...form, tip: 'gunluk' })} style={[styles.miniBtn, form.tip === 'gunluk' && styles.miniBtnActive, { flex: 1 }]}>
                  <Text style={[styles.miniBtnText, form.tip === 'gunluk' && { color: '#fff' }]}>GÜNLÜK</Text>
                </Pressable>
                <Pressable onPress={() => setForm({ ...form, tip: 'tek_seferlik' })} style={[styles.miniBtn, form.tip === 'tek_seferlik' && styles.miniBtnActive, { flex: 1 }]}>
                  <Text style={[styles.miniBtnText, form.tip === 'tek_seferlik' && { color: '#fff' }]}>TEK SEFERLİK</Text>
                </Pressable>
              </View>

              {/* İkon Picker */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 6 }}>İkon</Text>
              <Pressable onPress={() => setIconOpen(true)} style={[styles.checkRow, { paddingVertical: 12 }]}>
                <Ionicons name={form.icon as any} size={24} color={Colors.brand.primary} />
                <Text style={{ color: Colors.text.primary, flex: 1 }}>{form.icon}</Text>
                <Ionicons name="chevron-forward" size={18} color={Colors.text.secondary} />
              </Pressable>

              <Field label="Sıralama" v={String(form.siralama || 0)} on={(x) => setForm({ ...form, siralama: parseInt(x.replace(/\D/g, '') || '0', 10) })} kb="number-pad" />

              {/* Aktif & Zorunlu */}
              <Pressable onPress={() => setForm({ ...form, aktif: !form.aktif })} style={[styles.checkRow, form.aktif && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                <Ionicons name={form.aktif ? 'checkbox' : 'square-outline'} size={20} color={form.aktif ? Colors.brand.primary : Colors.text.secondary} />
                <Text style={{ color: Colors.text.primary }}>Aktif</Text>
              </Pressable>
              <Pressable onPress={() => setForm({ ...form, zorunlu: !form.zorunlu })} style={[styles.checkRow, form.zorunlu && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                <Ionicons name={form.zorunlu ? 'checkbox' : 'square-outline'} size={20} color={form.zorunlu ? Colors.brand.primary : Colors.text.secondary} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>Zorunlu Hizmet</Text>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Müşteri iptal edemez, ücret rezervasyona otomatik eklenir</Text>
                </View>
              </Pressable>

              {/* Araç Kapsamı */}
              <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 12, marginBottom: 6 }}>Hangi Araçlar?</Text>
              <Pressable onPress={() => setForm({ ...form, arac_ids: [] })} style={[styles.checkRow, allVehiclesSelected && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                <Ionicons name={allVehiclesSelected ? 'radio-button-on' : 'radio-button-off'} size={20} color={allVehiclesSelected ? Colors.brand.primary : Colors.text.secondary} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>TÜM Araçlar</Text>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Filodaki tüm araçlara uygulanır</Text>
                </View>
              </Pressable>
              <Pressable onPress={() => setForm({ ...form, arac_ids: form.arac_ids?.length ? form.arac_ids : (vehicles[0] ? [vehicles[0].id] : []) })} style={[styles.checkRow, !allVehiclesSelected && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                <Ionicons name={!allVehiclesSelected ? 'radio-button-on' : 'radio-button-off'} size={20} color={!allVehiclesSelected ? Colors.brand.primary : Colors.text.secondary} />
                <View style={{ flex: 1 }}>
                  <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>Sadece Seçili Araçlar</Text>
                  <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{form.arac_ids?.length || 0} araç seçildi</Text>
                </View>
              </Pressable>
              {!allVehiclesSelected && (
                <View style={{ marginTop: 8, gap: 4 }}>
                  {vehicles.map(v => {
                    const sel = (form.arac_ids || []).includes(v.id);
                    return (
                      <Pressable key={v.id} onPress={() => toggleVehicle(v.id)} style={[styles.checkRow, sel && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }, { paddingVertical: 8 }]}>
                        <Ionicons name={sel ? 'checkbox' : 'square-outline'} size={18} color={sel ? Colors.brand.primary : Colors.text.secondary} />
                        <View style={{ flex: 1 }}>
                          <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{v.plaka}</Text>
                          <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{v.marka} {v.model}</Text>
                        </View>
                      </Pressable>
                    );
                  })}
                </View>
              )}
            </ScrollView>
            <GlassButton title={editing ? 'KAYDET' : 'EKLE'} onPress={save} size="lg" />

            {/* İkon Picker — nested overlay (Modal-in-Modal yerine) */}
            {iconOpen && (
              <View style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.85)', borderRadius: Radius.lg, padding: Spacing.lg, zIndex: 10 }}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 12 }}>
                  <Text style={styles.modalTitle}>İkon Seç</Text>
                  <Pressable onPress={() => setIconOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
                </View>
                <ScrollView showsVerticalScrollIndicator={false}>
                  <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8, justifyContent: 'flex-start' }}>
                    {ICON_OPTIONS.map(ic => (
                      <Pressable
                        key={ic}
                        onPress={() => { setForm({ ...form, icon: ic }); setIconOpen(false); }}
                        style={{
                          width: 64, height: 64, borderRadius: Radius.md, backgroundColor: form.icon === ic ? Colors.brand.primary : Colors.bg.surface2,
                          alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: form.icon === ic ? Colors.brand.primaryLight : Colors.border.base,
                        }}
                      >
                        <Ionicons name={ic as any} size={28} color={form.icon === ic ? '#fff' : Colors.brand.primary} />
                      </Pressable>
                    ))}
                  </View>
                </ScrollView>
              </View>
            )}
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// ===== Holidays =====
function HolidaysTab() {
  const [list, setList] = useState<any[]>([]);
  const [tarih, setTarih] = useState('');
  const [aciklama, setAciklama] = useState('');
  const load = useCallback(async () => { try { setList(await adminApi.holidays()); } catch {} }, []);
  useEffect(() => { load(); }, [load]);

  const add = async () => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(tarih)) { Alert.alert('Hata', 'Tarih YYYY-MM-DD formatında olmalı'); return; }
    if (!aciklama.trim()) { Alert.alert('Hata', 'Açıklama girin'); return; }
    try { await adminApi.addHoliday({ tarih, aciklama }); setTarih(''); setAciklama(''); load(); }
    catch (e: any) { Alert.alert('Hata', e.message); }
  };
  const remove = (h: any) => Alert.alert('Sil?', `${h.tarih} - ${h.aciklama}`, [{ text: 'Vazgeç' }, { text: 'Sil', style: 'destructive', onPress: async () => { await adminApi.deleteHoliday(h.id); load(); } }]);

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <GlassCard>
        <Text style={{ ...Typography.h4, color: Colors.text.primary, marginBottom: 8 }}>Tatil Ekle</Text>
        <Field label="Tarih (YYYY-MM-DD)" v={tarih} on={setTarih} />
        <Field label="Açıklama" v={aciklama} on={setAciklama} />
        <GlassButton title="EKLE" onPress={add} size="md" style={{ marginTop: 8 }} />
      </GlassCard>
      <SectionTitle title="Tatiller" subtitle="Bu tarihlerde rezervasyon kapalı" />
      {list.length === 0 ? <Empty title="Tatil yok" /> : list.map(h => (
        <GlassCard key={h.id}>
          <View style={{ flexDirection: 'row', alignItems: 'center' }}>
            <View style={{ flex: 1 }}>
              <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{h.tarih}</Text>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{h.aciklama}</Text>
            </View>
            <Pressable onPress={() => remove(h)} style={styles.iconBtn}><Ionicons name="trash" size={14} color={Colors.status.error} /></Pressable>
          </View>
        </GlassCard>
      ))}
    </ScrollView>
  );
}

// ===== Topups (Bekleyen havale + manuel bakiye) =====
function TopupsTab() {
  const [pending, setPending] = useState<any[]>([]);
  const [customers, setCustomers] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [selCustomer, setSelCustomer] = useState<any>(null);
  const [tutar, setTutar] = useState('');
  const [aciklama, setAciklama] = useState('Yönetici tarafından bakiye eklendi');
  const [op, setOp] = useState<'credit' | 'debit'>('credit');

  const load = useCallback(async () => {
    try {
      setPending(await adminApi.pendingTopups());
      setCustomers(await adminApi.customers());
    } catch {}
  }, []);
  useEffect(() => { load(); }, [load]);

  const approve = async (tx: any) => {
    Alert.alert('Onayla?', `${tx.musteri_adi || ''} - ${tx.tutar.toFixed(2)}₺ havale?`, [
      { text: 'Vazgeç' },
      {
        text: 'Onayla', onPress: async () => {
          try { await adminApi.approveTopup(tx.id); load(); }
          catch (e: any) { Alert.alert('Hata', e.message); }
        },
      },
    ]);
  };

  const reject = async (tx: any) => {
    Alert.alert('Reddet?', `${tx.musteri_adi || ''} - ${tx.tutar.toFixed(2)}₺ havale yüklemesi reddedilsin mi?`, [
      { text: 'Vazgeç' },
      {
        text: 'Reddet', style: 'destructive', onPress: async () => {
          try { await (adminApi as any).rejectTopup(tx.id); load(); }
          catch (e: any) { Alert.alert('Hata', e.message); }
        },
      },
    ]);
  };

  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const filteredCustomers = customers.filter((c: any) => {
    if (!search.trim()) return true;
    const q = search.toLowerCase().trim();
    return (
      (c.ad || '').toLowerCase().includes(q) ||
      (c.soyad || '').toLowerCase().includes(q) ||
      (c.telefon || '').toLowerCase().includes(q) ||
      (c.tc_norm || c.tc || '').toLowerCase().includes(q)
    );
  });

  const submitManual = async () => {
    if (!selCustomer) { Alert.alert('Hata', 'Müşteri seçin'); return; }
    const t = parseFloat(tutar.replace(',', '.'));
    if (!t || t <= 0) { Alert.alert('Hata', 'Pozitif tutar girin'); return; }
    try {
      if (op === 'credit') await adminApi.walletCredit(selCustomer.id, t, aciklama);
      else await (adminApi as any).walletDebit?.(selCustomer.id, t, aciklama);
      setOpen(false); setSelCustomer(null); setTutar(''); load();
      Alert.alert('OK', 'Bakiye güncellendi');
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.md, paddingBottom: 60 }}>
      <Pressable onPress={() => setOpen(true)} style={[styles.fab, { width: '100%', height: 48, borderRadius: Radius.pill, flexDirection: 'row', gap: 6 }]}>
        <Ionicons name="cash" size={20} color="#fff" />
        <Text style={{ color: '#fff', fontWeight: '700' }}>MANUEL BAKİYE İŞLEMİ</Text>
      </Pressable>
      <SectionTitle title="Bekleyen Havale Yüklemeleri" subtitle="AI şüpheli bulduğu dekontlar — manuel onay gerekiyor" />
      {pending.length === 0 ? <Empty title="Bekleyen yok" /> : pending.map(p => (
        <GlassCard key={p.id} highlight>
          <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{p.musteri_adi || '—'}</Text>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>Ref: {p.referans} • {new Date(p.tarih).toLocaleString('tr-TR')}</Text>
              <Text style={{ ...Typography.h4, color: Colors.brand.primaryLight, marginTop: 4 }}>+{p.tutar.toLocaleString('tr-TR')} ₺</Text>

              {/* AI Doğrulama Raporu */}
              {p.ai_result && (
                <View style={{ marginTop: 8, padding: 8, backgroundColor: Colors.bg.surface2, borderRadius: Radius.sm, borderLeftWidth: 3, borderLeftColor: p.ai_result.valid ? Colors.status.success : Colors.status.warning }}>
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                    <Ionicons name="sparkles" size={12} color={Colors.brand.primary} />
                    <Text style={{ ...Typography.micro, fontWeight: '800', color: Colors.text.primary, textTransform: 'uppercase' }}>AI Raporu (güven {((p.ai_result.confidence || 0) * 100).toFixed(0)}%)</Text>
                  </View>
                  {p.ai_result.fields && Object.entries(p.ai_result.fields).map(([k, v]: any) => (
                    <View key={k} style={{ flexDirection: 'row', gap: 4, marginTop: 2 }}>
                      <Ionicons name={v.match ? 'checkmark-circle' : 'close-circle'} size={12} color={v.match ? Colors.status.success : Colors.status.error} />
                      <Text style={{ ...Typography.micro, color: Colors.text.secondary, flex: 1 }} numberOfLines={1}>
                        <Text style={{ fontWeight: '700' }}>{k}:</Text> {String(v.extracted ?? '—')}{v.expected ? ` / bekl: ${String(v.expected)}` : ''}
                      </Text>
                    </View>
                  ))}
                  {p.ai_result.reasons?.length > 0 && (
                    <Text style={{ ...Typography.micro, color: Colors.status.error, marginTop: 4, fontStyle: 'italic' }} numberOfLines={3}>
                      ⚠ {p.ai_result.reasons.join('; ')}
                    </Text>
                  )}
                </View>
              )}
            </View>
            {/* Dekont küçük resim */}
            {p.dekont_url && (
              <Pressable onPress={() => setPreviewUrl(p.dekont_url)}>
                <Image source={{ uri: p.dekont_url }} style={{ width: 70, height: 90, borderRadius: Radius.sm, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base }} />
                <View style={{ position: 'absolute', bottom: 2, right: 2, backgroundColor: 'rgba(0,0,0,0.6)', borderRadius: 8, paddingHorizontal: 4 }}>
                  <Ionicons name="search" size={10} color="#fff" />
                </View>
              </Pressable>
            )}
          </View>
          <View style={{ flexDirection: 'row', gap: 6, marginTop: 8 }}>
            <Pressable onPress={() => approve(p)} style={[styles.miniBtn, { backgroundColor: Colors.status.success, flex: 1 }]}>
              <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700', textAlign: 'center' }}>ONAYLA</Text>
            </Pressable>
            <Pressable onPress={() => reject(p)} style={[styles.miniBtn, { backgroundColor: Colors.status.error, flex: 1 }]}>
              <Text style={{ color: '#fff', fontSize: 11, fontWeight: '700', textAlign: 'center' }}>REDDET</Text>
            </Pressable>
          </View>
        </GlassCard>
      ))}

      {/* Tam ekran dekont önizleme */}
      <Modal visible={!!previewUrl} animationType="fade" transparent onRequestClose={() => setPreviewUrl(null)}>
        <Pressable onPress={() => setPreviewUrl(null)} style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.95)', alignItems: 'center', justifyContent: 'center' }}>
          {previewUrl && <Image source={{ uri: previewUrl }} style={{ width: '95%', height: '85%', resizeMode: 'contain' }} />}
          <View style={{ position: 'absolute', top: 50, right: 20 }}>
            <Pressable onPress={() => setPreviewUrl(null)} style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name="close" size={28} color="#fff" />
            </Pressable>
          </View>
        </Pressable>
      </Modal>

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Text style={styles.modalTitle}>Manuel Bakiye İşlemi</Text>
              <Pressable onPress={() => setOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <View style={{ flexDirection: 'row', gap: 6, marginTop: 8 }}>
              <Pressable onPress={() => setOp('credit')} style={[styles.miniBtn, op === 'credit' && styles.miniBtnActive, { flex: 1 }]}><Text style={[styles.miniBtnText, op === 'credit' && { color: '#fff' }]}>+ EKLE</Text></Pressable>
              <Pressable onPress={() => setOp('debit')} style={[styles.miniBtn, op === 'debit' && styles.miniBtnActive, { flex: 1 }]}><Text style={[styles.miniBtnText, op === 'debit' && { color: '#fff' }]}>− DÜŞ</Text></Pressable>
            </View>
            <Field label="Tutar (₺)" v={tutar} on={setTutar} kb="decimal-pad" />
            <Field label="Açıklama" v={aciklama} on={setAciklama} />
            <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginTop: 8 }}>Müşteri</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.sm, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 10, marginTop: 4 }}>
              <Ionicons name="search" size={14} color={Colors.text.tertiary} />
              <TextInput value={search} onChangeText={setSearch} placeholder="Ad, soyad, telefon veya TC ara…" placeholderTextColor={Colors.text.tertiary} style={{ flex: 1, color: Colors.text.primary, paddingVertical: 8, paddingHorizontal: 6, fontSize: 13 }} />
              {!!search && (
                <Pressable onPress={() => setSearch('')}>
                  <Ionicons name="close-circle" size={16} color={Colors.text.tertiary} />
                </Pressable>
              )}
            </View>
            <ScrollView style={{ maxHeight: 240, marginTop: 6 }}>
              {filteredCustomers.length === 0 ? (
                <Text style={{ ...Typography.caption, color: Colors.text.tertiary, textAlign: 'center', padding: 12 }}>Eşleşen müşteri yok</Text>
              ) : filteredCustomers.map(c => (
                <Pressable key={c.id} onPress={() => setSelCustomer(c)} style={[styles.checkRow, selCustomer?.id === c.id && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                  <Ionicons name={selCustomer?.id === c.id ? 'radio-button-on' : 'radio-button-off'} size={18} color={selCustomer?.id === c.id ? Colors.brand.primary : Colors.text.secondary} />
                  <View style={{ flex: 1 }}>
                    <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>{c.ad} {c.soyad}</Text>
                    <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Mevcut: {(c.bakiye || 0).toLocaleString('tr-TR')} ₺ • {c.telefon}</Text>
                  </View>
                </Pressable>
              ))}
            </ScrollView>
            <GlassButton title="UYGULA" onPress={submitManual} size="lg" style={{ marginTop: 8 }} />
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

function Field({ label, v, on, kb, multi }: { label: string; v: any; on: (x: string) => void; kb?: any; multi?: boolean }) {
  return (
    <View style={{ marginTop: 8 }}>
      <Text style={{ ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginBottom: 4 }}>{label}</Text>
      <TextInput value={v ?? ''} onChangeText={on} keyboardType={kb} multiline={multi} style={[styles.input, multi && { height: 70, textAlignVertical: 'top' }]} placeholderTextColor={Colors.text.tertiary} />
    </View>
  );
}

/**
 * Generic 2-column bracket editor.
 * Used for: vehicle.km_kademeleri (min_gun, gunluk_km),
 *           vehicle.sure_indirim_kademeleri (min_gun, indirim_tutar),
 *           settings.km_hacim_indirim_kademeleri (min_km, indirim_tutar).
 */
/**
 * 3-column price bracket editor. Used for vehicle.gunluk_fiyat_kademeleri.
 * Each row: {min_gun, max_gun (optional, null = ∞), gunluk_fiyat}
 */
/**
 * Reusable 3-column range bracket editor.
 * Each row: { min_gun, max_gun (null=∞), [valueKey]: number }
 */
function RangeBracketEditor({ rows, onChange, valueKey, valueLabel, valueSuffix, valueKb, addLabel }: {
  rows: any[]; onChange: (rows: any[]) => void;
  valueKey: string; valueLabel: string; valueSuffix: string;
  valueKb?: any; addLabel?: string;
}) {
  const list = Array.isArray(rows) ? rows : [];
  const update = (i: number, key: string, val: number | null) => {
    const next = list.map((r, idx) => idx === i ? { ...r, [key]: val } : r);
    onChange(next);
  };
  const removeAt = (i: number) => onChange(list.filter((_, idx) => idx !== i));
  const add = () => onChange([...list, { min_gun: (list[list.length - 1]?.max_gun || 0) + 1, max_gun: null, [valueKey]: 0 }]);
  const sorted = [...list].sort((a, b) => (a.min_gun || 0) - (b.min_gun || 0));
  return (
    <View style={{ gap: 8 }}>
      <View style={{ flexDirection: 'row', gap: 6, paddingHorizontal: 4 }}>
        <Text style={{ flex: 1, ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>Min Gün</Text>
        <Text style={{ flex: 1, ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>Max Gün</Text>
        <Text style={{ flex: 1.2, ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>{valueLabel}</Text>
        <View style={{ width: 36 }} />
      </View>
      {sorted.length === 0 && (
        <Text style={{ ...Typography.caption, color: Colors.text.tertiary, fontStyle: 'italic', paddingVertical: 4 }}>
          Kademe yok — varsayılan tüm sürelere uygulanır.
        </Text>
      )}
      {sorted.map((r, _i) => {
        const realIdx = list.indexOf(r);
        return (
          <View key={realIdx} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
            <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 8 }}>
              <TextInput
                value={String(r.min_gun ?? 0)}
                onChangeText={(x) => update(realIdx, 'min_gun', parseInt(x.replace(/\D/g, '') || '0', 10))}
                keyboardType="number-pad"
                style={{ flex: 1, paddingVertical: 10, color: Colors.text.primary, fontSize: 14 }}
              />
            </View>
            <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 8 }}>
              <TextInput
                value={r.max_gun == null ? '' : String(r.max_gun)}
                onChangeText={(x) => {
                  const clean = x.replace(/\D/g, '');
                  update(realIdx, 'max_gun', clean === '' ? null : parseInt(clean, 10));
                }}
                placeholder="∞"
                placeholderTextColor={Colors.text.tertiary}
                keyboardType="number-pad"
                style={{ flex: 1, paddingVertical: 10, color: Colors.text.primary, fontSize: 14 }}
              />
            </View>
            <View style={{ flex: 1.2, flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 8 }}>
              <TextInput
                value={String(r[valueKey] ?? 0)}
                onChangeText={(x) => {
                  const clean = x.replace(/[^\d.]/g, '');
                  const parsed = valueKb === 'number-pad' ? parseInt(clean || '0', 10) : parseFloat(clean || '0');
                  update(realIdx, valueKey, parsed);
                }}
                keyboardType={valueKb || 'decimal-pad'}
                style={{ flex: 1, paddingVertical: 10, color: Colors.text.primary, fontSize: 14 }}
              />
              <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{valueSuffix}</Text>
            </View>
            <Pressable onPress={() => removeAt(realIdx)} style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name="trash" size={14} color={Colors.status.error} />
            </Pressable>
          </View>
        );
      })}
      <Pressable onPress={add} style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 10, borderRadius: Radius.md, backgroundColor: Colors.bg.glassRed, borderWidth: 1, borderColor: Colors.border.accent }}>
        <Ionicons name="add" size={16} color={Colors.brand.primary} />
        <Text style={{ ...Typography.caption, color: Colors.brand.primary, fontWeight: '700' }}>{addLabel || 'KADEME EKLE'}</Text>
      </Pressable>
      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, fontStyle: 'italic', paddingTop: 2 }}>
        💡 Max Gün boş bırakılırsa sonsuza kadar geçerlidir.
      </Text>
    </View>
  );
}

function PriceBracketEditor({ rows, onChange }: { rows: any[]; onChange: (rows: any[]) => void }) {
  return <RangeBracketEditor rows={rows} onChange={onChange} valueKey="gunluk_fiyat" valueLabel="Günlük Fiyat" valueSuffix="₺" addLabel="FİYAT KADEMESİ EKLE" />;
}

function KmBracketEditor({ rows, onChange }: { rows: any[]; onChange: (rows: any[]) => void }) {
  return <RangeBracketEditor rows={rows} onChange={onChange} valueKey="gunluk_km" valueLabel="Günlük KM" valueSuffix="km" valueKb="number-pad" addLabel="KM KADEMESİ EKLE" />;
}

function KmAsimBracketEditor({ rows, onChange }: { rows: any[]; onChange: (rows: any[]) => void }) {
  return <RangeBracketEditor rows={rows} onChange={onChange} valueKey="km_asim_fiyat" valueLabel="₺/km" valueSuffix="₺/km" addLabel="KM AŞIM KADEMESİ EKLE" />;
}

function BracketEditor({
  rows, onChange, leftKey, rightKey, leftLabel, rightLabel, leftSuffix, rightSuffix, addLabel,
}: {
  rows: any[];
  onChange: (rows: any[]) => void;
  leftKey: string; rightKey: string;
  leftLabel: string; rightLabel: string;
  leftSuffix?: string; rightSuffix?: string;
  addLabel?: string;
}) {
  const list = Array.isArray(rows) ? rows : [];
  const updateAt = (i: number, key: string, val: number) => {
    const next = list.map((r, idx) => idx === i ? { ...r, [key]: val } : r);
    onChange(next);
  };
  const removeAt = (i: number) => onChange(list.filter((_, idx) => idx !== i));
  const add = () => onChange([...list, { [leftKey]: 0, [rightKey]: 0 }]);
  // Sort by left
  const sorted = [...list].sort((a, b) => (a[leftKey] || 0) - (b[leftKey] || 0));
  return (
    <View style={{ gap: 8 }}>
      <View style={{ flexDirection: 'row', gap: 6, paddingHorizontal: 4 }}>
        <Text style={{ flex: 1, ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>{leftLabel}</Text>
        <Text style={{ flex: 1, ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>{rightLabel}</Text>
        <View style={{ width: 36 }} />
      </View>
      {sorted.length === 0 && (
        <Text style={{ ...Typography.caption, color: Colors.text.tertiary, fontStyle: 'italic', paddingVertical: 4 }}>
          Kademe eklenmemiş — varsayılan kurallar uygulanır.
        </Text>
      )}
      {sorted.map((r, i) => (
        <View key={i} style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 8 }}>
            <TextInput
              value={String(r[leftKey] ?? 0)}
              onChangeText={(x) => updateAt(list.indexOf(r), leftKey, parseInt(x.replace(/\D/g, '') || '0', 10))}
              keyboardType="number-pad"
              style={{ flex: 1, paddingVertical: 10, color: Colors.text.primary, fontSize: 14 }}
              placeholderTextColor={Colors.text.tertiary}
            />
            {!!leftSuffix && <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{leftSuffix}</Text>}
          </View>
          <View style={{ flex: 1, flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base, paddingHorizontal: 8 }}>
            <TextInput
              value={String(r[rightKey] ?? 0)}
              onChangeText={(x) => updateAt(list.indexOf(r), rightKey, parseFloat(x.replace(/[^\d.]/g, '') || '0'))}
              keyboardType="decimal-pad"
              style={{ flex: 1, paddingVertical: 10, color: Colors.text.primary, fontSize: 14 }}
              placeholderTextColor={Colors.text.tertiary}
            />
            {!!rightSuffix && <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{rightSuffix}</Text>}
          </View>
          <Pressable onPress={() => removeAt(list.indexOf(r))} style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, alignItems: 'center', justifyContent: 'center' }}>
            <Ionicons name="trash" size={14} color={Colors.status.error} />
          </Pressable>
        </View>
      ))}
      <Pressable onPress={add} style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 10, borderRadius: Radius.md, backgroundColor: Colors.bg.glassRed, borderWidth: 1, borderColor: Colors.border.accent }}>
        <Ionicons name="add" size={16} color={Colors.brand.primary} />
        <Text style={{ ...Typography.caption, color: Colors.brand.primary, fontWeight: '700' }}>{addLabel || 'KADEME EKLE'}</Text>
      </Pressable>
    </View>
  );
}

// ==================== ADMIN KULLANICILAR ====================
type AdminUser = { id: string; ad: string; soyad?: string; tc_norm?: string; telefon?: string; email?: string; kullanici_adi?: string; created_at?: string };

function AdminsTab({ currentUserId }: { currentUserId?: string }) {
  const [list, setList] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [form, setForm] = useState({ ad: '', soyad: '', tc: '', telefon: '', email: '' });

  const load = async () => {
    setLoading(true);
    try { const r = await adminApi.listAdmins(); setList(r); }
    catch (e: any) { Alert.alert('Hata', e.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const openNew = () => {
    setEditing(null);
    setForm({ ad: '', soyad: '', tc: '', telefon: '', email: '' });
    setOpen(true);
  };
  const openEdit = (a: AdminUser) => {
    setEditing(a);
    setForm({ ad: a.ad || '', soyad: a.soyad || '', tc: a.tc_norm || '', telefon: a.telefon || '', email: a.email || '' });
    setOpen(true);
  };
  const submit = async () => {
    if (!form.ad.trim() || !form.soyad.trim()) { Alert.alert('Eksik', 'Ad ve soyad zorunlu'); return; }
    if (form.tc.replace(/\D/g, '').length !== 11) { Alert.alert('Eksik', 'TC 11 haneli olmalı'); return; }
    try {
      if (editing) await adminApi.updateAdmin(editing.id, form);
      else await adminApi.createAdmin(form);
      setOpen(false);
      load();
    } catch (e: any) { Alert.alert('Hata', e.message); }
  };
  const remove = (a: AdminUser) => {
    if (a.id === currentUserId) { Alert.alert('Bilgi', 'Kendi hesabınızı silemezsiniz'); return; }
    Alert.alert('Sil?', `${a.ad} ${a.soyad || ''} adlı yöneticiyi silmek istiyor musunuz?`, [
      { text: 'Vazgeç' },
      { text: 'Sil', style: 'destructive', onPress: async () => {
        try { await adminApi.deleteAdmin(a.id); load(); }
        catch (e: any) { Alert.alert('Hata', e.message); }
      } }
    ]);
  };

  return (
    <ScrollView contentContainerStyle={{ padding: Spacing.lg, gap: Spacing.md }} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={Colors.text.primary} />}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: Spacing.sm }}>
        <View>
          <Text style={{ ...Typography.h3, color: Colors.text.primary }}>Yönetici Kullanıcılar</Text>
          <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>Bu listedeki kişiler Ad+Soyad+TC ile yönetici olarak giriş yapabilir</Text>
        </View>
        <Pressable testID="admin-new" onPress={openNew} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 14, paddingVertical: 10, borderRadius: Radius.md, backgroundColor: Colors.brand.primary }}>
          <Ionicons name="add" size={16} color="#fff" />
          <Text style={{ color: '#fff', fontWeight: '700' }}>Yeni</Text>
        </Pressable>
      </View>

      {list.length === 0 && !loading && (
        <Text style={{ ...Typography.caption, color: Colors.text.tertiary, textAlign: 'center', marginTop: 24 }}>Henüz yönetici yok.</Text>
      )}

      {list.map(a => (
        <View key={a.id} style={{ backgroundColor: Colors.bg.surface, borderRadius: Radius.lg, padding: Spacing.md, borderWidth: 1, borderColor: Colors.border.base }}>
          <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
            <View style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: Colors.brand.primary + '22', alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name="shield-checkmark" size={22} color={Colors.brand.primary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{a.ad} {a.soyad || ''}{a.id === currentUserId && <Text style={{ ...Typography.micro, color: Colors.brand.primary }}>  (siz)</Text>}</Text>
              <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>TC: {a.tc_norm || '—'}</Text>
              {!!a.telefon && <Text style={{ ...Typography.caption, color: Colors.text.tertiary }}>{a.telefon}</Text>}
              {!!a.email && <Text style={{ ...Typography.caption, color: Colors.text.tertiary }}>{a.email}</Text>}
            </View>
            <Pressable onPress={() => openEdit(a)} style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base }}>
              <Ionicons name="pencil" size={14} color={Colors.text.primary} />
            </Pressable>
            <Pressable onPress={() => remove(a)} style={{ width: 36, height: 36, borderRadius: 18, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base }}>
              <Ionicons name="trash" size={14} color={Colors.status.error} />
            </Pressable>
          </View>
        </View>
      ))}

      <Modal visible={open} animationType="slide" transparent onRequestClose={() => setOpen(false)}>
        <View style={{ flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(0,0,0,0.5)' }}>
          <View style={{ backgroundColor: Colors.bg.surface, borderTopLeftRadius: 20, borderTopRightRadius: 20, padding: Spacing.lg, maxHeight: '90%' }}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: Spacing.md }}>
              <Text style={{ ...Typography.h3, color: Colors.text.primary }}>{editing ? 'Yöneticiyi Düzenle' : 'Yeni Yönetici'}</Text>
              <Pressable onPress={() => setOpen(false)}><Ionicons name="close" size={22} color={Colors.text.primary} /></Pressable>
            </View>
            <ScrollView>
              <View style={{ gap: Spacing.sm }}>
                <Field label="Ad *" v={form.ad} on={(x) => setForm({ ...form, ad: x })} />
                <Field label="Soyad *" v={form.soyad} on={(x) => setForm({ ...form, soyad: x })} />
                <Field label="TC Kimlik No (11 hane) *" v={form.tc} on={(x) => setForm({ ...form, tc: x.replace(/\D/g, '').slice(0, 11) })} kb="number-pad" />
                <Field label="Telefon" v={form.telefon} on={(x) => setForm({ ...form, telefon: x })} kb="phone-pad" />
                <Field label="E-posta" v={form.email} on={(x) => setForm({ ...form, email: x })} />
              </View>
              <Pressable onPress={submit} style={{ marginTop: Spacing.lg, backgroundColor: Colors.brand.primary, paddingVertical: 14, borderRadius: Radius.md, alignItems: 'center' }}>
                <Text style={{ color: '#fff', fontWeight: '700' }}>{editing ? 'Güncelle' : 'Oluştur'}</Text>
              </Pressable>
            </ScrollView>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}


const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: Colors.bg.base },
  topBar: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: Spacing.xl, paddingVertical: Spacing.md, borderBottomWidth: 1, borderBottomColor: Colors.border.base },
  adminTitle: { ...Typography.h2, color: Colors.text.primary },
  adminSub: { ...Typography.caption, color: Colors.text.secondary },
  logoutBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: Colors.bg.surface, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base },
  tabBar: { paddingVertical: Spacing.md, maxHeight: 56, flexGrow: 0 },
  tabBtn: { flexDirection: 'row', alignItems: 'center', gap: 6, paddingHorizontal: Spacing.lg, paddingVertical: 8, borderRadius: Radius.pill, backgroundColor: Colors.bg.surface, borderWidth: 1, borderColor: Colors.border.base },
  tabBtnActive: { backgroundColor: Colors.brand.primary, borderColor: Colors.brand.primary },
  tabBtnText: { ...Typography.caption, color: Colors.text.secondary, fontWeight: '600' },
  tabBtnTextActive: { color: '#fff' },
  statsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.md },
  statCard: { width: '47%', alignItems: 'flex-start', padding: Spacing.lg },
  statIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center', borderWidth: 1, marginBottom: Spacing.sm },
  statVal: { fontSize: 28, fontWeight: '900', color: Colors.text.primary },
  statLabel: { ...Typography.caption, color: Colors.text.secondary, marginTop: 2 },
  input: { backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, padding: Spacing.md, color: Colors.text.primary, borderWidth: 1, borderColor: Colors.border.base, fontSize: 14 },
  fab: { width: 48, height: 48, borderRadius: 24, backgroundColor: Colors.brand.primary, alignItems: 'center', justifyContent: 'center' },
  iconBtn: { width: 32, height: 32, borderRadius: 16, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center' },
  orderBtn: { width: 32, height: 28, borderRadius: 8, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, alignItems: 'center', justifyContent: 'center' },
  miniBtn: { paddingHorizontal: Spacing.md, paddingVertical: 6, borderRadius: Radius.pill, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, alignItems: 'center', justifyContent: 'center' },
  miniBtnActive: { backgroundColor: Colors.brand.primary, borderColor: Colors.brand.primary },
  miniBtnText: { fontSize: 11, fontWeight: '600', color: Colors.text.secondary },
  modalBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'flex-end' },
  modalCard: { backgroundColor: Colors.bg.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: Spacing.xl, gap: Spacing.sm, borderTopWidth: 1, borderColor: Colors.border.base, maxHeight: '90%' },
  modalTitle: { ...Typography.h2, color: Colors.text.primary },
  checkRow: { flexDirection: 'row', alignItems: 'center', gap: 8, padding: 8, borderRadius: 8, backgroundColor: Colors.bg.surface2, marginVertical: 2, borderWidth: 1, borderColor: Colors.border.base },
});
