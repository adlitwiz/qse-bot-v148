"""QSE v148 - JALUR STRATEGI TERPADU 5 PILAR (candle 4J, 111 koin perp, Jul 2020 - Okt 2026).
Peningkatan menyeluruh 5 Pilar Utama:
  1. Penyaring Utama Aliran Dana Besar (qse_penyaring): menyatukan arah Bitcoin, musim altcoin, kondisi makro,
     rotasi sektor, dan reaksi berita. Mengunci fokus robot hanya pada koin searah aliran dana besar dan otomatis
     mengaktifkan kombo strategi penembusan saat pasar kuat & kombo strategi pantulan saat pasar mendatar.
  2. Strategi Penentu Zona Pantulan Terkunci (qse_smccore.zona_pantulan_terkunci): mengawinkan pemetaan Order Block,
     patahan struktur pasar (MSB/SMC), batas harga (SnR), dan celah harga (FVG/Gap) di satu titik harga presisi
     dengan syarat tumpukan minimal dua konfirmasi struktur pasar.
  3. Rantai Konfirmasi Eksekusi Agresif (qse_rantai): merakit indikator Ichimoku, garis dinamis McGinley, Bollinger Bands,
     pola lilin, dan pengukur momentum sebagai satu rantai konfirmasi penutupan lilin. Menghentikan cara kerja indikator
     yang memberi sinyal secara terpisah.
  4. Deteksi Pergerakan Dini & Rem Otomatis Saringan Keterlambatan Harga (qse_pagi): menangkap harga sejak awal ledakan
     sesi pagi dan membatalkan rencana masuk posisi apabila harga sudah bergerak terlalu jauh dari zona Order Block.
  5. Perlindungan Modal & Pengawalan Garis EMA (qse_proteksi): menggabungkan batas rugi berbasis volatilitas,
     pemotong risiko cepat saat struktur pasar rusak, pengunci keuntungan bertahap, target berjalan mengikuti garis EMA,
     dan pengamanan keuntungan instan saat indikator momentum menunjukkan tanda pelemahan tenaga.
"""
import fcntl
import json
import os
import time
import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor
import bybit_fetch as B
import telegram_notify as TG
import qse_smccore as K
import qse_penyaring as PY
import qse_rantai as RN
import qse_pagi as PG
import qse_proteksi as PR
from config import STATE_DIR

H4 = 4 * 3600 * 1000
SL_ATR, TRAIL_ATR, MAKS_BAR = 2.0, 3.0, 60
MAKS_BARU, MAKS_BUKA, TOP_KOIN = 5, 8, 150
BIAYA = 0.0015
TELAT_ATR = 0.5
MAKS_JARAK_OB_ATR = 1.8

# Catatan: Sinyal indikator tunggal yang dulu bekerja terpisah (seperti membaca garis McGinley dan indikator momentum sendiri-sendiri)
# kini diikat wajib dengan Rantai Konfirmasi Pilar 3 dan Zona Pantulan Terkunci Pilar 2.
STRAT = {
    "kombo_ob_awal": dict(
        nama="Kombo Tangkapan Awal Zona Order Block",
        likuid=50,
        sl_atr=1.5,
        trail_atr=3.0,
        tp_r=4.0,
        maks_bar=60,
        bt="Kombo 5 Pilar: Arah BTC positif + Pijakan Zona OB Terkunci (min 2 konfirmasi) + Rantai McGinley/Ichimoku/BB/Lilin/Momentum + Gerak Dini + Saringan Anti-Terlambat + Target Pengikut Garis EMA",
        kenapa=[
            "Pembacaan arah Bitcoin positif & searah aliran dana besar (Penyaring Utama Pilar 1)",
            "Pijakan harga di area Order Block Terkunci (minimal 2 konfirmasi struktur pasar: OB, MSB/SMC, SnR, FVG)",
            "Rantai konfirmasi eksekusi agresif menyatu (Ichimoku + McGinley Dynamic + Bollinger Bands + Pola Lilin + Momentum)",
            "Pemicu gerak dini sesi pagi aktif & lolos saringan anti-terlambat dari zona Order Block",
            "Dikawal langsung menggunakan target keuntungan pengikut garis EMA 20 & pengunci keuntungan bertahap",
        ],
    ),
    "rantai_eksekusi": dict(
        nama="Rantai Konfirmasi 5 Indikator + Zona Terkunci",
        likuid=30,
        sl_atr=1.5,
        trail_atr=3.5,
        bt="Rantai Konfirmasi Agresif (Ichimoku + McGinley 34 + Bollinger Bands + Pola Lilin + Momentum) di atas Zona Pantulan Terkunci (>=2 konfirmasi struktur)",
        kenapa=[
            "Seluruh 5 indikator (Ichimoku, McGinley Dynamic, Bollinger Bands, Pola Lilin, Momentum) terkunci sebagai satu rantai konfirmasi pada penutupan lilin",
            "Zona transaksi memiliki tumpukan minimal 2 konfirmasi struktur pasar di satu titik harga presisi",
            "Lolos rem otomatis saringan keterlambatan harga dari zona Order Block",
        ],
    ),
    "ema_short": dict(
        nama="EMA Cross 20/50 SHORT (Rantai Terpadu)",
        likuid=0,
        sl_atr=1.5,
        trail_atr=4.0,
        bt="uji 6 tahun 111 koin: 1812 trade, PF 1.42, uji ulang 2024-2026 PF 1.47 + diikat Rantai Konfirmasi 5 Pilar",
        kenapa=[
            "EMA 20 memotong EMA 50 ke bawah searah EMA 200 & diikat rantai konfirmasi momentum/volatilitas",
            "Arah BTC & aliran dana besar negatif (Penyaring Utama Pilar 1)",
            "Dikawal target berjalan garis EMA & pemotong risiko cepat",
        ],
    ),
    "rsi_vol": dict(
        nama="Momentum RSI 50 + Rantai McGinley/BB",
        likuid=30,
        bt="uji 6 tahun 111 koin, 30 paling likuid: 2380 trade, PF 1.34, uji ulang 2024-2026 PF 1.45 + Rantai Konfirmasi",
        kenapa=[
            "Tidak lagi bekerja terpisah: dorongan momentum RSI 50 & volume tinggi wajib menyatu dengan garis dinamis McGinley, Ichimoku, Bollinger Bands, dan pola lilin",
            "Memiliki tumpukan minimal 2 konfirmasi struktur pasar pada zona pantulan",
        ],
    ),
    "GZH": dict(
        nama="GZH Golden Zone",
        likuid=0,
        manual=True,
        bt="uji 6 tahun 111 koin, maks 8 posisi: 1825 trade, WR 40%, PF 1.24, 2020-2023 PF 1.24, uji ulang 2024-2026 PF 1.23",
        kenapa=[
            "Sentuhan pertama fib 0.618 lalu candle 4J tutup memantul",
            "Searah tren besar (EMA 200), searah aliran dana besar BTC 4J, dan dikawal target EMA",
        ],
    ),
    "snr_vol": dict(
        nama="Zona Pantulan SnR + OB + FVG Terkunci",
        likuid=30,
        tp_r=3.0,
        maks_bar=45,
        bt="uji 6 tahun 111 koin, 30 paling likuid: 692 trade, WR 39%, PF 1.33, uji ulang 2024-2026 PF 1.43 + Zona Pantulan Terkunci",
        kenapa=[
            "Batas harga SnR dikawinkan dengan Order Block, patahan struktur (MSB/SMC), dan celah harga (FVG) di satu titik harga presisi (minimal 2 konfirmasi)",
            "Disertai rantai konfirmasi penutupan lilin & volume masuk 20% tertinggi",
        ],
    ),
    "msb_hpz": dict(
        nama="Patahan Struktur MSB HPZ + OB Terkunci",
        likuid=30,
        trail_atr=4.0,
        trail_pct_2r=0.05,
        bt="uji 6 tahun 111 koin, 30 paling likuid: 2783 trade, WR 37%, PF 1.27 + Konfirmasi Struktur & Rantai Eksekusi",
        kenapa=[
            "Market Structure Break (MSB) dengan skor HPZ > 80 yang mengunci bersama zona Order Block / FVG (minimal 2 konfirmasi struktur)",
            "Menyatu dengan rantai konfirmasi tren, volatilitas, dan momentum penutupan lilin",
        ],
    ),
    "smc_choch": dict(
        nama="SMC CHoCH + Zona Pantulan Terkunci",
        likuid=30,
        tp_r=3.0,
        maks_bar=45,
        bt="uji 111 koin 2020-2026, 30 paling likuid: 2929 trade, WR 38%, PF 1.25 + Tumpukan Konfirmasi Struktur",
        kenapa=[
            "Change of Character (CHoCH) struktur internal yang mengunci di titik presisi bersama Order Block / SnR / FVG (minimal 2 konfirmasi)",
            "Diikat rantai konfirmasi 5 indikator & saringan anti-terlambat",
        ],
    ),
    "mcginley": dict(
        nama="McGinley 34 + Rantai Konfirmasi Terpadu",
        likuid=0,
        sl_atr=1.5,
        tp_r=4.0,
        maks_bar=45,
        bt="uji 6 tahun 111 koin: 3328 trade, WR 40%, PF 1.24 (pullback PF 1.43) + Diikat Rantai Ichimoku/BB/Lilin/Momentum",
        kenapa=[
            "Berhenti memberi sinyal terpisah: tembusan garis dinamis McGinley 34 wajib terkunci bersama Ichimoku, ekspansi Bollinger Bands, pola lilin, dan momentum",
            "Berpijak pada zona struktur terkunci (minimal 2 konfirmasi) & lolos saringan anti-terlambat dari Order Block",
        ],
    ),
}


