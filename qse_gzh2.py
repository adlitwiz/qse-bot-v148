"""QSE v150 GZH PANTULAN PENDEK (9 Nov 2026, QC 53, riset/upgrade/hasil_v161.txt dan hasil_v161_gzh.txt).
Dugaan user benar: GZH lama minus karena TP terlalu jauh (titik 0 dan -0.236, tahan lama). Uji 152 koin 4J:
 GZH lama (SL ujung kaki + 0.2 ATR, TP 0/-0.236)  : uji 2025-2026 n 45, WR 38%, -8.9R
 GZH pantulan pendek (aturan di bawah)             : latih 2023-2024 n 200 WR 72% +43.7R, uji 2025-2026 n 182 WR 69% PF 1.70 +38.4R,
                                                     15 dari 21 bulan positif, bulan terburuk -2.4R, sekitar 1 sinyal per 4 hari.
Aturan: zigzag GZH depth 10, ambang 8 ATR. Sentuhan PERTAMA ke fib 0.618 dari sisi 0, candle 4J penyentuh tutup kembali di atas
0.618 (konfirmasi). LONG saja, BTC 4J di atas EMA 50. Entry harga tutup, SL 1 ATR di bawah entry, TP PENUH sejauh jarak entry ke fib 0.5 (pantulan),
paling lama 48 jam. SHORT, TP 0.382, TP 0.5R-0.8R, BE di 0.3R, dan gerbang kompas USDT.D diuji dan lebih jelek (lihat QC 53).
Peka parameter: ambang 6 ATR hanya impas, jadi lot 0.5x dan dicatat terpisah. Matikan: QSE_GZH2=0.
v170 QC 64 (10 Nov 2026, riset/upgrade/run_v170_gzh.py, hasil_v170_gzh.txt): GZH DUA ARAH. Kunci mati saat BTC 4J < EMA 50 dihapus,
saat itu modul mencari SHORT. Cermin persis (sentuh 0.618, TP 0.5, SL 1 ATR) RUGI di semua gerbang (BTC: latih -0.281R, uji -0.121R;
BTC + kompas: uji -0.325R), jadi tidak dipakai. Dari 2916 kombinasi aturan x gerbang, 100 lolos latih dan hanya 7 untung di 2025
DAN 2026. Yang dipasang, satu-satunya keluarga yang positif di 2023, 2024, 2025, 2026:
 GZH SHORT pantulan dalam: zigzag depth 10 ambang 6 ATR, sentuhan PERTAMA ke fib 0.786, candle 4J tutup kembali di bawah 0.786,
 BTC 4J < EMA 50 dan koin di bawah EMA 200. Entry tutup, SL 1.5 ATR, TP PENUH 0.8R, paling lama 96 jam.
 latih n 80 rata +0.150R PF 1.43, uji n 133 WR 60% rata +0.057R PF 1.14 (2025 +5.6R, 2026 +2.0R). Tepi tipis: KELAS RINGAN.
Gerbang kompas FOKUS SHORT membuat hasil lebih jelek, jadi tidak dipakai. Matikan SHORT saja: QSE_GZH2_SHORT=0."""
import json
import os
import time

import numpy as np

from config import STATE_DIR

F = os.path.join(STATE_DIR, "gzh2.json")
DEPTH, THR, LOT, TAHAN_JAM = 10, 8.0, 0.5, 48
THR_S, FIB_S, SL_S, TP_S, TAHAN_S = 6.0, 0.786, 1.5, 0.8, 96          # QC 64: GZH SHORT pantulan dalam
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


