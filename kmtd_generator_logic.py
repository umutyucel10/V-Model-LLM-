# -*- coding: utf-8 -*-
import os
import time
import text_cleanup
from llm_handler import call_gemma3_api
from config import CHUNK_SIZE, CHUNK_OVERLAP  # Gerekmese de zararı yok

def generate_kmtd_from_tid(requirement_content, project_name="Proje"):
    prompt = (
        f"Sen bir sistem test mühendisisin. Görevin, verilen Kullanıcı Gereksinimini (User Requirement) doğrulamak için spesifik bir Kabul Testi (Acceptance Test) senaryosu yazmaktır."
        
        f"--- ÖRNEK BAŞARILI TEST (BUNU YAP!) ---\n"
        f"GEREKSİNİM: \"Sistem, 3 saniye içinde hedefleri tespit etmelidir.\"\n"
        f"BAŞARILI TEST: \"Bilinen 5 adet test hedefi, sisteme enjekte edildiğinde, tüm hedeflerin 3 saniyelik zaman aşımı dolmadan arayüzde 'Tespit Edildi' olarak işaretlendiği doğrulanmalıdır.\"\n"
        f"(Açıklama: Bu test, 'nasıl' yapılacağını anlatan, özgün ve ölçülebilir bir senaryodur.)\n"
        
        f"Şimdi, bu BAŞARILI TEST mantığına uyarak aşağıdaki TİD için KMTD üret:\n\n"
        f"Aşağıdaki TİD metnini incele:\n"
        f'"{requirement_content}"\n\n'
        f"Kurallar:\n"
        f"- Türkçe olmalı, TİD'in aynısı olmamalı ve test adına daha fazla detay içermemeli.\n"
        f"- Sadece 1 cümlelik, teknik ve işlevsel bir KMTD yaz.\n"
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
            if response and text_cleanup.gecerli_mi(response, 6):
                return response.strip()
        except Exception as e:
            print(f"[KMTD Generator] deneme {_attempt+1} hata: {e}")
    return response.strip() if response else None


def run_generation_from_requirements(requirement_list, project_name="Project", status_callback=None):
    if not requirement_list:
        if status_callback:
            status_callback("KMTD üretimi için TİD listesi bulunamadı.", is_error=True)
        return {"result": False, "message": "Gereksinim listesi boş."}

    if status_callback:
        status_callback(f"TİD listesi alındı. ")

    start_time = time.time()
    kmtd_list = []

    for index, req_item in enumerate(requirement_list):
        try:
            tid_id = req_item.get('TID_ID', f"UR-{index+1:03d}")
            tid_content = req_item.get('TID_Aciklama', '')
            
            if not tid_content:
                if status_callback:
                    status_callback(f"{tid_id} için içerik boş, atlanıyor.", is_error=True)
                continue

            if status_callback:
                status_callback(f"({index+1}/{len(requirement_list)}) {tid_id} için KMTD üretiliyor...")

            # LLM'den KMTD metni al
            kmtd_description = generate_kmtd_from_tid(tid_content, project_name)
            
            if kmtd_description and text_cleanup.gecerli_mi(kmtd_description, 6):  # Kısa veya hatalı cevapları filtrele
                new_kmtd_id = f"AT-{index+1:03d}"
                
                # --- Ortak temizleyici: etiket (KMTD:), numara (1.), markdown, echo ---
                clean_description = text_cleanup.temizle(kmtd_description, test=True)

                # Arayüz'ün beklediği formatta veriyi hazırla
                kmtd_list.append({
                    "KMTD_ID": new_kmtd_id,
                    "KMTD_Aciklama": clean_description,  # ARTIK TEMİZ VERİ
                    "Bound_TID": tid_id
                })
                
                if status_callback:
                    status_callback(f"✅️{new_kmtd_id} üretildi: {clean_description}")
            else:
                # FALLBACK: model 3 denemede de üretemedi → madde ATLANMASIN, izlenebilirlik boşluğu
                # kalmasın diye gereksinimden deterministik bir doğrulama testi türet (Copilot ile iyileştir).
                new_kmtd_id = f"AT-{index+1:03d}"
                fallback = f"{tid_content.strip().rstrip('.')} gereksiniminin sağlandığı ilgili test koşullarında doğrulanmalıdır"
                kmtd_list.append({
                    "KMTD_ID": new_kmtd_id,
                    "KMTD_Aciklama": fallback,
                    "Bound_TID": tid_id
                })
                if status_callback:
                    status_callback(f"⚠️{new_kmtd_id} modelden alınamadı; otomatik doğrulama testi eklendi.")
        
        except Exception as e:
            if status_callback:
                status_callback(f"{tid_id} işlenirken hata: {e}", is_error=True)
            continue

    duration = time.time() - start_time
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    status_callback(f"🕙 Toplam süre: {minutes} dakika {seconds}saniye")

    return {"result": True, "kmtd_list": kmtd_list, "message": "KMTD üretimi başarılı."}