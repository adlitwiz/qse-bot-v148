"""QSE v150 KOIN JAGOAN (QC 60 dan 61, 10 Nov 2026, permintaan user). Pasangan 1 koin + 1 teknik + arah yang belum pernah kalah.
Rekor = hasil asli jalur v150 2023-2026 (profil_koin.json) + trade live robot sesudah data uji. Kalah = R < -0.05
(kena SL di entry dihitung impas, bukan kalah). Status dihitung ulang setiap kali dipakai, jadi kalah pertama mencopot mahkota.
 👑 JAGOAN SEJATI   : 4 pasangan 0 kalah di latih 2023-2024 (min 5 sinyal) DAN di uji 2025-2026. Otomatis KELAS UTAMA.
 👑 JUARA KONSISTEN (QC 62, masuk Jagoan Sejati): latih 2023-2024 n >= 8, WR >= 80%, PF > 2.5, untung 2025 dan 2026. 8 pasangan,
    6 SHORT 2 LONG. Otomatis KELAS UTAMA. Dicopot kalau rekor 2023-2026 + live di bawah WR 65% atau PF 2.0.
 👑 JAGOAN HISTORIS : pasangan lain di daftar profil_koin.json (min 5 sinyal 2023-2026, 0 kalah). Kelas asli.
 🔥 REKOR TAK TERKALAHKAN : pasangan di luar daftar yang sudah 5 menang atau lebih, 0 kalah. Kelas asli.
 🌱 BERPOTENSI JAGOAN : 1-4 menang, 0 kalah (koin baru seperti BEAT dan BLEND). Kelas asli.
Uji jujur (riset/upgrade/hasil_v167_jagoan.txt): dari 16 pasangan tak terkalahkan 2023-2024 hanya 4 yang tetap 0 kalah di 2025-2026,
dengan 2-5 sinyal uji per pasangan. Saklar env QSE_JAGOAN_UTAMA: 0 = tidak ada kelas naik, 1 = semua 👑 KELAS UTAMA,
selain itu (bawaan) hanya JAGOAN SEJATI."""
import os
import numpy as np

KALAH = -0.05
N_JAGOAN = 5
T2023 = 1672531200000
NAMA = {"ichimoku": "Ichimoku", "orderblock": "Order Block", "ema_short": "EMA Cross 20/50", "rsi_vol": "RSI 50 + Volume",
        "mcginley": "McGinley 34", "snr_vol": "SnR Pantul + Volume", "msb_hpz": "MSB HPZ", "smc_choch": "SMC CHoCH",
        "trendline": "Tembus Trendline Stop"}


JUARA_WR, JUARA_PF, JUARA_N = 0.65, 2.0, 8


def kelas_utama(s):
    """True kalau status jagoan ini dapat KELAS UTAMA."""
    if not s:
        return False
    sw = os.environ.get("QSE_JAGOAN_UTAMA", "sejati")
    if sw == "0":
        return False
    if sw == "1":
        return s.get("jenis") in ("SEJATI", "JUARA", "JAGOAN")
    return s.get("jenis") in ("SEJATI", "JUARA")


def _daftar():
    import qse_otak as OT
    j = OT._profil_data().get("jagoan") or {}
    return j.get("pasangan") or {}, set(j.get("sejati") or [])


def _juara():
    import qse_otak as OT
    return (OT._profil_data().get("jagoan") or {}).get("juara") or {}


def _rows(sym, jalur, arah, live=None):
    import qse_otak as OT
    d = OT._profil_data()
    if jalur == "trendline":          # QC 62: rekor Tembus Trendline Stop dari riset mesin DASBOR (tt_entry.py, 2023-2026)
        tr = (d.get("jagoan") or {}).get("trendline_riset") or {}
        for nm in OT._nama_uji(sym):
            if nm in tr:
                return np.array(tr[nm], float)
        return np.array([], float)
    rows = []
    for nm in OT._nama_uji(sym):
        rows = d["sinyal"].get(f"{nm}|{jalur}|{arah}") or []
        if rows:
            break
    r = [float(x[1]) for x in rows if int(x[0]) >= T2023]
    try:
        import qse_strat as ST
        live = OT._ledger() if live is None else live
        r += [float(ST.r_hasil(c)) for c in live if c.get("sym") == sym and c.get("jalur") == jalur and c.get("arah") == arah
              and float(c.get("selesai") or c["t"]) * 1000 > d.get("akhir_ms", 0)]
    except Exception as ex:
        print("[WARN] jagoan live", ex)
    return np.array(r, float)


