import React, { useState } from 'react';
import { View, Text, Pressable, Platform, Modal, TextInput, TouchableOpacity } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import DateTimePicker from '@react-native-community/datetimepicker';
import { Colors, Typography, Radius } from './theme';

/**
 * DateTimeField — TR formatlı tarih+saat girişi (GG.AA.YYYY HH:mm)
 * Hem manuel yazma hem takvim/saat seçici desteği.
 * value: TR formatlı string (örn "11.05.2026 16:00")
 * onChange: TR formatlı string döner
 */
export function DateTimeField({
  label,
  value,
  onChange,
  showTime = true,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  showTime?: boolean;
}) {
  const [pickerMode, setPickerMode] = useState<'date' | 'time' | null>(null);
  const [androidStep, setAndroidStep] = useState<'date' | 'time' | null>(null);
  const [pendingDate, setPendingDate] = useState<Date | null>(null);

  const parseTr = (s: string): Date | null => {
    if (!s) return null;
    const m = s.match(/^(\d{2})\.(\d{2})\.(\d{4})(?:\s+(\d{2}):(\d{2}))?/);
    if (!m) return null;
    const [, dd, mm, yyyy, hh = '12', mi = '00'] = m;
    const d = new Date(parseInt(yyyy), parseInt(mm) - 1, parseInt(dd), parseInt(hh), parseInt(mi));
    return isNaN(d.getTime()) ? null : d;
  };

  const formatTr = (d: Date): string => {
    const p = (n: number) => String(n).padStart(2, '0');
    return showTime
      ? `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`
      : `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`;
  };

  const currentDate = parseTr(value) || new Date();

  const onChangePicker = (event: any, selected?: Date) => {
    if (Platform.OS === 'android') {
      // Android: dismiss event when cancelled
      if (event.type === 'dismissed') {
        setPickerMode(null);
        setAndroidStep(null);
        setPendingDate(null);
        return;
      }
      if (selected) {
        if (androidStep === 'date' && showTime) {
          // Save date, open time picker next
          setPendingDate(selected);
          setAndroidStep('time');
          setPickerMode('time');
          return;
        }
        // Final
        const finalDate = pendingDate
          ? new Date(pendingDate.getFullYear(), pendingDate.getMonth(), pendingDate.getDate(), selected.getHours(), selected.getMinutes())
          : selected;
        onChange(formatTr(finalDate));
        setPickerMode(null);
        setAndroidStep(null);
        setPendingDate(null);
      }
    } else {
      // iOS: inline picker, change is live
      if (selected) {
        onChange(formatTr(selected));
      }
    }
  };

  const openPicker = () => {
    if (Platform.OS === 'android') {
      setAndroidStep('date');
      setPickerMode('date');
    } else {
      setPickerMode('date');
    }
  };

  return (
    <View style={{ marginVertical: 6 }}>
      <Text style={{ ...Typography.micro, color: Colors.text.secondary, marginBottom: 4, fontWeight: '600' }}>{label}</Text>
      <View style={{ flexDirection: 'row', gap: 6 }}>
        <TextInput
          value={value}
          onChangeText={onChange}
          placeholder={showTime ? 'GG.AA.YYYY SS:DD' : 'GG.AA.YYYY'}
          placeholderTextColor={Colors.text.tertiary}
          keyboardType="default"
          style={{
            flex: 1,
            backgroundColor: Colors.bg.surface2,
            color: Colors.text.primary,
            paddingVertical: 10,
            paddingHorizontal: 12,
            borderRadius: Radius.sm,
            borderWidth: 1,
            borderColor: Colors.border.base,
            fontSize: 13,
          }}
        />
        <Pressable
          onPress={openPicker}
          style={{
            backgroundColor: Colors.brand.primary,
            paddingHorizontal: 14,
            justifyContent: 'center',
            alignItems: 'center',
            borderRadius: Radius.sm,
          }}
        >
          <Ionicons name="calendar" size={18} color="#fff" />
        </Pressable>
      </View>

      {/* iOS inline modal */}
      {Platform.OS === 'ios' && pickerMode !== null && (
        <Modal transparent animationType="fade" visible onRequestClose={() => setPickerMode(null)}>
          <View style={{ flex: 1, backgroundColor: 'rgba(0,0,0,0.5)', justifyContent: 'flex-end' }}>
            <View style={{ backgroundColor: Colors.bg.base, padding: 16, borderTopLeftRadius: 16, borderTopRightRadius: 16 }}>
              <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 }}>
                <View style={{ flexDirection: 'row', gap: 6 }}>
                  <Pressable onPress={() => setPickerMode('date')} style={{ paddingHorizontal: 12, paddingVertical: 6, backgroundColor: pickerMode === 'date' ? Colors.brand.primary : Colors.bg.surface, borderRadius: 6 }}>
                    <Text style={{ color: pickerMode === 'date' ? '#fff' : Colors.text.primary, fontWeight: '700' }}>Tarih</Text>
                  </Pressable>
                  {showTime && (
                    <Pressable onPress={() => setPickerMode('time')} style={{ paddingHorizontal: 12, paddingVertical: 6, backgroundColor: pickerMode === 'time' ? Colors.brand.primary : Colors.bg.surface, borderRadius: 6 }}>
                      <Text style={{ color: pickerMode === 'time' ? '#fff' : Colors.text.primary, fontWeight: '700' }}>Saat</Text>
                    </Pressable>
                  )}
                </View>
                <TouchableOpacity onPress={() => setPickerMode(null)} style={{ paddingHorizontal: 12, paddingVertical: 6, backgroundColor: Colors.status.success, borderRadius: 6 }}>
                  <Text style={{ color: '#fff', fontWeight: '700' }}>Tamam</Text>
                </TouchableOpacity>
              </View>
              <DateTimePicker
                value={currentDate}
                mode={pickerMode}
                display="spinner"
                onChange={onChangePicker}
                locale="tr-TR"
                textColor={Colors.text.primary}
              />
            </View>
          </View>
        </Modal>
      )}

      {/* Android native picker */}
      {Platform.OS === 'android' && pickerMode !== null && (
        <DateTimePicker
          value={pendingDate || currentDate}
          mode={pickerMode}
          is24Hour={true}
          display="default"
          onChange={onChangePicker}
        />
      )}
    </View>
  );
}