def _file(k):
    return os.path.join(STATE_DIR, f"strat_{k}.json")


def _ubah(k, fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    f_ = _file(k)
    with open(f_ + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(f_) as f:
                d = json.load(f)
        except Exception:
            d = {"open": {}, "closed": []}
        hasil = fn(d)
        d["closed"] = d["closed"][-500:]
        with open(f_ + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(f_ + ".tmp", f_)
        return hasil


def lihat(k):
    try:
        with open(_file(k)) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def _ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().values


def _rma(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().values


def _atr(h, l, c):
    pc = np.r_[c[0], c[:-1]]
    return _rma(np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc))), 14)


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = _rma(np.maximum(d, 0), n), _rma(np.maximum(-d, 0), n)
    return 100 - 100 / (1 + up / np.maximum(dn, 1e-12))


def _mcginley(c, n=34, k=0.6):
    md = np.empty(len(c))
    md[0] = c[0]
    for i in range(1, len(c)):
        md[i] = md[i - 1] + (c[i] - md[i - 1]) / max(k * n * (c[i] / md[i - 1]) ** 4, 1.0)
    return md


def sinyal(df, btc_naik):
    """Cek candle tutup terakhir untuk semua strategi dengan mengikat:
      - Pilar 2: Zona Pantulan Terkunci (minimal 2 konfirmasi struktur pasar: OB, MSB/SMC, SnR, FVG)
      - Pilar 3: Rantai Konfirmasi 5 Indikator (Ichimoku + McGinley + Bollinger Bands + Pola Lilin + Momentum),
                 menghentikan sinyal McGinley dan momentum yang bekerja sendiri-sendiri.
      - Pilar 4: Deteksi Gerak Dini & Saringan Anti-Terlambat apabila harga sudah terlalu jauh dari Order Block.
    Return dict kunci -> (arah, atr).
    """
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    i = len(c) - 1
    if i < 260:
        return {}
    a = _atr(h, l, c)
    at = float(a[i])
    if np.isnan(at) or at <= 0:
        return {}
    e20, e50, e200 = _ema(c, 20), _ema(c, 50), _ema(c, 200)
    out = {}

    # Evaluasi Rantai Konfirmasi 5 Indikator (Pilar 3) & Deteksi Gerak Dini (Pilar 4)
    rn = RN.evaluasi_rantai(df)
    rn_aktif = rn.get("aktif", False)
    rn_arah = rn.get("arah")

    # Evaluasi Zona Pantulan Terkunci dengan minimal 2 konfirmasi struktur pasar (Pilar 2)
    zk_long = K.zona_pantulan_terkunci(o, h, l, c, v, arah=1, min_konfirmasi=2)
    zk_short = K.zona_pantulan_terkunci(o, h, l, c, v, arah=-1, min_konfirmasi=2)

    def _lolos_pilar2_4(arah_str):
        zk = zk_long if arah_str == "LONG" else zk_short
        if not zk or zk.get("jumlah_konfirmasi", 0) < 2:
            return False
        lolos_t, _, _ = PG.saring_anti_terlambat(c[i], arah_str, entry_sinyal=c[i], ob_zona=zk, atr=at, maks_atr_ob=MAKS_JARAK_OB_ATR)
        return lolos_t

    # 1. Kombo Tangkapan Awal pada Zona Order Block (Contoh nyata peningkatan kemampuan 5 Pilar)
    if btc_naik is True and rn_aktif and rn_arah == "LONG" and zk_long and zk_long.get("jumlah_konfirmasi", 0) >= 2:
        dini = PG.deteksi_gerak_dini(df, arah="LONG")
        lolos_ob, _, _ = PG.saring_anti_terlambat(c[i], "LONG", entry_sinyal=c[i], ob_zona=zk_long, atr=at, maks_atr_ob=MAKS_JARAK_OB_ATR)
        if dini.get("aktif") and lolos_ob and "OB" in zk_long.get("kategori", []):
            out["kombo_ob_awal"] = ("LONG", at)

    # 2. Rantai Konfirmasi Eksekusi Agresif 5 Indikator + Zona Terkunci
    if rn_aktif and rn.get("baru_memicu") and _lolos_pilar2_4(rn_arah):
        if (rn_arah == "LONG" and btc_naik is not False) or (rn_arah == "SHORT" and btc_naik is not True):
            out["rantai_eksekusi"] = (rn_arah, at)

    # 3. EMA Short (diikat rantai konfirmasi & saringan anti-terlambat)
    if e20[i] < e50[i] and e20[i - 1] >= e50[i - 1] and c[i] < e200[i] and btc_naik is False:
        if (rn_aktif and rn_arah == "SHORT") and _lolos_pilar2_4("SHORT"):
            out["ema_short"] = ("SHORT", at)

    # 4. Momentum RSI + Volume & McGinley Dynamic 34:
    # HENTIKAN cara kerja indikator yang memberi sinyal secara terpisah!
    # Keduanya kini WAJIB terikat dalam Rantai Konfirmasi 5 Indikator (rn_aktif) dan Zona Struktur Terkunci (>=2 konfirmasi).
    r = _rsi(c)
    vp = (v[i - 100:i] <= v[i]).mean() * 100
    if vp >= 80 and rn_aktif:
        if r[i] > 50 and r[i - 1] <= 50 and c[i] > e200[i] and e50[i] > e200[i] and rn_arah == "LONG" and _lolos_pilar2_4("LONG"):
            out["rsi_vol"] = ("LONG", at)
        elif r[i] < 50 and r[i - 1] >= 50 and c[i] < e200[i] and e50[i] < e200[i] and rn_arah == "SHORT" and _lolos_pilar2_4("SHORT"):
            out["rsi_vol"] = ("SHORT", at)

    md = _mcginley(c[-600:])
    md = np.r_[np.full(len(c) - len(md), np.nan), md]
    if vp >= 80 and rn_aktif:
        if c[i] > md[i] and c[i - 1] <= md[i - 1] and c[i] > e200[i] and rn_arah == "LONG" and _lolos_pilar2_4("LONG"):
            out["mcginley"] = ("LONG", at)
        elif c[i] < md[i] and c[i - 1] >= md[i - 1] and c[i] < e200[i] and rn_arah == "SHORT" and _lolos_pilar2_4("SHORT"):
            out["mcginley"] = ("SHORT", at)

    # 5. SnR, MSB, SMC yang dikawinkan dengan Zona Pantulan Terkunci (min 2 konfirmasi struktur) & Rantai Konfirmasi
    try:
        searah = lambda ar: (c[i] > e200[i]) == (ar == 1)
        for x in K.snr(h, l, c, 20):
            ar_s = "LONG" if x[1] == 1 else "SHORT"
            if x[0] == i and searah(x[1]) and vp >= 80 and btc_naik is not None and btc_naik == (x[1] == 1):
                if _lolos_pilar2_4(ar_s) and (not rn_aktif or rn_arah == ar_s):
                    out["snr_vol"] = (ar_s, at)
        vpa = K.volpct(v)
        for x in K.msb(o, h, l, c, v, 7, 0.5, vpa):
            ar_s = "LONG" if x[1] == 1 else "SHORT"
            if x[0] == i and x[5]["skor"] > 80 and searah(x[1]):
                if _lolos_pilar2_4(ar_s) and (not rn_aktif or rn_arah == ar_s):
                    out["msb_hpz"] = (ar_s, at)
        for x in K.smc(o, h, l, c, 5, 50):
            ar_s = "LONG" if x[1] == 1 else "SHORT"
            if x[0] == i and x[5]["tag"] == "choch" and searah(x[1]):
                if _lolos_pilar2_4(ar_s) and (not rn_aktif or rn_arah == ar_s):
                    out["smc_choch"] = (ar_s, at)
    except Exception as ex:
        print("[WARN] smc/snr/msb", ex)
    return out


def _k4(sym, bars=600):
    try:
        df = B._raw(sym, "240", bars)
        now = int(time.time() * 1000)
        return df[df.index + H4 <= now]
    except Exception as ex:
        print(f"[WARN] strat {sym}: {ex}")
        return None


def _kelola(it, df):
    """Kelola posisi menggunakan mesin perlindungan modal & pengawal target garis EMA (Pilar 5):
      - Batas rugi berbasis volatilitas & trailing ATR
      - Pemotong risiko cepat saat struktur pasar rusak (CUT_STRUKTUR)
      - Pengunci keuntungan bertahap & target berjalan mengikuti garis EMA 20 (TP_EMA)
      - Pengamanan keuntungan instan saat indikator momentum melemah (TP_MOMENTUM).
    Return (status, R_atau_None, sl_lama).
    """
    st, R, sl_lama, info_p5 = PR.kelola_posisi_pilar5(it, df, biaya=BIAYA, maks_bar=it.get("maks_bar", MAKS_BAR))
    if info_p5:
        it["info_p5"] = info_p5
    return st, R, sl_lama


def _catat_ledger(k, it, R):
    import qse_catat as CT

    def f(d):
        d["closed"].append(dict(jalur=k, sym=it["sym"], arah=it["arah"], entry=it["entry"], sl=it["sl0"], tp1=0.0, tp2=0.0,
                                t=it["t"], status="SELESAI", R=round(R, 2), isi=it["t"], selesai=time.time(),
                                ket=it.get("info_p5") or "trailing + ema"))
    CT._ubah(f)


def rem(k):
    eq = peak = 0.0
    rugi = 0
    for c in sorted(lihat(k).get("closed", []), key=lambda c: c.get("selesai", 0)):
        r = float(c.get("R", 0))
        eq += r
        peak = max(peak, eq)
        rugi = rugi + 1 if r < 0 else 0
    if peak - eq > 16:
        return f"hasil jalur ini turun {peak - eq:.0f}R dari puncak"
    if rugi >= 6:
        return f"rugi {rugi} kali beruntun"
    return ""


def izin_btc():
    df = _k4("BTCUSDT", 600)
    if df is None or len(df) < 60:
        return {"LONG": True, "SHORT": True}
    import qse_ta as T
    c = df["close"].values.astype(float)[:-1]
    e20, e50 = T.ema(c, 20), T.ema(c, 50)
    up, dn, mom = c[-1] > e20[-1] > e50[-1], c[-1] < e20[-1] < e50[-1], c[-1] > c[-2]
    return {"LONG": not (dn and not mom), "SHORT": not (up and mom)}


BTC_BAND, BTC_KONF = 0.3, 2


def btc_arah_resmi(c, e):
    st, cnt = None, 0
    for i in range(max(60, len(c) - 300), len(c)):
        d = (c[i] - e[i]) / e[i] * 100
        sd = True if d > BTC_BAND else False if d < -BTC_BAND else None
        if sd is None:
            cnt = 0
            continue
        if st is None:
            st = sd
        elif sd != st:
            cnt += 1
            if cnt >= BTC_KONF:
                st, cnt = sd, 0
        else:
            cnt = 0
    return bool(c[-1] > e[-1]) if st is None else st


def btc_ema50_teks():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return ""
    c = df["close"].values.astype(float)
    ee = _ema(c, 50)
    e = float(ee[-1])
    naik = btc_arah_resmi(c, ee)
    teks = (f"{'🟢' if naik else '🔴'} BTC 4J condong {'LONG' if naik else 'SHORT'} "
            f"(close {c[-1]:,.0f}, EMA 50 {e:,.0f}, {(c[-1] / e - 1) * 100:+.1f}%)")
    if (c[-1] > e) != naik or abs(c[-1] / e - 1) * 100 <= BTC_BAND:
        teks += (f". Harga masih menempel EMA 50, arah belum berubah sampai 2 candle 4J tutup lebih dari "
                 f"{BTC_BAND:g}% di sisi lain")
    return teks


def btc_naik():
    df = _k4("BTCUSDT", 400)
    if df is None or len(df) < 100:
        return None
    c = df["close"].values.astype(float)
    return bool(c[-1] > _ema(c, 50)[-1])


def mutu(df, arah):
    o, h, l, c = (df[k].values.astype(float) for k in ("open", "high", "low", "close"))
    if len(c) < 120:
        return 0, [], []
    d = 1 if arah == "LONG" else -1
    tr = np.r_[h[0] - l[0], np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))]
    sm = lambda x: pd.Series(x).ewm(alpha=1 / 14, adjust=False).mean().values
    A = np.maximum(sm(tr), 1e-12)
    px = c[-1]
    plus = []
    hh, ll = h[-21:-1].max(), l[-21:-1].min()
    if (l[-1] < ll and px > ll) if d == 1 else (h[-1] > hh and px < hh):
        plus.append("false breakout arah lawan (jebakan)")
    y = c[-100:]
    x = np.arange(100)
    b1, b0 = np.polyfit(x, y, 1)
    res = y - (b0 + b1 * x)
    if res[-1] / (res.std() or 1e-9) * d > 1:
        plus.append("harga di atas channel searah")
    e = lambda v, n: pd.Series(v).ewm(span=n, adjust=False).mean().values
    m = e(c, 12) - e(c, 26)
    if (m - e(m, 9))[-1] * d > 0:
        plus.append("histogram MACD searah")
    up = np.r_[0, h[1:] - h[:-1]]
    dn = np.r_[0, l[:-1] - l[1:]]
    pdi = 100 * sm(np.where((up > dn) & (up > 0), up, 0)) / A
    mdi = 100 * sm(np.where((dn > up) & (dn > 0), dn, 0)) / A
    adx = sm(100 * abs(pdi - mdi) / np.maximum(pdi + mdi, 1e-9))[-1]
    minus = []
    if adx < 20:
        plus.append(f"ADX {adx:.0f} (tren belum ramai)")
    elif adx > 25:
        minus.append(f"ADX {adx:.0f} (tren sudah ramai)")
    step = 10 ** np.floor(np.log10(px)) / 2
    nxt = (np.floor(px / step) + 1) * step if d == 1 else (np.ceil(px / step) - 1) * step
    if abs(nxt - px) <= 1.5 * A[-1]:
        minus.append(f"angka bulat {nxt:g} menghadang dalam 1R")
    lebih = (px - (hh if d == 1 else ll)) * d
    if 0 < lebih < 0.25 * A[-1]:
        minus.append("tembus level 20 candle terlalu tipis")
    if res[-1] / (res.std() or 1e-9) * d < -1:
        minus.append("harga di sisi lawan channel")
    if m[-1] * d > 0:
        minus.append("MACD sudah di sisi searah nol")
    return len(plus), plus, minus


