"""QSE v148 - JALUR STRATEGI TAMBAHAN yang lolos uji 14 strategi umum (candle 4J, 111 koin perp, Jul 2020 - Okt 2026).
Aturan dipilih dari data 2020-2023, lalu diuji di 2024-2026 tanpa diubah. Biaya 0.15%. Maks 8 posisi per jalur.
Yang lolos dan dipasang:
  ema_short : EMA 20 memotong EMA 50 ke bawah, close di bawah EMA 200, BTC 4J di bawah EMA 50. Hanya SHORT.
              1812 trade, WR 42%, PF 1.42 (2020-23 PF 1.37, 2024-26 PF 1.47), turun terdalam 16%, untung tiap tahun.
  rsi_vol   : RSI 14 memotong 50 searah tren (close dan EMA 50 di sisi yang sama dari EMA 200), volume candle masuk
              20% tertinggi dari 100 candle, koin 30 paling likuid. LONG dan SHORT.
              2380 trade, WR 40%, PF 1.34 (2020-23 PF 1.26, 2024-26 PF 1.45), turun terdalam 15%, positif 21 dari 26 kuartal.
Keluar (sama dengan Ichimoku): SL awal 2 ATR, tiap candle 4J tutup SL digeser ke puncak - 3 ATR, tutup paksa 60 candle. Angka per jalur bisa beda, lihat cfg sl_atr dan trail_atr.
Yang gagal: Donchian 20/55, Supertrend, Bollinger squeeze, Bollinger dan RSI 2 mean reversion, pullback 3 candle,
inside bar, momentum 30 hari, funding ekstrem (searah atau lawan), breakout volume (lolos per trade tapi tidak di portofolio)."""
import fcntl
import json
import os
import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import bybit_fetch as B
import telegram_notify as TG
from config import STATE_DIR

H4 = 4 * 3600 * 1000
# SL dan keluar per jalur (19 Okt 2026). Grid SL 1.5/2/2.5/3 ATR x trailing atau TP 2/3/4, dipilih di 2020-2023, dicek di
# 2024-2026 dan data lama 2017-2020. Rata R per trade naik di ketiga periode untuk:
# EMA SHORT SL 1.5 trailing 4 (+0.30 -> +0.54R di 2017-20, +0.11 -> +0.18R di 2024-26), McGinley SL 1.5 TP 4R,
# MSB trailing 4. RSI, SMC, SnR tetap (rasio profit/drawdown tidak naik). SL/TP per koin juga diuji, tidak lebih baik.
SL_ATR, TRAIL_ATR, MAKS_BAR = 2.0, 3.0, 60
MAKS_BARU, MAKS_BUKA, TOP_KOIN = 5, 8, 150
BIAYA = 0.0015
TELAT_ATR = 0.5
STRAT = {
    "ema_short": dict(nama="EMA Cross 20/50 SHORT", likuid=0, sl_atr=1.5, trail_atr=4.0,
                      bt="uji 6 tahun 111 koin: 1812 trade, PF 1.42, uji ulang 2024-2026 PF 1.47, untung tiap tahun",
                      kenapa=["EMA 20 baru memotong EMA 50 ke bawah: momentum turun mulai",
                              "Harga di bawah EMA 200: tren besar turun",
                              "BTC 4J di bawah EMA 50: pasar ikut menekan"]),
    "rsi_vol": dict(nama="RSI 50 + Volume", likuid=30,
                    bt="uji 6 tahun 111 koin, 30 paling likuid: 2380 trade, PF 1.34, uji ulang 2024-2026 PF 1.45",
                    kenapa=["RSI 14 baru melewati 50 searah tren besar (EMA 50 dan harga di sisi yang sama dari EMA 200)",
                            "Volume candle masuk 20% tertinggi dari 100 candle: dorongan nyata",
                            "Koin termasuk 30 paling likuid"]),
    "GZH": dict(nama="GZH Golden Zone", likuid=0, manual=True,
                bt="uji 6 tahun 111 koin, maks 8 posisi: 1825 trade, WR 40%, PF 1.24, 2020-2023 PF 1.24, uji ulang 2024-2026 PF 1.23",
                kenapa=["Sentuhan pertama fib 0.618 lalu candle 4J tutup memantul",
                        "Searah tren besar (EMA 200) dan searah BTC 4J"]),
    "snr_vol": dict(nama="SnR Pantul + Volume", likuid=30, tp_r=3.0, maks_bar=45,
                    bt="uji 6 tahun 111 koin, 30 paling likuid, maks 8 posisi: 692 trade, WR 39%, PF 1.33, 2020-2023 PF 1.26, uji ulang 2024-2026 PF 1.43",
                    kenapa=["Pivot support/resistance 20 candle baru terkonfirmasi, harga memantul darinya",
                            "Searah tren besar (EMA 200) dan searah BTC 4J",
                            "Volume candle masuk 20% tertinggi dari 100 candle"]),
    "msb_hpz": dict(nama="MSB LuxAlgo HPZ", likuid=30, trail_atr=4.0, trail_pct_2r=0.05,
                    bt="uji 6 tahun 111 koin, 30 paling likuid, maks 8 posisi: 2783 trade, WR 37%, PF 1.27, 2020-2023 PF 1.32, uji ulang 2024-2026 PF 1.21",
                    kenapa=["Market structure break: close menembus pivot 7 candle dengan momentum kuat",
                            "Skor zona di atas 80 (HPZ): momentum dan volume besar",
                            "Searah tren besar (EMA 200)"]),
    "smc_choch": dict(nama="SMC CHoCH searah tren", likuid=30, tp_r=3.0, maks_bar=45,
                      bt="uji 111 koin 2020-2026, 30 paling likuid, maks 8 posisi: 2929 trade, WR 38%, PF 1.25 (2020-2023 PF 1.30, 2024-2026 PF 1.19), data lama 2017-2020 PF 1.40",
                      kenapa=["Change of Character (CHoCH) struktur internal: arah kecil berbalik",
                              "Searah tren besar (EMA 200)"]),
    "mcginley": dict(nama="McGinley 34 + Volume", likuid=0, sl_atr=1.5, tp_r=4.0, maks_bar=45,
                     bt="uji 6 tahun 111 koin, maks 8 posisi: 3328 trade, WR 40%, PF 1.24, 2020-2023 PF 1.26, uji ulang 2024-2026 PF 1.23, data lama 2017-2020 PF 1.10",
                     kenapa=["Harga baru menembus McGinley Dynamic 34: arah jangka menengah berbalik",
                             "Searah tren besar: harga di sisi yang sama dari EMA 200",
                             "Volume candle masuk 20% tertinggi dari 100 candle: dorongan nyata"]),
}


def _file(k):
    return os.path.join(STATE_DIR, f"strat_{k}.json")


def _ubah(k, fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    f_ = _file(k)
    with open(f_ + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(f_) as f:
                d = json.load(f)
        except Exception:
            d = {"open": {}, "closed": []}
        hasil = fn(d)
        d["closed"] = d["closed"][-500:]
        with open(f_ + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(f_ + ".tmp", f_)
        return hasil


def lihat(k):
    try:
        with open(_file(k)) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values


def _atr(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    return _rma(np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))), 14)


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = _rma(np.maximum(d, 0), n), _rma(np.maximum(-d, 0), n)
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))


