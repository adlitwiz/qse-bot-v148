"""QSE v150 - JALUR STRATEGI TAMBAHAN yang lolos uji 14 strategi umum (candle 4J, 111 koin perp, Jul 2020 - Okt 2026).
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
import qse_modal as MD          # kelas margin di kartu (9 Nov 2026)
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
MAKS_BARU, MAKS_BUKA, TOP_KOIN = int(os.environ.get("QSE_MAKS_BARU", "8")), int(os.environ.get("QSE_MAKS_BUKA", "16")), 150
BIAYA = 0.0015
TELAT_ATR = 0.5
STRAT = {
    # QC 61 (riset/upgrade/hasil_v167_jagoan.txt, Z3): SL ke entry di +0.4R lalu trailing 4 ATR, tanpa TP 20%, tanpa jam ke-12 dan
    # batas 30 jam. Lawan kartu lama: latih +234R vs +171R, uji 2025-2026 +263R vs +146R, 2026 -128R vs -174R.
    "ema_short": dict(nama="EMA Cross 20/50 SHORT", likuid=0, sl_atr=1.5, trail_atr=4.0, be_r=0.4,
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
    # QC 59 (riset/upgrade/run_v166_trail.py, 152 koin): kartu (TP 20% di +0.5R lalu sisa) dengan sisa trailing 3 ATR maks 60 candle
    # lawan sisa TP 4R maks 45 candle: latih 2023-2024 +135R lawan +101R, uji 2025-2026 +697R lawan +350R (PF 1.35 lawan 1.18), WR tetap 61%.
    # Trailing 2.5 ATR kalah di latih (+86R). TP 4R dengan trailing 3 ATR tetap +93R / +349R: untungnya dari melepas batas TP 4R.
    "mcginley": dict(nama="McGinley 34 + Volume", likuid=0, sl_atr=1.5, trail_atr=3.0,
                     bt="uji 152 koin 2023-2026 aturan kartu (TP 20% di +0.5R, sisa trailing 3 ATR): latih 2023-2024 PF 1.07, uji 2025-2026 PF 1.35, menang 61%",
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


def sinyal(df, btc_naik, netral=False):
    """Cek candle tutup terakhir untuk semua strategi. Return dict kunci -> (arah, atr). Aturan persis backtest.
    netral=True (QC 73, BTC kurang dari 1% dari EMA 50): SnR Pantul tidak lagi wajib searah BTC. Pemanggil menandainya kelas ringan."""
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
            if x[0] == i and searah(x[1]) and vp >= 80 and btc_naik is not None and (netral or btc_naik == (x[1] == 1)):
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
        v150_langkah(it, hi, lo, cl)
        if (lo <= it["sl"]) if L else (hi >= it["sl"]):
            v150_tutup(it, it["sl"])
            return "SL", ((it["sl"] - e) if L else (e - it["sl"])) / risk - BIAYA * e / risk, sl_lama
        if it.get("tp"):          # jalur TP tetap (McGinley): TP tidak dicek di candle masuk, sama dengan backtest
            if it["bar"] > 0 and ((hi >= it["tp"]) if L else (lo <= it["tp"])):
                v150_tutup(it, it["tp"])
                return "TP", abs(it["tp"] - e) / risk - BIAYA * e / risk, sl_lama
            it["bar"] += 1
            it["last"] = int(ts)
            it["close"] = cl
            if it["bar"] >= it.get("maks_bar", MAKS_BAR):
                v150_tutup(it, cl)
                return "WAKTU", ((cl - e) if L else (e - cl)) / risk - BIAYA * e / risk, sl_lama
            continue
        if it.get("be_r") and ((hi - e) if L else (e - lo)) >= it["be_r"] * risk:
            it["sl"] = max(it["sl"], e) if L else min(it["sl"], e)          # QC 61: SL ke entry di +0.4R
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
            v150_tutup(it, cl)
            return "WAKTU", ((cl - e) if L else (e - cl)) / risk - BIAYA * e / risk, sl_lama
    return "BUKA", None, sl_lama


def v150_langkah(it, hi, lo, cl):
    """v150: jejak aturan keluar yang diikuti orang, berjalan di samping aturan jalur, per candle 4J: TPawal 20% di +0.5R lalu SL
    ke entry, jam ke-12 dinamis (rugi >= 0.5R tutup, melawan SL ke -0.5R), batas 30 jam (candle ke-8) untuk yang belum aman.
    Dipanggil sebelum aturan jalur di tiap candle. Hasil di it['v9']['R'] (tanpa biaya)."""
    e = it["entry"]
    risk = abs(e - it.get("sl0", it["sl"])) or it.get("risk") or 1e-12
    d = 1 if it["arah"] == "LONG" else -1
    v = it.get("v9")
    if v is None:
        v = it["v9"] = dict(real=0.0, sisa=1.0, aman=False, sl=float(it.get("sl0", it["sl"])), n=0, R=None)
    if v["R"] is not None or it.get("be_r"):
        return          # QC 61: jalur SL ke entry +0.4R tidak memakai TP 20%, hasil = aturan jalur (v150_tutup)
    if (lo <= v["sl"]) if d == 1 else (hi >= v["sl"]):
        v["R"] = v["real"] + v["sisa"] * (v["sl"] - e) * d / risk
        return
    lv = e + d * TPS_R * risk
    if not v["aman"] and ((hi >= lv) if d == 1 else (lo <= lv)):
        v["real"] += TPS_PORSI * TPS_R
        v["sisa"] = 1.0 - TPS_PORSI
        v["aman"] = True
        v["sl"] = e
    v["n"] += 1
    if not v["aman"]:
        g = (cl - e) * d / risk
        if v["n"] == 3:
            if g <= -0.5:
                v["R"] = v["real"] + v["sisa"] * g
                return
            if g < 0:
                nsl = e - d * 0.5 * risk
                if (nsl > v["sl"]) if d == 1 else (nsl < v["sl"]):
                    v["sl"] = nsl
        if v["n"] >= 8:
            v["R"] = v["real"] + v["sisa"] * g


def v150_tutup(it, px):
    """Saat jalur selesai di harga px: hasil jejak v150 (sudah biaya). None kalau jejak belum ada."""
    v = it.get("v9")
    if not v:
        return None
    e = it["entry"]
    risk = abs(e - it.get("sl0", it["sl"])) or it.get("risk") or 1e-12
    d = 1 if it["arah"] == "LONG" else -1
    if v["R"] is None:
        v["R"] = v["real"] + v["sisa"] * (px - e) * d / risk
    it["R9"] = round(v["R"] - BIAYA * e / risk, 3)
    return it["R9"]


def r_hasil(c):
    """Hasil trade kertas menurut aturan v150 (R9). Catatan lama tanpa jejak: perkiraan dari puncak harga (best):
    kalau pernah +0.5R, 20% untung 0.5R dan sisa tidak rugi. Tanpa data puncak: hasil aturan jalur."""
    if c.get("R9") is not None:
        return float(c["R9"])
    R = float(c["R"])
    try:
        e = c["entry"]; risk = abs(e - c.get("sl0", c["sl"]))
        d = 1 if c["arah"] == "LONG" else -1
        if risk > 0 and c.get("best") is not None and (c["best"] - e) * d / risk >= TPS_R:
            return TPS_PORSI * TPS_R + (1 - TPS_PORSI) * max(R, 0.0)
    except Exception:
        pass
    return R


def _catat_ledger(k, it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur=k, sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl0"], tp1=0.0, tp2=0.0,
                                t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"], selesai=time.time(), ket="trailing"))
    CT._ubah(f)


def rem(k):
    import qse_porto as PO_r
    if not PO_r.REM_LOT:          # rem mati sejak 27 Okt 2026, diganti batas 5 posisi per orang
        return ""
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
    try:
        import qse_kompas as KP          # 9 Nov 2026: kompas pasar ikut tampil supaya semua menu sinkron dengan Cek BTC
        k = KP.kompas()
        if k:
            teks = f"{k['ikon']} Kompas {k['status']} (15m/1J/4J + USDT.D)  ·  " + teks
    except Exception:
        pass
    return teks


def btc_naik():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return None
    c = df["close"].values.astype(float)
    return bool(c[-1] > _ema(c, 50)[-1])


# QC 83 TREN TUA (riset/upgrade/run_v187*.py, hasil_v187_kompas.txt): sinyal SHORT searah BTC paling bagus di awal tren turun dan rugi
# saat BTC 4J sudah 3 sampai 7 hari terus di bawah EMA 50 (pasar jenuh jual). Siaran 2022-2026: SHORT umur 0-2 hari PF 1.61 (latih) / 1.93
# (uji), umur 3-7 hari PF 0.46 / 0.47, rugi di tiap tahun 2022-2026 (total -322R dari 1847 sinyal), 12 bulan terakhir PF 0.68 (-56R).
# Umur di atas 7 hari tidak konsisten (latih rugi, uji untung) jadi tidak ditahan. LONG tua (> 5 hari) impas di latih, tidak dipasang.
# QC 84 (run_v188*.py, hasil_v188_tua_tajam.txt), standar user: yang disiarkan harus kelompok PF >= 1.45 di 4.3 tahun, 12 bulan, dan
# 6 bulan terakhir. Kelompok PF < 1.30 ditahan ke uji kertas. Berlaku DUA ARAH.
# Tren TURUN tua (BTC 4J 3-7 hari di bawah EMA 50). Konfluensi dan kelas koin TIDAK menolong SHORT di sini (2 teknik PF 0.26 / 0.41,
# 3+ teknik 0.20 / 0.06, koin kelas A ketat 0.38 / 0.89). Yang memisahkan untung dan rugi adalah candle 4J BTC yang baru tutup:
#   SHORT pantulan (BTC 4J tutup naik >= 0.1%, bukan EMA Cross): latih PF 1.62, uji 1.97, 12 bulan 2.68, 6 bulan 5.87, 101 sinyal. DISIARKAN.
#   SHORT lain (mengejar candle merah, atau EMA Cross): PF 0.34 / 0.29, -346R dari 1464 sinyal. DITAHAN.
#   LONG pantulan saat BTC 4J tutup naik: PF 1.73 / 1.98, 12 bulan 2.85, 6 bulan 2.95, 257 sinyal (2+ teknik PF 2.35). DISIARKAN.
#   LONG saat BTC 4J tutup turun: PF 0.19 / 0.67, 67 sinyal. DITAHAN.
#   Ichimoku SHORT (modul sendiri): latih 0.77, uji 1.49, tidak terbukti rugi, tidak digerbang.
# Tren NAIK tua (BTC 4J lebih dari 5 hari di atas EMA 50):
#   LONG searah: latih PF 0.97, uji 0.64, 12 bulan 0.62, 6 bulan 0.82, -88R dari 2075 sinyal, rugi di 4 dari 5 tahun. Tidak ada
#   bagiannya yang PF >= 1.45 di semua periode (kelas A 0.78, 3+ teknik latih 0.85). DITAHAN semua teknik, termasuk Ichimoku dan Order Block.
#   SHORT melawan: PF 0.79 / 0.82, 6 bulan 0.33. DITAHAN.
# Hasil siaran: PF 1.40 -> 1.61, +2561R -> +3048R. 12 bulan PF 1.16 -> 1.28 (+276R -> +400R). 6 bulan PF 1.26 -> 1.33 (+212R -> +242R).
# Kelas Utama PF 1.73 -> 1.98. Sinyal ditahan 17.4%. HARGA yang dibayar: saat BTC lama di atas EMA 50 grup bisa tanpa sinyal berhari-hari
# (terpanjang 24.7 hari, Okt-Nov 2023, 22 kali jeda 4 hari atau lebih dalam 4.3 tahun). Varian aktif QSE_TUA_LONG_MAKS=7 (LONG ditahan
# hanya hari ke-5 sampai ke-7): PF 1.55, +3014R, 12 bulan 1.26, 6 bulan 1.30, jeda terpanjang 3.3 hari. Katup sepi (QSE_TUA_SEPI_JAM=48)
# tersedia tetapi mati: user memilih tidak entry daripada menerima sinyal dari kelompok PF kecil.
# Matikan semua: QSE_TREN_TUA=0. Tahan semua SHORT 3-7 hari seperti QC 83: QSE_TUA_SEMUA=1.
TUA_MIN = float(os.environ.get("QSE_TUA_MIN", "3"))
TUA_MAKS = float(os.environ.get("QSE_TUA_MAKS", "7"))
TUA_PANTUL = float(os.environ.get("QSE_TUA_PANTUL", "0.1"))             # persen gerak candle 4J BTC terakhir
TUA_LONG_MIN = float(os.environ.get("QSE_TUA_LONG_MIN", "5"))
TUA_LONG_MAKS = float(os.environ.get("QSE_TUA_LONG_MAKS", "7"))         # QC 85: varian AKTIF jadi bawaan. 0 = tanpa batas atas (varian ketat)
# QC 85 KATUP HARIAN (run_v189_harian.py, hasil_v189_harian.txt): kalau sampai jam 16 WIB belum ada sinyal siaran hari itu, sinyal tahanan
# tren tua berikutnya dilepas (satu per hari). 4.3 tahun: 80 sinyal dilepas, PF 1.16, +3.9R. Hari kosong 110 -> 37 dari 1571, 12 bulan
# 27 -> 8 dari 365. Total siaran +3014R -> +3018R, PF tetap 1.55. Sisa hari kosong = hari tanpa sinyal apa pun, juga yang ditahan.
# Matikan: QSE_TUA_HARIAN_JAM=0.
TUA_HARIAN_JAM = float(os.environ.get("QSE_TUA_HARIAN_JAM", "16"))
TUA_SEPI_JAM = float(os.environ.get("QSE_TUA_SEPI_JAM", "0"))           # katup sepi, 0 = mati
_UMUR = {}


def umur_dari(c):
    """(sisi, hari) dari harga tutup 4J: sisi +1 di atas EMA 50, -1 di bawah. hari = lama beruntun di sisi itu."""
    c = np.asarray(c, float)
    if len(c) < 100:
        return None
    s = c > _ema(c, 50)
    n = 1
    while n < len(s) and s[-1 - n] == s[-1]:
        n += 1
    return (1 if s[-1] else -1), n * 4 / 24.0


def _muat_umur():
    c = _UMUR.get("v")
    if c and time.time() - c[0] < 600 and int(c[0] // 14400) == int(time.time() // 14400):          # candle 4J baru = hitung ulang
        return
    df = _k4("BTCUSDT", 400)
    v, r4 = None, None
    if df is not None and len(df) >= 100:
        cl = df["close"].values.astype(float)
        v = umur_dari(cl)
        r4 = float((cl[-1] / cl[-2] - 1) * 100)
    _UMUR["v"] = (time.time(), v)
    _UMUR["r4"] = r4


def umur_tren():
    """Umur tren BTC 4J sekarang, cache 10 menit. None kalau data tidak ada."""
    _muat_umur()
    return _UMUR["v"][1]


def btc_candle():
    """Gerak candle 4J BTC yang baru tutup, dalam persen. None kalau data tidak ada."""
    _muat_umur()
    return _UMUR.get("r4")


def sepi_jam(now=None):
    """Jam sejak sinyal siaran terakhir (kartu jalur yang bukan uji live, atau kartu scan 1 jam). 0 kalau tidak ada catatan."""
    now = now or time.time()
    akhir = float(_UMUR.get("katup_t") or 0)
    try:
        for k in STRAT:
            d = lihat(k)
            for it in list(d["open"].values()) + list(d.get("closed", [])[-40:]):
                if not it.get("uji_live") and not it.get("otak_saring"):
                    akhir = max(akhir, float(it.get("t") or 0))
    except Exception as ex:
        print("[WARN] sepi jalur", ex)
    try:
        import qse_radar as RD
        for v in (RD._baca().get("kirim") or {}).values():
            akhir = max(akhir, float(v[0] if isinstance(v, list) else v))
    except Exception:
        pass
    return (now - akhir) / 3600 if akhir > 0 else 0.0


def fase_tua(u=None):
    """'TURUN' saat BTC 4J 3-7 hari di bawah EMA 50, 'NAIK' saat lebih dari 5 hari di atas, selain itu ''."""
    u = umur_tren() if u is None else u
    if not u or os.environ.get("QSE_TREN_TUA", "1") == "0":
        return ""
    if u[0] == -1 and TUA_MIN < u[1] <= TUA_MAKS:
        return "TURUN"
    if u[0] == 1 and u[1] > TUA_LONG_MIN and (TUA_LONG_MAKS <= 0 or u[1] <= TUA_LONG_MAKS):
        return "NAIK"
    return ""


def akhir_siaran():
    """Waktu (epoch detik) sinyal siaran terakhir: kartu jalur bukan uji live, kartu scan 1 jam, atau katup yang terpakai."""
    akhir = float(_UMUR.get("katup_t") or 0)
    try:
        for k in STRAT:
            d = lihat(k)
            for it in list(d["open"].values()) + list(d.get("closed", [])[-40:]):
                if not it.get("uji_live") and not it.get("otak_saring"):
                    akhir = max(akhir, float(it.get("t") or 0))
    except Exception as ex:
        print("[WARN] akhir siaran jalur", ex)
    try:
        import qse_radar as RD
        for v in (RD._baca().get("kirim") or {}).values():
            akhir = max(akhir, float(v[0] if isinstance(v, list) else v))
    except Exception:
        pass
    return akhir


def katup_harian(now=None, akhir=None):
    """True kalau sudah lewat jam TUA_HARIAN_JAM WIB dan belum ada sinyal siaran sejak jam 00:00 WIB hari ini."""
    if TUA_HARIAN_JAM <= 0:
        return False
    now = now or time.time()
    wib = now + 7 * 3600
    if (wib % 86400) / 3600 < TUA_HARIAN_JAM:
        return False
    awal_hari = now - (wib % 86400)
    a = akhir_siaran() if akhir is None else akhir
    return a < awal_hari


def tren_tua(arah, umur=None, k=None, r4=None, sepi=None, pakai_katup=False, now=None, akhir=None):
    """Alasan sinyal ditahan ke uji kertas karena tren BTC sudah tua (QC 84, dua arah), atau ''. k = kunci teknik."""
    alasan = _tren_tua(arah, umur, k, r4, sepi, pakai_katup)
    if alasan and k is not None and katup_harian(now, akhir):
        if pakai_katup:
            _UMUR["katup_t"] = now or time.time()
            print(f"[TREN TUA] katup harian: belum ada sinyal sejak 00:00 WIB, sinyal {k} {arah} dilepas ({alasan})")
        return ""
    return alasan


def _tren_tua(arah, umur, k, r4, sepi, pakai_katup):
    u = umur if umur is not None else umur_tren()
    fase = fase_tua(u)
    if not fase:
        return ""
    if fase == "NAIK":
        if arah == "LONG":
            return f"tren naik BTC sudah {u[1]:.1f} hari di atas EMA 50 4J, jenuh beli (uji LONG hari ke-5 sampai ke-7 PF 0.65, -83R)"
        return f"SHORT melawan tren naik BTC yang sudah {u[1]:.1f} hari (uji PF 0.80)"
    r4 = btc_candle() if r4 is None else r4
    if arah == "LONG":
        if r4 is not None and r4 < 0:
            return f"LONG saat tren turun BTC {u[1]:.1f} hari dan candle 4J BTC terakhir tutup turun (uji PF 0.38)"
        return ""          # LONG pantulan saat BTC 4J tutup naik: uji PF 1.85
    dasar = f"tren turun BTC sudah {u[1]:.1f} hari di bawah EMA 50 4J (jenuh jual)"
    if os.environ.get("QSE_TUA_SEMUA", "0") == "1":
        return dasar + ", uji SHORT umur 3-7 hari PF 0.47"
    if k == "ichimoku":
        return ""          # modul sendiri, hasil campur (latih 0.77, uji 1.49)
    if k != "ema_short" and r4 is not None and r4 >= TUA_PANTUL:
        return ""          # SHORT pantulan: uji PF 1.62 / 1.97
    if TUA_SEPI_JAM > 0 and k is not None:
        sp = sepi_jam() if sepi is None else sepi
        if sp >= TUA_SEPI_JAM:
            if pakai_katup:
                _UMUR["katup_t"] = time.time()
            return ""
    return dasar + (", EMA Cross di tren tua (uji PF 0.45)" if k == "ema_short" and r4 is not None and r4 >= TUA_PANTUL else
                    f", candle 4J BTC terakhir belum memantul {TUA_PANTUL:g}%: SHORT di sini mengejar candle merah (uji PF 0.32, -346R)")


def umur_teks():
    """Baris umur tren untuk kompas dan laporan. '' kalau data tidak ada."""
    u = umur_tren()
    if not u:
        return ""
    sisi = "di atas" if u[0] > 0 else "di bawah"
    fase = fase_tua(u)
    r4 = btc_candle()
    if fase == "TURUN":
        ket = ("⏳ JENUH JUAL. Candle 4J BTC terakhir "
               + (f"naik {r4:+.2f}%: SHORT pantulan non EMA Cross dan LONG pantulan boleh keluar (uji PF 1.8)" if r4 is not None and r4 >= TUA_PANTUL else
                  f"{r4:+.2f}%: SHORT baru ditahan (uji PF 0.32)" + (", LONG pantulan boleh keluar" if r4 >= 0 else ", LONG juga ditahan")
                  if r4 is not None else "belum terbaca, SHORT ditahan"))
    elif fase == "NAIK":
        ket = "⏳ JENUH BELI: LONG baru dan SHORT melawan ditahan ke uji kertas sampai hari ke-7 (uji LONG hari ke-5 sampai ke-7 PF 0.65)"
    else:
        ket = ("tren muda, sinyal searah paling bagus (uji PF 1.6-1.9)" if u[1] <= 2 else "tren berjalan")
    return f"⏳ Umur tren: BTC 4J sudah {u[1]:.1f} hari {sisi} EMA 50  ·  {ket}"


def btc_jarak():
    """Jarak harga tutup BTC 4J terakhir ke EMA 50 dalam persen (plus = di atas). None kalau data tidak ada."""
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return None
    c = df["close"].values.astype(float)
    e = _ema(c, 50)[-1]
    return float((c[-1] - e) / e * 100)


# v173 QC 71 (riset/upgrade/run_v173_long.py, hasil_v173_long.txt): 30 ribu sinyal 8 teknik 2023-2026, aturan keluar live.
# DITAHAN (rugi di latih dan di kedua tahun uji):
#   MSB HPZ SHORT saat BTC 4J di atas EMA 50: 2023 -0.246R, 2024 +0.071R (latih gabungan -0.11R), 2025 -0.167R, 2026 -0.224R.
#   McGinley LONG saat BTC 4J lebih dari 2% di bawah EMA 50: 2023 -0.097R, 2024 -0.081R, 2025 -0.130R, 2026 -0.145R (n 85-158 per tahun).
# TIDAK dibuka: MSB HPZ / Order Block / Ichimoku / SnR Pantul LONG saat BTC di bawah EMA 50. MSB -0.108, -0.254, -0.050, +0.017R.
#   Order Block -0.021, +0.378, -0.325, -0.404R. Ichimoku -0.205, -0.104, +0.092, +0.129R. SnR -0.148, +0.027, +0.154, -0.111R.
# SPESIALIS (label kartu, untung di keempat tahun atau impas di 2023 lalu untung 3 tahun):
SPESIALIS = {
    ("msb_hpz", "LONG"): ("atas", "2023 +0.12R, 2024 +0.21R, 2025 +0.19R, 2026 +0.13R per trade"),
    ("ichimoku", "LONG"): ("atas", "2023 +0.15R, 2024 +0.28R, 2025 +0.17R, 2026 +0.08R per trade"),
    ("orderblock", "LONG"): ("atas", "2023 +0.06R, 2024 +0.13R, 2025 +0.16R, 2026 +0.23R per trade"),
    ("smc_choch", "SHORT"): ("bawah", "2023 -0.01R, 2024 +0.13R, 2025 +0.16R, 2026 +0.10R per trade"),
    ("rsi_vol", "SHORT"): ("bawah", "2023 -0.02R, 2024 +0.25R, 2025 +0.30R, 2026 +0.07R per trade"),
    ("ichimoku", "SHORT"): ("bawah", "2023 -0.01R, 2024 +0.25R, 2025 +0.01R, 2026 +0.18R per trade"),
}


# v175 QC 73 (riset/upgrade/run_v175_qc73.py, hasil_v175_qc73.txt, 30.178 sinyal 2023-2026, aturan keluar live):
# KONFLUENSI teknik berbeda searah di koin yang sama dalam 3 candle 4J. 1 teknik -0.017 / +0.062 / +0.122 / -0.009R per sinyal,
#   2 teknik +0.058 / +0.259 / +0.292 / +0.049R (untung di 4 tahun), 3+ teknik -0.095 / +0.322 / +0.274 / +0.091R (WR 61%, PF 1.73).
#   Jadi 3+ teknik naik ke KELAS UTAMA dan 2 teknik menambah nilai urut.
# BTC NETRAL (jarak ke EMA 50 di bawah 1%). Gerbang arah BTC yang dipakai live: SnR Pantul searah BTC, Order Block LONG dan GZH menurut
#   sisi BTC, MSB HPZ SHORT ditahan di atas EMA 50. Teknik lain (RSI, McGinley, SMC, Ichimoku) memang tidak digerbang BTC.
#   Sinyal SnR + Order Block yang MELAWAN sisi BTC saat netral: -0.311 / +0.159 / +0.134 / -0.319R (n 85, rugi di 2023 dan 2026).
#   MSB HPZ SHORT netral di atas EMA 50: -0.305 / +0.378 / +0.166 / -0.391R (n 58). Uji TIDAK mendukung. Dibuka atas permintaan user,
#   selalu KELAS RINGAN kecuali konfluensi 3+, hanya lewat scan 1 jam. QSE_NETRAL_BAND=0 mengembalikan gerbang lama.
# UNIVERSE: peringkat likuiditas 1-30 -0.011 / +0.208 / +0.206 / +0.003R, 31-75 +0.020 / +0.120 / +0.266 / +0.063R,
#   76-110 -0.039 / +0.137 / +0.190 / -0.095R, 111-150 -0.130 / +0.012 / +0.084 / -0.107R, di atas 150 -0.106 / +0.104 / -0.148R.
#   Makin tidak likuid makin lemah. Universe pindai diperluas atas permintaan user, koin di luar 150 teratas selalu KELAS RINGAN.
# v176 QC 74 (riset/upgrade/run_v176_rugi.py, hasil_v176_rugi.txt): kelompok yang rugi di latih 2023-2024 dan tidak pulih di uji 2025-2026
# dipindah ke UJI LIVE (robot tetap mencatat trade kertasnya, tidak disiarkan):
#   c. teknik tunggal di koin peringkat likuiditas 111+   : -0.135 / +0.000 / +0.044 / -0.116R, total -194R
#   d. McGinley tunggal melawan sisi BTC (EMA 50 4J)      : -0.161 / +0.083 / +0.054 / -0.075R, total -111R
#   e. RSI 50 LONG tunggal                                : +0.023 / -0.118 / -0.044 / +0.150R, latih -0.054R
# Semua sinyal 30178: PF 1.28, rata -0.010 / +0.117 / +0.167 / +0.010R. Sesudah tiga kelompok itu dikeluarkan 21876 sinyal: PF 1.45,
# rata +0.035 / +0.153 / +0.210 / +0.046R (untung di 4 tahun), total +2292R jadi +2510R. Pelonggaran BTC netral dan universe di luar
# 150 (QC 73, uji tidak lulus) dimatikan: QSE_NETRAL_LONGGAR=1 dan QSE_TOP_PINDAI=300 menghidupkannya lagi.
# PENGGANTI: konfluensi 2+ teknik searah (bukan SHORT saat BTC di atas EMA 50) +0.048 / +0.308 / +0.312 / +0.086R = KELAS UTAMA,
# termasuk EMA Cross SHORT 2+ teknik (-0.070 / +0.375 / +0.389 / +0.067R, tunggal 2026 -0.141R). 2+ teknik SHORT saat BTC di atas
# EMA 50 -0.189 / +0.046 / +0.115 / -0.119R: kelas tidak dinaikkan.
NETRAL_BAND = float(os.environ.get("QSE_NETRAL_BAND", "1.0"))
# v180 QC 77 (permintaan user): pelonggaran BTC netral hidup lagi (sinyalnya tetap KELAS RINGAN, uji QC 73 tidak lulus). McGinley tunggal
# melawan sisi BTC TIDAK masuk uji live saat BTC netral: uji -0.164 / +0.391 / +0.084 / +0.026R, PF 1.13 (di luar netral PF 0.88).
# Teknik tunggal di koin peringkat 111-150 disiarkan lagi sebagai KELAS RINGAN (uji PF 0.87: -0.135 / +0.005 / +0.042 / -0.113R).
# v181 QC 78 (permintaan user: hanya yang untung di uji): pelonggaran BTC netral mati lagi (uji -0.311 / +0.159 / +0.134 / -0.319R) dan
# teknik tunggal peringkat 111-150 kembali uji live (PF 0.87). McGinley saat BTC netral TETAP disiarkan (PF 1.13, uji 2025 dan 2026 plus).
# Frekuensi dijaga dari kelompok yang untung: batas posisi kertas robot per teknik 8 jadi 16 dan sinyal baru per candle 5 jadi 8, supaya
# sinyal dari populasi teruji (PF 1.45, 109 per minggu di 150 koin) tidak terbuang karena slot penuh. QSE_MAKS_BUKA / QSE_MAKS_BARU.
NETRAL_LONGGAR = os.environ.get("QSE_NETRAL_LONGGAR", "0") == "1"
TOP_PINDAI = int(os.environ.get("QSE_TOP_PINDAI", "150"))
PERINGKAT_TUNGGAL = int(os.environ.get("QSE_PERINGKAT_TUNGGAL", "110"))
PERINGKAT_RINGAN = 110          # teknik tunggal di atas peringkat ini: kelas ringan


def uji_live(k, arah, bj, peringkat, konf, umur=None, r4=None, sepi=None):
    """Alasan sinyal masuk UJI LIVE (dicatat sebagai trade kertas, tidak disiarkan), atau ''. Saklar QSE_UJI_LIVE=0."""
    if os.environ.get("QSE_UJI_LIVE", "1") == "0":
        return ""
    if peringkat and peringkat > TOP_KOIN:
        return "koin di luar 150 teratas (uji -0.11 / +0.10 / -0.15R)"
    if bj is not None:          # QC 84: umur tren dua arah (jenuh jual 3-7 hari, jenuh beli di atas 5 hari)
        tt = tren_tua(arah, umur, k=k, r4=r4, sepi=sepi, pakai_katup=True)
        if tt:
            return tt
    if konf >= 2:
        return ""
    if peringkat and peringkat > PERINGKAT_TUNGGAL:
        return f"teknik tunggal di koin peringkat {peringkat} (uji peringkat 111+: total -194R)"
    if k == "mcginley" and bj is not None and (bj < 0) == (arah == "LONG") and not btc_netral(bj):
        return "McGinley tunggal melawan sisi BTC (uji total -111R)"
    if k == "rsi_vol" and arah == "LONG":
        return "RSI 50 LONG tunggal (latih -0.05R)"
    return ""


def konf_utama(arah, bj, konf):
    """True kalau konfluensi menaikkan sinyal ke KELAS UTAMA: 2+ teknik searah, kecuali SHORT saat BTC 4J di atas EMA 50."""
    return konf >= KONF_UTAMA and not (arah == "SHORT" and bj is not None and bj > 0) and os.environ.get("QSE_KONF_UTAMA", "1") != "0"


def uji_live_teks():
    """Rapor trade kertas kelompok UJI LIVE dari catatan robot (dipakai /nyawa)."""
    g = {}
    for k in STRAT:
        try:
            for c in lihat(k).get("closed", []):
                if c.get("uji_live") and c.get("R") is not None:
                    g.setdefault(c["uji_live"].split(" (")[0], []).append(float(c["R"]))
        except Exception:
            pass
    rows = ["🧪 <b>UJI LIVE</b> (kelompok yang rugi atau impas di uji mundur: dicatat robot, tidak disiarkan. Naik lagi kalau hasil live berbalik)"]
    try:
        import qse_lalat as LT
        rows.append(LT.rapor_uji() + ("" if not LT.siar() else " (yang disiarkan hanya medali dan kualitas tinggi)"))
    except Exception:
        pass
    if not g:
        rows.append("Belum ada trade kertas uji live jalur yang selesai.")
    for nm, r in sorted(g.items(), key=lambda z: -len(z[1])):
        rows.append(f"• {nm}: {len(r)} trade, WR {sum(1 for x in r if x > 0) / len(r) * 100:.0f}%, total {sum(r):+.1f}R")
    return "\n".join(rows)
MIN_TURNOVER = float(os.environ.get("QSE_MIN_TURNOVER", "5000000"))
KONF_UTAMA = 2          # QC 74: 2+ teknik searah


def btc_netral(bj):
    """True kalau BTC 4J berjarak kurang dari NETRAL_BAND persen dari EMA 50 (pasar tanpa arah jelas). QSE_NETRAL_BAND=0 mematikan."""
    return bj is not None and NETRAL_BAND > 0 and abs(bj) < NETRAL_BAND


def netral_longgar(bj):
    """True kalau gerbang arah BTC dilonggarkan saat netral. QC 74: mati secara bawaan karena ujinya rugi (QSE_NETRAL_LONGGAR=1)."""
    return NETRAL_LONGGAR and btc_netral(bj)


def status_btc(bj=None, ambil=True):
    """Baris status pasar untuk bubble pertama."""
    bj = btc_jarak() if (bj is None and ambil) else bj
    if bj is None:
        return "₿ BTC 4J: data belum tersedia"
    nm = "⚖️ <b>BTC NETRAL</b> · Long dan Short terbuka" if btc_netral(bj) else \
         ("📈 <b>BTC FOKUS LONG</b>" if bj > 0 else "📉 <b>BTC FOKUS SHORT</b>")
    return f"{nm}  ·  4J {bj:+.1f}% dari EMA 50"


def gerbang_qc71(k, arah, bj):
    """Alasan sinyal ditahan menurut uji QC 71, atau ''. Matikan: QSE_GERBANG_QC71=0."""
    if bj is None or os.environ.get("QSE_GERBANG_QC71", "1") == "0":
        return ""
    if k == "msb_hpz" and arah == "SHORT" and bj > 0:
        return f"MSB HPZ SHORT saat BTC 4J di atas EMA 50 ({bj:+.1f}%): uji rugi di 2023, 2025, 2026"
    if k == "mcginley" and arah == "LONG" and bj <= -2:
        return f"McGinley LONG saat BTC 4J {bj:+.1f}% dari EMA 50 (lebih dari 2% di bawah): uji rugi di 2023 sampai 2026"
    return ""


def baris_spesialis(k, arah, bj=None):
    """Baris kartu: teknik ini spesialis arah ini di kondisi BTC sekarang. Kosong kalau bukan."""
    v = SPESIALIS.get((k, arah))
    if not v:
        return ""
    bj = btc_jarak() if bj is None else bj
    if bj is None or (v[0] == "atas") != (bj > 0):
        return ""
    return (f"🎯 <b>SPESIALIS {arah}</b>: teknik ini paling tajam untuk {arah} saat BTC 4J di {v[0]} EMA 50 (sekarang {bj:+.1f}%). "
            f"Uji aturan live: {v[1]}")


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


DUMP_SATU = 0.12
PUMP_SATU = 0.10


def pump_tolak(df, arah):
    """SHORT pada koin yang naik lebih dari 30% dalam 30 hari (180 candle 4J) dilewati. Uji 2021-2026 semua jalur:
    SHORT seperti ini PF 0.80 (2021-23) dan 0.79 (2024-26). Dibuang: total naik +28R dan +17R, PF naik di dua periode.
    Return teks alasan atau ''."""
    try:
        if df is None or len(df) < 2:
            return ""
        if arah == "LONG" and os.environ.get("QSE_AKHIR_PEKAN", "1") == "1" and time.gmtime(time.time()).tm_wday in (5, 6):
            # v150 (riset/upgrade/hasil_g22.txt, 383 koin, universe 150 koin likuid): LONG yang masuk Sabtu-Minggu UTC
            # (Sabtu 07:00 sampai Senin 06:59 WIB) rugi di 2024 (-0.07R), 2025 (-0.14R), dipilih dari dua tahun itu lalu terbukti lagi
            # di 2026 (-0.11R) yang tidak ikut memilih. Ditahan: NILAI 8+ 2025 PF 1.26 -> 1.39, 2026 PF 1.34 -> 1.39.
            return "LONG akhir pekan (Sabtu-Minggu UTC): rugi di 2024, 2025, dan 2026"
        if arah == "LONG":
            # v150 (2 Nov 2026, riset/upgrade/ringkasan.txt nomor 29): LONG tepat sesudah candle 4J sinyal naik 10% atau lebih ditahan.
            # 2021-23 untung besar (PF 4.58), tapi sejak 2024 rugi: 2024 PF 0.79, 2025-26 PF 0.87, yang lolos profil koin PF 0.84.
            o_ = float(df["open"].iloc[-1])
            naik = (float(df["close"].iloc[-1]) - o_) / o_ if o_ > 0 else 0.0
            return (f"candle 4J sinyal sudah terbang {naik * 100:.0f}%, LONG di pucuk (sejak 2024 PF 0.79-0.87)"
                    if naik >= PUMP_SATU else "")
        if arah != "SHORT" or len(df) < 181:
            return ""
        c = df["close"].astype(float)
        # v150 (2 Nov 2026, kasus UNI -13% satu candle): SHORT tepat sesudah candle 4J sinyal anjlok 12% atau lebih dilewati.
        # Uji 2021-2026 semua jalur: 94 sinyal seperti ini rata -0.18R (2021-23 -0.32R, 2024-26 -0.12R), rugi di dua periode.
        # Dibuang: NILAI 8+ total +298R -> +310R, PF 1.37 -> 1.38, semua sinyal tetap (PF 1.24). Ambang 10% dan 11% tidak konsisten.
        o_ = float(df["open"].iloc[-1])
        dump = (o_ - float(c.iloc[-1])) / o_ if o_ > 0 else 0.0
        if dump >= DUMP_SATU:
            return f"candle 4J sinyal sudah anjlok {dump * 100:.0f}%, SHORT di dasar dump (uji 2021-2026 rata -0.18R)"
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


# Lama trade di uji 2021-2026 dengan batas waktu 36 jam (27 Okt 2026, populasi sinyal live, riset/porto/stat_waktu.py):
# (persen kena TP 20% dalam 36 jam, median jam sampai TP 20%, median lama trade yang sudah aman dalam jam)
# Diperbarui dengan aturan jam ke-8 (riset/porto/stat_final.py).
LAMA_JALUR = {"ema_short": (59, 8, 47), "ichimoku": (55, 7, 31), "mcginley": (62, 7, 39), "msb_hpz": (61, 6, 25),
              "orderblock": (56, 8, 70), "rsi_vol": (57, 7, 32), "smc_choch": (60, 8, 32), "snr_vol": (64, 5, 26), "GZH": (43, 8, 84)}


def _hari(j):
    return f"{j / 24:.0f} hari" if j >= 36 else f"{j:.0f} jam"


def batas_masuk_teks(it, k, fmt=None):
    b = batas_masuk(it, k)
    if not b:
        return []
    fmt = fmt or TG.fp
    t = it.get("tick", 0.0001)
    jam = time.strftime("%d/%m %H:%M", time.gmtime(b[2] + 7 * 3600))
    return [f"🎯 Entry valid {fmt(b[0], t)} sampai {fmt(b[1], t)}, berlaku sampai {jam} WIB. Harga di luar itu atau lewat jam itu, lewati"]


# Uji 2021-2026 (dev 2021-23 / uji 2024-26): dari trade yang sudah +2R, berapa persen selesai di +2R atau lebih.
# Tinggi di kedua periode = jangan TP manual, tahan sampai TP jalur.
TAHAN_TP = {"snr_vol": "70%", "smc_choch": "68%", "orderblock": "59%"}          # mcginley keluar dari daftar sejak QC 59 (tanpa TP, trailing 3 ATR)


def be_r(j):
    """QC 61: level R untuk SL ke entry (tanpa TP sebagian) kalau jalur memakai aturan ini, selain itu None."""
    return STRAT.get(kunci_jalur(j), {}).get("be_r")


def kunci_jalur(j):
    """'saran snr_vol' atau 'snr_vol' -> 'snr_vol'."""
    return (j or "").replace("saran ", "").strip()


# TP SEBAGIAN (27 Okt 2026, untuk menaikkan win rate). Uji 35 ribu sinyal jalur 2021-2026 di candle 1 jam: tutup 20% di
# +0.5R lalu SL ke entry, sisa ikut aturan jalur (TP atau trailing). Sinyal mode seimbang (skor 3+): WR 73.2% (2021-23 72.7%,
# 2024-26 73.6%) lawan 45.5% cara lama (TP bertahap 25% di 1R dan 50% di 2R, 4 jalur tahan sampai TP), PF 1.56 lawan 1.54,
# rugi beruntun terpanjang 42 lawan 150 trade. Biayanya: total R per lot 57% dari cara lama, drawdown juga turun ke 67%.
# Semua 9 jalur naik WR ke 69-76%. Pembanding: 20% di 0.4R WR 77% total 47%, 20% di 0.75R WR 65% total 76%, 20% di 1R WR 58%.
TPS_R, TPS_PORSI = 0.5, 0.20


def tp_sebagian(entry, sl0, arah):
    """Harga TP sebagian (+0.5R dari entry)."""
    risk = abs(entry - sl0)
    return entry + TPS_R * risk if arah == "LONG" else entry - TPS_R * risk


# Tangga TP lain diuji 27 Okt 2026 (mode seimbang, 2021-2026): 20% 0.5R + 25% 1R PF 1.49, + 25% 2R PF 1.54,
# 20/25/25% di 0.5R/1R/2R PF 1.47, 25% 0.5R + 50% 2R PF 1.50, 20% tiap 0.5R/1R/2R/3R PF 1.48. Menang tetap 73%,
# PF dan total semua di bawah 20% di 0.5R saja (PF 1.56). Jadi tetap dua level: 20% di +0.5R, sisa 80% aturan jalur.


def rencana_be(entry, sl, arah, tick, be, jarak=None, fmt=None, waktu=True):
    """QC 61: rencana keluar jalur SL ke entry di +be R lalu trailing, tanpa TP sebagian dan tanpa batas waktu."""
    fmt = fmt or TG.fp
    risk = abs(entry - sl)
    if not risk or not entry:
        return []
    pc = lambda x: abs(x - entry) / entry * 100
    lv = entry + be * risk if arah == "LONG" else entry - be * risk
    rows = [f"🔒 <b>Untung sampai {fmt(lv, tick)} (+{pc(lv):.1f}%, +{be:g}R): pindahkan SL ke entry {fmt(entry, tick)}</b>. "
            "Tanpa TP sebagian, posisi 100% tetap jalan",
            f"🏁 <b>Sisa 100%: tanpa TP, ikut SL berjalan</b>" + (f" (Trailing Stop {fmt(jarak, tick)}, {jarak / entry * 100:.1f}%)" if jarak else ""),
            f"🛑 <b>SL: {fmt(sl, tick)} (-{pc(sl):.1f}%)</b>"]
    if waktu:
        rows.append("⏳ Tanpa aturan jam ke-12 dan batas 30 jam. Uji EMA Cross 2025-2026: +263R lawan +146R aturan lama")
        rows.append(f"📲 Pasang di Bybit, tombol TP/SL: Entire Position, SL Trigger Price {fmt(sl, tick)}. Saat robot kirim SL KE ENTRY, "
                    f"ganti SL ke {fmt(entry, tick)}. Lalu /entry supaya robot memantau")
    return rows


def rencana_tp(entry, sl, arah, tick, tp=None, jarak=None, fmt=None, uji=True, waktu=True):
    """Baris tebal rencana keluar untuk sinyal jalur: TP 20% posisi di +0.5R lalu SL ke entry, sisa 80% ke TP jalur
    atau SL berjalan, SL, dan batas waktu (waktu=False untuk kartu posisi yang sudah punya baris jam batasnya).
    Semua dengan harga dan persen dari entry."""
    fmt = fmt or TG.fp
    risk = abs(entry - sl)
    if not risk or not entry:
        return []
    pc = lambda x: abs(x - entry) / entry * 100
    tps = tp_sebagian(entry, sl, arah)
    rows = [f"💰 <b>TP {int(TPS_PORSI * 100)}% posisi: {fmt(tps, tick)} (+{pc(tps):.1f}%)</b>. Setelah kena, "
            f"<b>pindahkan SL ke entry {fmt(entry, tick)}</b>"]
    if tp:
        rows.append(f"🏁 <b>TP {100 - int(TPS_PORSI * 100)}% sisa: {fmt(tp, tick)} (untung {pc(tp):.1f}%)</b>")
    else:
        rows.append(f"🏁 <b>Sisa {100 - int(TPS_PORSI * 100)}%: tanpa TP, ikut SL berjalan</b>"
                    + (f" (Trailing Stop {fmt(jarak, tick)}, {jarak / entry * 100:.1f}%)" if jarak else ""))
    try:
        import qse_modal as MD
        jw = MD.waktu_jam()
    except Exception:
        jw = 30.0
    uj = UJI_WAKTU.get(round(jw))
    rows.append(f"🛑 <b>SL: {fmt(sl, tick)} (-{pc(sl):.1f}%)</b>"
                + (f"  ·  uji 2021-2026: menang {uj[0]}%, kena SL penuh {uj[1]}%" if (uji and uj) else ""))
    if waktu:
        sl8 = entry - 0.5 * risk if arah == "LONG" else entry + 0.5 * risk
        rows.append(f"🛡 <b>Jam ke-12 belum kena TP {int(TPS_PORSI * 100)}% dan harga melawan</b>: SL naik ke {fmt(sl8, tick)} (rugi {pc(sl8):.1f}%, separuh SL). "
                    f"Sudah rugi lebih dari itu, tutup market. Harga searah: SL tetap")
    if jw > 0 and waktu:
        rows.append(f"⏳ <b>Batas {jw:g} jam</b>: belum kena TP {int(TPS_PORSI * 100)}%, tutup market. Sudah kena, posisi aman "
                    f"dan tidak makan slot")
    if waktu:
        rows.append(f"📲 Pasang di Bybit, tombol TP/SL: Partial Position, Proportion {int(TPS_PORSI * 100)}, TP Trigger Price "
                    f"{fmt(tps, tick)}. Entire Position, SL Trigger Price {fmt(sl, tick)}"
                    + (f", TP Trigger Price {fmt(tp, tick)}" if tp else "") + ". Lalu /entry supaya robot memantau")
    return rows


# Per trade semua sinyal live 2021-2026 (TP sebagian 20% di +0.5R, jam ke-8 SL ke -0.5R, batas 36 jam): menang 62%,
# kena SL penuh 3%, PF 1.86. Tanpa jam ke-8: menang 68%, SL penuh 17%, PF 1.82. riset/porto/pf_slpenuh2.py
# v150 per trade semua sinyal 2021-2026 data Binance (riset/upgrade/run_g13.py): jam 12 dinamis + 30 jam menang 61%, SL penuh 11%, PF 1.36
# (aturan lama di data yang sama: menang 58%, SL penuh 6%, PF 1.34)
UJI_WAKTU = {30: (61, 11), 36: (62, 3)}


def tp_cepat_teks(it, fmt=None, k=None, waktu=True):
    """Rencana TP untuk semua kartu sinyal (nama lama dipertahankan): 20% di +0.5R lalu SL ke entry, sisa aturan jalur.
    it: entry, sl atau sl0, arah, tick, tp (jalur ber-TP), dan jarak atau trail_atr+sl_atr (jalur trailing)."""
    try:
        sl0 = it.get("sl0", it["sl"])
        risk = abs(it["entry"] - sl0)
        if not risk:
            return []
        jarak = it.get("jarak")
        if not jarak and it.get("trail_atr") and it.get("sl_atr"):
            jarak = it["trail_atr"] / it["sl_atr"] * (it.get("risk") or risk)
        be = it.get("be_r") or (be_r(k) if k else None)
        if be and not it.get("tp"):
            return rencana_be(it["entry"], sl0, it.get("arah", "LONG"), it.get("tick", 0.0001), be, jarak=jarak, fmt=fmt, waktu=waktu)
        return rencana_tp(it["entry"], sl0, it.get("arah", "LONG"), it.get("tick", 0.0001), tp=it.get("tp"), jarak=jarak, fmt=fmt,
                          waktu=waktu)
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


REM7_NILAI = 8          # v150: saat rem 7 hari menyala hanya NILAI 10 (skor 90) yang dikirim, setengah lot


def lolos_mode(pr):
    """pr = hasil prioritas(). True kalau skor label cukup untuk mode sekarang.
    Rem 7 hari menyala: hanya NILAI 10. Uji 2023-2026 (riset/upgrade/hasil_v150.txt, hasil_v150b.txt): dibanding tahan total,
    total +161R jadi +168R, 5.9 jadi 6.5 sinyal per minggu, PF 2025-26 1.58 jadi 1.62, DD 17R jadi 18R."""
    try:
        import qse_catat as CT
        if CT.rem7()["aktif"] and pr[0] < REM7_NILAI:
            return False
    except Exception:
        pass
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
    skor 8+ PF 2.25/2.22. Win rate dengan TP sebagian 20% di +0.5R lalu SL ke entry: 71.7%, 74.8%, 77.5% (PF 1.42, 1.73, 2.18)."""
    if n >= 8:
        return "👑 NILAI 10 (menang 78%, PF 2.2)"
    if n >= 5:
        return "🔥 NILAI 9 (menang 75%, PF 1.7)"
    if n >= 3:
        return "✅ NILAI 8 (menang 72%, PF 1.4)"
    return ""


