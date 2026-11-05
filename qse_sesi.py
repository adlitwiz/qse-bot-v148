"""QSE v150 - LAPORAN SESI pagi (06:00 WIB), siang (12:00 WIB), malam (18:00 WIB). Lima bagian, langsung bisa dipakai:
1. Peta komando BTC (qse_btcmap): tren 1J/4J/1D McGinley, volume objektif, order flow, S/R, likuiditas, fokus.
2. Karakter sesi dari candle 1 jam BTC: rentang Asia (07:00-14:00 WIB), London (14:00-20:00 WIB), New York (20:00-04:00 WIB).
   Uji BTC 2019-2026 (riset/v150/sesi_stat.py, 2.838 hari):
   - London menyapu high atau low Asia di 78% hari (2019-22 dan 2023-26 sama), dua sisi 7-9%.
   - Arah sesudah sapuan (pola AMD: sapu lalu balik) 46-53%, sama dengan lempar koin. Level Asia = target, bukan arah.
   - New York membuat high atau low baru hari itu di 75% (2019-22) dan 86% (2023-26) hari: gerak terbesar biasanya di NY.
3. Rotasi dana: BTC.D, altseason meter (alt besar lawan BTC 7 hari), kekuatan mayoritas 50 koin paling likuid (persen naik 24 jam).
4. Radar bandar: funding dan open interest Bybit. Funding sangat negatif + harga naik = rawan short squeeze, funding sangat
   positif + harga turun = rawan long squeeze. Info, bukan sinyal (funding ekstrem searah atau lawan gagal uji jalur 2020-2026).
5. Pantauan 3-5 koin: sinyal jalur yang masih valid (harga dalam 0.5R dari entry robot, SL belum tersentuh), lalu koin likuid
   paling volatil yang harganya dekat support/resistance 4J. Plus berita merah dan token unlock hari ini."""
import time
import numpy as np

JAM = 3600000
SESI_JUDUL = {"pagi": "🌅 LAPORAN PAGI · sesi Asia", "siang": "☀️ LAPORAN SIANG · jelang London", "malam": "🌙 LAPORAN MALAM · jelang New York",
              "tengah": "🌌 LAPORAN TENGAH MALAM · penutupan New York"}


