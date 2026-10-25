"""QSE v148 - PERLINDUNGAN MODAL & MAKSIMALISASI HASIL TRANSAKSI (PILAR 5).
Menggabungkan 4 kemampuan perlindungan modal dan pengawalan keuntungan:
  1. Batas Rugi Berbasis Volatilitas (Volatility-based SL dengan ATR dinamis + penyangga struktur)
  2. Pemotong Risiko Cepat saat Struktur Pasar Rusak (Fast Risk Cutter saat MSB/CHoCH/ayunan pivot berlawanan menembus struktur)
  3. Pengunci Keuntungan Bertahap (Stepped Profit Lock di +1R -> kunci BE/+0.25R, +2R -> kunci +1.2R, +3R -> kunci +2.2R)
  4. Target Berjalan Mengikuti Garis EMA (EMA Dynamic Trailing Target: mengawal posisi mengikuti EMA 20 / EMA 50)
  5. Pengamanan Keuntungan Instan saat Indikator Momentum Menunjukkan Tanda Pelemahan Tenaga.
"""
import numpy as np
import pandas as pd
import qse_rantai as RN
import qse_smccore as K


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().values


def hitung_sl_volatilitas(entry, arah, atr, sl_zona=None, sl_atr_mult=1.5):
    """1. Batas rugi berbasis volatilitas (ATR) yang digabungkan dengan batas struktur zona (bila ada)."""
    L = arah in ("LONG", 1)
    jarak_vol = max(sl_atr_mult * atr, 1e-9)
    sl_vol = (entry - jarak_vol) if L else (entry + jarak_vol)
    if sl_zona is not None and sl_zona > 0:
        # Gunakan pengaman yang mengawinkan zona struktur dan volatilitas ATR (dibatasi maks 2.5 ATR agar risiko terkendali)
        if L:
            sl_gab = min(sl_vol, float(sl_zona))
            sl_gab = max(sl_gab, entry - 2.5 * atr)
        else:
            sl_gab = max(sl_vol, float(sl_zona))
            sl_gab = min(sl_gab, entry + 2.5 * atr)
        return float(sl_gab)
    return float(sl_vol)


