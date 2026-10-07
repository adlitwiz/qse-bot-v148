"""QSE v148 - semua seri indikator dan bahan pola, urutan mengikuti Pine baris 180-800."""
import numpy as np
import pandas as pd
import qse_ta as T
from qse_ta import sh, nz, na, NAN
import config
from config import P
import qse_rules as R

TF_MS = 4 * 3600 * 1000


def _core_t(df):
    c = df["close"].values.astype(float)
    a, b = T.ema(c, 20), T.ema(c, 50)
    t = np.where((c > a) & (a > b), 1.0, np.where((c < a) & (a < b), -1.0, 0.0))
    t[np.isnan(a) | np.isnan(b)] = NAN
    return sh(t, 1)


def _map_prev_period(ts4, dfp):
    """lookahead_on di TF lebih tinggi: nilai periode yang memuat bar (f_core sudah t[1])."""
    if dfp is None or len(dfp) == 0:
        return np.full(len(ts4), NAN)
    val = _core_t(dfp)
    pts = dfp.index.values.astype("datetime64[ms]").astype(np.int64)
    pos = np.searchsorted(pts, ts4, side="right") - 1
    out = np.where(pos >= 0, val[np.clip(pos, 0, None)], NAN)
    return out


def _map_1h(ts4, df1h):
    if df1h is None or len(df1h) == 0:
        return np.full(len(ts4), NAN)
    val = _core_t(df1h)
    hts = df1h.index.values.astype("datetime64[ms]").astype(np.int64)
    off = 0 if config.H1_INTRABAR == "first" else 3 * 3600 * 1000
    s = pd.Series(val, index=hts)
    return s.reindex(ts4 + off).values


_BTC_MEMO = {}


def _btc_fc(btc):
    """Hasil sama untuk semua koin, jadi dihitung sekali per proses."""
    key = (len(btc), str(btc.index[0]), str(btc.index[-1]), float(btc["close"].iloc[-1]))
    if key not in _BTC_MEMO:
        if len(_BTC_MEMO) >= 4:
            _BTC_MEMO.pop(next(iter(_BTC_MEMO)))
        _BTC_MEMO[key] = _btc_fc_calc(btc)
    return _BTC_MEMO[key]


def _btc_fc_calc(btc):
    c, h, l = (btc[k].values.astype(float) for k in ("close", "high", "low"))
    a, b = T.ema(c, 20), T.ema(c, 50)
    st = np.where((c > a) & (a > b), 1.0, np.where((c < a) & (a < b), -1.0, 0.0))
    st[np.isnan(a) | np.isnan(b)] = NAN
    at = T.atr(h, l, c, 14)
    dp, dm, ad = T.dmi(h, l, c, 14, 14)
    cr = T.correlation(c, np.arange(len(c), dtype=float), 50)
    upn = np.where(c > sh(c, 6), 1.0, 0.0)
    st6 = sh(st, 6)
    s1, s2, s0 = (st6 == 1) * 1.0, (st6 == -1) * 1.0, (st6 == 0) * 1.0
    n1, n2, n0 = T.sma(s1, 500), T.sma(s2, 500), T.sma(s0, 500)
    u1, u2, u0 = T.sma(s1 * upn, 500), T.sma(s2 * upn, 500), T.sma(s0 * upn, 500)
    with np.errstate(divide="ignore", invalid="ignore"):
        p1 = np.where(n1 > 0, u1 / n1 * 100, 50.0)
        p2 = np.where(n2 > 0, u2 / n2 * 100, 50.0)
        p0 = np.where(n0 > 0, u0 / n0 * 100, 50.0)
        mv = np.where(at > 0, T.sma(np.abs(c - sh(c, 6)) / at, 200), 0.0)
    pv = np.where(st == 1, p1, np.where(st == -1, p2, p0))
    nv = np.where(st == 1, n1, np.where(st == -1, n2, n0)) * 500
    e20, e50 = T.ema(c, 20), T.ema(c, 50)
    d = dict(bSt=sh(st, 1), bProb=sh(pv, 1), bNs=sh(nv, 1), bMv=sh(mv, 1), bAdx=sh(ad, 1),
             bRs=sh(cr * cr, 1), bAtr=sh(at, 1), bC=sh(c, 1), bE20=sh(e20, 1), bE50=sh(e50, 1),
             bC1=sh(c, 2), crsC=c)
    return pd.DataFrame(d, index=btc.index.values.astype("datetime64[ms]").astype(np.int64))


