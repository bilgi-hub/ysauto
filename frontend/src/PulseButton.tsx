/**
 * Pulse Button — sürekli nabız atan dikkat çekici buton (rezervasyon CTA için)
 * react-native-reanimated ile cross-platform pulse animasyonu
 */
import React, { useEffect } from 'react';
import { Pressable, Text, StyleSheet, ViewStyle, TextStyle } from 'react-native';
import Animated, { useSharedValue, useAnimatedStyle, withRepeat, withSequence, withTiming, Easing } from 'react-native-reanimated';
import { Colors, Radius, Typography } from './theme';

interface Props {
  title: string;
  onPress: () => void;
  testID?: string;
  style?: ViewStyle;
}

export default function PulseButton({ title, onPress, testID, style }: Props) {
  const scale = useSharedValue(1);
  const glow = useSharedValue(0);

  useEffect(() => {
    // 1.4 saniyelik pulse cycle: büyür → küçülür, sonsuz tekrar
    scale.value = withRepeat(
      withSequence(
        withTiming(1.04, { duration: 700, easing: Easing.inOut(Easing.ease) }),
        withTiming(1, { duration: 700, easing: Easing.inOut(Easing.ease) }),
      ),
      -1,
      false
    );
    // Renk parlaması (glow) — aynı ritimle
    glow.value = withRepeat(
      withSequence(
        withTiming(1, { duration: 700, easing: Easing.inOut(Easing.ease) }),
        withTiming(0, { duration: 700, easing: Easing.inOut(Easing.ease) }),
      ),
      -1,
      false
    );
  }, []);

  const animContainer = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    shadowOpacity: 0.3 + glow.value * 0.5,
    shadowRadius: 8 + glow.value * 12,
  }));

  return (
    <Animated.View style={[styles.shadowWrap, animContainer, style]}>
      <Pressable testID={testID} onPress={onPress} android_ripple={{ color: 'rgba(255,255,255,0.2)' }} style={styles.btn}>
        <Text style={styles.title}>{title}</Text>
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  shadowWrap: {
    borderRadius: Radius.lg,
    backgroundColor: Colors.brand.primary,
    shadowColor: Colors.brand.primary,
    shadowOffset: { width: 0, height: 0 },
    elevation: 8,
  } as ViewStyle,
  btn: {
    paddingVertical: 18,
    paddingHorizontal: 24,
    borderRadius: Radius.lg,
    alignItems: 'center',
    justifyContent: 'center',
  } as ViewStyle,
  title: {
    ...Typography.bodyBold,
    color: '#fff',
    fontWeight: '800',
    fontSize: 16,
    letterSpacing: 0.5,
  } as TextStyle,
});
