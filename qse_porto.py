"""Penjaga portofolio gabungan semua jalur terbukti (Ichimoku, Order Block, EMA, RSI, McGinley, SnR, MSB, SMC, GZH).

Uji 111 koin perp 4J, 2021-2026, biaya 0.15% plus funding, risiko 0.5% per trade:
- Tanpa batas gabungan (8 per jalur saja): sampai 46 posisi bersamaan, drawdown 112% modal, bulan terburuk -63%.
- Maks 8 posisi searah di semua jalur, SMC/MSB/GZH hanya saat posisi searah kurang dari 4, satu koin satu jalur,
  rem lot setengah saat hasil gabungan turun lebih dari 16R (8% modal) atau rugi 8 kali beruntun:
  6219 trade, PF 1.19, +244%, drawdown 16%, bulan terburuk -7%. Rasio profit/drawdown 6.9 -> 15.1,
  dev 2021-2023 dan uji 2024-2026 sama-sama naik.
Supaya sinyal lebih ramai: batas 16 posisi searah (jalur lemah saat kurang dari 8) dengan risiko 0.25% per trade.
  Sinyal 2.9 -> 4.6 per hari, hari tanpa sinyal 16% -> 8%, rasio profit/drawdown tetap (13.8), drawdown sekitar 19%.
  Rem 32R = 8% modal di risiko 0.25%.
Teknik tambahan (double top/bottom, head and shoulders, triangle, wedge, divergensi RSI) diuji 2017-2026:
  untung sendiri-sendiri, tapi di portofolio gabungan tidak menambah sinyal berarti dan rasio tidak naik. Tidak dipasang.

Upgrade 27 Okt 2026, batas pindah ke tiap orang (maks 5 posisi dari entry sendiri, qse_modal). Simulasi 2021-2026 sinyal
mode seimbang, satu orang ambil urut prioritas sampai 5 posisi, TP sebagian 20% di +0.5R lalu SL ke entry:
- Batas buku robot 16 searah + rem lot setengah (sebelumnya): total +146R, drawdown 41R, rasio 3.6.
  Buku robot berisi semua sinyal termasuk nilai rendah yang tidak dikirim, jadi slot 16 sering penuh oleh sinyal
  yang tidak pernah kamu lihat dan sinyal bagus sesudahnya ikut tertahan.
- Tanpa batas 16 (8 per jalur dan satu koin satu jalur tetap), tanpa rem: total +282R, drawdown 25R, rasio 11.1.
  2021-2023 rasio 1.9 -> 6.4, 2024-2026 2.9 -> 5.4. Sinyal terkirim 1.7 -> 2.2 per hari.
- Rem lot setengah menurunkan rasio di semua varian (rem 32R/8 rasio 7.9, 64R/12 rasio 7.1, rem per jalur 16R/6
  rasio 8.3, rem dari hasil orang sendiri 6R/5 sampai 10R/8 rasio 6.6 sampai 7.4). Jadi rem tidak dipakai lagi (REM_LOT).

Perputaran modal 27 Okt 2026 (qse_modal, riset/porto/pf_waktu3.py, populasi sinyal seperti bot live): posisi yang belum kena
TP 20% dalam 36 jam ditutup, posisi yang SL-nya sudah di entry tidak makan slot (maks 2 posisi aman). Satu orang 2021-2026:
+314R DD 28 PF 1.52 -> +393R DD 31 PF 1.63, selesai dalam 48 jam 62% -> 77%, slot terkunci rata-rata 60 -> 17 jam.
"""
import time

MAKS_SEARAH = 0          # 0 = tidak ada batas buku robot gabungan (diganti batas 5 posisi per orang)
LEMAH = {"smc_choch", "msb_hpz", "GZH"}
LEMAH_MAKS = 0
REM_DD_R, REM_RUGI = 32.0, 8              # 32R = 8% modal di risiko 0.25% per trade
REM_LOT = False          # rem lot setengah dimatikan 27 Okt 2026 (lihat uji di atas). True = nyalakan lagi semua rem jalur
BOBOT = {"GZH": 0.5}
_RES = {}            # reservasi posisi yang baru dibuka tapi belum tersimpan di catatan jalur