def _mcginley(c, n=34, k=0.6):
    md = np.empty(len(c))
    md[0] = c[0]
    for i in range(1, len(c)):
        # pembagi minimal 1 supaya McGinley tidak melompati harga (rumus asli tidak stabil saat harga jauh dari garis)
        md[i] = md[i - 1] + (c[i] - md[i - 1]) / max(k * n * (c[i] / md[i - 1]) ** 4, 1.0)
    return md


def sinyal(df, btc_naik):
    """Cek candle tutup terakhir untuk semua strategi. Return dict kunci -> (arah, atr). Aturan persis backtest."""
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    i = len(c) - 1
    if i < 260:
        return {}
    a = _atr(h, l, c)
    e20, e50, e200 = _ema(c, 20), _ema(c, 50), _ema(c, 200)
    out = {}
    if e20[i] < e50[i] and e20[i - 1] >= e50[i - 1] and c[i] < e200[i] and btc_naik is False:
        out["ema_short"] = ("SHORT", float(a[i]))
    r = _rsi(c)
    vp = (v[i - 100:i] <= v[i]).mean() * 100
    if vp >= 80:
        if r[i] > 50 and r[i - 1] <= 50 and c[i] > e200[i] and e50[i] > e200[i]:
            out["rsi_vol"] = ("LONG", float(a[i]))
        elif r[i] < 50 and r[i - 1] >= 50 and c[i] < e200[i] and e50[i] < e200[i]:
            out["rsi_vol"] = ("SHORT", float(a[i]))
    md = _mcginley(c[-600:])          # sama dengan backtest: dihitung dari 600 candle terakhir
    md = np.r_[np.full(len(c) - len(md), np.nan), md]
    if vp >= 80:
        if c[i] > md[i] and c[i - 1] <= md[i - 1] and c[i] > e200[i]:
            out["mcginley"] = ("LONG", float(a[i]))
        elif c[i] < md[i] and c[i - 1] >= md[i - 1] and c[i] < e200[i]:
            out["mcginley"] = ("SHORT", float(a[i]))
    # SnR, MSB, SMC dari dua script TradingView, fungsi deteksi sama persis dengan backtest (qse_smccore)
    try:
        import qse_smccore as K
        searah = lambda ar: (c[i] > e200[i]) == (ar == 1)
        for x in K.snr(h, l, c, 20):
            if x[0] == i and searah(x[1]) and vp >= 80 and btc_naik is not None and btc_naik == (x[1] == 1):
                out["snr_vol"] = ("LONG" if x[1] == 1 else "SHORT", float(a[i]))
        vpa = K.volpct(v)
        for x in K.msb(o, h, l, c, v, 7, 0.5, vpa):
            if x[0] == i and x[5]["skor"] > 80 and searah(x[1]):
                out["msb_hpz"] = ("LONG" if x[1] == 1 else "SHORT", float(a[i]))
        for x in K.smc(o, h, l, c, 5, 50):
            if x[0] == i and x[5]["tag"] == "choch" and searah(x[1]):
                out["smc_choch"] = ("LONG" if x[1] == 1 else "SHORT", float(a[i]))
    except Exception as ex:
        print("[WARN] smc/snr/msb", ex)
    return out


def _k4(sym, bars=600):
    try:
        df = B._raw(sym, "240", bars)
        now = int(time.time() * 1000)
        return df[df.index + H4 <= now]
    except Exception as ex:
        print(f"[WARN] strat {sym}: {ex}")
        return None


def _kelola(it, df):
    """Sama dengan backtest: SL dicek dulu, lalu puncak dan SL berjalan trail_atr (bawaan 3 ATR), tutup paksa 60 candle."""
    L = it["arah"] == "LONG"
    e, risk = it["entry"], it["risk"]
    a = _atr(df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float))
    sl_lama = it["sl"]
    for k, ts in enumerate(df.index):
        if ts <= it["last"]:
            continue
        hi, lo, cl = float(df["high"].iloc[k]), float(df["low"].iloc[k]), float(df["close"].iloc[k])
        if (lo <= it["sl"]) if L else (hi >= it["sl"]):
            return "SL", ((it["sl"] - e) if L else (e - it["sl"])) / risk - BIAYA * e / risk, sl_lama
        if it.get("tp"):          # jalur TP tetap (McGinley): TP tidak dicek di candle masuk, sama dengan backtest
            if it["bar"] > 0 and ((hi >= it["tp"]) if L else (lo <= it["tp"])):
                return "TP", abs(it["tp"] - e) / risk - BIAYA * e / risk, sl_lama
            it["bar"] += 1
            it["last"] = int(ts)
            it["close"] = cl
            if it["bar"] >= it.get("maks_bar", MAKS_BAR):
                return "WAKTU", ((cl - e) if L else (e - cl)) / risk - BIAYA * e / risk, sl_lama
            continue
        if L:
            it["best"] = max(it["best"], hi)
            it["sl"] = max(it["sl"], it["best"] - it.get("trail_atr", TRAIL_ATR) * a[k])
        else:
            it["best"] = min(it["best"], lo)
            it["sl"] = min(it["sl"], it["best"] + it.get("trail_atr", TRAIL_ATR) * a[k])
        tp2 = it.get("trail_pct_2r")
        if tp2 and abs(it["best"] - e) >= 2 * risk:
            # MSB: setelah untung berjalan 2R, trailing pindah ke 5% harga. Uji 2021-2026 data 1 jam: rata hasil MSB
            # 0.13 -> 0.24R (2021-23) dan 0.10 -> 0.14R (2024-26). Jalur lain tidak konsisten, pemicu +5% harga lebih buruk
            it["sl"] = max(it["sl"], it["best"] - tp2 * e) if L else min(it["sl"], it["best"] + tp2 * e)
        it["bar"] += 1
        it["last"] = int(ts)
        it["close"] = cl
        if it["bar"] >= MAKS_BAR:
            return "WAKTU", ((cl - e) if L else (e - cl)) / risk - BIAYA * e / risk, sl_lama
    return "BUKA", None, sl_lama


