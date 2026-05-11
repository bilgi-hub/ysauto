/**
 * Tam takvim + saat seçici (özel)
 * - Pazar + tatiller bloklu
 * - Aracın dolu tarihleri gri gösterilir, seçilemez
 * - Seçilen tarihte yalnızca uygun saatler aktif (mesai dışı + çakışan saatler bloklu)
 * - 1 saat tampon dahil edilir
 */
import React, { useMemo, useState } from 'react';
import { View, Text, Pressable, StyleSheet, ScrollView } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { Colors, Radius, Spacing, Typography } from './theme';

const MONTHS = [
  'Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran',
  'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık',
];
const WEEKDAYS_SHORT = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz'];

function daysInMonth(year: number, month0: number) {
  return new Date(year, month0 + 1, 0).getDate();
}
function fmtYMD(d: Date) {
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}
function ymdEqual(a: Date, b: Date) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}
function startOfDay(d: Date) {
  const x = new Date(d); x.setHours(0, 0, 0, 0); return x;
}

export type Availability = {
  blocked_ranges: { start: string; end: string }[];
  customer_blocked_ranges?: { start: string; end: string; plaka?: string }[];
  holidays: { tarih: string; aciklama: string }[];
  blocked_weekdays: number[]; // 0=Mon..6=Sun
  mesai: { start: string; end: string };
  tampon_saat: number;
};

type Props = {
  availability: Availability | null;
  pickupDateTime: Date;
  returnDateTime: Date;
  onChangePickup: (d: Date) => void;
  onChangeReturn: (d: Date) => void;
  minDate?: Date; // bundan önceki tarihler bloklu
  lockPickup?: boolean; // true ise sadece iade tarihi seçilebilir (uzatma modu)
};

