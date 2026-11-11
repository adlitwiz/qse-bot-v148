"""QSE v150 - CHART PATTERN, POLA CANDLE, DAN STATISTIK EKOR CANDLE.
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


def _gz_pivots(h, l, c, depth=10, thr=4.0):
    """Zigzag Golden Zone Hunter. Return list per bar: (start, end, i_start) kaki fib yang diketahui di akhir bar t
    (pivot terkonfirmasi depth/2 bar kemudian, tanpa melihat masa depan)."""
    n = len(c)
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    tr = np.r_[h[0] - l[0], tr]
    atr = np.full(n, np.nan)
    if n > 10:
        atr[9] = tr[:10].mean()
        for i in range(10, n):
            atr[i] = (atr[i - 1] * 9 + tr[i]) / 10
    ln = depth // 2
    p_last, i_last, hi_last, y1, ada = 0.0, 0, False, None, False
    kaki = [None] * n
    for t in range(2 * ln, n):
        thr_t = (atr[t] / c[t]) * 100 * thr if not np.isnan(atr[t]) else 1e9
        w_h, w_l = h[t - 2 * ln:t + 1], l[t - 2 * ln:t + 1]
        ph = h[t - ln] if h[t - ln] >= w_h.max() else None
        pl = l[t - ln] if l[t - ln] <= w_l.min() else None
        for is_high, p in ((True, ph), (False, pl)):
            if p is None or (not is_high and ph is not None):
                continue
            dev = 100 * (p - p_last) / p if p else 0
            if hi_last == is_high and ada:
                if (p > p_last) if hi_last else (p < p_last):
                    p_last, i_last = p, t - ln
            elif abs(dev) > thr_t:
                y1, ada = p_last, True
                p_last, i_last, hi_last = p, t - ln, is_high
        if ada and y1:
            kaki[t] = (p_last, y1, i_last)
    return kaki, atr


def _gz_level(start, end, m):
    return start + (-1 if start > end else 1) * abs(start - end) * m


def gz_hunter(h, l, c, depth=10, thr=4.0, fee_pct=0.055, tf_jam=4, konf=True):
    """Golden Zone Hunter + backtest di sejarah koin ini.
    Kaki fib: 0 = pivot terakhir (start), 1 = pivot sebelumnya (end). 0 di atas = koreksi turun, setup LONG.
    Setup: sentuhan PERTAMA ke 0.618 datang dari sisi 0. Entry 0.618, SL di luar 1.0 plus 0.2 ATR,
    TP1 di 0 (tutup separuh, SL ke entry), TP2 di extension -0.236. Kaki yang sudah pernah disentuh tidak dipakai lagi."""
    h, l, c = (np.asarray(x, float) for x in (h, l, c))
    n = len(c)
    if n < 60:
        return None
    kaki, atr = _gz_pivots(h, l, c, depth, thr)
    hasil, dipakai, t = [], set(), 1
    while t < n - 1:
        k = kaki[t - 1]
        if not k or np.isnan(atr[t - 1]):
            t += 1
            continue
        start, end, i0 = k
        if (start, end) in dipakai or t <= i0:
            t += 1
            continue
        L = start > end
        e = _gz_level(start, end, 0.618)
        kena = (l[t] <= e < c[t - 1]) if L else (h[t] >= e > c[t - 1])
        if not kena:
            t += 1
            continue
        dipakai.add((start, end))
        a = atr[t - 1]
        if konf:
            # wajib candle penolakan: candle sentuh tutup kembali di sisi 0 dari 0.618, entry di harga tutup
            if not ((c[t] > e) if L else (c[t] < e)):
                t += 1
                continue
            e = c[t]
        sl = end - 0.2 * a if L else end + 0.2 * a
        tp1, tp2 = start, _gz_level(start, end, -0.236)
        risk = abs(e - sl)
        if risk <= 0:
            t += 1
            continue
        fee = 2 * fee_pct / 100 * e / risk
        r1, r2 = abs(tp1 - e) / risk, abs(tp2 - e) / risk
        res, j, tp1k = None, t + (1 if konf else 0), False
        while j < n:
            stop = e if tp1k else sl
            if (l[j] <= stop) if L else (h[j] >= stop):
                res = (0.5 * r1 if tp1k else -1.0) - fee
                break
            if not tp1k and ((h[j] >= tp1) if L else (l[j] <= tp1)) and j > t:
                tp1k = True
            if tp1k and ((h[j] >= tp2) if L else (l[j] <= tp2)):
                res = 0.5 * r1 + 0.5 * r2 - fee
                break
            j += 1
        if res is not None:
            hasil.append(dict(t=int(t), arah="LONG" if L else "SHORT", r=float(res), bar=int(j - t)))
        t = j + 1
    # kaki saat ini
    k = kaki[n - 1]
    if not k:
        return None
    start, end, i0 = k
    L = start > end
    e618 = _gz_level(start, end, 0.618)
    seb = slice(i0 + 1, n)
    sudah = bool(len(l[seb]) and ((l[seb].min() <= e618) if L else (h[seb].max() >= e618)))
    lv = {m: _gz_level(start, end, m) for m in (-1.0, -0.618, -0.236, 0.0, 0.5, 0.618, 0.65, 0.786, 1.0)}
    rs = [x["r"] for x in hasil]
    win = [x for x in rs if x > 0]
    rugi = -sum(x for x in rs if x < 0)
    bt = dict(n=len(rs), wr=len(win) / len(rs) * 100 if rs else 0.0, pf=(sum(win) / rugi if rugi > 0 else (9.9 if win else 0.0)),
              avg=sum(rs) / len(rs) if rs else 0.0, jam=float(np.median([x["bar"] for x in hasil]) * tf_jam) if hasil else None,
              tf="4J" if tf_jam == 4 else "1J")
    return dict(start=float(start), end=float(end), puncak=bool(L), sudah=sudah, atr=float(atr[n - 1]),
                levels={str(m): float(v) for m, v in lv.items()}, bt=bt)


# ---------- v173 QC 71: pola candle di candle sinyal sebagai penguat (riset/upgrade/run_v173_long.py bagian D) ----------
# Uji 30 ribu sinyal 8 teknik 2023-2026, aturan keluar live. Semua teknik digabung: pola searah TIDAK konsisten (2023 lebih jelek).
# Per teknik, selisih rata R dengan pola searah dikurangi tanpa pola positif di 2023, 2024, 2025, DAN 2026 hanya di tiga kelompok:
#   EMA Cross SHORT (+0.02, +0.12, +0.40, +0.04), Ichimoku SHORT (+0.07, +0.28, +0.05, +0.01), McGinley LONG (+0.09, +0.03, +0.07, +0.11).
# Negatif di keempat tahun: SMC CHoCH LONG (-0.05, -0.16, -0.25, -0.24). Jadi label penguat hanya untuk tiga kelompok itu,
# peringatan untuk SMC CHoCH LONG, dan teknik lain hanya diberi nama polanya tanpa klaim.
POLA_TERUJI = {("ema_short", "SHORT"): "+0.40R di 2025 dan +0.04R di 2026 dibanding tanpa pola",
               ("ichimoku", "SHORT"): "+0.05R di 2025 dan +0.01R di 2026 dibanding tanpa pola",
               ("mcginley", "LONG"): "+0.07R di 2025 dan +0.11R di 2026 dibanding tanpa pola"}
POLA_JELEK = {("smc_choch", "LONG"): "-0.25R di 2025 dan -0.24R di 2026 dibanding tanpa pola"}


def pola_sinyal(o, h, l, c, arah, i=-1):
    """Pola candle searah `arah` di candle i (definisi sama dengan uji). Return nama pola atau ''."""
    n = len(c)
    i = i if i >= 0 else n + i
    if i < 2:
        return ""
    rg = max(h[i] - l[i], 1e-12); bd = abs(c[i] - o[i])
    lw, uw = (min(o[i], c[i]) - l[i]) / rg, (h[i] - max(o[i], c[i])) / rg
    bd1 = abs(c[i - 1] - o[i - 1]); rg1 = max(h[i - 1] - l[i - 1], 1e-12); rg2 = max(h[i - 2] - l[i - 2], 1e-12)
    L = arah == "LONG"
    if L:
        if lw >= 0.55 and bd / rg <= 0.35 and uw <= 0.25:
            return "Hammer / Pin Bar (ekor bawah panjang)"
        if c[i] > o[i] and c[i - 1] < o[i - 1] and c[i] >= o[i - 1] and o[i] <= c[i - 1] and bd > bd1:
            return "Bullish Engulfing"
        if c[i - 2] < o[i - 2] and (o[i - 2] - c[i - 2]) / rg2 >= 0.5 and bd1 / rg1 <= 0.3 and c[i] > o[i] and c[i] > (o[i - 2] + c[i - 2]) / 2:
            return "Morning Star"
    else:
        if uw >= 0.55 and bd / rg <= 0.35 and lw <= 0.25:
            return "Shooting Star / Pin Bar (ekor atas panjang)"
        if c[i] < o[i] and c[i - 1] > o[i - 1] and c[i] <= o[i - 1] and o[i] >= c[i - 1] and bd > bd1:
            return "Bearish Engulfing"
        if c[i - 2] > o[i - 2] and (c[i - 2] - o[i - 2]) / rg2 >= 0.5 and bd1 / rg1 <= 0.3 and c[i] < o[i] and c[i] < (o[i - 2] + c[i - 2]) / 2:
            return "Evening Star"
    return ""


def baris_pola(k, arah, nama):
    """Baris kartu untuk pola candle di candle sinyal. Kosong kalau tidak ada pola."""
    if not nama:
        return ""
    if (k, arah) in POLA_TERUJI:
        return f"🕯 <b>Pola candle penguat: {nama}</b>. Uji teknik ini dengan pola searah: {POLA_TERUJI[(k, arah)]}"
    if (k, arah) in POLA_JELEK:
        return f"🕯 Pola candle: {nama}. Di teknik ini pola searah justru lebih jelek ({POLA_JELEK[(k, arah)]}), jangan dianggap penguat"
    return f"🕯 Pola candle: {nama} (info, di teknik ini tidak terbukti menambah hasil)"


# ---------- v174 QC 72: TANDA LAWAN (struktur berubah melawan sinyal) ----------
# Uji riset/upgrade/run_v174_rusak.py, 30 ribu sinyal 2023-2026, aturan keluar live:
#  MASUK TELAT di candle berikutnya. Tanpa tanda lawan -0.003 / +0.173 / +0.021 / -0.002R. Dengan pola candle lawan -0.057 / +0.140 /
#   +0.150 / -0.056R. Pola lawan DAN kejenuhan >= 50: -0.144 / +0.070 / +0.089 / -0.220R. Kejenuhan lawan saja (>= 75) JUSTRU lebih baik
#   (+0.105 / +0.113 / +0.255 / +0.116R), jadi kejenuhan sendirian TIDAK membatalkan sinyal.
#  POSISI JALAN, untung, belum TP awal. Pola lawan: TAHAN +0.120 / +0.272 / +0.345 / +0.073R lawan TUTUP +0.030 / +0.046 / +0.038 /
#   +0.032R. Pola lawan DAN kejenuhan >= 50: TAHAN +0.162 / -0.050 / +0.211 / -0.133R lawan TUTUP +0.035 / +0.048 / +0.041 / +0.047R.
# Jadi: sinyal yang belum diambil DIBATALKAN bila ada pola candle lawan atau CHoCH / MSB lawan. Posisi jalan diberi kabar DARURAT hanya
# bila pola lawan muncul bersama kejenuhan >= 50 atau bersama CHoCH / MSB lawan (satu-satunya kondisi di mana menahan tidak jelas unggul).
_TL_CACHE = {}


def tanda_lawan(sym, arah, df=None):
    """Tanda struktur berubah melawan `arah` di candle 4J terakhir yang sudah tutup. Return dict atau None kalau data tidak ada.
    dict: pola (nama pola candle lawan), choch (bool CHoCH / MSB lawan di 2 candle terakhir), jenuh (skor 0-100 sisi lawan), status,
    nyala (komponen jenuh yang menyala), batal (bool), darurat (bool), alasan (teks)."""
    import numpy as np
    try:
        if df is None:
            import qse_strat as ST
            df = ST._k4(sym, 300)
        if df is None or len(df) < 120:
            return None
        kunci = (sym, arah, int(df.index[-1]))
        if kunci in _TL_CACHE:
            return _TL_CACHE[kunci]
        o, h, l, c, v = (df[x].values.astype(float) for x in ("open", "high", "low", "close", "volume"))
        lawan = "SHORT" if arah == "LONG" else "LONG"
        pl = pola_sinyal(o, h, l, c, lawan)
        n = len(c); dl = 1 if lawan == "LONG" else -1
        ch = False
        try:
            import qse_smccore as K
            ch = any(z[0] >= n - 2 and z[1] == dl and z[5].get("tag") == "choch" for z in K.smc(o, h, l, c, 5, 50)) or \
                any(z[0] >= n - 2 and z[1] == dl for z in K.msb(o, h, l, c, v, 7, 0.5, K.volpct(v)))
        except Exception as ex:
            print("[WARN] tanda lawan struktur", sym, ex)
        import qse_ta as TA
        kj = TA.kejenuhan(o, h, l, c, v)
        skor = kj["os"] if arah == "SHORT" else kj["ob"]
        nyala = kj["nyala_os"] if arah == "SHORT" else kj["nyala_ob"]
        sebab = [x for x in (pl, "CHoCH / MSB lawan" if ch else "", f"kejenuhan {skor:.0f}% ({', '.join(nyala[:4])})" if skor >= 50 else "") if x]
        out = dict(pola=pl, choch=bool(ch), jenuh=float(skor), status=kj["status"], nyala=nyala, batal=bool(pl or ch),
                   darurat=bool(pl and (skor >= 50 or ch)), alasan=" + ".join(sebab))
        if len(_TL_CACHE) > 2000:
            _TL_CACHE.clear()
        _TL_CACHE[kunci] = out
        return out
    except Exception as ex:
        print("[WARN] tanda lawan", sym, ex)
        return None