def _catat_ledger(k, it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur=k, sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl0"], tp1=0.0, tp2=0.0,
                                t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"], selesai=time.time(), ket="trailing"))
    CT._ubah(f)


def rem(k):
    eq = peak = 0.0
    rugi = 0
    for c in sorted(lihat(k).get("closed", []), key=lambda c: c.get("selesai", 0)):
        r = float(c.get("R", 0))
        eq += r
        peak = max(peak, eq)
        rugi = rugi + 1 if r < 0 else 0
    if peak - eq > 16:
        return f"hasil jalur ini turun {peak - eq:.0f}R dari puncak"
    if rugi >= 6:
        return f"rugi {rugi} kali beruntun"
    return ""


def izin_btc():
    """Izin arah dari BTC 4J, rumus sama dengan mesin robot (qse_features): LONG ditahan saat BTC turun (close < EMA20 < EMA50)
    dan candle terakhir merah, SHORT ditahan saat BTC naik dan candle terakhir hijau. Return dict LONG/SHORT -> bool."""
    df = _k4("BTCUSDT", 600)
    if df is None or len(df) < 60:
        return {"LONG": True, "SHORT": True}
    import qse_ta as T
    c = df["close"].values.astype(float)[:-1]          # sama dengan izin di laporan robot: candle BTC sebelum candle sinyal
    e20, e50 = T.ema(c, 20), T.ema(c, 50)
    up, dn, mom = c[-1] > e20[-1] > e50[-1], c[-1] < e20[-1] < e50[-1], c[-1] > c[-2]
    return {"LONG": not (dn and not mom), "SHORT": not (up and mom)}


BTC_BAND, BTC_KONF = 0.3, 2      # arah BTC resmi pindah setelah 2 candle 4J tutup lebih dari 0.3% di sisi lain EMA 50


def btc_arah_resmi(c, e):
    """Arah BTC terhadap EMA 50 dengan batas toleransi. Uji 2021-2026: pindah sisi tanpa batas 3.2 kali seminggu dan
    47% balik lagi dalam 12 jam (palsu). Batas 0.3% dan 2 candle: 1.5 kali seminggu, balik lagi 8%. Return True naik."""
    st, cnt = None, 0
    for i in range(max(60, len(c) - 300), len(c)):
        d = (c[i] - e[i]) / e[i] * 100
        sd = True if d > BTC_BAND else False if d < -BTC_BAND else None
        if sd is None:
            cnt = 0
            continue
        if st is None:
            st = sd
        elif sd != st:
            cnt += 1
            if cnt >= BTC_KONF:
                st, cnt = sd, 0
        else:
            cnt = 0
    return bool(c[-1] > e[-1]) if st is None else st


def btc_ema50_teks():
    """Info saja: arah BTC 4J terhadap EMA 50 dengan batas toleransi. Tidak dipakai menyaring sinyal."""
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return ""
    c = df["close"].values.astype(float)
    ee = _ema(c, 50)
    e = float(ee[-1])
    naik = btc_arah_resmi(c, ee)
    teks = (f"{'🟢' if naik else '🔴'} BTC 4J condong {'LONG' if naik else 'SHORT'} "
            f"(close {c[-1]:,.0f}, EMA 50 {e:,.0f}, {(c[-1] / e - 1) * 100:+.1f}%)")
    if (c[-1] > e) != naik or abs(c[-1] / e - 1) * 100 <= BTC_BAND:
        teks += (f". Harga masih menempel EMA 50, arah belum berubah sampai 2 candle 4J tutup lebih dari "
                 f"{BTC_BAND:g}% di sisi lain")
    return teks


def btc_naik():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return None
    c = df["close"].values.astype(float)
    return bool(c[-1] > _ema(c, 50)[-1])


def mutu(df, arah):
    """Kondisi candle sinyal (candle 4J tutup terakhir) yang menaikkan kualitas. Return (jumlah plus, plus, []).
    Uji 2021-2026 35 ribu sinyal jalur terbukti, 22 kondisi klasik diuji, dipilih di 2021-2023. Yang menaikkan PF:
    jebakan false breakout arah lawan, harga di atas channel regresi searah, histogram MACD searah, ADX di bawah 20.
    3 kondisi atau lebih: PF 1.37 (2021-23 1.29, 2024-26 1.45), 2.3 sinyal per hari, jadi label MUTU TINGGI.
    Kondisi minus (ADX di atas 25, angka bulat menghadang dalam 1R, tembus tipis, sisi lawan channel, MACD searah nol)
    hanya dipakai menyaring sinyal impas lewat mutu_buang."""
    o, h, l, c = (df[k].values.astype(float) for k in ("open", "high", "low", "close"))
    if len(c) < 120:
        return 0, [], []
    d = 1 if arah == "LONG" else -1
    tr = np.r_[h[0] - l[0], np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))]
    sm = lambda x: pd.Series(x).ewm(alpha=1 / 14, adjust=False).mean().values
    A = np.maximum(sm(tr), 1e-12)
    px = c[-1]
    plus = []
    hh, ll = h[-21:-1].max(), l[-21:-1].min()
    if (l[-1] < ll and px > ll) if d == 1 else (h[-1] > hh and px < hh):
        plus.append("false breakout arah lawan (jebakan)")
    y = c[-100:]
    x = np.arange(100)
    b1, b0 = np.polyfit(x, y, 1)
    res = y - (b0 + b1 * x)
    if res[-1] / (res.std() or 1e-9) * d > 1:
        plus.append("harga di atas channel searah")
    e = lambda v, n: pd.Series(v).ewm(span=n, adjust=False).mean().values
    m = e(c, 12) - e(c, 26)
    if (m - e(m, 9))[-1] * d > 0:
        plus.append("histogram MACD searah")
    up = np.r_[0, h[1:] - h[:-1]]
    dn = np.r_[0, l[:-1] - l[1:]]
    pdi = 100 * sm(np.where((up > dn) & (up > 0), up, 0)) / A
    mdi = 100 * sm(np.where((dn > up) & (dn > 0), dn, 0)) / A
    adx = sm(100 * abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9))[-1]
    minus = []
    if adx < 20:
        plus.append(f"ADX {adx:.0f} (tren belum ramai)")
    elif adx > 25:
        minus.append(f"ADX {adx:.0f} (tren sudah ramai)")
    step = 10 ** np.floor(np.log10(px)) / 2
    nxt = (np.floor(px / step) + 1) * step if d == 1 else (np.ceil(px / step) - 1) * step
    if abs(nxt - px) <= 1.5 * A[-1]:
        minus.append(f"angka bulat {nxt:g} menghadang dalam 1R")
    lebih = (px - (hh if d == 1 else ll)) * d
    if 0 < lebih < 0.25 * A[-1]:
        minus.append("tembus level 20 candle terlalu tipis")
    if res[-1] / (res.std() or 1e-9) * d < -1:
        minus.append("harga di sisi lawan channel")
    if m[-1] * d > 0:
        minus.append("MACD sudah di sisi searah nol")
    return len(plus), plus, minus


def pump_tolak(df, arah):
    """SHORT pada koin yang naik lebih dari 30% dalam 30 hari (180 candle 4J) dilewati. Uji 2021-2026 semua jalur:
    SHORT seperti ini PF 0.80 (2021-23) dan 0.79 (2024-26). Dibuang: total naik +28R dan +17R, PF naik di dua periode.
    Return teks alasan atau ''."""
    try:
        if arah != "SHORT" or df is None or len(df) < 181:
            return ""
        c = df["close"].astype(float)
        r30 = float(c.iloc[-1]) / float(c.iloc[-181]) - 1
        return f"koin sudah naik {r30 * 100:.0f}% dalam 30 hari, SHORT melawan pump" if r30 > 0.30 else ""
    except Exception:
        return ""


def mutu_buang(plus, minus):
    """Saring sinyal impas: minus lebih banyak 2 dari plus. Uji 2021-2026 kelompok ini PF 0.97 (2021-23 0.94,
    2024-26 1.00), sekitar 14% sinyal. Sisa sinyal PF 1.31. Return alasan atau ''."""
    return ", ".join(minus) if len(plus) - len(minus) <= -2 else ""


def mutu_teks(it):
    if len(it.get("mutu_plus") or []) >= 3:
        return [f"💎 <b>MUTU TINGGI</b>: {', '.join(it['mutu_plus'])}. Uji 2021-2026 PF 1.37"]
    return []


TELAT_JALUR = {"ema_short", "rsi_vol", "mcginley", "snr_vol", "smc_choch", "ichimoku"}
# Umur maksimal sinyal (candle 4J) selama harga masih dalam 0.5R. Uji ulang 26 Okt 2026 (2021-23 / 2024-26, entry di candle ke):
# EMA 3-4 1.33/1.23, 5-6 1.37/1.26, 7-8 1.44/1.29. McGinley 1.30/1.17, 1.26/1.11, 1.43/1.14. RSI 1.29/1.35, 1.15/1.37, 1.28/1.50.
# SnR 1.19/1.42, 1.24/1.30, 7-8 0.99/1.38. SMC 3-4 1.16/1.06 (lemah), MSB 5-6 0.97. Jadi EMA, McGinley, RSI 8 candle (32 jam),
# SnR 6 candle (24 jam), SMC dan Ichimoku tetap 2 candle, lainnya 1 candle.
UMUR_JALUR = {"ema_short": 8.1, "mcginley": 8.1, "rsi_vol": 8.1, "snr_vol": 6.1, "smc_choch": 2.1, "ichimoku": 2.1}


