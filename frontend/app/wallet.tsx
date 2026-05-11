/**
 * Cüzdan / Bakiye - Top up via card or havale, view transactions
 */
import React, { useState, useCallback, useEffect } from 'react';
import { View, Text, StyleSheet, ScrollView, RefreshControl, Pressable, TextInput, Alert, ActivityIndicator, Modal, KeyboardAvoidingView, Platform, Image } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useRouter, useLocalSearchParams } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import * as Clipboard from 'expo-clipboard';
import { customerApi, WalletTx, Settings } from '../src/api';
import { Colors, Radius, Spacing, Typography } from '../src/theme';
import { GlassCard, GlassButton, Empty } from '../src/ui';

const PENDING_KEY = 'ys_pending_reservation';

function fmtDate(s: string) {
  try {
    return new Date(s).toLocaleString('tr-TR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
  } catch { return s; }
}

function CopyRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    if (!value || value === '—') return;
    try {
      await Clipboard.setStringAsync(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  };
  return (
    <View style={{ marginBottom: 8 }}>
      <Text style={{ ...Typography.micro, color: Colors.text.tertiary, fontWeight: '700', letterSpacing: 0.5, marginBottom: 2 }}>{label}</Text>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
        <Text
          selectable
          style={{
            flex: 1,
            ...(mono ? { fontSize: 14, letterSpacing: 1, fontFamily: Platform.select({ ios: 'Menlo', android: 'monospace', default: 'monospace' }) } : { fontSize: 15 }),
            color: Colors.text.primary,
            fontWeight: '700',
          }}
          numberOfLines={mono ? 2 : 1}
        >
          {value || '—'}
        </Text>
        <Pressable
          onPress={onCopy}
          disabled={!value || value === '—'}
          style={{
            flexDirection: 'row', alignItems: 'center', gap: 4,
            paddingHorizontal: 10, paddingVertical: 6,
            borderRadius: 6,
            backgroundColor: copied ? Colors.status.success + '30' : Colors.bg.surface2,
            borderWidth: 1,
            borderColor: copied ? Colors.status.success : Colors.border.base,
            opacity: (!value || value === '—') ? 0.4 : 1,
          }}
        >
          <Ionicons name={copied ? 'checkmark' : 'copy-outline'} size={14} color={copied ? Colors.status.success : Colors.text.secondary} />
          <Text style={{ fontSize: 11, fontWeight: '700', color: copied ? Colors.status.success : Colors.text.secondary }}>
            {copied ? 'KOPYALANDI' : 'KOPYALA'}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function WalletScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ topup?: string; amount?: string }>();
  const [bakiye, setBakiye] = useState(0);
  const [txs, setTxs] = useState<WalletTx[]>([]);
  const [settings, setSettings] = useState<Settings>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [topupOpen, setTopupOpen] = useState(false);
  const [yontem, setYontem] = useState<'shopier' | 'havale'>('havale');
  const [tutar, setTutar] = useState('');
  const [havaleRef, setHavaleRef] = useState('');
  const [dekontB64, setDekontB64] = useState<string | null>(null);  // Havale dekont fotoğrafı
  const [dekontUploading, setDekontUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [shopierMock, setShopierMock] = useState<{ order_id: string; tutar: number; mode: 'real' | 'mock' } | null>(null);

  const load = useCallback(async () => {
    try {
      const [w, t, s] = await Promise.all([
        customerApi.wallet(),
        customerApi.walletTx(),
        customerApi.publicSettings(),
      ]);
      setBakiye(w.bakiye);
      setTxs(t);
      setSettings(s);
    } catch {} finally {
      setLoading(false); setRefreshing(false);
    }
  }, []);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  // URL'den geliyorsa otomatik topup modal'ını aç
  useEffect(() => {
    if (params?.topup === '1' && !topupOpen) {
      setTopupOpen(true);
      if (params.amount && !tutar) {
        setTutar(String(params.amount));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params?.topup, params?.amount]);

  // Topup başarılı olduktan sonra pending rezervasyon var mı kontrol et
  const checkPendingAfterTopup = async (newBakiye: number) => {
    try {
      const pendingStr = await AsyncStorage.getItem(PENDING_KEY);
      if (!pendingStr) return false;
      const pending = JSON.parse(pendingStr);
      if (!pending?.vehicleId || !pending?.required) return false;
      if (newBakiye >= pending.required) {
        Alert.alert(
          'Bekleyen Rezervasyon',
          `Bakiyeniz şimdi yeterli (${newBakiye.toLocaleString('tr-TR')} ₺). Daha önce başlattığınız ${pending.required.toLocaleString('tr-TR')} ₺'lik rezervasyonu otomatik olarak oluşturmak ister misiniz?`,
          [
            { text: 'Vazgeç', style: 'cancel', onPress: () => AsyncStorage.removeItem(PENDING_KEY) },
            {
              text: 'Evet, Oluştur',
              onPress: () => {
                router.replace({ pathname: '/vehicle/[id]', params: { id: pending.vehicleId, autoSubmit: '1' } });
              },
            },
          ],
        );
        return true;
      } else {
        Alert.alert(
          'Bakiye Hala Yetersiz',
          `Rezervasyon için ${pending.required.toLocaleString('tr-TR')} ₺ gerekli. Şu an ${newBakiye.toLocaleString('tr-TR')} ₺'niz var. ${(pending.required - newBakiye).toLocaleString('tr-TR')} ₺ daha yükleyin.`,
        );
        return false;
      }
    } catch { return false; }
  };

  const pickDekont = async (source: 'camera' | 'library') => {
    try {
      setDekontUploading(true);
      let perm;
      if (source === 'camera') {
        perm = await ImagePicker.requestCameraPermissionsAsync();
      } else {
        perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      }
      if (!perm.granted) { Alert.alert('İzin Gerekli', source === 'camera' ? 'Kamera izni verilmedi' : 'Galeri izni verilmedi'); return; }
      const result = source === 'camera'
        ? await ImagePicker.launchCameraAsync({ quality: 0.7, base64: true, allowsEditing: false, mediaTypes: ['images'] })
        : await ImagePicker.launchImageLibraryAsync({ quality: 0.7, base64: true, allowsEditing: false, mediaTypes: ['images'] });
      if (result.canceled || !result.assets?.[0]) return;
      const b64 = result.assets[0].base64;
      if (!b64) { Alert.alert('Hata', 'Fotoğraf okunamadı'); return; }
      if (b64.length > 8 * 1024 * 1024) { Alert.alert('Hata', 'Fotoğraf çok büyük (max ~6MB). Daha düşük çözünürlük seçin.'); return; }
      setDekontB64(`data:image/jpeg;base64,${b64}`);
    } catch (e: any) {
      Alert.alert('Hata', e?.message || 'Fotoğraf yüklenemedi');
    } finally {
      setDekontUploading(false);
    }
  };

  const onSubmit = async () => {
    const t = parseFloat(tutar.replace(',', '.'));
    if (!t || t < 50) { Alert.alert('Hata', 'En az 50 ₺ yükleme yapılabilir'); return; }
    if (yontem !== 'havale') { Alert.alert('Bilgi', 'Şu an sadece HAVALE/EFT ile bakiye yükleme aktiftir. Shopier yakında devreye alınacaktır.'); return; }
    setSubmitting(true);
    try {
      // HAVALE: dekont zorunlu
      if (!dekontB64) { Alert.alert('Eksik', 'Lütfen dekont fotoğrafı yükleyin'); setSubmitting(false); return; }
      const r: any = await customerApi.walletTopup({ tutar: t, yontem: 'havale', havale_referans: havaleRef, dekont_base64: dekontB64 });
      if (r.ai_onay) {
        Alert.alert('Otomatik Onay ✅', `Dekontunuz AI doğrulamasından geçti. Bakiyenize ${t.toFixed(2)} ₺ eklendi.\nYeni bakiye: ${(r.bakiye || 0).toFixed(2)} ₺`);
      } else {
        const reasons = r.ai_result?.reasons?.length ? `\n\nSebep: ${r.ai_result.reasons.slice(0, 3).join('; ')}` : '';
        Alert.alert('İncelemeye Alındı 🕒', `Dekontunuz incelemeye alındı. Yönetici onayı sonrası bakiyenize işlenecektir.${reasons}`);
      }
      setTopupOpen(false);
      setTutar(''); setHavaleRef(''); setDekontB64(null);
      load();
    } catch (e: any) {
      Alert.alert('Hata', e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const confirmShopierMock = async () => {
    if (!shopierMock) return;
    setSubmitting(true);
    try {
      const r = await customerApi.shopierMockConfirm(shopierMock.order_id);
      const tutarVal = shopierMock.tutar;
      setShopierMock(null);
      setTopupOpen(false);
      setTutar('');
      load();
      const handled = await checkPendingAfterTopup(r.bakiye);
      if (!handled) Alert.alert('Başarılı', `${tutarVal.toFixed(2)} ₺ bakiyenize eklendi.\nYeni bakiye: ${r.bakiye.toFixed(2)} ₺`);
    } catch (e: any) {
      Alert.alert('Hata', e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.bg}>
      <SafeAreaView style={{ flex: 1 }} edges={['top']}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="wallet-back">
            <Ionicons name="arrow-back" size={20} color={Colors.text.primary} />
          </Pressable>
          <Text style={styles.title}>Cüzdanım</Text>
          <View style={{ width: 40 }} />
        </View>
        <ScrollView
          contentContainerStyle={{ paddingBottom: 40 }}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} tintColor={Colors.brand.primary} />}
        >
          {loading ? (
            <ActivityIndicator color={Colors.brand.primary} style={{ marginTop: 40 }} />
          ) : (
            <>
              {/* BALANCE */}
              <View style={{ paddingHorizontal: Spacing.xl }}>
                <View style={styles.balanceCard}>
                  <View style={styles.balanceRedBg} />
                  <View style={styles.balanceContent}>
                    <Text style={styles.balanceLabel}>TOPLAM BAKİYE</Text>
                    <Text style={styles.balanceValue}>{bakiye.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺</Text>
                    <Text style={styles.balanceSub}>YS Auto Cüzdan</Text>
                    <View style={styles.balanceCardFooter}>
                      <View style={styles.cardChip} />
                      <Ionicons name="card" size={28} color="rgba(255,255,255,0.5)" />
                    </View>
                  </View>
                </View>
                <GlassButton testID="topup-btn" title="BAKİYE YÜKLE" onPress={() => setTopupOpen(true)} size="lg" icon={<Ionicons name="add" size={20} color="#fff" />} style={{ marginTop: Spacing.lg }} />
              </View>

              {/* HISTORY */}
              <View style={{ paddingHorizontal: Spacing.xl, marginTop: Spacing.xl }}>
                <Text style={styles.subtitle}>İşlem Geçmişi</Text>
              </View>
              {txs.length === 0 ? (
                <Empty title="Henüz işlem yok" subtitle="Bakiye yüklediğinizde burada görünecek" icon={<Ionicons name="receipt-outline" size={36} color={Colors.text.tertiary} />} />
              ) : (
                <View style={{ paddingHorizontal: Spacing.xl, gap: Spacing.sm, marginTop: Spacing.md }}>
                  {txs.map(t => (
                    <View key={t.id} style={styles.txCard}>
                      <View style={[styles.txIcon, t.isaret === '+' ? styles.txIconPos : styles.txIconNeg]}>
                        <Ionicons name={t.isaret === '+' ? 'arrow-down' : 'arrow-up'} size={16} color={t.isaret === '+' ? Colors.status.success : Colors.status.error} />
                      </View>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.txDesc} numberOfLines={2}>{t.aciklama}</Text>
                        <Text style={styles.txDate}>{fmtDate(t.tarih)} {t.referans ? `• ${t.referans}` : ''}</Text>
                        {t.durum === 'beklemede' && <Text style={{ ...Typography.micro, color: Colors.status.warning, marginTop: 2 }}>⏳ Onay bekliyor</Text>}
                      </View>
                      <Text style={[styles.txAmount, { color: t.isaret === '+' ? Colors.status.success : Colors.text.primary }]}>
                        {t.isaret} {t.tutar.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺
                      </Text>
                    </View>
                  ))}
                </View>
              )}
            </>
          )}
        </ScrollView>
      </SafeAreaView>

      {/* Topup Modal */}
      <Modal visible={topupOpen} animationType="slide" transparent onRequestClose={() => setTopupOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={{ flex: 1 }}>
          <View style={styles.modalBg}>
            <View style={styles.modalCard}>
              <View style={styles.modalHeader}>
                <Text style={styles.modalTitle}>Bakiye Yükle</Text>
                <Pressable onPress={() => setTopupOpen(false)}><Ionicons name="close" size={24} color={Colors.text.primary} /></Pressable>
              </View>
              <ScrollView showsVerticalScrollIndicator={false} style={{ maxHeight: 520 }}>
                <View style={{ flexDirection: 'row', gap: 6, marginBottom: 12 }}>
                  <Pressable testID="yontem-shopier" disabled style={[styles.yontemBtn, { opacity: 0.45 }]}>
                    <Ionicons name="card" size={16} color={Colors.text.tertiary} />
                    <Text style={[styles.yontemText, { color: Colors.text.tertiary }]}>SHOPIER</Text>
                    <View style={{ position: 'absolute', top: -6, right: 4, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 8, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base }}>
                      <Text style={{ fontSize: 8, fontWeight: '800', color: Colors.text.tertiary, letterSpacing: 0.5 }}>YAKINDA</Text>
                    </View>
                  </Pressable>
                  <Pressable testID="yontem-havale" onPress={() => setYontem('havale')} style={[styles.yontemBtn, yontem === 'havale' && styles.yontemBtnActive]}>
                    <Ionicons name="business" size={16} color={yontem === 'havale' ? '#fff' : Colors.text.secondary} />
                    <Text style={[styles.yontemText, yontem === 'havale' && { color: '#fff' }]}>HAVALE/EFT</Text>
                  </Pressable>
                </View>

                <Text style={styles.label}>Yükleme Tutarı (₺)</Text>
                <TextInput testID="topup-tutar" value={tutar} onChangeText={(v) => setTutar(v.replace(/[^\d.,]/g, ''))} keyboardType="decimal-pad" placeholder="500" placeholderTextColor={Colors.text.tertiary} style={styles.input} />
                <View style={{ flexDirection: 'row', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                  {[500, 1000, 2500, 5000].map(p => (
                    <Pressable key={p} onPress={() => setTutar(String(p))} style={styles.quickAmount}>
                      <Text style={styles.quickAmountText}>{p.toLocaleString('tr-TR')} ₺</Text>
                    </Pressable>
                  ))}
                </View>

                {yontem === 'shopier' ? (
                  <View style={{ gap: 8, marginTop: 12 }}>
                    <View style={[styles.shopierBox, { opacity: 0.7 }]}>
                      <Ionicons name="construct" size={20} color={Colors.text.tertiary} />
                      <Text style={styles.shopierTitle}>Shopier yakında aktif olacak</Text>
                      <Text style={styles.shopierDesc}>
                        Kredi/banka kartı ile anında bakiye yükleme entegrasyonu üzerinde çalışıyoruz. Şimdilik HAVALE/EFT seçeneğini kullanabilirsiniz.
                      </Text>
                    </View>
                  </View>
                ) : (
                  <View style={{ gap: 8, marginTop: 12 }}>
                    <View style={styles.ibanBox}>
                      <View style={{ marginBottom: 8 }}>
                        <Text style={{ ...Typography.micro, color: Colors.text.tertiary, fontWeight: '700', letterSpacing: 0.5, marginBottom: 2 }}>BANKA</Text>
                        <Text selectable style={{ fontSize: 15, color: Colors.text.primary, fontWeight: '700' }}>{settings.banka || '—'}</Text>
                      </View>
                      <CopyRow label="HESAP SAHİBİ" value={settings.hesap_sahibi || '—'} />
                      <CopyRow label="IBAN" value={settings.iban || '—'} mono />
                    </View>
                    <Text style={styles.label}>Transfer Referans No (Opsiyonel)</Text>
                    <TextInput value={havaleRef} onChangeText={setHavaleRef} placeholder="Banka transfer referansı" placeholderTextColor={Colors.text.tertiary} style={styles.input} />

                    {/* DEKONT YÜKLEME (zorunlu) */}
                    <Text style={[styles.label, { marginTop: 8 }]}>Dekont Fotoğrafı (Zorunlu)</Text>
                    {dekontB64 ? (
                      <View style={{ position: 'relative' }}>
                        <Image source={{ uri: dekontB64 }} style={{ width: '100%', height: 180, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2 }} resizeMode="contain" />
                        <Pressable onPress={() => setDekontB64(null)} style={{ position: 'absolute', top: 8, right: 8, backgroundColor: 'rgba(0,0,0,0.7)', borderRadius: 18, padding: 8 }}>
                          <Ionicons name="trash" size={16} color={Colors.status.error} />
                        </Pressable>
                        <View style={{ position: 'absolute', bottom: 8, left: 8, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 12, backgroundColor: 'rgba(0,0,0,0.65)', flexDirection: 'row', alignItems: 'center', gap: 4 }}>
                          <Ionicons name="checkmark-circle" size={14} color={Colors.status.success} />
                          <Text style={{ ...Typography.micro, color: '#fff', fontWeight: '700' }}>YÜKLENDİ</Text>
                        </View>
                      </View>
                    ) : (
                      <View style={{ flexDirection: 'row', gap: 8 }}>
                        <Pressable onPress={() => pickDekont('camera')} disabled={dekontUploading} style={[styles.input, { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, backgroundColor: Colors.bg.glassRed, borderColor: Colors.border.accent, opacity: dekontUploading ? 0.5 : 1 }]}>
                          <Ionicons name="camera" size={18} color={Colors.brand.primary} />
                          <Text style={{ color: Colors.brand.primary, fontWeight: '700' }}>KAMERA</Text>
                        </Pressable>
                        <Pressable onPress={() => pickDekont('library')} disabled={dekontUploading} style={[styles.input, { flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, opacity: dekontUploading ? 0.5 : 1 }]}>
                          <Ionicons name="images" size={18} color={Colors.text.primary} />
                          <Text style={{ color: Colors.text.primary, fontWeight: '700' }}>GALERİ</Text>
                        </Pressable>
                      </View>
                    )}
                    {dekontUploading && <ActivityIndicator color={Colors.brand.primary} />}

                    <View style={styles.warnBox}>
                      <Ionicons name="sparkles" size={16} color={Colors.brand.primary} />
                      <Text style={styles.warnText}>
                        Dekontunuz yapay zekayla tarih, tutar, IBAN, gönderici ve alıcı adı bakımından kontrol edilir. Eşleşme tam ise bakiyeniz otomatik yüklenir; aksi halde yöneticinin onayı için incelemeye alınır.
                      </Text>
                    </View>
                  </View>
                )}
              </ScrollView>
              <GlassButton
                testID="topup-confirm"
                title={yontem === 'shopier' ? 'YAKINDA AKTİF OLACAK' : 'BİLDİR'}
                onPress={onSubmit}
                loading={submitting}
                disabled={yontem === 'shopier'}
                size="lg"
              />
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* Shopier MOCK confirm modal */}
      <Modal visible={!!shopierMock} animationType="fade" transparent onRequestClose={() => setShopierMock(null)}>
        <View style={styles.mockBg}>
          <View style={styles.mockCard}>
            <View style={styles.mockHeader}>
              <Text style={styles.mockTitle}>SHOPIER</Text>
              <Pressable onPress={() => setShopierMock(null)}><Ionicons name="close" size={20} color="#fff" /></Pressable>
            </View>
            <View style={{ alignItems: 'center', paddingVertical: Spacing.lg }}>
              <View style={styles.mockBadge}>
                <Ionicons name="alert-circle" size={14} color={Colors.status.warning} />
                <Text style={styles.mockBadgeText}>TEST MODU</Text>
              </View>
              <Text style={styles.mockAmount}>{shopierMock?.tutar.toLocaleString('tr-TR', { minimumFractionDigits: 2 })} ₺</Text>
              <Text style={styles.mockOrder}>Sipariş: {shopierMock?.order_id}</Text>
              <Text style={styles.mockNote}>
                Shopier API anahtarları henüz eklenmediği için test modunda çalışıyoruz. Anahtarlar eklendiğinde gerçek 3D Secure ödeme sayfası açılacaktır.
              </Text>
            </View>
            <GlassButton
              title="ÖDEMEYİ ONAYLA (TEST)"
              onPress={confirmShopierMock}
              loading={submitting}
              size="lg"
            />
            <GlassButton
              title="VAZGEÇ"
              onPress={() => setShopierMock(null)}
              variant="ghost"
              style={{ marginTop: 6 }}
            />
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: Colors.bg.base },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: Spacing.xl, paddingVertical: Spacing.md, borderBottomWidth: 1, borderBottomColor: Colors.border.base },
  backBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: Colors.bg.surface, alignItems: 'center', justifyContent: 'center' },
  title: { ...Typography.h2, color: Colors.text.primary, flex: 1, textAlign: 'center' },
  subtitle: { ...Typography.h3, color: Colors.text.primary },
  balanceCard: { height: 200, borderRadius: Radius.xl, overflow: 'hidden', marginTop: Spacing.lg, backgroundColor: '#1a0a0a', borderWidth: 1, borderColor: Colors.border.accent },
  balanceRedBg: { ...StyleSheet.absoluteFillObject, backgroundColor: Colors.brand.primary, opacity: 0.85 },
  balanceContent: { flex: 1, padding: Spacing.xl, justifyContent: 'space-between' },
  balanceLabel: { ...Typography.micro, color: 'rgba(255,255,255,0.8)', letterSpacing: 2 },
  balanceValue: { fontSize: 38, fontWeight: '900', color: '#fff', marginTop: 4, letterSpacing: -0.5 },
  balanceSub: { ...Typography.caption, color: 'rgba(255,255,255,0.7)', marginTop: 4 },
  balanceCardFooter: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  cardChip: { width: 36, height: 28, borderRadius: 4, backgroundColor: 'rgba(255,255,255,0.3)' },
  txCard: { flexDirection: 'row', alignItems: 'center', gap: 12, padding: Spacing.md, backgroundColor: Colors.bg.surface, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.base },
  txIcon: { width: 36, height: 36, borderRadius: 18, alignItems: 'center', justifyContent: 'center' },
  txIconPos: { backgroundColor: 'rgba(52, 199, 89, 0.15)' },
  txIconNeg: { backgroundColor: 'rgba(255, 59, 48, 0.15)' },
  txDesc: { ...Typography.bodyBold, color: Colors.text.primary },
  txDate: { ...Typography.micro, color: Colors.text.tertiary, marginTop: 2 },
  txAmount: { ...Typography.bodyBold, fontWeight: '800' },
  modalBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.7)', justifyContent: 'flex-end' },
  modalCard: { backgroundColor: Colors.bg.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: Spacing.xl, gap: 8, borderTopWidth: 1, borderColor: Colors.border.base },
  modalHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  modalTitle: { ...Typography.h2, color: Colors.text.primary },
  yontemBtn: { flex: 1, height: 44, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 6, borderWidth: 1, borderColor: Colors.border.base },
  yontemBtnActive: { backgroundColor: Colors.brand.primary, borderColor: Colors.brand.primary },
  yontemText: { fontSize: 12, fontWeight: '700', color: Colors.text.secondary, letterSpacing: 1 },
  label: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase', marginBottom: 4 },
  input: { backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, padding: Spacing.md, color: Colors.text.primary, borderWidth: 1, borderColor: Colors.border.base, fontSize: 15 },
  quickAmount: { paddingHorizontal: Spacing.md, paddingVertical: 6, borderRadius: Radius.pill, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base },
  quickAmountText: { fontSize: 12, color: Colors.text.primary, fontWeight: '600' },
  ibanBox: { padding: Spacing.md, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, gap: 4 },
  ibanLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' },
  ibanValue: { ...Typography.bodyBold, color: Colors.text.primary, marginBottom: 4 },
  ibanIban: { ...Typography.bodyBold, color: Colors.text.primary, fontVariant: ['tabular-nums'] },
  warnBox: { flexDirection: 'row', gap: 6, padding: 10, borderRadius: Radius.md, backgroundColor: 'rgba(90, 200, 250, 0.08)', borderLeftWidth: 3, borderLeftColor: Colors.status.info },
  warnText: { ...Typography.caption, color: Colors.text.secondary, flex: 1 },
  shopierBox: { padding: Spacing.lg, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.accent, gap: 6 },
  shopierTitle: { ...Typography.h4, color: Colors.text.primary, marginTop: 4 },
  shopierDesc: { ...Typography.caption, color: Colors.text.secondary, lineHeight: 18 },
  brandPill: { paddingHorizontal: Spacing.sm, paddingVertical: 4, borderRadius: Radius.pill, backgroundColor: Colors.bg.surface, borderWidth: 1, borderColor: Colors.border.base },
  brandPillText: { ...Typography.micro, color: Colors.text.secondary, fontWeight: '700' },
  mockBg: { flex: 1, backgroundColor: 'rgba(0,0,0,0.85)', alignItems: 'center', justifyContent: 'center', padding: Spacing.xl },
  mockCard: { width: '100%', maxWidth: 400, borderRadius: Radius.xl, backgroundColor: Colors.brand.primaryDark, padding: Spacing.xl, borderWidth: 1, borderColor: Colors.brand.primaryLight },
  mockHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  mockTitle: { color: '#fff', fontSize: 22, fontWeight: '900', letterSpacing: 2 },
  mockBadge: { flexDirection: 'row', gap: 4, paddingHorizontal: Spacing.md, paddingVertical: 4, borderRadius: Radius.pill, backgroundColor: 'rgba(255,149,0,0.2)', borderWidth: 1, borderColor: Colors.status.warning, alignItems: 'center' },
  mockBadgeText: { ...Typography.micro, color: Colors.status.warning, fontWeight: '700' },
  mockAmount: { fontSize: 44, fontWeight: '900', color: '#fff', marginTop: Spacing.md },
  mockOrder: { ...Typography.caption, color: 'rgba(255,255,255,0.7)', marginTop: 4, fontVariant: ['tabular-nums'] },
  mockNote: { ...Typography.caption, color: 'rgba(255,255,255,0.85)', textAlign: 'center', marginTop: Spacing.md, lineHeight: 18 },
});
