"""QSE v148 - proses satu koin: fitur -> mesin -> vonis PUSAT INSTRUKSI (EKSEKUSI/TAHAN, rapor, GOLDEN MOMENT)."""
import math
import numpy as np
import qse_features as F
import qse_engine as E
import qse_rules as R
from config import P

TF_MS = F.TF_MS
TPV = np.array([0.8 if P["useTpX"] else 1.2, 1.4, 1.8, 2.4, 3.2])
PARR = E.params_array(P)
BRK = np.array(R.BRK, dtype=np.bool_)
FAM = np.array(R.FAM, dtype=np.int64)
FIB_IDX = set(list(range(8)) + [30, 31])


def mulai_uji(ts):
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


def process(sym, df, df1h, dfD, dfW, btc, tick):
    v = F.build(df, df1h, dfD, dfW, btc, sym, tick)
    ts = v["ts"]
    n = len(ts)
    mu = mulai_uji(ts)
    barNo = (ts // TF_MS).astype(np.int64)
    res = E.run(mu, v["close"], v["high"], v["low"], v["atr"], v["cLa"], v["cSa"], v["kOKL"], v["kOKS"],
                v["okL"], v["okS"], v["g0L"], v["g0S"], v["mktOk"], v["slLv"], v["slSv"], v["rgIdx"],
                v["trending"], v["ranging"], v["pPr"], barNo, v["biasLg"], v["lvL"], v["lvS"], v["sw8L"],
                v["sw8H"], v["wkBL"], v["wkBS"], v["obU"], v["obD"], v["capMove"], v["d1"], v["btcOkL"],
                v["btcOkS"], v["isSpk"], v["trapU"], v["trapD"], BRK, FAM, TPV, PARR, float(tick))
    (rkId, rkDr, vlSt, vlId, vlDir, vlE, vlS, vlP, vlP2, vlTy, vlBar, vlDb, vlTc, vlMae, vlDn, vlLs, vlLsR,
     vlCnt, vlRes, s1A, sSc, sJ, sWb, sNn, sEx, sPF, wnA, lsA, ntA, pfA, wrA, bnA, pvA, hafL, hafS,
     zLv, zSL, zTP, zT2, oTy, durA, durN, lg) = res

    L = n - 1
    c, lo, hi, a = v["close"][L], v["low"][L], v["high"][L], v["atr"][L]
    biasLg = bool(v["biasLg"][L])
    totT = int(vlCnt[2] + vlCnt[3])
    lsT = int(vlCnt[3])
    wrT = vlCnt[2] / totT * 100 if totT else 0.0
    pfT = (vlRes + lsT) / lsT if lsT > 0 else (9.9 if vlRes > 0 else 0.0)
    nilT = "SAMPEL KURANG" if totT < 10 else "A" if (wrT >= 60 and pfT >= 1.6) else "B" if (wrT >= 50 and pfT >= 1.2) \
        else "C" if (wrT >= 45 and pfT >= 1.0) else "D buruk"
    bProb = float(v["bProb"][L]) if not np.isnan(v["bProb"][L]) else 50.0
    btcOkL, btcOkS = bool(v["btcOkL"][L]), bool(v["btcOkS"][L])
    trapU, trapD = bool(v["trapU"][L]), bool(v["trapD"][L])
    doneB = P["doneB"]

    def hold(k):
        return vlSt[k] != 0 or L - vlDb[k] < doneB

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
            return v["helpL"][L] >= 6 and v["confL"][L] >= 4 and v["d1"][L] > 0 and not v["rwBlock"][L] and not v["suicS"][L]
        return v["helpS"][L] >= 6 and v["confS"][L] >= 4 and v["d1"][L] < 0 and not v["rwBlock"][L] and not v["suicL"][L]

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
        tersentuh = sl_kena = tp1_kena = False
        if vlSt[k] == 1 and not np.isnan(e):
            a0 = int(vlBar[k]) + 1
            if a0 <= L:
                hh, ll = v["high"][a0:L + 1], v["low"][a0:L + 1]
                tersentuh = bool((ll <= e).any()) if d else bool((hh >= e).any())
                sl_kena = bool((ll <= sl).any()) if d else bool((hh >= sl).any())
                tp1_kena = bool((hh >= t1).any()) if d else bool((ll <= t1).any())
        saran.append(dict(
            tersentuh=tersentuh, sl_kena=sl_kena, tp1_kena=tp1_kena, close_now=float(c),
            slot=k + 1, idx=ik, pola=R.NM[ik], alasan_pola=R.NRA[ik], arah="LONG" if d else "SHORT",
            status=int(vlSt[k]), sudah_masuk=bool(vlSt[k] == 2), eksekusi=bool(okE(k)), alasan=alasan(k),
            mutu="A" if gr == 1 else "B" if gr == 2 else "C", golden=(k == gIdx), zona_emas=ik in FIB_IDX,
            gold_kurang=gold_miss(k), order=ty, entry=e, sl=sl, tp1=t1, tp2=t2, rr1=rr1, rr2=abs(t2 - e) / risk,
            jarak_atr=abs(c - e) / a if a > 0 else 99.0, peluang=pz, win=int(wnA[j]), loss=int(lsA[j]),
            net_r=float(ntA[j]), pf=float(pfA[j]), wr=wr, hafal=int(hafL[ik] if d else hafS[ik]),
            ev=wr / 100 * rr1 - (1 - wr / 100), dur=float(durA[j] / durN[j]) if durN[j] > 0 else 0.0,
            breakout=bool(BRK[ik]), anti=(d != biasLg), lolos=bool(pvA[j]),
        ))
    rg = ["TREND NAIK", "TREND TURUN", "SIDEWAYS", "VOLATILE"][int(v["rgIdx"][L])]
    btcTxt = "BTC 4J " + ("NAIK" if v["btcUp"][L] else "TURUN" if v["btcDn"][L] else "SIDEWAYS")
    return dict(
        symbol=sym, time=int(ts[L]), close=float(c), atr=float(a), tick=tick, rapor=nilT, trd=totT,
        wr=wrT, pf=pfT, net_r=float(vlRes), bias="LONG" if biasLg else "SHORT", regime=rg, bProb=bProb,
        btc=btcTxt, golden=gIdx + 1 if gIdx >= 0 else 0, saran=saran, candle=n, mulai=mu,
        lolos=int(sum(1 for i in range(90) if pvA[i] or pvA[i + 90])), feed="FEED RESMI BYBIT:%s.P" % sym,
    )