def umur_maks(k):
    return UMUR_JALUR.get(k, 1.0)


def batas_masuk(it, k):
    """Rentang harga dan batas waktu sinyal MARKET masih boleh diikuti. Uji entry telat 2020-2026: harga dalam 0.5R
    dari entry robot dan maks 2 candle 4J masih untung (EMA 1.22/1.24, RSI 1.21/1.39, McGinley 1.14/1.27, SnR 1.29/1.46,
    SMC 1.19/1.12, Ichimoku 1.16/1.23). MSB, Order Block, GZH hanya sampai candle 4J berikutnya tutup.
    Return (bawah, atas, batas_detik) atau None."""
    try:
        risk = it.get("risk") or abs(it["entry"] - it.get("sl0", it["sl"]))
        if not risk:
            return None
        akhir = it.get("t", time.time()) + 14400 * umur_maks(k)      # sama dengan aturan pesan 4J
        return it["entry"] - 0.5 * risk, it["entry"] + 0.5 * risk, akhir
    except Exception:
        return None


# Lama trade di uji 2021-2026 (jam, median): (yang kalah, yang menang)
LAMA_JALUR = {"ema_short": (48, 124), "ichimoku": (44, 100), "mcginley": (52, 180), "msb_hpz": (36, 84), "orderblock": (108, 240),
              "rsi_vol": (44, 112), "smc_choch": (52, 180), "snr_vol": (52, 180), "GZH": (48, 108)}


def _hari(j):
    return f"{j / 24:.0f} hari" if j >= 36 else f"{j:.0f} jam"


def batas_masuk_teks(it, k, fmt=None):
    b = batas_masuk(it, k)
    if not b:
        return []
    fmt = fmt or TG.fp
    t = it.get("tick", 0.0001)
    jam = time.strftime("%d/%m %H:%M", time.gmtime(b[2] + 7 * 3600))
    out = [f"🎯 Entry valid {fmt(b[0], t)} sampai {fmt(b[1], t)}, berlaku sampai {jam} WIB. Lewat itu, lewati"]
    lm = LAMA_JALUR.get(k)
    if lm:
        out.append(f"⏳ Lama trade (uji): kalau kalah biasanya selesai ±{_hari(lm[0])}, kalau menang ±{_hari(lm[1])}")
    return out


# Uji 2021-2026 (dev 2021-23 / uji 2024-26): dari trade yang sudah +2R, berapa persen selesai di +2R atau lebih.
# Tinggi di kedua periode = jangan TP manual, tahan sampai TP jalur.
TAHAN_TP = {"snr_vol": "70%", "smc_choch": "68%", "orderblock": "59%", "mcginley": "58%"}


def kunci_jalur(j):
    """'saran snr_vol' atau 'snr_vol' -> 'snr_vol'."""
    return (j or "").replace("saran ", "").strip()


def tp_cepat_teks(it, fmt=None, k=None):
    """Jalur TAHAN_TP: peringatan jangan TP manual. Jalur lain: TP bertahap 25% di +1R, 50% di +2R, sisa ikut jalur.
    Uji 2021-2026 39 ribu trade TP bertahap: WR 43% lawan 38%, PF 1.26 lawan 1.31 (dev 1.25, uji 1.27)."""
    try:
        fmt = fmt or TG.fp
        risk = abs(it["entry"] - it.get("sl0", it["sl"]))
        if not risk:
            return []
        L = it.get("arah", "LONG") == "LONG"
        t = it.get("tick", 0.0001)
        kk = kunci_jalur(k)
        if it.get("combo_fix"):
            return ["⛔ <b>Tahan sampai TP</b>, jangan TP manual (COMBO FIX)"]
        if kk in TAHAN_TP:
            return ["⛔ <b>Tahan sampai TP</b>, jangan TP manual"]
        r1 = it["entry"] + risk if L else it["entry"] - risk
        r2 = it["entry"] + 2 * risk if L else it["entry"] - 2 * risk
        return [f"💰 TP bertahap: 25% di {fmt(r1, t)}, 50% di {fmt(r2, t)}, sisa ikut jalur"]
    except Exception:
        return []


# PF uji per jalur (kartu masing-masing), dipakai mengurutkan sinyal setelah jumlah label
PF_JALUR = {"tt": 1.47, "orderblock": 1.45, "ema_short": 1.42, "rsi_vol": 1.34, "snr_vol": 1.33, "ichimoku": 1.29,
            "msb_hpz": 1.27, "smc_choch": 1.25, "mcginley": 1.24, "GZH": 1.24}


_VOLP = {}


def vol_pasar():
    """Volume BTC candle 4J terakhir yang sudah tutup dibagi rata-rata 180 candle (30 hari). Disimpan per candle."""
    t4 = int(time.time() // 14400)
    if t4 in _VOLP:
        return _VOLP[t4]
    x = None
    try:
        df = _k4("BTCUSDT", 200)
        v = df["volume"].astype(float)
        if len(v) >= 180:
            x = float(v.iloc[-1] / v.iloc[-180:].mean())
    except Exception as ex:
        print("[WARN] volume pasar", ex)
    _VOLP.clear()
    _VOLP[t4] = x
    return x


def vol_tinggi():
    """Label VOLUME PASAR TINGGI: volume BTC 4J di atas 2.5x rata 30 hari. Uji 2021-2026 sinyal jalur terbukti di candle
    seperti ini (19% sinyal): PF 1.66 (2021-23) dan 1.86 (2024-26), WR 45/48%, combo 3+ di saat itu PF 1.88/1.99.
    Konsisten di hampir semua jalur (SnR 0.98/1.41 paling lemah)."""
    x = vol_pasar()
    return round(x, 1) if x and x > 2.5 else None


# MODE PROFIT (/mode profit): hanya kirim sinyal dengan skor label 5 ke atas. Uji 2021-2026 semua sinyal jalur:
# skor >=5 PF 1.65 (2021-23) dan 1.77 (2024-26), WR 44/45%, 2.1-2.5 sinyal per hari, drawdown 98/118R
# lawan semua sinyal PF 1.24/1.28, 15-18 per hari, drawdown 383/651R. Skor >=8 PF 2.25/2.22 tapi 0.3-0.5 per hari.
MODE_MIN = {"semua": 0, "seimbang": 3, "profit": 5, "raja": 8}


def mode_sinyal():
    """Otomatis mode seimbang (skor label 3 ke atas). Uji 2021-2026: PF 1.43 dan 1.55 (dengan label BTC.D TURUN 26 Okt:
    PF 1.42 dan 1.57, total R naik 17-19%, hari ada sinyal 88% dan 85%), rasio profit/drawdown 6.7 dan 6.3,
    hari tanpa sinyal 17%, total R hampir 2x skor 5+ (PF 1.65/1.77, rasio 6.5/7.1, tapi 50% hari kosong, terpanjang 14 hari).
    Semua sinyal: PF 1.24/1.28, rasio 5.1/4.0. File mode_sinyal.json hanya dipakai kalau sengaja diubah."""
    try:
        with open(os.path.join(STATE_DIR, "mode_sinyal.json")) as f:
            m = json.load(f).get("mode", "seimbang")
        return m if m in MODE_MIN else "seimbang"
    except Exception:
        return "seimbang"


def set_mode(m):
    m = (m or "").lower()
    if m not in MODE_MIN:
        return None
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "mode_sinyal.json"), "w") as f:
        json.dump({"mode": m}, f)
    return m


