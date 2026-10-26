"""Fitur MULTI-TP + SARAN PINDAH SL tiap kenaikan profit (permintaan 26 Okt 2026). Modular, bawaan OTOMATIS:
nyala sendiri hanya kalau uji bulanan QSE LAB di sinyal robot 180 hari terakhir membuktikan total R dan PF lebih tinggi
dari aturan jalur (minimal 150 trade, dicoba jarak 1, 2, 3, 5%, dipilih yang terbaik). Hasil uji di STATE_DIR/lab/slsaran_auto.json.

Aturan:
- Pemicu: posisi kamu berstatus jalan (TERISI atau TP1).
- Tiap profit harga naik 1 interval (bawaan 1%) dari entry, kirim saran SL sekali per level (high-water mark):
  level 1 SL ke entry + buffer biaya, level n SL ke profit level n-1.
- Robot TIDAK memindahkan SL dan TIDAK menutup posisi di Bybit. TP1, TP2 hanya dikabari, catat sendiri dengan /tp KOIN 30%.
- Cooldown per posisi supaya tidak spam.

Konfigurasi lewat environment (.env), tanpa token di kode:
  QSE_SLSARAN_AKTIF=auto        bawaan: ikut hasil uji bulanan lab. 1 = paksa nyala, 0 = paksa mati
  QSE_SLSARAN_INTERVAL=1        jarak level profit dalam persen harga
  QSE_LEVERAGE=1                pengali untuk profit terhadap modal (info)
  QSE_SL_BUFFER=0.12            buffer biaya untuk SL breakeven, persen
  QSE_MULTI_TP=3:30,6:30        daftar TP, format level%:porsi%
  QSE_SLSARAN_COOLDOWN=15       jeda minimal antar pesan per posisi, menit
  QSE_SLSARAN_MODE=live         live atau paper (paper: pesan diberi tanda PAPER)
Kanal notifikasi memakai Telegram yang sama (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID di .env).

Hasil uji jujur 2021-2026, 12 ribu sinyal jalur, data 1 jam, kalau saran SL selalu diikuti:
  aturan jalur sekarang PF 1.26 / 1.38, total +861R / +1321R, WR 37 / 39%
  saran SL tiap 1%       PF 1.60 / 1.34, total +392R / +287R, WR 48 / 44%
  saran SL tiap 2%       PF 1.37 / 1.28, total +432R / +418R
WR naik, tapi total profit turun 55 sampai 78% karena trade besar ikut terpotong. Karena itu tidak dipaksa nyala:
mode auto menunggu bukti dari sinyal robot sendiri tiap bulan."""
import logging
import os
import time

log = logging.getLogger("qse.slsaran")


def _env(k, d, f=str):
    try:
        return f(os.environ.get(k, d))
    except Exception:
        return f(d)


def _hasil_lab():
    try:
        import json
        from config import STATE_DIR
        with open(os.path.join(STATE_DIR, "lab", "slsaran_auto.json")) as f:
            return json.load(f)
    except Exception:
        return None


def konfig(baku=False):
    """baku=True: nilai dasar tanpa melihat hasil lab (dipakai saat uji)."""
    tp = []
    for x in _env("QSE_MULTI_TP", "3:30,6:30").split(","):
        try:
            lv, pr = x.split(":")
            tp.append((float(lv), float(pr)))
        except Exception:
            continue
    k = dict(aktif=False, interval=_env("QSE_SLSARAN_INTERVAL", 1.0, float), sumber="mati",
             lev=_env("QSE_LEVERAGE", 1.0, float), buffer=_env("QSE_SL_BUFFER", 0.12, float),
             tp=sorted(tp), cooldown=_env("QSE_SLSARAN_COOLDOWN", 15.0, float) * 60,
             mode=_env("QSE_SLSARAN_MODE", "live"))
    if baku:
        return k
    pilih = str(_env("QSE_SLSARAN_AKTIF", "auto")).strip().lower()
    if pilih in ("1", "ya", "on", "true"):
        k.update(aktif=True, sumber="paksa")
    elif pilih in ("0", "tidak", "off", "false"):
        k.update(aktif=False, sumber="mati")
    else:
        h = _hasil_lab()
        if h and h.get("aktif") and h.get("interval") and time.time() - h.get("t", 0) < 40 * 86400:
            k.update(aktif=True, interval=float(h["interval"]), sumber="auto")
    return k


