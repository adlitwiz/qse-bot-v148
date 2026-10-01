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

BANTUAN = ("❓ <b>QSE v148 | BANTUAN</b>\n\n"
           "<b>Catat entry</b>\n"
           "/entry long market AUSDT = entry MARKET di harga sekarang\n"
           "/entry long limit AUSDT 1.022 = order LIMIT yang menunggu terisi\n"
           "/entry long limit AUSDT 1.022 terisi 02:00 = lupa catat, sudah terisi jam 02:00 WIB\n"
           "Tambahan opsional: sl 0.99 tp1 1.05 tp2 1.08 lev 10\n\n"
           "<b>Kelola posisi</b>\n"
           "/tp AUSDT 30% = ambil profit 30% posisi di harga sekarang (bisa 50% atau 100%)\n"
           "/sl AUSDT 50% = cut loss 50% posisi di harga sekarang\n"
           "/tp AUSDT 50% 1.050 = sama, tapi di harga yang kamu tulis\n"
           "/ubah AUSDT sl 0.99 tp1 1.05 tp2 1.08 = ubah level SL atau TP\n"
           "/ubah AUSDT sl entry = geser SL ke titik impas\n"
           "/tutup AUSDT = tutup semua sisa posisi di harga sekarang\n"
           "/batal AUSDT = batalkan order yang belum terisi\n\n"
           "<b>Alarm harga</b>\n"
           "/alert BTC 60000 = kabari saat harga menyentuh 60000, bisa ditambah catatan\n"
           "/alert = daftar alarm aktif\n"
           "/alert hapus BTC atau /alert hapus semua = hapus alarm\n\n"
           "<b>Info</b>\n"
           "/cek AUSDT = konsultasi robot sebelum entry\n"
           "/evaluasi = jalur, pola, koin, hari, dan jam terbaik dari trade kamu, plus lot disarankan\n"
           "/uji = hasil uji mundur 6 bulan saran cadangan dan saran siklus\n"
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
    if cmd == "/ubah":
        return SY.ubah_level(args)
    if cmd in ("/alert", "/alarm"):
        return AL.perintah(args)
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
            ikon = {"/entry": "📝", "/cek": "🧐", "/tutup": "✋", "/tp": "💰", "/sl": "🛑", "/ubah": "✏️", "/batal": "❌", "/alert": "🔔", "/alarm": "🔔", "/evaluasi": "📚",
                    "/uji": "🧪",
                    "/bantuan": "❓", "/help": "❓", "/start": "❓"}
            isi = isi if "QSE v148 |" in isi.split("\n")[0] else f"{ikon.get(cmd, '🤖')} <b>QSE v148 | {cmd.upper()[1:]}</b>\n\n{isi}"
            TG.send(isi.split("\n\n"))
            n += 1
    return n