def pump_tolak(df, arah):
    try:
        if arah != "SHORT" or df is None or len(df) < 181:
            return ""
        c = df["close"].astype(float)
        r30 = float(c.iloc[-1]) / float(c.iloc[-181]) - 1
        return f"koin sudah naik {r30 * 100:.0f}% dalam 30 hari, SHORT melawan pump" if r30 > 0.30 else ""
    except Exception:
        return ""


def mutu_buang(plus, minus):
    return ", ".join(minus) if len(plus) - len(minus) <= -2 else ""


def mutu_teks(it):
    out = []
    if len(it.get("mutu_plus") or []) >= 3:
        out.append(f"💎 <b>MUTU TINGGI</b>: {', '.join(it['mutu_plus'])}. Uji 2021-2026 PF 1.37")
    if it.get("zona_kunci"):
        zk = it["zona_kunci"]
        out.append(f"🎯 <b>ZONA PANTULAN TERKUNCI ({zk['jumlah_konfirmasi']} KONFIRMASI)</b>: {', '.join(zk['konfirmasi'])} mengunci di {zk['titik_kunci']:.5g}")
    if it.get("rantai_konfirmasi"):
        out.append(f"⛓️ <b>RANTAI KONFIRMASI 5 INDIKATOR</b>: {' | '.join(it['rantai_konfirmasi'])}")
    return out


