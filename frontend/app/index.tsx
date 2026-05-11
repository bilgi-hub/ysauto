import { useEffect } from 'react';
import { View, ActivityIndicator } from 'react-native';
import { useRouter } from 'expo-router';
import { auth } from '../src/api';
import { Colors } from '../src/theme';

export default function Index() {
  const router = useRouter();

  useEffect(() => {
    (async () => {
      const stored = await auth.getStored();
      if (stored?.user?.role === 'admin') {
        router.replace('/admin');
      } else if (stored?.user?.role === 'customer') {
        router.replace('/(tabs)');
      } else {
        router.replace('/login');
      }
    })();
  }, []);

  return (
    <View style={{ flex: 1, backgroundColor: Colors.bg.base, alignItems: 'center', justifyContent: 'center' }}>
      <ActivityIndicator color={Colors.brand.primary} size="large" />
    </View>
  );
}
