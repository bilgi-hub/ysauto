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

def make_token(user_id: str, role: str) -> str:
    return pyjwt.encode({
        "sub": user_id, "role": role,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES),
    }, JWT_SECRET, algorithm=JWT_ALG)

def normalize_tc(tc: str) -> str:
    return re.sub(r"\D", "", tc or "")[:11]

def normalize_name(s: str) -> str:
    return (s or "").strip().lower()

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
    if not EMERGENT_LLM_KEY:
        return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": ["AI servisi yapılandırılmamış"]}

    # data: prefix'i kaldır
    raw = foto_base64.strip()
    if raw.startswith("data:"):
        comma = raw.find(",")
        if comma > 0:
            raw = raw[comma + 1:]

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    except Exception as e:
        logger.error(f"emergentintegrations import error: {e}")
        return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": [f"AI kütüphanesi yüklenemedi: {e}"]}

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

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"dekont-{uuid.uuid4().hex[:10]}",
        system_message=sys_msg,
    ).with_model("gemini", "gemini-2.5-pro")

    image = ImageContent(image_base64=raw)
    msg = UserMessage(
        text=(
            "Bu banka dekontunu analiz et ve istenen JSON'u dön. "
            f"Beklenen alıcı IBAN: {expected_iban or '(belirtilmemiş)'}\n"
            f"Beklenen alıcı: {expected_recipient_name or '(belirtilmemiş)'}\n"
            f"Beklenen gönderici: {expected_sender_name or '(belirtilmemiş)'}\n"
            f"Beklenen tutar: {expected_amount} TL"
        ),
        file_contents=[image],
    )

    try:
        ai_resp = await chat.send_message(msg)
    except Exception as e:
        logger.error(f"LLM dekont error: {e}")
        return {"valid": False, "fields": {}, "confidence": 0.0, "reasons": [f"AI hatası: {e}"]}

    # JSON extract
    raw_txt = ai_resp.strip() if isinstance(ai_resp, str) else str(ai_resp)
    # Code block temizle
    raw_txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_txt.strip(), flags=re.MULTILINE)
    try:
        parsed = _json.loads(raw_txt)
    except Exception:
        # JSON bulamadık - regex ile substring çek
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

    valid = (
        is_valid_receipt and tarih_ok and tutar_ok and iban_ok and alici_ok and gonderen_ok
        and confidence >= 0.6
    )
    if confidence < 0.6 and is_valid_receipt:
        reasons.append(f"AI güveni düşük ({confidence:.2f})")

    return {
        "valid": valid,
        "fields": fields_report,
        "confidence": confidence,
        "is_valid_receipt": is_valid_receipt,
        "reasons": reasons,
    }


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = pyjwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALG])
    except pyjwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Oturum süresi dolmuş, tekrar giriş yapın")
    role = payload.get("role")
    uid = payload.get("sub")
    if role == "customer":
        c = await db.customers.find_one({"id": uid}, {"_id": 0})
        if not c:
            raise HTTPException(401, "Kullanıcı bulunamadı")
        if c.get("blocked"):
            raise HTTPException(403, c.get("block_reason") or "Hesabınız askıya alınmış. Yetkili ile iletişime geçin.")
        return {"role": "customer", **c}
    elif role == "admin":
        a = await db.admins.find_one({"id": uid}, {"_id": 0, "password_hash": 0})
        if not a:
            raise HTTPException(401, "Yönetici bulunamadı")
        return {"role": "admin", **a}
    raise HTTPException(401, "Geçersiz oturum")

async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Bu işlem için yönetici yetkisi gerekli")
    return user

