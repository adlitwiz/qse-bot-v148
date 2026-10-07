"""QSE v148 - CHART PATTERN, POLA CANDLE, DAN STATISTIK EKOR CANDLE.
Chart pattern dari pivot 4J: channel naik/turun, range, segitiga (netral, naik, turun), wedge naik/turun,
flag dan pennant, double top/bottom, head and shoulders dan kebalikannya.
Backtest per koin: tiap kemunculan pola yang sama di sejarah koin, apakah harga lalu bergerak 1,5 ATR searah pola
lebih dulu daripada 1,5 ATR melawan, dalam 12 candle."""
import numpy as np

K = 4            # lebar pivot
JEND = 80        # pivot dipakai maksimal 80 candle ke belakang


def _pivot(h, l):
    n = len(h)
    piv = []
    for i in range(K, n - K):
        w_h, w_l = h[i - K:i + K + 1], l[i - K:i + K + 1]
        if h[i] == w_h.max():
            piv.append((i, h[i], 1))
        if l[i] == w_l.min():
            piv.append((i, l[i], -1))
    out = []
    for p in piv:
        if out and out[-1][2] == p[2]:
            if (p[2] == 1 and p[1] >= out[-1][1]) or (p[2] == -1 and p[1] <= out[-1][1]):
                out[-1] = p
        else:
            out.append(p)
    return out


def _slope(pts):
    if len(pts) < 2:
        return 0.0
    x = np.array([p[0] for p in pts], float)
    y = np.array([p[1] for p in pts], float)
    return float(np.polyfit(x, y, 1)[0])


def _deteksi(t, piv, h, l, c, a):
    """Pola di candle t memakai pivot yang sudah terkonfirmasi (idx + K <= t)."""
    at = a[t]
    if not at > 0:
        return None
    pv = [p for p in piv if p[0] + K <= t and p[0] >= t - JEND]
    H = [p for p in pv if p[2] == 1][-3:]
    Lw = [p for p in pv if p[2] == -1][-3:]
    # head and shoulders
    if len(H) == 3 and len(Lw) >= 2:
        h1, h2, h3 = (p[1] for p in H)
        if h2 - max(h1, h3) >= 0.8 * at and abs(h1 - h3) <= 0.6 * at:
            leher = min(p[1] for p in Lw[-2:])
            return dict(nama="Head and Shoulders", arah="TURUN", tembus=bool(c[t] < leher), level=leher)
    if len(Lw) == 3 and len(H) >= 2:
        l1, l2, l3 = (p[1] for p in Lw)
        if min(l1, l3) - l2 >= 0.8 * at and abs(l1 - l3) <= 0.6 * at:
            leher = max(p[1] for p in H[-2:])
            return dict(nama="Inverse Head and Shoulders", arah="NAIK", tembus=bool(c[t] > leher), level=leher)
    # double top dan bottom
    if len(H) >= 2 and Lw:
        a_, b_ = H[-2], H[-1]
        mid = [p for p in Lw if a_[0] < p[0] < b_[0]]
        if abs(a_[1] - b_[1]) <= 0.4 * at and b_[0] - a_[0] >= 5 and mid and max(a_[1], b_[1]) - mid[0][1] >= 1.5 * at:
            return dict(nama="Double Top", arah="TURUN", tembus=bool(c[t] < mid[0][1]), level=mid[0][1])
    if len(Lw) >= 2 and H:
        a_, b_ = Lw[-2], Lw[-1]
        mid = [p for p in H if a_[0] < p[0] < b_[0]]
        if abs(a_[1] - b_[1]) <= 0.4 * at and b_[0] - a_[0] >= 5 and mid and mid[0][1] - min(a_[1], b_[1]) >= 1.5 * at:
            return dict(nama="Double Bottom", arah="NAIK", tembus=bool(c[t] > mid[0][1]), level=mid[0][1])
    # flag dan pennant
    if t >= 30:
        imp = c[t - 8] - c[t - 25]
        rg = h[t - 8:t + 1].max() - l[t - 8:t + 1].min()
        if abs(imp) >= 4 * at and rg <= 0.5 * abs(imp):
            kecil = (h[t - 3:t + 1].max() - l[t - 3:t + 1].min()) < 0.6 * (h[t - 8:t - 4].max() - l[t - 8:t - 4].min())
            naik = imp > 0
            jenis = "Pennant" if kecil else "Flag"
            return dict(nama=("Bull " if naik else "Bear ") + jenis, arah="NAIK" if naik else "TURUN", tembus=False,
                        level=float(h[t - 8:t + 1].max() if naik else l[t - 8:t + 1].min()))
    # garis tren: channel, range, segitiga, wedge
    if len(H) >= 2 and len(Lw) >= 2:
        sh, sl = _slope(H) / at, _slope(Lw) / at
        tol = 0.02
        datar_h, datar_l = abs(sh) < tol, abs(sl) < tol
        if datar_h and datar_l:
            return dict(nama="Range", arah="NETRAL", tembus=False, level=None)
        if sh < -tol and sl > tol:
            return dict(nama="Segitiga Netral", arah="NETRAL", tembus=False, level=None)
        if datar_h and sl > tol:
            return dict(nama="Segitiga Naik (Bullish Triangle)", arah="NAIK", tembus=bool(c[t] > H[-1][1]), level=H[-1][1])
        if sh < -tol and datar_l:
            return dict(nama="Segitiga Turun (Bearish Triangle)", arah="TURUN", tembus=bool(c[t] < Lw[-1][1]), level=Lw[-1][1])
        if sh > tol and sl > tol:
            if sl > sh * 1.2:
                return dict(nama="Rising Wedge", arah="TURUN", tembus=bool(c[t] < Lw[-1][1]), level=Lw[-1][1])
            return dict(nama="Bullish Channel", arah="NAIK", tembus=False, level=None)
        if sh < -tol and sl < -tol:
            if sh < sl * 1.2:
                return dict(nama="Falling Wedge", arah="NAIK", tembus=bool(c[t] > H[-1][1]), level=H[-1][1])
            return dict(nama="Bearish Channel", arah="TURUN", tembus=False, level=None)
    return None