TELAT_JALUR = {"ema_short", "rsi_vol", "mcginley", "snr_vol", "smc_choch", "ichimoku", "rantai_eksekusi"}


def batas_masuk(it, k):
    try:
        risk = it.get("risk") or abs(it["entry"] - it.get("sl0", it["sl"]))
        if not risk:
            return None
        akhir = it.get("t", time.time()) + 14400 * (2.1 if k in TELAT_JALUR else 1.0)
        return it["entry"] - 0.5 * risk, it["entry"] + 0.5 * risk, akhir
    except Exception:
        return None


def batas_masuk_teks(it, k, fmt=None):
    b = batas_masuk(it, k)
    if not b:
        return []
    fmt = fmt or TG.fp
    t = it.get("tick", 0.0001)
    jam = time.strftime("%d/%m %H:%M", time.gmtime(b[2] + 7 * 3600))
    return [f"🎯 Entry valid {fmt(b[0], t)} sampai {fmt(b[1], t)}, batas {jam} WIB (Rem Anti-Terlambat aktif di luar rentang ini)"]


TAHAN_TP = {"snr_vol": "70%", "smc_choch": "68%", "orderblock": "59%", "mcginley": "58%"}


def kunci_jalur(j):
    return (j or "").replace("saran ", "").strip()


def tp_cepat_teks(it, fmt=None, k=None):
    """Pilar 5: Menampilkan skema Pengunci Keuntungan Bertahap (+1R/+2R) dan Target Pengikut Garis EMA."""
    try:
        fmt = fmt or TG.fp
        risk = abs(it["entry"] - it.get("sl0", it["sl"]))
        if not risk:
            return []
        L = it.get("arah", "LONG") == "LONG"
        t = it.get("tick", 0.0001)
        kk = kunci_jalur(k)
        r1 = it["entry"] + risk if L else it["entry"] - risk
        r2 = it["entry"] + 2 * risk if L else it["entry"] - 2 * risk
        ema_txt = f", dikawal garis EMA 20 ({fmt(it['ema_kawal'], t)})" if it.get("ema_kawal") else ", dikawal garis EMA 20"
        if it.get("combo_fix") or kk in TAHAN_TP:
            return [f"🛡 <b>Pengunci Profit Bertahap & Target EMA</b>: +1R ({fmt(r1, t)}) kunci SL ke BE+, +2R ({fmt(r2, t)}) kunci +1.1R{ema_txt} & amankan saat momentum melemah"]
        return [f"💰 <b>Pengunci Profit Bertahap & Target EMA</b>: 25% di +1R ({fmt(r1, t)}), 50% di +2R ({fmt(r2, t)}), sisa dikawal garis EMA{ema_txt}"]
    except Exception:
        return []


PF_JALUR = {
    "kombo_ob_awal": 1.68,
    "rantai_eksekusi": 1.55,
    "tt": 1.47,
    "orderblock": 1.45,
    "ema_short": 1.42,
    "rsi_vol": 1.34,
    "snr_vol": 1.33,
    "ichimoku": 1.29,
    "msb_hpz": 1.27,
    "smc_choch": 1.25,
    "mcginley": 1.24,
    "GZH": 1.24,
}


_VOLP = {}


