"""QSE v150 - RADAR (v175 QC 73, 11 Nov 2026, permintaan user).
1. Bubble terpisah: ringkasan pasar, satu koin satu bubble, lalu bubble 🧠 ANALISA OTAK BOT & SARAN GZH.
2. Scan otomatis tiap 1 jam memakai pindai paksa (7 teknik, Ichimoku, Order Block, GZH, konfluensi). QC 75: hanya konfluensi 2+ teknik
   (Kelas Utama) dari candle 4J terakhir yang dikirim, dengan keputusan tegas. Tidak ada sinyal: satu bubble radar berisi koin yang paling dekat ke pemicu. Sinyal yang sama tidak dikirim dua kali.
3. Batal sinyal yang sadar posisi: belum entry cukup kabar singkat, sudah entry diberi MANAJEMEN POSISI AKTIF dengan harga konkrit.
Saklar: QSE_RADAR_JAM=0 mematikan scan per jam, QSE_RADAR_SEPI=0 mematikan bubble radar saat tidak ada sinyal."""
import json
import os
import time

import telegram_notify as TG
from config import STATE_DIR

F = os.path.join(STATE_DIR, "radar.json")
MENIT_SCAN = 3          # scan per jam mulai menit ke-3
MENIT_SCAN_4J = 22      # di jam tutup candle 4J: sesudah siaran 4 jam selesai


def _baca():
    try:
        with open(F) as fh:
            d = json.load(fh)
    except Exception:
        d = {}
    d.setdefault("jam", 0); d.setdefault("kirim", {}); d.setdefault("kawal", {})
    return d


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = F + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(d, fh)
    os.replace(tmp, F)


def _wib(fmt="%H:%M", t=None):
    return time.strftime(fmt, time.gmtime((t or time.time()) + 7 * 3600))


# v177 QC 75b MOMENTUM BERPROSPEK (run_v177b.py, hasil_v177_momentum.txt): teknik tunggal yang diambil 1-3 jam sesudah candle 4J tutup,
# harga sudah bergerak searah sinyal 0 sampai 0.5R. Lolos: latih 2023-2024 positif, 2025 dan 2026 masing-masing positif, PF >= 1.3.
#   McGinley LONG jam 1 / 2 / 3: +0.057 / +0.099 / +0.158 / +0.231R (jam 1, PF 1.69), jam 2 PF 1.52, jam 3 PF 1.57
#   Order Block LONG jam 1 / 2 / 3: PF 1.43 / 1.39 / 1.56 (2023 sedikit minus, latih gabungan plus, 2025-2026 +0.12 sampai +0.34R)
#   Ichimoku LONG jam 1 / 2: PF 1.32 / 1.34 (jam 3 2026 -0.029R: tidak)
# Gagal: EMA Cross SHORT (2026 -0.12 sampai -0.14R), McGinley SHORT (latih minus), SMC CHoCH, SnR, MSB HPZ, RSI SHORT, Ichimoku SHORT.
# v180 QC 77 (permintaan user): momentum dibuka DUA ARAH untuk semua teknik terbukti. TERUJI = lolos uji di atas, boleh KELAS UTAMA.
# Sisanya (uji run_v177b tidak lolos: SHORT telat PF 0.69-1.36 dan tidak konsisten antar tahun) tetap dikirim tetapi KELAS RINGAN.
# Tambahan syarat untuk yang belum teruji: candle 1 jam terakhir tutup searah sinyal.
# v181 QC 78 (permintaan user: yang ujinya lemah tidak dipasang): QSE_MOMENTUM_KETAT bawaan 1, hanya yang lolos uji yang dikirim.
# Momentum SHORT telat dan intrabar selain McGinley LONG tidak dikirim. QSE_MOMENTUM_KETAT=0 mengirimnya lagi sebagai kelas ringan.
TERUJI = {("mcginley", "LONG"): (3.0, "PF 1.52-1.69"), ("orderblock", "LONG"): (3.0, "PF 1.39-1.56"), ("ichimoku", "LONG"): (2.0, "PF 1.32-1.34")}
MOMENTUM = dict(TERUJI)
for _k in ("mcginley", "orderblock", "ichimoku", "smc_choch", "msb_hpz", "snr_vol", "rsi_vol", "gzh"):
    for _a in ("LONG", "SHORT"):
        MOMENTUM.setdefault((_k, _a), (3.0, ""))
