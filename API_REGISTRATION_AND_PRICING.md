# Panduan Pendaftaran API Key dan Informasi Harga (Pricing)

Dokumen ini berisi informasi mengenai tautan (link) pendaftaran API key dan perkiraan harga untuk masing-masing penyedia layanan AI dan sumber media yang didukung oleh **MoneyPrinterTurbo**.

---

## 🌟 LLM (Language Model) Providers

### 1. DeepSeek (Sangat Direkomendasikan)
- **Kelebihan**: Sangat murah, kualitas sangat baik, tidak butuh VPN.
- **Daftar API**: [DeepSeek Platform](https://platform.deepseek.com/api_keys)
- **Harga (Pricing)**: Pay-as-you-go. Sangat murah (sekitar $0.14 - $0.28 per 1 Juta Token tergantung model). Pengguna baru biasanya mendapatkan gratis kredit awal.

### 2. Moonshot (Kimi)
- **Kelebihan**: Kualitas bahasa Indonesia dan Mandarin sangat bagus, akses cepat tanpa VPN.
- **Daftar API**: [Moonshot Console](https://platform.moonshot.cn/console/api-keys)
- **Harga (Pricing)**: Pay-as-you-go. Bervariasi berdasarkan ukuran context window (sekitar $1.60 - $8.00 per 1 Juta Token). Ada gratis kredit untuk pengguna baru.

### 3. Google Gemini
- **Kelebihan**: Gratis dengan limit tertentu (Cukup untuk penggunaan standar).
- **Daftar API**: [Google AI Studio](https://aistudio.google.com/app/apikey)
- **Harga (Pricing)**:
  - **Free Tier**: Tersedia batas request per menit (RPM) gratis untuk model `gemini-1.5-flash` dan `gemini-2.0-flash`.
  - **Pay-as-you-go**: Jika melebihi batas free tier, harga bervariasi tergantung penggunaan input/output token.

### 4. OpenAI (ChatGPT)
- **Kelebihan**: Standar industri, kualitas tidak diragukan. Butuh VPN di beberapa wilayah.
- **Daftar API**: [OpenAI Platform](https://platform.openai.com/api-keys)
- **Harga (Pricing)**: Pay-as-you-go. 
  - `gpt-4o-mini`: Sangat murah (~$0.15 per 1M input tokens).
  - `gpt-4o`: Lebih mahal (~$5.00 per 1M input tokens).

### 5. Qwen (Tongyi Qianwen - Alibaba)
- **Daftar API**: [DashScope Console](https://dashscope.console.aliyun.com/apiKey)
- **Harga (Pricing)**: Banyak model Qwen open-source yang ditawarkan dengan harga sangat murah atau gratis untuk kuota tertentu. Pay-as-you-go jika melebihi kuota.

### 6. ERNIE (Baidu Wenxin Yiyan)
- **Daftar API**: [Baidu Qianfan Console](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
- **Harga (Pricing)**: Pay-as-you-go. Tersedia tier uji coba gratis untuk beberapa model lite. Membutuhkan API Key dan Secret Key.

### 7. Provider LLM Gratis & Lokal
- **Ollama**: 100% Gratis. Berjalan di komputer lokal (butuh GPU yang memadai). Anda bisa menjalankan model seperti `qwen:7b` atau `llama3`.
- **G4F (GPT4Free)**: 100% Gratis berbasis proyek open-source, namun **stabilitas sangat rendah** dan sering mengalami kegagalan (error).
- **Pollinations**: Gratis (Public API). Dapat digunakan tanpa API Key.

---

## 🎬 Video & Image Sources (Sumber Material Video)

### 1. Pexels
- **Kelebihan**: Kualitas stok video sangat bagus dan beresolusi tinggi.
- **Daftar API**: [Pexels API Request](https://www.pexels.com/api/)
- **Harga (Pricing)**: **100% Gratis**. Dibatasi sekitar 200 request per jam atau 20.000 request per bulan. Sangat cukup untuk penggunaan reguler.

### 2. Pixabay
- **Kelebihan**: Variasi stok gambar dan video yang sangat luas.
- **Daftar API**: [Pixabay API Docs](https://pixabay.com/api/docs/) (Scroll ke bawah, API Key Anda ada di dalam parameter contoh URL jika sudah login).
- **Harga (Pricing)**: **100% Gratis**. Hanya ada batasan rate-limit standar (sekitar 5.000 request per jam).

---

## 🗣️ Layanan TTS (Text-to-Speech)

### 1. Azure TTS
- **Daftar API**: [Azure Portal](https://portal.azure.com/) (Pilih layanan Speech Service).
- **Harga (Pricing)**:
  - **Free Tier**: 500.000 karakter per bulan gratis (F0 pricing tier).
  - **Pay-as-you-go**: Sekitar $16 per 1 Juta karakter jika batas gratis terlewati.

### 2. SiliconFlow TTS
- **Harga (Pricing)**: Bervariasi tergantung model suara yang digunakan, sangat terjangkau dibandingkan TTS cloud standar.

### 3. VoiceBox (Local TTS)
- **Harga (Pricing)**: **100% Gratis**. Berjalan di perangkat lokal, cocok jika Anda tidak ingin membayar layanan cloud TTS.

---

## 💡 Tips & Rekomendasi
1. **Untuk Pengguna Pemula**: Mulailah dengan menggunakan **Gemini** (karena memiliki free tier), atau **DeepSeek** (karena sangat murah namun kualitasnya setara model top-tier).
2. **Untuk Stok Video**: Wajib mendaftar **Pexels** dan **Pixabay**. Keduanya sepenuhnya gratis dan akan memberikan variasi visual yang luar biasa untuk video Anda.
3. **Untuk Suara (TTS)**: Jika bisa mendaftar **Azure**, cobalah karena kuota gratis bulanannya sangat besar (500k karakter) dan suaranya sangat natural. Jika tidak, Anda bisa memanfaatkan **Gemini TTS** atau **VoiceBox**.