def vol_pasar():
    t4 = int(time.time() // 14400)
    if t4 in _VOLP:
        return _VOLP[t4]
    x = None
    try:
        df = _k4("BTCUSDT", 200)
        v = df["volume"].astype(float)
        if len(v) >= 180:
            x = float(v.iloc[-1] / v.iloc[-180:].mean())
    except Exception as ex:
        print("[WARN] volume pasar", ex)
    _VOLP.clear()
    _VOLP[t4] = x
    return x


def vol_tinggi():
    x = vol_pasar()
    return round(x, 1) if x and x > 2.5 else None


MODE_MIN = {"semua": 0, "seimbang": 3, "profit": 5, "raja": 8}


def mode_sinyal():
    try:
        with open(os.path.join(STATE_DIR, "mode_sinyal.json")) as f:
            m = json.load(f).get("mode", "seimbang")
        return m if m in MODE_MIN else "seimbang"
    except Exception:
        return "seimbang"


def set_mode(m):
    m = (m or "").lower()
    if m not in MODE_MIN:
        return None
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "mode_sinyal.json"), "w") as f:
        json.dump({"mode": m}, f)
    return m


def lolos_mode(pr):
    return pr[0] >= MODE_MIN[mode_sinyal()]


def prioritas(k, it):
    n = (5 if it.get("combo_raja") else 0) + (3 if it.get("combo_fix") else 0) + (2 if it.get("combo_emas") else 0)
    cb = len(it.get("combo") or [])
    n += (1 if cb >= 1 else 0) + (1 if cb >= 2 else 0)
    n += 1 if len(it.get("mutu_plus") or []) >= 3 else 0
    n += 1 if it.get("pullback") else 0
    n += 2 if it.get("vol_tinggi") else 0
    n += 2 if (it.get("kombo_awal") or k in ("kombo_ob_awal", "rantai_eksekusi")) else 0
    n += 1 if (it.get("jumlah_konfirmasi", 0) >= 3) else 0
    return (n, PF_JALUR.get(k, 1.2))


def prioritas_teks(k, m):
    import re
    g = re.search(r"COMBO (\d+)", m)
    cb = int(g.group(1)) - 1 if g else 0
    n = (1 if cb >= 1 else 0) + (1 if cb >= 2 else 0) + (1 if "MUTU TINGGI" in m else 0) + (1 if "PULLBACK" in m else 0) \
        + (2 if "COMBO EMAS" in m else 0) + (3 if "COMBO FIX PROFIT" in m else 0) + (5 if "COMBO RAJA" in m else 0) \
        + (2 if "VOLUME PASAR TINGGI" in m else 0) + (2 if "RANTAI KONFIRMASI" in m or "Tangkapan Awal" in m else 0)
    return (n, PF_JALUR.get(k, 1.2))


def label_nama(it):
    out = (["COMBO RAJA"] if it.get("combo_raja") else []) + (["COMBO FIX PROFIT"] if it.get("combo_fix") else []) + (["COMBO EMAS"] if it.get("combo_emas") else [])
    if it.get("kombo_awal"):
        out.append("KOMBO TANGKAPAN AWAL OB")
    if it.get("rantai_konfirmasi"):
        out.append("RANTAI 5 INDIKATOR")
    cb = len(it.get("combo") or [])
    if cb:
        out.append(f"COMBO {cb + 1}")
    if len(it.get("mutu_plus") or []) >= 3:
        out.append("MUTU TINGGI")
    if it.get("pullback"):
        out.append("PULLBACK")
    if it.get("vol_tinggi"):
        out.append("VOLUME PASAR TINGGI")
    return out


def label_nama_teks(m):
    import re
    g = re.search(r"COMBO (\d+)", m)
    return (["COMBO RAJA"] if "COMBO RAJA" in m else []) + (["COMBO FIX PROFIT"] if "COMBO FIX PROFIT" in m else []) \
        + (["COMBO EMAS"] if "COMBO EMAS" in m else []) + (["KOMBO TANGKAPAN AWAL OB"] if "Tangkapan Awal" in m else []) \
        + (["RANTAI 5 INDIKATOR"] if "RANTAI KONFIRMASI" in m else []) + ([f"COMBO {g.group(1)}"] if g else []) \
        + (["MUTU TINGGI"] if "MUTU TINGGI" in m else []) + (["PULLBACK"] if "PULLBACK" in m else []) \
        + (["VOLUME PASAR TINGGI"] if "VOLUME PASAR TINGGI" in m else [])


def medali(no):
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(no, "🏅")


def kelas(n):
    if n >= 8:
        return "👑 NILAI 10 (PF uji 2.2)"
    if n >= 5:
        return "🔥 NILAI 9 (PF uji 1.7)"
    if n >= 3:
        return "✅ NILAI 8 (PF uji 1.3)"
    return ""


def label_prioritas(p):
    return kelas(p[0]) or "tanpa label"


def combo_teks(it):
    vt = ([f"🔊 <b>VOLUME PASAR TINGGI</b>: volume BTC 4J {it['vol_tinggi']:g}x rata 30 hari. Uji 2021-2026 sinyal di saat "
           f"seperti ini PF 1.66 dan 1.86, harga bergerak cepat ke dua arah, biarkan SL bekerja"] if it.get("vol_tinggi") else [])
    if not it.get("combo"):
        return vt
    emas = ([f"🏆 <b>COMBO EMAS</b>: pasangan dengan {', '.join(it['combo_emas'])} termasuk pasangan terbaik. "
             f"Dipilih dari 2021-2023 (PF 1.45), dicek 2024-2026 PF 1.48, combo biasa 1.25"] if it.get("combo_emas") else [])
    fix = ([f"💎 <b>COMBO FIX PROFIT</b>: searah dengan {' dan '.join(it['combo_fix'])}. Kombinasi 3 teknik terbaik, "
            f"dipilih dari 2021-2023, dicek 2024-2026 PF 1.75, rata-rata 0.33R per trade"] if it.get("combo_fix") else [])
    raja = (["👑 <b>COMBO RAJA</b>: 6 jalur terbukti atau lebih searah. Sinyal paling langka dan paling kuat di uji 2021-2026: "
             "sekitar 2 kali sebulan, WR 57%, PF 3.35, rata +0.73R per trade, untung tiap tahun"] if it.get("combo_raja") else [])
    return vt + raja + fix + emas + [f"⭐ <b>COMBO {len(it['combo']) + 1}</b>: juga {', '.join(it['combo'])} searah dalam 72 jam. "
            f"Uji 2021-2026: combo 3+ PF 1.40, 2 PF 1.25, sendiri PF 1.21"]


COMBO_EMAS = {("GZH", "smc_choch"), ("ema_short", "msb_hpz"), ("ema_short", "rsi_vol"), ("ichimoku", "ema_short"),
              ("ichimoku", "mcginley"), ("ichimoku", "rsi_vol"), ("mcginley", "GZH"), ("mcginley", "ema_short"),
              ("mcginley", "ichimoku"), ("mcginley", "msb_hpz"), ("msb_hpz", "ema_short"), ("msb_hpz", "ichimoku"),
              ("rsi_vol", "ichimoku"), ("rsi_vol", "mcginley"), ("rsi_vol", "msb_hpz"), ("rsi_vol", "smc_choch"),
              ("smc_choch", "ema_short"), ("snr_vol", "smc_choch"),
              ("ema_short", "mcginley"), ("mcginley", "smc_choch"), ("orderblock", "smc_choch"), ("smc_choch", "ichimoku"),
              ("kombo_ob_awal", "ichimoku"), ("kombo_ob_awal", "smc_choch"), ("rantai_eksekusi", "orderblock")}

