"""QSE v148 - mesin backtest, skor, seleksi 5 saran, zona TP/SL, pelacak robot (Pine baris 838-1391).
Dikompilasi numba bila tersedia. Kode tipe order: 0 -, 1 MARKET, 2 CONDITIONAL STOP, 3 LIMIT, 4 SCALED LIMIT, 5 TUNGGU."""
import numpy as np

try:
    from numba import njit
    NUMBA_OK = True
except Exception:  # fallback tanpa numba, hasil sama, sekitar 50x lebih lambat
    NUMBA_OK = False
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

NP = 90
ORD = ["-", "MARKET", "CONDITIONAL STOP", "LIMIT", "SCALED LIMIT", "TUNGGU"]
PKEYS = ["minWinD", "minSmp", "minNetD", "minPFd", "minWRd", "banAfter", "banNetR", "minKeep", "needRg",
         "memCap", "memBon", "rgBon", "priorK", "fibBon", "gzBon", "retBon", "r1MinN", "useRegFit", "trendPen",
         "corrBon", "wrTop", "wrDrop", "pfTop", "pfDrop", "tierHard", "freeDir", "allowAnti", "antiMinR",
         "farPen", "provW", "biasBon", "tierBon", "grAbon", "wGrA", "eGrA", "pGrA", "wGrB", "eGrB", "pGrB",
         "slBuf", "slMinA", "slMaxA", "tpReach", "tp1Mul", "tp1Rch", "minRR", "maxFar", "mktTol", "doneB",
         "vlExpB", "lockB", "hardProven", "coolTP", "brkBars", "slPerm", "scEvery", "selEvery"]


@njit(cache=True)
def _nmin(a, b):
    if a != a or b != b:
        return np.nan
    return a if a < b else b


@njit(cache=True)
def _nmax(a, b):
    if a != a or b != b:
        return np.nan
    return a if a > b else b


@njit(cache=True)
def _wil(w, n):
    o = 0.0
    if n > 0:
        p = w / n
        o = max(0.0, (p + 1.9208 / n - 1.96 * np.sqrt((p * (1 - p) + 0.9604 / n) / n)) / (1 + 3.8416 / n)) * 100
    return o


@njit(cache=True)
def _ordty(brk, dz, twd, maxFar, mktTol):
    if dz > maxFar:
        return 5
    if brk:
        return 2
    if dz <= mktTol:
        return 1
    if dz <= 1.2 and twd:
        return 3
    if dz <= 2.5:
        return 4
    return 5


