import AsyncStorage from '@react-native-async-storage/async-storage';

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_URL || '';
const API = `${BASE_URL}/api`;
const TOKEN_KEY = 'ys_token';
const USER_KEY = 'ys_user';

export type Role = 'customer' | 'admin';

export type KmKademe = { min_gun: number; max_gun: number | null; gunluk_km: number };
export type KmAsimKademe = { min_gun: number; max_gun: number | null; km_asim_fiyat: number };
export type GunlukFiyatKademe = { min_gun: number; max_gun: number | null; gunluk_fiyat: number };

export type Vehicle = {
  id: string; plaka: string; marka: string; model: string; yil: number; renk: string;
  vites: string; yakit: string; foto_url: string;
  gunluk_fiyat: number; gunluk_km: number; aciklama: string;
  durum: 'musait' | 'dolu' | 'bakim';
  manuel_durum?: string | null;
  ekstra_ozellikler?: string[];
  gunluk_fiyat_kademeleri?: GunlukFiyatKademe[];
  km_kademeleri?: KmKademe[];
  km_asim_fiyat?: number | null;
  km_asim_kademeleri?: KmAsimKademe[];
};

export type Service = {
  id: string; isim: string; aciklama: string;
  fiyat: number; tip: 'gunluk' | 'tek_seferlik';
  icon: string; aktif: boolean; zorunlu?: boolean; arac_ids?: string[]; siralama: number;
};

export type Pricing = {
  gun_sayisi: number; gunluk_fiyat: number;
  arac_alt_toplam: number; sure_indirim_yuzde: number;
  sure_indirim_tutar: number; arac_toplam: number;
  hizmetler: { service_id: string; isim: string; tip: string; fiyat: number; adet: number; tutar: number }[];
  hizmetler_toplam: number;
  iskonto_yuzde: number; iskonto_tutar: number;
  toplam_tutar: number; on_odeme_tutar: number;
  kalan_odeme: number; paket_km: number;
};

export type Reservation = {
  id: string; customer_id: string; vehicle_id: string;
  vehicle_snapshot: { plaka: string; marka: string; model: string; foto_url: string; renk: string };
  baslangic_tarihi: string; bitis_tarihi: string;
  gun_sayisi: number; gunluk_fiyat: number;
  toplam_tutar: number; on_odeme_tutar: number; kalan_odeme: number; odenen_ucret: number;
  paket_km: number; kullanilan_km: number; alis_km?: number | null; guncel_km?: number | null; km_asim?: number;
  km_asim_tutar?: number;
  telefon: string;
  durum: 'beklemede' | 'onaylandi' | 'aktif' | 'tamamlandi' | 'iptal';
  odeme_durumu: 'beklemede' | 'on_odeme_alindi' | 'tam_odeme_alindi';
  odeme_yontemi: 'bakiye' | 'havale';
  uzatma_sayisi: number; son_uzatma_tarih?: string | null;
  olusturan?: 'musteri' | 'admin'; iskonto_yuzde?: number;
  pricing?: Pricing;
  secilen_hizmetler?: any[];
  created_at: string;
  kalan_saniye?: number;
  live?: { kontak: string; hiz: number; device_id: string; live: boolean };
  teslim_fotograflari?: { id: string; url: string; aciklama: string; uploaded_at: string }[];
};

export type AppNotification = {
  id: string; baslik: string; mesaj: string;
  hedef_type: string; tarih: string; okundu: boolean;
  deep_link?: string;
};

export type Settings = {
  iban?: string; banka?: string; hesap_sahibi?: string;
  iletisim_telefon?: string; iletisim_email?: string;
  iletisim_adres?: string; whatsapp?: string;
  mesai_baslangic?: string; mesai_bitis?: string;
  tatil_haftaici_gunler?: number[];
  indirim_min_gun?: number; indirim_yuzde?: number;
  km_asim_fiyat?: number;
  km_hacim_indirim_kademeleri?: KmHacimKademe[];
  sirket_adi?: string;
  kart_kdv_yuzde?: number;
  kart_komisyon_yuzde?: number;
};

