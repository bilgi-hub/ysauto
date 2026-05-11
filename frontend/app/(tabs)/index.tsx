/**
 * Ana Sayfa - YS AUTO (custom red banner hero + horizontal vehicle list)
 */
import React, { useEffect, useState, useCallback } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, Image, Pressable, Platform, ActivityIndicator, FlatList } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useRouter, useFocusEffect } from 'expo-router';
import { Ionicons, MaterialCommunityIcons } from '@expo/vector-icons';
import VehicleImageSlider from '../../src/VehicleImageSlider';
import { customerApi, auth, Vehicle } from '../../src/api';
import { Colors, Radius, Spacing, Typography } from '../../src/theme';
import { StatusBadge } from '../../src/ui';

const { width: SCREEN_W } = require('react-native').Dimensions.get('window');

export default function HomeScreen() {
  const router = useRouter();
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [user, setUser] = useState<{ ad: string; soyad: string; bakiye?: number } | null>(null);
  const [bakiye, setBakiye] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<'tum' | 'musait'>('tum');

  const load = useCallback(async () => {
    try {
      const [data, stored, w] = await Promise.all([
        customerApi.vehicles(),
        auth.getStored(),
        customerApi.wallet().catch(() => ({ bakiye: 0 })),
      ]);
      setVehicles(data);
      if (stored?.user) setUser({ ad: stored.user.ad, soyad: stored.user.soyad });
      setBakiye(w.bakiye || 0);
    } catch {} finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  const onRefresh = () => { setRefreshing(true); load(); };
  const filtered = filter === 'musait' ? vehicles.filter(v => v.durum === 'musait') : vehicles;
  const cardWidth = Math.min(280, SCREEN_W * 0.72);

  return (
    <View style={styles.bg}>
      <SafeAreaView style={{ flex: 1 }} edges={['top']}>
        <ScrollView
          contentContainerStyle={{ paddingBottom: 120 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={Colors.brand.primary} />}
          showsVerticalScrollIndicator={false}
        >
          {/* Header */}
          <View style={styles.header}>
            <View style={{ flexDirection: 'row', alignItems: 'center', flex: 1, gap: 10 }}>
              <View style={styles.avatar}>
                <Text style={styles.avatarLetter}>{(user?.ad?.[0] || 'Y').toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.greeting}>Merhaba 👋</Text>
                <Text style={styles.username} numberOfLines={1} testID="header-username">
                  {user ? `${user.ad} ${user.soyad}`.toLowerCase() : ''}
                </Text>
              </View>
            </View>
            {/* Cüzdanım pill — kullanıcı adının yanında, tıklanınca cüzdana gider */}
            <Pressable
              testID="wallet-pill"
              onPress={() => router.push('/wallet')}
              style={styles.walletPill}
            >
              <View style={styles.walletPillIcon}>
                <Ionicons name="wallet" size={16} color={Colors.brand.primary} />
              </View>
              <View>
                <Text style={styles.walletPillLabel}>Cüzdanım</Text>
                <Text style={styles.walletPillValue}>{bakiye.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺</Text>
              </View>
            </Pressable>
            <Pressable
              testID="logout-btn"
              onPress={async () => { await auth.logout(); router.replace('/login'); }}
              style={styles.logoutBtn}
            >
              <Ionicons name="log-out-outline" size={20} color={Colors.text.primary} />
            </Pressable>
          </View>

          {/* RED BANNER HERO */}
          <Pressable onPress={() => router.push('/wallet')}>
            <View style={styles.heroWrap}>
              <View style={styles.heroRedBg}>
                <View style={styles.heroRedShape} />
                <View style={styles.heroDarkBottom} />
              </View>
              <View style={styles.heroContent}>
                <View style={{ flex: 1 }}>
                  <View style={styles.heroLogoRow}>
                    <Text style={styles.heroLabelSmall}>YS AUTO</Text>
                    <Image source={require('../../assets/images/logo.jpeg')} style={styles.heroLogoBadge} resizeMode="cover" />
                  </View>
                  <Text style={styles.heroTitle}>Yola Çıkmaya Hazır mısınız?</Text>
                  <Text style={styles.heroSub}>{vehicles.filter(v => v.durum === 'musait').length} araç müsait</Text>
                </View>
                <View style={styles.heroIcon}>
                  <Ionicons name="car-sport" size={36} color={Colors.brand.primary} />
                </View>
              </View>
            </View>
          </Pressable>

          {/* Filter chips */}
          <View style={styles.filterRow}>
            <Pressable onPress={() => setFilter('tum')} style={[styles.chip, filter === 'tum' && styles.chipActive]} testID="filter-all">
              <Text style={[styles.chipText, filter === 'tum' && styles.chipTextActive]}>Tümü ({vehicles.length})</Text>
            </Pressable>
            <Pressable onPress={() => setFilter('musait')} style={[styles.chip, filter === 'musait' && styles.chipActive]} testID="filter-available">
              <Text style={[styles.chipText, filter === 'musait' && styles.chipTextActive]}>Müsait ({vehicles.filter(v => v.durum === 'musait').length})</Text>
            </Pressable>
          </View>

          <View style={styles.sectionTitleRow}>
            <View>
              <Text style={styles.sectionTitle}>Araç Filomuz</Text>
              <Text style={styles.sectionSubtitle}>Aracı seçin, rezervasyon yapın</Text>
            </View>
          </View>

          {loading ? (
            <View style={{ paddingVertical: 60, alignItems: 'center' }}>
              <ActivityIndicator color={Colors.brand.primary} />
            </View>
          ) : filtered.length === 0 ? (
            <View style={{ paddingVertical: 60, alignItems: 'center' }}>
              <Ionicons name="car-outline" size={48} color={Colors.text.tertiary} />
              <Text style={{ ...Typography.h4, color: Colors.text.primary, marginTop: 12 }}>Araç bulunamadı</Text>
            </View>
          ) : (
            <FlatList
              horizontal
              data={filtered}
              keyExtractor={(v) => v.id}
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={{ paddingHorizontal: Spacing.xl, gap: Spacing.md }}
              snapToInterval={cardWidth + Spacing.md}
              decelerationRate="fast"
              renderItem={({ item }) => (
                <VehicleCard
                  v={item}
                  width={cardWidth}
                  onPress={() => router.push(`/vehicle/${item.id}`)}
                />
              )}
            />
          )}
        </ScrollView>
      </SafeAreaView>
    </View>
  );
}

function VehicleCard({ v, onPress, width }: { v: Vehicle; onPress: () => void; width: number }) {
  return (
    <Pressable testID={`vehicle-card-${v.id}`} onPress={onPress} style={({ pressed }) => [{ width }, styles.card, pressed && { opacity: 0.85, transform: [{ scale: 0.98 }] }]}>
      <View style={styles.cardImageWrap}>
        <Image source={{ uri: v.foto_url || 'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?w=600' }} style={styles.cardImage} resizeMode="cover" />
        <View style={styles.cardImageOverlay} />
        <View style={styles.cardBadgeWrap}>
          <StatusBadge status={v.durum} />
        </View>
      </View>
      <View style={styles.cardBody}>
        <Text style={styles.cardBrand}>{v.marka}</Text>
        <Text style={styles.cardModel} numberOfLines={1}>{v.model}</Text>
        <View style={styles.cardMetaRow}>
          <View style={styles.metaPill}>
            <MaterialCommunityIcons name="car-shift-pattern" size={11} color={Colors.text.secondary} />
            <Text style={styles.metaText}>{v.vites}</Text>
          </View>
          <View style={styles.metaPill}>
            <MaterialCommunityIcons name="fuel" size={11} color={Colors.text.secondary} />
            <Text style={styles.metaText}>{v.yakit}</Text>
          </View>
          {(v.ekstra_ozellikler || []).slice(0, 1).map((o, i) => (
            <View key={i} style={styles.metaPill}>
              <Ionicons name="star-outline" size={11} color={Colors.text.secondary} />
              <Text style={styles.metaText}>{o}</Text>
            </View>
          ))}
        </View>
        <View style={styles.priceRow}>
          <Ionicons name="pricetag-outline" size={14} color={Colors.text.secondary} />
          <Text style={styles.priceLabel}>Günlük</Text>
          <Text style={styles.priceValue}>{v.gunluk_fiyat.toLocaleString('tr-TR')} TL</Text>
        </View>
        <View style={styles.kmRow}>
          <Ionicons name="speedometer-outline" size={14} color={Colors.text.secondary} />
          <Text style={styles.kmLabel}>Günlük Km: <Text style={styles.kmValue}>{v.gunluk_km} Km</Text></Text>
        </View>
        <View style={styles.cardCta}>
          <Text style={styles.ctaText}>{v.durum === 'musait' ? 'REZERVE ET' : 'DETAYLAR'}</Text>
          <Ionicons name="arrow-forward" size={14} color="#fff" />
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: Colors.bg.base },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: Spacing.xl, paddingTop: Spacing.lg, paddingBottom: Spacing.md, gap: 8 },
  avatar: { width: 44, height: 44, borderRadius: 22, backgroundColor: Colors.bg.surface, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base },
  avatarLetter: { fontSize: 18, color: Colors.brand.primary, fontWeight: '900' },
  greeting: { ...Typography.caption, color: Colors.text.secondary },
  username: { ...Typography.h2, color: Colors.text.primary, marginTop: 2, textTransform: 'lowercase' },
  logoutBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: Colors.bg.surface, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base },

  heroWrap: { marginHorizontal: Spacing.xl, height: 180, borderRadius: Radius.xl, overflow: 'hidden', backgroundColor: '#1a0a0a', borderWidth: 1, borderColor: Colors.border.base, marginTop: Spacing.sm },
  heroRedBg: { ...StyleSheet.absoluteFillObject },
  heroRedShape: { position: 'absolute', top: 0, left: 0, right: 0, height: '70%', backgroundColor: Colors.brand.primary, borderBottomLeftRadius: 80, borderBottomRightRadius: 200 },
  heroDarkBottom: { position: 'absolute', bottom: 0, left: 0, right: 0, height: '40%', backgroundColor: 'rgba(0,0,0,0.85)' },
  heroContent: { flex: 1, flexDirection: 'row', padding: Spacing.xl, alignItems: 'center', zIndex: 2 },
  heroLogoRow: { flexDirection: 'row', alignItems: 'center', gap: 8 },
  heroLabelSmall: { ...Typography.micro, color: '#fff', letterSpacing: 2, opacity: 0.8 },
  heroLogoBadge: { width: 26, height: 26, borderRadius: 13, backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center' },
  heroLogoText: { fontSize: 11, fontWeight: '900', color: Colors.brand.primary, letterSpacing: -0.5 },
  heroTitle: { ...Typography.h2, color: '#fff', marginTop: 6, lineHeight: 30 },
  heroSub: { ...Typography.caption, color: 'rgba(255,255,255,0.75)', marginTop: 8 },
  heroIcon: { width: 80, height: 80, borderRadius: 40, backgroundColor: 'rgba(0,0,0,0.4)', alignItems: 'center', justifyContent: 'center', borderWidth: 2, borderColor: 'rgba(255,255,255,0.1)' },

  walletCard: { flexDirection: 'row', alignItems: 'center', gap: 12, marginHorizontal: Spacing.xl, marginTop: Spacing.md, padding: Spacing.lg, backgroundColor: Colors.bg.surface, borderRadius: Radius.lg, borderWidth: 1, borderColor: Colors.border.base },
  walletIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: Colors.bg.glassRed, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.accent },
  walletLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' },
  walletValue: { ...Typography.h3, color: Colors.text.primary, fontWeight: '800', marginTop: 2 },
  walletAction: { flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: Spacing.md, paddingVertical: 8, borderRadius: Radius.pill, backgroundColor: Colors.bg.glassRed, borderWidth: 1, borderColor: Colors.border.accent },
  walletActionText: { ...Typography.micro, color: Colors.brand.primary, fontWeight: '700' },
  // Yeni: Header'da kullanıcı adının yanında küçük "Cüzdanım" pill
  walletPill: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingLeft: 8, paddingRight: 12, paddingVertical: 6,
    borderRadius: Radius.pill,
    backgroundColor: Colors.bg.glassRed,
    borderWidth: 1, borderColor: Colors.border.accent,
    marginRight: 8,
  },
  walletPillIcon: {
    width: 28, height: 28, borderRadius: 14,
    backgroundColor: Colors.bg.surface,
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 1, borderColor: Colors.border.accent,
  },
  walletPillLabel: { ...Typography.micro, color: Colors.brand.primary, fontWeight: '800', textTransform: 'uppercase', fontSize: 9, letterSpacing: 0.4 },
  walletPillValue: { ...Typography.bodyBold, color: Colors.text.primary, fontSize: 13, lineHeight: 16, marginTop: 0 },

  filterRow: { flexDirection: 'row', gap: Spacing.sm, paddingHorizontal: Spacing.xl, marginTop: Spacing.lg },
  chip: { paddingHorizontal: Spacing.lg, paddingVertical: 8, borderRadius: Radius.pill, backgroundColor: Colors.bg.surface, borderWidth: 1, borderColor: Colors.border.base },
  chipActive: { backgroundColor: Colors.brand.primary, borderColor: Colors.brand.primary },
  chipText: { ...Typography.caption, color: Colors.text.secondary, fontWeight: '600' },
  chipTextActive: { color: '#fff' },

  sectionTitleRow: { paddingHorizontal: Spacing.xl, marginTop: Spacing.xl, marginBottom: Spacing.md },
  sectionTitle: { ...Typography.h2, color: Colors.text.primary },
  sectionSubtitle: { ...Typography.caption, color: Colors.text.secondary, marginTop: 2 },

  card: { backgroundColor: Colors.bg.surface, borderRadius: Radius.lg, overflow: 'hidden', borderWidth: 1, borderColor: Colors.border.base },
  cardImageWrap: { aspectRatio: 16 / 10, position: 'relative', backgroundColor: Colors.bg.surface2 },
  cardImage: { width: '100%', height: '100%' },
  cardImageOverlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.15)' },
  cardBadgeWrap: { position: 'absolute', top: 8, right: 8 },
  cardBody: { padding: Spacing.md },
  cardBrand: { ...Typography.micro, color: Colors.text.secondary, letterSpacing: 1 },
  cardModel: { ...Typography.h3, color: Colors.text.primary, marginTop: 2 },
  cardMetaRow: { flexDirection: 'row', gap: 4, marginTop: 8, flexWrap: 'wrap' },
  metaPill: { flexDirection: 'row', alignItems: 'center', gap: 3, backgroundColor: Colors.bg.surface2, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 8 },
  metaText: { fontSize: 11, color: Colors.text.secondary, fontWeight: '600' },
  priceRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 10 },
  priceLabel: { ...Typography.caption, color: Colors.text.secondary, flex: 1 },
  priceValue: { ...Typography.h4, color: Colors.brand.primary, fontWeight: '900' },
  kmRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 4 },
  kmLabel: { ...Typography.caption, color: Colors.text.secondary },
  kmValue: { color: Colors.text.primary, fontWeight: '700' },
  cardCta: { marginTop: Spacing.md, height: 40, borderRadius: Radius.pill, backgroundColor: Colors.brand.primary, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6 },
  ctaText: { fontSize: 12, color: '#fff', fontWeight: '800', letterSpacing: 1 },
});