def saran_sl(entry, arah, level, k):
    """Harga SL yang disarankan saat high-water mark di level ini."""
    d = 1 if arah == "LONG" else -1
    p = k["buffer"] if level == 1 else (level - 1) * k["interval"]
    return entry * (1 + d * p / 100)


def simulasi(highs, lows, closes, entry, arah, sl, k=None):
    """Mode backtest: jalankan aturan saran SL (dianggap diikuti) di deret harga. Return (profit %, alasan keluar)."""
    k = k or konfig()
    d = 1 if arah == "LONG" else -1
    hw, best = 0, entry
    for hi, lo in zip(highs, lows):
        if (lo <= sl) if d == 1 else (hi >= sl):
            return (sl - entry) * d / entry * 100, "SL"
        best = max(best, hi) if d == 1 else min(best, lo)
        lvl = int(((best - entry) * d / entry * 100) // k["interval"])
        if lvl > hw:
            hw = lvl
            n = saran_sl(entry, arah, lvl, k)
            sl = max(sl, n) if d == 1 else min(sl, n)
    return (closes[-1] - entry) * d / entry * 100, "akhir data"


def cek():
    """Dipanggil tiap menit per orang (lewat SY.per_orang). Return daftar pesan."""
    k = konfig()
    if not k["aktif"]:
        return []
    import qse_saya as SY
    d0 = SY._load()
    pesan, ubah = [], {}
    now = time.time()
    for key, it in d0["open"].items():
        if it.get("status") not in ("TERISI", "TP1"):
            continue
        try:
            px = SY.harga_live(it["sym"])
        except Exception as ex:
            log.warning("harga %s gagal: %s", it["sym"], ex)
            px = None
        if not px:
            continue                       # API gagal atau harga terlambat: lewati menit ini, coba lagi menit depan
        L = it["arah"] == "LONG"
        prof = ((px - it["entry"]) if L else (it["entry"] - px)) / it["entry"] * 100
        lvl = int(prof // k["interval"]) if prof > 0 else 0
        hw = it.get("sl_hw", 0)
        if lvl <= hw or now - it.get("sl_hw_t", 0) < k["cooldown"]:
            continue
        t = it.get("tick") or SY.tick_of(None, px)
        sl_baru = saran_sl(it["entry"], it["arah"], lvl, k)
        tp_rows = []
        for i, (lv, pr) in enumerate(k["tp"], 1):
            harga_tp = it["entry"] * (1 + (lv if L else -lv) / 100)
            tp_rows.append(f"{'✅' if prof >= lv else '⏳'} TP{i} {SY.fp(harga_tp, t)} (+{lv:g}%, tutup {pr:g}%)")
        tp_baru = [(i, pr) for i, (lv, pr) in enumerate(k["tp"], 1) if hw * k["interval"] < lv <= prof]
        tag = (" [PAPER]" if k["mode"] == "paper" else "") + (" [AUTO: terbukti uji bulanan]" if k["sumber"] == "auto" else "")
        pesan.append(f"📶 <b>{it['sym']} {it['arah']}  ·  profit +{lvl * k['interval']:g}%{tag}</b>\n"
                     f"Entry {SY.fp(it['entry'], t)}  ·  harga {SY.fp(px, t)}  ·  profit {prof:+.2f}% harga"
                     + (f" ({prof * k['lev']:+.1f}% modal di {k['lev']:g}x)" if k["lev"] != 1 else "") + "\n"
                     f"🛡 Saran SL baru: {SY.fp(sl_baru, t)} "
                     + ("(entry + biaya)" if lvl == 1 else f"(kunci +{(lvl - 1) * k['interval']:g}%)") + ". Pindahkan sendiri di Bybit.\n"
                     + "\n".join(tp_rows)
                     + "".join(f"\n💰 TP{i} kena: tutup {pr:g}% di Bybit, lalu catat /tp {it['sym'][:-4]} {pr:g}%" for i, pr in tp_baru))
        ubah[key] = (lvl, now)
    if ubah:
        def f(d):
            for kk, (lv, tt) in ubah.items():
                if kk in d["open"]:
                    d["open"][kk]["sl_hw"] = lv
                    d["open"][kk]["sl_hw_t"] = tt
        try:
            SY.ubah(f)
        except Exception as ex:
            log.error("simpan high-water mark gagal: %s", ex)
    return pesan
