/**
 * Stars component — interactive (input) and display modes
 */
import React from 'react';
import { View, Pressable, Text } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors } from './theme';

interface Props {
  value: number;            // 0-5 (decimal allowed for display)
  onChange?: (v: number) => void;  // if provided, interactive
  size?: number;
  showNumber?: boolean;
  color?: string;
}

export function Stars({ value, onChange, size = 18, showNumber = false, color }: Props) {
  const c = color ?? '#FBBF24';
  const stars = [1, 2, 3, 4, 5];
  const interactive = !!onChange;

  return (
    <View style={{ flexDirection: 'row', alignItems: 'center', gap: 2 }}>
      {stars.map((s) => {
        const filled = value >= s;
        const half = !filled && value >= s - 0.5;
        const iconName: any = filled ? 'star' : half ? 'star-half' : 'star-outline';
        const Cmp: any = interactive ? Pressable : View;
        return (
          <Cmp
            key={s}
            onPress={interactive ? () => onChange!(s) : undefined}
            hitSlop={interactive ? 6 : 0}
            style={{ padding: interactive ? 2 : 0 }}
          >
            <Ionicons name={iconName} size={size} color={c} />
          </Cmp>
        );
      })}
      {showNumber && (
        <Text style={{ marginLeft: 4, fontSize: Math.max(11, size - 5), color: Colors.text.secondary, fontWeight: '700' }}>
          {value > 0 ? value.toFixed(1) : '—'}
        </Text>
      )}
    </View>
  );
}

export default Stars;
