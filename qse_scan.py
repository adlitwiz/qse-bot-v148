"""QSE v148 - proses satu koin: fitur -> mesin -> vonis PUSAT INSTRUKSI (EKSEKUSI/TAHAN, rapor, GOLDEN MOMENT)."""
import math
import numpy as np
import qse_features as F
import qse_engine as E
import qse_rules as R
import qse_skill as SK
import qse_siklus as SIK
import qse_pola as PL
from config import P

TFMS = {"240": 4 * 3600 * 1000, "60": 3600 * 1000}
TPV = np.array([0.8 if P["useTpX"] else 1.2, 1.4, 1.8, 2.4, 3.2])
PARR = E.params_array(P)
BRK = np.array(R.BRK, dtype=np.bool_)
FAM = np.array(R.FAM, dtype=np.int64)
FIB_IDX = set(list(range(8)) + [30, 31])


def _pola_top(NM, jidx, wnA, lsA, ntA, wrA, pfA, minSmp=12):
    """Sama dengan f_lib DASBOR: tiap pola pakai arah dengan net R lebih besar, wajib minimal 12 trade dan net > 0."""
    out, pakai = [], set()
    for _ in range(5):
        bb, bv = -1, -99999.0
        for i in range(90):
            if i in pakai:
                continue
            dl = ntA[jidx(i, True)] >= ntA[jidx(i, False)]
            j = jidx(i, dl)
            if ntA[j] > bv and wnA[j] + lsA[j] >= minSmp and ntA[j] > 0:
                bv, bb = ntA[j], i
        if bb < 0:
            break
        pakai.add(bb)
        dl = ntA[jidx(bb, True)] >= ntA[jidx(bb, False)]
        j = jidx(bb, dl)
        out.append(dict(pola=NM[bb], arah="LONG" if dl else "SHORT", net_r=float(ntA[j]), win=int(wnA[j]),
                        loss=int(lsA[j]), wr=float(wrA[j]), pf=float(pfA[j])))
    return out


def mulai_uji(ts, TF_MS):
    last_bar_time = int(ts[-1]) + TF_MS          # bar realtime yang sedang berjalan di TradingView
    ujiW = 3000 * TF_MS
    tgl = math.floor(last_bar_time / (ujiW / 2)) * (ujiW / 2) - ujiW
    idx = np.where(ts >= tgl)[0]
    return int(idx[0]) if len(idx) else len(ts)


def grade(wb, ex, pf):
    if wb >= P["wGrA"] and ex >= P["eGrA"] and pf >= P["pGrA"]:
        return 1
    if wb >= P["wGrB"] and ex >= P["eGrB"] and pf >= P["pGrB"]:
        return 2
    return 3


GRID = np.round(np.arange(0, 3.01, 0.1), 2)


def fill_prob(v, L, gap, isL, H):
    """Peluang harga menyentuh entry LIMIT dalam H candle ke depan, dari riwayat koin ini
    dengan kondisi BTC dan volume yang mirip dengan sekarang. gap dalam ATR.
    Return (peluang untuk gap ini, tabel peluang untuk gap 0 sampai 3 ATR per 0.1)."""
    h, l, c, a = v["high"], v["low"], v["close"], v["atr"]
    n = L + 1
    if n < H + 50:
        return (100.0 if gap <= 0 else 0.0), [100.0] + [0.0] * (len(GRID) - 1)
    from numpy.lib.stride_tricks import sliding_window_view as swv
    if isL:
        fut = swv(l[:n], H).min(axis=1)
        x = (c[:n - H] - fut[1:n - H + 1]) / a[:n - H]
    else:
        fut = swv(h[:n], H).max(axis=1)
        x = (fut[1:n - H + 1] - c[:n - H]) / a[:n - H]
    m = len(x)
    lo = max(0, m - 1500)
    x = x[lo:]
    bst = np.where(v["btcUp"][lo:m], 1, np.where(v["btcDn"][lo:m], -1, 0))
    now_b = 1 if v["btcUp"][L] else -1 if v["btcDn"][L] else 0
    rv = v["rvol"][lo:m]
    rvn = v["rvol"][L]
    bucket = lambda r: np.where(r < 0.8, 0, np.where(r < 1.5, 1, 2))
    ok = ~np.isnan(x)
    sel = ok & (bst == now_b) & (bucket(rv) == bucket(np.array([rvn]))[0])
    if sel.sum() < 60:
        sel = ok & (bst == now_b)
    if sel.sum() < 60:
        sel = ok
    if sel.sum() == 0:
        return (100.0 if gap <= 0 else 0.0), [100.0] + [0.0] * (len(GRID) - 1)
    xs = x[sel]
    tab = [float((xs >= g).mean() * 100) if g > 0 else 100.0 for g in GRID]
    p = 100.0 if gap <= 0 else float((xs >= gap).mean() * 100)
    return p, tab


