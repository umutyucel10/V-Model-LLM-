# -*- coding: utf-8 -*-
"""Configuration file for IEEE 15288 LLM system"""

import os


def _env_number(name, default, converter):
    try:
        return converter(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default

# --- LLM API Configuration ---
# LM Studio Configuration
LMSTUDIO_BASE_URL = "http://localhost:1234/v1"   # LM Studio API URL
LMSTUDIO_API_KEY = "lm-studio"                   # LM Studio API key
DEFAULT_MODEL_NAME = "google_gemma-3-4b-it"
# Yalnızca başlatılan süreç için model değiştirmeye izin verir. Normal EHSİM
# açılışı mevcut Gemma 3 4B modelini kullanmaya devam eder.
MODEL_NAME = os.environ.get("EHSIM_LM_MODEL", DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME

# --- Donanım Kartları AI Görsel Sağlayıcısı ---
# Varsayılan güvenli davranış devre dışıdır. Adres, model ve kimlik bilgileri
# kaynak koda yazılmaz; yalnızca ortam değişkenlerinden okunur.
IMAGE_GENERATION_CONFIG = {
    "provider": os.environ.get("EHSIM_IMAGE_PROVIDER", "disabled").strip() or "disabled",
    "base_url": os.environ.get("EHSIM_IMAGE_API_URL", "").strip(),
    "model": os.environ.get("EHSIM_IMAGE_MODEL", "").strip(),
    "api_key": os.environ.get("EHSIM_IMAGE_API_KEY", ""),
    "api_key_header": os.environ.get("EHSIM_IMAGE_API_KEY_HEADER", "Authorization").strip(),
    "api_key_prefix": os.environ.get("EHSIM_IMAGE_API_KEY_PREFIX", "Bearer "),
    "health_path": os.environ.get("EHSIM_IMAGE_HEALTH_PATH", "/health").strip(),
    "models_path": os.environ.get("EHSIM_IMAGE_MODELS_PATH", "").strip(),
    "generate_path": os.environ.get("EHSIM_IMAGE_GENERATE_PATH", "/generate").strip(),
    "workflow_path": os.environ.get("EHSIM_COMFYUI_WORKFLOW", "").strip(),
    "output_node_id": os.environ.get("EHSIM_COMFYUI_OUTPUT_NODE", "").strip(),
    "poll_interval": _env_number("EHSIM_COMFYUI_POLL_INTERVAL", 0.35, float),
    "timeout": _env_number("EHSIM_IMAGE_TIMEOUT", 180.0, float),
    "max_file_size": _env_number("EHSIM_IMAGE_MAX_BYTES", 20 * 1024 * 1024, int),
    "max_pixels": _env_number("EHSIM_IMAGE_MAX_PIXELS", 24_000_000, int),
}

# Belge üretimi sonrasında kavramsal/AI görsel üretimi hiçbir zaman kendiliğinden
# başlamaz. Toplu üretim yalnızca arayüzde açık kullanıcı onayıyla çalışır.
HARDWARE_AUTO_IMAGE_GENERATION = False

# --- Model Processing Constraints ---
# Maksimum context token uzunluğunu 4096/8192 civarında tutuyoruz
# (yüksek ayarlarsan model VRAM/RAM yüzünden yüklenmez).
MAX_CONTEXT_TOKENS = 8192  

# --- Chunking Settings ---
# Büyük belgeler için parçalama (RAG uyumlu)
CHUNK_SIZE = 4000    # her parçanın token boyutu (ortalama 1500 token)
CHUNK_OVERLAP = 50   # parçalar arasında biraz örtüşme
ENABLE_CHUNKING = True     # Chunking aktif/pasif kontrolü

# --- Pasif Radar Context ---
PASIF_RADAR_CONTEXT = """PASİF RADAR KAPSAMI:

 Pasif radar sistemleri, kendi sinyalini yaymadan, mevcut elektromanyetik yayınları (FM radyo, DVB-T, analog TV vb.) kullanarak hedeflerin konumunu, hızını ve hareket yönünü belirler. Yayıncı sinyali referans olarak kullanılırken, hedeften yansıyan sinyal surveillance kanalı tarafından alınır. Pasif radar sistemleri genellikle aşağıdaki alt bileşenlerden oluşur:
 - Referans ve surveillance kanalları
 - TDOA ve FDOA hesaplamaları
 - Dijital beamforming
 - Doppler analiz (hız tespiti)
 - Çoklu frekans ve bant desteği (FM, DVB-T2, DAB)
 - Multistatik (çok istasyonlu) yapı
 - Stealth hedef tespiti
 - Gerçek zamanlı işleme (saniyelik güncelleme)
 - Yüksek dinamik aralık, düşük gürültü seviyesi
 - Elektronik karıştırmaya (jamming) dayanıklı çalışma
 - Sinyal sınıflandırma (özellikle PRISM gibi sistemlerde)

 IEEE 15288 STANDART KAPSAMI:
 - Stakeholder Needs and Requirements Definition
 - System Requirements Definition (işlevsel, performans, güvenlik, arayüz vb.)
 - Architectural Design (mimari yapı, bağlantılar)
 - Detailed Design (modül detayları, algoritmalar)
 """

# --- File Settings ---
OUTPUT_HTML_FILE = "IEEE15288LLMVAR.html"
SLEEP_DURATION = 0  # seconds between LLM calls

# --- Processing Settings ---
USE_BATCH_PROCESSING = True   # Set to False to use individual processing
BATCH_SIZE = 10               # Maximum number of TIDs to process in one batch call
