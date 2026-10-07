"""QSE SIKLUS v1 - port dari Pine QSE_SIKLUS_v1 milik pengguna.
  1. Arah multi timeframe: peluang naik 6 bar ke depan dari kondisi EMA yang sama di 500 bar (4J dan 1D)
  2. Aliran dana: CMF 20, MFI 14, CVD, dan open interest (OI diambil terpisah hanya untuk kandidat saran)
  3. Musiman: hari dan jam (WIB) dengan rata-rata gerak terbaik dan terburuk
  4. Siklus pivot: puncak dan dasar besar (200 bar kiri kanan), proyeksi puncak atau dasar berikutnya
  5. Pola kembar: 20 bar terakhir dicocokkan dengan masa lalu (korelasi minimal 0,80), diuji 15 titik ke belakang
  6. Saran siklus: hanya bila pola kembar teruji, arah 4J dan 1D, aliran dana, dan BTC semuanya searah"""
import math
import time
import numpy as np
import requests
from numpy.lib.stride_tricks import sliding_window_view as swv
import qse_ta as T

DAY = 86400000
WIB = 7 * 3600000
HARI = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]


# ---------------- 1. arah multi timeframe ----------------
def arah_tf(df):
    """f_fc Pine: (peluang naik %, jumlah sampel) di bar terakhir yang sudah tutup, nilai [1]."""
    if df is None or len(df) < 80:
        return None, 0
    c = df["close"].values.astype(float)
    a, b = T.ema(c, 20), T.ema(c, 50)
    st = np.where((c > a) & (a > b), 1, np.where((c < a) & (a < b), -1, 0))
    st[np.isnan(a) | np.isnan(b)] = 0
    upn = np.r_[np.zeros(6), (c[6:] > c[:-6]).astype(float)]
    st6 = np.r_[np.full(6, 9), st[:-6]]
    res = []
    for k in (1, -1, 0):
        s = (st6 == k).astype(float)
        res.append((T.sma(s, 500), T.sma(s * upn, 500)))
    i = len(c) - 2                                  # nilai [1]
    if i < 0:
        return None, 0
    j = {1: 0, -1: 1, 0: 2}[int(st[i])]
    n, u = res[j][0][i], res[j][1][i]
    if np.isnan(n):
        return None, 0
    return (float(u / n * 100) if n > 0 else 50.0), int(round(n * 500))


# ---------------- 2. aliran dana ----------------
def aliran(df):
    h, l, c, o, v = (df[k].values.astype(float) for k in ("high", "low", "close", "open", "volume"))
    with np.errstate(divide="ignore", invalid="ignore"):
        mfv = np.where(h != l, ((c - l) - (h - c)) / (h - l) * v, 0.0)
    cmf = mfv[-20:].sum() / max(v[-20:].sum(), 1e-10)
    tp = (h + l + c) / 3
    raw = tp * v
    up = np.where(np.r_[False, tp[1:] > tp[:-1]], raw, 0.0)[-14:].sum()
    dn = np.where(np.r_[False, tp[1:] < tp[:-1]], raw, 0.0)[-14:].sum()
    mfi = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    cvd = np.cumsum(np.where(c > o, v, np.where(c < o, -v, 0.0)))
    cvd_up = bool(cvd[-1] > T.ema(cvd, 20)[-1])
    skor = (1 if cmf > 0.05 else -1 if cmf < -0.05 else 0) + (1 if mfi > 55 else -1 if mfi < 45 else 0) + (1 if cvd_up else -1)
    return dict(cmf=float(cmf), mfi=float(mfi), cvd_up=cvd_up, skor=skor, oi=None)


def oi_skor(sym, base_url, pr_ch):
    """Skor OI Pine: harga naik + OI naik = +1, harga turun + OI naik = -1, lainnya 0."""
    try:
        r = requests.get(base_url + "/v5/market/open-interest",
                         params={"category": "linear", "symbol": sym, "intervalTime": "4h", "limit": 8}, timeout=10)
        lst = r.json()["result"]["list"]
        oi = [float(x["openInterest"]) for x in sorted(lst, key=lambda x: int(x["timestamp"]))]
        if len(oi) < 7 or oi[-7] <= 0:
            return None, 0
        ch = (oi[-1] - oi[-7]) / oi[-7] * 100
        sk = 1 if pr_ch > 0 and ch > 0 else -1 if pr_ch < 0 and ch > 0 else 0
        return ch, sk
    except Exception:
        return None, 0


