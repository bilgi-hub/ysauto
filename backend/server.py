"""
YS Auto - Backend (v2)
Features:
- Customer auth (TC + Ad + Soyad), Admin auth
- Wallet system (bakiye + transactions, kart/havale yükleme)
- Vehicles + reservations with deposit deduction from wallet
- Tatil günleri (Pazar default + admin yönetir) + mesai saatleri
- 2+ gün indirim (% admin tarafından ayarlanır)
- Ek hizmetler (günlük/tek_seferlik) - admin CRUD
- KM limit + aşım fiyatı (km başına ₺)
- Provizyon sistemi (kapanışta kullanılır/iade)
- Manuel rezervasyon (admin) + iskonto
- Bot KM proxy (rentacarss bot)
- Notifications
"""
import os
import re
import math
import hashlib
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from typing import List, Optional

import bcrypt
import httpx
import jwt as pyjwt
import json as _json
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]
JWT_SECRET = os.environ.get("JWT_SECRET", "ys-auto-secret-2026-change-prod")
JWT_ALG = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24 * 30

# ==================== MULTI-TENANT ====================
# Mevcut firma (YS Auto) için default tenant_id. Yeni firmalar eklendikçe
# her firmaya kendi tenant_id'si verilecek. Süper admin tüm tenant'ları görebilir.
DEFAULT_TENANT_ID = os.environ.get("DEFAULT_TENANT_ID", "ys_auto")
# Süper admin TC listesi (platform sahibi — tüm tenant'ları yönetebilir)
SUPER_ADMIN_TCS = set(filter(None, (
    os.environ.get("SUPER_ADMIN_TCS", "17695979542")  # Yusuf Sünger
).split(",")))

BOT_API_URL = os.environ.get("BOT_API_URL", "http://89.252.179.135:8081")
BOT_BEARER = os.environ.get(
    "BOT_BEARER_TOKEN",
    "913dde91c73eee7797c4fb3d8acf0e4a6d8178889cb7931e5b36274663834693",
)

client = AsyncIOMotorClient(MONGO_URL)
db = client[DB_NAME]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="YS Auto API")
api = APIRouter(prefix="/api")
security = HTTPBearer()

# ==================== MODELS ====================
class CustomerLoginIn(BaseModel):
    ad: Optional[str] = None
    soyad: Optional[str] = None
    tc: Optional[str] = None
    telefon: Optional[str] = None  # TC yerine telefonla da giriş yapılabilir

class AdminLoginIn(BaseModel):
    kullanici_adi: Optional[str] = None
    sifre: Optional[str] = None
    # Yeni: ad/soyad/tc ile giriş
    ad: Optional[str] = None
    soyad: Optional[str] = None
    tc: Optional[str] = None

class TokenOut(BaseModel):
    token: str
    role: str
    user: dict

class CustomerCreate(BaseModel):
    ad: str
    soyad: str
    tc: str
    telefon: str
    email: Optional[str] = None
    notlar: Optional[str] = None
    adres: Optional[str] = None
    tip: Optional[str] = "bireysel"  # 'bireysel' | 'kurumsal'
    firma_adi: Optional[str] = None
    vergi_no: Optional[str] = None
    yetkili: Optional[str] = None  # kurumsal yetkilinin adı

class CustomerUpdate(BaseModel):
    ad: Optional[str] = None
    soyad: Optional[str] = None
    tc: Optional[str] = None
    telefon: Optional[str] = None
    email: Optional[str] = None
    notlar: Optional[str] = None
    adres: Optional[str] = None
    tip: Optional[str] = None
    firma_adi: Optional[str] = None
    vergi_no: Optional[str] = None
    yetkili: Optional[str] = None
    blocked: Optional[bool] = None
    block_reason: Optional[str] = None

class KmKademe(BaseModel):
    """Aracın gün sayısına göre günlük KM limiti (range-tabanlı).
    Örn: {min_gun:1, max_gun:7, gunluk_km:250} → 1-7 gün arası 250 km/gün
         {min_gun:8, max_gun:30, gunluk_km:120} → 8-30 gün arası 120 km/gün
         {min_gun:31, max_gun:None, gunluk_km:80} → 31+ gün 80 km/gün
    """
    min_gun: int
    max_gun: Optional[int] = None
    gunluk_km: int

class GunlukFiyatKademe(BaseModel):
    """Aracın kira süresine göre değişen günlük fiyatı."""
    min_gun: int
    max_gun: Optional[int] = None
    gunluk_fiyat: float

class KmAsimKademe(BaseModel):
    """Aracın kira süresine göre değişen km aşım ücreti.
    Örn: {min_gun:1, max_gun:7, km_asim_fiyat:12} → 1-7 gün için 12₺/km
         {min_gun:8, max_gun:None, km_asim_fiyat:10} → 8+ gün için 10₺/km
    """
    min_gun: int
    max_gun: Optional[int] = None
    km_asim_fiyat: float

class KmHacimKademe(BaseModel):
    """Ek KM satın alma hacim indirim kademesi (sabit tutar)."""
    min_km: int
    indirim_tutar: float

class VehicleCreate(BaseModel):
    plaka: str
    marka: str
    model: str
    yil: int
    renk: str
    vites: str = "Otomatik"
    yakit: str = "Benzin"
    foto_url: str = ""
    fotograflar: List[str] = []  # Çoklu foto (base64 data URL veya http URL); ilk öğe kapak — foto_url geriye uyumluluk için
    gunluk_fiyat: float
    gunluk_km: int = 250
    aciklama: str = ""
    manuel_durum: Optional[str] = None
    ekstra_ozellikler: List[str] = []  # ["7 Koltuk", "Yüksek Performans" vb]
    gunluk_fiyat_kademeleri: List[GunlukFiyatKademe] = []  # Süreye göre değişen günlük fiyat — boşsa gunluk_fiyat kullanılır
    km_kademeleri: List[KmKademe] = []  # Dinamik günlük KM limiti (range) — boşsa gunluk_km kullanılır
    km_asim_fiyat: Optional[float] = None  # Araç-bazlı km aşım ücreti (₺/km) — varsayılan, kademe yoksa kullanılır
    km_asim_kademeleri: List[KmAsimKademe] = []  # Süreye göre değişen km aşım ücreti — varsa öncelikli
    # Bakım & Yasal Takip
    sigorta_bitis: Optional[str] = None  # ISO date (YYYY-MM-DD) — Trafik sigortası bitiş
    kasko_bitis: Optional[str] = None    # ISO date — Kasko bitiş
    muayene_bitis: Optional[str] = None  # ISO date — Muayene/Fenni muayene bitiş
    sonraki_yag_bakim_km: Optional[int] = None  # Sonraki yağ bakım odometre değeri (mutlak KM)
    mevcut_km: Optional[int] = None       # Aracın anlık odometresi (manuel veya GPS bot)
    siralama: int = 0  # Görüntüleme sıralaması (küçük olan üstte)
    # Konsinye (consignment)
    konsinye: bool = False
    konsinye_sahibi_id: Optional[str] = None  # konsinyatorler.id
    konsinye_pay_yuzde: Optional[float] = None  # Sahibin payı (0-100), None ise 70 default

class VehicleUpdate(BaseModel):
    plaka: Optional[str] = None
    marka: Optional[str] = None
    model: Optional[str] = None
    yil: Optional[int] = None
    renk: Optional[str] = None
    vites: Optional[str] = None
    yakit: Optional[str] = None
    foto_url: Optional[str] = None
    fotograflar: Optional[List[str]] = None
    gunluk_fiyat: Optional[float] = None
    gunluk_km: Optional[int] = None
    aciklama: Optional[str] = None
    manuel_durum: Optional[str] = None
    ekstra_ozellikler: Optional[List[str]] = None
    gunluk_fiyat_kademeleri: Optional[List[GunlukFiyatKademe]] = None
    km_kademeleri: Optional[List[KmKademe]] = None
    km_asim_fiyat: Optional[float] = None
    km_asim_kademeleri: Optional[List[KmAsimKademe]] = None
    sigorta_bitis: Optional[str] = None
    kasko_bitis: Optional[str] = None
    muayene_bitis: Optional[str] = None
    sonraki_yag_bakim_km: Optional[int] = None
    mevcut_km: Optional[int] = None
    siralama: Optional[int] = None
    konsinye: Optional[bool] = None
    konsinye_sahibi_id: Optional[str] = None
    konsinye_pay_yuzde: Optional[float] = None

# ==================== KONSİNYE (Consignment) Modelleri ====================
class KonsinyatorIn(BaseModel):
    ad: str
    soyad: str
    tc: str
    telefon: Optional[str] = None
    email: Optional[str] = None
    iban: Optional[str] = None
    banka_hesap_sahibi: Optional[str] = None
    varsayilan_pay_yuzde: float = 70.0
    notlar: Optional[str] = None

class KonsinyatorUpdate(BaseModel):
    ad: Optional[str] = None
    soyad: Optional[str] = None
    tc: Optional[str] = None
    telefon: Optional[str] = None
    email: Optional[str] = None
    iban: Optional[str] = None
    banka_hesap_sahibi: Optional[str] = None
    varsayilan_pay_yuzde: Optional[float] = None
    notlar: Optional[str] = None
    aktif: Optional[bool] = None

class BakimGiderIn(BaseModel):
    vehicle_id: str
    tutar: float
    aciklama: str
    tarih: str  # ISO YYYY-MM-DD

class KonsinyeOdemeIn(BaseModel):
    konsinye_sahibi_id: str
    donem: str  # YYYY-MM
    tutar: float
    odeme_tarihi: Optional[str] = None  # ISO
    aciklama: Optional[str] = None

class ServiceSelection(BaseModel):
    service_id: str
    adet: int = 1

class ReservationCreate(BaseModel):
    vehicle_id: str
    baslangic_tarihi: str
    bitis_tarihi: str
    telefon: str
    secilen_hizmetler: List[ServiceSelection] = []
    odeme_tipi: Optional[str] = "auto"  # "full" | "deposit" | "auto" (default: bakiyeye göre otomatik karar)

class ReservationExtend(BaseModel):
    yeni_bitis_tarihi: str
    secilen_hizmetler: List[ServiceSelection] = []  # (legacy) Uzatma için ek hizmetler — UI artık göstermiyor
    ek_km: int = 0  # Müşterinin uzatma sırasında satın aldığı ek km miktarı

class ManualReservationCreate(BaseModel):
    customer_id: str
    vehicle_id: str
    baslangic_tarihi: str
    bitis_tarihi: str
    telefon: str
    iskonto_yuzde: float = 0.0
    secilen_hizmetler: List[ServiceSelection] = []
    odeme_durumu: str = "beklemede"  # beklemede / on_odeme_alindi / tam_odeme_alindi
    # Admin overrides (opsiyonel)
    toplam_tutar_override: Optional[float] = None  # Manuel toplam tutar (₺) — None ise otomatik hesaplanır
    paket_km_override: Optional[int] = None  # Manuel paket KM — None ise araç ayarından hesaplanır
    odenen_ucret: float = 0.0  # Peşin alınan miktar (₺)
    # 📏 Ek KM Satışı (rezervasyon oluştururken — opsiyonel)
    ek_km: Optional[int] = Field(default=None, ge=0, description="Başlangıçta satılan ek KM")
    ek_km_manuel_tutar: Optional[float] = Field(default=None, ge=0, description="Ek KM manuel fiyat (boş ise otomatik)")
    ek_km_odeme_alindi: bool = True  # Peşin mi alındı, yoksa kalan'a eklensin mi?

class NotificationCreate(BaseModel):
    baslik: str
    mesaj: str
    hedef_type: str
    hedef_customer_ids: List[str] = []

class ReviewCreate(BaseModel):
    reservation_id: str
    arac_puan: int  # 1-5
    servis_puan: int  # 1-5
    yorum: str = ""  # opsiyonel

class ReviewAdminUpdate(BaseModel):
    durum: Optional[str] = None  # 'beklemede' | 'onaylandi' | 'gizli'
    admin_cevap: Optional[str] = None

class SettingsUpdate(BaseModel):
    iban: Optional[str] = None
    banka: Optional[str] = None
    hesap_sahibi: Optional[str] = None
    iletisim_telefon: Optional[str] = None
    iletisim_email: Optional[str] = None
    iletisim_adres: Optional[str] = None
    whatsapp: Optional[str] = None
    mesai_baslangic: Optional[str] = None  # "09:00"
    mesai_bitis: Optional[str] = None  # "18:00"
    tatil_haftaici_gunler: Optional[List[int]] = None  # [6] -> Sunday (0=Mon..6=Sun)
    indirim_min_gun: Optional[int] = None  # 2 — fallback if vehicle has no sure_indirim_kademeleri
    indirim_yuzde: Optional[float] = None  # 10.0 — fallback if vehicle has no sure_indirim_kademeleri
    km_asim_fiyat: Optional[float] = None  # ₺/km
    km_hacim_indirim_kademeleri: Optional[List[KmHacimKademe]] = None  # Ek KM hacim indirimi kademeleri
    sirket_adi: Optional[str] = None
    kart_kdv_yuzde: Optional[float] = None  # KDV % for card payments (default 20)
    kart_komisyon_yuzde: Optional[float] = None  # Commission % for card payments (default 5)

class WalletTopupIn(BaseModel):
    tutar: float
    yontem: str  # 'kart' | 'havale'
    kart_no: Optional[str] = None
    kart_sahibi: Optional[str] = None
    son_kullanma: Optional[str] = None
    cvc: Optional[str] = None
    havale_referans: Optional[str] = None
    dekont_base64: Optional[str] = None  # Havale için zorunlu — dekont fotoğrafı (data URI veya raw base64)

class ServiceCreate(BaseModel):
    isim: str
    aciklama: str = ""
    fiyat: float
    tip: str  # 'gunluk' | 'tek_seferlik'
    icon: str = "pricetag-outline"
    aktif: bool = True
    zorunlu: bool = False
    arac_ids: List[str] = []  # Boş = tüm araçlar; doluysa sadece bu araçlara uygulanır
    siralama: int = 0

class ServiceUpdate(BaseModel):
    isim: Optional[str] = None
    aciklama: Optional[str] = None
    fiyat: Optional[float] = None
    tip: Optional[str] = None
    icon: Optional[str] = None
    aktif: Optional[bool] = None
    zorunlu: Optional[bool] = None
    arac_ids: Optional[List[str]] = None
    siralama: Optional[int] = None

class HolidayCreate(BaseModel):
    tarih: str  # YYYY-MM-DD
    aciklama: str

class ProvisionCreate(BaseModel):
    reservation_id: str
    tutar: float
    aciklama: str

class PaymentConfirm(BaseModel):
    referans_no: Optional[str] = None
    notlar: Optional[str] = None

# ==================== HELPERS ====================
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def parse_iso(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail=f"Geçersiz tarih formatı: {s}")

def hash_pw(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()

def verify_pw(p: str, h: str) -> bool:
    try:
        return bcrypt.checkpw(p.encode(), h.encode())
    except Exception:
        return False

def make_token(user_id: str, role: str, tenant_id: Optional[str] = None, is_super: bool = False) -> str:
    """JWT token. tenant_id ve is_super (süper admin) bilgilerini taşır.
    Geriye dönük uyumluluk: çağrıya tenant_id verilmezse DEFAULT_TENANT_ID kullanılır."""
    return pyjwt.encode({
        "sub": user_id, "role": role,
        "tenant_id": tenant_id or DEFAULT_TENANT_ID,
        "is_super": bool(is_super),
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }, JWT_SECRET, algorithm=JWT_ALG)

def normalize_tc(tc: str) -> str:
    return re.sub(r"\D", "", tc or "")[:11]

def normalize_name(s: str) -> str:
    """Case-insensitive ad/soyad karşılaştırması için normalize eder.
    Türkçe I/İ/ı/i sorununu çözer — "İBRAHİM", "ibrahim", "İbrahim" hepsi eşleşir.
    Diğer Türkçe karakterler (ü, ö, ş, ç, ğ) standart lower() ile zaten doğru çalışır.
    """
    if not s:
        return ""
    s = s.strip()
    # Tüm i-varyantlarını tek bir 'i'ye indir (Türkçe locale farkını yok say)
    s = s.replace("İ", "i").replace("I", "i").replace("ı", "i")
    return s.lower()

def normalize_phone(p: str) -> str:
    """Türkiye telefon numarasını standart 10 haneye normalize eder.
    +90 5xx xxx xx xx, 0 5xx xxx xx xx, 5xx xxx xx xx → 5xxxxxxxxx (10 hane)."""
    if not p:
        return ""
    digits = re.sub(r"\D", "", p)
    if digits.startswith("90") and len(digits) >= 12:
        digits = digits[2:]
    if digits.startswith("0") and len(digits) >= 11:
        digits = digits[1:]
    return digits[:10]

def hhmm_to_tuple(s: str) -> tuple:
    """'09:00' -> (9, 0)"""
    try:
        h, m = s.split(":")
        return int(h), int(m)
    except Exception:
        return 9, 0

async def get_settings() -> dict:
    s = await db.settings.find_one({"key": "company"}, {"_id": 0})
    return s or {}

# ==================== AI DEKONT DOĞRULAMA ====================
EMERGENT_LLM_KEY = os.getenv("EMERGENT_LLM_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Confidence >= bu eşik => otomatik onay, altı => admin manuel onay
DEKONT_AUTO_APPROVE_CONFIDENCE = float(os.getenv("DEKONT_AUTO_APPROVE_CONFIDENCE", "0.85"))

def _norm_iban(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", "", str(s)).upper().replace("İ", "I").replace("Ş", "S").replace("Ğ", "G").replace("Ç", "C").replace("Ö", "O").replace("Ü", "U")

def _norm_name(s: Optional[str]) -> str:
    if not s:
        return ""
    s = str(s).upper().strip()
    s = s.replace("İ", "I").replace("Ş", "S").replace("Ğ", "G").replace("Ç", "C").replace("Ö", "O").replace("Ü", "U")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

async def validate_dekont_with_ai(
    foto_base64: str,
    expected_iban: str,
    expected_recipient_name: str,
    expected_sender_name: str,
    expected_amount: float,
) -> dict:
    """
    Dekont fotoğrafını LLM ile analiz edip beklenen değerlerle karşılaştırır.
    Tüm 5 alan tam eşleşmeli: tarih (1 gün tolerans), tutar, IBAN, alıcı adı, gönderici adı.
    Returns: {
      "valid": bool,                # tüm alanlar eşleşti mi
      "fields": {tarih, tutar, alici_iban, alici_adi, gonderici_adi: {extracted, match, ...}},
      "confidence": float,          # 0..1
      "reasons": [str]              # uyumsuzluklar listesi
    }
    """
    if not GEMINI_API_KEY:
        return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": ["AI servisi yapılandırılmamış (GEMINI_API_KEY tanımlı değil)"]}

    # data: prefix'i kaldır + mime type yakala
    raw = foto_base64.strip()
    mime_type = "image/jpeg"
    if raw.startswith("data:"):
        # data:image/png;base64,XXXX
        try:
            header, raw = raw.split(",", 1)
            m_mime = re.search(r"data:([^;]+);base64", header)
            if m_mime:
                mime_type = m_mime.group(1)
        except Exception:
            comma = raw.find(",")
            if comma > 0:
                raw = raw[comma + 1:]

    # Sistem promptu
    sys_msg = (
        "Sen bir banka dekont/transfer makbuzu analiz uzmanısın. Sana verilen Türkçe banka dekontu "
        "veya havale/EFT makbuzu fotoğrafından şu alanları çıkar ve SADECE JSON formatında dön:\n"
        "{\n"
        "  \"tarih\": \"YYYY-MM-DD\" veya null,\n"
        "  \"tutar\": ondalıklı sayı (örn 1500.00) veya null,\n"
        "  \"alici_iban\": \"TRxxxxxxxxxxxxxxxxxxxxxxxx\" (boşluksuz) veya null,\n"
        "  \"alici_adi\": \"AD SOYAD veya FIRMA ADI\" veya null,\n"
        "  \"gonderici_adi\": \"AD SOYAD\" veya null,\n"
        "  \"confidence\": 0..1 arası bir değer (alanları ne kadar net okuyabildiğin),\n"
        "  \"is_valid_receipt\": true/false (gerçek bir banka dekontu mu?)\n"
        "}\n\n"
        "Türkçe karakterleri ASCII karşılığına dönüştür (Ş→S, İ→I, Ğ→G, Ç→C, Ö→O, Ü→U).\n"
        "Sadece JSON dön, başka açıklama yapma."
    )

    user_text = (
        "Bu banka dekontunu analiz et ve istenen JSON'u dön. "
        f"Beklenen alıcı IBAN: {expected_iban or '(belirtilmemiş)'}\n"
        f"Beklenen alıcı: {expected_recipient_name or '(belirtilmemiş)'}\n"
        f"Beklenen gönderici: {expected_sender_name or '(belirtilmemiş)'}\n"
        f"Beklenen tutar: {expected_amount} TL"
    )

    gemini_url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": sys_msg}]},
        "contents": [{
            "role": "user",
            "parts": [
                {"text": user_text},
                {"inline_data": {"mime_type": mime_type, "data": raw}},
            ],
        }],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as cli:
            r = await cli.post(gemini_url, json=payload)
            if r.status_code != 200:
                err_txt = r.text[:300]
                logger.error(f"Gemini API hata {r.status_code}: {err_txt}")
                return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": [f"Gemini API hatası (HTTP {r.status_code})"]}
            data = r.json()
    except Exception as e:
        logger.error(f"Gemini API isteği başarısız: {e}")
        return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": [f"AI bağlantı hatası: {e}"]}

    # Gemini response'tan metni çek
    try:
        ai_resp = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        logger.error(f"Gemini response parse hatası: {_json.dumps(data)[:300]}")
        return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": ["Gemini cevabı beklenen formatta değil"]}

    # JSON extract
    raw_txt = ai_resp.strip() if isinstance(ai_resp, str) else str(ai_resp)
    raw_txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_txt.strip(), flags=re.MULTILINE)
    try:
        parsed = _json.loads(raw_txt)
    except Exception:
        m = re.search(r"\{.*\}", raw_txt, re.DOTALL)
        if not m:
            return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": [f"AI çıktısı JSON değil: {raw_txt[:200]}"]}
        try:
            parsed = _json.loads(m.group(0))
        except Exception:
            return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": ["AI JSON parse hatası"]}

    confidence = float(parsed.get("confidence", 0) or 0)
    is_valid_receipt = bool(parsed.get("is_valid_receipt", True))

    extracted = {
        "tarih": parsed.get("tarih"),
        "tutar": parsed.get("tutar"),
        "alici_iban": parsed.get("alici_iban"),
        "alici_adi": parsed.get("alici_adi"),
        "gonderici_adi": parsed.get("gonderici_adi"),
    }

    # ==== Karşılaştırma ====
    reasons = []
    fields_report = {}

    if not is_valid_receipt:
        reasons.append("Yüklenen fotoğraf banka dekontu olarak tanımlanamadı")

    # Tarih kontrolü (1 gün tolerans)
    today = datetime.now(timezone.utc).date()
    tarih_ok = False
    try:
        if extracted["tarih"]:
            t = datetime.strptime(extracted["tarih"], "%Y-%m-%d").date()
            diff = abs((today - t).days)
            tarih_ok = diff <= 1
            if not tarih_ok:
                reasons.append(f"Dekont tarihi bugünden {diff} gün uzakta (max 1 gün)")
        else:
            reasons.append("Dekontta tarih okunamadı")
    except Exception:
        reasons.append("Dekont tarihi formatı geçersiz")
    fields_report["tarih"] = {"extracted": extracted["tarih"], "match": tarih_ok}

    # Tutar kontrolü (kuruş hassasiyeti)
    tutar_ok = False
    try:
        if extracted["tutar"] is not None:
            ext_tutar = float(extracted["tutar"])
            tutar_ok = abs(ext_tutar - float(expected_amount)) < 0.01
            if not tutar_ok:
                reasons.append(f"Tutar uyuşmuyor: dekont={ext_tutar:.2f}₺, beklenen={expected_amount:.2f}₺")
        else:
            reasons.append("Dekontta tutar okunamadı")
    except Exception:
        reasons.append("Dekont tutarı sayısal değil")
    fields_report["tutar"] = {"extracted": extracted["tutar"], "expected": expected_amount, "match": tutar_ok}

    # IBAN kontrolü
    exp_iban = _norm_iban(expected_iban)
    ext_iban = _norm_iban(extracted["alici_iban"])
    iban_ok = bool(exp_iban) and bool(ext_iban) and exp_iban == ext_iban
    if not iban_ok:
        if not exp_iban:
            reasons.append("Sistemde alıcı IBAN tanımlı değil")
        elif not ext_iban:
            reasons.append("Dekontta alıcı IBAN okunamadı")
        else:
            reasons.append(f"IBAN uyuşmuyor: dekont={ext_iban[-6:]}…, beklenen={exp_iban[-6:]}…")
    fields_report["alici_iban"] = {"extracted": ext_iban, "expected": exp_iban, "match": iban_ok}

    # Alıcı adı kontrolü
    exp_alici = _norm_name(expected_recipient_name)
    ext_alici = _norm_name(extracted["alici_adi"])
    alici_ok = bool(exp_alici) and bool(ext_alici) and (exp_alici in ext_alici or ext_alici in exp_alici)
    if not alici_ok:
        if not exp_alici:
            reasons.append("Sistemde alıcı adı tanımlı değil")
        elif not ext_alici:
            reasons.append("Dekontta alıcı adı okunamadı")
        else:
            reasons.append(f"Alıcı adı uyuşmuyor: dekont='{ext_alici}', beklenen='{exp_alici}'")
    fields_report["alici_adi"] = {"extracted": ext_alici, "expected": exp_alici, "match": alici_ok}

    # Gönderici (müşteri) adı kontrolü
    exp_gonderen = _norm_name(expected_sender_name)
    ext_gonderen = _norm_name(extracted["gonderici_adi"])
    gonderen_ok = bool(exp_gonderen) and bool(ext_gonderen) and (exp_gonderen in ext_gonderen or ext_gonderen in exp_gonderen)
    if not gonderen_ok:
        if not exp_gonderen:
            reasons.append("Müşteri adı sistemde yok")
        elif not ext_gonderen:
            reasons.append("Dekontta gönderici okunamadı")
        else:
            reasons.append(f"Gönderici uyuşmuyor: dekont='{ext_gonderen}', müşteri='{exp_gonderen}'")
    fields_report["gonderici_adi"] = {"extracted": ext_gonderen, "expected": exp_gonderen, "match": gonderen_ok}

    # Tüm 5 alan eşleşmesi (yardımcı bilgi olarak hesaplanır)
    all_fields_match = (
        is_valid_receipt and tarih_ok and tutar_ok and iban_ok and alici_ok and gonderen_ok
    )
    # Otomatik onay kuralı (kullanıcı isteği):
    #   - confidence > DEKONT_AUTO_APPROVE_CONFIDENCE (default 0.85) VE
    #   - is_valid_receipt = true VE
    #   - tutar/IBAN/alıcı eşleşiyor (tarih ve gönderici uyumu confidence içinde kapsanır)
    # Tüm eşleşme şartını da arıyoruz ki yanlış dekont (örn. başkasının kestiği) otomatik onaylanmasın.
    valid = bool(
        all_fields_match
        and confidence > DEKONT_AUTO_APPROVE_CONFIDENCE
    )
    if not valid:
        if not is_valid_receipt:
            pass  # already added above
        elif confidence <= DEKONT_AUTO_APPROVE_CONFIDENCE:
            reasons.append(
                f"AI güven skoru otomatik onay eşiğinin altında ({confidence:.2f} ≤ {DEKONT_AUTO_APPROVE_CONFIDENCE:.2f}) — admin onayı bekleniyor"
            )

    return {
        "valid": valid,
        "fields": fields_report,
        "confidence": confidence,
        "is_valid_receipt": is_valid_receipt,
        "all_fields_match": all_fields_match,
        "auto_approve_threshold": DEKONT_AUTO_APPROVE_CONFIDENCE,
        "reasons": reasons,
    }


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = pyjwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Oturum süresi dolmuş, tekrar giriş yapın")
    role = payload.get("role")
    uid = payload.get("sub")
    # JWT'den tenant context'i al (eski token'larda yok → default'a düş)
    jwt_tenant_id = payload.get("tenant_id") or DEFAULT_TENANT_ID
    jwt_is_super = bool(payload.get("is_super", False))
    if role == "customer":
        c = await db.customers.find_one({"id": uid}, {"_id": 0})
        if not c:
            raise HTTPException(401, "Kullanıcı bulunamadı")
        if c.get("blocked"):
            raise HTTPException(403, c.get("block_reason") or "Hesabınız askıya alınmış. Yetkili ile iletişime geçin.")
        # Doc'taki tenant_id öncelikli, yoksa JWT'den
        tid = c.get("tenant_id") or jwt_tenant_id
        return {"role": "customer", "tenant_id": tid, "is_super": False, **c}
    elif role == "admin":
        a = await db.admins.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
        if not a:
            raise HTTPException(401, "Yönetici bulunamadı")
        tid = a.get("tenant_id") or jwt_tenant_id
        # is_super önceliği: admin doc'taki flag > JWT > SUPER_ADMIN_TCS env
        is_super = bool(a.get("is_super")) or jwt_is_super or (a.get("tc_norm") in SUPER_ADMIN_TCS)
        return {"role": "admin", "tenant_id": tid, "is_super": is_super, **a}
    elif role == "konsinye":
        k = await db.konsinyatorler.find_one({"id": uid}, {"_id": 0})
        if not k:
            raise HTTPException(401, "Konsinye kullanıcı bulunamadı")
        if not k.get("aktif", True):
            raise HTTPException(403, "Hesabınız aktif değil. Yetkili ile iletişime geçin.")
        tid = k.get("tenant_id") or jwt_tenant_id
        return {"role": "konsinye", "tenant_id": tid, "is_super": False, **k}
    raise HTTPException(401, "Geçersiz oturum")

# ==================== Multi-Tenant Helpers ====================
def tenant_id_of(user: dict) -> str:
    """Kullanıcının ait olduğu tenant_id'yi döner. Yoksa DEFAULT_TENANT_ID."""
    return (user.get("tenant_id") if user else None) or DEFAULT_TENANT_ID

def is_super_admin(user: dict) -> bool:
    """Süper admin (platform sahibi) mi?"""
    return bool(user and user.get("is_super"))

def tenant_filter(user: dict, override_tenant: Optional[str] = None) -> dict:
    """Mongo find/count query'lerine genişletilecek filtre.
    Süper admin: tüm tenant'lar (filtre yok) — `override_tenant` verilirse o tenant'a kilitlenir.
    Normal kullanıcı: kendi tenant'ı.
    Geriye dönük uyumluluk: tenant_id alanı olmayan eski dokümanlar default tenant'a aittir.
    """
    if user and user.get("is_super"):
        if override_tenant:
            return {"tenant_id": override_tenant}
        return {}  # Süper admin tüm tenant'ları görür
    tid = tenant_id_of(user)
    if tid == DEFAULT_TENANT_ID:
        # Default tenant: tenant_id alanı olmayan eski dokümanlar da bu tenant'a aittir
        return {"$or": [{"tenant_id": tid}, {"tenant_id": {"$exists": False}}]}
    return {"tenant_id": tid}

def tenant_stamp(user: dict, override_tenant: Optional[str] = None) -> dict:
    """Yeni insert/update için tenant_id alanını ekler.
    Kullanım: doc = {"id": ..., **tenant_stamp(user)}
    Süper admin için override_tenant ile farklı tenant'a yazılabilir."""
    if user and user.get("is_super") and override_tenant:
        return {"tenant_id": override_tenant}
    return {"tenant_id": tenant_id_of(user)}

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Bu işlem için yönetici yetkisi gerekli")
    return user

async def require_customer(user: dict = Depends(get_current_user)) -> dict:
    # Admin de müşteri ekranını görebilsin (önizleme için)
    if user["role"] not in ("customer", "admin"):
        raise HTTPException(403, "Bu işlem müşteri girişi gerektirir")
    return user

# ==================== Calendar / Business Hours ====================
async def is_holiday(d: datetime) -> Optional[str]:
    """Returns reason if it's a holiday, else None."""
    s = await get_settings()
    weekday = d.weekday()  # 0=Mon..6=Sun
    blocked = s.get("tatil_haftaici_gunler") or [6]
    if weekday in blocked:
        names = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
        return f"{names[weekday]} günleri tatil"
    # Specific holiday dates
    iso_date = d.strftime("%Y-%m-%d")
    h = await db.holidays.find_one({"tarih": iso_date}, {"_id": 0})
    if h:
        return f"Tatil: {h['aciklama']}"
    return None

async def is_within_business_hours(d: datetime) -> Optional[str]:
    """Returns reason if outside business hours, else None."""
    s = await get_settings()
    sh, sm = hhmm_to_tuple(s.get("mesai_baslangic", "09:00"))
    eh, em = hhmm_to_tuple(s.get("mesai_bitis", "18:00"))
    # Convert to UTC+3 (Turkey) - we assume admin sets local time
    # For simplicity use date.hour/minute as is (assume input is already TR local)
    # In real setup we'd track timezone, but for MVP we'll trust input.
    # Convert UTC to local TR time:
    tr_local = d + timedelta(hours=3)
    h, m = tr_local.hour, tr_local.minute
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    cur_min = h * 60 + m
    if cur_min < start_min or cur_min > end_min:
        return f"İşlem {sh:02d}:{sm:02d} - {eh:02d}:{em:02d} arasında olmalı"
    return None

async def validate_pickup_dropoff(start: datetime, end: datetime):
    """Raise HTTPException if any restriction violated."""
    # Holidays
    h = await is_holiday(start)
    if h:
        raise HTTPException(400, f"Teslim alış tarihi: {h}. Lütfen başka bir gün seçin.")
    h = await is_holiday(end)
    if h:
        raise HTTPException(400, f"İade tarihi: {h}. Lütfen başka bir gün seçin.")
    # Business hours
    bh = await is_within_business_hours(start)
    if bh:
        raise HTTPException(400, f"Teslim alış saati: {bh}")
    bh = await is_within_business_hours(end)
    if bh:
        raise HTTPException(400, f"İade saati: {bh}")

# ==================== Pricing ====================
def calc_days(bas: datetime, bit: datetime) -> int:
    delta = bit - bas
    days = delta.days + (1 if delta.seconds > 0 else 0)
    return max(1, days)

def daily_km_for(vehicle: dict, days: int) -> int:
    """Return the daily KM allowance for the vehicle given total rental days (range-based).
    Bracket: {min_gun, max_gun(None=∞), gunluk_km}. Falls back to vehicle.gunluk_km.
    NOT: 'Display amaçlı' — yeni mantıkta paket_km hesabı için paket_km_for kullanılır (segmentli).
    """
    kademeler = vehicle.get("km_kademeleri") or []
    fallback = int(vehicle.get("gunluk_km", 250) or 250)
    if not kademeler:
        return fallback
    for k in sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0)):
        try:
            mg = int(k.get("min_gun", 0) or 0)
            mxg = k.get("max_gun")
            mxg_n = int(mxg) if mxg is not None else 10**9
            kmd = int(k.get("gunluk_km", fallback) or fallback)
        except Exception:
            continue
        if mg <= days <= mxg_n:
            return max(0, kmd)
    return fallback

def paket_km_for(vehicle: dict, days: int) -> int:
    """Segmented/kümülatif paket KM hesabı.
    Her gün için ait olduğu kademenin günlük km'sini toplar.
    Örn: 1-7 → 250, 8+ → 120. 10 gün için = 7×250 + 3×120 = 1750 + 360 = 2110 km.
    """
    kademeler = vehicle.get("km_kademeleri") or []
    fallback = int(vehicle.get("gunluk_km", 250) or 250)
    if days <= 0:
        return 0
    if not kademeler:
        return fallback * days
    # Her gün için (1..N) uygun kademeyi bul, kümüle et
    total = 0
    sorted_kademeler = sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0))
    for d in range(1, days + 1):
        kmd = fallback
        for k in sorted_kademeler:
            try:
                mg = int(k.get("min_gun", 0) or 0)
                mxg = k.get("max_gun")
                mxg_n = int(mxg) if mxg is not None else 10**9
                if mg <= d <= mxg_n:
                    kmd = max(0, int(k.get("gunluk_km", fallback) or fallback))
                    break
            except Exception:
                continue
        total += kmd
    return total

def km_asim_for(vehicle: dict, settings: dict, days: Optional[int] = None) -> float:
    """Return per-km overage price.
    Priority:
      1. If days provided AND vehicle has km_asim_kademeleri matching → bracket price
      2. Vehicle's km_asim_fiyat (varsayılan)
      3. Settings.km_asim_fiyat fallback (legacy)
    """
    kademeler = vehicle.get("km_asim_kademeleri") or []
    if days is not None and kademeler:
        for k in sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0)):
            try:
                mg = int(k.get("min_gun", 0) or 0)
                mxg = k.get("max_gun")
                mxg_n = int(mxg) if mxg is not None else 10**9
                price = float(k.get("km_asim_fiyat", 0) or 0)
            except Exception:
                continue
            if mg <= days <= mxg_n:
                return price
    v_val = vehicle.get("km_asim_fiyat")
    if v_val is not None:
        try:
            return float(v_val)
        except Exception:
            pass
    return float(settings.get("km_asim_fiyat", 8.0) or 8.0)

def km_volume_indirim_for(vehicle: dict, settings: dict, ek_km: int) -> float:
    """DEPRECATED: KM hacim indirim özelliği sistemden kaldırıldı (kullanıcı talebi). Her zaman 0 döner."""
    return 0.0

def daily_price_for(vehicle: dict, days: int) -> float:
    """Return the effective daily PRICE for the vehicle given total rental days.
    Uses gunluk_fiyat_kademeleri brackets: pick the bracket where min_gun <= days <= max_gun.
    🆕 Eğer gün sayısı tüm bracket'lerin üstündeyse, EN YÜKSEK bracket fiyatı kullanılır
       (örn: 22-30 gün → 1700₺ tanımlıysa, 35 günlük uzatma da 1700₺ üzerinden hesaplanır).
    If no brackets defined, falls back to vehicle.gunluk_fiyat.
    """
    kademeler = vehicle.get("gunluk_fiyat_kademeleri") or []
    fallback = float(vehicle.get("gunluk_fiyat", 0) or 0)
    if not kademeler:
        return fallback
    sorted_k = sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0))
    for k in sorted_k:
        try:
            mg = int(k.get("min_gun", 0) or 0)
            mxg = k.get("max_gun")
            mxg_n = int(mxg) if mxg is not None else 10**9
            price = float(k.get("gunluk_fiyat", fallback) or fallback)
        except Exception:
            continue
        if mg <= days <= mxg_n:
            return price
    # 🆕 Hiçbir bracket eşleşmedi → en yüksek (son) bracket'in fiyatını kullan
    # Bu, uzatmalar 'son tanımlı kademe' fiyatından devam etsin diye gerekli.
    try:
        last_k = sorted_k[-1]
        last_mg = int(last_k.get("min_gun", 0) or 0)
        if days > last_mg:
            return float(last_k.get("gunluk_fiyat", fallback) or fallback)
    except Exception:
        pass
    return fallback

def matched_price_kademe(vehicle: dict, days: int) -> Optional[dict]:
    """Return the matched price bracket dict for transparency in UI, or None.
    🆕 If days exceeds all brackets, returns the highest bracket so frontend can
       show the consistent "tier" applied for extensions.
    """
    kademeler = vehicle.get("gunluk_fiyat_kademeleri") or []
    if not kademeler:
        return None
    sorted_k = sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0))
    for k in sorted_k:
        try:
            mg = int(k.get("min_gun", 0) or 0)
            mxg = k.get("max_gun")
            mxg_n = int(mxg) if mxg is not None else 10**9
            if mg <= days <= mxg_n:
                return {"min_gun": mg, "max_gun": k.get("max_gun"), "gunluk_fiyat": float(k.get("gunluk_fiyat", 0))}
        except Exception:
            continue
    # 🆕 Üst limit aşıldı → en yüksek bracket'i döndür
    try:
        last_k = sorted_k[-1]
        last_mg = int(last_k.get("min_gun", 0) or 0)
        if days > last_mg:
            return {"min_gun": last_mg, "max_gun": last_k.get("max_gun"), "gunluk_fiyat": float(last_k.get("gunluk_fiyat", 0))}
    except Exception:
        pass
    return None

def matched_km_asim_kademe(vehicle: dict, days: int) -> Optional[dict]:
    """Return the matched km_asim bracket dict for transparency in UI, or None."""
    kademeler = vehicle.get("km_asim_kademeleri") or []
    if not kademeler:
        return None
    for k in sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0)):
        try:
            mg = int(k.get("min_gun", 0) or 0)
            mxg = k.get("max_gun")
            mxg_n = int(mxg) if mxg is not None else 10**9
            if mg <= days <= mxg_n:
                return {"min_gun": mg, "max_gun": k.get("max_gun"), "km_asim_fiyat": float(k.get("km_asim_fiyat", 0))}
        except Exception:
            continue
    return None

def sure_indirim_for(vehicle: dict, days: int, base_total: float, fallback_min: int, fallback_yuzde: float) -> float:
    """DEPRECATED: Süre indirimi sistemden kaldırıldı (kullanıcı talebi). Her zaman 0 döner.
    Eski rezervasyonlarda kaydedilmiş indirim tutarları korunur (geriye dönük etki yok).
    """
    return 0.0

def km_volume_indirim(settings: dict, ek_km: int) -> float:
    """Return flat-amount discount for buying ek_km extra kilometers (highest min_km ≤ ek_km wins)."""
    brackets = settings.get("km_hacim_indirim_kademeleri") or []
    if not brackets or ek_km <= 0:
        return 0.0
    best = 0.0
    best_min = -1
    for b in brackets:
        try:
            mk = int(b.get("min_km", 0) or 0)
            amt = float(b.get("indirim_tutar", 0) or 0)
        except Exception:
            continue
        if ek_km >= mk and mk >= best_min:
            best_min = mk
            best = amt
    return round(max(0.0, best), 2)

async def calc_pricing(vehicle: dict, days: int, services_sel: List[dict] = None, iskonto_yuzde: float = 0.0, force_mandatory: bool = True) -> dict:
    """Compute reservation pricing with discount and services.
    force_mandatory=False ise zorunlu hizmetler otomatik eklenmez (admin kullanıcı tarafından kaldırılabilir)."""
    s = await get_settings()
    fallback_min = s.get("indirim_min_gun", 2)
    fallback_yuzde = s.get("indirim_yuzde", 10.0)

    base_total = daily_price_for(vehicle, days) * days
    indirim_tutar = sure_indirim_for(vehicle, days, base_total, fallback_min, fallback_yuzde)
    arac_total = round(max(0, base_total - indirim_tutar), 2)
    # Effective % for backwards-compat (UI-only label)
    eff_yuzde = round((indirim_tutar / base_total * 100.0) if base_total > 0 else 0.0, 2)

    # Zorunlu hizmetleri otomatik ekle (eğer secilen_hizmetler'de yoksa) — Bu araç için uygun olanlar
    sel_ids = set([sel["service_id"] for sel in (services_sel or [])])
    if not services_sel:
        services_sel = []
    if force_mandatory:
        zorunlu_q = {"aktif": True, "zorunlu": True, "$or": [{"arac_ids": {"$exists": False}}, {"arac_ids": {"$size": 0}}, {"arac_ids": vehicle["id"]}]}
        zorunlu_docs = await db.services.find(zorunlu_q, {"_id": 0}).to_list(50)
        for zsvc in zorunlu_docs:
            if zsvc["id"] not in sel_ids:
                services_sel.append({"service_id": zsvc["id"], "adet": 1})

    services_total = 0.0
    services_breakdown = []
    if services_sel:
        for sel in services_sel:
            svc = await db.services.find_one({"id": sel["service_id"], "aktif": True}, {"_id": 0})
            if not svc:
                continue
            # Araç-spesifik kontrol: arac_ids varsa bu araç içinde mi?
            arac_list = svc.get("arac_ids") or []
            if arac_list and vehicle["id"] not in arac_list:
                continue
            adet = max(1, sel.get("adet", 1))
            line = svc["fiyat"] * adet * (days if svc["tip"] == "gunluk" else 1)
            services_total += line
            services_breakdown.append({
                "service_id": svc["id"], "isim": svc["isim"], "tip": svc["tip"],
                "fiyat": svc["fiyat"], "adet": adet, "tutar": round(line, 2),
                "zorunlu": bool(svc.get("zorunlu", False)),
            })

    subtotal = arac_total + services_total
    iskonto_admin = round(subtotal * (iskonto_yuzde / 100.0), 2) if iskonto_yuzde else 0.0
    toplam = round(max(0, subtotal - iskonto_admin), 2)
    on_odeme = round(toplam * 0.20, 2)

    return {
        "gun_sayisi": days,
        "gunluk_fiyat": daily_price_for(vehicle, days),
        "gunluk_fiyat_baz": float(vehicle.get("gunluk_fiyat", 0)),
        "fiyat_kademe": matched_price_kademe(vehicle, days),
        "fiyat_kademeleri": vehicle.get("gunluk_fiyat_kademeleri") or [],
        "arac_alt_toplam": round(base_total, 2),
        "sure_indirim_yuzde": eff_yuzde,
        "sure_indirim_tutar": indirim_tutar,
        "arac_toplam": round(arac_total, 2),
        "hizmetler": services_breakdown,
        "hizmetler_toplam": round(services_total, 2),
        "iskonto_yuzde": iskonto_yuzde,
        "iskonto_tutar": iskonto_admin,
        "toplam_tutar": toplam,
        "on_odeme_tutar": on_odeme,
        "kalan_odeme": round(toplam - on_odeme, 2),
        "paket_km": paket_km_for(vehicle, days),
        "gunluk_km_uygulanan": daily_km_for(vehicle, days),
    }

# ==================== Wallet helpers ====================
async def get_wallet(customer_id: str) -> dict:
    w = await db.wallets.find_one({"customer_id": customer_id}, {"_id": 0})
    if not w:
        w = {"customer_id": customer_id, "bakiye": 0.0, "created_at": now_iso()}
        await db.wallets.insert_one(dict(w))
    return w

async def wallet_add_transaction(customer_id: str, tutar: float, tip: str, aciklama: str, referans: Optional[str] = None) -> dict:
    """tip: 'yukleme' (+), 'odeme' (-), 'iade' (+), 'provizyon_alma' (-), 'provizyon_iade' (+)"""
    w = await get_wallet(customer_id)
    sign = 1 if tip in ("yukleme", "iade", "provizyon_iade") else -1
    delta = sign * abs(tutar)
    if w["bakiye"] + delta < 0:
        raise HTTPException(402, f"Bakiye yetersiz. Mevcut: {w['bakiye']:.2f}₺ — Gerekli: {abs(tutar):.2f}₺")
    yeni = round(w["bakiye"] + delta, 2)
    await db.wallets.update_one({"customer_id": customer_id}, {"$set": {"bakiye": yeni}})
    tx = {
        "id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "tip": tip,
        "tutar": round(abs(tutar), 2),
        "isaret": "+" if delta > 0 else "-",
        "aciklama": aciklama,
        "referans": referans,
        "bakiye_sonra": yeni,
        "tarih": now_iso(),
    }
    await db.wallet_tx.insert_one(dict(tx))
    return {"bakiye": yeni, "transaction": tx}


async def auto_settle_pending_payments(customer_id: str) -> dict:
    """Müşterinin bakiyesinden açık rezervasyonların kalan ödemelerini otomatik düşer.
    Sıralama: En eski rezervasyon (baslangic_tarihi asc) ilk.
    Durum filtresi: beklemede + onaylandi + aktif (iptal/tamamlandi hariç).
    Bakiye 0'a düşene veya kalan ödeme kalmayana kadar devam eder.
    """
    settlements: List[dict] = []
    total_applied = 0.0

    w = await get_wallet(customer_id)
    available = float(w.get("bakiye", 0) or 0)
    if available <= 0:
        return {"applied_total": 0.0, "settlements": [], "bakiye_kalan": available}

    # Açık rezervasyonlar (en eski ilk)
    cursor = db.reservations.find(
        {"customer_id": customer_id, "durum": {"$in": ["beklemede", "onaylandi", "aktif"]}},
        {"_id": 0}
    ).sort("baslangic_tarihi", 1)
    reservations = await cursor.to_list(200)

    for r in reservations:
        if available <= 0:
            break
        kalan = float(r.get("kalan_odeme", 0) or 0)
        if kalan <= 0:
            continue
        odenecek = round(min(available, kalan), 2)
        if odenecek <= 0:
            continue
        # Bakiyeden düş
        try:
            await wallet_add_transaction(
                customer_id, odenecek, "odeme",
                f"Rezervasyon kalan ödeme otomatik tahsil: {r.get('vehicle_snapshot', {}).get('plaka', r.get('id'))}",
                referans=r.get("id"),
            )
        except HTTPException:
            break
        # Rezervasyonu güncelle
        yeni_odenen = round(float(r.get("odenen_ucret", 0) or 0) + odenecek, 2)
        yeni_kalan = round(max(0.0, kalan - odenecek), 2)
        toplam = float(r.get("toplam_tutar", 0) or 0)
        on_odeme = float(r.get("on_odeme_tutar", 0) or 0)
        if yeni_kalan <= 0.01:
            yeni_odeme_durumu = "tam_odeme_alindi"
            yeni_kalan = 0.0
        elif yeni_odenen >= on_odeme and on_odeme > 0:
            yeni_odeme_durumu = "on_odeme_alindi"
        else:
            yeni_odeme_durumu = r.get("odeme_durumu", "beklemede")
        await db.reservations.update_one(
            {"id": r["id"]},
            {"$set": {
                "odenen_ucret": yeni_odenen,
                "kalan_odeme": yeni_kalan,
                "odeme_durumu": yeni_odeme_durumu,
            }}
        )
        available = round(available - odenecek, 2)
        total_applied = round(total_applied + odenecek, 2)
        settlements.append({
            "reservation_id": r["id"],
            "plaka": r.get("vehicle_snapshot", {}).get("plaka"),
            "applied": odenecek,
            "yeni_kalan": yeni_kalan,
            "yeni_durum": yeni_odeme_durumu,
        })

    return {"applied_total": total_applied, "settlements": settlements, "bakiye_kalan": available}

# ==================== Bot proxy ====================
async def fetch_bot_vehicles() -> Optional[List[dict]]:
    if not BOT_BEARER:
        return None
    try:
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.get(f"{BOT_API_URL}/vehicles", headers={"Authorization": f"Bearer {BOT_BEARER}"})
            if r.status_code == 200:
                return r.json().get("vehicles", [])
    except Exception as e:
        logger.info(f"Bot offline (mock fallback): {e}")
    return None

# ⚡ Bot veri cache — admin/vehicles gibi list endpoint'lerinde 20 araç için 20 ayrı bot çağrısı yapılmasını engeller
_bot_cache: dict = {"data": None, "expires_at": 0.0}
async def fetch_bot_vehicles_cached(ttl_sec: float = 5.0) -> Optional[List[dict]]:
    """fetch_bot_vehicles() çıktısını N saniye memory'de tutar. Periodic sync ve admin liste sayfası için ideal."""
    import time
    now = time.time()
    if _bot_cache["data"] is not None and _bot_cache["expires_at"] > now:
        return _bot_cache["data"]
    data = await fetch_bot_vehicles()
    if data is not None:
        _bot_cache["data"] = data
        _bot_cache["expires_at"] = now + ttl_sec
    return data

async def get_live_vehicle(plaka: str) -> Optional[dict]:
    vs = await fetch_bot_vehicles_cached()
    if not vs:
        return None
    np = (plaka or "").replace(" ", "").upper()
    for v in vs:
        # Çoklu alan desteği: PlateNumber (yeni bot) / plate_number / plate / plaka
        candidates = [
            v.get("PlateNumber"),
            v.get("plate_number"),
            v.get("plate"),
            v.get("plaka"),
        ]
        for cand in candidates:
            if cand and str(cand).replace(" ", "").upper() == np:
                return v
    return None

# ==================== Bot motor blokaj proxy ====================
async def _get_device_id_by_plaka(plaka: str) -> Optional[int]:
    """Bot'tan plakaya göre DeviceID (sayısal IMEI) alır."""
    live = await get_live_vehicle(plaka)
    if not live:
        return None
    did = live.get("DeviceID")
    try:
        return int(did) if did is not None else None
    except Exception:
        return None

async def bot_motor_blokaj(plaka: str, aktif: bool) -> bool:
    """Bot'a motor blokaj komutu gönderir.
    aktif=True  → Motor KİTLENİR (engine block)
    aktif=False → Motor AÇILIR (engine unblock)
    POST /engine-block  body: {deviceId: int, block: bool}
    """
    if not BOT_BEARER:
        return False
    device_id = await _get_device_id_by_plaka(plaka)
    if not device_id:
        logger.warning(f"engine-block: {plaka} için DeviceID bulunamadı")
        return False
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(
                f"{BOT_API_URL}/engine-block",
                headers={"Authorization": f"Bearer {BOT_BEARER}", "Content-Type": "application/json"},
                json={"deviceId": device_id, "block": bool(aktif)},
            )
            if 200 <= r.status_code < 300:
                try:
                    data = r.json()
                    if data.get("success") is True:
                        logger.info(f"engine-block OK: {plaka} (deviceId={device_id}) block={aktif}")
                        return True
                    logger.warning(f"engine-block bot reddetti: {plaka} resp={data}")
                except Exception:
                    logger.info(f"engine-block 2xx (non-json): {plaka} block={aktif}")
                    return True
            else:
                logger.warning(f"engine-block FAIL: {plaka} status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        logger.warning(f"engine-block error: {plaka} {e}")
    return False

# ==================== Expo Push Notification ====================
EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

async def send_push_to_customer(customer_id: str, title: str, body: str, data: Optional[dict] = None) -> int:
    """Müşterinin tüm push token'larına bildirim yollar. Başarılı gönderim sayısını döner.
    Token bulunamazsa 0 döner — in-app notification ayrıca insert edilmeli."""
    tokens_docs = await db.push_tokens.find({"customer_id": customer_id}, {"_id": 0, "token": 1}).to_list(20)
    tokens = [t["token"] for t in tokens_docs if t.get("token", "").startswith("ExponentPushToken[")]
    if not tokens:
        return 0
    messages = [
        {
            "to": t,
            "sound": "default",
            "title": title[:60],
            "body": body[:240],
            "priority": "high",
            "data": data or {},
        }
        for t in tokens
    ]
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(EXPO_PUSH_URL, json=messages, headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                return len(tokens)
            logger.warning(f"Expo push send fail: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.warning(f"Expo push error: {e}")
    return 0

async def send_push_to_admins(title: str, body: str, data: Optional[dict] = None, only_super: bool = False) -> int:
    """Tüm admin (veya sadece superadmin) kullanıcıların push token'larına bildirim yollar.
    `only_super=True` ise konsinye sahipleri hariç tutulur."""
    q = {} if not only_super else {"is_super": True}
    admin_ids = [a["id"] for a in await db.admins.find(q, {"_id": 0, "id": 1}).to_list(50)]
    if not admin_ids:
        return 0
    tokens_docs = await db.push_tokens.find(
        {"admin_id": {"$in": admin_ids}}, {"_id": 0, "token": 1}
    ).to_list(50)
    tokens = [t["token"] for t in tokens_docs if t.get("token", "").startswith("ExponentPushToken[")]
    if not tokens:
        return 0
    # Dedupe
    tokens = list(set(tokens))
    messages = [
        {
            "to": t,
            "sound": "default",
            "title": title[:60],
            "body": body[:240],
            "priority": "high",
            "channelId": "default",
            "data": data or {},
        }
        for t in tokens
    ]
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(EXPO_PUSH_URL, json=messages, headers={"Content-Type": "application/json"})
            if r.status_code == 200:
                return len(tokens)
            logger.warning(f"Expo admin push send fail: {r.status_code} {r.text[:200]}")
    except Exception as e:
        logger.warning(f"Expo admin push error: {e}")
    return 0

async def notify_admin(baslik: str, mesaj: str, data: Optional[dict] = None, only_super: bool = False):
    """Admin için fresh-count'a yansıyacak şekilde admin_notifications koleksiyonuna kayıt + push."""
    try:
        await db.admin_notifications.insert_one({
            "id": str(uuid.uuid4()),
            "baslik": baslik,
            "mesaj": mesaj,
            "data": data or {},
            "only_super": bool(only_super),
            "tarih": now_iso(),
            "okuyanlar": [],
        })
    except Exception as e:
        logger.warning(f"admin notif insert fail: {e}")
    try:
        await send_push_to_admins(baslik, mesaj, data, only_super=only_super)
    except Exception as e:
        logger.warning(f"admin push fail: {e}")

async def notify_customer(customer_id: str, baslik: str, mesaj: str, data: Optional[dict] = None):
    """In-app bildirim + Expo Push aynı anda yollar."""
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": baslik,
        "mesaj": mesaj,
        "hedef_type": "secili",
        "hedef_customer_ids": [customer_id],
        "tarih": now_iso(), "okuyanlar": [],
    })
    try:
        await send_push_to_customer(customer_id, baslik, mesaj, data)
    except Exception as e:
        logger.warning(f"push notify fail: {e}")

# ==================== Status ====================
async def compute_vehicle_status(vehicle: dict) -> str:
    if vehicle.get("manuel_durum"):
        return vehicle["manuel_durum"]
    now = now_iso()
    active = await db.reservations.find_one({
        "vehicle_id": vehicle["id"],
        "baslangic_tarihi": {"$lte": now},
        "bitis_tarihi": {"$gte": now},
        "durum": {"$in": ["onaylandi", "aktif"]},
    })
    return "dolu" if active else "musait"

# ==================== Seed ====================
async def seed_admin():
    """İlk kurulumda mevcut admin/admin1234 yoksa Yusuf Sünger'i seed eder.
    Eğer eski 'admin' kullanıcı adı varsa ve TC alanı yoksa, sahibinin TC'siyle migrate eder."""
    # Yusuf Sünger TC bilgileri
    OWNER_TC = "17695979542"
    OWNER_AD = "Yusuf"
    OWNER_SOYAD = "Sünger"
    # Migrate: kullanici_adi='admin' kaydı varsa ve tc_norm yoksa güncelle
    legacy = await db.admins.find_one({"kullanici_adi": "admin"})
    if legacy:
        upd = {}
        if not legacy.get("tc_norm"):
            upd["tc_norm"] = OWNER_TC
        if not legacy.get("ad") or legacy.get("ad") == "Sistem Yöneticisi":
            upd["ad"] = OWNER_AD
        if not legacy.get("soyad"):
            upd["soyad"] = OWNER_SOYAD
        if upd:
            await db.admins.update_one({"id": legacy["id"]}, {"$set": upd})
            logger.info(f"Legacy admin migrated to Yusuf Sünger TC={OWNER_TC}")
    else:
        # Hiç admin yoksa sıfırdan oluştur
        await db.admins.insert_one({
            "id": str(uuid.uuid4()),
            "ad": OWNER_AD,
            "soyad": OWNER_SOYAD,
            "tc_norm": OWNER_TC,
            "kullanici_adi": "admin",  # geri uyumluluk için
            "password_hash": hash_pw("admin1234"),  # geri uyumluluk için
            "created_at": now_iso(),
        })

async def seed_settings():
    if not await db.settings.find_one({"key": "company"}):
        await db.settings.insert_one({
            "key": "company",
            "sirket_adi": "YS Auto",
            "iban": "TR00 0000 0000 0000 0000 0000 00",
            "banka": "Banka Adı",
            "hesap_sahibi": "YS Auto",
            "iletisim_telefon": "+90 555 000 00 00",
            "iletisim_email": "info@ysauto.com",
            "iletisim_adres": "İstanbul, Türkiye",
            "whatsapp": "+905550000000",
            "mesai_baslangic": "09:00",
            "mesai_bitis": "18:00",
            "tatil_haftaici_gunler": [6],  # Sunday
            "indirim_min_gun": 2,
            "indirim_yuzde": 10.0,
            "km_asim_fiyat": 8.0,  # 8 ₺ / km
        })

async def seed_services():
    if await db.services.count_documents({}) == 0:
        await db.services.insert_many([
            {"id": str(uuid.uuid4()), "isim": "Çocuk Koltuğu", "aciklama": "0-4 yaş güvenlik koltuğu", "fiyat": 75.0, "tip": "gunluk", "icon": "shield-checkmark-outline", "aktif": True, "zorunlu": False, "siralama": 1},
            {"id": str(uuid.uuid4()), "isim": "Ek Sürücü", "aciklama": "İkinci sürücü tanımlama", "fiyat": 100.0, "tip": "gunluk", "icon": "person-add-outline", "aktif": True, "zorunlu": False, "siralama": 2},
            {"id": str(uuid.uuid4()), "isim": "Tam Muafiyet Kasko", "aciklama": "Mini hasar onarım dahil tam koruma", "fiyat": 150.0, "tip": "gunluk", "icon": "umbrella-outline", "aktif": True, "zorunlu": False, "siralama": 3},
            {"id": str(uuid.uuid4()), "isim": "HGS Kullanımı", "aciklama": "Otoyol/köprü ücretleri", "fiyat": 250.0, "tip": "tek_seferlik", "icon": "card-outline", "aktif": True, "zorunlu": False, "siralama": 4},
            {"id": str(uuid.uuid4()), "isim": "Yakıt Dolu Teslim", "aciklama": "Aracı dolu teslim alma", "fiyat": 1500.0, "tip": "tek_seferlik", "icon": "flash-outline", "aktif": True, "zorunlu": False, "siralama": 5},
        ])
        logger.info("Ek hizmetler eklendi")

async def seed_demo():
    if await db.customers.count_documents({}) == 0:
        c1id = str(uuid.uuid4())
        c2id = str(uuid.uuid4())
        await db.customers.insert_many([
            {"id": c1id, "ad": "Ahmet", "soyad": "Yılmaz", "tc_norm": "12345678901", "telefon": "+90 555 123 45 67", "email": "ahmet@test.com", "blocked": False, "created_at": now_iso()},
            {"id": c2id, "ad": "Mehmet", "soyad": "Demir", "tc_norm": "98765432101", "telefon": "+90 532 555 12 34", "email": None, "blocked": False, "created_at": now_iso()},
        ])
        # Add some balance for testing
        await db.wallets.insert_one({"customer_id": c1id, "bakiye": 5000.0, "created_at": now_iso()})

    if await db.vehicles.count_documents({}) == 0:
        vehicles_data = [
            {"plaka": "34 YS 0123", "marka": "Renault", "model": "Clio Joy", "yil": 2024, "renk": "Kırmızı",
             "vites": "Manuel", "yakit": "Benzin", "gunluk_fiyat": 1200.0, "gunluk_km": 250,
             "foto_url": "https://images.unsplash.com/photo-1549399542-7e3f8b79c341?w=800",
             "ekstra_ozellikler": [], "aciklama": "Ekonomik şehir aracı."},
            {"plaka": "34 YS 0456", "marka": "Volkswagen", "model": "Golf R", "yil": 2024, "renk": "Siyah",
             "vites": "Otomatik", "yakit": "Benzin", "gunluk_fiyat": 3500.0, "gunluk_km": 150,
             "foto_url": "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?w=800",
             "ekstra_ozellikler": ["Yüksek Performans"], "aciklama": "Performans tutkunları için."},
            {"plaka": "34 YS 0789", "marka": "Peugeot", "model": "3008 SUV", "yil": 2024, "renk": "Beyaz",
             "vites": "Otomatik", "yakit": "Dizel", "gunluk_fiyat": 2200.0, "gunluk_km": 250,
             "foto_url": "https://images.unsplash.com/photo-1606220588913-b3aacb4d2f46?w=800",
             "ekstra_ozellikler": ["7 Koltuk"], "aciklama": "Aile yolculukları için ideal SUV."},
            {"plaka": "34 YS 1001", "marka": "Fiat", "model": "Egea", "yil": 2024, "renk": "Gri",
             "vites": "Manuel", "yakit": "Dizel", "gunluk_fiyat": 1500.0, "gunluk_km": 250,
             "foto_url": "https://images.unsplash.com/photo-1605559424843-9e4c228bf1c2?w=800",
             "ekstra_ozellikler": [], "aciklama": "Yakıt ekonomik sedan."},
            {"plaka": "34 YS 1234", "marka": "Mercedes-Benz", "model": "C200 AMG", "yil": 2024, "renk": "Siyah",
             "vites": "Otomatik", "yakit": "Benzin", "gunluk_fiyat": 5500.0, "gunluk_km": 300,
             "foto_url": "https://images.unsplash.com/photo-1618843479313-40f8afb4b4d8?w=800",
             "ekstra_ozellikler": ["Premium"], "aciklama": "Lüks ve konforun zirvesi."},
            {"plaka": "34 YS 2024", "marka": "Toyota", "model": "Corolla Hybrid", "yil": 2024, "renk": "Mavi",
             "vites": "Otomatik", "yakit": "Hibrit", "gunluk_fiyat": 1900.0, "gunluk_km": 300,
             "foto_url": "https://images.unsplash.com/photo-1623869675781-80aa31012a5a?w=800",
             "ekstra_ozellikler": [], "aciklama": "Yakıt tasarruflu ve çevre dostu."},
        ]
        docs = []
        for v in vehicles_data:
            docs.append({"id": str(uuid.uuid4()), "manuel_durum": None, "created_at": now_iso(), **v})
        await db.vehicles.insert_many(docs)

@app.on_event("startup")
async def startup():
    await ensure_indexes()
    await seed_tenants()
    await migrate_tenant_id()
    await seed_admin()
    await seed_settings()
    await seed_services()
    await seed_demo()
    await init_vehicle_order()
    # 6 saat hatırlatma background task
    asyncio.create_task(rental_expiry_reminder_loop())
    # Bot-Sync background task (oto müşteri/rezervasyon + KM senkron + motor blokaj)
    asyncio.create_task(bot_sync_loop())
    # Tenant backfill safety-net (yeni insert'lere tenant_id atanmamışsa otomatik düzeltir)
    asyncio.create_task(tenant_backfill_loop())


# ==================== MULTI-TENANT — Periodic Backfill ====================
async def tenant_backfill_loop():
    """Her 10 dakikada bir tenant_id alanı olmayan yeni dokümanları
    DEFAULT_TENANT_ID'ye atar. Bu, multi-tenant geçişi sırasında insert
    çağrılarının atlanmasına karşı güvenlik ağıdır."""
    await asyncio.sleep(60)  # ilk başta 1 dk bekle
    while True:
        try:
            await migrate_tenant_id()
        except Exception as e:
            logger.warning(f"tenant_backfill_loop hatası: {e}")
        await asyncio.sleep(600)  # 10 dakika


# ==================== MULTI-TENANT — Seed & Migration ====================
async def seed_tenants():
    """Default tenant'ı oluşturur (idempotent). Yeni firmalar buraya eklenecek."""
    try:
        existing = await db.tenants.find_one({"id": DEFAULT_TENANT_ID})
        if not existing:
            await db.tenants.insert_one({
                "id": DEFAULT_TENANT_ID,
                "ad": "YS Auto",
                "slug": DEFAULT_TENANT_ID,
                "aktif": True,
                "plan": "owner",   # owner | starter | pro | enterprise
                "created_at": now_iso(),
                "owner_email": "info@ysauto.com",
            })
            logger.info(f"✅ Default tenant oluşturuldu: {DEFAULT_TENANT_ID}")
        # Tenants index
        try:
            await db.tenants.create_index("id", unique=True, name="idx_tenants_id")
            await db.tenants.create_index("slug", unique=True, sparse=True, name="idx_tenants_slug")
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"seed_tenants hatası (yine devam ediyoruz): {e}")


async def migrate_tenant_id():
    """Mevcut tüm dokümanlara tenant_id alanı yoksa DEFAULT_TENANT_ID ata.
    Idempotent — sadece tenant_id yok olan dokümanları günceller.
    Multi-tenant'a geçişin sıfır kesintili migration adımıdır."""
    try:
        collections = [
            "vehicles", "customers", "admins", "reservations", "wallets",
            "wallet_tx", "services", "notifications", "push_tokens",
            "speed_violations", "holidays", "reviews", "settings",
            "konsinyatorler", "arac_bakim_giderleri", "konsinye_odemeler",
        ]
        total = 0
        for col in collections:
            try:
                result = await db[col].update_many(
                    {"tenant_id": {"$exists": False}},
                    {"$set": {"tenant_id": DEFAULT_TENANT_ID}},
                )
                if result.modified_count > 0:
                    logger.info(f"  ↳ {col}: {result.modified_count} doküman güncellendi")
                    total += result.modified_count
            except Exception as e:
                logger.warning(f"  ⚠️ {col} migration hatası: {e}")
        # Süper admin flag'ini set et
        if SUPER_ADMIN_TCS:
            sup_result = await db.admins.update_many(
                {"tc_norm": {"$in": list(SUPER_ADMIN_TCS)}, "is_super": {"$ne": True}},
                {"$set": {"is_super": True}},
            )
            if sup_result.modified_count > 0:
                logger.info(f"  ↳ {sup_result.modified_count} admin süper admin olarak işaretlendi")
        logger.info(f"✅ Tenant migration tamamlandı (toplam {total} doküman güncellendi)")
    except Exception as e:
        logger.error(f"⚠️ migrate_tenant_id genel hata: {e}")


async def ensure_indexes():
    """MongoDB index'lerini oluşturur. Idempotent — birden çok kez çağrılabilir.
    Performans açısından kritik index'ler:
      - id lookup (her collection için, primary)
      - Login/Bot lookup (tc_norm, telefon_norm, plaka)
      - Rezervasyon overlap kontrolü (vehicle_id + baslangic/bitis)
      - Müşteri bazlı liste sorguları (customer_id + created_at)
    """
    try:
        # CORE — primary id lookup (her collection)
        for col in ["vehicles", "customers", "admins", "reservations", "wallets",
                    "wallet_tx", "services", "notifications", "push_tokens",
                    "speed_violations", "holidays", "settings", "reviews"]:
            try:
                await db[col].create_index("id", name=f"idx_{col}_id")
            except Exception:
                pass

        # CUSTOMERS — login & bot lookup (sparse unique)
        await db.customers.create_index("tc_norm", name="idx_customers_tc",
                                        sparse=True, background=True)
        await db.customers.create_index("telefon_norm", name="idx_customers_tel",
                                        sparse=True, background=True)
        await db.customers.create_index([("created_at", -1)], name="idx_customers_created",
                                        background=True)

        # ADMINS — login lookup
        await db.admins.create_index("tc_norm", name="idx_admins_tc",
                                     sparse=True, background=True)
        await db.admins.create_index("kullanici_adi", name="idx_admins_username",
                                     sparse=True, background=True)

        # VEHICLES — plaka & ordering
        await db.vehicles.create_index("plaka", name="idx_vehicles_plaka", background=True)
        await db.vehicles.create_index([("siralama", 1)], name="idx_vehicles_siralama",
                                       sparse=True, background=True)

        # RESERVATIONS — en kritik. Çakışma sorguları için compound.
        await db.reservations.create_index(
            [("vehicle_id", 1), ("baslangic_tarihi", 1), ("bitis_tarihi", 1)],
            name="idx_rez_vehicle_dates", background=True)
        await db.reservations.create_index(
            [("customer_id", 1), ("durum", 1)],
            name="idx_rez_customer_durum", background=True)
        await db.reservations.create_index("durum", name="idx_rez_durum", background=True)
        await db.reservations.create_index(
            [("bitis_tarihi", 1), ("durum", 1)],
            name="idx_rez_bitis_durum", background=True)
        await db.reservations.create_index([("created_at", -1)],
                                           name="idx_rez_created", background=True)

        # WALLETS — customer_id lookup
        await db.wallets.create_index("customer_id", name="idx_wallets_customer",
                                      unique=True, background=True)

        # WALLET_TX — müşteri geçmişi listesi
        await db.wallet_tx.create_index(
            [("customer_id", 1), ("created_at", -1)],
            name="idx_wallettx_customer_created", background=True)

        # NOTIFICATIONS — kullanıcı bildirimleri
        await db.notifications.create_index(
            [("customer_id", 1), ("created_at", -1)],
            name="idx_notif_customer_created", background=True)
        await db.notifications.create_index(
            [("customer_id", 1), ("is_read", 1)],
            name="idx_notif_customer_unread", background=True)

        # PUSH_TOKENS — push gönderme
        await db.push_tokens.create_index("customer_id", name="idx_push_customer",
                                          background=True)
        await db.push_tokens.create_index("admin_id", name="idx_push_admin",
                                          background=True)
        await db.push_tokens.create_index("token", name="idx_push_token",
                                          unique=True, sparse=True, background=True)

        # SERVICES — ek hizmetler
        await db.services.create_index([("aktif", 1), ("zorunlu", 1)],
                                       name="idx_services_aktif_zorunlu",
                                       background=True)

        # SETTINGS — config lookup
        await db.settings.create_index("key", name="idx_settings_key",
                                       unique=True, background=True)

        # HOLIDAYS — tarih lookup
        await db.holidays.create_index("tarih", name="idx_holidays_tarih",
                                       background=True)

        # SPEED_VIOLATIONS — rezervasyon ve plaka bazlı
        await db.speed_violations.create_index("reservation_id",
                                               name="idx_speedviol_rez",
                                               sparse=True, background=True)
        await db.speed_violations.create_index(
            [("plaka", 1), ("created_at", -1)],
            name="idx_speedviol_plaka_created", background=True)

        # REVIEWS — araç bazlı yorumlar
        try:
            await db.reviews.create_index(
                [("vehicle_id", 1), ("created_at", -1)],
                name="idx_reviews_vehicle_created", background=True)
        except Exception:
            pass

        # KONSİNYE — araç sahibi yönetimi & bakım/ödemeler
        try:
            await db.konsinyatorler.create_index("tc_norm", unique=True, sparse=True,
                                                 name="idx_kons_tc", background=True)
            await db.konsinyatorler.create_index("tenant_id", name="idx_kons_tenant",
                                                 sparse=True, background=True)
            await db.arac_bakim_giderleri.create_index(
                [("konsinye_sahibi_id", 1), ("tarih", -1)],
                name="idx_bakim_sahibi_tarih", background=True)
            await db.arac_bakim_giderleri.create_index("vehicle_id",
                                                       name="idx_bakim_vehicle",
                                                       background=True)
            await db.konsinye_odemeler.create_index(
                [("konsinye_sahibi_id", 1), ("donem", -1)],
                name="idx_odeme_sahibi_donem", background=True)
        except Exception:
            pass

        # ⚡ HIZ OPTİMİZASYONU — Ek index'ler (Mayıs 2026)
        try:
            # TENANT_ID compound — multi-tenant query'lerde devasa hız farkı yaratır
            await db.vehicles.create_index(
                [("tenant_id", 1), ("siralama", 1)],
                name="idx_vehicles_tenant_sira", sparse=True, background=True)
            await db.customers.create_index(
                [("tenant_id", 1), ("created_at", -1)],
                name="idx_customers_tenant_created", sparse=True, background=True)
            await db.customers.create_index(
                [("tenant_id", 1), ("tip", 1)],
                name="idx_customers_tenant_tip", sparse=True, background=True)
            await db.reservations.create_index(
                [("tenant_id", 1), ("durum", 1), ("baslangic_tarihi", 1)],
                name="idx_rez_tenant_durum_basl", sparse=True, background=True)

            # NOTIFICATIONS — admin bildirim listesi sıralaması (tarih DESC)
            await db.notifications.create_index(
                [("hedef_type", 1), ("tarih", -1)],
                name="idx_notif_hedef_tarih", background=True)
            await db.notifications.create_index(
                [("tarih", -1)],
                name="idx_notif_tarih", background=True)

            # WALLET_TX — tarih bazlı sıralama (admin listesi)
            await db.wallet_tx.create_index(
                [("tarih", -1)],
                name="idx_wallettx_tarih", background=True)
            await db.wallet_tx.create_index(
                [("durum", 1), ("tarih", -1)],
                name="idx_wallettx_durum_tarih", sparse=True, background=True)

            # RESERVATIONS — kaynak (bot/manuel) bazlı listeleme
            await db.reservations.create_index(
                [("kaynak", 1), ("durum", 1)],
                name="idx_rez_kaynak_durum", sparse=True, background=True)
            # Aktif rezervasyonu olan araç sorgusu için
            await db.reservations.create_index(
                [("durum", 1), ("vehicle_id", 1)],
                name="idx_rez_durum_vehicle", background=True)

            # CUSTOMERS — admin liste sayfasında full-text yerine prefix arama hızı
            await db.customers.create_index(
                [("ad", 1)], name="idx_customers_ad", sparse=True, background=True)
            await db.customers.create_index(
                [("soyad", 1)], name="idx_customers_soyad", sparse=True, background=True)

            # VEHICLES — admin liste filtre & sıralama
            await db.vehicles.create_index(
                [("kaynak", 1)], name="idx_vehicles_kaynak", sparse=True, background=True)

            # DEKONTLAR — admin dekont liste
            await db.dekontlar.create_index(
                [("durum", 1), ("tarih", -1)],
                name="idx_dekontlar_durum_tarih", sparse=True, background=True)
            await db.dekontlar.create_index(
                [("customer_id", 1), ("tarih", -1)],
                name="idx_dekontlar_customer_tarih", sparse=True, background=True)
        except Exception as e:
            logger.error(f"⚠️ Ek index oluşturma hatası: {e}")

        logger.info("✅ MongoDB index'leri kontrol edildi/oluşturuldu")
    except Exception as e:
        logger.error(f"⚠️ Index oluşturma hatası (sistem yine de çalışır): {e}")


async def init_vehicle_order():
    """Siralama alanı olmayan araçlara created_at sırasına göre siralama atar."""
    vs = await db.vehicles.find({"$or": [{"siralama": {"$exists": False}}, {"siralama": None}]}, {"_id": 0, "id": 1, "created_at": 1}).sort("created_at", 1).to_list(500)
    if not vs:
        return
    # Mevcut max siralama'yı bul
    max_doc = await db.vehicles.find_one({"siralama": {"$exists": True, "$ne": None}}, sort=[("siralama", -1)])
    next_sira = int(max_doc.get("siralama", 0)) + 1 if max_doc else 1
    for v in vs:
        await db.vehicles.update_one({"id": v["id"]}, {"$set": {"siralama": next_sira}})
        next_sira += 1

async def rental_expiry_reminder_loop():
    """Her 30 dakikada bir aktif rezervasyonları kontrol eder.
    Bitişine ~6 saat kala (5.5h - 6.5h penceresinde) tek seferlik bildirim gönderir."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Bitişe 5.5h - 6.5h kalmış olanlar
            window_start = (now + timedelta(hours=5, minutes=30)).isoformat()
            window_end = (now + timedelta(hours=6, minutes=30)).isoformat()
            docs = await db.reservations.find({
                "durum": {"$in": ["onaylandi", "aktif"]},
                "bitis_tarihi": {"$gte": window_start, "$lte": window_end},
                "expiry_reminder_sent": {"$ne": True},
            }, {"_id": 0}).to_list(200)
            for r in docs:
                plaka = r.get("vehicle_snapshot", {}).get("plaka", "")
                marka = r.get("vehicle_snapshot", {}).get("marka", "")
                model = r.get("vehicle_snapshot", {}).get("model", "")
                try:
                    bit_local = (parse_iso(r["bitis_tarihi"]) + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
                except Exception:
                    bit_local = r["bitis_tarihi"]
                baslik = "Kiralama Süresi Yaklaşıyor"
                mesaj = f"{marka} {model} ({plaka}) iade saatinize yaklaşık 6 saat kaldı. Bitiş: {bit_local}. Süre uzatmak için 'Rezerv.' sayfasından işlem yapabilirsiniz."
                await notify_customer(r["customer_id"], baslik, mesaj, {"type": "rental_expiry", "reservation_id": r["id"]})
                await db.reservations.update_one({"id": r["id"]}, {"$set": {"expiry_reminder_sent": True}})
                logger.info(f"6h reminder sent for reservation {r['id']}")
        except Exception as e:
            logger.warning(f"reminder loop error: {e}")
        await asyncio.sleep(30 * 60)  # 30 dakika

async def bot_sync_loop():
    """Bot-Sync background task — her 30 saniyede bir bot'tan gelen aktif sözleşmeleri işler.
    - Bottaki ContractCustomer + ContractCustomerMobilePhone ile DB'de müşteri yoksa OTOMATİK kayıt eder.
    - Bottaki sözleşme tarihleriyle DB'de aktif rezervasyon yoksa OTOMATİK rezervasyon oluşturur (durum=aktif).
    - ContractDistance → reservation.kullanilan_km eşitlenir.
    - Kalan KM 50'nin altına inerse uyarı bildirimi (tek seferlik) yollar.
    - Kalan KM <= 0 olursa motor blokaj bildirimi + bot motor-blokaj POST komutu (true) yollar.
    - DeviceSpeed > hiz_limit (default 120 km/h) olursa müşteri + admin'e push bildirim (5 dk debounce)."""
    await asyncio.sleep(8)  # uygulama tam başlasın
    while True:
        try:
            bot_vehicles = await fetch_bot_vehicles()
            if not bot_vehicles:
                await asyncio.sleep(30)
                continue
            for bv in bot_vehicles:
                try:
                    plaka = (bv.get("PlateNumber") or "").replace(" ", "").upper()
                    if not plaka:
                        continue
                    cust_name = (bv.get("ContractCustomer") or "").strip()
                    cust_phone = (bv.get("ContractCustomerMobilePhone") or "").strip()
                    contract_start = bv.get("ContractStart")
                    contract_end = bv.get("ContractEnd")
                    contract_dist = bv.get("ContractDistance")
                    if not (cust_name and cust_phone and contract_start and contract_end):
                        # Bu araç şu an sözleşmesiz / müsait — atla
                        continue

                    # 1) DB'de araç bul (plaka eşleşmesi)
                    db_vehicle = await db.vehicles.find_one({"plaka": {"$regex": f"^{re.escape(plaka)}$", "$options": "i"}}, {"_id": 0})
                    if not db_vehicle:
                        # Plaka boşluk farkları için bir tarama daha
                        all_vs = await db.vehicles.find({}, {"_id": 0}).to_list(500)
                        for vv in all_vs:
                            if (vv.get("plaka", "") or "").replace(" ", "").upper() == plaka:
                                db_vehicle = vv
                                break
                    if not db_vehicle:
                        logger.info(f"bot-sync: plaka {plaka} DB'de bulunamadı, atlandı")
                        continue

                    # 2) Müşteri bul (telefon_norm ile) — yoksa oluştur
                    phone_norm = normalize_phone(cust_phone)
                    if not phone_norm or len(phone_norm) != 10:
                        continue
                    customer = await db.customers.find_one({"telefon_norm": phone_norm}, {"_id": 0})
                    if not customer:
                        parts = cust_name.split()
                        ad = parts[0] if parts else cust_name
                        soyad = " ".join(parts[1:]) if len(parts) > 1 else "-"
                        new_cid = str(uuid.uuid4())
                        customer = {
                            "id": new_cid,
                            "ad": ad,
                            "soyad": soyad,
                            "tc_norm": "",  # Placeholder — admin daha sonra ekleyebilir
                            "telefon": cust_phone,
                            "telefon_norm": phone_norm,
                            "kaynak": "bot_oto",
                            "tip": "bireysel",
                            "blocked": False,
                            "created_at": now_iso(),
                        }
                        await db.customers.insert_one(customer)
                        logger.info(f"bot-sync: yeni müşteri oluşturuldu {ad} {soyad} ({phone_norm})")
                        try:
                            await notify_admin(
                                "👤 Yeni Müşteri Kaydı",
                                f"{ad} {soyad} ({phone_norm}) sisteme kaydedildi — Bot otomatik",
                                {"type": "new_customer", "customer_id": customer["id"]},
                            )
                        except Exception:
                            pass

                    # 3) Aktif/onaylı VEYA aynı sözleşme başlangıç tarihiyle daha önce oluşturulmuş rezervasyon var mı?
                    # Bu kontrol bot'un tamamlandı/iptal edilmiş rezervasyonları tekrar oluşturmasını ENGELLER
                    try:
                        contract_start_iso = parse_iso(contract_start).isoformat()
                    except Exception:
                        contract_start_iso = contract_start

                    # Önce bu (araç + müşteri + bot sözleşme başlangıç tarihi) ile herhangi durumda kayıt var mı?
                    existing_any = await db.reservations.find_one({
                        "vehicle_id": db_vehicle["id"],
                        "customer_id": customer["id"],
                        "bot_contract_start": contract_start_iso,
                    }, {"_id": 0})

                    reservation = None
                    if existing_any:
                        # Daha önce bu sözleşme için bir kayıt yaratıldı
                        # Eğer durum 'tamamlandi' veya 'iptal' ise yeni oluşturma — bot bu rezervasyonu yok say
                        if existing_any.get("durum") in ("tamamlandi", "iptal"):
                            logger.debug(f"bot-sync: {plaka} tamamlandı/iptal, atlandı")
                            continue
                        reservation = existing_any
                    else:
                        # Geri uyumluluk: bot_contract_start yoksa eski koleksiyondaki aktif/onaylı rezervasyonu bul
                        reservation = await db.reservations.find_one({
                            "vehicle_id": db_vehicle["id"],
                            "customer_id": customer["id"],
                            "durum": {"$in": ["onaylandi", "aktif"]},
                        }, {"_id": 0})
                        # Backfill: eski rezervasyona bot_contract_start kaydet
                        if reservation and not reservation.get("bot_contract_start"):
                            await db.reservations.update_one(
                                {"id": reservation["id"]},
                                {"$set": {"bot_contract_start": contract_start_iso}}
                            )
                            reservation["bot_contract_start"] = contract_start_iso

                    if not reservation:
                        # Sözleşme tarih aralığını parse et
                        start_iso = contract_start_iso
                        try:
                            end_iso = parse_iso(contract_end).isoformat()
                        except Exception:
                            end_iso = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                        try:
                            days = max(1, int((parse_iso(end_iso) - parse_iso(start_iso)).total_seconds() // 86400) or 1)
                        except Exception:
                            days = 1
                        paket_km_val = paket_km_for(db_vehicle, days)
                        arac_tutari = float(db_vehicle.get("gunluk_fiyat", 0) or 0) * days
                        # 🔧 Zorunlu ek hizmetleri otomatik ekle (yıkama vb.) — bu araç için uygun olanlar
                        ek_hizmetler_auto = []
                        ek_hizmet_tutari = 0.0
                        try:
                            zq = {"aktif": True, "zorunlu": True, "$or": [{"arac_ids": {"$exists": False}}, {"arac_ids": {"$size": 0}}, {"arac_ids": db_vehicle["id"]}]}
                            zorunlu_docs = await db.services.find(zq, {"_id": 0}).to_list(50)
                            for zsvc in zorunlu_docs:
                                line = float(zsvc.get("fiyat", 0) or 0) * (days if zsvc.get("tip") == "gunluk" else 1)
                                ek_hizmetler_auto.append({
                                    "service_id": zsvc["id"], "isim": zsvc.get("isim", ""), "tip": zsvc.get("tip", "tek_seferlik"),
                                    "fiyat": float(zsvc.get("fiyat", 0) or 0), "adet": 1, "tutar": round(line, 2),
                                    "zorunlu": True,
                                })
                                ek_hizmet_tutari += line
                        except Exception as e:
                            logger.warning(f"bot-sync: zorunlu hizmet ekleme hata ({plaka}): {e}")
                        ek_hizmet_tutari = round(ek_hizmet_tutari, 2)
                        toplam_tutar = round(arac_tutari + ek_hizmet_tutari, 2)
                        new_res = {
                            "id": str(uuid.uuid4()),
                            "customer_id": customer["id"],
                            "vehicle_id": db_vehicle["id"],
                            "vehicle_snapshot": {
                                "plaka": db_vehicle.get("plaka"),
                                "marka": db_vehicle.get("marka"),
                                "model": db_vehicle.get("model"),
                                "foto_url": db_vehicle.get("foto_url"),
                                "gunluk_fiyat": db_vehicle.get("gunluk_fiyat"),
                            },
                            "baslangic_tarihi": start_iso,
                            "bitis_tarihi": end_iso,
                            "gun": days,
                            "paket_km": paket_km_val,
                            "kullanilan_km": max(0, int(contract_dist or 0)),
                            "ek_km": 0,
                            "ek_hizmetler": ek_hizmetler_auto,
                            "ek_hizmet_tutari": ek_hizmet_tutari,
                            "arac_tutari": arac_tutari,
                            "toplam_tutar": toplam_tutar,
                            "odenen_ucret": 0.0,
                            "kalan_odeme": toplam_tutar,
                            "odeme_yontemi": "Bot Otomatik",
                            "odeme_durumu": "beklemede",
                            "durum": "aktif",
                            "kaynak": "bot_oto",
                            "bot_contract_start": contract_start_iso,
                            "telefon": cust_phone,
                            "created_at": now_iso(),
                        }
                        await db.reservations.insert_one(new_res)
                        reservation = new_res
                        logger.info(f"bot-sync: yeni rezervasyon (aktif) oluşturuldu {plaka} → {cust_name}")
                        try:
                            await notify_admin(
                                "🚗 Yeni Rezervasyon (Bot)",
                                f"{plaka} → {cust_name} ({days} gün, {toplam_tutar:.0f}₺)",
                                {"type": "new_reservation", "reservation_id": new_res["id"], "kaynak": "bot_oto"},
                            )
                        except Exception:
                            pass
                        # Otomatik giden fatura oluştur (rezervasyon aktif olarak başladığında muhasebede yer alsın)
                        try:
                            await _create_giden_fatura(new_res)
                        except Exception as e:
                            logger.warning(f"bot-sync: otomatik fatura oluşturulamadı {plaka}: {e}")
                        await notify_customer(
                            customer["id"],
                            "Kiralama Aktifleştirildi",
                            f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) aracınızın kiralama süreci aktif. KM hakkınız: {paket_km_val:,} km. İyi yolculuklar!".replace(",", "."),
                            {"type": "reservation_activated", "reservation_id": new_res["id"]},
                        )

                    # 4) KM senkronize et + 50 km uyarısı + 0 km motor kilitleme
                    yeni_kullanilan = max(0, int(contract_dist or 0))
                    eski_kullanilan = int(reservation.get("kullanilan_km", 0) or 0)
                    paket_km_total = int(reservation.get("paket_km", 0) or 0) + int(reservation.get("ek_km_satin", 0) or 0)
                    kalan = paket_km_total - yeni_kullanilan

                    updates = {}
                    if yeni_kullanilan != eski_kullanilan:
                        updates["kullanilan_km"] = yeni_kullanilan
                        updates["bot_last_sync"] = now_iso()

                    # 50 km uyarısı (sadece oto-kilit aktifse uyarı yolla — kapalıysa müşteri rahatsız edilmesin)
                    km_oto_kilit_aktif = reservation.get("km_oto_kilit_aktif", True)
                    if km_oto_kilit_aktif and kalan <= 50 and kalan > 0 and not reservation.get("km_warning_50_sent"):
                        updates["km_warning_50_sent"] = True
                        await notify_customer(
                            customer["id"],
                            "KM Hakkınız Bitmek Üzere",
                            f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) için {kalan} km hakkınız kaldı. Tükenince araç motoru kilitlenecektir. Ek KM satın almak için 'Rezerv.' sayfasından işlem yapabilirsiniz.",
                            {"type": "km_warning_50", "reservation_id": reservation["id"], "kalan_km": kalan},
                        )

                    # 0 km motor kilitleme — bu rezervasyon için oto-kilit aktif değilse atla
                    if km_oto_kilit_aktif and kalan <= 0 and not reservation.get("motor_kilitli"):
                        ok = await bot_motor_blokaj(plaka, True)
                        updates["motor_kilitli"] = True
                        updates["motor_kilit_tarih"] = now_iso()
                        await notify_customer(
                            customer["id"],
                            "Motor Kilitlendi",
                            f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) için KM hakkınız tamamen tükendi ve araç motoru kilitlendi. Devam edebilmek için 'Rezerv.' sayfasından ek KM satın aldığınızda motor otomatik açılacaktır.",
                            {"type": "motor_locked", "reservation_id": reservation["id"]},
                        )
                        logger.info(f"bot-sync: motor kilitlendi {plaka} bot_response={ok}")
                    elif not km_oto_kilit_aktif and kalan <= 0:
                        logger.info(f"bot-sync: KM bitti ama oto-kilit kapalı, atlandı {plaka}")

                    # KM tekrar pozitife döndüyse (ek KM alındı) → motor aç
                    if kalan > 0 and reservation.get("motor_kilitli"):
                        ok = await bot_motor_blokaj(plaka, False)
                        updates["motor_kilitli"] = False
                        updates["motor_acilis_tarih"] = now_iso()
                        # km_warning_50_sent flag'i de sıfırla — yeni KM hakkı için tekrar uyarı çıksın
                        updates["km_warning_50_sent"] = False
                        await notify_customer(
                            customer["id"],
                            "Motor Açıldı",
                            f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) için yeni KM hakkınız tanımlandı ve araç motoru açıldı. İyi yolculuklar dileriz! 🚗",
                            {"type": "motor_unlocked", "reservation_id": reservation["id"]},
                        )
                        logger.info(f"bot-sync: motor açıldı {plaka} bot_response={ok}")

                    if updates:
                        await db.reservations.update_one({"id": reservation["id"]}, {"$set": updates})

                    # 5) HIZ LİMİT KONTROLÜ — DeviceSpeed > limit ise müşteri + admin'e push (5dk debounce)
                    try:
                        dev_speed = bv.get("DeviceSpeed")
                        if dev_speed is not None:
                            dev_speed = int(dev_speed)
                            hiz_limit = int(db_vehicle.get("hiz_limit") or 120)
                            if dev_speed > hiz_limit:
                                last_alert = reservation.get("speed_alert_last_at")
                                now_dt = datetime.now(timezone.utc)
                                send_now = True
                                if last_alert:
                                    try:
                                        last_dt = parse_iso(last_alert)
                                        if (now_dt - last_dt).total_seconds() < 300:  # 5 dk debounce
                                            send_now = False
                                    except Exception:
                                        pass
                                if send_now:
                                    msg = f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) — Anlık hız: {dev_speed} km/h (limit: {hiz_limit} km/h). Lütfen hız sınırına uyun."
                                    await notify_customer(
                                        customer["id"],
                                        "Hız Limit Aşımı",
                                        msg,
                                        {"type": "speed_violation", "reservation_id": reservation["id"], "speed": dev_speed, "limit": hiz_limit},
                                    )
                                    # Admin'e de in-app bildirim (push token olan adminlere)
                                    await db.notifications.insert_one({
                                        "id": str(uuid.uuid4()),
                                        "baslik": "Hız İhlali (Admin)",
                                        "mesaj": f"{plaka} aracı {dev_speed} km/h hızla seyrediyor (limit {hiz_limit}). Müşteri: {customer.get('ad','')} {customer.get('soyad','')}",
                                        "hedef_type": "admin",
                                        "tarih": now_iso(), "okuyanlar": [],
                                    })
                                    # Audit log
                                    await db.speed_violations.insert_one({
                                        "id": str(uuid.uuid4()),
                                        "reservation_id": reservation["id"],
                                        "customer_id": customer["id"],
                                        "vehicle_id": db_vehicle["id"],
                                        "plaka": plaka,
                                        "speed": dev_speed,
                                        "limit": hiz_limit,
                                        "lat": bv.get("DeviceLatitude"),
                                        "lon": bv.get("DeviceLongitude"),
                                        "tarih": now_iso(),
                                    })
                                    await db.reservations.update_one(
                                        {"id": reservation["id"]},
                                        {"$set": {"speed_alert_last_at": now_iso()}}
                                    )
                                    logger.info(f"bot-sync: hız ihlali {plaka} speed={dev_speed} > limit={hiz_limit}")
                    except Exception as e:
                        logger.warning(f"bot-sync speed check error ({plaka}): {e}")
                except Exception as e:
                    logger.warning(f"bot-sync vehicle loop error ({bv.get('PlateNumber','?')}): {e}")
        except Exception as e:
            logger.warning(f"bot-sync outer error: {e}")
        await asyncio.sleep(30)  # 30 saniyede bir senkronize et

# ==================== PUBLIC ====================
@api.get("/")
async def root():
    return {"app": "YS Auto", "version": "2.0.0", "status": "online"}

# ==================== AUTH ====================
@api.get("/me")
async def get_my_profile(user: dict = Depends(require_customer)):
    """Müşterinin kendi profilini döndürür (ad, soyad, telefon, email, adres, tip vb.)"""
    cust = await db.customers.find_one({"id": user["id"]}, {"_id": 0, "tc_norm": 0})
    if not cust:
        raise HTTPException(404, "Müşteri bulunamadı")
    return cust

@api.post("/auth/customer/login", response_model=TokenOut)
async def customer_login(body: CustomerLoginIn):
    cust = None
    # 1) Telefonla giriş (Ad+Soyad şart değil — botla otomatik kayıt olmuş olabilir)
    if body.telefon:
        phone_norm = normalize_phone(body.telefon)
        if len(phone_norm) != 10:
            raise HTTPException(400, "Telefon numarası geçersiz (10 haneli olmalı)")
        cust = await db.customers.find_one({"telefon_norm": phone_norm}, {"_id": 0})
        if not cust:
            # Geri uyumluluk: telefon_norm yoksa eski 'telefon' alanını taraması
            all_custs = await db.customers.find({}, {"_id": 0}).to_list(2000)
            for c in all_custs:
                if normalize_phone(c.get("telefon", "")) == phone_norm:
                    cust = c
                    # Geri yazıp arama hızlansın
                    await db.customers.update_one({"id": c["id"]}, {"$set": {"telefon_norm": phone_norm}})
                    break
        if not cust:
            raise HTTPException(404, "Bu telefon ile kayıtlı müşteri bulunamadı. Lütfen yetkili ile iletişime geçin.")
    # 2) TC + Ad + Soyad ile klasik giriş
    elif body.tc:
        tc = normalize_tc(body.tc)
        if len(tc) != 11:
            raise HTTPException(400, "TC Kimlik Numarası 11 haneli olmalıdır")
        cust = await db.customers.find_one({"tc_norm": tc}, {"_id": 0})
        if not cust:
            raise HTTPException(404, "Bu TC Kimlik No ile kayıtlı müşteri bulunamadı. Lütfen yetkili ile iletişime geçin.")
        if normalize_name(cust["ad"]) != normalize_name(body.ad or "") or normalize_name(cust["soyad"]) != normalize_name(body.soyad or ""):
            raise HTTPException(401, "Ad veya soyad TC Kimlik No ile eşleşmiyor")
    else:
        raise HTTPException(400, "TC Kimlik No veya Telefon gerekli")
    if cust.get("blocked"):
        raise HTTPException(403, cust.get("block_reason") or "Hesabınız askıya alındı.")
    return TokenOut(token=make_token(cust["id"], "customer", tenant_id=cust.get("tenant_id")), role="customer", user={
        "id": cust["id"], "ad": cust["ad"], "soyad": cust["soyad"],
        "telefon": cust.get("telefon"), "email": cust.get("email"),
    })
async def admin_login(body: AdminLoginIn):
    a = None
    # 1) Ad+Soyad+TC ile giriş (yeni yöntem)
    if body.tc:
        tc = normalize_tc(body.tc)
        if len(tc) != 11:
            raise HTTPException(400, "TC Kimlik Numarası 11 haneli olmalıdır")
        a = await db.admins.find_one({"tc_norm": tc})
        if a:
            ad_norm = normalize_name(body.ad or "")
            soyad_norm = normalize_name(body.soyad or "")
            if ad_norm and normalize_name(a.get("ad", "")) != ad_norm:
                raise HTTPException(401, "Ad TC ile eşleşmiyor")
            if soyad_norm and normalize_name(a.get("soyad", "")) != soyad_norm:
                raise HTTPException(401, "Soyad TC ile eşleşmiyor")
    # 2) Geri uyumluluk: kullanıcı adı + şifre ile giriş
    elif body.kullanici_adi and body.sifre:
        a = await db.admins.find_one({"kullanici_adi": body.kullanici_adi})
        if not a or not a.get("password_hash") or not verify_pw(body.sifre, a["password_hash"]):
            raise HTTPException(401, "Kullanıcı adı veya şifre hatalı")
    else:
        raise HTTPException(400, "Ad, soyad ve TC gerekli")
    if not a:
        raise HTTPException(404, "Bu bilgilerle kayıtlı yönetici bulunamadı")
    return TokenOut(token=make_token(a["id"], "admin", tenant_id=a.get("tenant_id"), is_super=bool(a.get("is_super")) or a.get("tc_norm") in SUPER_ADMIN_TCS), role="admin", user={
        "id": a["id"], "ad": a["ad"], "soyad": a.get("soyad"),
        "kullanici_adi": a.get("kullanici_adi"), "tc": a.get("tc_norm"),
    })

# ==================== BİRLEŞİK GİRİŞ — Önce Admin sonra Müşteri ====================
class UnifiedLoginIn(BaseModel):
    ad: str
    soyad: str
    tc: str

@api.post("/auth/login", response_model=TokenOut)
async def unified_login(body: UnifiedLoginIn):
    """Birleşik giriş: önce admin TC'sini kontrol eder, bulamazsa müşteri olarak dener."""
    tc = normalize_tc(body.tc)
    if len(tc) != 11:
        raise HTTPException(400, "TC Kimlik Numarası 11 haneli olmalıdır")
    ad_norm = normalize_name(body.ad)
    soyad_norm = normalize_name(body.soyad)
    if not ad_norm or not soyad_norm:
        raise HTTPException(400, "Ad ve soyad zorunlu")

    # 1) Admin tablosunda ara
    admin = await db.admins.find_one({"tc_norm": tc})
    if admin:
        if normalize_name(admin.get("ad", "")) != ad_norm:
            raise HTTPException(401, "Ad TC ile eşleşmiyor")
        if normalize_name(admin.get("soyad", "")) != soyad_norm:
            raise HTTPException(401, "Soyad TC ile eşleşmiyor")
        is_super = bool(admin.get("is_super")) or admin.get("tc_norm") in SUPER_ADMIN_TCS
        return TokenOut(token=make_token(admin["id"], "admin", tenant_id=admin.get("tenant_id"), is_super=is_super), role="admin", user={
            "id": admin["id"], "ad": admin["ad"], "soyad": admin.get("soyad"),
            "kullanici_adi": admin.get("kullanici_adi"), "tc": admin.get("tc_norm"),
        })

    # 2) Konsinye (araç sahibi) tablosunda ara
    kons = await db.konsinyatorler.find_one({"tc_norm": tc}, {"_id": 0})
    if kons:
        if normalize_name(kons.get("ad", "")) != ad_norm:
            raise HTTPException(401, "Ad TC ile eşleşmiyor")
        if normalize_name(kons.get("soyad", "")) != soyad_norm:
            raise HTTPException(401, "Soyad TC ile eşleşmiyor")
        if not kons.get("aktif", True):
            raise HTTPException(403, "Hesabınız aktif değil. Yetkili ile iletişime geçin.")
        return TokenOut(token=make_token(kons["id"], "konsinye", tenant_id=kons.get("tenant_id")), role="konsinye", user={
            "id": kons["id"], "ad": kons["ad"], "soyad": kons.get("soyad"),
            "telefon": kons.get("telefon"), "email": kons.get("email"),
        })

    # 3) Müşteri olarak ara
    cust = await db.customers.find_one({"tc_norm": tc}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Bu TC ile kayıtlı kullanıcı bulunamadı. Lütfen yetkili ile iletişime geçin.")
    if normalize_name(cust["ad"]) != ad_norm or normalize_name(cust["soyad"]) != soyad_norm:
        raise HTTPException(401, "Ad veya soyad TC ile eşleşmiyor")
    if cust.get("blocked"):
        raise HTTPException(403, cust.get("block_reason") or "Hesabınız askıya alındı.")
    return TokenOut(token=make_token(cust["id"], "customer", tenant_id=cust.get("tenant_id")), role="customer", user={
        "id": cust["id"], "ad": cust["ad"], "soyad": cust["soyad"],
        "telefon": cust.get("telefon"), "email": cust.get("email"),
    })

# ==================== ADMIN KULLANICI YÖNETİMİ ====================
class AdminUserIn(BaseModel):
    ad: str
    soyad: str
    tc: str
    telefon: Optional[str] = None
    email: Optional[str] = None

@api.get("/admin/admins")
async def list_admins(_: dict = Depends(require_admin)):
    rows = await db.admins.find({}, {"_id": 0, "password_hash": 0}).sort("created_at", 1).to_list(200)
    return rows

@api.post("/admin/admins")
async def create_admin(body: AdminUserIn, user: dict = Depends(require_admin)):
    tc = normalize_tc(body.tc)
    if len(tc) != 11:
        raise HTTPException(400, "TC Kimlik Numarası 11 haneli olmalıdır")
    if not body.ad.strip() or not body.soyad.strip():
        raise HTTPException(400, "Ad ve soyad zorunlu")
    # Çakışma kontrolü: aynı TC ile admin veya müşteri varsa hata
    if await db.admins.find_one({"tc_norm": tc}):
        raise HTTPException(400, "Bu TC ile zaten bir yönetici kayıtlı")
    if await db.customers.find_one({"tc_norm": tc}):
        raise HTTPException(400, "Bu TC ile bir müşteri kayıtlı — yönetici eklenemez")
    doc = {
        "id": str(uuid.uuid4()),
        "ad": body.ad.strip(),
        "soyad": body.soyad.strip(),
        "tc_norm": tc,
        "telefon": (body.telefon or "").strip() or None,
        "email": (body.email or "").strip() or None,
        "created_at": now_iso(),
        **tenant_stamp(user),
    }
    await db.admins.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api.put("/admin/admins/{aid}")
async def update_admin(aid: str, body: AdminUserIn, _: dict = Depends(require_admin)):
    tc = normalize_tc(body.tc)
    if len(tc) != 11:
        raise HTTPException(400, "TC Kimlik Numarası 11 haneli olmalıdır")
    existing = await db.admins.find_one({"id": aid})
    if not existing:
        raise HTTPException(404, "Yönetici bulunamadı")
    # TC değiştiyse çakışma kontrolü
    if tc != existing.get("tc_norm"):
        if await db.admins.find_one({"tc_norm": tc, "id": {"$ne": aid}}):
            raise HTTPException(400, "Bu TC ile zaten bir yönetici kayıtlı")
        if await db.customers.find_one({"tc_norm": tc}):
            raise HTTPException(400, "Bu TC ile bir müşteri kayıtlı")
    await db.admins.update_one({"id": aid}, {"$set": {
        "ad": body.ad.strip(),
        "soyad": body.soyad.strip(),
        "tc_norm": tc,
        "telefon": (body.telefon or "").strip() or None,
        "email": (body.email or "").strip() or None,
    }})
    return {"ok": True}

@api.delete("/admin/admins/{aid}")
async def delete_admin(aid: str, user: dict = Depends(require_admin)):
    if aid == user["id"]:
        raise HTTPException(400, "Kendi hesabınızı silemezsiniz")
    total = await db.admins.count_documents({})
    if total <= 1:
        raise HTTPException(400, "Son yönetici silinemez")
    res = await db.admins.delete_one({"id": aid})
    if res.deleted_count == 0:
        raise HTTPException(404, "Yönetici bulunamadı")
    return {"ok": True}

# ==================== Kaynak Kod ZIP İndirme (Admin Only) ====================
from fastapi.responses import FileResponse

@api.get("/admin/download/source")
async def download_source(_: dict = Depends(require_admin)):
    """Admin için kaynak kod ZIP'ini indirir.
    /app/backend/downloads/ysauto_source.zip dosyasını döndürür."""
    import os
    path = "/app/backend/downloads/ysauto_source.zip"
    if not os.path.exists(path):
        raise HTTPException(404, "ZIP henüz oluşturulmamış. Lütfen admin'e haber verin.")
    return FileResponse(path, media_type="application/zip", filename="ysauto_source.zip")

@api.get("/download/source-public")
async def download_source_public(token: str = "", kind: str = "full"):
    """Genel indirme — sadece doğru token ile.
    kind=full → tüm backend zip, kind=minimal → sadece server.py + requirements.txt"""
    expected = "ys2026dnldYS"
    if token != expected:
        raise HTTPException(403, "Geçersiz indirme token'ı")
    import os
    if kind == "minimal":
        path = "/app/backend/downloads/ysauto_minimal.zip"
        fname = "ysauto_minimal.zip"
    elif kind == "backup":
        path = "/app/backend/downloads/ysauto_full_backup.zip"
        fname = "ysauto_full_backup.zip"
    else:
        path = "/app/backend/downloads/ysauto_source.zip"
        fname = "ysauto_source.zip"
    if not os.path.exists(path):
        raise HTTPException(404, "ZIP bulunamadı")
    return FileResponse(path, media_type="application/zip", filename=fname)

@api.get("/auth/me")
async def auth_me(user: dict = Depends(get_current_user)):
    role = user["role"]
    if role == "customer":
        w = await get_wallet(user["id"])
        return {"role": "customer", "user": {
            "id": user["id"], "ad": user["ad"], "soyad": user["soyad"],
            "telefon": user.get("telefon"), "email": user.get("email"),
            "bakiye": w["bakiye"],
        }}
    if role == "konsinye":
        return {"role": "konsinye", "user": {
            "id": user["id"], "ad": user["ad"], "soyad": user.get("soyad"),
            "telefon": user.get("telefon"), "email": user.get("email"),
        }}
    return {"role": "admin", "user": {"id": user["id"], "ad": user["ad"], "kullanici_adi": user["kullanici_adi"]}}

# ==================== Push Token Kayıt ====================
class PushTokenIn(BaseModel):
    token: str
    platform: Optional[str] = None  # 'ios' | 'android' | 'web'

@api.post("/push/register")
async def register_push_token(body: PushTokenIn, user: dict = Depends(require_customer)):
    token = (body.token or "").strip()
    if not token.startswith("ExponentPushToken[") or not token.endswith("]"):
        raise HTTPException(400, "Geçersiz Expo push token formatı")
    # upsert by token (her cihazda 1 token)
    await db.push_tokens.update_one(
        {"token": token},
        {"$set": {
            "token": token,
            "customer_id": user["id"],
            "platform": body.platform or "unknown",
            "updated_at": now_iso(),
        }, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True}

@api.post("/push/unregister")
async def unregister_push_token(body: PushTokenIn, user: dict = Depends(require_customer)):
    await db.push_tokens.delete_one({"token": body.token, "customer_id": user["id"]})
    return {"ok": True}

@api.post("/admin/push/register")
async def admin_register_push_token(body: PushTokenIn, user: dict = Depends(require_admin)):
    """Admin (yetkili / konsinye dahil) Expo push token kaydı."""
    token = (body.token or "").strip()
    if not token.startswith("ExponentPushToken[") or not token.endswith("]"):
        raise HTTPException(400, "Geçersiz Expo push token formatı")
    await db.push_tokens.update_one(
        {"token": token},
        {"$set": {
            "token": token,
            "admin_id": user["id"],
            "platform": body.platform or "unknown",
            "updated_at": now_iso(),
        }, "$setOnInsert": {"created_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True}

@api.post("/admin/push/unregister")
async def admin_unregister_push_token(body: PushTokenIn, user: dict = Depends(require_admin)):
    await db.push_tokens.delete_one({"token": body.token, "admin_id": user["id"]})
    return {"ok": True}

@api.post("/admin/push/test")
async def admin_send_test_push(user: dict = Depends(require_admin)):
    """Mevcut admin'in cihazına test bildirimi yollar."""
    docs = await db.push_tokens.find({"admin_id": user["id"]}, {"_id": 0, "token": 1}).to_list(20)
    tokens = [d["token"] for d in docs if d.get("token", "").startswith("ExponentPushToken[")]
    if not tokens:
        return {"sent": 0, "detail": "Cihaz token'ı bulunamadı. Lütfen mobil uygulamadan giriş yapın ve bildirim izni verin."}
    messages = [
        {
            "to": t, "sound": "default", "priority": "high", "channelId": "default",
            "title": "🔔 YS Auto Test",
            "body": "Bildirim sistemi çalışıyor! Tıklayarak uygulamayı açabilirsiniz.",
            "data": {"type": "test"},
        } for t in tokens
    ]
    try:
        async with httpx.AsyncClient(timeout=8.0) as c:
            r = await c.post(EXPO_PUSH_URL, json=messages, headers={"Content-Type": "application/json"})
            ok = r.status_code == 200
            return {"sent": len(tokens) if ok else 0, "detail": "OK" if ok else f"Expo hata: {r.status_code} {r.text[:200]}"}
    except Exception as e:
        return {"sent": 0, "detail": f"Hata: {e}"}

# ==================== CUSTOMER: Vehicles ====================
@api.get("/vehicles")
async def list_vehicles(user: dict = Depends(require_customer)):
    # ⚡ Liste yanıtında BÜYÜK alanları HARİÇ tut (fotograflar detayda yüklenir)
    proj = {"_id": 0, "fotograflar": 0, "aciklama_detay": 0, "kontrat_html": 0}
    docs = await db.vehicles.find({}, proj).sort([("siralama", 1), ("gunluk_fiyat", 1)]).to_list(200)
    # Mesai başı saatini ve TR saatini al
    s = await get_settings()
    mesai_baslangic = s.get("mesai_baslangic", "09:00")
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    now_utc = _dt.now(_tz.utc)

    # ⚡ N+1 fix: Tüm araçların aktif rezervasyonlarını TEK sorguda çek
    vehicle_ids = [v["id"] for v in docs]
    all_active_rezler = await db.reservations.find(
        {"vehicle_id": {"$in": vehicle_ids}, "durum": {"$in": ["aktif", "onaylandi"]}},
        {"_id": 0, "vehicle_id": 1, "baslangic_tarihi": 1, "bitis_tarihi": 1},
    ).to_list(2000)
    # vehicle_id'ye göre grupla
    rez_by_vehicle: dict[str, list] = {}
    for r in all_active_rezler:
        rez_by_vehicle.setdefault(r["vehicle_id"], []).append(r)

    out = []
    for v in docs:
        v["durum"] = await compute_vehicle_status(v)
        active_rezler = rez_by_vehicle.get(v["id"], [])
        current_rez = None  # Şu an kirada
        next_rez = None  # En yakın gelecek rez
        prev_end = None  # En son biten rez bitişi (geçmiş, son 24 saat içinde)
        overdue_rez = None  # 🆕 Bitiş tarihi 5+ dakika geçmiş ama hala aktif (teslim edilmedi)
        for r in active_rezler:
            try:
                bas = parse_iso(r["baslangic_tarihi"])
                bit = parse_iso(r["bitis_tarihi"])
            except Exception:
                continue
            if bas <= now_utc < bit:
                current_rez = {"bas": bas.isoformat(), "bit": bit.isoformat()}
            elif bas > now_utc:
                if next_rez is None or bas < parse_iso(next_rez["bas"]):
                    next_rez = {"bas": bas.isoformat(), "bit": bit.isoformat()}
            elif bit <= now_utc and (now_utc - bit) <= _td(hours=24):
                # Son 24 saat içinde biten
                if prev_end is None or bit > parse_iso(prev_end):
                    prev_end = bit.isoformat()
            # 🆕 GECİKMİŞ TESLİM: 5+ dakika geçmiş hala aktif rez
            if bit < now_utc - _td(minutes=5):
                if overdue_rez is None or bit > parse_iso(overdue_rez["bit"]):
                    overdue_rez = {"bit": bit.isoformat()}
        # Durum hesabı: kirada > yıkamada > musait
        # NOT: Gecikmiş teslim ana sayfada "yıkamada" olarak görünür (kullanıcı talebi).
        # Engelleme rezervasyon oluşturma anında 423 hatası ile yapılır.
        availability_status = "musait"
        availability_info = {}
        if current_rez:
            availability_status = "kirada"
            availability_info["return_at"] = current_rez["bit"]
        elif prev_end:
            # 1 saat içinde mi bitti?
            prev_end_dt = parse_iso(prev_end)
            cleaning_done_at = prev_end_dt + _td(hours=1)
            if now_utc < cleaning_done_at:
                availability_status = "yikamada"
                availability_info["ready_at"] = cleaning_done_at.isoformat()
                availability_info["dakika_kaldi"] = max(0, int((cleaning_done_at - now_utc).total_seconds() / 60))
            # else: zaten 1 saat geçmiş, müsait
        v["availability_status"] = availability_status
        v["availability_info"] = availability_info
        v["next_reservation_at"] = next_rez["bas"] if next_rez else None
        out.append(v)
    return out

@api.get("/vehicles/{vid}")
async def vehicle_detail(vid: str, user: dict = Depends(require_customer)):
    v = await db.vehicles.find_one({"id": vid}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    v["durum"] = await compute_vehicle_status(v)
    return v

@api.get("/vehicles/{vid}/availability")
async def vehicle_availability(vid: str, user: dict = Depends(require_customer)):
    """Müsaitlik takvim verisi:
    - blocked_ranges: bu araç için meşgul tarih aralıkları (ISO start/end)
    - holidays: tatil tarihleri (YYYY-MM-DD)
    - blocked_weekdays: haftada bloklu günler [0..6] (0=Pzt..6=Pzr)
    - mesai: { start: 'HH:MM', end: 'HH:MM' }
    - tampon_saat: peş peşe rezervasyonlar arası min boşluk (saat)
    - suggested_start / suggested_end: müşteri açısından önerilen en yakın müsait aralık (ISO)
    """
    v = await db.vehicles.find_one({"id": vid}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")

    # Dolu rezervasyonlar (bu araç için)
    docs = await db.reservations.find(
        {"vehicle_id": vid, "durum": {"$in": ["beklemede", "onaylandi", "aktif"]}},
        {"_id": 0, "baslangic_tarihi": 1, "bitis_tarihi": 1},
    ).to_list(500)

    # Müşterinin BAŞKA araçlardaki aktif rezervasyonları (kendisinin çakışan rez'leri)
    customer_docs = await db.reservations.find(
        {
            "customer_id": user["id"],
            "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
            "vehicle_id": {"$ne": vid},
        },
        {"_id": 0, "baslangic_tarihi": 1, "bitis_tarihi": 1, "vehicle_snapshot": 1},
    ).to_list(50)

    s = await get_settings()
    holidays_docs = await db.holidays.find({}, {"_id": 0, "tarih": 1, "aciklama": 1}).to_list(500)

    # YENİ: Önerilen en yakın müsait aralık hesabı
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    now_utc = _dt.now(_tz.utc)
    mesai_baslangic_str = s.get("mesai_baslangic", "09:00")
    try:
        mh, mm = [int(x) for x in mesai_baslangic_str.split(":")]
    except Exception:
        mh, mm = 9, 0
    # Önceki rez bitişi (geçmişte bitenler VEYA şu an aktif olanların bitişi — yıkama tamponu için)
    prev_end = None
    next_start = None
    for d in docs:
        try:
            b = parse_iso(d["baslangic_tarihi"])
            e = parse_iso(d["bitis_tarihi"])
        except Exception:
            continue
        # Eğer rez bitmiş VEYA şu an aktif ise (start <= now < end) — bitişini prev_end olarak al
        if e > now_utc and b <= now_utc:
            # Şu an aktif: prev_end'i bunun bitişine zorla (en geç olanı seç)
            if prev_end is None or e > prev_end:
                prev_end = e
        elif e <= now_utc:
            # Geçmiş rez
            if prev_end is None or e > prev_end:
                prev_end = e
        elif b > now_utc:
            # Gelecek rez (next_start kontrolü prev_end set edildikten sonra yapılır)
            if next_start is None or b < next_start:
                next_start = b
    # Suggested start: max(prev_end, bugün mesai başı TR) + 1 saat yıkama; prev_end yoksa mesai başı
    tr_offset = _td(hours=3)
    tr_now = now_utc + tr_offset
    # Bugün TR mesai başı / bitiş saatleri
    today_mesai_bas_tr = tr_now.replace(hour=mh, minute=mm, second=0, microsecond=0)
    mesai_bitis_str = s.get("mesai_bitis", "18:00")
    try:
        eh, em = [int(x) for x in mesai_bitis_str.split(":")]
    except Exception:
        eh, em = 18, 0
    today_mesai_bit_tr = tr_now.replace(hour=eh, minute=em, second=0, microsecond=0)

    def _round_up_30(dt_tr):
        """30 dakikalık slot'a yukarı yuvarla (TR yerel)"""
        if dt_tr.minute == 0 and dt_tr.second == 0:
            return dt_tr.replace(microsecond=0)
        if dt_tr.minute <= 30 and not (dt_tr.minute == 30 and dt_tr.second == 0):
            return dt_tr.replace(minute=30, second=0, microsecond=0)
        return (dt_tr + _td(hours=1)).replace(minute=0, second=0, microsecond=0)

    if prev_end:
        # prev_end TR yerel saatine çevir
        prev_end_tr = prev_end + tr_offset
        # Aynı gün mesai başı/bitiş (TR yerel)
        same_day_mesai_bas_tr = prev_end_tr.replace(hour=mh, minute=mm, second=0, microsecond=0)
        same_day_mesai_bit_tr = prev_end_tr.replace(hour=eh, minute=em, second=0, microsecond=0)
        if prev_end_tr < same_day_mesai_bas_tr:
            # Mesai başlamadan döndü → bugün mesai başı + 1 saat yıkama
            suggested_start_tr = same_day_mesai_bas_tr + _td(hours=1)
        elif prev_end_tr > same_day_mesai_bit_tr:
            # Mesai bittikten sonra döndü → yarın mesai başı + 1 saat yıkama
            next_day_tr = (prev_end_tr + _td(days=1)).replace(hour=mh, minute=mm, second=0, microsecond=0)
            suggested_start_tr = next_day_tr + _td(hours=1)
        else:
            # Mesai içinde döndü → bitiş + 1 saat yıkama
            suggested_start_tr = prev_end_tr + _td(hours=1)
        # ✨ Eğer suggested_start hala geçmişteyse ve şu an mesai içindeyse → şu anki saate yuvarla
        if suggested_start_tr <= tr_now and today_mesai_bas_tr <= tr_now <= today_mesai_bit_tr:
            suggested_start_tr = _round_up_30(tr_now)
        suggested_start = suggested_start_tr - tr_offset
    else:
        # ✨ Hiç önceki rez yok (temiz araç) → ŞU AN mesai içindeyse şu ana yuvarla, değilse mesai başı
        if today_mesai_bas_tr <= tr_now <= today_mesai_bit_tr:
            # Şu an mesai içinde → şu ana yuvarla
            suggested_start_tr = _round_up_30(tr_now)
        elif tr_now < today_mesai_bas_tr:
            # Mesai henüz başlamadı → bugün mesai başı
            suggested_start_tr = today_mesai_bas_tr
        else:
            # Mesai bitti → yarın mesai başı
            suggested_start_tr = (today_mesai_bas_tr + _td(days=1))
        suggested_start = suggested_start_tr - tr_offset
    # Tatil/Pazar gününü atla (suggested_start'ı sonraki müsait güne kaydır)
    blocked_wd = s.get("tatil_haftaici_gunler") or [6]  # default: Pazar
    holidays_set = set(h["tarih"] for h in holidays_docs)
    def _is_blocked_day(dt_utc):
        # TR yerel günü hesapla
        tr_local = dt_utc + tr_offset
        ymd = tr_local.strftime("%Y-%m-%d")
        if ymd in holidays_set:
            return True
        if tr_local.weekday() in blocked_wd:
            return True
        return False
    # En fazla 14 gün ileri zorla
    guard = 0
    while _is_blocked_day(suggested_start) and guard < 14:
        # Bir sonraki gün mesai başına git
        suggested_start = (suggested_start + _td(days=1)).replace(hour=mh, minute=mm, second=0, microsecond=0) - tr_offset
        # TR yerel mesai başını UTC'ye çevir: aslında saat değeri TR yerel olarak ayarlanmalı
        suggested_start_tr = suggested_start + tr_offset
        suggested_start_tr = suggested_start_tr.replace(hour=mh, minute=mm, second=0, microsecond=0)
        suggested_start = suggested_start_tr - tr_offset
        guard += 1
    # Suggested end: next_start - 1 saat veya suggested_start + 1 gün
    if next_start:
        suggested_end = next_start - _td(hours=1)
        if suggested_end <= suggested_start:
            suggested_end = suggested_start + _td(days=1)
    else:
        suggested_end = suggested_start + _td(days=1)
    # İade tarihini de pazar/tatilden kaydır (mesai bitiş saatine çek)
    mesai_bitis_str = s.get("mesai_bitis", "18:00")
    try:
        eh, em = [int(x) for x in mesai_bitis_str.split(":")]
    except Exception:
        eh, em = 18, 0
    guard = 0
    while _is_blocked_day(suggested_end) and guard < 14:
        suggested_end_tr = suggested_end + tr_offset
        suggested_end_tr = (suggested_end_tr + _td(days=1)).replace(hour=eh, minute=em, second=0, microsecond=0)
        suggested_end = suggested_end_tr - tr_offset
        guard += 1

    return {
        "blocked_ranges": [
            {"start": d["baslangic_tarihi"], "end": d["bitis_tarihi"]} for d in docs
        ],
        "customer_blocked_ranges": [
            {
                "start": d["baslangic_tarihi"],
                "end": d["bitis_tarihi"],
                "plaka": d.get("vehicle_snapshot", {}).get("plaka", ""),
            }
            for d in customer_docs
        ],
        "holidays": [{"tarih": h["tarih"], "aciklama": h.get("aciklama", "")} for h in holidays_docs],
        "blocked_weekdays": s.get("tatil_haftaici_gunler") or [6],
        "mesai": {
            "start": s.get("mesai_baslangic", "09:00"),
            "end": s.get("mesai_bitis", "18:00"),
        },
        "tampon_saat": 1,
        "suggested_start": suggested_start.isoformat(),
        "suggested_end": suggested_end.isoformat(),
        "prev_reservation_end": prev_end.isoformat() if prev_end else None,
        "next_reservation_start": next_start.isoformat() if next_start else None,
    }

# ==================== CUSTOMER: Services ====================
@api.get("/services")
async def list_services(user: dict = Depends(require_customer), vehicle_id: Optional[str] = None):
    docs = await db.services.find({"aktif": True}, {"_id": 0}).sort("siralama", 1).to_list(50)
    if vehicle_id:
        # Sadece bu araca uygun olanları filtrele (arac_ids boş = tüm araçlar)
        docs = [d for d in docs if not d.get("arac_ids") or vehicle_id in d.get("arac_ids", [])]
    return docs

# ==================== CUSTOMER: Available vehicles in window (extend için alternatif) ====================
class AvailableQuery(BaseModel):
    baslangic_tarihi: str
    bitis_tarihi: str
    exclude_vehicle_id: Optional[str] = None

@api.post("/vehicles/available")
async def list_available_vehicles(body: AvailableQuery, user: dict = Depends(require_customer)):
    """Belirtilen tarih aralığında müsait olan araçları döner (1 saat tampon dahil)."""
    bas = parse_iso(body.baslangic_tarihi)
    bit = parse_iso(body.bitis_tarihi)
    if bit <= bas:
        raise HTTPException(400, "Bitiş başlangıçtan sonra olmalı")
    bas_ext = (bas - timedelta(hours=1)).isoformat()
    bit_ext = (bit + timedelta(hours=1)).isoformat()

    # Çakışan rezervasyonları olan araç id'leri
    busy_pipeline = [
        {"$match": {
            "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
            "baslangic_tarihi": {"$lt": bit_ext},
            "bitis_tarihi": {"$gt": bas_ext},
        }},
        {"$group": {"_id": "$vehicle_id"}},
    ]
    busy_ids = set()
    async for doc in db.reservations.aggregate(busy_pipeline):
        busy_ids.add(doc["_id"])

    query: dict = {"durum": {"$ne": "bakim"}}
    if body.exclude_vehicle_id:
        query["id"] = {"$ne": body.exclude_vehicle_id}

    vehicles = await db.vehicles.find(query, {"_id": 0}).sort("marka", 1).to_list(500)
    available = [v for v in vehicles if v["id"] not in busy_ids]
    return {"available": available, "count": len(available)}

# ==================== CUSTOMER: Extend Quote (uzatma fiyat hesabı) ====================
class ExtendQuoteIn(BaseModel):
    yeni_bitis_tarihi: str
    secilen_hizmetler: List[ServiceSelection] = []
    ek_km: int = 0  # Müşterinin uzatma sırasında satın aldığı ek km

@api.post("/reservations/{rid}/extend-quote")
async def extend_quote(rid: str, body: ExtendQuoteIn, user: dict = Depends(require_customer)):
    r = await db.reservations.find_one({"id": rid, "customer_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if r["durum"] not in ("onaylandi", "aktif"):
        raise HTTPException(400, "Sadece aktif/onaylı rezervasyonlar uzatılabilir")
    eski_bit = parse_iso(r["bitis_tarihi"])
    yeni_bit = parse_iso(body.yeni_bitis_tarihi)
    if yeni_bit <= eski_bit:
        raise HTTPException(400, "Yeni bitiş tarihi mevcut bitiş tarihinden sonra olmalı")

    # Validate calendar/business hours for new end date
    h = await is_holiday(yeni_bit)
    if h:
        return {"ok": False, "blocked_reason": "tatil", "message": f"Yeni iade tarihi: {h}"}
    bh = await is_within_business_hours(yeni_bit)
    if bh:
        # 🆕 Eğer rezervasyon başlangıç saati de mesai dışıysa (admin manuel oluşturduysa)
        # ve uzatma da aynı saat civarındaysa, mesai kontrolünü atla
        try:
            eski_bas = parse_iso(r["baslangic_tarihi"])
            bas_bh = await is_within_business_hours(eski_bas)
            tr_bas = eski_bas + timedelta(hours=3)
            tr_yeni = yeni_bit + timedelta(hours=3)
            ayni_saat = (tr_bas.hour == tr_yeni.hour and abs(tr_bas.minute - tr_yeni.minute) <= 10)
            if bas_bh and ayni_saat:
                pass  # Bypass — orijinal rez de mesai dışı, aynı saatte uzatma izin verilsin
            else:
                return {"ok": False, "blocked_reason": "mesai", "message": f"Yeni iade saati: {bh}"}
        except Exception:
            return {"ok": False, "blocked_reason": "mesai", "message": f"Yeni iade saati: {bh}"}

    # Çakışma kontrolü
    yeni_bit_ext = (yeni_bit + timedelta(hours=1)).isoformat()
    eski_bas_ext = (parse_iso(r["baslangic_tarihi"]) - timedelta(hours=1)).isoformat()
    conflict = await db.reservations.find_one({
        "vehicle_id": r["vehicle_id"],
        "id": {"$ne": rid},
        "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
        "baslangic_tarihi": {"$lt": yeni_bit_ext},
        "bitis_tarihi": {"$gt": eski_bas_ext},
    })
    if conflict:
        return {"ok": False, "blocked_reason": "cakisma", "message": "Bu araç seçtiğiniz uzatma tarihinde başka bir rezervasyon ile çakışıyor."}

    ek_gun = calc_days(eski_bit, yeni_bit)
    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    s = await get_settings()
    fallback_min = s.get("indirim_min_gun", 2)
    fallback_yuzde = s.get("indirim_yuzde", 10.0)

    # NEW: Süre indirimi — toplam (eski + yeni) gün baz alınarak hesaplanır.
    # Daha önce uygulanmış indirim ile farkı tahsil edilir/düşülür.
    eski_gun = int(r.get("gun_sayisi") or 0)
    yeni_toplam_gun = eski_gun + ek_gun
    # NEW: Günlük fiyat kademesi — uzatma yapıldığında YENİ günler, yeni toplam gün
    # için geçerli kademe fiyatından hesaplanır (eski günler değişmez).
    yeni_gunluk_fiyat = daily_price_for(v, yeni_toplam_gun)
    yeni_base_total = yeni_gunluk_fiyat * yeni_toplam_gun
    eski_indirim_uygulanmis = float((r.get("pricing") or {}).get("sure_indirim_tutar") or r.get("sure_indirim_tutar") or 0)
    yeni_total_indirim = sure_indirim_for(v, yeni_toplam_gun, yeni_base_total, fallback_min, fallback_yuzde)
    ek_indirim = round(max(0.0, yeni_total_indirim - eski_indirim_uygulanmis), 2)
    ek_base = round(yeni_gunluk_fiyat * ek_gun, 2)
    ek_arac = round(max(0.0, ek_base - ek_indirim), 2)

    # Ek hizmetler — uzatma için seçilen ekstralar (zorunlu hizmetler hariç tutulur)
    services_total = 0.0
    services_breakdown = []
    if body.secilen_hizmetler:
        for sel in body.secilen_hizmetler:
            svc = await db.services.find_one({"id": sel.service_id, "aktif": True}, {"_id": 0})
            if not svc or svc.get("zorunlu"):
                continue
            adet = max(1, sel.adet)
            line = svc["fiyat"] * adet * (ek_gun if svc["tip"] == "gunluk" else 1)
            services_total += line
            services_breakdown.append({
                "service_id": svc["id"], "isim": svc["isim"], "fiyat": svc["fiyat"], "tutar": round(line, 2),
            })
    services_total = round(services_total, 2)

    # Ek KM satın alma (km_asim_fiyat üzerinden) + hacim indirimi — ARAÇ BAZLI + SÜREYE GÖRE
    ek_km_buy = max(0, int(body.ek_km or 0))
    km_asim_fiyat = km_asim_for(v, s, days=yeni_toplam_gun)
    ek_km_brut = round(ek_km_buy * km_asim_fiyat, 2)
    ek_km_indirim = km_volume_indirim_for(v, s, ek_km_buy)
    ek_km_tutar = round(max(0.0, ek_km_brut - ek_km_indirim), 2)

    ek_tutar = round(ek_arac + services_total + ek_km_tutar, 2)

    # Cüzdan bakiyesi yeterli mi?
    w = await get_wallet(user["id"])
    bakiye_yeterli = w["bakiye"] >= ek_tutar

    return {
        "ok": True,
        "ek_gun": ek_gun,
        "ek_tutar": ek_tutar,
        "ek_arac_tutar": ek_arac,
        "ek_hizmet_tutar": services_total,
        "ek_hizmetler": services_breakdown,
        "ek_indirim": ek_indirim,
        "yeni_toplam_indirim": yeni_total_indirim,
        "yeni_gunluk_fiyat": yeni_gunluk_fiyat,
        "eski_gunluk_fiyat": float((r.get("pricing") or {}).get("gunluk_fiyat") or r.get("gunluk_fiyat") or 0),
        "fiyat_kademe": matched_price_kademe(v, yeni_toplam_gun),
        "fiyat_kademeleri": v.get("gunluk_fiyat_kademeleri") or [],
        "km_asim_kademe": matched_km_asim_kademe(v, yeni_toplam_gun),
        "km_asim_kademeleri": v.get("km_asim_kademeleri") or [],
        "ek_km_satin": ek_km_buy,
        "ek_km_brut": ek_km_brut,
        "ek_km_indirim": ek_km_indirim,
        "ek_km_tutar": ek_km_tutar,
        "km_asim_fiyat": km_asim_fiyat,
        "yeni_gunluk_km": daily_km_for(v, yeni_toplam_gun),
        "yeni_paket_km": int(r.get("paket_km", 0) or 0) - paket_km_for(v, eski_gun) + paket_km_for(v, yeni_toplam_gun) + ek_km_buy,
        "bakiye": w["bakiye"],
        "bakiye_yeterli": bakiye_yeterli,
        "eksik": max(0, ek_tutar - w["bakiye"]),
    }

# ==================== CUSTOMER: Pricing Quote ====================
@api.post("/quote")
async def get_quote(body: ReservationCreate, user: dict = Depends(require_customer)):
    """Returns price calculation without creating reservation."""
    v = await db.vehicles.find_one({"id": body.vehicle_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    bas = parse_iso(body.baslangic_tarihi)
    bit = parse_iso(body.bitis_tarihi)
    if bit <= bas:
        raise HTTPException(400, "Bitiş tarihi başlangıçtan sonra olmalı")
    days = calc_days(bas, bit)
    services = [s.dict() for s in body.secilen_hizmetler]
    pricing = await calc_pricing(v, days, services)
    return pricing

# ==================== CUSTOMER: Reservations ====================
@api.post("/reservations")
async def create_reservation(body: ReservationCreate, user: dict = Depends(require_customer)):
    v = await db.vehicles.find_one({"id": body.vehicle_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    durum = await compute_vehicle_status(v)
    if durum != "musait":
        raise HTTPException(400, f"Bu araç şu anda {durum} durumunda")

    # 🆕 GECİKMİŞ TESLİM kontrolü: Önceki müşteri henüz aracı teslim etmediyse yeni rezervasyon engelle
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td_local
    now_utc_check = _dt.now(_tz.utc)
    overdue_check = await db.reservations.find_one({
        "vehicle_id": v["id"],
        "durum": {"$in": ["aktif", "onaylandi"]},
        "bitis_tarihi": {"$lt": (now_utc_check - _td_local(minutes=5)).isoformat()},
    })
    if overdue_check:
        raise HTTPException(
            423,  # Locked
            "Bu araç rezervasyon anlaşmasının dışına çıkmış ve henüz teslim edilmemiş. Lütfen firma ile iletişime geçin."
        )

    bas = parse_iso(body.baslangic_tarihi)
    bit = parse_iso(body.bitis_tarihi)
    if bit <= bas:
        raise HTTPException(400, "Bitiş tarihi başlangıçtan sonra olmalı")

    await validate_pickup_dropoff(bas, bit)

    days = calc_days(bas, bit)

    # 1 saat tampon — yeni rezervasyon başka bir rezervasyondan en az 1 saat önce/sonra olmalı
    bas_ext = (bas - timedelta(hours=1)).isoformat()
    bit_ext = (bit + timedelta(hours=1)).isoformat()

    # ÖNCE müşterinin başka bir aktif rezervasyonu yeni rezerve ile ÇAKIŞIYOR mu? (sadece overlap, before/after serbest)
    customer_conflict = await db.reservations.find_one({
        "customer_id": user["id"],
        "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
        "baslangic_tarihi": {"$lt": bit_ext},  # mevcut.baslangic < yeni.bitis + 1h
        "bitis_tarihi": {"$gt": bas_ext},      # mevcut.bitis > yeni.baslangic - 1h
    })
    if customer_conflict:
        plaka = customer_conflict.get("vehicle_snapshot", {}).get("plaka", "")
        try:
            cb_bas = parse_iso(customer_conflict["baslangic_tarihi"])
            cb_bit = parse_iso(customer_conflict["bitis_tarihi"])
            cb_bas_local = (cb_bas + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
            cb_bit_local = (cb_bit + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
        except Exception:
            cb_bas_local = customer_conflict["baslangic_tarihi"]
            cb_bit_local = customer_conflict["bitis_tarihi"]
        raise HTTPException(
            409,
            f"Mevcut rezervasyonunuz ({plaka}, {cb_bas_local} - {cb_bit_local}) ile çakışıyor. Lütfen çakışmayan bir tarih aralığı seçin (en az 1 saat tampon ile) veya mevcut rezervasyonunuzu uzatın.",
        )

    # SONRA araç çakışma kontrolü
    conflict = await db.reservations.find_one({
        "vehicle_id": v["id"],
        "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
        "baslangic_tarihi": {"$lt": bit_ext},
        "bitis_tarihi": {"$gt": bas_ext},
    })
    if conflict:
        raise HTTPException(
            400,
            "Bu araç seçilen tarih aralığında dolu veya temizlik/iade için en az 1 saat tampon süresi gerekiyor. Lütfen başka bir saat seçin.",
        )

    services = [s.dict() for s in body.secilen_hizmetler]
    pricing = await calc_pricing(v, days, services)

    # Ödeme tipine göre tahsilat yap
    odeme_tipi = (body.odeme_tipi or "auto").lower()
    if odeme_tipi not in ("full", "deposit", "auto"):
        odeme_tipi = "auto"

    w = await get_wallet(user["id"])
    odenen_ucret = 0.0
    odeme_durumu = "beklemede"
    odeme_yontemi = "havale"
    rez_durumu = "beklemede"

    if odeme_tipi == "full":
        # Müşteri tam ödeme istedi → bakiye yetersizse 402
        if w["bakiye"] < pricing["toplam_tutar"]:
            raise HTTPException(402, f"Bakiye yetersiz: tam ödeme için {pricing['toplam_tutar']:.2f}₺ gerekli, mevcut {w['bakiye']:.2f}₺.")
        await wallet_add_transaction(
            user["id"], pricing["toplam_tutar"], "odeme",
            f"Rezervasyon (tam ödeme) - {v['plaka']}",
        )
        odenen_ucret = pricing["toplam_tutar"]
        odeme_durumu = "tam_odeme_alindi"
        odeme_yontemi = "bakiye"
        rez_durumu = "onaylandi"
    elif odeme_tipi == "deposit":
        # Müşteri sadece kapora ödemek istedi → bakiye kapora kadar olmalı
        if w["bakiye"] < pricing["on_odeme_tutar"]:
            raise HTTPException(402, f"Bakiye yetersiz: kapora için {pricing['on_odeme_tutar']:.2f}₺ gerekli, mevcut {w['bakiye']:.2f}₺.")
        await wallet_add_transaction(
            user["id"], pricing["on_odeme_tutar"], "odeme",
            f"Rezervasyon ön ödemesi - {v['plaka']}",
        )
        odenen_ucret = pricing["on_odeme_tutar"]
        odeme_durumu = "on_odeme_alindi"
        odeme_yontemi = "bakiye"
        rez_durumu = "onaylandi"
    else:
        # AUTO mod (geri-uyumlu): tam varsa tamı, yoksa kaporayı, o da yoksa havale
        if w["bakiye"] >= pricing["toplam_tutar"]:
            await wallet_add_transaction(
                user["id"], pricing["toplam_tutar"], "odeme",
                f"Rezervasyon (tam ödeme) - {v['plaka']}",
            )
            odenen_ucret = pricing["toplam_tutar"]
            odeme_durumu = "tam_odeme_alindi"
            odeme_yontemi = "bakiye"
            rez_durumu = "onaylandi"
        elif w["bakiye"] >= pricing["on_odeme_tutar"]:
            await wallet_add_transaction(
                user["id"], pricing["on_odeme_tutar"], "odeme",
                f"Rezervasyon ön ödemesi - {v['plaka']}",
            )
            odenen_ucret = pricing["on_odeme_tutar"]
            odeme_durumu = "on_odeme_alindi"
            odeme_yontemi = "bakiye"
            rez_durumu = "onaylandi"

    r = {
        "id": str(uuid.uuid4()),
        "customer_id": user["id"],
        "vehicle_id": v["id"],
        "vehicle_snapshot": {
            "plaka": v["plaka"], "marka": v["marka"], "model": v["model"],
            "foto_url": v.get("foto_url", ""), "renk": v.get("renk"),
        },
        "baslangic_tarihi": body.baslangic_tarihi,
        "bitis_tarihi": body.bitis_tarihi,
        "telefon": body.telefon,
        "secilen_hizmetler": pricing["hizmetler"],
        "pricing": pricing,
        "gun_sayisi": pricing["gun_sayisi"],
        "gunluk_fiyat": pricing["gunluk_fiyat"],
        "toplam_tutar": pricing["toplam_tutar"],
        "on_odeme_tutar": pricing["on_odeme_tutar"],
        "kalan_odeme": round(pricing["toplam_tutar"] - odenen_ucret, 2),
        "odenen_ucret": odenen_ucret,
        "paket_km": pricing["paket_km"],
        "kullanilan_km": 0,
        "alis_km": None,
        "guncel_km": None,
        "km_asim": 0,
        "sure_indirim_tutar": pricing.get("sure_indirim_tutar", 0),
        "durum": rez_durumu,
        "odeme_durumu": odeme_durumu,
        "odeme_yontemi": odeme_yontemi,  # 'bakiye' / 'havale'
        "uzatma_sayisi": 0,
        "son_uzatma_tarih": None,
        "olusturan": "musteri",  # 'musteri' / 'admin'
        "iskonto_yuzde": 0.0,
        "created_at": now_iso(),
    }
    await db.reservations.insert_one(dict(r))

    # Otomatik Giden Fatura oluştur (Muhasebe için)
    try:
        await _create_giden_fatura(r)
    except Exception:
        pass

    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Yeni Rezervasyon",
        "mesaj": f"{user['ad']} {user['soyad']} - {v['marka']} {v['model']} ({v['plaka']}) - {days} gün - {pricing['toplam_tutar']:.2f}₺ ({odeme_yontemi}). Tel: {body.telefon}",
        "hedef_type": "admin",
        "hedef_customer_ids": [],
        "tarih": now_iso(),
        "okuyanlar": [],
    })
    return await db.reservations.find_one({"id": r["id"]}, {"_id": 0})

@api.get("/reservations")
async def my_reservations(user: dict = Depends(require_customer), durum: Optional[str] = None):
    q = {"customer_id": user["id"]}
    if durum:
        q["durum"] = durum
    docs = await db.reservations.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    # Müşteri sadece "aktif" durumda iken teslim fotoğraflarını görsün
    for d in docs:
        if d.get("durum") != "aktif":
            d.pop("teslim_fotograflari", None)
    return docs

@api.get("/reservations/active")
async def my_active(user: dict = Depends(require_customer)):
    # 🆕 Durumu baz al — bitiş tarihi geçmiş olsa bile durum 'aktif'/'onaylandi' ise hala aktif sayılır
    # (admin 'tamamlandi' yapana kadar)
    r = await db.reservations.find_one({
        "customer_id": user["id"],
        "durum": {"$in": ["onaylandi", "aktif"]},
    }, {"_id": 0}, sort=[("baslangic_tarihi", 1)])
    if not r:
        r = await db.reservations.find_one({
            "customer_id": user["id"],
            "durum": "beklemede",
        }, {"_id": 0}, sort=[("created_at", -1)])
    if not r:
        return None

    plaka = r.get("vehicle_snapshot", {}).get("plaka")
    if plaka:
        live = await get_live_vehicle(plaka)
        if live:
            try:
                hiz_str = (live.get("speed", "0") or "0").replace(" km/h", "").replace(",", ".")
                hiz_val = float(hiz_str)
            except Exception:
                hiz_val = 0.0
            r["live"] = {
                "kontak": live.get("ignition_status"),
                "hiz": hiz_val,
                "device_id": live.get("device_id"),
                "live": True,
            }
    try:
        bit = parse_iso(r["bitis_tarihi"])
        rem_seconds = max(0, int((bit - datetime.now(timezone.utc)).total_seconds()))
        r["kalan_saniye"] = rem_seconds
    except Exception:
        pass
    # Müşteri sadece "aktif" durumda iken teslim fotoğraflarını görsün
    if r.get("durum") != "aktif":
        r.pop("teslim_fotograflari", None)
    return r

# NOT: Bu endpoint, /reservations/{rid} (dinamik) endpoint'inden ÖNCE TANIMLI olmak ZORUNDA.
# FastAPI ilk match'i seçer; aksi takdirde rid='pending-review' lookup edilir ve 404 döner.
@api.get("/reservations/pending-review")
async def list_pending_review_reservations(user: dict = Depends(require_customer)):
    """Henüz yorum bırakılmamış tamamlanmış kiralamalar (Yorum Yap butonunun gösterimi için)."""
    res = await db.reservations.find({"customer_id": user["id"], "durum": "tamamlandi"}, {"_id": 0}).sort("bitis_tarihi", -1).to_list(100)
    reviewed_ids = set()
    if res:
        reviewed_docs = await db.reviews.find({"reservation_id": {"$in": [r["id"] for r in res]}}, {"_id": 0, "reservation_id": 1}).to_list(200)
        reviewed_ids = {d["reservation_id"] for d in reviewed_docs}
    return [r for r in res if r["id"] not in reviewed_ids]

@api.get("/reservations/{rid}")
async def reservation_detail(rid: str, user: dict = Depends(require_customer)):
    r = await db.reservations.find_one({"id": rid, "customer_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if r.get("durum") != "aktif":
        r.pop("teslim_fotograflari", None)
    return r

@api.post("/reservations/{rid}/extend")
async def extend_reservation(rid: str, body: ReservationExtend, user: dict = Depends(require_customer)):
    r = await db.reservations.find_one({"id": rid, "customer_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    return await _extend_logic(r, body, charge_balance=True, user_id=user["id"])

@api.post("/admin/reservations/{rid}/extend-quote")
async def admin_extend_quote(rid: str, body: ExtendQuoteIn, _: dict = Depends(require_admin)):
    """Admin için süre uzatma teklif (fiyat hesabı). Müşterinin tarafındaki ile AYNI mantık kullanır
    (kademe fiyat + süre indirimi + ek hizmet + ek KM). Bakiye kontrolü yapılmaz (admin kararı)."""
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    return await _compute_extend_quote(r, body, check_balance=False)

# ==================== ORTAK: Süre Uzatma Hesabı ====================
async def _compute_extend_quote(r: dict, body: ExtendQuoteIn, check_balance: bool = True) -> dict:
    """Müşteri ve admin tarafı için ortak süre uzatma fiyat hesabı.
    - Kademe fiyat (gunluk_fiyat_kademeleri) → yeni toplam gün için
    - Süre indirimi → eski indirim ile fark
    - Ek hizmetler (zorunlu hariç)
    - Ek KM satın alma + hacim indirimi
    - Bakiye kontrolü (sadece check_balance=True ise)
    - Tatil/mesai/çakışma kontrolleri
    """
    if r["durum"] not in ("onaylandi", "aktif"):
        raise HTTPException(400, "Sadece aktif/onaylı rezervasyonlar uzatılabilir")
    eski_bit = parse_iso(r["bitis_tarihi"])
    yeni_bit = parse_iso(body.yeni_bitis_tarihi)
    if yeni_bit <= eski_bit:
        raise HTTPException(400, "Yeni bitiş tarihi mevcut bitiş tarihinden sonra olmalı")

    # Tatil/mesai kontrolü
    h = await is_holiday(yeni_bit)
    if h:
        return {"ok": False, "blocked_reason": "tatil", "message": f"Yeni iade tarihi: {h}"}
    bh = await is_within_business_hours(yeni_bit)
    if bh:
        try:
            eski_bas = parse_iso(r["baslangic_tarihi"])
            bas_bh = await is_within_business_hours(eski_bas)
            tr_bas = eski_bas + timedelta(hours=3)
            tr_yeni = yeni_bit + timedelta(hours=3)
            ayni_saat = (tr_bas.hour == tr_yeni.hour and abs(tr_bas.minute - tr_yeni.minute) <= 10)
            if not (bas_bh and ayni_saat):
                return {"ok": False, "blocked_reason": "mesai", "message": f"Yeni iade saati: {bh}"}
        except Exception:
            return {"ok": False, "blocked_reason": "mesai", "message": f"Yeni iade saati: {bh}"}

    # Çakışma kontrolü (1 saat tampon)
    yeni_bit_ext = (yeni_bit + timedelta(hours=1)).isoformat()
    eski_bas_ext = (parse_iso(r["baslangic_tarihi"]) - timedelta(hours=1)).isoformat()
    conflict = await db.reservations.find_one({
        "vehicle_id": r["vehicle_id"],
        "id": {"$ne": r["id"]},
        "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
        "baslangic_tarihi": {"$lt": yeni_bit_ext},
        "bitis_tarihi": {"$gt": eski_bas_ext},
    })
    if conflict:
        return {"ok": False, "blocked_reason": "cakisma", "message": "Bu araç seçtiğiniz uzatma tarihinde başka bir rezervasyon ile çakışıyor."}

    ek_gun = calc_days(eski_bit, yeni_bit)
    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    s = await get_settings()
    fallback_min = s.get("indirim_min_gun", 2)
    fallback_yuzde = s.get("indirim_yuzde", 10.0)

    eski_gun = int(r.get("gun_sayisi") or 0)
    yeni_toplam_gun = eski_gun + ek_gun
    yeni_gunluk_fiyat = daily_price_for(v, yeni_toplam_gun)
    yeni_base_total = yeni_gunluk_fiyat * yeni_toplam_gun
    eski_indirim_uygulanmis = float((r.get("pricing") or {}).get("sure_indirim_tutar") or r.get("sure_indirim_tutar") or 0)
    yeni_total_indirim = sure_indirim_for(v, yeni_toplam_gun, yeni_base_total, fallback_min, fallback_yuzde)
    ek_indirim = round(max(0.0, yeni_total_indirim - eski_indirim_uygulanmis), 2)
    ek_base = round(yeni_gunluk_fiyat * ek_gun, 2)
    ek_arac = round(max(0.0, ek_base - ek_indirim), 2)

    # Ek hizmetler — uzatma için seçilen ekstralar (zorunlu hizmetler hariç tutulur)
    services_total = 0.0
    services_breakdown = []
    if body.secilen_hizmetler:
        for sel in body.secilen_hizmetler:
            svc = await db.services.find_one({"id": sel.service_id, "aktif": True}, {"_id": 0})
            if not svc or svc.get("zorunlu"):
                continue
            adet = max(1, sel.adet)
            line = svc["fiyat"] * adet * (ek_gun if svc["tip"] == "gunluk" else 1)
            services_total += line
            services_breakdown.append({
                "service_id": svc["id"], "isim": svc["isim"], "fiyat": svc["fiyat"], "tutar": round(line, 2),
            })
    services_total = round(services_total, 2)

    # Ek KM satın alma
    ek_km_buy = max(0, int(body.ek_km or 0))
    km_asim_fiyat = km_asim_for(v, s, days=yeni_toplam_gun)
    ek_km_brut = round(ek_km_buy * km_asim_fiyat, 2)
    ek_km_indirim = km_volume_indirim_for(v, s, ek_km_buy)
    ek_km_tutar = round(max(0.0, ek_km_brut - ek_km_indirim), 2)

    ek_tutar = round(ek_arac + services_total + ek_km_tutar, 2)

    # Bakiye kontrolü (sadece müşteri tarafında)
    bakiye = 0.0
    bakiye_yeterli = True
    eksik = 0.0
    if check_balance:
        w = await get_wallet(r["customer_id"])
        bakiye = w["bakiye"]
        bakiye_yeterli = bakiye >= ek_tutar
        eksik = max(0, ek_tutar - bakiye)

    return {
        "ok": True,
        "ek_gun": ek_gun,
        "ek_tutar": ek_tutar,
        # Admin UI eski isimler — backward compat:
        "yeni_toplam_gun": yeni_toplam_gun,
        "yeni_birim_fiyat": yeni_gunluk_fiyat,
        "arac_fark": ek_arac,
        "toplam_ek_ucret": ek_tutar,
        # Müşteri detay alanları:
        "ek_arac_tutar": ek_arac,
        "ek_hizmet_tutar": services_total,
        "ek_hizmetler": services_breakdown,
        "ek_indirim": ek_indirim,
        "yeni_toplam_indirim": yeni_total_indirim,
        "yeni_gunluk_fiyat": yeni_gunluk_fiyat,
        "eski_gunluk_fiyat": float((r.get("pricing") or {}).get("gunluk_fiyat") or r.get("gunluk_fiyat") or 0),
        "fiyat_kademe": matched_price_kademe(v, yeni_toplam_gun),
        "fiyat_kademeleri": v.get("gunluk_fiyat_kademeleri") or [],
        "km_asim_kademe": matched_km_asim_kademe(v, yeni_toplam_gun),
        "km_asim_kademeleri": v.get("km_asim_kademeleri") or [],
        "ek_km_satin": ek_km_buy,
        "ek_km_brut": ek_km_brut,
        "ek_km_indirim": ek_km_indirim,
        "ek_km_tutar": ek_km_tutar,
        "km_asim_fiyat": km_asim_fiyat,
        "yeni_gunluk_km": daily_km_for(v, yeni_toplam_gun),
        "yeni_paket_km": int(r.get("paket_km", 0) or 0) - paket_km_for(v, eski_gun) + paket_km_for(v, yeni_toplam_gun) + ek_km_buy,
        "bakiye": bakiye,
        "bakiye_yeterli": bakiye_yeterli,
        "eksik": eksik,
    }

# ==================== ORTAK: Süre Uzatma Uygulama ====================
async def _extend_logic(r: dict, body: ReservationExtend, charge_balance: bool = True, user_id: str = None) -> dict:
    """Müşteri ve admin tarafı için ortak uzatma uygulama fonksiyonu.
    - charge_balance=True → müşteri bakiyesinden ÇEKER (sadece müşteri)
    - charge_balance=False → bakiyeden çekmez, sadece kalan_odeme'ye ekler (admin)
    """
    q = await _compute_extend_quote(r, body, check_balance=charge_balance)
    if not q.get("ok"):
        # Tatil/mesai/çakışma engelleri
        raise HTTPException(400, q.get("message") or "Uzatma yapılamadı")

    # Bakiye yeterli mi (sadece müşteri)
    if charge_balance and not q.get("bakiye_yeterli", True):
        raise HTTPException(402, f"Bakiye yetersiz. Eksik: {q.get('eksik'):.2f}₺")

    rid = r["id"]
    ek_tutar = float(q["ek_tutar"])
    yeni_bit = parse_iso(body.yeni_bitis_tarihi)
    yeni_toplam_gun = int(q["yeni_toplam_gun"])
    yeni_paket_km = int(q["yeni_paket_km"])
    yeni_gunluk_fiyat = float(q["yeni_gunluk_fiyat"])

    # Mevcut pricing'i güncelle
    eski_pricing = dict(r.get("pricing") or {})
    eski_arac_toplam = float(eski_pricing.get("arac_toplam") or r.get("arac_tutari") or 0)
    yeni_arac_toplam = round(eski_arac_toplam + float(q["ek_arac_tutar"]), 2)

    yeni_pricing = {
        **eski_pricing,
        "gun_sayisi": yeni_toplam_gun,
        "gunluk_fiyat": yeni_gunluk_fiyat,
        "arac_toplam": yeni_arac_toplam,
        "sure_indirim_tutar": float(q["yeni_toplam_indirim"]),
        "toplam_tutar": float(r.get("toplam_tutar") or 0) + ek_tutar,
        "paket_km": yeni_paket_km,
    }

    update_doc = {
        "bitis_tarihi": yeni_bit.isoformat(),
        "gun_sayisi": yeni_toplam_gun,
        "gunluk_fiyat": yeni_gunluk_fiyat,
        "arac_tutari": yeni_arac_toplam,
        "toplam_tutar": round(float(r.get("toplam_tutar") or 0) + ek_tutar, 2),
        "kalan_odeme": round(float(r.get("kalan_odeme") or 0) + ek_tutar, 2),
        "paket_km": yeni_paket_km,
        "pricing": yeni_pricing,
        "uzatma_sayisi": int(r.get("uzatma_sayisi") or 0) + 1,
        "son_uzatma_tarih": now_iso(),
    }

    # Bakiyeden çek (sadece müşteri)
    if charge_balance and ek_tutar > 0:
        try:
            await wallet_add_transaction(
                r["customer_id"], ek_tutar, "uzatma",
                f"Rezervasyon süre uzatması ({yeni_toplam_gun} gün)",
                referans=f"EXTEND-{rid}",
            )
            update_doc["kalan_odeme"] = round(float(r.get("kalan_odeme") or 0), 2)  # bakiyeden çekildi, eklenmedi
            update_doc["odenen_ucret"] = round(float(r.get("odenen_ucret") or 0) + ek_tutar, 2)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(500, f"Bakiye işlemi başarısız: {e}")

    await db.reservations.update_one({"id": rid}, {"$set": update_doc})

    # Bildirim
    try:
        await notify_customer(
            r["customer_id"],
            "Süre Uzatıldı",
            f"Rezervasyonunuzun süresi {yeni_toplam_gun} güne uzatıldı. Yeni bitiş: {yeni_bit.strftime('%d.%m.%Y %H:%M')}. {'Bakiyenizden çekildi' if charge_balance else 'Kalan ödemeye eklendi'}: {ek_tutar:.2f}₺",
            {"type": "reservation_extended", "reservation_id": rid},
        )
    except Exception:
        pass

    return {"ok": True, **q, "yeni_bitis_tarihi": yeni_bit.isoformat()}

@api.post("/admin/reservations/{rid}/extend")
async def admin_extend_reservation(rid: str, body: ReservationExtend, _: dict = Depends(require_admin)):
    """Admin manuel süre uzatma — Müşteri tarafıyla AYNI mantık.
    Bakiyeden ÇEKMEZ, kalan ödemeye ekler."""
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    return await _extend_logic(r, body, charge_balance=False)

async def _admin_extend_quote_logic(r: dict, body: ExtendQuoteIn) -> dict:
    """Legacy alias — yeni kod _compute_extend_quote kullanır."""
    return await _compute_extend_quote(r, body, check_balance=False)

    ek_gun = calc_days(eski_bit, yeni_bit)
    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")

    # Apply NEW vehicle-based discount logic + bracket pricing
    s = await get_settings()
    fallback_min = s.get("indirim_min_gun", 2)
    fallback_yuzde = s.get("indirim_yuzde", 10.0)
    eski_gun = int(r.get("gun_sayisi") or 0)
    yeni_toplam_gun = eski_gun + ek_gun
    # Yeni günler, yeni toplam günden hesaplanan kademe fiyatı ile çarpılır
    yeni_gunluk_fiyat = daily_price_for(v, yeni_toplam_gun)
    eski_indirim_uygulanmis = float((r.get("pricing") or {}).get("sure_indirim_tutar") or r.get("sure_indirim_tutar") or 0)
    yeni_total_indirim = sure_indirim_for(v, yeni_toplam_gun, yeni_gunluk_fiyat * yeni_toplam_gun, fallback_min, fallback_yuzde)
    ek_indirim = round(max(0.0, yeni_total_indirim - eski_indirim_uygulanmis), 2)
    ek_base = round(yeni_gunluk_fiyat * ek_gun, 2)
    ek_arac = round(max(0.0, ek_base - ek_indirim), 2)

    # Ek hizmetler — uzatma gün sayısı için tekrar hesaplanır.
    # ZORUNLU hizmetler bu aşamada EKLENMEZ (zaten ilk rezervasyonda alındı)
    services_total = 0.0
    services_breakdown = []
    if body.secilen_hizmetler:
        for sel in body.secilen_hizmetler:
            svc = await db.services.find_one({"id": sel.service_id, "aktif": True}, {"_id": 0})
            if not svc:
                continue
            # Zorunlu hizmetlerin uzatmada tekrar ücretlendirilmesini engelle (gün-bazlı zorunlu hariç)
            if svc.get("zorunlu"):
                continue
            adet = max(1, sel.adet)
            line = svc["fiyat"] * adet * (ek_gun if svc["tip"] == "gunluk" else 1)
            services_total += line
            services_breakdown.append({
                "service_id": svc["id"], "isim": svc["isim"], "tip": svc["tip"],
                "fiyat": svc["fiyat"], "adet": adet, "tutar": round(line, 2),
            })
    services_total = round(services_total, 2)

    # Ek KM satın alma (uzatma sırasında) — ARAÇ BAZLI hacim indirimi & km_asim (SÜREYE GÖRE)
    ek_km_buy = max(0, int(body.ek_km or 0))
    km_asim_fiyat = km_asim_for(v, s, days=yeni_toplam_gun)
    ek_km_brut = round(ek_km_buy * km_asim_fiyat, 2)
    ek_km_indirim = km_volume_indirim_for(v, s, ek_km_buy)
    ek_km_tutar = round(max(0.0, ek_km_brut - ek_km_indirim), 2)

    ek_tutar = round(ek_arac + services_total + ek_km_tutar, 2)
    # Paket KM artımı (KÜMÜLATİF/SEGMENTLİ): yeni toplam gün için paket_km - eski paket_km segment farkı
    # Eski paket_km'de flat (eski hesaplama) ya da segmentli olabilir; yine de fark hep doğru segmentli artımı verir.
    ek_paket_km_gun = max(0, paket_km_for(v, yeni_toplam_gun) - paket_km_for(v, eski_gun))
    ek_km = ek_paket_km_gun + ek_km_buy

    # Bakiye kontrolü
    w = await get_wallet(user["id"])
    if w["bakiye"] < ek_tutar:
        raise HTTPException(402, f"Bakiye yetersiz. Mevcut: {w['bakiye']:.2f}₺ — Gerekli: {ek_tutar:.2f}₺")

    # Deduct from wallet
    aciklama = f"Süre uzatma - {v['plaka']} ({ek_gun} gün)"
    if ek_km_buy > 0:
        aciklama += f" + {ek_km_buy} km"
    if services_breakdown:
        aciklama += f" + {len(services_breakdown)} ek hizmet"
    await wallet_add_transaction(user["id"], ek_tutar, "odeme", aciklama)

    # Eski rezervasyondaki secilen_hizmetler ile uzatma için seçilenleri birleştir
    existing_services = list(r.get("secilen_hizmetler") or [])
    existing_services.extend(services_breakdown)

    # pricing alanını da güncelle ki bir sonraki uzatmada doğru indirim baselinini bilelim
    new_pricing = dict(r.get("pricing") or {})
    new_pricing["sure_indirim_tutar"] = yeni_total_indirim
    new_pricing["gun_sayisi"] = yeni_toplam_gun

    await db.reservations.update_one(
        {"id": rid},
        {"$set": {
            "bitis_tarihi": body.yeni_bitis_tarihi,
            "gun_sayisi": yeni_toplam_gun,
            "toplam_tutar": round(r["toplam_tutar"] + ek_tutar, 2),
            "odenen_ucret": round(r.get("odenen_ucret", 0) + ek_tutar, 2),
            "paket_km": r["paket_km"] + ek_km,
            "secilen_hizmetler": existing_services,
            "son_uzatma_tarih": now_iso(),
            "sure_indirim_tutar": yeni_total_indirim,
            "pricing": new_pricing,
            "uzatma_yapildi": True,
            "uzatma_tarihi": now_iso(),
        }, "$inc": {"uzatma_sayisi": 1}},
    )

    # Muhasebe: Yeni mantık — _create_giden_fatura artık aya bölünmüş çoklu fatura
    # oluşturur ve mevcut otomatik faturaları (auto_generated=true) günceller, manuel
    # düzenlenmiş olanlara dokunmaz. Uzatma sonrası yeni aylar için ek fatura otomatik üretilir.
    try:
        updated_res = await db.reservations.find_one({"id": rid}, {"_id": 0})
        if updated_res:
            await _create_giden_fatura(updated_res)
    except Exception as e:
        logger.warning(f"extend: muhasebe fatura güncellenemedi rid={rid}: {e}")

    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Süre Uzatıldı",
        "mesaj": f"{user['ad']} {user['soyad']} rezervasyonunu {ek_gun} gün uzattı (+{ek_tutar:.2f}₺ bakiyeden tahsil edildi). Plaka: {r.get('vehicle_snapshot', {}).get('plaka')}",
        "hedef_type": "admin",
        "hedef_customer_ids": [],
        "tarih": now_iso(),
        "okuyanlar": [],
    })
    return await db.reservations.find_one({"id": rid}, {"_id": 0})

@api.post("/reservations/{rid}/payment-confirm")
async def confirm_payment(rid: str, body: PaymentConfirm, user: dict = Depends(require_customer)):
    r = await db.reservations.find_one({"id": rid, "customer_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    await db.reservations.update_one({"id": rid}, {"$set": {
        "odeme_bildirimi": {"referans_no": body.referans_no, "notlar": body.notlar, "tarih": now_iso()},
    }})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Ödeme Bildirimi (Havale)",
        "mesaj": f"{user['ad']} {user['soyad']} ödeme yaptığını bildirdi. Ref: {body.referans_no or '—'}",
        "hedef_type": "admin", "hedef_customer_ids": [], "tarih": now_iso(), "okuyanlar": [],
    })
    return {"ok": True, "message": "Ödeme bildiriminiz alındı, yönetici onayı bekleniyor"}

# ==================== CUSTOMER: Wallet ====================
@api.get("/wallet")
async def my_wallet(user: dict = Depends(require_customer)):
    w = await get_wallet(user["id"])
    return {"bakiye": w["bakiye"]}

@api.get("/wallet/transactions")
async def my_wallet_tx(user: dict = Depends(require_customer)):
    docs = await db.wallet_tx.find({"customer_id": user["id"]}, {"_id": 0}).sort("tarih", -1).to_list(200)
    return docs

@api.post("/wallet/topup")
async def wallet_topup(body: WalletTopupIn, user: dict = Depends(require_customer)):
    if body.tutar < 50 or body.tutar > 100000:
        raise HTTPException(400, "Yükleme tutarı 50₺ - 100.000₺ arası olmalı")

    if body.yontem == "kart":
        # Kart ödemesi: KDV + komisyon düşülerek bakiyeye geçer
        s = await get_settings()
        kdv = float(s.get("kart_kdv_yuzde", 20.0))
        kom = float(s.get("kart_komisyon_yuzde", 5.0))
        # Müşterinin GİRDİĞİ tutardan KDV+komisyon düşülür → cüzdana NET tutar geçer
        kdv_tutar = round(body.tutar * (kdv / 100.0), 2)
        kom_tutar = round(body.tutar * (kom / 100.0), 2)
        net_tutar = round(body.tutar - kdv_tutar - kom_tutar, 2)
        if net_tutar <= 0:
            raise HTTPException(400, "Net tutar 0'dan büyük olmalı")

        if not (body.kart_no and body.cvc and body.son_kullanma):
            raise HTTPException(400, "Kart bilgileri eksik")
        kn = re.sub(r"\D", "", body.kart_no)
        if len(kn) < 13:
            raise HTTPException(400, "Geçersiz kart numarası")
        # MOCK: Test card ending 0000 fails (Shopier gerçek entegrasyon ileride)
        if kn.endswith("0000"):
            raise HTTPException(402, "Kart işlemi reddedildi (test modu)")
        result = await wallet_add_transaction(
            user["id"], net_tutar, "yukleme",
            f"Kart ile yükleme (****{kn[-4:]}) - Brüt:{body.tutar:.2f}₺ KDV:{kdv_tutar:.2f}₺ Kom:{kom_tutar:.2f}₺",
            referans=f"KART-{uuid.uuid4().hex[:8].upper()}",
        )
        return {
            "ok": True,
            "bakiye": result["bakiye"],
            "yontem": "kart",
            "durum": "tamamlandi",
            "brut_tutar": body.tutar,
            "kdv_tutar": kdv_tutar,
            "komisyon_tutar": kom_tutar,
            "net_tutar": net_tutar,
        }

    elif body.yontem == "havale":
        # Havale: dekont ZORUNLU, AI doğrulamasından geçirilir
        if not body.dekont_base64:
            raise HTTPException(400, "Havale yüklemesi için dekont fotoğrafı zorunludur")

        s = await get_settings()
        admin_iban = s.get("iban") or ""
        admin_hesap_sahibi = s.get("hesap_sahibi") or s.get("sirket_adi") or ""
        if not admin_iban or not admin_hesap_sahibi:
            # Admin bilgileri eksikse otomatik doğrulamayı atla, direkt admin'e gönder
            ai_result = {
                "valid": False,
                "fields": {},
                "confidence": 0.0,
                "reasons": ["Sistem yapılandırması eksik (admin IBAN/hesap sahibi tanımlanmamış)"],
            }
        else:
            customer_full = f"{user.get('ad', '')} {user.get('soyad', '')}".strip()
            try:
                ai_result = await validate_dekont_with_ai(
                    foto_base64=body.dekont_base64,
                    expected_iban=admin_iban,
                    expected_recipient_name=admin_hesap_sahibi,
                    expected_sender_name=customer_full,
                    expected_amount=body.tutar,
                )
            except Exception as e:
                logger.error(f"AI dekont doğrulama hata: {e}")
                ai_result = {"valid": False, "fields": {}, "confidence": 0.0, "reasons": [f"AI hata: {e}"]}

        # Dekont'u büyükse data URI'ye dönüştür (frontend Image component için)
        dekont = body.dekont_base64.strip()
        if not dekont.startswith("data:"):
            dekont = f"data:image/jpeg;base64,{dekont}"
        # Boyut sınırı (kabaca ~10MB)
        if len(dekont) > 12 * 1024 * 1024:
            raise HTTPException(400, "Dekont fotoğrafı çok büyük (max ~9MB)")

        if ai_result.get("valid"):
            # OTOMATİK ONAY: doğrudan bakiyeye işle
            result = await wallet_add_transaction(
                user["id"], body.tutar, "yukleme",
                f"Havale yükleme (AI onaylı) - Ref: {body.havale_referans or '—'}",
                referans=body.havale_referans or f"AI-{uuid.uuid4().hex[:8].upper()}",
            )
            # Dekont kaydını ayrıca tut (audit için)
            await db.dekontlar.insert_one({
                "id": str(uuid.uuid4()),
                "customer_id": user["id"],
                "musteri_ad": f"{user.get('ad','')} {user.get('soyad','')}".strip(),
                "tutar": body.tutar,
                "havale_referans": body.havale_referans or "",
                "dekont_url": dekont,
                "ai_result": ai_result,
                "durum": "ai_onayli",
                "tarih": now_iso(),
            })
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "baslik": "Havale Bakiyesi Yüklendi",
                "mesaj": f"{body.tutar:.2f}₺ havale ödemeniz AI doğrulamasından geçti, bakiyenize otomatik eklendi.",
                "hedef_type": "secili", "hedef_customer_ids": [user["id"]],
                "tarih": now_iso(), "okuyanlar": [],
            })
            return {
                "ok": True,
                "yontem": "havale",
                "durum": "tamamlandi",
                "ai_onay": True,
                "ai_result": ai_result,
                "bakiye": result["bakiye"],
                "message": "Dekont AI doğrulamasından geçti. Bakiyeniz güncellendi.",
            }
        else:
            # ŞÜPHELİ DURUM: admin'e gönder
            tx_id = str(uuid.uuid4())
            await db.wallet_tx.insert_one({
                "id": tx_id,
                "customer_id": user["id"],
                "tip": "yukleme_beklemede",
                "tutar": body.tutar,
                "isaret": "+",
                "aciklama": "Havale/EFT yükleme talebi (AI şüpheli)",
                "referans": body.havale_referans or "—",
                "bakiye_sonra": None,
                "tarih": now_iso(),
                "durum": "beklemede",
                "dekont_url": dekont,
                "ai_result": ai_result,
            })
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "baslik": "Havale Onay Bekliyor (AI Şüpheli)",
                "mesaj": f"{user.get('ad','')} {user.get('soyad','')} - {body.tutar:.2f}₺ havale. Sebep: {'; '.join(ai_result.get('reasons') or ['Doğrulanamadı'])[:200]}",
                "hedef_type": "admin", "hedef_customer_ids": [],
                "tarih": now_iso(), "okuyanlar": [],
            })
            try:
                await notify_admin(
                    "💳 Dekont Onay Bekliyor",
                    f"{user.get('ad','')} {user.get('soyad','')} - {body.tutar:.2f}₺ havale (AI şüpheli)",
                    {"type": "wallet_topup_pending", "customer_id": user["id"], "tx_id": tx_id},
                )
            except Exception:
                pass
            return {
                "ok": True,
                "yontem": "havale",
                "durum": "beklemede",
                "ai_onay": False,
                "ai_result": ai_result,
                "message": "Dekontunuz incelemeye alındı. Yönetici onayı sonrası bakiyenize işlenecektir.",
            }
    raise HTTPException(400, "Geçersiz yöntem")

# ==================== SHOPIER (Gerçek Klasik API - OSB) ====================
import hmac as _hmac
import hashlib as _hashlib
import base64 as _base64
import secrets as _secrets

SHOPIER_GATEWAY_URL = "https://www.shopier.com/ShowProduct/api_pay4.php"

def _shopier_signature(random_nr: str, platform_order_id: str, total_order_value: str, currency: str, secret: str, api_key: str = "") -> str:
    """Shopier klasik API HMAC-SHA256 signature (base64).
    Imza: HMAC_SHA256( random_nr + platform_order_id + total_order_value + currency, key=API_secret )
    Bazı yeni versiyonlarda data sonuna API_KEY de eklenir — onu callback hash formülüyle uyumlu olarak destekliyoruz.
    """
    raw = f"{random_nr}{platform_order_id}{total_order_value}{currency}"
    h = _hmac.new(secret.encode("utf-8"), raw.encode("utf-8"), _hashlib.sha256).digest()
    return _base64.b64encode(h).decode("utf-8")

class ShopierInitIn(BaseModel):
    tutar: float

@api.post("/wallet/shopier/init")
async def shopier_init(body: ShopierInitIn, user: dict = Depends(require_customer)):
    """Shopier klasik API ile gerçek ödeme başlatma. KDV+Komisyon brüt tutardan kesilir,
    cüzdana NET tutar geçer (callback geldiğinde).
    """
    if body.tutar < 50 or body.tutar > 100000:
        raise HTTPException(400, "Yükleme tutarı 50₺ - 100.000₺ arası olmalı")

    SHOPIER_API_KEY = os.environ.get("SHOPIER_API_KEY", "").strip()
    SHOPIER_API_SECRET = os.environ.get("SHOPIER_API_SECRET", "").strip()
    SHOPIER_WEBSITE_INDEX = os.environ.get("SHOPIER_WEBSITE_INDEX", "1").strip()

    if not (SHOPIER_API_KEY and SHOPIER_API_SECRET):
        raise HTTPException(503, "Shopier yapılandırılmadı")

    s = await get_settings()
    kdv_pct = float(s.get("kart_kdv_yuzde", 20.0))
    kom_pct = float(s.get("kart_komisyon_yuzde", 5.0))
    brut = round(body.tutar, 2)
    kdv_tutar = round(brut * (kdv_pct / 100.0), 2)
    kom_tutar = round(brut * (kom_pct / 100.0), 2)
    net_tutar = round(brut - kdv_tutar - kom_tutar, 2)
    if net_tutar <= 0:
        raise HTTPException(400, "Net tutar 0'dan büyük olmalı")

    order_id = uuid.uuid4().hex[:16].upper()
    # Shopier random_nr — 6 haneli sayı (resmi shopier-api kütüphanesi: 100000-999999)
    random_nr = str(_secrets.randbelow(900_000) + 100_000)

    # total_order_value: PHP/JS'de number olarak concat edildiğinde toString()
    # int → "1000", float → "1000.5" (trailing zero'sız)
    if brut == int(brut):
        total_value_str = str(int(brut))
    else:
        total_value_str = f"{brut:.2f}".rstrip("0").rstrip(".")

    currency = "0"

    sig = _shopier_signature(random_nr, order_id, total_value_str, currency, SHOPIER_API_SECRET)

    logger.info(f"Shopier init: order_id={order_id} random_nr={random_nr} total='{total_value_str}' currency={currency}")
    logger.info(f"Shopier signature data='{random_nr}{order_id}{total_value_str}{currency}' sig={sig}")

    # Customer info
    buyer_name = (user.get("ad") or "Müşteri").strip()
    buyer_surname = (user.get("soyad") or "Soyad").strip()
    buyer_email = (user.get("email") or "").strip() or f"customer-{user['id'][:8]}@ysauto.local"
    buyer_phone = (user.get("telefon") or "+905555555555").strip()
    buyer_address = (user.get("adres") or "Türkiye").strip()

    form_fields = {
        "API_key": SHOPIER_API_KEY,
        "website_index": SHOPIER_WEBSITE_INDEX,
        "platform_order_id": order_id,
        "product_name": f"YS Auto Bakiye Yukleme {brut:.0f} TL",
        "product_type": "0",  # 0=REAL_OBJECT (resmi shopier-api default)
        "buyer_name": buyer_name,
        "buyer_surname": buyer_surname,
        "buyer_email": buyer_email,
        "buyer_account_age": "0",
        "buyer_id_nr": str(user.get("id"))[:24],
        "buyer_phone": buyer_phone,
        "billing_address": buyer_address,
        "billing_city": "Istanbul",
        "billing_country": "Turkiye",
        "billing_postcode": "34000",
        "shipping_address": buyer_address,
        "shipping_city": "Istanbul",
        "shipping_country": "Turkiye",
        "shipping_postcode": "34000",
        "total_order_value": total_value_str,
        "currency": currency,
        "platform": "1",       # PlatformType.IN_FRAME = 1 (resmi shopier-api default)
        "is_in_frame": "1",    # PlatformType.IN_FRAME = 1
        "current_language": "0",  # TR
        "modul_version": "1.0.4",
        "random_nr": random_nr,
        "signature": sig,
    }

    # Pending kayıt — webhook geldiğinde net_tutar bakiyeye yazılacak
    pending_id = str(uuid.uuid4())
    await db.wallet_tx.insert_one({
        "id": pending_id,
        "customer_id": user["id"],
        "tip": "shopier_beklemede",
        "tutar": net_tutar,  # NET — bakiyeye eklenecek
        "brut_tutar": brut,
        "kdv_tutar": kdv_tutar,
        "komisyon_tutar": kom_tutar,
        "isaret": "+",
        "aciklama": f"Shopier ödeme - {order_id} (Brüt: {brut:.2f}₺ - KDV:{kdv_tutar:.2f} - Kom:{kom_tutar:.2f})",
        "referans": order_id,
        "bakiye_sonra": None,
        "tarih": now_iso(),
        "durum": "beklemede",
    })

    return {
        "ok": True,
        "mode": "real",
        "order_id": order_id,
        "checkout_url": f"{os.environ.get('PUBLIC_BACKEND_URL', '').rstrip('/')}/api/wallet/shopier/redirect/{order_id}",
        "gateway_url": SHOPIER_GATEWAY_URL,
        "form_fields": form_fields,
        "brut_tutar": brut,
        "kdv_tutar": kdv_tutar,
        "komisyon_tutar": kom_tutar,
        "net_tutar": net_tutar,
    }

# Shopier redirect: form'u auto-submit eden HTML sayfası döner — frontend WebView'da açar
from fastapi.responses import HTMLResponse, PlainTextResponse

@api.get("/wallet/shopier/redirect/{order_id}", response_class=HTMLResponse)
async def shopier_redirect(order_id: str):
    """Shopier'a auto-submit eden HTML form sayfası. Frontend bu URL'i WebView'da açar."""
    tx = await db.wallet_tx.find_one({"referans": order_id, "tip": "shopier_beklemede"}, {"_id": 0})
    if not tx:
        return HTMLResponse("<h1>Sipariş bulunamadı</h1>", status_code=404)
    if tx.get("durum") != "beklemede":
        return HTMLResponse("<h1>Bu işlem zaten tamamlanmış</h1>", status_code=410)

    # Form alanlarını yeniden oluştur (signature dahil)
    SHOPIER_API_KEY = os.environ.get("SHOPIER_API_KEY", "").strip()
    SHOPIER_API_SECRET = os.environ.get("SHOPIER_API_SECRET", "").strip()
    SHOPIER_WEBSITE_INDEX = os.environ.get("SHOPIER_WEBSITE_INDEX", "1").strip()

    user = await db.customers.find_one({"id": tx["customer_id"]}, {"_id": 0})
    if not user:
        return HTMLResponse("<h1>Müşteri bulunamadı</h1>", status_code=404)

    brut = float(tx.get("brut_tutar", tx["tutar"]))
    random_nr = str(_secrets.randbelow(30000) + 100)
    if brut == int(brut):
        total_value_str = str(int(brut))
    else:
        total_value_str = f"{brut:.2f}".rstrip("0").rstrip(".")
    currency = "0"
    sig = _shopier_signature(random_nr, order_id, total_value_str, currency, SHOPIER_API_SECRET)
    logger.info(f"Shopier redirect: order_id={order_id} random_nr={random_nr} total='{total_value_str}' sig={sig}")

    buyer_name = (user.get("ad") or "Müşteri").strip()
    buyer_surname = (user.get("soyad") or "Soyad").strip()
    buyer_email = (user.get("email") or "").strip() or f"customer-{user['id'][:8]}@ysauto.local"
    buyer_phone = (user.get("telefon") or "+905555555555").strip()
    buyer_address = (user.get("adres") or "Türkiye").strip()

    fields = {
        "API_key": SHOPIER_API_KEY,
        "website_index": SHOPIER_WEBSITE_INDEX,
        "platform_order_id": order_id,
        "product_name": f"YS Auto Bakiye Yukleme {brut:.0f} TL",
        "product_type": "0",
        "buyer_name": buyer_name,
        "buyer_surname": buyer_surname,
        "buyer_email": buyer_email,
        "buyer_account_age": "0",
        "buyer_id_nr": str(user.get("id"))[:24],
        "buyer_phone": buyer_phone,
        "billing_address": buyer_address,
        "billing_city": "Istanbul",
        "billing_country": "Turkiye",
        "billing_postcode": "34000",
        "shipping_address": buyer_address,
        "shipping_city": "Istanbul",
        "shipping_country": "Turkiye",
        "shipping_postcode": "34000",
        "total_order_value": total_value_str,
        "currency": currency,
        "platform": "0",
        "is_in_frame": "0",
        "current_language": "0",
        "modul_version": "1.0.4",
        "random_nr": random_nr,
        "signature": sig,
    }

    inputs_html = "\n".join(
        f'<input type="hidden" name="{k}" value="{(v or "").replace(chr(34), "&quot;")}">'
        for k, v in fields.items()
    )
    html = f"""<!DOCTYPE html>
<html lang="tr"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Shopier — Yönlendiriliyor</title>
<style>
body{{font-family:-apple-system,Roboto,sans-serif;background:#0d0e10;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;padding:20px}}
.box{{text-align:center;max-width:420px}}
.spinner{{width:48px;height:48px;border:4px solid #2a2c30;border-top-color:#a30015;border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 16px}}
@keyframes spin{{to{{transform:rotate(360deg)}}}}
h1{{font-size:18px;margin:0 0 6px}}
p{{color:#888;font-size:14px}}
</style></head>
<body>
<div class="box">
<div class="spinner"></div>
<h1>Shopier Güvenli Ödemeye Yönlendiriliyorsunuz</h1>
<p>Lütfen bekleyin...</p>
</div>
<form id="shopierForm" method="post" action="{SHOPIER_GATEWAY_URL}" style="display:none">
{inputs_html}
</form>
<script>document.getElementById('shopierForm').submit();</script>
</body></html>"""
    return HTMLResponse(content=html)

# Asıl callback endpoint — Shopier form-encoded POST gönderir
from fastapi import Request as _FastRequest

async def _process_shopier_callback(payload: dict) -> dict:
    SHOPIER_API_SECRET = os.environ.get("SHOPIER_API_SECRET", "").strip()
    if not SHOPIER_API_SECRET:
        raise HTTPException(503, "Shopier yapılandırılmadı")

    # Shopier YENI callback formatı: { res: <base64 JSON>, hash: <hex hmac> }
    # Eski format: { platform_order_id, status, random_nr, signature }
    if "res" in payload and "hash" in payload:
        res_b64 = payload.get("res", "")
        recv_hash = (payload.get("hash") or "").lower()
        SHOPIER_API_KEY = os.environ.get("SHOPIER_API_KEY", "").strip()
        # Hash doğrula: hash_hmac('sha256', res + USERNAME, SECRET, false=hex)
        # Shopier resmi PHP: hash_hmac('sha256', $_POST['res'] . $username, $key, false)
        signed_data = (res_b64 + SHOPIER_API_KEY).encode("utf-8")
        expected_hash = _hmac.new(SHOPIER_API_SECRET.encode(), signed_data, _hashlib.sha256).hexdigest().lower()
        if not _hmac.compare_digest(expected_hash, recv_hash):
            logger.warning(f"Shopier yeni callback hash uyuşmadı. expected={expected_hash[:20]}... got={recv_hash[:20]}...")
            return {"ok": False, "status": "hash_invalid"}
        try:
            decoded_json = _base64.b64decode(res_b64).decode("utf-8")
            data = _json.loads(decoded_json)
        except Exception as e:
            logger.error(f"Shopier res decode hatası: {e}")
            return {"ok": False, "status": "decode_error"}

        is_test = bool(data.get("istest"))
        if is_test:
            logger.info(f"Shopier TEST callback alındı (yok sayıldı): {data}")
            return {"ok": True, "status": "test", "test": True}

        # Gerçek ödeme: Shopier orderid (kendi iç ID'si) ile bizim siparişi eşleştir
        # Bizim platform_order_id'yi 'customernote' veya başka alanda göndermediğimiz için,
        # Shopier'ın `orderid`'sini bizim wallet_tx.referans olarak takip etmemiz gerekiyor.
        # Şu an basit eşleşme: en son yapılan shopier_beklemede tx (price ile)
        price_str = str(data.get("price", "")).replace(",", ".")
        try:
            price = float(price_str)
        except Exception:
            price = 0.0
        buyer_email = (data.get("email") or "").lower()
        # Önce buyer_email ile aktif beklemede tx'leri bul
        candidate_txs = await db.wallet_tx.find({
            "tip": "shopier_beklemede",
            "durum": "beklemede",
            "brut_tutar": price,
        }, {"_id": 0}).sort("tarih", -1).to_list(20)
        if not candidate_txs:
            logger.warning(f"Shopier callback: eşleşen sipariş bulunamadı price={price}, email={buyer_email}")
            return {"ok": False, "status": "no_match"}
        # En son olanı al
        tx = candidate_txs[0]

        # Ödeme başarılı kabul et (test değilse hash doğru → ödeme alındı)
        await wallet_add_transaction(
            tx["customer_id"], tx["tutar"], "yukleme",
            tx.get("aciklama", f"Shopier ödeme - {data.get('orderid')}"),
            referans=f"SHOPIER-{data.get('orderid')}",
        )
        await db.wallet_tx.update_one({"id": tx["id"]}, {"$set": {"durum": "tamamlandi", "shopier_orderid": str(data.get("orderid"))}})
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "baslik": "Shopier Ödeme Başarılı",
            "mesaj": f"{tx['tutar']:.2f}₺ bakiyenize eklendi.",
            "hedef_type": "secili",
            "hedef_customer_ids": [tx["customer_id"]],
            "tarih": now_iso(), "okuyanlar": [],
        })
        return {"ok": True, "status": "success", "shopier_orderid": data.get("orderid")}

    # ESKİ format (legacy)
    order_id = payload.get("platform_order_id") or payload.get("order_id")
    status = (payload.get("status") or "").lower()
    random_nr = payload.get("random_nr") or ""
    sig = payload.get("signature") or ""
    if not order_id:
        raise HTTPException(400, "platform_order_id eksik")

    tx = await db.wallet_tx.find_one({"referans": order_id, "tip": "shopier_beklemede"}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Sipariş bulunamadı")
    if tx.get("durum") == "tamamlandi":
        return {"ok": True, "already": True, "status": "success"}

    raw = f"{random_nr}{order_id}{status}"
    expected = _base64.b64encode(_hmac.new(SHOPIER_API_SECRET.encode(), raw.encode(), _hashlib.sha256).digest()).decode()
    sig_ok = _hmac.compare_digest(expected, sig)
    if not sig_ok and status == "success":
        logger.warning(f"Shopier eski format imza uyuşmadı (order={order_id})")

    if status == "success":
        await wallet_add_transaction(
            tx["customer_id"], tx["tutar"], "yukleme",
            tx.get("aciklama", f"Shopier ödeme - {order_id}"),
            referans=f"SHOPIER-{order_id}",
        )
        await db.wallet_tx.update_one({"id": tx["id"]}, {"$set": {"durum": "tamamlandi"}})
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "baslik": "Shopier Ödeme Başarılı",
            "mesaj": f"{tx['tutar']:.2f}₺ bakiyenize eklendi.",
            "hedef_type": "secili",
            "hedef_customer_ids": [tx["customer_id"]],
            "tarih": now_iso(), "okuyanlar": [],
        })
    else:
        await db.wallet_tx.update_one({"id": tx["id"]}, {"$set": {"durum": "basarisiz"}})
    return {"ok": True, "status": status}

@api.post("/wallet/shopier/callback")
async def shopier_callback_form(request: _FastRequest):
    """Shopier'in ödeme bildirim callback'i. Shopier her zaman 200 OK bekler;
    aksi halde test sipariş bildirimi başarısız olur. Hatalar sadece loglanır.
    """
    try:
        form = await request.form()
        payload = {k: form.get(k) for k in form.keys()}
        logger.info(f"Shopier callback received: order={payload.get('platform_order_id')} status={payload.get('status')}")
    except Exception as e:
        logger.error(f"Shopier callback form parse error: {e}")
        return PlainTextResponse(content="success", status_code=200)

    try:
        result = await _process_shopier_callback(payload)
        return PlainTextResponse(content="success", status_code=200)
    except HTTPException as he:
        # Order bulunamadı (test bildirimi olabilir) veya geçersiz veri → yine 200 OK dön
        logger.warning(f"Shopier callback ignored ({he.status_code}): {he.detail} payload={payload}")
        return PlainTextResponse(content="success", status_code=200)
    except Exception as e:
        logger.error(f"Shopier callback unexpected error: {e}")
        return PlainTextResponse(content="success", status_code=200)

# GET versiyonu — Shopier panel'den "test sipariş bildirimi" bazen GET ile de check eder
@api.get("/wallet/shopier/callback")
async def shopier_callback_get():
    """Shopier'in callback URL'ine GET attığında 200 OK dönelim (URL doğrulama için)."""
    return PlainTextResponse(content="OK", status_code=200)

# Shopier başarılı dönüş URL'i — kullanıcının tarayıcı yönlendirileceği başarı/iptal sayfası
@api.get("/wallet/shopier/return/{order_id}", response_class=HTMLResponse)
async def shopier_return(order_id: str):
    tx = await db.wallet_tx.find_one({"referans": order_id}, {"_id": 0})
    durum = tx.get("durum") if tx else "yok"
    color = "#15803d" if durum == "tamamlandi" else ("#a30015" if durum == "basarisiz" else "#999")
    text = "Ödemeniz Başarılı!" if durum == "tamamlandi" else ("Ödeme Başarısız" if durum == "basarisiz" else "Ödeme İşleniyor...")
    return HTMLResponse(f"""<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
<title>Ödeme Sonucu</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{font-family:-apple-system,Roboto,sans-serif;background:#0d0e10;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;padding:20px;text-align:center}}
.box{{max-width:380px}}
h1{{color:{color};margin:0 0 12px}}
p{{color:#aaa}}</style></head>
<body><div class="box">
<h1>{text}</h1>
<p>Sipariş No: <code>{order_id}</code></p>
<p>Bu pencereyi kapatabilirsiniz, uygulamada bakiyeniz güncellenecektir.</p>
</div></body></html>""")

# ==================== CUSTOMER: Notifications ====================
@api.get("/notifications")
async def my_notifications(user: dict = Depends(require_customer)):
    docs = await db.notifications.find({
        "$or": [
            {"hedef_type": "tum"},
            {"hedef_type": "secili", "hedef_customer_ids": user["id"]},
        ],
    }, {"_id": 0}).sort("tarih", -1).to_list(200)
    for d in docs:
        d["okundu"] = user["id"] in (d.get("okuyanlar") or [])
    return docs

@api.get("/notifications/unread-count")
async def unread_count(user: dict = Depends(require_customer)):
    docs = await db.notifications.find({
        "$or": [
            {"hedef_type": "tum"},
            {"hedef_type": "secili", "hedef_customer_ids": user["id"]},
        ],
        "okuyanlar": {"$nin": [user["id"]]},
    }).to_list(500)
    return {"count": len(docs)}

@api.post("/notifications/{nid}/read")
async def mark_read(nid: str, user: dict = Depends(require_customer)):
    await db.notifications.update_one({"id": nid}, {"$addToSet": {"okuyanlar": user["id"]}})
    return {"ok": True}

@api.post("/notifications/read-all")
async def mark_all_read(user: dict = Depends(require_customer)):
    docs = await db.notifications.find({
        "$or": [{"hedef_type": "tum"}, {"hedef_type": "secili", "hedef_customer_ids": user["id"]}],
    }).to_list(500)
    for d in docs:
        await db.notifications.update_one({"id": d["id"]}, {"$addToSet": {"okuyanlar": user["id"]}})
    return {"ok": True}

# ==================== Public Settings ====================
@api.get("/settings/public")
async def public_settings():
    s = await db.settings.find_one({"key": "company"}, {"_id": 0})
    return s or {}

@api.get("/holidays/public")
async def public_holidays():
    docs = await db.holidays.find({}, {"_id": 0}).sort("tarih", 1).to_list(200)
    return docs


# ==================== SPONSORS / İŞ ORTAKLARI ====================
class SponsorIn(BaseModel):
    ad: str
    logo_base64: Optional[str] = None  # data:image/png;base64,... veya null
    whatsapp: str
    icons: Optional[List[str]] = []    # Ionicons name list (2-5 sektör ikonu)
    icon: Optional[str] = None         # geriye dönük uyumluluk için
    mesaj_template: Optional[str] = "Merhaba, YS AUTO uygulaması üzerinden iletişime geçiyorum."
    sira: int = 0
    aktif: bool = True

@api.get("/sponsors/public")
async def public_sponsors():
    """Müşteri tarafı — sadece aktif sponsorlar, sıralanmış."""
    docs = await db.sponsors.find({"aktif": True}, {"_id": 0}).sort("sira", 1).to_list(100)
    # geriye dönük: eski 'icon' (tekil) -> 'icons' (liste) normalize
    for d in docs:
        if not d.get("icons") and d.get("icon"):
            d["icons"] = [d["icon"]]
        elif not d.get("icons"):
            d["icons"] = []
    return docs

@api.get("/admin/sponsors")
async def admin_list_sponsors(_: dict = Depends(require_admin)):
    docs = await db.sponsors.find({}, {"_id": 0}).sort("sira", 1).to_list(100)
    for d in docs:
        if not d.get("icons") and d.get("icon"):
            d["icons"] = [d["icon"]]
        elif not d.get("icons"):
            d["icons"] = []
    return docs

@api.post("/admin/sponsors")
async def admin_create_sponsor(body: SponsorIn, _: dict = Depends(require_admin)):
    doc = body.model_dump()
    doc["id"] = str(uuid.uuid4())
    doc["created_at"] = now_iso()
    doc["updated_at"] = now_iso()
    await db.sponsors.insert_one(doc)
    doc.pop("_id", None)
    return doc

@api.put("/admin/sponsors/{sid}")
async def admin_update_sponsor(sid: str, body: SponsorIn, _: dict = Depends(require_admin)):
    update = body.model_dump()
    update["updated_at"] = now_iso()
    r = await db.sponsors.update_one({"id": sid}, {"$set": update})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Sponsor bulunamadı")
    doc = await db.sponsors.find_one({"id": sid}, {"_id": 0})
    return doc

@api.delete("/admin/sponsors/{sid}")
async def admin_delete_sponsor(sid: str, _: dict = Depends(require_admin)):
    r = await db.sponsors.delete_one({"id": sid})
    if r.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Sponsor bulunamadı")
    return {"ok": True}


# ==================== ADMIN: Customers ====================
@api.get("/admin/customers")
async def admin_list_customers(_: dict = Depends(require_admin), q: Optional[str] = Query(None), filtre: Optional[str] = Query(None)):
    query = {}
    if q:
        rgx = {"$regex": re.escape(q), "$options": "i"}
        query = {"$or": [{"ad": rgx}, {"soyad": rgx}, {"telefon": rgx}, {"email": rgx}, {"firma_adi": rgx}, {"tc_norm": q}]}
    if filtre == "engelli":
        query["blocked"] = True
    elif filtre == "kurumsal":
        query["tip"] = "kurumsal"
    elif filtre == "bireysel":
        query["tip"] = {"$in": ["bireysel", None]}
    docs = await db.customers.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    # ⚡ N+1 fix: Tüm wallet'ları TEK sorguda çek
    customer_ids = [d["id"] for d in docs]
    wallets = await db.wallets.find(
        {"customer_id": {"$in": customer_ids}},
        {"_id": 0, "customer_id": 1, "bakiye": 1},
    ).to_list(len(customer_ids) + 10)
    wallet_by_cid = {w["customer_id"]: w.get("bakiye", 0.0) for w in wallets}
    for d in docs:
        d["tc_masked"] = (d.get("tc_norm", "") or "")[:3] + "*****" + (d.get("tc_norm", "") or "")[-2:]
        d["bakiye"] = wallet_by_cid.get(d["id"], 0.0)
    return docs

@api.post("/admin/customers")
async def admin_create_customer(body: CustomerCreate, _: dict = Depends(require_admin)):
    tc = normalize_tc(body.tc)
    if len(tc) != 11:
        raise HTTPException(400, "TC 11 haneli olmalı")
    if await db.customers.find_one({"tc_norm": tc}):
        raise HTTPException(400, "Bu TC ile kayıtlı müşteri zaten var")
    c = {
        "id": str(uuid.uuid4()),
        "ad": body.ad.strip(), "soyad": body.soyad.strip(),
        "tc_norm": tc, "telefon": body.telefon.strip(),
        "email": (body.email or "").strip() or None,
        "notlar": body.notlar or "",
        "adres": (body.adres or "").strip() or None,
        "tip": body.tip or "bireysel",
        "firma_adi": (body.firma_adi or "").strip() or None,
        "vergi_no": (body.vergi_no or "").strip() or None,
        "yetkili": (body.yetkili or "").strip() or None,
        "blocked": False,
        "created_at": now_iso(),
    }
    await db.customers.insert_one(dict(c))
    return await db.customers.find_one({"id": c["id"]}, {"_id": 0})

@api.put("/admin/customers/{cid}")
async def admin_update_customer(cid: str, body: CustomerUpdate, _: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if "blocked" in upd and upd["blocked"] is False:
        upd["block_reason"] = None
    # TC normalize + benzersizlik kontrolü
    if "tc" in upd:
        tc_clean = normalize_tc(upd.pop("tc"))
        if tc_clean:
            if len(tc_clean) != 11:
                raise HTTPException(400, "TC Kimlik Numarası 11 haneli olmalıdır")
            # Aynı TC ile başka müşteri var mı?
            dup = await db.customers.find_one({"tc_norm": tc_clean, "id": {"$ne": cid}})
            if dup:
                raise HTTPException(400, f"Bu TC ile zaten kayıtlı bir müşteri var: {dup.get('ad','')} {dup.get('soyad','')}")
            # Admin tablosunda da çakışıyor mu?
            adm = await db.admins.find_one({"tc_norm": tc_clean})
            if adm:
                raise HTTPException(400, "Bu TC bir yönetici hesabına ait")
            upd["tc_norm"] = tc_clean
        else:
            # Boş TC gönderildiyse temizle
            upd["tc_norm"] = ""
    # Telefon normalize → telefon_norm
    if "telefon" in upd:
        upd["telefon_norm"] = normalize_phone(upd["telefon"] or "")
    if upd:
        await db.customers.update_one({"id": cid}, {"$set": upd})
    return await db.customers.find_one({"id": cid}, {"_id": 0})

@api.delete("/admin/customers/{cid}")
async def admin_delete_customer(cid: str, _: dict = Depends(require_admin)):
    await db.customers.delete_one({"id": cid})
    return {"ok": True}

# Admin: View as customer — generate a customer token for impersonation
@api.post("/admin/customers/{cid}/view-as")
async def admin_view_as_customer(cid: str, _: dict = Depends(require_admin)):
    cust = await db.customers.find_one({"id": cid}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Müşteri bulunamadı")
    return TokenOut(token=make_token(cust["id"], "customer", tenant_id=cust.get("tenant_id")), role="customer", user={
        "id": cust["id"], "ad": cust["ad"], "soyad": cust["soyad"],
        "telefon": cust.get("telefon"), "email": cust.get("email"),
    })

# Admin: Manual wallet credit
@api.post("/admin/customers/{cid}/wallet/credit")
async def admin_wallet_credit(cid: str, tutar: float, aciklama: str = "Yönetici tarafından bakiye eklendi", _: dict = Depends(require_admin)):
    if tutar <= 0:
        raise HTTPException(400, "Tutar pozitif olmalı")
    result = await wallet_add_transaction(cid, tutar, "yukleme", aciklama, referans="ADMIN")
    # Auto-settle: açık rezervasyonların kalan ödemelerinden düş
    settlement = await auto_settle_pending_payments(cid)
    # Müşteriye bildirim gönder
    if settlement.get("applied_total", 0) > 0:
        bildirim_msg = f"+{tutar:.2f}₺ bakiyenize eklendi. Bu bakiyeden {settlement['applied_total']:.2f}₺ açık rezervasyonlarınızın ödemesine otomatik aktarıldı."
    else:
        bildirim_msg = f"+{tutar:.2f}₺ bakiyenize eklendi. {aciklama}"
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Bakiye Eklendi",
        "mesaj": bildirim_msg,
        "hedef_type": "secili",
        "hedef_customer_ids": [cid],
        "tarih": now_iso(),
        "okuyanlar": [],
    })
    # Bakiye değerini son durum ile güncelle
    result["bakiye"] = settlement.get("bakiye_kalan", result.get("bakiye"))
    result["auto_settlement"] = settlement
    return result

@api.post("/admin/customers/{cid}/wallet/debit")
async def admin_wallet_debit(cid: str, tutar: float, aciklama: str = "Yönetici tarafından düşüldü", _: dict = Depends(require_admin)):
    if tutar <= 0:
        raise HTTPException(400, "Tutar pozitif olmalı")
    result = await wallet_add_transaction(cid, tutar, "odeme", aciklama, referans="ADMIN")
    # Müşteriye bildirim gönder
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Bakiye Düşüldü",
        "mesaj": f"-{tutar:.2f}₺ bakiyenizden düşüldü. {aciklama}",
        "hedef_type": "secili",
        "hedef_customer_ids": [cid],
        "tarih": now_iso(),
        "okuyanlar": [],
    })
    return result

@api.get("/admin/customers/{cid}/wallet")
async def admin_get_wallet(cid: str, _: dict = Depends(require_admin)):
    w = await get_wallet(cid)
    txs = await db.wallet_tx.find({"customer_id": cid}, {"_id": 0}).sort("tarih", -1).to_list(200)
    return {"bakiye": w["bakiye"], "transactions": txs}

# ==================== ADMIN: Vehicles ====================
@api.get("/admin/vehicles/available")
async def admin_vehicles_available(
    gun: str = Query("bugun", regex="^(bugun|yarin)$"),
    _: dict = Depends(require_admin),
):
    """Belirtilen gün için (bugün/yarın) rezerve edilebilir araçları listeler.
    Onaylı + aktif rezervasyonları kontrol eder. Aracın anlık durumu (musait/dolu) yok sayılır.
    Her aracın yanında sonraki aktif rezervasyonun başlangıcı + önceki rezervasyonun bitişi döner (varsa).
    YENİ: Türkiye saatine göre (UTC+3) hesaplanır — UTC olmaz, kullanıcı 00:00–03:00 arasında 'yarın' tabını yanlış görmez.
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    # Hedef gün penceresi — TÜRKİYE SAATİNE GÖRE (UTC+3)
    now_utc = _dt.now(_tz.utc)
    tr_now = now_utc + _td(hours=3)  # Türkiye yerel saati
    tr_today = tr_now.replace(hour=0, minute=0, second=0, microsecond=0)
    offset = 1 if gun == "yarin" else 0
    # TR yerel pencereyi UTC'ye çevir (DB ISO UTC formatta)
    window_start_tr = tr_today + _td(days=offset)
    window_end_tr = window_start_tr + _td(days=1)
    # TR → UTC: -3 saat
    window_start = window_start_tr - _td(hours=3)
    window_end = window_end_tr - _td(hours=3)

    # Mesai başlangıç saatini ayarlardan al
    s = await get_settings()
    mesai_baslangic = s.get("mesai_baslangic", "09:00")

    # Tüm araçları çek
    vehicles = await db.vehicles.find({}, {"_id": 0}).sort([("siralama", 1), ("created_at", -1)]).to_list(200)

    # Aktif/onaylı rezervasyonları çek
    reservations = await db.reservations.find(
        {"durum": {"$in": ["aktif", "onaylandi"]}},
        {"_id": 0, "vehicle_id": 1, "baslangic_tarihi": 1, "bitis_tarihi": 1, "durum": 1, "vehicle_snapshot": 1},
    ).to_list(length=None)

    # Araç bazlı rezervasyon haritası
    res_by_vehicle: dict = {}
    for r in reservations:
        vid = r.get("vehicle_id")
        if not vid:
            continue
        try:
            bas = parse_iso(r["baslangic_tarihi"])
            bit = parse_iso(r["bitis_tarihi"])
        except Exception:
            continue
        res_by_vehicle.setdefault(vid, []).append({
            "bas": bas, "bit": bit, "durum": r.get("durum"),
        })

    out = []
    for v in vehicles:
        vid = v.get("id")
        v_rezler = res_by_vehicle.get(vid, [])
        # Pencere ile çakışan rezervasyon var mı?
        cakisma = next((r for r in v_rezler if r["bas"] < window_end and r["bit"] > window_start), None)
        # Pencereden sonra başlayan en yakın rezervasyon
        sonraki = sorted(
            [r for r in v_rezler if r["bas"] >= window_end],
            key=lambda x: x["bas"],
        )
        sonraki_baslangic = sonraki[0]["bas"].isoformat() if sonraki else None
        # Pencereden önce/içinde biten en yakın rezervasyon (temizlik tamponu için)
        onceki = sorted(
            [r for r in v_rezler if r["bit"] <= window_end],
            key=lambda x: x["bit"], reverse=True,
        )
        onceki_bitis = onceki[0]["bit"].isoformat() if onceki else None

        out.append({
            "id": vid,
            "plaka": v.get("plaka"),
            "marka": v.get("marka"),
            "model": v.get("model"),
            "foto_url": v.get("foto_url"),
            "gunluk_fiyat": v.get("gunluk_fiyat"),
            "available": cakisma is None,
            "conflict": None if not cakisma else {
                "baslangic": cakisma["bas"].isoformat(),
                "bitis": cakisma["bit"].isoformat(),
                "durum": cakisma["durum"],
            },
            "next_reservation": sonraki_baslangic,
            "prev_reservation_end": onceki_bitis,
        })

    return {
        "gun": gun,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "mesai_baslangic": mesai_baslangic,
        "vehicles": out,
        "available_count": sum(1 for x in out if x["available"]),
        "occupied_count": sum(1 for x in out if not x["available"]),
    }


# Admin: belirli bir tarih için müsait + yakında dönen araçlar
@api.get("/admin/vehicles/available-at")
async def admin_vehicles_available_at(
    target_iso: str = Query(..., description="Hedef tarih+saat ISO formatında (TR yerel)"),
    tolerance_days: int = Query(2, ge=0, le=14),
    _: dict = Depends(require_admin),
):
    """Belirli bir hedef tarih için araç müsaitliğini ve yakında dönenleri listeler.
    - musait: hedef anda dolu olmayan araçlar
    - yaklasan: şu an dolu ama dönüş tarihi hedef tarihten ±tolerance gün içinde olan araçlar
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    try:
        target_tr = _dt.fromisoformat(target_iso.replace('Z', '+00:00'))
        if target_tr.tzinfo is None:
            # TR yerel kabul et
            target_utc = target_tr - _td(hours=3)
        else:
            target_utc = target_tr.astimezone(_tz.utc).replace(tzinfo=None)
            target_tr = target_utc + _td(hours=3)
    except Exception:
        raise HTTPException(400, "target_iso geçersiz")

    s = await get_settings()
    mesai_baslangic = s.get("mesai_baslangic", "09:00")

    vehicles = await db.vehicles.find({}, {"_id": 0}).sort([("siralama", 1), ("created_at", -1)]).to_list(200)
    reservations = await db.reservations.find(
        {"durum": {"$in": ["aktif", "onaylandi"]}},
        {"_id": 0, "vehicle_id": 1, "baslangic_tarihi": 1, "bitis_tarihi": 1, "durum": 1},
    ).to_list(length=None)

    res_by_vehicle: dict = {}
    for r in reservations:
        vid = r.get("vehicle_id")
        if not vid:
            continue
        try:
            bas = parse_iso(r["baslangic_tarihi"])
            bit = parse_iso(r["bitis_tarihi"])
            # Naive'e dönüştür (tutarlılık için)
            if bas.tzinfo is not None:
                bas = bas.astimezone(_tz.utc).replace(tzinfo=None)
            if bit.tzinfo is not None:
                bit = bit.astimezone(_tz.utc).replace(tzinfo=None)
        except Exception:
            continue
        res_by_vehicle.setdefault(vid, []).append({"bas": bas, "bit": bit, "durum": r.get("durum")})

    musait = []
    yaklasan = []
    tolerance_seconds = tolerance_days * 24 * 3600

    for v in vehicles:
        vid = v.get("id")
        v_rezler = res_by_vehicle.get(vid, [])
        # Hedef anı kapsayan rezervasyon var mı?
        cakisma = next((r for r in v_rezler if r["bas"] <= target_utc < r["bit"]), None)
        # En yakın dönüş (hedef öncesi/sonrası fark etmez, mutlak değere göre)
        nearest_return = None
        nearest_gap_seconds = None
        for r in v_rezler:
            gap = (r["bit"] - target_utc).total_seconds()
            if nearest_gap_seconds is None or abs(gap) < abs(nearest_gap_seconds):
                nearest_gap_seconds = gap
                nearest_return = r["bit"]
        # Hedef sonrası ilk başlayan rezervasyon (yeni rezervasyon için bilgi)
        sonraki = sorted([r for r in v_rezler if r["bas"] > target_utc], key=lambda x: x["bas"])
        sonraki_baslangic = sonraki[0]["bas"].isoformat() if sonraki else None
        # Hedef öncesi son biten rezervasyon
        onceki = sorted([r for r in v_rezler if r["bit"] <= target_utc], key=lambda x: x["bit"], reverse=True)
        onceki_bitis = onceki[0]["bit"].isoformat() if onceki else None

        base = {
            "id": vid,
            "plaka": v.get("plaka"),
            "marka": v.get("marka"),
            "model": v.get("model"),
            "foto_url": v.get("foto_url"),
            "gunluk_fiyat": v.get("gunluk_fiyat"),
            "available": cakisma is None,
            "next_reservation": sonraki_baslangic,
            "prev_reservation_end": onceki_bitis,
        }
        if cakisma is None:
            musait.append(base)
        else:
            # Dolu — dönüş tarihi hedef tarihten ±tolerance gün içinde mi?
            gap = (cakisma["bit"] - target_utc).total_seconds()
            if abs(gap) <= tolerance_seconds:
                base["return_iso"] = cakisma["bit"].isoformat()
                base["gap_seconds"] = int(gap)
                base["gap_hours"] = round(gap / 3600, 1)
                base["conflict"] = {
                    "baslangic": cakisma["bas"].isoformat(),
                    "bitis": cakisma["bit"].isoformat(),
                    "durum": cakisma["durum"],
                }
                yaklasan.append(base)

    # Yaklasan listesini hedefe yakınlığa göre sırala
    yaklasan.sort(key=lambda x: abs(x.get("gap_seconds", 0)))

    return {
        "target": target_utc.isoformat(),
        "target_tr": target_tr.isoformat(),
        "tolerance_days": tolerance_days,
        "mesai_baslangic": mesai_baslangic,
        "musait": musait,
        "yaklasan": yaklasan,
        "musait_count": len(musait),
        "yaklasan_count": len(yaklasan),
    }


@api.get("/admin/quote/{vehicle_id}")
async def admin_quote(
    vehicle_id: str,
    gun: int = Query(1, ge=1, le=365),
    _: dict = Depends(require_admin),
):
    """WhatsApp teklif mesajı için fiyatlandırma + KM + zorunlu hizmet özeti.
    Aracın gün-bazlı kademeli fiyat, KM paketi, km aşım fiyatı ve zorunlu hizmetlerini döner.
    """
    v = await db.vehicles.find_one({"id": vehicle_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    s = await get_settings()
    # Liste (max) ve indirimli (kademe) günlük fiyatlar
    fallback_price = float(v.get("gunluk_fiyat", 0) or 0)
    indirimli = daily_price_for(v, gun)
    matched = matched_price_kademe(v, gun)
    # Liste fiyatı = kademelerin en yüksek fiyatı, yoksa fallback
    kademeler = v.get("gunluk_fiyat_kademeleri") or []
    if kademeler:
        try:
            liste_fiyat = max(float(k.get("gunluk_fiyat", 0) or 0) for k in kademeler)
            liste_fiyat = max(liste_fiyat, fallback_price)
        except Exception:
            liste_fiyat = fallback_price
    else:
        liste_fiyat = fallback_price

    gunluk_km = daily_km_for(v, gun)
    toplam_km = paket_km_for(v, gun)  # ✨ Kademeli/kümülatif toplam (örn. 7×250+3×120)
    km_asim_fiyat = km_asim_for(v, s, days=gun)

    # Zorunlu ek hizmetler
    zorunlu_q = {"aktif": True, "zorunlu": True, "$or": [{"arac_ids": {"$exists": False}}, {"arac_ids": {"$size": 0}}, {"arac_ids": vehicle_id}]}
    zorunlu_docs = await db.services.find(zorunlu_q, {"_id": 0}).to_list(50)
    zorunlu_list = []
    zorunlu_toplam = 0.0
    for z in zorunlu_docs:
        fiyat = float(z.get("fiyat", 0) or 0)
        birim = z.get("birim", "kira_basina")  # 'gunluk' veya 'kira_basina'
        tutar = fiyat * gun if birim == "gunluk" else fiyat
        zorunlu_toplam += tutar
        zorunlu_list.append({
            "ad": z.get("ad"),
            "aciklama": z.get("aciklama"),
            "fiyat": fiyat,
            "birim": birim,
            "tutar": tutar,
        })

    kira_toplam = indirimli * gun
    grand_total = kira_toplam + zorunlu_toplam

    return {
        "vehicle": {
            "id": v.get("id"),
            "plaka": v.get("plaka"),
            "marka": v.get("marka"),
            "model": v.get("model"),
            "vites": v.get("vites"),
            "yakit": v.get("yakit"),
        },
        "gun": gun,
        "liste_fiyat": liste_fiyat,
        "indirimli_fiyat": indirimli,
        "fiyat_kademe_matched": matched,
        "gunluk_km": gunluk_km,
        "toplam_km": toplam_km,
        "km_kademeleri": v.get("km_kademeleri") or [],
        "km_asim_fiyat": km_asim_fiyat,
        "zorunlu_hizmetler": zorunlu_list,
        "zorunlu_toplam": zorunlu_toplam,
        "kira_toplam": kira_toplam,
        "grand_total": grand_total,
        "iletisim_telefon": s.get("iletisim_telefon"),
        "firma_adi": s.get("firma_adi") or "YS AUTO - Araç Kiralama",
    }


@api.get("/admin/vehicles")
async def admin_list_vehicles(_: dict = Depends(require_admin)):
    docs = await db.vehicles.find({}, {"_id": 0}).sort([("siralama", 1), ("created_at", -1)]).to_list(200)
    for v in docs:
        v["durum"] = await compute_vehicle_status(v)
        # GPS bot'tan canlı KM al — bot offline ise saklı mevcut_km değerini kullan (mock fallback)
        try:
            live = await get_live_vehicle(v.get("plaka", ""))
            if live:
                # Çoklu alan: DeviceTotalDistance (yeni bot) / odometer / km
                km_val = live.get("DeviceTotalDistance") or live.get("odometer") or live.get("km")
                if km_val is not None:
                    v["canli_km"] = int(km_val)
                # Konum & motor bilgileri
                if live.get("DeviceLatitude") is not None:
                    v["canli_konum"] = {
                        "lat": live.get("DeviceLatitude"),
                        "lng": live.get("DeviceLongitude"),
                        "yon": live.get("DeviceDirection"),
                        "hiz": live.get("DeviceSpeed"),
                    }
                if live.get("DeviceIsIgnitionOn") is not None:
                    v["motor_durumu"] = "calisiyor" if live.get("DeviceIsIgnitionOn") else "kapali"
                if live.get("DeviceIsEngineBloked") is not None:
                    v["motor_blokaj_aktif"] = bool(live.get("DeviceIsEngineBloked"))
                if live.get("DeviceLastUpdate"):
                    v["bot_son_guncelleme"] = live.get("DeviceLastUpdate")
        except Exception:
            pass
        if "canli_km" not in v and v.get("mevcut_km") is not None:
            v["canli_km"] = v["mevcut_km"]
    return docs

@api.post("/admin/vehicles")
async def admin_create_vehicle(body: VehicleCreate, _: dict = Depends(require_admin)):
    v = {"id": str(uuid.uuid4()), "created_at": now_iso(), **body.dict()}
    # foto_url <-> fotograflar[0] senkronizasyonu (geriye uyumluluk)
    if v.get("fotograflar") and not v.get("foto_url"):
        v["foto_url"] = v["fotograflar"][0]
    elif v.get("foto_url") and not v.get("fotograflar"):
        v["fotograflar"] = [v["foto_url"]]
    await db.vehicles.insert_one(dict(v))
    return await db.vehicles.find_one({"id": v["id"]}, {"_id": 0})

@api.put("/admin/vehicles/{vid}")
async def admin_update_vehicle(vid: str, body: VehicleUpdate, _: dict = Depends(require_admin)):
    # exclude_unset=True: sadece istemcinin gerçekten gönderdiği alanları al.
    # None değerleri SAKLA — özellikle manuel_durum=None "Otomatik" durumuna geçişi için kritik.
    upd = body.dict(exclude_unset=True)
    # fotograflar gönderildi ise foto_url'i ilk fotoyla senkronize et
    if "fotograflar" in upd:
        fl = upd.get("fotograflar") or []
        upd["foto_url"] = fl[0] if fl else ""
    if upd:
        await db.vehicles.update_one({"id": vid}, {"$set": upd})
    return await db.vehicles.find_one({"id": vid}, {"_id": 0})

@api.put("/admin/vehicles/order")
async def admin_reorder_vehicles(payload: dict, _: dict = Depends(require_admin)):
    """Bulk update vehicle order. Payload: {orders: [{id, siralama}, ...]}"""
    orders = payload.get("orders") or []
    if not isinstance(orders, list):
        raise HTTPException(400, "orders bir liste olmalı")
    updated = 0
    for item in orders:
        vid = item.get("id")
        sira = item.get("siralama")
        if vid and sira is not None:
            r = await db.vehicles.update_one({"id": vid}, {"$set": {"siralama": int(sira)}})
            if r.modified_count:
                updated += 1
    return {"ok": True, "updated": updated}


@api.delete("/admin/vehicles/{vid}")
async def admin_delete_vehicle(vid: str, _: dict = Depends(require_admin)):
    await db.vehicles.delete_one({"id": vid})
    return {"ok": True}

class MotorBlokajIn(BaseModel):
    aktif: bool  # true = motor KİTLE, false = motor AÇ

@api.post("/admin/vehicles/{vid}/motor-blokaj")
async def admin_motor_blokaj(vid: str, body: MotorBlokajIn, _: dict = Depends(require_admin)):
    """Admin manuel motor blokaj kontrolü.
    Bot endpoint'ine POST atar, sonucu döner."""
    v = await db.vehicles.find_one({"id": vid}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    plaka = v.get("plaka", "")
    if not plaka:
        raise HTTPException(400, "Aracın plakası yok")
    ok = await bot_motor_blokaj(plaka, body.aktif)
    await db.vehicles.update_one({"id": vid}, {"$set": {
        "manuel_motor_blokaj": bool(body.aktif),
        "manuel_motor_blokaj_tarih": now_iso(),
    }})
    # Aktif rezervasyon varsa onun motor_kilitli flag'ini de güncelle (UI tutarlılığı için)
    active = await db.reservations.find_one({
        "vehicle_id": vid,
        "durum": {"$in": ["onaylandi", "aktif"]},
    }, {"_id": 0})
    if active:
        await db.reservations.update_one({"id": active["id"]}, {"$set": {
            "motor_kilitli": bool(body.aktif),
            "motor_kilit_tarih" if body.aktif else "motor_acilis_tarih": now_iso(),
        }})
        # Müşteriye bildirim
        try:
            if body.aktif:
                await notify_customer(
                    active["customer_id"],
                    "Motor Manuel Kilitlendi",
                    f"{v.get('marka','')} {v.get('model','')} ({plaka}) — Aracınızın motoru yönetim tarafından kilitlendi. Detay için iletişime geçin.",
                    {"type": "motor_locked_manual", "reservation_id": active["id"]},
                )
            else:
                await notify_customer(
                    active["customer_id"],
                    "Motor Açıldı",
                    f"{v.get('marka','')} {v.get('model','')} ({plaka}) aracınızın motoru açılmıştır. İyi yolculuklar dileriz! 🚗",
                    {"type": "motor_unlocked_manual", "reservation_id": active["id"]},
                )
        except Exception as e:
            logger.warning(f"notify after manual blokaj err: {e}")
    return {"ok": True, "bot_responded": ok, "plaka": plaka, "aktif": body.aktif}

# ==================== ADMIN: Reservations ====================
@api.get("/admin/reservations")
async def admin_list_reservations(_: dict = Depends(require_admin), durum: Optional[str] = None):
    q = {}
    if durum:
        q["durum"] = durum
    docs = await db.reservations.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    # ⚡ N+1 fix: Tüm müşterileri TEK sorguda çek
    customer_ids = list({r["customer_id"] for r in docs if r.get("customer_id")})
    customers = await db.customers.find(
        {"id": {"$in": customer_ids}},
        {"_id": 0, "id": 1, "ad": 1, "soyad": 1, "telefon": 1, "tc_norm": 1},
    ).to_list(len(customer_ids) + 10) if customer_ids else []
    cust_by_id = {c["id"]: c for c in customers}
    for r in docs:
        c = cust_by_id.get(r.get("customer_id"))
        if c:
            r["musteri"] = {
                "ad": c["ad"],
                "soyad": c["soyad"],
                "telefon": c.get("telefon"),
                "tc_masked": (c.get("tc_norm", "") or "")[:3] + "*****" + (c.get("tc_norm", "") or "")[-2:],
            }
    return docs

@api.put("/admin/reservations/{rid}/durum")
async def admin_set_reservation_status(rid: str, durum: str, _: dict = Depends(require_admin)):
    if durum not in ("beklemede", "onaylandi", "aktif", "tamamlandi", "iptal"):
        raise HTTPException(400, "Geçersiz durum")

    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")

    eski_durum = r.get("durum")

    # İPTAL durumu: tahsil edilmiş ücreti müşteri bakiyesine iade et (idempotent)
    refunded = 0.0
    if durum == "iptal" and eski_durum != "iptal":
        odenen = float(r.get("odenen_ucret") or 0)
        if odenen > 0 and not r.get("iade_edildi"):
            try:
                plaka = (r.get("vehicle_snapshot") or {}).get("plaka", "")
                await wallet_add_transaction(
                    r["customer_id"],
                    odenen,
                    "iade",
                    f"Rezervasyon iptal iadesi - {plaka} ({rid[:8]})",
                    referans=f"REFUND-{rid}",
                )
                refunded = odenen
                # Bildirim
                await db.notifications.insert_one({
                    "id": str(uuid.uuid4()),
                    "baslik": "Rezervasyon İptal Edildi",
                    "mesaj": f"{plaka} aracı için rezervasyonunuz iptal edildi. {odenen:.2f}₺ bakiyenize iade edildi.",
                    "hedef_type": "secili",
                    "hedef_customer_ids": [r["customer_id"]],
                    "tarih": now_iso(), "okuyanlar": [],
                })
            except Exception as e:
                logger.warning(f"Refund failed for reservation {rid}: {e}")

    update_doc: dict = {"durum": durum}
    if durum == "iptal" and refunded > 0:
        update_doc["iade_edildi"] = True
        update_doc["iade_tutari"] = refunded
        update_doc["iade_tarihi"] = now_iso()
        update_doc["odenen_ucret"] = 0
        update_doc["odeme_durumu"] = "iade_edildi"

    # Muhasebe: İptal edilen rezervasyonun giden faturası silinir
    if durum == "iptal" and eski_durum != "iptal":
        try:
            await db.invoices.delete_many({"reservation_id": rid, "tip": "giden"})
        except Exception:
            pass

    await db.reservations.update_one({"id": rid}, {"$set": update_doc})
    # tamamlandi'ya geçildi mi? Otomatik giden fatura oluştur (idempotent — zaten varsa atlar) + müşteriye yorum bildirimi
    if durum == "tamamlandi" and eski_durum != "tamamlandi":
        try:
            updated_res = await db.reservations.find_one({"id": rid}, {"_id": 0})
            if updated_res:
                await _create_giden_fatura(updated_res)
        except Exception as e:
            logger.warning(f"Otomatik giden fatura oluşturulamadı (res={rid}): {e}")
        try:
            plaka = (r.get("vehicle_snapshot") or {}).get("plaka", "")
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "baslik": "⭐ Deneyiminizi Paylaşır mısınız?",
                "mesaj": f"{plaka} plakalı araç kiralamanız sona ermiştir. Deneyiminizi puanlayarak diğer müşterilere yardımcı olabilir misiniz? 'Bildirim' sayfasından yorum bırakabilirsiniz.",
                "hedef_type": "secili",
                "hedef_customer_ids": [r["customer_id"]],
                "tarih": now_iso(),
                "okuyanlar": [],
                "deep_link": f"/review/{rid}",
            })
        except Exception:
            pass
    return await db.reservations.find_one({"id": rid}, {"_id": 0})

# Admin: Tam rezervasyon düzenleme
class AdminReservationUpdate(BaseModel):
    baslangic_tarihi: Optional[str] = None
    bitis_tarihi: Optional[str] = None
    telefon: Optional[str] = None
    durum: Optional[str] = None
    odenen_ucret: Optional[float] = None
    toplam_tutar: Optional[float] = None
    kalan_odeme: Optional[float] = None
    paket_km: Optional[int] = None
    alis_km: Optional[int] = None
    notlar: Optional[str] = None
    odeme_durumu: Optional[str] = None
    # NEW: Admin manuel ek hizmet düzenlemesi — None ise dokunulmaz, [] gönderilirse tüm hizmetler kaldırılır
    secilen_hizmetler: Optional[List[ServiceSelection]] = None
    iskonto_yuzde: Optional[float] = None
    # auto_recalc_total=True: secilen_hizmetler değişince toplam_tutar otomatik hesaplanır
    # (kullanıcı toplam_tutar'ı da gönderirse o öncelikli olur)
    auto_recalc_total: Optional[bool] = True
    # 🆕 Otomatik yeniden hesaplama bayrakları — alanlar boş bırakıldıysa kademelere göre tekrar hesapla
    recalc_toplam_tutar: Optional[bool] = False
    recalc_paket_km: Optional[bool] = False

@api.put("/admin/reservations/{rid}")
async def admin_edit_reservation(rid: str, body: AdminReservationUpdate, _: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    # auto_recalc_total bayrağı upd'a girmesin, ayır
    auto_recalc = upd.pop("auto_recalc_total", True)
    recalc_toplam = bool(upd.pop("recalc_toplam_tutar", False))
    recalc_paket_km = bool(upd.pop("recalc_paket_km", False))
    if not upd and not recalc_toplam and not recalc_paket_km:
        raise HTTPException(400, "Güncellenecek alan yok")
    if "baslangic_tarihi" in upd and "bitis_tarihi" in upd:
        bs = parse_iso(upd["baslangic_tarihi"]); bt = parse_iso(upd["bitis_tarihi"])
        if bt <= bs:
            raise HTTPException(400, "Bitiş tarihi başlangıçtan sonra olmalı")
        upd["gun_sayisi"] = calc_days(bs, bt)
    elif "bitis_tarihi" in upd:
        # Sadece bitiş tarihi değişti — mevcut başlangıçla gün sayısını yeniden hesapla
        r = await db.reservations.find_one({"id": rid}, {"_id": 0, "baslangic_tarihi": 1})
        if r:
            try:
                bs = parse_iso(r["baslangic_tarihi"]); bt = parse_iso(upd["bitis_tarihi"])
                if bt > bs:
                    upd["gun_sayisi"] = calc_days(bs, bt)
            except Exception:
                pass
    elif "baslangic_tarihi" in upd:
        # Sadece başlangıç tarihi değişti
        r = await db.reservations.find_one({"id": rid}, {"_id": 0, "bitis_tarihi": 1})
        if r:
            try:
                bs = parse_iso(upd["baslangic_tarihi"]); bt = parse_iso(r["bitis_tarihi"])
                if bt > bs:
                    upd["gun_sayisi"] = calc_days(bs, bt)
            except Exception:
                pass

    # NEW: secilen_hizmetler değişti mi? — toplam_tutar'ı otomatik yeniden hesapla
    if "secilen_hizmetler" in upd and auto_recalc:
        try:
            cur_r = await db.reservations.find_one({"id": rid}, {"_id": 0}) or {}
            vid = cur_r.get("vehicle_id")
            vehicle = await db.vehicles.find_one({"id": vid}, {"_id": 0}) if vid else None
            if vehicle:
                # gün sayısı: yeni varsa onu, yoksa mevcut
                days = upd.get("gun_sayisi") or cur_r.get("gun_sayisi") or 1
                iskonto = float(upd.get("iskonto_yuzde", cur_r.get("iskonto_yuzde", 0)) or 0)
                # Zorunlu hizmetleri otomatik EKLEME — admin elle kaldırabilmeli
                pricing = await calc_pricing(vehicle, int(days), upd.get("secilen_hizmetler", []), iskonto, force_mandatory=False)
                # Kullanıcı toplam_tutar'ı explicit göndermediyse, hesaplanan toplamı kullan
                if "toplam_tutar" not in upd:
                    upd["toplam_tutar"] = pricing["toplam_tutar"]
                # 🔄 pricing alt-objesini de güncelle ki konsinye/raporlar doğru çalışsın
                upd["pricing"] = pricing
                # secilen_hizmetler'i pricing breakdown ile değil, orijinal sel formatı ile sakla
                # (gönderilen format: [{service_id, adet}])
        except Exception as e:
            logger.warning(f"admin_edit: hizmet recalc başarısız rid={rid}: {e}")

    # 🆕 OTOMATİK HESAPLAMA — kullanıcı alanı boş bırakıp recalc bayrağını gönderdiyse
    # kademelere ve mevcut konfigürasyona göre toplam tutar / paket km yeniden hesapla
    if recalc_toplam or recalc_paket_km:
        try:
            cur_r = await db.reservations.find_one({"id": rid}, {"_id": 0}) or {}
            vid = cur_r.get("vehicle_id")
            vehicle = await db.vehicles.find_one({"id": vid}, {"_id": 0}) if vid else None
            if vehicle:
                days = upd.get("gun_sayisi") or cur_r.get("gun_sayisi") or 1
                iskonto = float(upd.get("iskonto_yuzde", cur_r.get("iskonto_yuzde", 0)) or 0)
                # Mevcut hizmetler: payload'da gelmediyse rezervasyondaki hizmetlerden seçimleri çıkar
                sel = upd.get("secilen_hizmetler")
                if sel is None:
                    sel = []
                    for h in (cur_r.get("hizmetler") or []):
                        if h.get("service_id"):
                            sel.append({"service_id": h["service_id"], "adet": h.get("adet", 1)})
                pricing = await calc_pricing(vehicle, int(days), sel, iskonto, force_mandatory=False)
                if recalc_toplam:
                    upd["toplam_tutar"] = pricing["toplam_tutar"]
                # 🔄 pricing alt-objesini de güncelle ki konsinye/raporlar doğru çalışsın
                upd["pricing"] = pricing
                if recalc_paket_km:
                    # km_kademeleri × gün — manuel rezervasyon mantığıyla aynı
                    km_kademeleri = vehicle.get("km_kademeleri") or []
                    km_calc = 0
                    if km_kademeleri:
                        # Her gün için en yakın küçük kademeyi uygula (toplam km)
                        for d in range(1, int(days) + 1):
                            best = None
                            for kk in km_kademeleri:
                                gmin = int(kk.get("gun_min", 1))
                                if d >= gmin and (best is None or gmin > best.get("gun_min", 0)):
                                    best = kk
                            if best:
                                km_calc += int(best.get("km", vehicle.get("gunluk_km", 250)))
                    else:
                        km_calc = int(vehicle.get("gunluk_km", 250)) * int(days)
                    upd["paket_km"] = km_calc
        except Exception as e:
            logger.warning(f"admin_edit recalc bayrakları başarısız rid={rid}: {e}")

    # 🛠️ PRICING SENKRONİZASYON — gun_sayisi/baslangic/bitis değişmiş ama recalc bayrağı gönderilmemişse
    # bile pricing alt-objesini güncelle. Aksi takdirde konsinye hesabı yanlış çalışır.
    if "pricing" not in upd and ("gun_sayisi" in upd or "baslangic_tarihi" in upd or "bitis_tarihi" in upd):
        try:
            cur_r = await db.reservations.find_one({"id": rid}, {"_id": 0}) or {}
            vid = cur_r.get("vehicle_id")
            vehicle = await db.vehicles.find_one({"id": vid}, {"_id": 0}) if vid else None
            if vehicle:
                days = upd.get("gun_sayisi") or cur_r.get("gun_sayisi") or 1
                iskonto = float(upd.get("iskonto_yuzde", cur_r.get("iskonto_yuzde", 0)) or 0)
                sel = upd.get("secilen_hizmetler")
                if sel is None:
                    sel = []
                    for h in (cur_r.get("hizmetler") or []):
                        if h.get("service_id"):
                            sel.append({"service_id": h["service_id"], "adet": h.get("adet", 1)})
                pricing = await calc_pricing(vehicle, int(days), sel, iskonto, force_mandatory=False)
                upd["pricing"] = pricing
        except Exception as e:
            logger.warning(f"admin_edit pricing sync başarısız rid={rid}: {e}")


    # Ödeme alanları değiştiyse: kalan_odeme ve odeme_durumu yeniden hesapla
    if "odenen_ucret" in upd or "toplam_tutar" in upd:
        cur = await db.reservations.find_one({"id": rid}, {"_id": 0}) or {}
        toplam = float(upd.get("toplam_tutar", cur.get("toplam_tutar", 0)) or 0)
        odenen = float(upd.get("odenen_ucret", cur.get("odenen_ucret", 0)) or 0)
        on_odeme = float(cur.get("on_odeme_tutar", 0) or 0)
        # 🆕 TAM ÖDEME KORUMA — Müşteri rezervasyonu tam ödediyse (eski toplam == eski odenen)
        # ve admin yeni odenen explicit göndermediyse, odenen yeni toplam'a eşitlensin.
        # Bu sayede hizmet ekle/çıkar yaparken kalan yanlış hesaplanmaz.
        eski_toplam = float(cur.get("toplam_tutar", 0) or 0)
        eski_odenen = float(cur.get("odenen_ucret", 0) or 0)
        eski_tam_odemeli = (
            cur.get("odeme_durumu") == "tam_odeme_alindi"
            or (eski_toplam > 0 and abs(eski_odenen - eski_toplam) < 0.01)
        )
        if "odenen_ucret" not in upd and "toplam_tutar" in upd and eski_tam_odemeli:
            odenen = round(toplam, 2)
            upd["odenen_ucret"] = odenen
        # Eğer admin explicit kalan_odeme yollamadıysa otomatik hesapla
        if "kalan_odeme" not in upd:
            upd["kalan_odeme"] = round(max(0.0, toplam - odenen), 2)
        # odeme_durumu otomatik karar (admin explicit yollamadıysa)
        if "odeme_durumu" not in upd:
            if odenen >= toplam - 0.01:
                upd["odeme_durumu"] = "tam_odeme_alindi"
            elif on_odeme > 0 and odenen >= on_odeme:
                upd["odeme_durumu"] = "on_odeme_alindi"
            elif odenen > 0:
                upd["odeme_durumu"] = "on_odeme_alindi"
            else:
                upd["odeme_durumu"] = "beklemede"

    # 🛠️ NOTLAR — string olarak gelirse mevcut not-log array'ine APPEND et (overwrite ETME)
    if "notlar" in upd:
        try:
            note_val = upd.pop("notlar", None)
            if note_val and isinstance(note_val, str) and note_val.strip():
                cur_r2 = await db.reservations.find_one({"id": rid}, {"_id": 0, "notlar": 1}) or {}
                existing = cur_r2.get("notlar") or []
                if not isinstance(existing, list):
                    existing = []
                existing.append({
                    "tarih": now_iso(),
                    "yazan": "Admin",
                    "metin": note_val.strip(),
                })
                upd["notlar"] = existing
        except Exception as e:
            logger.warning(f"admin_edit notlar append başarısız rid={rid}: {e}")

    await db.reservations.update_one({"id": rid}, {"$set": upd})

    # Muhasebe: Tarih değiştiyse giden faturayı güncelle
    if "gun_sayisi" in upd or "baslangic_tarihi" in upd:
        try:
            yeni = await db.reservations.find_one({"id": rid}, {"_id": 0})
            if yeni:
                # Yeni mantık: _create_giden_fatura aya bölünmüş çoklu fatura'yı oluşturur/günceller
                await _create_giden_fatura(yeni)
        except Exception as e:
            logger.warning(f"admin_update: muhasebe fatura güncellenemedi rid={rid}: {e}")

    return await db.reservations.find_one({"id": rid}, {"_id": 0})

@api.delete("/admin/reservations/{rid}")
async def admin_delete_reservation(rid: str, refund: bool = True, _: dict = Depends(require_admin)):
    """Rezervasyonu komple sil. refund=True ise ödenen tutar müşteri bakiyesine iade edilir."""
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if refund:
        odenen = float(r.get("odenen_ucret") or 0)
        if odenen > 0 and not r.get("iade_edildi"):
            try:
                plaka = (r.get("vehicle_snapshot") or {}).get("plaka", "")
                await wallet_add_transaction(
                    r["customer_id"], odenen, "iade",
                    f"Rezervasyon silindi - bakiye iade ({plaka})",
                    referans=f"DELETE-REFUND-{rid}",
                )
                await db.notifications.insert_one({
                    "id": str(uuid.uuid4()),
                    "baslik": "Rezervasyon Silindi",
                    "mesaj": f"{plaka} aracı için rezervasyonunuz silindi. {odenen:.2f}₺ bakiyenize iade edildi.",
                    "hedef_type": "secili",
                    "hedef_customer_ids": [r["customer_id"]],
                    "tarih": now_iso(), "okuyanlar": [],
                })
            except Exception as e:
                logger.warning(f"Delete-refund failed: {e}")
    # Muhasebe: İlgili giden faturayı sil
    try:
        await db.invoices.delete_many({"reservation_id": rid, "tip": "giden"})
    except Exception:
        pass
    await db.reservations.delete_one({"id": rid})
    return {"ok": True, "refunded": refund}

# ==================== CUSTOMER: Ek KM Satın Alma (uzatma yapmadan) ====================
class BuyKmIn(BaseModel):
    ek_km: int

@api.post("/reservations/{rid}/buy-km-quote")
async def buy_km_quote(rid: str, body: BuyKmIn, user: dict = Depends(require_customer)):
    r = await db.reservations.find_one({"id": rid, "customer_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if r["durum"] not in ("onaylandi", "aktif"):
        raise HTTPException(400, "Sadece aktif/onaylı rezervasyonlar için ek km alınabilir")
    s = await get_settings()
    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0}) or {}
    days_now = int(r.get("gun_sayisi") or 0)
    km_asim_fiyat = km_asim_for(v, s, days=days_now)
    ek_km = max(0, int(body.ek_km or 0))
    brut = round(ek_km * km_asim_fiyat, 2)
    indirim = km_volume_indirim_for(v, s, ek_km)
    tutar = round(max(0.0, brut - indirim), 2)
    w = await get_wallet(user["id"])
    # Hesapla: kullanıcının varsayılan fiyatı (kademe yokken) — kademe indirimi göstermek için
    km_asim_baz = float(v.get("km_asim_fiyat") or s.get("km_asim_fiyat", 8.0) or 8.0)
    return {
        "ok": True,
        "ek_km": ek_km,
        "tutar": tutar,
        "brut_tutar": brut,
        "indirim_tutar": indirim,
        "km_asim_fiyat": km_asim_fiyat,
        "km_asim_baz": km_asim_baz,
        "km_asim_kademe": matched_km_asim_kademe(v, days_now),
        "km_asim_kademeleri": v.get("km_asim_kademeleri") or [],
        "gun_sayisi": days_now,
        "bakiye": w["bakiye"],
        "bakiye_yeterli": w["bakiye"] >= tutar,
        "eksik": max(0, tutar - w["bakiye"]),
        "mevcut_paket_km": r.get("paket_km", 0),
    }

@api.post("/reservations/{rid}/buy-km")
async def buy_km(rid: str, body: BuyKmIn, user: dict = Depends(require_customer)):
    r = await db.reservations.find_one({"id": rid, "customer_id": user["id"]}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if r["durum"] not in ("onaylandi", "aktif"):
        raise HTTPException(400, "Sadece aktif/onaylı rezervasyonlar için ek km alınabilir")
    ek_km = max(0, int(body.ek_km or 0))
    if ek_km <= 0:
        raise HTTPException(400, "Ek km miktarı 0'dan büyük olmalı")
    s = await get_settings()
    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0}) or {}
    km_asim_fiyat = km_asim_for(v, s, days=int(r.get("gun_sayisi") or 0))
    brut = round(ek_km * km_asim_fiyat, 2)
    indirim = km_volume_indirim_for(v, s, ek_km)
    tutar = round(max(0.0, brut - indirim), 2)

    w = await get_wallet(user["id"])
    if w["bakiye"] < tutar:
        raise HTTPException(402, f"Bakiye yetersiz. Mevcut: {w['bakiye']:.2f}₺ — Gerekli: {tutar:.2f}₺")

    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0, "plaka": 1})
    plaka = v["plaka"] if v else "?"

    aciklama = f"Ek km satın alma - {plaka} ({ek_km} km)"
    if indirim > 0:
        aciklama += f" — hacim indirimi: -{indirim:.2f}₺"
    await wallet_add_transaction(user["id"], tutar, "odeme", aciklama)

    new_paket_km = (r.get("paket_km", 0) or 0) + ek_km
    new_toplam = round((r.get("toplam_tutar", 0) or 0) + tutar, 2)
    new_odenen = round((r.get("odenen_ucret", 0) or 0) + tutar, 2)

    await db.reservations.update_one(
        {"id": rid},
        {"$set": {
            "paket_km": new_paket_km,
            "toplam_tutar": new_toplam,
            "odenen_ucret": new_odenen,
            "ek_km_satin": True,
            "ek_km_satin_tarihi": now_iso(),
        }}
    )

    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Ek KM Satın Alındı",
        "mesaj": f"{ek_km} km satın alındı. Yeni paket km: {new_paket_km}. Bakiyenizden {tutar:.2f}₺ tahsil edildi.",
        "hedef_type": "secili",
        "hedef_customer_ids": [user["id"]],
        "tarih": now_iso(),
        "okuyanlar": [],
    })

    return {
        "ok": True,
        "ek_km": ek_km,
        "tutar": tutar,
        "brut_tutar": brut,
        "indirim_tutar": indirim,
        "yeni_paket_km": new_paket_km,
    }

# Admin: Teslim Fotoğrafları (araç teslim ederken çekilen fotoğraflar)
class TeslimFotoIn(BaseModel):
    foto_base64: str  # data URI veya raw base64
    aciklama: Optional[str] = ""

@api.get("/admin/reservations/{rid}/teslim-foto")
async def admin_list_teslim_foto(rid: str, _: dict = Depends(require_admin)):
    r = await db.reservations.find_one({"id": rid}, {"_id": 0, "id": 1, "teslim_fotograflari": 1})
    if r is None:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    return r.get("teslim_fotograflari") or []

@api.post("/admin/reservations/{rid}/teslim-foto")
async def admin_add_teslim_foto(rid: str, body: TeslimFotoIn, admin: dict = Depends(require_admin)):
    r = await db.reservations.find_one({"id": rid}, {"_id": 0, "id": 1, "customer_id": 1, "vehicle_snapshot": 1})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    foto = (body.foto_base64 or "").strip()
    if not foto:
        raise HTTPException(400, "Fotoğraf boş olamaz")
    # data URI değilse data:image/jpeg;base64, ön ekini ekle
    if not foto.startswith("data:"):
        foto = f"data:image/jpeg;base64,{foto}"
    # Kabaca boyut kontrolü (~10MB base64 ≈ 7.5MB binary)
    if len(foto) > 10 * 1024 * 1024:
        raise HTTPException(400, "Fotoğraf çok büyük (max ~7MB)")
    item = {
        "id": str(uuid.uuid4()),
        "url": foto,
        "aciklama": (body.aciklama or "").strip(),
        "uploaded_at": now_iso(),
        "uploaded_by": admin.get("id") or "admin",
    }
    await db.reservations.update_one(
        {"id": rid},
        {"$push": {"teslim_fotograflari": item}}
    )
    return item

@api.delete("/admin/reservations/{rid}/teslim-foto/{fid}")
async def admin_delete_teslim_foto(rid: str, fid: str, _: dict = Depends(require_admin)):
    r = await db.reservations.find_one({"id": rid}, {"_id": 0, "id": 1})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    res = await db.reservations.update_one(
        {"id": rid},
        {"$pull": {"teslim_fotograflari": {"id": fid}}}
    )
    if res.modified_count == 0:
        raise HTTPException(404, "Fotoğraf bulunamadı")
    return {"ok": True}

@api.put("/admin/reservations/{rid}/odeme")
async def admin_set_payment_status(rid: str, odeme_durumu: str, _: dict = Depends(require_admin)):
    if odeme_durumu not in ("beklemede", "on_odeme_alindi", "tam_odeme_alindi"):
        raise HTTPException(400, "Geçersiz ödeme durumu")
    await db.reservations.update_one({"id": rid}, {"$set": {"odeme_durumu": odeme_durumu}})
    return await db.reservations.find_one({"id": rid}, {"_id": 0})

class KmOtoKilitIn(BaseModel):
    aktif: bool = True

@api.put("/admin/reservations/{rid}/km-oto-kilit")
async def admin_toggle_km_oto_kilit(rid: str, body: KmOtoKilitIn, _: dict = Depends(require_admin)):
    """Bu rezervasyon için KM bitince motor oto-kilit özelliğini aç/kapa.
    Müşteriye BİLDİRİM GÖNDERMEZ — sadece admin'in sessiz kontrolü."""
    aktif = bool(body.aktif)
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    updates = {"km_oto_kilit_aktif": aktif}
    # Eğer kilit kapatılıyor ve motor şu an kilitli ise, motoru aç (sessizce)
    plaka = (r.get("vehicle_snapshot") or {}).get("plaka") or ""
    if not aktif and r.get("motor_kilitli") and plaka:
        try:
            ok = await bot_motor_blokaj(plaka, False)
            if ok:
                updates["motor_kilitli"] = False
                updates["motor_acilis_tarih"] = now_iso()
                updates["motor_acilis_kaynak"] = "admin_oto_kilit_kapatildi"
                logger.info(f"admin: km_oto_kilit kapatıldı, motor açıldı {plaka}")
        except Exception as e:
            logger.warning(f"admin km_oto_kilit motor açma hata: {e}")
    await db.reservations.update_one({"id": rid}, {"$set": updates})
    return {"ok": True, "km_oto_kilit_aktif": aktif, "motor_kilitli": updates.get("motor_kilitli", r.get("motor_kilitli", False))}

@api.put("/admin/reservations/{rid}/km")
async def admin_set_km(rid: str, alis_km: Optional[int] = None, guncel_km: Optional[int] = None, _: dict = Depends(require_admin)):
    """Admin manually sets car KM (or bot updates this)."""
    upd = {}
    if alis_km is not None:
        upd["alis_km"] = alis_km
    if guncel_km is not None:
        upd["guncel_km"] = guncel_km
    if not upd:
        raise HTTPException(400, "alis_km veya guncel_km gerekli")
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if "alis_km" in upd or "guncel_km" in upd:
        new_alis = upd.get("alis_km", r.get("alis_km") or 0) or 0
        new_gun = upd.get("guncel_km", r.get("guncel_km") or 0) or 0
        kullanilan = max(0, new_gun - new_alis)
        upd["kullanilan_km"] = kullanilan
        if kullanilan > r["paket_km"]:
            asim = kullanilan - r["paket_km"]
            upd["km_asim"] = asim
            # Auto-deduct overage from wallet
            s = await get_settings()
            asim_fiyat = s.get("km_asim_fiyat", 8.0)
            ucret = round(asim * asim_fiyat, 2)
            mevcut_asim_dususleri = sum([
                t["tutar"] for t in await db.wallet_tx.find({"customer_id": r["customer_id"], "referans": f"KMASIM-{rid}"}).to_list(100)
            ])
            yeni_dusus = ucret - mevcut_asim_dususleri
            if yeni_dusus > 0:
                try:
                    await wallet_add_transaction(
                        r["customer_id"], yeni_dusus, "odeme",
                        f"KM aşım ücreti - {r['vehicle_snapshot']['plaka']} ({asim} km)",
                        referans=f"KMASIM-{rid}",
                    )
                    upd["km_asim_tutar"] = ucret
                    await db.notifications.insert_one({
                        "id": str(uuid.uuid4()),
                        "baslik": "KM Aşım Bildirimi",
                        "mesaj": f"Aracınızın paket KM'si aşıldı. {asim} km × {asim_fiyat:.2f}₺ = {ucret:.2f}₺ bakiyenizden düşüldü.",
                        "hedef_type": "secili",
                        "hedef_customer_ids": [r["customer_id"]],
                        "tarih": now_iso(),
                        "okuyanlar": [],
                    })
                except HTTPException as e:
                    await db.notifications.insert_one({
                        "id": str(uuid.uuid4()),
                        "baslik": "KM Aşımı — Bakiye Yetersiz",
                        "mesaj": f"Aracınızda {asim} km aşım tespit edildi ancak bakiyeniz yetersiz olduğu için tahsil edilemedi. Lütfen 'Bakiye' sayfasından bakiye yükleyiniz.",
                        "hedef_type": "secili",
                        "hedef_customer_ids": [r["customer_id"]],
                        "tarih": now_iso(),
                        "okuyanlar": [],
                    })
    await db.reservations.update_one({"id": rid}, {"$set": upd})
    return await db.reservations.find_one({"id": rid}, {"_id": 0})

# Manuel rezervasyon
@api.post("/admin/reservations/manual")
async def admin_create_manual_reservation(body: ManualReservationCreate, _: dict = Depends(require_admin)):
    cust = await db.customers.find_one({"id": body.customer_id}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Müşteri bulunamadı")
    v = await db.vehicles.find_one({"id": body.vehicle_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")

    bas = parse_iso(body.baslangic_tarihi)
    bit = parse_iso(body.bitis_tarihi)
    if bit <= bas:
        raise HTTPException(400, "Bitiş tarihi başlangıçtan sonra olmalı")

    # Araç çakışma kontrolü (admin manuel rezervasyon için) — beklemede/onaylandi/aktif olan diğer rezervasyonlarla
    bas_ext = (bas - timedelta(hours=1)).isoformat()
    bit_ext = (bit + timedelta(hours=1)).isoformat()
    conflict = await db.reservations.find_one({
        "vehicle_id": v["id"],
        "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
        "baslangic_tarihi": {"$lt": bit_ext},
        "bitis_tarihi": {"$gt": bas_ext},
    })
    if conflict:
        try:
            cb_bas = parse_iso(conflict["baslangic_tarihi"])
            cb_bit = parse_iso(conflict["bitis_tarihi"])
            cb_bas_local = (cb_bas + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
            cb_bit_local = (cb_bit + timedelta(hours=3)).strftime("%d.%m.%Y %H:%M")
        except Exception:
            cb_bas_local = conflict["baslangic_tarihi"]
            cb_bit_local = conflict["bitis_tarihi"]
        cust_name = ""
        try:
            cc = await db.customers.find_one({"id": conflict.get("customer_id")}, {"_id": 0})
            if cc:
                cust_name = f" — {cc.get('ad','')} {cc.get('soyad','')}"
        except Exception:
            pass
        raise HTTPException(
            409,
            f"Bu araç seçilen tarih aralığında dolu: {cb_bas_local} - {cb_bit_local}{cust_name}. Çakışmayan bir tarih aralığı seçin.",
        )

    days = calc_days(bas, bit)

    services = [s.dict() for s in body.secilen_hizmetler]
    pricing = await calc_pricing(v, days, services, iskonto_yuzde=body.iskonto_yuzde)

    # Override'lar: admin manuel girdi
    final_toplam = pricing["toplam_tutar"]
    final_paket_km = pricing["paket_km"]
    if body.toplam_tutar_override is not None and body.toplam_tutar_override >= 0:
        final_toplam = float(body.toplam_tutar_override)
    if body.paket_km_override is not None and body.paket_km_override >= 0:
        final_paket_km = int(body.paket_km_override)
    final_kalan = max(0.0, final_toplam - float(body.odenen_ucret or 0))

    # Ödeme durumu otomatik karar: eğer admin 'beklemede' seçtiyse ama ödenen > 0 ise düzelt
    final_odeme_durumu = body.odeme_durumu
    if body.odenen_ucret and body.odenen_ucret > 0:
        if body.odenen_ucret >= final_toplam:
            final_odeme_durumu = "tam_odeme_alindi"
        elif body.odenen_ucret >= pricing.get("on_odeme_tutar", 0):
            if final_odeme_durumu == "beklemede":
                final_odeme_durumu = "on_odeme_alindi"

    r = {
        "id": str(uuid.uuid4()),
        "customer_id": body.customer_id,
        "vehicle_id": v["id"],
        "vehicle_snapshot": {
            "plaka": v["plaka"], "marka": v["marka"], "model": v["model"],
            "foto_url": v.get("foto_url", ""), "renk": v.get("renk"),
        },
        "baslangic_tarihi": body.baslangic_tarihi,
        "bitis_tarihi": body.bitis_tarihi,
        "telefon": body.telefon,
        "secilen_hizmetler": pricing["hizmetler"],
        "pricing": pricing,
        "gun_sayisi": pricing["gun_sayisi"],
        "gunluk_fiyat": pricing["gunluk_fiyat"],
        "toplam_tutar": final_toplam,
        "on_odeme_tutar": pricing["on_odeme_tutar"],
        "kalan_odeme": final_kalan,
        "odenen_ucret": float(body.odenen_ucret or 0),
        "paket_km": final_paket_km,
        "kullanilan_km": 0,
        "alis_km": None, "guncel_km": None, "km_asim": 0,
        "sure_indirim_tutar": pricing.get("sure_indirim_tutar", 0),
        "durum": "onaylandi",
        "odeme_durumu": final_odeme_durumu,
        "odeme_yontemi": "havale",
        "uzatma_sayisi": 0,
        "son_uzatma_tarih": None,
        "olusturan": "admin",
        "iskonto_yuzde": body.iskonto_yuzde,
        "created_at": now_iso(),
    }

    # 📏 Ek KM Satışı — rezervasyon oluştururken peşinen sat
    if body.ek_km and body.ek_km > 0:
        try:
            s_obj = await get_settings()
            km_asim_fiyat = km_asim_for(v, s_obj, days=days)
            ek_brut = round(body.ek_km * km_asim_fiyat, 2)
            ek_indirim_auto = km_volume_indirim_for(v, s_obj, body.ek_km)
            ek_auto_tutar = round(max(0.0, ek_brut - ek_indirim_auto), 2)
            if body.ek_km_manuel_tutar is not None and body.ek_km_manuel_tutar >= 0:
                ek_tutar = round(float(body.ek_km_manuel_tutar), 2)
                ek_is_manuel = True
                ek_manuel_indirim = round(max(0.0, ek_brut - ek_tutar), 2)
            else:
                ek_tutar = ek_auto_tutar
                ek_is_manuel = False
                ek_manuel_indirim = 0.0
            # Rezervasyon tutarlarına dahil et
            r["ek_km_satin"] = int(body.ek_km)
            r["ek_km_tutar"] = ek_tutar
            r["toplam_tutar"] = round(r["toplam_tutar"] + ek_tutar, 2)
            if body.ek_km_odeme_alindi:
                r["odenen_ucret"] = round(float(r["odenen_ucret"]) + ek_tutar, 2)
            r["kalan_odeme"] = round(max(0.0, r["toplam_tutar"] - r["odenen_ucret"]), 2)
            # Ödeme durumu yeniden değerlendir
            if r["kalan_odeme"] <= 0.01:
                r["odeme_durumu"] = "tam_odeme_alindi"
            elif r["odenen_ucret"] > 0:
                r["odeme_durumu"] = "on_odeme_alindi"
            # Not log'u oluştur
            ek_note = f"Admin başlangıçta ek KM sattı: +{body.ek_km} km × {km_asim_fiyat}₺ = {ek_tutar}₺"
            if ek_is_manuel:
                ek_note += f" [Manuel fiyat — brüt {ek_brut}₺, indirim {ek_manuel_indirim}₺]"
            elif ek_indirim_auto > 0:
                ek_note += f" (hacim indirimi: -{ek_indirim_auto}₺)"
            ek_note += " | ✅ Peşin alındı" if body.ek_km_odeme_alindi else " | ⏳ Kalan ödemeye eklendi"
            r["notlar"] = [{"tarih": now_iso(), "yazan": "Admin", "metin": ek_note}]
        except Exception as e:
            logger.warning(f"Manuel rez ek_km başarısız: {e}")

    await db.reservations.insert_one(dict(r))

    # Otomatik Giden Fatura
    try:
        await _create_giden_fatura(r)
    except Exception:
        pass

    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Manuel Rezervasyon Oluşturuldu",
        "mesaj": f"Sizin için {v['marka']} {v['model']} ({v['plaka']}) - {days} gün rezervasyon oluşturuldu. Toplam: {pricing['toplam_tutar']:.2f}₺",
        "hedef_type": "secili",
        "hedef_customer_ids": [body.customer_id],
        "tarih": now_iso(), "okuyanlar": [],
    })
    return await db.reservations.find_one({"id": r["id"]}, {"_id": 0})

# Provizyon
@api.post("/admin/reservations/{rid}/provizyon")
async def admin_create_provision(rid: str, body: ProvisionCreate, _: dict = Depends(require_admin)):
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    try:
        result = await wallet_add_transaction(
            r["customer_id"], body.tutar, "provizyon_alma",
            f"Provizyon: {body.aciklama}",
            referans=f"PROV-{rid}",
        )
    except HTTPException as e:
        raise HTTPException(402, f"Müşteri bakiyesi yetersiz: {e.detail}")
    p = {
        "id": str(uuid.uuid4()),
        "reservation_id": rid,
        "customer_id": r["customer_id"],
        "tutar": body.tutar,
        "aciklama": body.aciklama,
        "durum": "alindi",  # alindi / iade_edildi
        "created_at": now_iso(),
    }
    await db.provisions.insert_one(dict(p))
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Provizyon Alındı",
        "mesaj": f"{body.tutar:.2f}₺ provizyon bakiyenizden alındı: {body.aciklama}",
        "hedef_type": "secili",
        "hedef_customer_ids": [r["customer_id"]],
        "tarih": now_iso(), "okuyanlar": [],
    })
    return await db.provisions.find_one({"id": p["id"]}, {"_id": 0})

@api.post("/admin/provisions/{pid}/iade")
async def admin_refund_provision(pid: str, _: dict = Depends(require_admin)):
    p = await db.provisions.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Provizyon bulunamadı")
    if p["durum"] != "alindi":
        raise HTTPException(400, "Bu provizyon zaten iade edildi")
    await wallet_add_transaction(
        p["customer_id"], p["tutar"], "provizyon_iade",
        f"Provizyon iadesi: {p['aciklama']}",
        referans=f"PROVIADE-{pid}",
    )
    await db.provisions.update_one({"id": pid}, {"$set": {"durum": "iade_edildi", "iade_tarihi": now_iso()}})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Provizyon İadesi Yapıldı",
        "mesaj": f"Rezervasyonunuzun provizyon tutarı olan {p['tutar']:.2f}₺ bakiyenize iade edilmiştir.",
        "hedef_type": "secili",
        "hedef_customer_ids": [p["customer_id"]],
        "tarih": now_iso(), "okuyanlar": [],
    })
    return await db.provisions.find_one({"id": pid}, {"_id": 0})

@api.get("/admin/reservations/{rid}/provisions")
async def admin_list_provisions(rid: str, _: dict = Depends(require_admin)):
    return await db.provisions.find({"reservation_id": rid}, {"_id": 0}).sort("created_at", -1).to_list(100)

# ==================== ADMIN: EK KM SATIŞI ====================
class EkKmSatisIn(BaseModel):
    ek_km: int = Field(..., gt=0, description="Eklenecek KM miktarı")
    odeme_alindi: bool = True  # True: peşin alındı; False: kalan ödemeye eklensin
    not_aciklama: Optional[str] = None
    manuel_tutar: Optional[float] = Field(default=None, ge=0, description="Manuel fiyat override (boş ise otomatik hesap)")

@api.get("/admin/reservations/{rid}/ek-km-quote")
async def admin_ek_km_quote(rid: str, ek_km: int = 0, manuel_tutar: Optional[float] = None, _: dict = Depends(require_admin)):
    """Admin için ek KM fiyat önizlemesi — modalda kullanılır. manuel_tutar verilirse override."""
    if ek_km <= 0:
        raise HTTPException(400, "Geçerli bir KM miktarı girin")
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    s = await get_settings()
    total_days = int(r.get("gun_sayisi") or r.get("toplam_gun") or 1)
    km_asim_fiyat = km_asim_for(v, s, days=total_days)
    brut = round(ek_km * km_asim_fiyat, 2)
    indirim_auto = km_volume_indirim_for(v, s, ek_km)
    auto_tutar = round(max(0.0, brut - indirim_auto), 2)
    # Manuel override varsa onu kullan
    if manuel_tutar is not None and manuel_tutar >= 0:
        tutar = round(float(manuel_tutar), 2)
        manuel_indirim = round(max(0.0, brut - tutar), 2)
        indirim_label = "manuel"
    else:
        tutar = auto_tutar
        manuel_indirim = 0.0
        indirim_label = "auto" if indirim_auto > 0 else "yok"
    return {
        "ek_km": ek_km,
        "km_asim_fiyat": km_asim_fiyat,
        "brut": brut,
        "indirim": indirim_auto,
        "manuel_indirim": manuel_indirim,
        "indirim_tipi": indirim_label,
        "auto_tutar": auto_tutar,
        "tutar": tutar,
        "mevcut_paket_km": int(r.get("paket_km", 0) or 0) + int(r.get("ek_km_satin", 0) or 0),
        "kullanilan_km": int(r.get("kullanilan_km", 0) or 0),
        "yeni_paket_km": int(r.get("paket_km", 0) or 0) + int(r.get("ek_km_satin", 0) or 0) + ek_km,
    }

@api.post("/admin/reservations/{rid}/ek-km")
async def admin_ek_km_sat(rid: str, body: EkKmSatisIn, current: dict = Depends(require_admin)):
    """Mevcut rezervasyona ek KM paketi sat — admin telefonla talep eden müşteri için."""
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if r.get("durum") in ("iptal_edildi",):
        raise HTTPException(400, "İptal edilmiş rezervasyona ek KM satılamaz")
    v = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    s = await get_settings()
    total_days = int(r.get("gun_sayisi") or r.get("toplam_gun") or 1)
    km_asim_fiyat = km_asim_for(v, s, days=total_days)
    brut = round(body.ek_km * km_asim_fiyat, 2)
    indirim_auto = km_volume_indirim_for(v, s, body.ek_km)
    auto_tutar = round(max(0.0, brut - indirim_auto), 2)
    # Manuel override varsa onu kullan
    if body.manuel_tutar is not None and body.manuel_tutar >= 0:
        tutar = round(float(body.manuel_tutar), 2)
        manuel_indirim = round(max(0.0, brut - tutar), 2)
        is_manuel = True
    else:
        tutar = auto_tutar
        manuel_indirim = 0.0
        is_manuel = False
    # Mevcut değerleri al
    mevcut_ek_km = int(r.get("ek_km_satin", 0) or 0)
    mevcut_ek_km_tutar = float(r.get("ek_km_tutar", 0) or 0)
    mevcut_toplam = float(r.get("toplam_tutar", 0) or 0)
    mevcut_odenen = float(r.get("odenen_ucret", 0) or 0)
    # Yeni değerler
    yeni_ek_km = mevcut_ek_km + body.ek_km
    yeni_ek_km_tutar = round(mevcut_ek_km_tutar + tutar, 2)
    yeni_toplam = round(mevcut_toplam + tutar, 2)
    yeni_odenen = round(mevcut_odenen + tutar, 2) if body.odeme_alindi else mevcut_odenen
    yeni_kalan = round(max(0.0, yeni_toplam - yeni_odenen), 2)
    # Ödeme durumu
    if yeni_kalan <= 0.01:
        yeni_odeme_durumu = "tam_odeme_alindi"
    elif yeni_odenen > 0:
        yeni_odeme_durumu = "on_odeme_alindi"
    else:
        yeni_odeme_durumu = r.get("odeme_durumu", "beklemede")
    # Update
    upd = {
        "ek_km_satin": yeni_ek_km,
        "ek_km_tutar": yeni_ek_km_tutar,
        "toplam_tutar": yeni_toplam,
        "odenen_ucret": yeni_odenen,
        "kalan_odeme": yeni_kalan,
        "odeme_durumu": yeni_odeme_durumu,
    }
    # Log/notlar
    note_msg = f"Admin ek KM sattı: +{body.ek_km} km × {km_asim_fiyat}₺ = {tutar}₺"
    if is_manuel:
        note_msg += f" [Manuel fiyat — brüt {brut}₺, indirim {manuel_indirim}₺]"
    elif indirim_auto > 0:
        note_msg += f" (hacim indirimi: -{indirim_auto}₺)"
    if body.odeme_alindi:
        note_msg += " | ✅ Peşin alındı"
    else:
        note_msg += " | ⏳ Kalan ödemeye eklendi"
    if body.not_aciklama:
        note_msg += f" • Not: {body.not_aciklama}"
    notlar = list(r.get("notlar") or [])
    notlar.append({
        "tarih": now_iso(),
        "yazan": f"Admin: {current.get('ad', '')} {current.get('soyad', '')}".strip() or "Admin",
        "metin": note_msg,
    })
    upd["notlar"] = notlar
    await db.reservations.update_one({"id": rid}, {"$set": upd})
    # Bildirim (müşteriye)
    try:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "baslik": "Ek KM Paketi Eklendi",
            "mesaj": f"Rezervasyonunuza +{body.ek_km} km paketi eklendi. Tutar: {tutar:.2f}₺",
            "hedef_type": "secili",
            "hedef_customer_ids": [r.get("customer_id")] if r.get("customer_id") else [],
            "tarih": now_iso(), "okuyanlar": [],
        })
    except Exception:
        pass
    return await db.reservations.find_one({"id": rid}, {"_id": 0})

# ==================== ADMIN: EK KM İADE ====================
class EkKmIadeIn(BaseModel):
    iade_km: int = Field(..., gt=0, description="İade edilecek (kullanılmayan) KM miktarı")
    odeme_iade_edildi: bool = True  # True: müşteriye nakit/havale iade edildi (odenen_ucret düşer); False: kalan'dan düşer
    not_aciklama: Optional[str] = None

@api.get("/admin/reservations/{rid}/ek-km-iade-quote")
async def admin_ek_km_iade_quote(rid: str, iade_km: int = 0, _: dict = Depends(require_admin)):
    """Pro-rata iade önizlemesi — modalda kullanılır."""
    if iade_km <= 0:
        raise HTTPException(400, "Geçerli bir KM miktarı girin")
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    mevcut_ek_km = int(r.get("ek_km_satin", 0) or 0)
    mevcut_ek_km_tutar = float(r.get("ek_km_tutar", 0) or 0)
    if mevcut_ek_km <= 0:
        raise HTTPException(400, "Bu rezervasyonda satılmış ek KM bulunmuyor")
    if iade_km > mevcut_ek_km:
        raise HTTPException(400, f"İade KM ({iade_km}) satılan ek KM'den ({mevcut_ek_km}) fazla olamaz")
    birim_fiyat = round(mevcut_ek_km_tutar / mevcut_ek_km, 4) if mevcut_ek_km > 0 else 0.0
    iade_tutar = round(birim_fiyat * iade_km, 2)
    return {
        "iade_km": iade_km,
        "satilan_ek_km": mevcut_ek_km,
        "satilan_ek_km_tutar": mevcut_ek_km_tutar,
        "birim_fiyat": round(birim_fiyat, 2),
        "iade_tutar": iade_tutar,
        "kalan_ek_km": mevcut_ek_km - iade_km,
        "kalan_ek_km_tutar": round(mevcut_ek_km_tutar - iade_tutar, 2),
        "kullanilan_km": int(r.get("kullanilan_km", 0) or 0),
        "paket_km": int(r.get("paket_km", 0) or 0),
    }

@api.post("/admin/reservations/{rid}/ek-km-iade")
async def admin_ek_km_iade(rid: str, body: EkKmIadeIn, current: dict = Depends(require_admin)):
    """Satılmış ek KM paketinden kullanılmayan kısmı pro-rata iade eder."""
    r = await db.reservations.find_one({"id": rid}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    mevcut_ek_km = int(r.get("ek_km_satin", 0) or 0)
    mevcut_ek_km_tutar = float(r.get("ek_km_tutar", 0) or 0)
    mevcut_toplam = float(r.get("toplam_tutar", 0) or 0)
    mevcut_odenen = float(r.get("odenen_ucret", 0) or 0)
    if mevcut_ek_km <= 0:
        raise HTTPException(400, "Bu rezervasyonda satılmış ek KM bulunmuyor")
    if body.iade_km > mevcut_ek_km:
        raise HTTPException(400, f"İade KM ({body.iade_km}) satılan ek KM'den ({mevcut_ek_km}) fazla olamaz")
    # Pro-rata hesap
    birim_fiyat = round(mevcut_ek_km_tutar / mevcut_ek_km, 4) if mevcut_ek_km > 0 else 0.0
    iade_tutar = round(birim_fiyat * body.iade_km, 2)
    # Yeni değerler
    yeni_ek_km = mevcut_ek_km - body.iade_km
    yeni_ek_km_tutar = round(max(0.0, mevcut_ek_km_tutar - iade_tutar), 2)
    yeni_toplam = round(max(0.0, mevcut_toplam - iade_tutar), 2)
    if body.odeme_iade_edildi:
        # Müşteriye fiziksel iade edildi → ödenen tutar düşer
        yeni_odenen = round(max(0.0, mevcut_odenen - iade_tutar), 2)
    else:
        # Sadece kalan ödemeden düşülsün → odenen aynı kalır, toplam düştüğü için kalan otomatik azalır
        yeni_odenen = mevcut_odenen
    yeni_kalan = round(max(0.0, yeni_toplam - yeni_odenen), 2)
    # Ödeme durumu
    if yeni_toplam <= 0.01:
        yeni_odeme_durumu = "tam_odeme_alindi"
    elif yeni_kalan <= 0.01:
        yeni_odeme_durumu = "tam_odeme_alindi"
    elif yeni_odenen > 0:
        yeni_odeme_durumu = "on_odeme_alindi"
    else:
        yeni_odeme_durumu = r.get("odeme_durumu", "beklemede")
    upd = {
        "ek_km_satin": yeni_ek_km,
        "ek_km_tutar": yeni_ek_km_tutar,
        "toplam_tutar": yeni_toplam,
        "odenen_ucret": yeni_odenen,
        "kalan_odeme": yeni_kalan,
        "odeme_durumu": yeni_odeme_durumu,
    }
    # Log/notlar
    note_msg = f"Admin ek KM iadesi: -{body.iade_km} km × {round(birim_fiyat, 2)}₺ = {iade_tutar}₺"
    if body.odeme_iade_edildi:
        note_msg += " | 💸 Müşteriye iade edildi"
    else:
        note_msg += " | 🧾 Kalan ödemeden düşüldü"
    if body.not_aciklama:
        note_msg += f" • Not: {body.not_aciklama}"
    notlar = list(r.get("notlar") or [])
    notlar.append({
        "tarih": now_iso(),
        "yazan": f"Admin: {current.get('ad', '')} {current.get('soyad', '')}".strip() or "Admin",
        "metin": note_msg,
    })
    upd["notlar"] = notlar
    await db.reservations.update_one({"id": rid}, {"$set": upd})
    # Bildirim (müşteriye)
    try:
        await db.notifications.insert_one({
            "id": str(uuid.uuid4()),
            "baslik": "Ek KM İadesi Yapıldı",
            "mesaj": f"Rezervasyonunuzdan {body.iade_km} km iade edilmiştir. {iade_tutar:.2f}₺ tutar bakiyenize aktarılmıştır.",
            "hedef_type": "secili",
            "hedef_customer_ids": [r.get("customer_id")] if r.get("customer_id") else [],
            "tarih": now_iso(), "okuyanlar": [],
        })
    except Exception:
        pass
    return await db.reservations.find_one({"id": rid}, {"_id": 0})

# Approve havale topup
@api.post("/admin/wallet-tx/{tx_id}/approve")
async def admin_approve_topup(tx_id: str, _: dict = Depends(require_admin)):
    tx = await db.wallet_tx.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "İşlem bulunamadı")
    if tx.get("tip") != "yukleme_beklemede":
        raise HTTPException(400, "Bu işlem onay bekleyen havale değil")
    if tx.get("durum") == "tamamlandi":
        raise HTTPException(400, "Zaten onaylanmış")
    result = await wallet_add_transaction(tx["customer_id"], tx["tutar"], "yukleme", f"Havale onaylandı: {tx.get('aciklama', '')}", referans=tx.get("referans"))
    await db.wallet_tx.update_one({"id": tx_id}, {"$set": {"durum": "tamamlandi"}})
    # Auto-settle: açık rezervasyonların kalan ödemelerinden düş
    settlement = await auto_settle_pending_payments(tx["customer_id"])
    if settlement.get("applied_total", 0) > 0:
        bildirim_msg = f"{tx['tutar']:.2f}₺ havale yüklemeniz onaylandı, bakiyenize işlendi. Bu bakiyeden {settlement['applied_total']:.2f}₺ açık rezervasyonlarınızın ödemesine otomatik aktarıldı."
    else:
        bildirim_msg = f"{tx['tutar']:.2f}₺ havale yüklemeniz onaylandı, bakiyenize işlendi."
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Havale Onaylandı",
        "mesaj": bildirim_msg,
        "hedef_type": "secili",
        "hedef_customer_ids": [tx["customer_id"]],
        "tarih": now_iso(), "okuyanlar": [],
    })
    result["auto_settlement"] = settlement
    return result

@api.post("/admin/wallet-tx/{tx_id}/reject")
async def admin_reject_topup(tx_id: str, _: dict = Depends(require_admin)):
    tx = await db.wallet_tx.find_one({"id": tx_id}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "İşlem bulunamadı")
    if tx.get("tip") != "yukleme_beklemede":
        raise HTTPException(400, "Bu işlem onay bekleyen havale değil")
    await db.wallet_tx.update_one({"id": tx_id}, {"$set": {"durum": "reddedildi"}})
    await db.notifications.insert_one({
        "id": str(uuid.uuid4()),
        "baslik": "Havale Reddedildi",
        "mesaj": f"{tx['tutar']:.2f}₺ havale yükleme talebiniz onaylanmadı. Yetkili ile iletişime geçin.",
        "hedef_type": "secili",
        "hedef_customer_ids": [tx["customer_id"]],
        "tarih": now_iso(), "okuyanlar": [],
    })
    return {"ok": True}

@api.get("/admin/wallet-tx/pending")
async def admin_pending_topups(_: dict = Depends(require_admin)):
    docs = await db.wallet_tx.find({"tip": "yukleme_beklemede", "durum": "beklemede"}, {"_id": 0}).sort("tarih", -1).to_list(100)
    for d in docs:
        c = await db.customers.find_one({"id": d["customer_id"]}, {"_id": 0, "ad": 1, "soyad": 1})
        if c:
            d["musteri_adi"] = f"{c['ad']} {c['soyad']}"
    return docs

# ==================== ADMIN: Services ====================
@api.get("/admin/services")
async def admin_list_services(_: dict = Depends(require_admin)):
    return await db.services.find({}, {"_id": 0}).sort("siralama", 1).to_list(50)

@api.post("/admin/services")
async def admin_create_service(body: ServiceCreate, _: dict = Depends(require_admin)):
    if body.tip not in ("gunluk", "tek_seferlik"):
        raise HTTPException(400, "Tip 'gunluk' veya 'tek_seferlik' olmalı")
    s = {"id": str(uuid.uuid4()), **body.dict()}
    await db.services.insert_one(dict(s))
    return await db.services.find_one({"id": s["id"]}, {"_id": 0})

@api.put("/admin/services/{sid}")
async def admin_update_service(sid: str, body: ServiceUpdate, _: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd:
        await db.services.update_one({"id": sid}, {"$set": upd})
    return await db.services.find_one({"id": sid}, {"_id": 0})

@api.delete("/admin/services/{sid}")
async def admin_delete_service(sid: str, _: dict = Depends(require_admin)):
    await db.services.delete_one({"id": sid})
    return {"ok": True}

# ==================== ADMIN: Holidays ====================
@api.get("/admin/holidays")
async def admin_list_holidays(_: dict = Depends(require_admin)):
    return await db.holidays.find({}, {"_id": 0}).sort("tarih", 1).to_list(500)

@api.post("/admin/holidays")
async def admin_add_holiday(body: HolidayCreate, _: dict = Depends(require_admin)):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih):
        raise HTTPException(400, "Tarih YYYY-MM-DD formatında olmalı")
    if await db.holidays.find_one({"tarih": body.tarih}):
        raise HTTPException(400, "Bu tarih zaten tatil olarak ekli")
    h = {"id": str(uuid.uuid4()), "tarih": body.tarih, "aciklama": body.aciklama}
    await db.holidays.insert_one(dict(h))
    return await db.holidays.find_one({"id": h["id"]}, {"_id": 0})

@api.delete("/admin/holidays/{hid}")
async def admin_delete_holiday(hid: str, _: dict = Depends(require_admin)):
    await db.holidays.delete_one({"id": hid})
    return {"ok": True}

# ==================== ADMIN: Notifications ====================
@api.get("/admin/notifications/summary")
async def admin_notifications_summary(_: dict = Depends(require_admin)):
    """Eylem bekleyen olayların özeti (canlı badge için).
    Bekleyen rezervasyonlar + cüzdan talepleri + son 24sa hız ihlali + KM uyarıları
    """
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    items: list = []
    total = 0

    # Bekleyen rezervasyonlar
    pending_rez = await db.reservations.count_documents({"durum": "beklemede"})
    if pending_rez > 0:
        total += pending_rez
        items.append({
            "key": "pending_reservations",
            "icon": "calendar",
            "color": "warning",
            "title": f"{pending_rez} bekleyen rezervasyon",
            "subtitle": "Onay bekliyor",
            "tab": "reservations",
            "count": pending_rez,
        })

    # Bekleyen cüzdan yükleme talepleri
    pending_top = await db.topup_requests.count_documents({"durum": "beklemede"})
    if pending_top > 0:
        total += pending_top
        items.append({
            "key": "pending_topups",
            "icon": "wallet",
            "color": "success",
            "title": f"{pending_top} cüzdan yükleme talebi",
            "subtitle": "İnceleme bekliyor",
            "tab": "topups",
            "count": pending_top,
        })

    # Son 24 saatteki hız ihlalleri
    since = (_dt.now(_tz.utc) - _td(hours=24)).isoformat()
    speed_24h = await db.speed_violations.count_documents({"tarih": {"$gte": since}})
    if speed_24h > 0:
        # Detay: hangi araç
        recent = await db.speed_violations.find(
            {"tarih": {"$gte": since}}, {"_id": 0, "plaka": 1, "hiz": 1, "limit": 1},
        ).sort("tarih", -1).limit(1).to_list(length=1)
        det = ""
        if recent:
            det = f"{recent[0].get('plaka')} {recent[0].get('hiz', '?')}km/h"
        total += speed_24h
        items.append({
            "key": "speed_violations",
            "icon": "speedometer",
            "color": "error",
            "title": f"{speed_24h} hız ihlali (24sa)",
            "subtitle": det or "—",
            "tab": "vehicles",
            "count": speed_24h,
        })

    # KM uyarısı tetiklenen aktif rezervasyonlar
    km_warn = await db.reservations.count_documents({
        "durum": "aktif",
        "km_warning_50_sent": True,
    })
    if km_warn > 0:
        total += km_warn
        items.append({
            "key": "km_warnings",
            "icon": "alert",
            "color": "warning",
            "title": f"{km_warn} KM uyarısı",
            "subtitle": "50 KM altında kalan aktif kira",
            "tab": "reservations",
            "count": km_warn,
        })

    # Motor blokesi olan araçlar
    blocked = await db.reservations.count_documents({
        "durum": "aktif",
        "motor_kilitli": True,
    })
    if blocked > 0:
        total += blocked
        items.append({
            "key": "engine_blocked",
            "icon": "lock-closed",
            "color": "error",
            "title": f"{blocked} motor blokeli araç",
            "subtitle": "Aktif kira ile",
            "tab": "vehicles",
            "count": blocked,
        })

    # Son 24 saatteki Ek KM satın alımları (müşteri tarafından)
    since_24h = (_dt.now(_tz.utc) - _td(hours=24)).isoformat()
    ek_km_24h = await db.reservations.count_documents({
        "ek_km_satin": True,
        "ek_km_satin_tarihi": {"$gte": since_24h},
    })
    if ek_km_24h > 0:
        total += ek_km_24h
        items.append({
            "key": "recent_ek_km",
            "icon": "speedometer",
            "color": "info",
            "title": f"{ek_km_24h} Ek KM satın alımı (24sa)",
            "subtitle": "Müşteri ek KM aldı",
            "tab": "reservations",
            "count": ek_km_24h,
        })

    # Son 24 saatteki süre uzatmaları (müşteri tarafından)
    ext_24h = await db.reservations.count_documents({
        "uzatma_yapildi": True,
        "uzatma_tarihi": {"$gte": since_24h},
    })
    if ext_24h > 0:
        total += ext_24h
        items.append({
            "key": "recent_extensions",
            "icon": "time",
            "color": "info",
            "title": f"{ext_24h} süre uzatması (24sa)",
            "subtitle": "Müşteri rezervasyonu uzattı",
            "tab": "reservations",
            "count": ext_24h,
        })

    return {"total": total, "items": items}


# ==================== ADMIN: Yeni Olay Sayısı (badge için, son görüntülemeden bu yana) ====================
@api.get("/admin/notifications/fresh-count")
async def admin_notifications_fresh_count(user: dict = Depends(require_admin)):
    """
    Admin'in son 'mark-seen' işleminden bu yana gerçekleşen müşteri olaylarını sayar.
    Hiç mark-seen yapılmadıysa user.created_at kullanılır.
    Sayılan olaylar:
      - Yeni rezervasyonlar (beklemede)
      - Yeni cüzdan yükleme talepleri (beklemede)
      - Ek KM satın alımları
      - Süre uzatmaları
    """
    fresh_user = await db.users.find_one({"id": user["id"]}, {"_id": 0, "admin_notif_seen_at": 1, "created_at": 1})
    seen_at = (fresh_user or {}).get("admin_notif_seen_at") or (fresh_user or {}).get("created_at") or "2020-01-01T00:00:00"

    total = 0
    # Yeni rezervasyonlar
    new_rez = await db.reservations.count_documents({"durum": "beklemede", "olusturma_tarihi": {"$gte": seen_at}})
    total += new_rez
    # Yeni cüzdan yükleme talepleri
    new_topup = await db.wallet_transactions.count_documents({"durum": "beklemede", "tip": "yukleme", "tarih": {"$gte": seen_at}})
    total += new_topup
    # Ek KM satın alımları
    new_ek_km = await db.reservations.count_documents({"ek_km_satin_tarihi": {"$gte": seen_at}})
    total += new_ek_km
    # Süre uzatmaları
    new_ext = await db.reservations.count_documents({"uzatma_tarihi": {"$gte": seen_at}})
    total += new_ext
    return {"count": total, "seen_at": seen_at}


@api.post("/admin/notifications/mark-seen")
async def admin_notifications_mark_seen(user: dict = Depends(require_admin)):
    """Admin Bildirim sekmesini açtığında çağrılır — yeni olay sayısını 0'a sıfırlar."""
    await db.users.update_one({"id": user["id"]}, {"$set": {"admin_notif_seen_at": now_iso()}})
    return {"ok": True, "seen_at": now_iso()}


@api.post("/admin/notifications")
async def admin_send_notification(body: NotificationCreate, admin: dict = Depends(require_admin)):
    if body.hedef_type not in ("tum", "secili"):
        raise HTTPException(400, "hedef_type 'tum' veya 'secili' olmalı")
    n = {
        "id": str(uuid.uuid4()),
        "baslik": body.baslik.strip(), "mesaj": body.mesaj.strip(),
        "hedef_type": body.hedef_type,
        "hedef_customer_ids": body.hedef_customer_ids or [],
        "tarih": now_iso(), "okuyanlar": [],
        "gonderen": admin["ad"],
    }
    await db.notifications.insert_one(dict(n))
    return await db.notifications.find_one({"id": n["id"]}, {"_id": 0})

@api.get("/admin/notifications")
async def admin_list_notifications(_: dict = Depends(require_admin)):
    docs = await db.notifications.find({"hedef_type": {"$in": ["tum", "secili", "admin"]}}, {"_id": 0}).sort("tarih", -1).to_list(500)
    return docs

@api.delete("/admin/notifications/{nid}")
async def admin_delete_notification(nid: str, _: dict = Depends(require_admin)):
    await db.notifications.delete_one({"id": nid})
    return {"ok": True}

# ==================== ADMIN: Settings ====================
@api.get("/admin/settings")
async def admin_get_settings(_: dict = Depends(require_admin)):
    return await db.settings.find_one({"key": "company"}, {"_id": 0}) or {}

@api.put("/admin/settings")
async def admin_update_settings(body: SettingsUpdate, _: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if upd:
        await db.settings.update_one({"key": "company"}, {"$set": upd}, upsert=True)
    return await db.settings.find_one({"key": "company"}, {"_id": 0})

# ==================== ADMIN: Dashboard ====================
@api.get("/admin/dashboard")
async def admin_dashboard(_: dict = Depends(require_admin)):
    return {
        "musteri_sayisi": await db.customers.count_documents({}),
        "engelli_musteri": await db.customers.count_documents({"blocked": True}),
        "arac_sayisi": await db.vehicles.count_documents({}),
        "aktif_rezervasyon": await db.reservations.count_documents({"durum": {"$in": ["onaylandi", "aktif"]}}),
        "bekleyen_rezervasyon": await db.reservations.count_documents({"durum": "beklemede"}),
        "tamamlanan_rezervasyon": await db.reservations.count_documents({"durum": "tamamlandi"}),
        "bekleyen_havale": await db.wallet_tx.count_documents({"tip": "yukleme_beklemede", "durum": "beklemede"}),
        "bekleyen_yorum": await db.reviews.count_documents({"durum": "beklemede"}),
        "bot_online": (await fetch_bot_vehicles()) is not None,
    }


# ========================================================================
# REVIEWS / YORUMLAR — Müşteri Puan ve Yorum Sistemi
# ========================================================================

def _mask_customer_name(ad: str, soyad: str) -> str:
    """Anonimliği koru — Ad + Soyad'ın ilk harfi (örn 'Ahmet Y.')."""
    ad_clean = (ad or '').strip()
    soyad_clean = (soyad or '').strip()
    soyad_first = (soyad_clean[:1] + '.') if soyad_clean else ''
    return f"{ad_clean} {soyad_first}".strip() or 'Müşteri'

@api.post("/reviews")
async def create_review(body: ReviewCreate, user: dict = Depends(require_customer)):
    # 1) Rezervasyon var ve müşteriye ait mi?
    r = await db.reservations.find_one({"id": body.reservation_id, "customer_id": user["id"]})
    if not r:
        raise HTTPException(404, "Rezervasyon bulunamadı")
    if r.get("durum") != "tamamlandi":
        raise HTTPException(400, "Sadece tamamlanmış kiralamalar için yorum bırakabilirsiniz")
    # 2) Bu rezervasyon için zaten yorum var mı?
    if await db.reviews.find_one({"reservation_id": body.reservation_id}):
        raise HTTPException(400, "Bu kiralama için zaten yorum bıraktınız")
    # 3) Puan validasyonu
    if not (1 <= body.arac_puan <= 5) or not (1 <= body.servis_puan <= 5):
        raise HTTPException(400, "Puanlar 1-5 arasında olmalı")
    cust = await db.customers.find_one({"id": user["id"]}, {"_id": 0})
    vehicle = await db.vehicles.find_one({"id": r["vehicle_id"]}, {"_id": 0, "marka": 1, "model": 1, "plaka": 1, "foto_url": 1, "id": 1}) or {}
    rid = str(uuid.uuid4())
    doc = {
        "id": rid,
        "customer_id": user["id"],
        "customer_display": _mask_customer_name(cust.get("ad", ""), cust.get("soyad", "")),
        "vehicle_id": r["vehicle_id"],
        "vehicle_snapshot": {
            "marka": vehicle.get("marka", r.get("vehicle_snapshot", {}).get("marka", "")),
            "model": vehicle.get("model", r.get("vehicle_snapshot", {}).get("model", "")),
            "plaka": vehicle.get("plaka", r.get("vehicle_snapshot", {}).get("plaka", "")),
            "foto_url": vehicle.get("foto_url", r.get("vehicle_snapshot", {}).get("foto_url", "")),
        },
        "reservation_id": body.reservation_id,
        "arac_puan": int(body.arac_puan),
        "servis_puan": int(body.servis_puan),
        "yorum": (body.yorum or "").strip(),
        "durum": "beklemede",  # admin moderasyon: beklemede → onaylandi/gizli
        "admin_cevap": "",
        "tarih": now_iso(),
        "onayli_tarih": "",
    }
    await db.reviews.insert_one(dict(doc))
    # Düşük puan ise admin'e bildirim
    if int(body.arac_puan) <= 2 or int(body.servis_puan) <= 2:
        try:
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "baslik": "⚠️ Düşük Puanlı Yorum Geldi!",
                "mesaj": f"{doc['customer_display']} — Araç: {body.arac_puan}⭐ Servis: {body.servis_puan}⭐ ({vehicle.get('plaka', '')})",
                "hedef_type": "admin",
                "hedef_customer_ids": [],
                "tarih": now_iso(),
                "okuyanlar": [],
            })
        except Exception:
            pass
    return await db.reviews.find_one({"id": rid}, {"_id": 0})


@api.get("/reviews/vehicle/{vid}")
async def list_vehicle_reviews(vid: str, min_yildiz: int = 0, limit: int = 50):
    """Public — sadece onaylanmış yorumlar + ortalama. min_yildiz filtresi (araç puan üzerinden)."""
    q = {"vehicle_id": vid, "durum": "onaylandi"}
    if min_yildiz > 0:
        q["arac_puan"] = {"$gte": min_yildiz}
    docs = await db.reviews.find(q, {"_id": 0}).sort("tarih", -1).limit(limit).to_list(limit)
    # Ortalama tüm onaylı yorumlar üzerinden (filtreden bağımsız)
    all_docs = await db.reviews.find({"vehicle_id": vid, "durum": "onaylandi"}, {"_id": 0, "arac_puan": 1, "servis_puan": 1}).to_list(500)
    total = len(all_docs)
    avg_arac = round(sum(d["arac_puan"] for d in all_docs) / total, 2) if total else 0.0
    avg_servis = round(sum(d["servis_puan"] for d in all_docs) / total, 2) if total else 0.0
    return {"reviews": docs, "ortalama_arac": avg_arac, "ortalama_servis": avg_servis, "toplam": total}


@api.get("/reviews/featured")
async def list_featured_reviews(limit: int = 5):
    """Public — ana sayfa için en yüksek puanlı onaylanmış yorumlar (yorum metni dolu olanlar)."""
    docs = await db.reviews.find(
        {"durum": "onaylandi", "yorum": {"$ne": ""}},
        {"_id": 0}
    ).sort([("arac_puan", -1), ("servis_puan", -1), ("tarih", -1)]).limit(limit).to_list(limit)
    return docs


@api.get("/reviews/me")
async def list_my_reviews(user: dict = Depends(require_customer)):
    docs = await db.reviews.find({"customer_id": user["id"]}, {"_id": 0}).sort("tarih", -1).to_list(100)
    return docs


# Admin: yorum yönetimi
@api.get("/admin/reviews")
async def admin_list_reviews(durum: Optional[str] = None, _: dict = Depends(require_admin)):
    q = {}
    if durum:
        q["durum"] = durum
    return await db.reviews.find(q, {"_id": 0}).sort("tarih", -1).to_list(500)


@api.put("/admin/reviews/{rid}")
async def admin_update_review(rid: str, body: ReviewAdminUpdate, _: dict = Depends(require_admin)):
    upd = body.dict(exclude_unset=True)
    if "durum" in upd and upd["durum"] == "onaylandi":
        upd["onayli_tarih"] = now_iso()
    if upd:
        await db.reviews.update_one({"id": rid}, {"$set": upd})
    return await db.reviews.find_one({"id": rid}, {"_id": 0})


@api.delete("/admin/reviews/{rid}")
async def admin_delete_review(rid: str, _: dict = Depends(require_admin)):
    await db.reviews.delete_one({"id": rid})
    return {"ok": True}


# ========================================================================
# CUSTOMER COUNTS — Filter tab counts
# ========================================================================
@api.get("/admin/customers/counts")
async def admin_customer_counts(_: dict = Depends(require_admin)):
    tum = await db.customers.count_documents({})
    bireysel = await db.customers.count_documents({"tip": {"$in": ["bireysel", None]}})
    kurumsal = await db.customers.count_documents({"tip": "kurumsal"})
    engelli = await db.customers.count_documents({"blocked": True})
    return {"tum": tum, "bireysel": bireysel, "kurumsal": kurumsal, "engelli": engelli}


# ========================================================================
# KAZANÇ / MUHASEBE — Gelir & Gider
# ========================================================================
class ExpenseCreate(BaseModel):
    tarih: str  # ISO date YYYY-MM-DD
    kategori: str
    aciklama: Optional[str] = ""
    tutar: float
    kasa: Optional[str] = None  # 'rentcar' | 'eticaret' | None (Belirsiz)
    vehicle_id: Optional[str] = None  # 🆕 Araç bağlantısı (örn: kategori='Araç Bakım' için)


class ExpenseUpdate(BaseModel):
    tarih: Optional[str] = None
    kategori: Optional[str] = None
    aciklama: Optional[str] = None
    tutar: Optional[float] = None
    kasa: Optional[str] = None  # 'rentcar' | 'eticaret' | '' (clear)
    vehicle_id: Optional[str] = None  # 🆕 Araç bağlantısı


class ManualIncomeCreate(BaseModel):
    tarih: str  # ISO date YYYY-MM-DD
    kategori: str
    aciklama: Optional[str] = ""
    tutar: float
    kasa: Optional[str] = None


class ManualIncomeUpdate(BaseModel):
    tarih: Optional[str] = None
    kategori: Optional[str] = None
    aciklama: Optional[str] = None
    tutar: Optional[float] = None
    kasa: Optional[str] = None


VALID_KASA = ("rentcar", "eticaret")


def _norm_kasa(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    if v == "":
        return None
    if v not in VALID_KASA:
        raise HTTPException(400, "kasa 'rentcar' veya 'eticaret' olmalı")
    return v


@api.get("/admin/expenses")
async def admin_list_expenses(
    _: dict = Depends(require_admin),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    kasa: Optional[str] = Query(None),
):
    q: dict = {}
    if start or end:
        rng: dict = {}
        if start:
            rng["$gte"] = start
        if end:
            rng["$lte"] = end
        q["tarih"] = rng
    if kasa == "rentcar":
        q["kasa"] = "rentcar"
    elif kasa == "eticaret":
        q["kasa"] = "eticaret"
    elif kasa == "belirsiz":
        q["$or"] = [{"kasa": None}, {"kasa": {"$exists": False}}]
    docs = await db.expenses.find(q, {"_id": 0}).sort("tarih", -1).to_list(1000)
    return docs


@api.post("/admin/expenses")
async def admin_create_expense(body: ExpenseCreate, _: dict = Depends(require_admin)):
    if body.tutar <= 0:
        raise HTTPException(400, "Tutar 0'dan büyük olmalı")
    if not body.kategori.strip():
        raise HTTPException(400, "Kategori zorunlu")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih or ""):
        raise HTTPException(400, "Geçersiz tarih (YYYY-MM-DD)")
    doc = {
        "id": str(uuid.uuid4()),
        "tarih": body.tarih,
        "kategori": body.kategori.strip(),
        "aciklama": (body.aciklama or "").strip(),
        "tutar": round(float(body.tutar), 2),
        "kasa": _norm_kasa(body.kasa),
        "created_at": now_iso(),
    }
    await db.expenses.insert_one(dict(doc))
    return doc


@api.put("/admin/expenses/{eid}")
async def admin_update_expense(eid: str, body: ExpenseUpdate, _: dict = Depends(require_admin)):
    existing = await db.expenses.find_one({"id": eid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Gider bulunamadı")
    upd: dict = {}
    if body.tarih is not None:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih):
            raise HTTPException(400, "Geçersiz tarih (YYYY-MM-DD)")
        upd["tarih"] = body.tarih
    if body.kategori is not None:
        if not body.kategori.strip():
            raise HTTPException(400, "Kategori boş olamaz")
        upd["kategori"] = body.kategori.strip()
    if body.aciklama is not None:
        upd["aciklama"] = body.aciklama.strip()
    if body.tutar is not None:
        if body.tutar <= 0:
            raise HTTPException(400, "Tutar 0'dan büyük olmalı")
        upd["tutar"] = round(float(body.tutar), 2)
    if body.kasa is not None:
        upd["kasa"] = _norm_kasa(body.kasa)
    if upd:
        await db.expenses.update_one({"id": eid}, {"$set": upd})
    return await db.expenses.find_one({"id": eid}, {"_id": 0})


@api.delete("/admin/expenses/{eid}")
async def admin_delete_expense(eid: str, _: dict = Depends(require_admin)):
    await db.expenses.delete_one({"id": eid})
    return {"ok": True}


# --- Manuel Gelir (E-Ticaret satışı, diğer gelirler) ---
@api.get("/admin/manual-incomes")
async def admin_list_manual_incomes(
    _: dict = Depends(require_admin),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    kasa: Optional[str] = Query(None),
):
    q: dict = {}
    if start or end:
        rng: dict = {}
        if start:
            rng["$gte"] = start
        if end:
            rng["$lte"] = end
        q["tarih"] = rng
    if kasa == "rentcar":
        q["kasa"] = "rentcar"
    elif kasa == "eticaret":
        q["kasa"] = "eticaret"
    elif kasa == "belirsiz":
        q["$or"] = [{"kasa": None}, {"kasa": {"$exists": False}}]
    docs = await db.manual_incomes.find(q, {"_id": 0}).sort("tarih", -1).to_list(1000)
    return docs


@api.post("/admin/manual-incomes")
async def admin_create_manual_income(body: ManualIncomeCreate, _: dict = Depends(require_admin)):
    if body.tutar <= 0:
        raise HTTPException(400, "Tutar 0'dan büyük olmalı")
    if not body.kategori.strip():
        raise HTTPException(400, "Kategori zorunlu")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih or ""):
        raise HTTPException(400, "Geçersiz tarih (YYYY-MM-DD)")
    doc = {
        "id": str(uuid.uuid4()),
        "tarih": body.tarih,
        "kategori": body.kategori.strip(),
        "aciklama": (body.aciklama or "").strip(),
        "tutar": round(float(body.tutar), 2),
        "kasa": _norm_kasa(body.kasa),
        "created_at": now_iso(),
    }
    await db.manual_incomes.insert_one(dict(doc))
    return doc


@api.put("/admin/manual-incomes/{iid}")
async def admin_update_manual_income(iid: str, body: ManualIncomeUpdate, _: dict = Depends(require_admin)):
    existing = await db.manual_incomes.find_one({"id": iid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Gelir bulunamadı")
    upd: dict = {}
    if body.tarih is not None:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih):
            raise HTTPException(400, "Geçersiz tarih (YYYY-MM-DD)")
        upd["tarih"] = body.tarih
    if body.kategori is not None:
        if not body.kategori.strip():
            raise HTTPException(400, "Kategori boş olamaz")
        upd["kategori"] = body.kategori.strip()
    if body.aciklama is not None:
        upd["aciklama"] = body.aciklama.strip()
    if body.tutar is not None:
        if body.tutar <= 0:
            raise HTTPException(400, "Tutar 0'dan büyük olmalı")
        upd["tutar"] = round(float(body.tutar), 2)
    if body.kasa is not None:
        upd["kasa"] = _norm_kasa(body.kasa)
    if upd:
        await db.manual_incomes.update_one({"id": iid}, {"$set": upd})
    return await db.manual_incomes.find_one({"id": iid}, {"_id": 0})


@api.delete("/admin/manual-incomes/{iid}")
async def admin_delete_manual_income(iid: str, _: dict = Depends(require_admin)):
    await db.manual_incomes.delete_one({"id": iid})
    return {"ok": True}


# --- Hibrit kategori autocomplete: son kullanılan farklı kategoriler ---
@api.get("/admin/earning-categories")
async def admin_earning_categories(
    _: dict = Depends(require_admin),
    tip: str = Query(..., regex="^(gelir|gider)$"),
):
    """Geçmişte kullanılan distinct kategorileri döner (kullanım sıklığına göre)."""
    coll = db.manual_incomes if tip == "gelir" else db.expenses
    pipeline = [
        {"$group": {"_id": "$kategori", "count": {"$sum": 1}}},
        {"$sort": {"count": -1, "_id": 1}},
        {"$limit": 30},
    ]
    docs = await coll.aggregate(pipeline).to_list(50)
    defaults = {
        "gelir": ["E-Ticaret Satışı", "Yedek Parça Satışı", "Komisyon", "Sigorta Tahsilatı", "Diğer Gelir"],
        "gider": ["Yakıt", "Bakım", "Sigorta", "Kira", "Yıkama", "Vergi", "Personel", "Diğer Gider"],
    }
    used = [d["_id"] for d in docs if d.get("_id")]
    merged: list = []
    seen: set = set()
    for k in used + defaults[tip]:
        kk = (k or "").strip()
        if kk and kk not in seen:
            seen.add(kk)
            merged.append(kk)
    return merged


# --- Kasa Durumu (Cashflow snapshot) ---
@api.get("/admin/cashflow")
async def admin_cashflow(
    _: dict = Depends(require_admin),
    kasa: Optional[str] = Query(None),  # None / 'rentcar' / 'eticaret' / 'belirsiz'
):
    """
    Kasa Durumu — Net Kar hesabı.

    Rentcar Kasa = (yukleme + rentcar manuel gelir) - musteri_bakiye - bekleyen_havale - bloke_prov - rentcar gider
    E-Ticaret Kasa = eticaret manuel gelir - eticaret gider
    NET KAR (Cebimdeki) = Rentcar Kasa + E-Ticaret Kasa

    Belirsiz (kasa atanmamış) kayıtlar hesaba DAHİL DEĞİL — sadece kasa=belirsiz filtresinde görünür.
    """

    async def sum_field(coll, match: dict, field: str) -> float:
        pipeline = ([{"$match": match}] if match else []) + [{"$group": {"_id": None, "toplam": {"$sum": f"${field}"}}}]
        agg = await coll.aggregate(pipeline).to_list(1)
        return float(agg[0]["toplam"]) if agg else 0.0

    async def count_docs(coll, match: dict) -> int:
        return await coll.count_documents(match) if match is not None else 0

    # Tamamlanan rezervasyonlardan toplam (kasaya dönüşen kazanç) — Rentcar
    res_pipeline = [
        {"$match": {"durum": "tamamlandi"}},
        {"$group": {"_id": None, "toplam": {"$sum": "$toplam_tutar"}}},
    ]
    res_agg = await db.reservations.aggregate(res_pipeline).to_list(1)
    rezervasyon_kazanc_brut = float(res_agg[0]["toplam"]) if res_agg else 0.0

    # 🤝 KONSİNYE — Sahiplerine olan hak ediş hesabı + YS Auto net payı
    # YENİ MANTIK: Konsinye rezervasyonun sahibin payı YS Auto'nun geliri değil — ayrı havuzda.
    # rezervasyon_kazanc = brüt - sahibin_payi (sadece YS Auto'nun payı kasaya geçer)
    # Borç ödendiğinde YS Auto net kar etkilenmez (zaten gelirde sayılmamıştı).
    konsinye_toplam_hakkedis = 0.0
    konsinye_brut = 0.0
    konsinye_devlet_total = 0.0  # devlet kesintisi YS Auto'da kalır (vergi rezervi)
    konsinye_rez_sayisi = 0
    try:
        completed_rez = await db.reservations.find({"durum": "tamamlandi"}, {"_id": 0}).to_list(5000)
        for r in completed_rez:
            earn = await calculate_konsinye_earning_for_reservation(r)
            if earn:
                konsinye_toplam_hakkedis += earn["sahibin_hakkedisi"]
                konsinye_brut += earn["brut"]
                konsinye_devlet_total += earn.get("devlet_kesinti", 0)
                konsinye_rez_sayisi += 1
    except Exception as e:
        logger.warning(f"Konsinye hak ediş hesaplama hatası: {e}")
    
    # ⚠️ rezervasyon_kazanc = brüt - sahibin payı (sahibin payı hiç YS Auto'nun olmadı)
    rezervasyon_kazanc = round(rezervasyon_kazanc_brut - konsinye_toplam_hakkedis, 2)
    
    # Ödenmiş tutar — toplam konsinye_odemeler (bilgi için)
    konsinye_odenmis_total = await sum_field(db.konsinye_odemeler, {"odendi": True}, "tutar")
    konsinye_bakim_total = await sum_field(db.arac_bakim_giderleri, {}, "tutar")
    # Net sahip borcu = toplam hak ediş - ödenmiş - bakım giderleri
    konsinye_sahip_borc = max(0.0, round(konsinye_toplam_hakkedis - konsinye_odenmis_total - konsinye_bakim_total, 2))

    # Yüklemeler (yalnızca bilgi amaçlı — formülde KULLANILMIYOR)
    yukleme_total = await sum_field(db.wallet_tx, {"tip": "yukleme"}, "tutar")

    # Manuel gelirler (kasa kırılımı)
    mi_rentcar = await sum_field(db.manual_incomes, {"kasa": "rentcar"}, "tutar")
    mi_eticaret = await sum_field(db.manual_incomes, {"kasa": "eticaret"}, "tutar")
    mi_belirsiz = await sum_field(db.manual_incomes, {"$or": [{"kasa": None}, {"kasa": {"$exists": False}}]}, "tutar")

    # Müşteri bakiye borcu — bilgi amaçlı (müşterilerin cüzdanında duran para)
    musteri_bakiye = await sum_field(db.wallets, {}, "bakiye")

    # Bekleyen havaleler — bilgi amaçlı
    bekleyen_havale = await sum_field(db.wallet_tx, {"tip": "yukleme_beklemede", "durum": "beklemede"}, "tutar")
    beklemede_count = await count_docs(db.wallet_tx, {"tip": "yukleme_beklemede", "durum": "beklemede"})

    # Bloke provizyonlar — bilgi amaçlı
    bloke_prov = await sum_field(db.provisions, {"durum": "alindi"}, "tutar")

    # Giderler (kasa kırılımı)
    gider_rentcar = await sum_field(db.expenses, {"kasa": "rentcar"}, "tutar")
    gider_eticaret = await sum_field(db.expenses, {"kasa": "eticaret"}, "tutar")
    gider_belirsiz = await sum_field(db.expenses, {"$or": [{"kasa": None}, {"kasa": {"$exists": False}}]}, "tutar")

    # ✅ DOĞRU KASA HESABI:
    # Rentcar Kasa = Tamamlanan rezervasyon kazancı + Rentcar manuel gelir - Rentcar gider - Konsinye sahip borç
    # E-Ticaret Kasa = E-Ticaret manuel gelir - E-Ticaret gider
    # Para sadece tamamlanan rezervasyondan kazanılır; aktif/onaylı rezervasyonlardaki müşteri parası
    # henüz kazanç değildir (Bekleyen Gelir kartında ayrı gösteriliyor).
    # ✅ KASA HESABI (Yeni mantık):
    # Konsinye rezervasyonun sahibin payı zaten "rezervasyon_kazanc"a dahil EDİLMEDİ — sadece YS Auto payı sayıldı.
    # Sahibe ödeme yapılması artık kasayı etkilemez (zaten gelir olarak sayılmamıştı).
    # Bakım giderleri firma adına yapıldı, gider olarak sayılır (sahibin borcundan da düşülür).
    # Not: Devlet kesintisi (100₺/gün) YS Auto'da kalır (vergi rezervi).
    rentcar_kasa = round(rezervasyon_kazanc + mi_rentcar - gider_rentcar - konsinye_bakim_total, 2)
    eticaret_kasa = round(mi_eticaret - gider_eticaret, 2)
    net_kar = round(rentcar_kasa + eticaret_kasa, 2)

    # Belirsiz net (admin gözden geçirsin diye ayrı gösterilir)
    belirsiz_net = round(mi_belirsiz - gider_belirsiz, 2)

    # Filtreye göre dönüş
    if kasa == "rentcar":
        return {
            "kasa": "rentcar",
            "yukleme_total": round(yukleme_total, 2),
            "manuel_gelir": round(mi_rentcar, 2),
            "musteri_bakiye_borcu": round(musteri_bakiye, 2),
            "bekleyen_havaleler": round(bekleyen_havale, 2),
            "bekleyen_havale_adet": beklemede_count,
            "bloke_provizyonlar": round(bloke_prov, 2),
            "gider_total": round(gider_rentcar, 2),
            "rentcar_kasa": rentcar_kasa,
            "eticaret_kasa": 0.0,
            "net_kar": rentcar_kasa,
            "belirsiz_net": 0.0,
            "belirsiz_gelir": 0.0,
            "belirsiz_gider": 0.0,
        }
    if kasa == "eticaret":
        return {
            "kasa": "eticaret",
            "yukleme_total": 0.0,
            "manuel_gelir": round(mi_eticaret, 2),
            "musteri_bakiye_borcu": 0.0,
            "bekleyen_havaleler": 0.0,
            "bekleyen_havale_adet": 0,
            "bloke_provizyonlar": 0.0,
            "gider_total": round(gider_eticaret, 2),
            "rentcar_kasa": 0.0,
            "eticaret_kasa": eticaret_kasa,
            "net_kar": eticaret_kasa,
            "belirsiz_net": 0.0,
            "belirsiz_gelir": 0.0,
            "belirsiz_gider": 0.0,
        }
    if kasa == "belirsiz":
        return {
            "kasa": "belirsiz",
            "yukleme_total": 0.0,
            "manuel_gelir": round(mi_belirsiz, 2),
            "musteri_bakiye_borcu": 0.0,
            "bekleyen_havaleler": 0.0,
            "bekleyen_havale_adet": 0,
            "bloke_provizyonlar": 0.0,
            "gider_total": round(gider_belirsiz, 2),
            "rentcar_kasa": 0.0,
            "eticaret_kasa": 0.0,
            "net_kar": belirsiz_net,
            "belirsiz_net": belirsiz_net,
            "belirsiz_gelir": round(mi_belirsiz, 2),
            "belirsiz_gider": round(gider_belirsiz, 2),
        }

    # Tümü (kasa=None) — full breakdown
    return {
        "kasa": "tum",
        "yukleme_total": round(yukleme_total, 2),
        "manuel_gelir": round(mi_rentcar + mi_eticaret, 2),  # Belirsiz HARİÇ
        "musteri_bakiye_borcu": round(musteri_bakiye, 2),
        "bekleyen_havaleler": round(bekleyen_havale, 2),
        "bekleyen_havale_adet": beklemede_count,
        "bloke_provizyonlar": round(bloke_prov, 2),
        "gider_total": round(gider_rentcar + gider_eticaret, 2),  # Belirsiz HARİÇ
        "rentcar_kasa": rentcar_kasa,
        "eticaret_kasa": eticaret_kasa,
        "net_kar": net_kar,
        "belirsiz_net": belirsiz_net,
        "belirsiz_gelir": round(mi_belirsiz, 2),
        "belirsiz_gider": round(gider_belirsiz, 2),
        # 🤝 Konsinye breakdown
        "konsinye_toplam_hakkedis": round(konsinye_toplam_hakkedis, 2),
        "konsinye_brut": round(konsinye_brut, 2),
        "konsinye_rez_sayisi": konsinye_rez_sayisi,
        "konsinye_odenmis_total": round(konsinye_odenmis_total, 2),
        "konsinye_bakim_total": round(konsinye_bakim_total, 2),
        "konsinye_sahip_borc": round(konsinye_sahip_borc, 2),
        "rezervasyon_kazanc": round(rezervasyon_kazanc, 2),
    }


# --- Bekleyen Gelir (henüz tamamlanmamış aktif/onaylanmış rezervasyonlar) ---
@api.get("/admin/pending-revenue")
async def admin_pending_revenue(_: dict = Depends(require_admin)):
    """
    Bekleyen gelir: onaylanmış ve aktif rezervasyonların toplam_tutar toplamı.
    Bunlar rezervasyon tamamlandığında Kazanç'a dahil olacak.
    Sadece Rentcar kasası ile ilgili.
    """
    pipeline = [
        {"$match": {"durum": {"$in": ["onaylandi", "aktif"]}}},
        {"$group": {
            "_id": "$durum",
            "toplam": {"$sum": "$toplam_tutar"},
            "adet": {"$sum": 1},
        }},
    ]
    res = await db.reservations.aggregate(pipeline).to_list(10)
    onaylandi_total = 0.0
    aktif_total = 0.0
    onaylandi_count = 0
    aktif_count = 0
    for r in res:
        if r["_id"] == "onaylandi":
            onaylandi_total = float(r.get("toplam", 0))
            onaylandi_count = int(r.get("adet", 0))
        elif r["_id"] == "aktif":
            aktif_total = float(r.get("toplam", 0))
            aktif_count = int(r.get("adet", 0))
    return {
        "toplam": round(onaylandi_total + aktif_total, 2),
        "onaylandi_total": round(onaylandi_total, 2),
        "onaylandi_adet": onaylandi_count,
        "aktif_total": round(aktif_total, 2),
        "aktif_adet": aktif_count,
    }


@api.get("/admin/earnings")
async def admin_earnings(
    _: dict = Depends(require_admin),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    kasa: Optional[str] = Query(None),
):
    """
    Gelir kaynakları:
      - Tamamlanan rezervasyonlar (durum=tamamlandi) → toplam_tutar  (sadece RENTCAR kasası)
      - Manuel gelirler (db.manual_incomes) → kasa filtreli
    Gider kaynakları:
      - Manuel girilen gider kayıtları (db.expenses) → kasa filtreli
    Tarih filtresi opsiyonel (YYYY-MM-DD).

    YENİ MANTIK: Çoklu aya yayılan rezervasyonlar GÜN-BAZLI ORANTI ile bölünür.
    Yani 22.04-22.05 (30 gün) ve filtre Nisan → 8/30 oranında tutar Nisan'a yansır.
    """
    res_query: dict = {"durum": "tamamlandi"}
    exp_query: dict = {}
    mi_query: dict = {}

    # Rezervasyonları: filtre dönemine BAŞLANGIÇ veya BİTİŞ ile çakışan tüm tamamlananlar
    if start:
        # Rez başlangıcı dönem bitişinden ÖNCE olmalı (bas <= end)
        res_query.setdefault("baslangic_tarihi", {})["$lte"] = f"{end or '9999-12-31'}T23:59:59.999Z"
        exp_query.setdefault("tarih", {})["$gte"] = start
        mi_query.setdefault("tarih", {})["$gte"] = start
    if end:
        # Rez bitişi dönem başlangıcından SONRA olmalı (bit >= start)
        res_query.setdefault("bitis_tarihi", {})["$gte"] = f"{start or '0000-01-01'}T00:00:00.000Z"
        exp_query.setdefault("tarih", {})["$lte"] = end
        mi_query.setdefault("tarih", {})["$lte"] = end

    # Kasa filtresi
    include_rezervasyon = kasa in (None, "rentcar")
    if kasa == "rentcar":
        exp_query["kasa"] = "rentcar"
        mi_query["kasa"] = "rentcar"
    elif kasa == "eticaret":
        exp_query["kasa"] = "eticaret"
        mi_query["kasa"] = "eticaret"
    elif kasa == "belirsiz":
        exp_query["$or"] = [{"kasa": None}, {"kasa": {"$exists": False}}]
        mi_query["$or"] = [{"kasa": None}, {"kasa": {"$exists": False}}]
        include_rezervasyon = False  # Rezervasyon = kesin rentcar, belirsiz olamaz

    reservations: list = []
    if include_rezervasyon:
        reservations = await db.reservations.find(res_query, {"_id": 0}).sort("bitis_tarihi", -1).to_list(1000)
    expenses = await db.expenses.find(exp_query, {"_id": 0}).sort("tarih", -1).to_list(1000)
    manual_incomes = await db.manual_incomes.find(mi_query, {"_id": 0}).sort("tarih", -1).to_list(1000)

    # Dönem sınırları (UTC datetime)
    period_start = parse_iso(f"{start}T00:00:00.000Z") if start else None
    period_end = parse_iso(f"{end}T23:59:59.999Z") if end else None

    # Gelir kalemleri (rezervasyon + manuel) — orantılı bölünme
    gelir_kalemleri: list = []
    rezervasyon_gelir = 0.0
    konsinye_net_pay = 0.0  # 🆕 Konsinye rezervasyonlardan YS Auto'nun NET payı (sahibe pay düşülmüş)
    konsinye_brut_gelir = 0.0  # 🆕 Konsinye rezervasyonların tam tutarı (bilgi amaçlı)
    konsinye_sahibe_pay = 0.0  # 🆕 Konsinye sahibinin payı (gider değil — ayrı havuz)
    diger_rentcar_gelir = 0.0  # 🆕 Non-konsinye rezervasyonlardan gelir
    for r in reservations:
        amt_full = float(r.get("toplam_tutar") or 0)
        if amt_full <= 0:
            continue
        # Gün-bazlı orantı hesapla
        try:
            r_bas = parse_iso(r.get("baslangic_tarihi"))
            r_bit = parse_iso(r.get("bitis_tarihi"))
            total_days = max(1, (r_bit - r_bas).days + ((r_bit - r_bas).seconds / 86400))
        except Exception:
            r_bas, r_bit, total_days = None, None, 1.0
        # Dönem ile çakışan gün sayısı
        if period_start and period_end and r_bas and r_bit:
            ov_start = max(r_bas, period_start)
            ov_end = min(r_bit, period_end)
            overlap_seconds = max(0, (ov_end - ov_start).total_seconds())
            overlap_days = overlap_seconds / 86400.0
        else:
            overlap_days = total_days
        oran = min(1.0, max(0.0, overlap_days / total_days)) if total_days > 0 else 1.0
        amt = round(amt_full * oran, 2)
        if amt <= 0:
            continue

        # 🤝 Konsinye payı hesapla (rezervasyon konsinye araç ise sahibin payını çıkar)
        is_konsinye_rez = False
        sahibe_orantili = 0.0
        try:
            earn = await calculate_konsinye_earning_for_reservation(r)
            if earn:
                is_konsinye_rez = True
                sahibe_orantili = round(earn["sahibin_hakkedisi"] * oran, 2)
        except Exception:
            pass

        ys_pay_amt = round(amt - sahibe_orantili, 2)
        rezervasyon_gelir += ys_pay_amt  # YS'nin gerçek payı kasaya/gelire eklenir

        if is_konsinye_rez:
            konsinye_net_pay += ys_pay_amt
            konsinye_brut_gelir += amt
            konsinye_sahibe_pay += sahibe_orantili
        else:
            diger_rentcar_gelir += ys_pay_amt
        snap = r.get("vehicle_snapshot") or {}
        cust = await db.customers.find_one({"id": r.get("customer_id")}, {"_id": 0, "ad": 1, "soyad": 1})
        musteri = f"{(cust or {}).get('ad', '')} {(cust or {}).get('soyad', '')}".strip() or "—"

        # Detay: çoklu aya yayıldıysa breakdown
        breakdown = None
        is_split = oran < 0.999  # Tam değilse split olmuştur
        if is_split and r_bas and r_bit:
            breakdown = {
                "tam_tutar": round(amt_full, 2),
                "tam_gun": int(round(total_days)),
                "donem_gun": int(round(overlap_days)),
                "donem_oran": round(oran * 100, 1),
                "rez_baslangic": r_bas.isoformat(),
                "rez_bitis": r_bit.isoformat(),
            }
        gelir_kalemleri.append({
            "id": r.get("id"),
            "tarih": (r.get("bitis_tarihi") or "")[:10],
            "kaynak": "rezervasyon",
            "kategori": "Kiralama" + (" (Konsinye)" if is_konsinye_rez else ""),
            "aciklama": f"{snap.get('marka', '')} {snap.get('model', '')} ({snap.get('plaka', '')})".strip(),
            "musteri": musteri,
            "tutar": ys_pay_amt,  # YS'nin payı (sahibe pay düşülmüş)
            "tam_tutar": amt,  # 🆕 Tam müşteri ödemesi (bilgi)
            "sahibe_pay": sahibe_orantili if is_konsinye_rez else 0,  # 🆕 Konsinye sahibin payı
            "konsinye": is_konsinye_rez,  # 🆕 Konsinye işareti
            "kasa": "rentcar",
            "editable": False,
            "breakdown": breakdown,  # None ise tam tutar; varsa orantılı bölünme detayı
        })

    manuel_gelir = 0.0
    for mi in manual_incomes:
        amt = float(mi.get("tutar") or 0)
        if amt <= 0:
            continue
        manuel_gelir += amt
        gelir_kalemleri.append({
            "id": mi.get("id"),
            "tarih": mi.get("tarih"),
            "kaynak": "manuel",
            "kategori": mi.get("kategori", ""),
            "aciklama": mi.get("aciklama", ""),
            "musteri": "—",
            "tutar": round(amt, 2),
            "kasa": mi.get("kasa"),
            "editable": True,
            "breakdown": None,
        })

    gelir_kalemleri.sort(key=lambda x: x.get("tarih", ""), reverse=True)

    toplam_gelir = rezervasyon_gelir + manuel_gelir
    toplam_gider = sum(float(e.get("tutar") or 0) for e in expenses)
    net = round(toplam_gelir - toplam_gider, 2)

    return {
        "kasa": kasa or "tum",
        "toplam_gelir": round(toplam_gelir, 2),
        "rezervasyon_gelir": round(rezervasyon_gelir, 2),
        "manuel_gelir": round(manuel_gelir, 2),
        # 🤝 KONSİNYE BREAKDOWN (yeni)
        "konsinye_net_pay": round(konsinye_net_pay, 2),  # YS Auto'nun konsinye'den NET payı
        "konsinye_brut_gelir": round(konsinye_brut_gelir, 2),  # Konsinye rez. tam tutar (bilgi)
        "konsinye_sahibe_pay": round(konsinye_sahibe_pay, 2),  # Konsinye sahibine giden (gider değil)
        "diger_rentcar_gelir": round(diger_rentcar_gelir, 2),  # Konsinye-olmayan rentcar
        "toplam_gider": round(toplam_gider, 2),
        "net": net,
        "gelir_kalemleri": gelir_kalemleri,
        "gider_kalemleri": expenses,
    }


# ========================================================================
# ARAÇ PERFORMANSI — Her araç için kiralama gün, araç geliri, hizmet, km, toplam
# ========================================================================
@api.get("/admin/vehicle-performance")
async def admin_vehicle_performance(
    _: dict = Depends(require_admin),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
):
    """
    Her araç için tamamlanan rezervasyonlardan derlenmiş performans tablosu.
    YENİ MANTIK: Çoklu aya yayılan rezervasyonlar GÜN-BAZLI ORANTI ile bölünür.
    Yani Nisan'da 8 gün, Mayıs'ta 22 gün kirada olan araç → her ayın kendi payına göre kazanç+gün sayar.
    Dönüş:
      - araclar: [{vehicle_id, marka, model, plaka, foto_url, kiralama_gun, arac_gelir, hizmet_gelir, km_gelir, toplam_kazanc, rezervasyon_adet, splits: [...]}]
    """
    res_query: dict = {"durum": "tamamlandi"}
    # Çoklu-aya-yayılma desteği: bas <= end AND bit >= start
    if start:
        res_query.setdefault("baslangic_tarihi", {})["$lte"] = f"{end or '9999-12-31'}T23:59:59.999Z"
    if end:
        res_query.setdefault("bitis_tarihi", {})["$gte"] = f"{start or '0000-01-01'}T00:00:00.000Z"

    reservations = await db.reservations.find(res_query, {"_id": 0}).to_list(5000)

    # 🆕 Services map — secilen_hizmetler sadece service_id içerirse fiyatı buradan al
    all_services = await db.services.find({}, {"_id": 0}).to_list(500)
    services_map: dict = {str(s.get("id")): s for s in all_services if s.get("id")}

    # Dönem sınırları
    period_start = parse_iso(f"{start}T00:00:00.000Z") if start else None
    period_end = parse_iso(f"{end}T23:59:59.999Z") if end else None

    # Map: vehicle_id → aggregate
    agg: dict = {}
    for r in reservations:
        vid = r.get("vehicle_id")
        if not vid:
            continue
        try:
            r_bas = parse_iso(r.get("baslangic_tarihi"))
            r_bit = parse_iso(r.get("bitis_tarihi"))
            total_seconds = max(1.0, (r_bit - r_bas).total_seconds())
            total_days = total_seconds / 86400.0
        except Exception:
            r_bas, r_bit = None, None
            total_seconds, total_days = 1.0, 1.0
        # Dönemle çakışma oranı
        if period_start and period_end and r_bas and r_bit:
            ov_start = max(r_bas, period_start)
            ov_end = min(r_bit, period_end)
            overlap_seconds = max(0.0, (ov_end - ov_start).total_seconds())
            overlap_days = overlap_seconds / 86400.0
        else:
            overlap_seconds = total_seconds
            overlap_days = total_days
        oran = min(1.0, max(0.0, overlap_seconds / total_seconds)) if total_seconds > 0 else 1.0
        if oran <= 0:
            continue

        pricing = r.get("pricing") or {}
        rez_gun = int(r.get("gun_sayisi") or r.get("toplam_gun") or 0)
        pricing_gun = int(pricing.get("gun_sayisi") or 0)
        pricing_synced = bool(pricing_gun) and bool(rez_gun) and pricing_gun == rez_gun

        # ✨ HİZMET KAYNAĞI ÖNCELİĞİ: secilen_hizmetler (rezervasyon root) > pricing.hizmetler > ekstra_hizmetler
        # Çünkü bazı rezervasyonlarda pricing.hizmetler boş kalmış olabilir.
        hiz_root = r.get("secilen_hizmetler") or []
        hiz_pricing = pricing.get("hizmetler") or []
        hiz_extra = r.get("ekstra_hizmetler") or []
        hiz_list = hiz_root if len(hiz_root) > 0 else (hiz_pricing if len(hiz_pricing) > 0 else hiz_extra)
        hizmetler_toplam_dogru = 0.0
        for h in hiz_list:
            # 🆕 Hizmet sadece {service_id, adet} formatındaysa services_map'ten zenginleştir
            svc = None
            sid = h.get("service_id") or h.get("id")
            if sid and not h.get("fiyat") and not h.get("birim_fiyat") and not h.get("tutar"):
                svc = services_map.get(str(sid)) or {}
            tip = str(h.get("tip") or (svc or {}).get("tip") or "tek_seferlik").lower()
            fiyat = float(h.get("fiyat") or h.get("birim_fiyat") or (svc or {}).get("fiyat") or 0)
            tutar_field = float(h.get("tutar") or 0)
            adet = int(h.get("adet") or 1)
            if tip == "gunluk":
                hizmetler_toplam_dogru += fiyat * adet * max(1, rez_gun or 1)
            else:
                hizmetler_toplam_dogru += tutar_field if tutar_field else (fiyat * adet)

        km_gelir_full = float(r.get("ek_km_tutar") or 0) + float(r.get("km_asim_tutar") or 0)
        toplam_full = float(r.get("toplam_tutar") or 0)

        # Pricing.hizmetler boş ama secilen_hizmetler dolu ise pricing_synced'i False say (stale pricing)
        if pricing_synced and len(hiz_pricing) == 0 and len(hiz_root) > 0 and hizmetler_toplam_dogru > 0:
            pricing_synced = False

        if pricing_synced:
            arac_gelir_full = float(pricing.get("arac_toplam") or pricing.get("arac_total") or 0)
            hizmet_gelir_full = float(pricing.get("hizmetler_toplam") or 0) + float(r.get("ek_hizmet_tutar") or 0)
            # Eğer pricing.hizmetler_toplam=0 ama secilen_hizmetler'den hesap > 0 ise üstüne yaz
            if hizmet_gelir_full <= 0 and hizmetler_toplam_dogru > 0:
                hizmet_gelir_full = hizmetler_toplam_dogru
        else:
            # ⚠️ pricing eski/uyumsuz — toplam_tutar'dan türev hesap (cashflow ile tutarlı)
            arac_gelir_full = max(0.0, round(toplam_full - hizmetler_toplam_dogru - km_gelir_full, 2))
            if arac_gelir_full <= 0:
                gf = float(pricing.get("gunluk_fiyat") or pricing.get("gunluk_fiyat_baz") or r.get("gunluk_birim_fiyat") or 0)
                arac_gelir_full = round(gf * max(1, rez_gun or 1), 2)
            hizmet_gelir_full = hizmetler_toplam_dogru + float(r.get("ek_hizmet_tutar") or 0)

        # Orantı uygula
        arac_gelir = round(arac_gelir_full * oran, 2)
        hizmet_gelir = round(hizmet_gelir_full * oran, 2)
        km_gelir = round(km_gelir_full * oran, 2)
        toplam = round(toplam_full * oran, 2)
        days_in_period = round(overlap_days, 1)

        if not agg.get(vid):
            agg[vid] = {
                "vehicle_id": vid,
                "kiralama_gun": 0.0,
                "arac_gelir": 0.0,
                "hizmet_gelir": 0.0,
                "km_gelir": 0.0,
                "toplam_kazanc": 0.0,
                "rezervasyon_adet": 0,
                "splits": [],  # Çoklu aya yayılan rezervasyon detayları
            }
        a = agg[vid]
        a["kiralama_gun"] += days_in_period
        a["arac_gelir"] += arac_gelir
        a["hizmet_gelir"] += hizmet_gelir
        a["km_gelir"] += km_gelir
        a["toplam_kazanc"] += toplam
        a["rezervasyon_adet"] += 1
        # Split detayını sakla (orantı < 100% ise — yani çoklu aya yayılmış)
        if oran < 0.999 and r_bas and r_bit:
            a["splits"].append({
                "rez_id": r.get("id"),
                "rez_baslangic": r_bas.isoformat(),
                "rez_bitis": r_bit.isoformat(),
                "tam_tutar": round(toplam_full, 2),
                "tam_gun": round(total_days, 1),
                "donem_gun": days_in_period,
                "donem_tutar": toplam,
                "oran_yuzde": round(oran * 100, 1),
            })

    # Vehicle bilgilerini ekle
    vids = list(agg.keys())
    araclar: list = []
    toplam_konsinye_hakkedis = 0.0
    toplam_konsinye_brut = 0.0
    toplam_konsinye_devlet = 0.0
    # 🔧 ARAÇ BAKIM HARITASI — her araç için toplam bakım tutarı
    # Konsinye araçlar için: db.arac_bakim_giderleri
    # Kendi araçlar için: db.expenses (kategori="Araç Bakım", vehicle_id dolu)
    bakim_map: dict = {}  # vehicle_id -> toplam_bakim
    try:
        bakim_q: dict = {}
        if start: bakim_q.setdefault("tarih", {})["$gte"] = start
        if end: bakim_q.setdefault("tarih", {})["$lte"] = end + "T23:59:59.999Z"
        konsinye_bakim = await db.arac_bakim_giderleri.find(bakim_q, {"_id": 0, "vehicle_id": 1, "tutar": 1}).to_list(1000)
        for b in konsinye_bakim:
            vid = b.get("vehicle_id")
            if vid:
                bakim_map[vid] = bakim_map.get(vid, 0.0) + float(b.get("tutar") or 0)
        # Kendi araçlardan kategori='Araç Bakım' olan harcamalar
        exp_bakim_q: dict = {"kategori": "Araç Bakım", "vehicle_id": {"$ne": None}}
        if start: exp_bakim_q.setdefault("tarih", {})["$gte"] = start
        if end: exp_bakim_q.setdefault("tarih", {})["$lte"] = end + "T23:59:59.999Z"
        own_bakim = await db.expenses.find(exp_bakim_q, {"_id": 0, "vehicle_id": 1, "tutar": 1}).to_list(1000)
        for e in own_bakim:
            vid = e.get("vehicle_id")
            if vid:
                bakim_map[vid] = bakim_map.get(vid, 0.0) + float(e.get("tutar") or 0)
    except Exception as e:
        logger.warning(f"vehicle-performance bakım haritası başarısız: {e}")
    if vids:
        v_docs = await db.vehicles.find({"id": {"$in": vids}}, {"_id": 0, "id": 1, "marka": 1, "model": 1, "plaka": 1, "foto_url": 1, "konsinye": 1, "konsinye_sahibi_id": 1, "konsinye_pay_yuzde": 1}).to_list(1000)
        v_map = {v["id"]: v for v in v_docs}
        for vid, a in agg.items():
            v = v_map.get(vid) or {}
            is_konsinye = bool(v.get("konsinye"))
            pay_yuzde = float(v.get("konsinye_pay_yuzde") or 70.0) if is_konsinye else 0.0
            # Konsinye hesaplama: arac_gelir + km_gelir konsinye payına dahildir; hizmet_gelir DAHİL DEĞİL
            konsinye_brut = round(a["arac_gelir"] + a["km_gelir"], 2) if is_konsinye else 0.0
            konsinye_devlet = round(100.0 * a["kiralama_gun"], 2) if is_konsinye else 0.0
            konsinye_net = max(0.0, round(konsinye_brut - konsinye_devlet, 2))
            konsinye_hakkedis = round(konsinye_net * pay_yuzde / 100.0, 2) if is_konsinye else 0.0
            ys_komisyonu_konsinye = round(konsinye_net - konsinye_hakkedis, 2) if is_konsinye else 0.0
            # YS Auto net gelir: konsinye değilse toplam_kazanc; konsinye ise toplam_kazanc - sahip_payi
            # (Devlet kesintisi şu an çıkarılmıyor — kullanıcı talebi, gelecekteki vergi rezervi olarak değerlendirilebilir)
            ys_net = round(a["toplam_kazanc"] - konsinye_hakkedis, 2) if is_konsinye else round(a["toplam_kazanc"], 2)
            if is_konsinye:
                toplam_konsinye_hakkedis += konsinye_hakkedis
                toplam_konsinye_brut += konsinye_brut
                toplam_konsinye_devlet += konsinye_devlet
            araclar.append({
                "vehicle_id": vid,
                "marka": v.get("marka", "—"),
                "model": v.get("model", ""),
                "plaka": v.get("plaka", "—"),
                "foto_url": v.get("foto_url", ""),
                "kiralama_gun": int(round(a["kiralama_gun"])),
                "arac_gelir": round(a["arac_gelir"], 2),
                "hizmet_gelir": round(a["hizmet_gelir"], 2),
                "km_gelir": round(a["km_gelir"], 2),
                "toplam_kazanc": round(a["toplam_kazanc"], 2),
                "rezervasyon_adet": int(a["rezervasyon_adet"]),
                "splits": a["splits"],
                # Konsinye breakdown
                "konsinye": is_konsinye,
                "konsinye_pay_yuzde": pay_yuzde,
                "konsinye_brut": konsinye_brut,
                "konsinye_devlet_kesinti": konsinye_devlet,
                "konsinye_net": konsinye_net,
                "konsinye_hakkedis": konsinye_hakkedis,  # araç sahibine ödenecek
                "ys_net_kazanc": ys_net,  # YS Auto'nun bu araçtan net gelirleri (konsinye payı düşülmüş)
                # 🔧 Araç bakım toplamı (sadece görsel — net'i etkilemez)
                "bakim_tutar": round(bakim_map.get(vid, 0.0), 2),
            })
        araclar.sort(key=lambda x: x["toplam_kazanc"], reverse=True)

    toplam = round(sum(a["toplam_kazanc"] for a in araclar), 2)
    toplam_ys_net = round(sum(a["ys_net_kazanc"] for a in araclar), 2)
    # 🆕 Konsinye-ÖZEL YS net kazanç (sadece konsinye araçlarından gelen YS payı)
    konsinye_ys_net = round(sum(a["ys_net_kazanc"] for a in araclar if a.get("konsinye")), 2)
    return {
        "araclar": araclar,
        "toplam_kazanc": toplam,
        "arac_adet": len(araclar),
        # Konsinye özeti — admin için (SADECE konsinye araçlara özel, normal araçlar dahil değil)
        "konsinye_ozet": {
            "toplam_brut": round(toplam_konsinye_brut, 2),
            "toplam_devlet_kesinti": round(toplam_konsinye_devlet, 2),
            "toplam_hakkedis": round(toplam_konsinye_hakkedis, 2),  # toplam araç sahiplerine borç
            "ys_net_kazanc": konsinye_ys_net,  # SADECE konsinye araçlarından YS Auto'nun net payı
            "toplam_ys_net_tum_araclar": toplam_ys_net,  # bilgi amaçlı: tüm araçların toplam YS net (eski değer)
        },
    }


# ========================================================================
# MUHASEBE — Giden/Gelen Faturalar + Aylık Özet
# ========================================================================

class GelenFaturaCreate(BaseModel):
    tarih: str
    tedarikci: str
    fatura_no_dis: Optional[str] = ""
    kategori: str
    aciklama: Optional[str] = ""
    birim: Optional[str] = "Adet"
    miktar: float
    birim_fiyat_net: float  # KDV hariç birim fiyat
    kdv_orani: float = 20.0  # %
    kasa: Optional[str] = "rentcar"


class GelenFaturaUpdate(BaseModel):
    tarih: Optional[str] = None
    tedarikci: Optional[str] = None
    fatura_no_dis: Optional[str] = None
    kategori: Optional[str] = None
    aciklama: Optional[str] = None
    birim: Optional[str] = None
    miktar: Optional[float] = None
    birim_fiyat_net: Optional[float] = None
    kdv_orani: Optional[float] = None
    kasa: Optional[str] = None


class GidenFaturaUpdate(BaseModel):
    """Giden (rezervasyon kaynaklı) fatura için elle düzenleme alanları.
    KDV hariç tutar, KDV ve toplam otomatik hesaplanır."""
    tarih: Optional[str] = None
    aciklama: Optional[str] = None
    plaka: Optional[str] = None
    marka_model: Optional[str] = None
    customer_ad: Optional[str] = None
    birim: Optional[str] = None
    miktar: Optional[float] = None
    birim_fiyat_net: Optional[float] = None
    kdv_orani: Optional[float] = None
    kasa: Optional[str] = None


class AccountingSettings(BaseModel):
    kdv_orani: float = 20.0
    gecici_vergi_orani: float = 20.0
    gunluk_birim_fiyat_net: float = 500.0  # KDV hariç günlük kira birim fiyatı (giden fatura için)


async def _next_invoice_no(yil: int) -> str:
    """2026-0001 formatlı bir sonraki fatura no"""
    last = await db.invoices.find({"yil": yil}).sort("seq", -1).limit(1).to_list(1)
    next_seq = (last[0]["seq"] + 1) if last else 1
    return f"{yil}-{next_seq:04d}", next_seq


async def _create_giden_fatura(reservation: dict) -> Optional[dict]:
    """Bir rezervasyon için giden fatura oluştur veya uzatma için EK fatura ekle.

    KURALLAR:
    - **İLK rezervasyon**: TEK fatura kesilir (kaç gün/ay olursa olsun). Tarih = baslangic_tarihi
      → Yusuf Karagöz 30 gün kiraladığında → 1 fatura
    - **UZATMA**: Yeni günler için EK FATURA. Tarih = bugün (uzatma tarihi)
      → Müşteri 5 gün daha uzatırsa → 1 ek fatura, 5 gün × birim fiyat
    - Idempotent: aynı toplam gün için tekrar çağrılırsa hiçbir şey yapmaz
    - Admin elle düzenlenmiş faturalara (`auto_generated=False`) dokunulmaz
    """
    rid = reservation.get("id")
    if not rid:
        return None

    try:
        bas = parse_iso(reservation.get("baslangic_tarihi"))
        bit = parse_iso(reservation.get("bitis_tarihi"))
    except Exception:
        return None
    if not bas or not bit or bit <= bas:
        return None

    pricing = reservation.get("pricing") or {}
    snap = reservation.get("vehicle_snapshot") or {}

    # Settings: KDV ve günlük birim fiyat
    settings = await db.accounting_settings.find_one({"key": "main"}, {"_id": 0})
    kdv_orani = float((settings or {}).get("kdv_orani", 20.0))
    birim_fiyat_net = float((settings or {}).get("gunluk_birim_fiyat_net", 500.0))

    total_days = max(1, calc_days(bas, bit))
    if birim_fiyat_net <= 0:
        # Fallback: rezervasyon ortalamasından hesapla
        arac_total = float(pricing.get("arac_toplam") or pricing.get("arac_total") or 0)
        if arac_total > 0:
            birim_fiyat_net = round(arac_total / max(total_days, 1), 2)
        else:
            birim_fiyat_net = float(snap.get("gunluk_fiyat") or 0)

    if birim_fiyat_net <= 0:
        return None

    cust = await db.customers.find_one({"id": reservation.get("customer_id")}, {"_id": 0, "ad": 1, "soyad": 1})
    customer_ad = f"{(cust or {}).get('ad', '')} {(cust or {}).get('soyad', '')}".strip() or "—"
    plaka = snap.get("plaka", "")
    marka_model = f"{snap.get('marka', '')} {snap.get('model', '')}".strip()

    # Bu rezervasyonun mevcut faturalarını topla
    existing_invs = await db.invoices.find(
        {"reservation_id": rid, "tip": "giden"}, {"_id": 0}
    ).sort("created_at", 1).to_list(length=None)
    invoiced_days = sum(int(inv.get("miktar") or 0) for inv in existing_invs)

    # Delta: henüz faturalanmamış günler
    delta_days = total_days - invoiced_days

    if delta_days <= 0:
        # Faturalama tamamlanmış veya rezervasyon kısaltılmış → bir şey yapma
        return existing_invs[-1] if existing_invs else None

    kdv_haric = round(birim_fiyat_net * delta_days, 2)
    kdv_t = round(kdv_haric * kdv_orani / 100.0, 2)
    toplam = round(kdv_haric + kdv_t, 2)

    # Tarih: hiç fatura yoksa rezervasyon başlangıcı, varsa BUGÜN (uzatma)
    is_extension = len(existing_invs) > 0
    if is_extension:
        from datetime import datetime as _dt, timezone as _tz
        invoice_dt = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    else:
        invoice_dt = (reservation.get("baslangic_tarihi") or now_iso())[:10]

    try:
        yil = int(invoice_dt[:4])
        ay = int(invoice_dt[5:7])
    except Exception:
        n = datetime.now(timezone.utc)
        yil, ay = n.year, n.month

    no, seq = await _next_invoice_no(yil)
    aciklama = f"{plaka} {marka_model}".strip()
    if is_extension:
        aciklama += f" — Uzatma ({delta_days} gün)"

    doc = {
        "id": str(uuid.uuid4()),
        "no": no,
        "seq": seq,
        "tip": "giden",
        "tarih": invoice_dt,
        "yil": yil,
        "ay": ay,
        "donem_yil": yil,
        "donem_ay": ay,
        "reservation_id": rid,
        "customer_id": reservation.get("customer_id"),
        "customer_ad": customer_ad,
        "vehicle_id": reservation.get("vehicle_id"),
        "plaka": plaka,
        "marka_model": marka_model,
        "aciklama": aciklama,
        "birim": "Gün",
        "miktar": int(delta_days),
        "birim_fiyat_net": birim_fiyat_net,
        "kdv_orani": kdv_orani,
        "kdv_haric_tutar": kdv_haric,
        "kdv_tutar": kdv_t,
        "toplam_tutar": toplam,
        "kasa": "rentcar",
        "durum": "kesildi",
        "auto_generated": True,
        "is_extension": is_extension,
        "created_at": now_iso(),
    }
    await db.invoices.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@api.get("/admin/invoices")
async def admin_list_invoices(
    _: dict = Depends(require_admin),
    tip: Optional[str] = Query(None),  # giden / gelen / None
    yil: Optional[int] = Query(None),
    ay: Optional[int] = Query(None),
):
    q: dict = {}
    if tip:
        q["tip"] = tip
    if yil:
        q["yil"] = yil
    if ay:
        q["ay"] = ay
    docs = await db.invoices.find(q, {"_id": 0}).sort([("yil", -1), ("ay", -1), ("seq", -1)]).to_list(5000)
    return docs


@api.post("/admin/invoices/regenerate")
async def admin_regenerate_invoices(
    _: dict = Depends(require_admin),
    force: bool = Query(False),
):
    """Tüm rezervasyonlar için eksik giden faturaları üret.
    force=True ise mevcut giden faturalar silinip yeniden üretilir (birim fiyat değişikliğinden sonra)."""
    if force:
        await db.invoices.delete_many({"tip": "giden"})
    reservations = await db.reservations.find(
        {"durum": {"$in": ["onaylandi", "aktif", "tamamlandi"]}},
        {"_id": 0},
    ).to_list(10000)
    created = 0
    skipped = 0
    for r in reservations:
        existing = await db.invoices.find_one({"reservation_id": r["id"], "tip": "giden"})
        if existing:
            skipped += 1
            continue
        result = await _create_giden_fatura(r)
        if result:
            created += 1
    return {"created": created, "skipped": skipped, "total": len(reservations), "force": force}


@api.post("/admin/invoices/gelen")
async def admin_create_gelen_fatura(body: GelenFaturaCreate, _: dict = Depends(require_admin)):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih or ""):
        raise HTTPException(400, "Geçersiz tarih (YYYY-MM-DD)")
    if body.miktar <= 0 or body.birim_fiyat_net <= 0:
        raise HTTPException(400, "Miktar ve birim fiyat 0'dan büyük olmalı")
    if not body.tedarikci.strip() or not body.kategori.strip():
        raise HTTPException(400, "Tedarikçi ve kategori zorunlu")
    yil = int(body.tarih[:4])
    ay = int(body.tarih[5:7])
    no, seq = await _next_invoice_no(yil)
    kdv_haric = round(body.miktar * body.birim_fiyat_net, 2)
    kdv_tutar = round(kdv_haric * body.kdv_orani / 100.0, 2)
    toplam = round(kdv_haric + kdv_tutar, 2)
    doc = {
        "id": str(uuid.uuid4()),
        "no": no,
        "seq": seq,
        "tip": "gelen",
        "tarih": body.tarih,
        "yil": yil,
        "ay": ay,
        "tedarikci": body.tedarikci.strip(),
        "fatura_no_dis": (body.fatura_no_dis or "").strip(),
        "kategori": body.kategori.strip(),
        "aciklama": (body.aciklama or "").strip(),
        "birim": body.birim or "Adet",
        "miktar": float(body.miktar),
        "birim_fiyat_net": round(float(body.birim_fiyat_net), 2),
        "kdv_orani": float(body.kdv_orani),
        "kdv_haric_tutar": kdv_haric,
        "kdv_tutar": kdv_tutar,
        "toplam_tutar": toplam,
        "kasa": body.kasa or "rentcar",
        "durum": "kesildi",
        "created_at": now_iso(),
    }
    await db.invoices.insert_one(dict(doc))
    doc.pop("_id", None)
    return doc


@api.put("/admin/invoices/gelen/{iid}")
async def admin_update_gelen_fatura(iid: str, body: GelenFaturaUpdate, _: dict = Depends(require_admin)):
    existing = await db.invoices.find_one({"id": iid, "tip": "gelen"}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Fatura bulunamadı")
    upd: dict = {}
    for f in ("tarih", "tedarikci", "fatura_no_dis", "kategori", "aciklama", "birim", "kasa"):
        v = getattr(body, f, None)
        if v is not None:
            upd[f] = v.strip() if isinstance(v, str) else v
    if body.tarih:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih):
            raise HTTPException(400, "Geçersiz tarih")
        upd["yil"] = int(body.tarih[:4])
        upd["ay"] = int(body.tarih[5:7])
    if body.miktar is not None:
        if body.miktar <= 0:
            raise HTTPException(400, "Miktar 0'dan büyük olmalı")
        upd["miktar"] = float(body.miktar)
    if body.birim_fiyat_net is not None:
        if body.birim_fiyat_net <= 0:
            raise HTTPException(400, "Birim fiyat 0'dan büyük olmalı")
        upd["birim_fiyat_net"] = round(float(body.birim_fiyat_net), 2)
    if body.kdv_orani is not None:
        upd["kdv_orani"] = float(body.kdv_orani)
    # Recalc derived
    merged = {**existing, **upd}
    kdv_haric = round(float(merged["miktar"]) * float(merged["birim_fiyat_net"]), 2)
    kdv_tutar = round(kdv_haric * float(merged["kdv_orani"]) / 100.0, 2)
    upd["kdv_haric_tutar"] = kdv_haric
    upd["kdv_tutar"] = kdv_tutar
    upd["toplam_tutar"] = round(kdv_haric + kdv_tutar, 2)
    await db.invoices.update_one({"id": iid}, {"$set": upd})
    return await db.invoices.find_one({"id": iid}, {"_id": 0})


@api.delete("/admin/invoices/{iid}")
async def admin_delete_invoice(iid: str, _: dict = Depends(require_admin)):
    await db.invoices.delete_one({"id": iid})
    return {"ok": True}


@api.put("/admin/invoices/giden/{iid}")
async def admin_update_giden_fatura(iid: str, body: GidenFaturaUpdate, _: dict = Depends(require_admin)):
    """Giden faturayı düzenle. KDV hariç, KDV ve toplam otomatik yeniden hesaplanır.
    Sadece bu fatura güncellenir; ayarlardaki global KDV/birim fiyat etkilenmez."""
    existing = await db.invoices.find_one({"id": iid, "tip": "giden"}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Giden fatura bulunamadı")
    upd: dict = {}
    for f in ("tarih", "aciklama", "plaka", "marka_model", "customer_ad", "birim", "kasa"):
        v = getattr(body, f, None)
        if v is not None:
            upd[f] = v.strip() if isinstance(v, str) else v
    if body.tarih:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", body.tarih):
            raise HTTPException(400, "Geçersiz tarih (YYYY-MM-DD)")
        upd["yil"] = int(body.tarih[:4])
        upd["ay"] = int(body.tarih[5:7])
    if body.miktar is not None:
        if body.miktar <= 0:
            raise HTTPException(400, "Miktar 0'dan büyük olmalı")
        upd["miktar"] = float(body.miktar)
    if body.birim_fiyat_net is not None:
        if body.birim_fiyat_net <= 0:
            raise HTTPException(400, "Birim fiyat 0'dan büyük olmalı")
        upd["birim_fiyat_net"] = round(float(body.birim_fiyat_net), 2)
    if body.kdv_orani is not None:
        if body.kdv_orani < 0:
            raise HTTPException(400, "KDV oranı negatif olamaz")
        upd["kdv_orani"] = float(body.kdv_orani)
    # Türev tutarları yeniden hesapla
    merged = {**existing, **upd}
    kdv_haric = round(float(merged["miktar"]) * float(merged["birim_fiyat_net"]), 2)
    kdv_tutar = round(kdv_haric * float(merged["kdv_orani"]) / 100.0, 2)
    upd["kdv_haric_tutar"] = kdv_haric
    upd["kdv_tutar"] = kdv_tutar
    upd["toplam_tutar"] = round(kdv_haric + kdv_tutar, 2)
    upd["auto_generated"] = False  # Admin elle düzenledi → otomatik mekanizma dokunmasın
    upd["updated_at"] = now_iso()
    await db.invoices.update_one({"id": iid}, {"$set": upd})
    return await db.invoices.find_one({"id": iid}, {"_id": 0})


@api.get("/admin/accounting/years")
async def admin_accounting_years(_: dict = Depends(require_admin)):
    years = await db.invoices.distinct("yil")
    cur_year = datetime.now(timezone.utc).year
    if cur_year not in years:
        years.append(cur_year)
    years = sorted([int(y) for y in years if y], reverse=True)
    return years


@api.get("/admin/accounting/monthly")
async def admin_accounting_monthly(
    _: dict = Depends(require_admin),
    yil: int = Query(...),
):
    """12 aylık özet tablosu."""
    pipeline = [
        {"$match": {"yil": yil}},
        {"$group": {
            "_id": {"ay": "$ay", "tip": "$tip"},
            "kdv_haric": {"$sum": "$kdv_haric_tutar"},
            "kdv": {"$sum": "$kdv_tutar"},
            "toplam": {"$sum": "$toplam_tutar"},
        }},
    ]
    rows = await db.invoices.aggregate(pipeline).to_list(100)
    aylar = []
    for ay in range(1, 13):
        gelir = next((r for r in rows if r["_id"]["ay"] == ay and r["_id"]["tip"] == "giden"), None)
        gider = next((r for r in rows if r["_id"]["ay"] == ay and r["_id"]["tip"] == "gelen"), None)
        g_haric = round(float(gelir["kdv_haric"]) if gelir else 0, 2)
        g_kdv = round(float(gelir["kdv"]) if gelir else 0, 2)
        e_haric = round(float(gider["kdv_haric"]) if gider else 0, 2)
        e_kdv = round(float(gider["kdv"]) if gider else 0, 2)
        odenecek_kdv = round(g_kdv - e_kdv, 2)
        net_kar = round(g_haric - e_haric, 2)
        aylar.append({
            "ay": ay,
            "ay_adi": ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"][ay - 1],
            "gelir": g_haric,
            "gider": e_haric,
            "hesaplanan_kdv": g_kdv,
            "indirilecek_kdv": e_kdv,
            "odenecek_kdv": odenecek_kdv,
            "net_kar": net_kar,
        })
    # Yıl toplamı
    toplam_gelir = round(sum(a["gelir"] for a in aylar), 2)
    toplam_gider = round(sum(a["gider"] for a in aylar), 2)
    toplam_hesaplanan_kdv = round(sum(a["hesaplanan_kdv"] for a in aylar), 2)
    toplam_indirilecek_kdv = round(sum(a["indirilecek_kdv"] for a in aylar), 2)
    toplam_odenecek_kdv = round(toplam_hesaplanan_kdv - toplam_indirilecek_kdv, 2)
    toplam_net_kar = round(toplam_gelir - toplam_gider, 2)

    return {
        "yil": yil,
        "aylar": aylar,
        "toplam_gelir": toplam_gelir,
        "toplam_gider": toplam_gider,
        "toplam_hesaplanan_kdv": toplam_hesaplanan_kdv,
        "toplam_indirilecek_kdv": toplam_indirilecek_kdv,
        "toplam_odenecek_kdv": toplam_odenecek_kdv,
        "toplam_net_kar": toplam_net_kar,
    }


@api.get("/admin/accounting/quarterly")
async def admin_accounting_quarterly(
    _: dict = Depends(require_admin),
    yil: int = Query(...),
):
    """Geçici Vergi (3 aylık) hesaplaması.
    Türkiye'de şahıs şirketleri için 2022 sonrası 3 dönem (Q1: Ocak-Mart, Q2: Nisan-Haziran, Q3: Temmuz-Eylül) geçerlidir.
    Q4 (Ekim-Aralık) gösterilir ama 'bilgi amaçlı'dır.
    Kümülatif hesap: Her dönem = (Yıl başından dönem sonuna kadar net kar) × oran - önceki dönemlerde ödenen.
    """
    pipeline = [
        {"$match": {"yil": yil}},
        {"$group": {
            "_id": {"ay": "$ay", "tip": "$tip"},
            "kdv_haric": {"$sum": "$kdv_haric_tutar"},
            "kdv": {"$sum": "$kdv_tutar"},
        }},
    ]
    rows = await db.invoices.aggregate(pipeline).to_list(100)

    # Ayarlar (geçici vergi oranı)
    sett = await db.accounting_settings.find_one({"key": "main"}, {"_id": 0})
    oran = float((sett or {}).get("gecici_vergi_orani", 20.0)) / 100.0

    # Aylık ayrıştır
    def gelir_for(ay):
        r = next((x for x in rows if x["_id"]["ay"] == ay and x["_id"]["tip"] == "giden"), None)
        return round(float(r["kdv_haric"]) if r else 0, 2)

    def gider_for(ay):
        r = next((x for x in rows if x["_id"]["ay"] == ay and x["_id"]["tip"] == "gelen"), None)
        return round(float(r["kdv_haric"]) if r else 0, 2)

    quarters = [
        {"key": "Q1", "ad": "1. Dönem (Oca-Mar)", "aylar": [1, 2, 3]},
        {"key": "Q2", "ad": "2. Dönem (Nis-Haz)", "aylar": [4, 5, 6]},
        {"key": "Q3", "ad": "3. Dönem (Tem-Eyl)", "aylar": [7, 8, 9]},
        {"key": "Q4", "ad": "4. Dönem (Eki-Ara)", "aylar": [10, 11, 12], "info": "2022'den itibaren 4. dönem kaldırıldı (yıllık beyan)."},
    ]

    result = []
    kumulatif_gelir = 0.0
    kumulatif_gider = 0.0
    onceki_donemlerin_vergisi = 0.0
    for q in quarters:
        donem_gelir = round(sum(gelir_for(ay) for ay in q["aylar"]), 2)
        donem_gider = round(sum(gider_for(ay) for ay in q["aylar"]), 2)
        donem_net = round(donem_gelir - donem_gider, 2)
        kumulatif_gelir = round(kumulatif_gelir + donem_gelir, 2)
        kumulatif_gider = round(kumulatif_gider + donem_gider, 2)
        kumulatif_net = round(kumulatif_gelir - kumulatif_gider, 2)
        # Geçici vergi sadece pozitif kar üzerinden hesaplanır
        kumulatif_vergi = round(max(kumulatif_net, 0) * oran, 2)
        donem_odenecek = round(max(kumulatif_vergi - onceki_donemlerin_vergisi, 0), 2)
        onceki_donemlerin_vergisi = kumulatif_vergi
        result.append({
            "key": q["key"],
            "ad": q["ad"],
            "aylar": q["aylar"],
            "donem_gelir": donem_gelir,
            "donem_gider": donem_gider,
            "donem_net_kar": donem_net,
            "kumulatif_gelir": kumulatif_gelir,
            "kumulatif_gider": kumulatif_gider,
            "kumulatif_net_kar": kumulatif_net,
            "kumulatif_vergi": kumulatif_vergi,
            "odenecek_vergi": donem_odenecek,
            "info": q.get("info"),
        })

    return {
        "yil": yil,
        "oran": round(oran * 100, 2),
        "donemler": result,
    }


@api.get("/admin/accounting/annual")
async def admin_accounting_annual(_: dict = Depends(require_admin)):
    """Tüm yıllar için özet (gelir, gider, net kar, KDV, geçici vergi tahmini)."""
    pipeline = [
        {"$group": {
            "_id": {"yil": "$yil", "tip": "$tip"},
            "kdv_haric": {"$sum": "$kdv_haric_tutar"},
            "kdv": {"$sum": "$kdv_tutar"},
        }},
    ]
    rows = await db.invoices.aggregate(pipeline).to_list(500)

    sett = await db.accounting_settings.find_one({"key": "main"}, {"_id": 0})
    oran = float((sett or {}).get("gecici_vergi_orani", 20.0)) / 100.0

    years_set = sorted({int(r["_id"]["yil"]) for r in rows if r["_id"].get("yil")}, reverse=True)
    out = []
    for y in years_set:
        gelir = next((r for r in rows if r["_id"]["yil"] == y and r["_id"]["tip"] == "giden"), None)
        gider = next((r for r in rows if r["_id"]["yil"] == y and r["_id"]["tip"] == "gelen"), None)
        g_haric = round(float(gelir["kdv_haric"]) if gelir else 0, 2)
        g_kdv = round(float(gelir["kdv"]) if gelir else 0, 2)
        e_haric = round(float(gider["kdv_haric"]) if gider else 0, 2)
        e_kdv = round(float(gider["kdv"]) if gider else 0, 2)
        net = round(g_haric - e_haric, 2)
        odenecek_kdv = round(g_kdv - e_kdv, 2)
        yillik_vergi = round(max(net, 0) * oran, 2)
        out.append({
            "yil": y,
            "gelir": g_haric,
            "gider": e_haric,
            "hesaplanan_kdv": g_kdv,
            "indirilecek_kdv": e_kdv,
            "odenecek_kdv": odenecek_kdv,
            "net_kar": net,
            "tahmini_yillik_vergi": yillik_vergi,
        })
    # Tüm yılların toplamı
    toplam = {
        "gelir": round(sum(r["gelir"] for r in out), 2),
        "gider": round(sum(r["gider"] for r in out), 2),
        "net_kar": round(sum(r["net_kar"] for r in out), 2),
        "odenecek_kdv": round(sum(r["odenecek_kdv"] for r in out), 2),
        "tahmini_yillik_vergi": round(sum(r["tahmini_yillik_vergi"] for r in out), 2),
    }
    return {
        "oran": round(oran * 100, 2),
        "yillar": out,
        "toplam": toplam,
    }


@api.get("/admin/accounting/settings")
async def admin_get_accounting_settings(_: dict = Depends(require_admin)):
    doc = await db.accounting_settings.find_one({"key": "main"}, {"_id": 0})
    if not doc:
        doc = {"key": "main", "kdv_orani": 20.0, "gecici_vergi_orani": 20.0, "gunluk_birim_fiyat_net": 500.0}
        await db.accounting_settings.insert_one(dict(doc))
    return {
        "kdv_orani": float(doc.get("kdv_orani", 20.0)),
        "gecici_vergi_orani": float(doc.get("gecici_vergi_orani", 20.0)),
        "gunluk_birim_fiyat_net": float(doc.get("gunluk_birim_fiyat_net", 500.0)),
    }


@api.put("/admin/accounting/settings")
async def admin_update_accounting_settings(body: AccountingSettings, _: dict = Depends(require_admin)):
    if body.kdv_orani < 0 or body.kdv_orani > 100:
        raise HTTPException(400, "KDV oranı 0-100 arasında olmalı")
    if body.gecici_vergi_orani < 0 or body.gecici_vergi_orani > 100:
        raise HTTPException(400, "Geçici vergi oranı 0-100 arasında olmalı")
    if body.gunluk_birim_fiyat_net < 0:
        raise HTTPException(400, "Günlük birim fiyat negatif olamaz")
    await db.accounting_settings.update_one(
        {"key": "main"},
        {"$set": {
            "key": "main",
            "kdv_orani": body.kdv_orani,
            "gecici_vergi_orani": body.gecici_vergi_orani,
            "gunluk_birim_fiyat_net": body.gunluk_birim_fiyat_net,
        }},
        upsert=True,
    )
    return {
        "kdv_orani": body.kdv_orani,
        "gecici_vergi_orani": body.gecici_vergi_orani,
        "gunluk_birim_fiyat_net": body.gunluk_birim_fiyat_net,
    }

# ==================== KONSİNYE — Hesaplama Helper ====================
DEVLET_KESINTI_GUNLUK = 100.0  # Sabit devlet kesintisi (TL/gün), ileride ayarlardan değişebilir

async def calculate_konsinye_earning_for_reservation(rez: dict, vehicle: Optional[dict] = None) -> Optional[dict]:
    """Bir rezervasyon için konsinye sahibine düşen hak ediş tutarını hesaplar.
    Sadece konsinye araçlar için döner, normal araçlar için None.

    🚀 PERFORMANS: vehicle parametresi geçilirse DB sorgusu yapılmaz.

    Formül:
      Brüt = arac_toplam (orijinal) + uzatma_arac_tutar (varsa) + ek_km_satin_alim_tutar
      Devlet Kesintisi = 100₺ × toplam_gun
      Net = max(0, Brüt - Devlet Kesintisi)
      Sahibin Hak Edişi = Net × pay_yuzde / 100

    Ek hizmetler (yıkama, çocuk koltuğu, doluluk vb.) DAHIL DEĞİLDİR — YS Auto'da kalır.
    """
    vid = rez.get("vehicle_id")
    if not vid:
        return None
    v = vehicle if vehicle is not None else await db.vehicles.find_one({"id": vid}, {"_id": 0})
    if not v or not v.get("konsinye"):
        return None
    pay_yuzde = float(v.get("konsinye_pay_yuzde") or 70.0)
    pay_yuzde = max(0.0, min(100.0, pay_yuzde))

    # Gün sayısı: rezervasyonda explicit alan yoksa tarihlerden hesapla
    gun = int(rez.get("gun_sayisi") or rez.get("toplam_gun") or 0)
    if not gun and rez.get("baslangic_tarihi") and rez.get("bitis_tarihi"):
        try:
            bd = datetime.fromisoformat(rez["baslangic_tarihi"].replace("Z", "+00:00"))
            ed = datetime.fromisoformat(rez["bitis_tarihi"].replace("Z", "+00:00"))
            gun = max(1, math.ceil((ed - bd).total_seconds() / 86400))
        except Exception:
            gun = 1

    # ✨ Pricing rezervasyonun "pricing" alt-alanında ya da kök seviyesinde olabilir
    pricing = rez.get("pricing") or {}
    
    # 🚨 PRICING SENKRONİZASYON KONTROLÜ
    pricing_gun = int(pricing.get("gun_sayisi") or 0)
    pricing_synced = bool(pricing_gun) and pricing_gun == gun

    # ✨ HİZMET KAYNAĞI ÖNCELİĞİ: secilen_hizmetler (rezervasyon root) > pricing.hizmetler > ekstra_hizmetler
    hiz_root = rez.get("secilen_hizmetler") or []
    hiz_pricing = pricing.get("hizmetler") or []
    hiz_extra = rez.get("ekstra_hizmetler") or []
    hizmet_listesi = hiz_root if len(hiz_root) > 0 else (hiz_pricing if len(hiz_pricing) > 0 else hiz_extra)
    hizmetler_toplam_dogru = 0.0
    for h in hizmet_listesi:
        tip = str(h.get("tip") or "tek_seferlik").lower()
        fiyat = float(h.get("fiyat") or h.get("birim_fiyat") or 0)
        tutar_field = float(h.get("tutar") or 0)
        adet = int(h.get("adet") or 1)
        if tip == "gunluk":
            hizmetler_toplam_dogru += fiyat * adet * max(1, gun)
        else:
            hizmetler_toplam_dogru += tutar_field if tutar_field else (fiyat * adet)

    # Ek KM satın alma — alan adları sürüm boyunca değişmiş olabilir
    ek_km_satin_alim_tutar = float(
        rez.get("ek_km_satin_alim_tutar")
        or rez.get("ek_km_tutar")
        or rez.get("km_asim_tutar")
        or 0
    )

    # Pricing.hizmetler boş ama secilen_hizmetler dolu ise pricing_synced false
    if pricing_synced and len(hiz_pricing) == 0 and len(hiz_root) > 0 and hizmetler_toplam_dogru > 0:
        pricing_synced = False

    if pricing_synced:
        arac_toplam = float(
            pricing.get("arac_toplam")
            or pricing.get("arac_total")
            or rez.get("arac_toplam")
            or 0
        )
    else:
        # ⚠️ Pricing eski/uyumsuz — toplam_tutar - hizmetler - ek_km'den türet
        toplam_tutar_rez = float(rez.get("toplam_tutar") or 0)
        arac_toplam = max(0.0, round(toplam_tutar_rez - hizmetler_toplam_dogru - ek_km_satin_alim_tutar, 2))
        if arac_toplam <= 0:
            gf = float(pricing.get("gunluk_fiyat") or pricing.get("gunluk_fiyat_baz") or rez.get("gunluk_birim_fiyat") or 0)
            arac_toplam = round(gf * max(1, gun), 2)

    # 🆕 İndirim bilgileri — şeffaflık için (eski pricing'ten alınsa da bilgi amaçlı)
    arac_liste_fiyat = float(pricing.get("arac_alt_toplam") or arac_toplam)
    if not pricing_synced:
        # Liste fiyatı için günlük baz × gun fallback
        gfb = float(pricing.get("gunluk_fiyat_baz") or pricing.get("gunluk_fiyat") or 0)
        if gfb:
            arac_liste_fiyat = round(gfb * max(1, gun), 2)
    sure_indirim_tutar = float(pricing.get("sure_indirim_tutar") or 0)
    sure_indirim_yuzde = float(pricing.get("sure_indirim_yuzde") or 0)
    admin_iskonto_yuzde = float(pricing.get("iskonto_yuzde") or 0)
    admin_iskonto_tutar = float(pricing.get("iskonto_tutar") or 0)
    # Admin iskontosu sahibi etkilemez (YS Auto karşılar) — sadece bilgi amaçlı gösterilir
    # Uzatma — uzatmalar listesi varsa toplamlarını topla (sadece araç kısmı)
    uzatma_arac = 0.0
    for u in (rez.get("uzatmalar") or []):
        # ek_tutar = ek_arac + services + ek_km. Sadece arac payı için ek_arac kullanılır
        # Fallback: ek_tutar - ek_hizmet_tutar - ek_km_tutar
        ekt = float(u.get("ek_tutar") or 0)
        ekhz = float(u.get("ek_hizmet_tutar") or 0)
        ekkm = float(u.get("ek_km_tutar") or 0)
        uzatma_arac += max(0.0, ekt - ekhz - ekkm)

    brut = round(arac_toplam + uzatma_arac + ek_km_satin_alim_tutar, 2)
    devlet_kesinti = round(DEVLET_KESINTI_GUNLUK * gun, 2)
    net = max(0.0, round(brut - devlet_kesinti, 2))
    sahibin_hakkedisi = round(net * pay_yuzde / 100.0, 2)
    ys_komisyonu = round(net - sahibin_hakkedisi, 2)

    return {
        "vehicle_id": vid,
        "konsinye_sahibi_id": v.get("konsinye_sahibi_id"),
        "gun_sayisi": gun,
        "pay_yuzde": pay_yuzde,
        # İndirim şeffaflığı (sahibe gösterilir)
        "arac_liste_fiyat": arac_liste_fiyat,
        "sure_indirim_yuzde": sure_indirim_yuzde,
        "sure_indirim_tutar": sure_indirim_tutar,
        "admin_iskonto_yuzde": admin_iskonto_yuzde,
        "admin_iskonto_tutar": admin_iskonto_tutar,
        "arac_toplam": arac_toplam,
        "uzatma_arac": round(uzatma_arac, 2),
        "ek_km_satin_alim_tutar": ek_km_satin_alim_tutar,
        "brut": brut,
        "devlet_kesinti": devlet_kesinti,
        "net": net,
        "sahibin_hakkedisi": sahibin_hakkedisi,
        "ys_komisyonu": ys_komisyonu,
    }


def _anonim_musteri_id(customer_id: Optional[str]) -> str:
    """Müşteri ID'sini anonim bir koda çevirir (örn. '#a1b2')."""
    if not customer_id:
        return "—"
    h = hashlib.md5(str(customer_id).encode()).hexdigest()
    return f"#{h[:4].upper()}"


def require_konsinye(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "konsinye":
        raise HTTPException(403, "Yetkisiz erişim — konsinye hesabı gerekir")
    return user


def require_admin_or_konsinye(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") not in ("admin", "konsinye"):
        raise HTTPException(403, "Yetkisiz erişim")
    return user


# ==================== ADMIN: Konsinyatör (Araç Sahibi) Yönetimi ====================
@api.get("/admin/konsinyatorler")
async def admin_list_konsinyatorler(user: dict = Depends(require_admin)):
    items = await db.konsinyatorler.find({"$or": [{"tenant_id": tenant_id_of(user)}, {"tenant_id": {"$exists": False}}]} if not is_super_admin(user) else {}, {"_id": 0}).sort([("ad", 1)]).to_list(500)
    # Her konsinyatör için araç sayısı + toplam hak ediş özeti ekle
    out = []
    for k in items:
        v_count = await db.vehicles.count_documents({"konsinye_sahibi_id": k["id"]})
        out.append({**k, "arac_sayisi": v_count})
    return out


@api.post("/admin/konsinyatorler")
async def admin_create_konsinyator(body: KonsinyatorIn, user: dict = Depends(require_admin)):
    tc = normalize_tc(body.tc)
    if len(tc) != 11:
        raise HTTPException(400, "TC Kimlik 11 haneli olmalı")
    if not body.ad.strip() or not body.soyad.strip():
        raise HTTPException(400, "Ad ve soyad zorunlu")
    if await db.konsinyatorler.find_one({"tc_norm": tc}):
        raise HTTPException(400, "Bu TC ile zaten bir konsinye sahibi kayıtlı")
    if await db.admins.find_one({"tc_norm": tc}):
        raise HTTPException(400, "Bu TC ile bir yönetici kayıtlı")
    if await db.customers.find_one({"tc_norm": tc}):
        raise HTTPException(400, "Bu TC ile bir müşteri kayıtlı — konsinye sahibi eklenemez")
    pay = max(0.0, min(100.0, float(body.varsayilan_pay_yuzde or 70.0)))
    doc = {
        "id": str(uuid.uuid4()),
        "ad": body.ad.strip(),
        "soyad": body.soyad.strip(),
        "tc_norm": tc,
        "telefon": (body.telefon or "").strip() or None,
        "email": (body.email or "").strip() or None,
        "iban": (body.iban or "").strip() or None,
        "banka_hesap_sahibi": (body.banka_hesap_sahibi or "").strip() or None,
        "varsayilan_pay_yuzde": pay,
        "notlar": body.notlar,
        "aktif": True,
        "created_at": now_iso(),
        **tenant_stamp(user),
    }
    await db.konsinyatorler.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.put("/admin/konsinyatorler/{kid}")
async def admin_update_konsinyator(kid: str, body: KonsinyatorUpdate, _: dict = Depends(require_admin)):
    upd = body.dict(exclude_unset=True)
    if "tc" in upd:
        tc = normalize_tc(upd.pop("tc"))
        if len(tc) != 11:
            raise HTTPException(400, "TC Kimlik 11 haneli olmalı")
        # Çakışma kontrolü
        existing = await db.konsinyatorler.find_one({"tc_norm": tc, "id": {"$ne": kid}})
        if existing:
            raise HTTPException(400, "Bu TC ile başka bir konsinye sahibi var")
        upd["tc_norm"] = tc
    if "varsayilan_pay_yuzde" in upd and upd["varsayilan_pay_yuzde"] is not None:
        upd["varsayilan_pay_yuzde"] = max(0.0, min(100.0, float(upd["varsayilan_pay_yuzde"])))
    if upd:
        await db.konsinyatorler.update_one({"id": kid}, {"$set": upd})
    k = await db.konsinyatorler.find_one({"id": kid}, {"_id": 0})
    if not k:
        raise HTTPException(404, "Konsinye sahibi bulunamadı")
    return k


@api.delete("/admin/konsinyatorler/{kid}")
async def admin_delete_konsinyator(kid: str, _: dict = Depends(require_admin)):
    # Bağlı araç var mı kontrol et — varsa silme, deaktive et
    vc = await db.vehicles.count_documents({"konsinye_sahibi_id": kid})
    if vc > 0:
        await db.konsinyatorler.update_one({"id": kid}, {"$set": {"aktif": False}})
        return {"ok": True, "deactivated": True, "message": f"{vc} araç bağlı — pasifleştirildi (silinmedi)"}
    res = await db.konsinyatorler.delete_one({"id": kid})
    return {"ok": True, "deleted": res.deleted_count}


# ==================== ADMIN: Araç Bakım Giderleri ====================
@api.get("/admin/arac-bakim-giderleri")
async def admin_list_bakim_giderleri(vehicle_id: Optional[str] = None, konsinye_sahibi_id: Optional[str] = None, _: dict = Depends(require_admin)):
    q: dict = {}
    if vehicle_id:
        q["vehicle_id"] = vehicle_id
    if konsinye_sahibi_id:
        q["konsinye_sahibi_id"] = konsinye_sahibi_id
    items = await db.arac_bakim_giderleri.find(q, {"_id": 0}).sort([("tarih", -1)]).to_list(500)
    return items


@api.post("/admin/arac-bakim-giderleri")
async def admin_create_bakim_gideri(body: BakimGiderIn, user: dict = Depends(require_admin)):
    v = await db.vehicles.find_one({"id": body.vehicle_id}, {"_id": 0})
    if not v:
        raise HTTPException(404, "Araç bulunamadı")
    if not v.get("konsinye"):
        raise HTTPException(400, "Bu araç konsinye değil — bakım gideri sadece konsinye araçlar için kayıt edilir")
    doc = {
        "id": str(uuid.uuid4()),
        "vehicle_id": body.vehicle_id,
        "konsinye_sahibi_id": v.get("konsinye_sahibi_id"),
        "tutar": round(float(body.tutar or 0), 2),
        "aciklama": (body.aciklama or "").strip(),
        "tarih": body.tarih,
        "created_at": now_iso(),
        **tenant_stamp(user),
    }
    await db.arac_bakim_giderleri.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.delete("/admin/arac-bakim-giderleri/{gid}")
async def admin_delete_bakim_gideri(gid: str, _: dict = Depends(require_admin)):
    res = await db.arac_bakim_giderleri.delete_one({"id": gid})
    return {"ok": True, "deleted": res.deleted_count}


# ==================== ADMIN: Konsinye Hak Ediş Ödemeleri ====================
@api.get("/admin/konsinye-odemeler")
async def admin_list_konsinye_odemeler(konsinye_sahibi_id: Optional[str] = None, _: dict = Depends(require_admin)):
    q: dict = {}
    if konsinye_sahibi_id:
        q["konsinye_sahibi_id"] = konsinye_sahibi_id
    items = await db.konsinye_odemeler.find(q, {"_id": 0}).sort([("donem", -1)]).to_list(500)
    return items


@api.post("/admin/konsinye-odemeler")
async def admin_create_konsinye_odeme(body: KonsinyeOdemeIn, user: dict = Depends(require_admin)):
    k = await db.konsinyatorler.find_one({"id": body.konsinye_sahibi_id}, {"_id": 0})
    if not k:
        raise HTTPException(404, "Konsinye sahibi bulunamadı")
    doc = {
        "id": str(uuid.uuid4()),
        "konsinye_sahibi_id": body.konsinye_sahibi_id,
        "donem": body.donem,
        "tutar": round(float(body.tutar or 0), 2),
        "odeme_tarihi": body.odeme_tarihi or now_iso(),
        "aciklama": body.aciklama,
        "odendi": True,
        "created_at": now_iso(),
        **tenant_stamp(user),
    }
    await db.konsinye_odemeler.insert_one(doc)
    doc.pop("_id", None)
    return doc


@api.delete("/admin/konsinye-odemeler/{oid}")
async def admin_delete_konsinye_odeme(oid: str, _: dict = Depends(require_admin)):
    res = await db.konsinye_odemeler.delete_one({"id": oid})
    return {"ok": True, "deleted": res.deleted_count}


# ==================== ADMIN: Konsinye Kazanç Raporu (özet) ====================
@api.get("/admin/konsinye-rapor")
async def admin_konsinye_rapor(konsinye_sahibi_id: str, _: dict = Depends(require_admin)):
    """Bir konsinye sahibi için detaylı kazanç raporu döner — admin gözüyle (tüm bilgiler açık)."""
    return await _build_konsinye_report(konsinye_sahibi_id, mask_customer=False)


# ==================== KONSİNYE (Araç Sahibi) ENDPOINT'leri ====================
@api.get("/konsinye/me")
async def konsinye_me(user: dict = Depends(require_konsinye)):
    return {
        "id": user["id"],
        "ad": user["ad"],
        "soyad": user["soyad"],
        "telefon": user.get("telefon"),
        "email": user.get("email"),
        "iban": user.get("iban"),
        "varsayilan_pay_yuzde": user.get("varsayilan_pay_yuzde"),
    }


@api.get("/konsinye/vehicles")
async def konsinye_my_vehicles(user: dict = Depends(require_konsinye)):
    items = await db.vehicles.find({"konsinye_sahibi_id": user["id"]}, {"_id": 0}).sort([("siralama", 1), ("plaka", 1)]).to_list(200)
    return items


@api.get("/konsinye/reservations")
async def konsinye_my_reservations(user: dict = Depends(require_konsinye)):
    """Sadece konsinye sahibinin araçlarındaki rezervasyonlar — müşteri bilgileri anonim."""
    my_vehicle_ids = [v["id"] async for v in db.vehicles.find({"konsinye_sahibi_id": user["id"]}, {"id": 1})]
    if not my_vehicle_ids:
        return []
    rez = await db.reservations.find({"vehicle_id": {"$in": my_vehicle_ids}}, {"_id": 0}).sort([("baslangic_tarihi", -1)]).to_list(1000)
    # 🚀 PERFORMANS — araç bilgilerini tek seferde çek, lookup için map yap
    v_docs = await db.vehicles.find({"id": {"$in": my_vehicle_ids}}, {"_id": 0}).to_list(200)
    v_map = {v["id"]: v for v in v_docs}
    # Müşteri bilgilerini anonim ID ile değiştir
    out = []
    for r in rez:
        v = v_map.get(r.get("vehicle_id"))
        earn = await calculate_konsinye_earning_for_reservation(r, vehicle=v)
        # Frontend için sadece gerekli alanları çıkart
        v_slim = None
        if v:
            v_slim = {"plaka": v.get("plaka"), "marka": v.get("marka"), "model": v.get("model"), "yil": v.get("yil")}
        out.append({
            "id": r["id"],
            "musteri_kodu": _anonim_musteri_id(r.get("customer_id")),
            "arac": v_slim,
            "baslangic_tarihi": r.get("baslangic_tarihi"),
            "bitis_tarihi": r.get("bitis_tarihi"),
            "gun_sayisi": r.get("gun_sayisi") or r.get("toplam_gun"),
            "durum": r.get("durum"),
            "kazanc": earn,  # konsinye sahibinin bu rez'den hak edişi
        })
    return out


async def _build_konsinye_report(konsinye_sahibi_id: str, mask_customer: bool = True) -> dict:
    """Konsinye sahibi için kapsamlı kazanç raporu döner.
    mask_customer=True ise müşteri kodu kullanılır (KVKK).
    Tüm rezervasyonlardaki hak ediş + bakım giderleri + ödemeler özet halinde."""
    # Konsinye sahibinin araçları
    my_vehicles = await db.vehicles.find({"konsinye_sahibi_id": konsinye_sahibi_id}, {"_id": 0}).to_list(200)
    my_vehicle_ids = [v["id"] for v in my_vehicles]

    # Tüm rezervasyonlar (iptal hariç)
    rez_list = await db.reservations.find(
        {"vehicle_id": {"$in": my_vehicle_ids}, "durum": {"$ne": "iptal"}},
        {"_id": 0},
    ).sort([("baslangic_tarihi", -1)]).to_list(2000)

    # Tüm bakım giderleri
    bakim_list = await db.arac_bakim_giderleri.find(
        {"konsinye_sahibi_id": konsinye_sahibi_id}, {"_id": 0},
    ).sort([("tarih", -1)]).to_list(1000)

    # Tüm ödemeler
    odemeler = await db.konsinye_odemeler.find(
        {"konsinye_sahibi_id": konsinye_sahibi_id}, {"_id": 0},
    ).sort([("donem", -1)]).to_list(500)

    # Hesaplama: aylık + yıllık özet + her rezervasyon için detay
    detayli_rez = []
    aylik_kazanc: dict = {}  # 'YYYY-MM' -> {brut, net, hakkedis, gun}
    yillik_kazanc: dict = {}  # 'YYYY' -> {}
    toplam_brut = 0.0
    toplam_devlet = 0.0
    toplam_hakkedis = 0.0
    toplam_gun = 0

    # 🚀 PERFORMANS — vehicle map'i kullanarak DB sorgusu olmadan hızlı hesap
    v_map = {v["id"]: v for v in my_vehicles}
    for r in rez_list:
        earn = await calculate_konsinye_earning_for_reservation(r, vehicle=v_map.get(r.get("vehicle_id")))
        if not earn:
            continue
        # Hangi tarihe ait? başlangıç tarihine göre grupla
        bd_str = r.get("baslangic_tarihi") or now_iso()
        try:
            bd = datetime.fromisoformat(bd_str.replace("Z", "+00:00"))
        except Exception:
            bd = datetime.utcnow()
        ay_key = bd.strftime("%Y-%m")
        yil_key = bd.strftime("%Y")
        aylik_kazanc.setdefault(ay_key, {"brut": 0.0, "net": 0.0, "hakkedis": 0.0, "gun": 0, "rez_sayisi": 0})
        aylik_kazanc[ay_key]["brut"] += earn["brut"]
        aylik_kazanc[ay_key]["net"] += earn["net"]
        aylik_kazanc[ay_key]["hakkedis"] += earn["sahibin_hakkedisi"]
        aylik_kazanc[ay_key]["gun"] += earn["gun_sayisi"]
        aylik_kazanc[ay_key]["rez_sayisi"] += 1
        yillik_kazanc.setdefault(yil_key, {"brut": 0.0, "net": 0.0, "hakkedis": 0.0, "gun": 0, "rez_sayisi": 0})
        yillik_kazanc[yil_key]["brut"] += earn["brut"]
        yillik_kazanc[yil_key]["net"] += earn["net"]
        yillik_kazanc[yil_key]["hakkedis"] += earn["sahibin_hakkedisi"]
        yillik_kazanc[yil_key]["gun"] += earn["gun_sayisi"]
        yillik_kazanc[yil_key]["rez_sayisi"] += 1
        toplam_brut += earn["brut"]
        toplam_devlet += earn["devlet_kesinti"]
        toplam_hakkedis += earn["sahibin_hakkedisi"]
        toplam_gun += earn["gun_sayisi"]
        v = next((vv for vv in my_vehicles if vv["id"] == r["vehicle_id"]), None)
        detayli_rez.append({
            "id": r["id"],
            "musteri": _anonim_musteri_id(r.get("customer_id")) if mask_customer else f"{(await db.customers.find_one({'id': r.get('customer_id')}, {'_id': 0, 'ad': 1, 'soyad': 1, 'telefon': 1}) or {}).get('ad', '')} {(await db.customers.find_one({'id': r.get('customer_id')}, {'_id': 0, 'ad': 1, 'soyad': 1}) or {}).get('soyad', '')}".strip() or _anonim_musteri_id(r.get("customer_id")),
            "arac_plaka": v["plaka"] if v else "—",
            "arac_marka_model": f"{v.get('marka', '')} {v.get('model', '')}" if v else "—",
            "baslangic_tarihi": r.get("baslangic_tarihi"),
            "bitis_tarihi": r.get("bitis_tarihi"),
            "durum": r.get("durum"),
            "kazanc": earn,
        })

    # Bakım giderleri toplamı (tüm zamanlar)
    toplam_bakim = round(sum(b.get("tutar", 0) for b in bakim_list), 2)
    # Ödenmiş tutar
    toplam_odenmis = round(sum(o.get("tutar", 0) for o in odemeler if o.get("odendi", True)), 2)
    # Net borç: toplam hakediş - toplam bakım - toplam ödenmiş = borç (pozitif: sahibe borçluyuz; negatif: tahsil edilecek)
    net_borc = round(toplam_hakkedis - toplam_bakim - toplam_odenmis, 2)

    return {
        "aktif_arac_sayisi": len(my_vehicles),
        "toplam_rez_sayisi": len(detayli_rez),
        "toplam_gun": toplam_gun,
        "toplam_brut": round(toplam_brut, 2),
        "toplam_devlet_kesinti": round(toplam_devlet, 2),
        "toplam_hakkedis": round(toplam_hakkedis, 2),
        "toplam_bakim": toplam_bakim,
        "toplam_odenmis": toplam_odenmis,
        "kalan_borc": net_borc,  # > 0 ise sahibe ödeme bekleniyor
        "aylik_kazanc": aylik_kazanc,  # dict YYYY-MM -> summary
        "yillik_kazanc": yillik_kazanc,
        "rezervasyonlar": detayli_rez,
        "bakim_giderleri": bakim_list,
        "odemeler": odemeler,
    }


@api.get("/konsinye/dashboard")
async def konsinye_dashboard(user: dict = Depends(require_konsinye)):
    """Konsinye sahibinin özet dashboard'u — tüm kazanç + bakım + ödeme özet."""
    return await _build_konsinye_report(user["id"], mask_customer=True)


@api.get("/konsinye/bakim-giderleri")
async def konsinye_my_bakim(user: dict = Depends(require_konsinye)):
    items = await db.arac_bakim_giderleri.find({"konsinye_sahibi_id": user["id"]}, {"_id": 0}).sort([("tarih", -1)]).to_list(500)
    return items


@api.get("/konsinye/odemeler")
async def konsinye_my_odemeler(user: dict = Depends(require_konsinye)):
    items = await db.konsinye_odemeler.find({"konsinye_sahibi_id": user["id"]}, {"_id": 0}).sort([("donem", -1)]).to_list(500)
    return items




app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True, allow_origins=["*"],
    allow_methods=["*"], allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown():
    client.close()