def setup_short(h, l, c):
    """QC 64: konfirmasi GZH SHORT di candle terakhir (sentuh fib 0.786 dari bawah, tutup kembali di bawahnya, close < EMA 200)."""
    import qse_pola as PL
    import qse_strat as ST
    n = len(c)
    if n < 210:
        return None
    kaki, atr = PL._gz_pivots(h, l, c, DEPTH, THR_S)
    e200 = ST._ema(c, 200)
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
        e = PL._gz_level(start, end, FIB_S)
        kena = (l[t] <= e < c[t - 1]) if L else (h[t] >= e > c[t - 1])
        if not kena:
            t += 1
            continue
        dipakai.add((start, end))
        if t == n - 1 and (not L) and c[t] < e and c[t] < e200[t]:
            a = float(atr[t - 1])
            risk = SL_S * a
            if a > 0 and risk <= 0.1 * c[t]:
                hasil = dict(arah="SHORT", entry=float(c[t]), sl=float(c[t] + risk), tp=float(c[t] - TP_S * risk), atr=a,
                             start=float(start), end=float(end), tahan=TAHAN_S)
        t += 1
    return hasil


JEMBATAN_CANDLE = 48


def jembatan(sym, arah="LONG", now=None):
    """QC 69 (ide user, riset/upgrade/run_v171_saring.py): GZH sebagai jembatan koreksi follow the trend. True kalau ada sinyal jalur
    follow the trend searah (McGinley 34, RSI 50 + volume, EMA Cross) di koin ini dalam 48 candle 4J terakhir. Uji GZH LONG saat BTC 4J
    di atas EMA 50: dengan sinyal jalur sebelumnya 2023 +0.085R, 2024 +0.239R, 2025 +0.319R, 2026 +0.342R (n 16-31 per tahun, WR 61-81%).
    Tanpa: +0.365R, +0.149R, +0.248R, +0.020R. Lebih baik di 3 dari 4 tahun, sampel kecil, jadi hanya label, kelas tidak berubah."""
    try:
        import qse_strat as ST
        now = now or time.time()
        batas = now - JEMBATAN_CANDLE * 14400
        for k in ("mcginley", "rsi_vol", "ema_short"):
            d = ST.lihat(k)
            for it in list(d.get("open", {}).values()) + list(d.get("closed", []))[-300:]:
                if it.get("sym") == sym and it.get("arah") == arah and batas <= float(it.get("t", 0)) < now - 600:
                    return ST.STRAT.get(k, {}).get("nama", k)
    except Exception as ex:
        print("[WARN] gzh jembatan", ex)
    return None


def kartu(s, x):
    import qse_saya as SY
    if x.get("arah") == "SHORT":
        t = SY.tick_of(None, x["entry"])
        try:
            import qse_modal as MD
            lot = MD.baris_lot(x["entry"], x["sl"], kelas="RINGAN")
        except Exception:
            lot = ""
        st = rapor("SHORT")
        return (f"🟡 <b>GZH PANTULAN SHORT: {s} SHORT MARKET</b>\n"
                f"🌦 Cuaca: <b>↩️ RETRACEMENT TURUN</b> (BTC 4J di bawah EMA 50, koin di bawah EMA 200, pantulan naik ke fib 0.786 ditolak)\n"
                f"🏅 Rekam jejak aturan ini: uji 2025-2026 WR 60%, PF 1.14, +0.057R per trade dari 133 sinyal (latih PF 1.43). Tepi tipis"
                + (f"  ·  live {st['n']} trade WR {st['wr']:.0f}% {st['tot']:+.1f}R" if st["n"] else "") + "\n"
                + SY.blok_salin(x["entry"], x["sl"], x["tp"], x["tp"], "MARKET", t, sym=s, arah="SHORT")
                + f"\n📲 TP PENUH di +{TP_S:g}R, tutup semua di sana. SL {SL_S:g} ATR. Paling lama {TAHAN_S} jam. 🟨 KELAS RINGAN."
                + ("\n" + lot if lot else ""))
    t = SY.tick_of(None, x["entry"])
    r = (x["tp"] - x["entry"]) / (x["entry"] - x["sl"])
    try:
        import qse_modal as MD
        lot = MD.baris_lot(x["entry"], x["sl"], kelas="UTAMA")
    except Exception:
        lot = ""
    st = rapor()
    jb = jembatan(s, "LONG")
    return (f"🟡 <b>GZH PANTULAN PENDEK: {s} LONG MARKET</b>\n"
            + (f"🌉 <b>JEMBATAN TREN</b>: {jb} LONG sudah memberi sinyal di koin ini dalam 8 hari terakhir, ini koreksi ke fib 0.618 lalu lanjut tren. "
               f"Uji 2025-2026: WR 77%, +0.33R dari 44 sinyal (tanpa jembatan +0.17R)\n" if jb else "")
            + f"🌦 Cuaca: <b>↩️ RETRACEMENT</b> (koreksi ke fib 0.618 dalam tren, ambil pantulan cepat)\n"
            f"🏅 Rekam jejak aturan ini: uji 2025-2026 WR 69%, PF 1.70, +38R dari 182 sinyal (latih 2023-2024 WR 72%)"
            + (f"  ·  live {st['n']} trade WR {st['wr']:.0f}% {st['tot']:+.1f}R" if st["n"] else "") + "\n"
            + SY.blok_salin(x["entry"], x["sl"], x["tp"], x["tp"], "MARKET", t, sym=s, arah="LONG")
            + f"\n📲 TP PENUH di fib 0.5 (+{r:.2f}R), tutup semua di sana. SL 1 ATR. Paling lama {TAHAN_JAM} jam. 🟦 KELAS UTAMA."
            + ("\n" + lot if lot else ""))


