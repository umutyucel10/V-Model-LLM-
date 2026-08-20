# -*- coding: utf-8 -*-
import os
import text_cleanup
import time
from llm_handler import call_gemma3_api

def generate_dtet_ytet_from_dgoygo(requirement_content, project_name="Proje"):
    prompt = (
        f"Sen bir sistem test mühendisisin. Görevin, verilen DGÖ (Donanım-Geliştirme Özeti) gereksinimini doğrulamak için spesifik bir DTET (Donanım Testi) senaryosu yazmaktır."
        f"--- ÖRNEK BAŞARILI TEST (BUNU YAP!) ---\n"
        f"GEREKSİNİM: \"Sistem, 3 saniye içinde hedefleri tespit etmelidir.\"\n"
        f"BAŞARILI TEST: \"Bilinen 5 adet test hedefi, sisteme enjekte edildiğinde, tüm hedeflerin 3 saniyelik zaman aşımı dolmadan arayüzde 'Tespit Edildi' olarak işaretlendiği doğrulanmalıdır.\"\n"
        f"(Açıklama: Bu test, 'nasıl' yapılacağını anlatan, özgün ve ölçülebilir bir senaryodur.)\n"
        
        f"Aşağıdaki Donanım-Yazılım Geliştirme Özeti (DGÖ-YGÖ) metnini incele ve bu metinden çıkarılabilecek Donanım-Yazılım Test (DTET-YTET) dokümanı üret:\n"
        f'"{requirement_content}"\n\n'
        f"Kurallar:\n"
        f"- Türkçe olmalı, DGÖ-YGÖ'nün aynısı olmamalı ve test adına daha fazla detay içermemeli.\n"
        f"- Sadece 1 cümlelik, teknik ve işlevsel bir DTET-YTET (Donanım/Yazılım Testi) yaz.\n"
        f"- SAYI UYDURMA: kaynakta/üst maddede geçmeyen bir sayı veya değeri kendin üretme.\n"
        f"- DSB'yi YALNIZCA ölçülebilir bir değer (süre, sıcaklık, mesafe, oran, kapasite) GEREKLİ olduğu hâlde kaynakta VERİLMEMİŞSE kullan. Değerin geçeceği yere 'DSB' ve ardından birimi yaz; cümlenin kalanını normal kur. Tırnak, ok veya özel işaret KULLANMA.\n"
        f"- ÖNEMLİ: Madde niteliksel ise (ölçülecek bir sayı yoksa; ör. arayüz, güvenlik, kullanılabilirlik) DSB HİÇ KULLANMA; cümleyi DSB'siz, normal kur.\n"
        f"- Her maddeye ZAMAN ölçütü eklemek ZORUNDA DEĞİLSİN. Süre yalnızca gerçekten süreyle ilgili maddelerde geçmeli. YANLIŞ: 'güvenliğin DSB saniye içinde sağlandığı', 'DSB saniye içinde kullanıcı dostu olduğu'.\n"
        f"- DSB'yi fiile veya sayıya YAPIŞTIRMA. YANLIŞ: 'DSB malıdır', 'DSB-15 saniye', 'malzemeleri DSB tutmalıdır'. Aynı değerde hem DSB hem somut sayı KULLANMA.\n"
        f"- Cevap TAM BİR CÜMLE olmalı; sadece 'DSB saniye.' gibi tek parça yazma.\n"
        f"- ÇIKTI TAMAMEN TÜRKÇE OLMALI. Başka dilden (Çince, İngilizce) karakter veya kelime KULLANMA. Ölçüt yazacaksan 'GEÇTİ KRİTERİ:' de.\n"
        f"- Numara, başlık, açıklama veya ekstra cümle hiçbir şey ekleme.\n"
        f"- CÜMLE TEST CÜMLESİ OLSUN.\n\n"
    )
    
    # 4B model ara sıra boş/kısa cevap döner → 3 kez dene (temp=0.4 her denemede farklı üretir).
    response = None
    for _attempt in range(3):
        try:
            response = call_gemma3_api(prompt, max_tokens=300)
            if response and text_cleanup.gecerli_mi(response, 5):
                return response.strip()
        except Exception as e:
            print(f"[DTET-YTET Generator] deneme {_attempt+1} hata: {e}")
    return response.strip() if response else None


def run_generation_from_requirements(requirement_list, project_name="Project", status_callback=None):
    """
    Ana arayüzden gelen DGÖ-YGÖ listesini işler ve her biri için DTET-YTET üretir.
    """
    if not requirement_list:
        if status_callback:
            status_callback("DTET-YTET üretimi için DGÖ-YGÖ listesi bulunamadı (Liste boş).", is_error=True)
        return {"result": False, "message": "Gereksinim listesi (DGÖ-YGÖ) boş."}

    if status_callback:
        status_callback(f"DGÖ-YGÖ listesi alındı.")

    start_time = time.time()
    test_list = [] # main.py bu ismi bekliyor

    for index, req_item in enumerate(requirement_list):
        try:
            # 1. ID ve İçerik Okuma (Farklı anahtar isimlerini destekle)
            dgoygo_id = req_item.get('ID') or req_item.get('DGÖ-YGÖ_ID') or f"DGÖ-{index+1}"
            dgoygo_content = req_item.get('Aciklama') or req_item.get('DGÖ-YGÖ_Aciklama') or req_item.get('content') or ''
            
            if not dgoygo_content:
                continue

            if status_callback:
                status_callback(f"({index+1}/{len(requirement_list)}) {dgoygo_id} için DTET-YTET üretiliyor...")

            # 2. LLM Çağrısı
            dtet_text = generate_dtet_ytet_from_dgoygo(dgoygo_content, project_name)
            
            if dtet_text and text_cleanup.gecerli_mi(dtet_text, 5):
                new_id = f"HST-{len(test_list)+1:03d}"
                
                # Temizlik
                clean_text = dtet_text.strip(" .()[]").replace("Test Senaryosu:", "").strip()

                # 3. Listeye Ekleme (Standart 'ID' ve 'Aciklama' anahtarlarıyla)
                test_list.append({
                    "ID": new_id,
                    "Aciklama": clean_text,
                    "Bound_DGÖYGÖ": dgoygo_id
                })
                
                if status_callback:
                    status_callback(f"✅ {new_id} üretildi: {dgoygo_content}")
            else:
                # FALLBACK: model üretemedi → madde ATLANMASIN; gereksinimden otomatik doğrulama testi türet.
                new_id = f"HST-{len(test_list)+1:03d}"
                fallback = f"{dgoygo_content.strip().rstrip('.')} gereksiniminin sağlandığı ilgili test koşullarında doğrulanmalıdır"
                test_list.append({
                    "ID": new_id,
                    "Aciklama": fallback,
                    "Bound_DGÖYGÖ": dgoygo_id
                })
                if status_callback:
                    status_callback(f"⚠️ {new_id} modelden alınamadı; otomatik doğrulama testi eklendi.")
        
        except Exception as e:
            if status_callback:
                status_callback(f"Hata ({dgoygo_id}): {e}", is_error=True)
            continue

    duration = time.time() - start_time
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    
    # main.py 'test_list' bekliyor
    return {"result": True, "test_list": test_list, "message": "Başarılı"}