"""QSE v148 - SCAN MOMENTUM 15 DAN 30 MENIT (dipanggil listener tiap 15 menit).
Koin yang dipantau: rapor 4J A/B dari scan terakhir dan koin yang sedang kamu pegang.
Tanda awal pump atau dump: candle tutup terakhir dengan volume minimal 3 kali median 50 candle, badan candle
minimal 1,2 ATR, dan menembus high atau low 20 candle. Tiap koin paling sering sekali per 2 jam."""
import json
import os
import time
import numpy as np
import requests
from config import STATE_DIR, BYBIT_URL

FILE = os.path.join(STATE_DIR, "momentum.json")


def _kline(sym, iv):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/kline", timeout=10,
                         params={"category": "linear", "symbol": sym, "interval": iv, "limit": 80})
        rows = sorted(r.json()["result"]["list"], key=lambda x: int(x[0]))
        return np.array([[float(v) for v in x[1:6]] for x in rows[:-1]])      # buang candle berjalan
    except Exception:
        return None


def _cek(k):
    if k is None or len(k) < 55:
        return None
    o, h, l, c, v = k.T
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = tr[-15:-1].mean()
    vol_x = v[-1] / max(np.median(v[-51:-1]), 1e-12)
    badan = abs(c[-1] - o[-1])
    if atr <= 0 or vol_x < 3 or badan < 1.2 * atr:
        return None
    if c[-1] > h[-21:-1].max():
        return dict(arah="NAIK", pct=(c[-1] / o[-1] - 1) * 100, vol=vol_x, level=h[-21:-1].max(), ema=_ema(c, 20))
    if c[-1] < l[-21:-1].min():
        return dict(arah="TURUN", pct=(c[-1] / o[-1] - 1) * 100, vol=vol_x, level=l[-21:-1].min(), ema=_ema(c, 20))
    return None


def _ema(x, n):
    k, e = 2 / (n + 1), x[0]
    for y in x[1:]:
        e = y * k + e * (1 - k)
    return e


def scan(daftar, bias, posisi):
    """daftar = simbol, bias = {sym: 'LONG'/'SHORT'}, posisi = {sym: arah posisi kamu}. Return pesan."""
    try:
        with open(FILE) as f:
            st = json.load(f)
    except Exception:
        st = {}
    now = time.time()
    out = []
    for sym in daftar:
        if now - st.get(sym, 0) < 7200:
            continue
        for iv, nama in (("15", "15 menit"), ("30", "30 menit")):
            m = _cek(_kline(sym, iv))
            if not m:
                continue
            st[sym] = now
            b = bias.get(sym)
            searah = b and ((b == "LONG") == (m["arah"] == "NAIK"))
            teks = (f"⚡ <b>{sym} {m['arah']} TAJAM</b> di candle {nama}: {m['pct']:+.1f}%, volume {m['vol']:.1f}x rata-rata, "
                    f"tembus {'high' if m['arah'] == 'NAIK' else 'low'} 20 candle")
            if b:
                teks += f"\n↳ bias 4J {b}, " + ("searah. " if searah else "berlawanan, bisa jadi jebakan. ")
            teks += f"Jangan kejar. Kalau mau ikut, tunggu tarikan balik ke sekitar {m['ema']:.6g} (EMA20 {nama})."
            if sym in posisi:
                lawan = (posisi[sym] == "LONG") != (m["arah"] == "NAIK")
                teks += (" Posisi kamu searah, pertimbangkan geser SL ke entry." if not lawan else
                         " Posisi kamu BERLAWANAN, pertimbangkan kurangi risiko sekarang.")
            out.append(teks)
            break
    with open(FILE + ".tmp", "w") as f:
        json.dump({k: v for k, v in st.items() if now - v < 86400}, f)
    os.replace(FILE + ".tmp", FILE)
    return out