# INTRABAR (riset/upgrade/run_v179_intrabar.py, hasil_v179_intrabar.txt, 12.700 sinyal 2023-2026, candle 4J berjalan dicek tiap 1J tutup,
# aturan keluar live). McGinley LONG: semua +0.029 / +0.068 / +0.108 / +0.095R (PF 1.22), jam ke-3 +0.160 / +0.101 / +0.104 / +0.123R
# (PF 1.41), BTC searah +0.002 / +0.127 / +0.163 / +0.337R (PF 1.45), jam ke-1 PF 0.79. McGinley SHORT -0.144 / +0.018 / +0.114 /
# -0.075R (PF 0.96). RSI 50 LONG PF 1.10 (jam ke-3 PF 1.22, 2024 -0.061R), RSI 50 SHORT PF 1.01. Teknik lain belum diuji intrabar.
# McGinley LONG BTC searah per jam: jam ke-1 -0.221 / -0.183 / +0.419 / +0.628R (latih minus), jam ke-2 dan 3 gabungan +0.031 / +0.145 /
# +0.140 / +0.311R (PF 1.47).
# Jadi: McGinley LONG intrabar di jam ke-3, atau jam ke-2 saat BTC di atas EMA 50 = KELAS UTAMA. Intrabar lain = KELAS RINGAN.


def _c1_searah(sym, arah):
    """Candle 1 jam terakhir yang sudah tutup searah sinyal? None kalau data gagal (tidak menahan)."""
    try:
        import bybit_fetch as B
        d = B._raw(sym, "60", 4)
        d = d[d.index + 3600000 <= int(time.time() * 1000)]
        if not len(d):
            return None
        o, c = float(d["open"].iloc[-1]), float(d["close"].iloc[-1])
        return (c > o) if arah == "LONG" else (c < o)
    except Exception:
        return None


def kelas_intrabar(r, bj):
    """QC 77: sinyal di candle 4J yang masih berjalan. Menandai r["intrabar_ket"] dan kelasnya. Return True kalau layak dikirim."""
    if not r.get("intrabar") or r["mundur"]:
        return False
    utama = (r["k"], r["arah"]) == ("mcginley", "LONG") and (r["intrabar"] >= 3 or (r["intrabar"] >= 2 and bj is not None and bj > 0))
    if r.get("konf", 1) >= 2 and not r["ringan"]:
        utama = True
    if not utama:
        if os.environ.get("QSE_MOMENTUM_KETAT", "1") == "1" or _c1_searah(r["sym"], r["arah"]) is False:
            return False
        r["ringan"] = True
    r["intrabar_ket"] = f"jam ke-{r['intrabar']} candle 4J berjalan" + (", uji McGinley LONG intrabar PF 1.41-1.45" if utama and r["k"] == "mcginley" else "")
    return True


def momentum(r, now=None):
    """True kalau sinyal tunggal ini lolos MOMENTUM: teknik dan arah terdaftar, candle 4J terakhir, harga sudah bergerak searah (0 sampai
    0.5R), umur sejak candle tutup tidak lewat batas jam. Yang TERUJI dan bukan kelas ringan diberi label PF (r["momentum"]). Yang
    belum teruji wajib candle 1 jam terakhir searah, lalu dikirim sebagai KELAS RINGAN."""
    m = MOMENTUM.get((r["k"], r["arah"]))
    if not m or r["mundur"] or r.get("intrabar") or not (0 <= r["geser"] <= 0.5) or not r.get("t4"):
        return False
    jam = ((now or time.time()) - (r["t4"] / 1000 + 14400)) / 3600
    if jam > m[0] + 0.25:
        return False
    if m[1] and not r["ringan"]:
        r["momentum"] = m[1]
        return True
    if os.environ.get("QSE_MOMENTUM_KETAT", "1") == "1" or _c1_searah(r["sym"], r["arah"]) is False:
        return False
    r["ringan"] = True; r["momentum"] = "belum teruji, ukuran ringan"
    return True