def build(df, df1h, dfD, dfW, btc, symbol, mintick, tf="240", df4=None, btc_tf=None):
    """tf 240: chart 4 jam. tf 60: chart 1 jam (df = 1H, df4 = 4H termasuk candle berjalan, btc = BTC 4H
    termasuk candle berjalan, btc_tf = BTC 1H)."""
    p = P
    ts = df.index.values.astype("datetime64[ms]").astype(np.int64)
    o, h, l, c, vol = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    n = len(c)
    bi = np.arange(n, dtype=float)
    v = {}
    open_, high, low, close = o, h, l, c

    atrV = T.atr(h, l, c, p["atrLen"])
    brange = h - l
    avgRng = T.sma(brange, 20)
    atrPc = T.percentrank(atrV, 100)
    isSpk = brange > avgRng * p["spikeX"]
    mktOk = (~isSpk) & (nz(T.barssince(isSpk), 999) > 5) & (atrPc <= 92) & (atrPc >= 8)
    with np.errstate(divide="ignore", invalid="ignore"):
        bodyR = np.where(brange > 0, np.abs(c - o) / brange, 0.0)
        closR = np.where(brange > 0, (c - l) / brange, 0.5)
    ema20, ema50, ema200 = T.ema(c, 20), T.ema(c, 50), T.ema(c, 200)
    tUp = (c > ema50) & (ema50 > ema200)
    tDn = (c < ema50) & (ema50 < ema200)
    with np.errstate(divide="ignore", invalid="ignore"):
        rvol = vol / T.sma(vol, 20)
    rsiV = T.rsi(c, 14)
    bbM = T.sma(c, 20)
    bbSd = T.stdev(c, 20)
    bbU, bbL = bbM + 2 * bbSd, bbM - 2 * bbSd
    vwapV = T.vwap_daily(ts, (h + l + c) / 3, vol)
    stLine, stDir = T.supertrend(h, l, c, 3, 10)
    dcU, dcL = sh(T.highest(h, 20), 1), sh(T.lowest(l, 20), 1)
    dcM = (dcU + dcL) / 2
    capMove = T.sma(T.highest(h, 10) - T.lowest(l, 10), 50) / atrV
    pLo20, pHi20 = T.lowest(l, 20), T.highest(h, 20)
    hi10, lo10 = sh(T.highest(h, 10), 1), sh(T.lowest(l, 10), 1)
    sw8L, sw8H = T.lowest(l, 8), T.highest(h, 8)
    emaSlope = (ema20 - sh(ema20, 3)) / atrV
    oppUp = (c - sh(c, p["antiMBar"])) / atrV
    wkBL = np.maximum(T.highest(np.minimum(o, c) - l, p["wickLb"]), atrV * 0.3) * p["wickMul"]
    wkBS = np.maximum(T.highest(h - np.maximum(o, c), p["wickLb"]), atrV * 0.3) * p["wickMul"]

    o1, o2, c1, c2, h1, h2, l1, l2 = sh(o, 1), sh(o, 2), sh(c, 1), sh(c, 2), sh(h, 1), sh(h, 2), sh(l, 1), sh(l, 2)
    cdlL = (c > o) & (bodyR >= 0.5) & (closR >= 0.65)
    cdlS = (c < o) & (bodyR >= 0.5) & (closR <= 0.35)
    engL = (c > o) & (c > h1) & (o <= c1) & (c1 < o1)
    engS = (c < o) & (c < l1) & (o >= c1) & (c1 > o1)
    pinL = ((np.minimum(o, c) - l) > brange * 0.55) & (c > o) & (brange > atrV * 0.6)
    pinS = ((h - np.maximum(o, c)) > brange * 0.55) & (c < o) & (brange > atrV * 0.6)
    br1 = sh(brange, 1)
    stL = (c2 < o2) & (np.abs(c1 - o1) < br1 * 0.4) & (c > o) & (c > (o2 + c2) / 2)
    stS = (c2 > o2) & (np.abs(c1 - o1) < br1 * 0.4) & (c < o) & (c < (o2 + c2) / 2)
    sol3 = (c > o) & (c1 > o1) & (c2 > o2) & (c > c1) & (c1 > c2) & (bodyR > 0.5)
    cro3 = (c < o) & (c1 < o1) & (c2 < o2) & (c < c1) & (c1 < c2) & (bodyR > 0.5)

    def f_psy(px):
        mag = np.power(10.0, np.floor(np.log(np.maximum(px, mintick)) / np.log(10)))
        q = mag / 4
        return np.floor(px / q + 0.5) * q
    psyLv = f_psy(c)
    psyNear = np.abs(c - psyLv) <= atrV * p["psyTol"]
    psyBL = p["usePsy"] & psyNear & (l <= psyLv) & (c > psyLv) & cdlL
    psyBS = p["usePsy"] & psyNear & (h >= psyLv) & (c < psyLv) & cdlS
    trapU = (c < hi10) & (np.maximum(np.maximum(h, h1), h2) > hi10) & (rvol >= 1.2)
    trapD = (c > lo10) & (np.minimum(np.minimum(l, l1), l2) < lo10) & (rvol >= 1.2)

    # ===== GAP =====
    gU = l > h1
    gD = h < l1
    gATR = np.where(gU, l - h1, np.where(gD, l1 - h, 0.0)) / atrV
    lastGU = np.full(n, NAN)
    lastGD = np.full(n, NAN)
    a, b = NAN, NAN
    for i in range(n):
        if gU[i]:
            a = h1[i]
        if gD[i]:
            b = l1[i]
        lastGU[i], lastGD[i] = a, b
    h20p, l20p = sh(T.highest(h, 20), 1), sh(T.lowest(l, 20), 1)
    ug = p["useGap"]
    gm = p["gapMin"]
    comGap = ug & (gATR > 0) & (gATR < gm)
    brkGU = ug & gU & (gATR >= gm * 1.6) & (rvol >= 1.5) & (c > h20p)
    brkGD = ug & gD & (gATR >= gm * 1.6) & (rvol >= 1.5) & (c < l20p)
    runGU = ug & gU & (gATR >= gm) & tUp & (rvol >= 1.2) & ~brkGU
    runGD = ug & gD & (gATR >= gm) & tDn & (rvol >= 1.2) & ~brkGD
    exhGU = ug & gU & (gATR >= gm * 1.6) & (rsiV > 70)
    exhGD = ug & gD & (gATR >= gm * 1.6) & (rsiV < 30)
    islB = ug & sh(gD, 1) & gU
    islT = ug & sh(gU, 1) & gD

    # ===== INDIKATOR =====
    with np.errstate(divide="ignore", invalid="ignore"):
        bw = np.where(bbM != 0, (bbU - bbL) / bbM, 0.0)
    bw[np.isnan(bbM)] = NAN
    squeeze = T.percentrank(bw, 100) < 15
    sqBU = sh(squeeze, 1) & (c > bbU) & (rvol >= 1.2)
    sqBD = sh(squeeze, 1) & (c < bbL) & (rvol >= 1.2)
    bbRL = (l <= bbL) & (c > bbL) & cdlL
    bbRS = (h >= bbU) & (c < bbU) & cdlS
    diP, diM, adxV = T.dmi(h, l, c, 14, 14)
    adxRise = (adxV > sh(adxV, 1)) & (adxV > 20)
    dmiCU = T.crossover(diP, diM) & adxRise
    dmiCD = T.crossover(diM, diP) & adxRise
    obvV = T.cum(np.sign(T.change(c)) * vol)
    obvE = T.ema(obvV, 21)
    obvDL = (l <= pLo20 * 1.0005) & (obvV > T.lowest(obvV, 20)) & (obvV > obvE)
    obvDS = (h >= pHi20 * 0.9995) & (obvV < T.highest(obvV, 20)) & (obvV < obvE)
    tenkan = (T.highest(h, 9) + T.lowest(l, 9)) / 2
    kijun = (T.highest(h, 26) + T.lowest(l, 26)) / 2
    sa = (tenkan + kijun) / 2
    sb = (T.highest(h, 52) + T.lowest(l, 52)) / 2
    sa26 = nz(sh(sa, 26), sa)
    sb26 = nz(sh(sb, 26), sb)
    kumoT, kumoB = np.maximum(sa26, sb26), np.minimum(sa26, sb26)
    aboveK, belowK = c > kumoT, c < kumoB
    kBU = (c > kumoT) & (c1 <= nz(sh(kumoT, 1), kumoT))
    kBD = (c < kumoB) & (c1 >= nz(sh(kumoB, 1), kumoB))
    tkU, tkD = T.crossover(tenkan, kijun), T.crossunder(tenkan, kijun)
    macdL, macdSg, macdH = T.macd(c, 12, 26, 9)
    macdCU, macdCD = T.crossover(macdL, macdSg), T.crossunder(macdL, macdSg)
    divBM = (l <= pLo20 * 1.0005) & (macdL > T.lowest(macdL, 20)) & (macdL < 0)
    divSM = (h >= pHi20 * 0.9995) & (macdL < T.highest(macdL, 20)) & (macdL > 0)
    divBR = (l <= pLo20 * 1.0005) & (rsiV > T.lowest(rsiV, 20) + 3) & (rsiV < 45)
    divSR = (h >= pHi20 * 0.9995) & (rsiV < T.highest(rsiV, 20) - 3) & (rsiV > 55)
    rsiRL = (rsiV < 35) & (rsiV > sh(rsiV, 1)) & cdlL
    rsiRS = (rsiV > 65) & (rsiV < sh(rsiV, 1)) & cdlS

    # ===== BTC & MTF =====
    btcAlt = "BTC" not in symbol
    bf = _btc_fc(btc).reindex(ts, method="ffill")
    bSt, bProb, bC, bE20, bE50, bC1 = (bf[k].values for k in ("bSt", "bProb", "bC", "bE20", "bE50", "bC1"))
    btcUp = (bC > bE20) & (bE20 > bE50)
    btcDn = (bC < bE20) & (bE20 < bE50)
    btcMom = bC > bC1
    btcKuat = np.abs(bC - bC1) / np.maximum(bC1, mintick) * 100 >= 0.4
    gate = p["btcGate"]
    btcOkL = (not gate) | (not btcAlt) | ~(btcDn & ~btcMom)
    btcOkS = (not gate) | (not btcAlt) | ~(btcUp & btcMom)
    btcOkL = np.broadcast_to(btcOkL, (n,)).copy()
    btcOkS = np.broadcast_to(btcOkS, (n,)).copy()
    if tf == "60" and btc_tf is not None:
        bts = btc_tf.index.values.astype("datetime64[ms]").astype(np.int64)
        crsC = pd.Series(btc_tf["close"].values.astype(float), index=bts).reindex(ts, method="ffill").values
    else:
        crsC = bf["crsC"].values
    crsR = nz(c / np.maximum(crsC, mintick), 1.0)
    crsE = T.ema(crsR, 20)
    crsUp = (not p["useCRS"]) | (crsR > crsE)
    crsDn = (not p["useCRS"]) | (crsR < crsE)
    if tf == "60":
        m60 = _core_t(df)
        m240 = _map_prev_period(ts, df4)
    else:
        m60 = _map_1h(ts, df1h)
        m240 = _core_t(df)
    mDy = _map_prev_period(ts, dfD)
    mWk = _map_prev_period(ts, dfW)
    htfBull = (m60 >= 0) & (m240 >= 0) & ((m60 == 1) | (m240 == 1))
    htfBear = (m60 <= 0) & (m240 <= 0) & ((m60 == -1) | (m240 == -1))
    ltUp = (mDy >= 0) & (mWk >= 0)
    ltDn = (mDy <= 0) & (mWk <= 0)
    biasLg = np.zeros(n, bool)
    biasCtA = np.zeros(n, int)
    bl, bc = 0, 0
    for i in range(n):
        if bl == 0:
            bl = 1 if (htfBull[i] or (tUp[i] and not htfBear[i])) else -1
        nb = 1 if (htfBull[i] or (tUp[i] and not htfBear[i])) else -1
        if p["useLT"] and mDy[i] == mWk[i] and mDy[i] != 0 and not np.isnan(mDy[i]):
            nb = int(mDy[i])
        if nb == bl:
            bc = 0
        else:
            bc += 1
            if bc >= p["biasHold"]:
                bl, bc = nb, 0
        biasLg[i] = bl == 1
        biasCtA[i] = bc

    # ===== KALKULUS =====
    lrN = T.linreg(c, 50, 0)
    d1 = (lrN - T.linreg(c, 50, 1)) / atrV
    d2 = ((c - sh(c, 5)) - (sh(c, 5) - sh(c, 10))) / (5 * atrV)
    c3, c6, c9 = sh(c, 3), sh(c, 6), sh(c, 9)
    d3 = (((c - c3) - (c3 - c6)) - ((c3 - c6) - (c6 - c9))) / (3 * atrV)
    areaI = T.sma(c - ema50, 50) / atrV
    inflL = (d2 > 0) & (sh(d2, 1) <= 0)
    inflS = (d2 < 0) & (sh(d2, 1) >= 0)
    kScL = (d1 > p["d1Thr"]) * 1 + (d2 > p["d2Thr"]) * 1 + (d3 > 0) * 1 + (areaI > 0) * 1
    kScS = (d1 < -p["d1Thr"]) * 1 + (d2 < -p["d2Thr"]) * 1 + (d3 < 0) * 1 + (areaI < 0) * 1

    # ===== STATISTIK =====
    with np.errstate(divide="ignore", invalid="ignore"):
        zPr = np.where(bbSd > 0, (c - bbM) / bbSd, 0.0)
        corrR = T.correlation(c, bi, 50)
        rSq = corrR * corrR
        tSt = np.where(np.abs(corrR) < 0.999, corrR * np.sqrt(48) / np.sqrt(1 - rSq), 99.0)
        ha = np.power(T.stdev(T.change(c, 1), p["statLen"]), 2)
        hb = np.power(T.stdev(T.change(c, 10), p["statLen"]), 2)
        hurst = np.where(ha > 0, 0.5 * np.log(hb / (10 * ha)) / np.log(10) + 0.5, 0.5)
    tSt = np.where(np.isnan(tSt), 99.0, tSt)
    rwBlock = p["useRW"] & (hurst > 0.45) & (hurst < 0.55) & (rSq < 0.20) & (adxV < 18)
    rgIdx = np.where(atrPc > 92, 3, np.where(rSq < 0.25, 2, np.where(d1 > 0, 0, 1)))
    trending = (adxV >= 25) & (rSq >= 0.35)
    ranging = (rSq < 0.25) | (adxV < 20)
    suicL = p["useSuic"] & (zPr < -p["suicZ"]) & (rvol > 2.0) & (np.abs(c - ema20) / atrV > 2.5)
    suicS = p["useSuic"] & (zPr > p["suicZ"]) & (rvol > 2.0) & (np.abs(c - ema20) / atrV > 2.5)
    cumv = T.cum(np.where(c >= o, vol * 0.6, -vol * 0.6))
    cumE = T.ema(cumv, 9)
    cdvB, cdvS = cumv > cumE, cumv < cumE
    frL = p["frLen"]
    frU = T.pivothigh(h, frL, frL)
    frD = T.pivotlow(l, frL, frL)
    frU1, frU2, frD1, frD2 = (np.full(n, NAN) for _ in range(4))
    u1 = u2 = d1_ = d2_ = NAN
    for i in range(n):
        if not np.isnan(frU[i]):
            u2, u1 = u1, frU[i]
        if not np.isnan(frD[i]):
            d2_, d1_ = d1_, frD[i]
        frU1[i], frU2[i], frD1[i], frD2[i] = u1, u2, d1_, d2_
    frTU = ~na(frD1) & ~na(frD2) & (frD1 > frD2)
    frTD = ~na(frU1) & ~na(frU2) & (frU1 < frU2)
    frBU = ~na(frU1) & (c > frU1) & (c1 <= frU1)
    frBD = ~na(frD1) & (c < frD1) & (c1 >= frD1)

    # ===== TRENDLINE =====
    tp_ = p["tlPer"]
    tpH, tpL = T.pivothigh(h, tp_, tp_), T.pivotlow(l, tp_, tp_)
    th1 = th2 = tl1 = tl2 = NAN
    th1i = th2i = tl1i = tl2i = NAN
    tlHv, tlLv = np.full(n, NAN), np.full(n, NAN)
    TH = np.full((n, 4), NAN)
    for i in range(n):
        if not np.isnan(tpH[i]):
            th2, th2i, th1, th1i = th1, th1i, tpH[i], i - tp_
        if not np.isnan(tpL[i]):
            tl2, tl2i, tl1, tl1i = tl1, tl1i, tpL[i], i - tp_
        slpH = (th1 - th2) / (th1i - th2i) if (not np.isnan(th1) and not np.isnan(th2) and th1i != th2i) else 0.0
        slpL = (tl1 - tl2) / (tl1i - tl2i) if (not np.isnan(tl1) and not np.isnan(tl2) and tl1i != tl2i) else 0.0
        tlHv[i] = NAN if np.isnan(th1) else th1 + slpH * (i - th1i)
        tlLv[i] = NAN if np.isnan(tl1) else tl1 + slpL * (i - tl1i)
    tlTolP = atrV * p["tlTol"]
    atTlL = ~na(tlLv) & (l <= tlLv + tlTolP) & (l >= tlLv - tlTolP * 2) & (c > tlLv)
    atTlS = ~na(tlHv) & (h >= tlHv - tlTolP) & (h <= tlHv + tlTolP * 2) & (c < tlHv)
    tlBU = ~na(tlHv) & (c > tlHv) & (c1 <= nz(sh(tlHv, 1), tlHv))
    tlBD = ~na(tlLv) & (c < tlLv) & (c1 >= nz(sh(tlLv, 1), tlLv))
    chTop = tlLv + atrV * 2
    chBot = tlHv - atrV * 2
    atChT = p["useChan"] & ~na(chTop) & (h >= chTop - tlTolP) & (c < chTop)
    atChB = p["useChan"] & ~na(chBot) & (l <= chBot + tlTolP) & (c > chBot)
    fanFU, fanFD = np.zeros(n, bool), np.zeros(n, bool)
    fu = fd = 0
    for i in range(n):
        if tlBD[i]:
            fd += 1
            fu = 0
        if tlBU[i]:
            fu += 1
            fd = 0
        fanFU[i] = p["useFan"] and fu >= 3
        fanFD[i] = p["useFan"] and fd >= 3

    # ===== FIBONACCI SNR =====
    sL = p["swLen"]
    swH, swL = T.highest(h, sL), T.lowest(l, sL)
    upLeg = T.highestbars(h, sL) > T.lowestbars(l, sL)
    rngF = swH - swL
    ret = lambda q: np.where(upLeg, swH - rngF * q, swL + rngF * q)
    ext = lambda m: np.where(upLeg, swL + rngF * m, swH - rngF * m)
    fib0 = np.where(upLeg, swH, swL)
    r236, r382, r500, r786 = ret(0.236), ret(0.382), ret(0.5), ret(0.786)
    e127, e161 = ext(1.272), ext(1.618)
    gpTop, gpBot = np.maximum(ret(0.618), ret(0.65)), np.minimum(ret(0.618), ret(0.65))
    inGP = (c <= gpTop) & (c >= gpBot)
    gzTop, gzBot = np.maximum(r500, r786), np.minimum(r500, r786)
    inGZ = (c <= gzTop) & (c >= gzBot)
    ezTop, ezBot = np.maximum(e127, e161), np.minimum(e127, e161)
    inEZ = (c <= ezTop) & (c >= ezBot)
    sp = p["snrPer"]
    resV = T.valuewhen(~na(T.pivothigh(h, sp, sp)), sh(h, sp))
    supV = T.valuewhen(~na(T.pivotlow(l, sp, sp)), sh(l, sp))
    snrW = atrV * 0.35
    atRes = (h >= resV - snrW) & (l <= resV + snrW)
    atSup = (h >= supV - snrW) & (l <= supV + snrW)

    # ===== SMC =====
    mp = p["msbPiv"]
    mPh, mPl = T.pivothigh(h, mp, mp), T.pivotlow(l, mp, mp)
    chg = T.change(c)
    sdc = T.stdev(chg, 50)
    with np.errstate(divide="ignore", invalid="ignore"):
        momZ = np.where(sdc == 0, 0.0, (chg - T.sma(chg, 50)) / sdc)
    ph1, ph2, ph3, pl1, pl2, pl3 = (np.full(n, NAN) for _ in range(6))
    bosL, bosS, choL, choS, brkUp, brkDn = (np.zeros(n, bool) for _ in range(6))
    obBTa, obBBa, obSTa, obSBa, fvUTa, fvUBa, fvDTa, fvDBa = (np.full(n, NAN) for _ in range(8))
    obL, obS, fvFL, fvFS = (np.zeros(n, bool) for _ in range(4))
    q1 = q2 = q3 = r1 = r2 = r3 = NAN
    sBias = 0
    obBT = obBB = obST = obSB = fvUT = fvUB = fvDT = fvDB = NAN
    for i in range(n):
        if not np.isnan(mPh[i]):
            q3, q2, q1 = q2, q1, mPh[i]
        if not np.isnan(mPl[i]):
            r3, r2, r1 = r2, r1, mPl[i]
        ph1[i], ph2[i], ph3[i], pl1[i], pl2[i], pl3[i] = q1, q2, q3, r1, r2, r3
        cp = c[i - 1] if i > 0 else NAN
        bu = (not np.isnan(q1)) and c[i] > q1 and cp <= q1
        bd = (not np.isnan(r1)) and c[i] < r1 and cp >= r1
        brkUp[i], brkDn[i] = bu, bd
        mz = momZ[i]
        bosL[i] = bu and mz > 0.5 and sBias >= 0
        bosS[i] = bd and mz < -0.5 and sBias <= 0
        choL[i] = bu and mz > 0.5 and sBias < 0
        choS[i] = bd and mz < -0.5 and sBias > 0
        if bu:
            sBias = 1
        if bd:
            sBias = -1
        if bosL[i] or choL[i]:
            idx = 1
            for k in range(1, 11):
                if i - k >= 0 and c[i - k] < o[i - k]:
                    idx = k
                    break
            if i - idx >= 0:
                obBT, obBB = h[i - idx], l[i - idx]
        if bosS[i] or choS[i]:
            idx = 1
            for k in range(1, 11):
                if i - k >= 0 and c[i - k] > o[i - k]:
                    idx = k
                    break
            if i - idx >= 0:
                obST, obSB = h[i - idx], l[i - idx]
        if not np.isnan(obBB) and c[i] < obBB - atrV[i] * 0.2:
            obBT = NAN
        if not np.isnan(obST) and c[i] > obST + atrV[i] * 0.2:
            obST = NAN
        obL[i] = (not np.isnan(obBT)) and l[i] <= obBT and c[i] > obBB and c[i] > o[i]
        obS[i] = (not np.isnan(obSB)) and h[i] >= obSB and c[i] < obST and c[i] < o[i]
        if i >= 2 and l[i] > h[i - 2] and c[i - 1] > h[i - 2]:
            fvUT, fvUB = l[i], h[i - 2]
        if i >= 2 and h[i] < l[i - 2] and c[i - 1] < l[i - 2]:
            fvDT, fvDB = l[i - 2], h[i]
        fvFL[i] = (not np.isnan(fvUB)) and l[i] <= fvUT and l[i] >= fvUB and c[i] > o[i]
        fvFS[i] = (not np.isnan(fvDT)) and h[i] >= fvDB and h[i] <= fvDT and c[i] < o[i]
        obBTa[i], obBBa[i], obSTa[i], obSBa[i] = obBT, obBB, obST, obSB
    dowUp = p["useDow"] & ~na(ph2) & ~na(pl2) & (ph1 > ph2) & (pl1 > pl2)
    dowDn = p["useDow"] & ~na(ph2) & ~na(pl2) & (ph1 < ph2) & (pl1 < pl2)
    elwU = p["useElw"] & dowUp & (c > ph1) & (rvol >= 1.2)
    elwD = p["useElw"] & dowDn & (c < pl1) & (rvol >= 1.2)
    obBT, obSB = obBTa, obSBa
    swpL = (l < lo10) & (c > lo10) & (closR > 0.6)
    swpS = (h > hi10) & (c < hi10) & (closR < 0.4)
    fbL = (l < lo10) & (c > lo10) & (rvol >= 1.1) & cdlL
    fbS = (h > hi10) & (c < hi10) & (rvol >= 1.1) & cdlS
    neckD = np.where(~na(pl2), np.minimum(pl1, pl2), NAN)
    neckU = np.where(~na(ph2), np.maximum(ph1, ph2), NAN)

    up_ = p["usePat"]
    tol = p["patTol"]
    triC = ~na(ph2) & ~na(pl2) & (ph1 < ph2) & (pl1 > pl2)
    triL = triC & (c > ph1) & (c1 <= ph1) & (rvol >= 1.2)
    triS = triC & (c < pl1) & (c1 >= pl1) & (rvol >= 1.2)
    dblB = ~na(pl2) & (np.abs(pl1 - pl2) <= atrV * 0.4) & (c > ph1) & (c1 <= ph1)
    dblT = ~na(ph2) & (np.abs(ph1 - ph2) <= atrV * 0.4) & (c < pl1) & (c1 >= pl1)
    ib = (h1 < h2) & (l1 > l2)
    ibL = ib & (c > h1) & (rvol >= 1.1)
    ibS = ib & (c < l1) & (rvol >= 1.1)
    hsL = up_ & ~na(pl3) & ~na(neckU) & (pl2 < pl1 - atrV * 0.3) & (pl2 < pl3 - atrV * 0.3) & (np.abs(pl1 - pl3) <= atrV * tol) & (c > neckU) & (c1 <= neckU)
    hsS = up_ & ~na(ph3) & ~na(neckD) & (ph2 > ph1 + atrV * 0.3) & (ph2 > ph3 + atrV * 0.3) & (np.abs(ph1 - ph3) <= atrV * tol) & (c < neckD) & (c1 >= neckD)
    hound = up_ & ~na(ph3) & (ph2 > ph1) & (ph2 > ph3) & (np.abs(ph1 - ph3) <= atrV * tol) & ~na(neckD) & (c < neckD) & (c1 >= neckD) & (rvol < 0.9)
    trT = up_ & ~na(ph3) & (np.abs(ph1 - ph2) <= atrV * tol) & (np.abs(ph2 - ph3) <= atrV * tol) & ~na(neckD) & (c < neckD) & (c1 >= neckD)
    trB = up_ & ~na(pl3) & (np.abs(pl1 - pl2) <= atrV * tol) & (np.abs(pl2 - pl3) <= atrV * tol) & ~na(neckU) & (c > neckU) & (c1 <= neckU)
    hrT = up_ & (np.abs(h2 - h) <= atrV * 0.3) & (h1 < np.minimum(h2, h) - atrV * 0.2) & (c < l1)
    hrB = up_ & (np.abs(l2 - l) <= atrV * 0.3) & (l1 > np.maximum(l2, l) + atrV * 0.2) & (c > h1)
    rectC = up_ & ~na(ph2) & ~na(pl2) & (np.abs(ph1 - ph2) <= atrV * tol) & (np.abs(pl1 - pl2) <= atrV * tol)
    ascT = up_ & ~na(ph2) & ~na(pl2) & (np.abs(ph1 - ph2) <= atrV * tol) & (pl1 > pl2 + atrV * 0.2)
    desT = up_ & ~na(ph2) & ~na(pl2) & (np.abs(pl1 - pl2) <= atrV * tol) & (ph1 < ph2 - atrV * 0.2)
    wdgR = up_ & ~na(ph2) & ~na(pl2) & (ph1 > ph2) & (pl1 > pl2) & ((ph1 - pl1) < (ph2 - pl2) * 0.8)
    wdgF = up_ & ~na(ph2) & ~na(pl2) & (ph1 < ph2) & (pl1 < pl2) & ((ph1 - pl1) < (ph2 - pl2) * 0.8)
    polU = (sh(c, 5) - sh(c, 15)) / atrV > 2.5
    polD = (sh(c, 15) - sh(c, 5)) / atrV > 2.5
    rng5 = (T.highest(h, 5) - T.lowest(l, 5)) / atrV
    contU = (rectC & (c > ph1) & (c1 <= ph1) & (rvol >= 1.2)) | (ascT & (c > ph1) & (c1 <= ph1) & (rvol >= 1.2)) \
        | (up_ & polU & (rng5 < 1.6) & (c > sh(T.highest(h, 5), 1)) & (rvol >= 1.1)) \
        | (up_ & polU & triC & (c > ph1) & (c1 <= ph1)) | (wdgF & (c > ph1) & (c1 <= ph1))
    contD = (rectC & (c < pl1) & (c1 >= pl1) & (rvol >= 1.2)) | (desT & (c < pl1) & (c1 >= pl1) & (rvol >= 1.2)) \
        | (up_ & polD & (rng5 < 1.6) & (c < sh(T.lowest(l, 5), 1)) & (rvol >= 1.1)) \
        | (up_ & polD & triC & (c < pl1) & (c1 >= pl1)) | (wdgR & (c < pl1) & (c1 >= pl1))

    # ===== GERBANG =====
    slLv = np.maximum(np.minimum(np.maximum(np.minimum(sw8L - atrV * p["slBuf"], c - atrV * p["slMinA"]), c - atrV * p["slMaxA"]), c - wkBL), c - atrV * p["slMaxA"])
    slSv = np.minimum(np.maximum(np.minimum(np.maximum(sw8H + atrV * p["slBuf"], c + atrV * p["slMinA"]), c + atrV * p["slMaxA"]), c + wkBS), c + atrV * p["slMaxA"])
    okL = (c - slLv >= atrV * p["slMinA"] * 0.9) & btcOkL
    okS = (slSv - c >= atrV * p["slMinA"] * 0.9) & btcOkS
    helpL = aboveK * 1 + (tenkan > kijun) * 1 + (macdL > macdSg) * 1 + (rsiV > 50) * 1 + (diP > diM) * 1 + (obvV > obvE) * 1 + dowUp * 1 + crsUp * 1 + ltUp * 1
    helpS = belowK * 1 + (tenkan < kijun) * 1 + (macdL < macdSg) * 1 + (rsiV < 50) * 1 + (diM > diP) * 1 + (obvV < obvE) * 1 + dowDn * 1 + crsDn * 1 + ltDn * 1
    confL = htfBull * 1 + tUp * 1 + cdlL * 1 + (rvol >= 1.1) * 1 + cdvB * 1 + (d1 > 0) * 1
    confS = htfBear * 1 + tDn * 1 + cdlS * 1 + (rvol >= 1.1) * 1 + cdvS * 1 + (d1 < 0) * 1
    confMax = np.maximum(confL, confS)
    ext20 = np.abs(c - ema20) / atrV
    g1L = (confL >= p["minConf"]) & (ext20 <= p["chaseA"]) & (helpL >= p["minHelp"])
    g1S = (confS >= p["minConf"]) & (ext20 <= p["chaseA"]) & (helpS >= p["minHelp"])
    g0L = g1L & ((not p["needMTF"]) | htfBull)
    g0S = g1S & ((not p["needMTF"]) | htfBear)

    # ===== SKILL PRICE ACTION =====
    flipU = np.full(n, NAN)
    flipD = np.full(n, NAN)
    flipUB = np.zeros(n)
    flipDB = np.zeros(n)
    fU, fD, fUB, fDB = NAN, NAN, 0, 0
    for i in range(n):
        if i > 0 and c[i] > resV[i] and c[i - 1] <= resV[i]:
            fU, fUB = resV[i], i
        if i > 0 and c[i] < supV[i] and c[i - 1] >= supV[i]:
            fD, fDB = supV[i], i
        if not np.isnan(fU) and c[i] < fU - atrV[i] * 0.5:
            fU = NAN
        if not np.isnan(fD) and c[i] > fD + atrV[i] * 0.5:
            fD = NAN
        flipU[i], flipD[i], flipUB[i], flipDB[i] = fU, fD, fUB, fDB
    rtFlipL = ~na(flipU) & (bi - flipUB >= 2) & (bi - flipUB <= 40) & (l <= flipU + atrV * 0.25) & (c > flipU) & (cdlL | pinL | engL)
    rtFlipS = ~na(flipD) & (bi - flipDB >= 2) & (bi - flipDB <= 40) & (h >= flipD - atrV * 0.25) & (c < flipD) & (cdlS | pinS | engS)
    cfTlL = atTlL & atSup & (engL | pinL | cdlL)
    cfTlS = atTlS & atRes & (engS | pinS | cdlS)
    rsiPL, rsiPH = np.full(n, NAN), np.full(n, NAN)
    rpl = rph = NAN
    rsiM = sh(rsiV, mp)
    for i in range(n):
        if not np.isnan(mPl[i]):
            rpl = rsiM[i]
        if not np.isnan(mPh[i]):
            rph = rsiM[i]
        rsiPL[i], rsiPH[i] = rpl, rph
    lo5, hi5 = T.lowest(l, 5), T.highest(h, 5)
    hdvL = tUp & ~na(pl1) & (l > pl1) & (l <= lo5) & (rsiV < nz(rsiPL, 0) - 3) & cdlL
    hdvS = tDn & ~na(ph1) & (h < ph1) & (h >= hi5) & (rsiV > nz(rsiPH, 100) + 3) & cdlS
    bigL = (c > o) & (brange >= avgRng * 1.5) & (bodyR >= 0.6)
    bigS = (c < o) & (brange >= avgRng * 1.5) & (bodyR >= 0.6)
    blkL = (dowDn | sh(tDn, 5)) & ~na(pl1) & (lo5 > pl1) & tlBU & bigL
    blkS = (dowUp | sh(tUp, 5)) & ~na(ph1) & (hi5 < ph1) & tlBD & bigS
    stK = T.sma(T.stoch(rsiV, rsiV, rsiV, 14), 3)
    stD = T.sma(stK, 3)
    srL = tUp & T.crossover(stK, stD) & (sh(stK, 1) < 20)
    srS = tDn & T.crossunder(stK, stD) & (sh(stK, 1) > 80)
    rsL = dowUp & ~na(ph2) & (ph1 > ph2) & (l <= ph2 + atrV * 0.3) & (c > ph2) & cdlL
    rsS = dowDn & ~na(pl2) & (pl1 < pl2) & (h >= pl2 - atrV * 0.3) & (c < pl2) & cdlS
    h3p, l3p, r3p = sh(T.highest(h, 3), 1), sh(T.lowest(l, 3), 1), sh(T.highest(brange, 3), 1)
    dmTa, dmBa, spTa, spBa = (np.full(n, NAN) for _ in range(4))
    dmBar = np.zeros(n)
    spBar = np.zeros(n)
    dT_, dB_, sT_, sB_, dBr, sBr = NAN, NAN, NAN, NAN, 0, 0
    for i in range(n):
        if r3p[i] < avgRng[i] * 0.8 and c[i] > o[i] and brange[i] > avgRng[i] * 1.8 and bodyR[i] > 0.6:
            dT_, dB_, dBr = h3p[i], l3p[i], i
        if r3p[i] < avgRng[i] * 0.8 and c[i] < o[i] and brange[i] > avgRng[i] * 1.8 and bodyR[i] > 0.6:
            sT_, sB_, sBr = h3p[i], l3p[i], i
        if not np.isnan(dB_) and c[i] < dB_:
            dT_, dB_ = NAN, NAN
        if not np.isnan(sT_) and c[i] > sT_:
            sT_, sB_ = NAN, NAN
        dmTa[i], dmBa[i], spTa[i], spBa[i], dmBar[i], spBar[i] = dT_, dB_, sT_, sB_, dBr, sBr
    dmT, dmB, spT, spB = dmTa, dmBa, spTa, spBa
    sdL = ~na(dmT) & (bi - dmBar >= 3) & (bi - dmBar <= 60) & (l <= dmT) & (c > dmB) & (closR > 0.6)
    sdS = ~na(spT) & (bi - spBar >= 3) & (bi - spBar <= 60) & (h >= spB) & (c < spT) & (closR < 0.4)
    ema5, ema8, ema13, ema15, ema100 = T.ema(c, 5), T.ema(c, 8), T.ema(c, 13), T.ema(c, 15), T.ema(c, 100)
    brdC = ~na(ph2) & ~na(pl2) & (ph1 > ph2 + atrV * 0.2) & (pl1 < pl2 - atrV * 0.2)
    brdL = brdC & (c > ph1) & (c1 <= ph1) & (rvol >= 1.1)
    brdS = brdC & (c < pl1) & (c1 >= pl1) & (rvol >= 1.1)
    triBL = desT & (c > ph1) & (c1 <= ph1) & (rvol >= 1.1)
    triBS = ascT & (c < pl1) & (c1 >= pl1) & (rvol >= 1.1)
    rPh, rPl = T.pivothigh(rsiV, 5, 5), T.pivotlow(rsiV, 5, 5)
    rTlH, rTlL = np.full(n, NAN), np.full(n, NAN)
    a1 = a2 = b1 = b2 = NAN
    a1i = a2i = b1i = b2i = 0
    for i in range(n):
        if not np.isnan(rPh[i]):
            a2, a2i, a1, a1i = a1, a1i, rPh[i], i - 5
        if not np.isnan(rPl[i]):
            b2, b2i, b1, b1i = b1, b1i, rPl[i], i - 5
        if not np.isnan(a2) and a1 < a2 and a1i != a2i:
            rTlH[i] = a1 + (a1 - a2) / (a1i - a2i) * (i - a1i)
        if not np.isnan(b2) and b1 > b2 and b1i != b2i:
            rTlL[i] = b1 + (b1 - b2) / (b1i - b2i) * (i - b1i)
    rtbL = ~na(rTlH) & (rsiV > rTlH) & (sh(rsiV, 1) <= nz(sh(rTlH, 1), rTlH)) & cdlL
    rtbS = ~na(rTlL) & (rsiV < rTlL) & (sh(rsiV, 1) >= nz(sh(rTlL, 1), rTlL)) & cdlS
    rbUp = (ema5 > ema8) & (ema8 > ema13)
    rbDn = (ema5 < ema8) & (ema8 < ema13)
    rbL = rbUp & ~sh(rbUp, 3) & (c > ema5) & cdlL
    rbS = rbDn & ~sh(rbDn, 3) & (c < ema5) & cdlS
    p100L = (c > ema100) & (ema100 > sh(ema100, 5)) & (l <= ema100) & cdlL
    p100S = (c < ema100) & (ema100 < sh(ema100, 5)) & (h >= ema100) & cdlS
    gcL, gcS = T.crossover(ema50, ema200), T.crossunder(ema50, ema200)
    r815L = tUp & (ema8 > ema15) & (l <= ema15) & (c > ema8) & cdlL
    r815S = tDn & (ema8 < ema15) & (h >= ema15) & (c < ema8) & cdlS

    rv10, rv11, rv12, rv13 = rvol >= 1.0, rvol >= 1.1, rvol >= 1.2, rvol >= 1.3
    a04, a05 = atrV * 0.4, atrV * 0.5
    hurstT, zThr = p["hurstT"], p["zThr"]

    open = o
    loc = dict(locals())
    env = {k: val for k, val in loc.items() if not k.startswith("_")}
    env.update(sh=sh, nz=nz, na=na, ta_highest=T.ta_highest, ta_lowest=T.ta_lowest,
               math_abs=T.math_abs, math_avg=T.math_avg)
    cLa = np.column_stack([np.broadcast_to(np.asarray(x, bool), (n,)) for x in R.rules_cLa(env)])
    cSa = np.column_stack([np.broadcast_to(np.asarray(x, bool), (n,)) for x in R.rules_cSa(env)])
    lvL = np.column_stack([np.broadcast_to(T.f64(x), (n,)) for x in R.rules_lvL(env)])
    lvS = np.column_stack([np.broadcast_to(T.f64(x), (n,)) for x in R.rules_lvS(env)])
    lvL = np.where(np.isnan(lvL), ema20[:, None], lvL)
    lvS = np.where(np.isnan(lvS), ema20[:, None], lvS)

    # f_kOK per pola
    fam = np.array(R.FAM)
    d1t, d2t = p["d1Thr"], p["d2Thr"]
    hardL = np.stack([np.where(f == 1, (d2 > 0) | inflL, np.where(f == 2, (d3 > 0) | (d1 > d1t), d1 > d1t)) for f in fam], 1)
    hardS = np.stack([np.where(f == 1, (d2 < 0) | inflS, np.where(f == 2, (d3 < 0) | (d1 < -d1t), d1 < -d1t)) for f in fam], 1)
    km = p["kMode"]
    if km == "Mati":
        kOKL = np.ones((n, 90), bool)
        kOKS = np.ones((n, 90), bool)
    elif km == "Wajib (ketat)":
        kOKL = hardL & (kScL >= p["kMinSc"])[:, None]
        kOKS = hardS & (kScS >= p["kMinSc"])[:, None]
    else:
        kOKL = hardL | (kScL >= p["kMinSc"])[:, None]
        kOKS = hardS | (kScS >= p["kMinSc"])[:, None]

    obU = np.column_stack([resV, fib0, e127, dcU, kumoT, psyLv, bbU])
    obD = np.column_stack([supV, fib0, e127, dcL, kumoB, psyLv, bbL])
    pPr = np.minimum(0.72, np.maximum(0.35, 0.42 + confMax * 0.035 + np.where(hurst > hurstT, 0.05, 0)))

    out = dict(
        ts=ts, open=o, high=h, low=l, close=c, volume=vol, atr=atrV, cLa=cLa, cSa=cSa, lvL=lvL, lvS=lvS,
        kOKL=kOKL, kOKS=kOKS, okL=okL, okS=okS, g0L=g0L, g0S=g0S, mktOk=mktOk, slLv=slLv, slSv=slSv,
        rgIdx=rgIdx.astype(np.int64), trending=trending, ranging=ranging, pPr=pPr, biasLg=biasLg,
        sw8L=sw8L, sw8H=sw8H, wkBL=wkBL, wkBS=wkBS, obU=obU, obD=obD, capMove=capMove, d1=d1,
        btcOkL=btcOkL, btcOkS=btcOkS, isSpk=isSpk, trapU=trapU, trapD=trapD,
        # untuk vonis & pesan
        bProb=bProb, btcUp=btcUp, btcDn=btcDn, btcMom=btcMom, btcKuat=btcKuat, helpL=helpL, helpS=helpS,
        confL=confL, confS=confS, rwBlock=rwBlock, suicL=suicL, suicS=suicS, kScL=kScL, kScS=kScS,
        tUp=tUp, tDn=tDn, upLeg=upLeg, gzTop=gzTop, gzBot=gzBot, gpTop=gpTop, gpBot=gpBot, swH=swH, swL=swL,
        e127=e127, e161=e161, fib0=fib0,
        inGZ=inGZ, inGP=inGP, ema20=ema20, brkUp=brkUp, brkDn=brkDn, adx=adxV, rsi=rsiV, rvol=rvol,
        hurst=hurst, rSq=rSq, atrPc=atrPc, biasCt=biasCtA, m60=m60, m240=m240, mDy=mDy, mWk=mWk,
    )
    return out