def arah_prob(v, L, isL, Hn=1):
    """Peluang candle ke-Hn berikutnya tutup searah sinyal, dari riwayat koin ini
    pada tren koin dan kondisi BTC yang sama dengan sekarang. Return (persen, jumlah sampel)."""
    c = v["close"]
    n = L + 1
    if n < Hn + 100:
        return 50.0, 0
    ok = (c[Hn:n] > c[:n - Hn]) if isL else (c[Hn:n] < c[:n - Hn])
    m = len(ok)
    lo = max(0, m - 1500)
    ok = ok[lo:]
    tr = np.where(v["tUp"], 1, np.where(v["tDn"], -1, 0))
    bs = np.where(v["btcUp"], 1, np.where(v["btcDn"], -1, 0))
    sel = (tr[lo:m] == tr[L]) & (bs[lo:m] == bs[L])
    if sel.sum() < 60:
        sel = tr[lo:m] == tr[L]
    if sel.sum() < 60:
        sel = np.ones(len(ok), bool)
    return float(ok[sel].mean() * 100), int(sel.sum())


def btc_now(btc4, t_now, sym):
    """Gerbang BTC seperti di candle berjalan TradingView: pakai candle BTC 4J yang baru tutup."""
    bf = F._btc_fc(btc4)
    pos = np.searchsorted(bf.index.values, t_now, side="right") - 1
    if pos < 0:
        return None
    b = bf.iloc[pos]
    up = b.bC > b.bE20 > b.bE50
    dn = b.bC < b.bE20 < b.bE50
    mom = b.bC > b.bC1
    buka = (not P["btcGate"]) or ("BTC" in sym)
    return dict(okL=bool(buka or not (dn and not mom)), okS=bool(buka or not (up and mom)),
                prob=float(b.bProb) if b.bProb == b.bProb else 50.0,
                txt="BTC 4J " + ("NAIK" if up else "TURUN" if dn else "SIDEWAYS"))


