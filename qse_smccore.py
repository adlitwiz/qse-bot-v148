# Salinan riset/orderblock/smc_core.py, dipakai jalur SnR, MSB, dan SMC di qse_strat.py (aturan sama dengan backtest)
"""Inti deteksi Order Block, MSB, SMC, SnR. Semua kausal: setup diketahui saat candle i tutup.
Setup: (i, arah +1/-1, top, bot, jenis, fitur dict)."""
import numpy as np


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    a = np.full(len(c), np.nan)
    if len(c) <= n: return a
    a[n] = tr[1:n + 1].mean()
    for i in range(n + 1, len(c)):
        a[i] = (a[i - 1] * (n - 1) + tr[i]) / n
    return a


def ema(x, n):
    k = 2 / (n + 1); out = np.empty(len(x)); out[0] = x[0]
    for i in range(1, len(x)): out[i] = out[i - 1] + k * (x[i] - out[i - 1])
    return out


def volpct(v, n=100):
    """ta.percentrank: persen n nilai sebelumnya yang <= nilai sekarang."""
    out = np.full(len(v), np.nan)
    for i in range(n, len(v)):
        out[i] = (v[i - n:i] <= v[i]).mean() * 100
    return out


def cdv_delta(o, h, l, c, v):
    """Delta volume gaya CDV: porsi beli dari badan dan sumbu candle."""
    tw = h - np.maximum(o, c); bw = np.minimum(o, c) - l; body = abs(c - o)
    rng = tw + bw + body
    up = c >= o
    with np.errstate(invalid="ignore", divide="ignore"):
        rate = np.where(rng > 0, 0.5 * (tw + bw + 2 * body) / rng, 0.5)
    return np.where(up, v * rate, -v * rate)


def fitur(o, h, l, c, v):
    a = atr(h, l, c); e200 = ema(c, 200)
    d = cdv_delta(o, h, l, c, v)
    cs = np.cumsum(d); vs = np.cumsum(v)
    n = 20
    flow = np.full(len(c), np.nan)
    flow[n:] = (cs[n:] - cs[:-n]) / np.maximum(vs[n:] - vs[:-n], 1e-12)   # -1..1, positif = beli dominan
    rv = v / np.maximum(np.r_[np.full(20, np.nan), np.convolve(v, np.ones(20) / 20, "valid")[:-1]], 1e-12)
    return dict(atr=a, e200=e200, flow=flow, vp=volpct(v), rv=rv)


def obf(o, h, l, c, p=5, thr=0.0):
    """Order Block Finder (wugamlo): candle lawan terakhir sebelum p candle searah."""
    out = []
    up = c > o; dn = c < o
    for s in range(p + 1, len(c)):
        j = s - p
        mv = abs(c[j] - c[s]) / c[j] * 100
        if mv < thr: continue
        if dn[j] and up[j + 1:s + 1].all():
            out.append((s, 1, o[j], l[j], "obf"))
        elif up[j] and dn[j + 1:s + 1].all():
            out.append((s, -1, h[j], o[j], "obf"))
    return out


def _pivots(h, l, L, R):
    n = len(h); ph = np.zeros(n, bool); pl = np.zeros(n, bool)
    for t in range(L, n - R):
        if h[t] > h[t - L:t].max() and h[t] >= h[t + 1:t + R + 1].max(): ph[t] = True
        if l[t] < l[t - L:t].min() and l[t] <= l[t + 1:t + R + 1].min(): pl[t] = True
    return ph, pl


def msb(o, h, l, c, v, piv=7, zmin=0.5, vp=None):
    """LuxAlgo Market Structure Break + OB: tembus pivot dengan momentum z, OB = candle lawan terakhir 1..10."""
    n = len(c)
    ch = np.r_[0, np.diff(c)]
    out = []
    ph, pl = _pivots(h, l, piv, piv)
    lph = lpl = np.nan
    for i in range(60, n):
        t = i - piv
        if t >= 0 and ph[t]: lph = h[t]
        if t >= 0 and pl[t]: lpl = l[t]
        w = ch[i - 49:i + 1]; sd = w.std(ddof=0)
        z = 0 if sd == 0 else (ch[i] - w.mean()) / sd
        bull = not np.isnan(lph) and c[i] > lph and c[i - 1] <= lph and z > zmin
        bear = not np.isnan(lpl) and c[i] < lpl and c[i - 1] >= lpl and z < -zmin
        if not (bull or bear): continue
        k0 = 0
        for k in range(1, 11):
            if (bull and c[i - k] < o[i - k]) or (bear and c[i - k] > o[i - k]):
                k0 = k; break
        sc = min(100, abs(z) * 20 + (0 if vp is None or np.isnan(vp[i]) else vp[i] * 0.5))
        out.append((i, 1 if bull else -1, h[i - k0], l[i - k0], "msb", dict(skor=sc)))
        if bull: lph = np.nan
        else: lpl = np.nan
    return out


