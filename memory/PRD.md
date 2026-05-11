# YS Auto - Mobile App + Admin Panel (v2)

## Project Overview
Cam efektli (glassmorphism) sportif kırmızı-siyah temalı, müşteri rezervasyon + araç takip + cüzdan + bildirim uygulaması ve admin paneli.

## Architecture
- **Frontend:** Expo Router (RN+Web) - mobil müşteri (`/(tabs)/`) + admin web (`/admin`)
- **Backend:** FastAPI + MongoDB (`/api/*`)
- **Auth:** JWT, müşteri Ad+Soyad+TC, admin kullanıcı/şifre
- **Bot proxy:** rentacarss port 8081 (KAPALI - mock fallback aktif)

## v2 New Features

### 💰 Cüzdan Sistemi
- Bakiye + işlem geçmişi
- **Kredi kartı yükleme** (mock — son rakamlar 0000 hata, diğerleri başarılı; üretim için Iyzico bekliyor)
- **Havale/EFT yükleme** (admin onayı gerektiren akış)
- Tüm rezervasyon ön ödemeleri ve uzatmalar bakiyeden tahsil edilir
- Bakiye yetersizse otomatik cüzdan ekrana yönlendirme

### 📅 Takvim ve Mesai Kuralları
- Pazar varsayılan tatil (admin değiştirebilir, herhangi bir gün)
- Belirli tarih tatilleri (bayram vb.) admin ekler/siler
- Mesai saatleri (varsayılan 09:00-18:00) admin ayarlar
- Rezervasyon ve süre uzatmada teslim/iade tarihleri tatil + mesai dışı olamaz

### 💸 Dinamik Fiyat / İndirim
- 2+ gün rezervasyon → otomatik %10 indirim (gün sayısı + yüzde admin ayarlı)
- Süre uzatmada da aynı indirim mantığı
- Manuel rezervasyonda admin iskonto yapabilir (yüzde)

### 🛠️ Ek Hizmetler
- Çocuk Koltuğu, Ek Sürücü, Tam Muafiyet Kasko, HGS, Yakıt Dolu Teslim
- **Tip:** "günlük" veya "tek_seferlik" — hesaplama otomatik
- Admin CRUD ekleyip-çıkarabilir, fiyatlandırır

### 📏 KM Aşım
- Aktif kiralamada paket KM aşılırsa, KM başına ₺ ile bakiyeden otomatik düşülür
- Müşteriye otomatik bildirim
- Admin alış/güncel KM girer (ileride bot otomatik yapacak)

### 🛡️ Provizyon Sistemi
- Admin kira sonrası ek tahsilat için (trafik cezası, eksik yakıt vb) provizyon tanımlar
- Bakiyeden çekilir, sorun yoksa iade edilir

### 📋 Manuel Rezervasyon (Admin)
- Admin panelden müşteri seç + araç seç + tarihler + iskonto yapabilir
- Müşteriye otomatik bildirim gider

### 🎨 Tasarım Yenilenmiş
- **İsim:** YS Rent A Car → **YS AUTO**
- Ana sayfa hero: kırmızı kavisli bant + dark alt kısım (resim referansına benzer)
- Araç listesi: **yatay kaydırma** (snap), kart tasarımı resimle uyumlu (plaka, fiyat ₺, günlük km)
- Bakiye kartı ana sayfada görünür, dokunulduğunda cüzdan açılır
- Cüzdan ekranı: kırmızı kart + işlem geçmişi + kart/havale modal

## Test Credentials
- **Müşteri:** Ad=Ahmet, Soyad=Yılmaz, TC=12345678901 (5.000₺ test bakiyesi)
- **Müşteri 2:** Ad=Mehmet, Soyad=Demir, TC=98765432101
- **Admin:** admin / admin1234

## Bot Integration
- URL: `http://89.252.179.135:8081`
- Bearer Token: `913dde91c73eee7797c4fb3d8acf0e4a6d8178889cb7931e5b36274663834693`
- **MOCKED** — port 8081 firewall arkasında. Açıldığında otomatik canlı çekecek.

## Endpoints (Müşteri)
- `POST /auth/customer/login`, `GET /auth/me`
- `GET /vehicles`, `GET /vehicles/{id}`, `GET /services`
- `POST /quote` (fiyat hesaplama)
- `POST /reservations`, `GET /reservations`, `GET /reservations/active`, `GET /reservations/{id}`
- `POST /reservations/{id}/extend`, `POST /reservations/{id}/payment-confirm`
- `GET /wallet`, `GET /wallet/transactions`, `POST /wallet/topup`
- `GET /notifications`, `POST /notifications/{id}/read`
- `GET /settings/public`, `GET /holidays/public`

## Endpoints (Admin)
- Customers + wallet credit/debit + customer wallet view
- Vehicles CRUD + manuel durum
- Reservations + durum/ödeme/KM güncelleme + manuel rezervasyon
- Services CRUD, Holidays CRUD, Settings
- Notifications send + pending topup approval
- Provisions create + refund
- Dashboard stats

## Yapılmayan / Sonraki Tur
- Sözleşme/fatura PDF üretimi (geçmiş kiralama dökümleri)
- 6 saat öncesi otomatik bildirim cron job (şu an yapı hazır, scheduler eklenecek)
- Iyzico canlı ödeme entegrasyonu (şu an mock kart)
- Push notification (OneSignal token akışı)
- Admin web paneli için ek hizmetler/tatiller/bakiye yönetimi UI (backend hazır, frontend eklenecek)

## Notes
- "shadow*" deprecated uyarıları render etkilemiyor, üretimde boxShadow'a göçecek.
- Bot offline log'u normaldir, mock fallback ile uygulama tam çalışır.
