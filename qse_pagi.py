"""Info pagi 06:00 WIB: peluang pasar bergerak serentak hari ini dan arah yang biasanya diikuti altcoin.
Uji 40 koin paling likuid, data 15 menit, Jan 2022 - Sep 2026, hari dihitung 06:00 sampai 06:00 WIB.
Hari serentak = ada saat BTC bergerak 2% dalam 30 menit atau 3% dalam 3 jam, atau 70% koin bergerak 3% (30 menit)
atau 5% (3 jam) searah. Rata-rata 28% hari (2022-Jun 2024) dan 22% hari (Jul 2024-2026).
Arah BTC per hari tidak bisa ditebak (hari ini searah kemarin hanya 46%), tapi altcoin ikut arah BTC di 69% hari
dan 74% di hari serentak."""
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
                *[f"• {a}" for a in d["alasan"]],
                "Sejarah kondisi ini: BTC naik di 57% hari (hari biasa sekitar 49%), altcoin naik di 59% hari.",
                "🛑 Sinyal SHORT baru ditahan hari ini. Uji 2021-2026: SHORT di hari seperti ini rugi (PF 0.94 dan 0.99), "
                "LONG lebih bagus (PF 1.37 dan 1.21)."]
    return ["🧭 <b>Arah hari ini: TIDAK BISA DITEBAK</b>",
            "Tidak ada kondisi yang terbukti menebak arah hari ini, peluang naik atau turun sekitar 50%. "
            "Ikuti sinyal robot apa adanya, LONG maupun SHORT."]


SESI = {"pagi": ("🌅", "INFO PASAR PAGI", 18), "siang": ("☀️", "INFO PASAR SIANG", 12), "malam": ("🌙", "INFO PASAR MALAM", 12)}


