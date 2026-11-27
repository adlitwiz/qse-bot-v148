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


def _rapikan(teks, lp, kpt):
    """QC 153: satu keputusan saja di kartu. Baris keputusan lama diganti. PANTAU: baris lot, LOT x1.5 vonis, dan saran entry dibuang."""
    out = []
    for b in teks.split("\n"):
        if b.startswith("🧭 Keputusan:") or b.startswith("🧭 <b>Keputusan:"):
            out.append(f"🧭 Keputusan: <b>{kpt}</b>")
            continue
        if lp == 0 and (b.startswith("🚀 <b>LOT x") or b.startswith("💰 Saran entry") or b.startswith("1 teknik: lot")
                        or b.startswith("2+ teknik") or "Kalikan saran entry" in b):
            continue
        if lp == 0 and b.endswith(". Lot normal"):
            b = b[: -len(". Lot normal")]
        out.append(b)
    return "\n".join(out)


def olah(teks, rujukan=None, now=None):
    """Tandai kartu sinyal dengan LAPIS di baris paling atas dan satu keputusan:
    💎 LAPIS 1 ELIT (lot 2x, x1.25 koin andalan, x1.5 pasangan wangi), 🔷 LAPIS 2 (lot 1x), ⚪ PANTAU SAJA (tanpa lot, jangan dibuka).
    rujukan = kartu lengkap untuk menilai. Bukan kartu sinyal, mode mati, atau sudah diproses: teks dikembalikan apa adanya."""
    if not aktif() or not kartu_sinyal(teks) or "SINYAL ELIT</b>" in teks or "LAPIS 2</b>" in teks or "PANTAU SAJA</b> (" in teks:
        return teks
    lp, alasan = lapis((rujukan or "") + "\n" + teks, now)
    if lp == 1:
        kl = LOT_ELIT; sym_ = None; andal_ = False
        wangi_ = "PASANGAN WANGI" in (rujukan or "") + teks
        try:          # QC 150/151: koin andalan x1.25, pasangan wangi x1.5
            import qse_andalan as AN
            sym_ = _sym_arah(teks)[0]
            andal_ = bool(sym_ and AN.andalan(sym_))
            if andal_:
                kl = round(kl * AN.LOT_ANDALAN, 2)
            if wangi_:
                kl = round(kl * AN.LOT_WANGI, 2)
            if "BREAKOUT 20 + VOLUME" in (rujukan or "") + teks:          # QC 155 (run_v279b)
                import qse_breakout as BK
                kl = round(kl * BK.LOT_BREAKOUT, 2)
        except Exception as _ex:
            __import__("config").diam("qse_elit.py:andalan", _ex)
        badan = _rapikan(teks, 1, f"✅ AMBIL, 💎 LAPIS 1 ELIT lot {kl:g}x")
        return (f"💎 <b>LAPIS 1 · SINYAL ELIT</b> · AMBIL lot {kl:g}x\nSkor 80+, bukan koin liar, searah vonis baru"
                + (" + 🌹 pasangan wangi" if wangi_ else "") + (" + 🚀 breakout" if "BREAKOUT 20 + VOLUME" in (rujukan or "") + teks else "") + (" + 🏆 koin andalan" if andal_ else "") + f". Uji {UJI}.\n"
                + _ganti_lot(badan, _lot(teks, kl)))
    if lp == 2:
        badan = _rapikan(teks, 2, f"✅ AMBIL, 🔷 LAPIS 2 lot {LOT_LAPIS2:g}x")
        return (f"🔷 <b>LAPIS 2</b> · AMBIL lot {LOT_LAPIS2:g}x\nSkor 70-79, bukan koin liar, searah vonis baru. Lot setengah ELIT.\n"
                + _ganti_lot(badan, _lot(teks, LOT_LAPIS2)))
    badan = _rapikan(teks, 0, "⚪ PANTAU SAJA, jangan dibuka")
    return (f"⚪ <b>PANTAU SAJA</b> ({alasan}) · JANGAN DIBUKA\nHanya 💎 LAPIS 1 ELIT dan 🔷 LAPIS 2 yang memakai modal.\n"
            + _ganti_lot(badan, ""))


def lapis_r(r, now=None):
    """QC 153: LAPIS untuk data sinyal radar (dict r) tanpa kartu. Dipakai baris Keputusan sekarang di analisa otak."""
    sk = r.get("skor100")
    if sk is None:
        try:
            import qse_skor as SKR
            it = dict(sym=r["sym"], arah=r["arah"], entry=float(r.get("px") or 0), sl=float(r.get("sl") or 0), sl0=float(r.get("sl") or 0))
            sk = SKR.skor(r.get("k") or "", it, btc_j=r.get("bj"))[0]
        except Exception as _ex:
            __import__("config").diam("qse_elit.py:lapis_r", _ex)
            sk = None
    if sk is None:
        return 0, "skor tidak terbaca"
    return lapis(f"<b>{r['sym']} {r['arah']}</b>\nSKOR SINYAL {int(sk)}/100", now)


def koin_liar(teks):
    """QC 155: kartu sinyal koin liar tidak disiarkan lagi (permintaan user, 4 ronde riset tanpa cara yang lolos). Uji live tetap jalan."""
    if os.environ.get("QSE_SIAR_LIAR", "0") == "1" or not kartu_sinyal(teks):
        return False
    if "KOIN LIAR" in (teks or ""):
        return True
    try:
        import qse_liar as LI
        sym = _sym_arah(teks)[0]
        return bool(sym and LI.liar(sym)[0])
    except Exception as _ex:
        __import__("config").diam("qse_elit.py:koin_liar", _ex)
        return False