async def require_customer(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "customer":
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
    If no bracket matches, falls back to vehicle.gunluk_fiyat.
    """
    kademeler = vehicle.get("gunluk_fiyat_kademeleri") or []
    fallback = float(vehicle.get("gunluk_fiyat", 0) or 0)
    if not kademeler:
        return fallback
    for k in sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0)):
        try:
            mg = int(k.get("min_gun", 0) or 0)
            mxg = k.get("max_gun")
            mxg_n = int(mxg) if mxg is not None else 10**9
            price = float(k.get("gunluk_fiyat", fallback) or fallback)
        except Exception:
            continue
        if mg <= days <= mxg_n:
            return price
    return fallback

def matched_price_kademe(vehicle: dict, days: int) -> Optional[dict]:
    """Return the matched price bracket dict for transparency in UI, or None."""
    kademeler = vehicle.get("gunluk_fiyat_kademeleri") or []
    if not kademeler:
        return None
    for k in sorted(kademeler, key=lambda x: int(x.get("min_gun", 0) or 0)):
        try:
            mg = int(k.get("min_gun", 0) or 0)
            mxg = k.get("max_gun")
            mxg_n = int(mxg) if mxg is not None else 10**9
            if mg <= days <= mxg_n:
                return {"min_gun": mg, "max_gun": k.get("max_gun"), "gunluk_fiyat": float(k.get("gunluk_fiyat", 0))}
        except Exception:
            continue
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

async def calc_pricing(vehicle: dict, days: int, services_sel: List[dict] = None, iskonto_yuzde: float = 0.0) -> dict:
    """Compute reservation pricing with discount and services."""
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
    zorunlu_q = {"aktif": True, "zorunlu": True, "$or": [{"arac_ids": {"$exists": False}}, {"arac_ids": {"$size": 0}}, {"arac_ids": vehicle["id"]}]}
    zorunlu_docs = await db.services.find(zorunlu_q, {"_id": 0}).to_list(50)
    if not services_sel:
        services_sel = []
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

async def get_live_vehicle(plaka: str) -> Optional[dict]:
    vs = await fetch_bot_vehicles()
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
    await seed_admin()
    await seed_settings()
    await seed_services()
    await seed_demo()
    await init_vehicle_order()
    # 6 saat hatırlatma background task
    asyncio.create_task(rental_expiry_reminder_loop())
    # Bot-Sync background task (oto müşteri/rezervasyon + KM senkron + motor blokaj)
    asyncio.create_task(bot_sync_loop())


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
                mesaj = f"{marka} {model} ({plaka}) iadenize ~6 saat kaldı. Bitiş: {bit_local}. Süre uzatmak için 'Kiralarım' bölümünden işlem yapabilirsiniz."
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

                    # 3) Aktif/onaylı rezervasyon bul — yoksa oluştur (durum=aktif)
                    reservation = await db.reservations.find_one({
                        "vehicle_id": db_vehicle["id"],
                        "customer_id": customer["id"],
                        "durum": {"$in": ["onaylandi", "aktif"]},
                    }, {"_id": 0})

                    if not reservation:
                        # Sözleşme tarih aralığını parse et
                        try:
                            start_iso = parse_iso(contract_start).isoformat()
                        except Exception:
                            start_iso = now_iso()
                        try:
                            end_iso = parse_iso(contract_end).isoformat()
                        except Exception:
                            end_iso = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                        try:
                            days = max(1, int((parse_iso(end_iso) - parse_iso(start_iso)).total_seconds() // 86400) or 1)
                        except Exception:
                            days = 1
                        paket_km_val = paket_km_for(db_vehicle, days)
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
                            "ek_hizmetler": [],
                            "ek_hizmet_tutari": 0.0,
                            "arac_tutari": float(db_vehicle.get("gunluk_fiyat", 0) or 0) * days,
                            "toplam_tutar": float(db_vehicle.get("gunluk_fiyat", 0) or 0) * days,
                            "odenen_ucret": 0.0,
                            "kalan_odeme": float(db_vehicle.get("gunluk_fiyat", 0) or 0) * days,
                            "odeme_yontemi": "Bot Otomatik",
                            "odeme_durumu": "beklemede",
                            "durum": "aktif",
                            "kaynak": "bot_oto",
                            "telefon": cust_phone,
                            "created_at": now_iso(),
                        }
                        await db.reservations.insert_one(new_res)
                        reservation = new_res
                        logger.info(f"bot-sync: yeni rezervasyon (aktif) oluşturuldu {plaka} → {cust_name}")
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

                    # 50 km uyarısı
                    if kalan <= 50 and kalan > 0 and not reservation.get("km_warning_50_sent"):
                        updates["km_warning_50_sent"] = True
                        await notify_customer(
                            customer["id"],
                            "KM Hakkınız Bitmek Üzere",
                            f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) için kalan {kalan} km. Tükenince motorunuz kitlenecek — Ek KM almak için uygulamadan 'Süre/KM Uzat'.",
                            {"type": "km_warning_50", "reservation_id": reservation["id"], "kalan_km": kalan},
                        )

                    # 0 km motor kilitleme
                    if kalan <= 0 and not reservation.get("motor_kilitli"):
                        ok = await bot_motor_blokaj(plaka, True)
                        updates["motor_kilitli"] = True
                        updates["motor_kilit_tarih"] = now_iso()
                        await notify_customer(
                            customer["id"],
                            "Motor Kilitlendi",
                            f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) — KM hakkınız bitti, motor kilitlendi. Devam etmek için ek KM satın alın, motor otomatik açılacaktır.",
                            {"type": "motor_locked", "reservation_id": reservation["id"]},
                        )
                        logger.info(f"bot-sync: motor kilitlendi {plaka} bot_response={ok}")

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
                            f"{db_vehicle.get('marka','')} {db_vehicle.get('model','')} ({plaka}) — Yeni KM hakkınız aktif, motorunuz açıldı. İyi yolculuklar!",
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
    return TokenOut(token=make_token(cust["id"], "customer"), role="customer", user={
        "id": cust["id"], "ad": cust["ad"], "soyad": cust["soyad"],
        "telefon": cust.get("telefon"), "email": cust.get("email"),
    })

@api.post("/auth/admin/login", response_model=TokenOut)
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
    return TokenOut(token=make_token(a["id"], "admin"), role="admin", user={
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
        return TokenOut(token=make_token(admin["id"], "admin"), role="admin", user={
            "id": admin["id"], "ad": admin["ad"], "soyad": admin.get("soyad"),
            "kullanici_adi": admin.get("kullanici_adi"), "tc": admin.get("tc_norm"),
        })

    # 2) Müşteri olarak ara
    cust = await db.customers.find_one({"tc_norm": tc}, {"_id": 0})
    if not cust:
        raise HTTPException(404, "Bu TC ile kayıtlı kullanıcı bulunamadı. Lütfen yetkili ile iletişime geçin.")
    if normalize_name(cust["ad"]) != ad_norm or normalize_name(cust["soyad"]) != soyad_norm:
        raise HTTPException(401, "Ad veya soyad TC ile eşleşmiyor")
    if cust.get("blocked"):
        raise HTTPException(403, cust.get("block_reason") or "Hesabınız askıya alındı.")
    return TokenOut(token=make_token(cust["id"], "customer"), role="customer", user={
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
async def create_admin(body: AdminUserIn, _: dict = Depends(require_admin)):
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

# ==================== CUSTOMER: Vehicles ====================
@api.get("/vehicles")
async def list_vehicles(user: dict = Depends(require_customer)):
    docs = await db.vehicles.find({}, {"_id": 0}).sort([("siralama", 1), ("gunluk_fiyat", 1)]).to_list(200)
    out = []
    for v in docs:
        v["durum"] = await compute_vehicle_status(v)
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
    now = now_iso()
    r = await db.reservations.find_one({
        "customer_id": user["id"],
        "durum": {"$in": ["onaylandi", "aktif"]},
        "bitis_tarihi": {"$gte": now},
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
    if r["durum"] not in ("onaylandi", "aktif"):
        raise HTTPException(400, "Sadece aktif/onaylı rezervasyonlar uzatılabilir")
    eski_bit = parse_iso(r["bitis_tarihi"])
    yeni_bit = parse_iso(body.yeni_bitis_tarihi)
    if yeni_bit <= eski_bit:
        raise HTTPException(400, "Yeni bitiş tarihi mevcut bitiş tarihinden sonra olmalı")

    # Validate calendar/business hours for new end date
    h = await is_holiday(yeni_bit)
    if h:
        raise HTTPException(400, f"Yeni iade tarihi: {h}")
    bh = await is_within_business_hours(yeni_bit)
    if bh:
        raise HTTPException(400, f"Yeni iade saati: {bh}")

    # Check vehicle availability
    conflict = await db.reservations.find_one({
        "vehicle_id": r["vehicle_id"],
        "id": {"$ne": rid},
        "durum": {"$in": ["beklemede", "onaylandi", "aktif"]},
        "baslangic_tarihi": {"$lt": body.yeni_bitis_tarihi},
        "bitis_tarihi": {"$gt": r["baslangic_tarihi"]},
    })
    if conflict:
        raise HTTPException(400, "Aracın yeni tarihte başka rezervasyonu var, uzatma yapılamaz")

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
        }, "$inc": {"uzatma_sayisi": 1}},
    )

    # Muhasebe: Mevcut giden faturayı yeni gün sayısıyla güncelle
    try:
        existing_inv = await db.invoices.find_one({"reservation_id": rid, "tip": "giden"})
        if existing_inv:
            settings = await db.accounting_settings.find_one({"key": "main"}, {"_id": 0})
            birim_fiyat_net = float((settings or {}).get("gunluk_birim_fiyat_net", 500.0))
            kdv_orani = float((settings or {}).get("kdv_orani", 20.0))
            if birim_fiyat_net <= 0:
                birim_fiyat_net = float(existing_inv.get("birim_fiyat_net", 500.0))
            kdv_haric = round(birim_fiyat_net * yeni_toplam_gun, 2)
            kdv_t = round(kdv_haric * kdv_orani / 100.0, 2)
            top = round(kdv_haric + kdv_t, 2)
            await db.invoices.update_one(
                {"id": existing_inv["id"]},
                {"$set": {
                    "miktar": yeni_toplam_gun,
                    "birim_fiyat_net": birim_fiyat_net,
                    "kdv_orani": kdv_orani,
                    "kdv_haric_tutar": kdv_haric,
                    "kdv_tutar": kdv_t,
                    "toplam_tutar": top,
                }},
            )
    except Exception:
        pass

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
    for d in docs:
        d["tc_masked"] = (d.get("tc_norm", "") or "")[:3] + "*****" + (d.get("tc_norm", "") or "")[-2:]
        w = await db.wallets.find_one({"customer_id": d["id"]}, {"_id": 0, "bakiye": 1})
        d["bakiye"] = (w or {}).get("bakiye", 0.0)
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
    if upd:
        await db.customers.update_one({"id": cid}, {"$set": upd})
    return await db.customers.find_one({"id": cid}, {"_id": 0})

@api.delete("/admin/customers/{cid}")
async def admin_delete_customer(cid: str, _: dict = Depends(require_admin)):
    await db.customers.delete_one({"id": cid})
    return {"ok": True}

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
                    f"{v.get('marka','')} {v.get('model','')} ({plaka}) — Aracınızın motoru açıldı. İyi yolculuklar!",
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
    for r in docs:
        c = await db.customers.find_one({"id": r["customer_id"]}, {"_id": 0, "ad": 1, "soyad": 1, "telefon": 1, "tc_norm": 1})
        if c:
            r["musteri"] = {"ad": c["ad"], "soyad": c["soyad"], "telefon": c.get("telefon"), "tc_masked": (c.get("tc_norm", "") or "")[:3] + "*****" + (c.get("tc_norm", "") or "")[-2:]}
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
    # tamamlandi'ya geçildi mi? Müşteriye otomatik "Yorum Bırak" bildirimi gönder (sadece ilk geçişte)
    if durum == "tamamlandi" and eski_durum != "tamamlandi":
        try:
            plaka = (r.get("vehicle_snapshot") or {}).get("plaka", "")
            await db.notifications.insert_one({
                "id": str(uuid.uuid4()),
                "baslik": "⭐ Yorum Bırakır mısınız?",
                "mesaj": f"{plaka} araç kiralamanız tamamlandı. Deneyiminizi puanlayarak diğer müşterilere yardımcı olur musunuz?",
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

@api.put("/admin/reservations/{rid}")
async def admin_edit_reservation(rid: str, body: AdminReservationUpdate, _: dict = Depends(require_admin)):
    upd = {k: v for k, v in body.dict().items() if v is not None}
    if not upd:
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

    # Ödeme alanları değiştiyse: kalan_odeme ve odeme_durumu yeniden hesapla
    if "odenen_ucret" in upd or "toplam_tutar" in upd:
        cur = await db.reservations.find_one({"id": rid}, {"_id": 0}) or {}
        toplam = float(upd.get("toplam_tutar", cur.get("toplam_tutar", 0)) or 0)
        odenen = float(upd.get("odenen_ucret", cur.get("odenen_ucret", 0)) or 0)
        on_odeme = float(cur.get("on_odeme_tutar", 0) or 0)
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

    await db.reservations.update_one({"id": rid}, {"$set": upd})

    # Muhasebe: Tarih değiştiyse giden faturayı güncelle
    if "gun_sayisi" in upd or "baslangic_tarihi" in upd:
        try:
            existing_inv = await db.invoices.find_one({"reservation_id": rid, "tip": "giden"})
            if existing_inv:
                yeni = await db.reservations.find_one({"id": rid}, {"_id": 0})
                if yeni:
                    settings = await db.accounting_settings.find_one({"key": "main"}, {"_id": 0})
                    birim_fiyat_net = float((settings or {}).get("gunluk_birim_fiyat_net", 500.0))
                    kdv_orani = float((settings or {}).get("kdv_orani", 20.0))
                    if birim_fiyat_net <= 0:
                        birim_fiyat_net = float(existing_inv.get("birim_fiyat_net", 500.0))
                    miktar = int(yeni.get("gun_sayisi") or existing_inv.get("miktar") or 1)
                    if miktar < 1:
                        miktar = 1
                    kdv_haric = round(birim_fiyat_net * miktar, 2)
                    kdv_t = round(kdv_haric * kdv_orani / 100.0, 2)
                    top = round(kdv_haric + kdv_t, 2)
                    # Fatura tarihini de güncelle (başlangıç tarihi değiştiyse)
                    inv_upd: dict = {
                        "miktar": miktar,
                        "birim_fiyat_net": birim_fiyat_net,
                        "kdv_orani": kdv_orani,
                        "kdv_haric_tutar": kdv_haric,
                        "kdv_tutar": kdv_t,
                        "toplam_tutar": top,
                    }
                    if "baslangic_tarihi" in upd:
                        try:
                            tarih = (yeni.get("baslangic_tarihi") or "")[:10]
                            if re.match(r"^\d{4}-\d{2}-\d{2}$", tarih):
                                inv_upd["tarih"] = tarih
                                inv_upd["yil"] = int(tarih[:4])
                                inv_upd["ay"] = int(tarih[5:7])
                        except Exception:
                            pass
                    await db.invoices.update_one({"id": existing_inv["id"]}, {"$set": inv_upd})
        except Exception:
            pass

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
                        "baslik": "KM Aşım — Bakiye Yetersiz",
                        "mesaj": f"Aracınızda {asim} km aşım var. Lütfen bakiye yükleyin.",
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
        "baslik": "Provizyon İade Edildi",
        "mesaj": f"{p['tutar']:.2f}₺ provizyon bakiyenize iade edildi.",
        "hedef_type": "secili",
        "hedef_customer_ids": [p["customer_id"]],
        "tarih": now_iso(), "okuyanlar": [],
    })
    return await db.provisions.find_one({"id": pid}, {"_id": 0})

@api.get("/admin/reservations/{rid}/provisions")
async def admin_list_provisions(rid: str, _: dict = Depends(require_admin)):
    return await db.provisions.find({"reservation_id": rid}, {"_id": 0}).sort("created_at", -1).to_list(100)

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


class ExpenseUpdate(BaseModel):
    tarih: Optional[str] = None
    kategori: Optional[str] = None
    aciklama: Optional[str] = None
    tutar: Optional[float] = None
    kasa: Optional[str] = None  # 'rentcar' | 'eticaret' | '' (clear)


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
    rezervasyon_kazanc = float(res_agg[0]["toplam"]) if res_agg else 0.0

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
    # Rentcar Kasa = Tamamlanan rezervasyon kazancı + Rentcar manuel gelir - Rentcar gider
    # E-Ticaret Kasa = E-Ticaret manuel gelir - E-Ticaret gider
    # Para sadece tamamlanan rezervasyondan kazanılır; aktif/onaylı rezervasyonlardaki müşteri parası
    # henüz kazanç değildir (Bekleyen Gelir kartında ayrı gösteriliyor).
    rentcar_kasa = round(rezervasyon_kazanc + mi_rentcar - gider_rentcar, 2)
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
    """
    res_query: dict = {"durum": "tamamlandi"}
    exp_query: dict = {}
    mi_query: dict = {}

    if start:
        res_query.setdefault("bitis_tarihi", {})["$gte"] = f"{start}T00:00:00.000Z"
        exp_query.setdefault("tarih", {})["$gte"] = start
        mi_query.setdefault("tarih", {})["$gte"] = start
    if end:
        res_query.setdefault("bitis_tarihi", {})["$lte"] = f"{end}T23:59:59.999Z"
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

    # Gelir kalemleri (rezervasyon + manuel)
    gelir_kalemleri: list = []
    rezervasyon_gelir = 0.0
    for r in reservations:
        amt = float(r.get("toplam_tutar") or 0)
        if amt <= 0:
            continue
        rezervasyon_gelir += amt
        snap = r.get("vehicle_snapshot") or {}
        cust = await db.customers.find_one({"id": r.get("customer_id")}, {"_id": 0, "ad": 1, "soyad": 1})
        musteri = f"{(cust or {}).get('ad', '')} {(cust or {}).get('soyad', '')}".strip() or "—"
        gelir_kalemleri.append({
            "id": r.get("id"),
            "tarih": (r.get("bitis_tarihi") or "")[:10],
            "kaynak": "rezervasyon",
            "kategori": "Kiralama",
            "aciklama": f"{snap.get('marka', '')} {snap.get('model', '')} ({snap.get('plaka', '')})".strip(),
            "musteri": musteri,
            "tutar": round(amt, 2),
            "kasa": "rentcar",
            "editable": False,
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
    Filtre: bitis_tarihi'ne göre.
    Dönüş:
      - araclar: [{vehicle_id, marka, model, plaka, foto_url, kiralama_gun, arac_gelir, hizmet_gelir, km_gelir, toplam_kazanc, rezervasyon_adet}]
      - toplam_kazanc (tüm araçların toplamı)
    """
    res_query: dict = {"durum": "tamamlandi"}
    if start:
        res_query.setdefault("bitis_tarihi", {})["$gte"] = f"{start}T00:00:00.000Z"
    if end:
        res_query.setdefault("bitis_tarihi", {})["$lte"] = f"{end}T23:59:59.999Z"

    reservations = await db.reservations.find(res_query, {"_id": 0}).to_list(5000)
    # Map: vehicle_id → aggregate
    agg: dict = {}
    for r in reservations:
        vid = r.get("vehicle_id")
        if not vid:
            continue
        days = int(r.get("gun_sayisi") or 0)
        if days <= 0:
            try:
                bas = parse_iso(r.get("baslangic_tarihi"))
                bit = parse_iso(r.get("bitis_tarihi"))
                days = calc_days(bas, bit)
            except Exception:
                days = 0
        pricing = r.get("pricing") or {}
        # Araç gelir (rezervasyon ana ücreti + uzatma ek_arac payı)
        arac_gelir = float(pricing.get("arac_toplam") or pricing.get("arac_total") or 0)
        # Eğer pricing yoksa toplam_tutar'dan tahmin et
        # Hizmet gelir
        hizmet_gelir = float(pricing.get("hizmetler_toplam") or 0)
        hizmet_gelir += float(r.get("ek_hizmet_tutar") or 0)
        # KM gelir
        km_gelir = float(r.get("ek_km_tutar") or 0)
        km_gelir += float(r.get("km_asim_tutar") or 0)
        toplam = float(r.get("toplam_tutar") or 0)
        if not agg.get(vid):
            agg[vid] = {
                "vehicle_id": vid,
                "kiralama_gun": 0,
                "arac_gelir": 0.0,
                "hizmet_gelir": 0.0,
                "km_gelir": 0.0,
                "toplam_kazanc": 0.0,
                "rezervasyon_adet": 0,
            }
        a = agg[vid]
        a["kiralama_gun"] += days
        a["arac_gelir"] += arac_gelir
        a["hizmet_gelir"] += hizmet_gelir
        a["km_gelir"] += km_gelir
        a["toplam_kazanc"] += toplam
        a["rezervasyon_adet"] += 1

    # Vehicle bilgilerini ekle
    vids = list(agg.keys())
    araclar: list = []
    if vids:
        v_docs = await db.vehicles.find({"id": {"$in": vids}}, {"_id": 0, "id": 1, "marka": 1, "model": 1, "plaka": 1, "foto_url": 1}).to_list(1000)
        v_map = {v["id"]: v for v in v_docs}
        for vid, a in agg.items():
            v = v_map.get(vid) or {}
            araclar.append({
                "vehicle_id": vid,
                "marka": v.get("marka", "—"),
                "model": v.get("model", ""),
                "plaka": v.get("plaka", "—"),
                "foto_url": v.get("foto_url", ""),
                "kiralama_gun": int(a["kiralama_gun"]),
                "arac_gelir": round(a["arac_gelir"], 2),
                "hizmet_gelir": round(a["hizmet_gelir"], 2),
                "km_gelir": round(a["km_gelir"], 2),
                "toplam_kazanc": round(a["toplam_kazanc"], 2),
                "rezervasyon_adet": int(a["rezervasyon_adet"]),
            })
        araclar.sort(key=lambda x: x["toplam_kazanc"], reverse=True)

    toplam = round(sum(a["toplam_kazanc"] for a in araclar), 2)
    return {"araclar": araclar, "toplam_kazanc": toplam, "arac_adet": len(araclar)}


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
    """Bir rezervasyon için giden fatura oluştur (tam otomatik, sadece günlük kira baz alınır)."""
    rid = reservation.get("id")
    if not rid:
        return None
    # Zaten var mı?
    exists = await db.invoices.find_one({"reservation_id": rid, "tip": "giden"})
    if exists:
        return exists

    try:
        bas = parse_iso(reservation.get("baslangic_tarihi"))
        bit = parse_iso(reservation.get("bitis_tarihi"))
        days = calc_days(bas, bit)
    except Exception:
        days = int(reservation.get("gun_sayisi") or 1)

    if days < 1:
        days = 1

    pricing = reservation.get("pricing") or {}
    snap = reservation.get("vehicle_snapshot") or {}

    # Settings'ten KDV oranı + sabit günlük birim fiyat al
    settings = await db.accounting_settings.find_one({"key": "main"}, {"_id": 0})
    kdv_orani = float((settings or {}).get("kdv_orani", 20.0))
    birim_fiyat_net = float((settings or {}).get("gunluk_birim_fiyat_net", 500.0))

    if birim_fiyat_net <= 0:
        # Fallback: rezervasyon ortalamasından hesapla
        arac_total = float(pricing.get("arac_toplam") or pricing.get("arac_total") or 0)
        if arac_total > 0:
            birim_fiyat_net = round(arac_total / max(days, 1), 2)
        else:
            birim_fiyat_net = float(snap.get("gunluk_fiyat") or 0)

    if birim_fiyat_net <= 0:
        return None

    kdv_haric_tutar = round(birim_fiyat_net * days, 2)
    kdv_tutar = round(kdv_haric_tutar * kdv_orani / 100.0, 2)
    toplam_tutar = round(kdv_haric_tutar + kdv_tutar, 2)

    tarih = (reservation.get("baslangic_tarihi") or now_iso())[:10]
    try:
        yil = int(tarih[:4])
        ay = int(tarih[5:7])
    except Exception:
        n = datetime.now(timezone.utc)
        yil, ay = n.year, n.month

    no, seq = await _next_invoice_no(yil)

    cust = await db.customers.find_one({"id": reservation.get("customer_id")}, {"_id": 0, "ad": 1, "soyad": 1})
    customer_ad = f"{(cust or {}).get('ad', '')} {(cust or {}).get('soyad', '')}".strip() or "—"

    plaka = snap.get("plaka", "")
    marka_model = f"{snap.get('marka', '')} {snap.get('model', '')}".strip()

    doc = {
        "id": str(uuid.uuid4()),
        "no": no,
        "seq": seq,
        "tip": "giden",
        "tarih": tarih,
        "yil": yil,
        "ay": ay,
        "reservation_id": rid,
        "customer_id": reservation.get("customer_id"),
        "customer_ad": customer_ad,
        "vehicle_id": reservation.get("vehicle_id"),
        "plaka": plaka,
        "marka_model": marka_model,
        "aciklama": f"{plaka} {marka_model}".strip(),
        "birim": "Gün",
        "miktar": days,
        "birim_fiyat_net": birim_fiyat_net,
        "kdv_orani": kdv_orani,
        "kdv_haric_tutar": kdv_haric_tutar,
        "kdv_tutar": kdv_tutar,
        "toplam_tutar": toplam_tutar,
        "kasa": "rentcar",
        "durum": "kesildi",
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


app.include_router(api)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True, allow_origins=["*"],
    allow_methods=["*"], allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown():
    client.close()
