"""QSE v148 - JALUR STRATEGI TAMBAHAN yang lolos uji 14 strategi umum (candle 4J, 111 koin perp, Jul 2020 - Okt 2026).
Aturan dipilih dari data 2020-2023, lalu diuji di 2024-2026 tanpa diubah. Biaya 0.15%. Maks 8 posisi per jalur.
Level SL & TP dihitung objektif dengan mesin struktur + volatilitas bersih (level_strategis):
  - SL Aman: di balik struktur swing + buffer ekor candle (p80), dibatasi ketat 0.6% s/d 5.5% dari entry (bebas bug SL >10% akibat spike).
  - TP Strategis: memadukan jangkauan impuls ayunan 4J dan front-run support/resistance struktur di depan harga (1.6R s/d 3.0R, maks 14%)."""
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
SL_ATR, TRAIL_ATR, MAKS_BAR = 1.6, 2.5, 60
SL_MIN_PCT, SL_MAX_PCT, TP_MAX_PCT = 0.006, 0.055, 0.14
MAKS_BARU, MAKS_BUKA, TOP_KOIN = 5, 8, 150
BIAYA = 0.0015
TELAT_ATR = 0.35
STRAT = {
    "ema_short": dict(nama="EMA Cross 20/50 SHORT", likuid=0, tp_r=2.4, maks_bar=45,
                      bt="uji 6 tahun 111 koin: 1812 trade, PF 1.42, uji ulang 2024-2026 PF 1.47, untung tiap tahun",
                      kenapa=["EMA 20 baru memotong EMA 50 ke bawah: momentum turun mulai",
                              "Harga di bawah EMA 200: tren besar turun",
                              "BTC 4J di bawah EMA 50: pasar ikut menekan"]),
    "rsi_vol": dict(nama="RSI 50 + Volume", likuid=30, tp_r=2.4, maks_bar=45,
                    bt="uji 6 tahun 111 koin, 30 paling likuid: 2380 trade, PF 1.34, uji ulang 2024-2026 PF 1.45",
                    kenapa=["RSI 14 baru melewati 50 searah tren besar (EMA 50 dan harga di sisi yang sama dari EMA 200)",
                            "Volume candle masuk 20% tertinggi dari 100 candle: dorongan nyata",
                            "Koin termasuk 30 paling likuid"]),
    "GZH": dict(nama="GZH Golden Zone", likuid=0, manual=True, tp_r=2.2, maks_bar=45,
                bt="uji 6 tahun 111 koin, maks 8 posisi: 1825 trade, WR 40%, PF 1.24, 2020-2023 PF 1.24, uji ulang 2024-2026 PF 1.23",
                kenapa=["Sentuhan pertama fib 0.618 lalu candle 4J tutup memantul",
                        "Searah tren besar (EMA 200) dan searah BTC 4J"]),
    "snr_vol": dict(nama="SnR Pantul + Volume", likuid=30, tp_r=2.5, maks_bar=45,
                    bt="uji 6 tahun 111 koin, 30 paling likuid, maks 8 posisi: 692 trade, WR 39%, PF 1.33, 2020-2023 PF 1.26, uji ulang 2024-2026 PF 1.43",
                    kenapa=["Pivot support/resistance 20 candle baru terkonfirmasi, harga memantul darinya",
                            "Searah tren besar (EMA 200) dan searah BTC 4J",
                            "Volume candle masuk 20% tertinggi dari 100 candle"]),
    "msb_hpz": dict(nama="MSB LuxAlgo HPZ", likuid=30, tp_r=2.4, maks_bar=45,
                    bt="uji 6 tahun 111 koin, 30 paling likuid, maks 8 posisi: 2783 trade, WR 37%, PF 1.27, 2020-2023 PF 1.32, uji ulang 2024-2026 PF 1.21",
                    kenapa=["Market structure break: close menembus pivot 7 candle dengan momentum kuat",
                            "Skor zona di atas 80 (HPZ): momentum dan volume besar",
                            "Searah tren besar (EMA 200)"]),
    "smc_choch": dict(nama="SMC CHoCH searah tren", likuid=30, tp_r=2.5, maks_bar=45,
                      bt="uji 111 koin 2020-2026, 30 paling likuid, maks 8 posisi: 2929 trade, WR 38%, PF 1.25 (2020-2023 PF 1.30, 2024-2026 PF 1.19), data lama 2017-2020 PF 1.40",
                      kenapa=["Change of Character (CHoCH) struktur internal: arah kecil berbalik",
                              "Searah tren besar (EMA 200)"]),
    "mcginley": dict(nama="McGinley 34 + Volume", likuid=0, tp_r=2.4, maks_bar=45,
                     bt="uji 6 tahun 111 koin, maks 8 posisi: 3328 trade, WR 40%, PF 1.24, 2020-2023 PF 1.26, uji ulang 2024-2026 PF 1.23, data lama 2017-2020 PF 1.10",
                     kenapa=["Harga baru menembus McGinley Dynamic 34: arah jangka menengah berbalik",
                             "Searah tren besar: harga di sisi yang sama dari EMA 200",
                             "Volume candle masuk 20% tertinggi dari 100 candle: dorongan nyata"]),
}


