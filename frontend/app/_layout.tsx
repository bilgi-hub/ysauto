import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { View } from 'react-native';
import { useEffect } from 'react';
import { Colors } from '../src/theme';
import { auth } from '../src/api';
import { registerForPushNotificationsAsync, addNotificationResponseListener } from '../src/pushNotifications';

export default function RootLayout() {
  useEffect(() => {
    // Müşteri olarak giriş yapılmışsa push token kaydet
    let mounted = true;
    let sub: any = null;
    (async () => {
      try {
        const stored = await auth.getStored();
        if (!stored) return;
        if (stored.user.role !== 'customer') return;
        const token = await registerForPushNotificationsAsync();
        if (!mounted) return;
        if (token) {
          await auth.registerPushToken(token, 'mobile');
        }
        // Tıklanan bildirimi dinle (deep linking için)
        sub = addNotificationResponseListener(() => {
          // İleride bildirim tipine göre yönlendirme yapılabilir
        });
      } catch (e) {
        // ignore
      }
    })();
    return () => {
      mounted = false;
      try { sub?.remove?.(); } catch {}
    };
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: Colors.bg.base }}>
      <SafeAreaProvider>
        <StatusBar style="light" />
        <View style={{ flex: 1, backgroundColor: Colors.bg.base }}>
          <Stack
            screenOptions={{
              headerShown: false,
              contentStyle: { backgroundColor: Colors.bg.base },
              animation: 'fade',
            }}
          />
        </View>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
