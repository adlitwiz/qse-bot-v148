"""QSE v148 - UJI MUNDUR saran cadangan dan saran siklus di 6 bulan terakhir (sekitar 1080 candle 4J).
Aturan entry, SL, TP, dan pengelolaan (TP1 separuh, SL ke entry, sisa ke TP2) sama dengan yang dipakai live.
Fee taker pulang pergi dipotong. Batasan: rapor robot di masa lalu tidak dihitung ulang (terlalu berat),
jadi koin yang diuji adalah koin rapor A/B saat ini ditambah koin paling likuid."""
import json
import math
import os
import time
import numpy as np
import pandas as pd
import qse_features as F
import qse_skill as SK
import qse_siklus as SIK
import qse_ta as T
from config import STATE_DIR, P, FP

FILE = os.path.join(STATE_DIR, "uji.json")
H4 = 4 * 3600 * 1000
BARS = 1080          # sekitar 6 bulan candle 4J
LIMIT_BARS = 6       # LIMIT berlaku 24 jam


def lihat():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def aktif(jalur):
    """Jalur mati bila sudah 30 trade uji dan WR di bawah 50% atau PF di bawah 1.2."""
    u = lihat().get(jalur)
    return not (u and u["n"] >= 30 and (u["wr"] < 50 or u["pf"] < 1.2))


# ---------------- simulasi satu trade ----------------
def _simulasi(h, l, c, t, arah, order, entry, sl, tp1, tp2):
    """Return (R bersih fee, bar selesai) atau (None, bar) bila LIMIT tidak terisi."""
    L = arah == "LONG"
    n = len(c)
    i = t + 1
    if order == "LIMIT":
        isi = None
        for j in range(t + 1, min(n, t + 1 + LIMIT_BARS)):
            if (l[j] <= entry) if L else (h[j] >= entry):
                isi = j
                break
        if isi is None:
            return None, min(n - 1, t + LIMIT_BARS)
        i = isi
    risk = abs(entry - sl)
    if risk <= 0:
        return None, i
    fee = 2 * FP["fee_pct"] / 100 * entry / risk
    r1, r2 = abs(tp1 - entry) / risk, abs(tp2 - entry) / risk
    tp1_kena = False
    for j in range(i, n):
        stop = entry if tp1_kena else sl
        if (l[j] <= stop) if L else (h[j] >= stop):
            return (0.5 * r1 if tp1_kena else -1.0) - fee, j
        if not tp1_kena and ((h[j] >= tp1) if L else (l[j] <= tp1)):
            tp1_kena = True
        if tp1_kena and ((h[j] >= tp2) if L else (l[j] <= tp2)):
            return 0.5 * r1 + 0.5 * r2 - fee, j
    return None, n - 1          # belum selesai sampai data terakhir, tidak dihitung


# ---------------- jalur cadangan ----------------
def uji_cadangan(v, mulai, konf_min=6):
    h, l, c, a = v["high"], v["low"], v["close"], v["atr"]
    out, t = [], mulai
    n = len(c)
    while t < n - 2:
        bias = bool(v["biasLg"][t])
        zona = (v["inGP"][t] or v["inGZ"][t]) and bool(v["upLeg"][t]) == bias
        btc = v["btcOkL"][t] if bias else v["btcOkS"][t]
        if not (zona and btc) or not a[t] > 0:
            t += 1
            continue
        arah = "LONG" if bias else "SHORT"
        sk = SK.analisa(v, t)
        if SK.konfirmasi(sk, arah)[0] < konf_min:
            t += 1
            continue
        L = bias
        lo, hi = sorted((v["gpBot"][t], v["gpTop"][t]) if v["inGP"][t] else (v["gzBot"][t], v["gzTop"][t]))
        mid = (lo + hi) / 2
        order, e = ("MARKET", c[t]) if ((c[t] <= mid) if L else (c[t] >= mid)) else ("LIMIT", mid)
        batal = v["swL"][t] if L else v["swH"][t]
        base = batal - a[t] * P["slBuf"] if L else batal + a[t] * P["slBuf"]
        dist = (e - base) if L else (base - e)
        dist = min(max(dist if dist > 0 else a[t] * 1.5, a[t] * P["slMinA"]), a[t] * P["slMaxA"])
        sl = e - dist if L else e + dist
        tp1 = e + 0.8 * dist if L else e - 0.8 * dist
        lv = sk.get("res" if L else "sup") or []
        tp2 = next((x for x in lv if 1.2 * dist <= (x - e if L else e - x) <= 3 * dist), e + 1.8 * dist if L else e - 1.8 * dist)
        r, akhir = _simulasi(h, l, c, t, arah, order, e, sl, tp1, tp2)
        if r is not None:
            out.append(r)
        t = akhir + 1
    return out


