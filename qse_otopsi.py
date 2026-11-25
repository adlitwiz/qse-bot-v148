"""QC 104 🔬 OTOPSI RUGI. Tiap posisi yang selesai rugi (SL atau cutloss) dianalisa robot dari data, lalu diberi kesimpulan dan
satu blok PROMPT siap salin untuk dikirim ke Opus sebagai bahan perbaikan sistem.

Yang dihitung dari candle 1 jam Bybit selama posisi jalan: untung tertinggi yang sempat dicapai (MFE, dalam R), rugi terdalam (MAE),
jam ke berapa puncaknya, lama posisi, gerak BTC selama posisi dan apakah melawan arah, gerak koin dibanding BTC.
Dari catatan: teknik, kelas, jumlah teknik searah, jarak kolam stop, peringkat koin, hasil 10 trade terakhir teknik itu dan koin itu.
Kesimpulan = pola yang cocok dari daftar tetap (bukan tebakan bebas), supaya tiap temuan bisa diuji ulang di data.
Tidak ada aturan trading yang berubah otomatis dari otopsi: perubahan aturan tetap harus lolos uji latih, uji, 12 bulan, 6 bulan.
Saklar QSE_OTOPSI=0 mati. QSE_OTOPSI_R (bawaan -0.15): hasil lebih jelek dari ini yang diotopsi."""
import html
import os
import time

BATAS_R = float(os.environ.get("QSE_OTOPSI_R", "-0.15"))
UMUR_JAM = 12
JAM = 3600000


def hidup():
    return os.environ.get("QSE_OTOPSI", "1") != "0"


def _wib(ms):
    return time.strftime("%d/%m %H:%M", time.gmtime(ms / 1000 + 7 * 3600))


def jalur_harga(it, ambil=None, ambil4=None):
    """Statistik jalur harga selama posisi. ambil(sym, n) -> DataFrame candle 1 jam (index ms). Return dict atau {}."""
    try:
        if ambil is None:
            import bybit_fetch as B
            ambil = lambda s, n: B._raw(s, "60", n)
        t0 = int(it.get("fill_ts") or it.get("created_ts") or 0)
        t1 = int(it.get("closed_ts") or time.time() * 1000)
        if not t0 or t1 <= t0:
            return {}
        n = int(min(900, (time.time() * 1000 - t0) / JAM + 4))
        df = ambil(it["sym"], n)
        df = df[(df.index + JAM > t0) & (df.index <= t1)]
        if not len(df):
            return {}
        L = it["arah"] == "LONG"
        e = float(it["entry"])
        risk = float(it.get("risk0") or abs(e - float(it.get("sl0") or it["sl"])) or 1e-12)
        hi, lo = df["high"].values.astype(float), df["low"].values.astype(float)
        fav = (hi - e) / risk if L else (e - lo) / risk
        adv = (lo - e) / risk if L else (e - hi) / risk
        out = dict(mfe=float(max(fav.max(), 0.0)), mae=float(min(adv.min(), 0.0)), jam_mfe=int(fav.argmax()) + 1,
                   lama=(t1 - t0) / JAM, koin_pct=(float(df["close"].iloc[-1]) / e - 1) * 100)
        try:
            b = ambil("BTCUSDT", n)
            b = b[(b.index + JAM > t0) & (b.index <= t1)]
            if len(b):
                out["btc_pct"] = (float(b["close"].iloc[-1]) / float(b["open"].iloc[0]) - 1) * 100
                out["btc_maks_lawan"] = float(((b["low"].min() if L else b["high"].max()) / float(b["open"].iloc[0]) - 1) * 100)
        except Exception as _ex:
            __import__("config").diam("qse_otopsi.py:56", _ex)
        try:          # QC 109: kondisi jenuh sebelum masuk (RSI 14 candle 4J, gerak 72 jam searah sinyal)
            n4 = int(min(900, (time.time() * 1000 - t0) / (4 * JAM) + 60))
            c4 = ambil4(it["sym"], n4) if ambil4 else __import__("bybit_fetch")._raw(it["sym"], "240", n4)
            c4 = c4[c4.index + 4 * JAM <= t0]["close"].values.astype(float)
            if len(c4) >= 30:
                import numpy as _np
                dl = _np.diff(c4); up = _np.where(dl > 0, dl, 0.0); dn = _np.where(dl < 0, -dl, 0.0); au = up[:14].mean(); ad = dn[:14].mean()
                for a_, b_ in zip(up[14:], dn[14:]):
                    au = (au * 13 + a_) / 14; ad = (ad * 13 + b_) / 14
                out["rsi4"] = float(100 - 100 / (1 + au / max(ad, 1e-12)))
                out["gerak72"] = float((c4[-1] / c4[-19] - 1) * 100 * (1 if L else -1))
        except Exception as _ex:
            __import__("config").diam("qse_otopsi.py:69", _ex)
        return out
    except Exception as ex:
        print("[WARN] otopsi jalur harga", it.get("sym"), ex)
        return {}


