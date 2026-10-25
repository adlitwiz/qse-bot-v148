"""Info pagi 06:00 WIB & Deteksi Pergerakan Dini (PILAR 4):
1. Peluang pasar bergerak serentak hari ini dan arah yang biasanya diikuti altcoin (uji 40 koin paling likuid, data 15 menit, Jan 2022 - Sep 2026).
2. Arah sesi pagi 06:00 WIB (uji BTC 1 jam 2018-2026).
3. Deteksi Pergerakan Dini (Early Mover) & Momentum Sesi Pagi untuk menangkap harga sejak awal ledakan.
4. Saringan Keterlambatan Harga (Anti-Late Filter) sebagai rem otomatis yang membatalkan rencana masuk posisi apabila harga sudah bergerak terlalu jauh dari zona Order Block / titik kunci.
"""
import time
import numpy as np

# rentang harian BTC rata 7 hari sebelumnya: rendah < 2.61%, sedang 2.61-3.63%, tinggi > 3.63%
BATAS = (2.61, 3.63)
# (akhir pekan, tingkat rentang, kemarin serentak) -> [persen hari serentak 2022-Jun 2024, Jul 2024-2026, n, n]
TABEL = {
    (True, "rendah", True): [0, 0, 5, 4], (True, "rendah", False): [1, 4, 69, 81],
    (True, "sedang", True): [7, 31, 14, 13], (True, "sedang", False): [4, 6, 67, 68],
    (True, "tinggi", True): [29, 30, 41, 27], (True, "tinggi", False): [11, 12, 64, 41],
    (False, "rendah", True): [25, 18, 20, 11], (False, "rendah", False): [20, 13, 167, 213],
    (False, "sedang", True): [31, 50, 48, 58], (False, "sedang", False): [31, 23, 148, 154],
    (False, "tinggi", True): [56, 52, 130, 69], (False, "tinggi", False): [45, 35, 133, 83],
}
HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]


def _serentak(closes):
    """closes: dict sym -> list close 15 menit sejajar (lama ke baru). True kalau ada pemicu di 96 bar terakhir."""
    btc = np.array(closes["BTCUSDT"], float)
    alt = [np.array(v, float) for s, v in closes.items() if s != "BTCUSDT" and len(v) == len(btc)]
    if len(alt) < 20:
        return None
    A = np.vstack(alt)
    n = len(btc)
    for i in range(max(12, n - 96), n):
        for lb, bt, at in ((2, 2, 3), (12, 3, 5)):
            rb = (btc[i] / btc[i - lb] - 1) * 100
            ra = (A[:, i] / A[:, i - lb] - 1) * 100
            if abs(rb) >= bt or (ra >= at).mean() >= 0.7 or (ra <= -at).mean() >= 0.7:
                return True
    return False


# Arah hari ini (uji BTC 1 jam 2018-2026, hari 06:00-06:00 WIB). Dari puluhan kondisi yang dicoba, hanya 4 yang
# konsisten di 2018-2021 dan 2022-2026, semuanya condong NAIK. Kalau salah satu terpenuhi pada hari kemarin:
# BTC naik hari ini 57% dan 57% (hari lain 51% dan 47%), basket 40 altcoin naik 59% (2022-2026).
# Sinyal jalur di hari itu: SHORT PF 0.94 dan 0.99 (rugi), LONG PF 1.37 dan 1.21. Hari lain SHORT PF 1.35 dan 1.48.
# Jadi di hari condong naik, sinyal SHORT baru ditahan. Tidak ada kondisi condong TURUN yang lolos uji.
ATURAN_NAIK = (("r7", -0.0921, "BTC turun lebih dari 9% dalam 7 hari"),
               ("e20", 0.0994, "BTC lebih dari 10% di atas EMA 20 harian"),
               ("rsi", 70.96, "RSI harian BTC di atas 71"),
               ("cp", 0.1851, "BTC kemarin tutup di dasar rentang hariannya"))