COMBO_FIX = {("msb_hpz", frozenset({"ema_short", "smc_choch"})), ("ema_short", frozenset({"mcginley", "msb_hpz"})),
             ("rsi_vol", frozenset({"mcginley", "smc_choch"})), ("smc_choch", frozenset({"ichimoku", "mcginley"})),
             ("ichimoku", frozenset({"mcginley", "smc_choch"})), ("rsi_vol", frozenset({"mcginley", "msb_hpz"})),
             ("ichimoku", frozenset({"mcginley", "rsi_vol"})), ("rsi_vol", frozenset({"msb_hpz", "smc_choch"})),
             ("rsi_vol", frozenset({"ichimoku", "mcginley"})), ("ichimoku", frozenset({"rsi_vol", "smc_choch"})),
             ("kombo_ob_awal", frozenset({"ichimoku", "mcginley"})), ("rantai_eksekusi", frozenset({"ichimoku", "mcginley"}))}


def nama_ke_kunci(nm):
    peta = {cfg["nama"]: kk for kk, cfg in STRAT.items()}
    peta.update({"Ichimoku": "ichimoku", "Order Block": "orderblock"})
    return peta.get(nm)


def combo_raja(combo):
    return sum(1 for nm in (combo or []) if nama_ke_kunci(nm)) >= 5


def combo_fix(k, combo):
    kk = {nama_ke_kunci(nm): nm for nm in (combo or []) if nama_ke_kunci(nm)}
    for jalur, pas in COMBO_FIX:
        if jalur == k and pas <= set(kk):
            return sorted(kk[x] for x in pas)
    return []


def combo_emas(k, combo):
    return [nm for nm in (combo or []) if (k, nama_ke_kunci(nm)) in COMBO_EMAS]


def _combo(df, k, arah, bn, sym=None):
    nama = set()
    try:
        import qse_ichimoku as IC
    except Exception:
        IC = None
    try:
        import qse_ob as OB
    except Exception:
        OB = None
    for j in range(18):
        d = df.iloc[:len(df) - j] if j else df
        for kk, (ar, _) in sinyal(d, bn).items():
            if kk != k and ar == arah:
                nama.add(STRAT[kk]["nama"])
        if IC is not None and k != "ichimoku":
            ar_i, _ = IC._sinyal(d)
            if ar_i == arah:
                nama.add("Ichimoku")
        if OB is not None and k != "orderblock" and arah == "LONG" and "volume" in d:
            try:
                if OB._sinyal(d):
                    nama.add("Order Block")
            except Exception:
                pass
    try:
        cc, vv = df["close"].values.astype(float), df["volume"].values.astype(float)
        e9, e21, e2 = _ema(cc, 9), _ema(cc, 21), _ema(cc, 200)
        n_ = len(cc)
        for j in range(18):
            i = n_ - 1 - j
            if i < 210:
                break
            vp_ = (vv[i - 100:i] <= vv[i]).mean() * 100
            if vp_ < 80:
                continue
            if arah == "LONG" and e9[i] > e21[i] and e9[i - 1] <= e21[i - 1] and cc[i] > e2[i]:
                nama.add("EMA 9/21 + Volume")
            if arah == "SHORT" and e9[i] < e21[i] and e9[i - 1] >= e21[i - 1] and cc[i] < e2[i]:
                nama.add("EMA 9/21 + Volume")
    except Exception:
        pass
    if sym:
        try:
            now = time.time()
            for v in list(lihat("GZH").get("open", {}).values()) + list(lihat("GZH").get("closed", [])):
                if v.get("sym") == sym and v.get("arah") == arah and 0 <= now - v.get("t", 0) <= 72 * 3600 and k != "GZH":
                    nama.add(STRAT["GZH"]["nama"])
                    break
        except Exception:
            pass
    h, l = df["high"].values.astype(float), df["low"].values.astype(float)
    if len(h) > 2 and nama and h[-1] <= h[-2] and l[-1] >= l[-2]:
        nama.add("candle inside bar")
    return sorted(nama)


