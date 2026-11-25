# QSE v150 Bot

Robot sinyal futures kripto (Bybit perpetual USDT) untuk grup Telegram Trading For Liping.
Semua aturan sinyal, lot, SL, dan TP hanya dipasang kalau lolos uji di data 2022-2026: latih, uji, 12 bulan, 6 bulan, sesudah biaya.

## Menjalankan di VPS

1. File `~/qse_state/.env` berisi `TELEGRAM_BOT_TOKEN` dan `TELEGRAM_CHAT_ID`. Opsional `ANTHROPIC_API_KEY` untuk /pikir.
2. `bash run.sh` sekali untuk membuat venv dan memasang paket.
3. `bash pasang_listener.sh` memasang layanan `qse-listener` (systemd, hidup lagi otomatis).
4. Update: `cd ~/qse-bot-v148 && git pull && sudo systemctl restart qse-listener`

## Cek kesehatan

- `python3 cek_mandiri.py` memuat semua modul (cepat, tanpa jaringan).
- `python3 cek_mandiri.py --semua` menjalankan seluruh tes regresi di folder state sementara. Kode keluar 1 kalau ada yang gagal.
- Saat listener hidup, cek mandiri jalan otomatis. Modul yang gagal dimuat langsung dikabarkan ke grup.
- Error yang sengaja dilewati (blok `except`) dicatat oleh `config.diam()`, dicetak ke log maksimal sekali per jam per tempat,
  dan dirangkum di `/status` (baris 🩺 Kesehatan kode).
- Log layanan: `journalctl -u qse-listener -f`. Cari `[DIAM]` dan `[WARN]`.

## Modul utama

| Modul | Isi |
|---|---|
| `qse_listener.py` | Proses utama: perintah Telegram, jadwal scan, pantau posisi tiap menit |
| `qse_strat.py` | Jalur sinyal teknik 4J, kartu sinyal, uji live, sinyal tambahan searah vonis |
| `qse_radar.py` | Scan harga sekarang, scan Abdul, scan vonis berubah |
| `qse_vonis.py` | Vonis arah pasar (NAIK, TURUN, TUNGGU) dan lot vonis baru |
| `qse_saya.py` | Catatan posisi per anggota, ANALISA ULANG, TUTUP SEKARANG, peta SL rutin |
| `qse_otopsi.py` | Otopsi trade rugi, pola, status riset per pola |
| `qse_liar.py` | Tanda koin liar (ATR 4J >= 3.5%), perintah /liar |
| `qse_gurita.py` | Otak Gurita dan modal Gurita |
| `qse_skor.py` | Skor sinyal 0-100 dan kelas |
| `qse_dca.py` | Ceklis beli BTC spot |
| `qse_otak_umum.py` | Lapisan Claude API untuk /pikir (penjelasan saja) |
| `config.py` | Pengaturan dari .env, penjaga error diam |

## Riset

- `riset/upgrade/run_v*.py`: skrip uji ide (butuh data candle riset, tidak ikut repo). Hasil di `hasil_v*.txt`.
- `riset/upgrade/uji_qc*.py` dan `riset/v150/uji_*.py`: tes regresi per QC.
- `riset/v150/QC_v150.txt`: catatan semua perubahan per QC, termasuk ide yang ditolak beserta angkanya.

## Aturan perubahan

1. Pilih aturan di periode latih, buktikan di uji, 12 bulan, dan 6 bulan sesudah biaya.
2. Jangan kurangi frekuensi sinyal kecuali profit dan PF naik.
3. Jalankan `python3 cek_mandiri.py --semua` sebelum mengirim update.
