"""/cek BTC (23 Okt 2026, kesimpulan akhir 26 Okt): arah BTC per teknik di 1W, 1D, 4J, peluang dari sejarah, sentimen,
funding, open interest (hasil uji lab bulanan), arah hari ini, dan dominasi BTC (BTC.D CoinGecko plus indeks altcoin/BTC).
Ditutup KESIMPULAN AKHIR 24 jam, 7 hari, 30 hari, dampak ke altcoin, dan satu arah akhir. Tidak memberi sinyal entry.
Semua angka peluang dari uji BTC Agu 2018 - Okt 2026, dibagi dua periode: 2018-2021 (dev) dan 2022-2026 (uji).
Yang hanya bagus di satu periode ditandai tidak konsisten dan tidak dihitung."""
import time
import requests
import numpy as np
import pandas as pd

TEKNIK = [("ema50", "EMA 50"), ("ema200", "EMA 200"), ("e2050", "EMA 20/50"), ("mcg", "McGinley"), ("ichi", "Ichimoku"),
          ("rsi", "RSI 50"), ("macd", "MACD"), ("st", "Supertrend"), ("dmi", "DMI")]

# Peluang BTC naik dan rata-rata gerak setelah kondisi arah 1W dan 1D (dan 4J). Per kondisi: [dev, uji],
# tiap periode [persen naik, rata %, persen naik normal, rata normal %, jumlah kasus 4J].
PELUANG = {
    "3naik": {"f7": [[57, 3.0, 55, 1.6, 2612], [51, 0.7, 52, 0.5, 3066]], "f30": [[58, 9.7, 57, 7.2, 2612], [56, 5.3, 55, 2.3, 2969]]},
    "3turun": {"f7": [[64, 2.4, 55, 1.6, 786], [52, -0.3, 52, 0.5, 1932]], "f30": [[72, 7.9, 57, 7.2, 786], [61, 0.7, 55, 2.3, 1932]]},
    "wd_naik": {"f7": [[55, 1.9, 55, 1.6, 985], [53, 1.0, 52, 0.5, 1333]], "f30": [[51, 9.6, 57, 7.2, 985], [49, 3.3, 55, 2.3, 1292]]},
    "wd_turun": {"f7": [[58, 2.1, 55, 1.6, 552], [49, 0.2, 52, 0.5, 870]], "f30": [[61, 8.4, 57, 7.2, 552], [55, 1.8, 55, 2.3, 870]]},
    "wn_dt": {"f7": [[45, -0.9, 55, 1.6, 1559], [56, 1.4, 52, 0.5, 1734]], "f30": [[43, -0.2, 57, 7.2, 1559], [63, 4.1, 55, 2.3, 1734]]},
    "wt_dn": {"f7": [[64, 2.9, 55, 1.6, 671], [48, -0.9, 52, 0.5, 900]], "f30": [[79, 19.8, 57, 7.2, 671], [31, -6.6, 55, 2.3, 900]]},
    "lain": {"f7": [[39, -4.6, 55, 1.6, 323], [55, 0.8, 52, 0.5, 594]], "f30": [[32, -15.0, 57, 7.2, 323], [60, 0.1, 55, 2.3, 594]]},
}
NAMA_KOND = {"3naik": "1W, 1D, 4J searah NAIK", "3turun": "1W, 1D, 4J searah TURUN", "wd_naik": "1W dan 1D NAIK, 4J belum",
             "wd_turun": "1W dan 1D TURUN, 4J belum", "wn_dt": "1W NAIK, 1D TURUN (koreksi dalam tren naik)",
             "wt_dn": "1W TURUN, 1D NAIK (pantulan dalam tren turun)", "lain": "arah belum jelas"}
_CACHE = {}


def _ambil(iv, n):
    from qse_saya import _kline
    k = _kline("BTCUSDT", iv, n)
    if len(k) < 60:
        return None
    df = pd.DataFrame(k[:-1], columns=["ts", "high", "low", "close"])      # bar terakhir masih berjalan, dibuang
    return df.set_index("ts")