export type WalletTx = {
  id: string; customer_id: string;
  tip: string; tutar: number; isaret: '+' | '-';
  aciklama: string; referans?: string;
  bakiye_sonra?: number; tarih: string;
  durum?: string;
};

export type AuthUser = {
  id: string; ad: string; soyad: string;
  telefon?: string; email?: string;
  kullanici_adi?: string; bakiye?: number;
};

async function request<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(opts.headers as Record<string, string>),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  const text = await res.text();
  let data: any = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) {
    const message = data?.detail || data?.message || `Hata (${res.status})`;
    const err: any = new Error(typeof message === 'string' ? message : JSON.stringify(message));
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data as T;
}

export const auth = {
  /** Birleşik giriş: önce admin TC'sini, sonra müşteri TC'sini kontrol eder */
  async login(ad: string, soyad: string, tc: string) {
    const res = await request<{ token: string; role: Role; user: AuthUser }>(
      '/auth/login', { method: 'POST', body: JSON.stringify({ ad, soyad, tc }) });
    await AsyncStorage.setItem(TOKEN_KEY, res.token);
    await AsyncStorage.setItem(USER_KEY, JSON.stringify({ ...res.user, role: res.role }));
    return res;
  },
  async loginCustomer(ad: string, soyad: string, tc: string) {
    const res = await request<{ token: string; role: Role; user: AuthUser }>(
      '/auth/customer/login', { method: 'POST', body: JSON.stringify({ ad, soyad, tc }) });
    await AsyncStorage.setItem(TOKEN_KEY, res.token);
    await AsyncStorage.setItem(USER_KEY, JSON.stringify({ ...res.user, role: res.role }));
    return res;
  },
  async loginCustomerByPhone(telefon: string) {
    const res = await request<{ token: string; role: Role; user: AuthUser }>(
      '/auth/customer/login', { method: 'POST', body: JSON.stringify({ telefon }) });
    await AsyncStorage.setItem(TOKEN_KEY, res.token);
    await AsyncStorage.setItem(USER_KEY, JSON.stringify({ ...res.user, role: res.role }));
    return res;
  },
  async loginAdmin(kullanici_adi: string, sifre: string) {
    const res = await request<{ token: string; role: Role; user: AuthUser }>(
      '/auth/admin/login', { method: 'POST', body: JSON.stringify({ kullanici_adi, sifre }) });
    await AsyncStorage.setItem(TOKEN_KEY, res.token);
    await AsyncStorage.setItem(USER_KEY, JSON.stringify({ ...res.user, role: res.role }));
    return res;
  },
  async me() { return request<{ role: Role; user: AuthUser }>('/auth/me'); },
  async logout() { await AsyncStorage.removeItem(TOKEN_KEY); await AsyncStorage.removeItem(USER_KEY); },
  async registerPushToken(token: string, platform: string) {
    try {
      return await request<{ ok: boolean }>('/push/register', { method: 'POST', body: JSON.stringify({ token, platform }) });
    } catch { return null; }
  },
  async unregisterPushToken(token: string) {
    try {
      return await request<{ ok: boolean }>('/push/unregister', { method: 'POST', body: JSON.stringify({ token }) });
    } catch { return null; }
  },
  async getStored() {
    const token = await AsyncStorage.getItem(TOKEN_KEY);
    const userStr = await AsyncStorage.getItem(USER_KEY);
    if (!token || !userStr) return null;
    try { return { token, user: JSON.parse(userStr) as AuthUser & { role: Role } }; } catch { return null; }
  },
};