def _hari_utc(now):
    return int(now // 86400) * 86400 * 1000


def karakter_sesi(d1, sesi, now=None):
    """d1: DataFrame candle 1 jam BTC yang sudah tutup (index ms). Return list baris."""
    now = now or time.time()
    # pagi dikirim 23:00 UTC: hari UTC yang hampir selesai (07:00 WIB kemarin sampai 06:00 WIB) jadi "kemarin"
    h0 = int((now - 3600) // 86400) * 86400000 if sesi == "pagi" else _hari_utc(now)
    g = d1[(d1.index >= h0) & (d1.index < h0 + 86400000)]
    hi = lambda a, b: g[(g.index >= h0 + a * JAM) & (g.index < h0 + b * JAM)]
    A, L, N = hi(0, 7), hi(7, 13), hi(13, 21)
    f = lambda x: f"{x:,.0f}"
    rows = []
    if sesi == "pagi":
        if len(g):
            rows.append(f"• Kemarin: high {f(g['high'].max())}, low {f(g['low'].min())}, tutup {f(g['close'].iloc[-1])}. "
                        "High dan low kemarin adalah kolam likuiditas terdekat.")
        rows.append("• Sesi Asia (07:00-14:00 WIB) biasanya membentuk rentang sempit: rata 1.6% lawan 3.6% sehari (2023-26). "
                    "Catat high dan low Asia, itu target sapuan London.")
    elif sesi == "siang":
        if len(A):
            rows.append(f"• Rentang Asia sejauh ini: high {f(A['high'].max())}, low {f(A['low'].min())} "
                        f"({(A['high'].max() / A['low'].min() - 1) * 100:.1f}%).")
        rows.append("• London (mulai 14:00 WIB) menyapu salah satu ujung rentang Asia di 78% hari. Arah sesudah sapuan 50:50, "
                    "jadi jangan entry hanya karena sapuan. Pakai angka Sniper di bagian pantauan.")
    elif sesi in ("malam", "tengah"):
        if len(A):
            ah, al = A["high"].max(), A["low"].min()
            rows.append(f"• Asia: high {f(ah)}, low {f(al)}.")
            if len(L):
                sh, sl = L["high"].max() > ah, L["low"].min() < al
                ket = ("menyapu high Asia" if sh and not sl else "menyapu low Asia" if sl and not sh else
                       "menyapu dua sisi" if sh and sl else "belum menyapu rentang Asia")
                rows.append(f"• London: high {f(L['high'].max())}, low {f(L['low'].min())}, {ket}.")
        if sesi == "malam":
            rows.append("• New York (mulai 20:00 WIB) membuat high atau low baru hari itu di 86% hari (2023-26). Volatilitas terbesar "
                        "biasanya di sini. Pastikan SL terpasang di Bybit sebelum 20:30 WIB.")
        elif len(N):
            rows.append(f"• New York: high {f(N['high'].max())}, low {f(N['low'].min())}, tutup {f(N['close'].iloc[-1])}.")
    return rows


def rotasi(tk):
    rows = []
    try:
        import qse_btcarah as BA
        d = BA._btcd()
        if d:
            rows.append(f"• BTC.D {d:.1f}%")
    except Exception:
        pass
    try:
        import qse_altseason as AS
        u = AS.ukur()
        if u:
            ke = "mengalir ke ALTCOIN" if u["rasio7"] > 2 else "tersedot ke BTC" if u["rasio7"] < -2 else "seimbang"
            rows.append(f"• Alt besar lawan BTC 7 hari: {u['rasio7']:+.1f}% (alt {u['alt7']:+.1f}%, BTC {u['btc7']:+.1f}%): dana {ke}")
    except Exception:
        pass
    top = sorted((s for s in tk if s.endswith("USDT") and s != "BTCUSDT"), key=lambda s: -tk[s]["turnover"])[:50]
    if top:
        naik = sum(1 for s in top if tk[s]["chg24"] > 0) / len(top) * 100
        kuat = "mayoritas NAIK" if naik >= 65 else "mayoritas TURUN" if naik <= 35 else "campur"
        rows.append(f"• 50 koin paling likuid: {naik:.0f}% naik dalam 24 jam ({kuat})")
        if naik <= 20:
            rows.append("  ↳ Hampir semua turun. Uji 2019-2026: koin yang sudah turun 2 ATR harian atau lebih dalam 3 hari "
                        "biasanya memantul (median +1% sampai +5% dalam 24 jam). SHORT baru di dasar sering terlambat.")
        elif naik >= 80:
            rows.append("  ↳ Hampir semua naik. LONG baru setelah lari jauh rawan koreksi, ikuti hanya sinyal robot.")
    return rows


def radar_bandar(tk):
    import bybit_fetch as B
    rows = []
    try:
        oi = B._get("/v5/market/open-interest", {"category": "linear", "symbol": "BTCUSDT", "intervalTime": "1h", "limit": 25}).get("list", [])
        if len(oi) >= 25:
            a, b = float(oi[-1]["openInterest"]), float(oi[0]["openInterest"])
            ch = (b / a - 1) * 100
            rows.append(f"• Open interest BTC 24 jam: {ch:+.1f}%" + (" (posisi baru menumpuk)" if ch >= 5 else " (posisi ditutup)" if ch <= -5 else ""))
    except Exception:
        pass
    b = tk.get("BTCUSDT")
    if b:
        rows.append(f"• Funding BTC {b['funding'] * 100:+.4f}% per 8 jam" + (" (long ramai)" if b["funding"] >= 0.0003 else
                                                                              " (short ramai)" if b["funding"] <= -0.0001 else ""))
    top = sorted((s for s in tk if s.endswith("USDT")), key=lambda s: -tk[s]["turnover"])[:60]
    sq_s = [s for s in top if tk[s]["funding"] <= -0.0005 and tk[s]["chg24"] > 0.03]
    sq_l = [s for s in top if tk[s]["funding"] >= 0.0005 and tk[s]["chg24"] < -0.03]
    if sq_s:
        rows.append("• Rawan SHORT SQUEEZE (funding sangat negatif tapi harga naik): " + ", ".join(
            f"{s.replace('USDT', '')} {tk[s]['funding'] * 100:+.3f}%" for s in sq_s[:4]) + ". Jangan SHORT melawan.")
    if sq_l:
        rows.append("• Rawan LONG SQUEEZE (funding sangat positif tapi harga turun): " + ", ".join(
            f"{s.replace('USDT', '')} {tk[s]['funding'] * 100:+.3f}%" for s in sq_l[:4]) + ". Jangan LONG melawan.")
    if not sq_s and not sq_l:
        rows.append("• Tidak ada koin likuid dengan funding ekstrem yang melawan harga.")
    return rows


def _valid_jalur(tk):
    """Sinyal jalur terbuka yang harga sekarang masih dalam 0.5R dari entry robot dan SL awal belum tersentuh."""
    out = []
    sumber = []
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            sumber += [(k, it) for it in ST.lihat(k)["open"].values()]
    except Exception:
        pass
    for mod, k in (("qse_ichimoku", "ichimoku"), ("qse_ob", "orderblock")):
        try:
            m = __import__(mod)
            sumber += [(k, it) for it in m.lihat()["open"].values()]
        except Exception:
            pass
    now = time.time()
    for k, it in sumber:
        px = (tk.get(it["sym"]) or {}).get("last")
        risk = it.get("risk") or abs(it["entry"] - it.get("sl0", it["sl"]))
        if not px or not risk or now - it.get("t", 0) > 8 * 3600:
            continue
        dR = (px - it["entry"]) * (1 if it["arah"] == "LONG" else -1) / risk
        if -0.5 <= dR <= 0.5:
            out.append((it["sym"], it["arah"], k, dR, it))
    return out


def pantauan(tk, maks=5):
    """v150: sinyal jalur yang masih valid (dengan blok salin), lalu rencana Sniper S/R berangka (LIMIT, SL, TP)."""
    import qse_saya as SY
    rows = []
    v = _valid_jalur(tk)
    v.sort(key=lambda z: -tk.get(z[0], {}).get("turnover", 0))
    for sym, arah, k, dR, it in v[:maks]:
        px = (tk.get(sym) or {}).get("last") or it["entry"]
        t = it.get("tick") or SY.tick_of(None, px)
        tp = it.get("tp")
        rows.append(f"• 🎯 <b>{sym} {arah}</b> sinyal {k} masih valid ({dR:+.2f}R dari entry robot), MARKET\n"
                    + SY.blok_salin(px, it["sl"], tp, tp, "MARKET", t, catatan_tp="" if tp else "tanpa, pakai Trailing Stop",
                                    sym=sym, arah=arah))
    if len(rows) >= 3:
        return rows
    try:
        import qse_rencana as RC
        rows += RC.baris_pantauan(tk, maks=maks - len(rows))
    except Exception as ex:
        print("[WARN] pantauan sniper", ex)
    return rows or ["• Belum ada koin likuid dengan level S/R dekat harga. Rencana dihitung ulang tiap 30 menit."]


def peringatan_hari_ini(now=None):
    now = now or time.time()
    rows = []
    try:
        import qse_berita as BR
        ms = int(now * 1000)
        for e in BR.kalender():
            if 0 <= e["ts"] - ms <= 24 * JAM and any(k in e["judul"].upper() for k in ("CPI", "FOMC", "FEDERAL FUNDS", "INTEREST RATE", "NFP",
                                                                                      "NONFARM", "FED ")):
                jam = time.strftime("%d %b %H:%M WIB", time.gmtime(e["ts"] / 1000 + 7 * 3600))
                rows.append(f"• 🔴 {e['judul']} {jam}. Mode siaga otomatis: 1 jam sebelum rilis posisi untung ditutup, "
                            "sinyal baru ditahan sampai 1 jam sesudah rilis.")
    except Exception:
        pass
    try:
        import qse_unlock as UL
        for e in UL.kalender(hari=1, now=now)[:3]:
            rows.append(f"• 🔓 Unlock {e['sym']} {e['pct']:.1f}% pasokan {UL._jam(e['t'])}. LONG koin ini ditahan robot 7 hari sebelum unlock.")
    except Exception:
        pass
    return rows


def teks(sesi="pagi", now=None):
    import bybit_fetch as B
    import qse_btcmap as BM
    now = now or time.time()
    tk = B.get_tickers()
    p = BM.peta()
    ms = int(now * 1000)
    d1 = B._raw("BTCUSDT", "60", 60)
    d1 = d1[d1.index + JAM <= ms]
    blok = [f"<b>QSE v150 | {SESI_JUDUL.get(sesi, 'LAPORAN SESI')}</b>", "",
            "<b>1. Peta BTC</b>", BM.teks(p), "",
            "<b>2. Karakter sesi</b>", *karakter_sesi(d1, sesi, now), "",
            "<b>3. Rotasi dana</b>", *(rotasi(tk) or ["• Data belum tersedia"]), "",
            "<b>4. Radar bandar (funding dan open interest)</b>", *radar_bandar(tk), "",
            "<b>5. Pantauan koin</b>", *pantauan(tk)]
    pw = peringatan_hari_ini(now)
    if pw:
        blok += ["", "<b>⚠️ Peringatan hari ini</b>", *pw]
    return "\n".join(blok)


def amd_melawan(sym, arah, now=None):
    """v150 (riset/upgrade/hasil_v157_lokasi.txt): sinyal 4J v150 dilewati kalau range Asia hari ini (00-08 UTC) sudah disapu
    BERLAWANAN arah sinyal lalu harga kembali masuk range (pola AMD). Dipilih di 2023-2024: 152 sinyal rata -0.002R lawan +0.127R.
    Dicek di 2025-2026 yang tidak ikut memilih: 155 sinyal rata -0.028R lawan +0.133R. Return teks alasan atau ''."""
    try:
        import qse_saya as SY
        now = now or time.time()
        jam = time.gmtime(now).tm_hour
        if jam < 8:
            return ""
        d0 = int(now // 86400 * 86400 * 1000)
        b = [x for x in SY._kline(sym, "60", 30) if x[0] + 3600000 <= now * 1000]
        asia = [x for x in b if d0 <= x[0] < d0 + 8 * 3600000]
        lanjut = [x for x in b if x[0] >= d0 + 8 * 3600000]
        if len(asia) < 8 or not lanjut:
            return ""
        ah, al, c = max(x[1] for x in asia), min(x[2] for x in asia), b[-1][3]
        if not (al < c < ah):
            return ""
        if arah == "LONG" and min(x[2] for x in lanjut) < al:
            return "AMD melawan: low Asia sudah disapu lalu harga balik ke range (uji 2023-2026 rata -0.01R)"
        if arah == "SHORT" and max(x[1] for x in lanjut) > ah:
            return "AMD melawan: high Asia sudah disapu lalu harga balik ke range (uji 2023-2026 rata -0.01R)"
    except Exception:
        return ""
    return ""