def level_strategis(df, px, arah, tp_r=2.4, sl_acuan=None, cek_spike=True):
    """Hitung SL Aman (berbasis struktur swing + buffer ekor candle p80, dibatasi 0.6% s/d 5.5%)
    dan TP Strategis (berbasis jangkauan impuls 4J + front-run SnR struktur di depan harga, 1.6R s/d 3.0R, maks 14%).
    Return dict(entry, sl, tp, tp1, tp2, risk, atr_ef) atau None bila candle sinyal sedang spike ekstrem."""
    if px is None or px <= 0:
        return None
    L = arah == "LONG"
    if df is not None and len(df) >= 20:
        o, h, l, c = (df[k].values.astype(float) for k in ("open", "high", "low", "close"))
        hs, ls, cs, os_ = h[-60:], l[-60:], c[-60:], o[-60:]
        pc = np.r_[cs[0], cs[:-1]]
        tr = np.maximum(hs - ls, np.maximum(np.abs(hs - pc), np.abs(ls - pc)))
        med_tr = float(np.median(tr[-20:])) if len(tr) >= 5 else float(tr[-1])
        # Tolak entry jika candle sinyal terakhir adalah spike pump/dump ekstrem (> 3.0x median TR atau body > 10%)
        if cek_spike and (tr[-1] > 3.0 * max(med_tr, px * 0.005) or abs(cs[-1] - os_[-1]) / px > 0.10):
            return None
        tr_clean = np.minimum(tr, 2.0 * max(med_tr, px * 0.003))
        atr_ef = float(pd.Series(tr_clean).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
        atr_ef = min(max(atr_ef, px * 0.004), px * 0.030)

        wicks = (np.minimum(os_[-20:], cs[-20:]) - ls[-20:]) if L else (hs[-20:] - np.maximum(os_[-20:], cs[-20:]))
        wick_buf = float(np.percentile(wicks, 80)) if len(wicks) else 0.30 * atr_ef
        wick_buf = min(max(wick_buf, 0.25 * atr_ef), 0.55 * atr_ef)

        if sl_acuan is not None and ((L and sl_acuan < px) or ((not L) and sl_acuan > px)):
            raw_dist = abs(px - sl_acuan)
        else:
            sw_batal = (float(ls[-5:].min()) - wick_buf) if L else (float(hs[-5:].max()) + wick_buf)
            raw_dist = (px - sw_batal) if L else (sw_batal - px)
        if raw_dist <= 0 or raw_dist > px * SL_MAX_PCT:
            sw_dekat = (float(ls[-2:].min()) - wick_buf) if L else (float(hs[-2:].max()) + wick_buf)
            d_dekat = (px - sw_dekat) if L else (sw_dekat - px)
            raw_dist = d_dekat if (px * SL_MIN_PCT <= d_dekat <= px * SL_MAX_PCT) else 1.45 * atr_ef
    else:
        atr_ef = px * 0.018
        raw_dist = abs(px - sl_acuan) if (sl_acuan and ((L and sl_acuan < px) or ((not L) and sl_acuan > px))) else 1.5 * atr_ef

    min_d = max(px * SL_MIN_PCT, 1.0 * atr_ef)
    max_d = min(px * SL_MAX_PCT, 1.85 * atr_ef)
    if max_d < min_d:
        max_d = px * SL_MAX_PCT
    risk = min(max(raw_dist, min_d), max_d)
    sl = px - risk if L else px + risk

    # Hitung jangkauan impuls 8 candle (32 jam) dan struktur SnR di depan harga untuk TP strategis
    jangkauan = tp_r * risk
    snr_depan = []
    if df is not None and len(df) >= 20:
        if len(cs) >= 16:
            mfe = (pd.Series(hs).rolling(8).max().values[8:] - cs[:-8]) if L else (cs[:-8] - pd.Series(ls).rolling(8).min().values[8:])
            mfe_pos = mfe[mfe > 0]
            if len(mfe_pos) >= 5:
                jangkauan = float(np.percentile(mfe_pos, 72))
        for k in range(3, len(cs) - 3):
            if L and hs[k] == hs[k - 3:k + 4].max() and hs[k] > px:
                d_s = (hs[k] - 0.15 * atr_ef) - px
                if 1.6 * risk <= d_s <= 3.2 * risk:
                    snr_depan.append(d_s)
            elif (not L) and ls[k] == ls[k - 3:k + 4].min() and ls[k] < px:
                d_s = px - (ls[k] + 0.15 * atr_ef)
                if 1.6 * risk <= d_s <= 3.2 * risk:
                    snr_depan.append(d_s)

    tp_dist = min(max(0.5 * (tp_r * risk) + 0.5 * jangkauan, 1.8 * risk), max(tp_r, 2.2) * risk)
    if snr_depan:
        tp_dist = min(tp_dist, min(snr_depan))
    tp_dist = min(max(tp_dist, 1.6 * risk), min(3.0 * risk, px * TP_MAX_PCT))
    tp1_dist = max(1.0 * risk, min(1.25 * risk, tp_dist * 0.55))

    tp = px + tp_dist if L else max(px * 0.50, px - tp_dist)
    tp1 = px + tp1_dist if L else max(px * 0.50, px - tp1_dist)
    return dict(entry=px, sl=sl, tp=tp, tp1=tp1, tp2=tp, risk=risk, atr_ef=atr_ef)


def perbaiki_item(it, df=None, tp_r=2.4):
    """Sanitasi & perbaiki posisi terbuka bila SL > 5.5% atau TP > 14% / belum ada / salah sisi."""
    if not it or not it.get("entry"):
        return it
    e = float(it["entry"])
    arah = it.get("arah", "LONG")
    L = arah == "LONG"
    sl = float(it.get("sl") or 0)
    tp = float(it.get("tp") or 0)
    sl_pct = abs(e - sl) / e if e > 0 and sl > 0 else 99.0
    tp_pct = abs(tp - e) / e if e > 0 and tp > 0 else 99.0
    salah_sl = sl <= 0 or (L and sl >= e) or ((not L) and sl <= e) or sl_pct > 0.06 or sl_pct < 0.004
    salah_tp = tp <= 0 or (L and tp <= e) or ((not L) and tp >= e) or tp_pct > 0.15 or tp_pct < 0.008
    if salah_sl or salah_tp:
        lv = level_strategis(df, e, arah, tp_r=tp_r, sl_acuan=None if salah_sl else sl, cek_spike=False)
        if lv:
            if salah_sl:
                it["sl"] = lv["sl"]
                it["sl0"] = lv["sl"]
                it["risk"] = lv["risk"]
            else:
                it["risk"] = abs(e - it["sl"])
            if salah_tp:
                it["tp"] = lv["tp"]
                it["tp1"] = lv["tp1"]
                it["tp2"] = lv["tp2"]
    return it


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
            d = json.load(f)
        tp_r = STRAT.get(k, {}).get("tp_r") or 2.4
        ubah_ada = False
        for key, it in list(d.get("open", {}).items()):
            sl0, tp0 = it.get("sl"), it.get("tp")
            perbaiki_item(it, tp_r=tp_r)
            if it.get("sl") != sl0 or it.get("tp") != tp0:
                ubah_ada = True
        if ubah_ada:
            with open(_file(k) + ".tmp", "w") as fw:
                json.dump(d, fw)
            os.replace(_file(k) + ".tmp", _file(k))
        return d
    except Exception:
        return {"open": {}, "closed": []}


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values


def _atr(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    med = pd.Series(tr).rolling(20, min_periods=5).median().bfill().values
    return _rma(np.minimum(tr, 2.0 * np.maximum(med, c * 0.003)), 14)


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = _rma(np.maximum(d, 0), n), _rma(np.maximum(-d, 0), n)
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))