# ---------------- jalur siklus ----------------
def _arah_seri(close):
    """Seri f_fc Pine: nilai di bar i = peluang naik di bar i-1."""
    c = np.asarray(close, float)
    e20, e50 = T.ema(c, 20), T.ema(c, 50)
    st = np.where((c > e20) & (e20 > e50), 1, np.where((c < e20) & (e20 < e50), -1, 0))
    upn = np.r_[np.zeros(6), (c[6:] > c[:-6]).astype(float)]
    st6 = np.r_[np.full(6, 9), st[:-6]]
    pv = np.full(len(c), 50.0)
    for k in (1, -1, 0):
        s = (st6 == k).astype(float)
        n_, u_ = T.sma(s, 500), T.sma(s * upn, 500)
        with np.errstate(divide="ignore", invalid="ignore"):
            p = np.where(n_ > 0, u_ / n_ * 100, 50.0)
        pv = np.where(st == k, p, pv)
    pv[np.isnan(pv)] = 50.0
    return np.r_[50.0, pv[:-1]]


def _aliran_seri(df):
    h, l, c, o, v = (df[k].values.astype(float) for k in ("high", "low", "close", "open", "volume"))
    with np.errstate(divide="ignore", invalid="ignore"):
        mfv = np.where(h != l, ((c - l) - (h - c)) / (h - l) * v, 0.0)
    cmf = pd.Series(mfv).rolling(20).sum().values / np.maximum(pd.Series(v).rolling(20).sum().values, 1e-10)
    tp = (h + l + c) / 3
    raw = tp * v
    up = pd.Series(np.where(np.r_[False, tp[1:] > tp[:-1]], raw, 0.0)).rolling(14).sum().values
    dn = pd.Series(np.where(np.r_[False, tp[1:] < tp[:-1]], raw, 0.0)).rolling(14).sum().values
    with np.errstate(divide="ignore", invalid="ignore"):
        mfi = np.where(dn == 0, 100.0, 100 - 100 / (1 + up / dn))
    cvd = np.cumsum(np.where(c > o, v, np.where(c < o, -v, 0.0)))
    cvd_up = cvd > T.ema(cvd, 20)
    return (np.where(cmf > 0.05, 1, np.where(cmf < -0.05, -1, 0)) + np.where(mfi > 55, 1, np.where(mfi < 45, -1, 0))
            + np.where(cvd_up, 1, -1))


def uji_siklus(df, dfD, btc_prob, mulai, is_btc=False):
    c = df["close"].values.astype(float)
    h, l = df["high"].values.astype(float), df["low"].values.astype(float)
    a = T.atr(h, l, c, 14)
    e20 = T.ema(c, 20)
    c4 = _arah_seri(c)
    ts = df.index.values.astype("datetime64[ms]").astype(np.int64)
    if dfD is not None and len(dfD) > 60:
        dts = dfD.index.values.astype("datetime64[ms]").astype(np.int64)
        dser = _arah_seri(dfD["close"].values)
        pos = np.searchsorted(dts, ts, side="right") - 1          # hari yang memuat candle
        cD = np.where(pos >= 1, dser[np.clip(pos - 1, 0, None)], 50.0)
    else:
        cD = np.full(len(c), 50.0)
    dana = _aliran_seri(df)
    out, t = [], mulai
    n = len(c)
    while t < n - 2:
        bp = btc_prob[t] if btc_prob is not None and not np.isnan(btc_prob[t]) else 50.0
        preB = c4[t] >= 55 and cD[t] >= 55 and dana[t] >= 0 and (is_btc or bp >= 50)
        preS = c4[t] <= 45 and cD[t] <= 45 and dana[t] <= 0 and (is_btc or bp <= 50)
        if not (preB or preS) or not a[t] > 0:
            t += 1
            continue
        pk = SIK.pola_kembar(c[:t + 1])
        if not pk or not pk["frs"] or pk["n"] < 3 or pk["hitT"] < 8 or pk["hitN"] / pk["hitT"] < 0.6:
            t += 1
            continue
        L = preB and pk["up"] >= 0.67
        S = preS and pk["up"] <= 0.33
        if not (L or S):
            t += 1
            continue
        far = (c[t] - e20[t]) if L else (e20[t] - c[t])
        mkt = far <= a[t] * 0.3
        en = c[t] if mkt else e20[t]
        lw, hg = l[max(0, t - 9):t + 1].min(), h[max(0, t - 9):t + 1].max()
        rk = min(max((en - lw + a[t] * 0.2) if L else (hg - en + a[t] * 0.2), a[t] * 1.2), a[t] * 2.5)
        q50 = abs(math.exp(float(np.median(pk["frs"]))) - 1) * en
        q75 = abs(math.exp(SIK._rank(pk["frs"], 75 if L else 25)) - 1) * en
        tp1 = en + max(q50, rk * 0.8) if L else en - max(q50, rk * 0.8)
        tp2 = en + max(q75, rk * 1.5) if L else en - max(q75, rk * 1.5)
        r, akhir = _simulasi(h, l, c, t, "LONG" if L else "SHORT", "MARKET" if mkt else "LIMIT", en,
                             en - rk if L else en + rk, tp1, tp2)
        if r is not None:
            out.append(r)
        t = akhir + 1
    return out


