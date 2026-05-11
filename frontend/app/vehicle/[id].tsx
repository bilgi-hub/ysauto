/**
 * Araç Detayı + Rezervasyon Akışı
 */
import React, { useEffect, useState, useCallback, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView, Image, Pressable, TextInput, ActivityIndicator, Alert, KeyboardAvoidingView, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { Ionicons, MaterialCommunityIcons } from '@expo/vector-icons';
import VehicleImageSlider from '../../src/VehicleImageSlider';
import { Stars } from '../../src/Stars';
import PulseButton from '../../src/PulseButton';
import { customerApi, Vehicle, Settings } from '../../src/api';
import { Colors, Radius, Spacing, Typography } from '../../src/theme';
import { GlassCard, GlassButton, StatusBadge } from '../../src/ui';
import { DateTimePicker, Availability } from '../../src/DateTimePicker';

const PENDING_KEY = 'ys_pending_reservation';

function fmtDate(d: Date) {
  return d.toISOString().split('T')[0];
}
function addDays(d: Date, n: number) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function pretty(d: Date) {
  return d.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric', weekday: 'short' }) +
    ' ' + String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
}
function diffDays(a: Date, b: Date) {
  const ms = b.getTime() - a.getTime();
  const days = Math.ceil(ms / (1000 * 60 * 60 * 24));
  return Math.max(1, days);
}

export default function VehicleDetail() {
  const { id, autoSubmit } = useLocalSearchParams<{ id: string; autoSubmit?: string }>();
  const router = useRouter();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  const [settings, setSettings] = useState<Settings>({});
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [loading, setLoading] = useState(true);

  // Default: yarın 10:00 → ertesi gün 10:00
  const initStart = (() => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(10, 0, 0, 0); return d; })();
  const initEnd = (() => { const d = new Date(initStart); d.setDate(d.getDate() + 1); return d; })();
  const [start, setStart] = useState<Date>(initStart);
  const [end, setEnd] = useState<Date>(initEnd);
  const days = diffDays(start, end);
  const [phone, setPhone] = useState('');
  const [step, setStep] = useState<'detail' | 'reserve' | 'payment' | 'success'>('detail');
  const [submitting, setSubmitting] = useState(false);
  const [reservation, setReservation] = useState<any>(null);
  const [services, setServices] = useState<any[]>([]);
  const [selectedServices, setSelectedServices] = useState<Record<string, number>>({});
  const [pricing, setPricing] = useState<any>(null);
  const [walletBakiye, setWalletBakiye] = useState(0);
  const [activeRez, setActiveRez] = useState<any>(null); // müşterinin mevcut çakışan aktif rezervasyonu
  const [minStartDate, setMinStartDate] = useState<Date | undefined>(undefined);

  const load = useCallback(async () => {
    try {
      const [v, s, svc, w, av, actv, prof] = await Promise.all([
        customerApi.vehicle(id!),
        customerApi.publicSettings(),
        customerApi.services(id!).catch(() => []),
        customerApi.wallet().catch(() => ({ bakiye: 0 })),
        customerApi.vehicleAvailability(id!).catch(() => null),
        customerApi.activeReservation().catch(() => null),
        customerApi.myProfile().catch(() => null),
      ]);
      setVehicle(v);
      setSettings(s);
      setServices(svc);
      setWalletBakiye(w.bakiye || 0);
      setAvailability(av);
      setActiveRez(actv);
      // Profil telefonu otomatik doldur (boşsa)
      if (prof?.telefon) {
        setPhone((cur) => cur || prof.telefon || '');
      }

      // AUTO-SUBMIT: Cüzdan ekranından bakiye yüklemesi sonrası geri dönüşte
      if (autoSubmit === '1') {
        try {
          const pendingStr = await AsyncStorage.getItem(PENDING_KEY);
          if (pendingStr) {
            const pending = JSON.parse(pendingStr);
            if (pending.vehicleId === v.id) {
              const ps = new Date(pending.baslangic);
              const pe = new Date(pending.bitis);
              setStart(ps);
              setEnd(pe);
              setPhone(pending.telefon || '');
              setSelectedServices(pending.services || {});
              setStep('reserve');
              const targetTipi: 'full' | 'deposit' = pending.odeme_tipi || 'full';
              const required = pending.required || 0;
              setTimeout(async () => {
                if ((w.bakiye || 0) >= required) {
                  Alert.alert(
                    'Rezervasyon Onayı',
                    `Bakiye yüklemeniz başarılı. ${targetTipi === 'full' ? 'Tam ödeme' : 'Kapora'} (${required.toLocaleString('tr-TR')} ₺) bakiyenizden düşülerek rezervasyon onaylanacak.`,
                    [
                      { text: 'Vazgeç', onPress: () => AsyncStorage.removeItem(PENDING_KEY) },
                      { text: 'Onayla ve Oluştur', onPress: () => submitReserveAPIRef.current?.(targetTipi) },
                    ],
                  );
                } else {
                  Alert.alert(
                    'Bakiye Hala Yetersiz',
                    `Rezervasyon için ${required.toLocaleString('tr-TR')} ₺ gerekli ama bakiyeniz ${(w.bakiye || 0).toLocaleString('tr-TR')} ₺. Lütfen ek yükleme yapın.`,
                  );
                }
              }, 500);
            }
          }
        } catch {}
      }
    } catch (e: any) {
      Alert.alert('Hata', e?.message || 'Araç yüklenemedi');
      router.back();
    } finally {
      setLoading(false);
    }
  }, [id, router, autoSubmit]);

  useEffect(() => { load(); }, [load]);

  // Quote on changes
  React.useEffect(() => {
    if (!vehicle || step !== 'reserve') return;
    const t = setTimeout(async () => {
      try {
        const services_arr = Object.entries(selectedServices).filter(([_, v]) => v > 0).map(([k, v]) => ({ service_id: k, adet: v }));
        const q = await customerApi.quote({
          vehicle_id: vehicle.id,
          baslangic_tarihi: start.toISOString(),
          bitis_tarihi: end.toISOString(),
          secilen_hizmetler: services_arr,
        });
        setPricing(q);
      } catch {}
    }, 200);
    return () => clearTimeout(t);
  }, [vehicle, start, end, selectedServices, step]);

  // Aracın en geç biten aktif rezervasyonu → +1 saat tampon = sonraki müsaitlik tarihi
  const computeVehicleNextFree = useCallback((): Date | null => {
    if (!availability || availability.blocked_ranges.length === 0) return null;
    const now = new Date();
    let latest: Date | null = null;
    for (const r of availability.blocked_ranges) {
      const re = new Date(r.end);
      if (re > now && (!latest || re > latest)) latest = re;
    }
    if (!latest) return null;
    return new Date(latest.getTime() + 60 * 60 * 1000);
  }, [availability]);

  const fmtTR = (d: Date) =>
    d.toLocaleString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });

  const startReserveFlow = useCallback(() => {
    if (!vehicle) return;

    // BAKIM → kesinlikle rezerve edilemez
    if (vehicle.durum === 'bakim') {
      Alert.alert('Bu Araç Bakımda', 'Bu araç şu anda bakımda olduğu için rezervasyon alınamaz. Lütfen başka bir araç seçin.');
      return;
    }

    // 1) Aracın bir sonraki müsait tarihi (varsa) — sadece dolu araç uyarısı içindir
    const vehicleNextFree = computeVehicleNextFree();

    // 2) Müşterinin başka aktif rezervasyonu var mı? (sadece bilgilendirme amacıyla)
    const now = new Date();
    let hasFutureCustomerRez = false;
    let customerRezInfo = '';
    if (activeRez && (activeRez.durum === 'onaylandi' || activeRez.durum === 'aktif')) {
      try {
        const cb = new Date(activeRez.bitis_tarihi);
        if (cb > now) {
          hasFutureCustomerRez = true;
          const plaka = activeRez.vehicle_snapshot?.plaka || '';
          const bs = new Date(activeRez.baslangic_tarihi);
          const fmt = (d: Date) => d.toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
          customerRezInfo = `${plaka}: ${fmt(bs)} - ${fmt(cb)}`;
        }
      } catch {}
    }

    // Yarın 10:00'dan başla; takvim minimum tarihi yok (her zaman bugün+1 gün)
    const proceed = () => {
      const baseDate = new Date();
      baseDate.setDate(baseDate.getDate() + 1);
      baseDate.setHours(10, 0, 0, 0);
      const endDate = new Date(baseDate);
      endDate.setDate(endDate.getDate() + 1);
      setStart(baseDate);
      setEnd(endDate);
      setMinStartDate(undefined); // sınır yok — takvim dolu aralıkları zaten gösterecek
      setStep('reserve');
    };

    // ÖNCE: Müşterinin aktif kiralaması varsa bilgilendir + uzatma seçeneği sun
    if (hasFutureCustomerRez) {
      Alert.alert(
        'Aktif Kiralamanız Var',
        `Mevcut rezervasyonunuz: ${customerRezInfo}\n\nBu tarihler ile çakışmayan herhangi bir tarih aralığında yeni rezervasyon yapabilirsiniz. Mevcut rezervasyonun süresini uzatmak da mümkündür.`,
        [
          { text: 'Vazgeç', style: 'cancel' },
          { text: 'Süre Uzat', onPress: () => router.push('/(tabs)/rentals') },
          { text: 'Yeni Rezerve', onPress: proceed },
        ],
      );
      return;
    }

    // SONRA: Araç dolu mu? — Yine de rezerve edilebilir (takvim dolu tarihleri gösterir)
    if (vehicle.durum === 'dolu') {
      const fmt = (d: Date) => d.toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
      const msg = vehicleNextFree
        ? `Bu araç şu anda kirada. ${fmt(vehicleNextFree)} sonrasında veya başka müsait bir tarih için rezervasyon yapabilirsiniz. Takvimde dolu tarihler işaretlenecektir.`
        : 'Bu araç şu anda kirada. Müsait tarihler takvimde işaretlenecektir.';
      Alert.alert(
        'Bu Araç Şu An Kirada',
        msg,
        [
          { text: 'Vazgeç', style: 'cancel' },
          { text: 'Devam Et', onPress: proceed },
        ],
      );
      return;
    }

    // Normal akış
    proceed();
  }, [vehicle, activeRez, computeVehicleNextFree, router]);

  const total = pricing?.toplam_tutar || (vehicle ? vehicle.gunluk_fiyat * days : 0);
  const deposit = pricing?.on_odeme_tutar || total * 0.20;
  const remaining = pricing?.kalan_odeme || total - deposit;

  const submitReserveAPIRef = useRef<((odeme_tipi?: 'auto' | 'full' | 'deposit') => Promise<void>) | null>(null);

  const submitReserveAPI = async (odeme_tipi: 'auto' | 'full' | 'deposit' = 'auto') => {
    if (!vehicle) return;
    setSubmitting(true);
    try {
      const services_arr = Object.entries(selectedServices).filter(([_, v]) => v > 0).map(([k, v]) => ({ service_id: k, adet: v }));
      const r = await customerApi.reserve({
        vehicle_id: vehicle.id,
        baslangic_tarihi: start.toISOString(),
        bitis_tarihi: end.toISOString(),
        telefon: phone,
        secilen_hizmetler: services_arr,
        odeme_tipi,
      });
      setReservation(r);
      // Otomatik onay: bakiyeden ödeme alındıysa direkt başarılı ekrana git
      if (r.durum === 'onaylandi' && (r.odeme_durumu === 'on_odeme_alindi' || r.odeme_durumu === 'tam_odeme_alindi')) {
        setStep('success');
      } else {
        setStep('payment');
      }
      // Pending varsa temizle
      AsyncStorage.removeItem(PENDING_KEY).catch(() => {});
    } catch (e: any) {
      if (e?.status === 402 || (e?.message || '').includes('Bakiye yetersiz')) {
        Alert.alert(
          'Bakiye Yetersiz',
          `${e.message}\n\nCüzdanınıza bakiye yüklemek ister misiniz?`,
          [
            { text: 'Vazgeç' },
            { text: 'Bakiye Yükle', onPress: () => savePendingAndGoWallet(odeme_tipi === 'deposit' ? 'deposit' : 'full') },
          ],
        );
      } else if (e?.status === 409) {
        Alert.alert(
          'Aktif Kiralama Çakışması',
          e.message,
          [
            { text: 'Tamam', style: 'cancel' },
            { text: 'Süre Uzat', onPress: () => router.push('/(tabs)/rentals') },
          ],
        );
      } else {
        Alert.alert('Hata', e.message);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const savePendingAndGoWallet = async (odeme_tipi: 'full' | 'deposit') => {
    if (!vehicle || !pricing) return;
    const required = odeme_tipi === 'full' ? pricing.toplam_tutar : pricing.on_odeme_tutar;
    try {
      await AsyncStorage.setItem(PENDING_KEY, JSON.stringify({
        vehicleId: vehicle.id,
        baslangic: start.toISOString(),
        bitis: end.toISOString(),
        telefon: phone,
        services: selectedServices,
        required,
        odeme_tipi,
        savedAt: new Date().toISOString(),
      }));
    } catch {}
    router.push({ pathname: '/wallet', params: { topup: '1', amount: String(Math.ceil(required - walletBakiye)) } });
  };

  const onReserve = async () => {
    if (!vehicle || !pricing) return;
    if (phone.replace(/\D/g, '').length < 10) { Alert.alert('Hata', 'Geçerli bir telefon girin'); return; }

    const total = pricing.toplam_tutar;
    const deposit = pricing.on_odeme_tutar;
    const fmt = (n: number) => n.toLocaleString('tr-TR', { minimumFractionDigits: 0, maximumFractionDigits: 2 });

    // SENARYO A: Bakiye tam ödeme için yeterli → direkt full payment, soru yok
    if (walletBakiye >= total) {
      submitReserveAPI('full');
      return;
    }

    // SENARYO B: Bakiye kapora yeterli ama tam değil → SOR
    if (walletBakiye >= deposit) {
      Alert.alert(
        'Ödeme Yöntemi Seçin',
        `Toplam Kira: ${fmt(total)} ₺\nKapora (${Math.round((deposit / total) * 100)}%): ${fmt(deposit)} ₺\nMevcut Bakiyeniz: ${fmt(walletBakiye)} ₺\n\nNasıl devam edelim?`,
        [
          { text: 'Vazgeç', style: 'cancel' },
          {
            text: `Sadece Kapora (${fmt(deposit)} ₺)`,
            onPress: () => submitReserveAPI('deposit'),
          },
          {
            text: `Tamamı: Bakiye Yükle`,
            onPress: () => savePendingAndGoWallet('full'),
          },
        ],
      );
      return;
    }

    // SENARYO C: Bakiye kapora için bile yetersiz → SOR (ne kadar yüklesin?)
    const eksikKapora = deposit - walletBakiye;
    const eksikTam = total - walletBakiye;
    Alert.alert(
      'Bakiyeniz Yetersiz',
      `Toplam Kira: ${fmt(total)} ₺\nKapora: ${fmt(deposit)} ₺\nMevcut Bakiyeniz: ${fmt(walletBakiye)} ₺\n\nEksik kalan tutarı yükleyin. Sadece kapora ile ya da tam ödeme ile rezerve yapabilirsiniz.`,
      [
        { text: 'Vazgeç', style: 'cancel' },
        {
          text: `Kapora için (+${fmt(eksikKapora)} ₺)`,
          onPress: () => savePendingAndGoWallet('deposit'),
        },
        {
          text: `Tamamı için (+${fmt(eksikTam)} ₺)`,
          onPress: () => savePendingAndGoWallet('full'),
        },
      ],
    );
  };

  // ref'i her render'da güncel tut
  submitReserveAPIRef.current = submitReserveAPI;

  const onConfirmPayment = async () => {
    if (!reservation) return;
    setSubmitting(true);
    try {
      await customerApi.confirmPayment(reservation.id);
      setStep('success');
    } catch (e: any) {
      Alert.alert('Hata', e.message);
    } finally {
      setSubmitting(false);
    }
  };

  // Yükleme sırasında boş ekran — kullanıcı gecikme hissetmesin (spinner kaldırıldı)
  if (loading || !vehicle) {
    return <View style={styles.loaderBg} />;
  }

  return (
    <View style={styles.bg}>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ paddingBottom: step === 'reserve' && pricing ? 110 : 100 }}>
          {/* Hero */}
          <View style={styles.heroWrap}>
            <Image source={{ uri: vehicle.foto_url || 'https://images.unsplash.com/photo-1494976388531-d1058494cdd8?w=1200' }} style={styles.heroImg} resizeMode="cover" />
            <View style={styles.heroOverlay} />
            <SafeAreaView edges={['top']} style={styles.heroTop}>
              <Pressable testID="back-btn" onPress={() => router.back()} style={styles.backBtn}>
                <Ionicons name="arrow-back" size={20} color="#fff" />
              </Pressable>
              <StatusBadge status={vehicle.durum} />
            </SafeAreaView>
            <View style={styles.heroBottom}>
              <View style={styles.plateMain}>
                <Text style={styles.plateMainText}>{vehicle.plaka}</Text>
              </View>
              <Text style={styles.heroBrand}>{vehicle.marka}</Text>
              <Text style={styles.heroModel}>{vehicle.model} • {vehicle.yil}</Text>
            </View>
          </View>

          {step === 'detail' && (
            <View style={styles.body}>
              <View style={styles.specsRow}>
                <Spec iconLib="mci" icon="car-shift-pattern" label="Vites" value={vehicle.vites} />
                <Spec iconLib="mci" icon="fuel" label="Yakıt" value={vehicle.yakit} />
                <Spec icon="color-palette-outline" label="Renk" value={vehicle.renk} />
                <Spec icon="speedometer-outline" label="Günlük KM" value={`${vehicle.gunluk_km} km`} />
              </View>

              {vehicle.aciklama ? (
                <GlassCard style={{ marginTop: Spacing.lg }}>
                  <Text style={styles.descTitle}>Açıklama</Text>
                  <Text style={styles.descText}>{vehicle.aciklama}</Text>
                </GlassCard>
              ) : null}

              <PulseButton
                testID="btn-start-reserve"
                title="REZERVASYON YAP"
                onPress={startReserveFlow}
                style={{ marginTop: Spacing.lg }}
              />

              {/* Yorumlar */}
              <ReviewsSection vehicleId={vehicle.id} />
            </View>
          )}

          {step === 'reserve' && (
            <View style={styles.body}>
              <Text style={styles.stepTitle}>Tarih ve Saat Seçin</Text>

              <GlassCard style={{ marginTop: Spacing.md }}>
                <DateTimePicker
                  availability={availability}
                  pickupDateTime={start}
                  returnDateTime={end}
                  onChangePickup={setStart}
                  onChangeReturn={setEnd}
                  minDate={minStartDate}
                />
                <View style={styles.summaryBox}>
                  <View style={styles.summaryRow}>
                    <Text style={styles.summaryLabel}>Süre</Text>
                    <Text style={styles.summaryValue}>{days} gün</Text>
                  </View>
                  <View style={styles.summaryRow}>
                    <Text style={styles.summaryLabel}>Teslim</Text>
                    <Text style={styles.summaryValue}>{pretty(start)}</Text>
                  </View>
                  <View style={styles.summaryRow}>
                    <Text style={styles.summaryLabel}>İade</Text>
                    <Text style={styles.summaryValue}>{pretty(end)}</Text>
                  </View>
                </View>
              </GlassCard>

              <GlassCard style={{ marginTop: Spacing.lg }}>
                <Text style={styles.modalLabel}>İletişim Telefonu</Text>
                <TextInput
                  testID="input-phone"
                  value={phone}
                  onChangeText={setPhone}
                  placeholder="+90 555 000 00 00"
                  placeholderTextColor={Colors.text.tertiary}
                  style={styles.input}
                  keyboardType="phone-pad"
                />
                <Text style={styles.helperText}>Rezervasyon onayı için ulaşılacak numara</Text>
              </GlassCard>

              {services.length > 0 && (
                <GlassCard style={{ marginTop: Spacing.lg }}>
                  <Text style={styles.modalLabel}>Ek Hizmetler</Text>
                  <View style={{ gap: 8, marginTop: 6 }}>
                    {services.map(svc => {
                      const isMandatory = !!svc.zorunlu;
                      const sel = isMandatory || (selectedServices[svc.id] || 0) > 0;
                      return (
                        <Pressable
                          key={svc.id}
                          testID={`svc-${svc.id}`}
                          onPress={() => {
                            if (isMandatory) return; // zorunlu — iptal edilemez
                            setSelectedServices(prev => ({ ...prev, [svc.id]: sel ? 0 : 1 }));
                          }}
                          disabled={isMandatory}
                          style={[styles.svcRow, sel && styles.svcRowActive, isMandatory && { borderColor: Colors.brand.primaryLight }]}
                        >
                          <View style={[styles.svcIcon, sel && { backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent }]}>
                            <Ionicons name={svc.icon as any} size={18} color={sel ? Colors.brand.primary : Colors.text.secondary} />
                          </View>
                          <View style={{ flex: 1 }}>
                            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                              <Text style={styles.svcName}>{svc.isim}</Text>
                              {isMandatory && (
                                <View style={{ paddingHorizontal: 6, paddingVertical: 2, backgroundColor: Colors.brand.primary, borderRadius: 4 }}>
                                  <Text style={{ color: '#fff', fontSize: 9, fontWeight: '900', letterSpacing: 0.5 }}>ZORUNLU</Text>
                                </View>
                              )}
                            </View>
                            <Text style={styles.svcDesc}>{svc.aciklama}</Text>
                          </View>
                          <View style={{ alignItems: 'flex-end' }}>
                            <Text style={[styles.svcPrice, sel && { color: Colors.brand.primary }]}>{svc.fiyat.toLocaleString('tr-TR')} ₺</Text>
                            <Text style={styles.svcType}>{svc.tip === 'gunluk' ? 'günlük' : 'tek seferlik'}</Text>
                          </View>
                          {isMandatory ? (
                            <Ionicons name="lock-closed" size={18} color={Colors.brand.primary} />
                          ) : (
                            <Ionicons name={sel ? 'checkmark-circle' : 'ellipse-outline'} size={20} color={sel ? Colors.brand.primary : Colors.text.tertiary} />
                          )}
                        </Pressable>
                      );
                    })}
                  </View>
                </GlassCard>
              )}

              <GlassCard highlight style={{ marginTop: Spacing.lg }}>
                <Text style={styles.modalLabel}>Tutar Özeti</Text>
                {!!pricing?.paket_km && (
                  <View style={[styles.summaryRow, { marginBottom: 4, alignItems: 'center' }]}>
                    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
                      <Ionicons name="speedometer" size={16} color={Colors.brand.primary} />
                      <Text style={[styles.summaryLabel, { color: Colors.brand.primary, fontWeight: '700' }]}>Toplam KM Hakkınız</Text>
                    </View>
                    <Text style={[styles.summaryValue, { color: Colors.brand.primary, fontWeight: '700' }]}>
                      {Number(pricing.paket_km).toLocaleString('tr-TR')} km
                    </Text>
                  </View>
                )}
                <View style={styles.summaryRow}>
                  <Text style={styles.summaryLabel}>
                    {days} gün × {(pricing?.gunluk_fiyat || vehicle.gunluk_fiyat).toLocaleString('tr-TR')} ₺/gün
                  </Text>
                  <Text style={styles.summaryValue}>{(pricing?.arac_alt_toplam || 0).toLocaleString('tr-TR')} ₺</Text>
                </View>
                {/* Süre indirimi (kazanç olarak gösterilir) — sadece tasarruf varsa göster */}
                {pricing?.fiyat_kademe && pricing.gunluk_fiyat_baz && pricing.fiyat_kademe.gunluk_fiyat < pricing.gunluk_fiyat_baz && (
                  <View style={styles.summaryRow}>
                    <Text style={[styles.summaryLabel, { color: Colors.status.success }]}>🎉 Kazancınız</Text>
                    <Text style={[styles.summaryValue, { color: Colors.status.success, fontWeight: '700' }]}>
                      +{(days * (pricing.gunluk_fiyat_baz - pricing.fiyat_kademe.gunluk_fiyat)).toLocaleString('tr-TR')} ₺
                    </Text>
                  </View>
                )}
                {pricing?.sure_indirim_yuzde > 0 && (
                  <View style={styles.summaryRow}>
                    <Text style={[styles.summaryLabel, { color: Colors.status.success }]}>🎉 Kazancınız (%{pricing.sure_indirim_yuzde}, {days}+ gün)</Text>
                    <Text style={[styles.summaryValue, { color: Colors.status.success }]}>+{pricing.sure_indirim_tutar.toLocaleString('tr-TR')} ₺</Text>
                  </View>
                )}
                {pricing?.hizmetler?.length > 0 && pricing.hizmetler.map((h: any) => (
                  <View key={h.service_id} style={styles.summaryRow}>
                    <Text style={styles.summaryLabel}>{h.isim} ({h.tip === 'gunluk' ? `${h.adet}×${days}g` : 'tek seferlik'})</Text>
                    <Text style={styles.summaryValue}>+{h.tutar.toLocaleString('tr-TR')} ₺</Text>
                  </View>
                ))}
                <View style={styles.summaryDivider} />
                <View style={styles.summaryRow}>
                  <Text style={styles.summaryLabelBold}>Toplam</Text>
                  <Text style={[styles.summaryValueBold, { color: Colors.text.primary }]}>{total.toLocaleString('tr-TR')} ₺</Text>
                </View>
                <View style={styles.summaryRow}>
                  <Text style={styles.summaryLabelBold}>Ön Ödeme (%20)</Text>
                  <Text style={[styles.summaryValueBold, { color: Colors.brand.primary }]}>{deposit.toLocaleString('tr-TR')} ₺</Text>
                </View>
                <View style={styles.summaryRow}>
                  <Text style={styles.summaryLabel}>Kalan (Teslimde)</Text>
                  <Text style={styles.summaryValue}>{remaining.toLocaleString('tr-TR')} ₺</Text>
                </View>
                <View style={[styles.balanceInfoBox, walletBakiye < deposit && styles.balanceInfoBoxLow]}>
                  <Ionicons name={walletBakiye >= deposit ? 'checkmark-circle' : 'wallet'} size={16} color={walletBakiye >= deposit ? Colors.status.success : Colors.status.warning} />
                  <Text style={[styles.balanceInfoText, walletBakiye < deposit && { color: Colors.status.warning }]}>
                    Bakiye: {walletBakiye.toLocaleString('tr-TR')} ₺ {walletBakiye >= deposit ? '— Ön ödeme bakiyeden alınacak' : '— Bakiye yetersiz, yüklemeye yönlendirileceksiniz'}
                  </Text>
                </View>
              </GlassCard>

              <GlassButton
                testID="btn-reserve"
                title="REZERVASYONU OLUŞTUR"
                onPress={onReserve}
                loading={submitting}
                size="lg"
                style={{ marginTop: Spacing.lg }}
              />
              <GlassButton
                title="VAZGEÇ"
                onPress={() => setStep('detail')}
                variant="ghost"
                style={{ marginTop: Spacing.sm }}
              />
            </View>
          )}

          {step === 'payment' && reservation && (
            <View style={styles.body}>
              <View style={styles.successWrap}>
                <View style={styles.successIcon}>
                  <Ionicons name="checkmark-circle" size={40} color={Colors.status.success} />
                </View>
                <Text style={styles.successTitle}>Rezervasyon Oluşturuldu</Text>
                <Text style={styles.successSub}>%20 ön ödeme ile rezervasyonunuzu kesinleştirin</Text>
              </View>

              <GlassCard highlight style={{ marginTop: Spacing.lg, padding: Spacing.xl, alignItems: 'center' }}>
                <Text style={styles.modalLabel}>Ön Ödeme Tutarı</Text>
                <Text style={styles.bigPrice}>{reservation.on_odeme_tutar.toLocaleString('tr-TR')} ₺</Text>
                <Text style={styles.priceSub}>Toplam: {reservation.toplam_tutar.toLocaleString('tr-TR')} ₺ (Kalan: {reservation.kalan_odeme.toLocaleString('tr-TR')} ₺)</Text>
              </GlassCard>

              <GlassCard style={{ marginTop: Spacing.lg }}>
                <Text style={styles.modalLabel}>Banka Bilgileri (IBAN)</Text>
                <View style={{ marginTop: Spacing.sm, gap: Spacing.xs }}>
                  <Row label="Banka" value={settings.banka || '—'} />
                  <Row label="Hesap Sahibi" value={settings.hesap_sahibi || '—'} />
                  <View>
                    <Text style={styles.summaryLabel}>IBAN</Text>
                    <Text selectable style={styles.iban}>{settings.iban || '—'}</Text>
                  </View>
                  <Row label="Açıklama" value={`Rezervasyon #${reservation.id.slice(0, 8)}`} />
                </View>
              </GlassCard>

              <View style={styles.warningBox}>
                <Ionicons name="information-circle" size={18} color={Colors.status.info} />
                <Text style={styles.warningText}>
                  Transferinizi yaptıktan sonra "Ödedim, Bildir" butonuna basın. Rezervasyonunuz yönetici onayı sonrası aktif olacaktır.
                </Text>
              </View>

              <GlassButton
                testID="btn-payment-done"
                title="ÖDEDİM, BİLDİR"
                onPress={onConfirmPayment}
                loading={submitting}
                size="lg"
                style={{ marginTop: Spacing.lg }}
              />
            </View>
          )}

          {step === 'success' && (
            <View style={[styles.body, { alignItems: 'center', paddingVertical: Spacing.xxxl }]}>
              <View style={styles.successIconLarge}>
                <Ionicons name="checkmark" size={48} color="#fff" />
              </View>
              <Text style={styles.successBigTitle}>
                {reservation?.durum === 'onaylandi' ? 'Rezervasyonunuz Onaylandı' : 'Bildiriminiz Alındı'}
              </Text>
              <Text style={styles.successBigSub}>
                {reservation?.durum === 'onaylandi'
                  ? `Bakiyenizden ${(reservation?.odenen_ucret || 0).toLocaleString('tr-TR')} ₺ tahsil edildi. Rezervasyonunuz kesinleşti — teslim alış tarihinde aracınızı alabilirsiniz.`
                  : 'Yönetici en kısa sürede ödemenizi onaylayacaktır. Bildirimleri takip edin.'}
              </Text>
              <GlassButton
                title="ANA SAYFAYA DÖN"
                onPress={() => router.replace('/(tabs)')}
                size="lg"
                style={{ marginTop: Spacing.xxl }}
              />
              <GlassButton
                title="KİRALARIMI GÖSTER"
                onPress={() => router.replace('/(tabs)/rentals')}
                variant="secondary"
                style={{ marginTop: Spacing.sm }}
              />
            </View>
          )}
        </ScrollView>

        {/* Sticky bottom total bar — sadece rezervasyon adımında ve fiyat hesaplandığında görünür */}
        {step === 'reserve' && pricing && (
          <SafeAreaView edges={['bottom']} style={styles.stickyBar}>
            <View style={{ flex: 1 }}>
              <Text style={{ ...Typography.micro, color: Colors.text.tertiary, textTransform: 'uppercase' }}>Toplam</Text>
              <Text style={{ ...Typography.h2, color: Colors.brand.primaryLight, fontWeight: '800' }}>
                {total.toLocaleString('tr-TR')} ₺
              </Text>
            </View>
            {pricing.fiyat_kademe && pricing.gunluk_fiyat_baz && pricing.fiyat_kademe.gunluk_fiyat < pricing.gunluk_fiyat_baz && (
              <View style={{ paddingHorizontal: 8, paddingVertical: 4, backgroundColor: Colors.status.success + '20', borderRadius: 6, marginRight: 8 }}>
                <Text style={{ fontSize: 10, color: Colors.status.success, fontWeight: '700' }}>
                  +{(days * (pricing.gunluk_fiyat_baz - pricing.fiyat_kademe.gunluk_fiyat)).toLocaleString('tr-TR')}₺
                </Text>
                <Text style={{ fontSize: 9, color: Colors.status.success }}>kazancınız</Text>
              </View>
            )}
          </SafeAreaView>
        )}
      </KeyboardAvoidingView>
    </View>
  );
}