def cek_struktur_rusak(df_slice, arah, entry, sl_awal):
    """2. Pemotong risiko cepat saat struktur pasar rusak (Fast Risk Cutter).
    Mendeteksi apakah pada lilin penutupan terbaru terjadi patahan struktur pasar (CHoCH / MSB berlawanan
    atau penutupan menembus pivot low/high 5 lilin disertai aliran balik) sebelum SL tersentuh penuh.
    Return (rusak: bool, alasan: str).
    """
    if df_slice is None or len(df_slice) < 30:
        return False, ""
    o, h, l, c, v = (df_slice[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    L = arah in ("LONG", 1)
    px = float(c[-1])

    # Pemotong risiko cepat bekerja saat posisi sedang tertekan (di bawah entry untuk LONG / di atas entry untuk SHORT)
    # atau struktur patah keras menembus swing pivot terakhir
    sedang_rugi = (px < entry) if L else (px > entry)
    if not sedang_rugi:
        return False, ""

    # Cek 1: SMC CHoCH / BOS berlawanan di candle terakhir
    try:
        ev_smc = K.smc(o[-80:], h[-80:], l[-80:], c[-80:], size=5, swing=20)
        if ev_smc:
            idx_last, ar_smc, _, _, _, ex = ev_smc[-1]
            if idx_last == len(c[-80:]) - 1 and ((L and ar_smc == -1) or ((not L) and ar_smc == 1)):
                return True, f"pemotong risiko cepat: struktur pasar SMC {ex.get('tag', 'CHoCH').upper()} patah berlawanan arah"
    except Exception:
        pass

    # Cek 2: Harga tutup menembus pivot support/resistance 6 candle terakhir + EMA 20 & EMA 50 berbalik melawan
    e20 = _ema(c, 20)[-1]
    e50 = _ema(c, 50)[-1]
    if L:
        piv_low = float(l[-7:-1].min())
        if px < piv_low and px < e20 < e50 and c[-1] < o[-1] and c[-2] < o[-2]:
            return True, f"pemotong risiko cepat: struktur support {piv_low:.4g} jebol disertai 2 lilin merah & EMA 20/50 berbalik turun"
    else:
        piv_high = float(h[-7:-1].max())
        if px > piv_high and px > e20 > e50 and c[-1] > o[-1] and c[-2] > o[-2]:
            return True, f"pemotong risiko cepat: struktur resistance {piv_high:.4g} jebol disertai 2 lilin hijau & EMA 20/50 berbalik naik"

    return False, ""


def hitung_pengunci_dan_target_ema(it, df_slice):
    """3 & 4 & 5. Pengunci keuntungan bertahap + Target berjalan mengikuti garis EMA + Pengamanan saat momentum melemah.
    Mengembalikan dict(sl_baru, target_ema, tahap_kunci, amankan_momentum, alasan_momentum).
    """
    L = it["arah"] == "LONG"
    e = float(it["entry"])
    risk = float(it.get("risk") or abs(e - it.get("sl0", it["sl"])) or 1e-9)
    sl_sekarang = float(it["sl"])
    best = float(it.get("best", e))

    c = df_slice["close"].values.astype(float)
    h = df_slice["high"].values.astype(float)
    l = df_slice["low"].values.astype(float)
    a_arr = _atr(h, l, c, 14)
    at = float(a_arr[-1]) if not np.isnan(a_arr[-1]) and a_arr[-1] > 0 else risk / 1.5

    e20 = float(_ema(c, 20)[-1])
    e50 = float(_ema(c, 50)[-1])
    px = float(c[-1])

    # Hitung R tertinggi yang sudah dicapai (best_r) dan R berjalan sekarang (now_r)
    best_r = ((best - e) if L else (e - best)) / risk
    now_r = ((px - e) if L else (e - px)) / risk

    sl_baru = sl_sekarang
    tahap_kunci = it.get("tahap_kunci", "")

    # A. Pengunci Keuntungan Bertahap (Stepped Profit Lock)
    if best_r >= 3.0:
        kunci_lv = (e + 2.0 * risk) if L else (e - 2.0 * risk)
        sl_baru = max(sl_baru, kunci_lv) if L else min(sl_baru, kunci_lv)
        tahap_kunci = "KUNCI +2.0R (untung mencapai >=3R)"
    elif best_r >= 2.0:
        kunci_lv = (e + 1.1 * risk) if L else (e - 1.1 * risk)
        sl_baru = max(sl_baru, kunci_lv) if L else min(sl_baru, kunci_lv)
        tahap_kunci = "KUNCI +1.1R (untung mencapai >=2R)"
    elif best_r >= 1.0:
        kunci_lv = (e + 0.20 * risk) if L else (e - 0.20 * risk)
        sl_baru = max(sl_baru, kunci_lv) if L else min(sl_baru, kunci_lv)
        tahap_kunci = "KUNCI IMPAS+ (+0.20R setelah >=1R)"

    # B. Target Berjalan Mengikuti Garis EMA (EMA Dynamic Trailing)
    # Saat harga sudah bergerak searah >= 1.2R, garis EMA 20 (dikurangi buffer tipis 0.25 ATR) mengawal posisi sebagai trailing target/stop dinamis
    ema_trail = (e20 - 0.25 * at) if L else (e20 + 0.25 * at)
    if best_r >= 1.2:
        if L and ema_trail > e and ema_trail < px:
            if ema_trail > sl_baru:
                sl_baru = float(ema_trail)
                tahap_kunci = f"PENGAWAL GARIS EMA 20 ({e20:.4g})"
        elif (not L) and ema_trail < e and ema_trail > px:
            if ema_trail < sl_baru:
                sl_baru = float(ema_trail)
                tahap_kunci = f"PENGAWAL GARIS EMA 20 ({e20:.4g})"

    # Target berjalan EMA di depan harga (proyeksi target dinamis mengikuti kemiringan EMA 20)
    e20_series = _ema(c, 20)
    slope_ema = float(e20_series[-1] - e20_series[-4]) if len(e20_series) >= 4 else 0.0
    target_ema_berjalan = float(px + max(2.0 * at, 3.0 * abs(slope_ema))) if L else float(px - max(2.0 * at, 3.0 * abs(slope_ema)))

    # C. Pengamanan Keuntungan Instan saat Indikator Momentum Melemah
    amankan_mom = False
    alasan_mom = ""
    if now_r >= 0.8:
        melemah, why_m, _ = RN.cek_pelemahan_momentum(df_slice, it["arah"])
        if melemah:
            amankan_mom = True
            alasan_mom = why_m
            # Kencangkan SL tepat ke bawah/atas lilin terakhir atau kunci 80% keuntungan berjalan
            sl_ketat = (px - 0.25 * at) if L else (px + 0.25 * at)
            sl_baru = max(sl_baru, sl_ketat) if L else min(sl_baru, sl_ketat)

    return dict(
        sl_baru=float(sl_baru),
        ema20=e20,
        ema50=e50,
        target_ema=target_ema_berjalan,
        tahap_kunci=tahap_kunci,
        amankan_momentum=amankan_mom,
        alasan_momentum=alasan_mom,
        now_r=now_r,
        best_r=best_r,
    )


def kelola_posisi_pilar5(it, df, biaya=0.0015, maks_bar=60):
    """Fungsi pengelola posisi terpadu (Pilar 5) untuk seluruh strategi:
    - Mengecek batas rugi berbasis volatilitas & trailing SL.
    - Mengecek pemotong risiko cepat saat struktur pasar rusak.
    - Mengaktifkan pengunci keuntungan bertahap & pengawal target garis EMA.
    - Mengamankan keuntungan saat indikator momentum menunjukkan tanda pelemahan tenaga.
    Return (status, R_atau_None, sl_lama, info_aksi).
    """
    L = it["arah"] == "LONG"
    e, risk = float(it["entry"]), float(it["risk"])
    h_all = df["high"].values.astype(float)
    l_all = df["low"].values.astype(float)
    c_all = df["close"].values.astype(float)
    a_all = _atr(h_all, l_all, c_all, 14)
    sl_lama = float(it["sl"])
    info_aksi = ""

    for k, ts in enumerate(df.index):
        if ts <= it["last"]:
            continue
        hi, lo, cl = float(h_all[k]), float(l_all[k]), float(c_all[k])
        at = float(a_all[k]) if not np.isnan(a_all[k]) and a_all[k] > 0 else risk / 1.5

        # 1. Cek apakah SL (batas rugi volatilitas / pengunci profit / pengawal EMA) tersentuh
        if (lo <= it["sl"]) if L else (hi >= it["sl"]):
            r_out = ((it["sl"] - e) if L else (e - it["sl"])) / risk - biaya * e / risk
            st_lbl = "TP_EMA" if r_out > 0.15 and it.get("tahap_kunci") else "SL"
            return st_lbl, r_out, sl_lama, it.get("tahap_kunci", "")

        # 2. Cek TP tetap bila strategi memiliki target puncak tetap dan belum dialihkan penuh ke pengawal EMA
        if it.get("tp") and it["bar"] > 0 and ((hi >= it["tp"]) if L else (lo <= it["tp"])):
            return "TP", abs(it["tp"] - e) / risk - biaya * e / risk, sl_lama, "Target TP Tercapai"

        # Update harga terbaik (best excursion)
        if L:
            it["best"] = max(float(it.get("best", e)), hi)
        else:
            it["best"] = min(float(it.get("best", e)), lo)

        # 3. Jalankan evaluasi Pilar 5 pada irisan data kausal sampai candle k
        df_slice = df.iloc[:k + 1]

        # 3a. Pemotong Risiko Cepat saat Struktur Pasar Rusak (ketika sedang rugi)
        rusak, alasan_rusak = cek_struktur_rusak(df_slice, it["arah"], e, it.get("sl0", it["sl"]))
        if rusak and it["bar"] >= 1:
            r_cut = ((cl - e) if L else (e - cl)) / risk - biaya * e / risk
            it["close"] = cl
            it["last"] = int(ts)
            return "CUT_STRUKTUR", r_cut, sl_lama, alasan_rusak

        # 3b. Pengunci Keuntungan Bertahap + Target Berjalan Garis EMA + Deteksi Pelemahan Momentum
        p5 = hitung_pengunci_dan_target_ema(it, df_slice)
        if p5["amankan_momentum"] and p5["now_r"] >= 0.85:
            # Segera amankan keuntungan saat indikator momentum menunjukkan tanda pelemahan tenaga
            r_mom = p5["now_r"] - biaya * e / risk
            it["close"] = cl
            it["last"] = int(ts)
            it["sl"] = p5["sl_baru"]
            return "TP_MOMENTUM", r_mom, sl_lama, p5["alasan_momentum"]

        # Geser SL mengikuti gabungan Trailing ATR + Pengunci Bertahap + Garis EMA 20
        trail_atr = float(it.get("trail_atr", 3.0))
        if L:
            sl_atr_trail = it["best"] - trail_atr * at
            it["sl"] = max(float(it["sl"]), sl_atr_trail, p5["sl_baru"])
        else:
            sl_atr_trail = it["best"] + trail_atr * at
            it["sl"] = min(float(it["sl"]), sl_atr_trail, p5["sl_baru"])

        tp2 = it.get("trail_pct_2r")
        if tp2 and abs(it["best"] - e) >= 2 * risk:
            it["sl"] = max(it["sl"], it["best"] - tp2 * e) if L else min(it["sl"], it["best"] + tp2 * e)

        if p5["tahap_kunci"]:
            it["tahap_kunci"] = p5["tahap_kunci"]
            info_aksi = p5["tahap_kunci"]
        it["ema_kawal"] = p5["ema20"]
        it["target_ema"] = p5["target_ema"]

        it["bar"] += 1
        it["last"] = int(ts)
        it["close"] = cl
        if it["bar"] >= it.get("maks_bar", maks_bar):
            return "WAKTU", ((cl - e) if L else (e - cl)) / risk - biaya * e / risk, sl_lama, "Batas waktu tercapai"

    return "BUKA", None, sl_lama, info_aksi