def kelas_teks(r):
    return "🟨 KELAS RINGAN" if r["ringan"] else "🟦 KELAS UTAMA"


def kartu(r, no=None):
    """Satu sinyal = satu bubble. Keputusan tegas, level lengkap, tanpa daftar koin lain."""
    import qse_saya as SY
    tunggu = r["geser"] > 0.25
    kpt = f"⏳ PASANG LIMIT di {SY.fp(r['entry_robot'], r['tick'])}" if tunggu else "✅ AMBIL SEKARANG — MARKET"
    ket = [x for x in ("struktur ✅ valid searah", "candle terakhir" if not r["mundur"] else "candle sebelumnya",
                       ("🎯 spesialis " + r["arah"]) if r.get("spesialis") else "", ("🕯 " + r["pola"]) if r.get("pola") else "",
                       f"harga {abs(r['geser']):.1f}R {'lebih baik dari' if r['geser'] < 0 else 'di atas'} harga sinyal" if abs(r["geser"]) >= 0.1 else "",
                       "BTC netral" if r.get("netral") else "", f"likuiditas peringkat {r['peringkat']}" if r.get("luar") else "") if x]
    tek = f"<b>{TG.e(r['nama'])}</b>"
    if r.get("intrabar_ket"):
        tek += f"  ·  ⚡ INTRABAR ({r['intrabar_ket']})"
    elif r.get("momentum") and r.get("konf", 1) < 2:
        tek += (f"  ·  ⚡ MOMENTUM BERPROSPEK (harga sudah searah, uji 2023-2026 {r['momentum']})" if r["momentum"].startswith("PF") else
                f"  ·  ⚡ MOMENTUM (harga dan candle 1 jam searah, {r['momentum']})")
    if r.get("konf", 1) >= 2:
        tek += f"  ·  ⭐ KONFLUENSI {r['konf']} TEKNIK (+ {TG.e(', '.join(r['konf_nama']))})"
    px, o = (r["entry_robot"], "LIMIT") if tunggu else (r["px"], "MARKET")
    if r.get("tp"):
        blok = SY.blok_salin(px, r["sl"] + (px - r["px"]), r["tp"] + (px - r["px"]), r["tp"] + (px - r["px"]), o, r["tick"], sym=r["sym"], arah=r["arah"],
                             sebagian=True)
    else:
        blok = SY.blok_salin(px, r["sl"] + (px - r["px"]), order=o, tick=r["tick"], catatan_tp="tanpa, pakai SL berjalan", sym=r["sym"], arah=r["arah"],
                             sebagian=True)
    return (f"{'🟢' if r['arah'] == 'LONG' else '🔴'} <b>{r['sym']} {r['arah']}</b>  ·  {kelas_teks(r)}"
            + (f"  ·  #{no}" if no else "") + f"\n🏷 Teknik: {tek}\n🧭 Keputusan: <b>{kpt}</b>\nℹ️ " + "  ·  ".join(ket) + "\n" + blok
            + "\n📲 TP awal: tutup 20% lalu SL ke entry. Sisa posisi ikut SL berjalan.")


def pasar_teks(inf, judul, n_utama, n_ringan):
    import qse_strat as ST
    rows = [f"🛰 <b>QSE v150 | {judul} {_wib('%H:%M')} WIB</b>", ST.status_btc(inf.get("bj"), ambil=False)]
    try:
        vp = ST.vol_pasar()
        if vp:
            rows.append(f"💧 Likuiditas: volume BTC 4J {vp:.1f}x rata 30 hari" + (" (tinggi, sinyal lebih kuat)" if vp > 2.5 else " (sepi)" if vp < 0.6 else ""))
    except Exception:
        pass
    rows.append(f"🔎 {inf['n']}" + (f" dari {inf['total']}" if inf["n"] < inf["total"] else "") + f" koin Futures, 10 mesin + konfluensi, {inf['detik']:.0f} detik")
    rows.append(f"🎯 Hasil: <b>{n_utama} Kelas Utama</b>, {n_ringan} kelas ringan" + (". Tiap koin satu pesan di bawah." if n_utama + n_ringan else ""))
    return "\n".join(rows)


