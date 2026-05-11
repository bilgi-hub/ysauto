/**
 * Kira Geçmişim - Active rental + past rentals
 */
import React, { useCallback, useState, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, Image, Pressable, Alert, TextInput, Modal, ActivityIndicator, KeyboardAvoidingView, Platform, Keyboard, TouchableWithoutFeedback } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useRouter, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import ZoomableImage from '../../src/ZoomableImage';
import { customerApi, Reservation, Vehicle } from '../../src/api';
import { Colors, Radius, Spacing, Typography } from '../../src/theme';
import { GlassCard, GlassButton, StatusBadge, Empty, SectionTitle } from '../../src/ui';
import { DateTimePicker, Availability } from '../../src/DateTimePicker';

const PENDING_EXTEND_KEY = 'ys_pending_extend';

function fmtDate(s: string) {
  try {
    const d = new Date(s);
    return d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' });
  } catch { return s; }
}
function fmtDateTime(s: string) {
  try {
    const d = new Date(s);
    const date = d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' });
    const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
    return `${date} • ${time}`;
  } catch { return s; }
}
function fmtTime(s: string) {
  try {
    const d = new Date(s);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch { return ''; }
}
function fmtCountdown(seconds: number) {
  if (seconds <= 0) return '0s';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d} gün ${h} saat`;
  if (h > 0) return `${h} saat ${m} dk`;
  return `${m} dakika`;
}

export default function RentalsScreen() {
  const router = useRouter();
  const [active, setActive] = useState<Reservation | null>(null);
  const [list, setList] = useState<Reservation[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [extendOpen, setExtendOpen] = useState(false);
  const [extendNewEnd, setExtendNewEnd] = useState<Date | null>(null);
  const [extendAvailability, setExtendAvailability] = useState<Availability | null>(null);
  const [extendQuote, setExtendQuote] = useState<{ ek_gun: number; ek_tutar: number; ek_indirim: number; ek_arac_tutar?: number; ek_hizmet_tutar?: number; ek_km_satin?: number; ek_km_tutar?: number; km_asim_fiyat?: number; yeni_gunluk_fiyat?: number; eski_gunluk_fiyat?: number; yeni_paket_km?: number; fiyat_kademe?: { min_gun: number; max_gun: number | null; gunluk_fiyat: number } | null; km_asim_kademe?: { min_gun: number; max_gun: number | null; km_asim_fiyat: number } | null; bakiye: number; bakiye_yeterli: boolean; eksik: number } | null>(null);
  const [extendBlocked, setExtendBlocked] = useState<{ reason: string; message: string } | null>(null);
  const [extendAlternatives, setExtendAlternatives] = useState<Vehicle[] | null>(null);
  const [extendLoading, setExtendLoading] = useState(false);
  const [extendEkKm, setExtendEkKm] = useState<string>('0');  // (legacy, artık kullanılmıyor)
  const [extendKmFiyat, setExtendKmFiyat] = useState<number>(8); // ₺/km, public settings'ten gelir

  // Ek KM Satın Alma (uzatmadan bağımsız)
  const [buyKmOpen, setBuyKmOpen] = useState(false);
  const [buyKmInput, setBuyKmInput] = useState<string>('100');
  const [buyKmQuoteRes, setBuyKmQuoteRes] = useState<{ ek_km: number; tutar: number; brut_tutar?: number; indirim_tutar?: number; km_asim_fiyat: number; km_asim_baz?: number; km_asim_kademe?: { min_gun: number; max_gun: number | null; km_asim_fiyat: number } | null; km_asim_kademeleri?: { min_gun: number; max_gun: number | null; km_asim_fiyat: number }[]; gun_sayisi?: number; bakiye: number; bakiye_yeterli: boolean; eksik: number; mevcut_paket_km: number } | null>(null);
  const [buyKmLoading, setBuyKmLoading] = useState(false);
  const [paymentOpen, setPaymentOpen] = useState(false);
  const [payRef, setPayRef] = useState('');
  const [payNote, setPayNote] = useState('');
  const [payLoading, setPayLoading] = useState(false);
  const [previewPhoto, setPreviewPhoto] = useState<string | null>(null);
  const [paymentTargetId, setPaymentTargetId] = useState<string | null>(null);
  const [reviewedIds, setReviewedIds] = useState<Set<string>>(new Set());
  const [walletBakiye, setWalletBakiye] = useState<number>(0);

  const load = useCallback(async () => {
    try {
      const [a, all, myReviews, w] = await Promise.all([
        customerApi.activeReservation(),
        customerApi.reservations(),
        customerApi.myReviews().catch(() => []),
        customerApi.wallet().catch(() => ({ bakiye: 0 })),
      ]);
      setActive(a);
      setList(all);
      setReviewedIds(new Set((myReviews || []).map((m: any) => m.reservation_id)));
      setWalletBakiye(Number(w?.bakiye || 0));
    } catch (e: any) {
      console.warn('rentals error', e?.message);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Extend modal'ı açıldığında: aracın müsaitliğini ve default yeni iade tarihini set et
  const openExtendModal = async () => {
    if (!active) return;
    setExtendOpen(true);
    setExtendBlocked(null);
    setExtendAlternatives(null);
    setExtendQuote(null);
    setExtendEkKm('0');
    // Default yeni iade = mevcut + 1 gün, saat aynı
    const def = new Date(active.bitis_tarihi);
    def.setDate(def.getDate() + 1);
    setExtendNewEnd(def);
    try {
      const [av, settings] = await Promise.all([
        customerApi.vehicleAvailability(active.vehicle_id),
        customerApi.publicSettings().catch(() => null),
      ]);
      setExtendAvailability(av);
      if (settings && (settings as any).km_asim_fiyat) {
        setExtendKmFiyat(Number((settings as any).km_asim_fiyat) || 8);
      }

      // Eğer aracın mevcut bitiş+1 saat sonrasında BAŞKA bir aktif rezervasyon varsa,
      // hard limit göster + alternatif araçları proaktif yükle
      if (av && av.blocked_ranges) {
        const myEndMs = new Date(active.bitis_tarihi).getTime();
        let nextOther: Date | null = null;
        for (const r of av.blocked_ranges) {
          const rs = new Date(r.start);
          if (rs.getTime() > myEndMs && (!nextOther || rs < nextOther)) {
            nextOther = rs;
          }
        }
        if (nextOther) {
          // En geç uzatılabilir tarih = sonraki rezervasyonun başlangıcı - 1h tampon
          const maxExtendableMs = nextOther.getTime() - 60 * 60 * 1000;
          if (def.getTime() > maxExtendableMs) {
            // Default önerimiz hard limit'i aşıyor → uygulanabilir bir tarihe ayarla
            const safe = new Date(maxExtendableMs);
            // Aynı saat olmaya zorla
            safe.setHours(def.getHours(), def.getMinutes(), 0, 0);
            if (safe.getTime() > maxExtendableMs) {
              safe.setDate(safe.getDate() - 1);
            }
            if (safe > new Date(active.bitis_tarihi)) {
              setExtendNewEnd(safe);
            }
          }
        }
      }
    } catch {}
  };

  // Aracın bir sonraki başkasına ait rezervasyonu — uzatma için kesin hard limit
  const nextOtherRezStart: Date | null = (() => {
    if (!active || !extendAvailability?.blocked_ranges) return null;
    const myEndMs = new Date(active.bitis_tarihi).getTime();
    let earliest: Date | null = null;
    for (const r of extendAvailability.blocked_ranges) {
      const rs = new Date(r.start);
      if (rs.getTime() > myEndMs && (!earliest || rs < earliest)) {
        earliest = rs;
      }
    }
    return earliest;
  })();

  // Hard limit varsa, alternatif araçları ön-yükle (kullanıcı tarih seçmeden de görsün)
  useEffect(() => {
    if (!extendOpen || !active || !nextOtherRezStart) {
      return;
    }
    (async () => {
      try {
        const fromIso = active.bitis_tarihi;
        // Kullanıcının uzatmak isteyeceği makul aralık: mevcut bitiş → +7 gün veya nextOtherRezStart sonrası
        const probeEnd = new Date(Math.max(
          new Date(active.bitis_tarihi).getTime() + 7 * 24 * 60 * 60 * 1000,
          nextOtherRezStart.getTime() + 24 * 60 * 60 * 1000,
        ));
        const alts = await customerApi.availableVehicles({
          baslangic_tarihi: fromIso,
          bitis_tarihi: probeEnd.toISOString(),
          exclude_vehicle_id: active.vehicle_id,
        });
        if (alts.available && alts.available.length > 0) {
          setExtendAlternatives(alts.available);
        }
      } catch {}
    })();
  }, [extendOpen, active, nextOtherRezStart]);
  useEffect(() => {
    if (!extendOpen || !active || !extendNewEnd) return;
    const t = setTimeout(async () => {
      try {
        const q = await customerApi.extendQuote(active.id, extendNewEnd.toISOString(), [], 0);
        if (q.ok) {
          setExtendBlocked(null);
          setExtendQuote({
            ek_gun: q.ek_gun || 0,
            ek_tutar: q.ek_tutar || 0,
            ek_arac_tutar: q.ek_arac_tutar || 0,
            ek_hizmet_tutar: q.ek_hizmet_tutar || 0,
            ek_indirim: q.ek_indirim || 0,
            ek_km_satin: q.ek_km_satin || 0,
            ek_km_tutar: q.ek_km_tutar || 0,
            km_asim_fiyat: q.km_asim_fiyat || extendKmFiyat,
            yeni_gunluk_fiyat: q.yeni_gunluk_fiyat,
            eski_gunluk_fiyat: q.eski_gunluk_fiyat,
            yeni_paket_km: q.yeni_paket_km,
            fiyat_kademe: q.fiyat_kademe || null,
            km_asim_kademe: q.km_asim_kademe || null,
            bakiye: q.bakiye || 0,
            bakiye_yeterli: !!q.bakiye_yeterli,
            eksik: q.eksik || 0,
          });
          if (q.km_asim_fiyat) setExtendKmFiyat(q.km_asim_fiyat);
          setExtendAlternatives(null);
        } else {
          setExtendQuote(null);
          setExtendBlocked({ reason: q.blocked_reason || 'cakisma', message: q.message || 'Bu tarihe uzatılamaz' });
          // Çakışma ise alternatif araç ara
          if (q.blocked_reason === 'cakisma') {
            try {
              const fromIso = active.bitis_tarihi; // mevcut iade
              const toIso = extendNewEnd.toISOString(); // hedeflenen iade
              const alts = await customerApi.availableVehicles({
                baslangic_tarihi: fromIso,
                bitis_tarihi: toIso,
                exclude_vehicle_id: active.vehicle_id,
              });
              setExtendAlternatives(alts.available || []);
            } catch {
              setExtendAlternatives([]);
            }
          }
        }
      } catch (e: any) {
        setExtendBlocked({ reason: 'hata', message: e.message || 'Hata' });
      }
    }, 250);
    return () => clearTimeout(t);
  }, [extendOpen, active, extendNewEnd]);

  // AsyncStorage'da pending extend var mı? Cüzdan yüklemesi sonrası geri dönülmüşse kontrol et
  useFocusEffect(useCallback(() => {
    (async () => {
      try {
        const s = await AsyncStorage.getItem(PENDING_EXTEND_KEY);
        if (!s) return;
        const pending = JSON.parse(s);
        if (!pending?.rezervationId || !pending?.yeni_bitis_tarihi || !pending?.required) return;
        const w = await customerApi.wallet().catch(() => ({ bakiye: 0 }));
        if ((w.bakiye || 0) >= pending.required) {
          Alert.alert(
            'Bekleyen Süre Uzatma',
            `Bakiyeniz şimdi yeterli (${(w.bakiye || 0).toLocaleString('tr-TR')} ₺). ${pending.required.toLocaleString('tr-TR')} ₺'lik uzatma işlemini tamamlayalım mı?`,
            [
              { text: 'Vazgeç', onPress: () => AsyncStorage.removeItem(PENDING_EXTEND_KEY) },
              {
                text: 'Evet, Uzat',
                onPress: async () => {
                  try {
                    await customerApi.extend(pending.rezervationId, pending.yeni_bitis_tarihi, [], pending.ek_km || 0);
                    Alert.alert('Başarılı', 'Süre uzatıldı, ücret bakiyenizden tahsil edildi.');
                    AsyncStorage.removeItem(PENDING_EXTEND_KEY);
                    load();
                  } catch (e: any) {
                    Alert.alert('Hata', e.message);
                  }
                },
              },
            ],
          );
        }
      } catch {}
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []));

  const onExtend = async () => {
    if (!active || !extendNewEnd || !extendQuote) return;
    setExtendLoading(true);
    try {
      // Bakiye yetersizse cüzdana yönlendir + pending kaydet
      if (!extendQuote.bakiye_yeterli) {
        Alert.alert(
          'Bakiyeniz Yetersiz',
          `Uzatma için ${extendQuote.ek_tutar.toLocaleString('tr-TR')} ₺ gerekli. Mevcut bakiyeniz: ${extendQuote.bakiye.toLocaleString('tr-TR')} ₺. Eksik: ${extendQuote.eksik.toLocaleString('tr-TR')} ₺.\n\nÖnce cüzdanınıza bakiye yükleyin, ardından uzatma otomatik tamamlanacaktır.`,
          [
            { text: 'Vazgeç', style: 'cancel' },
            {
              text: 'Bakiye Yükle',
              onPress: async () => {
                await AsyncStorage.setItem(PENDING_EXTEND_KEY, JSON.stringify({
                  rezervationId: active.id,
                  yeni_bitis_tarihi: extendNewEnd.toISOString(),
                  required: extendQuote.ek_tutar,
                  ek_km: Math.max(0, parseInt(extendEkKm || '0', 10) || 0),
                }));
                setExtendOpen(false);
                router.push({ pathname: '/wallet', params: { topup: '1', amount: String(Math.ceil(extendQuote.eksik)) } });
              },
            },
          ],
        );
        return;
      }
      const ekKmNum = 0;  // Ek KM artık ayrı bir akış (EK KM AL butonu)
      await customerApi.extend(active.id, extendNewEnd.toISOString(), [], ekKmNum);
      Alert.alert('Başarılı', `Süre ${extendQuote.ek_gun} gün uzatıldı. Bakiyenizden ${extendQuote.ek_tutar.toLocaleString('tr-TR')} ₺ tahsil edildi.`);
      setExtendOpen(false);
      load();
    } catch (e: any) {
      Alert.alert('Hata', e.message || 'Uzatma başarısız');
    } finally {
      setExtendLoading(false);
    }
  };

  const onConfirmPayment = async () => {
    if (!paymentTargetId) return;
    setPayLoading(true);
    try {
      await customerApi.confirmPayment(paymentTargetId, payRef.trim() || undefined, payNote.trim() || undefined);
      Alert.alert('Bildirildi', 'Ödeme bildiriminiz alındı. Yönetici onayı bekleniyor.');
      setPaymentOpen(false);
      setPayRef(''); setPayNote('');
      load();
    } catch (e: any) {
      Alert.alert('Hata', e.message);
    } finally {
      setPayLoading(false);
    }
  };

  // ===== Ek KM Satın Alma =====
  const openBuyKm = async () => {
    if (!active) return;
    setBuyKmInput('100');
    setBuyKmQuoteRes(null);
    setBuyKmOpen(true);
  };

  // Ek km input değiştiğinde quote'u güncelle
  useEffect(() => {
    if (!buyKmOpen || !active) return;
    const t = setTimeout(async () => {
      try {
        const ek = Math.max(0, parseInt(buyKmInput || '0', 10) || 0);
        const q = await customerApi.buyKmQuote(active.id, ek);
        setBuyKmQuoteRes(q);
      } catch {}
    }, 200);
    return () => clearTimeout(t);
  }, [buyKmOpen, buyKmInput, active]);

  const onBuyKm = async () => {
    if (!active || !buyKmQuoteRes) return;
    if (buyKmQuoteRes.ek_km <= 0) { Alert.alert('Uyarı', 'Lütfen satın almak istediğiniz km miktarını giriniz'); return; }
    if (!buyKmQuoteRes.bakiye_yeterli) {
      Alert.alert(
        'Bakiyeniz Yetersiz',
        `${buyKmQuoteRes.tutar.toLocaleString('tr-TR')} ₺ gerekli. Mevcut: ${buyKmQuoteRes.bakiye.toLocaleString('tr-TR')} ₺. Eksik: ${buyKmQuoteRes.eksik.toLocaleString('tr-TR')} ₺.`,
        [
          { text: 'Vazgeç', style: 'cancel' },
          { text: 'Bakiye Yükle', onPress: () => { setBuyKmOpen(false); router.push({ pathname: '/wallet', params: { topup: '1', amount: String(Math.ceil(buyKmQuoteRes.eksik)) } }); } },
        ],
      );
      return;
    }
    setBuyKmLoading(true);
    try {
      const r = await customerApi.buyKm(active.id, buyKmQuoteRes.ek_km);
      Alert.alert('Başarılı', `${r.ek_km} km satın alındı. Yeni paket km: ${r.yeni_paket_km}. Bakiyenizden ${r.tutar.toLocaleString('tr-TR')} ₺ tahsil edildi.`);
      setBuyKmOpen(false);
      load();
    } catch (e: any) {
      Alert.alert('Hata', e.message || 'İşlem başarısız');
    } finally {
      setBuyKmLoading(false);
    }
  };

  const past = list.filter(r => r.id !== active?.id);

  return (
    <View style={{ flex: 1, backgroundColor: Colors.bg.base }}>
      <SafeAreaView style={{ flex: 1 }} edges={['top']}>
        <ScrollView
          contentContainerStyle={{ paddingBottom: 120 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.brand.primary} />}
        >
          <View style={styles.header}>
            <Text style={styles.title}>Rezervasyonlarım</Text>
            <Text style={styles.subtitle}>Aktif rezervasyon ve geçmiş</Text>
          </View>

          {loading ? (
            <View style={{ paddingVertical: 60, alignItems: 'center' }}>
              <ActivityIndicator color={Colors.brand.primary} />
            </View>
          ) : (
            <>
              {active ? (
                <View style={{ paddingHorizontal: Spacing.xl, marginTop: Spacing.lg }}>
                  <View style={styles.activeWrap}>
                    <Image source={{ uri: active.vehicle_snapshot.foto_url || 'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?w=800' }} style={styles.activeImage} />
                    <View style={styles.activeOverlay} />
                    <View style={styles.activeContent}>
                      <View style={styles.statusRowTop}>
                        <StatusBadge status={active.durum} />
                        <View style={styles.plate}>
                          <Text style={styles.plateText}>{active.vehicle_snapshot.plaka}</Text>
                        </View>
                      </View>
                      <Text style={styles.activeTitle}>{active.vehicle_snapshot.marka} {active.vehicle_snapshot.model}</Text>

                      <View style={styles.dateRow}>
                        <View style={styles.dateBox}>
                          <Text style={styles.dateLabel}>Teslim</Text>
                          <Text style={styles.dateValue}>{fmtDate(active.baslangic_tarihi)}</Text>
                          <Text style={styles.timeValue}>{fmtTime(active.baslangic_tarihi)}</Text>
                        </View>
                        <Ionicons name="arrow-forward" size={18} color={Colors.text.secondary} />
                        <View style={styles.dateBox}>
                          <Text style={styles.dateLabel}>İade</Text>
                          <Text style={styles.dateValue}>{fmtDate(active.bitis_tarihi)}</Text>
                          <Text style={styles.timeValue}>{fmtTime(active.bitis_tarihi)}</Text>
                        </View>
                      </View>

                      {/* Aktif rezervasyonda Kalan Süre yerine Kira Süresi göster */}
                      {active.durum === 'aktif' ? (
                        <View style={styles.countdownBox}>
                          <Ionicons name="calendar-outline" size={16} color={Colors.brand.primaryLight} />
                          <Text style={[styles.countdownText, { color: Colors.brand.primaryLight }]}>
                            Kira Süresi: {active.gun_sayisi} gün
                          </Text>
                        </View>
                      ) : (typeof active.kalan_saniye === 'number' && active.kalan_saniye > 0 && (
                        <View style={[styles.countdownBox, active.kalan_saniye < 21600 && styles.countdownUrgent]}>
                          <Ionicons name="time-outline" size={16} color={active.kalan_saniye < 21600 ? Colors.status.error : Colors.text.primary} />
                          <Text style={[styles.countdownText, active.kalan_saniye < 21600 && { color: Colors.status.error }]}>
                            Kalan: {fmtCountdown(active.kalan_saniye)}
                          </Text>
                        </View>
                      ))}

                      {(() => {
                        const kullan = Math.max(0, Number(active.kullanilan_km || 0));
                        const paket = Math.max(1, Number(active.paket_km || 0) + Number((active as any).ek_km_satin || 0));
                        const kalan = paket - kullan;
                        const pct = Math.max(0, Math.min(100, (kullan / paket) * 100));
                        const kalanPct = 100 - pct;
                        const motorLocked = !!(active as any).motor_kilitli;
                        const danger = kalan <= 0 || motorLocked;
                        const warning = !danger && kalan <= 50;
                        const barColor = danger ? Colors.status.error : warning ? Colors.status.warning : '#22c55e';
                        return (
                          <View style={styles.kmGaugeWrap}>
                            <View style={styles.kmGaugeHeader}>
                              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                                <Ionicons name="speedometer" size={16} color={Colors.text.primary} />
                                <Text style={styles.kmGaugeTitle}>KM Hakkınız</Text>
                              </View>
                              <Text style={[styles.kmGaugePctBig, { color: barColor }]}>
                                {kalanPct.toFixed(0)}%
                              </Text>
                            </View>

                            {/* Progress bar */}
                            <View style={styles.kmGaugeBarTrack}>
                              <View style={[styles.kmGaugeBarFill, { width: `${pct}%`, backgroundColor: barColor }]} />
                              {/* 50 km eşik göstergesi */}
                              {paket > 50 && (
                                <View style={[styles.kmGaugeThreshold, { left: `${Math.max(0, Math.min(100, ((paket - 50) / paket) * 100))}%` }]} />
                              )}
                            </View>

                            {/* 3 mini stat */}
                            <View style={styles.kmStatsRow}>
                              <View style={styles.kmStatCol}>
                                <Text style={styles.kmStatLabel}>Paket</Text>
                                <Text style={styles.kmStatValue}>{paket.toLocaleString('tr-TR')} <Text style={styles.kmStatUnit}>km</Text></Text>
                              </View>
                              <View style={styles.kmStatDivider} />
                              <View style={styles.kmStatCol}>
                                <Text style={styles.kmStatLabel}>Kullanılan</Text>
                                <Text style={styles.kmStatValue}>{kullan.toLocaleString('tr-TR')} <Text style={styles.kmStatUnit}>km</Text></Text>
                              </View>
                              <View style={styles.kmStatDivider} />
                              <View style={styles.kmStatCol}>
                                <Text style={styles.kmStatLabel}>Kalan</Text>
                                <Text style={[styles.kmStatValue, { color: barColor }]}>
                                  {Math.max(0, kalan).toLocaleString('tr-TR')} <Text style={[styles.kmStatUnit, { color: barColor }]}>km</Text>
                                </Text>
                              </View>
                            </View>

                            {/* Motor kilit / Uyarı kutusu — CTA ile */}
                            {motorLocked && (
                              <View style={styles.motorLockBox}>
                                <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
                                  <Ionicons name="lock-closed" size={18} color={Colors.status.error} />
                                  <View style={{ flex: 1 }}>
                                    <Text style={styles.motorLockTitle}>Motor Kilitli</Text>
                                    <Text style={styles.motorLockMsg}>KM hakkınız bittiği için aracınızın motoru kilitlendi. Ek KM satın aldığınızda motor otomatik olarak açılır.</Text>
                                  </View>
                                </View>
                                {buyKmOpen ? null : (
                                  <Pressable onPress={() => openBuyKm()} style={[styles.lockCtaBtn, { backgroundColor: Colors.status.error }]} testID="motor-locked-buy-km">
                                    <Ionicons name="add-circle" size={16} color="#fff" />
                                    <Text style={styles.lockCtaText}>Ek KM Satın Al</Text>
                                  </Pressable>
                                )}
                              </View>
                            )}
                            {!motorLocked && warning && (
                              <View style={styles.kmWarnBox}>
                                <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 8 }}>
                                  <Ionicons name="warning" size={18} color={Colors.status.warning} />
                                  <Text style={styles.kmWarnMsg}>
                                    KM hakkınız bitmek üzere — <Text style={{ fontWeight: '700', color: Colors.status.warning }}>{kalan.toLocaleString('tr-TR')} km</Text> kaldı. KM tükenince aracın motoru kilitlenecektir.
                                  </Text>
                                </View>
                                <Pressable onPress={() => openBuyKm()} style={[styles.lockCtaBtn, { backgroundColor: Colors.status.warning, marginTop: 8 }]} testID="km-warning-buy-km">
                                  <Ionicons name="add-circle" size={16} color="#fff" />
                                  <Text style={styles.lockCtaText}>Ek KM Satın Al</Text>
                                </Pressable>
                              </View>
                            )}
                          </View>
                        );
                      })()}

                      {(active.alis_km != null || active.guncel_km != null) && (
                        <View style={styles.kmDetailRow}>
                          <View style={styles.kmDetailItem}>
                            <Ionicons name="navigate-circle-outline" size={14} color={Colors.text.secondary} />
                            <Text style={styles.kmDetailLabel}>Alış KM</Text>
                            <Text style={styles.kmDetailValue}>{(active.alis_km || 0).toLocaleString('tr-TR')}</Text>
                          </View>
                          <View style={styles.kmDetailItem}>
                            <Ionicons name="speedometer" size={14} color={Colors.brand.primary} />
                            <Text style={styles.kmDetailLabel}>Güncel KM</Text>
                            <Text style={[styles.kmDetailValue, { color: Colors.brand.primary }]}>{(active.guncel_km || 0).toLocaleString('tr-TR')}</Text>
                          </View>
                        </View>
                      )}

                      {(active.km_asim || 0) > 0 && (
                        <View style={styles.kmAsimBox}>
                          <Ionicons name="warning" size={16} color={Colors.status.error} />
                          <Text style={styles.kmAsimText}>
                            ⚠ KM Aşımı: {active.km_asim} km {active.km_asim_tutar ? `(${active.km_asim_tutar.toLocaleString('tr-TR')} ₺ bakiyeden alındı)` : ''}
                          </Text>
                        </View>
                      )}

                      <View style={styles.payRow}>
                        <View>
                          <Text style={styles.payLabel}>Toplam Tutar</Text>
                          <Text style={styles.payValue}>{active.toplam_tutar.toLocaleString('tr-TR')} ₺</Text>
                        </View>
                        <View>
                          <Text style={styles.payLabel}>Kalan Ödeme</Text>
                          <Text style={[styles.payValue, { color: Colors.status.warning }]}>{active.kalan_odeme.toLocaleString('tr-TR')} ₺</Text>
                        </View>
                      </View>

                      <View style={styles.actionsRow}>
                        {(() => {
                          const bakiyeYetersiz = active.kalan_odeme > 0 && walletBakiye < active.kalan_odeme;
                          if (bakiyeYetersiz) {
                            // Bakiye yetersiz: sadece BAKİYE YÜKLE butonu göster
                            const eksik = Math.ceil(active.kalan_odeme - walletBakiye);
                            return (
                              <GlassButton
                                testID="btn-topup-rental"
                                title={`BAKİYE YÜKLE (${active.kalan_odeme.toLocaleString('tr-TR')} ₺)`}
                                onPress={() => router.push({ pathname: '/wallet', params: { topup: '1', amount: String(eksik) } })}
                                variant="primary"
                                size="md"
                                icon={<Ionicons name="wallet" size={16} color="#fff" />}
                                style={{ flex: 1 }}
                              />
                            );
                          }
                          // Bakiye yeterli (veya kalan_odeme=0): normal 3 buton
                          return (
                            <>
                              {active.durum !== 'iptal' && active.durum !== 'tamamlandi' && (
                                <GlassButton
                                  testID="btn-extend"
                                  title="SÜRE UZAT"
                                  onPress={openExtendModal}
                                  variant="primary"
                                  size="md"
                                  icon={<Ionicons name="time" size={16} color="#fff" />}
                                  style={{ flex: 1 }}
                                />
                              )}
                              {active.durum !== 'iptal' && active.durum !== 'tamamlandi' && (
                                <GlassButton
                                  testID="btn-buy-km"
                                  title="EK KM AL"
                                  onPress={openBuyKm}
                                  variant="secondary"
                                  size="md"
                                  icon={<Ionicons name="speedometer" size={16} color="#fff" />}
                                  style={{ flex: 1 }}
                                />
                              )}
                              {active.kalan_odeme > 0 && (
                                <GlassButton
                                  testID="btn-pay"
                                  title="ÖDEME BİLDİR"
                                  onPress={() => { setPaymentTargetId(active.id); setPaymentOpen(true); }}
                                  variant="secondary"
                                  size="md"
                                  icon={<Ionicons name="cash-outline" size={16} color="#fff" />}
                                  style={{ flex: 1 }}
                                />
                              )}
                            </>
                          );
                        })()}
                      </View>
                    </View>
                  </View>

                  {/* Teslim Anı Fotoğrafları (sadece aktif rezervasyon için) */}
                  {active.durum === 'aktif' && (active.teslim_fotograflari?.length || 0) > 0 && (
                    <GlassCard style={{ marginTop: Spacing.md }}>
                      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 8 }}>
                        <Ionicons name="camera" size={18} color={Colors.brand.primary} />
                        <View style={{ flex: 1 }}>
                          <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>Aracın Teslim Anı</Text>
                          <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>{active.teslim_fotograflari!.length} fotoğraf • Yetkili tarafından çekildi</Text>
                        </View>
                      </View>
                      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                        <View style={{ flexDirection: 'row', gap: 8 }}>
                          {active.teslim_fotograflari!.map((p) => (
                            <Pressable key={p.id} onPress={() => setPreviewPhoto(p.url)} style={{ width: 120 }}>
                              <Image source={{ uri: p.url }} style={{ width: 120, height: 120, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2 }} />
                              {!!p.aciklama && <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginTop: 4 }} numberOfLines={2}>{p.aciklama}</Text>}
                            </Pressable>
                          ))}
                        </View>
                      </ScrollView>
                      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 6, fontStyle: 'italic' }}>
                        ℹ️ Bu fotoğraflar aracın size teslim edildiği andaki durumunu gösterir. Olası hasar/çizik anlaşmazlıklarında referans alınır.
                      </Text>
                    </GlassCard>
                  )}
                </View>
              ) : (
                <Empty
                  title="Aktif kiralama yok"
                  subtitle="Ana sayfadan bir araç seçip rezervasyon oluşturun"
                  icon={<Ionicons name="car-outline" size={48} color={Colors.text.tertiary} />}
                />
              )}

              <SectionTitle title="Geçmiş Rezervasyonlar" subtitle={`${past.length} kayıt`} />

              {past.length === 0 ? (
                <Empty
                  title="Henüz geçmiş kiralama yok"
                  icon={<Ionicons name="archive-outline" size={36} color={Colors.text.tertiary} />}
                />
              ) : (
                <View style={{ paddingHorizontal: Spacing.xl, gap: Spacing.md }}>
                  {past.map(r => <PastCard key={r.id} r={r} onConfirm={() => { setPaymentTargetId(r.id); setPaymentOpen(true); }} alreadyReviewed={reviewedIds.has(r.id)} walletBakiye={walletBakiye} />)}
                </View>
              )}
            </>
          )}
        </ScrollView>
      </SafeAreaView>

      {/* Extend Modal — Yeni: Takvim + Bakiye + Alternatif araç */}
      <Modal visible={extendOpen} animationType="slide" transparent onRequestClose={() => setExtendOpen(false)}>
        <View style={styles.modalBg}>
          <View style={[styles.modalCard, { maxHeight: '92%' }]}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Süreyi Uzat</Text>
              <Pressable onPress={() => setExtendOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>

            {!active ? (
              <ActivityIndicator color={Colors.brand.primary} />
            ) : (
              <ScrollView showsVerticalScrollIndicator={false} style={{ maxHeight: 600 }}>
                <View style={[styles.extendInfo, { marginBottom: Spacing.md }]}>
                  <View>
                    <Text style={styles.extendInfoLabel}>Mevcut İade</Text>
                    <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 }}>{fmtDateTime(active.bitis_tarihi)}</Text>
                  </View>
                  <View>
                    <Text style={styles.extendInfoLabel}>Araç</Text>
                    <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 }}>{active.vehicle_snapshot?.plaka}</Text>
                  </View>
                </View>

                <Text style={styles.modalLabel}>Yeni iade tarihini seçin (saat aynı kalır)</Text>

                {/* Hard limit uyarısı + alternatif araçlar (proaktif) */}
                {nextOtherRezStart && (
                  <View style={[styles.warningBox, { flexDirection: 'column', alignItems: 'stretch', gap: 8, marginBottom: Spacing.md, borderLeftWidth: 3, borderLeftColor: Colors.status.warning }]}>
                    <View style={{ flexDirection: 'row', gap: 6 }}>
                      <Ionicons name="warning" size={16} color={Colors.status.warning} />
                      <Text style={[styles.warningText, { flex: 1, fontWeight: '700' }]}>
                        Bu araç {nextOtherRezStart.toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })} sonrası başka bir müşteriye rezerve edilmiştir. Bu tarihten itibaren uzatma yapılamaz.
                      </Text>
                    </View>
                    {extendAlternatives && extendAlternatives.length > 0 && (
                      <Text style={styles.warningText}>
                        Daha uzun süre için aşağıda müsait olan diğer araçlarımıza bakabilirsiniz.
                      </Text>
                    )}
                  </View>
                )}

                {extendNewEnd && (
                  <DateTimePicker
                    availability={extendAvailability}
                    pickupDateTime={new Date(active.bitis_tarihi)}
                    returnDateTime={extendNewEnd}
                    onChangePickup={() => {}}
                    onChangeReturn={(d) => setExtendNewEnd(d)}
                    minDate={new Date(new Date(active.bitis_tarihi).getTime() + 24 * 60 * 60 * 1000)}
                    lockPickup
                  />
                )}

                {/* Ek Hizmetler kaldırıldı - sadece Ek KM Satın Alma */}

                {/* Quote ya da Bloklu durumu göster */}
                {extendQuote && !extendBlocked && (
                  <View style={[styles.extendInfo, { marginTop: Spacing.md, flexDirection: 'column', alignItems: 'stretch' }]}>
                    <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
                      <Text style={styles.extendInfoLabel}>Eklenecek Süre</Text>
                      <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{extendQuote.ek_gun} gün</Text>
                    </View>
                    {extendQuote.ek_arac_tutar != null && extendQuote.ek_gun > 0 && extendQuote.yeni_gunluk_fiyat != null && (
                      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
                        <Text style={styles.extendInfoLabel}>{extendQuote.ek_gun} gün × {extendQuote.yeni_gunluk_fiyat.toLocaleString('tr-TR')}₺/gün</Text>
                        <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>+{extendQuote.ek_arac_tutar.toLocaleString('tr-TR')} ₺</Text>
                      </View>
                    )}
                    {/* Süre indirimi (kazanç olarak gösterilir) — sadece tasarruf varsa göster */}
                    {extendQuote.fiyat_kademe && extendQuote.eski_gunluk_fiyat && extendQuote.yeni_gunluk_fiyat != null && extendQuote.yeni_gunluk_fiyat < extendQuote.eski_gunluk_fiyat && (
                      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
                        <Text style={[styles.extendInfoLabel, { color: Colors.status.success }]}>🎉 Kazancınız</Text>
                        <Text style={{ color: Colors.status.success, fontWeight: '700' }}>
                          +{(extendQuote.ek_gun * (extendQuote.eski_gunluk_fiyat - extendQuote.yeni_gunluk_fiyat)).toLocaleString('tr-TR')} ₺
                        </Text>
                      </View>
                    )}
                    {extendQuote.ek_indirim > 0 && (
                      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
                        <Text style={styles.extendInfoLabel}>🎉 Kazancınız</Text>
                        <Text style={{ color: Colors.status.success }}>+{extendQuote.ek_indirim.toLocaleString('tr-TR')} ₺</Text>
                      </View>
                    )}
                    {!!extendQuote.yeni_paket_km && (
                      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6, alignItems: 'center' }}>
                        <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                          <Ionicons name="speedometer" size={14} color={Colors.brand.primary} />
                          <Text style={[styles.extendInfoLabel, { color: Colors.brand.primary, fontWeight: '700' }]}>Yeni Toplam KM Hakkınız</Text>
                        </View>
                        <Text style={{ color: Colors.brand.primary, fontWeight: '700' }}>{Number(extendQuote.yeni_paket_km).toLocaleString('tr-TR')} km</Text>
                      </View>
                    )}
                    <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
                      <Text style={styles.extendInfoLabel}>Toplam Tutar</Text>
                      <Text style={styles.extendInfoValue}>+{extendQuote.ek_tutar.toLocaleString('tr-TR')} ₺</Text>
                    </View>
                    <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                      <Text style={styles.extendInfoLabel}>Mevcut Bakiyeniz</Text>
                      <Text style={{ ...Typography.bodyBold, color: extendQuote.bakiye_yeterli ? Colors.status.success : Colors.status.warning }}>
                        {extendQuote.bakiye.toLocaleString('tr-TR')} ₺ {extendQuote.bakiye_yeterli ? '✓' : `(eksik ${extendQuote.eksik.toLocaleString('tr-TR')} ₺)`}
                      </Text>
                    </View>
                  </View>
                )}

                {extendBlocked && (
                  <View style={[styles.warningBox, { marginTop: Spacing.md, flexDirection: 'column', alignItems: 'stretch', gap: 8 }]}>
                    <View style={{ flexDirection: 'row', gap: 6 }}>
                      <Ionicons name="warning" size={16} color={Colors.status.warning} />
                      <Text style={[styles.warningText, { fontWeight: '700' }]}>{extendBlocked.message}</Text>
                    </View>

                    {extendBlocked.reason === 'cakisma' && extendAlternatives !== null && (
                      <>
                        {extendAlternatives.length > 0 ? (
                          <>
                            <Text style={[styles.warningText, { marginTop: 4 }]}>
                              Bu tarih aralığında müsait olan diğer araçlarımız:
                            </Text>
                            {extendAlternatives.slice(0, 5).map(v => (
                              <Pressable
                                key={v.id}
                                onPress={() => {
                                  setExtendOpen(false);
                                  router.push(`/vehicle/${v.id}`);
                                }}
                                style={styles.altCar}
                              >
                                <Image source={{ uri: v.foto_url || 'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?w=600' }} style={styles.altImg} resizeMode="cover" />
                                <View style={{ flex: 1 }}>
                                  <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{v.marka} {v.model}</Text>
                                  <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{v.plaka} • {v.gunluk_fiyat.toLocaleString('tr-TR')} ₺/gün</Text>
                                </View>
                                <Ionicons name="chevron-forward" size={18} color={Colors.brand.primaryLight} />
                              </Pressable>
                            ))}
                            <Text style={[styles.warningText, { marginTop: 4, fontStyle: 'italic' }]}>
                              Bu araçlardan birini seçip yeni bir rezervasyon yapabilirsiniz. Mevcut aracınızı zamanında iade etmeniz gerekmektedir.
                            </Text>
                          </>
                        ) : (
                          <View style={{ padding: Spacing.md, backgroundColor: 'rgba(255,59,48,0.1)', borderRadius: Radius.sm, borderLeftWidth: 3, borderLeftColor: Colors.status.error }}>
                            <Text style={{ ...Typography.bodyBold, color: Colors.status.error, marginBottom: 4 }}>⚠️ Müsait Araç Yok</Text>
                            <Text style={{ ...Typography.caption, color: Colors.text.secondary, lineHeight: 18 }}>
                              Bu tarih aralığında filomuzda müsait olan aracımız bulunmuyor. Lütfen aracı planlanan iade tarihinde teslim edin.
                            </Text>
                          </View>
                        )}
                      </>
                    )}
                  </View>
                )}

                <View style={[styles.warningBox, { marginTop: Spacing.md }]}>
                  <Ionicons name="information-circle" size={16} color={Colors.status.info} />
                  <Text style={styles.warningText}>
                    Uzatma için günlük ücretin tamamı bakiyenizden tahsil edilir. Uzun süreler için indirim otomatik uygulanır.
                  </Text>
                </View>

                <GlassButton
                  testID="btn-extend-confirm"
                  title={
                    extendBlocked
                      ? 'BU TARİHE UZATILAMAZ'
                      : extendQuote
                        ? (extendQuote.bakiye_yeterli ? 'UZATMAYI ONAYLA' : 'BAKİYE YÜKLE & UZAT')
                        : 'YÜKLENİYOR...'
                  }
                  onPress={onExtend}
                  loading={extendLoading}
                  disabled={!!extendBlocked || !extendQuote}
                  size="lg"
                  style={{ marginTop: Spacing.md }}
                />
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>

      {/* Payment Confirm Modal */}
      <Modal visible={paymentOpen} animationType="slide" transparent onRequestClose={() => setPaymentOpen(false)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Ödeme Bildirimi</Text>
              <Pressable onPress={() => setPaymentOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>
            <Text style={styles.modalSubtitle}>IBAN'a yaptığınız transferi yöneticiye bildirin.</Text>
            <Text style={styles.modalLabel}>İşlem Referans No (Opsiyonel)</Text>
            <TextInput
              value={payRef} onChangeText={setPayRef}
              style={styles.input}
              placeholder="Banka transfer referansı"
              placeholderTextColor={Colors.text.tertiary}
            />
            <Text style={styles.modalLabel}>Notlar (Opsiyonel)</Text>
            <TextInput
              value={payNote} onChangeText={setPayNote}
              style={[styles.input, { height: 80 }]}
              placeholder="Eklemek istedikleriniz"
              placeholderTextColor={Colors.text.tertiary}
              multiline
            />
            <GlassButton
              testID="btn-payment-confirm"
              title="GÖNDER"
              onPress={onConfirmPayment}
              loading={payLoading}
              size="lg"
            />
          </View>
        </View>
      </Modal>

      {/* Tam ekran fotoğraf önizleme — Pinch-Zoom + Pan + Double-Tap */}
      <Modal visible={!!previewPhoto} animationType="fade" transparent onRequestClose={() => setPreviewPhoto(null)}>
        <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.95)', alignItems: 'center', justifyContent: 'center' }}>
          {previewPhoto && <ZoomableImage uri={previewPhoto} onClose={() => setPreviewPhoto(null)} />}
          <View style={{ position: 'absolute', top: 50, right: 20 }}>
            <Pressable onPress={() => setPreviewPhoto(null)} style={{ width: 44, height: 44, borderRadius: 22, backgroundColor: 'rgba(255,255,255,0.2)', alignItems: 'center', justifyContent: 'center' }}>
              <Ionicons name="close" size={28} color="#fff" />
            </Pressable>
          </View>
          <View style={{ position: 'absolute', bottom: 40, alignSelf: 'center', paddingHorizontal: 14, paddingVertical: 6, backgroundColor: 'rgba(255,255,255,0.1)', borderRadius: 14 }}>
            <Text style={{ color: '#fff', fontSize: 11 }}>İki parmakla yakınlaştırın • Çift dokunma ile sıfırla</Text>
          </View>
        </View>
      </Modal>

      {/* Ek KM Satın Alma Modal */}
      <Modal visible={buyKmOpen} animationType="slide" transparent onRequestClose={() => setBuyKmOpen(false)}>
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={styles.modalBg}
        >
          <TouchableWithoutFeedback onPress={Keyboard.dismiss} accessible={false}>
            <View style={{ flex: 1, justifyContent: 'flex-end' }}>
              <TouchableWithoutFeedback>
                <View style={styles.modalCard}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
              <View style={{ flex: 1 }}>
                <Text style={styles.modalTitle}>Ek KM Satın Al</Text>
                {active && <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{active.vehicle_snapshot?.marka} {active.vehicle_snapshot?.model} • {active.vehicle_snapshot?.plaka}</Text>}
              </View>
              <Pressable onPress={() => setBuyKmOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
            </View>

            <View style={{ marginTop: Spacing.md, padding: Spacing.md, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base }}>
              <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Mevcut Paket KM</Text>
              <Text style={{ ...Typography.h3, color: Colors.text.primary, fontWeight: '800', marginTop: 2 }}>
                {(buyKmQuoteRes?.mevcut_paket_km || active?.paket_km || 0).toLocaleString('tr-TR')} km
              </Text>
              {!!active?.guncel_km && active?.alis_km !== undefined && (
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 4 }}>
                  Kullanılan: {((active.guncel_km || 0) - (active.alis_km || 0)).toLocaleString('tr-TR')} km
                </Text>
              )}
            </View>

              <View style={{ marginTop: Spacing.md }}>
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <Ionicons name="speedometer" size={18} color={Colors.brand.primary} />
                  <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, flex: 1 }}>Satın alınacak KM</Text>
                  <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{(buyKmQuoteRes?.km_asim_fiyat || extendKmFiyat).toLocaleString('tr-TR')} ₺/km</Text>
                </View>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                <Pressable
                  onPress={() => {
                    Keyboard.dismiss();
                    const cur = Math.max(0, parseInt(buyKmInput || '0', 10) || 0);
                    setBuyKmInput(String(Math.max(0, cur - 50)));
                  }}
                  style={{ width: 44, height: 44, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, alignItems: 'center', justifyContent: 'center' }}
                >
                  <Ionicons name="remove" size={20} color={Colors.text.primary} />
                </Pressable>
                <TextInput
                  value={buyKmInput}
                  onChangeText={(v) => setBuyKmInput(v.replace(/\D/g, ''))}
                  keyboardType="number-pad"
                  returnKeyType="done"
                  blurOnSubmit
                  onSubmitEditing={Keyboard.dismiss}
                  placeholder="0"
                  placeholderTextColor={Colors.text.tertiary}
                  style={{
                    flex: 1, height: 44, paddingHorizontal: 12, textAlign: 'center',
                    backgroundColor: Colors.bg.surface2, borderRadius: Radius.md,
                    borderWidth: 1, borderColor: Colors.border.base,
                    color: Colors.text.primary, fontSize: 18, fontWeight: '700',
                  }}
                />
                <Pressable
                  onPress={() => {
                    Keyboard.dismiss();
                    const cur = Math.max(0, parseInt(buyKmInput || '0', 10) || 0);
                    setBuyKmInput(String(cur + 50));
                  }}
                  style={{ width: 44, height: 44, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, alignItems: 'center', justifyContent: 'center' }}
                >
                  <Ionicons name="add" size={20} color={Colors.text.primary} />
                </Pressable>
              </View>
              <View style={{ flexDirection: 'row', gap: 6, marginTop: 8 }}>
                {[100, 250, 500, 1000].map(v => (
                  <Pressable
                    key={v}
                    onPress={() => setBuyKmInput(String(v))}
                    style={{ flex: 1, paddingVertical: 8, borderRadius: Radius.sm, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, alignItems: 'center' }}
                  >
                    <Text style={{ ...Typography.micro, color: Colors.text.secondary, fontWeight: '700' }}>+{v}</Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {buyKmQuoteRes && buyKmQuoteRes.ek_km > 0 && (
              <View style={{ marginTop: Spacing.md, padding: Spacing.md, backgroundColor: Colors.bg.glassRed, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.accent }}>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
                  <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>Yeni Paket KM</Text>
                  <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>
                    {(buyKmQuoteRes.mevcut_paket_km + buyKmQuoteRes.ek_km).toLocaleString('tr-TR')} km
                  </Text>
                </View>
                <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 6 }}>
                  <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{buyKmQuoteRes.ek_km} km × {buyKmQuoteRes.km_asim_fiyat.toLocaleString('tr-TR')}₺/km</Text>
                  <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{buyKmQuoteRes.tutar.toLocaleString('tr-TR')} ₺</Text>
                </View>
                {/* KM aşım indirimi — Option B: 2 satır, normal fiyat ve sizin fiyatınız + toplam tasarruf */}
                {buyKmQuoteRes.km_asim_kademe && buyKmQuoteRes.km_asim_baz != null && buyKmQuoteRes.km_asim_baz > buyKmQuoteRes.km_asim_fiyat && (
                  <View style={{ paddingVertical: 10, paddingHorizontal: 12, marginBottom: 8, backgroundColor: Colors.status.success + '15', borderRadius: 8, borderLeftWidth: 3, borderLeftColor: Colors.status.success }}>
                    <Text style={{ fontSize: 12, color: Colors.status.success, fontWeight: '800', marginBottom: 4 }}>🎉 Kazancınız</Text>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                      <Text style={{ fontSize: 11, color: Colors.text.tertiary, textDecorationLine: 'line-through' }}>
                        Normal: {buyKmQuoteRes.km_asim_baz.toLocaleString('tr-TR')}₺/km
                      </Text>
                      <Ionicons name="arrow-forward" size={11} color={Colors.status.success} />
                      <Text style={{ fontSize: 12, color: Colors.status.success, fontWeight: '700' }}>
                        Sizin Fiyatınız: {buyKmQuoteRes.km_asim_fiyat.toLocaleString('tr-TR')}₺/km
                      </Text>
                    </View>
                    <Text style={{ fontSize: 11, color: Colors.status.success, fontWeight: '700', marginTop: 4 }}>
                      Kazancınız: +{(buyKmQuoteRes.ek_km * (buyKmQuoteRes.km_asim_baz - buyKmQuoteRes.km_asim_fiyat)).toLocaleString('tr-TR')} ₺
                    </Text>
                  </View>
                )}
                <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
                  <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>Mevcut Bakiyeniz</Text>
                  <Text style={{ ...Typography.bodyBold, color: buyKmQuoteRes.bakiye_yeterli ? Colors.status.success : Colors.status.warning }}>
                    {buyKmQuoteRes.bakiye.toLocaleString('tr-TR')} ₺ {buyKmQuoteRes.bakiye_yeterli ? '✓' : `(eksik ${buyKmQuoteRes.eksik.toLocaleString('tr-TR')} ₺)`}
                  </Text>
                </View>
              </View>
            )}

            <View style={[styles.warningBox, { marginTop: Spacing.md }]}>
              <Ionicons name="information-circle" size={16} color={Colors.status.info} />
              <Text style={styles.warningText}>
                Satın alınan ek km, mevcut paket km'nize eklenecek ve bakiyenizden tahsil edilecektir. KM aşım ücretinden kurtulmak için tavsiye edilir.
              </Text>
            </View>

            <GlassButton
              testID="btn-buy-km-confirm"
              title={
                !buyKmQuoteRes || buyKmQuoteRes.ek_km <= 0
                  ? 'KM MİKTARI GİRİN'
                  : (buyKmQuoteRes.bakiye_yeterli ? `${buyKmQuoteRes.tutar.toLocaleString('tr-TR')} ₺ ÖDE & SATIN AL` : 'BAKİYE YÜKLE & SATIN AL')
              }
              onPress={onBuyKm}
              loading={buyKmLoading}
              disabled={!buyKmQuoteRes || buyKmQuoteRes.ek_km <= 0}
              size="lg"
              style={{ marginTop: Spacing.md }}
            />
                </View>
              </TouchableWithoutFeedback>
            </View>
          </TouchableWithoutFeedback>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

function PastCard({ r, onConfirm, alreadyReviewed, walletBakiye }: { r: Reservation; onConfirm: () => void; alreadyReviewed?: boolean; walletBakiye: number }) {
  const kalan = Number(r.kalan_odeme || 0);
  const bakiyeYetersiz = kalan > 0 && walletBakiye < kalan;
  const eksik = Math.max(0, Math.ceil(kalan - walletBakiye));
  return (
    <GlassCard style={{ padding: Spacing.md }}>
      <View style={{ flexDirection: 'row', gap: Spacing.md }}>
        <Image source={{ uri: r.vehicle_snapshot.foto_url || 'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?w=400' }} style={{ width: 70, height: 70, borderRadius: 12, backgroundColor: Colors.bg.surface2 }} />
        <View style={{ flex: 1, gap: 4 }}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text style={{ ...Typography.h4, color: Colors.text.primary }}>{r.vehicle_snapshot.marka}</Text>
            <StatusBadge status={r.durum} />
          </View>
          <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{r.vehicle_snapshot.model} • {r.vehicle_snapshot.plaka}</Text>
          <Text style={{ ...Typography.caption, color: Colors.text.tertiary }}>{fmtDateTime(r.baslangic_tarihi)} → {fmtDateTime(r.bitis_tarihi)}</Text>
          {r.durum !== 'iptal' && r.gun_sayisi > 0 && (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4, marginTop: 2 }}>
              <Ionicons name="calendar-outline" size={12} color={Colors.brand.primaryLight} />
              <Text style={{ ...Typography.micro, color: Colors.brand.primaryLight, fontWeight: '700' }}>
                Kira Süresi: {r.gun_sayisi} gün
              </Text>
            </View>
          )}
          <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginTop: 2, alignItems: 'center' }}>
            <Text style={{ ...Typography.bodyBold, color: Colors.brand.primary }}>{r.toplam_tutar.toLocaleString('tr-TR')} ₺</Text>
            {r.durum === 'beklemede' && bakiyeYetersiz && (
              <Pressable
                onPress={() => router.push({ pathname: '/wallet', params: { topup: '1', amount: String(eksik) } })}
                style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, backgroundColor: Colors.brand.primary }}
              >
                <Ionicons name="wallet" size={12} color="#fff" />
                <Text style={{ ...Typography.micro, color: '#fff', fontWeight: '800' }}>BAKİYE YÜKLE ({kalan.toLocaleString('tr-TR')} ₺)</Text>
              </Pressable>
            )}
            {r.durum === 'beklemede' && !bakiyeYetersiz && (
              <Pressable onPress={onConfirm}>
                <Text style={{ ...Typography.micro, color: Colors.status.info, fontWeight: '700' }}>ÖDEME BİLDİR</Text>
              </Pressable>
            )}
            {r.durum === 'tamamlandi' && !alreadyReviewed && (
              <Pressable onPress={() => router.push(`/review/${r.id}` as any)} style={{ flexDirection: 'row', alignItems: 'center', gap: 4, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 14, backgroundColor: '#FBBF24' }}>
                <Ionicons name="star" size={12} color="#fff" />
                <Text style={{ ...Typography.micro, color: '#fff', fontWeight: '800' }}>YORUM YAP</Text>
              </Pressable>
            )}
            {r.durum === 'tamamlandi' && alreadyReviewed && (
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 3 }}>
                <Ionicons name="checkmark-circle" size={12} color={Colors.status.success} />
                <Text style={{ ...Typography.micro, color: Colors.status.success, fontWeight: '700' }}>YORUM BIRAKILDI</Text>
              </View>
            )}
          </View>
        </View>
      </View>
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  header: { paddingHorizontal: Spacing.xl, paddingTop: Spacing.lg, paddingBottom: Spacing.sm },
  title: { ...Typography.h1, color: Colors.text.primary },
  subtitle: { ...Typography.caption, color: Colors.text.secondary, marginTop: 4 },

  activeWrap: {
    borderRadius: Radius.xl,
    overflow: 'hidden',
    backgroundColor: Colors.bg.surface,
    borderWidth: 1, borderColor: Colors.border.accent,
    shadowColor: Colors.brand.primary, shadowOpacity: 0.4, shadowRadius: 30, elevation: 10,
  },
  activeImage: { width: '100%', height: 180 },
  activeOverlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.55)', height: 180 },
  activeContent: { padding: Spacing.xl, marginTop: -60, backgroundColor: 'transparent' },

  statusRowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  plate: {
    backgroundColor: '#fff', paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 4, borderWidth: 2, borderColor: '#000',
  },
  plateText: { fontSize: 14, fontWeight: '900', color: '#000', letterSpacing: 1 },
  activeTitle: { ...Typography.h2, color: '#fff', marginTop: Spacing.md },

  dateRow: {
    flexDirection: 'row', alignItems: 'center', gap: Spacing.md,
    marginTop: Spacing.lg,
    backgroundColor: Colors.bg.glassDark,
    padding: Spacing.md,
    borderRadius: Radius.md,
    borderWidth: 1, borderColor: Colors.border.base,
  },
  dateBox: { flex: 1, alignItems: 'center' },
  dateLabel: { ...Typography.micro, color: Colors.text.secondary },
  dateValue: { ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 },
  timeValue: { ...Typography.caption, color: Colors.brand.primaryLight, marginTop: 2, fontWeight: '700' },

  countdownBox: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    marginTop: Spacing.md,
    backgroundColor: Colors.bg.surface, padding: Spacing.md,
    borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base,
  },
  countdownUrgent: {
    borderColor: Colors.status.error,
    backgroundColor: 'rgba(255, 59, 48, 0.1)',
  },
  countdownText: { ...Typography.bodyBold, color: Colors.text.primary },

  kmRow: { flexDirection: 'row', gap: Spacing.sm, marginTop: Spacing.md },
  kmBox: {
    flex: 1, padding: Spacing.md, borderRadius: Radius.md,
    backgroundColor: Colors.bg.surface, borderWidth: 1, borderColor: Colors.border.base,
    alignItems: 'center',
  },
  kmLabel: { ...Typography.micro, color: Colors.text.secondary },
  kmValue: { ...Typography.h4, color: Colors.text.primary, marginTop: 4 },
  motorLockBox: {
    backgroundColor: 'rgba(255,59,48,0.10)',
    borderLeftWidth: 3, borderLeftColor: Colors.status.error,
    borderRadius: Radius.md, padding: Spacing.md, marginTop: Spacing.md,
  },
  motorLockTitle: { ...Typography.bodyBold, color: Colors.status.error, marginBottom: 2 },
  motorLockMsg: { ...Typography.caption, color: Colors.text.primary, lineHeight: 18 },
  kmWarnBox: {
    backgroundColor: 'rgba(245,158,11,0.10)',
    borderLeftWidth: 3, borderLeftColor: Colors.status.warning,
    borderRadius: Radius.md, padding: Spacing.md, marginTop: Spacing.md,
  },
  kmWarnMsg: { ...Typography.caption, color: Colors.text.primary, flex: 1, lineHeight: 18 },
  lockCtaBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, paddingVertical: 10, paddingHorizontal: 14, borderRadius: Radius.md, marginTop: 10,
  },
  lockCtaText: { ...Typography.bodyBold, color: '#fff', fontWeight: '700' },
  kmGaugeWrap: {
    marginTop: Spacing.md,
    backgroundColor: Colors.bg.surface2,
    borderRadius: Radius.lg,
    padding: Spacing.md,
    borderWidth: 1, borderColor: Colors.border.base,
  },
  kmGaugeHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8,
  },
  kmGaugeTitle: { ...Typography.bodyBold, color: Colors.text.primary, fontWeight: '700' },
  kmGaugePctBig: { ...Typography.h3, fontWeight: '800' },
  kmGaugeBarTrack: {
    height: 12, borderRadius: 6,
    backgroundColor: Colors.bg.surface3 || 'rgba(255,255,255,0.06)',
    overflow: 'hidden', marginBottom: 12, position: 'relative',
  },
  kmGaugeBarFill: { height: '100%', borderRadius: 6 },
  kmGaugeThreshold: {
    position: 'absolute', top: -2, bottom: -2, width: 2,
    backgroundColor: 'rgba(245,158,11,0.6)',
  },
  kmStatsRow: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: 'rgba(255,255,255,0.03)',
    borderRadius: Radius.md, paddingVertical: 8,
  },
  kmStatCol: { flex: 1, alignItems: 'center' },
  kmStatDivider: { width: 1, height: 28, backgroundColor: Colors.border.base },
  kmStatLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 2 },
  kmStatValue: { ...Typography.bodyBold, color: Colors.text.primary, fontWeight: '700' },
  kmStatUnit: { ...Typography.micro, color: Colors.text.secondary, fontWeight: '500' },
  kmDetailRow: { flexDirection: 'row', gap: 6, marginTop: 8 },
  kmDetailItem: { flex: 1, flexDirection: 'row', alignItems: 'center', gap: 4, padding: 8, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base },
  kmDetailLabel: { ...Typography.micro, color: Colors.text.secondary, flex: 1 },
  kmDetailValue: { ...Typography.bodyBold, color: Colors.text.primary, fontVariant: ['tabular-nums'] },
  kmAsimBox: { flexDirection: 'row', alignItems: 'center', gap: 6, marginTop: 8, padding: 10, borderRadius: Radius.md, backgroundColor: 'rgba(255, 59, 48, 0.10)', borderLeftWidth: 3, borderLeftColor: Colors.status.error },
  kmAsimText: { ...Typography.caption, color: Colors.status.error, flex: 1, fontWeight: '600' },

  payRow: {
    flexDirection: 'row', justifyContent: 'space-between', marginTop: Spacing.lg,
    paddingTop: Spacing.md, borderTopWidth: 1, borderTopColor: Colors.border.base,
  },
  payLabel: { ...Typography.micro, color: Colors.text.secondary },
  payValue: { ...Typography.h3, color: Colors.text.primary, marginTop: 2 },

  actionsRow: { flexDirection: 'row', gap: Spacing.sm, marginTop: Spacing.lg },

  modalBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'flex-end' },
  modalCard: {
    backgroundColor: Colors.bg.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    padding: Spacing.xl, gap: Spacing.md, borderTopWidth: 1, borderColor: Colors.border.base,
  },
  modalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  modalTitle: { ...Typography.h2, color: Colors.text.primary },
  modalSubtitle: { ...Typography.caption, color: Colors.text.secondary },
  modalLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' },
  input: {
    backgroundColor: Colors.bg.surface2, borderRadius: Radius.md,
    padding: Spacing.md, color: Colors.text.primary, borderWidth: 1, borderColor: Colors.border.base,
    fontSize: 15,
  },
  warningBox: {
    flexDirection: 'row', gap: 8, padding: Spacing.md,
    backgroundColor: 'rgba(90, 200, 250, 0.08)', borderRadius: Radius.md,
    borderLeftWidth: 3, borderLeftColor: Colors.status.info,
  },
  warningText: { ...Typography.caption, color: Colors.text.secondary, flex: 1, lineHeight: 18 },
  extendInfo: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: Spacing.md, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md },
  extendInfoLabel: { ...Typography.caption, color: Colors.text.secondary },
  extendInfoValue: { ...Typography.h3, color: Colors.brand.primary },
  altCar: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: Spacing.sm, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base, marginTop: 6 },
  altImg: { width: 90, height: 64, borderRadius: 8, backgroundColor: Colors.bg.elevated, borderWidth: 1, borderColor: Colors.border.base },
});
