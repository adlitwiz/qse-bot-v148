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


LIMIT_ATR = 0.25          # v170 QC 64: jarak Pending Limit alternatif dari harga tutup sinyal
JALUR_LIMIT = ("ema_short", "mcginley", "rsi_vol")          # jalur yang cara masuknya diuji di run_v170_tahan.py


def rincian_skor(k, it):
    """v170: baris rincian skor sinyal (label terbukti, peluang otak, profil koin) supaya alasan kelas dan penahanan terbaca."""
    try:
        import qse_strat as ST
        import qse_btcmap as BM
        n = ST.prioritas(k, it)[0]
        z = next(x for x in BM.SKOR if n >= x[0])
        bag = [f"💯 Skor <b>{z[1]}/100</b> ({z[2]}, uji PF {z[4]}, WR {z[5]})"]
        lab = ST.label_nama(it)
        bag.append("label: " + (", ".join(lab) if lab else "tidak ada"))
    except Exception:
        bag = []
    if it.get("otak") is not None:
        bag.append(f"peluang otak {it['otak'] * 100:.0f}% (batas {it.get('otak_batas', 0) * 100:.0f}%)")
    pr = it.get("profil") or {}
    if pr.get("n"):
        bag.append(f"profil koin {pr['n']} sinyal" + (f", PF {pr['pf']:.2f}" if pr.get("pf") is not None else ""))
    return "🧮 " + "  ·  ".join(bag) if bag else ""


def alternatif_limit(k, it):
    """v170: saran Pending Limit di harga lebih baik untuk sinyal eks-tahanan. Uji run_v170_tahan.py (pasangan koin+teknik yang latihnya
    negatif, dinilai 2025-2026): Limit 0.25 ATR terisi 86%, PF 1.20, +0.055R per sinyal. Market PF 1.19, +0.052R. Setara, bukan lebih
    unggul (di latih Market lebih baik), jadi ini pilihan, bukan pengganti. Stop Trap PF 1.15, +0.035R: tidak disarankan."""
    if k not in JALUR_LIMIT:
        return ""
    try:
        import qse_saya as SY
        import qse_strat as ST
        e, sl = it["entry"], it.get("sl0", it["sl"])
        risk = abs(e - sl)
        slk = it.get("sl_atr") or ST.STRAT.get(k, {}).get("sl_atr", ST.SL_ATR)
        a = risk / slk if slk else 0
        if a <= 0:
            return ""
        d = 1 if it["arah"] == "LONG" else -1
        lv = e - d * LIMIT_ATR * a
        t = it.get("tick") or SY.tick_of(None, e)
        return (f"🪤 <b>Pilihan Pending Limit</b> (harga lebih baik): antre di <b>{SY.fp(lv, t)}</b>, SL tetap {SY.fp(sl, t)}, berlaku 24 jam. "
                f"Uji sinyal lemah 2025-2026: terisi 86%, PF 1.20 (Market PF 1.19). Stop Trap tidak disarankan (PF 1.15)")
    except Exception as ex:
        print("[WARN] alternatif limit", ex)
        return ""


