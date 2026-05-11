import React, { useEffect, useState } from 'react';
import { Tabs } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { Platform, View, StyleSheet, Text } from 'react-native';
import { BlurView } from 'expo-blur';
import { Colors, Spacing, Typography } from '../../src/theme';
import { customerApi } from '../../src/api';

function TabBarBg() {
  return (
    <View style={StyleSheet.absoluteFill}>
      {Platform.OS !== 'web' ? (
        <BlurView intensity={50} tint="dark" style={StyleSheet.absoluteFill} />
      ) : (
        <View style={[StyleSheet.absoluteFill, { backgroundColor: 'rgba(15, 15, 15, 0.92)' }]} />
      )}
      <View style={[StyleSheet.absoluteFill, styles.tint]} />
      <View style={styles.topBorder} />
    </View>
  );
}

function NotifIcon({ color, focused }: { color: string; focused: boolean }) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r = await customerApi.unreadCount();
        if (alive) setCount(r.count || 0);
      } catch {}
    };
    tick();
    const itv = setInterval(tick, 20000);
    return () => { alive = false; clearInterval(itv); };
  }, []);
  return (
    <View>
      <Ionicons name={focused ? 'notifications' : 'notifications-outline'} size={24} color={color} />
      {count > 0 && (
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{count > 9 ? '9+' : count}</Text>
        </View>
      )}
    </View>
  );
}

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: Colors.brand.primary,
        tabBarInactiveTintColor: Colors.text.secondary,
        tabBarStyle: {
          position: 'absolute',
          backgroundColor: 'transparent',
          borderTopWidth: 0,
          height: Platform.OS === 'ios' ? 90 : 70,
          paddingBottom: Platform.OS === 'ios' ? 28 : 10,
          paddingTop: 10,
          elevation: 0,
        },
        tabBarBackground: () => <TabBarBg />,
        tabBarLabelStyle: { fontSize: 11, fontWeight: '600', marginTop: 2 },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Ana Sayfa',
          tabBarIcon: ({ color, focused }) => <Ionicons name={focused ? 'home' : 'home-outline'} size={24} color={color} />,
        }}
      />
      <Tabs.Screen
        name="rentals"
        options={{
          title: 'Rezervasyonlarım',
          tabBarIcon: ({ color, focused }) => <Ionicons name={focused ? 'car-sport' : 'car-sport-outline'} size={24} color={color} />,
        }}
      />
      <Tabs.Screen
        name="contact"
        options={{
          title: 'İletişim',
          tabBarIcon: ({ color, focused }) => <Ionicons name={focused ? 'call' : 'call-outline'} size={24} color={color} />,
        }}
      />
      <Tabs.Screen
        name="notifications"
        options={{
          title: 'Bildirim',
          tabBarIcon: ({ color, focused }) => <NotifIcon color={color} focused={focused} />,
        }}
      />
    </Tabs>
  );
}

const styles = StyleSheet.create({
  tint: { backgroundColor: 'rgba(229, 9, 20, 0.04)' },
  topBorder: { height: 1, backgroundColor: Colors.border.base, position: 'absolute', top: 0, left: 0, right: 0 },
  badge: {
    position: 'absolute', top: -4, right: -8,
    minWidth: 16, height: 16, borderRadius: 8,
    backgroundColor: Colors.brand.primary,
    alignItems: 'center', justifyContent: 'center',
    paddingHorizontal: 4,
    borderWidth: 1, borderColor: Colors.bg.base,
  },
  badgeText: { fontSize: 9, color: '#fff', fontWeight: '700' },
});
