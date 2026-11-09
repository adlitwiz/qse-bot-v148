"""QSE v150 GZH PANTULAN PENDEK (9 Nov 2026, QC 53, riset/upgrade/hasil_v161.txt dan hasil_v161_gzh.txt).
Dugaan user benar: GZH lama minus karena TP terlalu jauh (titik 0 dan -0.236, tahan lama). Uji 152 koin 4J:
 GZH lama (SL ujung kaki + 0.2 ATR, TP 0/-0.236)  : uji 2025-2026 n 45, WR 38%, -8.9R
 GZH pantulan pendek (aturan di bawah)             : latih 2023-2024 n 200 WR 72% +43.7R, uji 2025-2026 n 182 WR 69% PF 1.70 +38.4R,
                                                     15 dari 21 bulan positif, bulan terburuk -2.4R, sekitar 1 sinyal per 4 hari.
Aturan: zigzag GZH depth 10, ambang 8 ATR. Sentuhan PERTAMA ke fib 0.618 dari sisi 0, candle 4J penyentuh tutup kembali di atas
0.618 (konfirmasi). LONG saja, BTC 4J di atas EMA 50. Entry harga tutup, SL 1 ATR di bawah entry, TP PENUH sejauh jarak entry ke fib 0.5 (pantulan),
paling lama 48 jam. SHORT, TP 0.382, TP 0.5R-0.8R, BE di 0.3R, dan gerbang kompas USDT.D diuji dan lebih jelek (lihat QC 53).
Peka parameter: ambang 6 ATR hanya impas, jadi lot 0.5x dan dicatat terpisah. Matikan: QSE_GZH2=0."""
import json
import os
import time

import numpy as np

from config import STATE_DIR

F = os.path.join(STATE_DIR, "gzh2.json")
DEPTH, THR, LOT, TAHAN_JAM = 10, 8.0, 0.5, 48
JAM = 3600


def _baca():
    try:
        with open(F) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": [], "kaki": {}}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(F + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(F + ".tmp", F)


def setup_terakhir(h, l, c):
    """Kalau candle terakhir (sudah tutup) adalah konfirmasi GZH pantulan LONG, return dict, kalau tidak None. Sama dengan uji."""
    import qse_pola as PL
    n = len(c)
    if n < 80:
        return None
    kaki, atr = PL._gz_pivots(h, l, c, DEPTH, THR)
    dipakai, t, hasil = set(), 1, None
    while t < n:
        k = kaki[t - 1]
        if not k or np.isnan(atr[t - 1]):
            t += 1
            continue
        start, end, i0 = k
        if (start, end) in dipakai or t <= i0:
            t += 1
            continue
        L = start > end
        e = PL._gz_level(start, end, 0.618)
        kena = (l[t] <= e < c[t - 1]) if L else (h[t] >= e > c[t - 1])
        if not kena:
            t += 1
            continue
        dipakai.add((start, end))
        if t == n - 1 and L and c[t] > e:
            a = float(atr[t - 1])
            # sama dengan uji: target = jarak entry ke fib 0.5 (kalau candle konfirmasi sudah tutup di atas 0.5, jarak itu dipakai ke atas)
            tp = c[t] + abs(PL._gz_level(start, end, 0.5) - c[t])
            if a > 0 and a <= 0.1 * c[t] and tp > c[t]:
                hasil = dict(entry=float(c[t]), sl=float(c[t] - a), tp=float(tp), atr=a, start=float(start), end=float(end))
        t += 1
    return hasil


def kartu(s, x):
    import qse_saya as SY
    t = SY.tick_of(None, x["entry"])
    r = (x["tp"] - x["entry"]) / (x["entry"] - x["sl"])
    try:
        import qse_modal as MD
        lot = MD.baris_lot(x["entry"], x["sl"], kelas="UTAMA")
    except Exception:
        lot = ""
    st = rapor()
    return (f"🟡 <b>GZH PANTULAN PENDEK: {s} LONG MARKET</b>\n"
            f"🌦 Cuaca: <b>↩️ RETRACEMENT</b> (koreksi ke fib 0.618 dalam tren, ambil pantulan cepat)\n"
            f"🏅 Rekam jejak aturan ini: uji 2025-2026 WR 69%, PF 1.70, +38R dari 182 sinyal (latih 2023-2024 WR 72%)"
            + (f"  ·  live {st['n']} trade WR {st['wr']:.0f}% {st['tot']:+.1f}R" if st["n"] else "") + "\n"
            + SY.blok_salin(x["entry"], x["sl"], x["tp"], x["tp"], "MARKET", t, sym=s, arah="LONG")
            + f"\n📲 TP PENUH di fib 0.5 (+{r:.2f}R), tutup semua di sana. SL 1 ATR. Paling lama {TAHAN_JAM} jam. 🟦 KELAS UTAMA."
            + ("\n" + lot if lot else ""))