def _legs(h, l, size):
    """Pivot gaya LuxAlgo SMC: tinggi[size] > tertinggi size candle berikutnya."""
    n = len(h); leg = 0; piv = []           # (bar konfirmasi, jenis 'H'/'L', index pivot, level)
    for i in range(size, n):
        hh = h[i - size + 1:i + 1].max(); ll = l[i - size + 1:i + 1].min()
        new = leg
        if h[i - size] > hh: new = 0
        elif l[i - size] < ll: new = 1
        if new != leg:
            piv.append((i, "H" if new == 0 else "L", i - size, h[i - size] if new == 0 else l[i - size]))
        leg = new
    return piv


def smc(o, h, l, c, size=5, swing=50, a200=None):
    """LuxAlgo SMC: struktur internal (size) + swing (swing). OB internal saat BOS/CHoCH."""
    n = len(c)
    if a200 is None: a200 = atr(h, l, c, 200)
    hv = (h - l) >= 2 * np.nan_to_num(a200, nan=np.inf)
    ph_ = np.where(hv, l, h); pl_ = np.where(hv, h, l)
    ip = {}; sp = {}
    for b, k, idx, lv in _legs(h, l, size): ip.setdefault(b, []).append((k, idx, lv))
    for b, k, idx, lv in _legs(h, l, swing): sp.setdefault(b, []).append((k, idx, lv))
    iH = [np.nan, 0, True]; iL = [np.nan, 0, True]; sH = [np.nan, 0, True]; sL = [np.nan, 0, True]
    itr = 0; strd = 0; top = np.nan; bot = np.nan
    out = []
    for i in range(1, n):
        for k, idx, lv in sp.get(i, []):
            if k == "H": sH = [lv, idx, False]; top = lv
            else: sL = [lv, idx, False]; bot = lv
        for k, idx, lv in ip.get(i, []):
            if k == "H": iH = [lv, idx, False]
            else: iL = [lv, idx, False]
        if not np.isnan(top): top = max(top, h[i])
        if not np.isnan(bot): bot = min(bot, l[i])
        # swing break
        if not sH[2] and not np.isnan(sH[0]) and c[i] > sH[0] and c[i - 1] <= sH[0]:
            sH[2] = True; strd = 1
        if not sL[2] and not np.isnan(sL[0]) and c[i] < sL[0] and c[i - 1] >= sL[0]:
            sL[2] = True; strd = -1
        # internal break
        for P, arah in ((iH, 1), (iL, -1)):
            if P[2] or np.isnan(P[0]): continue
            other = sH if arah == 1 else sL
            if P[0] == other[0]: continue
            if (arah == 1 and c[i] > P[0] and c[i - 1] <= P[0]) or (arah == -1 and c[i] < P[0] and c[i - 1] >= P[0]):
                tag = "choch" if itr == -arah else "bos"
                P[2] = True; itr = arah
                a, b = P[1], i
                if arah == 1:
                    j = a + int(np.argmin(pl_[a:b]))
                else:
                    j = a + int(np.argmax(ph_[a:b]))
                eq = (top + bot) / 2 if not (np.isnan(top) or np.isnan(bot)) else np.nan
                out.append((i, arah, ph_[j], pl_[j], "smc", dict(tag=tag, swing=strd * arah, eq=eq)))
    return out


def snr(h, l, c, per=20):
    """SnR swing pivot periode per: pantul di S1 (long) / R1 (short) saat pivot baru terkonfirmasi."""
    ph, pl = _pivots(h, l, per, per)
    out = []
    for i in range(2 * per, len(c)):
        t = i - per
        if pl[t] and c[i] > l[t]: out.append((i, 1, l[t], l[t], "snr"))
        if ph[t] and c[i] < h[t]: out.append((i, -1, h[t], h[t], "snr"))
    return out