def riwayat(it, closed):
    """Hasil 10 trade selesai terakhir di teknik yang sama dan di koin yang sama (sebelum trade ini)."""
    t = it.get("closed_ts") or 0
    lama = [c for c in closed if c.get("result_r") is not None and (c.get("closed_ts") or 0) < t and c.get("status") != "BATAL"]
    def ring(x):
        x = x[-10:]
        if not x:
            return None
        r = [c["result_r"] for c in x]
        return dict(n=len(r), wr=sum(1 for v in r if v > 0) / len(r) * 100, tot=sum(r))
    beruntun = 0
    for c in reversed(lama):
        if c["result_r"] < 0:
            beruntun += 1
        else:
            break
    return dict(jalur=ring([c for c in lama if c.get("jalur") == it.get("jalur")]),
                koin=ring([c for c in lama if c.get("sym") == it.get("sym")]), beruntun=beruntun)


def temuan(it, jh, rw):
    """Daftar (kode, kalimat) pola rugi yang cocok. Kode dipakai untuk rekap dan pengujian ulang."""
    out = []
    L = it["arah"] == "LONG"
    mfe = jh.get("mfe")
    if mfe is not None:
        if mfe >= 0.5:
            out.append(("BALIK_SESUDAH_TP1", f"Sempat untung {mfe:+.2f}R (lewat TP1 +0.5R) lalu berbalik. Cek apakah TP 20% dan SL ke entry sudah dijalankan."))
        elif mfe >= 0.3:
            out.append(("BALIK_SEBELUM_TP1", f"Sempat untung {mfe:+.2f}R di jam ke-{jh['jam_mfe']} lalu berbalik sebelum TP1. "
                        "Uji v203: mengunci profit di +0.3R atau +0.4R menurunkan total di 4 periode, jadi ini biaya wajar aturan."))
        elif mfe < 0.1:
            out.append(("LANGSUNG_SALAH", f"Hampir tidak pernah untung (tertinggi {mfe:+.2f}R). Arah atau waktu masuk salah sejak awal."))
    if jh.get("lama") is not None and jh["lama"] <= 4:
        out.append(("SL_CEPAT", f"Selesai dalam {jh['lama']:.1f} jam. Rugi secepat ini biasanya masuk telat atau masuk saat harga sedang liar."))
    bp = jh.get("btc_pct")
    if bp is not None:
        lawan = -bp if L else bp
        if lawan >= 1.5:
            out.append(("BTC_MELAWAN", f"BTC bergerak {bp:+.2f}% selama posisi, melawan {it['arah']}. Rugi ikut arus pasar, bukan salah koin."))
        elif abs(bp) < 0.7:
            kp = jh.get("koin_pct") or 0
            if (kp < 0) == L and abs(kp) >= 2:
                out.append(("KOIN_SENDIRI", f"BTC hampir diam ({bp:+.2f}%) tapi koin bergerak {kp:+.2f}%. Rugi dari koin itu sendiri."))
        elif lawan <= -0.7:          # QC 141: BTC searah posisi, koin melawan (kasus HMSTR)
            kp = jh.get("koin_pct") or 0
            if (kp < 0) == L and abs(kp) >= 2:
                out.append(("VONIS_BENAR_KOIN_LAWAN", f"Arah pasar benar: BTC {bp:+.2f}% searah {it['arah']}. Tapi koin bergerak {kp:+.2f}% "
                            "melawan pasar. Rugi dari koin itu sendiri, bukan dari salah baca arah."))
    try:          # QC 141: koin liar (ATR 4J >= 3.5%)
        import qse_liar as LI
        ya_, x_ = LI.liar(it["sym"], jh.get("df4"))
        if ya_:
            out.append(("KOIN_LIAR", f"Koin liar: gerak rata-rata {x_:.1f}% per candle 4J (ambang {LI.AMBANG:g}%). Kelompok ini menang 34-36%, "
                        "PF 1.14 di uji dan 0.94 di 6 bulan terakhir."))
    except Exception as _ex:
        __import__("config").diam("qse_otopsi.py:132", _ex)
    rs, g72 = jh.get("rsi4"), jh.get("gerak72")
    if rs is not None and ((not L and rs <= 35) or (L and rs >= 70)):
        out.append(("JENUH", f"Masuk {it['arah']} saat RSI 4J {rs:.0f} (sudah {'jenuh jual' if not L else 'jenuh beli'}), gerak 72 jam searah "
                    f"{g72:+.1f}%. Uji v221: SHORT saat RSI 4J <= 35 PF 1.55 di 2022-2024 tapi 0.87 (12 bulan) dan 0.66 (6 bulan)."
                    if not L else f"Masuk LONG saat RSI 4J {rs:.0f}. Uji v221: LONG di RSI >= 70 justru lebih bagus (PF 1.8-3.7), jadi ini bukan sebab."))
    k = it.get("kolam")
    if k is not None and k < 0.8:
        out.append(("RAWAN_SAPU", f"Swing 20 candle 4J hanya {k:.1f}R dari entry. Kelompok ini PF 0.59-0.80 di uji v203."))
    bj = it.get("btc_j")
    if bj is not None and ((bj < 0) == L) and abs(bj) >= 1:
        out.append(("LAWAN_SISI_BTC", f"Masuk {it['arah']} saat BTC 4J {bj:+.1f}% dari EMA 50 (melawan sisi BTC)."))
    if str(it.get("kelas") or "").upper() == "RINGAN":
        out.append(("KELAS_RINGAN", "Sinyal kelas ringan. Kelompok ini memang lebih lemah di uji, ukuran seharusnya 0.2x."))
    if str(it.get("jalur") or "manual") == "manual":
        out.append(("MANUAL", "Entry manual, bukan sinyal robot. Tidak ada angka uji untuk entry ini."))
    if it.get("serok"):
        out.append(("SEROK", f"Posisi ditambah {len(it['serok'])} kali saat jalan. Menambah saat minus memperbesar rugi di SL."))
    if it.get("sl_manual"):
        out.append(("SL_DIUBAH", "SL diubah manual dari SL sinyal."))
    if rw.get("beruntun", 0) >= 2:
        out.append(("RUGI_BERUNTUN", f"Ini rugi ke-{rw['beruntun'] + 1} berturut-turut."))
    j = rw.get("jalur")
    if j and j["n"] >= 5 and j["tot"] < -1:
        out.append(("TEKNIK_LEMAH_LIVE", f"Teknik ini di 10 trade terakhir: WR {j['wr']:.0f}%, total {j['tot']:+.2f}R."))
    kk = rw.get("koin")
    if kk and kk["n"] >= 3 and kk["tot"] < -1.5:
        out.append(("KOIN_LEMAH_LIVE", f"Koin ini di {kk['n']} trade terakhir: WR {kk['wr']:.0f}%, total {kk['tot']:+.2f}R."))
    if not out:
        out.append(("TANPA_POLA", "Tidak cocok dengan pola rugi yang dikenal. Rugi biasa dari sinyal yang valid."))
    return out