def _ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def _teknik(df):
    """Arah 9 teknik di bar terakhir yang sudah tutup: +1 naik, -1 turun, 0 netral. Sama persis dengan uji."""
    c, h, l = df.close, df.high, df.low
    o = {}
    o["ema50"] = np.sign(c.iloc[-1] - _ema(c, 50).iloc[-1])
    o["ema200"] = np.sign(c.iloc[-1] - _ema(c, 200).iloc[-1]) if len(c) >= 200 else 0
    o["e2050"] = np.sign(_ema(c, 20).iloc[-1] - _ema(c, 50).iloc[-1])
    v = c.values
    m = np.empty(len(v))
    m[0] = v[0]
    for i in range(1, len(v)):
        m[i] = m[i - 1] + (v[i] - m[i - 1]) / (34 * (v[i] / m[i - 1]) ** 4)
    o["mcg"] = np.sign(m[-1] - m[-4])
    sa = (((h.rolling(9).max() + l.rolling(9).min()) / 2 + (h.rolling(26).max() + l.rolling(26).min()) / 2) / 2).shift(26)
    sb = ((h.rolling(52).max() + l.rolling(52).min()) / 2).shift(26)
    o["ichi"] = 1 if v[-1] > max(sa.iloc[-1], sb.iloc[-1]) else -1 if v[-1] < min(sa.iloc[-1], sb.iloc[-1]) else 0
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + up / dn)).iloc[-1]
    o["rsi"] = np.sign(rsi - 50)
    mac = _ema(c, 12) - _ema(c, 26)
    o["macd"] = np.sign((mac - _ema(mac, 9)).iloc[-1])
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 10, adjust=False).mean()
    hl = (h + l) / 2
    ub, lb = (hl + 3 * atr).values, (hl - 3 * atr).values
    fu, fl, st = ub.copy(), lb.copy(), 0
    for i in range(1, len(v)):
        fu[i] = min(ub[i], fu[i - 1]) if v[i - 1] <= fu[i - 1] else ub[i]
        fl[i] = max(lb[i], fl[i - 1]) if v[i - 1] >= fl[i - 1] else lb[i]
        st = 1 if v[i] > fu[i - 1] else -1 if v[i] < fl[i - 1] else st
    o["st"] = st
    pdm = h.diff().where((h.diff() > -l.diff()) & (h.diff() > 0), 0)
    ndm = (-l.diff()).where((-l.diff() > h.diff()) & (-l.diff() > 0), 0)
    o["dmi"] = np.sign(pdm.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1] - ndm.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    o = {k: int(x) for k, x in o.items()}
    return o, sum(o.values()), rsi


def _fng():
    c = _CACHE.get("fng")
    if c and time.time() - c[0] < 3600:
        return c[1]
    try:
        x = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10).json()["data"][0]
        v = int(x["value"])
    except Exception:
        v = None
    _CACHE["fng"] = (time.time(), v)
    return v


def _funding():
    """Rata funding BTC 7 hari terakhir (21 kali 8 jam)."""
    c = _CACHE.get("fund")
    if c and time.time() - c[0] < 1800:
        return c[1]
    try:
        from config import BYBIT_URL
        rows = requests.get(BYBIT_URL + "/v5/market/funding/history",
                            params={"category": "linear", "symbol": "BTCUSDT", "limit": 21}, timeout=10).json()["result"]["list"]
        v = sum(float(r["fundingRate"]) for r in rows) / len(rows)
    except Exception:
        v = None
    _CACHE["fund"] = (time.time(), v)
    return v


def _kondisi(w, d, h4):
    sw, sd, sh = np.sign(w), np.sign(d), np.sign(h4)
    if sw == sd == sh == 1:
        return "3naik"
    if sw == sd == sh == -1:
        return "3turun"
    if sw == 1 and sd == 1:
        return "wd_naik"
    if sw == -1 and sd == -1:
        return "wd_turun"
    if sw == 1 and sd == -1:
        return "wn_dt"
    if sw == -1 and sd == 1:
        return "wt_dn"
    return "lain"


def _baris_peluang(k, hz, label):
    a, b = PELUANG[k][hz]
    lebih = [x[0] - x[2] for x in (a, b)]
    tanda = "✅" if all(z >= 3 for z in lebih) else "🔻" if all(z <= -3 for z in lebih) else "➖"
    return (f"{tanda} {label}: naik di {a[0]}% dan {b[0]}% kasus (biasanya {a[2]}% dan {b[2]}%), "
            f"rata-rata {a[1]:+.1f}% dan {b[1]:+.1f}%")