def _statistik(rs):
    n = len(rs)
    if not n:
        return dict(n=0, wr=0.0, pf=0.0, avg=0.0, net=0.0)
    win = [x for x in rs if x > 0]
    rugi = -sum(x for x in rs if x < 0)
    return dict(n=n, wr=len(win) / n * 100, pf=(sum(win) / rugi) if rugi > 0 else 9.9,
                avg=sum(rs) / n, net=sum(rs))


def jalankan(daftar, ambil, btc4, batas_detik=900):
    """daftar = [(sym, tick)]. ambil(sym) -> (df4 tutup, df1h, dfD, dfW). Simpan hasil ke uji.json."""
    t0 = time.time()
    hasil = {"cadangan": [], "siklus": []}
    per_koin = {}
    bf = F._btc_fc(btc4)
    for sym, tick in daftar:
        if time.time() - t0 > batas_detik:
            break
        try:
            df, h1, dD, dW = ambil(sym)
            if df is None or len(df) < BARS + 600:
                continue
            v = F.build(df, h1, dD, dW, btc4, sym, tick)
            mulai = len(df) - BARS
            rc = uji_cadangan(v, mulai)
            ts = df.index.values.astype("datetime64[ms]").astype(np.int64)
            bp = bf["bProb"].reindex(ts + H4, method="ffill").values
            rs = uji_siklus(df, dD, bp, mulai, sym.startswith("BTC"))
            hasil["cadangan"] += rc
            hasil["siklus"] += rs
            per_koin[sym] = dict(cadangan=_statistik(rc), siklus=_statistik(rs))
        except Exception as ex:
            print(f"[WARN] uji {sym}: {ex}")
    out = dict(ts=int(time.time() * 1000), koin=len(per_koin), bar=BARS,
               cadangan=_statistik(hasil["cadangan"]), siklus=_statistik(hasil["siklus"]), per_koin=per_koin,
               durasi=int(time.time() - t0))
    if "1j" in lihat():
        out["1j"] = lihat()["1j"]
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(out, f)
    os.replace(FILE + ".tmp", FILE)
    return out


def ringkas(u=None):
    u = u or lihat()
    if not u or "cadangan" not in u:
        return "Uji mundur belum pernah jalan. Jalan otomatis seminggu sekali."
    rows = [f"<b>🧪 UJI MUNDUR 6 BULAN</b> ({u['koin']} koin, {time.strftime('%d/%m %H:%M', time.gmtime(u['ts'] / 1000 + 7 * 3600))} WIB)"]
    for j, nama in (("cadangan", "Saran cadangan"), ("siklus", "Saran siklus"), ("1j", "Saran TF 1J")):
        if j not in u:
            continue
        s = u[j]
        st = "AKTIF" if aktif(j) else "DIMATIKAN"
        if s["n"] < 30:
            st += ", data belum cukup untuk menilai"
        rows.append(f"{nama}: {s['n']} trade | WR {s['wr']:.0f}% | PF {s['pf']:.2f} | rata {s['avg']:+.2f}R | {st}")
    return "\n".join(rows)


def catat_1j(results):
    """Uji jalur 1J = gabungan rapor robot TF 1J (simulasi DASBOR di chart 1 jam) dari koin yang dipindai."""
    n = sum(r["trd"] for r in results)
    if not n:
        return
    win = sum(r["trd"] * r["wr"] / 100 for r in results)
    net = sum(r["net_r"] for r in results)
    kalah = n - win
    u = lihat()
    u["1j"] = dict(n=int(n), wr=win / n * 100, pf=(net + kalah) / kalah if kalah > 0 else 9.9, avg=net / n, net=net,
                   koin=len(results), ts=int(time.time() * 1000))
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(u, f)
    os.replace(FILE + ".tmp", FILE)