def _mcginley(c, n=34, k=0.6):
    md = np.empty(len(c))
    md[0] = c[0]
    for i in range(1, len(c)):
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
    md = _mcginley(c[-600:])
    md = np.r_[np.full(len(c) - len(md), np.nan), md]
    if vp >= 80:
        if c[i] > md[i] and c[i - 1] <= md[i - 1] and c[i] > e200[i]:
            out["mcginley"] = ("LONG", float(a[i]))
        elif c[i] < md[i] and c[i - 1] >= md[i - 1] and c[i] < e200[i]:
            out["mcginley"] = ("SHORT", float(a[i]))
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
    """Kelola posisi: cek SL dulu, cek TP strategis, lalu geser SL berjalan (trailing) saat profit berkembang."""
    perbaiki_item(it, df)
    L = it["arah"] == "LONG"
    e, risk = it["entry"], max(it.get("risk") or abs(it["entry"] - it["sl"]), 1e-12)
    a = _atr(df["high"].values.astype(float), df["low"].values.astype(float), df["close"].values.astype(float))
    sl_lama = it["sl"]
    for k, ts in enumerate(df.index):
        if ts <= it["last"]:
            continue
        hi, lo, cl = float(df["high"].iloc[k]), float(df["low"].iloc[k]), float(df["close"].iloc[k])
        if (lo <= it["sl"]) if L else (hi >= it["sl"]):
            return "SL", ((it["sl"] - e) if L else (e - it["sl"])) / risk - BIAYA * e / risk, sl_lama
        if it.get("tp") and it["bar"] > 0 and ((hi >= it["tp"]) if L else (lo <= it["tp"])):
            return "TP", abs(it["tp"] - e) / risk - BIAYA * e / risk, sl_lama
        if L:
            it["best"] = max(it.get("best", e), hi)
            if (it["best"] - e) >= 1.2 * risk:
                it["sl"] = max(it["sl"], it["best"] - TRAIL_ATR * a[k])
        else:
            it["best"] = min(it.get("best", e), lo)
            if (e - it["best"]) >= 1.2 * risk:
                it["sl"] = min(it["sl"], it["best"] + TRAIL_ATR * a[k])
        it["bar"] += 1
        it["last"] = int(ts)
        it["close"] = cl
        if it["bar"] >= it.get("maks_bar", MAKS_BAR):
            return "WAKTU", ((cl - e) if L else (e - cl)) / risk - BIAYA * e / risk, sl_lama
    return "BUKA", None, sl_lama