def label_prioritas(p):
    return kelas(p[0]) or "tanpa label"


def combo_teks(it):
    """Baris COMBO (dan COMBO EMAS) untuk kartu semua jalur, plus label VOLUME PASAR TINGGI dan BTC.D TURUN, dan info
    token unlock >= 1% dalam 7 hari (qse_unlock, info saja di kartu, LONG baru sudah ditahan di qse_porto.izin)."""
    try:
        import qse_unlock as UL
        ul = UL.teks(it.get("sym") or "", it.get("arah"))
    except Exception:
        ul = ""
    vt = [ul] if ul else []
    vt += ([f"🔊 <b>VOLUME PASAR TINGGI</b>: volume BTC 4J {it['vol_tinggi']:g}x rata 30 hari. Uji 2021-2026 sinyal di saat "
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
                    out[k].append(f"{'✅' if R > 0 else '🛑'} <b>{STRAT[k]['nama'].upper()} SELESAI  ·  {it['sym']} {it['arah']}  ·  {'untung' if R > 0 else 'rugi'} {abs(R) * it['risk'] / it['entry'] * 100:.2f}%</b>\n"
                                  + (f"TP {TG.fp(it['tp'], t)} tersentuh." if st == "TP" else
                                     f"Kena SL di sekitar {TG.fp(it['sl'], t)}. Analisa volume menyusul." if st == "SL" else
                                     f"Sudah {it.get('maks_bar', MAKS_BAR)} candle 4J. Tutup sekarang di harga pasar."))
            # pesan GESER SL tidak lagi dari sini: dikirim per orang oleh pantau() (qse_saya._kabar_geser), dihitung dari
            # entry dan SL masing-masing, tidak pernah mundur setelah TP sebagian memindah SL ke entry

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
    bj = btc_jarak()
    try:
        izin = izin_btc()
    except Exception:
        izin = {"LONG": True, "SHORT": True}
    pindai = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]

    def cek(sym):
        df = _k4(sym, 600)
        if df is None or len(df) < 261:
            return sym, {}, None, 0.0
        return sym, sinyal(df, bn, netral_longgar(bj)), df, float((df["close"] * df["volume"]).iloc[-180:].sum())
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
        slot = min(MAKS_BARU, MAKS_BUKA - sum(1 for x_ in d["open"].values() if not x_.get("uji_live")))          # trade kertas uji live tidak memakan slot
        if slot <= 0:
            _CEK[k] = (0, "slot posisi penuh")
            continue
        boleh = set(urut[:cfg["likuid"]]) if cfg["likuid"] else set(urut)
        buka = {it["sym"] for it in d["open"].values()} | dipakai
        calon = [x for x in semua if k in x[1] and x[0] in boleh and x[0] not in buka]
        calon.sort(key=lambda x: urut.index(x[0]))
        baru = []
        for sym, sg, df, _ in calon:
            if sum(1 for x_ in baru if not x_.get("uji_live")) >= slot or len(baru) >= slot + 3:
                break
            if sym in dipakai:
                continue
            arah, a = sg[k]
            netral_buka = bool(k == "snr_vol" and bn is not None and bn != (arah == "LONG"))          # QC 73: SnR melawan sisi BTC, hanya lolos saat netral
            if cfg.get("izin_btc") and not izin.get(arah, True):
                if not netral_longgar(bj):
                    print(f"[STRAT {k}] {sym} {arah} ditahan: izin BTC 4J tidak mengizinkan {arah}")
                    continue
                netral_buka = True          # QC 73: BTC netral, arah tidak ditahan BTC. Sinyalnya kelas ringan
            try:          # v174 QC 72: kapok (3 SL beruntun di koin dan arah ini, 14 hari)
                kpk = __import__("qse_nyawa").kapok(sym, arah)
            except Exception:
                kpk = ""
            if kpk:
                print(f"[STRAT {k}] {sym} {arah} ditahan: {kpk}")
                continue
            gq = gerbang_qc71(k, arah, bj)
            if gq and netral_longgar(bj):
                gq, netral_buka = "", True
            if gq:
                print(f"[STRAT {k}] {sym} {arah} ditahan: {gq}")
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
                      trail_atr=cfg.get("trail_atr", TRAIL_ATR), trail_pct_2r=cfg.get("trail_pct_2r"), be_r=cfg.get("be_r"))
            if cfg.get("tp_r"):
                it.update(tp=px + cfg["tp_r"] * risk if L else px - cfg["tp_r"] * risk, maks_bar=cfg["maks_bar"])
            it.update(mutu=sk, mutu_plus=mp, btc_j=bj, netral_buka=netral_buka)
            try:
                import qse_pola as QPL
                it["pola_c"] = QPL.pola_sinyal(*(df[x_].values.astype(float) for x_ in ("open", "high", "low", "close")), arah)
            except Exception as ex:
                print("[WARN] pola candle", ex)
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
            tolak_senin = PO.senin_tolak(it.get("combo"), it.get("combo_emas"), it.get("combo_fix"), it.get("dom_turun"))
            if tolak_senin:
                print(f"[STRAT {k}] {sym} {arah} dilewati: {tolak_senin}")
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
            it["peringkat"] = urut.index(sym) + 1 if sym in urut else 0
            it["uji_live"] = uji_live(k, arah, bj, it["peringkat"], len(it.get("combo") or []) + 1)          # QC 74
            if it["uji_live"]:
                print(f"[STRAT {k}] {sym} {arah} UJI LIVE (trade kertas, tidak disiarkan): {it['uji_live']}")
            import qse_otak as OT
            OT.tandai(it, k, df)          # otak robot: peluang rendah atau celah live = tetap dicatat, tidak dikirim
            baru.append(it)
            dipakai.add(sym)
            if not OT.tersaring(it) and not it["uji_live"]:
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
# mesin di luar STRAT yang ikut pindai paksa (QC 72). GZH SHORT kelas ringan (QC 64), GZH LONG kelas utama.
LAIN_PINDAI = {"ichimoku": dict(nama="Ichimoku", likuid=20, sl_atr=1.5), "orderblock": dict(nama="Order Block", likuid=50, tp_r=4.0),
               "gzh": dict(nama="GZH Golden Zone", likuid=0, sl_atr=1.5, tp_r=0.8)}