def analisa():
    from qse_saya import harga_live, fp
    px = harga_live("BTCUSDT")
    tf = {}
    for nm, iv, n in (("1W", "W", 400), ("1D", "D", 1000), ("4J", "240", 1000)):
        df = _ambil(iv, n)
        if df is None:
            return "Data BTC dari Bybit belum bisa diambil. Coba lagi sebentar."
        tf[nm] = _teknik(df)
    rows = [f"<b>ARAH BTC</b>  ·  harga {fp(px, 0.1)}", ""]

    # 1. teknikal per timeframe
    ik = lambda x: "▲" if x > 0 else "▼" if x < 0 else "•"
    tabel = [f"{'Teknik':<11}  1W  1D  4J"]
    for k, nm in TEKNIK:
        tabel.append(f"{nm:<11}" + "".join(f"   {ik(tf[t][0][k])}" for t in ("1W", "1D", "4J")))
    tabel.append(f"{'Skor':<11}" + "".join(f" {tf[t][1]:+3d}" for t in ("1W", "1D", "4J")))
    rows += ["📊 <b>TEKNIKAL PER TIMEFRAME</b>", "▲ naik  ▼ turun  • netral. Skor = jumlah naik dikurangi turun dari 9 teknik.",
             "<pre>" + "\n".join(tabel) + "</pre>"]
    arah = lambda s: "NAIK" if s > 0 else "TURUN" if s < 0 else "NETRAL"
    rows.append("  ·  ".join(f"{t} {arah(tf[t][1])}" for t in ("1W", "1D", "4J")))
    kond = _kondisi(tf["1W"][1], tf["1D"][1], tf["4J"][1])
    rows += [f"Kondisi: <b>{NAMA_KOND[kond]}</b>", ""]

    # 2. peluang dari sejarah
    rows += ["🎲 <b>PELUANG DARI SEJARAH</b>",
             "Kondisi yang sama di BTC 2018-2021 dan 2022-2026, angka pertama periode lama, kedua periode baru.",
             _baris_peluang(kond, "f7", "7 hari"), _baris_peluang(kond, "f30", "30 hari"),
             "✅ lebih sering naik dari biasa di dua periode, 🔻 lebih sering turun, ➖ tidak beda atau tidak konsisten.", ""]

    # 3. sentimen dan fundamental
    rows.append("🌡 <b>SENTIMEN DAN FUNDAMENTAL</b>")
    edge = []
    fg = _fng()
    if fg is not None:
        if fg <= 20:
            rows.append(f"✅ Fear and Greed {fg}, takut ekstrem. Sejarah: 30 hari kemudian naik di 65% dan 59% kasus "
                        f"(biasanya 57% dan 55%).")
            edge.append(1)
        elif fg >= 80:
            rows.append(f"➖ Fear and Greed {fg}, serakah ekstrem. Dulu sering lanjut naik, sejak 2022 tidak beda dari biasa.")
        else:
            rows.append(f"➖ Fear and Greed {fg}. Di rentang ini tidak beda dari biasa.")
    fu = _funding()
    if fu is not None:
        pct = fu * 100
        if fu < 0:
            rows.append(f"✅ Funding 7 hari rata {pct:+.4f}%, trader banyak SHORT. Sejarah: 30 hari kemudian naik di 97% dan 61% "
                        f"kasus (biasanya 57% dan 55%).")
            edge.append(1)
        elif fu >= 0.000261:
            rows.append(f"🔻 Funding 7 hari rata {pct:+.4f}%, trader terlalu banyak LONG. Sejarah: 30 hari kemudian naik hanya di "
                        f"43% dan 47% kasus (biasanya 57% dan 55%).")
            edge.append(-1)
        else:
            rows.append(f"➖ Funding 7 hari rata {pct:+.4f}%, normal.")
    try:
        from qse_saya import berita_depan
        bd = berita_depan(24)
        if bd:
            rows.append(f"📅 Berita besar 24 jam ke depan: {bd['judul']}. Harga biasanya bergerak cepat di jam itu.")
    except Exception:
        pass
    oi = {}
    try:
        import qse_lab as LB
        oi = LB.oi_info()
        rows += oi.get("rows", [])
    except Exception as ex:
        print("[WARN] oi cek", ex)
    try:
        import qse_news as NW
        bk = NW.berita_koin("BTCUSDT", maks=3)
        if bk:
            rows += ["📰 Berita BTC terbaru:"] + bk
    except Exception:
        pass
    rows.append("")

    # 4. arah hari ini (aturan pagi dan lebar pasar)
    lu, dh = {}, None
    try:
        import qse_pagi as PG
        rows += PG.tebak_teks("cek") + [""] + PG.baris_arah("cek") + [""] + PG.kesimpulan_arah() + [""]
        lu = PG.pasar_luas() or {}
        dh = PG.arah_hari()
    except Exception as ex:
        print("[WARN] arah hari cek", ex)

    # 5. dominasi BTC
    rows.append("🪙 <b>DOMINASI BTC (BTC.D)</b>")
    dom = _btcd()
    dt = lu.get("dom_turun")
    a7d, a30d = (lu.get("altbtc_7h") or 0) * 100, (lu.get("altbtc_30h") or 0) * 100
    if dom is not None:
        rows.append(f"BTC.D sekarang {dom:.1f}% dari total kapitalisasi kripto (CoinGecko).")
    if dt is None:
        rows.append("Tren dominasi belum terbaca dari data Bybit.")
    elif dt:
        rows += [f"📉 Tren TURUN: indeks 40 altcoin teramai lawan BTC di atas EMA 20 harian (7 hari {a7d:+.1f}%, 30 hari {a30d:+.1f}%). "
                 "Altcoin sedang lebih kuat dari BTC.",
                 "✅ Uji 9 jalur 2017-2026: SHORT altcoin di kondisi ini PF 1.57, 1.34, 1.68, biasanya 1.09, 1.18, 1.24. "
                 "Sinyal SHORT dapat label 📉 BTC.D TURUN."]
    else:
        rows += [f"📈 Tren NAIK: indeks 40 altcoin teramai lawan BTC di bawah EMA 20 harian (7 hari {a7d:+.1f}%, 30 hari {a30d:+.1f}%). "
                 "BTC sedang lebih kuat dari altcoin.",
                 "➖ Di kondisi ini SHORT altcoin kembali ke hasil biasa. LONG altcoin tidak terpengaruh konsisten."]
    rows += ["Tren dominasi tidak terbukti menebak arah BTC sendiri (uji 2018-2026 tidak konsisten), jadi tidak masuk hitungan arah BTC.", ""]

    # 6. kesimpulan akhir
    tanda = lambda tb: 1 if all(x[0] - x[2] >= 3 for x in tb) else -1 if all(x[0] - x[2] <= -3 for x in tb) else 0
    t7, t30 = tanda(PELUANG[kond]["f7"]), tanda(PELUANG[kond]["f30"])
    pagi_naik = bool(dh and dh.get("naik"))
    luas_naik = (lu.get("d50") or 0) >= 0.8
    oi_arah = oi.get("arah") or 0
    tbk = None
    try:
        import qse_tebak as TB
        tbk = TB.tebak()
    except Exception as ex:
        print("[WARN] tebak cek", ex)
    # 24 jam: hanya dasar yang lolos uji ulang 27 Okt 2026. Model arah hanya NAIK KUAT (BTC 55-57%), aturan naik pagi
    # (BTC naik 55-58% di semua periode), atau pola open interest teruji. Lebar pasar 80%+ hanya untuk altcoin (BTC 50-53%).
    naik24 = bool(tbk and TB.terbukti(tbk)) or pagi_naik or oi_arah > 0
    turun24 = oi_arah < 0 and not naik24
    alasan30 = []
    if t30:
        alasan30.append(f"teknikal {NAMA_KOND[kond]} ({'+' if t30 > 0 else '-'})")
    if fg is not None and fg <= 20:
        alasan30.append("takut ekstrem (+)")
    if fu is not None and fu < 0:
        alasan30.append("funding negatif (+)")
    elif fu is not None and fu >= 0.000261:
        alasan30.append("funding terlalu tinggi (-)")
    skor30 = t30 + sum(edge)
    rows.append("🏁 <b>KESIMPULAN AKHIR</b>")
    if naik24:
        al = [f"{dh['alasan'][0]} (aturan teruji)"] if pagi_naik else []
        if tbk and TB.terbukti(tbk) and not (pagi_naik and tbk.get("pakai_lama")):
            al.append(TB.dasar(tbk))
        if oi_arah > 0:
            al.append("pola open interest teruji")
        rows.append(f"⏱ 24 jam: 🟢 CONDONG NAIK. Dasar: {', '.join(al)}. Tetap peluang, bukan kepastian.")
    elif turun24:
        rows.append("⏱ 24 jam: 🔴 CONDONG TURUN. Dasar: pola open interest teruji. Tetap peluang, bukan kepastian.")
    elif tbk:
        rows.append(f"⏱ 24 jam: ⚪ NETRAL 50:50 ({TB.alasan_netral(tbk)}). Ikuti sinyal robot apa adanya.")
    else:
        rows.append("⏱ 24 jam: ⚪ NETRAL. Data BTC belum lengkap untuk model arah. Ikuti sinyal robot apa adanya.")
    a, b = PELUANG[kond]["f7"]
    rows.append(f"📅 7 hari: {'🟢 CONDONG NAIK' if t7 > 0 else '🔴 CONDONG TURUN' if t7 < 0 else '⚪ NETRAL'}. "
                f"Kondisi {NAMA_KOND[kond]} naik di {a[0]}% dan {b[0]}% kasus, biasanya {a[2]}% dan {b[2]}%.")
    rows.append(f"🗓 30 hari: {'🟢 CONDONG NAIK' if skor30 > 0 else '🔴 CONDONG TURUN atau tertahan' if skor30 < 0 else '⚪ NETRAL'}"
                + (f" ({', '.join(alasan30)})." if alasan30 else ". Teknikal, sentimen, dan funding tidak memberi keunggulan arah."))
    rows.append("🪙 Altcoin: " + ("BTC.D turun, SHORT altcoin lebih kuat dari biasa." if dt else
                                  "BTC.D naik, sinyal altcoin hasil biasa." if dt is not None else "dominasi belum terbaca.")
                + (" 80%+ koin di atas EMA50 1D: altcoin naik besok di 56-58% hari (biasanya 51-56%)." if luas_naik else ""))
    if naik24 and skor30 >= 0:
        akhir = "🟢 CONDONG NAIK"
        # Utamakan LONG hanya di hari aturan pagi (uji sinyal: SHORT PF 0.94/0.99, LONG 1.37/1.21). Arah lain tidak
        # terbukti mengubah hasil sinyal (membuang sinyal lawan tebakan: PF naik di satu periode, turun di periode lain).
        aksi = ("Utamakan sinyal LONG robot. SHORT baru ditahan otomatis hari ini." if pagi_naik else
                "Ikuti sinyal robot LONG dan SHORT apa adanya. Arah ini tidak terbukti mengubah hasil sinyal.")
    elif turun24 and skor30 <= 0:
        akhir, aksi = "🔴 CONDONG TURUN (24 jam)", "Ikuti sinyal robot. LONG baru pakai SL disiplin, jangan tambah posisi melawan arah."
    elif turun24:
        akhir, aksi = "🟡 CAMPUR: 24 jam condong turun, 30 hari condong naik", "Jangan kejar LONG hari ini. Ikuti sinyal robot apa adanya."
    elif skor30 > 0:
        akhir, aksi = "🟢 CONDONG NAIK (jangka 30 hari)", "Hari ini tetap ikuti sinyal robot LONG dan SHORT. DCA spot tetap jalan seperti biasa."
    elif skor30 < 0 and naik24:
        akhir = "🟡 CAMPUR: 24 jam condong naik, 30 hari condong tertahan"
        aksi = ("Ikuti sinyal LONG robot, SHORT baru ditahan otomatis hari ini." if pagi_naik else
                "Ikuti sinyal robot LONG dan SHORT.") + " Posisi tetap ikuti SL dan TP."
    elif skor30 < 0:
        akhir, aksi = "🔴 CONDONG TURUN atau tertahan (jangka 30 hari)", "Ikuti sinyal robot. SHORT tidak ditahan, LONG pakai SL disiplin."
    else:
        akhir, aksi = "⚪ NETRAL", "Ikuti sinyal robot apa adanya, LONG dan SHORT sama peluangnya."
    if dt:
        aksi += " Kalau ambil SHORT altcoin, pilih yang berlabel BTC.D TURUN."
    if oi.get("gerak"):
        aksi += " Peluang gerak besar 24 jam lebih tinggi dari biasa, pasang SL."
    rows += [f"➡️ <b>ARAH AKHIR BTC: {akhir}</b>", f"🎯 {aksi}",
             "Ini arah, bukan sinyal entry. Entry tetap dari sinyal robot. Arah teknikal 4J saja tidak bisa menebak 1 sampai 3 hari "
             "(uji 49 sampai 55%, sama dengan acak)."]
    return "\n".join(rows)


def _btcd():
    """BTC.D sekarang dari CoinGecko, cadangan CoinPaprika. Disimpan 1 jam."""
    c = _CACHE.get("btcd")
    if c and time.time() - c[0] < 3600:
        return c[1]
    v = None
    try:
        v = float(requests.get("https://api.coingecko.com/api/v3/global", timeout=10,
                               headers={"User-Agent": "qse-bot/148"}).json()["data"]["market_cap_percentage"]["btc"])
    except Exception:
        try:
            v = float(requests.get("https://api.coinpaprika.com/v1/global", timeout=10).json()["bitcoin_dominance_percentage"])
        except Exception:
            v = None
    _CACHE["btcd"] = (time.time(), v)
    return v
