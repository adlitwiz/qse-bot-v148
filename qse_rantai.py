"""QSE v148 - RANTAI KONFIRMASI EKSEKusi AGRESIF (PILAR 3).
Merakit 5 indikator menjadi satu rantai konfirmasi pemicu eksekusi yang agresif:
  1. Indikator Ichimoku (Tenkan, Kijun, dan posisi Awan Senkou Span A/B)
  2. Garis Dinamis McGinley (McGinley Dynamic 34 untuk kemiringan dan pijakan tren dinamis)
  3. Bollinger Bands (SMA 20 ± 2 SD & Bandwidth Squeeze/Expansion untuk ledakan volatilitas)
  4. Pola Lilin / Candlestick (Engulfing, Hammer/Pinbar, Marubozu, atau lilin dorongan penuh pada penutupan)
  5. Pengukur Momentum (RSI 14, MACD Histogram, Rate of Change, dan Volume Persentil)

Aturan keras Pilar 3:
- Menghentikan cara kerja indikator yang memberi sinyal secara terpisah (standalone).
- Memaksa seluruh indikator tersebut bekerja sebagai SATU RANTAI KONFIRMASI yang menyatukan:
    [Tahap 1: Arah Tren] (Ichimoku + McGinley Dynamic + EMA 200 searah)
  + [Tahap 2: Ledakan Volatilitas] (Bollinger Bands ekspansi/tembus atau pelepasan squeeze + lonjakan volume)
  + [Tahap 3: Dorongan Tenaga Harga pada Penutupan Lilin] (Pola lilin konfirmasi + momentum RSI/MACD menguat di close).
"""
import numpy as np
import pandas as pd
import qse_pola as PL


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return _rma(tr, n)


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = _rma(np.maximum(d, 0), n), _rma(np.maximum(-d, 0), n)
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))


def _mcginley(c, n=34, k=0.6):
    md = np.empty(len(c))
    md[0] = c[0]
    for i in range(1, len(c)):
        md[i] = md[i - 1] + (c[i] - md[i - 1]) / max(k * n * (c[i] / max(md[i - 1], 1e-12)) ** 4, 1.0)
    return md


def _ichimoku_komponen(h, l, c):
    s_h, s_l = pd.Series(h), pd.Series(l)
    tk = (s_h.rolling(9).max().values + s_l.rolling(9).min().values) / 2
    kj = (s_h.rolling(26).max().values + s_l.rolling(26).min().values) / 2
    sa = np.r_[np.full(26, np.nan), ((tk + kj) / 2)[:-26]]
    sb52 = (s_h.rolling(52).max().values + s_l.rolling(52).min().values) / 2
    sb = np.r_[np.full(26, np.nan), sb52[:-26]]
    return tk, kj, sa, sb


def _bollinger_komponen(c, n=20, mult=2.0):
    s = pd.Series(c)
    mid = s.rolling(n).mean().values
    sd = s.rolling(n).std(ddof=0).values
    up = mid + mult * sd
    lo = mid - mult * sd
    bw = (up - lo) / np.maximum(mid, 1e-12)
    return mid, up, lo, bw