def ramal(sesi="pagi", gerak_t=0):
    """Info pasar 06:00, 12:00, 18:00 WIB. Peluang serentak dan arah hari ini sama untuk satu hari (06:00-06:00 WIB),
    siang dan malam ditambah apa yang sudah terjadi sejak 06:00."""
    import bybit_fetch as B
    now = time.time()
    awal = int((now + 7 * 3600 - 6 * 3600) // 86400) * 86400 - 7 * 3600 + 6 * 3600     # 06:00 WIB hari ini (UTC detik)
    wd = time.gmtime(awal + 7 * 3600).tm_wday
    akhir_pekan = wd in (5, 6)
    # rentang harian BTC 7 hari terakhir (hari 06:00-06:00 WIB)
    h = B._raw("BTCUSDT", "60", 24 * 9)
    rng = []
    for k in range(1, 8):
        a, b = (awal - k * 86400) * 1000, (awal - (k - 1) * 86400) * 1000
        x = h[(h.index >= a) & (h.index < b)]
        if len(x) >= 20:
            rng.append((x["high"].max() / x["low"].min() - 1) * 100)
    r7 = sum(rng) / len(rng) if rng else None
    tingkat = None if r7 is None else "rendah" if r7 < BATAS[0] else "sedang" if r7 <= BATAS[1] else "tinggi"
    # kemarin serentak? 40 koin paling ramai, 15 menit, 24 jam sebelum 06:00 hari ini
    kemarin = None
    try:
        tk = B.get_tickers()
        top = [s for s, _ in sorted(((s, v["turnover"]) for s, v in tk.items() if s.endswith("USDT") and s != "BTCUSDT"),
                                    key=lambda z: -z[1])[:39]]
        cl = {}
        for s in ["BTCUSDT"] + top:
            df = B._raw(s, "15", 140)
            df = df[df.index < awal * 1000].iloc[-108:]
            if len(df) == 108:
                cl[s] = list(df["close"].values)
        kemarin = _serentak(cl)
    except Exception as ex:
        print("[WARN] pagi serentak kemarin", ex)
    ik_s, judul, jam_berita = SESI.get(sesi, SESI["pagi"])
    rows = [f"{ik_s} <b>QSE v148 | {judul}</b>  ·  {HARI[wd]}", ""]
    if tingkat is None:
        return None
    if sesi != "pagi":
        try:
            x = h[h.index >= awal * 1000]
            if len(x):
                b0 = float(x["open"].iloc[0]) if "open" in x else float(x["close"].iloc[0])
                px = float((tk.get("BTCUSDT") or {}).get("last") or x["close"].iloc[-1])
                rows += ["📍 <b>Sejak 06:00 WIB</b>",
                         f"• BTC {(px / b0 - 1) * 100:+.1f}% (rentang {(x['high'].max() / x['low'].min() - 1) * 100:.1f}%)",
                         "• Gerak serentak hari ini: " + ("sudah terjadi" if gerak_t >= awal else "belum terjadi"), ""]
        except Exception as ex:
            print("[WARN] info sesi", ex)
    kk = kemarin if kemarin is not None else False
    p = TABEL[(akhir_pekan, tingkat, kk)]
    rata = (p[0] + p[1]) / 2
    lvl = "TINGGI" if rata >= 40 else "SEDANG" if rata >= 20 else "RENDAH"
    ik = {"TINGGI": "🔴", "SEDANG": "🟡", "RENDAH": "🟢"}[lvl]
    rows += [f"{ik} Peluang pasar bergerak serentak hari ini: <b>{lvl}</b>",
             f"Sejarah kondisi yang sama: {p[0]}% dan {p[1]}% hari (rata semua hari 28% dan 22%).", "",
             "Alasannya:",
             f"• {'Akhir pekan, pasar biasanya sepi' if akhir_pekan else 'Hari kerja'}",
             f"• Rentang harian BTC 7 hari terakhir rata {r7:.1f}% ({tingkat})",
             "• Kemarin " + ("ada gerak serentak" if kemarin else "tidak ada gerak serentak" if kemarin is not None
                            else "tidak terbaca, dianggap tidak ada"), ""]
    try:
        rows += baris_arah()
        if sesi != "pagi":
            rows.append("ℹ️ Arah hari ini dihitung jam 06:00 dan berlaku sampai 06:00 besok. Dihitung ulang jam 12 atau 18 "
                        "lebih jelek di uji 2021-2026 (total profit turun 160-310R), jadi tidak diganti. "
                        "Larangan hanya untuk sinyal SHORT baru. Posisi SHORT yang sudah jalan tetap ikuti SL dan TP, "
                        "uji menutupnya lebih awal juga lebih jelek.")
    except Exception as ex:
        print("[WARN] baris arah", ex)
    rows += ["Altcoin ikut arah harian BTC di 81% hari (74% saat serentak), jadi arah BTC jadi patokan altcoin juga."]
    try:
        from qse_saya import berita_depan
        bd = berita_depan(jam_berita)
        if bd:
            rows += ["", f"📅 Berita besar {jam_berita} jam ke depan: {bd['judul']}. Jam rilis biasanya memicu gerak cepat."]
    except Exception:
        pass
    rows += ["", "Pastikan semua SL terpasang di Bybit. Robot mengirim peringatan GERAK SERENTAK kalau terjadi."]
    return "\n".join(rows)


_BTC_BARIS = [0.0, ""]


def baris_btc_sinyal():
    """Satu blok info BTC yang ikut di setiap pemberitahuan sinyal. Fakta posisi harga lawan EMA, plus kesimpulan uji:
    uji 2021-2026 35 ribu sinyal, arah BTC (9 teknik di 1W, 1D, 4J, searah atau lawan sinyal) tidak konsisten mengubah
    hasil sinyal (contoh 3 timeframe lawan PF 0.76 lalu 1.98). Yang konsisten hanya arah hari ini (condong naik)
    dan volume pasar tinggi, keduanya sudah dipakai robot."""
    if time.time() - _BTC_BARIS[0] < 600 and _BTC_BARIS[1]:
        return _BTC_BARIS[1]
    try:
        import bybit_fetch as B
        rows = []
        px = None
        for iv, nm in (("240", "4J"), ("D", "1D")):
            df = B._raw("BTCUSDT", iv, 260)
            c = df["close"].astype(float)
            c = c.iloc[:-1]                              # candle terakhir masih berjalan
            px = px or float(df["close"].iloc[-1])
            e50 = float(c.ewm(span=50, adjust=False).mean().iloc[-1])
            e200 = float(c.ewm(span=200, adjust=False).mean().iloc[-1])
            pos = lambda e: f"{'di atas' if px > e else 'di bawah'} EMA{'50' if e == e50 else '200'} ({(px / e - 1) * 100:+.1f}%)"
            rows.append(f"{nm}: {pos(e50)}, {pos(e200)}")
        d = arah_hari()
        arah = ("CONDONG NAIK (SHORT baru ditahan)" if d and d["naik"] else "tidak bisa ditebak, 50/50") if d else "belum terbaca"
        teks = (f"₿ <b>BTC {px:,.0f}</b>  ·  " + "  ·  ".join(rows) + f"\n🧭 Arah hari ini: {arah}. "
                "Posisi BTC lawan EMA di atas hanya info, di uji tidak mengubah hasil sinyal.")
        _BTC_BARIS[:] = [time.time(), teks]
        return teks
    except Exception as ex:
        print("[WARN] baris btc sinyal", ex)
        return ""
