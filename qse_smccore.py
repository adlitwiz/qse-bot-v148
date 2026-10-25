# Salinan riset/orderblock/smc_core.py + Peningkatan Pilar 2:
# Mengawinkan Order Block, patahan struktur pasar (MSB & SMC BOS/CHoCH), batas harga (SnR), dan celah harga (FVG/Gap)
# menjadi satu strategi penentu zona pantulan yang saling mengunci di satu titik harga presisi dengan minimal 2 konfirmasi struktur pasar.
"""Inti deteksi Order Block, MSB, SMC, SnR, FVG (Celah Harga), dan Zona Pantulan Terkunci (Pilar 2).
Semua kausal: setup diketahui saat candle i tutup.
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


def fvg(o, h, l, c, a=None, min_atr=0.25):
    """Deteksi Celah Harga / Fair Value Gap (FVG) 3-candle yang belum tertutup (unmitigated).
    Bullish FVG: low[i] > high[i-2] dengan dorongan hijau di i-1.
    Bearish FVG: high[i] < low[i-2] dengan dorongan merah di i-1.
    Return list (i, arah +1/-1, top, bot, 'fvg', dict(lebar_atr)).
    """
    n = len(c)
    if a is None:
        a = atr(h, l, c)
    out = []
    for i in range(2, n):
        at = a[i] if not np.isnan(a[i]) and a[i] > 0 else (h[i] - l[i] or 1e-9)
        if l[i] > h[i - 2] and c[i - 1] > o[i - 1]:
            gap = l[i] - h[i - 2]
            if gap >= min_atr * at:
                out.append((i, 1, float(l[i]), float(h[i - 2]), "fvg", dict(lebar_atr=float(gap / at))))
        elif h[i] < l[i - 2] and c[i - 1] < o[i - 1]:
            gap = l[i - 2] - h[i]
            if gap >= min_atr * at:
                out.append((i, -1, float(l[i - 2]), float(h[i]), "fvg", dict(lebar_atr=float(gap / at))))
    return out


def zona_pantulan_terkunci(o, h, l, c, v, arah=None, lookback=120, min_konfirmasi=2):
    """PILAR 2: Kawinkan pemetaan Order Block (OB), patahan struktur pasar (MSB / SMC BOS-CHoCH),
    batas harga (SnR), dan celah harga (FVG/Gap) menjadi satu strategi penentu zona pantulan.
    Seluruh pemetaan saling mengunci di satu titik harga presisi (titik_kunci), dan hanya menandai
    zona transaksi yang memiliki tumpukan minimal `min_konfirmasi` (default 2) konfirmasi struktur pasar.

    Return dict zona terkunci terbaik untuk arah (+1 LONG / -1 SHORT) atau None bila tumpukan < min_konfirmasi.
    """
    n = len(c)
    if n < 80:
        return None
    a_arr = atr(h, l, c)
    at = float(a_arr[-1]) if not np.isnan(a_arr[-1]) and a_arr[-1] > 0 else float(abs(h[-1] - l[-1]) or 1e-6)
    px = float(c[-1])
    s0 = max(20, n - lookback)

    # Kumpulkan kandidat komponen dari 4 dimensi pemetaan yang masih aktif (belum tertembus penuh)
    vp = volpct(v)
    ob_list = [x for x in obf(o, h, l, c, 5, 0.3) if x[0] >= s0]
    msb_list = [x for x in msb(o, h, l, c, v, 7, 0.3, vp) if x[0] >= s0]
    smc_list = [x for x in smc(o, h, l, c, 5, 50, atr(h, l, c, 200)) if x[0] >= s0]
    snr_list = [x for x in snr(h, l, c, 15) if x[0] >= max(20, n - 250)]
    fvg_list = [x for x in fvg(o, h, l, c, a_arr, 0.15) if x[0] >= s0]

    arah_kandidat = [1, -1] if arah is None else ([1] if arah in (1, "LONG") else [-1])
    terbaik = None

    for ar in arah_kandidat:
        komponen = []  # (jenis_kategori, nama_detail, bot, top, titik_tengah, bar_idx)

        # 1. Order Block (OB Finder 3-5 bar)
        for idx, d, top, bot, _ in reversed(ob_list):
            if d != ar:
                continue
            b_lo, b_hi = min(top, bot), max(top, bot)
            if idx + 1 < n:
                if ar == 1 and l[idx + 1:].min() < b_lo - 0.5 * at:
                    continue
                if ar == -1 and h[idx + 1:].max() > b_hi + 0.5 * at:
                    continue
            komponen.append(("OB", "Order Block", float(b_lo), float(b_hi), float((b_lo + b_hi) / 2), int(idx)))
            break

        # 2. Patahan Struktur Pasar (MSB & SMC BOS/CHoCH & Tembus Pivot Struktur)
        for idx, d, top, bot, _, ex in reversed(msb_list):
            if d != ar:
                continue
            b_lo, b_hi = min(top, bot), max(top, bot)
            komponen.append(("STRUKTUR_MSB", f"Patahan Struktur MSB (skor {ex.get('skor', 0):.0f})", float(b_lo), float(b_hi), float((b_lo + b_hi) / 2), int(idx)))
            break

        for idx, d, top, bot, _, ex in reversed(smc_list):
            if d != ar:
                continue
            b_lo, b_hi = min(top, bot), max(top, bot)
            tag = (ex.get("tag") or "bos").upper()
            komponen.append(("STRUKTUR_SMC", f"Patahan Struktur SMC {tag}", float(b_lo), float(b_hi), float((b_lo + b_hi) / 2), int(idx)))
            break

        # Deteksi patahan struktur lokal 10-20 bar bila belum tercatat di smc_list
        if not any(k_[0].startswith("STRUKTUR") for k_ in komponen) and n >= 25:
            hh20, ll20 = float(h[-21:-1].max()), float(l[-21:-1].min())
            if ar == 1 and c[-1] > hh20:
                komponen.append(("STRUKTUR_BOS", "Patahan Struktur BOS 20 Bar", float(l[-6:-1].min()), hh20, float((l[-6:-1].min() + hh20) / 2), n - 1))
            elif ar == -1 and c[-1] < ll20:
                komponen.append(("STRUKTUR_BOS", "Patahan Struktur BOS 20 Bar", ll20, float(h[-6:-1].max()), float((ll20 + h[-6:-1].max()) / 2), n - 1))

        # 3. Batas Harga (Support / Resistance SnR)
        for idx, d, top, bot, _ in reversed(snr_list):
            if d != ar:
                continue
            lv = float((top + bot) / 2)
            if (ar == 1 and lv <= px + 1.2 * at) or (ar == -1 and lv >= px - 1.2 * at):
                komponen.append(("SNR", "Batas Harga SnR", lv - 0.30 * at, lv + 0.30 * at, lv, int(idx)))
                break

        # 4. Celah Harga (Fair Value Gap / FVG)
        for idx, d, top, bot, _, ex in reversed(fvg_list):
            if d != ar:
                continue
            b_lo, b_hi = min(top, bot), max(top, bot)
            if idx + 1 < n:
                if ar == 1 and c[idx + 1:].min() < b_lo:
                    continue
                if ar == -1 and c[idx + 1:].max() > b_hi:
                    continue
            komponen.append(("FVG", f"Celah Harga FVG ({ex.get('lebar_atr', 0):.1f} ATR)", float(b_lo), float(b_hi), float((b_lo + b_hi) / 2), int(idx)))
            break

        if len(komponen) < min_konfirmasi:
            continue

        # Cari klaster komponen yang saling mengunci dalam satu struktur dorongan harga (<= 3.0 ATR)
        klaster_terbaik = []
        for i_k, k_utama in enumerate(komponen):
            klaster = [k_utama]
            for j_k, k_lain in enumerate(komponen):
                if i_k == j_k:
                    continue
                overlap = max(k_utama[2], k_lain[2]) <= min(k_utama[3], k_lain[3]) + 1.5 * at
                dekat = abs(k_utama[4] - k_lain[4]) <= 3.0 * at
                if overlap or dekat:
                    klaster.append(k_lain)
            if len(klaster) > len(klaster_terbaik):
                klaster_terbaik = klaster

        kategori_unik = {x[0] for x in klaster_terbaik}
        if len(kategori_unik) < min_konfirmasi:
            continue

        # Hitung titik harga presisi (titik kunci) yang menyatukan OB dan konfirmasi struktur lainnya
        ob_items = [x for x in klaster_terbaik if x[0] == "OB"]
        if ob_items:
            # Kunci pada batas atas OB (untuk LONG) / batas bawah OB (untuk SHORT) yang diperkuat komponen struktur lain
            ob_lo, ob_hi = ob_items[0][2], ob_items[0][3]
            zona_bot = float(ob_lo)
            zona_top = float(max(ob_hi, np.mean([x[3] for x in klaster_terbaik]))) if ar == 1 else float(ob_hi)
            if ar == -1:
                zona_bot = float(min(ob_lo, np.mean([x[2] for x in klaster_terbaik])))
            titik_kunci = float((zona_bot + zona_top) / 2)
        else:
            irisan_bot = max(x[2] for x in klaster_terbaik)
            irisan_top = min(x[3] for x in klaster_terbaik)
            if irisan_bot <= irisan_top:
                zona_bot, zona_top = float(irisan_bot), float(irisan_top)
                titik_kunci = float((zona_bot + zona_top) / 2)
            else:
                titik_kunci = float(np.mean([x[4] for x in klaster_terbaik]))
                zona_bot = float(min(x[2] for x in klaster_terbaik))
                zona_top = float(max(x[3] for x in klaster_terbaik))

        jarak_atr = float(abs(px - titik_kunci) / at)
        sl_presisi = float(zona_bot - 0.35 * at) if ar == 1 else float(zona_top + 0.35 * at)
        kandidat = dict(
            arah="LONG" if ar == 1 else "SHORT",
            arah_num=ar,
            titik_kunci=titik_kunci,
            zona_bot=zona_bot,
            zona_top=zona_top,
            sl=sl_presisi,
            atr=at,
            harga_sekarang=px,
            jarak_atr=jarak_atr,
            jumlah_konfirmasi=len(kategori_unik),
            konfirmasi=[x[1] for x in klaster_terbaik],
            kategori=sorted(kategori_unik),
            di_zona=bool(zona_bot - 0.8 * at <= px <= zona_top + 1.5 * at),
        )
        if terbaik is None or (kandidat["jumlah_konfirmasi"], -kandidat["jarak_atr"]) > (terbaik["jumlah_konfirmasi"], -terbaik["jarak_atr"]):
            terbaik = kandidat

    return terbaik