def lolos_mode(pr):
    """pr = hasil prioritas(). True kalau skor label cukup untuk mode sekarang."""
    return pr[0] >= MODE_MIN[mode_sinyal()]


def prioritas(k, it):
    """Kunci urut sinyal: jumlah label terbukti dulu (COMBO, COMBO 3+, MUTU TINGGI, PULLBACK), lalu PF jalur.
    Label: combo 3+ PF 1.40, mutu tinggi PF 1.37, McGinley pullback PF 1.43, semua di atas PF jalur mana pun tanpa label."""
    n = (5 if it.get("combo_raja") else 0) + (3 if it.get("combo_fix") else 0) + (2 if it.get("combo_emas") else 0)
    cb = len(it.get("combo") or [])
    n += (1 if cb >= 1 else 0) + (1 if cb >= 2 else 0)
    n += 1 if len(it.get("mutu_plus") or []) >= 3 else 0
    n += 1 if it.get("pullback") else 0
    n += 2 if it.get("vol_tinggi") else 0
    return (_tambah_dom(n, it.get("dom_turun")), PF_JALUR.get(k, 1.2))


def _tambah_dom(n, dom):
    """BTC.D TURUN +2 skor, tapi tidak mengangkat ke NILAI 10 sendirian. Uji 2021-2026 dengan batas ini: NILAI 8 PF 1.30/1.44,
    NILAI 9 PF 1.50/1.73, NILAI 10 tetap 2.25/2.22. Tanpa batas NILAI 10 turun ke 1.72/1.95."""
    return max(n, min(n + 2, 7)) if dom else n


def prioritas_teks(k, m):
    """Prioritas dari teks kartu (dipakai listener yang menerima kartu jadi)."""
    import re
    g = re.search(r"COMBO (\d+)", m)
    cb = int(g.group(1)) - 1 if g else 0
    n = (1 if cb >= 1 else 0) + (1 if cb >= 2 else 0) + (1 if "MUTU TINGGI" in m else 0) + (1 if "PULLBACK" in m else 0) \
        + (2 if "COMBO EMAS" in m else 0) + (3 if "COMBO FIX PROFIT" in m else 0) + (5 if "COMBO RAJA" in m else 0) \
        + (2 if "VOLUME PASAR TINGGI" in m else 0)
    return (_tambah_dom(n, "BTC.D TURUN" in m), PF_JALUR.get(k, 1.2))


def label_nama(it):
    """Nama label terbukti pada sinyal, untuk ditampilkan di urutan prioritas."""
    out = (["COMBO RAJA"] if it.get("combo_raja") else []) + (["COMBO FIX PROFIT"] if it.get("combo_fix") else []) + (["COMBO EMAS"] if it.get("combo_emas") else [])
    cb = len(it.get("combo") or [])
    if cb:
        out.append(f"COMBO {cb + 1}")
    if len(it.get("mutu_plus") or []) >= 3:
        out.append("MUTU TINGGI")
    if it.get("pullback"):
        out.append("PULLBACK")
    if it.get("vol_tinggi"):
        out.append("VOLUME PASAR TINGGI")
    if it.get("dom_turun"):
        out.append("BTC.D TURUN")
    return out


def label_nama_teks(m):
    import re
    g = re.search(r"COMBO (\d+)", m)
    return (["COMBO RAJA"] if "COMBO RAJA" in m else []) + (["COMBO FIX PROFIT"] if "COMBO FIX PROFIT" in m else []) + (["COMBO EMAS"] if "COMBO EMAS" in m else []) + ([f"COMBO {g.group(1)}"] if g else []) + (["MUTU TINGGI"] if "MUTU TINGGI" in m else []) \
        + (["PULLBACK"] if "PULLBACK" in m else []) + (["VOLUME PASAR TINGGI"] if "VOLUME PASAR TINGGI" in m else []) \
        + (["BTC.D TURUN"] if "BTC.D TURUN" in m else [])


def medali(no):
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(no, "🏅")


def kelas(n):
    """Tanda nilai dari skor label (permintaan user: skor 3 = NILAI 8, 5 = NILAI 9, 8 = NILAI 10).
    Uji 2021-2026 (PF 2021-23 / 2024-26, sudah dengan label BTC.D TURUN): skor 3-4 PF 1.30/1.44, skor 5-7 PF 1.50/1.73,
    skor 8+ PF 2.25/2.22."""
    if n >= 8:
        return "👑 NILAI 10 (PF uji 2.2)"
    if n >= 5:
        return "🔥 NILAI 9 (PF uji 1.7)"
    if n >= 3:
        return "✅ NILAI 8 (PF uji 1.3)"
    return ""


def label_prioritas(p):
    return kelas(p[0]) or "tanpa label"


def combo_teks(it):
    """Baris COMBO (dan COMBO EMAS) untuk kartu semua jalur, plus label VOLUME PASAR TINGGI dan BTC.D TURUN."""
    vt = ([f"🔊 <b>VOLUME PASAR TINGGI</b>: volume BTC 4J {it['vol_tinggi']:g}x rata 30 hari. Uji 2021-2026 sinyal di saat "
           f"seperti ini PF 1.66 dan 1.86, harga bergerak cepat ke dua arah, biarkan SL bekerja"] if it.get("vol_tinggi") else [])
    vt += (["📉 <b>BTC.D TURUN</b>: altcoin sedang lebih kuat dari BTC (indeks alt/BTC di atas EMA 20 harian). Uji 2017-2026 "
            "SHORT di kondisi ini PF 1.57, 1.34, 1.68, biasanya 1.09, 1.18, 1.24"] if it.get("dom_turun") else [])
    if not it.get("combo"):
        return vt
    emas = ([f"🏆 <b>COMBO EMAS</b>: pasangan dengan {', '.join(it['combo_emas'])} termasuk pasangan terbaik. "
             f"Dipilih dari 2021-2023 (PF 1.45), dicek 2024-2026 PF 1.48, combo biasa 1.25"] if it.get("combo_emas") else [])
    fix = ([f"💎 <b>COMBO FIX PROFIT</b>: searah dengan {' dan '.join(it['combo_fix'])}. Kombinasi 3 teknik terbaik, "
            f"dipilih dari 2021-2023, dicek 2024-2026 PF 1.75, rata-rata 0.33R per trade"] if it.get("combo_fix") else [])
    raja = (["👑 <b>COMBO RAJA</b>: 6 jalur terbukti atau lebih searah. Sinyal paling langka dan paling kuat di uji 2021-2026: "
             "sekitar 2 kali sebulan, WR 57%, PF 3.35, rata +0.73R per trade, untung tiap tahun"] if it.get("combo_raja") else [])
    return vt + raja + fix + emas + [f"⭐ <b>COMBO {len(it['combo']) + 1}</b>: juga {', '.join(it['combo'])} searah dalam 72 jam. "
            f"Uji 2021-2026: combo 3+ PF 1.40, 2 PF 1.25, sendiri PF 1.21"]