def sapu_rusak(now=None):
    """v174 QC 72: sinyal robot dari candle sebelumnya yang belum aman (belum kena TP awal) dicek ulang tiap candle 4J. Ada pola candle
    lawan atau CHoCH / MSB lawan: sinyal diberi cap batal (tidak pernah ditawarkan lagi, tidak diturunkan kelasnya) dan dikabari sekali.
    QC 73: kabarnya sadar posisi (qse_radar.batal_teks).
    Trade kertas robot tetap jalan untuk statistik. Return list pesan."""
    import qse_pola as QPL
    now = now or time.time()
    c4 = int(now // 14400) * 14400
    out = []

    def proses(nama, k):
        def f(d):
            ps = []
            for it in d["open"].values():
                if it.get("batal") or it.get("t", now) >= c4 - 60 or (it.get("v9") or {}).get("aman") or now - it.get("t", now) > 3 * 14400:
                    continue
                tl = QPL.tanda_lawan(it["sym"], it["arah"])
                if tl and tl["batal"]:
                    it["batal"] = tl["alasan"]; it["pola_lawan"] = tl["pola"] or "CHoCH / MSB lawan"
                    # v175 QC 73: sadar posisi. Sudah entry = MANAJEMEN POSISI AKTIF dengan harga konkrit, belum entry = kabar singkat
                    try:
                        ps += __import__("qse_radar").batal_teks(it["sym"], it["arah"], nama, tl)
                    except Exception as ex_:
                        print("[WARN] batal sadar posisi", ex_)
                        ps.append(("ringkas", f"{it['sym']} {it['arah']} ({nama}: {tl['alasan']})"))
            return ps
        return f
    for k, cfg in STRAT.items():
        try:
            out += _ubah(k, proses(cfg["nama"], k)) or []
        except Exception as ex:
            print("[WARN] sapu rusak", k, ex)
    for nama, mod in (("Ichimoku", "qse_ichimoku"), ("Order Block", "qse_ob")):
        try:
            out += __import__(mod)._ubah(proses(nama, mod)) or []
        except Exception as ex:
            print("[WARN] sapu rusak", nama, ex)
    try:
        return __import__("qse_radar").gabung_batal(out)
    except Exception as ex:
        print("[WARN] gabung batal", ex)
        return [t for _, t in out]


def pindai_sekarang(batas=60, top=None, intrabar=False):
    """v173 QC 71: pindai paksa detik ini, tanpa mencatat posisi apa pun. Semua koin Futures teratas dicek ulang di dua candle 4J
    terakhir yang sudah tutup, lalu dipilah: masih valid di harga sekarang (harga dalam 0.5R dari harga sinyal dan umur sinyal belum
    lewat) atau sudah lewat. Return (valid, lewat, info). valid = list dict urut rekomendasi.
    intrabar=True (QC 77, dipakai scan 1 jam): candle 4J yang MASIH BERJALAN ikut dicek dengan harga dan volume sementara. Sinyal baru
    di candle berjalan diberi tanda intrabar dan jam ke berapa candle itu (uji run_v179_intrabar: lihat qse_radar.kelas_intrabar)."""
    t0 = time.time()
    tk = B.get_tickers()
    try:
        tick = B.get_symbols()
    except Exception:
        tick = {}
    bn, bj = btc_naik(), btc_jarak()
    try:
        izin = izin_btc()
    except Exception:
        izin = {"LONG": True, "SHORT": True}
    semua_ = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if (s in tick or not tick) and B.ada_futures(s)]
    # QC 73: universe diperluas. 150 teratas tetap, sisanya ikut kalau turnover 24 jam memadai, maksimal TOP_PINDAI koin
    pindai = semua_[:TOP_KOIN] + [s for s in semua_[TOP_KOIN:(top or TOP_PINDAI)] if tk[s]["turnover"] >= MIN_TURNOVER]
    netral = netral_longgar(bj)

    def cek(sym):
        try:
            df = _k4(sym, 600)
            if df is None or len(df) < 262:
                return sym, []
            out = []
            for mundur in (0, 1):
                d_ = df if mundur == 0 else df.iloc[:-1]
                for k, (arah, a) in sinyal(d_, bn, netral).items():
                    if mundur and umur_maks(k) < 2:
                        continue
                    out.append((k, arah, a, mundur, float(d_["close"].iloc[-1]), d_))
            if intrabar:          # QC 77: candle 4J berjalan, minimal sudah 1 jam. Sinyal yang belum ada di candle tutup terakhir = baru
                try:
                    raw = B._raw(sym, "240", 600)
                    umur_ = time.time() - int(raw.index[-1]) / 1000
                    if len(raw) > len(df) and 3000 <= umur_ < 14400:
                        lama_ = {(k_, x_[1]) for x_ in out for k_ in [x_[0]] if x_[3] == 0}
                        for k, (arah, a) in sinyal(raw, bn, netral).items():
                            if (k, arah) not in lama_:
                                out.append((k, arah, a, 0, float(raw["close"].iloc[-1]), dict(df=raw, ib=int(umur_ // 3600) or 1)))
                except Exception as ex_:
                    print("[WARN] pindai intrabar", sym, ex_)
            # v174 QC 72: Ichimoku, Order Block, dan GZH ikut dihitung ulang di candle terakhir detik ini juga
            try:
                import qse_ichimoku as IC_
                ar_, a_ = IC_._sinyal(df)
                if ar_:
                    out.append(("ichimoku", ar_, a_, 0, float(df["close"].iloc[-1]), df))
            except Exception as ex_:
                print("[WARN] pindai ichimoku", sym, ex_)
            try:
                import qse_ob as OB_
                x_ = OB_._sinyal(df)
                if x_ and (bn or netral):          # QC 73: BTC netral, Order Block LONG tidak ditahan sisi BTC (kelas ringan)
                    out.append(("orderblock", "LONG", x_["atr"], 0, float(df["close"].iloc[-1]), dict(df=df, sl=x_["sl"], nb=not bn)))
            except Exception as ex_:
                print("[WARN] pindai ob", sym, ex_)
            try:
                import qse_gzh2 as GZ_
                hh_, ll_, cc_ = (df[x].values.astype(float) for x in ("high", "low", "close"))
                for ar_g, fn_g in (("SHORT", GZ_.setup_short), ("LONG", GZ_.setup_terakhir)):
                    sisi = (bn is False) if ar_g == "SHORT" else bool(bn)          # sisi BTC yang biasa dipakai GZH
                    if bn is None or not (sisi or netral):
                        continue          # QC 73: BTC netral, GZH dicari dua arah. Arah yang melawan sisi BTC kelas ringan
                    g_ = fn_g(hh_, ll_, cc_)
                    if g_:
                        out.append(("gzh", ar_g, g_.get("atr") or float(_atr(hh_, ll_, cc_)[-1]), 0, float(df["close"].iloc[-1]),
                                    dict(df=df, sl=g_.get("sl"), tp=g_.get("tp"), nb=not sisi)))
            except Exception as ex_:
                print("[WARN] pindai gzh", sym, ex_)
            return sym, out
        except Exception as ex:
            print("[WARN] pindai", sym, ex)
            return sym, []
    # batas 60 detik: perintah Telegram tidak boleh macet lama (penjaga listener merestart di 180 detik). Koin yang belum selesai dilewati
    from concurrent.futures import as_completed
    ex = ThreadPoolExecutor(16)
    fs = [ex.submit(cek, s_) for s_ in pindai]
    hasil = []
    try:
        for f_ in as_completed(fs, timeout=batas):
            hasil.append(f_.result())
    except Exception as e_:
        print(f"[WARN] pindai paksa belum selesai dalam {batas} detik:", type(e_).__name__)
    ex.shutdown(wait=False, cancel_futures=True)
    n_selesai = len(hasil)
    urut = [s for s in pindai]
    valid, lewat = [], []
    try:
        import qse_pola as QPL
    except Exception:
        QPL = None
    for sym, lst in hasil:
        for k, arah, a, mundur, cl, d_ in lst:
            ekstra = d_ if isinstance(d_, dict) else {}
            d_ = ekstra.get("df", d_) if ekstra else d_
            cfg = STRAT.get(k) or LAIN_PINDAI[k]
            if cfg.get("manual"):
                continue
            if cfg["likuid"] and urut.index(sym) >= cfg["likuid"]:
                continue
            d = 1 if arah == "LONG" else -1
            risk = cfg.get("sl_atr", SL_ATR) * a
            if ekstra.get("sl"):
                risk = abs(cl - ekstra["sl"])
            px = tk[sym]["last"] or cl
            geser = (px - cl) * d / risk
            why = gerbang_qc71(k, arah, bj) or ("" if izin.get(arah, True) or not cfg.get("izin_btc") else f"izin BTC 4J tidak mengizinkan {arah}")
            nb = bool((why and netral) or ekstra.get("nb") or (k == "snr_vol" and bn is not None and bn != (arah == "LONG")))
            # QC 73: BTC netral, gerbang arah BTC dilepas (sinyalnya kelas ringan)
            if nb:
                why = ""
            if not why and (risk / px < 0.003 or risk / px > 0.10):
                why = "jarak SL di luar 0.3% sampai 10% harga"
            if not why and abs(geser) > 0.5:
                why = f"harga sudah {'lari' if geser > 0 else 'melawan'} {abs(geser):.1f}R dari harga sinyal"
            tl = None
            if not why:
                try:
                    why = __import__("qse_nyawa").kapok(sym, arah)
                except Exception:
                    pass
            if not why and mundur and QPL:          # sinyal candle sebelumnya: batal kalau candle terakhir memberi tanda lawan
                tl = QPL.tanda_lawan(sym, arah)
                if tl and tl["batal"]:
                    why = "struktur berubah: " + tl["alasan"]
            pc = ""
            try:
                pc = QPL.pola_sinyal(*(d_[x_].values.astype(float) for x_ in ("open", "high", "low", "close")), arah) if QPL else ""
            except Exception:
                pass
            sp = SPESIALIS.get((k, arah))
            sp_ok = bool(sp and bj is not None and (sp[0] == "atas") == (bj > 0))
            nilai = (2 if sp_ok else 0) + (1 if pc and QPL and (k, arah) in QPL.POLA_TERUJI else 0) + (1 if geser < 0 else 0) + (0 if mundur else 1) \
                - (2 if k == "ema_short" else 0)
            luar = urut.index(sym) >= TOP_KOIN
            ringan = bool(cfg.get("ringan") or k == "ema_short" or (k == "gzh" and arah == "SHORT") or nb or luar)
            row = dict(intrabar=ekstra.get("ib", 0), netral=nb, luar=luar, peringkat=urut.index(sym) + 1, t4=int(d_.index[-1]) if hasattr(d_, "index") else 0, sym=sym, k=k, nama=cfg["nama"], arah=arah, px=px, sl=px - d * risk, risk=risk, geser=geser, mundur=mundur, pola=pc,
                       spesialis=sp_ok, nilai=nilai - (1 if ringan else 0), why=why, tick=tick.get(sym, 0.0001), ringan=ringan,
                       entry_robot=cl, tp=(px + (ekstra["tp"] - cl)) if ekstra.get("tp") else (px + d * cfg["tp_r"] * risk) if cfg.get("tp_r") else None)
            (lewat if why else valid).append(row)
    try:          # QC 73: kelas disamakan dengan kartu jalur live (eks-tahanan otak, skor Tren rendah, kompas merah = kelas ringan)
        import qse_ditahan as DT_
        live_ = {(k_, it_["sym"], it_["arah"]): it_ for k_, _, it_ in DT_._sumber()}
        for r in valid:
            it_ = live_.get((r["k"], r["sym"], r["arah"]))
            if it_ is not None and DT_.kelas(r["k"], it_)[0] == "RINGAN":
                r["ringan"] = True
    except Exception as ex:
        print("[WARN] kelas pindai", ex)
    # QC 73 konfluensi: teknik berbeda searah di koin yang sama (sinyal yang batal karena struktur atau kapok tidak dihitung)
    grup = {}
    for r in valid + [x for x in lewat if "struktur berubah" not in x["why"] and "kapok" not in x["why"].lower()]:
        grup.setdefault((r["sym"], r["arah"]), {})[r["k"]] = r["nama"]
    satu = {}
    for r in valid:
        g = grup[(r["sym"], r["arah"])]
        r["konf"] = len(g); r["konf_nama"] = [v for kk, v in g.items() if kk != r["k"]]
        if konf_utama(r["arah"], bj, r["konf"]) and not r["luar"] and not r["netral"]:
            r["ringan"] = False; r["nilai"] += 1 + r["konf"]
        elif r["konf"] < 2 and r["peringkat"] > PERINGKAT_RINGAN:
            r["ringan"] = True          # QC 77: teknik tunggal di koin peringkat 111-150 disiarkan sebagai kelas ringan (uji PF 0.87)
        b = satu.get((r["sym"], r["arah"]))
        if b is None or (r["ringan"], -r["nilai"]) < (b["ringan"], -b["nilai"]):
            satu[(r["sym"], r["arah"])] = r          # satu koin satu kartu: ambil teknik terbaiknya
    valid = sorted(satu.values(), key=lambda r: (r["ringan"], -r["nilai"], urut.index(r["sym"])))
    for r in list(valid):          # QC 74: kelompok yang rugi di uji mundur tidak ditawarkan (robot tetap mencatat trade kertasnya)
        ul = uji_live(r["k"], r["arah"], bj, r["peringkat"], r["konf"])
        if ul:
            r["why"] = "uji live: " + ul
            valid.remove(r); lewat.append(r)
    return valid, lewat, dict(n=n_selesai, total=len(pindai), detik=time.time() - t0, bj=bj, netral=btc_netral(bj))


def buka_radar(r, now=None):
    """QC 83 (kasus AVAX): kartu scan 1 jam dari candle 4J yang MASIH BERJALAN (intrabar) belum punya posisi jalur, jadi /entry tidak
    menemukan jalurnya: nilai tidak tercatat dan posisi memakai TP1/TP2 umum, bukan TP 20% + SL berjalan seperti isi kartu. Fungsi ini
    membuka posisi jalur untuk kartu itu saat kartu dikirim, dengan level yang sama dengan kartu. Sesudah itu /entry, /status, SL berjalan,
    dan kabar keluar memakai mesin jalur yang sama dengan sinyal candle tutup. Return True kalau posisi jalur dibuat."""
    k = r.get("k")
    cfg = STRAT.get(k)
    if not cfg or cfg.get("manual") or not r.get("intrabar"):
        return False
    sym, arah = r["sym"], r["arah"]
    if any(it["sym"] == sym for kk in STRAT for it in lihat(kk)["open"].values()):
        return False          # satu koin satu jalur
    now = now or time.time()
    L = arah == "LONG"
    px, risk = float(r["px"]), float(r["risk"])
    if not (px > 0 and risk > 0):
        return False
    sl = px - risk if L else px + risk
    try:
        raw = B._raw(sym, "240", 600)
    except Exception as ex:
        print("[WARN] buka radar data", sym, ex)
        raw = None
    t4 = int(r.get("t4") or 0)          # candle 4J berjalan saat kartu dibuat. Candle itu ikut dikelola begitu tutup
    it = dict(sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, risk=risk, best=px, bar=0, t=now, last=(t4 - H4) if t4 else 0, close=px,
              tick=r.get("tick") or 0.0001, sl_atr=cfg.get("sl_atr", SL_ATR), trail_atr=cfg.get("trail_atr", TRAIL_ATR),
              trail_pct_2r=cfg.get("trail_pct_2r"), be_r=cfg.get("be_r"), intrabar=int(r["intrabar"]), radar=True,
              peringkat=r.get("peringkat") or 0, uji_live="", mutu=0, mutu_plus=[], btc_j=btc_jarak(), netral_buka=bool(r.get("netral")))
    if cfg.get("tp_r"):
        it.update(tp=px + cfg["tp_r"] * risk if L else px - cfg["tp_r"] * risk, maks_bar=cfg["maks_bar"])
    if raw is not None and len(raw) >= 262:
        try:
            sk, mp, _ = mutu(raw, arah)
            it.update(mutu=sk, mutu_plus=mp)
        except Exception as ex:
            print("[WARN] buka radar mutu", ex)
        try:
            it["combo"] = _combo(raw, k, arah, btc_naik(), sym)
            it["combo_emas"] = combo_emas(k, it["combo"])
            it["combo_fix"] = combo_fix(k, it["combo"])
            it["combo_raja"] = combo_raja(it["combo"])
            it["vol_tinggi"] = vol_tinggi()
        except Exception as ex:
            print("[WARN] buka radar combo", ex)
    key = f"{sym}|{int(now)}"

    def simpan(dd):
        dd["open"][key] = it
    _ubah(k, simpan)
    print(f"[STRAT {k}] {sym} {arah} posisi jalur dibuka dari kartu scan 1 jam (intrabar jam ke-{it['intrabar']})")
    return True


def pindai_teks(maks=6):
    """Teks /sinyal4j: hasil pindai paksa. QC 73: tiap bagian jadi bubble sendiri (dipisah TG.PISAH)."""
    import qse_radar as RD
    try:
        valid, lewat, inf = pindai_sekarang()
    except Exception as ex:
        return f"🔎 <b>PINDAI PAKSA</b>: gagal mengambil data ({TG.e(str(ex)[:120])}). Coba lagi sebentar."
    return TG.PISAH.join(RD.bubble(valid, lewat, inf, "PINDAI PAKSA", maks=maks))



def _sudah_pakai(it):
    """Baris per orang yang sudah memakai sinyal ini lalu keluar rugi atau impas (catatan tiap orang terpisah)."""
    try:
        import qse_saya as SY
        return SY.baris_sudah_pakai(it["sym"], it["arah"], it.get("t"))
    except Exception:
        return []


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
    lot_b, cat_hari = PO.lot_hari(lot_b, it.get("dom_turun"))
    mb_baris = ""
    try:
        import qse_mb as MBJ          # v150: otak MB asli FlyWire menilai sinyal jalur, lot x2 kalau disukai, x0.4 kalau dijauhi
        kali, va = MBJ.lot_jalur(k, it["sym"], it["arah"])
        if kali != 1.0:
            lot_b = f"{min(1.0, SY.lot_angka(lot_b) * kali):g}x"
            mb_baris = (f"🧬 Otak MB asli: valensi {va:+.3f}, {'disukai, lot dinaikkan' if kali > 1 else 'dijauhi, lot diturunkan'} "
                        f"(uji 2025-2026: disukai rata +0.21R, dijauhi +0.09R)")
    except Exception as ex:
        print("[WARN] lot MB jalur", ex)
    kp_teks = ""
    try:
        import qse_kompas as KP          # 9 Nov 2026: LONG melawan kompas merah, lot 0.5x
        kk, kp_teks = KP.label(it["arah"])
        import qse_overmind as OM          # QC 57: alasan kelas ringan dari dewan
        r_, why_ = OM.kelas_jalur(k)
        if r_:
            kp_teks = (kp_teks + "\n" if kp_teks else "") + why_
        if kk != 1.0:
            lot_b = "0.2x"          # kelas ringan
    except Exception:
        pass
    jg, ju = [], False
    try:
        import qse_jagoan as JG          # QC 60/61: label koin jagoan, KELAS UTAMA otomatis untuk jagoan sejati
        jg = JG.tandai(k, it)
        ju = bool(jg and JG.kelas_utama(it.get("jagoan")))
        if ju:
            lot_b = f"{max(SY.lot_angka(lot_b), 0.5):g}x"
    except Exception as ex:
        print("[WARN] jagoan", ex)
    try:
        import qse_klaster as KS          # v170 QC 66: skor klaster Tren, kuintil terbawah kelas ringan
        _kt = KS.baris(k, it)
        if _kt:
            kp_teks = (kp_teks + "\n" if kp_teks else "") + _kt
            if KS.lemah(it.get("tren")) and not ju:
                lot_b = "0.2x"
    except Exception as ex:
        print("[WARN] klaster", ex)
    try:          # v173 QC 71: label spesialis arah dan pola candle di candle sinyal
        import qse_pola as QPL
        for _b in (baris_spesialis(k, it["arah"], it.get("btc_j")), QPL.baris_pola(k, it["arah"], it.get("pola_c"))):
            if _b:
                kp_teks = (kp_teks + "\n" if kp_teks else "") + _b
    except Exception as ex:
        print("[WARN] spesialis", ex)
    if k == "ema_short" and not ju:
        lot_b = "0.2x"          # QC 62: EMA Cross SHORT kelas ringan (2026 -128R, saringan latih tidak membalik), kecuali jagoan sejati
        kp_teks = (kp_teks + "\n" if kp_teks else "") + "🟨 EMA Cross SHORT kelas ringan: rugi di 2026 (uji -128R)"
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], kelas=MD.kelas_dari(SY.lot_angka(lot_b)), konf=1 + len(it.get("combo") or []),
                           arah=it["arah"], bj=it.get("btc_j"))          # QC 88 lot per konfluensi
    except Exception:
        lot = ""
    jarak = it.get("trail_atr", TRAIL_ATR) * a
    try:
        import qse_cuaca as CU          # 9 Nov 2026: cuaca pasar, kelas koin, rekam jejak teknik di koin ini
        cuaca = CU.baris(k, it)
    except Exception:
        cuaca = ""
    return "\n".join([
        SY.GARIS,
        *jg,
        f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {it['arah']}</b>  ·  {cfg['nama']} 4J",
        f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  <b>{MD.teks_kelas(lot_b)}</b> (margin dan leverage tiap orang di baris bawah)",
        *([cuaca] if cuaca else []),
        *([kp_teks] if kp_teks else []),
        *combo_teks(it),
        *([cat_hari] if cat_hari else []),
        *([mb_baris] if mb_baris else []),
        *mutu_teks(it),
        *(["🔁 <b>PULLBACK DALAM TREN BESAR</b>: searah EMA 200, tren pendek baru berbalik. "
           "Uji 2021-2026 McGinley pullback PF 1.43, McGinley biasa PF 1.18"] if it.get("pullback") else []),
        SY.GARIS,
        (SY.blok_salin(it["entry"], it["sl"], it["tp"], it["tp"], "MARKET", t, sym=it["sym"], arah=it["arah"], rentang=batas_masuk(it, k),
                       sebagian=True) if it.get("tp") else
         SY.blok_salin(it["entry"], it["sl"], order="MARKET", tick=t, catatan_tp="tanpa, pakai SL berjalan", sym=it["sym"], arah=it["arah"],
                       rentang=batas_masuk(it, k), sebagian=True)),
        *batas_masuk_teks(it, k),
        *_sudah_pakai(it),
        *tp_cepat_teks(it, k=k),
        *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Tetap boleh entry, pakai lot setengah sampai pulih"] if rm else []),
        "💡 <b>Kenapa</b>",
        *[f"• {z}" for z in cfg["kenapa"]],
        f"• Bukti: {cfg['bt']}",
        "🛠 <b>Cara</b>",
        *([f"1. Masuk MARKET sekarang. SL {TG.fp(it['sl'], t)}, TP {TG.fp(it['tp'], t)} (untung {abs(it['tp'] - it['entry']) / it['entry'] * 100:.1f}%) untuk sisa posisi",
            f"2. Pasang juga TP sebagian: tutup 20% posisi di harga baris 💰. Setelah kena, SL ke entry. Selain itu jangan geser SL",
            f"3. Jam ke-12 belum kena TP 20% dan harga melawan: SL naik ke separuh jarak SL (harga searah: SL tetap). 30 jam belum kena: tutup market. Robot mengabari. Sudah aman tapi "
            f"{it.get('maks_bar', MAKS_BAR) // 6} "
            f"hari belum kena SL atau TP: tutup manual",
            "4. Catat dengan /entry supaya ada pengingat dan analisa volume kalau kena SL"] if it.get("tp") else
          [(f"1. Masuk MARKET sekarang. SL di {TG.fp(it['sl'], t)} ({it['risk'] / it['entry'] * 100:.1f}%). Tanpa TP sebagian. "
            f"Untung +{be_r(k):g}R (baris 🔒): SL ke entry, robot mengabari") if be_r(k) else
           (f"1. Masuk MARKET sekarang. SL di {TG.fp(it['sl'], t)} ({it['risk'] / it['entry'] * 100:.1f}%). Pasang TP sebagian 20% "
           f"di harga baris 💰, setelah kena SL ke entry. Sisanya tanpa TP"),
           "2. Pasang Trailing Stop Bybit, isi seperti blok di bawah, atau ikuti pesan GESER SL",
           *([f"   Setelah harga sampai ({TG.fp(it['entry'] + 2 * it['risk'] if L else it['entry'] - 2 * it['risk'], t)}), ganti jarak "
              f"Trailing Stop jadi 5% harga. Robot mengingatkan lewat SL TERBARU"] if it.get("trail_pct_2r") else []),
           ("3. Tanpa jam ke-12 dan batas 30 jam. Posisi tutup lewat SL berjalan, atau 10 hari belum kena SL: tutup manual" if be_r(k) else
            "3. Jam ke-12 belum kena TP 20% dan harga melawan: SL naik ke separuh jarak SL (harga searah: SL tetap). 30 jam belum kena: tutup market. Robot mengabari. "
            "Sudah aman tapi 10 hari belum kena SL: tutup manual"),
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
                        f"SL {TG.fp(it['sl'], it['tick'])} | {g * it['risk'] / it['entry'] * 100:+.2f}% | candle {it['bar']}/{MAKS_BAR}")
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
