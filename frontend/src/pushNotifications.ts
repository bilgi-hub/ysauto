// Expo Push Notification kurulumu
// — Müşteri giriş yaptıktan sonra registerForPushNotificationsAsync() çağırılmalı.
// — Token alındığında backend'e POST /api/push/register yollanır.
// — Web platformunda push çalışmaz (Expo Go web'de desteklemez), no-op döner.

import { Platform } from 'react-native';
import Constants from 'expo-constants';

let Notifications: any = null;
let Device: any = null;
try {
  // dinamik import; modül yoksa veya web'de patlamasın
  Notifications = require('expo-notifications');
  Device = require('expo-device');
} catch (e) {
  Notifications = null;
  Device = null;
}

// Foreground'da gelen bildirimi ekranda göster
if (Notifications && Notifications.setNotificationHandler) {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: true,
    }),
  });
}

export async function registerForPushNotificationsAsync(): Promise<string | null> {
  // Web veya modül yok → no-op
  if (Platform.OS === 'web' || !Notifications) return null;
  try {
    // Sadece gerçek cihazda push çalışır
    if (Device && Device.isDevice === false) {
      return null;
    }
    const { status: existingStatus } = await Notifications.getPermissionsAsync();
    let finalStatus = existingStatus;
    if (existingStatus !== 'granted') {
      const { status } = await Notifications.requestPermissionsAsync();
      finalStatus = status;
    }
    if (finalStatus !== 'granted') {
      return null;
    }
    // Android için kanal
    if (Platform.OS === 'android') {
      await Notifications.setNotificationChannelAsync('default', {
        name: 'YS Auto Bildirimleri',
        importance: 4, // IMPORTANCE_HIGH
        vibrationPattern: [0, 250, 250, 250],
        lightColor: '#E11D48',
      });
    }
    // Project ID - app.json'dan
    const projectId =
      (Constants?.expoConfig as any)?.extra?.eas?.projectId ||
      (Constants as any)?.easConfig?.projectId;

    const tokenResp = await Notifications.getExpoPushTokenAsync(
      projectId ? { projectId } : undefined
    );
    return tokenResp?.data || null;
  } catch (e) {
    console.warn('Push register error', e);
    return null;
  }
}

export function addNotificationResponseListener(
  cb: (data: any) => void
): { remove: () => void } | null {
  if (!Notifications) return null;
  const sub = Notifications.addNotificationResponseReceivedListener((resp: any) => {
    cb(resp?.notification?.request?.content?.data);
  });
  return sub;
}