def _tp_teks(it, fp):
    """QC 125: TP yang tidak masuk akal (jalur tanpa TP tetap, misal EMA Cross) tidak ditampilkan sebagai angka palsu."""
    e = float(it.get("entry") or 0); L = it.get("arah") == "LONG"; out = []
    for nm in ("tp1", "tp2"):
        v = it.get(nm)
        if v and e and ((v > e) if L else (v < e)) and abs(v / e - 1) < 0.5:
            out.append(f"{nm.upper()} {fp(v)}")
    return ", ".join(out) if out else "tanpa TP tetap (SL berjalan)"


def _lengkapi(it):
    """QC 128: konteks masuk (BTC 4J dari EMA 50, kolam stop, combo, mutu) diambil dari buku sinyal jalur yang sama
    (koin dan arah sama, sinyal paling dekat sebelum entry, maks 48 jam). Dulu tampil '-' karena catatan posisi tidak membawanya."""
    if it.get("btc_j") is not None and it.get("kolam") is not None:
        return it
    try:
        import qse_strat as ST
        t0 = int(it.get("fill_ts") or it.get("created_ts") or 0) / 1000
        k = ST.kunci_jalur(it.get("jalur") or "") if it.get("jalur") else ""
        calon = []
        for kk in ([k] if k in ST.STRAT else list(ST.STRAT)):
            d = ST.lihat(kk)
            for v in list(d.get("open", {}).values()) + d.get("closed", []):
                if v.get("sym") == it["sym"] and v.get("arah") == it["arah"] and 0 <= t0 - float(v.get("t", 0)) <= 48 * 3600:
                    calon.append(v)
        if calon:
            v = max(calon, key=lambda x: float(x.get("t", 0)))
            it = dict(it)
            for f in ("btc_j", "kolam", "combo", "mutu"):
                if it.get(f) is None and v.get(f) is not None:
                    it[f] = v[f]
            if isinstance(it.get("btc_j"), float):
                it["btc_j"] = round(it["btc_j"], 2)
    except Exception as ex:
        print("[WARN] otopsi lengkapi", ex)
    if it.get("btc_j") is None:          # QC 136: konteks masuk tidak tercatat, pakai posisi BTC saat otopsi (ditandai)
        try:
            import qse_strat as ST_
            b_ = ST_.btc_jarak()
            if b_ is not None:
                it = dict(it, btc_j_kini=round(float(b_), 2))
        except Exception as _ex:
            __import__("config").diam("qse_otopsi.py:207", _ex)
    try:          # QC 136: skor kartu sinyal asal dari log siaran (kartu yang dikirim robot)
        if it.get("skor100") is None:
            import telegram_notify as TG_
            t0 = int(it.get("fill_ts") or it.get("created_ts") or 0) / 1000
            x = TG_.siaran_cocok(it["sym"], it["arah"], it.get("entry"), jam=48, tol=0.05, now=t0 + 600 if t0 else None)
            if x and x.get("skor") is not None:
                it = dict(it, skor100=int(x["skor"]))
    except Exception as ex:
        print("[WARN] otopsi skor", ex)
    return it


