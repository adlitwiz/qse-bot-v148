"""QSE v148 - SCAN MOMENTUM 15 DAN 30 MENIT (dipanggil listener tiap 15 menit).
Koin yang dipantau: rapor 4J A/B dari scan terakhir dan koin yang sedang kamu pegang.
Tanda awal pump atau dump: candle tutup terakhir dengan volume minimal 3 kali median 50 candle, badan candle
minimal 1,2 ATR, dan menembus high atau low 20 candle.
Seperti Golden Zone Hunter, momentum hanya dikirim sebagai SARAN kalau lolos penilaian semua aspek
(bias 4J searah wajib, tren 1 jam, BTC 15 menit, volume, jarak ke entry), lengkap dengan entry, SL, TP.
Momentum di koin yang sedang kamu pegang tetap dikabarkan sebagai info posisi. Tiap koin paling sering sekali per 2 jam."""
import json
import os
import time
import numpy as np
import requests
from config import STATE_DIR, BYBIT_URL

FILE = os.path.join(STATE_DIR, "momentum.json")
MIN_SKOR = 65


def _kline(sym, iv, limit=80):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/kline", timeout=10,
                         params={"category": "linear", "symbol": sym, "interval": iv, "limit": limit})
        rows = sorted(r.json()["result"]["list"], key=lambda x: int(x[0]))
        return np.array([[float(v) for v in x[1:6]] for x in rows[:-1]])      # buang candle berjalan
    except Exception:
        return None


def _ema(x, n):
    k, e = 2 / (n + 1), x[0]
    for y in x[1:]:
        e = y * k + e * (1 - k)
    return e


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
    base = dict(pct=(c[-1] / o[-1] - 1) * 100, vol=vol_x, ema=_ema(c, 20), atr=atr, close=c[-1],
                hi=h[-1], lo=l[-1])
    if c[-1] > h[-21:-1].max():
        return dict(base, arah="NAIK", level=h[-21:-1].max())
    if c[-1] < l[-21:-1].min():
        return dict(base, arah="TURUN", level=l[-21:-1].min())
    return None


def _fp(x, tick):
    if not tick or tick <= 0:
        return f"{x:.6g}"
    d = max(0, int(round(-np.log10(tick))))
    return f"{round(x / tick) * tick:.{d}f}"


def _rencana(m):
    """Entry LIMIT di retest level yang ditembus atau EMA20 (yang lebih dekat ke harga), SL di balik candle momentum."""
    L = m["arah"] == "NAIK"
    a, c = m["atr"], m["close"]
    e = max(m["level"], m["ema"]) if L else min(m["level"], m["ema"])
    if (L and e >= c) or ((not L) and e <= c):
        e = c - 0.5 * a if L else c + 0.5 * a
    sl0 = (min(m["lo"], e - a) - 0.2 * a) if L else (max(m["hi"], e + a) + 0.2 * a)
    dist = min(max(abs(e - sl0), 1.0 * a), 2.5 * a)
    sl = e - dist if L else e + dist
    return dict(arah="LONG" if L else "SHORT", entry=e, sl=sl, tp1=e + dist if L else e - dist,
                tp2=e + 2 * dist if L else e - 2 * dist, dist=dist)


def _nilai(sym, m, rc, info, btc15):
    """Skor 0-100 dan alasan. Bias 4J searah wajib, selain itu skor minimal MIN_SKOR."""
    L = rc["arah"] == "LONG"
    plus, minus, sk = [], [], 0
    i = info.get(sym) or {}
    if i.get("bias") != rc["arah"]:
        return 0, plus, ["bias 4J tidak searah"]
    sk += 30
    plus.append(f"bias 4J {rc['arah']} searah")
    sk += 10 if i.get("rapor") == "A" else 5
    plus.append(f"rapor robot {i.get('rapor', '-')}")
    k1 = _kline(sym, "60", 40)
    if k1 is not None and len(k1) >= 25:
        e1 = _ema(k1[:, 3], 20)
        if (k1[-1, 3] > e1) == L:
            sk += 20
            plus.append("tren 1 jam searah")
        else:
            minus.append("tren 1 jam belum searah")
    if (L and btc15 >= 0.15) or ((not L) and btc15 <= -0.15):
        sk += 15
        plus.append(f"BTC 45 menit {btc15:+.2f}% searah")
    elif abs(btc15) < 0.15:
        sk += 7
        plus.append("BTC tenang")
    else:
        minus.append(f"BTC 45 menit {btc15:+.2f}% melawan")
    if m["vol"] >= 4:
        sk += 10
        plus.append(f"volume {m['vol']:.1f}x")
    jarak = abs(m["close"] - rc["entry"]) / m["atr"]
    if jarak <= 1.5:
        sk += 15
        plus.append(f"entry dekat ({jarak:.1f} ATR)")
    else:
        minus.append(f"entry jauh ({jarak:.1f} ATR), peluang terisi kecil")
    return sk, plus, minus