def kartu(k, nama, it):
    import qse_saya as SY
    jg = []
    try:
        import qse_jagoan as JG          # QC 60: label koin jagoan di baris paling atas
        jg = JG.tandai(k, it)
    except Exception as ex:
        print("[WARN] jagoan", ex)
    atas = "\n".join(jg) + "\n" if jg else ""
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
    import qse_strat as ST
    be = ST.be_r(k)
    if be:          # QC 61: EMA Cross tanpa TP sebagian, SL ke entry di +0.4R lalu SL berjalan
        lv = e + d * be * risk
        blok = (SY.blok_salin(e, sl, order="MARKET", tick=t, catatan_tp="tanpa, pakai SL berjalan", sym=it["sym"], arah=it["arah"])
                + f"\n📲 Tanpa TP sebagian. Harga sampai {SY.fp(lv, t)} (+{be:g}R): SL ke entry. Sisa ikut SL berjalan (pesan GESER SL). "
                "Tanpa jam ke-12 dan batas 30 jam.")
    else:
        blok = (SY.blok_salin(e, sl, tp1, tp2, "MARKET", t, sym=it["sym"], arah=it["arah"])
                + "\n📲 TP1 tutup 50% lalu SL ke entry.")
    skor = rincian_skor(k, it)
    try:
        import qse_klaster as KS          # v170 QC 66: skor klaster Tren (satu-satunya klaster yang lolos uji 2025 dan 2026)
        _kt = KS.baris(k, it)
        if _kt:
            skor = (skor + "\n" if skor else "") + _kt
    except Exception as ex:
        print("[WARN] klaster", ex)
    if prio:
        return (atas + f"🚀 <b>SINYAL JALUR LIVE: {it['sym']} {it['arah']}</b>  ·  {nama}" + (f"  ·  {' '.join(lab)}" if lab else "")
                + f"\n✅ Masuk daftar terbukti ({nm_prio}), dikirim tanpa ditahan. Catatan otak: {why}."
                + f"\n<b>{ik}</b>" + (f" ({alasan_kl})" if alasan_kl else "")
                + (f"\n{skor}" if skor else "")
                + (f"\n{cuaca}" if cuaca else "") + "\n"
                + blok + ("\n" + lot if lot else ""))
    alt = alternatif_limit(k, it)
    return (atas + f"🧠 <b>SINYAL JALUR EKS-TAHANAN OTAK: {it['sym']} {it['arah']}</b>  ·  {nama}" + (f"  ·  {' '.join(lab)}" if lab else "")
            + f"\n⚠️ Catatan otak: {why}. Tetap dikirim, kamu yang memilih. Uji: sinyal yang lolos otak PF 1.35, semua sinyal PF 1.23."
            + f"\n<b>{ik}</b> ({alasan_kl})"
            + (f"\n{skor}" if skor else "")
            + (f"\n{cuaca}" if cuaca else "") + "\n"
            + blok + (f"\n{alt}" if alt else "") + ("\n" + lot if lot else ""))


def kelas(k, it, prio=None):
    """('UTAMA'|'RINGAN', alasan). Permintaan user 9 Nov: RINGAN untuk EMA Cross SHORT koin baru, LONG saat kompas merah,
    dan sinyal eks-tahanan otak. Sisanya yang masuk daftar terbukti UTAMA."""
    if prio is None:
        prio = prioritas_live(k, it)[0]
    if it.get("jagoan"):
        try:
            import qse_jagoan as JG
            if JG.kelas_utama(it["jagoan"]):
                return "UTAMA", "👑 koin jagoan sejati"
        except Exception:
            pass
    # v175 QC 73: konfluensi 3+ teknik searah di koin yang sama = KELAS UTAMA (uji: -0.095 / +0.322 / +0.274 / +0.091R, WR 61%, PF 1.73)
    # v176 QC 74: 2+ teknik (bukan SHORT saat BTC 4J di atas EMA 50): +0.048 / +0.308 / +0.312 / +0.086R
    try:
        import qse_strat as ST_
        if ST_.konf_utama(it["arah"], it.get("btc_j"), len(it.get("combo") or []) + 1):
            return "UTAMA", f"⭐ konfluensi {len(it['combo']) + 1} teknik searah"
    except Exception:
        pass
    if it.get("netral_buka"):
        return "RINGAN", "BTC netral: arah ini dibuka tanpa izin BTC (uji tidak konsisten)"
    if (it.get("peringkat") or 0) > 110:
        return "RINGAN", f"teknik tunggal di koin peringkat likuiditas {it['peringkat']} (uji peringkat 111-150 PF 0.87)"
    if not prio:
        return "RINGAN", "sinyal eks-tahanan otak"
    try:
        import qse_klaster as KS
        if KS.lemah(KS.skor(k, it)):
            return "RINGAN", "skor Tren di bawah 20 (BTC, EMA 50, EMA 200 tidak mendukung arah ini)"
    except Exception:
        pass
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
    if k == "ema_short":          # QC 62: EMA Cross SHORT rugi 2026 (-128R) dan tidak ada saringan latih yang membaliknya
        return "RINGAN", "EMA Cross SHORT, rugi di 2026 (uji -128R), semua sinyalnya kelas ringan"
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
        if it.get("blokir_koin") or it.get("uji_live"):
            continue                      # QC 56: teknik ini rugi di koin ini. QC 74: kelompok uji live. Tidak dikirim sama sekali
        try:
            out.append(kartu(k, nama, it))
        except Exception as ex:
            print("[WARN] kartu ditahan", ex)
    d["kirim"] = {k: v for k, v in d["kirim"].items() if now - v < 7 * 86400}
    _tulis(d)
    return out