def evaluasi_rantai(df, arah_target=None):
    """Evaluasi rantai konfirmasi 5 indikator pada lilin penutupan terakhir (index -1).
    Return dict lengkap jika rantai konfirmasi terpenuhi, atau dict(aktif=False, ...) jika terputus.
    """
    if df is None or len(df) < 220:
        return dict(aktif=False, alasan_putus="data candle kurang dari 220 bar")

    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    i = len(c) - 1
    a_arr = _atr(h, l, c, 14)
    at = float(a_arr[i]) if not np.isnan(a_arr[i]) and a_arr[i] > 0 else float(abs(h[i] - l[i]) or 1e-6)

    # 1. Hitung komponen Ichimoku & McGinley Dynamic & EMA 200 (ARAH TREN)
    tk, kj, sa, sb = _ichimoku_komponen(h, l, c)
    md = _mcginley(c[-min(len(c), 600):])
    md_now, md_prev = float(md[-1]), float(md[-2])
    e200 = float(_ema(c, 200)[i])
    cloud_top = float(max(sa[i], sb[i])) if not (np.isnan(sa[i]) or np.isnan(sb[i])) else e200
    cloud_bot = float(min(sa[i], sb[i])) if not (np.isnan(sa[i]) or np.isnan(sb[i])) else e200

    # 2. Hitung komponen Bollinger Bands & Volume (LEDAKAN VOLATILITAS)
    bb_mid, bb_up, bb_lo, bw = _bollinger_komponen(c, 20, 2.0)
    bw_now = float(bw[i])
    bw_prev = float(bw[i - 1])
    bw_pct = float((bw[max(0, i - 100):i] <= bw_now).mean() * 100) if i >= 30 else 50.0
    vp = float((v[max(0, i - 100):i] <= v[i]).mean() * 100)
    rng_candle = float(h[i] - l[i])

    # 3. Hitung komponen Pola Lilin & Momentum pada Penutupan (DORONGAN TENAGA HARGA)
    rsi = _rsi(c, 14)
    rsi_now, rsi_prev = float(rsi[i]), float(rsi[i - 1])
    macd_line = _ema(c, 12) - _ema(c, 26)
    macd_hist = macd_line - _ema(macd_line, 9)
    hist_now, hist_prev = float(macd_hist[i]), float(macd_hist[i - 1])
    pola_lilin = PL.pola_candle(o, h, l, c, i)

    kandidat_arah = [1, -1] if arah_target is None else ([1] if arah_target in ("LONG", 1) else [-1])

    for d in kandidat_arah:
        L = d == 1
        ar_str = "LONG" if L else "SHORT"
        detail_rantai = []

        # --- TAHAP 1: KESATUAN ARAH TREN (Ichimoku + McGinley Dynamic + EMA 200) ---
        tren_ema200 = (c[i] > e200) if L else (c[i] < e200)
        ichi_searah = ((c[i] > cloud_top or (tk[i] >= kj[i] and c[i] >= kj[i])) if L
                       else (c[i] < cloud_bot or (tk[i] <= kj[i] and c[i] <= kj[i])))
        mcg_searah = (c[i] > md_now and md_now >= md_prev * 0.999) if L else (c[i] < md_now and md_now <= md_prev * 1.001)

        if not (tren_ema200 and ichi_searah and mcg_searah):
            continue
        detail_rantai.append(
            f"Arah Tren Terkunci ({'di atas' if L else 'di bawah'} Awan Ichimoku/Kijun + menembus garis dinamis McGinley {md_now:.4g} + searah EMA 200)"
        )

        # --- TAHAP 2: LEDAKAN VOLATILITAS (Bollinger Bands + Ekspansi Rentang/Volume) ---
        bb_searah = (c[i] > bb_mid[i]) if L else (c[i] < bb_mid[i])
        bb_ekspansi = (
            bw_now > bw_prev * 1.02
            or (L and c[i] >= bb_up[i] * 0.995)
            or ((not L) and c[i] <= bb_lo[i] * 1.005)
            or rng_candle >= 1.15 * at
            or vp >= 70.0
        )
        if not (bb_searah and bb_ekspansi):
            continue
        detail_rantai.append(
            f"Ledakan Volatilitas Bollinger (harga {'di atas' if L else 'di bawah'} BB Mid, bandwidth ekspansi {bw_now * 100:.1f}%, persentil volume {vp:.0f}%)"
        )

        # --- TAHAP 3: DORONGAN TENAGA HARGA PADA PENUTUPAN LILIN (Pola Lilin + Momentum) ---
        body = (c[i] - o[i]) * d
        close_pos = ((c[i] - l[i]) / max(rng_candle, 1e-12)) if L else ((h[i] - c[i]) / max(rng_candle, 1e-12))
        lilin_kuat = (
            body > 0 and (
                close_pos >= 0.60
                or body >= 0.55 * rng_candle
                or (pola_lilin and any(k in pola_lilin for k in (("Bullish", "Hammer", "hijau") if L else ("Bearish", "Shooting", "merah"))))
            )
        )
        mom_kuat = (
            ((rsi_now > 50 and rsi_now >= rsi_prev - 1.0) if L else (rsi_now < 50 and rsi_now <= rsi_prev + 1.0))
            and ((hist_now > 0 or hist_now > hist_prev) if L else (hist_now < 0 or hist_now < hist_prev))
        )
        if not (lilin_kuat and mom_kuat):
            continue
        nama_lilin = pola_lilin or (f"Lilin dorongan {'hijau' if L else 'merah'} tutup di {close_pos * 100:.0f}% rentang")
        detail_rantai.append(
            f"Dorongan Tenaga Penutupan Lilin ({nama_lilin}, RSI {rsi_now:.0f}, MACD Histogram {'menguat' if L else 'menekan'})"
        )

        # Hitung apakah sinyal ini baru saja memicu ledakan di 1-2 candle terakhir (fresh trigger)
        baru_memicu = bool(
            (c[i - 1] <= md_prev if L else c[i - 1] >= md_prev)
            or (tk[i - 1] <= kj[i - 1] if L else tk[i - 1] >= kj[i - 1])
            or (rsi_prev <= 52 if L else rsi_prev >= 48)
            or (bw_now > bw_prev * 1.08)
            or vp >= 80.0
        )

        skor_rantai = int(min(100, 65 + (10 if vp >= 80 else 0) + (10 if pola_lilin else 0) + (10 if abs(rsi_now - 50) >= 8 else 0) + (5 if baru_memicu else 0)))

        return dict(
            aktif=True,
            baru_memicu=baru_memicu,
            arah=ar_str,
            arah_num=d,
            atr=at,
            close=float(c[i]),
            mcginley=md_now,
            tenkan=float(tk[i]),
            kijun=float(kj[i]),
            bb_mid=float(bb_mid[i]),
            bb_up=float(bb_up[i]),
            bb_lo=float(bb_lo[i]),
            rsi=rsi_now,
            macd_hist=hist_now,
            vp=vp,
            pola_lilin=nama_lilin,
            skor_rantai=skor_rantai,
            rantai_konfirmasi=detail_rantai,
        )

    return dict(aktif=False, alasan_putus="rantai konfirmasi 5 indikator belum menyatu penuh pada penutupan lilin")


