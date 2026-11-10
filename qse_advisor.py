"""QSE v170 ADVISOR MODE (QC 66, 10 Nov 2026, permintaan user). Sekali tiap candle 4J tutup, robot menjelaskan keputusannya:
berapa sinyal jalur baru yang dikirim, ditahan, dan diblokir, lalu merinci 2 sinyal yang ditahan (alasan, rincian skor, skor Tren) dan
memberi skenario alternatif lintas teknik: teknik lain yang rekam jejaknya paling baik di koin itu (hasil asli 8 jalur 2023-2026 dari
profil_koin.json, minimal 10 sinyal, PF di atas 1.3) dan pilihan Pending Limit. Ini pengganti Waterfall Routing: semua mesin (Trendline,
GZH, Order Block, Ichimoku, pola, lalat, Whip-Fade) sudah memindai semua koin secara paralel, jadi yang ditambahkan adalah petunjuk mesin
mana yang cocok saat satu teknik gagal di koin itu. Tidak ada sinyal baru yang dibuat modul ini, isinya penjelasan dan rujukan yang
angkanya berasal dari data uji. Matikan: QSE_ADVISOR=0."""
import json
import os
import time

from config import STATE_DIR

F = os.path.join(STATE_DIR, "advisor.json")
T2023 = 1672531200000
NAMA = {"ichimoku": "Ichimoku", "orderblock": "Order Block", "ema_short": "EMA Cross 20/50", "rsi_vol": "RSI 50 + Volume",
        "mcginley": "McGinley 34", "snr_vol": "SnR Pantul + Volume", "msb_hpz": "MSB HPZ", "smc_choch": "SMC CHoCH"}


