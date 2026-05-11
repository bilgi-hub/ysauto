/**
 * Müşteri Yorum Bırakma Ekranı
 * /review/[rid] — rid: reservation_id
 */
import React, { useEffect, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TextInput, Pressable, Alert, KeyboardAvoidingView, Platform } from 'react-native';
import { useLocalSearchParams, router } from 'expo-router';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import { Colors, Radius, Spacing, Typography } from '../../src/theme';
import { GlassCard, GlassButton } from '../../src/ui';
import { Stars } from '../../src/Stars';
import { customerApi } from '../../src/api';

export default function ReviewScreen() {
  const { rid } = useLocalSearchParams<{ rid: string }>();
  const [reservation, setReservation] = useState<any>(null);
  const [aracPuan, setAracPuan] = useState(0);
  const [servisPuan, setServisPuan] = useState(0);
  const [yorum, setYorum] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [alreadyReviewed, setAlreadyReviewed] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const pending = await customerApi.pendingReviewReservations();
        const r = (pending || []).find((x: any) => x.id === rid);
        if (r) {
          setReservation(r);
        } else {
          // Belki zaten yorum bırakılmış
          try {
            const mine = await customerApi.myReviews();
            if (mine.some((m: any) => m.reservation_id === rid)) {
              setAlreadyReviewed(true);
            }
          } catch {}
        }
      } catch {} finally {
        setLoading(false);
      }
    })();
  }, [rid]);

  const submit = async () => {
    if (aracPuan === 0 || servisPuan === 0) {
      Alert.alert('Eksik Puan', 'Lütfen hem araç hem servis için en az 1 yıldız seçin.');
      return;
    }
    setSubmitting(true);
    try {
      await customerApi.createReview({
        reservation_id: rid!,
        arac_puan: aracPuan,
        servis_puan: servisPuan,
        yorum: yorum.trim(),
      });
      Alert.alert('Teşekkürler! 🌟', 'Yorumunuz alındı. Onaylandıktan sonra yayınlanacak.', [
        { text: 'Tamam', onPress: () => router.back() },
      ]);
    } catch (e: any) {
      Alert.alert('Hata', e?.message || 'Yorum gönderilemedi');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <Header title="Yorum" />
        <View style={{ flex: 1 }} />
      </SafeAreaView>
    );
  }

  if (alreadyReviewed) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <Header title="Yorum" />
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.xl }}>
          <Ionicons name="checkmark-circle" size={64} color={Colors.status.success} />
          <Text style={{ ...Typography.h2, color: Colors.text.primary, marginTop: 12 }}>Yorum Mevcut</Text>
          <Text style={{ ...Typography.body, color: Colors.text.secondary, textAlign: 'center', marginTop: 6 }}>
            Bu kiralama için zaten bir yorum bıraktınız. Teşekkürler! ⭐
          </Text>
          <GlassButton title="GERİ DÖN" onPress={() => router.back()} size="lg" style={{ marginTop: 20 }} />
        </View>
      </SafeAreaView>
    );
  }

  if (!reservation) {
    return (
      <SafeAreaView style={styles.container} edges={['top']}>
        <Header title="Yorum" />
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: Spacing.xl }}>
          <Ionicons name="alert-circle-outline" size={48} color={Colors.text.tertiary} />
          <Text style={{ ...Typography.body, color: Colors.text.secondary, marginTop: 8, textAlign: 'center' }}>
            Bu kiralama için yorum yapamazsınız. Sadece tamamlanmış ve daha önce yorum yapılmamış kiralamalar için yorum yapılabilir.
          </Text>
          <GlassButton title="GERİ DÖN" onPress={() => router.back()} size="lg" style={{ marginTop: 20 }} />
        </View>
      </SafeAreaView>
    );
  }

  const v = reservation.vehicle_snapshot || {};

  return (
    <SafeAreaView style={styles.container} edges={['top']}>
      <Header title="Yorum Bırak" />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: Spacing.xl, gap: Spacing.lg, paddingBottom: 40 }}>
          {/* Araç bilgisi */}
          <GlassCard>
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
              <View style={{ width: 56, height: 56, borderRadius: 8, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center' }}>
                <Ionicons name="car-sport" size={28} color={Colors.brand.primary} />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={{ ...Typography.bodyBold, color: Colors.text.primary }}>{v.marka} {v.model}</Text>
                <Text style={{ ...Typography.caption, color: Colors.text.secondary }}>{v.plaka} • {reservation.gun_sayisi} gün</Text>
              </View>
            </View>
          </GlassCard>

          {/* Araç Puanı */}
          <GlassCard>
            <Text style={styles.section}>🚗 Araç Puanınız</Text>
            <Text style={styles.sectionSub}>Araç temizliği, durumu, performansı hakkında</Text>
            <View style={{ alignItems: 'center', marginTop: 12 }}>
              <Stars value={aracPuan} onChange={setAracPuan} size={42} />
              <Text style={{ ...Typography.bodyBold, color: Colors.brand.primary, marginTop: 8 }}>{aracPuan > 0 ? `${aracPuan}/5` : 'Seçim yapın'}</Text>
            </View>
          </GlassCard>

          {/* Servis Puanı */}
          <GlassCard>
            <Text style={styles.section}>🎯 Servis Puanınız</Text>
            <Text style={styles.sectionSub}>İletişim, teslim alma, iade süreci hakkında</Text>
            <View style={{ alignItems: 'center', marginTop: 12 }}>
              <Stars value={servisPuan} onChange={setServisPuan} size={42} />
              <Text style={{ ...Typography.bodyBold, color: Colors.brand.primary, marginTop: 8 }}>{servisPuan > 0 ? `${servisPuan}/5` : 'Seçim yapın'}</Text>
            </View>
          </GlassCard>

          {/* Yorum (opsiyonel) */}
          <GlassCard>
            <Text style={styles.section}>💬 Yorumunuz (Opsiyonel)</Text>
            <Text style={styles.sectionSub}>Deneyiminizi paylaşın — diğer müşterilere yardımcı olun</Text>
            <TextInput
              value={yorum}
              onChangeText={setYorum}
              placeholder="Örn. Araç tertemizdi, süreç hızlıydı..."
              placeholderTextColor={Colors.text.tertiary}
              multiline
              numberOfLines={4}
              maxLength={500}
              style={styles.textarea}
            />
            <Text style={{ ...Typography.micro, color: Colors.text.tertiary, textAlign: 'right', marginTop: 4 }}>{yorum.length}/500</Text>
          </GlassCard>

          <GlassButton title={submitting ? 'GÖNDERİLİYOR…' : 'YORUMU GÖNDER'} onPress={submit} loading={submitting} size="lg" disabled={aracPuan === 0 || servisPuan === 0} />
          <Text style={{ ...Typography.micro, color: Colors.text.tertiary, textAlign: 'center' }}>
            ℹ️ Yorumunuz admin onayından sonra yayınlanacaktır.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Header({ title }: { title: string }) {
  return (
    <View style={styles.header}>
      <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn}>
        <Ionicons name="chevron-back" size={26} color={Colors.text.primary} />
      </Pressable>
      <Text style={styles.headerTitle}>{title}</Text>
      <View style={{ width: 32 }} />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.bg.base },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: Spacing.lg, paddingVertical: Spacing.sm, borderBottomWidth: 1, borderBottomColor: Colors.border.base },
  backBtn: { width: 32, height: 32, alignItems: 'center', justifyContent: 'center' },
  headerTitle: { ...Typography.h3, color: Colors.text.primary, flex: 1, textAlign: 'center' },
  section: { ...Typography.bodyBold, color: Colors.text.primary },
  sectionSub: { ...Typography.caption, color: Colors.text.secondary, marginTop: 2 },
  textarea: {
    marginTop: 12,
    minHeight: 90,
    color: Colors.text.primary,
    backgroundColor: Colors.bg.surface2,
    borderRadius: Radius.md,
    borderWidth: 1,
    borderColor: Colors.border.base,
    padding: 12,
    textAlignVertical: 'top',
    fontSize: 14,
  },
});