def rapor(arah=None):
    d = _baca()
    r = [c["R"] for c in d["closed"] if c.get("R") is not None and (arah is None or c.get("arah", "LONG") == arah)]
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
        S = it.get("arah") == "SHORT"
        dd = -1 if S else 1
        risk = abs(it["entry"] - it["sl"])
        tahan = it.get("tahan", TAHAN_JAM)
        for ts, row in df.iterrows():
            if (row["high"] >= it["sl"]) if S else (row["low"] <= it["sl"]):
                R, why = -1.0, "SL kena"
                break
            if (row["low"] <= it["tp"]) if S else (row["high"] >= it["tp"]):
                R, why = abs(it["tp"] - it["entry"]) / risk, "TP kena"
                break
            if ts >= it["t_ms"] + tahan * JAM * 1000:
                R, why = (row["close"] - it["entry"]) * dd / risk, f"{tahan} jam, tutup market"
                break
        if R is None:
            continue
        R -= 0.0011 * it["entry"] / risk
        d["open"].pop(k)
        d["closed"] = (d["closed"] + [dict(it, R=round(R, 3), why=why, selesai=time.time())])[-300:]
        out.append(f"{'✅' if R > 0 else '🛑'} 🟡 <b>GZH {it['sym']} {it.get('arah', 'LONG')}</b> selesai: {why}, {R:+.2f}R.")
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
    cari_short = bn is False          # QC 64: tidak lagi diam, BTC 4J di bawah EMA 50 = cari GZH SHORT
    if cari_short and os.environ.get("QSE_GZH2_SHORT", "1") == "0":
        d["catatan"] = "BTC 4J di bawah EMA 50, GZH SHORT dimatikan (QSE_GZH2_SHORT=0)"
        _tulis(d)
        return out
    d["catatan"] = "BTC 4J di bawah EMA 50: mode GZH SHORT (fib 0.786, kelas ringan)" if cari_short else ""
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
        x = (setup_short if cari_short else setup_terakhir)(df["high"].values.astype(float), df["low"].values.astype(float),
                                                            df["close"].values.astype(float))
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
    ss = rapor("SHORT")
    rows = ["🟡 <b>GZH PANTULAN DUA ARAH</b> (BTC 4J di atas EMA 50: LONG fib 0.618 lalu TP fib 0.5. Di bawah EMA 50: SHORT fib 0.786, TP 0.8R, kelas ringan)",
            f"Live: {st['n']} trade selesai, WR {st['wr']:.0f}%, total {st['tot']:+.2f}R (SHORT {ss['n']} trade {ss['tot']:+.2f}R). Posisi jalan {len(d['open'])}."]
    for it in d["open"].values():
        rows.append(f"• {it['sym']} {it.get('arah', 'LONG')} entry {it['entry']:.6g} SL {it['sl']:.6g} TP {it['tp']:.6g}")
    if d.get("catatan"):
        rows.append(d["catatan"])
    return "\n".join(rows)
