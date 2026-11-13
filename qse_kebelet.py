"""QC 92 🪰⚡ KEBELET SPOT · ACM BAR PSG. Jalur Spot terpisah: kartu, buku, dan rapor sendiri, tidak memakai slot dan rapor sinyal 4J.
Riwayat: QC 91 dipasang, lalu dicabut karena token klub hanya ada di Spot. QC 92 dipasang lagi atas izin user sebagai jalur SPOT
(Bybit Spot atau Binance Spot), LONG saja, tanpa leverage.

Cara kerja (Celah 1, riset/scalp/run_v196_celah.py, run_v196b_spot.py, run_v196c_futures.py, hasil_v196_celah.txt):
  Tiap hari 07:00 WIB (00 UTC) robot menghitung support S/R 4J (pivot k=3, 150 candle, sama dengan qse_btcmap.snr dan rencana lalat)
  untuk ACM, BAR, PSG, hanya level yang berjarak paling jauh 2 ATR dari harga. Tiap menit harga dipantau. Begitu harga MENYENTUH
  support, kartu BELI SEKARANG dikirim. SL 1.5 ATR 4J di bawah level, TP1 +0.5 ATR jual 50% lalu SL ke entry, TP2 +0.8 ATR,
  batas tahan 24 jam (6 candle 4J). Satu koin satu posisi, satu sentuhan per hari per koin.
Uji 2023-2026 (data 4J, terisi saat harga menyentuh level, SL dan TP di candle yang sama = SL), koin dipilih dari latih 2023-2024:
  biaya Spot 0.20%: latih WR 81% PF 1.51, uji 2025-Okt 2026 WR 80% PF 1.39, 12 bulan WR 82% PF 1.43, 6 bulan WR 84% PF 1.78.
  Rata menang +0.43R, rata rugi -0.99R, rugi beruntun terpanjang 8. Sekitar 2 sentuhan per hari dari 3 koin.
Di 140 koin futures lain Celah 1 rugi (PF 0.76-0.90), jadi jalur ini khusus 3 koin ini.
LONG token klub ditunda Minggu malam WIB (aturan QC 66). Saklar QSE_KEBELET=0 mati, QSE_KEBELET_KOIN (koma), QSE_KEBELET_SL (ATR, 1.5)."""
import json
import os
import time

STATE_DIR = os.environ.get("QSE_STATE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"))
PATH = os.path.join(STATE_DIR, "kebelet.json")
KOIN = [s.strip().upper() for s in os.environ.get("QSE_KEBELET_KOIN", "ACMUSDT,BARUSDT,PSGUSDT").split(",") if s.strip()]
SL_ATR = float(os.environ.get("QSE_KEBELET_SL", "1.5"))
TP1_ATR, TP2_ATR, TAHAN_JAM = 0.5, 0.8, 24
SENTUH = 0.001          # harga dalam 0.1% di atas support = dianggap menyentuh
RISIKO = 1.0            # persen modal yang hilang kalau SL kena
UJI = ("Uji 2023-2026 ACM/BAR/PSG LONG di support 4J, biaya Spot 0.2%: WR 80-84%, PF 1.39-1.78 "
       "(latih, uji, 12 bulan, 6 bulan). Rata menang +0.43R, rata rugi -0.99R.")


def hidup():
    return os.environ.get("QSE_KEBELET", "1") != "0"


def _baca():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {"rencana": {}, "hari": "", "buka": {}, "tutup": []}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PATH + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PATH + ".tmp", PATH)


def _hari(now):
    return time.strftime("%Y-%m-%d", time.gmtime(now))


def rencana_baru(d, now):
    """Hitung support hari ini (sekali per hari UTC, sesudah candle 4J 00 UTC tutup)."""
    import qse_rencana as RC
    p = dict(RC.PARAM, sk=SL_ATR)
    d["rencana"] = {}
    for s in KOIN:
        try:
            for r in RC.hitung(s, p=p):
                if r["arah"] == "LONG":
                    d["rencana"][s] = dict(level=r["level"], sl=r["sl"], atr=r["atr"], pasar=r.get("pasar") or "", tick=r.get("tick") or 0)
        except Exception as ex:
            print("[WARN] kebelet rencana", s, ex)
    d["hari"] = _hari(now)
    d["pakai"] = []


def _fp(x):
    try:
        import telegram_notify as TG
        return TG.fp(x, 0)
    except Exception:
        return f"{x:.6g}"


def baris_modal(entry, sl):
    """Ukuran Spot tanpa leverage: porsi modal supaya rugi di SL = RISIKO% modal."""
    sl_pct = (entry - sl) / entry * 100
    if sl_pct <= 0:
        return ""
    porsi = min(RISIKO / sl_pct * 100, 100.0)
    return f"💰 Pakai sekitar <b>{porsi:.0f}% modal</b> untuk koin ini, rugi kalau SL kena sekitar {porsi * sl_pct / 100:.1f}% modal."