# QC 141 STATUS RISET: tiap pola sudah diuji atau belum. Otopsi berikutnya langsung tahu jawabannya, prompt hanya meminta uji pola yang
# BELUM diuji. None = belum diuji. Angka = selisih total R kalau aturan dipasang (latih / uji / 12 bulan / 6 bulan).
RISET = {
    "JENUH": "v221 + v259: SHORT saat BTC 4J <= -3% dari EMA 50 lot 0.5x +134.7 / +4.9 / +3.9 / -5.2R, gagal di 6 bulan. "
             "SHORT saat BTC <= -5% justru PF 3.44 di 6 bulan.",
    "RUGI_BERUNTUN": "v216: lot 0.5x sesudah 3 rugi beruntun per teknik, profit uji turun 348R. Ditolak.",
    "KOIN_SENDIRI": "v216 + v259: lot 0.5x saat koin melawan BTC, profit uji turun 100-113R. Ditolak.",
    "VONIS_BENAR_KOIN_LAWAN": "v259: koin naik saat BTC turun (atau sebaliknya) sebelum masuk, lot 0.5x profit uji turun 100.5R. Ditolak. "
                              "Aturan keluar saat koin melawan BTC selama posisi: BELUM diuji.",
    "BTC_MELAWAN": "v250: tutup saat BTC melawan 1.5-3%, profit turun di 3-4 periode. Ditolak.",
    "LANGSUNG_SALAH": "v216: potong cepat di jam ke-2 sampai ke-6 kalau belum pernah +0.1R, hampir semua variasi menurunkan profit. Ditolak.",
    "SL_CEPAT": "v216: sama dengan LANGSUNG_SALAH, potong cepat menurunkan profit. Ditolak.",
    "BALIK_SEBELUM_TP1": "v203: kunci profit di +0.3R atau +0.4R menurunkan total di 4 periode. Ditolak.",
    "BALIK_SESUDAH_TP1": "v239 sampai v242: TP 35%, TP 50% saat melemah, TP di +1R/+2R/+3R. Hanya TP LONG di +1R yang lolos (QC 127).",
    "KOIN_LIAR": "v260 + v261: kelompok ini lebih lemah, tapi menaikkan WR dengan TP lebih awal membuat WR 50% dan profit latih turun 20-48R. "
                 "Ditandai saja (QC 141).",
    "KELAS_RINGAN": "v216: SHORT 1 teknik lot 0.5x, profit uji turun 288R. Ditolak.",
    "TEKNIK_LEMAH_LIVE": "v216: kurangi lot sesudah teknik rugi beruntun menurunkan profit uji. Ditolak.",
    "KOIN_LEMAH_LIVE": "v241: ingatan per koin tidak lolos uji. Ditolak.",
    "RAWAN_SAPU": "v203: kolam stop < 0.8R PF 0.59-0.80.",
    "MANUAL": "Perilaku, bukan aturan sinyal: ikuti kartu robot.",
    "SEROK": "Perilaku: jangan menambah posisi saat minus.",
    "SL_DIUBAH": "Perilaku: jangan mengubah SL sinyal.",
    "TANPA_POLA": "Rugi biasa dari sinyal valid. Sistem menang sekitar 34-38%, profit dari trade yang lari jauh.",
    "LAWAN_SISI_BTC": None,
}
BERULANG_N = 3          # pola sama muncul >= 3 kali dalam 14 hari = kandidat riset (kalau belum diuji) atau pengingat (kalau sudah)


def berulang(kode, closed, t_ms):
    """Berapa kali pola ini tercatat di otopsi 14 hari terakhir (sebelum trade ini)."""
    return sum(1 for c in closed if kode in (c.get("pola") or []) and 0 < t_ms - (c.get("closed_ts") or 0) <= 14 * 24 * JAM)