def scan(daftar, bias, posisi, info=None):
    """daftar = simbol, bias = {sym: 'LONG'/'SHORT'}, posisi = {sym: arah posisi kamu},
    info = {sym: dict(rapor, tick)}. Return pesan."""
    info = info or {}
    info = {s: dict(info.get(s) or {}, bias=bias.get(s)) for s in set(info) | set(bias)}
    try:
        with open(FILE) as f:
            st = json.load(f)
    except Exception:
        st = {}
    now = time.time()
    out = []
    b15 = _kline("BTCUSDT", "15", 10)
    btc15 = (b15[-1, 3] / b15[-4, 3] - 1) * 100 if b15 is not None and len(b15) >= 4 else 0.0
    for sym in daftar:
        if now - st.get(sym, 0) < 7200:
            continue
        for iv, nama in (("15", "15 menit"), ("30", "30 menit")):
            m = _cek(_kline(sym, iv))
            if not m:
                continue
            st[sym] = now
            rc = _rencana(m)
            tick = (info.get(sym) or {}).get("tick")
            judul = (f"⚡ <b>{sym} {m['arah']} TAJAM</b> di candle {nama}: {m['pct']:+.1f}%, volume {m['vol']:.1f}x, "
                     f"tembus {'high' if m['arah'] == 'NAIK' else 'low'} 20 candle")
            if sym in posisi:
                lawan = (posisi[sym] == "LONG") != (m["arah"] == "NAIK")
                out.append(judul + ("\n↳ Posisi kamu searah, pertimbangkan geser SL ke entry." if not lawan else
                                    "\n↳ Posisi kamu BERLAWANAN, pertimbangkan kurangi risiko sekarang."))
                break
            sk, plus, minus = _nilai(sym, m, rc, info, btc15)
            if sk < MIN_SKOR:
                print(f"[MOMENTUM] {sym} {m['arah']} {nama} tidak dikirim, skor {sk}: {'; '.join(minus)}")
                break
            e, sl, t1, t2 = rc["entry"], rc["sl"], rc["tp1"], rc["tp2"]
            pc = lambda x: abs(x - e) / e * 100
            batas = time.strftime("%d/%m %H:%M WIB", time.gmtime(now + 7200 + 7 * 3600))
            out.append(
                judul + f"\n{'🟢' if rc['arah'] == 'LONG' else '🔴'} <b>SARAN {rc['arah']} {sym}</b> | skor {sk}/100, "
                + ("LAYAK BANGET DIIKUTI" if sk >= 80 else "LAYAK DIIKUTI")
                + f"\n<pre>LIMIT {_fp(e, tick)}\nSL    {_fp(sl, tick)}  -1.00R  -{pc(sl):.1f}%\n"
                f"TP1   {_fp(t1, tick)}  +1.00R  +{pc(t1):.1f}%\nTP2   {_fp(t2, tick)}  +2.00R  +{pc(t2):.1f}%</pre>\n"
                f"Yang bikin yakin: {'; '.join(plus)}\n"
                + (f"Yang perlu diwaspadai: {'; '.join(minus)}\n" if minus else "")
                + f"Jangan kejar harga. Pasang LIMIT di retest {_fp(e, tick)}, berlaku sampai {batas}. "
                f"Kalau belum terisi, batalkan. Pakai setengah lot karena ini sinyal TF kecil.")
            break
    with open(FILE + ".tmp", "w") as f:
        json.dump({k: v for k, v in st.items() if now - v < 86400}, f)
    os.replace(FILE + ".tmp", FILE)
    return out