def otak_teks(sinyal=None, lewat=None, bj=None):
    """Bubble terakhir: 🧠 ANALISA OTAK BOT & SARAN GZH. sinyal = list dict(sym, arah, nama, ringan). Keputusan tegas untuk saat ini."""
    import qse_strat as ST
    sinyal = sinyal or []; lewat = lewat or []
    if bj is None:
        try:
            bj = ST.btc_jarak()
        except Exception:
            bj = None
    rows = ["🧠 <b>ANALISA OTAK BOT & SARAN GZH</b>"]
    # 1. arah pasar
    if bj is None:
        rows.append("• Pasar: data BTC belum tersedia")
    elif ST.btc_netral(bj):
        rows.append(f"• Pasar: BTC netral ({bj:+.1f}% dari EMA 50 4J). Tidak ada arah dominan, pilih koin dari struktur masing-masing")
    else:
        rows.append(f"• Pasar: BTC {'di atas' if bj > 0 else 'di bawah'} EMA 50 4J ({bj:+.1f}%). Arah utama {'LONG' if bj > 0 else 'SHORT'}")
    # 2. likuiditas
    try:
        vp = ST.vol_pasar()
        if vp:
            rows.append(f"• Likuiditas: volume BTC 4J {vp:.1f}x rata 30 hari, " + ("tinggi. Tembusan lebih bisa dipercaya" if vp > 2.5 else
                        "tipis. Tembusan rawan palsu, utamakan Limit" if vp < 0.6 else "normal"))
    except Exception:
        pass
    # 3. teknik dominan
    hit = {}
    for r in list(sinyal) + [x for x in lewat if "struktur berubah" not in x.get("why", "")]:
        hit[(r["nama"], r["arah"])] = hit.get((r["nama"], r["arah"]), 0) + 1
    if hit:
        top = sorted(hit.items(), key=lambda z: -z[1])[:2]
        rows.append("• Teknik dominan: " + ", ".join(f"{TG.e(n)} {a} ({v} koin)" for (n, a), v in top))
    else:
        try:
            import qse_overmind as OM
            pj = (OM._baca() or {}).get("pemimpin_jalur")
            if pj:
                rows.append(f"• Teknik dominan: belum ada pemicu di candle ini. Pemimpin 20 trade terakhir: {TG.e(str(pj))}")
        except Exception:
            pass
    ht = None
    try:
        import qse_nyawa as NY
        ht = NY.hati()
        rows.append(f"{ht['ikon']} Hati: <b>{ht['nama']}</b> ({ht['hp']:.0f}/100 HP). {ht['sebab']}")
    except Exception as ex:
        print("[WARN] radar hati", ex)
    # pikiran: satu kalimat penalaran dari fakta di atas
    try:
        vp_ = ST.vol_pasar()
        n_l = sum(1 for r in sinyal if r["arah"] == "LONG"); n_s = len(sinyal) - n_l
        if bj is None:
            pk = "data BTC belum lengkap, jadi saya hanya percaya sinyal yang punya 2 teknik searah"
        elif ST.btc_netral(bj):
            pk = ("BTC belum memilih arah. Uji saya: saat netral LONG untung di 4 tahun, SHORT rugi di 2023. " +
                  ("LONG saya dahulukan" if n_l >= n_s else "SHORT saya ambil hanya yang 2 teknik searah"))
        elif bj > 0:
            pk = "BTC di atas EMA 50, arus mendukung LONG. " + ("SHORT yang muncul saya anggap melawan arus, ukuran ringan" if n_s else "Saya menunggu pullback LONG, bukan mengejar harga")
        else:
            pk = "BTC di bawah EMA 50, arus mendukung SHORT. " + ("LONG yang muncul hanya pantulan, ambil untung cepat di TP awal" if n_l else "Saya menunggu pantulan untuk SHORT, bukan menjual di dasar")
        if vp_ and vp_ < 0.6:
            pk += ". Volume tipis, tembusan mudah gagal"
        elif vp_ and vp_ > 2.5:
            pk += ". Volume besar, gerakan ini punya tenaga"
        rows.append(f"💭 Pikiran: {pk}.")
    except Exception as ex:
        print("[WARN] radar pikiran", ex)
    # 4. saran GZH
    try:
        import qse_gzh2 as GZ
        d = GZ._baca(); st = GZ.rapor()
        mode = "LONG pantulan fib 0.618, TP fib 0.5" if (bj or 0) > 0 else "SHORT pantulan fib 0.786, TP 0.8R"
        buka = ", ".join(f"{it['sym'].replace('USDT', '')} {it.get('arah', 'LONG')}" for it in list(d["open"].values())[:4])
        rows.append(f"🟡 Saran GZH: cari {mode}. Posisi GZH jalan: {buka or 'kosong'}. Rekor live {st['n']} trade, WR {st['wr']:.0f}%, {st['tot']:+.2f}R")
    except Exception as ex:
        print("[WARN] radar gzh", ex)
    # 5. keputusan
    ut = [r for r in sinyal if not r.get("ringan")]; rg = [r for r in sinyal if r.get("ringan")]
    maks = (ht or {}).get("maks", 2)
    if ut:
        kp = (f"ambil {ut[0]['sym'].replace('USDT', '')} {ut[0]['arah']} sekarang dengan ukuran Kelas Utama"
              + (f", lalu {ut[1]['sym'].replace('USDT', '')} {ut[1]['arah']}" if len(ut) > 1 and maks > 1 else "")
              + f". Maksimal {maks} posisi baru di jam ini" + (". Kelas ringan dilewati dulu" if ht and ht["maks"] < 2 and rg else ""))
    elif rg and ht and ht["maks"] < 2:
        kp = f"tahan modal. Hanya ada kelas ringan ({rg[0]['sym'].replace('USDT', '')} {rg[0]['arah']}) dan hati robot sedang {ht['nama'].lower()}"
    elif rg:
        kp = f"boleh ambil {rg[0]['sym'].replace('USDT', '')} {rg[0]['arah']} dengan ukuran ringan. Belum ada Kelas Utama, jangan tambah ukuran"
    else:
        kp = "tahan modal. Belum ada pemicu yang lolos, jangan masuk tanpa sinyal. Kawal posisi yang sudah jalan"
    rows.append(f"🧭 <b>Keputusan sekarang:</b> {kp}.")
    if lewat:
        rows.append(f"⚪ Dilewati robot: {len(lewat)} pemicu (telat, batal, atau ditahan uji).")
    return "\n".join(rows)


