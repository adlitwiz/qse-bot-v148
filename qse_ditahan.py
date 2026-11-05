"""QSE v150 - kartu sinyal yang DITAHAN otak robot. Sebelumnya sinyal jalur yang ditahan otak (peluang rendah, profil koin belum lulus)
tetap dicatat di Jalur Live tapi tidak dikirim. Sekarang tiap posisi baru jalur yang ditahan dikirim sebagai kartu tersendiri,
dengan alasan penahanan dan lot kecil, supaya semua transaksi di laporan Jalur juga sampai ke Telegram.
Uji saringan otak (qse_otak.py): 2023-2026 semua sinyal PF 1.23, sesudah saringan PF 1.35. Sinyal yang ditahan rata-rata lebih lemah,
jadi lot kartu ini 0.1x. Sinyal ditahan yang didukung 3+ jalur lain diambil gurita (kartu gurita), tidak dikirim dua kali.
Matikan dengan env QSE_KIRIM_DITAHAN=0."""
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
    try:
        import qse_modal as MD
        lot = MD.baris_lot(e, sl, kali=LOT)
    except Exception:
        lot = ""
    why = it.get("otak_why") or "peluang menurut otak robot rendah"
    return (f"🧠 <b>SINYAL JALUR DITAHAN OTAK: {it['sym']} {it['arah']}</b>  ·  {nama}" + (f"  ·  {' '.join(lab)}" if lab else "")
            + f"\n⚠️ Ditahan karena: {why}. Dicatat robot di Jalur Live. Uji: sinyal yang lolos otak PF 1.35, semua sinyal PF 1.23.\n"
            + SY.blok_salin(e, sl, tp1, tp2, "MARKET", t, sym=it["sym"], arah=it["arah"])
            + f"\n📲 Lot kecil {LOT:g}x. TP1 tutup 50% lalu SL ke entry." + ("\n" + lot if lot else ""))


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
        if len(it.get("combo") or []) >= 3:
            continue                      # diambil gurita lewat cincin saraf
        try:
            out.append(kartu(k, nama, it))
        except Exception as ex:
            print("[WARN] kartu ditahan", ex)
    d["kirim"] = {k: v for k, v in d["kirim"].items() if now - v < 7 * 86400}
    _tulis(d)
    return out