export function DateTimePicker({ availability, pickupDateTime, returnDateTime, onChangePickup, onChangeReturn, minDate: minDateProp, lockPickup }: Props) {
  const [editing, setEditing] = useState<'pickup' | 'return'>(lockPickup ? 'return' : 'pickup');
  const [viewMonth, setViewMonth] = useState<Date>(startOfDay(lockPickup ? returnDateTime : pickupDateTime));

  const today = startOfDay(new Date());
  const baseMin = minDateProp ? startOfDay(minDateProp) : today;
  const minDate = editing === 'pickup' ? baseMin : startOfDay(pickupDateTime);

  const blockedRanges = availability?.blocked_ranges || [];
  const customerBlockedRanges = availability?.customer_blocked_ranges || [];
  // Tüm bloklu aralıklar (araç + müşterinin diğer rezervasyonları)
  const allBlockedRanges = [...blockedRanges, ...customerBlockedRanges];
  const holidaysSet = useMemo(() => new Set((availability?.holidays || []).map(h => h.tarih)), [availability]);
  const blockedWeekdays = availability?.blocked_weekdays || [6];
  // 0=Mon..6=Sun (server) — JS Date.getDay(): 0=Sun..6=Sat. Convert.
  const isBlockedWeekday = (d: Date) => {
    const jsDay = d.getDay(); // 0=Sun..6=Sat
    const serverDay = (jsDay + 6) % 7; // 0=Mon..6=Sun
    return blockedWeekdays.includes(serverDay);
  };

  const isFullyBookedDay = (d: Date) => {
    // Bir gün tamamen meşgulse (en az bir rezervasyon o günü kapsıyor)
    const dayStart = new Date(d); dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(d); dayEnd.setHours(23, 59, 59, 999);
    return allBlockedRanges.some(r => {
      const rs = new Date(r.start); const re = new Date(r.end);
      return rs <= dayEnd && re >= dayStart;
    });
  };

  const isCustomerBookedDay = (d: Date) => {
    const dayStart = new Date(d); dayStart.setHours(0, 0, 0, 0);
    const dayEnd = new Date(d); dayEnd.setHours(23, 59, 59, 999);
    return customerBlockedRanges.some(r => {
      const rs = new Date(r.start); const re = new Date(r.end);
      return rs <= dayEnd && re >= dayStart;
    });
  };

  // Uzatma modunda: pickupDateTime'dan sonraki ilk başkalarına ait rezervasyonun başlangıcını bul
  // — bu tarihten itibaren TÜM günler hard-block edilir (kullanıcı tıklayamaz bile)
  const extendHardLimit = useMemo<Date | null>(() => {
    if (!lockPickup) return null;
    const pickupMs = pickupDateTime.getTime();
    let earliest: Date | null = null;
    for (const r of allBlockedRanges) {
      const rs = new Date(r.start);
      if (rs.getTime() > pickupMs && (!earliest || rs < earliest)) {
        earliest = rs;
      }
    }
    return earliest;
  }, [lockPickup, allBlockedRanges, pickupDateTime]);

  const dayDisabled = (d: Date) => {
    if (d < minDate) return true;
    // Bugün ise: o günün son slotu (mesai bitişi) zaten geçmişse o günü disable et
    const todayStart = startOfDay(new Date());
    if (d.getTime() === todayStart.getTime()) {
      const [eh, em] = (availability?.mesai.end || '18:00').split(':').map(Number);
      const lastSlot = new Date(d);
      lastSlot.setHours(eh, em, 0, 0);
      if (Date.now() >= lastSlot.getTime()) return true;
    }
    // Uzatma modunda: başkasının rezervasyon başlangıç gününden itibaren tüm günler bloklu
    if (extendHardLimit) {
      const limitDayStart = startOfDay(extendHardLimit);
      if (d.getTime() >= limitDayStart.getTime()) return 'cakisma';
    }
    if (holidaysSet.has(fmtYMD(d))) return 'tatil';
    if (isBlockedWeekday(d)) return 'pazar';
    return false;
  };

  // Saat slotları (mesai aralığında, yarım saatlik adımlar)
  const slots = useMemo(() => {
    const [sh, sm] = (availability?.mesai.start || '09:00').split(':').map(Number);
    const [eh, em] = (availability?.mesai.end || '18:00').split(':').map(Number);
    const out: { h: number; m: number; label: string }[] = [];
    let curMin = sh * 60 + sm;
    const endMin = eh * 60 + em;
    while (curMin <= endMin) {
      const h = Math.floor(curMin / 60);
      const m = curMin % 60;
      out.push({ h, m, label: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}` });
      curMin += 30;
    }
    return out;
  }, [availability]);

  const tamponMs = (availability?.tampon_saat || 1) * 3600 * 1000;

  // Belirli bir tarih+saat seçimi — seçenekler için diğer rezervasyonlarla 1 saat tampon kontrolü
  const slotDisabled = (selectedDate: Date, slot: { h: number; m: number }) => {
    const dt = new Date(selectedDate);
    dt.setHours(slot.h, slot.m, 0, 0);
    // Bugün ise geçmiş saatleri engelle
    const nowMs = Date.now();
    if (dt.getTime() <= nowMs) return true;
    if (editing === 'return' && dt <= pickupDateTime) return true;
    // Çakışma + tampon (hem araç hem müşteri rezervasyonları)
    for (const r of allBlockedRanges) {
      const rs = new Date(r.start);
      const re = new Date(r.end);
      // Tampon ekleyerek çakışma kontrolü
      const rsBuf = new Date(rs.getTime() - tamponMs);
      const reBuf = new Date(re.getTime() + tamponMs);
      if (editing === 'pickup') {
        // Pickup tarih/saat bu aralık içine düşemez
        if (dt >= rsBuf && dt < reBuf) return true;
      } else {
        // Return: pickup-return aralığı bu rezervasyonla çakışmamalı (tampon dahil)
        if (pickupDateTime < reBuf && dt > rsBuf) return true;
      }
    }
    return false;
  };

  const monthMatrix = useMemo(() => {
    const y = viewMonth.getFullYear();
    const m = viewMonth.getMonth();
    const first = new Date(y, m, 1);
    const firstWeekdayJS = first.getDay(); // 0=Sun
    // Pzt başlat: offset
    const offset = (firstWeekdayJS + 6) % 7;
    const days = daysInMonth(y, m);
    const cells: (Date | null)[] = [];
    for (let i = 0; i < offset; i++) cells.push(null);
    for (let d = 1; d <= days; d++) cells.push(new Date(y, m, d));
    while (cells.length % 7 !== 0) cells.push(null);
    return cells;
  }, [viewMonth]);

  const onPickDate = (d: Date) => {
    if (editing === 'pickup') {
      const next = new Date(d);
      next.setHours(pickupDateTime.getHours(), pickupDateTime.getMinutes(), 0, 0);
      onChangePickup(next);
      // İade saati = teslim saati. İade tarihi pickup'tan sonra olmalı, eğer değilse ertesi gün yap.
      const r = new Date(returnDateTime);
      r.setHours(next.getHours(), next.getMinutes(), 0, 0);
      if (r <= next) {
        const r2 = new Date(next); r2.setDate(r2.getDate() + 1);
        onChangeReturn(r2);
      } else {
        onChangeReturn(r);
      }
    } else {
      // İade tarihi seçildi — saat pickup'tan kopyalanır
      const next = new Date(d);
      next.setHours(pickupDateTime.getHours(), pickupDateTime.getMinutes(), 0, 0);
      // Eğer tarih = pickup tarihi ise saat aynı olur, en az +1 gün gerekiyor
      if (next <= pickupDateTime) {
        const r2 = new Date(pickupDateTime); r2.setDate(r2.getDate() + 1);
        onChangeReturn(r2);
      } else {
        onChangeReturn(next);
      }
    }
  };

  const onPickSlot = (slot: { h: number; m: number }) => {
    const cur = editing === 'pickup' ? pickupDateTime : returnDateTime;
    const next = new Date(cur);
    next.setHours(slot.h, slot.m, 0, 0);
    if (editing === 'pickup') {
      onChangePickup(next);
      // İade saatini de pickup saatine eşitle (tarih korunur)
      const r = new Date(returnDateTime);
      r.setHours(slot.h, slot.m, 0, 0);
      if (r <= next) {
        const r2 = new Date(next);
        r2.setDate(r2.getDate() + 1);
        onChangeReturn(r2);
      } else {
        onChangeReturn(r);
      }
    } else {
      onChangeReturn(next);
    }
  };

  // Kira süresi (gün) — pickup ile return arasındaki tam gün sayısı
  const rentDays = useMemo(() => {
    const ms = returnDateTime.getTime() - pickupDateTime.getTime();
    return Math.max(1, Math.ceil(ms / (1000 * 60 * 60 * 24)));
  }, [pickupDateTime, returnDateTime]);

  const changeRentDays = (delta: number) => {
    // Mevcut return date'ten itibaren, blocked olmayan bir sonraki/önceki günü bul
    let candidate = new Date(returnDateTime);
    candidate.setDate(candidate.getDate() + delta);
    const minReturn = new Date(pickupDateTime);
    minReturn.setDate(minReturn.getDate() + 1);
    // En az pickup + 1 gün olmalı
    if (candidate.getTime() < minReturn.getTime()) return;
    // Engellenmiş günleri atla (delta yönünde)
    const step = delta > 0 ? 1 : -1;
    let safety = 30; // sonsuz döngü koruması
    while (dayDisabled(candidate) && safety > 0) {
      candidate.setDate(candidate.getDate() + step);
      // Eğer geriye giderken minReturn'den önce kaldıysak dur
      if (step < 0 && candidate.getTime() < minReturn.getTime()) return;
      safety--;
    }
    if (dayDisabled(candidate)) return;
    onChangeReturn(candidate);
  };

  const selectedDate = editing === 'pickup' ? pickupDateTime : returnDateTime;

  return (
    <View>
      {/* Tab seçici (uzatma modunda gizli) */}
      {!lockPickup && (
        <View style={styles.tabRow}>
          <Pressable testID="dt-tab-pickup" onPress={() => { setEditing('pickup'); setViewMonth(startOfDay(pickupDateTime)); }} style={[styles.tab, editing === 'pickup' && styles.tabActive]}>
            <Ionicons name="log-in-outline" size={16} color={editing === 'pickup' ? '#fff' : Colors.text.secondary} />
            <View style={{ marginLeft: 6 }}>
              <Text style={[styles.tabLabel, editing === 'pickup' && { color: '#fff' }]}>TESLİM ALIŞ</Text>
              <Text style={[styles.tabValue, editing === 'pickup' && { color: '#fff' }]}>
                {pickupDateTime.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' })} • {String(pickupDateTime.getHours()).padStart(2, '0')}:{String(pickupDateTime.getMinutes()).padStart(2, '0')}
              </Text>
            </View>
          </Pressable>
          <Pressable testID="dt-tab-return" onPress={() => { setEditing('return'); setViewMonth(startOfDay(returnDateTime)); }} style={[styles.tab, editing === 'return' && styles.tabActive]}>
            <Ionicons name="log-out-outline" size={16} color={editing === 'return' ? '#fff' : Colors.text.secondary} />
            <View style={{ marginLeft: 6 }}>
              <Text style={[styles.tabLabel, editing === 'return' && { color: '#fff' }]}>İADE</Text>
              <Text style={[styles.tabValue, editing === 'return' && { color: '#fff' }]}>
                {returnDateTime.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short' })} • {String(returnDateTime.getHours()).padStart(2, '0')}:{String(returnDateTime.getMinutes()).padStart(2, '0')}
              </Text>
            </View>
          </Pressable>
        </View>
      )}

      {/* Uzatma modunda: sadece yeni iade tarihi başlığı */}
      {lockPickup && (
        <View style={[styles.tab, styles.tabActive, { marginBottom: Spacing.md }]}>
          <Ionicons name="time-outline" size={18} color="#fff" />
          <View style={{ marginLeft: 8 }}>
            <Text style={[styles.tabLabel, { color: '#fff' }]}>YENİ İADE TARİHİ</Text>
            <Text style={[styles.tabValue, { color: '#fff' }]}>
              {returnDateTime.toLocaleDateString('tr-TR', { day: '2-digit', month: 'short', year: 'numeric' })} • {String(returnDateTime.getHours()).padStart(2, '0')}:{String(returnDateTime.getMinutes()).padStart(2, '0')}
            </Text>
          </View>
        </View>
      )}

      {/* Ay başlığı */}
      <View style={styles.monthHeader}>
        <Pressable
          onPress={() => setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() - 1, 1))}
          style={styles.monthNavBtn}
          testID="dt-prev-month"
        >
          <Ionicons name="chevron-back" size={18} color={Colors.text.primary} />
        </Pressable>
        <Text style={styles.monthTitle}>
          {MONTHS[viewMonth.getMonth()]} {viewMonth.getFullYear()}
        </Text>
        <Pressable
          onPress={() => setViewMonth(new Date(viewMonth.getFullYear(), viewMonth.getMonth() + 1, 1))}
          style={styles.monthNavBtn}
          testID="dt-next-month"
        >
          <Ionicons name="chevron-forward" size={18} color={Colors.text.primary} />
        </Pressable>
      </View>

      {/* Hafta günleri */}
      <View style={styles.weekRow}>
        {WEEKDAYS_SHORT.map((w, i) => (
          <Text key={w} style={[styles.weekday, (i === 6) && { color: Colors.brand.primaryLight }]}>{w}</Text>
        ))}
      </View>

      {/* Takvim grid */}
      <View style={styles.grid}>
        {monthMatrix.map((d, idx) => {
          if (!d) return <View key={idx} style={styles.cell} />;
          const isSelected = ymdEqual(d, selectedDate);
          const blockReason = dayDisabled(d);
          const fullyBooked = isFullyBookedDay(d) && !isSelected;
          const customerBooked = isCustomerBookedDay(d) && !isSelected;
          const disabled = !!blockReason;
          // Range: pickup→return arası (her iki uç dahil değil, sadece arası)
          const pickupDay = startOfDay(pickupDateTime).getTime();
          const returnDay = startOfDay(returnDateTime).getTime();
          const cellDay = startOfDay(d).getTime();
          const isPickupCell = cellDay === pickupDay;
          const isReturnCell = cellDay === returnDay;
          const isInRange = cellDay > pickupDay && cellDay < returnDay;
          const isRangeEdge = isPickupCell || isReturnCell;

          return (
            <Pressable
              key={idx}
              testID={`dt-day-${fmtYMD(d)}`}
              onPress={() => !disabled && onPickDate(d)}
              disabled={disabled}
              style={[
                styles.cell,
                fullyBooked && styles.cellBooked,
                customerBooked && styles.cellCustomerBooked,
                disabled && styles.cellDisabled,
                (blockReason === 'tatil' || blockReason === 'pazar') && styles.cellHoliday,
                isInRange && styles.cellInRange,
                isRangeEdge && styles.cellRangeEdge,
                isSelected && styles.cellSelected,
              ]}
            >
              <Text style={[
                styles.cellText,
                disabled && styles.cellTextDisabled,
                isSelected && styles.cellTextSelected,
                fullyBooked && !isSelected && styles.cellTextBooked,
                (blockReason === 'tatil' || blockReason === 'pazar') && !isSelected && styles.cellTextHoliday,
              ]}>
                {d.getDate()}
              </Text>
              {fullyBooked && !customerBooked && !disabled && !isSelected && <View style={styles.bookedDot} />}
              {customerBooked && !disabled && !isSelected && <View style={styles.customerDot} />}
            </Pressable>
          );
        })}
      </View>

      {/* Kira süresi kısayolu */}
      <View style={styles.rentDaysRow}>
        <Pressable
          testID="dt-days-dec"
          onPress={() => changeRentDays(-1)}
          disabled={rentDays <= 1}
          style={[styles.daysBtn, rentDays <= 1 && { opacity: 0.4 }]}
        >
          <Ionicons name="chevron-back" size={18} color={Colors.text.primary} />
        </Pressable>
        <View style={styles.daysCenter}>
          <Text style={styles.daysLabel}>KİRA SÜRESİ</Text>
          <Text style={styles.daysValue}>{rentDays} GÜN</Text>
        </View>
        <Pressable
          testID="dt-days-inc"
          onPress={() => changeRentDays(1)}
          style={styles.daysBtn}
        >
          <Ionicons name="chevron-forward" size={18} color={Colors.text.primary} />
        </Pressable>
      </View>

      <View style={styles.legend}>
        <View style={styles.legendItem}><View style={[styles.legendDot, { backgroundColor: Colors.brand.primary }]} /><Text style={styles.legendText}>Seçili</Text></View>
        <View style={styles.legendItem}><View style={[styles.legendDot, { backgroundColor: Colors.text.tertiary }]} /><Text style={styles.legendText}>Dolu</Text></View>
        {customerBlockedRanges.length > 0 && (
          <View style={styles.legendItem}><View style={[styles.legendDot, { backgroundColor: Colors.status.info }]} /><Text style={styles.legendText}>Sizin Rez.</Text></View>
        )}
        <View style={styles.legendItem}><View style={[styles.legendDot, { backgroundColor: Colors.status.warning }]} /><Text style={styles.legendText}>Tatil/Pazar</Text></View>
      </View>

      {/* Saat seçici (sadece teslim alış için) */}
      {editing === 'pickup' ? (
        <>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={[styles.slotsRow, { marginTop: Spacing.lg }]}>
            {slots.map(s => {
              const dt = new Date(selectedDate);
              dt.setHours(s.h, s.m, 0, 0);
              const isSel = dt.getHours() === selectedDate.getHours() && dt.getMinutes() === selectedDate.getMinutes();
              const dis = slotDisabled(selectedDate, s);
              return (
                <Pressable
                  key={s.label}
                  testID={`dt-slot-${s.label}`}
                  onPress={() => !dis && onPickSlot(s)}
                  disabled={dis}
                  style={[styles.slot, isSel && styles.slotSelected, dis && styles.slotDisabled]}
                >
                  <Text style={[styles.slotText, isSel && styles.slotTextSelected, dis && styles.slotTextDisabled]}>{s.label}</Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </>
      ) : (
        <View style={styles.returnTimeBox}>
          <Ionicons name="lock-closed" size={16} color={Colors.brand.primaryLight} />
          <View style={{ flex: 1 }}>
            <Text style={styles.returnTimeLabel}>{lockPickup ? 'İade Saati' : 'İade Saati (otomatik)'}</Text>
            <Text style={styles.returnTimeValue}>
              {String(pickupDateTime.getHours()).padStart(2, '0')}:{String(pickupDateTime.getMinutes()).padStart(2, '0')} — {lockPickup ? 'Mevcut iade saatiniz korunur' : 'Teslim alış saatinizle aynıdır'}
            </Text>
          </View>
        </View>
      )}

      <View style={styles.infoBox}>
        <Ionicons name="information-circle" size={14} color={Colors.text.secondary} />
        <Text style={styles.infoText}>
          Pazar günleri ve mesai saatleri (
          {availability?.mesai.start} - {availability?.mesai.end}
          ) dışı kapalıdır. Rezervasyonlar arası en az {availability?.tampon_saat || 1} saat tampon vardır.
        </Text>
      </View>
    </View>
  );
}

const CELL_W = `${100 / 7}%` as any;
const styles = StyleSheet.create({
  tabRow: { flexDirection: 'row', gap: 8, marginBottom: Spacing.md },
  tab: { flex: 1, flexDirection: 'row', alignItems: 'center', padding: Spacing.md, borderRadius: Radius.md, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base },
  tabActive: { backgroundColor: Colors.brand.primary, borderColor: Colors.brand.primaryLight },
  tabLabel: { ...Typography.micro, color: Colors.text.secondary, letterSpacing: 1 },
  tabValue: { ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 },
  monthHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingVertical: Spacing.sm },
  monthNavBtn: { width: 36, height: 36, borderRadius: 18, backgroundColor: Colors.bg.surface2, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: Colors.border.base },
  monthTitle: { ...Typography.h4, color: Colors.text.primary },
  weekRow: { flexDirection: 'row', marginTop: 4, marginBottom: 4 },
  weekday: { width: CELL_W, textAlign: 'center', ...Typography.micro, color: Colors.text.tertiary, fontWeight: '700' },
  grid: { flexDirection: 'row', flexWrap: 'wrap' },
  cell: { width: CELL_W, aspectRatio: 1, alignItems: 'center', justifyContent: 'center', padding: 2 },
  cellSelected: { backgroundColor: Colors.brand.primary, borderRadius: 8 },
  cellInRange: { backgroundColor: Colors.brand.primary + '30', borderRadius: 0 },
  cellRangeEdge: { backgroundColor: Colors.brand.primary, borderRadius: 8 },
  cellDisabled: { opacity: 0.35 },
  cellBooked: { backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: 8 },
  cellCustomerBooked: { backgroundColor: 'rgba(90, 200, 250, 0.12)', borderRadius: 8, borderWidth: 1, borderColor: 'rgba(90, 200, 250, 0.4)' },
  cellHoliday: { backgroundColor: 'rgba(251, 191, 36, 0.35)', borderRadius: 8, borderWidth: 1, borderColor: 'rgba(251, 191, 36, 0.7)', opacity: 1 },
  cellText: { ...Typography.body, color: Colors.text.primary, fontWeight: '600' },
  cellTextDisabled: { color: Colors.text.tertiary, textDecorationLine: 'line-through' },
  cellTextSelected: { color: '#fff', fontWeight: '900' },
  cellTextBooked: { color: Colors.text.tertiary },
  cellTextHoliday: { color: Colors.status.warning },
  bookedDot: { position: 'absolute', bottom: 6, width: 4, height: 4, borderRadius: 2, backgroundColor: Colors.text.tertiary },
  customerDot: { position: 'absolute', bottom: 6, width: 4, height: 4, borderRadius: 2, backgroundColor: Colors.status.info },
  holidayDot: { position: 'absolute', bottom: 6, width: 4, height: 4, borderRadius: 2, backgroundColor: Colors.status.warning },
  rentDaysRow: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    marginTop: 4, marginBottom: Spacing.sm,
    backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, padding: Spacing.sm,
    borderWidth: 1, borderColor: Colors.border.base,
  },
  daysBtn: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: Colors.brand.primary, alignItems: 'center', justifyContent: 'center',
  },
  daysCenter: { flex: 1, alignItems: 'center' },
  daysLabel: { ...Typography.micro, color: Colors.text.secondary, letterSpacing: 1, fontWeight: '700' },
  daysValue: { fontSize: 18, fontWeight: '900', color: Colors.brand.primary, marginTop: 2 },
  legend: { flexDirection: 'row', gap: Spacing.md, marginTop: Spacing.sm, justifyContent: 'center' },
  legendItem: { flexDirection: 'row', alignItems: 'center', gap: 4 },
  legendDot: { width: 8, height: 8, borderRadius: 4 },
  legendText: { ...Typography.micro, color: Colors.text.secondary },
  timeTitle: { ...Typography.bodyBold, color: Colors.text.primary, marginTop: Spacing.lg, marginBottom: Spacing.sm },
  slotsRow: { gap: 6, paddingVertical: 4 },
  slot: { paddingHorizontal: Spacing.md, paddingVertical: 8, borderRadius: Radius.pill, backgroundColor: Colors.bg.surface2, borderWidth: 1, borderColor: Colors.border.base, minWidth: 64, alignItems: 'center' },
  slotSelected: { backgroundColor: Colors.brand.primary, borderColor: Colors.brand.primaryLight },
  slotDisabled: { opacity: 0.3 },
  slotText: { ...Typography.bodyBold, color: Colors.text.primary, fontWeight: '700' },
  slotTextSelected: { color: '#fff' },
  slotTextDisabled: { textDecorationLine: 'line-through', color: Colors.text.tertiary },
  returnTimeBox: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: Spacing.lg, padding: Spacing.md, backgroundColor: Colors.bg.surface2, borderRadius: Radius.md, borderWidth: 1, borderColor: Colors.border.accent },
  returnTimeLabel: { ...Typography.micro, color: Colors.text.secondary, textTransform: 'uppercase' },
  returnTimeValue: { ...Typography.bodyBold, color: Colors.text.primary, marginTop: 2 },
  infoBox: { flexDirection: 'row', gap: 6, marginTop: Spacing.md, padding: Spacing.sm, borderRadius: Radius.sm, backgroundColor: Colors.bg.surface2, borderLeftWidth: 3, borderLeftColor: Colors.brand.primaryLight },
  infoText: { flex: 1, ...Typography.micro, color: Colors.text.secondary, lineHeight: 16 },
});