@njit(cache=True)
def run(mulai, close, high, low, atr, cLa, cSa, kOKL, kOKS, okL, okS, g0L, g0S, mktOk, slLv, slSv,
        rgIdx, trending, ranging, pPr, barNo, biasLg, lvL, lvS, sw8L, sw8H, wkBL, wkBS, obU, obD,
        capMove, d1, btcOkL, btcOkS, isSpk, trapU, trapD, brk, fam, tpv, P, mintick):
    n = len(close)
    minWinD, minSmp, minNetD, minPFd, minWRd = P[0], P[1], P[2], P[3], P[4]
    banAfter, banNetR, minKeep, needRg = P[5], P[6], P[7], P[8] > 0.5
    memCap, memBon, rgBon, priorK, fibBon, gzBon, retBon, r1MinN = P[9], P[10], P[11], P[12], P[13], P[14], P[15], P[16]
    useRegFit, trendPen, corrBon = P[17] > 0.5, P[18], P[19]
    wrTop, wrDrop, pfTop, pfDrop, tierHard = P[20], P[21], P[22], P[23], P[24] > 0.5
    freeDir, allowAnti, antiMinR = P[25] > 0.5, P[26] > 0.5, P[27]
    farPen, provW, biasBon, tierBon, grAbon = P[28], P[29], P[30], P[31], P[32]
    wGrA, eGrA, pGrA, wGrB, eGrB, pGrB = P[33], P[34], P[35], P[36], P[37], P[38]
    slBuf, slMinA, slMaxA, tpReach, tp1Mul, tp1Rch, minRR = P[39], P[40], P[41], P[42], P[43], P[44], P[45]
    maxFar, mktTol = P[46], P[47]
    doneB, vlExpB, lockB, hardProven = int(P[48]), int(P[49]), int(P[50]), P[51] > 0.5
    coolTP, brkBars, slPerm = int(P[52]), int(P[53]), int(P[54])
    scEvery, selEvery = int(P[55]), int(P[56])
    JMAX = 3

    bS = np.zeros(1350, np.int64); bD = np.zeros(1350, np.int64)
    bSL = np.full(1350, np.nan); bTP = np.full(1350, np.nan)
    bN = np.zeros(1350, np.int64); bW = np.zeros(1350, np.int64)
    bGW = np.zeros(1350); bGL = np.zeros(1350)
    bRg = np.zeros(1350, np.int64); bEB = np.zeros(1350, np.int64)
    mRL = np.zeros(NP); mWL = np.zeros(NP, np.int64); mLL = np.zeros(NP, np.int64)
    mRS = np.zeros(NP); mWS = np.zeros(NP, np.int64); mLS = np.zeros(NP, np.int64)
    rgR = np.zeros(360); rgWn = np.zeros(360, np.int64); rgLs = np.zeros(360, np.int64)
    muteTil = np.zeros(NP, np.int64); slcL = np.zeros(NP, np.int64); slcS = np.zeros(NP, np.int64)
    opN = np.zeros(270, np.int64); durA = np.zeros(180); durN = np.zeros(180, np.int64)
    binL = np.zeros(NP, np.bool_); binS = np.zeros(NP, np.bool_)
    hafL = np.zeros(NP, np.int64); hafS = np.zeros(NP, np.int64)
    perL = np.zeros(NP, np.bool_); perS = np.zeros(NP, np.bool_)
    wnA = np.zeros(180, np.int64); lsA = np.zeros(180, np.int64)
    ntA = np.zeros(180); pfA = np.zeros(180); wrA = np.zeros(180)
    bnA = np.zeros(180, np.bool_); pvA = np.zeros(180, np.bool_); p0A = np.zeros(180, np.bool_)
    sSc = np.full(NP, -99999.0); sJ = np.zeros(NP, np.int64)
    sWb = np.zeros(NP); sNn = np.zeros(NP, np.int64); sEx = np.zeros(NP); sPF = np.zeros(NP)
    rkId = np.full(5, -1, np.int64); rkDr = np.ones(5, np.bool_)
    vlSt = np.zeros(5, np.int64); vlId = np.full(5, -1, np.int64); vlDir = np.zeros(5, np.int64)
    vlE = np.full(5, np.nan); vlT = np.full(5, np.nan); vlB = np.full(5, np.nan)
    vlS = np.full(5, np.nan); vlP = np.full(5, np.nan); vlP2 = np.full(5, np.nan)
    vlTy = np.zeros(5, np.int64); vlBar = np.zeros(5, np.int64); vlFB = np.zeros(5, np.int64)
    vlMae = np.full(5, np.nan); vlDn = np.zeros(5, np.int64); vlTc = np.zeros(5, np.bool_)
    vlDb = np.zeros(5, np.int64); vlLs = np.zeros(5, np.int64); vlLsR = np.zeros(5)
    vlCnt = np.zeros(4, np.int64); vlRes = 0.0; s1A = np.zeros(3)
    zLv = np.zeros(5); zSL = np.zeros(5); zTP = np.zeros(5); zT2 = np.zeros(5)
    zT = np.zeros(5); zB = np.zeros(5); oTy = np.zeros(5, np.int64)
    # log trade robot: bar isi, bar keluar, pola, arah, R
    lg = np.zeros((4000, 5)); lgN = 0

    for t in range(n):
        c = close[t]; hi = high[t]; lo = low[t]; a = atr[t]
        rgi_now = rgIdx[t]
        # ===== BACKTEST =====
        if t >= mulai:
            for i in range(NP):
                c0L = cLa[t, i] and okL[t] and g0L[t] and kOKL[t, i]
                c0S = cSa[t, i] and okS[t] and g0S[t] and kOKS[t, i]
                oL = c0L
                oS = c0S
                iv = i * 3
                if oL or oS or opN[iv] > 0:
                    for j in range(JMAX + 1):
                        ix = i * 15 + j
                        if bS[ix] == 0 and mktOk[t] and (oL or oS):
                            dr = 1 if oL else -1
                            sv = slLv[t] if oL else slSv[t]
                            rq = abs(c - sv)
                            if rq > 0:
                                bD[ix] = dr; bSL[ix] = sv; bTP[ix] = c + dr * rq * tpv[j]
                                bRg[ix] = rgi_now; bEB[ix] = t; bS[ix] = 1; opN[iv] += 1
                        if bS[ix] == 1:
                            dd = bD[ix]
                            hs = lo <= bSL[ix] if dd == 1 else hi >= bSL[ix]
                            ht = hi >= bTP[ix] if dd == 1 else lo <= bTP[ix]
                            if ht and not hs:
                                bN[ix] += 1; bW[ix] += 1; bGW[ix] += tpv[j]; bS[ix] = 0; opN[iv] -= 1
                                if j == 0:
                                    if dd == 1:
                                        mRL[i] += tpv[j]; mWL[i] += 1; slcL[i] = max(0, slcL[i] - 2)
                                    else:
                                        mRS[i] += tpv[j]; mWS[i] += 1; slcS[i] = max(0, slcS[i] - 2)
                                    rgi = i * 4 + bRg[ix]
                                    rgR[rgi] += tpv[j]; rgWn[rgi] += 1
                                    dq = i if dd == 1 else i + 90
                                    durA[dq] += t - bEB[ix]; durN[dq] += 1
                            elif hs:
                                bN[ix] += 1; bGL[ix] += 1.0; bS[ix] = 0; opN[iv] -= 1
                                if j == 0:
                                    dq = i if dd == 1 else i + 90
                                    durA[dq] += t - bEB[ix]; durN[dq] += 1
                                    if dd == 1:
                                        mLL[i] += 1; slcL[i] += 1
                                    else:
                                        mLS[i] += 1; slcS[i] += 1
                                    rgi = i * 4 + bRg[ix]
                                    rgLs[rgi] += 1
        # ===== AGREGASI =====
        hidup = 0
        for i in range(NP):
            for d in range(2):
                j = i if d == 0 else i + 90
                w = mWL[i] if d == 0 else mWS[i]
                ls = mLL[i] if d == 0 else mLS[i]
                gg = mRL[i] if d == 0 else mRS[i]
                nt = gg - ls
                pf = gg / ls if ls > 0 else (9.9 if gg > 0 else 0.0)
                wrd = w / (w + ls) * 100.0 if (w + ls) > 0 else 0.0
                rgj = i * 4 + rgi_now
                rgOk = (not needRg) or (rgWn[rgj] + rgLs[rgj]) < 2 or (rgR[rgj] - rgLs[rgj]) >= 0
                p0 = w >= minWinD and (w + ls) >= minSmp and nt >= minNetD and pf >= minPFd and wrd >= minWRd
                if p0:
                    if d == 0:
                        binL[i] = False
                    else:
                        binS[i] = False
                slc = slcL[i] if d == 0 else slcS[i]
                bn = (slc >= banAfter and nt <= banNetR) or (binL[i] if d == 0 else binS[i]) or (perL[i] if d == 0 else perS[i])
                wnA[j] = w; lsA[j] = ls; ntA[j] = nt; pfA[j] = pf; wrA[j] = wrd; bnA[j] = bn
                if not bn:
                    hidup += 1
                p0A[j] = p0
                pvA[j] = p0 and (not bn) and rgOk
        if hidup < minKeep:
            for j in range(180):
                if bnA[j] and ntA[j] >= 0:
                    bnA[j] = False
                    pvA[j] = p0A[j]
        # ===== SKOR =====
        if t >= mulai and barNo[t] % scEvery == 0:
            for i in range(NP):
                sSc[i] = -99999.0
                nBst = max(ntA[i], ntA[i + 90])
                memB = min(1.0, nBst / memCap) * memBon if nBst > 0 else 0.0
                rgi0 = i * 4 + rgi_now
                rgNet = rgR[rgi0] - rgLs[rgi0] * 1.0
                rgB = min(1.0, rgNet / memCap) * rgBon if (rgWn[rgi0] >= 2 and rgNet > 0) else 0.0
                fitB = 0.0
                if useRegFit:
                    f = fam[i]
                    if trending[t]:
                        fitB = -trendPen if f == 2 else (corrBon if f == 1 else corrBon * 0.8)
                    elif ranging[t]:
                        fitB = 4.0 if f == 2 else (corrBon if f == 1 else -4.0)
                for j in range(JMAX + 1):
                    ix = i * 15 + j
                    nn = bN[ix]
                    if nn >= 2:
                        wr = bW[ix] / nn * 100.0
                        ex = (bW[ix] / nn) * tpv[j] - (1 - bW[ix] / nn)
                        wb = _wil(bW[ix] + pPr[t] * priorK, nn + priorK)
                        pfv = bGW[ix] / bGL[ix] if bGL[ix] > 0 else (9.9 if bGW[ix] > 0 else 0.0)
                        fb = (fibBon + gzBon) if (i <= 7 or i == 30 or i == 31) else 0.0
                        sc = wb * 0.5 + wr * 0.15 + min(pfv, 3.0) * 9.0 + ex * 22.0 + min(nn, 30) * 0.45 + fb \
                            + (0.0 if brk[i] else retBon) + (-12.0 if nn < r1MinN else 0.0) + memB + rgB + fitB
                        if ex > -0.15 and sc > sSc[i]:
                            sSc[i] = sc; sJ[i] = j; sWb[i] = wb; sNn[i] = nn; sEx[i] = ex; sPF[i] = pfv
        # ===== SELEKSI =====
        bl = biasLg[t]
        perluSel = barNo[t] % selEvery == 0
        if t >= mulai:
            for q in range(5):
                if vlSt[q] == 0:
                    perluSel = True
        if perluSel:
            usd = np.zeros(NP, np.bool_)
            for q in range(5):
                if vlSt[q] != 0 and vlId[q] >= 0:
                    usd[vlId[q]] = True
            for k in range(5):
                own = vlId[k] if vlSt[k] != 0 else -1
                if own >= 0:
                    usd[own] = False
                wrK = max(wrTop - k * wrDrop, minWRd)
                pfK = max(pfTop - k * pfDrop, minPFd)
                bi = -1; bd = bl; bv = -99998.0
                for i in range(NP):
                    if usd[i] or t <= muteTil[i]:
                        continue
                    tgL = wrA[i] >= wrK and pfA[i] >= pfK
                    tgS = wrA[i + 90] >= wrK and pfA[i + 90] >= pfK
                    gr2 = sWb[i] >= wGrB and sEx[i] >= eGrB and sPF[i] >= pGrB
                    grA = sWb[i] >= wGrA and sEx[i] >= eGrA and sPF[i] >= pGrA
                    oL2 = pvA[i] and gr2 and (tgL or not tierHard)
                    oS2 = pvA[i + 90] and gr2 and (tgS or not tierHard)
                    if not freeDir:
                        if bl:
                            oS2 = oS2 and allowAnti and k >= 1 and ntA[i + 90] >= antiMinR
                        else:
                            oL2 = oL2 and allowAnti and k >= 1 and ntA[i] >= antiMinR
                    if oL2:
                        skL = sSc[i] - abs(c - lvL[t, i]) / a * farPen + ntA[i] * provW + (biasBon if bl else 0.0) \
                            + (4.0 if hafL[i] > 0 else 0.0) + (tierBon if tgL else 0.0) + (grAbon if grA else 0.0)
                        if skL > bv:
                            bv = skL; bi = i; bd = True
                    if oS2:
                        skS = sSc[i] - abs(c - lvS[t, i]) / a * farPen + ntA[i + 90] * provW + (0.0 if bl else biasBon) \
                            + (4.0 if hafS[i] > 0 else 0.0) + (tierBon if tgS else 0.0) + (grAbon if grA else 0.0)
                        if skS > bv:
                            bv = skS; bi = i; bd = False
                if own >= 0:
                    usd[own] = True
                if bi >= 0:
                    usd[bi] = True
                rkId[k] = bi; rkDr[k] = bd
        for k in range(1, 5):
            for q in range(k):
                if rkId[k] >= 0 and rkId[k] == rkId[q]:
                    rkId[k] = -1
        # ===== ZONA =====
        for k in range(5):
            ik = rkId[k]; isL = rkDr[k]
            lv = 0.0; sl = 0.0; tp = 0.0; tp1 = 0.0
            if ik >= 0:
                lv = lvL[t, ik] if isL else lvS[t, ik]
                base = sw8L[t] - a * slBuf if isL else sw8H[t] + a * slBuf
                wSL = lv - wkBL[t] if isL else lv + wkBS[t]
                ref = _nmin(base, wSL) if isL else _nmax(base, wSL)
                rr = _nmin(_nmax(abs(lv - ref), a * slMinA), a * slMaxA)
                sl = lv - rr if isL else lv + rr
                bO = lv + a * 8 if isL else lv - a * 8
                tg = a * 0.4
                for q in range(7):
                    vv = obU[t, q] if isL else obD[t, q]
                    if isL:
                        if vv > lv + tg and vv < bO:
                            bO = vv
                    else:
                        if vv < lv - tg and vv > bO:
                            bO = vv
                tv = tpv[sJ[ik]]
                if isL:
                    tpC = _nmin(lv + rr * tv, bO - a * 0.25)
                    tpC = _nmin(tpC, lv + capMove[t] * tpReach * a)
                    tp = _nmax(tpC, lv + rr * minRR)
                    t1c = _nmin(lv + rr * tp1Mul, _nmin(bO - a * 0.25, lv + capMove[t] * tp1Rch * a))
                    t1c = _nmax(t1c, lv + rr * 0.45)
                    tp1 = _nmin(t1c, tp)
                else:
                    tpC = _nmax(lv - rr * tv, bO + a * 0.25)
                    tpC = _nmax(tpC, lv - capMove[t] * tpReach * a)
                    tp = _nmin(tpC, lv - rr * minRR)
                    t1c = _nmax(lv - rr * tp1Mul, _nmax(bO + a * 0.25, lv - capMove[t] * tp1Rch * a))
                    t1c = _nmin(t1c, lv - rr * 0.45)
                    tp1 = _nmax(t1c, tp)
            zLv[k] = lv; zSL[k] = sl; zTP[k] = tp1; zT2[k] = tp
            zT[k] = lv + a * 0.4; zB[k] = lv - a * 0.4
            oTy[k] = 0
            if ik >= 0:
                oTy[k] = _ordty(brk[ik], abs(c - lv) / a, (lv > c and d1[t] > 0) or (lv < c and d1[t] < 0), maxFar, mktTol)
        # ===== PELACAK =====
        if t >= mulai:
            for k in range(5):
                for q in range(5):
                    if q < k and vlSt[k] == 1 and vlId[k] >= 0 and vlId[k] == vlId[q] and vlSt[q] != 0:
                        vlSt[k] = 0; vlId[k] = -1; vlDn[k] = 4
                idk = rkId[k]
                st = vlSt[k]
                if st == 0:
                    if t - vlDb[k] >= doneB:
                        dup = False
                        for q in range(5):
                            if q != k and vlSt[q] != 0 and vlId[q] == idk and idk >= 0:
                                dup = True
                        if dup:
                            vlDn[k] = 4
                        else:
                            if idk < 0 or not (btcOkL[t] if rkDr[k] else btcOkS[t]):
                                vlSt[k] = 0; vlId[k] = -1; vlDn[k] = 4
                            else:
                                vlSt[k] = 1; vlId[k] = idk; vlDir[k] = 1 if rkDr[k] else -1
                                vlE[k] = zLv[k]; vlT[k] = zT[k]; vlB[k] = zB[k]; vlS[k] = zSL[k]
                                vlP[k] = zTP[k]; vlP2[k] = zT2[k]; vlTy[k] = oTy[k]; vlBar[k] = t
                                vlTc[k] = False; vlDn[k] = 0
                elif st == 1:
                    dkk = vlDir[k]; lkI = vlId[k]; tyk = vlTy[k]
                    sentuh = lo <= vlE[k] if dkk == 1 else hi >= vlE[k]
                    jebol = c > vlE[k] if dkk == 1 else c < vlE[k]
                    isC = tyk == 2
                    if isC:
                        isi = jebol and (not isSpk[t]) and not (dkk == 1 and trapU[t]) and not (dkk == -1 and trapD[t])
                    else:
                        isi = tyk != 5 and sentuh
                    lawan = (not freeDir) and (not allowAnti) and ((dkk == 1) != bl)
                    btcLwn = not (btcOkL[t] if dkk == 1 else btcOkS[t])
                    if sentuh and tyk != 5 and not isC:
                        vlTc[k] = True
                    if t >= vlBar[k] and isi:
                        if isC:
                            dlt = c - vlE[k]
                            vlE[k] = c; vlS[k] += dlt; vlP[k] += dlt; vlP2[k] += dlt
                            vlT[k] = c + a * 0.4; vlB[k] = c - a * 0.4
                        vlSt[k] = 2; vlMae[k] = lo if dkk == 1 else hi; vlFB[k] = t; vlCnt[0] += 1
                    elif t - vlBar[k] >= vlExpB:
                        vlDn[k] = 3; vlCnt[1] += 1; vlLs[k] = 1
                        if idk < 0 or not (btcOkL[t] if rkDr[k] else btcOkS[t]):
                            vlSt[k] = 0; vlId[k] = -1; vlDn[k] = 4
                        else:
                            vlSt[k] = 1; vlId[k] = idk; vlDir[k] = 1 if rkDr[k] else -1
                            vlE[k] = zLv[k]; vlT[k] = zT[k]; vlB[k] = zB[k]; vlS[k] = zSL[k]
                            vlP[k] = zTP[k]; vlP2[k] = zT2[k]; vlTy[k] = oTy[k]; vlBar[k] = t
                            vlTc[k] = False; vlDn[k] = 0
                    elif lawan or btcLwn:
                        vlDn[k] = 5; vlSt[k] = 0; vlId[k] = -1; vlDb[k] = t; vlTc[k] = False
                        vlLs[k] = 2 if btcLwn else 3
                    elif not vlTc[k]:
                        lkQ = max(lkI, 0)
                        jq = lkQ if dkk == 1 else lkQ + 90
                        rusak = lkI < 0 or bnA[jq] or (hardProven and not pvA[jq])
                        bolehGanti = rusak or t - vlBar[k] >= lockB or tyk == 5
                        if bolehGanti and idk >= 0:
                            dup = False
                            for q in range(5):
                                if q != k and vlSt[q] != 0 and vlId[q] == idk:
                                    dup = True
                            if (not dup) and (lkI != idk or dkk != (1 if rkDr[k] else -1) or abs(vlE[k] - zLv[k]) > a * 0.5):
                                if not (btcOkL[t] if rkDr[k] else btcOkS[t]):
                                    vlSt[k] = 0; vlId[k] = -1; vlDn[k] = 4
                                else:
                                    vlSt[k] = 1; vlId[k] = idk; vlDir[k] = 1 if rkDr[k] else -1
                                    vlE[k] = zLv[k]; vlT[k] = zT[k]; vlB[k] = zB[k]; vlS[k] = zSL[k]
                                    vlP[k] = zTP[k]; vlP2[k] = zT2[k]; vlTy[k] = oTy[k]; vlBar[k] = t
                                    vlTc[k] = False; vlDn[k] = 0
                    if vlSt[k] == 1 and vlId[k] >= 0:
                        vlTy[k] = _ordty(brk[vlId[k]], abs(c - vlE[k]) / a,
                                         (vlE[k] > c and d1[t] > 0) or (vlE[k] < c and d1[t] < 0), maxFar, mktTol)
                if st == 2 or (st == 1 and vlSt[k] == 2):
                    dk = vlDir[k]
                    fb = vlFB[k] == t
                    if vlMae[k] != vlMae[k]:
                        vlMae[k] = lo if dk == 1 else hi
                    else:
                        vlMae[k] = min(vlMae[k], lo) if dk == 1 else max(vlMae[k], hi)
                    if dk == 1:
                        hSL = lo <= vlS[k] or vlMae[k] <= vlS[k]
                        hTP = (c >= vlP[k]) if fb else (hi >= vlP[k])
                    else:
                        hSL = hi >= vlS[k] or vlMae[k] >= vlS[k]
                        hTP = (c <= vlP[k]) if fb else (lo <= vlP[k])
                    ik = vlId[k]
                    if hTP and not hSL:
                        rr = abs(vlP[k] - vlE[k]) / max(abs(vlE[k] - vlS[k]), mintick)
                        vlRes += rr; vlCnt[2] += 1
                        if ik >= 0:
                            if dk == 1:
                                mRL[ik] += rr; mWL[ik] += 1; slcL[ik] = max(0, slcL[ik] - 2); hafL[ik] += 1; binL[ik] = False
                            else:
                                mRS[ik] += rr; mWS[ik] += 1; slcS[ik] = max(0, slcS[ik] - 2); hafS[ik] += 1; binS[ik] = False
                            muteTil[ik] = t + coolTP
                        vlDn[k] = 1; vlLs[k] = 4; vlLsR[k] = rr
                        if k == 0:
                            s1A[0] += 1; s1A[2] += rr
                        if lgN < 4000:
                            lg[lgN, 0] = vlFB[k]; lg[lgN, 1] = t; lg[lgN, 2] = ik; lg[lgN, 3] = dk; lg[lgN, 4] = rr; lgN += 1
                        vlSt[k] = 0; vlTc[k] = False; vlDb[k] = t
                    elif hSL:
                        vlRes -= 1.0; vlCnt[3] += 1
                        if ik >= 0:
                            if dk == 1:
                                mLL[ik] += 1; slcL[ik] += 1; binL[ik] = True
                                if slcL[ik] >= slPerm and mRL[ik] - mLL[ik] <= 0 and hafL[ik] < 3:
                                    perL[ik] = True
                            else:
                                mLS[ik] += 1; slcS[ik] += 1; binS[ik] = True
                                if slcS[ik] >= slPerm and mRS[ik] - mLS[ik] <= 0 and hafS[ik] < 3:
                                    perS[ik] = True
                            muteTil[ik] = t + brkBars
                        vlDn[k] = 2; vlLs[k] = 5; vlLsR[k] = -1.0
                        if k == 0:
                            s1A[1] += 1; s1A[2] -= 1
                        if lgN < 4000:
                            lg[lgN, 0] = vlFB[k]; lg[lgN, 1] = t; lg[lgN, 2] = ik; lg[lgN, 3] = dk; lg[lgN, 4] = -1.0; lgN += 1
                        vlSt[k] = 0; vlTc[k] = False; vlDb[k] = t

    return (rkId, rkDr, vlSt, vlId, vlDir, vlE, vlS, vlP, vlP2, vlTy, vlBar, vlDb, vlTc, vlMae, vlDn, vlLs, vlLsR,
            vlCnt, vlRes, s1A, sSc, sJ, sWb, sNn, sEx, sPF, wnA, lsA, ntA, pfA, wrA, bnA, pvA, hafL, hafS,
            zLv, zSL, zTP, zT2, oTy, durA, durN, lg[:lgN])


def params_array(P):
    return np.array([float(P[k]) for k in PKEYS], dtype=np.float64)