def radar_teks(lewat, inf):
    """Tidak ada sinyal: koin yang paling dekat ke pemicu, supaya grup tahu apa yang sedang dipantau."""
    dekat = [r for r in lewat if "lari" in r["why"] or "melawan" in r["why"]]
    dekat.sort(key=lambda r: abs(r["geser"]))
    nm = []
    for r in dekat:
        z = f"{r['sym'].replace('USDT', '')} {r['arah']} ({r['nama']}, harga {abs(r['geser']):.1f}R dari pemicu)"
        if z not in nm:
            nm.append(z)
    kd = ""
    if len(nm) < 2:
        try:
            import qse_kandidat as KD
            import qse_strat as ST
            import bybit_fetch as B
            tk = B.get_tickers()
            syms = sorted(tk, key=lambda s: -tk[s]["turnover"])[:KD.MAKS_KOIN]
            cal = []
            for s in syms:
                for x in KD.cari(ST._k4(s, 120), KD.fokus()):
                    cal.append(dict(x, sym=s))
            cal.sort(key=lambda x: x["jarak"])
            for x in cal:
                z = f"{x['sym'].replace('USDT', '')} {x['arah']} ({x['teknik']}, {x['pemicu']})"
                if z not in nm:
                    nm.append(z)
                if len(nm) >= 2:
                    break
        except Exception as ex:
            print("[WARN] radar kandidat", ex)
    if nm:
        kd = "Saya memantau ketat " + " dan ".join(TG.e(z) for z in nm[:2]) + ". Kalau candle ini tutup konfirmasi, sinyalnya langsung saya kirim."
    else:
        kd = "Belum ada koin yang dekat ke pemicu. Saya tetap memindai semua mesin tiap jam."
    import qse_strat as ST
    return f"⚡ <b>Radar 1 Jam {_wib()} WIB</b>\n{ST.status_btc(inf.get('bj'), ambil=False)}\n{kd}"