# Pasangan combo terbaik, dipilih dari data 2021-2023 (PF pasangan minimal 1.4, minimal 100 trade), dicek di 2024-2026:
# combo emas PF 1.45 (2021-23) dan 1.48 (2024-26), combo biasa 1.17/1.25, sendiri 1.19/1.22. Sekitar 3.6 sinyal per hari.
# Format (jalur sinyal, jalur pendukung dalam 72 jam searah).
COMBO_EMAS = {("GZH", "smc_choch"), ("ema_short", "msb_hpz"), ("ema_short", "rsi_vol"), ("ichimoku", "ema_short"),
              ("ichimoku", "mcginley"), ("ichimoku", "rsi_vol"), ("mcginley", "GZH"), ("mcginley", "ema_short"),
              ("mcginley", "ichimoku"), ("mcginley", "msb_hpz"), ("msb_hpz", "ema_short"), ("msb_hpz", "ichimoku"),
              ("rsi_vol", "ichimoku"), ("rsi_vol", "mcginley"), ("rsi_vol", "msb_hpz"), ("rsi_vol", "smc_choch"),
              ("smc_choch", "ema_short"), ("snr_vol", "smc_choch"),
              # tambahan 20 Okt 2026 (dipilih 2021-2023 PF >= 1.35 dan 80 trade, lolos 2024-2026 PF 1.38-1.58)
              ("ema_short", "mcginley"), ("mcginley", "smc_choch"), ("orderblock", "smc_choch"), ("smc_choch", "ichimoku")}

# COMBO FIX PROFIT: jalur sinyal + 2 jalur pendukung tertentu searah dalam 72 jam. Dipilih dari 2021-2023 (PF minimal 1.6,
# minimal 60 trade), 10 dari 11 lolos di 2024-2026 (PF 1.46-2.20). Gabungan uji 2024-2026 PF 1.75, expectancy 0.33R per trade,
# hampir 3 kali sinyal tanpa combo (0.11R). Sekitar 1 sinyal per hari.
COMBO_FIX = {("msb_hpz", frozenset({"ema_short", "smc_choch"})), ("ema_short", frozenset({"mcginley", "msb_hpz"})),
             ("rsi_vol", frozenset({"mcginley", "smc_choch"})), ("smc_choch", frozenset({"ichimoku", "mcginley"})),
             ("ichimoku", frozenset({"mcginley", "smc_choch"})), ("rsi_vol", frozenset({"mcginley", "msb_hpz"})),
             ("ichimoku", frozenset({"mcginley", "rsi_vol"})), ("rsi_vol", frozenset({"msb_hpz", "smc_choch"})),
             ("rsi_vol", frozenset({"ichimoku", "mcginley"})), ("ichimoku", frozenset({"rsi_vol", "smc_choch"}))}


def nama_ke_kunci(nm):
    peta = {cfg["nama"]: kk for kk, cfg in STRAT.items()}
    peta.update({"Ichimoku": "ichimoku", "Order Block": "orderblock"})
    return peta.get(nm)


def combo_raja(combo):
    """COMBO RAJA: minimal 5 jalur terbukti LAIN searah dalam 72 jam (candle inside bar dan EMA 9/21 tidak dihitung).
    Uji 2021-2026: 156 sinyal (sekitar 2 kali sebulan), WR 57%, PF 3.35 (2021-23 3.49, 2024-26 3.20), rata +0.73R per
    trade, untung tiap tahun dan di semua jalur. Makin banyak jalur searah makin bagus: 3 jalur 0.22R, 4 jalur 0.27R,
    5 jalur 0.62R, 6 jalur 1.38R."""
    return sum(1 for nm in (combo or []) if nama_ke_kunci(nm)) >= 5


def combo_fix(k, combo):
    """Pasangan 2 pendukung yang membentuk COMBO FIX PROFIT. Return list nama pendukung atau []."""
    kk = {nama_ke_kunci(nm): nm for nm in (combo or []) if nama_ke_kunci(nm)}
    for jalur, pas in COMBO_FIX:
        if jalur == k and pas <= set(kk):
            return sorted(kk[x] for x in pas)
    return []


def combo_emas(k, combo):
    """Pasangan combo emas pada sinyal ini. Return list nama pendukung yang membentuk pasangan emas."""
    return [nm for nm in (combo or []) if (k, nama_ke_kunci(nm)) in COMBO_EMAS]


def _combo(df, k, arah, bn, sym=None):
    """Jalur terbukti lain yang memberi sinyal searah di koin ini dalam 18 candle 4J terakhir (72 jam).
    Uji 2021-2026 35 ribu trade: jendela 24 jam combo 2+ jalur 2.2 sinyal per hari PF 1.47, jendela 72 jam 3.7 per hari PF 1.40
    (2021-23 1.31, 2024-26 1.49), sendiri PF 1.21. Syarat kondisi (EMA, cloud, RSI, BTC searah) tidak menaikkan PF, tidak dipakai."""
    nama = set()
    try:
        import qse_ichimoku as IC
    except Exception:
        IC = None
    try:
        import qse_ob as OB
    except Exception:
        OB = None
    for j in range(18):
        d = df.iloc[:len(df) - j] if j else df
        for kk, (ar, _) in sinyal(d, bn).items():
            if kk != k and ar == arah:
                nama.add(STRAT[kk]["nama"])
        if IC is not None and k != "ichimoku":
            ar_i, _ = IC._sinyal(d)
            if ar_i == arah:
                nama.add("Ichimoku")
        if OB is not None and k != "orderblock" and arah == "LONG" and "volume" in d:
            try:
                if OB._sinyal(d):
                    nama.add("Order Block")
            except Exception:
                pass
    # EMA 9/21 cross searah EMA 200 dengan volume 20% tertinggi: diuji 20 Okt 2026 sebagai teknik baru. Sendiri impas
    # (PF 0.98 saat tidak bareng jalur lain), jadi bukan jalur sinyal, tapi sebagai pendukung combo: sinyal jalur yang
    # sendirian PF 1.19, dengan pendukung ini PF 1.33 (2021-23 1.25, 2024-26 1.38). Stochastic, Williams %R, RSI 30/70 rugi,
    # SMA/WMA/triple cross, CCI, Parabolic SAR, kekuatan koin vs BTC lebih lemah dari EMA 9/21, tidak dipakai.
    try:
        cc, vv = df["close"].values.astype(float), df["volume"].values.astype(float)
        e9, e21, e2 = _ema(cc, 9), _ema(cc, 21), _ema(cc, 200)
        n_ = len(cc)
        for j in range(18):
            i = n_ - 1 - j
            if i < 210:
                break
            vp_ = (vv[i - 100:i] <= vv[i]).mean() * 100
            if vp_ < 80:
                continue
            if arah == "LONG" and e9[i] > e21[i] and e9[i - 1] <= e21[i - 1] and cc[i] > e2[i]:
                nama.add("EMA 9/21 + Volume")
            if arah == "SHORT" and e9[i] < e21[i] and e9[i - 1] >= e21[i - 1] and cc[i] < e2[i]:
                nama.add("EMA 9/21 + Volume")
    except Exception:
        pass
    if sym:
        # GZH dikirim terpisah (alarm fib), dicek dari catatan jalur GZH 72 jam terakhir
        try:
            now = time.time()
            for v in list(lihat("GZH").get("open", {}).values()) + list(lihat("GZH").get("closed", [])):
                if v.get("sym") == sym and v.get("arah") == arah and 0 <= now - v.get("t", 0) <= 72 * 3600 and k != "GZH":
                    nama.add(STRAT["GZH"]["nama"])
                    break
        except Exception:
            pass
    # candle sinyal inside bar (high dan low di dalam candle sebelumnya): uji 2021-2026 PF 1.39 (dev 1.33, uji 1.45)
    # vs 1.25, konsisten di 7 dari 9 jalur. Dihitung satu pendukung combo: combo 3+ jadi 4.0 per hari, PF tetap 1.42
    h, l = df["high"].values.astype(float), df["low"].values.astype(float)
    if len(h) > 2 and nama and h[-1] <= h[-2] and l[-1] >= l[-2]:
        nama.add("candle inside bar")
    return sorted(nama)