def kartu(s, it):
    koin = s.replace("USDT", "")
    rows = ["🪰⚡ <b>KEBELET SPOT · BELI SEKARANG</b>",
            f"🟢 <b>{koin}/USDT LONG</b> · harga menyentuh support 4J · Spot Bybit atau Binance",
            "",
            "<pre>"
            f"Beli   {_fp(it['entry'])}\n"
            f"SL     {_fp(it['sl'])}  rugi {(it['entry'] - it['sl']) / it['entry'] * 100:.1f}%\n"
            f"TP1    {_fp(it['tp1'])}  untung {(it['tp1'] - it['entry']) / it['entry'] * 100:.1f}%  jual 50%, SL ke harga beli\n"
            f"TP2    {_fp(it['tp2'])}  untung {(it['tp2'] - it['entry']) / it['entry'] * 100:.1f}%  jual sisa\n"
            f"Batas  24 jam, lewat itu jual Market"
            "</pre>",
            "📲 Cara pasang: pilih <b>Limit</b>, isi harga = harga jual teratas di order book, centang <b>TP/SL</b>, "
            "isi TP = TP2 dan SL = SL di atas, lalu Buy. Saat robot kirim TP1 kena, jual 50% dan ubah SL ke harga beli.",
            f"📍 Support {_fp(it['level'])}. SL 1.5 ATR di bawah level supaya tidak tersapu ekor."]
    m = baris_modal(it["entry"], it["sl"])
    if m:
        rows.append(m)
    rows.append(f"🧪 {UJI}")
    rows.append("Jalur Spot terpisah: tidak masuk slot dan rapor sinyal 4 jam.")
    return "\n".join(rows)


def _kirim(teks):
    try:
        import telegram_notify as TG
        TG.send([teks])
    except Exception as ex:
        print("[WARN] kebelet kirim", ex)


def cek(now=None, harga=None):
    """Dipanggil tiap menit. harga = fungsi sym -> harga (untuk tes). Return list kejadian."""
    if not hidup():
        return []
    now = now or time.time()
    if harga is None:
        import qse_saya as SY
        harga = SY.harga_live
    d = _baca()
    if d.get("hari") != _hari(now) and (now % 86400) >= 300:
        rencana_baru(d, now)
    ev = []
    try:
        import qse_rencana as RC
        tunda = lambda s: RC._ditunda({"arah": "LONG", "sym": s}, now)
    except Exception:
        tunda = lambda s: False
    for s, it in list(d["buka"].items()):
        px = harga(s) or 0
        if px <= 0:
            continue
        koin = s.replace("USDT", "")
        risk = it["entry"] - it["sl0"]
        hasil = None
        if px <= it["sl"]:
            hasil = (0.5 * it["r1"] if it.get("k1") else (it["sl"] - it["entry"]) / risk), ("SL di harga beli sesudah TP1" if it.get("k1") else "SL")
        elif not it.get("k1") and px >= it["tp1"]:
            it["k1"] = True; it["sl"] = it["entry"]; it["r1"] = (it["tp1"] - it["entry"]) / risk
            _kirim(f"🪰⚡ <b>KEBELET SPOT {koin}</b>: TP1 kena {_fp(px)}. <b>Jual 50%</b>, ubah SL ke harga beli {_fp(it['entry'])}.")
            ev.append(("TP1", s))
        elif it.get("k1") and px >= it["tp2"]:
            hasil = 0.5 * it["r1"] + 0.5 * (it["tp2"] - it["entry"]) / risk, "TP2"
        elif now - it["t"] >= TAHAN_JAM * 3600:
            g = (px - it["entry"]) / risk
            hasil = (0.5 * it["r1"] + 0.5 * g if it.get("k1") else g), "batas 24 jam"
        if hasil:
            R, why = hasil
            d["tutup"].append(dict(sym=s, t=it["t"], tt=now, R=round(R, 3), why=why))
            d["tutup"] = d["tutup"][-500:]
            del d["buka"][s]
            _kirim(f"🪰⚡ <b>KEBELET SPOT {koin} selesai</b>: {why}, {R:+.2f}R. Jual sisa koin di Market kalau belum terjual otomatis.")
            ev.append((why, s))
    for s, rp in d.get("rencana", {}).items():
        if s in d["buka"] or s in d.get("pakai", []) or tunda(s):
            continue
        px = harga(s) or 0
        if px <= 0 or px <= rp["sl"]:
            continue
        if px <= rp["level"] * (1 + SENTUH):
            a = rp["atr"]
            it = dict(entry=px, sl=rp["sl"], sl0=rp["sl"], tp1=px + TP1_ATR * a, tp2=px + TP2_ATR * a, level=rp["level"], t=now,
                      pasar=rp.get("pasar"))
            d["buka"][s] = it
            d.setdefault("pakai", []).append(s)
            _kirim(kartu(s, it))
            ev.append(("MASUK", s))
            print(f"[KEBELET] {s} LONG Spot {px} support {rp['level']}", flush=True)
    _tulis(d)
    return ev


def rapor():
    d = _baca()
    t = d.get("tutup", [])
    rows = ["🪰⚡ <b>KEBELET SPOT · ACM BAR PSG</b> (buku terpisah)"]
    if t:
        r = [x["R"] for x in t]
        g = sum(x for x in r if x > 0); k = -sum(x for x in r if x < 0)
        rows.append(f"Live: {len(r)} trade, WR {sum(1 for x in r if x > 0) / len(r) * 100:.0f}%, PF {g / k if k else 99:.2f}, total {sum(r):+.2f}R")
    else:
        rows.append("Live: belum ada trade selesai.")
    for s, it in d.get("buka", {}).items():
        rows.append(f"• {s} LONG jalan dari {_fp(it['entry'])}, SL {_fp(it['sl'])}{', TP1 sudah' if it.get('k1') else ''}")
    rp = d.get("rencana", {})
    if rp:
        rows.append("Support hari ini: " + ", ".join(f"{s} {_fp(v['level'])}" for s, v in rp.items()))
    rows.append(UJI)
    return "\n".join(rows)