def _grup_skor(s):
    """Hasil di luar data latih (uji 2025-Okt 2026, 12 bulan, 6 bulan) per kelompok skor, run_v254_wr_skor.py."""
    if s is None:
        return ""
    if s >= 80:
        return "kelompok skor 80+: menang 36-41% trade, PF 1.50-1.91 (SHORT 6 bulan terakhir PF 0.90)"
    if s >= 50:
        return "kelompok skor 50-79: menang 33-35% trade, PF 1.13-1.47"
    if s >= 20:
        return "kelompok skor 20-49: menang 33-36% trade, PF 1.19-1.50"
    return "kelompok skor 0-19: menang 32-34% trade, PF 1.08-1.35"


def evaluasi(it, jh, pola):
    """QC 136 EVALUASI KE DEPAN: rugi ini wajar atau tanda masalah, dan apa yang dilakukan berikutnya. Hanya dari hasil uji."""
    rows = []
    s = it.get("skor100")
    if s is not None:
        rows.append(f"Sinyal asal skor {s}/100, {_grup_skor(s)}. Skor tinggi menaikkan peluang, bukan menjamin: 6 dari 10 trade skor 80+ "
                    f"tetap tidak menang, untungnya datang dari yang menang besar.")
    else:
        rows.append("Skor sinyal asal tidak ditemukan di log kartu 48 jam (entry dari kartu lama atau manual).")
    if jh and "koin_pct" in jh and "btc_pct" in jh:
        kp, bp = jh["koin_pct"], jh["btc_pct"]
        lawan = (kp > 0) == (it["arah"] == "SHORT")
        if lawan and abs(kp) > 2 * max(abs(bp), 0.3):
            rows.append(f"Kenapa rugi: koin bergerak {kp:+.2f}% melawan posisi, jauh lebih besar dari BTC {bp:+.2f}%. Koin ini lari sendiri (berita, pump koin).")
        elif lawan:
            rows.append(f"Kenapa rugi: koin {kp:+.2f}% dan BTC {bp:+.2f}% bergerak bersama melawan posisi. Pasar naik atau turun serentak.")
    p = set(pola or [])
    if p & {"BTC_MELAWAN", "KOIN_SENDIRI", "LANGSUNG_SALAH", "SL_CEPAT"}:
        rows.append("Sudah diuji 2022-2026: tutup saat BTC melawan 1.5-3% (run_v250), balik arah sesudah SL (run_v245), dan deteksi BTC berbalik "
                    "(run_v248) semuanya menurunkan profit. Jadi pola ini rugi wajar dari sistem, bukan aturan yang salah.")
    if (it.get("why") or "").upper() != "SL" and (it.get("result_r") or 0) > -0.9:
        rows.append(f"Posisi ditutup manual di {it.get('result_r', 0):+.2f}R sebelum SL. Aturan robot: ikuti SL. Di uji, tutup manual di -0.4R "
                    f"ke bawah menurunkan profit 18-37% karena banyak posisi balik untung.")
    belum = [k for k in (pola or []) if RISET.get(k, None) is None and k in RISET]
    if belum:
        rows.append("👉 Ke depan: pola " + ", ".join(belum) + " BELUM pernah diuji. Kirim prompt di bawah ke Opus untuk diuji di data 2022-2026.")
    else:
        rows.append("👉 Ke depan: semua pola di trade ini sudah diuji dan tidak ada aturan yang lolos 4 periode. Tetap ikuti sinyal, "
                    "lot sudah menyesuaikan skor, kelas, dan vonis. Prompt tidak perlu dikirim lagi untuk pola yang sama.")
    return rows


