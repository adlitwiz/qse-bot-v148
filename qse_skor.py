"""QC 122 SKOR SINYAL 0-100 (riset/upgrade/run_v238_skor.py, run_v238b_ekspor.py, hasil_v238b_ekspor.txt).

Model pohon (HistGradientBoosting) belajar HANYA dari sinyal siaran Jul 2022-Des 2024, diekspor ke qse_skor_model.json (tanpa sklearn).
16 ciri: teknik, arah, konfluensi 8 jam, combo 72 jam, NILAI combo, skor vonis, vonis searah, hari condong naik, RSI 4J, gerak 72 jam,
jarak ke EMA 50 4J dalam ATR, sisi BTC, jarak BTC ke EMA 50 4J, TP dalam R, lebar SL persen, ATR persen.
Skor 0-100 = persentil hasil model di sinyal latih. Di luar latih (uji 2025-Okt 2026, 12 bulan, 6 bulan), PF:
  skor 0-24 1.38/1.10/1.19, 25-49 1.51/1.19/1.18, 50-74 1.35/1.13/1.27, 75-89 1.89/1.23/1.27, 90-100 2.20/1.84/1.97.
LOT: skor < 20 x0.5, skor >= 80 x1.5, lainnya x1 (jumlah sinyal sama). Saldo siaran 886/227/248 ke 1312/286/257, Gurita 2159/226/190
ke 2719/277/211 (uji, 12 bln, 6 bln), DD naik 0-4 poin. Ambang 50/75 (x0.5 di bawah 50, x1.5 di atas 75) kalah: Gurita uji 2094, siaran
6 bulan 218. Skor tidak membatalkan aturan hari condong naik (SHORT skor tinggi di hari naik tetap rugi). Saklar QSE_SKOR=0."""
import json
import math
import os
import time

_M = {}
LOT_RENDAH, LOT_TINGGI, BATAS_RENDAH, BATAS_TINGGI = 0.5, 1.5, 20, 80


def model():
    if not _M:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "qse_skor_model.json")) as f:
            _M.update(json.load(f))
    return _M


def prediksi(x):
    """Nilai model untuk vektor ciri (urutan kolom model). NaN ikut arah missing_go_to_left seperti sklearn."""
    J = model(); s = J["base"]
    for t in J["pohon"]:
        i = 0
        while not t[i][6]:
            _, f, th, ml, kiri, kanan, _ = t[i]; v = x[f]
            i = (kiri if ml else kanan) if (v is None or v != v) else (kiri if v <= th else kanan)
        s += t[i][0]
    return s


def ke100(nilai):
    """Persentil nilai model di sinyal latih, 0-100."""
    import bisect
    return int(min(100, bisect.bisect_left(model()["persentil"], nilai)))


def kali_lot(s100):
    if os.environ.get("QSE_SKOR", "1") == "0" or s100 is None:
        return 1.0
    return LOT_TINGGI if s100 >= BATAS_TINGGI else (LOT_RENDAH if s100 < BATAS_RENDAH else 1.0)


def _ema(x, n):
    a = 2 / (n + 1); o = x[0]
    for v in x[1:]:
        o = o + a * (v - o)
    return o


def _rsi(c):
    if len(c) < 30:
        return None
    up = [max(b - a, 0) for a, b in zip(c, c[1:])]; dn = [max(a - b, 0) for a, b in zip(c, c[1:])]
    au, ad = sum(up[:14]) / 14, sum(dn[:14]) / 14
    for u, d in zip(up[14:], dn[14:]):
        au, ad = (au * 13 + u) / 14, (ad * 13 + d) / 14
    return 100 - 100 / (1 + au / max(ad, 1e-12))