export const customerApi = {
  vehicles: () => request<Vehicle[]>('/vehicles'),
  myProfile: () => request<{ id: string; ad: string; soyad: string; telefon?: string; email?: string; adres?: string; tip?: string; firma_adi?: string; vergi_no?: string; yetkili?: string }>('/me'),
  vehicle: (id: string) => request<Vehicle>(`/vehicles/${id}`),
  services: (vehicle_id?: string) => request<Service[]>(`/services${vehicle_id ? `?vehicle_id=${encodeURIComponent(vehicle_id)}` : ''}`),
  quote: (data: { vehicle_id: string; baslangic_tarihi: string; bitis_tarihi: string; telefon?: string; secilen_hizmetler?: { service_id: string; adet: number }[] }) =>
    request<Pricing>('/quote', { method: 'POST', body: JSON.stringify({ ...data, telefon: data.telefon || '' }) }),
  reservations: () => request<Reservation[]>('/reservations'),
  activeReservation: () => request<Reservation | null>('/reservations/active'),
  reservationDetail: (rid: string) => request<Reservation>(`/reservations/${rid}`),
  reserve: (data: { vehicle_id: string; baslangic_tarihi: string; bitis_tarihi: string; telefon: string; secilen_hizmetler?: { service_id: string; adet: number }[]; odeme_tipi?: 'auto' | 'full' | 'deposit' }) =>
    request<Reservation>('/reservations', { method: 'POST', body: JSON.stringify({ ...data, secilen_hizmetler: data.secilen_hizmetler || [], odeme_tipi: data.odeme_tipi || 'auto' }) }),
  confirmPayment: (rid: string, referans_no?: string, notlar?: string) =>
    request<{ ok: boolean; message: string }>(`/reservations/${rid}/payment-confirm`, { method: 'POST', body: JSON.stringify({ referans_no, notlar }) }),

  wallet: () => request<{ bakiye: number }>('/wallet'),
  walletTx: () => request<WalletTx[]>('/wallet/transactions'),
  walletTopup: (data: { tutar: number; yontem: 'kart' | 'havale'; kart_no?: string; kart_sahibi?: string; son_kullanma?: string; cvc?: string; havale_referans?: string; dekont_base64?: string }) =>
    request<{ ok: boolean; bakiye?: number; yontem: string; durum: string; brut_tutar?: number; kdv_tutar?: number; komisyon_tutar?: number; net_tutar?: number; ai_onay?: boolean; ai_result?: any; message?: string }>('/wallet/topup', { method: 'POST', body: JSON.stringify(data) }),

  shopierInit: (tutar: number) =>
    request<{ ok: boolean; checkout_url: string; order_id: string; mode: 'real' | 'mock'; info?: string }>('/wallet/shopier/init', { method: 'POST', body: JSON.stringify({ tutar }) }),
  shopierMockConfirm: (order_id: string) =>
    request<{ ok: boolean; bakiye: number; durum: string }>(`/wallet/shopier/confirm-mock?order_id=${encodeURIComponent(order_id)}`, { method: 'POST' }),

  vehicleAvailability: (vid: string) =>
    request<{
      blocked_ranges: { start: string; end: string }[];
      customer_blocked_ranges: { start: string; end: string; plaka: string }[];
      holidays: { tarih: string; aciklama: string }[];
      blocked_weekdays: number[];
      mesai: { start: string; end: string };
      tampon_saat: number;
    }>(`/vehicles/${vid}/availability`),

  availableVehicles: (data: { baslangic_tarihi: string; bitis_tarihi: string; exclude_vehicle_id?: string }) =>
    request<{ available: Vehicle[]; count: number }>('/vehicles/available', { method: 'POST', body: JSON.stringify(data) }),

  extendQuote: (rid: string, yeni_bitis_tarihi: string, secilen_hizmetler: { service_id: string; adet: number }[] = [], ek_km: number = 0) =>
    request<{
      ok: boolean;
      ek_gun?: number;
      ek_tutar?: number;
      ek_arac_tutar?: number;
      ek_hizmet_tutar?: number;
      ek_hizmetler?: { service_id: string; isim: string; fiyat: number; tutar: number }[];
      ek_indirim?: number;
      ek_km_satin?: number;
      ek_km_tutar?: number;
      km_asim_fiyat?: number;
      bakiye?: number;
      bakiye_yeterli?: boolean;
      eksik?: number;
      blocked_reason?: 'tatil' | 'mesai' | 'cakisma';
      message?: string;
    }>(`/reservations/${rid}/extend-quote`, { method: 'POST', body: JSON.stringify({ yeni_bitis_tarihi, secilen_hizmetler, ek_km }) }),

  extend: (rid: string, yeni_bitis_tarihi: string, secilen_hizmetler: { service_id: string; adet: number }[] = [], ek_km: number = 0) =>
    request<any>(`/reservations/${rid}/extend`, { method: 'POST', body: JSON.stringify({ yeni_bitis_tarihi, secilen_hizmetler, ek_km }) }),

  buyKmQuote: (rid: string, ek_km: number) =>
    request<{ ok: boolean; ek_km: number; tutar: number; brut_tutar?: number; indirim_tutar?: number; km_asim_fiyat: number; km_asim_baz?: number; km_asim_kademe?: KmAsimKademe | null; km_asim_kademeleri?: KmAsimKademe[]; gun_sayisi?: number; bakiye: number; bakiye_yeterli: boolean; eksik: number; mevcut_paket_km: number }>(`/reservations/${rid}/buy-km-quote`, {
      method: 'POST',
      body: JSON.stringify({ ek_km }),
    }),

  buyKm: (rid: string, ek_km: number) =>
    request<{ ok: boolean; ek_km: number; tutar: number; brut_tutar?: number; indirim_tutar?: number; yeni_paket_km: number }>(`/reservations/${rid}/buy-km`, {
      method: 'POST',
      body: JSON.stringify({ ek_km }),
    }),

  notifications: () => request<AppNotification[]>('/notifications'),
  unreadCount: () => request<{ count: number }>('/notifications/unread-count'),
  markRead: (nid: string) => request<{ ok: boolean }>(`/notifications/${nid}/read`, { method: 'POST' }),
  markAllRead: () => request<{ ok: boolean }>('/notifications/read-all', { method: 'POST' }),

  publicSettings: () => request<Settings>('/settings/public'),
  publicHolidays: () => request<{ id: string; tarih: string; aciklama: string }[]>('/holidays/public'),

  // Reviews / Yorumlar
  createReview: (data: { reservation_id: string; arac_puan: number; servis_puan: number; yorum?: string }) =>
    request<any>('/reviews', { method: 'POST', body: JSON.stringify(data) }),
  vehicleReviews: (vid: string, min_yildiz: number = 0) =>
    request<{ reviews: any[]; ortalama_arac: number; ortalama_servis: number; toplam: number }>(`/reviews/vehicle/${vid}?min_yildiz=${min_yildiz}`),
  featuredReviews: () => request<any[]>('/reviews/featured'),
  myReviews: () => request<any[]>('/reviews/me'),
  pendingReviewReservations: () => request<any[]>('/reservations/pending-review'),
};