def bubble(valid, lewat, inf, judul="SCAN 1 JAM", maks=6, hanya_utama=False, otak=True):
    """List bubble: [pasar, kartu..., otak]. hanya_utama: kelas ringan tidak ditampilkan."""
    tampil = [r for r in valid if not (hanya_utama and r["ringan"])][:maks]
    out = [pasar_teks(inf, judul, sum(1 for r in tampil if not r["ringan"]), sum(1 for r in tampil if r["ringan"]))]
    out += [kartu(r, no) for no, r in enumerate(tampil, 1)]
    if otak:
        out.append(otak_teks(tampil, lewat, inf.get("bj")))
    return out


def jalankan(now=None, paksa=False):
    """Dipanggil tiap menit oleh listener. Sekali per jam: pindai semua mesin, kirim sinyal BARU (belum pernah disiarkan) satu koin satu
    bubble. Tidak ada yang baru: satu bubble radar + analisa otak. Return list bubble (kosong kalau belum waktunya)."""
    if os.environ.get("QSE_RADAR_JAM", "1") == "0" and not paksa:
        return []
    now = now or time.time()
    jam = int(now // 3600); menit = int(now % 3600 // 60)
    jam4 = jam % 4 == 0          # jam tutup candle 4J (UTC kelipatan 4)
    d = _baca()
    if not paksa and (d["jam"] == jam or menit < (MENIT_SCAN_4J if jam4 else MENIT_SCAN) or menit > 50):
        return []
    d["jam"] = jam
    _tulis(d)          # ditandai dulu: gagal di tengah tidak mengulang pindai tiap menit
    import qse_strat as ST
    try:
        valid, lewat, inf = ST.pindai_sekarang(batas=120, intrabar=True)
    except Exception as ex:
        print("[WARN] radar pindai", ex)
        return []
    # v177 QC 75 (riset/upgrade/run_v177_jam.py, hasil_v177_jam.txt): scan 1 jam hanya KONFLUENSI 2+ teknik (Kelas Utama) dari candle 4J
    # terakhir. Masuk 1-3 jam sesudah tutup, harga masih dalam 0.5R: +0.041 / +0.262 / +0.302 / +0.027R (jam 1) sampai +0.032 / +0.317 /
    # +0.210 / +0.005R (jam 3), PF 1.46-1.58, untung 4 tahun. Teknik tunggal telat PF 1.14-1.25 (jam 1 2023 -0.033R), EMA Cross SHORT
    # tunggal 2026 -0.10R di semua jam, sinyal candle sebelumnya (5-7 jam) PF 1.30-1.41: tidak dikirim scan. QSE_RADAR_SEMUA=1 = semua.
    if os.environ.get("QSE_RADAR_SEMUA", "0") != "1":
        valid = [r for r in valid if (kelas_intrabar(r, inf.get("bj")) if r.get("intrabar") else
                                      ((not r["ringan"] and r.get("konf", 1) >= 2 and not r["mundur"]) or momentum(r, now)))]
    valid.sort(key=lambda r: (r["ringan"], -r["nilai"]))
    baru = []
    for r in valid:
        k = f"{r['sym']}|{r['arah']}"
        kl = "RINGAN" if r["ringan"] else "UTAMA"
        lama = d["kirim"].get(k) or [0, ""]
        lama = lama if isinstance(lama, list) else [lama, "UTAMA"]
        naik = kl == "UTAMA" and lama[1] == "RINGAN"          # QC 77: yang dulu dikirim kelas ringan boleh dikirim lagi saat naik Kelas Utama
        if now - lama[0] < 8 * 3600 and not naik:
            continue
        try:
            x = TG.siaran_cocok(r["sym"], r["arah"], r["px"], jam=8, tol=0.04, now=now)
            if x and not (kl == "UTAMA" and x.get("kelas") == "RINGAN"):
                d["kirim"][k] = [now, x.get("kelas") or "UTAMA"]          # sudah disiarkan lewat pesan 4 jam atau kartu jalur
                continue
        except Exception:
            pass
        baru.append(r)
    baru = baru[:6]
    for r in baru:
        d["kirim"][f"{r['sym']}|{r['arah']}"] = [now, "RINGAN" if r["ringan"] else "UTAMA"]
        if r.get("intrabar"):          # QC 83: kartu intrabar langsung punya posisi jalur, supaya /entry dan /status ikut aturan jalur
            try:
                ST.buka_radar(r, now)
            except Exception as ex:
                print("[WARN] radar buka jalur", r.get("sym"), ex)
    d["kirim"] = {k: t for k, t in d["kirim"].items() if now - (t[0] if isinstance(t, list) else t) < 2 * 86400}
    _tulis(d)
    if baru:
        return bubble(baru, lewat, inf, "SCAN 1 JAM", maks=6)
    if jam4 or os.environ.get("QSE_RADAR_SEPI", "1") == "0":
        return []          # jam tutup 4J: siaran 4 jam sudah membawa analisa otak
    return [radar_teks(lewat, inf) + "\n\n" + otak_teks([], lewat, inf.get("bj"))]


# ---------------- batal sinyal yang sadar posisi ----------------
def pemegang(sym, arah):
    """Siapa yang punya order atau posisi di koin dan arah ini. Return list (nama, it)."""
    import qse_saya as SY
    out = []
    for u in SY.daftar_pengguna():
        try:
            for it in SY._baca(SY._path_uid(u))["open"].values():
                if it.get("sym") == sym and it.get("arah") == arah and it.get("status") in ("MENUNGGU", "TERISI", "TP1"):
                    out.append((SY.nama_pengguna(u), it))
        except Exception as ex:
            print("[WARN] pemegang", ex)
    return out


def kelola_teks(nama_orang, it, teknik, tl, df=None):
    """MANAJEMEN POSISI AKTIF: sinyal asal posisi ini kehilangan struktur. Dua opsi dengan harga konkrit, satu yang disarankan."""
    import qse_saya as SY
    import qse_strat as ST
    sym, arah = it["sym"], it["arah"]; L = arah == "LONG"
    t = it.get("tick") or SY.tick_of(None, it["entry"])
    px = SY.harga_live(sym) or it["entry"]
    r = SY._r_at(it, px)
    sl_k, aman = None, None
    try:
        df = ST._k4(sym, 120) if df is None else df
        h, l, c = (df[x].values.astype(float) for x in ("high", "low", "close"))
        a = float(ST._atr(h, l, c)[-1]); e50 = float(ST._ema(c, 50)[-1])
        aman = bool((c[-1] > e50) if L else (c[-1] < e50))
        sl_k = (l[-1] - 0.2 * a) if L else (h[-1] + 0.2 * a)          # di balik ujung candle pembalikan
        if (L and (sl_k <= it["sl"] or sl_k >= px)) or (not L and (sl_k >= it["sl"] or sl_k <= px)):
            sl_k = None
    except Exception as ex:
        print("[WARN] kelola", sym, ex)
    st = "Overbought" if L else "Oversold"
    rows = [f"🛡 <b>MANAJEMEN POSISI AKTIF: {sym} {arah}</b>  ·  👤 {TG.e(nama_orang)}",
            f"• Fakta: {TG.e(tl['alasan'])} di candle 4J terakhir (sinyal {TG.e(teknik)}). Kejenuhan {st} {tl['jenuh']:.0f}%",
            f"• Posisi {r:+.2f}R di {SY.fp(px, t)}. Entry {SY.fp(it['entry'], t)}, SL {SY.fp(it['sl'], t)}"
            + ("" if aman is None else f". Struktur besar {'masih aman (harga di sisi benar EMA 50 4J)' if aman else 'melemah (harga sudah di sisi salah EMA 50 4J)'}")]
    a_ = (f"<b>Opsi A · Pertahankan, SL ketat</b>: geser SL ke {SY.fp(sl_k, t)} (di balik ujung candle pembalikan). Posisi tetap penuh"
          if sl_k else f"<b>Opsi A · Pertahankan</b>: SL tetap {SY.fp(it['sl'], t)}, jangan dilonggarkan. Posisi tetap penuh")
    if it.get("status") == "TP1":
        b_ = f"<b>Opsi B · Kunci hasil</b>: SL sudah di entry. Tutup 50% sisa posisi di market, sisanya ikut SL berjalan"
    elif r > 0.05:
        b_ = f"<b>Opsi B · Amankan modal</b>: geser SL ke entry {SY.fp(it['entry'], t)} sekarang, atau tutup 50% di market lalu SL ke entry"
    else:
        b_ = (f"<b>Opsi B · Kurangi muatan</b>: tutup 50% di market sekarang ({SY.fp(px, t)}), sisa pakai SL "
              f"{SY.fp(sl_k if sl_k else it['sl'], t)}. SL ke entry belum bisa karena posisi belum untung")
    pilih_b = bool(tl.get("darurat"))          # hanya pemicu yang teruji (pola lawan + kejenuhan 50%+ atau CHoCH / MSB lawan)
    rows += ["• " + a_, "• " + b_,
             "🧭 <b>Saran robot: Opsi " + ("B" if pilih_b else "A") + "</b>. "
             + ("Pola lawan datang bersama kejenuhan atau struktur lawan. Uji 2023-2026: menahan +0.16 / -0.05 / +0.21 / -0.13R, mengamankan +0.04R tiap tahun"
                if pilih_b else "Pola lawan saja belum cukup untuk keluar. Uji 2023-2026: menahan +0.07 sampai +0.35R, menutup +0.03R")]
    return "\n".join(rows)


def batal_teks(sym, arah, teknik, tl):
    """Pesan untuk satu sinyal yang strukturnya berubah. Return (jenis, teks): 'posisi' = bubble sendiri, 'ringkas' = digabung satu baris."""
    pg = pemegang(sym, arah)
    isi = [p for p in pg if p[1].get("status") in ("TERISI", "TP1")]
    antre = [p for p in pg if p[1].get("status") == "MENUNGGU"]
    out = [("posisi", kelola_teks(nm, it, teknik, tl)) for nm, it in isi]
    if antre:
        out.append(("posisi", f"⚪ <b>Batal Sebelum Entry: {sym} {arah}</b>  ·  👤 {TG.e(', '.join(nm for nm, _ in antre))}\n"
                              f"Order belum terisi dan struktur berubah ({TG.e(tl['alasan'])}). Batalkan order ini di Bybit, lalu tekan Batal order di Kelola Posisi."))
    if not pg:
        out.append(("ringkas", f"{sym.replace('USDT', '')} {arah} ({TG.e(teknik)}: {TG.e(tl['alasan'])})"))
    return out


def gabung_batal(hasil):
    """hasil = list (jenis, teks) dari batal_teks. Return list bubble: posisi satu-satu, yang belum entry jadi satu bubble singkat."""
    out = [t for j, t in hasil if j == "posisi"]
    rk = [t for j, t in hasil if j == "ringkas"]
    if rk:
        out.append("⚪ <b>Batal sebelum entry</b> (struktur berubah, dicoret dari daftar pantau): " + "  ·  ".join(rk[:8])
                   + (f" (+{len(rk) - 8} lagi)" if len(rk) > 8 else "") + "\nTidak ada posisi kamu di koin ini. Tidak perlu tindakan.")
    return out