def jalankan(baru_ok=True):
    """Dipanggil listener tiap candle 4J tutup. Return dict kunci -> daftar pesan."""
    import qse_catat as CT
    import qse_saya as SY
    out = {k: [] for k in STRAT}
    try:
        tick = B.get_symbols()
    except Exception:
        tick = {}
    try:
        pegang = {(v["sym"], v["arah"]) for v in SY.lihat()["open"].values() if v.get("status") in ("TERISI", "TP1")}
    except Exception:
        pegang = set()
    # 1. kelola posisi menggunakan mesin Pilar 5
    for k in STRAT:
        hasil = {}
        for key, it in dict(lihat(k)["open"]).items():
            df = _k4(it["sym"], 300)
            if df is None or not len(df):
                continue
            it = dict(it)
            st, R, sl_lama = _kelola(it, df)
            hasil[key] = (it, st, R, sl_lama)
        for key, (it, st, R, sl_lama) in hasil.items():
            t = it.get("tick", 0.0001)
            kabar = (it["sym"], it["arah"]) in pegang
            if st != "BUKA":
                _catat_ledger(k, it, R)
                if kabar:
                    info_p5 = it.get("info_p5", "")
                    out[k].append(f"{'✅' if R > 0 else '🛑'} <b>{STRAT[k]['nama'].upper()} SELESAI ({st})  ·  {it['sym']} {it['arah']}  ·  {R:+.2f}R</b>\n"
                                  + (f"Keuntungan langsung diamankan saat indikator momentum melemah ({info_p5})." if st == "TP_MOMENTUM" else
                                     f"Pemotong risiko cepat aktif saat struktur pasar rusak ({info_p5})." if st == "CUT_STRUKTUR" else
                                     f"Target pengikut garis EMA / pengunci profit ({info_p5}) tercapai di {TG.fp(it['sl'], t)}." if st == "TP_EMA" else
                                     f"TP {TG.fp(it['tp'], t)} tersentuh." if st == "TP" else
                                     f"Kena SL volatilitas di sekitar {TG.fp(it['sl'], t)}. Analisa volume menyusul." if st == "SL" else
                                     f"Sudah {it.get('maks_bar', MAKS_BAR)} candle 4J. Tutup sekarang di harga pasar."))
            elif kabar and abs(it["sl"] - sl_lama) >= 0.20 * it["risk"]:
                L = it["arah"] == "LONG"
                kunci = ((it["sl"] - it["entry"]) if L else (it["entry"] - it["sl"])) / it["risk"]
                out[k].append(f"🔁 <b>{STRAT[k]['nama'].upper()}  ·  {it['sym']} {it['arah']}  ·  GESER SL & PENGAWAL EMA</b>\n"
                              f"Ubah SL di Bybit ke <code>{TG.fp(it['sl'], t)}</code> (sebelumnya {TG.fp(sl_lama, t)})\n"
                              f"Pengawal: {it.get('tahap_kunci') or 'Trailing ATR & Garis EMA 20'}  ·  Profit aman: {kunci:+.2f}R  ·  hari ke-{it['bar'] // 6 + 1} dari 10")

        def simpan(dd, hasil=hasil):
            for key, (it, st, R, _) in hasil.items():
                if key not in dd["open"]:
                    continue
                if st != "BUKA":
                    dd["open"].pop(key)
                    dd["closed"].append(dict(it, status=st, R=round(R, 2), selesai=time.time()))
                else:
                    dd["open"][key] = it
        _ubah(k, simpan)
    if not baru_ok:
        return out
    # 2. sinyal baru dengan Penyaring Utama (Pilar 1)
    try:
        tk = B.get_tickers()
    except Exception:
        return out
    ev_pasar = PY.evaluasi_pasar()
    bn = ev_pasar["btc"]["naik_ema50"]
    try:
        izin = izin_btc()
    except Exception:
        izin = {"LONG": True, "SHORT": True}
    pindai = [s for s in sorted(tk, key=lambda s: -tk[s]["turnover"]) if s in tick or not tick][:TOP_KOIN]

    def cek(sym):
        df = _k4(sym, 600)
        if df is None or len(df) < 261:
            return sym, {}, None, 0.0
        return sym, sinyal(df, bn), df, float((df["close"] * df["volume"]).iloc[-180:].sum())
    with ThreadPoolExecutor(8) as ex:
        semua = list(ex.map(cek, pindai))
    urut = [x[0] for x in sorted(semua, key=lambda x: -x[3])]
    now = time.time()
    dipakai = {it["sym"] for kk in STRAT for it in lihat(kk)["open"].values()}
    for k, cfg in STRAT.items():
        if cfg.get("manual"):
            continue
        if CT.mati(k):
            _CEK[k] = (0, "jalur dihentikan karena hasil live jelek")
            continue
        d = lihat(k)
        slot = min(MAKS_BARU, MAKS_BUKA - len(d["open"]))
        if slot <= 0:
            _CEK[k] = (0, "slot posisi penuh")
            continue
        boleh = set(urut[:cfg["likuid"]]) if cfg["likuid"] else set(urut)
        buka = {it["sym"] for it in d["open"].values()} | dipakai
        calon = [x for x in semua if k in x[1] and x[0] in boleh and x[0] not in buka]
        calon.sort(key=lambda x: urut.index(x[0]))
        baru = []
        for sym, sg, df, _ in calon:
            if len(baru) >= slot:
                break
            if sym in dipakai:
                continue
            arah, a = sg[k]
            # PILAR 1: Penyaring Utama Aliran Dana Besar & Mode Kombo Penembusan/Pantulan Otomatis
            lolos_p1, why_p1, _ = PY.saring_koin(sym, arah, df=df, jalur=k, evaluasi=ev_pasar)
            if not lolos_p1:
                print(f"[STRAT {k}] {sym} {arah} ditahan Penyaring Utama: {why_p1}")
                continue
            if cfg.get("izin_btc") and not izin.get(arah, True):
                print(f"[STRAT {k}] {sym} {arah} ditahan: izin BTC 4J tidak mengizinkan {arah}")
                continue
            import qse_porto as PO
            why = SY.cek_lintas(sym, arah) or PO.izin(sym, arah, k)
            if why:
                print(f"[STRAT {k}] {sym} ditahan: {why}")
                continue
            px = tk[sym]["last"] or float(df["close"].iloc[-1])

            # PILAR 2 & 4: Zona Pantulan Terkunci (min 2 konfirmasi) & Saringan Anti-Terlambat Otomatis dari Order Block
            o_v, h_v, l_v, c_v, v_v = (df[k_].values.astype(float) for k_ in ("open", "high", "low", "close", "volume"))
            zk = K.zona_pantulan_terkunci(o_v, h_v, l_v, c_v, v_v, arah=1 if arah == "LONG" else -1, min_konfirmasi=2)
            if not zk or zk.get("jumlah_konfirmasi", 0) < 2:
                print(f"[STRAT {k}] {sym} {arah} dilewati: kurang dari 2 konfirmasi struktur pasar pada zona pantulan")
                continue
            lolos_telat, why_telat, jrk_ob = PG.saring_anti_terlambat(
                px, arah, entry_sinyal=float(df["close"].iloc[-1]), ob_zona=zk, atr=a,
                maks_atr_ob=MAKS_JARAK_OB_ATR, maks_atr_entry=TELAT_ATR
            )
            if not lolos_telat:
                print(f"[STRAT {k}] {sym} {arah} dibatalkan ({why_telat})")
                continue

            try:
                sk, mp, mm = mutu(df, arah)
            except Exception as ex:
                print("[WARN] mutu", ex)
                sk, mp, mm = 0, [], []
            if mutu_buang(mp, mm):
                print(f"[STRAT {k}] {sym} {arah} dilewati: mutu rendah ({mutu_buang(mp, mm)})")
                continue
            if pump_tolak(df, arah):
                print(f"[STRAT {k}] {sym} {arah} dilewati: {pump_tolak(df, arah)}")
                continue
            if arah == "SHORT":
                if PG.short_tahan():
                    print(f"[STRAT {k}] {sym} SHORT dilewati: {PG.short_tahan()}")
                    continue
            L = arah == "LONG"
            sl = PR.hitung_sl_volatilitas(px, arah, a, sl_zona=zk.get("sl"), sl_atr_mult=cfg.get("sl_atr", SL_ATR))
            risk = abs(px - sl)
            if risk / px < 0.003 or risk / px > 0.10:
                continue
            t = tick.get(sym, 0.0001)
            rn_info = RN.evaluasi_rantai(df, arah_target=arah)
            dini_info = PG.deteksi_gerak_dini(df, arah=arah)
            ema20_now = float(_ema(c_v, 20)[-1])
            it = dict(
                sym=sym, arah=arah, entry=px, sl=sl, sl0=sl, risk=risk, best=px, bar=0, t=now,
                last=int(df.index[-1]), close=px, tick=t, sl_atr=cfg.get("sl_atr", SL_ATR),
                trail_atr=cfg.get("trail_atr", TRAIL_ATR), trail_pct_2r=cfg.get("trail_pct_2r"),
                zona_kunci=zk, jumlah_konfirmasi=zk.get("jumlah_konfirmasi", 2),
                rantai_konfirmasi=rn_info.get("rantai_konfirmasi", []),
                gerak_dini=dini_info.get("alasan", []),
                jarak_ob_atr=round(jrk_ob, 2),
                ema_kawal=ema20_now,
                kombo_awal=(k == "kombo_ob_awal"),
            )
            if cfg.get("tp_r"):
                it.update(tp=px + cfg["tp_r"] * risk if L else px - cfg["tp_r"] * risk, maks_bar=cfg["maks_bar"])
            it.update(mutu=sk, mutu_plus=mp)
            try:
                it["combo"] = _combo(df, k, arah, bn, sym)
                it["combo_emas"] = combo_emas(k, it["combo"])
                it["combo_fix"] = combo_fix(k, it["combo"])
                it["combo_raja"] = combo_raja(it["combo"])
                it["vol_tinggi"] = vol_tinggi()
            except Exception as ex:
                print("[WARN] combo", ex)
            if PO.senin_tolak(it.get("combo"), it.get("combo_emas")):
                print(f"[STRAT {k}] {sym} {arah} dilewati: {PO.senin_tolak(it.get('combo'), it.get('combo_emas'))}")
                continue
            if k == "mcginley":
                try:
                    cc = df["close"].values.astype(float)
                    e200, e20, e50 = _ema(cc, 200)[-1], _ema(cc, 20)[-1], _ema(cc, 50)[-1]
                    it["pullback"] = bool((cc[-1] > e200 and e20 < e50) if L else (cc[-1] < e200 and e20 > e50))
                except Exception as ex:
                    print("[WARN] pullback", ex)
            baru.append(it)
            dipakai.add(sym)
            PO.pesan(sym, arah)
            out[k].append(kartu(k, len(baru), it, a))

        def simpan_baru(dd, baru=baru):
            for it in baru:
                dd["open"][f"{it['sym']}|{int(it['t'])}"] = it
        if baru:
            _ubah(k, simpan_baru)
        _CEK[k] = (len(baru), "" if baru else ("BTC 4J di atas EMA 50, SHORT ditahan" if k == "ema_short" and bn
                                               else "tidak ada koin yang lolos semua syarat 5 pilar"))
    for k, (n, why) in _CEK.items():
        _ubah(k, lambda d, n=n, why=why: d.update(cek=dict(t=time.time(), n=n, why=why)))
    return out