def fitur(k, it, df4=None, btc_j=None, vonis_skor=None, naik=None, jejak8=None, jejak72=None):
    """Ciri satu sinyal (dict nama -> nilai), sama dengan definisi riset v238b. df4 = candle 4J koin (tes), lainnya diambil live."""
    import qse_strat as ST
    J = model(); d = 1 if it["arah"] == "LONG" else -1; sym = it["sym"]
    if df4 is None:
        df4 = ST._k4(sym, 300)
    c = [float(x) for x in df4["close"].values[:-1]]          # hanya candle 4J yang sudah tutup
    h = df4["high"].values[:-1].astype(float); l_ = df4["low"].values[:-1].astype(float)
    import numpy as np
    atr = float(ST._atr(h, l_, np.asarray(c))[-1]) if len(c) > 20 else None
    e = float(it.get("entry") or c[-1]); risk = abs(e - float(it.get("sl0", it.get("sl")))) if it.get("sl") is not None else None
    if btc_j is None:
        btc_j = it.get("btc_j") if it.get("btc_j") is not None else ST.btc_jarak()
    if vonis_skor is None or naik is None:
        try:
            import qse_vonis as QV
            ak = QV._baca().get("akhir") or {}
            vonis_skor = ak.get("skor") if vonis_skor is None else vonis_skor
        except Exception:
            pass
        try:
            import qse_pagi as PG
            hr = PG.arah_hari()
            naik = bool(hr and hr.get("naik")) if naik is None else naik
        except Exception:
            naik = False if naik is None else naik
    if jejak8 is None or jejak72 is None:
        import qse_gurita as GR
        jejak8 = GR._jejak_72j(jam=8) if jejak8 is None else jejak8
        jejak72 = GR._jejak_72j(jam=72) if jejak72 is None else jejak72
    kunci = (sym, it["arah"])
    kf = len(jejak8.get(kunci, set()) | {k})
    lain = jejak72.get(kunci, set()) - {k}
    cb = len(lain)
    emas = any((k, p) in ST.COMBO_EMAS for p in lain); fix = any(j == k and pas <= lain for j, pas in ST.COMBO_FIX)
    nil = 5 * (cb >= 5) + 3 * fix + 2 * emas + (cb >= 1) + (cb >= 2)
    vs = float(vonis_skor) if vonis_skor is not None else float("nan")
    vrel = (1 if vs >= 5 else -1 if vs <= -5 else 0) * d if vs == vs else float("nan")
    rsi = _rsi(c[-120:])
    m72 = (c[-1] / c[-19] - 1) * 100 * d if len(c) > 19 else float("nan")
    de = (c[-1] - _ema(c[-300:], 50)) / atr * d if atr else float("nan")
    x = dict(jal=float(J["jalur"].index(k)) if k in J["jalur"] else float("nan"), d=float(d), kf=float(kf), cb=float(cb), nil=float(nil),
             sk=vs * d, vrel=float(vrel), nh=float(bool(naik)), rsi=float(rsi) if rsi is not None else float("nan"), m72=float(m72), de=float(de),
             searah=float((btc_j or 0) * d >= 0) if btc_j is not None else float("nan"), bdist=float(btc_j) * d if btc_j is not None else float("nan"),
             tpr=float(J["tpr"].get(k, 0.0)), slp=risk / e * 100 if risk else float("nan"), atrp=atr / e * 100 if atr else float("nan"))
    return x


def skor(k, it, **kw):
    """(skor 0-100, kali lot, baris teks) atau (None, 1.0, '') kalau gagal."""
    try:
        x = fitur(k, it, **kw)
        v = prediksi([x[c] for c in model()["kolom"]])
        s = ke100(v); kl = kali_lot(s)
        return s, kl, baris(s, kl)
    except Exception as ex:
        print("[WARN] skor sinyal", it.get("sym"), ex)
        return None, 1.0, ""


def baris(s, kl):
    if s is None:
        return ""
    grp = ("90-100: uji PF 2.20, 12 bln 1.84, 6 bln 1.97" if s >= 90 else "75-89: uji PF 1.89, 12 bln 1.23, 6 bln 1.27" if s >= 75 else
           "50-74: uji PF 1.35, 12 bln 1.13, 6 bln 1.27" if s >= 50 else "25-49: uji PF 1.51, 12 bln 1.19, 6 bln 1.18" if s >= 25 else
           "0-24: uji PF 1.38, 12 bln 1.10, 6 bln 1.19")
    ikon = "🟢" if s >= 80 else "🟡" if s >= 20 else "🟠"
    return (f"{ikon} <b>SKOR SINYAL {s}/100</b> (peringkat sinyal ini di antara 13.593 sinyal latih, dari 16 ciri: teknik, arah, "
            f"konfluensi, vonis, hari naik, RSI 4J, gerak 72 jam, jarak EMA 50, BTC, lebar SL, ATR. Kelompok {grp})"
            + (f". <b>Lot x{kl:g}</b>" if kl != 1 else ". Lot normal")
            + (" (skor 80+ terbukti, lot dibesarkan)" if kl > 1 else " (skor di bawah 20, lot dikecilkan, tetap untung di uji)" if kl < 1 else ""))


def dari_teks(m):
    """QC 131: (kelas utama 1/0, skor atau -1) dari teks kartu jadi, untuk mengurutkan kartu."""
    import re
    g = re.search(r"SKOR SINYAL (\d+)/100", m or "")
    return (0 if "KELAS RINGAN" in (m or "") else 1, int(g.group(1)) if g else -1)


def pilihan(daftar):
    """QC 131 baris PILIHAN TERBAIK. daftar: list (sym arah, utama 1/0, skor). Hanya mengurutkan dan menandai, tidak membuang sinyal."""
    top = [x for x in daftar if x[1] and x[2] >= BATAS_TINGGI]
    if top:
        return ("⭐ <b>PILIHAN TERBAIK</b> (Kelas Utama + skor 80+, lot x1.5): "
                + ", ".join(f"{nm} skor {sk}" for nm, _, sk in top[:3]))
    ut = sorted([x for x in daftar if x[1] and x[2] >= 0], key=lambda x: -x[2])
    if ut:
        return (f"⭐ <b>Terbaik candle ini:</b> {ut[0][0]} (Kelas Utama, skor {ut[0][2]}). Belum ada Kelas Utama dengan skor 80+, "
                "sinyal lain tetap valid dengan lot sesuai skor.")
    return ""
