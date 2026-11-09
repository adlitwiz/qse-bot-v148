"""QSE v150 - kartu sinyal yang DITAHAN otak robot. Sebelumnya sinyal jalur yang ditahan otak (peluang rendah, profil koin belum lulus)
tetap dicatat di Jalur Live tapi tidak dikirim. Sekarang tiap posisi baru jalur yang ditahan dikirim sebagai kartu tersendiri,
dengan alasan penahanan dan lot kecil, supaya semua transaksi di laporan Jalur juga sampai ke Telegram.
Uji saringan otak (qse_otak.py): 2023-2026 semua sinyal PF 1.23, sesudah saringan PF 1.35. Sinyal yang ditahan rata-rata lebih lemah,
jadi lot kartu ini 0.1x. Sinyal ditahan yang didukung 3+ jalur lain diambil gurita (kartu gurita), tidak dikirim dua kali.
Matikan dengan env QSE_KIRIM_DITAHAN=0.
v150 9 Nov 2026 (permintaan user): sumbatan dibuka. Sinyal berlabel COMBO RAJA, COMBO FIX PROFIT, COMBO EMAS, EMA Cross SHORT,
BTC.D TURUN SHORT, atau NILAI 9-10 dikirim sebagai SINYAL JALUR LIVE KELAS UTAMA. KELAS RINGAN (ukuran ringan tiap orang): EMA Cross SHORT
koin baru, LONG saat kompas merah, dan sinyal eks-tahanan otak. Semua sinyal tetap dicatat di Jalur Live. Tidak ada lagi yang dilewati karena combo 3+."""
import json
import os
import time
from config import STATE_DIR

F = os.path.join(STATE_DIR, "ditahan.json")
LOT = 0.1
UMUR_JAM = 4