def _zona(v, R, rkId, rkDr, sJ):
    """Zona entry, SL, TP dan tipe order di candle berjalan, sama seperti f_zone Pine yang dihitung ulang tiap tick."""
    a, c, d1 = v["atr"][R], v["close"][R], v["d1"][R]
    zLv, zSL, zTP, zT2 = (np.zeros(5) for _ in range(4))
    oTy = np.zeros(5, np.int64)
    for k in range(5):
        ik, isL = int(rkId[k]), bool(rkDr[k])
        if ik < 0:
            continue
        lv = v["lvL"][R, ik] if isL else v["lvS"][R, ik]
        base = v["sw8L"][R] - a * P["slBuf"] if isL else v["sw8H"][R] + a * P["slBuf"]
        wSL = lv - v["wkBL"][R] if isL else lv + v["wkBS"][R]
        ref = E._nmin(base, wSL) if isL else E._nmax(base, wSL)
        rr = E._nmin(E._nmax(abs(lv - ref), a * P["slMinA"]), a * P["slMaxA"])
        sl = lv - rr if isL else lv + rr
        bO = lv + a * 8 if isL else lv - a * 8
        for q in range(7):
            vv = v["obU"][R, q] if isL else v["obD"][R, q]
            if isL and lv + a * 0.4 < vv < bO:
                bO = vv
            if (not isL) and bO < vv < lv - a * 0.4:
                bO = vv
        tv, cm = TPV[sJ[ik]], v["capMove"][R]
        if isL:
            tpC = E._nmin(E._nmin(lv + rr * tv, bO - a * 0.25), lv + cm * P["tpReach"] * a)
            tp = E._nmax(tpC, lv + rr * P["minRR"])
            t1c = E._nmax(E._nmin(lv + rr * P["tp1Mul"], E._nmin(bO - a * 0.25, lv + cm * P["tp1Rch"] * a)), lv + rr * 0.45)
            tp1 = E._nmin(t1c, tp)
        else:
            tpC = E._nmax(E._nmax(lv - rr * tv, bO + a * 0.25), lv - cm * P["tpReach"] * a)
            tp = E._nmin(tpC, lv - rr * P["minRR"])
            t1c = E._nmin(E._nmax(lv - rr * P["tp1Mul"], E._nmax(bO + a * 0.25, lv - cm * P["tp1Rch"] * a)), lv - rr * 0.45)
            tp1 = E._nmax(t1c, tp)
        zLv[k], zSL[k], zTP[k], zT2[k] = lv, sl, tp1, tp
        oTy[k] = E._ordty(bool(BRK[ik]), abs(c - lv) / a, bool((lv > c and d1 > 0) or (lv < c and d1 < 0)),
                          P["maxFar"], P["mktTol"])
    return zLv, zSL, zTP, zT2, oTy