def _posisi():
    """Semua posisi robot terbuka di semua jalur. Return list (sym, arah, jalur)."""
    out = []
    try:
        import qse_ichimoku as IC
        out += [(v["sym"], v["arah"], "ichimoku") for v in IC.lihat()["open"].values()]
    except Exception as ex:
        print("[WARN] porto ichimoku", ex)
    try:
        import qse_ob as OB
        out += [(v["sym"], v.get("arah", "LONG"), "orderblock") for v in OB.lihat()["open"].values()]
    except Exception as ex:
        print("[WARN] porto orderblock", ex)
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            out += [(v["sym"], v["arah"], k) for v in ST.lihat(k)["open"].values()]
    except Exception as ex:
        print("[WARN] porto strategi", ex)
    return out


def hitung(arah):
    pos = _posisi()
    syms = {s for s, _, _ in pos}
    now = time.time()
    for s in [s for s, (_, t) in _RES.items() if now - t > 900 or s in syms]:
        _RES.pop(s, None)
    n = sum(1 for _, a, _ in pos if a == arah) + sum(1 for a, _ in _RES.values() if a == arah)
    return n, syms | set(_RES)


def hari(ts=None):
    """Momen tetap mingguan berdasarkan waktu entry (UTC). Uji 35 ribu sinyal jalur terbukti:
    Senin (07:00 WIB Senin s.d. 07:00 WIB Selasa) PF 1.05 di 2021-2023, 0.96 di 2024-2026, 1.13 di 2017-2020: lemah di semua
    periode, sinyal baru tidak dibuka. Sabtu-Minggu PF 1.08/0.90 dan 0.91/0.88 di 2021-2026 (tapi bagus di 2017-2020),
    jadi lot setengah. Selasa-Jumat PF 1.32-1.50. Hasil: rasio profit/drawdown 7.0 jadi 11.5, total profit tetap.
    Senin tetap boleh kalau COMBO EMAS atau COMBO 3+: PF 1.24 (2021-23 1.25, 2024-26 1.24), sinyal Senin tanpa label PF 0.89.
    Upgrade 27 Okt 2026: Senin juga boleh kalau berlabel BTC.D TURUN (lihat senin_tolak).
    Return "senin", "akhir_pekan", atau ""."""
    d = time.gmtime(ts if ts is not None else time.time()).tm_wday
    return "senin" if d == 0 else "akhir_pekan" if d in (5, 6) else ""


def senin_tolak(combo, combo_emas, combo_fix=None, dom_turun=False):
    """Hari Senin hanya sinyal COMBO EMAS, COMBO FIX, COMBO 3+, atau berlabel BTC.D TURUN. Return alasan tolak atau ''.
    BTC.D TURUN (27 Okt 2026, mode seimbang, cara keluar TP sebagian): sinyal Senin tanpa COMBO tapi berlabel BTC.D TURUN
    PF 2.02 (2021-23) dan 4.47 (2024-26), menang 74% dan 88%, konsisten di 2021-22, 2023-24, 2025-26 (PF 1.56, 3.85, 3.55).
    Sinyal Senin tanpa COMBO dan tanpa label itu tetap lemah (PF 0.91 dan 0.56), jadi tetap ditolak.
    Membuka label ini: total profit naik 10-11%, PF 1.47 jadi 1.50 dan 1.60 jadi 1.65, sekitar 2 sinyal tambahan per minggu."""
    if hari() != "senin":
        return ""
    if combo_emas or combo_fix or dom_turun or len(combo or []) >= 2:
        return ""
    return "hari Senin, hanya COMBO EMAS, COMBO 3+, atau label BTC.D TURUN yang dibuka (sinyal Senin lain PF 0.89)"