def _baca():
    try:
        with open(F) as f:
            return json.load(f)
    except Exception:
        return {"kirim": {}}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(F + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(F + ".tmp", F)


def _sumber():
    out = []
    try:
        import qse_strat as ST
        for k, cfg in ST.STRAT.items():
            out += [(k, cfg.get("nama", k), it) for it in ST.lihat(k)["open"].values()]
    except Exception as ex:
        print("[WARN] ditahan strat", ex)
    for mod, k, nm in (("qse_ichimoku", "ichimoku", "Ichimoku"), ("qse_ob", "orderblock", "Order Block + Volume")):
        try:
            m = __import__(mod)
            out += [(k, nm, it) for it in m.lihat()["open"].values()]
        except Exception:
            pass
    return out


def prioritas_live(k, it):
    """(True, alasan) kalau sinyal masuk daftar terbukti yang wajib dikirim tanpa ditahan."""
    try:
        import qse_strat as ST
        n = ST.prioritas(k, it)[0]
    except Exception:
        n = 0
    if it.get("combo_raja"):
        return True, "COMBO RAJA"
    if it.get("combo_fix"):
        return True, "COMBO FIX PROFIT"
    if it.get("combo_emas"):
        return True, "COMBO EMAS"
    if k == "ema_short" and it.get("arah") == "SHORT":
        return True, "EMA Cross 20/50 SHORT"
    if it.get("dom_turun") and it.get("arah") == "SHORT":
        return True, "BTC.D TURUN SHORT"
    if n >= 5:
        return True, "NILAI 10" if n >= 8 else "NILAI 9"
    return False, ""


def kartu(k, nama, it):
    import qse_saya as SY
    t = it.get("tick")
    L = it["arah"] == "LONG"
    e, sl = it["entry"], it["sl"]
    risk = abs(e - sl) or e * 0.02
    d = 1 if L else -1
    tp1 = e + d * 0.5 * risk
    tp2 = it.get("tp") or e + d * 1.5 * risk
    lab = []
    if it.get("combo_raja"):
        lab.append("👑 COMBO RAJA")
    elif it.get("combo_fix"):
        lab.append("💎 COMBO FIX PROFIT")
    elif it.get("combo_emas"):
        lab.append("🏆 COMBO EMAS")
    elif it.get("combo"):
        lab.append(f"⭐ COMBO {len(it['combo']) + 1}")
    if it.get("dom_turun"):
        lab.append("📉 BTC.D TURUN")
    why = it.get("otak_why") or "peluang menurut otak robot rendah"
    prio, nm_prio = prioritas_live(k, it)
    kl, alasan_kl = kelas(k, it, prio)
    cuaca = ""
    try:
        import qse_cuaca as CU
        cuaca = CU.baris(k, it)
    except Exception:
        pass
    try:
        import qse_kompas as KP
        _, kp_teks = KP.label(it["arah"])
        if kp_teks:
            cuaca = (cuaca + "\n" if cuaca else "") + kp_teks.replace("Lot dipotong 0.5x", "Kelas ringan")
    except Exception:
        pass
    try:
        import qse_modal as MD
        lot = MD.baris_lot(e, sl, kelas=kl)
    except Exception:
        lot = ""
    ik = "🟦 KELAS UTAMA" if kl == "UTAMA" else "🟨 KELAS RINGAN"
    if prio:
        return (f"🚀 <b>SINYAL JALUR LIVE: {it['sym']} {it['arah']}</b>  ·  {nama}" + (f"  ·  {' '.join(lab)}" if lab else "")
                + f"\n✅ Masuk daftar terbukti ({nm_prio}), dikirim tanpa ditahan. Catatan otak: {why}."
                + f"\n<b>{ik}</b>" + (f" ({alasan_kl})" if alasan_kl else "")
                + (f"\n{cuaca}" if cuaca else "") + "\n"
                + SY.blok_salin(e, sl, tp1, tp2, "MARKET", t, sym=it["sym"], arah=it["arah"])
                + "\n📲 TP1 tutup 50% lalu SL ke entry." + ("\n" + lot if lot else ""))
    return (f"🧠 <b>SINYAL JALUR EKS-TAHANAN OTAK: {it['sym']} {it['arah']}</b>  ·  {nama}" + (f"  ·  {' '.join(lab)}" if lab else "")
            + f"\n⚠️ Catatan otak: {why}. Tetap dikirim, kamu yang memilih. Uji: sinyal yang lolos otak PF 1.35, semua sinyal PF 1.23."
            + f"\n<b>{ik}</b> ({alasan_kl})"
            + (f"\n{cuaca}" if cuaca else "") + "\n"
            + SY.blok_salin(e, sl, tp1, tp2, "MARKET", t, sym=it["sym"], arah=it["arah"])
            + "\n📲 TP1 tutup 50% lalu SL ke entry." + ("\n" + lot if lot else ""))


def kelas(k, it, prio=None):
    """('UTAMA'|'RINGAN', alasan). Permintaan user 9 Nov: RINGAN untuk EMA Cross SHORT koin baru, LONG saat kompas merah,
    dan sinyal eks-tahanan otak. Sisanya yang masuk daftar terbukti UTAMA."""
    if prio is None:
        prio = prioritas_live(k, it)[0]
    if not prio:
        return "RINGAN", "sinyal eks-tahanan otak"
    if it["arah"] == "LONG":
        try:
            import qse_kompas as KP
            if KP.label("LONG")[0] < 1:
                return "RINGAN", "LONG saat kompas merah"
        except Exception:
            pass
    try:
        import qse_overmind as OM
        r_, why_ = OM.kelas_jalur(k)
        if r_:
            return "RINGAN", why_
    except Exception:
        pass
    pr = it.get("profil") or {}
    lab_kuat = it.get("combo_raja") or it.get("combo_fix") or it.get("combo_emas")
    if k == "ema_short" and not lab_kuat and (pr.get("n", 0) < 10):
        return "RINGAN", "EMA Cross SHORT di koin baru, rekam jejak koin kurang dari 10 sinyal"
    return "UTAMA", ""


def jalankan():
    """Tiap menit: kirim kartu untuk posisi jalur baru yang ditahan otak. Return list pesan."""
    if os.environ.get("QSE_KIRIM_DITAHAN", "1") == "0":
        return []
    d = _baca(); now = time.time(); out = []
    for k, nama, it in _sumber():
        t0 = it.get("t", 0)
        key = f"{k}|{it.get('sym')}|{int(t0)}"
        if key in d["kirim"] or not it.get("otak_saring") or now - t0 > UMUR_JAM * 3600:
            continue
        d["kirim"][key] = now
        if it.get("blokir_koin"):
            continue                      # QC 56: teknik ini rugi di koin ini, tidak dikirim sama sekali
        try:
            out.append(kartu(k, nama, it))
        except Exception as ex:
            print("[WARN] kartu ditahan", ex)
    d["kirim"] = {k: v for k, v in d["kirim"].items() if now - v < 7 * 86400}
    _tulis(d)
    return out