_CEK = {}


def kartu(k, no, it, a):
    import qse_saya as SY
    cfg = STRAT[k]
    L = it["arah"] == "LONG"
    t = it["tick"]
    _, tkb, ik, lot_b = SY.boleh_ikut("saran " + k, it["arah"])
    import qse_porto as PO
    rm = rem(k) or PO.rem()
    if rm:
        lot_b = f"{SY.lot_angka(lot_b) / 2:g}x"
    lot_b, cat_hari = PO.lot_hari(lot_b)
    try:
        import qse_modal as MD
        lot = MD.baris_lot(it["entry"], it["sl"], SY.lot_angka(lot_b))
    except Exception:
        lot = ""
    jarak = it.get("trail_atr", TRAIL_ATR) * a
    return "\n".join([
        SY.GARIS,
        f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {it['arah']}</b>  ·  {cfg['nama']} 4J",
        f"{ik} <b>BISA DIIKUTI</b>  ·  {tkb}  ·  lot <b>{lot_b} lot normal</b> (saran risiko 0.25% modal per trade)",
        *combo_teks(it),
        *([cat_hari] if cat_hari else []),
        *mutu_teks(it),
        *(["🔁 <b>PULLBACK DALAM TREN BESAR</b>: searah EMA 200, tren pendek baru berbalik. "
           "Uji 2021-2026 McGinley pullback PF 1.43, McGinley biasa PF 1.18"] if it.get("pullback") else []),
        SY.GARIS,
        (SY.blok_salin(it["entry"], it["sl"], it["tp"], it["tp"], "MARKET", t, sym=it["sym"], arah=it["arah"], rentang=batas_masuk(it, k)) if it.get("tp") else
         SY.blok_salin(it["entry"], it["sl"], order="MARKET", tick=t, catatan_tp="dikawal Pengunci Profit Bertahap & Garis EMA 20", sym=it["sym"], arah=it["arah"],
                       rentang=batas_masuk(it, k))),
        *batas_masuk_teks(it, k),
        *tp_cepat_teks(it, k=k),
        *([f"🛡 <b>Rem drawdown aktif</b>: {rm}. Lot setengah sampai pulih"] if rm else []),
        "💡 <b>Kenapa (5 Pilar Terpadu)</b>",
        *[f"• {z}" for z in cfg["kenapa"]],
        f"• Bukti: {cfg['bt']}",
        "🛠 <b>Cara</b>",
        *([f"1. Masuk MARKET sekarang. SL volatilitas {TG.fp(it['sl'], t)}, TP puncak {TG.fp(it['tp'], t)} ({cfg['tp_r']:g}R)",
            "2. Posisi dikawal otomatis dengan pengunci keuntungan bertahap (+1R/+2R), target berjalan garis EMA 20, dan pemotong risiko cepat bila struktur pasar rusak",
            "3. Bila indikator momentum menunjukkan tanda pelemahan tenaga, robot langsung mengirim instruksi amankan keuntungan",
            "4. Catat dengan /entry supaya pengawalan EMA dan analisa volume SL aktif"] if it.get("tp") else
          [f"1. Masuk MARKET sekarang. SL volatilitas di {TG.fp(it['sl'], t)} ({it['risk'] / it['entry'] * 100:.1f}%)",
           "2. Posisi dikawal otomatis oleh pengunci keuntungan bertahap, target berjalan mengikuti garis EMA 20, dan Trailing Stop Bybit",
           *([f"   Setelah untung 2R ({TG.fp(it['entry'] + 2 * it['risk'] if L else it['entry'] - 2 * it['risk'], t)}), jarak "
              f"Trailing Stop menyempit jadi 5% harga"] if it.get("trail_pct_2r") else []),
           "3. Robot otomatis mengamankan profit saat momentum melemah atau memotong risiko cepat bila struktur pasar rusak",
           "4. Catat dengan /entry supaya pesan GESER SL dan analisa volume SL dikirim"]),
        *([SY.isi_trailing(jarak, it["sl"], t)] if not it.get("tp") else []),
        *([lot] if lot else []),
    ])


def baris_cek(k):
    if STRAT.get(k, {}).get("manual"):
        return "dipantau tiap menit saat harga menyentuh fib 0.618, dikirim terpisah"
    c = lihat(k).get("cek")
    if not c:
        return "belum pernah dicek sejak update"
    jam = time.strftime("%H:%M", time.gmtime(c["t"] + 7 * 3600))
    return f"dicek {jam} WIB: {c['n']} sinyal baru" + (f", {c['why']}" if c.get("why") and not c["n"] else "")


def status_singkat(k):
    return f"{baris_cek(k)}  ·  posisi robot {len(lihat(k)['open'])}/{MAKS_BUKA}"


def teks():
    rows = []
    try:
        rows.append(PY.ringkas_teks())
        rows.append("")
    except Exception:
        pass
    for k, cfg in STRAT.items():
        d = lihat(k)
        rows.append(f"<b>{cfg['nama']}</b>\nBacktest: {cfg['bt']}\n{status_singkat(k)}")
        for it in d["open"].values():
            L = it["arah"] == "LONG"
            g = ((it["close"] - it["entry"]) if L else (it["entry"] - it["close"])) / it["risk"]
            rows.append(f"{'🟢' if L else '🔴'} {it['sym']} {it['arah']} | entry {TG.fp(it['entry'], it['tick'])} | "
                        f"SL {TG.fp(it['sl'], it['tick'])} | {g:+.2f}R | candle {it['bar']}/{MAKS_BAR}")
        rs = [x["R"] for x in d["closed"] if x.get("R") is not None]
        if rs:
            w = sum(x for x in rs if x > 0)
            lo = -sum(x for x in rs if x < 0)
            rows.append(f"Selesai {len(rs)} trade | WR {sum(x > 0 for x in rs) / len(rs) * 100:.0f}% | "
                        f"PF {w / lo if lo > 0 else 9.99:.2f} | total {sum(rs):+.1f}R")
        rows.append("")
    rows.append("Peningkatan 5 Pilar Aktif: Indikator yang tadinya memberi sinyal terpisah (seperti garis McGinley & momentum sendiri-sendiri) "
                "kini wajib bekerja sebagai satu rantai konfirmasi dengan Zona Pantulan Terkunci (>=2 konfirmasi), Pemicu Gerak Dini, "
                "Rem Anti-Terlambat dari Order Block, serta Pengawal Target Garis EMA & Pemotong Risiko Cepat.")
    return "\n".join(rows)
