"""QSE v170 SKOR KLASTER TREN (QC 66, 10 Nov 2026, riset/upgrade/run_v170_klaster.py, hasil_v170_klaster.txt).
Permintaan: skor konfluensi 4 klaster (Tren, Momentum, Struktur, Volume). Hasil uji jujur (batas dikunci dari latih 2023-2024, 15967 sinyal
EMA Cross SHORT / McGinley 34 / RSI 50, dinilai 2025-2026, 16458 sinyal, aturan kartu live):
 TREN     : sepertiga atas +0.180R, sepertiga bawah +0.021R. Selisih +0.240R di 2025 dan +0.076R di 2026. LOLOS di kedua tahun.
 MOMENTUM : selisih +0.065R di 2025, -0.033R di 2026. Tidak lolos.
 STRUKTUR : selisih -0.120R di 2025 (terbalik), +0.093R di 2026. Tidak lolos.
 VOLUME   : selisih +0.154R di 2025, -0.065R di 2026. Tidak lolos.
 Skor gabungan 4 klaster: 2025 naik bersama skor, 2026 datar (semua pita sekitar 0R). Tidak dipasang.
 DNA koin (rasio sumbu, ATR persen, korelasi BTC) untuk memilih teknik: 'cocok' +0.076R lawan 'tidak cocok' +0.103R (sumbu), tidak memisah.
Yang dipasang hanya klaster TREN: BTC 4J terhadap EMA 50, kemiringan EMA 50 koin (6 candle, per ATR), jarak harga ke EMA 200 (per ATR),
semua diarahkan ke arah sinyal. Tiap fitur dibagi 10 kelompok dari latih, nilai kelompok = rata R latih. Skor 0-100 = peringkat di latih.
Per kuintil: latih -0.103 / -0.003 / +0.034 / +0.094 / +0.156R. 2025 +0.007 / +0.166 / +0.081 / +0.176 / +0.384R.
2026 -0.026 / -0.066 / -0.005 / +0.004 / +0.028R. Kuintil 1 (skor < 20) tidak pernah untung berarti di tiga periode: KELAS RINGAN.
Catatan: nilai kelompok tidak naik lurus (contoh: BTC lebih dari 2.8% di sisi yang salah dari EMA 50 paling jelek, harga terlalu dekat atau
terlalu jauh dari EMA 200 jelek), jadi skor ini peta hasil latih, bukan ukuran "makin kencang makin bagus".
QC 68: skor ini diberi nama indikator QIE (indikator arah). Uji sebagai indikator berdiri sendiri (run_v170_qie.py): QIE > +60 dikurangi
QIE < -60, gerak 24 jam berikutnya: 2023 +0.066, 2024 -0.033, 2025 +0.123, 2026 -0.029 ATR, positif di 80 dari 152 koin. QIE TIDAK meramal
arah sendirian. Ia hanya terbukti sebagai saringan mutu untuk sinyal jalur. Jadi QIE tidak membuat sinyal sendiri.
Berlaku untuk jalur yang diuji saja (ema_short, mcginley, rsi_vol). Matikan aturan kelas: QSE_KLASTER_KELAS=0."""
import json
import os

import numpy as np

JALUR = ("ema_short", "mcginley", "rsi_vol")
BATAS_LEMAH, BATAS_KUAT = 20, 80
_PETA = [None]


def _peta():
    if _PETA[0] is None:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "klaster_tren.json")) as f:
            _PETA[0] = json.load(f)
    return _PETA[0]


def skor_dari_fitur(f_btc, f_slope, f_e200):
    """Skor Tren 0-100 dari tiga fitur (sudah diarahkan ke arah sinyal). Sama dengan uji."""
    p = _peta()
    v = []
    for nm, x in (("f_btc", f_btc), ("f_slope", f_slope), ("f_e200", f_e200)):
        ft = p["fitur"][nm]
        if x is None or x != x:
            x = ft["median"]
        v.append(ft["nilai"][int(np.searchsorted(ft["batas"], x))])
    return float(np.searchsorted(p["persentil"], float(np.mean(v))) / len(p["persentil"]) * 100)


def fitur(h, l, c, btc_c, arah, i=-1):
    """Tiga fitur tren di candle i dari candle 4J koin (h, l, c) dan harga tutup BTC 4J yang sejajar ujungnya."""
    import qse_strat as ST
    d = 1 if arah == "LONG" else -1
    a = ST._atr(h, l, c); e50, e200 = ST._ema(c, 50), ST._ema(c, 200)
    b50 = ST._ema(btc_c, 50)
    if not a[i] or a[i] != a[i]:
        return None
    return ((btc_c[i] - b50[i]) / b50[i] * 100 * d, (e50[i] - e50[i - 6]) / a[i] * d, (c[i] - e200[i]) / a[i] * d)


def skor(k, it):
    """Skor Tren 0-100 untuk sinyal jalur, atau None kalau jalur ini tidak diuji atau data tidak cukup. Disimpan di it['tren']."""
    if k not in JALUR:
        return None
    if it.get("tren") is not None:
        return it["tren"]
    try:
        import qse_strat as ST
        df, bt = ST._k4(it["sym"], 600), ST._k4("BTCUSDT", 600)
        if df is None or bt is None or len(df) < 260 or len(bt) < 260:
            return None
        # candle sinyal = candle 4J yang tutup tepat sebelum sinyal dibuat (it["t"] detik). Skor dihitung di candle itu, bukan candle terbaru
        t_sig = it.get("t_ms") or ((int(it["t"]) // 14400 - 1) * 14400 * 1000 if it.get("t") else None)
        if t_sig is not None:
            df, bt = df[df.index <= t_sig], bt[bt.index <= t_sig]
        n = min(len(df), len(bt))
        if n < 260 or int(df.index[-1]) != int(bt.index[-1]):
            return None
        f = fitur(df["high"].values.astype(float)[-n:], df["low"].values.astype(float)[-n:], df["close"].values.astype(float)[-n:],
                  bt["close"].values.astype(float)[-n:], it["arah"])
        if f is None:
            return None
        it["tren"] = round(skor_dari_fitur(*f), 0)
        return it["tren"]
    except Exception as ex:
        print("[WARN] klaster tren", it.get("sym"), ex)
        return None


def lemah(s):
    return s is not None and s < BATAS_LEMAH and os.environ.get("QSE_KLASTER_KELAS", "1") != "0"


def baris(k, it):
    """Baris kartu: skor Tren dan artinya. Kosong kalau tidak ada skor."""
    s = skor(k, it)
    if s is None:
        return ""
    if s < BATAS_LEMAH:
        ket = "RENDAH, kelas ringan. Uji: kelompok ini -0.10R latih, +0.01R 2025, -0.03R 2026"
    elif s >= BATAS_KUAT:
        ket = "TINGGI. Uji: kelompok ini +0.16R latih, +0.38R 2025, +0.03R 2026"
    else:
        ket = "sedang"
    return f"🧭 QIE · Skor Tren <b>{s:.0f}/100</b> ({ket})  ·  BTC 4J, kemiringan EMA 50, jarak EMA 200"
