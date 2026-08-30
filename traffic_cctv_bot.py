import time
import os
import re
import cv2
import requests
import schedule

# ================= KREDENSIAL & KONFIGURASI =================
TOMTOM_API_KEY = os.getenv("TOMTOM_API_KEY", "B1KiF1M0oI5zMhHbFaA4MKAqsOTng8BU")
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN", "dTWhwCkiJ8CUdfmPMSNf")
TARGET_WHATSAPP_NUMBER = os.getenv("TARGET_WHATSAPP_NUMBER", "089654784312")  # Nomor tujuan Anda

ORIGIN = os.getenv("ORIGIN", "-6.1583873,106.6923912")       # Koordinat Asal (Rumah) - Format: lat,lon
DESTINATION = os.getenv("DESTINATION", "-6.127079,106.7407451")  # Koordinat Tujuan (Kantor) - Format: lat,lon

# Daftar CCTV per rute (M3U8 Stream atau Snapshot JPG)
# Disesuaikan dengan rute: Kalideres/Cengkareng -> Pantai Indah Kapuk (PIK)
CCTV_DATABASE = {
    "Rute 1 (Utama)": {
        "nama_titik": "Pantai Indah Kapuk (PIK)",
        "stream_url": "https://lewatmana.com/cam/286/pantai-indah-kapuk/"
    },
    "Rute 2 (Alternatif)": {
        "nama_titik": "Flyover Jati Baru / Arteri",
        "stream_url": "https://lewatmana.com/cam/336/flyover-jati-baru/"
    },
    "Rute 3 (Alternatif)": {
        "nama_titik": "Simpang MH Thamrin (Bali Tower)",
        "stream_url": "https://dki-jkt.balitower.co.id:7028/502493_JKP_SATPOL-PP_SIMPANG-JL.-MH.-THAMRIN-C09_CCTV-02/tracks-v1/index.fmp4.m3u8"
    }
}

