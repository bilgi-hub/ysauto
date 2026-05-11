/**
 * Vehicle Image Slider — horizontal swipeable with Instagram-style white dots
 * - Falls back to single Image if only 1 photo
 * - Falls back to placeholder if no photos
 */
import React, { useRef, useState } from 'react';
import { View, Image, ScrollView, NativeSyntheticEvent, NativeScrollEvent, StyleSheet, Dimensions } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from './theme';

interface Props {
  photos: string[];
  fallback?: string | null;
  height: number;
  width?: number;
  borderRadius?: number;
}

export default function VehicleImageSlider({ photos, fallback, height, width, borderRadius = 0 }: Props) {
  const SCREEN_W = Dimensions.get('window').width;
  const W = width ?? SCREEN_W;
  const [page, setPage] = useState(0);
  const scrollRef = useRef<ScrollView>(null);

  const photoList: string[] = (photos && photos.length > 0)
    ? photos
    : (fallback ? [fallback] : []);

  if (photoList.length === 0) {
    return (
      <View style={[styles.empty, { width: W, height, borderRadius }]}>
        <Ionicons name="car-sport" size={40} color={Colors.text.tertiary} />
      </View>
    );
  }

  if (photoList.length === 1) {
    return (
      <Image source={{ uri: photoList[0] }} style={{ width: W, height, borderRadius, backgroundColor: Colors.bg.surface2 }} resizeMode="contain" />
    );
  }

  const onScroll = (e: NativeSyntheticEvent<NativeScrollEvent>) => {
    const x = e.nativeEvent.contentOffset.x;
    const p = Math.round(x / W);
    if (p !== page) setPage(p);
  };

  return (
    <View style={{ width: W, height, position: 'relative' }}>
      <ScrollView
        ref={scrollRef}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScroll={onScroll}
        scrollEventThrottle={16}
        style={{ width: W, height, borderRadius, overflow: 'hidden' }}
      >
        {photoList.map((url, idx) => (
          <Image key={idx} source={{ uri: url }} style={{ width: W, height, backgroundColor: Colors.bg.surface2 }} resizeMode="contain" />
        ))}
      </ScrollView>
      {/* Dots */}
      <View style={styles.dotsRow} pointerEvents="none">
        {photoList.map((_, idx) => (
          <View key={idx} style={[styles.dot, idx === page && styles.dotActive]} />
        ))}
      </View>
      {/* Counter */}
      <View style={styles.counter} pointerEvents="none">
        <View style={styles.counterBg}>
          <Ionicons name="images" size={10} color="#fff" />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  empty: {
    backgroundColor: Colors.bg.surface2,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dotsRow: {
    position: 'absolute',
    bottom: 8,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 4,
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
    backgroundColor: 'rgba(255,255,255,0.5)',
  },
  dotActive: {
    backgroundColor: '#fff',
    width: 7,
    height: 7,
    borderRadius: 3.5,
  },
  counter: {
    position: 'absolute',
    top: 8,
    right: 8,
  },
  counterBg: {
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 10,
    backgroundColor: 'rgba(0,0,0,0.55)',
    flexDirection: 'row',
    gap: 3,
    alignItems: 'center',
  },
});
