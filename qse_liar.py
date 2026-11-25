"""QSE v150 QC 141 - TANDA KOIN LIAR (koin seperti HMSTR: harga sangat liar, gerak per candle 4J besar).
Ciri yang bisa diukur saat sinyal tanpa melihat masa depan: ATR 14 candle 4J >= 3.5% dari harga (ambang p75 periode latih,
riset/upgrade/run_v260_koin_liar.py). Kelompok ini di populasi siaran 2022-2026, aturan keluar QC 127, sesudah biaya:
menang 34-36%, PF 1.15 (latih) / 1.14 (uji) / 1.32 (12 bulan) / 0.94 (6 bulan), semua sinyal lain PF 1.31 / 1.52 / 1.20 / 1.28.
Usaha menaikkan WR kelompok ini (run_v261_wr_liar.py, 8 variasi TP lebih awal dan SL ke entry lebih awal): WR naik ke 50-53% tapi
total R turun 20-48R di latih, jadi aturan keluar tidak diubah. Tanda ini label saja: sinyal, lot, SL, dan TP tetap."""
import os
import time
import numpy as np

AMBANG = float(os.environ.get("QSE_LIAR_ATR", "3.5") or 3.5)
_CACHE = {}


def atr_pct(sym, df=None):
    """ATR 14 candle 4J dalam persen harga. df boleh diberikan (dataframe 4J dengan high, low, close). None kalau gagal."""
    now = time.time()
    c_ = _CACHE.get(sym)
    if df is None and c_ and now - c_[0] < 1800:
        return c_[1]
    try:
        if df is None:
            import qse_strat as ST
            df = ST._k4(sym, 120)
        h, l, c = (np.asarray(df[k].values, float) for k in ("high", "low", "close"))
        if len(c) < 20:
            return None
        import qse_strat as ST
        x = float(ST._atr(h, l, c)[-1] / c[-1] * 100)
    except Exception as _ex:
        __import__("config").diam("qse_liar.py:30", _ex)
        return None
    _CACHE[sym] = (now, x)
    return x


def liar(sym, df=None):
    x = atr_pct(sym, df)
    return x is not None and x >= AMBANG, x


def baris(sym, df=None):
    """Satu baris untuk kartu sinyal. '' kalau bukan koin liar atau saklar QSE_TANDA_LIAR=0."""
    if os.environ.get("QSE_TANDA_LIAR", "1") == "0":
        return ""
    ya, x = liar(sym, df)
    if not ya:
        return ""
    return (f"🐹 <b>KOIN LIAR</b> (gerak rata-rata {x:.1f}% per candle 4J, ambang {AMBANG:g}%). Uji 2022-2026 kelompok ini: menang 34-36%, "
            "PF 1.14 di uji dan 0.94 di 6 bulan terakhir, lebih lemah dari sinyal biasa (PF 1.28-1.52). Lot dan SL tetap sesuai kartu. "
            "Kalau slot terbatas, pilih kartu lain yang bukan koin liar.")


def tag(sym, df=None):
    """Tanda pendek untuk judul (radar, peta SL). '' kalau bukan koin liar."""
    if os.environ.get("QSE_TANDA_LIAR", "1") == "0":
        return ""
    return "🐹 KOIN LIAR" if liar(sym, df)[0] else ""


def daftar(maks=25):
    """QC 142: koin liar dari scan 4J terakhir (cache 6 jam), urut paling liar. List (sym, atr%)."""
    now = time.time()
    x = [(k, v[1]) for k, v in _CACHE.items() if v[1] is not None and v[1] >= AMBANG and now - v[0] <= 6 * 3600]
    return sorted(x, key=lambda z: -z[1])[:maks]


def teks():
    """/liar: daftar koin liar hasil scan 4J terakhir dan cara robot menanganinya."""
    d = daftar()
    n_all = sum(1 for v in _CACHE.values() if time.time() - v[0] <= 6 * 3600)
    if not n_all:
        return "🐹 <b>KOIN LIAR</b>\nBelum ada data. Daftar terisi sesudah scan 4J berikutnya."
    baris = [f"{i + 1}. {s_.replace('USDT', '')} gerak {a:.1f}% per candle 4J" for i, (s_, a) in enumerate(d)]
    return (f"🐹 <b>KOIN LIAR</b> (ATR 4J >= {AMBANG:g}% dari harga): {len(d)} dari {n_all} koin di scan 4J terakhir.\n"
            + ("\n".join(baris) if baris else "Tidak ada koin liar saat ini.")
            + "\n\nCiri ini mirip HMSTR. Uji 2022-2026: menang 34-36%, PF 1.14 di uji, 0.94 di 6 bulan. Sinyal di koin ini tetap dikirim "
              "dengan tanda 🐹. Posisi di koin liar dikawal lebih rapat: robot mengirim keputusan di rugi 0.3R dan 0.7R.")
