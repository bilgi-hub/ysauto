import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, Image } from 'react-native';
import { useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { SafeAreaView } from 'react-native-safe-area-context';
import { auth } from '../src/api';
import { Colors, Radius, Spacing, Typography } from '../src/theme';
import { GlassCard, GlassButton } from '../src/ui';

/**
 * Birleşik Giriş Ekranı
 * Tek form: Ad / Soyad / TC Kimlik No
 * Backend (POST /api/auth/login) önce admin tablosunda TC arar, bulamazsa müşteri olarak dener.
 * Yönlendirme rol'e göre yapılır.
 */
export default function LoginScreen() {
  const router = useRouter();
  const [ad, setAd] = useState('');
  const [soyad, setSoyad] = useState('');
  const [tc, setTc] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async () => {
    setError('');
    if (!ad.trim() || !soyad.trim()) { setError('Ad ve soyad zorunlu'); return; }
    if (tc.replace(/\D/g, '').length !== 11) { setError('TC Kimlik No 11 haneli olmalı'); return; }
    setLoading(true);
    try {
      const r = await auth.login(ad.trim(), soyad.trim(), tc);
      if (r.role === 'admin') router.replace('/admin');
      else router.replace('/(tabs)');
    } catch (e: any) {
      setError(e?.message || 'Giriş başarısız');
    } finally { setLoading(false); }
  };

  return (
    <View style={styles.bg}>
      <View style={styles.overlay} />
      <SafeAreaView style={{ flex: 1 }} edges={['top', 'bottom']}>
        <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
          <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            {/* Logo */}
            <View style={styles.logoWrap}>
              <View style={styles.logoCard}>
                <Image source={require('../assets/images/logo.jpeg')} style={styles.logoImg} resizeMode="contain" />
              </View>
              <Text style={styles.brandTitle}>YS AUTO</Text>
              <Text style={styles.brandSub}>Premium Araç Kiralama</Text>
            </View>

            <GlassCard style={{ padding: Spacing.lg }}>
              <Text style={styles.heading}>Giriş Yap</Text>
              <Text style={styles.subHeading}>Ad, soyad ve TC Kimlik No ile devam edin</Text>

              <View style={{ gap: Spacing.md, marginTop: Spacing.md }}>
                <Text style={styles.label}>Ad</Text>
                <TextInput
                  testID="input-ad"
                  value={ad}
                  onChangeText={setAd}
                  placeholder="Adınız"
                  placeholderTextColor={Colors.text.tertiary}
                  style={styles.input}
                  autoCapitalize="words"
                  returnKeyType="next"
                />
                <Text style={styles.label}>Soyad</Text>
                <TextInput
                  testID="input-soyad"
                  value={soyad}
                  onChangeText={setSoyad}
                  placeholder="Soyadınız"
                  placeholderTextColor={Colors.text.tertiary}
                  style={styles.input}
                  autoCapitalize="words"
                  returnKeyType="next"
                />
                <Text style={styles.label}>TC Kimlik No</Text>
                <TextInput
                  testID="input-tc"
                  value={tc}
                  onChangeText={(v) => setTc(v.replace(/\D/g, '').slice(0, 11))}
                  placeholder="11 haneli TC Kimlik No"
                  placeholderTextColor={Colors.text.tertiary}
                  style={styles.input}
                  keyboardType="number-pad"
                  maxLength={11}
                  returnKeyType="done"
                  onSubmitEditing={handleSubmit}
                />
              </View>

              {!!error && <Text style={styles.error}>{error}</Text>}

              <GlassButton
                title={loading ? 'Giriş yapılıyor...' : 'GİRİŞ YAP'}
                onPress={handleSubmit}
                disabled={loading}
                style={{ marginTop: Spacing.lg }}
                testID="btn-submit"
              />

              <Text style={styles.helper}>
                Hesabınız yok mu? Yetkili tarafından kayıt yapılması gerekir.
              </Text>
            </GlassCard>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

const styles = StyleSheet.create({
  bg: { flex: 1, backgroundColor: Colors.bg.base },
  overlay: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.55)' },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: Spacing.lg },
  logoWrap: { alignItems: 'center', marginBottom: Spacing.xl },
  logoCard: {
    width: 96, height: 96, borderRadius: 28,
    backgroundColor: '#fff', alignItems: 'center', justifyContent: 'center',
    shadowColor: Colors.brand.primary, shadowOpacity: 0.6, shadowRadius: 18, shadowOffset: { width: 0, height: 6 },
    elevation: 12,
  },
  logoImg: { width: 76, height: 76, borderRadius: 16 },
  brandTitle: { ...Typography.h1, color: '#fff', fontWeight: '800', marginTop: 10, letterSpacing: 2 },
  brandSub: { ...Typography.caption, color: 'rgba(255,255,255,0.75)', marginTop: 2 },
  heading: { ...Typography.h3, color: Colors.text.primary, fontWeight: '700' },
  subHeading: { ...Typography.caption, color: Colors.text.secondary, marginTop: 4 },
  label: { ...Typography.caption, color: Colors.text.secondary, marginTop: 2 },
  input: {
    backgroundColor: Colors.bg.surface2,
    borderColor: Colors.border.base, borderWidth: 1,
    borderRadius: Radius.md, paddingHorizontal: 14, paddingVertical: 12,
    color: Colors.text.primary, fontSize: 16,
  },
  error: { ...Typography.caption, color: Colors.status.error, marginTop: Spacing.sm, textAlign: 'center' },
  helper: { ...Typography.micro, color: Colors.text.tertiary, textAlign: 'center', marginTop: Spacing.lg },
});