def _pf(r):
    g, b = r[r > 0].sum(), -r[r < 0].sum()
    return float(g / b) if b > 0 else (99.0 if g > 0 else 0.0)


def _kunci(sym, jalur, arah, daftar):
    import qse_otak as OT
    for nm in OT._nama_uji(sym):
        if f"{nm}|{jalur}|{arah}" in daftar:
            return f"{nm}|{jalur}|{arah}"
    return None


def status(sym, jalur, arah, live=None):
    """dict(n, menang, kalah, impas, jenis). jenis 'SEJATI', 'JAGOAN' (historis), 'REKOR', 'POTENSI' atau None."""
    try:
        r = _rows(sym, jalur, arah, live)
        daftar, sejati = _daftar()
    except Exception as ex:
        print("[WARN] jagoan", sym, ex)
        return None
    n, kalah, menang = len(r), int((r < KALAH).sum()), int((r > 0).sum())
    jenis = None
    kj = _kunci(sym, jalur, arah, _juara())
    if kj:          # QC 62: juara konsisten, boleh kalah, mahkota bertahan selama WR >= 65% dan PF >= 2.0
        wr, pf_ = (menang / n if n else 0.0), _pf(r)
        ok = n >= JUARA_N and wr >= JUARA_WR and pf_ >= JUARA_PF
        return dict(n=n, menang=menang, kalah=kalah, impas=n - menang - kalah, jenis="JUARA" if ok else None, daftar=True, juara=True,
                    wr=round(wr * 100), pf=round(pf_, 2), r25=_juara()[kj].get("r25"), r26=_juara()[kj].get("r26"))
    key = _kunci(sym, jalur, arah, daftar)
    if n and not kalah:
        if key and n >= N_JAGOAN:
            jenis = "SEJATI" if key in sejati else "JAGOAN"
        elif menang >= N_JAGOAN:
            jenis = "REKOR"
        elif menang >= 1:
            jenis = "POTENSI"
    return dict(n=n, menang=menang, kalah=kalah, impas=n - menang - kalah, jenis=jenis, daftar=bool(key))


def tandai(k, it, mesin=None):
    """Isi it['jagoan'] dan kembalikan baris label kartu (list, kosong kalau tidak punya rekor). mesin = (win, loss) rekam jejak
    mesin DASBOR untuk Tembus Trendline, dipakai kalau koin tidak ada di riset."""
    s = status(it.get("sym", ""), k, it.get("arah", ""))
    if (not s or not s["jenis"]) and mesin and not (s or {}).get("n") and mesin[0] > 0 and mesin[1] == 0:
        s = dict(n=mesin[0], menang=mesin[0], kalah=0, impas=0, jenis="REKOR" if mesin[0] >= N_JAGOAN else "POTENSI", mesin=True)
    if not s or not s["jenis"]:
        return []
    it["jagoan"] = s
    rek = f"{s['menang']} menang, 0 kalah" + (f", {s['impas']} impas" if s["impas"] else "")
    tek = f"{NAMA.get(k, k)} {it['arah']}"
    kl = "Otomatis KELAS UTAMA" if kelas_utama(s) else "Kelas asli, belum dinaikkan"
    if s.get("mesin"):
        tek += " (rekam jejak mesin DASBOR)"
    if s["jenis"] == "JUARA":
        return [f"👑 <b>SINYAL KOIN JAGOAN SEJATI SISI {it['arah']} (JUARA KONSISTEN)</b>",
                f"Rekor koin ini di teknik {tek}: {s['n']} sinyal, WR {s['wr']}%, PF {s['pf']:.2f}, untung 2025 {s['r25']:+.1f}R dan "
                f"2026 {s['r26']:+.1f}R. {kl}"]
    if s["jenis"] == "SEJATI":
        return ["👑 <b>SINYAL KOIN JAGOAN SEJATI (BELUM PERNAH KALAH)</b>",
                f"Rekor koin ini di teknik {tek}: {rek}. Lulus 0 kalah di latih 2023-2024 dan uji 2025-2026. {kl}"]
    if s["jenis"] == "JAGOAN":
        return ["👑 <b>SINYAL KOIN JAGOAN (BELUM PERNAH KALAH)</b>",
                f"Rekor koin ini di teknik {tek}: {rek} (2023-2026 + live). Jagoan historis. {kl}"]
    if s["jenis"] == "REKOR":
        return ["🔥 <b>REKOR TAK TERKALAHKAN</b>", f"Rekor koin ini di teknik {tek}: {rek}. {kl}"]
    return [f"🌱 <b>BERPOTENSI JAGOAN</b> (Rekor: {s['menang']} Menang, 0 Kalah - Butuh {N_JAGOAN - s['menang']} kemenangan lagi "
            f"untuk jadi Jagoan)", f"Teknik {tek}. {kl}"]


