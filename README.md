# YS Auto - Araç Kiralama Uygulaması

## Kurulum

### Backend (FastAPI + MongoDB)
```bash
cd backend
pip install -r requirements.txt
# .env'i MONGO_URL, EMERGENT_LLM_KEY, BOT_API_URL, BOT_BEARER_TOKEN ile doldurun
uvicorn server:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend (Expo)
```bash
cd frontend
yarn install
# .env'de EXPO_PUBLIC_BACKEND_URL'i backend URL'inize ayarlayın
yarn start
```

## Railway'e Deploy
- Backend: bu klasördeki `backend/` GitHub repo'sundan deploy edin
- MongoDB: Atlas (ücretsiz) veya Railway plugin
- Env variables: backend/.env içeriğini Railway > Variables'a ekleyin
- Bot: kendi VPS'inizde çalışıyor (http://162.19.245.185:8081)

## Admin Giriş
- Ad: Yusuf | Soyad: Sünger | TC: 17695979542

## Önemli Endpoint'ler
- POST /api/auth/login (birleşik admin+müşteri)
- POST /api/admin/vehicles/{vid}/motor-blokaj
- Bot-sync arkaplanda 30sn periyotla çalışır
