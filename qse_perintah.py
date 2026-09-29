"""QSE v148 - semua perintah Telegram. Dipakai qse_listener.py (balasan detik) dan main.py (cadangan)."""
import fcntl
import json
import os
import re
import time
import qse_fixprofit as FX
import qse_saya as SY
import telegram_notify as TG
from config import STATE_DIR

LOCK_BOT = os.path.join(STATE_DIR, ".lock")

BANTUAN = ("<b>Perintah QSE Bot</b>\n"
           "/entry long limit AUSDT 1.022 = catat trade kamu. Tambahan opsional: sl 0.99 tp1 1.05 tp2 1.08. "
           "Tanpa harga dianggap MARKET di harga sekarang\n"
           "/cek AUSDT = konsultasi robot sebelum entry. Bisa ditambah arah dan harga: /cek AUSDT long 1.022\n"
           "/tutup AUSDT 1.050 = catat keluar lebih awal dari trade kamu, harga opsional\n"
           "/batal AUSDT = batalkan order yang belum terisi dan hapus sinyal robot koin itu dari catatan\n"
           "/status = order terbuka, trade kamu, dan WR hari ini, 7 hari, 30 hari\n"
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
                bag.append(f"{n_sig} sinyal robot dihapus dari catatan" + (" (tercatat permanen setelah scan selesai)" if antri else ""))
            if n_saya:
                bag.append(f"{n_saya} order kamu yang belum terisi dibatalkan")
            if jalan:
                bag.append(f"{jalan} posisi kamu masih jalan, pakai /tutup {a} HARGA untuk keluar")
            rows.append(f"➡️ {sym}: " + ("; ".join(bag) if bag else "tidak ada order terbuka"))
        return "\n".join(rows)
    if cmd == "/status":
        led = FX.load()
        if not dari_main:
            for s in FX.antrian_lihat():
                FX.batal_manual(led, s)
        sig_all = [c for c in led["closed"] if c.get("why") in ("SL", "BE", "TP2")]
        try:
            with open(os.path.join(STATE_DIR, "state.json")) as f:
                s4 = json.load(f).get("scan4")
        except Exception:
            s4 = None
        akhir = time.strftime("%d/%m %H:%M", time.gmtime(s4 / 1000 + 7 * 3600)) if s4 else "-"
        return "\n".join([
            "<b>Sinyal robot</b>",
            TG.ringkas_open(led),
            "WR sinyal robot: " + SY.ringkas(sig_all, ("SL", "BE", "TP2")),
            "",
            SY.status_saya(),
            "",
            f"Scan 4 jam terakhir: candle tutup {akhir} WIB"])
    if cmd in ("/bantuan", "/help", "/start"):
        return BANTUAN
    return ""


def proses(cmds, dari_main=False):
    """Jalankan daftar (perintah, argumen), kirim balasan ke Telegram. Return jumlah dibalas."""
    n = 0
    for cmd, args in cmds:
        args = [x for x in (re.sub(r"[^A-Z0-9.,]", "", a.upper()) for a in args) if x]
        try:
            isi = balas(cmd, args, dari_main)
        except Exception as ex:
            isi = f"Perintah gagal: {TG.e(str(ex)[:200])}"
        if isi:
            TG.send([f"<b>QSE v148 | {cmd.upper()[1:]}</b>\n{isi}"])
            n += 1
    return n