def rapor():
    d = _baca()
    r = [c["R"] for c in d["closed"] if c.get("R") is not None]
    return dict(n=len(r), wr=(sum(1 for x in r if x > 0) / len(r) * 100) if r else 0.0, tot=sum(r))


def _kelola(d):
    import qse_strat as ST
    out = []
    for k, it in list(d["open"].items()):
        df = ST._k4(it["sym"], 30)
        if df is None:
            continue
        df = df[df.index > it["t_ms"]]
        R, why = None, ""
        risk = it["entry"] - it["sl"]
        for ts, row in df.iterrows():
            if row["low"] <= it["sl"]:
                R, why = -1.0, "SL kena"
                break
            if row["high"] >= it["tp"]:
                R, why = (it["tp"] - it["entry"]) / risk, "TP fib 0.5 kena"
                break
            if ts >= it["t_ms"] + TAHAN_JAM * JAM * 1000:
                R, why = (row["close"] - it["entry"]) / risk, f"{TAHAN_JAM} jam, tutup market"
                break
        if R is None:
            continue
        R -= 0.0011 * it["entry"] / risk
        d["open"].pop(k)
        d["closed"] = (d["closed"] + [dict(it, R=round(R, 3), why=why, selesai=time.time())])[-300:]
        out.append(f"{'✅' if R > 0 else '🛑'} 🟡 <b>GZH {it['sym']} LONG</b> selesai: {why}, {R:+.2f}R.")
    return out


def jalankan(simbol=None):
    """Dipanggil tiap menit. Kerja sekali sesudah candle 4J tutup (menit 2-14). Return list pesan."""
    if os.environ.get("QSE_GZH2", "1") == "0":
        return []
    now = time.time()
    c4 = int(now // 14400 * 14400)
    d = _baca()
    out = []
    try:
        out += _kelola(d)
    except Exception as ex:
        print("[WARN] gzh2 kelola", ex)
    if d.get("c4") == c4 or not (120 <= now - c4 <= 900):
        _tulis(d)
        return out
    d["c4"] = c4
    import qse_strat as ST
    bn = ST.btc_naik()
    if bn is False:
        d["catatan"] = "BTC 4J di bawah EMA 50, GZH pantulan diam"
        _tulis(d)
        return out
    if simbol is None:
        try:
            with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
                simbol = sorted({r["symbol"] for r in json.load(f)})
        except Exception:
            simbol = []
    for s in simbol:
        if any(it["sym"] == s for it in d["open"].values()):
            continue
        df = ST._k4(s, 400)
        if df is None or len(df) < 120:
            continue
        x = setup_terakhir(df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float))
        if not x:
            continue
        kunci = f"{s}|{x['start']:.10g}|{x['end']:.10g}"
        if kunci in d["kaki"]:
            continue
        d["kaki"][kunci] = int(now)
        t_ms = int(df.index[-1])
        d["open"][f"{s}|{t_ms}"] = dict(sym=s, t_ms=t_ms, t=now, **x)
        out.append(kartu(s, x))
    d["kaki"] = {k: v for k, v in d["kaki"].items() if now - v < 30 * 86400}
    _tulis(d)
    return out


def teks():
    d = _baca(); st = rapor()
    rows = ["🟡 <b>GZH PANTULAN PENDEK</b> (fib 0.618 lalu TP fib 0.5, LONG, BTC 4J di atas EMA 50)",
            f"Live: {st['n']} trade selesai, WR {st['wr']:.0f}%, total {st['tot']:+.2f}R. Posisi jalan {len(d['open'])}."]
    for it in d["open"].values():
        rows.append(f"• {it['sym']} LONG entry {it['entry']:.6g} SL {it['sl']:.6g} TP {it['tp']:.6g}")
    if d.get("catatan"):
        rows.append(d["catatan"])
    return "\n".join(rows)