def laporan(it, closed, ambil=None, nama=""):
    """Teks otopsi satu trade rugi, termasuk blok prompt untuk Opus."""
    import qse_saya as SY
    it0 = it
    it = _lengkapi(it)
    jh = jalur_harga(it, ambil)
    rw = riwayat(it, closed)
    tm = temuan(it, jh, rw)
    t = it.get("tick") or 0.0001
    fp = lambda x: SY.fp(x, t)
    jl = SY.NAMA_JALUR.get(it.get("jalur") or "", it.get("jalur") or "manual")
    t0 = int(it.get("fill_ts") or it.get("created_ts") or 0)
    why = it.get("why") or "?"
    jenis = "SL" if "SL" in str(why).upper() else "CUTLOSS / TUTUP RUGI"
    rows = [f"🔬 <b>OTOPSI {jenis}: {it['sym']} {it['arah']}</b> · hasil <b>{it.get('result_r', 0):+.2f}R</b>",
            f"Teknik {html.escape(str(jl))} · entry {fp(it['entry'])} · SL {fp(it.get('sl0') or it['sl'])} · "
            f"masuk {_wib(t0) if t0 else '?'} · selesai {_wib(it.get('closed_ts') or 0)} WIB ({html.escape(str(why))})"]
    if jh:
        rows.append(f"📈 Selama posisi: untung tertinggi {jh['mfe']:+.2f}R di jam ke-{jh['jam_mfe']}, rugi terdalam {jh['mae']:+.2f}R, "
                    f"lama {jh['lama']:.1f} jam" + (f", BTC {jh['btc_pct']:+.2f}%" if "btc_pct" in jh else "") + ".")
    rows.append("<b>Kesimpulan robot:</b>\n" + "\n".join(f"• {x}" for _, x in tm))
    kode = [k for k, _ in tm]
    it["_pola"] = kode; it0["_pola"] = kode
    if jh and "btc_pct" in jh:          # QC 141: vonis dinilai dari gerak BTC selama posisi
        L_ = it["arah"] == "LONG"; bp_ = jh["btc_pct"]
        benar = (bp_ > 0) == L_ and abs(bp_) >= 0.3
        rows.append(f"🧭 <b>Arah pasar</b>: BTC {bp_:+.2f}% selama posisi, " + ("searah posisi, jadi arah vonis BENAR." if benar else
                    "melawan posisi, jadi arah pasar berbalik." if abs(bp_) >= 0.3 else "hampir diam, arah tidak menentukan."))
    try:          # QC 136
        rows.append("📌 <b>Evaluasi ke depan</b>\n" + "\n".join(f"• {x}" for x in evaluasi(it, jh, kode)))
    except Exception as ex:
        print("[WARN] otopsi evaluasi", ex)
    try:          # QC 141 status riset tiap pola dan pola yang berulang
        t_ms = it.get("closed_ts") or 0
        st_ = []
        for k_ in kode:
            n_ = berulang(k_, closed, t_ms)
            ul_ = f" Muncul {n_ + 1}x dalam 14 hari." if n_ + 1 >= BERULANG_N else ""
            if RISET.get(k_):
                st_.append(f"{k_}: {RISET[k_]}{ul_}")
            elif k_ in RISET:
                st_.append(f"{k_}: BELUM diuji.{ul_}" + (" 🔁 KANDIDAT RISET, kirim prompt." if ul_ else ""))
        if st_:
            rows.append("📚 <b>Status riset pola</b>\n" + "\n".join(f"• {x}" for x in st_))
    except Exception as ex:
        print("[WARN] otopsi status riset", ex)
    # ---- blok prompt ----
    p = [f"EVALUASI RUGI QSE v150 ({jenis})",
         f"Trade: {it['sym']} {it['arah']}, teknik {jl}, kelas {it.get('kelas') or '-'}, konfluensi {1 + len(it.get('combo') or [])} teknik, "
         f"peringkat koin {it.get('peringkat') or '-'}, skor sinyal {it['skor100'] if it.get('skor100') is not None else '-'}/100.",
         f"Entry {fp(it['entry'])}, SL {fp(it.get('sl0') or it['sl'])}, {_tp_teks(it, fp)}. "
         f"Masuk {_wib(t0) if t0 else '?'} WIB, selesai {_wib(it.get('closed_ts') or 0)} WIB, alasan {why}, hasil {it.get('result_r', 0):+.2f}R."]
    if jh:
        p.append(f"Jalur harga: MFE {jh['mfe']:+.2f}R di jam ke-{jh['jam_mfe']}, MAE {jh['mae']:+.2f}R, lama {jh['lama']:.1f} jam, "
                 f"koin {jh.get('koin_pct', 0):+.2f}%" + (f", BTC {jh['btc_pct']:+.2f}% (terjauh melawan {jh.get('btc_maks_lawan', 0):+.2f}%)" if "btc_pct" in jh else "") + ".")
    p.append(f"Konteks masuk: BTC 4J " + (f"{it['btc_j']}%" if it.get("btc_j") is not None else
                                           f"(saat entry tidak tercatat, saat otopsi {it['btc_j_kini']:+.2f}%)" if it.get("btc_j_kini") is not None else "-%")
             + f" dari EMA 50, kolam stop "
             f"{('%.1fR' % it['kolam']) if it.get('kolam') is not None else '-'}, serok {len(it.get('serok') or [])}x, "
             f"SL diubah manual {'ya' if it.get('sl_manual') else 'tidak'}.")
    if rw.get("jalur"):
        p.append(f"10 trade terakhir teknik ini: {rw['jalur']['n']} trade, WR {rw['jalur']['wr']:.0f}%, total {rw['jalur']['tot']:+.2f}R. "
                 f"Rugi beruntun sebelum ini: {rw.get('beruntun', 0)}.")
    p.append("Pola yang cocok: " + ", ".join(k for k, _ in tm) + ".")
    sudah_ = [k for k in kode if RISET.get(k)]
    if sudah_:
        p.append("Sudah diuji (jangan diulang): " + " | ".join(f"{k}: {RISET[k]}" for k in sudah_))
    if "VONIS_BENAR_KOIN_LAWAN" in kode:
        p.append("Ide belum diuji: aturan keluar saat koin bergerak melawan posisi sementara BTC searah posisi.")
    p.append("Tugas: cari apakah pola rugi ini bisa dicegah dengan aturan baru (saringan masuk, kelas, atau aturan keluar), fokus ke pola dan "
             "ide yang BELUM diuji. Uji di populasi siaran: pilih di latih, buktikan di uji, 12 bulan, dan 6 bulan sesudah biaya. "
             "Pasang hanya kalau lolos semua periode dan tidak menurunkan frekuensi atau total profit. Kalau tidak lolos, laporkan apa adanya.")
    rows.append("📋 <b>Prompt untuk Opus</b> (tekan lama blok di bawah untuk salin):\n<pre>" + html.escape("\n".join(p)) + "</pre>")
    try:          # QC 129: otak umum (Claude API) menjawab langsung kalau ANTHROPIC_API_KEY ada
        import qse_otak_umum as OU
        if OU.aktif():
            j = OU.otopsi("\n".join(p))
            if j:
                rows.append(j)
    except Exception as ex:
        print("[WARN] otak umum otopsi", ex)
    return "\n\n".join(rows)