def process(sym, df, df1h, dfD, dfW, btc, tick, tf="240", df4=None, btc_tf=None, lim_h=24, btc_live=None,
            df_live=None, h1_live=None):
    """df = candle tutup. df_live = candle tutup + 1 candle berjalan (opsional). Dengan df_live, vonis, entry,
    SL, TP dihitung seperti panel DASBOR di candle berjalan. Mesin tetap hanya memakai candle tutup."""
    TF_MS = TFMS[tf]
    live = (df_live is not None and tf == "240" and len(df_live) == len(df) + 1
            and df_live.index[-2] == df.index[-1])
    if live:
        v = F.build(df_live, h1_live if h1_live is not None else df1h, dfD, dfW,
                    btc_live if btc_live is not None else btc, sym, tick, tf, df4, btc_tf)
    else:
        v = F.build(df, df1h, dfD, dfW, btc, sym, tick, tf, df4, btc_tf)
    n = len(v["ts"]) - (1 if live else 0)
    ts = v["ts"][:n]
    RT = n if live else n - 1
    mu = mulai_uji(ts, TF_MS)
    barNo = (ts // TF_MS).astype(np.int64)
    w = {k: v[k][:n] for k in ("close", "high", "low", "atr", "cLa", "cSa", "kOKL", "kOKS", "okL", "okS", "g0L",
                                "g0S", "mktOk", "slLv", "slSv", "rgIdx", "trending", "ranging", "pPr", "biasLg", "lvL",
                                "lvS", "sw8L", "sw8H", "wkBL", "wkBS", "obU", "obD", "capMove", "d1", "btcOkL", "btcOkS",
                                "isSpk", "trapU", "trapD")}
    res = E.run(mu, w["close"], w["high"], w["low"], w["atr"], w["cLa"], w["cSa"], w["kOKL"], w["kOKS"],
                w["okL"], w["okS"], w["g0L"], w["g0S"], w["mktOk"], w["slLv"], w["slSv"], w["rgIdx"],
                w["trending"], w["ranging"], w["pPr"], barNo, w["biasLg"], w["lvL"], w["lvS"], w["sw8L"],
                w["sw8H"], w["wkBL"], w["wkBS"], w["obU"], w["obD"], w["capMove"], w["d1"], w["btcOkL"],
                w["btcOkS"], w["isSpk"], w["trapU"], w["trapD"], BRK, FAM, TPV, PARR, float(tick))
    (rkId, rkDr, vlSt, vlId, vlDir, vlE, vlS, vlP, vlP2, vlTy, vlBar, vlDb, vlTc, vlMae, vlDn, vlLs, vlLsR,
     vlCnt, vlRes, s1A, sSc, sJ, sWb, sNn, sEx, sPF, wnA, lsA, ntA, pfA, wrA, bnA, pvA, hafL, hafS,
     zLv, zSL, zTP, zT2, oTy, durA, durN, lg) = res

    L = n - 1
    if live:
        zLv, zSL, zTP, zT2, oTy = _zona(v, RT, rkId, rkDr, sJ)
    c, lo, hi, a = v["close"][RT], v["low"][RT], v["high"][RT], v["atr"][RT]
    biasLg = bool(v["biasLg"][L])
    totT = int(vlCnt[2] + vlCnt[3])
    lsT = int(vlCnt[3])
    wrT = vlCnt[2] / totT * 100 if totT else 0.0
    pfT = (vlRes + lsT) / lsT if lsT > 0 else (9.9 if vlRes > 0 else 0.0)
    nilT = "SAMPEL KURANG" if totT < 10 else "A" if (wrT >= 60 and pfT >= 1.6) else "B" if (wrT >= 50 and pfT >= 1.2) \
        else "C" if (wrT >= 45 and pfT >= 1.0) else "D buruk"
    bProb = float(v["bProb"][L]) if not np.isnan(v["bProb"][L]) else 50.0
    btcOkL, btcOkS = bool(v["btcOkL"][L]), bool(v["btcOkS"][L])
    bn = btc_now(btc_live, int(ts[L]) + TF_MS, sym) if btc_live is not None else None
    if bn:
        btcOkL, btcOkS, bProb = bn["okL"], bn["okS"], bn["prob"]
    trapU, trapD = bool(v["trapU"][RT]), bool(v["trapD"][RT])
    doneB = P["doneB"]

    def hold(k):
        # TradingView menilai panel di bar_index candle berjalan (L + 1)
        return vlSt[k] != 0 or (L + 1) - vlDb[k] < doneB

    def sId(k):
        return int(vlId[k]) if (hold(k) and vlId[k] >= 0) else int(rkId[k])

    def sDir(k):
        return bool(vlDir[k] == 1) if hold(k) else bool(rkDr[k])

    def jidx(i, isL):
        return i if isL else i + 90

    def slKena(k):
        return vlSt[k] == 2 and not np.isnan(vlS[k]) and (lo <= vlS[k] if vlDir[k] == 1 else hi >= vlS[k])

    def jbk(k):
        return vlSt[k] == 1 and vlTy[k] == 2 and ((sDir(k) and trapU) or ((not sDir(k)) and trapD))

    def okE(k):
        ik = sId(k)
        iq = max(ik, 0)
        d = sDir(k)
        return (ik >= 0 and grade(sWb[iq], sEx[iq], sPF[iq]) <= 2 and bool(pvA[jidx(iq, d)]) and d == biasLg
                and not jbk(k) and not slKena(k) and (btcOkL if d else btcOkS) and nilT != "D buruk" and totT >= 10)

    def alasan(k):
        ik = sId(k)
        iq = max(ik, 0)
        d = sDir(k)
        if ik < 0:
            return "belum ada saran"
        if not pvA[jidx(iq, d)]:
            return "belum lolos uji"
        if grade(sWb[iq], sEx[iq], sPF[iq]) > 2:
            return "nilai C"
        if d != biasLg:
            return "lawan arah"
        if not (btcOkL if d else btcOkS):
            return "BTC 4J melawan"
        if jbk(k):
            return "ada jebakan"
        if totT < 10:
            return "sampel robot kurang"
        if nilT == "D buruk":
            return "rapor D buruk"
        if slKena(k):
            return "SL tersentuh"
        return "aman"

    def bentuk(d):
        if d:
            return v["helpL"][RT] >= 6 and v["confL"][RT] >= 4 and v["d1"][RT] > 0 and not v["rwBlock"][RT] and not v["suicS"][RT]
        return v["helpS"][RT] >= 6 and v["confS"][RT] >= 4 and v["d1"][RT] < 0 and not v["rwBlock"][RT] and not v["suicL"][RT]

    def dval(k, arr, zarr):
        return float(arr[k]) if hold(k) else float(zarr[k])

    def gold_miss(k):
        ik = sId(k)
        d = sDir(k)
        m = []
        if nilT != "A":
            m.append("rapor A (sekarang %s)" % nilT)
        if not (ik >= 0 and okE(k)):
            m.append("saran EKSEKUSI")
        if not ((bProb >= 55 and btcOkL) if d else (bProb <= 45 and btcOkS)):
            m.append("BTC selaras (naik %d%%)" % round(bProb))
        if not bentuk(d):
            m.append("bentuk pasar searah")
        if not (ik >= 0 and abs(c - dval(k, vlE, zLv)) <= a):
            m.append("entry dalam 1 ATR")
        return m

    gIdx = -1
    for k in range(5):
        if gIdx < 0 and sId(k) >= 0 and vlSt[k] != 2 and not gold_miss(k):
            gIdx = k

    saran = []
    for k in range(5):
        ik = sId(k)
        if ik < 0:
            continue
        d = sDir(k)
        j = jidx(ik, d)
        e, sl, t1, t2 = dval(k, vlE, zLv), dval(k, vlS, zSL), dval(k, vlP, zTP), dval(k, vlP2, zT2)
        ty = E.ORD[int(vlTy[k] if hold(k) else oTy[k])]
        risk = max(abs(e - sl), tick)
        gr = grade(sWb[ik], sEx[ik], sPF[ik])
        pz = int(round(min(99, 100 * math.exp(-0.28 * abs(c - e) / max(a, tick))))) if not np.isnan(e) else 0
        wr = float(wrA[j])
        rr1 = abs(t1 - e) / risk
        gap = ((c - e) if d else (e - c)) / a if a > 0 and not np.isnan(e) else 0.0
        p_isi, p_tab = fill_prob(v, L, gap, d, max(1, int(lim_h * 3600000 // TF_MS)))
        p_isi4, p_tab4 = fill_prob(v, L, gap, d, max(1, int(4 * 3600000 // TF_MS)))
        p_arah, n_arah = arah_prob(v, L, d, max(1, int(4 * 3600000 // TF_MS)))
        tersentuh = sl_kena = tp1_kena = False
        if vlSt[k] == 1 and not np.isnan(e):
            a0 = int(vlBar[k]) + 1
            if a0 <= L:
                hh, ll = v["high"][a0:L + 1], v["low"][a0:L + 1]
                tersentuh = bool((ll <= e).any()) if d else bool((hh >= e).any())
                sl_kena = bool((ll <= sl).any()) if d else bool((hh >= sl).any())
                tp1_kena = bool((hh >= t1).any()) if d else bool((ll <= t1).any())
        saran.append(dict(
            p_isi=p_isi, p_tab=p_tab, p_isi4=p_isi4, p_tab4=p_tab4, p_arah=p_arah, n_arah=n_arah, tersentuh=tersentuh, sl_kena=sl_kena, tp1_kena=tp1_kena, close_now=float(c),
            slot=k + 1, idx=ik, pola=R.NM[ik], alasan_pola=R.NRA[ik], arah="LONG" if d else "SHORT",
            status=int(vlSt[k]), sudah_masuk=bool(vlSt[k] == 2), eksekusi=bool(okE(k)), alasan=alasan(k),
            mutu="A" if gr == 1 else "B" if gr == 2 else "C", golden=(k == gIdx), zona_emas=ik in FIB_IDX,
            gold_kurang=gold_miss(k), order=ty, entry=e, sl=sl, tp1=t1, tp2=t2, rr1=rr1, rr2=abs(t2 - e) / risk,
            jarak_atr=abs(c - e) / a if a > 0 else 99.0, peluang=pz, win=int(wnA[j]), loss=int(lsA[j]),
            net_r=float(ntA[j]), pf=float(pfA[j]), wr=wr, hafal=int(hafL[ik] if d else hafS[ik]),
            ev=wr / 100 * rr1 - (1 - wr / 100), dur=float(durA[j] / durN[j]) if durN[j] > 0 else 0.0,
            breakout=bool(BRK[ik]), anti=(d != biasLg), lolos=bool(pvA[j]),
        ))
    up_leg = bool(v["upLeg"][RT])
    in_gp, in_gz = bool(v["inGP"][RT]), bool(v["inGZ"][RT])
    pasar = dict(
        arah="LONG" if biasLg else "SHORT", leg="naik" if up_leg else "turun", in_gp=in_gp, in_gz=in_gz,
        zona_searah=bool((in_gp or in_gz) and (up_leg == biasLg)),
        gp=(float(v["gpBot"][RT]), float(v["gpTop"][RT])), gz=(float(v["gzBot"][RT]), float(v["gzTop"][RT])),
        batal=float(v["swL"][RT] if biasLg else v["swH"][RT]), bentuk=bool(bentuk(biasLg)),
        btc_ok=bool(btcOkL if biasLg else btcOkS),
        btc_selaras=bool((bProb >= 55 and btcOkL) if biasLg else (bProb <= 45 and btcOkS)),
        adx=float(v["adx"][RT]) if not np.isnan(v["adx"][RT]) else 0.0,
        fib_hi=float(v["swH"][RT]), fib_lo=float(v["swL"][RT]), e127=float(v["e127"][RT]), e161=float(v["e161"][RT]),
        k_now=tuple(float(v[k][RT]) for k in ("open", "high", "low", "close")),
        k_prev=tuple(float(v[k][RT - 1]) for k in ("open", "high", "low", "close")),
    )
    rg = ["TREND NAIK", "TREND TURUN", "SIDEWAYS", "VOLATILE"][int(v["rgIdx"][RT])]
    btcTxt = bn["txt"] if bn else "BTC 4J " + ("NAIK" if v["btcUp"][L] else "TURUN" if v["btcDn"][L] else "SIDEWAYS")
    return dict(
        pasar=pasar, izin=("LONG dan SHORT" if btcOkL and btcOkS else "LONG saja" if btcOkL else "SHORT saja" if btcOkS else "tidak ada"),
        symbol=sym, tf=tf, tf_ms=TF_MS, time=int(ts[L]), close=float(c), atr=float(a), tick=tick, rapor=nilT, trd=totT,
        wr=wrT, pf=pfT, net_r=float(vlRes), bias="LONG" if biasLg else "SHORT", regime=rg, bProb=bProb,
        btc=btcTxt, golden=gIdx + 1 if gIdx >= 0 else 0, saran=saran, candle=n, mulai=mu, skill=SK.analisa(v, RT),
        awal_ts=int(ts[0]), uji_ts=int(ts[mu]) if mu < len(ts) else int(ts[-1]),
        siklus=SIK.analisa(df, dfD, bProb, sym.startswith("BTC")) if tf == "240" else None,
        lolos=int(sum(1 for i in range(90) if pvA[i] or pvA[i + 90])), feed="FEED RESMI BYBIT:%s.P" % sym,
        pola_top=_pola_top(R.NM, jidx, wnA, lsA, ntA, wrA, pfA),
        gzh=PL.gz_hunter(v["high"][:n], v["low"][:n], v["close"][:n]) if tf == "240" else None,
        pola_chart=PL.analisa(v["open"][:n], v["high"][:n], v["low"][:n], v["close"][:n], v["atr"][:n],
                              backtest=nilT in ("A", "B", "C")) if tf == "240" else None,
    )
