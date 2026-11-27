"""QSE v150 QC 154 - UJI LIVE KOIN LIAR (tanpa modal, tanpa pesan sinyal). Permintaan user 27 Nov 2026: pantau teknik khusus koin liar.
Teknik S3 BELI KAPITULASI (riset/upgrade/run_v277b_teknik_liar.py): koin liar (ATR 4J >= 3.5% harga), candle 4J tutup di bawah
Bollinger 20 tengah - 2.5 SD dan RSI 14 < 20, LONG di close, SL 3 ATR, TP penuh 1R (3 ATR), maks 120 jam.
Uji 2022-2026: PF 1.75 / 3.81 / 0.98 / 2.00 (latih, uji, 12 bulan, 6 bulan), WR 60 / 79 / 52 / 64%. Gagal di 12 bulan, jadi hanya dicatat.
Hasil live tampil di /status. Kalau 3 bulan live PF >= 1.8 dan minimal 20 trade, teknik ini layak diuji ulang untuk dinaikkan jadi sinyal.
Riset lain yang sudah dicoba untuk koin liar dan gagal: v260, v261, v262, v275, v276 (4.320 kombinasi teknik robot), v277 (breakout, squeeze,
fade, pump fade, pullback), v278 (funding, open interest, rezim BTC, momentum 7 hari)."""
import json
import os
import threading
import time
import numpy as np
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "liar_lab.json")
KANDIDAT = []
_KUNCI = threading.Lock()
SL_ATR, TP_R, MAKS_JAM = 3.0, 1.0, 120


def _baca():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    d["closed"] = d["closed"][-500:]
    with open(FILE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(FILE + ".tmp", FILE)


def kandidat(sym, df):
    """Dipanggil scan 4J per koin (data sudah ada). Simpan kandidat S3 kalau candle 4J terakhir yang tutup memenuhi syarat."""
    try:
        if os.environ.get("QSE_LIAR_LAB", "1") == "0":
            return
        import qse_strat as ST
        h, l, c = (np.asarray(df[k].values, float) for k in ("high", "low", "close"))
        if len(c) < 60:
            return
        atr = float(ST._atr(h, l, c)[-1])
        if atr / c[-1] * 100 < 3.52:
            return
        mid = c[-20:].mean(); sd = c[-20:].std(ddof=1)
        r = float(ST._rsi(c, 14)[-1])
        if c[-1] < mid - 2.5 * sd and r < 20:
            with _KUNCI:
                KANDIDAT.append(dict(sym=sym, t=int(df.index[-1]), e=float(c[-1]), atr=atr, rsi=round(r, 1)))
    except Exception as _ex:
        __import__("config").diam("qse_liar_lab.py:kandidat", _ex)


def _candle1j(sym, t0):
    import bybit_fetch as B
    n = int(min(200, (time.time() - t0) / 3600 + 3))
    df = B._raw(sym, "60", max(n, 3))
    return df[df.index >= t0 * 1000]


def proses(now=None, ambil=None):
    """Sesudah scan 4J: buka catatan untuk kandidat baru, cek SL/TP posisi catatan dari candle 1 jam. Return jumlah ditutup."""
    now = now or time.time()
    d = _baca()
    with _KUNCI:
        kd = list(KANDIDAT); KANDIDAT.clear()
    for k in kd:
        kunci = f"{k['sym']}|{k['t']}"
        if kunci in d["open"] or any(o["sym"] == k["sym"] for o in d["open"].values()):
            continue
        d["open"][kunci] = dict(sym=k["sym"], e=k["e"], sl=k["e"] - SL_ATR * k["atr"], tp=k["e"] + TP_R * SL_ATR * k["atr"], t=now, rsi=k["rsi"])
    tutup = 0
    for kunci, p in list(d["open"].items()):
        try:
            df = (ambil or _candle1j)(p["sym"], p["t"])
            r = None
            for hh, ll in zip(df["high"].values.astype(float), df["low"].values.astype(float)):
                if ll <= p["sl"]:
                    r = -1.0; break
                if hh >= p["tp"]:
                    r = TP_R; break
            if r is None and now - p["t"] >= MAKS_JAM * 3600 and len(df):
                r = (float(df["close"].values[-1]) - p["e"]) / (p["e"] - p["sl"])
            if r is not None:
                r -= 0.0015 * p["e"] / (p["e"] - p["sl"])
                d["closed"].append(dict(p, r=round(r, 3), selesai=now)); d["open"].pop(kunci); tutup += 1
        except Exception as _ex:
            __import__("config").diam("qse_liar_lab.py:proses", _ex)
    _tulis(d)
    return tutup


def baris_status():
    d = _baca(); c = d.get("closed", [])
    if not c and not d.get("open"):
        return "\n🧪 Uji live koin liar (S3 beli kapitulasi, tanpa modal): belum ada sinyal."
    r = np.array([x["r"] for x in c]) if c else np.array([])
    g = r[r > 0].sum(); l_ = -r[r < 0].sum()
    return (f"\n🧪 Uji live koin liar (S3 beli kapitulasi, tanpa modal): {len(c)} selesai, menang {int((r > 0).sum())}, "
            f"{r.sum():+.2f}R, PF {g / l_ if l_ else 0:.2f}, {len(d.get('open', {}))} jalan. Naik jadi sinyal kalau 3 bulan PF >= 1.8 dan >= 20 trade.")