def teks():
    """Isi menu 👑 Daftar Koin Jagoan: sejati, historis, pantauan live, dan mahkota yang dicopot."""
    import qse_otak as OT
    daftar, sejati = _daftar()
    try:
        live = OT._ledger()
    except Exception:
        live = []
    bag = {"SEJATI": [], "JAGOAN": [], "copot": [], "SHORT": [], "LONG": []}
    for key in _juara():
        sym, jalur, arah = key.split("|")
        s = status(sym, jalur, arah, live)
        if not s:
            continue
        baris = f"{sym.replace('USDT', '')} {arah} · {NAMA.get(jalur, jalur)}: {s['n']} sinyal, WR {s['wr']}%, PF {s['pf']:.2f}"
        bag[arah if s["jenis"] == "JUARA" else "copot"].append((-s["pf"], baris))
    for key, v in daftar.items():
        sym, jalur, arah = key.split("|")
        s = status(sym, jalur, arah, live)
        if not s or not s["n"]:          # Tembus Trendline: rekor dari riset mesin dasbor, tidak ada di profil sinyal
            s = dict(v, kalah=0, jenis="JAGOAN")
        baris = f"{sym.replace('USDT', '')} {arah} · {NAMA.get(jalur, jalur)}: {s['menang']} menang, {s['kalah']} kalah"
        bag[s["jenis"] if s["jenis"] in ("SEJATI", "JAGOAN") else "copot"].append((-s["n"], baris))
    pantau = {}
    for c in live:
        key = (c.get("sym"), c.get("jalur"), c.get("arah"))
        if not all(key) or key in pantau or _kunci(*key, daftar):
            continue
        s = status(*key, live=live)
        if s and s["jenis"] in ("REKOR", "POTENSI"):
            pantau[key] = s
    nomor = lambda xs: [f"{i}. {b}" for i, (_, b) in enumerate(sorted(xs), 1)] or ["Belum ada."]
    rows = ["👑 <b>DAFTAR KOIN JAGOAN</b> (1 koin + 1 teknik)",
            "\n<b>1. Koin Jagoan Sejati</b> (otomatis KELAS UTAMA)",
            "🔴 Sisi SHORT, juara konsisten (latih WR >= 80%, PF > 2.5, untung 2025 dan 2026):"]
    rows += nomor(bag["SHORT"])
    rows.append("🟢 Sisi LONG, juara konsisten:")
    rows += nomor(bag["LONG"])
    rows.append("✨ Tak terkalahkan (0 kalah di latih 2023-2024 dan uji 2025-2026):")
    rows += nomor(bag["SEJATI"])
    rows.append("\n<b>2. Koin Jagoan Historis</b> (0 kalah 2023-2026, minimal 5 sinyal, kelas asli)")
    rows += nomor(bag["JAGOAN"])
    rows.append(f"\n<b>3. Pantauan Berpotensi Jagoan Live</b> (trade live, 0 kalah, menuju {N_JAGOAN}-0)")
    if pantau:
        for k, s in sorted(pantau.items(), key=lambda x: -x[1]["menang"]):
            ik = "🔥" if s["jenis"] == "REKOR" else "🌱"
            sisa = "" if s["jenis"] == "REKOR" else f", butuh {N_JAGOAN - s['menang']} menang lagi"
            rows.append(f"{ik} {k[0].replace('USDT', '')} {k[2]} · {NAMA.get(k[1], k[1])}: {s['menang']} menang, 0 kalah{sisa}")
    else:
        rows.append("Belum ada.")
    if bag["copot"]:
        rows.append("\n❌ <b>Mahkota dicopot</b> (kalah pertama, atau juara konsisten turun di bawah WR 65% / PF 2.0)")
        rows += [f"• {b}" for _, b in sorted(bag["copot"])]
    rows.append("\nKalah = rugi lebih dari 0.05R. Kena SL di entry dihitung impas. Uji kelompok: pasangan WR >= 80% di latih tidak lebih baik dari sinyal lain di 2025-2026, daftar juara dipilih dengan melihat 2025-2026.")
    return "\n".join(rows)
