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
MOMENTUM = {("mcginley", "LONG"): (3.0, "PF 1.52-1.69"), ("orderblock", "LONG"): (3.0, "PF 1.39-1.56"), ("ichimoku", "LONG"): (2.0, "PF 1.32-1.34")}


def momentum(r, now=None):
    """True kalau sinyal tunggal ini lolos MOMENTUM BERPROSPEK: teknik dan arah terdaftar, candle terakhir, harga sudah bergerak searah
    (0 sampai 0.5R), umur sejak candle 4J tutup tidak lewat batas jam teknik itu, bukan kelas ringan. Menandai r["momentum"]."""
    m = MOMENTUM.get((r["k"], r["arah"]))
    if not m or r["mundur"] or r["ringan"] or not (0 <= r["geser"] <= 0.5) or not r.get("t4"):
        return False
    jam = ((now or time.time()) - (r["t4"] / 1000 + 14400)) / 3600
    if jam > m[0] + 0.25:
        return False
    r["momentum"] = m[1]
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
    if r.get("momentum") and r.get("konf", 1) < 2:
        tek += f"  ·  ⚡ MOMENTUM BERPROSPEK (harga sudah searah, uji 2023-2026 {r['momentum']})"
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
    rows.append(f"🎯 Hasil: <b>{n_utama} Kelas Utama</b>, {n_ringan} momentum" + (". Tiap koin satu pesan di bawah." if n_utama + n_ringan else ""))
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
    try:
        import qse_nyawa as NY
        hp = NY._baca()["hp"]
        rows.append(f"• Nyawa robot {hp:.0f}/100 HP" + (". Kondisi tertekan: ambil hanya Kelas Utama" if hp < 60 else ""))
    except Exception:
        pass
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
    if ut:
        kp = (f"ambil {ut[0]['sym'].replace('USDT', '')} {ut[0]['arah']} sekarang dengan ukuran Kelas Utama"
              + (f", lalu {ut[1]['sym'].replace('USDT', '')} {ut[1]['arah']}" if len(ut) > 1 else "") + ". Maksimal 2 posisi baru di jam ini")
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
    out = [pasar_teks(inf, judul, sum(1 for r in tampil if not r["ringan"] and not r.get("momentum")),
                      sum(1 for r in tampil if r["ringan"] or r.get("momentum")))]
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
        valid, lewat, inf = ST.pindai_sekarang(batas=120)
    except Exception as ex:
        print("[WARN] radar pindai", ex)
        return []
    # v177 QC 75 (riset/upgrade/run_v177_jam.py, hasil_v177_jam.txt): scan 1 jam hanya KONFLUENSI 2+ teknik (Kelas Utama) dari candle 4J
    # terakhir. Masuk 1-3 jam sesudah tutup, harga masih dalam 0.5R: +0.041 / +0.262 / +0.302 / +0.027R (jam 1) sampai +0.032 / +0.317 /
    # +0.210 / +0.005R (jam 3), PF 1.46-1.58, untung 4 tahun. Teknik tunggal telat PF 1.14-1.25 (jam 1 2023 -0.033R), EMA Cross SHORT
    # tunggal 2026 -0.10R di semua jam, sinyal candle sebelumnya (5-7 jam) PF 1.30-1.41: tidak dikirim scan. QSE_RADAR_SEMUA=1 = semua.
    if os.environ.get("QSE_RADAR_SEMUA", "0") != "1":
        valid = [r for r in valid if (not r["ringan"] and r.get("konf", 1) >= 2 and not r["mundur"]) or momentum(r, now)]
    baru = []
    for r in valid:
        k = f"{r['sym']}|{r['arah']}"
        if now - d["kirim"].get(k, 0) < 8 * 3600:
            continue
        try:
            if TG.siaran_cocok(r["sym"], r["arah"], r["px"], jam=8, tol=0.04, now=now):
                d["kirim"][k] = now          # sudah disiarkan lewat pesan 4 jam atau kartu jalur
                continue
        except Exception:
            pass
        baru.append(r)
    baru = baru[:5]
    for r in baru:
        d["kirim"][f"{r['sym']}|{r['arah']}"] = now
    d["kirim"] = {k: t for k, t in d["kirim"].items() if now - t < 2 * 86400}
    _tulis(d)
    if baru:
        return bubble(baru, lewat, inf, "SCAN 1 JAM", maks=5)
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