# ================= HELPER FORMATTER =================
def format_duration(seconds):
    """Mengubah durasi detik menjadi format jam & menit yang mudah dibaca."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours > 0:
        return f"{hours} jam {minutes} mnt" if minutes > 0 else f"{hours} jam"
    return f"{minutes} mnt"

def format_distance(meters):
    """Mengubah jarak meter menjadi kilometer."""
    if meters >= 1000:
        return f"{meters / 1000:.1f} km"
    return f"{meters} m"

def upload_temp_image(image_path):
    """Upload snapshot ke hosting gambar cepat agar tautan dapat langsung dibuka di WhatsApp."""
    try:
        with open(image_path, "rb") as f:
            res = requests.post("https://tmpfiles.org/api/v1/upload", files={"file": f}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                raw_url = data.get("data", {}).get("url")
                if raw_url:
                    # Ubah ke direct download URL
                    return raw_url.replace("tmpfiles.org/", "tmpfiles.org/dl/")
    except Exception as e:
        print(f"[-] Gagal upload temp image: {e}")
    return None

# ================= 1. CEK TRAFFIC (TOMTOM ROUTING API) =================
def get_traffic_summary(origin, destination, api_key):
    url = f"https://api.tomtom.com/routing/1/calculateRoute/{origin}:{destination}/json"
    params = {
        "key": api_key,
        "traffic": "true",           # Memperhitungkan data real-time traffic
        "maxAlternatives": 2,        # Meminta hingga 2 rute alternatif
        "routeType": "fastest"
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        if response.status_code != 200:
            print(f"[-] TomTom API Error: HTTP {response.status_code} - {response.text}")
            return None
            
        data = response.json()
        if "routes" not in data or not data["routes"]:
            return None
            
        routes_summary = []
        for idx, route in enumerate(data["routes"]):
            summary = route["summary"]
            
            # Label rute
            summary_name = f"Rute {idx+1} (Utama)" if idx == 0 else f"Rute {idx+1} (Alternatif)"
            
            # Waktu tempuh & jarak dari summary TomTom
            duration_traffic_sec = summary.get("travelTimeInSeconds", 0)
            duration_normal_sec = summary.get("noTrafficTravelTimeInSeconds", duration_traffic_sec)
            traffic_delay_sec = summary.get("trafficDelayInSeconds", 0)
            length_meters = summary.get("lengthInMeters", 0)
            
            routes_summary.append({
                "summary": summary_name,
                "distance": format_distance(length_meters),
                "duration_normal": format_duration(duration_normal_sec),
                "duration_traffic": format_duration(duration_traffic_sec),
                "duration_sec": duration_traffic_sec,
                "traffic_delay": format_duration(traffic_delay_sec) if traffic_delay_sec > 0 else "0 mnt"
            })
            
        # Urutkan berdasarkan waktu tempuh aktual tercepat
        routes_summary.sort(key=lambda x: x["duration_sec"])
        return routes_summary
    except Exception as e:
        print(f"[-] Gagal menghubungi TomTom API: {e}")
        return None

# ================= 2. CAPTURE SNAPSHOT CCTV =================
def capture_cctv_frame(stream_url, output_image_path="snapshot.jpg"):
    try:
        # Penanganan khusus jika URL berupa halaman LewatMana
        if "lewatmana.com/cam/" in stream_url:
            page_res = requests.get(stream_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if page_res.status_code == 200:
                match = re.search(r'src=["\'](https://media\.lewatmana\.com/cam/[^"\']+)["\']', page_res.text)
                if match:
                    img_url = match.group(1)
                    img_res = requests.get(img_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://lewatmana.com/"}, timeout=10)
                    if img_res.status_code == 200:
                        with open(output_image_path, "wb") as f:
                            f.write(img_res.content)
                        print(f"[OK] Berhasil capture snapshot dari LewatMana: {img_url}")
                        return True

        # Jika endpoint berupa direct image JPG/PNG
        if stream_url.endswith(".jpg") or stream_url.endswith(".jpeg") or stream_url.endswith(".png"):
            res = requests.get(stream_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            if res.status_code == 200:
                with open(output_image_path, "wb") as f:
                    f.write(res.content)
                print(f"[OK] Berhasil mengunduh direct snapshot image.")
                return True
                
        # Jika endpoint berupa live video stream (.m3u8 / RTSP)
        cap = cv2.VideoCapture(stream_url)
        if not cap.isOpened():
            print(f"[-] Tidak dapat membuka stream CCTV: {stream_url}")
            return False
            
        ret, frame = cap.read()
        if ret:
            cv2.imwrite(output_image_path, frame)
            cap.release()
            print(f"[OK] Berhasil capture frame dari live stream CCTV.")
            return True
            
        cap.release()
        print(f"[-] Gagal membaca frame dari stream: {stream_url}")
        return False
    except Exception as e:
        print(f"[-] Gagal mengambil gambar CCTV: {e}")
        return False

# ================= 3. KIRIM PESAN VIA WHATSAPP (FONNTE) =================
def send_whatsapp_alert(target_phone, message, fonnte_token):
    """Mengirim pesan notifikasi ke WhatsApp menggunakan Fonnte."""
    url = "https://api.fonnte.com/send"
    headers = {"Authorization": fonnte_token}
    data = {
        "target": target_phone,
        "message": message,
        "countryCode": "62"
    }
    
    try:
        response = requests.post(url, headers=headers, data=data, timeout=30)
        return response.json()
    except Exception as e:
        print(f"[-] Gagal mengirim ke WhatsApp Fonnte: {e}")
        return None

# ================= 4. PIPELINE ORKESTRASI =================
def run_traffic_job():
    now_str = time.strftime("%d/%m/%Y %H:%M WIB")
    print(f"\n[+] [{now_str}] Memulai pengecekan rute dan traffic...")
    
    routes = get_traffic_summary(ORIGIN, DESTINATION, TOMTOM_API_KEY)
    if not routes:
        print("[-] Gagal mendapatkan data rute dari TomTom.")
        return
        
    best_route = routes[0]
    cctv_image = "cctv_snapshot.jpg"
    
    # 1. Pilih CCTV berdasarkan rute terbaik
    cctv_info = CCTV_DATABASE.get(best_route["summary"], list(CCTV_DATABASE.values())[0])
    cctv_captured = capture_cctv_frame(cctv_info["stream_url"], cctv_image)
    
    # Fallback ke kamera kedua jika kamera pertama gagal/offline
    if not cctv_captured and len(CCTV_DATABASE) > 1:
        fallback_info = list(CCTV_DATABASE.values())[1]
        print(f"[*] Mencoba fallback ke CCTV: {fallback_info['nama_titik']}...")
        if capture_cctv_frame(fallback_info["stream_url"], cctv_image):
            cctv_info = fallback_info
            cctv_captured = True

    # 2. Upload snapshot agar menghasilkan link gambar yang bisa langsung diklik di WA
    image_link = None
    if cctv_captured:
        image_link = upload_temp_image(cctv_image)
        if image_link:
            print(f"[OK] Link foto CCTV siap: {image_link}")

    # 3. Susun Template Pesan WhatsApp
    message = (
        f"🚦 *UPDATE TRAFFIC HARIAN* 🚦\n"
        f"📅 _{now_str}_\n\n"
        f"🚗 *Rute Tercepat:* {best_route['summary']}\n"
        f"⏱ *Waktu Tempuh:* {best_route['duration_traffic']} (Normal: {best_route['duration_normal']})\n"
        f"⚠️ *Estimasi Delay Macet:* {best_route['traffic_delay']}\n"
        f"📏 *Jarak:* {best_route['distance']}\n\n"
        f"📹 *Titik Pantau CCTV:* {cctv_info['nama_titik']}\n"
    )
    
    if image_link:
        message += f"📸 *Buka Foto CCTV:* {image_link}"
    elif cctv_captured:
        message += "📸 *Snapshot CCTV berhasil disimpan secara lokal.*"
    else:
        message += "⚠️ *Snapshot CCTV sedang offline.*"
    
    # Tambahkan info alternatif jika ada
    if len(routes) > 1:
        alt_route = routes[1]
        message += f"\n\n🔀 *Alternatif:* {alt_route['summary']} ({alt_route['duration_traffic']})"
        
    print("[+] Mengirim notifikasi ke WhatsApp...")
    fonnte_res = send_whatsapp_alert(
        TARGET_WHATSAPP_NUMBER,
        message,
        FONNTE_TOKEN
    )
    print(f"[OK] Respon Fonnte: {fonnte_res}")
    print("[OK] Notifikasi selesai diproses.")

# ================= 5. SCHEDULER =================
if __name__ == "__main__":
    # Jadwal otomatis setiap hari kerja (Senin - Jumat) jam 07:40 pagi
    schedule.every().monday.at("07:40").do(run_traffic_job)
    schedule.every().tuesday.at("07:40").do(run_traffic_job)
    schedule.every().wednesday.at("07:40").do(run_traffic_job)
    schedule.every().thursday.at("07:40").do(run_traffic_job)
    schedule.every().friday.at("07:40").do(run_traffic_job)
    
    # Jika ingin berjalan setiap hari (termasuk Sabtu & Minggu), uncomment baris di bawah:
    # schedule.every().day.at("07:40").do(run_traffic_job)
    
    print("[*] Bot Traffic & CCTV WhatsApp aktif. Menunggu jadwal (07:40 WIB)...")
    
    # Uncomment baris di bawah jika ingin langsung menguji coba sekali:
    # run_traffic_job()
    
    while True:
        schedule.run_pending()
        time.sleep(30)