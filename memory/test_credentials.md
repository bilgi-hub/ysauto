# Test Credentials

## Admin
- Username: admin
- Password: admin1234
- Endpoint: POST /api/auth/admin/login

## Customer — Klasik TC ile
- Ad: Ahmet
- Soyad: Yılmaz
- TC: 12345678901
- Endpoint: POST /api/auth/customer/login

## Customer — Telefon ile (bot_oto kaydı)
- Telefon: +905550164165
- Müşteri: İBRAHİM YILDIZTAN (bot_oto)
- Endpoint: POST /api/auth/customer/login  body: {"telefon": "+905550164165"}

- Telefon: +905437716475
- Müşteri: YUSUF KARAGÖZ (bot_oto)

## Bot
- URL: http://162.19.245.185:8081
- Bearer Token: 913dde91c73eee7797c4fb3d8acf0e4a6d8178889cb7931e5b36274663834693
- Endpoints: GET /vehicles, GET /health
- Beklenen (henüz yok): POST /motor-blokaj body: {plaka, aktif}
