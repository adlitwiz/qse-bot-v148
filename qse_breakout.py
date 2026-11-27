"""QSE v150 QC 155 - KONFLUENSI BARU BREAKOUT 20 + VOLUME (hasil riset teknik koin liar yang dipakai di koin normal).
Riset riset/upgrade/run_v279_teknik_koin_normal.py dan run_v279b_konfluen_baru.py (data 2022-2026, tanpa melihat masa depan: breakout
harus terjadi di candle 4J yang sudah tutup, paling lama 3 candle sebelum sinyal sampai candle sinyal).
Breakout = close candle 4J di atas high tertinggi 20 candle sebelumnya (SHORT: di bawah low terendah) dan volume >= 1.5x rata 20 candle.
  Sendiri sebagai sinyal: PF 1.32 / 1.04 / 1.11 / 1.55, tidak lolos. Sebagai konfluensi sinyal siaran: PF 1.50 / 1.81 / 1.10 / 1.33.
  Di dalam ELIT: PF 8.28 / 3.90 / 2.32 / 2.58 (ELIT tanpa breakout 8.06 / 2.02 / 2.17 / 2.71).
  Lot ELIT + breakout x1.25 di atas QC 151: saldo 112057 / 903 / 332 / 286 lawan 73783 / 805 / 326 / 276, DD 18 / 37 / 37 / 21% lawan 17 / 33 / 33 / 19%.
  x1.5 saldo lebih besar (168053 / 1004 / 337 / 295) tapi DD 41%, tidak dipilih.
Data breakout diambil dari candle 4J yang sudah dipakai scan (tanpa panggilan tambahan), disimpan 6 jam."""
import os
import time
import numpy as np

LOT_BREAKOUT = float(os.environ.get("QSE_LOT_BREAKOUT", "1.25"))
_CACHE = {}


def hitung(df):
    """(naik, turun): ada breakout di 3 candle 4J terakhir yang sudah tutup."""
    try:
        h, l, c, v = (np.asarray(df[k].values, float) for k in ("high", "low", "close", "volume"))
        if len(c) < 25:
            return False, False
        up = dn = False
        for j in (len(c) - 1, len(c) - 2, len(c) - 3):
            vr = v[j] / max(v[j - 20:j].mean(), 1e-12)
            if vr >= 1.5 and c[j] > h[j - 20:j].max():
                up = True
            if vr >= 1.5 and c[j] < l[j - 20:j].min():
                dn = True
        return up, dn
    except Exception as _ex:
        __import__("config").diam("qse_breakout.py:hitung", _ex)
        return False, False


def catat(sym, df):
    _CACHE[sym] = (time.time(), *hitung(df))


def ada(sym, arah, now=None):
    c_ = _CACHE.get(sym)
    if not c_ or (now or time.time()) - c_[0] > 6 * 3600:
        return False
    return c_[1] if arah == "LONG" else c_[2]


def baris(sym, arah):
    if os.environ.get("QSE_BREAKOUT", "1") == "0" or not ada(sym, arah):
        return ""
    return (f"🚀 <b>BREAKOUT 20 + VOLUME</b> searah {arah}: harga menembus {'high' if arah == 'LONG' else 'low'} 20 candle 4J dengan volume "
            f"1.5x. Di dalam ELIT uji PF 3.90 lawan 2.02 tanpa breakout. Sinyal ELIT dengan breakout lot x{LOT_BREAKOUT:g}.")
