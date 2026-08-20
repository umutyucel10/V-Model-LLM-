# EHSİM - ComfyUI bağlantısı

EHSİM, Gemma ile yalnızca doğrulanmış donanım alanlarından bir görsel promptu
hazırlar. PNG/JPEG/WebP üretimi ayrı çalışan ComfyUI sunucusuna gönderilir.
ComfyUI kapalı veya eksik yapılandırılmışsa uygulamanın geri kalanı çalışmaya
devam eder ve görsel sağlayıcısı güvenli biçimde devre dışı kalır.

## 1. ComfyUI iş akışını hazırlayın

1. Kullanacağınız modeli ve iş akışını ComfyUI içinde açıp normal şekilde test
   edin.
2. İş akışını `File -> Export Workflow (API)` ile JSON olarak dışa aktarın.
   Normal `Save` biçimi API çağrısında kullanılamaz.
3. Dışa aktarılan JSON'da ilgili değerleri aşağıdaki işaretçilerle değiştirin.
   İşaretçileri JSON string değeri olarak, tırnak içinde bırakmak en güvenli
   yöntemdir:

```json
{
  "3": {
    "class_type": "KSampler",
    "inputs": {"seed": "{{SEED}}"}
  },
  "4": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": {"ckpt_name": "{{MODEL}}"}
  },
  "5": {
    "class_type": "EmptyLatentImage",
    "inputs": {"width": "{{WIDTH}}", "height": "{{HEIGHT}}", "batch_size": 1}
  },
  "6": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "{{PROMPT}}"}
  },
  "7": {
    "class_type": "CLIPTextEncode",
    "inputs": {"text": "{{NEGATIVE_PROMPT}}"}
  }
}
```

Altı işaretçinin tamamı zorunludur. `{{PROMPT}}` ve
`{{NEGATIVE_PROMPT}}` ayrı metin girdilerinde; `{{MODEL}}` bir
`ckpt_name`/`unet_name`/`model_name` girdisinde; `{{SEED}}` bir
`seed`/`noise_seed` girdisinde; boyut işaretçileri de karşılık gelen
`width`/`height` girdilerinde bulunmalıdır. Bu düğümlerin tamamı seçilen
görsel çıktı dalına bağlı olmalıdır. Model, seed, width ve height
işaretçileri başka metinle birleştirilmeden alanın tam değeri olmalıdır.

Böylece arayüzde gösterilen prompt, negative prompt, model, seed ve
çözünürlük değerlerinin gerçekten çalıştırılan iş akışına uygulandığı ve
görselle birlikte kaydedilen provenance bilgisinin doğru olduğu garanti
edilir. EHSİM sayısal işaretçileri JSON sayısına dönüştürür ve prompt içindeki
tırnak/yeni satır karakterlerini güvenli biçimde işler. İş akışında tek
bir indirilebilir görsel çıktı düğümü (`SaveImage`/`PreviewImage`) bulunmalıdır.
Birden çok görsel çıktı varsa `EHSIM_COMFYUI_OUTPUT_NODE` ile bunlardan biri
açıkça seçilmelidir.

## 2. Ortam değişkenlerini ayarlayın

Aynı PowerShell oturumunda, yolları kendi kurulumunuza göre düzenleyin:

```powershell
$env:EHSIM_IMAGE_PROVIDER = "comfyui"
$env:EHSIM_IMAGE_API_URL = "http://127.0.0.1:8188"
$env:EHSIM_IMAGE_MODEL = "model-dosyasi.safetensors"
$env:EHSIM_COMFYUI_WORKFLOW = "C:\ComfyUI\workflows\ehsim-api.json"
```

İsteğe bağlı ayarlar:

```powershell
$env:EHSIM_IMAGE_TIMEOUT = "300"
$env:EHSIM_COMFYUI_OUTPUT_NODE = "9"
$env:EHSIM_COMFYUI_POLL_INTERVAL = "0.35"
```

Bir ters vekil/API anahtarı kullanılıyorsa `EHSIM_IMAGE_API_KEY`,
`EHSIM_IMAGE_API_KEY_HEADER` ve `EHSIM_IMAGE_API_KEY_PREFIX` ayarlanabilir.
Anahtarları kaynak koda, workflow JSON'una veya kullanıcı katalog verisine
yazmayın.

## 3. Bağlantıyı doğrulayın

Önce ComfyUI'yi başlatın, ardından:

```powershell
Invoke-RestMethod http://127.0.0.1:8188/system_stats
```

EHSİM açıldığında AI Donanım Görseli ekranı hem ComfyUI bağlantısını hem de API
workflow dosyasını yerel olarak denetler. İkisi de hazırsa `2 - Görseli Üret`
düğmesi, Gemma promptu hazırlandıktan sonra etkinleşir. Seçilen modelin ve özel
düğümlerin sunucuda gerçekten kurulu olduğu ilk üretim isteğinde ComfyUI
tarafından doğrulanır; ilk kullanımdan önce aynı workflow'u ComfyUI arayüzünde
çalıştırmak önerilir.

Üretilen dosya önce geçici önizlemede tutulur. Ancak kullanıcı `Kabul Et`
dedikten sonra proje `ai_gorselleri` klasörüne benzersiz ve atomik adla yazılır.
AI görseli gerçek/datasheet görselini otomatik olarak değiştirmez ve toplu
üretimde otomatik kapak yapılmaz.

## Sorun giderme

- `Export Workflow (API)` uyarısı: Normal ComfyUI kayıt JSON'u seçilmiştir;
  workflow'u API biçiminde yeniden dışa aktarın.
- Model yapılandırılmadı: Workflow `{{MODEL}}` kullanıyorsa
  `EHSIM_IMAGE_MODEL` değerini ComfyUI'deki checkpoint adıyla aynı yazın.
- Görsel çıktı bulunamadı: Workflow'a `SaveImage` ekleyin veya birden çok çıktı
  varsa `EHSIM_COMFYUI_OUTPUT_NODE` ile doğru düğüm kimliğini seçin.
- Üretim iptali: EHSİM yeni ComfyUI job API'sinde yalnızca kendi iş kimliğini
  iptal eder. Eski sunucu API'sinde `/queue` geri dönüşü yalnızca henüz
  başlamamış işi kuyruktan kaldırabilir; çalışan GPU işi sunucuda tamamlanabilir
  ancak EHSİM sonucu kaydetmez. Paylaşılan ComfyUI sunucusundaki başka işleri
  durdurmamak için genel `/interrupt` çağrısı yapılmaz.