def _awal(now):
    return int((now + 3600) // 86400) * 86400 - 3600          # 06:00 WIB hari ini dalam detik UTC


def arah_hari(now=None):
    """dict(hari, naik, alasan). Dihitung sekali per hari 06:00 WIB dan disimpan."""
    import json, os
    from config import STATE_DIR
    now = now or time.time()
    aw = _awal(now)
    f = os.path.join(STATE_DIR, "arah_hari.json")
    try:
        with open(f) as fh:
            d = json.load(fh)
        if d.get("hari") == aw:
            return d
    except Exception:
        pass
    import bybit_fetch as B
    import pandas as pd
    h = B._raw("BTCUSDT", "60", 24 * 150)
    h = h[h.index < aw * 1000]
    if len(h) < 24 * 60:
        return None
    t = pd.to_datetime(h.index, unit="ms", utc=True)
    day = (t - pd.Timedelta(hours=23)).floor("D")
    D = pd.DataFrame({"c": h["close"].groupby(day).last().values, "hi": h["high"].groupby(day).max().values,
                      "lo": h["low"].groupby(day).min().values})
    c = D["c"]
    dd = c.diff()
    up = dd.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-dd.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    nilai = {"r7": c.iloc[-1] / c.iloc[-8] - 1, "e20": c.iloc[-1] / c.ewm(span=20, adjust=False).mean().iloc[-1] - 1,
             "rsi": float((100 - 100 / (1 + up / dn)).iloc[-1]),
             "cp": (D["c"].iloc[-1] - D["lo"].iloc[-1]) / max(D["hi"].iloc[-1] - D["lo"].iloc[-1], 1e-9)}
    alasan = [teks for k, th, teks in ATURAN_NAIK if (nilai[k] <= th if k in ("r7", "cp") else nilai[k] >= th)]
    d = dict(hari=aw, naik=bool(alasan), alasan=alasan, nilai={k: round(float(v), 4) for k, v in nilai.items()})
    try:
        with open(f + ".tmp", "w") as fh:
            json.dump(d, fh)
        os.replace(f + ".tmp", f)
    except Exception:
        pass
    return d


_GAGAL = [0.0]


def short_tahan():
    """Teks alasan kalau sinyal SHORT baru harus ditahan hari ini (hari condong naik), atau ''."""
    if time.time() - _GAGAL[0] < 600:
        return ""
    try:
        d = arah_hari()
        if d is None:
            _GAGAL[0] = time.time()
        return "hari ini condong NAIK (" + d["alasan"][0] + "), SHORT ditahan" if d and d["naik"] else ""
    except Exception as ex:
        print("[WARN] arah hari", ex)
        return ""


def baris_arah():
    d = arah_hari()
    if not d:
        return ["🧭 <b>Arah hari ini</b>: data BTC belum terbaca."]
    if d["naik"]:
        return ["🧭 <b>Arah hari ini: CONDONG NAIK</b>",
                f"Pemicu kemarin: {', '.join(d['alasan'])}.",
                "Uji 2018-2026: di hari seperti ini BTC naik 57% (biasanya 49%), keranjang 40 altcoin naik 59%, "
                "sinyal LONG PF 1.37 dan 1.21, sinyal SHORT rugi (PF 0.94 dan 0.99). Sinyal SHORT baru otomatis ditahan hari ini."]
    return ["🧭 <b>Arah hari ini: BELUM ADA CONDONG KUAT</b>",
            "Tidak satu pun dari 4 kondisi pemicu naik terpenuhi kemarin. Peluang naik/turun hari ini mendekati 50:50, "
            "sinyal LONG dan SHORT jalan normal."]


def ramal(sesi="pagi", gerak_t=0):
    """Pesan info pasar 06:00, 12:00, dan 18:00 WIB."""
    import bybit_fetch as B
    from qse_saya import berita_depan
    tk = B.get_tickers()
    top = [s for s, _ in sorted(((s, v["turnover"]) for s, v in tk.items() if s.endswith("USDT") and s != "BTCUSDT"),
                                key=lambda z: -z[1])[:39]]
    now = int(time.time() * 1000)
    closes = {}
    for s in ["BTCUSDT"] + top:
        try:
            df = B._raw(s, "15", 120)
            df = df[df.index + 900000 <= now]
            closes[s] = df["close"].values.astype(float)[-100:]
        except Exception:
            pass
    if "BTCUSDT" not in closes or len(closes["BTCUSDT"]) < 96:
        return ""
    ser = _serentak({s: list(v[:-1]) for s, v in closes.items()})          # 24 jam sebelumnya
    D = B._raw("BTCUSDT", "D", 12)
    D = D[D.index + 86400000 <= now]
    if len(D) < 8:
        return ""
    rng = ((D["high"].values[-7:] / D["low"].values[-7:] - 1) * 100).mean()
    tingkat = "rendah" if rng < BATAS[0] else "sedang" if rng <= BATAS[1] else "tinggi"
    wib = time.gmtime(time.time() + 7 * 3600)
    wk = wib.tm_wday in (5, 6)
    p1, p2, n1, n2 = TABEL[(wk, tingkat, bool(ser))]
    c4 = B._raw("BTCUSDT", "240", 70)
    c4 = c4[c4.index + 14400000 <= now]["close"].values.astype(float)
    k, out = 2 / 51, c4[0]
    for x in c4[1:]:
        out = x * k + out * (1 - k)
    naik = c4[-1] > out
    bd = berita_depan(18)
    jdl = {"pagi": "PAGI 06:00", "siang": "SIANG 12:00", "malam": "MALAM 18:00"}.get(sesi, "PASAR")
    rows = [f"🌅 <b>QSE v148 | INFO PASAR {jdl} WIB ({HARI[wib.tm_wday]})</b>", "",
            f"Peluang pasar bergerak serentak hari ini: <b>sekitar {(p1 + p2) // 2}%</b> "
            f"(2022-2024: {p1}% dari {n1} hari, 2024-2026: {p2}% dari {n2} hari).",
            f"Dasar hitung: {'akhir pekan' if wk else 'hari kerja'}, rentang harian BTC 7 hari terakhir {rng:.1f}% ({tingkat}), "
            f"24 jam terakhir {'sempat' if ser else 'tidak'} bergerak serentak."]
    if sesi != "pagi":
        awal = _awal(time.time())
        sudah = gerak_t >= awal
        b0 = B._raw("BTCUSDT", "60", 30)
        b0 = b0[(b0.index >= awal * 1000) & (b0.index + 3600000 <= now)]
        if len(b0):
            ch = (float(b0["close"].iloc[-1]) / float(b0["open"].iloc[0]) - 1) * 100
            rg = (float(b0["high"].max()) / float(b0["low"].min()) - 1) * 100
            rows.append(f"Sejak 06:00 WIB tadi: BTC {ch:+.1f}% (rentang {rg:.1f}%), gerak serentak "
                        + ("SUDAH terjadi hari ini." if sudah else "belum terjadi."))
    if bd:
        rows.append(f"📅 Ada berita besar USD hari ini ({bd['judul']}), peluang guncangan lebih tinggi di sekitar jam rilis.")
    rows += ["", *baris_arah(), "",
             f"Patokan 4J sekarang: BTC {c4[-1]:,.0f} USDT, {'di atas' if naik else 'di bawah'} EMA 50 ({out:,.0f}). "
             f"Di 74% hari yang bergerak serentak, mayoritas altcoin bergerak searah BTC.", "",
             "Yang perlu dilakukan: tidak perlu menebak arah sebelum kejadian. Kalau nanti pasar bergerak serentak, "
             "robot langsung mengirim peringatan dalam 1 menit."]
    return "\n".join(rows)


def baris_btc_sinyal():
    """Satu baris arah BTC untuk pesan sinyal baru, dari data yang sama dengan /cek BTC."""
    import bybit_fetch as B
    now = int(time.time() * 1000)
    c4 = B._raw("BTCUSDT", "240", 70)
    c4 = c4[c4.index + 14400000 <= now]["close"].values.astype(float)
    k, e50 = 2 / 51, c4[0]
    for x in c4[1:]:
        e50 = x * k + e50 * (1 - k)
    naik = c4[-1] > e50
    d = arah_hari()
    ah = "hari ini CONDONG NAIK (SHORT ditahan)" if d and d.get("naik") else "arah hari ini netral"
    return (f"🧭 BTC Sekarang: {c4[-1]:,.0f} USDT, 4J {'DI ATAS' if naik else 'DI BAWAH'} EMA 50 ({e50:,.0f})  ·  {ah}. "
            f"Detail 1W/1D/4J: /cek BTC")


# ==================== PILAR 4: DETEKSI PERGERAKAN DINI & SARINGAN ANTI TERLAMBAT ====================

def deteksi_gerak_dini(df, arah=None):
    """Tajamkan deteksi pergerakan dini (early mover) dan pembacaan momentum sesi pagi untuk menangkap
    harga sejak awal ledakan sebelum harga lari terlalu jauh.
    Kriteria pemicu gerak dini:
      1. Ekspansi badan lilin dini: badan lilin terakhir >= 0.85x rata-rata 10 lilin sebelumnya & tutup di 30% ujung searah.
      2. Lonjakan volume awal (early volume ignition): volume >= 1.3x rata-rata 20 lilin atau CDV positif kuat.
      3. Momentum sesi pagi / harian searah: dorongan dari pembukaan sesi pagi (6 lilin 4J terakhir) searah,
         serta harga belum melesat melebihi batas jenuh (gerak < 5% di satu lilin agar tidak pucuk, sesuai uji mover.py).
    Return dict(aktif, arah, skor, alasan, gerak_pct, atr).
    """
    if df is None or len(df) < 40:
        return dict(aktif=False, arah=arah or "LONG", skor=0, alasan=[], gerak_pct=0.0, atr=0.0)
    o, h, l, c, v = (df[k].values.astype(float) for k in ("open", "high", "low", "close", "volume"))
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    atr = float(tr[-14:].mean()) if len(tr) >= 14 else float(h[-1] - l[-1] or 1e-9)

    ch_pct = (c[-1] / o[-1] - 1) * 100
    d = 1 if (arah == "LONG" if arah else ch_pct >= 0) else -1
    ar_str = "LONG" if d == 1 else "SHORT"

    body = (c[-1] - o[-1]) * d
    rng = max(h[-1] - l[-1], 1e-12)
    avg_body = float(np.abs(c[-11:-1] - o[-11:-1]).mean()) or 1e-9
    rv = float(v[-1] / max(v[-21:-1].mean(), 1e-12))

    # Posisi penutupan dalam rentang lilin (dekat high untuk LONG, dekat low untuk SHORT)
    close_pos = (c[-1] - l[-1]) / rng if d == 1 else (h[-1] - c[-1]) / rng
    # Momentum sesi pagi (perubahan 6 bar / 24 jam atau sejak awal hari)
    sesi_ret = (c[-1] / c[-6] - 1) * 100 * d if len(c) >= 7 else ch_pct * d

    alasan = []
    skor = 0
    if body >= 0.85 * avg_body and close_pos >= 0.65:
        skor += 35
        alasan.append(f"pemicu gerak dini (badan lilin {body / avg_body:.1f}x rata-rata, tutup kuat {close_pos * 100:.0f}%)")
    if rv >= 1.25:
        skor += 30
        alasan.append(f"dorongan volume awal {rv:.1f}x rata-rata")
    if sesi_ret > 0:
        skor += 20
        alasan.append(f"momentum sesi pagi searah ({sesi_ret:+.1f}%)")
    # Sesuai mover.py: gerak awal terbaik saat masih < 5% (awal ledakan, belum terlambat)
    if 0.3 <= abs(ch_pct) <= 5.5:
        skor += 15
        alasan.append(f"awal ledakan terjaga ({ch_pct:+.1f}%, belum jenuh)")
    elif abs(ch_pct) > 8.0:
        skor -= 30  # sudah terlalu liar

    try:
        ah = arah_hari()
        if ah and ah.get("naik") and d == 1:
            skor += 15
            alasan.append("didukung arah sesi pagi 06:00 WIB condong NAIK")
    except Exception:
        pass

    return dict(
        aktif=bool(skor >= 50 and body > 0),
        arah=ar_str,
        skor=min(100, max(0, skor)),
        alasan=alasan,
        gerak_pct=round(float(ch_pct), 2),
        atr=atr,
    )


def saring_anti_terlambat(px_sekarang, arah, entry_sinyal=None, ob_zona=None, atr=None, maks_atr_ob=1.8, maks_atr_entry=0.5):
    """PILAR 4: Penyaring keterlambatan harga (Anti-Late Filter) sebagai rem otomatis pada seluruh kombo strategi.
    Membatalkan rencana masuk posisi apabila:
      1. Harga sudah bergerak terlalu jauh dari zona Order Block / zona pantulan (> maks_atr_ob ATR dari tepi/titik OB).
      2. Harga sudah lari terlalu jauh dari harga sinyal penutupan (> maks_atr_entry ATR).
    Return (lolos: bool, alasan_batal: str, jarak_ob_atr: float).
    """
    if not px_sekarang or not atr or atr <= 0:
        return True, "", 0.0
    L = arah in ("LONG", 1)
    jarak_ob_atr = 0.0

    # 1. Cek jarak dari zona Order Block (bila ob_zona tersedia: tuple/list (bot, top) atau dict)
    if ob_zona is not None:
        if isinstance(ob_zona, dict):
            z_bot = float(ob_zona.get("zona_bot", ob_zona.get("ob_low", ob_zona.get("bot", px_sekarang))))
            z_top = float(ob_zona.get("zona_top", ob_zona.get("ob_top", ob_zona.get("top", px_sekarang))))
            titik = float(ob_zona.get("titik_kunci", z_top if L else z_bot))
        elif isinstance(ob_zona, (tuple, list)) and len(ob_zona) >= 2:
            z_bot, z_top = float(min(ob_zona[0], ob_zona[1])), float(max(ob_zona[0], ob_zona[1]))
            titik = z_top if L else z_bot
        else:
            z_bot = z_top = titik = float(px_sekarang)

        # Jarak searah lari dari tepi atas OB (untuk LONG) atau tepi bawah OB (untuk SHORT)
        lari_ob = (px_sekarang - z_top) if L else (z_bot - px_sekarang)
        jarak_ob_atr = float(max(0.0, lari_ob) / atr)
        if jarak_ob_atr > maks_atr_ob:
            return (
                False,
                f"rem anti-terlambat aktif: harga ({px_sekarang:g}) sudah bergerak terlalu jauh ({jarak_ob_atr:.2f} ATR > batas {maks_atr_ob:g} ATR) dari zona Order Block ({z_bot:g}-{z_top:g})",
                jarak_ob_atr,
            )
        # Cek bila harga sudah jebol ke belakang Order Block (struktur batal)
        jebol = (z_bot - px_sekarang) if L else (px_sekarang - z_top)
        if jebol > 0.35 * atr:
            return (
                False,
                f"rem anti-terlambat aktif: harga ({px_sekarang:g}) sudah menembus batas belakang Order Block ({z_bot:g}-{z_top:g})",
                jarak_ob_atr,
            )

    # 2. Cek jarak keterlambatan dari harga penutupan lilin sinyal
    if entry_sinyal is not None and entry_sinyal > 0:
        lari_entry = (px_sekarang - entry_sinyal) if L else (entry_sinyal - px_sekarang)
        jarak_e_atr = float(abs(lari_entry) / atr)
        if lari_entry > maks_atr_entry * atr:
            return (
                False,
                f"rem anti-terlambat aktif: harga ({px_sekarang:g}) sudah lari +{jarak_e_atr:.2f} ATR dari titik pemicu ({entry_sinyal:g})",
                jarak_ob_atr or jarak_e_atr,
            )

    return True, "", jarak_ob_atr