def cek(now=None, ambil=None):
    """Dipanggil tiap menit. Return list pesan otopsi untuk trade rugi yang baru selesai (sekali per trade)."""
    if not hidup():
        return []
    import qse_saya as SY
    now_ms = int((now or time.time()) * 1000)

    @SY.per_orang
    def _isi_otopsi():
        d = SY._load()
        baru = [c for c in d.get("closed", []) if c.get("result_r") is not None and c["result_r"] <= BATAS_R and not c.get("otopsi")
                and c.get("status") != "BATAL" and 0 <= now_ms - (c.get("closed_ts") or 0) <= UMUR_JAM * JAM]
        if not baru:
            return []
        kunci = {(c.get("sym"), c.get("closed_ts")) for c in baru}

        def tandai(dd):
            for c in dd.get("closed", []):
                if (c.get("sym"), c.get("closed_ts")) in kunci:
                    c["otopsi"] = True
        SY.ubah(tandai)
        out = []
        simpan = {}
        for c in baru[:3]:
            try:
                out.append(laporan(c, d.get("closed", []), ambil))
                if c.get("_pola"):
                    simpan[(c.get("sym"), c.get("closed_ts"))] = c["_pola"]
            except Exception as ex:
                print("[WARN] otopsi", c.get("sym"), ex)
        if simpan:          # QC 141: kode pola disimpan supaya pola berulang 14 hari bisa dihitung
            def isi(dd):
                for c in dd.get("closed", []):
                    k_ = (c.get("sym"), c.get("closed_ts"))
                    if k_ in simpan:
                        c["pola"] = simpan[k_]
            SY.ubah(isi)
        return out
    return _isi_otopsi()


ARTI_POLA = {"LANGSUNG_SALAH": "untung tertinggi < +0.1R", "SL_CEPAT": "selesai <= 4 jam", "BTC_MELAWAN": "BTC bergerak >= 1.5% melawan",
             "KOIN_SENDIRI": "BTC diam (< 0.7%), koin bergerak >= 2% melawan", "JENUH": "SHORT di RSI 4J <= 35 atau LONG di >= 70",
             "BALIK_SESUDAH_TP1": "sempat >= +0.5R lalu berbalik", "BALIK_SEBELUM_TP1": "sempat +0.3 sampai +0.5R lalu berbalik",
             "RUGI_BERUNTUN": "rugi ke-3 atau lebih berturut-turut", "TEKNIK_LEMAH_LIVE": "teknik 10 trade terakhir total < -1R",
             "KOIN_LEMAH_LIVE": "koin 3+ trade terakhir total < -1.5R", "LAWAN_SISI_BTC": "masuk melawan sisi BTC 4J (>= 1% dari EMA 50)",
             "RAWAN_SAPU": "swing 20 candle 4J < 0.8R dari entry", "KELAS_RINGAN": "sinyal kelas ringan", "MANUAL": "entry manual",
             "SEROK": "posisi ditambah saat jalan", "SL_DIUBAH": "SL diubah manual", "TANPA_POLA": "tidak cocok pola apa pun",
             "VONIS_BENAR_KOIN_LAWAN": "BTC searah posisi, koin bergerak >= 2% melawan", "KOIN_LIAR": "ATR 4J >= 3.5% dari harga"}


