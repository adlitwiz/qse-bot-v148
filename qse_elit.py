"""QSE v150 QC 147/148 - MODE ELIT (permintaan user 26 Nov 2026: saldo naik, WR tinggi, PF tinggi, drawdown turun).
Riset: riset/upgrade/run_v266_elit.py (pilih subset PF >= 1.8 di 4 periode) dan run_v267_celah.py (risiko, slot, lapis).
LAPIS 1 💎 ELIT  : SKOR SINYAL 80+, bukan koin liar, searah vonis baru <= 12 jam. Lot 2x.
LAPIS 2 🔷       : SKOR SINYAL 70-79, bukan koin liar, searah vonis baru <= 12 jam. Lot 1x.
Lainnya ⚪ PANTAU SAJA (tanpa lot). 6 posisi berisiko per orang (qse_modal). Saldo 150 USDT, mulai ulang tiap periode, keluar QC 127, biaya ikut:
             latih            uji Jan25-Okt26   12 bulan          6 bulan
  SEKARANG   4302 DD 33%      639 DD 44%        192 DD 44%        230 DD 34%      PF 1.90 / 1.65 / 1.28 / 1.36, WR 34-36%
  QC 148     55379 DD 17%     719 DD 29%        292 DD 29%        255 DD 18%      PF 6.71 / 2.77 / 2.04 / 2.41, WR 55 / 45 / 40 / 40%
Dipilih dari 45 kombinasi (risiko 1-3%, 4/6/8 slot, lapis 2 0/0.5/1x): satu-satunya yang menang saldo DAN DD lebih kecil di uji, 12 bulan,
6 bulan dengan DD maksimum terendah. Saklar QSE_MODE_ELIT=0 kembali ke aturan lama."""
import os
import re

UJI = "PF 2.77 / 2.04 / 2.41 (uji, 12 bulan, 6 bulan), drawdown 18-29% (dulu 34-44%)"
LOT_ELIT = float(os.environ.get("QSE_LOT_ELIT", "2.0"))
LOT_LAPIS2 = float(os.environ.get("QSE_LOT_LAPIS2", "1.0"))


def aktif():
    return os.environ.get("QSE_MODE_ELIT", "1") != "0"


def _sym_arah(t):
    m = re.search(r"<b>(?:[^<]*?)?([A-Z0-9]+USDT) (LONG|SHORT)", t or "")
    return (m.group(1), m.group(2)) if m else (None, None)


def kartu_sinyal(t):
    """True kalau teks ini kartu sinyal (punya koin, arah, dan SL)."""
    return bool(_sym_arah(t)[0]) and bool(re.search(r"\nSL\s+[\d.]", t or ""))


def lapis(t, now=None):
    """(1 ELIT, 2 LAPIS 2, 0 PANTAU), alasan kalau 0."""
    sym, arah = _sym_arah(t)
    s = re.search(r"SKOR SINYAL (\d+)/100", t or "")
    sk = int(s.group(1)) if s else -1
    if sk < 70:
        return 0, f"skor {sk if sk >= 0 else '-'} di bawah 70"
    if "KOIN LIAR" in (t or ""):
        return 0, "koin liar"
    try:
        import qse_liar as LI
        if sym and LI.liar(sym)[0]:
            return 0, "koin liar"
    except Exception as _ex:
        __import__("config").diam("qse_elit.py:liar", _ex)
    try:
        import qse_vonis as QV
        if QV.lot_vonis_baru(arah, now)[0] <= 1:
            return 0, "tidak searah vonis baru (<= 12 jam)"
    except Exception as _ex:
        __import__("config").diam("qse_elit.py:vonis", _ex)
        return 0, "vonis tidak terbaca"
    return (1 if sk >= 80 else 2), ""


def elit(t, now=None):
    """(ya, alasan). ya hanya untuk lapis 1 (dipakai aturan gambar)."""
    lp, al = lapis(t, now)
    return lp == 1, (al or ("lapis 2, skor 70-79" if lp == 2 else ""))


def _ganti_lot(teks, baris_baru):
    out, buang, sudah = [], False, False
    for b in teks.split("\n"):
        if b.startswith("🟦 <b>KELAS") or b.startswith("🟨 <b>KELAS") or b.startswith("⚪ <b>PANTAU SAJA"):
            if not sudah and baris_baru:
                out.append(baris_baru)
            sudah = buang = True
            continue
        if buang and b.startswith("   "):
            continue
        buang = False
        out.append(b)
    if not sudah and baris_baru:
        out.append(baris_baru)
    return "\n".join(out)


def _lot(teks, kali):
    try:
        import qse_btcmap as BM
        import qse_modal as QM
        lv = BM.level_dari_kartu(teks)
        if lv.get("entry") and lv.get("sl"):
            return QM.baris_lot_kali(lv["entry"], lv["sl"], kali)
    except Exception as _ex:
        __import__("config").diam("qse_elit.py:lot", _ex)
    return ""


def olah(teks, rujukan=None, now=None):
    """Tandai kartu sinyal: 💎 ELIT lot 2x, 🔷 LAPIS 2 lot 1x, lainnya ⚪ PANTAU SAJA tanpa lot. rujukan = kartu lengkap untuk menilai.
    Bukan kartu sinyal, mode mati, atau sudah diproses: teks dikembalikan apa adanya."""
    if not aktif() or not kartu_sinyal(teks) or "SINYAL ELIT</b>" in teks or "LAPIS 2</b>" in teks or "PANTAU SAJA</b> (" in teks:
        return teks
    lp, alasan = lapis((rujukan or "") + "\n" + teks, now)
    if lp == 1:
        kl = LOT_ELIT; sym_ = None; andal_ = False
        try:          # QC 150: ELIT di koin andalan lot x1.25 (run_v269)
            import qse_andalan as AN
            sym_ = _sym_arah(teks)[0]
            andal_ = bool(sym_ and AN.andalan(sym_))
            if andal_:
                kl = round(LOT_ELIT * AN.LOT_ANDALAN, 2)
            if "PASANGAN WANGI" in (rujukan or "") + teks:          # QC 151 (run_v270)
                kl = round(kl * AN.LOT_WANGI, 2)
        except Exception as _ex:
            __import__("config").diam("qse_elit.py:andalan", _ex)
        return (f"💎 <b>SINYAL ELIT</b>: skor 80+, bukan koin liar, searah vonis baru"
                + (" + 🌹 pasangan wangi" if "PASANGAN WANGI" in (rujukan or "") + teks else "")
                + (" + 🏆 koin andalan" if andal_ else "") + f". Lot {kl:g}x. Uji {UJI}.\n"
                + _ganti_lot(teks, _lot(teks, kl)))
    if lp == 2:
        return (f"🔷 <b>LAPIS 2</b>: skor 70-79, bukan koin liar, searah vonis baru. Lot {LOT_LAPIS2:g}x (setengah ELIT).\n"
                + _ganti_lot(teks, _lot(teks, LOT_LAPIS2)))
    return _ganti_lot(teks, f"⚪ <b>PANTAU SAJA</b> ({alasan}). Bukan sinyal ELIT atau LAPIS 2, jangan dibuka.")
