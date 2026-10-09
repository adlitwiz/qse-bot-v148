"""QSE v148 - semua perintah Telegram. Dipakai qse_listener.py (balasan detik) dan main.py (cadangan)."""
import fcntl
import json
import os
import re
import time
import qse_fixprofit as FX
import qse_saya as SY
import qse_alarm as AL
import telegram_notify as TG
from config import STATE_DIR

LOCK_BOT = os.path.join(STATE_DIR, ".lock")

def mulai_scan():
    """Jalankan scan sekarang di proses terpisah supaya listener tetap bisa membalas perintah lain."""
    import subprocess
    import sys
    tanda = os.path.join(STATE_DIR, ".scan_terakhir")
    try:
        if time.time() - os.path.getmtime(tanda) < 600:
            sisa = int(600 - (time.time() - os.path.getmtime(tanda))) // 60 + 1
            return f"Scan terakhir belum 10 menit. Coba lagi sekitar {sisa} menit lagi, atau cek /sinyal4j dan /sinyal1j."
    except OSError:
        pass
    open(tanda, "w").close()
    folder = os.path.dirname(os.path.abspath(__file__))
    subprocess.Popen([sys.executable, "main.py", "--scan"], cwd=folder, env=os.environ.copy(),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    return ("Scan dimulai. Robot menilai ulang koin rapor A/B di TF 4J dan TF 1J dengan harga terkini. "
            "Hasilnya terkirim dalam 1 sampai 3 menit.")


def mulai_laporan4j():
    """Paksa laporan 4 jam sekarang (laporan susulan) di proses terpisah."""
    import fcntl
    import subprocess
    import sys
    try:
        with open(os.path.join(STATE_DIR, ".main.lock"), "a") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        return "Laporan 4 jam sedang dibuat. Hasilnya otomatis terkirim begitu selesai."
    tanda = os.path.join(STATE_DIR, ".laporan_terakhir")
    try:
        if time.time() - os.path.getmtime(tanda) < 900:
            return "Laporan 4 jam baru saja diminta. Tunggu hasilnya dulu, paling lama 20 menit."
    except OSError:
        pass
    open(tanda, "w").close()
    folder = os.path.dirname(os.path.abspath(__file__))
    log = open(os.path.join(STATE_DIR, "main.log"), "a")
    log.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} /laporan4j =====\n")
    log.flush()
    subprocess.Popen([sys.executable, "-u", "main.py", "semua"], cwd=folder, env=os.environ.copy(),
                     stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    log.close()
    return ("Laporan 4 jam susulan dimulai. Robot memindai semua koin dengan harga sekarang. "
            "Hasilnya terkirim dalam 10 sampai 20 menit dan otomatis disematkan.")


BANTUAN = ("❓ <b>QSE v148 | BANTUAN</b>\n\n"
           "<b>Catat entry</b>\n"
           "/entry long market AUSDT = entry MARKET di harga sekarang\n"
           "/entry long limit AUSDT 1.022 = order LIMIT yang menunggu terisi\n"
           "/entry long limit AUSDT 1.022 terisi 02:00 = lupa catat, sudah terisi jam 02:00 WIB\n"
           "Tambahan opsional: sl 0.99 tp1 1.05 tp2 1.08 lev 10\n\n"
           "<b>Kelola posisi</b>\n"
           "/tp AUSDT 30% = ambil profit 30% posisi di harga sekarang (bisa 50% atau 100%)\n"
           "/sl AUSDT 50% = cut loss 50% posisi di harga sekarang\n"
           "/sl AUSDT short 100% = tutup hanya posisi SHORT (kalau ada LONG dan SHORT di koin yang sama)\n"
           "/serok AUSDT long 0.95 = tambah posisi di harga lebih baik, lot dibatasi supaya rugi total di SL maks 1.5R\n"
           "/hapus AUSDT short = hapus catatan trade selesai terakhir yang salah\n"
           "/tp AUSDT 50% 1.050 = sama, tapi di harga yang kamu tulis\n"
           "/ubah AUSDT sl 0.99 tp1 1.05 tp2 1.08 = ubah level SL atau TP\n"
           "/ubah AUSDT sl entry = geser SL ke titik impas\n"
           "/tutup AUSDT = tutup semua sisa posisi di harga sekarang\n"
           "/batal AUSDT = batalkan order yang belum terisi\n\n"
           "<b>Modal dan risiko</b>\n"
           "/modal 1000 risk 1 = modal 1000 USDT, risiko 1% per trade, tiap saran menampilkan ukuran posisi\n"
           "/modal rem 3 posisi 3 = rem harian -3R dan maksimal 3 posisi sekaligus\n"
           "/modal = lihat pengaturan dan kondisi rem sekarang\n\n"
           "<b>Alarm harga</b>\n"
           "/alert BTC 60000 = kabari saat harga menyentuh 60000, bisa ditambah catatan\n"
           "/alert = daftar alarm aktif\n"
           "/alert hapus BTC atau /alert hapus semua = hapus alarm\n\n"
           "<b>Sinyal</b>\n"
           "/sinyal4j = saran TF 4 jam yang masih aktif, dengan harga sekarang\n"
           "/sinyal1j = saran TF 1 jam yang masih aktif\n"
           "/scan = scan sekarang dengan harga terkini, hasil dalam 1 sampai 3 menit\n"
           "/laporan4j = buat ulang laporan 4 jam sekarang (laporan susulan), hasil dalam 10 sampai 20 menit\n"
           "/berita = uji news ke trade: sumber berita, terjemahan, harga Bybit\n"
           "/ujimomentum = backtest saran momentum 15/30 menit di koin rapor A/B (atau /ujimomentum SOL)\n"
           "/jalur = hasil live saran momentum, news searah, dan news mandiri\n"
           "/altseason = cek rezim altcoin vs BTC dan peluangnya di sejarah\n\n"
           "<b>Info</b>\n"
           "/cek AUSDT = analisa lengkap koin: kesimpulan, saran robot, teknikal, siklus, skill, fundamental, derivatif, kalender\n"
           "/evaluasi = jalur, pola, koin, hari, dan jam terbaik dari trade kamu, plus lot disarankan\n"
           "/uji = hasil uji mundur 6 bulan saran cadangan, fib, dan siklus\n"
           "/kalibrasi ETHFI = angka bot untuk dicocokkan dengan DASBOR TradingView\n"
           "/tespin = cek apakah bot sudah bisa menyematkan pesan\n"
           "/status = trade kamu, floating, dan WR\n"
           "/bantuan = daftar perintah ini")


def _sym(a):
    return a if a.endswith("USDT") else a + "USDT"


def _bot_bebas():
    lk = open(LOCK_BOT, "a")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lk
    except OSError:
        lk.close()
        return None


def _batal_sinyal(sym, dari_main):
    """Hapus sinyal robot koin ini dari catatan. Return teks keterangan."""
    if dari_main:
        led = FX.load()
        n = FX.batal_manual(led, sym)
        FX.save(led)
        return n, False
    lk = _bot_bebas()
    try:
        led = FX.load()
        ada = sum(1 for v in led["open"].values() if v["sym"] == sym)
        if not ada:
            return 0, False
        if lk:
            FX.batal_manual(led, sym)
            FX.save(led)
            return ada, False
        FX.antrian_tambah(sym)
        return ada, True
    finally:
        if lk:
            lk.close()


def balas(cmd, args, dari_main=False):
    if cmd == "/entry":
        return SY.entry(args)
    if cmd == "/cek":
        if not args:
            return "Format: /cek AUSDT atau /cek AUSDT long 1.022"
        sym = _sym(args[0])
        arah = next((("LONG" if a in ("LONG", "BUY") else "SHORT") for a in args[1:]
                     if a in ("LONG", "SHORT", "BUY", "SELL")), None)
        harga = next((SY._angka(a) for a in args[1:] if SY._angka(a) is not None), None)
        return SY.konsultasi(sym, arah, harga)
    if cmd == "/tutup":
        return SY.tutup(args)
    if cmd == "/tp":
        return SY.tutup(args, "ambil profit")
    if cmd == "/sl":
        return SY.tutup(args, "cut loss")
    if cmd == "/tespin":
        ids = TG.send(["📌 <b>QSE v148 | TES PIN</b>\nKalau pesan ini tersemat, izin pin bot sudah benar."]) or []
        if not ids:
            return "Pesan tes gagal terkirim."
        err = TG.pin(ids[0])
        return ("✅ Pin berhasil. Sinyal 4 jam berikutnya akan otomatis disematkan dan pin lama dilepas."
                if not err else f"❌ Pin gagal. Kata Telegram: {TG.e(str(err))}\nBuka info grup, Administrator, pilih bot, "
                f"lalu aktifkan izin Sematkan pesan (Pin messages).")
    if cmd == "/kalibrasi":
        return SY.kalibrasi_teks(args[0]) if args else "Format: /kalibrasi ETHFI"
    if cmd == "/serok":
        return SY.serok(args)
    if cmd == "/hapus":
        return SY.hapus(args)
    if cmd == "/ubah":
        return SY.ubah_level(args)
    if cmd in ("/alert", "/alarm"):
        return AL.perintah(args)
    if cmd in ("/sinyal4j", "/sinyal4", "/sinyal"):
        return SY.saran_aktif("240")
    if cmd in ("/sinyal1j", "/sinyal1"):
        return SY.saran_aktif("60")
    if cmd == "/scan":
        return mulai_scan()
    if cmd in ("/laporan4j", "/laporan", "/susul"):
        return mulai_laporan4j()
    if cmd in ("/jalur", "/rekapjalur"):
        import qse_catat as CT
        return CT.teks()
    if cmd in ("/altseason", "/alt"):
        import qse_altseason as AS
        return AS.teks() or "Data altcoin gagal diambil, coba lagi nanti."
    if cmd in ("/ujimomentum", "/ujimom"):
        import qse_momentum as MO
        try:
            with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
                lama = json.load(f)
        except Exception:
            return "Belum ada hasil scan 4 jam. Coba lagi setelah laporan 4 jam keluar."
        sym = [r["symbol"] for r in lama if r.get("tf", "240") == "240" and r["rapor"] in ("A", "B")]
        if args:
            sym = [a.upper() if a.upper().endswith("USDT") else a.upper() + "USDT" for a in args]
        return MO.uji(sym) if sym else "Belum ada koin rapor A/B untuk diuji."
    if cmd in ("/berita", "/news"):
        import qse_news as NW
        return NW.tes()
    if cmd == "/modal":
        import qse_modal as MD
        return MD.perintah(args)
    if cmd == "/evaluasi":
        return SY.evaluasi()
    if cmd == "/uji":
        import qse_uji as QU
        return QU.ringkas()
    if cmd == "/batal":
        if not args:
            return "Format: /batal AUSDT"
        rows = []
        for a in args:
            sym = _sym(a)
            n_sig, antri = _batal_sinyal(sym, dari_main)
            n_saya, jalan = SY.batal(sym)
            bag = []
            if n_sig:
                bag.append(f"{n_sig} saran robot dihapus dari daftar pantau" + (" (tercatat permanen setelah scan selesai)" if antri else ""))
            if n_saya:
                bag.append(f"{n_saya} order kamu yang belum terisi dibatalkan")
            if jalan:
                bag.append(f"{jalan} posisi kamu masih jalan, pakai /tutup {a} HARGA untuk keluar")
            rows.append(f"➡️ {sym}: " + ("; ".join(bag) if bag else "tidak ada order terbuka"))
        return "\n".join(rows)
    if cmd == "/status":
        try:
            with open(os.path.join(STATE_DIR, "state.json")) as f:
                s4 = json.load(f).get("scan4")
        except Exception:
            s4 = None
        akhir = time.strftime("%d/%m %H:%M", time.gmtime(s4 / 1000 + 7 * 3600)) if s4 else "-"
        return "📊 <b>QSE v148 | STATUS</b>\n" + f"Scan 4 jam terakhir: candle tutup {akhir} WIB\n\n" + SY.status_saya()
    if cmd in ("/bantuan", "/help", "/start"):
        return BANTUAN
    return ""


def proses(cmds, dari_main=False):
    """Jalankan daftar (perintah, argumen), kirim balasan ke Telegram. Return jumlah dibalas."""
    n = 0
    for cmd, args in cmds:
        args = [x for x in (re.sub(r"[^A-Z0-9.,:/%]", "", a.upper()) for a in args) if x]
        try:
            isi = balas(cmd, args, dari_main)
        except Exception as ex:
            isi = f"Perintah gagal: {TG.e(str(ex)[:200])}"
        if isi:
            ikon = {"/entry": "📝", "/cek": "🧐", "/tutup": "✋", "/tp": "💰", "/sl": "🛑", "/ubah": "✏️", "/hapus": "🗑️", "/serok": "➕", "/kalibrasi": "🧪", "/tespin": "📌", "/batal": "❌", "/alert": "🔔", "/alarm": "🔔", "/evaluasi": "📚",
                    "/uji": "🧪", "/modal": "💼", "/scan": "🔎", "/laporan4j": "📊", "/laporan": "📊", "/susul": "📊", "/berita": "📰", "/ujimomentum": "⚡", "/jalur": "📒", "/rekapjalur": "📒", "/altseason": "🌈", "/alt": "🌈", "/ujimom": "⚡", "/news": "📰", "/sinyal4j": "📡", "/sinyal4": "📡",
                    "/sinyal": "📡", "/sinyal1j": "📡", "/sinyal1": "📡",
                    "/bantuan": "❓", "/help": "❓", "/start": "❓"}
            isi = isi if "QSE v148 |" in isi.split("\n")[0] else f"{ikon.get(cmd, '🤖')} <b>QSE v148 | {cmd.upper()[1:]}</b>\n\n{isi}"
            TG.send(isi.split("\n\n"))
            n += 1
    return n