def _hasil(t, arah, h, l, c, a, n_bar=12, m=1.5):
    """1 = bergerak m ATR searah lebih dulu, 0 = melawan lebih dulu, None = tidak keduanya."""
    e, at = c[t], a[t]
    up, dn = e + m * at, e - m * at
    for j in range(t + 1, min(len(c), t + 1 + n_bar)):
        hit_up, hit_dn = h[j] >= up, l[j] <= dn
        if hit_up and hit_dn:
            return None
        if hit_up:
            return 1 if arah == "NAIK" else 0
        if hit_dn:
            return 1 if arah == "TURUN" else 0
    return None


def pola_candle(o, h, l, c, t):
    rg = h[t] - l[t]
    if rg <= 0:
        return None
    bd = abs(c[t] - o[t])
    up_w, lo_w = h[t] - max(o[t], c[t]), min(o[t], c[t]) - l[t]
    if t >= 1 and c[t] > o[t] and c[t - 1] < o[t - 1] and c[t] >= o[t - 1] and o[t] <= c[t - 1]:
        return "Bullish Engulfing"
    if t >= 1 and c[t] < o[t] and c[t - 1] > o[t - 1] and c[t] <= o[t - 1] and o[t] >= c[t - 1]:
        return "Bearish Engulfing"
    if bd <= 0.1 * rg:
        return "Doji (ragu-ragu)"
    if lo_w >= 0.55 * rg and bd <= 0.35 * rg:
        return "Hammer, ekor bawah panjang (penolakan turun)"
    if up_w >= 0.55 * rg and bd <= 0.35 * rg:
        return "Shooting Star, ekor atas panjang (penolakan naik)"
    if bd >= 0.8 * rg:
        return "Marubozu " + ("hijau, dorongan naik kuat" if c[t] > o[t] else "merah, dorongan turun kuat")
    return None


def analisa(o, h, l, c, a, backtest=True):
    """Pola chart terakhir, pola candle, dan statistik ekor candle koin ini."""
    o, h, l, c, a = (np.asarray(x, float) for x in (o, h, l, c, a))
    n = len(c)
    out = dict(chart=None, candle=None, wick=None)
    if n < 120:
        return out
    piv = _pivot(h, l)
    t = n - 1
    d = _deteksi(t, piv, h, l, c, a)
    if d:
        if backtest:
            nm, hit, tot, naik = d["nama"], 0, 0, 0
            for i in range(150, n - 13, 2):
                x = _deteksi(i, piv, h, l, c, a)
                if not x or x["nama"] != nm:
                    continue
                arah = x["arah"] if x["arah"] != "NETRAL" else "NAIK"
                res = _hasil(i, arah, h, l, c, a)
                if res is None:
                    continue
                tot += 1
                hit += res
                naik += res if arah == "NAIK" else 1 - res
            d.update(n=tot, wr=hit / tot * 100 if tot else None, naik=naik / tot * 100 if tot else None)
        out["chart"] = d
    out["candle"] = pola_candle(o, h, l, c, t)
    lo_w = (np.minimum(o, c) - l)[-500:] / np.maximum(a[-500:], 1e-12)
    up_w = (h - np.maximum(o, c))[-500:] / np.maximum(a[-500:], 1e-12)
    legs = [abs(piv[i][1] - piv[i - 1][1]) / max(a[piv[i][0]], 1e-12) for i in range(max(1, len(piv) - 40), len(piv))]
    out["wick"] = dict(bawah=float(np.nanpercentile(lo_w, 85)), atas=float(np.nanpercentile(up_w, 85)),
                       leg=float(np.median(legs)) if legs else 3.0)
    return out


def teks(pl):
    """Satu sampai dua baris teks pola chart dan candle."""
    if not pl:
        return []
    rows = []
    d = pl.get("chart")
    if d:
        tx = f"Chart pattern: {d['nama']} ({'condong ' + d['arah'].lower() if d['arah'] != 'NETRAL' else 'netral, tunggu tembus'})"
        if d.get("tembus"):
            tx += ", sudah tembus"
        if d.get("n"):
            if d["arah"] == "NETRAL":
                tx += f" | di koin ini {d['n']} kali, tembus naik {d['naik']:.0f}%"
            else:
                tx += f" | di koin ini {d['n']} kali, berhasil {d['wr']:.0f}%"
        rows.append(tx)
    if pl.get("candle"):
        rows.append(f"Candle terakhir: {pl['candle']}")
    return rows
