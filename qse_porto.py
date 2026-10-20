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
"""
import time

MAKS_SEARAH = 16
LEMAH = {"smc_choch", "msb_hpz", "GZH"}          # PF terendah, hanya mengisi slot saat portofolio masih longgar
LEMAH_MAKS = 8
REM_DD_R, REM_RUGI = 32.0, 8              # 32R = 8% modal di risiko 0.25% per trade
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
    Return "senin", "akhir_pekan", atau ""."""
    d = time.gmtime(ts if ts is not None else time.time()).tm_wday
    return "senin" if d == 0 else "akhir_pekan" if d in (5, 6) else ""


def senin_tolak(combo, combo_emas):
    """Hari Senin hanya sinyal COMBO EMAS atau COMBO 3+. Return alasan tolak atau ''."""
    if hari() != "senin":
        return ""
    if combo_emas or len(combo or []) >= 2:
        return ""
    return "hari Senin, hanya COMBO EMAS atau COMBO 3+ yang dibuka (sinyal Senin lain PF 0.89)"


def lot_hari(lot_b):
    """Lot saran disesuaikan momen mingguan. Return (lot baru, baris catatan atau '')."""
    if hari() == "akhir_pekan":
        try:
            import qse_saya as SY
            return f"{SY.lot_angka(lot_b) / 2:g}x", ("📅 Akhir pekan: lot setengah. Uji 2021-2026 entry Sabtu-Minggu PF sekitar 0.9, "
                                                   "Selasa-Jumat PF 1.3-1.5")
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
    if n >= MAKS_SEARAH:
        return f"sudah {n} posisi {arah} robot di semua jalur, batas {MAKS_SEARAH}"
    if jalur in LEMAH and n >= LEMAH_MAKS:
        return f"jalur cadangan, hanya dibuka saat posisi {arah} robot kurang dari {LEMAH_MAKS} (sekarang {n})"
    return ""


def pesan(sym, arah):
    _RES[sym] = (arah, time.time())


def rem():
    """Rem gabungan: lot setengah saat hasil semua jalur turun lebih dari 32R (8% modal) dari puncak atau rugi 8 kali beruntun."""
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
           for a, n in (("LONG", nl), ("SHORT", ns)) if n >= MAKS_SEARAH]
    if rm:
        out.append(f"🛡 Rem aktif, pakai lot setengah: {rm}")
    return "\n".join(out)          # kosong saat normal, baris hanya muncul kalau mengubah tindakan kamu