def rekap(hari=7, ambil=None, ambil4=None):
    """/otopsi: rekap rugi 7 hari terakhir (QC 109), dengan jalur harga tiap trade, dan satu prompt gabungan siap kirim ke Opus."""
    import qse_saya as SY
    d = SY._load()
    a = int(time.time() * 1000) - hari * 86400000
    semua = [c for c in d.get("closed", []) if c.get("result_r") is not None and c.get("status") != "BATAL" and (c.get("closed_ts") or 0) >= a]
    rugi = [c for c in semua if c["result_r"] <= BATAS_R]
    if not rugi:
        return f"🔬 <b>OTOPSI RUGI</b>\nTidak ada trade rugi dalam {hari} hari terakhir."
    hit = {}
    baris = []
    for c in rugi[-15:]:
        jh = jalur_harga(c, ambil, ambil4)          # QC 109: jalur harga dihitung, bukan kosong, supaya pola terbaca
        tm = temuan(c, jh, riwayat(c, d.get("closed", [])))
        for k, _ in tm:
            hit[k] = hit.get(k, 0) + 1
        ctx = []
        if jh.get("mfe") is not None:
            ctx.append(f"MFE {jh['mfe']:+.2f}R, MAE {jh['mae']:+.2f}R, {jh['lama']:.1f} jam")
        if jh.get("btc_pct") is not None:
            ctx.append(f"koin {jh['koin_pct']:+.1f}% BTC {jh['btc_pct']:+.1f}%")
        if jh.get("rsi4") is not None:
            ctx.append(f"RSI4J masuk {jh['rsi4']:.0f}, 72j searah {jh['gerak72']:+.1f}%")
        if c.get("kelas"):
            ctx.append(f"kelas {c['kelas']}")
        baris.append(f"- {_wib(c.get('fill_ts') or c.get('created_ts') or 0)} {c['sym']} {c['arah']} {c.get('jalur') or 'manual'} "
                     f"{c['result_r']:+.2f}R ({c.get('why') or '?'}) | " + "; ".join(ctx) + " | pola: " + ", ".join(k for k, _ in tm))
    tot = sum(c["result_r"] for c in semua)
    def grup(f):
        g = {}
        for c in semua:
            k = f(c); x = g.setdefault(k, [0, 0, 0.0]); x[0] += 1; x[1] += c["result_r"] > 0; x[2] += c["result_r"]
        return "; ".join(f"{k} {n} trade WR {w / n * 100:.0f}% {r:+.2f}R" for k, (n, w, r) in sorted(g.items(), key=lambda z: z[1][2]))
    per_arah = grup(lambda c: c["arah"]); per_tek = grup(lambda c: (c.get("jalur") or "manual").replace("saran ", ""))
    urut = sorted(hit.items(), key=lambda z: -z[1])
    rows = [f"🔬 <b>OTOPSI RUGI {hari} HARI</b>",
            f"{len(semua)} trade selesai, WR {sum(1 for c in semua if c['result_r'] > 0) / len(semua) * 100:.0f}%, total {tot:+.2f}R. "
            f"Rugi {len(rugi)} trade, total {sum(c['result_r'] for c in rugi):+.2f}R.",
            f"<b>Per arah:</b> {per_arah}\n<b>Per teknik:</b> {per_tek}",
            "<b>Pola terbanyak:</b>\n" + "\n".join(f"• {k}: {n} dari {len(rugi)} rugi ({ARTI_POLA.get(k, '')})" for k, n in urut[:6])]
    p = [f"REKAP RUGI QSE v150, {hari} hari terakhir: {len(semua)} trade selesai, total {tot:+.2f}R, rugi {len(rugi)} trade "
         f"({sum(c['result_r'] for c in rugi):+.2f}R).",
         f"Per arah: {per_arah}.", f"Per teknik: {per_tek}.",
         "Pola (jumlah dari trade rugi, arti): " + "; ".join(f"{k} {n}x ({ARTI_POLA.get(k, '')})" for k, n in urut) + ".",
         "Daftar rugi (waktu masuk WIB, koin, arah, teknik, hasil | MFE MAE lama, gerak koin dan BTC selama posisi, RSI 4J saat masuk | pola):"] + baris + [
         "Tugas: cari pola rugi yang paling sering, uji apakah bisa dicegah dengan aturan (latih, uji, 12 bulan, 6 bulan sesudah biaya). "
         "Pasang hanya yang lolos semua periode tanpa menurunkan frekuensi dan profit. Laporkan yang gagal apa adanya."]
    rows.append("📋 <b>Prompt gabungan untuk Opus</b> (tekan lama untuk salin):\n<pre>" + html.escape("\n".join(p))[:3000] + "</pre>")
    return "\n\n".join(rows)