def jalankan(baru_ok=True):
    """Dipanggil listener tiap candle 4J tutup. Return dict kunci -> daftar pesan."""
    import qse_catat as CT
    import qse_saya as SY
    out = {k: [] for k in STRAT}
    try:
        tick = B.get_symbols()
    except Exception:
        tick = {}
    try:
        pegang = {(v["sym"], v["arah"]) for v in SY.lihat()["open"].values() if v.get("status") in ("TERISI", "TP1")}
    except Exception:
        pegang = set()
    # 1. kelola posisi
    for k in STRAT:
        hasil = {}
        for key, it in dict(lihat(k)["open"]).items():
            df = _k4(it["sym"], 300)
            if df is None or not len(df):
                continue
            it = dict(it)
            st, R, sl_lama = _kelola(it, df)
            hasil[key] = (it, st, R, sl_lama)
        for key, (it, st, R, sl_lama) in hasil.items():
            t = it.get("tick", 0.0001)
            kabar = (it["sym"], it["arah"]) in pegang
            if st in ("SL", "WAKTU", "TP"):
                _catat_ledger(k, it, R)
                if kabar:
                    out[k].append(f"{'✅' if R > 0 else '🛑'} <b>{STRAT[k]['nama'].upper()} SELESAI  ·  {it['sym']} {it['arah']}  ·  {R:+.2f}R</b>\n"
                                  + (f"TP {TG.fp(it['tp'], t)} tersentuh." if st == "TP" else
                                     f"Kena SL di sekitar {TG.fp(it['sl'], t)}. Analisa volume menyusul." if st == "SL" else
                                     f"Sudah {it.get('maks_bar', MAKS_BAR)} candle 4J. Tutup sekarang di harga pasar."))
            elif kabar and abs(it["sl"] - sl_lama) >= 0.25 * it["risk"]:
                L = it["arah"] == "LONG"
                kunci = ((it["sl"] - it["entry"]) if L else (it["entry"] - it["sl"])) / it["risk"]
                out[k].append(f"🔁 <b>{STRAT[k]['nama'].upper()}  ·  {it['sym']} {it['arah']}  ·  GESER SL</b>\n"
                              f"Ubah SL di Bybit ke <code>{TG.fp(it['sl'], t)}</code> (sebelumnya {TG.fp(sl_lama, t)})\n"
                              f"Profit aman kalau harga balik: {kunci:+.2f}R  ·  hari ke-{it['bar'] // 6 + 1} dari 10")

        def simpan(dd, hasil=hasil):
            for key, (it, st, R, _) in hasil.items():
                if key not in dd["open"]:
                    continue
                if st in ("SL", "WAKTU", "TP"):
                    dd["open"].pop(key)
                    dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=time.time()))
                else:
                    dd["open"][key] = it
        _ubah(k, simpan)
    if not baru_ok:
        return out
    # 2. sinyal baru
    try:
        tk = B.get_tickers()
    except Exception:
        return out
    bn = btc_naik()
    try:
        izin = izin_btc()
    except Exception:
        izin = {"LONG": True, "SHORT": True}
    pindai = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]

    def cek(sym):
        df = _k4(sym, 600)
        if df is None or len(df) < 261:
            return sym, {}, None, 0.0
        return sym, sinyal(df, bn), df, float((df["close"] * df["volume"]).iloc[-180:].sum())
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, pindai))
    urut = [x[0] for x in sorted(semua, key=lambda x: -x[3])]
    now = time.time()
    # satu koin hanya satu jalur: koin yang sudah dipegang jalur mana pun atau baru dikirim di candle ini dilewati
    dipakai = {it["sym"] for kk in STRAT for it in lihat(kk)["open"].values()}
    for k, cfg in STRAT.items():
        if cfg.get("manual"):
            continue          # GZH: sinyal datang dari pemantau sentuhan 0.618 tiap menit, posisinya tetap dikelola di sini
        if CT.mati(k):
            _CEK[k] = (0, "jalur dihentikan karena hasil live jelek")
            continue
        d = lihat(k)
        slot = min(MAKS_BARU, MAKS_BUKA - len(d["open"]))
        if slot <= 0:
            _CEK[k] = (0, "slot posisi penuh")
            continue
        boleh = set(urut[:cfg["likuid"]]) if cfg["likuid"] else set(urut)
        buka = {it["sym"] for it in d["open"].values()} | dipakai
        calon = [x for x in semua if k in x[1] and x[0] in boleh and x[0] not in buka]
        calon.sort(key=lambda x: urut.index(x[0]))
        baru = []
        for sym, sg, df, _ in calon:
            if len(baru) >= slot:
                break
            if sym in dipakai:
                continue
            arah, a = sg[k]
            if cfg.get("izin_btc") and not izin.get(arah, True):
                print(f"[STRAT {k}] {sym} {arah} ditahan: izin BTC 4J tidak mengizinkan {arah}")
                continue
            import qse_porto as PO
            why = SY.cek_lintas(sym, arah) or PO.izin(sym, arah, k)
            if why:
                print(f"[STRAT {k}] {sym} ditahan: {why}")
                continue
            px = tk[sym]["last"] or float(df["close"].iloc[-1])
            telat = now * 1000 - (int(df.index[-1]) + H4)
            if telat > 1800000 and abs(px - float(df["close"].iloc[-1])) > TELAT_ATR * a:
                continue
            try:
                sk, mp, mm = mutu(df, arah)
            except Exception as ex:
                print("[WARN] mutu", ex)
                sk, mp, mm = 0, [], []
            if mutu_buang(mp, mm):
                print(f"[STRAT {k}] {sym} {arah} dilewati: mutu rendah ({mutu_buang(mp, mm)})")
                continue
            if pump_tolak(df, arah):
                print(f"[STRAT {k}] {sym} {arah} dilewati: {pump_tolak(df, arah)}")
                continue
            if arah == "SHORT":
                import qse_pagi as PG
                if PG.short_tahan():
                    print(f"[STRAT {k}] {sym} SHORT dilewati: {PG.short_tahan()}")
                    continue
            L = arah == "LONG"
            risk = cfg.get("sl_atr", SL_ATR) * a
            if risk / px < 0.003 or risk / px > 0.10:  # SL lebih dari 10% dilewati: uji 2021-2026 SL 10-15% PF 1.05, di atas 15% PF 0.75
                continue
            sl = px - risk if L else px + risk
            t = tick.get(sym, 0.0001)
            it = dict(sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, risk=risk, best=px, bar=0, t=now,
                      last=int(df.index[-1]), close=px, tick=t, sl_atr=cfg.get("sl_atr", SL_ATR),
                      trail_atr=cfg.get("trail_atr", TRAIL_ATR), trail_pct_2r=cfg.get("trail_pct_2r"))
            if cfg.get("tp_r"):
                it.update(tp=px + cfg["tp_r"] * risk if L else px - cfg["tp_r"] * risk, maks_bar=cfg["maks_bar"])
            it.update(mutu=sk, mutu_plus=mp)
            try:
                it["combo"] = _combo(df, k, arah, bn, sym)
                it["combo_emas"] = combo_emas(k, it["combo"])
                it["combo_fix"] = combo_fix(k, it["combo"])
                it["combo_raja"] = combo_raja(it["combo"])
                it["vol_tinggi"] = vol_tinggi()
            except Exception as ex:
                print("[WARN] combo", ex)
            if arah == "SHORT":
                import qse_pagi as PG
                it["dom_turun"] = PG.dom_turun(k, arah)
            if PO.senin_tolak(it.get("combo"), it.get("combo_emas")):
                print(f"[STRAT {k}] {sym} {arah} dilewati: {PO.senin_tolak(it.get('combo'), it.get('combo_emas'))}")
                continue
            if k == "mcginley":
                # pullback: searah tren besar (EMA 200) tapi EMA 20 masih di sisi lawan EMA 50. Uji 2021-2026 McGinley
                # pullback PF 1.43 (2021-23 1.42, 2024-26 1.44), McGinley searah semua tren PF 1.18 (1.10/1.23)
                try:
                    cc = df["close"].values.astype(float)
                    e200, e20, e50 = _ema(cc, 200)[-1], _ema(cc, 20)[-1], _ema(cc, 50)[-1]
                    it["pullback"] = bool((cc[-1] > e200 and e20 < e50) if L else (cc[-1] < e200 and e20 > e50))
                except Exception as ex:
                    print("[WARN] pullback", ex)
            baru.append(it)
            dipakai.add(sym)
            PO.pesan(sym, arah)
            out[k].append(kartu(k, len(baru), it, a))

        def simpan_baru(dd, baru=baru):
            for it in baru:
                dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
        if baru:
            _ubah(k, simpan_baru)
        _CEK[k] = (len(baru), "" if baru else ("BTC 4J di atas EMA 50, SHORT ditahan" if k == "ema_short" and bn
                                               else "tidak ada koin yang lolos semua syarat"))
    for k, (n, why) in _CEK.items():
        _ubah(k, lambda d, n=n, why=why: d.update(cek=dict(t=time.time(), n=n, why=why)))
    return out