def _baca():
    try:
        with open(F) as f:
            return json.load(f)
    except Exception:
        return {}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(F + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(F + ".tmp", F)


def teknik_cocok(sym, kecuali=None, maks=2):
    """Teknik + arah dengan rekam jejak terbaik di koin ini (2023-2026): list (jalur, arah, n, pf, total_r), urut PF."""
    import numpy as np
    import qse_otak as OT
    d = OT._profil_data()
    hitam = OT.hitam(sym) if hasattr(OT, "hitam") else None
    if hitam:
        return []
    out = []
    for nm in OT._nama_uji(sym):
        for key, rows in d["sinyal"].items():
            p = key.split("|")
            if p[0] != nm or (kecuali and (p[1], p[2]) == kecuali):
                continue
            r = np.array([x[1] for x in rows if x[0] >= T2023], float)
            if len(r) < 10:
                continue
            g, b = r[r > 0].sum(), -r[r < 0].sum()
            pf = g / b if b > 0 else 99.0
            if pf > 1.3 and r.sum() > 0:
                out.append((p[1], p[2], len(r), round(float(pf), 2), round(float(r.sum()), 1)))
        if out:
            break
    return sorted(out, key=lambda x: -x[3])[:maks]


def _rinci(k, nama, it):
    import qse_ditahan as DT
    rows = [f"{'🟢' if it['arah'] == 'LONG' else '🔴'} <b>{it['sym']} {it['arah']}</b>  ·  {nama}",
            f"⛔ {'Diblokir' if it.get('blokir_koin') else 'Ditahan'}: {it.get('otak_why') or 'peluang menurut otak robot rendah'}"]
    try:
        s = DT.rincian_skor(k, it)
        if s:
            rows.append(s)
        import qse_klaster as KS
        kt = KS.baris(k, it)
        if kt:
            rows.append(kt)
    except Exception as ex:
        print("[WARN] advisor skor", ex)
    try:
        alt = teknik_cocok(it["sym"], kecuali=(k, it["arah"]))
        if alt:
            rows.append("🔀 Skenario lain di koin ini: " + "  ·  ".join(
                f"{NAMA.get(j, j)} {a} (PF {pf:.2f}, {n} sinyal, {tot:+.1f}R)" for j, a, n, pf, tot in alt) + ". Tunggu sinyal teknik itu")
        else:
            rows.append("🔀 Skenario lain: belum ada teknik yang terbukti di koin ini (minimal 10 sinyal, PF di atas 1.3). Lebih baik lewati koin ini")
        if not it.get("blokir_koin"):
            lm = DT.alternatif_limit(k, it)
            if lm:
                rows.append(lm)
    except Exception as ex:
        print("[WARN] advisor alternatif", ex)
    return "\n".join(rows)


def _pasar():
    rows = []
    try:
        import qse_strat as ST
        bn = ST.btc_naik()
        if bn is True:
            rows.append("📈 BTC 4J di atas EMA 50: GZH mencari LONG (fib 0.618), jalur LONG kelas utama kalau skor Tren mendukung")
        elif bn is False:
            rows.append("📉 BTC 4J di bawah EMA 50: GZH mencari SHORT (fib 0.786, kelas ringan), EMA Cross SHORT kelas ringan")
    except Exception:
        pass
    try:
        import qse_kompas as KP
        k = KP.kompas()
        if k and k.get("status"):
            rows.append(f"🧭 Kompas: {k['status']}")
    except Exception:
        pass
    return rows


def susun(now=None, sumber=None):
    """Teks advisor untuk candle 4J yang baru tutup. sumber = list (k, nama, it), bawaan dari qse_ditahan._sumber()."""
    import qse_ditahan as DT
    now = now or time.time()
    c4 = int(now // 14400) * 14400
    baru = [(k, nm, it) for k, nm, it in (sumber if sumber is not None else DT._sumber()) if it.get("t", 0) >= c4 - 60]
    blokir = [x for x in baru if x[2].get("blokir_koin")]
    tahan = [x for x in baru if x[2].get("otak_saring") and not x[2].get("blokir_koin")]
    kirim = [x for x in baru if not x[2].get("otak_saring")]
    eks = [x for x in tahan if not DT.prioritas_live(x[0], x[2])[0]]
    rows = ["🎓 <b>QSE v170 | ADVISOR 4J</b>",
            f"Candle 4J tutup: {len(baru)} sinyal jalur baru. Dikirim penuh {len(kirim) + len(tahan) - len(eks)}, eks-tahanan kelas ringan {len(eks)}, "
            f"diblokir {len(blokir)}."]
    rows += _pasar()
    try:
        import qse_strat as ST
        urut = sorted(eks + blokir, key=lambda x: (not x[2].get("blokir_koin"), ST.prioritas(x[0], x[2])[0]), reverse=True)
    except Exception:
        urut = eks + blokir
    if urut:
        rows.append(f"\n<b>{min(2, len(urut))} sinyal yang ditahan, alasan dan skenario lain:</b>")
        for k, nm, it in urut[:2]:
            rows.append("\n" + _rinci(k, nm, it))
        if len(urut) > 2:
            rows.append(f"\nDitahan lainnya: " + ", ".join(f"{it['sym']} {it['arah']}" for _, _, it in urut[2:10]))
    elif not baru:
        rows.append("\nTidak ada sinyal jalur baru di candle ini. Mesin lain tetap memindai: Tembus Trendline, GZH, Sniper Koin Spesialis, "
                    "Whip-Fade 15 menit. Cek Sinyal 4J untuk antrean yang masih berlaku.")
    else:
        rows.append("\nTidak ada sinyal yang ditahan di candle ini.")
    return "\n".join(rows)


def jalankan(now=None):
    """Dipanggil tiap menit. Kirim sekali per candle 4J, menit 16-40 sesudah tutup (sesudah semua jalur selesai memindai)."""
    if os.environ.get("QSE_ADVISOR", "1") == "0":
        return []
    now = now or time.time()
    c4 = int(now // 14400) * 14400
    d = _baca()
    if d.get("c4") == c4 or not (960 <= now - c4 <= 2400):
        return []
    d["c4"] = c4
    _tulis(d)
    try:
        return [susun(now)]
    except Exception as ex:
        print("[WARN] advisor", ex)
        return []