def cek_pelemahan_momentum(df, arah):
    """PILAR 5: Deteksi tanda pelemahan tenaga pada indikator momentum & garis EMA untuk segera mengamankan keuntungan.
    Tanda pelemahan tenaga:
      1. RSI membalik tajam dari area jenuh (>70 turun untuk LONG, <30 naik untuk SHORT) atau patah di bawah/atas 50.
      2. Histogram MACD menyusut 2 lilin berturut-turut disertai penutupan lilin melawan garis dinamis McGinley / EMA 20.
    Return (melemah: bool, alasan: str, level_ema_pengawal: float).
    """
    if df is None or len(df) < 35:
        return False, "", 0.0
    o, h, l, c = (df[k].values.astype(float) for k in ("open", "high", "low", "close"))
    L = arah in ("LONG", 1)
    e20 = _ema(c, 20)
    rsi = _rsi(c, 14)
    macd_line = _ema(c, 12) - _ema(c, 26)
    hist = macd_line - _ema(macd_line, 9)
    ema_kawal = float(e20[-1])

    # 1. Pelemahan dari puncak ekstrem RSI + lilin berbalik warna
    if L and rsi[-2] >= 68 and rsi[-1] < rsi[-2] - 4.0 and c[-1] < o[-1]:
        return True, f"momentum RSI melemah tajam dari puncak ({rsi[-2]:.0f} -> {rsi[-1]:.0f}) disertai lilin merah", ema_kawal
    if (not L) and rsi[-2] <= 32 and rsi[-1] > rsi[-2] + 4.0 and c[-1] > o[-1]:
        return True, f"momentum RSI melemah tajam dari lembah ({rsi[-2]:.0f} -> {rsi[-1]:.0f}) disertai lilin hijau", ema_kawal

    # 2. Histogram MACD menyusut 2 bar berturut-turut dan harga menembus balik EMA 20
    if L and hist[-1] < hist[-2] < hist[-3] and c[-1] < e20[-1]:
        return True, f"tenaga histogram MACD melemah 2 lilin beruntun & harga tutup di bawah EMA 20 ({ema_kawal:.4g})", ema_kawal
    if (not L) and hist[-1] > hist[-2] > hist[-3] and c[-1] > e20[-1]:
        return True, f"tenaga histogram MACD melemah 2 lilin beruntun & harga tutup di atas EMA 20 ({ema_kawal:.4g})", ema_kawal

    return False, "", ema_kawal