def lot_hari(lot_b, dom_turun=False):
    """Lot saran disesuaikan momen mingguan. Return (lot baru, baris catatan atau '').
    27 Okt 2026, mode seimbang, cara keluar TP sebagian: sinyal akhir pekan berlabel BTC.D TURUN PF 1.75 (2021-23) dan
    1.52 (2024-26), menang 78-79%, sinyal akhir pekan lain PF 1.18 dan 1.00. Jadi label BTC.D TURUN tetap lot penuh:
    total profit naik 1-3%, drawdown sama."""
    if hari() == "akhir_pekan":
        if dom_turun:
            return lot_b, ("📅 Akhir pekan, tapi berlabel BTC.D TURUN: lot penuh. Uji 2021-2026 akhir pekan BTC.D TURUN "
                           "PF 1.75 dan 1.52, sinyal akhir pekan lain 1.18 dan 1.00")
        try:
            import qse_saya as SY
            return f"{SY.lot_angka(lot_b) / 2:g}x", ("📅 Akhir pekan: lot setengah. Uji 2021-2026 sinyal akhir pekan PF 1.18 dan "
                                                   "1.00, Selasa-Jumat PF 1.3-2.4")
        except Exception:
            return lot_b, ""
    return lot_b, ""


def izin(sym, arah, jalur):
    """Alasan sinyal baru ditahan oleh batas portofolio atau momen mingguan, kosong bila boleh."""
    if hari() == "senin" and jalur == "GZH":
        return "hari Senin (07:00 WIB Senin s.d. 07:00 WIB Selasa): uji 2017-2026 sinyal Senin PF 0.96-1.13, sinyal baru tidak dibuka"
    n, syms = hitung(arah)
    if sym in syms:
        return "koin ini sudah dipegang jalur robot lain (satu koin satu jalur)"
    if MAKS_SEARAH and n >= MAKS_SEARAH:
        return f"sudah {n} posisi {arah} robot di semua jalur, batas {MAKS_SEARAH}"
    if LEMAH_MAKS and jalur in LEMAH and n >= LEMAH_MAKS:
        return f"jalur cadangan, hanya dibuka saat posisi {arah} robot kurang dari {LEMAH_MAKS} (sekarang {n})"
    try:
        # token unlock >= 1% pasokan dalam 7 hari: LONG baru ditahan (uji 2021-2026 PF 0.28, qse_unlock)
        import qse_unlock as UL
        u = UL.tolak_long(sym, arah)
        if u:
            return u
    except Exception as ex:
        print("[WARN] unlock izin", ex)
    return ""


def pesan(sym, arah):
    _RES[sym] = (arah, time.time())


def rem():
    """Rem gabungan: lot setengah saat hasil semua jalur turun lebih dari 32R (8% modal) dari puncak atau rugi 8 kali beruntun.
    Mati sejak 27 Okt 2026 (REM_LOT False): dengan batas 5 posisi per orang, rem menurunkan rasio profit/drawdown."""
    if not REM_LOT:
        return ""
    cl = []
    try:
        import qse_ichimoku as IC
        cl += [("ichimoku", c) for c in IC.lihat().get("closed", [])]
    except Exception:
        pass
    try:
        import qse_ob as OB
        cl += [("orderblock", c) for c in OB.lihat().get("closed", [])]
    except Exception:
        pass
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            cl += [(k, c) for c in ST.lihat(k).get("closed", [])]
    except Exception:
        pass
    eq = peak = 0.0
    rugi = 0
    for k, c in sorted(cl, key=lambda z: z[1].get("selesai", 0)):
        r = float(c.get("R", 0) or 0) * BOBOT.get(k, 1.0)
        eq += r
        peak = max(peak, eq)
        rugi = rugi + 1 if r < 0 else 0
    if peak - eq > REM_DD_R:
        return f"hasil gabungan semua jalur turun {peak - eq:.0f}R dari puncak"
    if rugi >= REM_RUGI:
        return f"semua jalur rugi {rugi} kali beruntun"
    return ""


def baris():
    """Baris status portofolio untuk laporan 4 jam, hanya saat batas penuh atau rem aktif."""
    pos = _posisi()
    nl = sum(1 for _, a, _ in pos if a == "LONG")
    ns = sum(1 for _, a, _ in pos if a == "SHORT")
    rm = rem()
    out = [f"⛔ Sinyal {a} baru ditahan: robot sudah pegang {n} posisi {a}, batas {MAKS_SEARAH}"
           for a, n in (("LONG", nl), ("SHORT", ns)) if MAKS_SEARAH and n >= MAKS_SEARAH]
    if rm:
        out.append(f"🛡 Rem aktif, pakai lot setengah: {rm}")
    return "\n".join(out)          # kosong saat normal, baris hanya muncul kalau mengubah tindakan kamu