export const adminApi = {
  dashboard: () => request<any>('/admin/dashboard'),
  customers: (q?: string, filtre?: 'engelli' | 'kurumsal' | 'bireysel') => {
    const params: string[] = [];
    if (q) params.push(`q=${encodeURIComponent(q)}`);
    if (filtre) params.push(`filtre=${filtre}`);
    return request<any[]>(`/admin/customers${params.length ? `?${params.join('&')}` : ''}`);
  },
  createCustomer: (d: any) => request<any>('/admin/customers', { method: 'POST', body: JSON.stringify(d) }),
  updateCustomer: (cid: string, d: any) => request<any>(`/admin/customers/${cid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteCustomer: (cid: string) => request<any>(`/admin/customers/${cid}`, { method: 'DELETE' }),
  walletCredit: (cid: string, tutar: number, aciklama?: string) =>
    request<any>(`/admin/customers/${cid}/wallet/credit?tutar=${tutar}&aciklama=${encodeURIComponent(aciklama || '')}`, { method: 'POST' }),
  walletDebit: (cid: string, tutar: number, aciklama?: string) =>
    request<any>(`/admin/customers/${cid}/wallet/debit?tutar=${tutar}&aciklama=${encodeURIComponent(aciklama || '')}`, { method: 'POST' }),
  customerWallet: (cid: string) => request<any>(`/admin/customers/${cid}/wallet`),

  vehicles: () => request<Vehicle[]>('/admin/vehicles'),
  createVehicle: (d: any) => request<Vehicle>('/admin/vehicles', { method: 'POST', body: JSON.stringify(d) }),
  updateVehicle: (vid: string, d: any) => request<Vehicle>(`/admin/vehicles/${vid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteVehicle: (vid: string) => request<any>(`/admin/vehicles/${vid}`, { method: 'DELETE' }),
  reorderVehicles: (orders: { id: string; siralama: number }[]) => request<any>('/admin/vehicles/order', { method: 'PUT', body: JSON.stringify({ orders }) }),
  setMotorBlokaj: (vid: string, aktif: boolean) =>
    request<{ ok: boolean; bot_responded: boolean; plaka: string; aktif: boolean }>(
      `/admin/vehicles/${vid}/motor-blokaj`,
      { method: 'POST', body: JSON.stringify({ aktif }) }
    ),
  // Admin Kullanıcı Yönetimi
  listAdmins: () => request<Array<{ id: string; ad: string; soyad?: string; tc_norm?: string; telefon?: string; email?: string; kullanici_adi?: string; created_at?: string }>>('/admin/admins'),
  createAdmin: (body: { ad: string; soyad: string; tc: string; telefon?: string; email?: string }) =>
    request<any>('/admin/admins', { method: 'POST', body: JSON.stringify(body) }),
  updateAdmin: (aid: string, body: { ad: string; soyad: string; tc: string; telefon?: string; email?: string }) =>
    request<any>(`/admin/admins/${aid}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteAdmin: (aid: string) =>
    request<{ ok: boolean }>(`/admin/admins/${aid}`, { method: 'DELETE' }),

  reservations: (durum?: string) => request<any[]>(`/admin/reservations${durum ? `?durum=${durum}` : ''}`),
  setReservationStatus: (rid: string, durum: string) =>
    request<any>(`/admin/reservations/${rid}/durum?durum=${durum}`, { method: 'PUT' }),
  editReservation: (rid: string, d: any) =>
    request<any>(`/admin/reservations/${rid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteReservation: (rid: string, refund: boolean = true) =>
    request<any>(`/admin/reservations/${rid}?refund=${refund}`, { method: 'DELETE' }),
  // Teslim Fotoğrafları (admin yükler, müşteri rezervasyon aktif iken görür)
  listTeslimFoto: (rid: string) =>
    request<{ id: string; url: string; aciklama: string; uploaded_at: string; uploaded_by: string }[]>(`/admin/reservations/${rid}/teslim-foto`),
  addTeslimFoto: (rid: string, foto_base64: string, aciklama: string = '') =>
    request<{ id: string; url: string; aciklama: string; uploaded_at: string }>(`/admin/reservations/${rid}/teslim-foto`, {
      method: 'POST',
      body: JSON.stringify({ foto_base64, aciklama }),
    }),
  deleteTeslimFoto: (rid: string, fid: string) =>
    request<{ ok: boolean }>(`/admin/reservations/${rid}/teslim-foto/${fid}`, { method: 'DELETE' }),
  setPaymentStatus: (rid: string, odeme_durumu: string) =>
    request<any>(`/admin/reservations/${rid}/odeme?odeme_durumu=${odeme_durumu}`, { method: 'PUT' }),
  setKm: (rid: string, alis_km?: number, guncel_km?: number) => {
    const params = new URLSearchParams();
    if (alis_km !== undefined) params.append('alis_km', String(alis_km));
    if (guncel_km !== undefined) params.append('guncel_km', String(guncel_km));
    return request<any>(`/admin/reservations/${rid}/km?${params.toString()}`, { method: 'PUT' });
  },
  manualReservation: (d: any) => request<any>('/admin/reservations/manual', { method: 'POST', body: JSON.stringify(d) }),
  createProvision: (rid: string, d: { tutar: number; aciklama: string }) =>
    request<any>(`/admin/reservations/${rid}/provizyon`, { method: 'POST', body: JSON.stringify({ reservation_id: rid, ...d }) }),
  refundProvision: (pid: string) => request<any>(`/admin/provisions/${pid}/iade`, { method: 'POST' }),
  listProvisions: (rid: string) => request<any[]>(`/admin/reservations/${rid}/provisions`),

  pendingTopups: () => request<any[]>('/admin/wallet-tx/pending'),
  approveTopup: (txId: string) => request<any>(`/admin/wallet-tx/${txId}/approve`, { method: 'POST' }),
  rejectTopup: (txId: string) => request<any>(`/admin/wallet-tx/${txId}/reject`, { method: 'POST' }),

  services: () => request<Service[]>('/admin/services'),
  createService: (d: any) => request<Service>('/admin/services', { method: 'POST', body: JSON.stringify(d) }),
  updateService: (sid: string, d: any) => request<Service>(`/admin/services/${sid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteService: (sid: string) => request<any>(`/admin/services/${sid}`, { method: 'DELETE' }),

  holidays: () => request<any[]>('/admin/holidays'),
  addHoliday: (d: { tarih: string; aciklama: string }) => request<any>('/admin/holidays', { method: 'POST', body: JSON.stringify(d) }),
  deleteHoliday: (hid: string) => request<any>(`/admin/holidays/${hid}`, { method: 'DELETE' }),

  notifications: () => request<any[]>('/admin/notifications'),
  sendNotification: (d: { baslik: string; mesaj: string; hedef_type: 'tum' | 'secili'; hedef_customer_ids?: string[] }) =>
    request<any>('/admin/notifications', { method: 'POST', body: JSON.stringify(d) }),
  deleteNotification: (nid: string) => request<any>(`/admin/notifications/${nid}`, { method: 'DELETE' }),

  settings: () => request<Settings>('/admin/settings'),
  updateSettings: (d: Settings) => request<Settings>('/admin/settings', { method: 'PUT', body: JSON.stringify(d) }),

  // Reviews / Yorum Yönetimi
  listReviews: (durum?: string) => request<any[]>(`/admin/reviews${durum ? `?durum=${durum}` : ''}`),
  updateReview: (rid: string, d: { durum?: string; admin_cevap?: string }) =>
    request<any>(`/admin/reviews/${rid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteReview: (rid: string) => request<any>(`/admin/reviews/${rid}`, { method: 'DELETE' }),

  // Müşteri filtre sayaçları
  customerCounts: () => request<{ tum: number; bireysel: number; kurumsal: number; engelli: number }>('/admin/customers/counts'),

  // Kazanç / Muhasebe
  earnings: (start?: string, end?: string, kasa?: 'rentcar' | 'eticaret' | 'belirsiz') => {
    const p: string[] = [];
    if (start) p.push(`start=${start}`);
    if (end) p.push(`end=${end}`);
    if (kasa) p.push(`kasa=${kasa}`);
    return request<{ kasa?: string; toplam_gelir: number; rezervasyon_gelir: number; manuel_gelir: number; toplam_gider: number; net: number; gelir_kalemleri: any[]; gider_kalemleri: any[] }>(`/admin/earnings${p.length ? `?${p.join('&')}` : ''}`);
  },
  cashflow: (kasa?: 'rentcar' | 'eticaret' | 'belirsiz') => request<{ kasa?: string; yukleme_total: number; manuel_gelir: number; musteri_bakiye_borcu: number; bekleyen_havaleler: number; bekleyen_havale_adet: number; bloke_provizyonlar: number; gider_total: number; rentcar_kasa: number; eticaret_kasa: number; net_kar: number; belirsiz_net: number; belirsiz_gelir: number; belirsiz_gider: number }>(`/admin/cashflow${kasa ? `?kasa=${kasa}` : ''}`),
  pendingRevenue: () => request<{ toplam: number; onaylandi_total: number; onaylandi_adet: number; aktif_total: number; aktif_adet: number }>('/admin/pending-revenue'),
  vehiclePerformance: (start?: string, end?: string) => {
    const p: string[] = [];
    if (start) p.push(`start=${start}`);
    if (end) p.push(`end=${end}`);
    return request<{ araclar: any[]; toplam_kazanc: number; arac_adet: number }>(`/admin/vehicle-performance${p.length ? `?${p.join('&')}` : ''}`);
  },
  earningCategories: (tip: 'gelir' | 'gider') => request<string[]>(`/admin/earning-categories?tip=${tip}`),
  // Expenses
  listExpenses: (start?: string, end?: string, kasa?: string) => {
    const p: string[] = [];
    if (start) p.push(`start=${start}`);
    if (end) p.push(`end=${end}`);
    if (kasa) p.push(`kasa=${kasa}`);
    return request<any[]>(`/admin/expenses${p.length ? `?${p.join('&')}` : ''}`);
  },
  createExpense: (d: { tarih: string; kategori: string; aciklama?: string; tutar: number; kasa?: 'rentcar' | 'eticaret' | null }) =>
    request<any>('/admin/expenses', { method: 'POST', body: JSON.stringify(d) }),
  updateExpense: (eid: string, d: { tarih?: string; kategori?: string; aciklama?: string; tutar?: number; kasa?: 'rentcar' | 'eticaret' | null }) =>
    request<any>(`/admin/expenses/${eid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteExpense: (eid: string) => request<any>(`/admin/expenses/${eid}`, { method: 'DELETE' }),
  // Manuel gelirler
  listManualIncomes: (start?: string, end?: string, kasa?: string) => {
    const p: string[] = [];
    if (start) p.push(`start=${start}`);
    if (end) p.push(`end=${end}`);
    if (kasa) p.push(`kasa=${kasa}`);
    return request<any[]>(`/admin/manual-incomes${p.length ? `?${p.join('&')}` : ''}`);
  },
  createManualIncome: (d: { tarih: string; kategori: string; aciklama?: string; tutar: number; kasa?: 'rentcar' | 'eticaret' | null }) =>
    request<any>('/admin/manual-incomes', { method: 'POST', body: JSON.stringify(d) }),
  updateManualIncome: (iid: string, d: { tarih?: string; kategori?: string; aciklama?: string; tutar?: number; kasa?: 'rentcar' | 'eticaret' | null }) =>
    request<any>(`/admin/manual-incomes/${iid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteManualIncome: (iid: string) => request<any>(`/admin/manual-incomes/${iid}`, { method: 'DELETE' }),

  // Muhasebe
  accountingYears: () => request<number[]>('/admin/accounting/years'),
  accountingMonthly: (yil: number) => request<{ yil: number; aylar: any[]; toplam_gelir: number; toplam_gider: number; toplam_hesaplanan_kdv: number; toplam_indirilecek_kdv: number; toplam_odenecek_kdv: number; toplam_net_kar: number }>(`/admin/accounting/monthly?yil=${yil}`),
  accountingQuarterly: (yil: number) => request<{ yil: number; oran: number; donemler: any[] }>(`/admin/accounting/quarterly?yil=${yil}`),
  accountingAnnual: () => request<{ oran: number; yillar: any[]; toplam: any }>('/admin/accounting/annual'),
  accountingSettings: () => request<{ kdv_orani: number; gecici_vergi_orani: number; gunluk_birim_fiyat_net: number }>('/admin/accounting/settings'),
  updateAccountingSettings: (d: { kdv_orani: number; gecici_vergi_orani: number; gunluk_birim_fiyat_net: number }) =>
    request<any>('/admin/accounting/settings', { method: 'PUT', body: JSON.stringify(d) }),
  listInvoices: (tip?: 'giden' | 'gelen', yil?: number, ay?: number) => {
    const p: string[] = [];
    if (tip) p.push(`tip=${tip}`);
    if (yil) p.push(`yil=${yil}`);
    if (ay) p.push(`ay=${ay}`);
    return request<any[]>(`/admin/invoices${p.length ? `?${p.join('&')}` : ''}`);
  },
  createGelenFatura: (d: any) => request<any>('/admin/invoices/gelen', { method: 'POST', body: JSON.stringify(d) }),
  updateGelenFatura: (iid: string, d: any) => request<any>(`/admin/invoices/gelen/${iid}`, { method: 'PUT', body: JSON.stringify(d) }),
  deleteInvoice: (iid: string) => request<any>(`/admin/invoices/${iid}`, { method: 'DELETE' }),
  regenerateInvoices: (force?: boolean) => request<{ created: number; skipped: number; total: number; force: boolean }>(`/admin/invoices/regenerate${force ? '?force=true' : ''}`, { method: 'POST' }),
};