# ---------------- 3. musiman ----------------
def musiman(df, min_n=20):
    ts = df.index.values.astype("datetime64[ms]").astype(np.int64) + WIB
    o, c = df["open"].values.astype(float), df["close"].values.astype(float)
    rt = np.where(o > 0, (c - o) / o * 100, 0.0)
    dow = ((ts // DAY) + 4) % 7            # 1 Jan 1970 = Kamis, 0 = Minggu
    jam = (ts % DAY) // 3600000

    def best(key, nama):
        rows = []
        for k in np.unique(key):
            m = key == k
            if m.sum() >= min_n:
                rows.append((nama(k), rt[m].mean(), (rt[m] > 0).mean() * 100))
        if not rows:
            return None
        rows.sort(key=lambda x: x[1])
        return dict(terbaik=rows[-1], terburuk=rows[0], semua={x[0]: (float(x[1]), float(x[2])) for x in rows})
    return dict(hari=best(dow, lambda k: HARI[int(k)]), jam=best(jam, lambda k: f"{int(k):02d}:00"))


# ---------------- 4. siklus pivot ----------------
def siklus_pivot(df, pv=200):
    h, l = df["high"].values.astype(float), df["low"].values.astype(float)
    ts = df.index.values.astype("datetime64[ms]").astype(np.int64)
    pH, pL = T.pivothigh(h, pv, pv), T.pivotlow(l, pv, pv)
    K, P, Tm = [], [], []
    for i in range(len(h)):
        for k, arr in ((1, pH), (-1, pL)):
            if not np.isnan(arr[i]):
                p, t = arr[i], ts[i - pv]
                if K and K[-1] == k:
                    if (k == 1 and p > P[-1]) or (k == -1 and p < P[-1]):
                        P[-1], Tm[-1] = p, t
                else:
                    K.append(k), P.append(p), Tm.append(t)
    if len(K) < 2:
        return None
    naik, turun, dBT, dTB = [], [], [], []
    for i in range(1, len(K)):
        dt = Tm[i] - Tm[i - 1]
        if K[i] == -1:
            turun.append((P[i - 1] - P[i]) / P[i - 1])
            dTB.append(dt)
        else:
            naik.append((P[i] - P[i - 1]) / P[i - 1])
            dBT.append(dt)
    lk, lt, lp = K[-1], Tm[-1], P[-1]
    out = dict(jenis="DASAR" if lk == -1 else "PUNCAK", t=int(lt), p=float(lp), n=len(K))
    if lk == -1 and dBT and naik:
        t1 = lt + int(np.mean(dBT))
        pa = lp * (1 + np.mean(naik))
        pb = lp * (1 + naik[-1] * (max(0.3, min(1.5, naik[-1] / naik[-2])) if len(naik) >= 2 else 1.0))
        out.update(berikut="PUNCAK", t1=int(t1), lo=float(min(pa, pb)), hi=float(max(pa, pb)),
                   sd=float(np.std(dBT) if len(dBT) > 1 else np.mean(dBT) * 0.15))
    elif lk == 1 and dTB and turun:
        t1 = lt + int(np.mean(dTB))
        ba = lp * (1 - np.mean(turun))
        bb = lp * (1 - turun[-1] * (max(0.5, min(1.2, turun[-1] / turun[-2])) if len(turun) >= 2 else 1.0))
        out.update(berikut="DASAR", t1=int(t1), lo=float(min(ba, bb)), hi=float(max(ba, bb)),
                   sd=float(np.std(dTB) if len(dTB) > 1 else np.mean(dTB) * 0.15))
    return out


# ---------------- 5. pola kembar ----------------
def _match(rr, o, N, L, H, S, K, thr):
    j0 = o + max(L, H)
    j1 = min(N - L, j0 + S)
    if j1 <= j0:
        return 0, 0.5, 0.0, []
    a = rr[o:o + L]
    W = swv(rr, L)[j0:j1 + 1]
    am, Wm = a - a.mean(), W - W.mean(axis=1, keepdims=True)
    va, vb = (am * am).sum(), (Wm * Wm).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        cs = np.where((va > 0) & (vb > 0), (Wm @ am) / np.sqrt(va * vb), 0.0)
    js = np.arange(j0, j1 + 1)
    pil, fw = [], []
    cs = cs.copy()
    for _ in range(K):
        q = int(np.argmax(cs))
        if cs[q] <= thr:
            break
        jb = int(js[q])
        pil.append(jb)
        fw.append(float(rr[jb - H:jb].sum()))
        cs[np.abs(js - jb) < L] = -2.0
    n = len(pil)
    return n, (sum(1 for f in fw if f > 0) / n if n else 0.5), (float(np.mean(fw)) if n else 0.0), fw


def pola_kembar(c, L=20, H=12, S=400, K=5, thr=0.80):
    N = min(len(c) - 2, 1500)
    if N <= L + H + 60:
        return None
    cc = c[::-1][:N + 1]                               # cc[0] = candle terakhir
    rr = np.where(cc[1:N + 1] > 0, np.log(cc[:N] / cc[1:N + 1]), 0.0)
    hitT = hitN = 0
    for o in range(H, H + 15):
        vn, vu, _, _ = _match(rr, o, N, L, H, S, K, thr)
        if vn >= 2 and abs(vu - 0.5) >= 0.15:
            act = rr[o - H:o].sum()
            hitT += 1
            hitN += int((vu > 0.5) == (act > 0))
    n, up, m, fw = _match(rr, 0, N, L, H, S, K, thr)
    return dict(n=n, up=up, gerak=m, hitT=hitT, hitN=hitN, frs=fw, H=H)


def _rank(a, p):
    s = sorted(a)
    k = max(1, math.ceil(p / 100 * len(s)))
    return s[k - 1]


# ---------------- gabungan ----------------
def analisa(df, dfD, btc_prob, is_btc=False):
    """Semua komponen siklus di candle 4J terakhir yang sudah tutup. Saran OI dilengkapi di main."""
    try:
        c = df["close"].values.astype(float)
        h, l = df["high"].values.astype(float), df["low"].values.astype(float)
        a = float(T.atr(h, l, c, 14)[-1])
        e20 = float(T.ema(c, 20)[-1])
        c4P, c4N = arah_tf(df)
        dfDc = dfD.iloc[:-1] if dfD is not None and len(dfD) > 1 else dfD
        cDP, cDN = arah_tf(dfDc)
        fl = aliran(df)
        pk = pola_kembar(c)
        out = dict(c4P=c4P, c4N=c4N, cDP=cDP, cDN=cDN, aliran=fl, pola=pk, musim=musiman(df),
                   pivot=siklus_pivot(df), atr=a, ema20=e20, close=float(c[-1]),
                   pr_ch=float((c[-1] - c[-7]) / c[-7] * 100) if len(c) > 7 else 0.0, saran=None)
        if not pk or not pk["frs"]:
            return out
        hitR = pk["hitN"] / pk["hitT"] if pk["hitT"] else 0.0
        bp = 50.0 if btc_prob is None else btc_prob
        base = pk["n"] >= 3 and pk["hitT"] >= 8 and hitR >= 0.6
        okB = base and pk["up"] >= 0.67 and (c4P or 50) >= 55 and (cDP or 50) >= 55 and fl["skor"] >= 0 and (is_btc or bp >= 50)
        okS = base and pk["up"] <= 0.33 and (c4P or 50) <= 45 and (cDP or 50) <= 45 and fl["skor"] <= 0 and (is_btc or bp <= 50)
        if not (okB or okS):
            return out
        L = okB
        far = (c[-1] - e20) if L else (e20 - c[-1])
        mkt = far <= a * 0.3
        en = float(c[-1]) if mkt else e20
        lw, hg = float(l[-10:].min()), float(h[-10:].max())
        rk = min(max((en - lw + a * 0.2) if L else (hg - en + a * 0.2), a * 1.2), a * 2.5)
        frs = pk["frs"]
        q50 = abs(math.exp(float(np.median(frs))) - 1) * en
        q75 = abs(math.exp(_rank(frs, 75 if L else 25)) - 1) * en
        out["saran"] = dict(arah="LONG" if L else "SHORT", order="MARKET" if mkt else "LIMIT", entry=en,
                            sl=en - rk if L else en + rk,
                            tp1=en + max(q50, rk * 0.8) if L else en - max(q50, rk * 0.8),
                            tp2=en + max(q75, rk * 1.5) if L else en - max(q75, rk * 1.5),
                            hitR=hitR)
    except Exception as ex:
        return dict(error=str(ex)[:100])
    return out


def tgl(ms):
    return time.strftime("%d %b %Y", time.gmtime((ms + WIB) / 1000))