_CEK = {}


def kartu(k, no, it, a):
    import qse_saya as SY
    cfg = STRAT[k]
    L = it["arah"] == "LONG"
    t = it["tick"]
    _, tkb, ik, lot_b = SY.boleh_ikut("saran " + k, it["arah"])
    import qse_porto as PO
    rm = rem(k) or PO.rem()
    if rm:
        lot_b = f"{SY.lot_angka(lot_b) / 2:g}x"
    lot_b, cat_hari = PO.lot_hari(lot_b)
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], SY.lot_angka(lot_b))
    except Exception:
        lot = ""
    jarak = it.get("trail_atr", TRAIL_ATR) * a
    return "\n".join([
        SY.GARIS,
        f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {it['arah']}</b>  ·  {cfg['nama']} 4J",
        f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
        *combo_teks(it),
        *([cat_hari] if cat_hari else []),
        *mutu_teks(it),
        *(["🔁 <b>PULLBACK DALAM TREN BESAR</b>: searah EMA 200, tren pendek baru berbalik. "
           "Uji 2021-2026 McGinley pullback PF 1.43, McGinley biasa PF 1.18"] if it.get("pullback") else []),
        SY.GARIS,
        (SY.blok_salin(it["entry"], it["sl"], it["tp"], it["tp"], "MARKET", t, sym=it["sym"], arah=it["arah"], rentang=batas_masuk(it, k)) if it.get("tp") else
         SY.blok_salin(it["entry"], it["sl"], order="MARKET", tick=t, catatan_tp="tidak ada, pakai SL berjalan", sym=it["sym"], arah=it["arah"],
                       rentang=batas_masuk(it, k))),
        *batas_masuk_teks(it, k),
        *tp_cepat_teks(it, k=k),
        *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Tetap boleh entry, pakai lot setengah sampai pulih"] if rm else []),
        "💡 <b>Kenapa</b>",
        *[f"• {z}" for z in cfg["kenapa"]],
        f"• Bukti: {cfg['bt']}",
        "🛠 <b>Cara</b>",
        *([f"1. Masuk MARKET sekarang. SL {TG.fp(it['sl'], t)}, TP {TG.fp(it['tp'], t)} ({cfg['tp_r']:g}R). Tutup penuh di TP",
            f"2. Jangan geser SL. TP {cfg['tp_r']:g}R penuh lebih bagus dari trailing di uji",
            f"3. Kalau {it.get('maks_bar', MAKS_BAR) // 6} hari belum kena SL atau TP, tutup manual",
            "4. Catat dengan /entry supaya ada pengingat dan analisa volume kalau kena SL"] if it.get("tp") else
          [f"1. Masuk MARKET sekarang. SL di {TG.fp(it['sl'], t)} ({it['risk'] / it['entry'] * 100:.1f}%). Jangan pasang TP",
           "2. Pasang Trailing Stop Bybit, isi seperti blok di bawah, atau ikuti pesan GESER SL",
           *([f"   Setelah untung 2R ({TG.fp(it['entry'] + 2 * it['risk'] if L else it['entry'] - 2 * it['risk'], t)}), ganti jarak "
              f"Trailing Stop jadi 5% harga. Robot mengingatkan lewat SL TERBARU"] if it.get("trail_pct_2r") else []),
           "3. Kalau 10 hari belum kena SL, tutup manual",
           "4. Catat dengan /entry supaya pesan GESER SL dan analisa volume SL dikirim"]),
        *([SY.isi_trailing(jarak, it["sl"], t)] if not it.get("tp") else []),
        *([lot] if lot else []),
    ])


def baris_cek(k):
    if STRAT.get(k, {}).get("manual"):
        return "dipantau tiap menit saat harga menyentuh fib 0.618, dikirim terpisah"
    c = lihat(k).get("cek")
    if not c:
        return "belum pernah dicek sejak update"
    jam = time.strftime("%H:%M", time.gmtime(c["t"] + 7 * 3600))
    return f"dicek {jam} WIB: {c['n']} sinyal baru" + (f", {c['why']}" if c.get("why") and not c["n"] else "")


def status_singkat(k):
    return f"{baris_cek(k)}  ·  posisi robot {len(lihat(k)['open'])}/{MAKS_BUKA}"


def teks():
    rows = []
    for k, cfg in STRAT.items():
        d = lihat(k)
        rows.append(f"<b>{cfg['nama']}</b>\nBacktest: {cfg['bt']}\n{status_singkat(k)}")
        for it in d["open"].values():
            L = it["arah"] == "LONG"
            g = ((it["close"] - it["entry"]) if L else (it["entry"] - it["close"])) / it["risk"]
            rows.append(f"{'🟢' if L else '🔴'} {it['sym']} {it['arah']} | entry {TG.fp(it['entry'], it['tick'])} | "
                        f"SL {TG.fp(it['sl'], it['tick'])} | {g:+.2f}R | candle {it['bar']}/{MAKS_BAR}")
        rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
        if rs:
            w = sum(x for x in rs if x > 0)
            lo = -sum(x for x in rs if x < 0)
            rows.append(f"Selesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                        f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
        rows.append("")
    rows.append("Gagal uji dan tidak dipakai: entry retest order block, SMC BOS, SnR tanpa volume, Donchian 20/55, Supertrend, "
                "Bollinger squeeze, mean reversion Bollinger dan RSI 2, "
                "pullback 3 candle, inside bar, momentum 30 hari, funding ekstrem, breakout volume.")
    return "\n".join(rows)