function Spec({ icon, label, value, iconLib }: any) {
  return (
    <View style={styles.spec}>
      {iconLib === 'mci' ? (
        <MaterialCommunityIcons name={icon} size={16} color={Colors.brand.primary} />
      ) : (
        <Ionicons name={icon} size={16} color={Colors.brand.primary} />
      )}
      <Text style={styles.specLabel}>{label}</Text>
      <Text style={styles.specValue}>{value}</Text>
    </View>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.summaryRow}>
      <Text style={styles.summaryLabel}>{label}</Text>
      <Text style={styles.summaryValue}>{value}</Text>
    </View>
  );
}

// ===== Reviews Section =====
function ReviewsSection({ vehicleId }: { vehicleId: string }) {
  const [data, setData] = useState<{ reviews: any[]; ortalama_arac: number; ortalama_servis: number; toplam: number } | null>(null);
  const [minStar, setMinStar] = useState(0);

  useEffect(() => {
    (async () => {
      try {
        const res = await customerApi.vehicleReviews(vehicleId, minStar);
        setData(res);
      } catch {}
    })();
  }, [vehicleId, minStar]);

  if (!data) return null;
  if (data.toplam === 0 && minStar === 0) {
    return (
      <View style={{ marginTop: Spacing.xl }}>
        <Text style={{ ...Typography.h3, color: Colors.text.primary, marginBottom: 8 }}>⭐ Yorumlar</Text>
        <GlassCard>
          <View style={{ alignItems: 'center', padding: 16 }}>
            <Ionicons name="chatbubbles-outline" size={36} color={Colors.text.tertiary} />
            <Text style={{ ...Typography.caption, color: Colors.text.tertiary, marginTop: 6 }}>Henüz yorum yok</Text>
            <Text style={{ ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 }}>İlk yorumu sen bırak!</Text>
          </View>
        </GlassCard>
      </View>
    );
  }

  return (
    <View style={{ marginTop: Spacing.xl }}>
      <Text style={{ ...Typography.h3, color: Colors.text.primary, marginBottom: 8 }}>⭐ Yorumlar ({data.toplam})</Text>
      {/* Ortalama özeti */}
      <GlassCard>
        <View style={{ flexDirection: 'row', justifyContent: 'space-around' }}>
          <View style={{ alignItems: 'center' }}>
            <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Araç</Text>
            <Stars value={data.ortalama_arac} size={18} />
            <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 }}>{data.ortalama_arac.toFixed(1)}/5</Text>
          </View>
          <View style={{ alignItems: 'center' }}>
            <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Servis</Text>
            <Stars value={data.ortalama_servis} size={18} />
            <Text style={{ ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 }}>{data.ortalama_servis.toFixed(1)}/5</Text>
          </View>
        </View>
      </GlassCard>

      {/* Yıldız filtresi */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 10 }} contentContainerStyle={{ gap: 6 }}>
        {[0, 5, 4, 3, 2, 1].map(s => (
          <Pressable key={s} onPress={() => setMinStar(s)} style={{
            paddingHorizontal: 10, paddingVertical: 5, borderRadius: 14,
            backgroundColor: minStar === s ? Colors.brand.primary : Colors.bg.surface2,
            borderWidth: 1, borderColor: minStar === s ? Colors.brand.primary : Colors.border.base,
            flexDirection: 'row', alignItems: 'center', gap: 3,
          }}>
            <Text style={{ fontSize: 11, color: minStar === s ? '#fff' : Colors.text.primary, fontWeight: '700' }}>{s === 0 ? 'Tümü' : `${s}+`}</Text>
            {s > 0 && <Ionicons name="star" size={10} color={minStar === s ? '#fff' : '#FBBF24'} />}
          </Pressable>
        ))}
      </ScrollView>

      {/* Yorumlar */}
      <View style={{ gap: 10, marginTop: 12 }}>
        {data.reviews.length === 0 ? (
          <Text style={{ ...Typography.caption, color: Colors.text.tertiary, textAlign: 'center', padding: 16 }}>Bu filtreye uyan yorum yok</Text>
        ) : data.reviews.map(r => (
          <GlassCard key={r.id}>
            <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <View style={{ flex: 1 }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{r.customer_display}</Text>
                <Text style={{ ...Typography.micro, color: Colors.text.tertiary }}>{new Date(r.tarih).toLocaleDateString('tr-TR')}</Text>
              </View>
            </View>
            <View style={{ flexDirection: 'row', gap: 12, marginTop: 6 }}>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Araç</Text>
                <Stars value={r.arac_puan} size={12} />
              </View>
              <View style={{ flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                <Text style={{ ...Typography.micro, color: Colors.text.secondary }}>Servis</Text>
                <Stars value={r.servis_puan} size={12} />
              </View>
            </View>
            {!!r.yorum && <Text style={{ ...Typography.body, color: Colors.text.primary, marginTop: 8 }}>{r.yorum}</Text>}
            {!!r.admin_cevap && (
              <View style={{ marginTop: 8, paddingLeft: 10, borderLeftWidth: 2, borderLeftColor: Colors.brand.primary }}>
                <Text style={{ ...Typography.micro, color: Colors.brand.primary, fontWeight: '700' }}>YS AUTO Cevabı</Text>
                <Text style={{ ...Typography.caption, color: Colors.text.secondary, marginTop: 2 }}>{r.admin_cevap}</Text>
              </View>
            )}
          </GlassCard>
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: Colors.bg.base },
  loaderBg: { flex: 1, backgroundColor: Colors.bg.base, alignItems: 'center', justifyContent: 'center' },
  heroWrap: { height: 320, position: 'relative', backgroundColor: Colors.bg.surface },
  heroImg: { width: '100%', height: '100%' },
  heroOverlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.45)' },
  heroTop: { position: 'absolute', top: 0, left: 0, right: 0, paddingHorizontal: Spacing.xl, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingTop: Spacing.md },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: 'rgba(0,0,0,0.5)', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base },
  heroBottom: { position: 'absolute', bottom: Spacing.xl, left: Spacing.xl, right: Spacing.xl },
  plateMain: { backgroundColor: '#fff', alignSelf: 'flex-start', paddingHorizontal: 12, paddingVertical: 6, borderRadius: 6, borderWidth: 2, borderColor: '#000', marginBottom: Spacing.sm },
  plateMainText: { fontSize: 18, fontWeight: '900', color: '#000', letterSpacing: 1 },
  heroBrand: { ...Typography.micro, color: Colors.brand.primary, letterSpacing: 2 },
  heroModel: { ...Typography.h1, color: '#fff', fontSize: 28 },
  body: { padding: Spacing.xl },
  specsRow: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  spec: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: Colors.bg.surface, paddingHorizontal: Spacing.md, paddingVertical: 8, borderRadius: Radius.pill, borderWidth: 1, borderColor: Colors.border.base },
  specLabel: { ...Typography.micro, color: Colors.text.secondary },
  specValue: { ...Typography.caption, color: Colors.text.primary, fontWeight: '700' },
  descTitle: { ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 4 },
  descText: { ...Typography.body, color: Colors.text.secondary, lineHeight: 22 },
  priceLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' },
  priceMain: { fontSize: 36, fontWeight: '900', color: Colors.brand.primary, letterSpacing: -0.5, marginTop: 4 },
  priceSub: { ...Typography.caption, color: Colors.text.tertiary, marginTop: 4 },
  stepTitle: { ...Typography.h2, color: Colors.text.primary, marginTop: Spacing.md },
  modalLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginBottom: 6 },
  dateChips: { flexDirection: 'row', gap: 6, flexWrap: 'wrap' },
  dateChip: { paddingHorizontal: Spacing.md, paddingVertical: 8, borderRadius: Radius.pill, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base },
  dateChipActive: { backgroundColor: Colors.brand.primary, borderColor: Colors.brand.primary },
  dateChipText: { ...Typography.caption, color: Colors.text.secondary },
  dateChipTextActive: { color: '#fff', fontWeight: '700' },
  daysControl: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: Spacing.md, marginTop: Spacing.sm },
  daysBtn: { width: 48, height: 48, borderRadius: 24, backgroundColor: Colors.brand.primary, alignItems: 'center', justifyContent: 'center' },
  daysDisplay: { flex: 1, alignItems: 'center' },
  daysValue: { fontSize: 36, fontWeight: '900', color: Colors.text.primary },
  daysLabel: { ...Typography.caption, color: Colors.text.secondary },
  summaryBox: { marginTop: Spacing.lg, padding: Spacing.md, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, gap: 6 },
  summaryRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  summaryLabel: { ...Typography.caption, color: Colors.text.secondary },
  summaryValue: { ...Typography.bodyBold, color: Colors.text.primary },
  summaryLabelBold: { ...Typography.bodyBold, color: Colors.text.primary },
  summaryValueBold: { ...Typography.h4, color: Colors.text.primary },
  summaryDivider: { height: 1, backgroundColor: Colors.border.base, marginVertical: Spacing.sm },
  input: { backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, padding: Spacing.md, color: Colors.text.primary, borderWidth: 1, borderColor: Colors.border.base, fontSize: 15 },
  helperText: { ...Typography.micro, color: Colors.text.tertiary, marginTop: 4 },
  successWrap: { alignItems: 'center', marginTop: Spacing.md },
  successIcon: { width: 64, height: 64, borderRadius: 32, backgroundColor: 'rgba(52, 199, 89, 0.15)', alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.status.success },
  successTitle: { ...Typography.h2, color: Colors.text.primary, marginTop: Spacing.md },
  successSub: { ...Typography.caption, color: Colors.text.secondary, marginTop: 4, textAlign: 'center' },
  bigPrice: { fontSize: 44, fontWeight: '900', color: Colors.brand.primary, marginTop: 6 },
  stickyBar: { position: 'absolute', bottom: 0, left: 0, right: 0, flexDirection: 'row', alignItems: 'center', backgroundColor: Colors.bg.surface, borderTopWidth: 1, borderTopColor: Colors.border.base, paddingHorizontal: Spacing.lg, paddingTop: Spacing.sm, paddingBottom: Spacing.sm, ...Platform.select({ ios: { shadowColor: '#000', shadowOffset: { width: 0, height: -2 }, shadowOpacity: 0.15, shadowRadius: 8 }, android: { elevation: 12 } }) },
  iban: { ...Typography.bodyBold, color: Colors.text.primary, fontVariant: ['tabular-nums'], letterSpacing: 0.5, marginTop: 4 },
  warningBox: { flexDirection: 'row', gap: 8, padding: Spacing.md, backgroundColor: 'rgba(90, 200, 250, 0.08)', borderRadius: Radius.md, marginTop: Spacing.md, borderLeftWidth: 3, borderLeftColor: Colors.status.info },
  warningText: { ...Typography.caption, color: Colors.text.secondary, flex: 1, lineHeight: 18 },
  successIconLarge: { width: 96, height: 96, borderRadius: 48, backgroundColor: Colors.status.success, alignItems: 'center', justifyContent: 'center', shadowColor: Colors.status.success, shadowOpacity: 0.5, shadowRadius: 24, elevation: 8 },
  successBigTitle: { ...Typography.h1, color: Colors.text.primary, marginTop: Spacing.lg, textAlign: 'center' },
  successBigSub: { ...Typography.body, color: Colors.text.secondary, marginTop: Spacing.sm, textAlign: 'center', lineHeight: 22 },
  balanceInfoBox: { flexDirection: 'row', alignItems: 'center', gap: 6, padding: 10, marginTop: Spacing.sm, backgroundColor: 'rgba(52, 199, 89, 0.10)', borderRadius: Radius.md, borderLeftWidth: 3, borderLeftColor: Colors.status.success },
  balanceInfoBoxLow: { backgroundColor: 'rgba(255, 149, 0, 0.10)', borderLeftColor: Colors.status.warning },
  balanceInfoText: { ...Typography.caption, color: Colors.text.primary, flex: 1 },
  svcRow: { flexDirection: 'row', alignItems: 'center', gap: 10, padding: Spacing.md, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base },
  svcRowActive: { borderColor: Colors.border.accent, backgroundColor: Colors.bg.glassRed },
  svcIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: Colors.bg.surface, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base },
  svcName: { ...Typography.bodyBold, color: Colors.text.primary },
  svcDesc: { ...Typography.caption, color: Colors.text.secondary, marginTop: 2 },
  svcPrice: { ...Typography.bodyBold, color: Colors.text.primary, fontWeight: '800' },
  svcType: { ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 },
});