def _catat_ledger(k, it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur=k, sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it.get("sl0", it["sl"]),
                                tp1=it.get("tp1", it.get("tp", 0.0)), tp2=it.get("tp", 0.0),
                                t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"], selesai=time.time(), ket="strategis"))
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
    df = _k4("BTCUSDT", 600)
    if df is None or len(df) < 60:
        return {"LONG": True, "SHORT": True}
    import qse_ta as T
    c = df["close"].values.astype(float)[:-1]
    e20, e50 = T.ema(c, 20), T.ema(c, 50)
    up, dn, mom = c[-1] > e20[-1] > e50[-1], c[-1] < e20[-1] < e50[-1], c[-1] > c[-2]
    return {"LONG": not (dn and not mom), "SHORT": not (up and mom)}


def btc_ema50_teks():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return ""
    c = df["close"].values.astype(float)
    e = float(_ema(c, 50)[-1])
    naik = c[-1] > e
    return (f"{'🟢' if naik else '🔴'} BTC 4J {'di atas' if naik else 'di bawah'} EMA 50 "
            f"(close {c[-1]:,.0f}, EMA 50 {e:,.0f}, {(c[-1] / e - 1) * 100:+.1f}%): condong {'LONG' if naik else 'SHORT'}")


def btc_naik():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return None
    c = df["close"].values.astype(float)
    return bool(c[-1] > _ema(c, 50)[-1])


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
        d_saya = SY.lihat()
        pegang = {(v["sym"], v["arah"]) for v in d_saya["open"].values() if v.get("status") in ("TERISI", "TP1")}
        sudah_entry = {v["sym"] for v in d_saya["open"].values()} | {
            c["sym"] for c in d_saya.get("closed", [])[-100:]
            if time.time() * 1000 - (c.get("closed_ts") or 0) < 12 * 3600000
        }
    except Exception:
        pegang, sudah_entry = set(), set()
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
                                  + (f"TP strategis {TG.fp(it['tp'], t)} tersentuh." if st == "TP" else
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
    dipakai = {it["sym"] for kk in STRAT for it in lihat(kk)["open"].values()} | sudah_entry
    for k, cfg in STRAT.items():
        if cfg.get("manual"):
            continue
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
                continue
            import qse_porto as PO
            why = SY.cek_lintas(sym, arah) or PO.izin(sym, arah, k)
            if why:
                continue
            px = tk[sym]["last"] or float(df["close"].iloc[-1])
            telat = now * 1000 - (int(df.index[-1]) + H4)
            if telat > 1800000 and abs(px - float(df["close"].iloc[-1])) > TELAT_ATR * a:
                continue
            lv = level_strategis(df, px, arah, tp_r=cfg.get("tp_r", 2.4))
            if not lv:
                continue
            t = tick.get(sym, 0.0001)
            it = dict(sym=sym, arah=arah, entry=px, sl=lv["sl"], sl0=lv["sl"], tp=lv["tp"], tp1=lv["tp1"], tp2=lv["tp2"],
                      risk=lv["risk"], best=px, bar=0, t=now, last=int(df.index[-1]), close=px, tick=t,
                      maks_bar=cfg.get("maks_bar", MAKS_BAR))
            baru.append(it)
            dipakai.add(sym)
            PO.pesan(sym, arah)
            out[k].append(kartu(k, len(baru), it, lv["atr_ef"]))

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
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], SY.lot_angka(lot_b))
    except Exception:
        lot = ""
    sl_pct = abs(it["entry"] - it["sl"]) / it["entry"] * 100
    tp_pct = abs(it["tp"] - it["entry"]) / it["entry"] * 100
    rr = abs(it["tp"] - it["entry"]) / max(it["risk"], 1e-12)
    return "\n".join([
        SY.GARIS,
        f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {it['arah']}</b>  ·  {cfg['nama']} 4J",
        f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
        SY.GARIS,
        SY.blok_salin(it["entry"], it["sl"], it.get("tp1") or it["tp"], it["tp"], "MARKET", t, sym=it["sym"], arah=it["arah"]),
        *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Lot setengah sampai pulih"] if rm else []),
        "💡 <b>Kenapa Objektif</b>",
        *[f"• {z}" for z in cfg["kenapa"]],
        f"• SL Aman di balik struktur swing + buffer ekor ({sl_pct:.2f}%), TP Strategis di target ayunan/SnR ({tp_pct:.2f}%, +{rr:.2f}R)",
        f"• Bukti: {cfg['bt']}",
        "🛠 <b>Cara</b>",
        f"1. Masuk MARKET sekarang. Pasang SL {TG.fp(it['sl'], t)} (-{sl_pct:.2f}%) dan TP {TG.fp(it['tp'], t)} (+{tp_pct:.2f}%, {rr:.1f}R)",
        "2. Bisa ambil separuh di TP1 lalu biarkan sisanya ke TP2 / dikawal SL berjalan otomatis",
        f"3. Kalau {it.get('maks_bar', MAKS_BAR) // 6} hari belum kena SL atau TP, tutup manual",
        "4. Catat dengan /entry supaya otomatis dipantau tiap menit",
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
            g = ((it["close"] - it["entry"]) if L else (it["entry"] - it["close"])) / max(it["risk"], 1e-12)
            tp_txt = f" | TP {TG.fp(it['tp'], it['tick'])}" if it.get("tp") else ""
            rows.append(f"{'🟢' if L else '🔴'} {it['sym']} {it['arah']} | entry {TG.fp(it['entry'], it['tick'])} | "
                        f"SL {TG.fp(it['sl'], it['tick'])}{tp_txt} | {g:+.2f}R | candle {it['bar']}/{it.get('maks_bar', MAKS_BAR)}")
        rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
        if rs:
            w = sum(x for x in rs if x > 0)
            lo = -sum(x for x in rs if x < 0)
            rows.append(f"Selesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                        f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
        rows.append("")
    return "\n".join(rows)
