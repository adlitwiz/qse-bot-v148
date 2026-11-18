"""QC 104 🧭 VONIS PASAR. Satu perintah yang memutuskan arah altcoin DETIK INI dari semua bahan yang robot punya:
BTC di 15 menit, 1 jam, 4 jam (kompas), jarak BTC 4J ke EMA 50, USDT.D, BTC.D, lebar pasar (berapa persen altcoin naik 24 jam),
kekuatan altcoin dibanding BTC, funding altcoin, rasio akun LONG/SHORT dan funding BTC (himbauan), dan Fear and Greed.

Tiap bahan memberi suara naik (+), turun (-), atau netral, dengan bobot:
  BTC 4J lawan EMA 50  bobot 3  (teruji: sinyal searah sisi BTC PF 1.4-2.0, melawan sisi BTC PF 0.9-1.3, riset v204 dan QC 71-74)
  USDT.D               bobot 2
  lebar pasar 24 jam   bobot 2
  BTC 15m, 1J, 4J      bobot 1 masing-masing
  BTC.D                bobot 1
  altcoin lawan BTC    bobot 1
  sinyal semua teknik  bobot 2  (QC 106: sinyal 11 jalur yang dibuka 24 jam terakhir, 70% atau lebih satu arah)
Jumlah suara -14 sampai +14. Vonis: +5 atau lebih = LONG ALTCOIN, -5 atau kurang = SHORT ALTCOIN, di antaranya NETRAL.
Funding, rasio L/S, dan Fear and Greed ditampilkan sebagai catatan kerumunan, tidak ikut suara (ujinya tidak konsisten, riset v201).
Vonis ini ringkasan keadaan, bukan sinyal entry. Sinyal tetap dari teknik yang lolos uji.
Perubahan vonis (LONG <-> SHORT, bertahan 2 pemeriksaan) dikabarkan ke grup dan pemilik posisi yang melawan di-tag.
Saklar QSE_VONIS=0 mematikan kabar otomatis. Perintah /pasar tetap jalan.

QC 107: keluaran /pasar dibuat konkrit, tiga jawaban di depan: (a) keputusan FOKUS LONG / FOKUS SHORT / TRANSISI dengan jumlah bahan searah,
umur tren BTC, dan ukuran posisi, (b) nasib tiap posisi yang jalan terhadap vonis, lengkap dengan harga SL, harga +0.5R, dan tindakan yang
SUDAH TERUJI (bukan saran baru: cutloss lebih awal dan kunci profit lebih awal ditolak uji QC 104), (c) 1-2 sinyal valid searah vonis yang
harganya masih layak, dengan Entry, SL, TP. Daftar suara tiap bahan pindah ke bawah."""
import html
import json
import os
import time

STATE_DIR = os.environ.get("QSE_STATE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"))
PATH = os.path.join(STATE_DIR, "vonis.json")
AMBANG = 5
TOP = 100


def _baca():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PATH + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PATH + ".tmp", PATH)


def bahan():
    """Kumpulkan semua data live. Tiap sumber gagal sendiri-sendiri tanpa menggagalkan yang lain."""
    x = {}
    try:
        import qse_kompas as KP
        x["kompas"] = KP.kompas()
    except Exception as ex:
        print("[WARN] vonis kompas", ex)
    try:
        import qse_strat as ST
        x["bj"] = ST.btc_jarak()
    except Exception as ex:
        print("[WARN] vonis btc jarak", ex)
    try:
        import qse_strat as ST
        x["umur"] = ST.umur_tren(); x["fase"] = ST.fase_tua(x["umur"])
    except Exception as ex:
        print("[WARN] vonis umur", ex)
    try:
        import bybit_fetch as B
        x["tickers"] = B.get_tickers()
    except Exception as ex:
        print("[WARN] vonis tickers", ex)
    try:          # QC 106: suara dari SEMUA teknik robot (11 jalur): sinyal yang dibuka 24 jam terakhir, LONG lawan SHORT
        import qse_gurita as GR
        now = time.time()
        baru = [it for _, it in GR._sumber() if now - float(it.get("t") or 0) <= 86400 and not it.get("radar")]
        x["teknik"] = (sum(1 for it in baru if it.get("arah") == "LONG"), sum(1 for it in baru if it.get("arah") == "SHORT"))
    except Exception as ex:
        print("[WARN] vonis teknik", ex)
    try:
        import qse_himbauan as QH
        x["himbauan"] = (QH._baca().get("data") or {})
    except Exception:
        pass
    try:
        import qse_btcarah as BA
        x["fng"] = BA._fng()
    except Exception:
        pass
    return x


def hitung(x=None):
    """Return dict(vonis, skor, maks, faktor=[(nama, nilai, suara, bobot)], catatan=[...], kuat=[...], lemah=[...])."""
    x = x if x is not None else bahan()
    F, cat = [], []
    k = x.get("kompas") or {}
    bj = x.get("bj")
    if bj is not None:
        F.append(("BTC 4J lawan EMA 50", f"{bj:+.1f}%", 1 if bj > 1 else -1 if bj < -1 else 0, 3))
    for nm, key in (("BTC 15 menit", "s15"), ("BTC 1 jam", "s1"), ("BTC 4 jam", "s4")):
        if key in k:
            v = k[key]
            F.append((nm, "naik" if v > 0 else "turun" if v < 0 else "datar", 1 if v > 0 else -1 if v < 0 else 0, 1))
    u = k.get("usdt") or {}
    if u:
        ch = f" ({u['ch24']:+.2f}% 24 jam)" if u.get("ch24") is not None else ""
        F.append(("USDT.D", ("naik, uang keluar ke tunai" if u.get("naik") else "turun, uang masuk kripto" if u.get("turun") else "datar") + ch,
                  -1 if u.get("naik") else 1 if u.get("turun") else 0, 2))
    b = k.get("btcd") or {}
    if b:
        ch = f" ({b['ch24']:+.2f}% 24 jam)" if b.get("ch24") is not None else ""
        F.append(("BTC.D", ("naik, altcoin kalah dari BTC" if b.get("naik") else "turun, altcoin lebih kuat" if b.get("turun") else "datar") + ch,
                  -1 if b.get("naik") else 1 if b.get("turun") else 0, 1))
    tk = x.get("tickers") or {}
    kuat, lemah = [], []
    if tk:
        alt = sorted(((s, v) for s, v in tk.items() if s.endswith("USDT") and s not in ("BTCUSDT", "USDCUSDT")),
                     key=lambda z: -z[1].get("turnover", 0))[:TOP]
        ch = sorted(v["chg24"] * 100 for _, v in alt)
        if len(ch) >= 20:
            naik = sum(1 for c in ch if c > 0) / len(ch) * 100
            med = ch[len(ch) // 2]
            F.append(("Lebar pasar", f"{naik:.0f}% dari {len(ch)} altcoin terlikuid naik 24 jam, tengah {med:+.1f}%",
                      1 if naik >= 60 else -1 if naik <= 40 else 0, 2))
            btc = (tk.get("BTCUSDT") or {}).get("chg24")
            if btc is not None:
                rel = med - btc * 100
                F.append(("Altcoin lawan BTC", f"altcoin tengah {med:+.1f}% lawan BTC {btc * 100:+.1f}% (selisih {rel:+.1f})",
                          1 if rel >= 1 else -1 if rel <= -1 else 0, 1))
            fd = sorted(v.get("funding", 0) * 100 for _, v in alt)
            fm = fd[len(fd) // 2]
            cat.append(f"Funding altcoin tengah {fm:+.4f}%" + (": LONG ramai, rawan dibanting" if fm >= 0.02 else
                                                               ": SHORT ramai, rawan short squeeze" if fm <= -0.005 else ": wajar"))
            urut = sorted(alt, key=lambda z: -z[1]["chg24"])
            kuat = [(s.replace("USDT", ""), v["chg24"] * 100) for s, v in urut[:5]]
            lemah = [(s.replace("USDT", ""), v["chg24"] * 100) for s, v in urut[-5:][::-1]]
    if x.get("teknik") is not None:
        nl, ns = x["teknik"]
        tot = nl + ns
        suara = 0 if tot < 4 else 1 if nl / tot >= 0.7 else -1 if ns / tot >= 0.7 else 0
        F.append(("Sinyal semua teknik 24 jam", f"{nl} LONG lawan {ns} SHORT dari 11 jalur" + (" (terlalu sedikit untuk bersuara)" if tot < 4 else ""), suara, 2))
    h = x.get("himbauan") or {}
    try:
        import qse_himbauan as QH
        if h.get("ls") is not None:
            cat.append(f"Rasio akun L/S BTC {h['ls']:.2f}" + (": 🔻 rawan dump, ritel LONG ramai" if h["ls"] >= QH.LS_DUMP else ": wajar"))
        if h.get("f3") is not None:
            cat.append(f"Funding BTC 3 hari {h['f3'] * 100:.4f}%" + (": 🔺 rawan pump, SHORT ramai" if h["f3"] <= QH.FUND_PUMP else ": wajar"))
    except Exception:
        pass
    if x.get("fng") is not None:
        g = x["fng"]
        cat.append(f"Fear and Greed {g}" + (" (takut ekstrem)" if g <= 20 else " (takut)" if g < 40 else " (serakah ekstrem)" if g >= 80
                                             else " (serakah)" if g > 60 else " (netral)"))
    skor = sum(s * w for _, _, s, w in F)
    maks = sum(w for _, _, _, w in F)
    lengkap = maks >= 9
    vonis = "LONG" if skor >= AMBANG else "SHORT" if skor <= -AMBANG else "NETRAL"
    if not lengkap:
        vonis = "NETRAL"
    return dict(vonis=vonis, skor=skor, maks=maks, faktor=F, catatan=cat, kuat=kuat, lemah=lemah, lengkap=lengkap,
                kompas=k.get("status"), t=time.time(), bj=bj, umur=x.get("umur"), fase=x.get("fase"), himbauan=h,
                harga={s_: v_.get("last") for s_, v_ in tk.items() if v_.get("last")} if tk else {})


def rsi4j(sym, df=None):
    """RSI 14 Wilder dari candle 4J yang sudah tutup, atau None."""
    try:
        if df is None:
            import bybit_fetch as B
            df = B._raw(sym, "240", 80)
        c = [float(x) for x in df["close"].values[:-1]]
        if len(c) < 30:
            return None
        up = [max(b - a, 0) for a, b in zip(c, c[1:])]; dn = [max(a - b, 0) for a, b in zip(c, c[1:])]
        au, ad = sum(up[:14]) / 14, sum(dn[:14]) / 14
        for u_, d_ in zip(up[14:], dn[14:]):
            au, ad = (au * 13 + u_) / 14, (ad * 13 + d_) / 14
        return 100 - 100 / (1 + au / max(ad, 1e-12))
    except Exception:
        return None


def vonis_terakhir(maks_umur=3600):
    try:
        d = _baca()
        if time.time() - float(d.get("t", 0)) <= maks_umur:
            return d.get("calon")
    except Exception:
        pass
    return None


# QC 112 LOT MOMENTUM (riset/upgrade/run_v228_momentum.py, hasil_v228_momentum.txt). Populasi siaran, keluar terpasang:
#   LONG saat RSI 4J >= 65 dan vonis BUKAN LONG: PF 0.86 / 0.47 / 0.55 / 0.99 (latih, uji, 12 bln, 6 bln). Lot kartu 0.5x: buku siaran 12 slot
#   1126/714/228/261 -> 1186/839/257/268. Tidak dipakai di Gurita (Gurita uji 2065 -> 2038).
#   LONG saat RSI 4J >= 75: PF 2.04/2.24/2.23/3.32. Gurita risiko x1.5 (maks 2.25 total): 1092/2065/212/177 -> 1167/2159/226/190, DD sama.
#   Tetangga: RSI >= 70 x1.5 uji 2059 (turun tipis), RSI >= 65 x1.5 uji 1905 (turun). Kartu siaran x1.5 tidak lolos (latih 1126 -> 1113).
MOM_LEMAH, MOM_KUAT = 65.0, 75.0


def lot_momentum(sym, arah, vonis=None, rs=None):
    """(kali lot kartu, teks). LONG jenuh beli tanpa vonis LONG: 0.5x."""
    if arah != "LONG" or os.environ.get("QSE_MOMENTUM", "1") == "0":
        return 1.0, ""
    v = vonis or vonis_terakhir()
    if v == "LONG" or v is None:
        return 1.0, ""
    rs = rsi4j(sym) if rs is None else rs
    if rs is not None and rs >= MOM_LEMAH:
        return 0.5, (f"📉 <b>LOT 0.5x</b>: LONG di RSI 4J {rs:.0f} saat vonis {v}. Uji 2022-2026 kelompok ini PF 0.86 / 0.47 / 0.55 / 0.99. "
                     "Tunggu vonis LONG untuk lot penuh.")
    return 1.0, ""


IKON = {"LONG": "🟢", "SHORT": "🔴", "NETRAL": "⚪"}
JUDUL = {"LONG": "🟢 FOKUS LONG", "SHORT": "🔴 FOKUS SHORT", "NETRAL": "⚪ TRANSISI / TUNGGU PANTULAN"}
UKURAN = {          # QC 110: hanya angka uji vonis historis (run_v226_vonis.py), bukan saran baru
    "LONG": ("Sinyal LONG: <b>lot 1.5x</b> (LONG searah vonis PF 1.57 / 1.74 / 1.50 / 1.98 di latih, uji, 12 bulan, 6 bulan. Buku Gurita "
             "otomatis x1.5). Sinyal SHORT: lot normal. Membuang SHORT lawan vonis TIDAK terbukti lebih untung, jadi tidak perlu dibuang."),
    "SHORT": ("Sinyal SHORT: <b>lot normal, jangan dibesarkan</b> (SHORT searah vonis 12 bulan PF 1.13, 6 bulan 0.99). Sinyal LONG: lot normal "
              "(LONG lawan vonis 12 bulan PF 1.14, 6 bulan 1.34, tidak lebih jelek)."),
    "NETRAL": ("Semua sinyal <b>lot normal</b>. LONG saat netral tidak konsisten (uji 2025-2026 PF 0.88), SHORT saat netral PF 1.06 sampai 1.33. "
               "Tunggu vonis LONG untuk membesarkan lot."),
}
ARTI = UKURAN          # nama lama, dipakai uji


def _fp(x, sym=None):
    import qse_saya as SY
    return SY.fp(x, SY.tick_of(None, x))


def _harga(v, sym):
    px = (v.get("harga") or {}).get(sym)
    if px:
        return float(px)
    try:
        import qse_saya as SY
        return SY.harga_live(sym)
    except Exception:
        return None


def nasib(v, tag=False):
    """Baris per posisi jalan: searah atau melawan vonis, dengan harga dan tindakan yang sudah teruji.
    tag=True: semua orang, pemilik di-tag. tag=False: orang yang sedang aktif saja."""
    import qse_saya as SY
    vonis = v["vonis"]
    h = v.get("himbauan") or {}
    try:
        import qse_himbauan as QH
        kd = QH.kondisi(h.get("ls"), h.get("f3"))
        amb_h = QH.AMBANG_R
    except Exception:
        kd, amb_h = {}, 0.5

    def isi():
        d = SY._load()
        out = []
        for it in d["open"].values():
            if it.get("status") not in ("TERISI", "TP1"):
                continue
            sym, arah = it["sym"], it["arah"]
            L = arah == "LONG"
            px = _harga(v, sym)
            fl = SY.floating(it, px) if px else None
            r = fl["r"] if fl else None
            e, sl = float(it["entry"]), float(it["sl"])
            risk = float(it.get("risk0") or abs(e - sl) or 0)
            h05 = e + (0.5 * risk if L else -0.5 * risk)
            rt = f" {r:+.2f}R" if r is not None else ""
            kepala = f"<b>{sym} {arah}</b>{rt}"
            aman = it.get("status") == "TP1" or (sl - e) * (1 if L else -1) >= 0          # TP awal sudah kena atau SL sudah di entry
            rawan = (kd.get("dump") and L) or (kd.get("pump") and not L)
            if rawan and r is not None and r >= amb_h:
                out.append(f"🚨 {kepala}  ·  Himbauan BTC {'rawan dump' if L else 'rawan pump'} aktif. <b>KUNCI PROFIT: tutup MARKET di {_fp(px)}</b> "
                           f"(aturan teruji 4 periode).")
            elif vonis == "NETRAL":
                out.append(f"⚪ {kepala}  ·  pasar transisi. Tahan, SL {_fp(sl)}."
                           + ("" if aman or not risk else f" Di {_fp(h05)} (+0.5R): tutup 20%, geser SL ke {_fp(e)}."))
            elif arah == vonis:
                out.append(f"✅ {kepala}  ·  <b>SEARAH VONIS</b>. Aman, tahan. SL {_fp(sl)}"
                           + (", sisa ikut SL berjalan." if aman or not risk else
                              f". TP awal +0.5R sudah tercapai: tutup 20% di {_fp(px)}, geser SL ke {_fp(e)}." if r is not None and r >= 0.5 else
                              f". Di {_fp(h05)} (+0.5R): tutup 20%, geser SL ke {_fp(e)}."))
            elif aman:
                out.append(f"⚠️ {kepala}  ·  <b>MELAWAN VONIS</b>, tapi sudah aman: SL {_fp(sl)} di entry atau lebih baik. Jangan tambah. "
                           f"Sisa ikut SL berjalan.")
            elif r is not None and r >= 0.5 and risk:
                out.append(f"⚠️ {kepala}  ·  <b>MELAWAN VONIS</b>. <b>Kunci sekarang: tutup 20% di {_fp(px)} dan geser SL ke {_fp(e)}</b> "
                           f"(TP awal +0.5R sudah lewat).")
            elif r is not None and r > 0 and risk:
                out.append(f"⚠️ {kepala}  ·  <b>MELAWAN VONIS</b>, untung kecil. Jangan tambah. SL tetap {_fp(sl)}. "
                           f"Begitu {_fp(h05)} (+0.5R): tutup 20%, geser SL ke {_fp(e)}.")
            else:
                out.append(f"⚠️ {kepala}  ·  <b>MELAWAN VONIS</b>, minus. Jangan serok. SL tetap {_fp(sl)}, biarkan SL bekerja "
                           f"(cutloss lebih awal saat arah berubah diuji rugi di 4 periode).")
        return out
    if not tag:
        return isi()

    @SY.per_orang
    def _isi_arah():
        return isi()
    return _isi_arah()


def _posisi(vonis, tag=False):
    """Nama lama (QC 104), dipakai kabar perubahan vonis: baris posisi yang melawan."""
    return [b for b in nasib(dict(vonis=vonis), tag) if "MELAWAN" in b or "KUNCI" in b] if vonis in ("LONG", "SHORT") else []


def siap_tembak(v, maks=2, now=None, sumber=None):
    """1-2 sinyal valid searah vonis yang harganya masih layak diambil DETIK INI. Sumber: sinyal terbuka dari 11 jalur robot (SL belum kena),
    bukan tahanan, umur maksimal 8 jam, harga tidak lari lebih dari +0.25R dan tidak terkoreksi lebih dari 0.40R (uji v214: koreksi lebih
    dalam PF 0.7-0.9). Saat TRANSISI hanya konfluensi 2+ teknik yang searah sisi BTC 4J. Return list (teks kepala, blok level)."""
    import qse_saya as SY
    now = now or time.time()
    vonis, bj = v["vonis"], v.get("bj")
    arah_ok = vonis if vonis in ("LONG", "SHORT") else ("LONG" if (bj or 0) > 0 else "SHORT" if (bj or 0) < 0 else None)
    if not arah_ok:
        return []
    if sumber is None:
        import qse_gurita as GR
        sumber = GR._sumber()
    try:
        import qse_gurita as GR
        ditahan = GR._ditahan
    except Exception:
        ditahan = lambda k, it: False
    try:
        import qse_strat as ST
        nama = lambda k: (ST.STRAT.get(k) or {}).get("nama") or {"ichimoku": "Ichimoku", "orderblock": "Order Block"}.get(k, k)
    except Exception:
        nama = lambda k: k
    try:
        import qse_radar as RD
    except Exception:
        RD = None
    kand = {}
    for k, it in sumber:
        try:
            if it.get("arah") != arah_ok or it.get("uji_live") or it.get("radar") or now - float(it.get("t") or 0) > 8 * 3600:
                continue
            sym = it["sym"]; L = arah_ok == "LONG"
            e, risk = float(it["entry"]), float(it.get("risk") or 0)
            sl = float(it.get("sl0") or it["sl"])
            px = _harga(v, sym)
            if not px or not risk > 0 or (px - sl) * (1 if L else -1) <= 0:
                continue
            g = (px - e) * (1 if L else -1) / risk
            konf = len(it.get("combo") or []) + 1
            if not (-0.40 <= g <= 0.25) or (vonis == "NETRAL" and konf < 2):
                continue
            try:
                if ditahan(k, it):
                    continue
            except Exception:
                pass
            umur = (now - float(it["t"])) / 3600
            gm = False
            if RD is not None and L and konf >= 2:
                t4 = (int(float(it["t"]) // 14400) * 14400 - 14400) * 1000
                gm = RD.golden(dict(arah="LONG", ringan=False, konf=konf, mundur=False, intrabar=0, t4=t4, entry_robot=e, risk=risk, sym=sym, geser=g),
                               bj, now)
            c = dict(k=k, it=it, sym=sym, px=px, sl=sl, e=e, risk=risk, g=g, konf=konf, umur=umur, gm=gm, nama=[nama(k)])
            lama = kand.get(sym)
            if lama:          # koin sama dari jalur lain: gabung nama teknik, pakai yang konfluensinya lebih besar
                c["nama"] = lama["nama"] + [n_ for n_ in c["nama"] if n_ not in lama["nama"]]
                if lama["konf"] >= c["konf"]:
                    lama["nama"] = c["nama"]; continue
            kand[sym] = c
        except Exception as ex:
            print("[WARN] vonis siap tembak", it.get("sym"), ex)
    urut = sorted(kand.values(), key=lambda c: (not c["gm"], -min(c["konf"], 3), c["umur"]))[:maks]
    out = []
    for c in urut:
        it = c["it"]; L = arah_ok == "LONG"; d_ = 1 if L else -1
        rn = (c["px"] - c["sl"]) * d_
        tpr = (float(it["tp"]) - c["e"]) * d_ / c["risk"] if it.get("tp") else None
        tp = c["px"] + d_ * tpr * rn if tpr else None
        geser = ("harga masih di harga sinyal" if abs(c["g"]) < 0.05 else f"harga diskon {abs(c['g']):.2f}R dari harga sinyal" if c["g"] < 0
                 else f"harga sudah jalan {c['g']:.2f}R dari harga sinyal")
        kelas = "Kelas Utama, konfluensi " + str(c["konf"]) + " teknik" if c["konf"] >= 2 else "1 teknik"
        kepala = (f"{'✨ ' if c['gm'] else ''}{'🟢' if L else '🔴'} <b>{c['sym']} {arah_ok}</b>  ·  {kelas} ({html.escape(', '.join(c['nama'][:3]))})"
                  f"  ·  umur {c['umur']:.1f} jam  ·  {geser}"
                  + ("  ·  ✨ <b>GOLDEN MOMENT</b> (uji 2022-2026 PF 1.78-2.30)" if c["gm"] else ""))
        blok = SY.blok_salin(c["px"], c["sl"], tp, tp, "MARKET", it.get("tick"), sym=c["sym"], arah=arah_ok, sebagian=True,
                             catatan_tp="" if tp else "tanpa, pakai SL berjalan")
        out.append((kepala, blok))
    return out


def baris_dominasi(v):
    """QC 109: USDT.D dan BTC.D dalam angka (CoinGecko), perubahan 24 jam, arti, dan suaranya di vonis. Plus beda Kompas dan Vonis."""
    import qse_kompas as KP
    cg = KP._cg(); ch = KP._cg_24j()
    sv = {nm: (nilai, s * w) for nm, nilai, s, w in v["faktor"]}
    def b(nm, key, naik_arti, turun_arti):
        x = f"{cg[key]:.2f}%" if cg and cg.get(key) else "angka belum terbaca"
        c = f", {ch[key]:+.2f} poin dalam {ch['jam']:.0f} jam" if ch else ""
        st = sv.get(nm)
        arah = (st[0].split(" (")[0] if st else "belum terbaca")
        arti = naik_arti if arah.startswith("naik") else turun_arti if arah.startswith("turun") else "tidak memberi arah"
        return f"• <b>{nm} {x}</b>{c}: tren {arah.split(',')[0]}, {arti} (suara {st[1] if st else 0:+d})"
    k = v.get("kompas")
    return ("💵 <b>Dominasi</b>\n" + b("USDT.D", "usdt", "uang keluar ke stablecoin, tekanan TURUN", "uang masuk ke kripto, dorongan NAIK") + "\n"
            + b("BTC.D", "btc", "BTC lebih kuat dari altcoin, altcoin rawan", "altcoin lebih kuat dari BTC") + "\n"
            + (f"ℹ️ Kompas di kartu sinyal ({html.escape(str(k))}) hanya membaca BTC 15 menit sampai 1 jam dan cepat berubah. "
               "Vonis ini gabungan semua bahan dan lebih lambat berubah. Kalau keduanya beda, arah jangka pendek dan arah besar sedang tidak sama."
               if k else ""))


def teks(v=None, tag=False, judul="ARAH PASAR DETIK INI"):
    v = v or hitung()
    F = v["faktor"]
    tanda = 1 if v["skor"] > 0 else -1 if v["skor"] < 0 else 0
    naik = sum(1 for _, _, s, _ in F if s > 0); turun = sum(1 for _, _, s, _ in F if s < 0)
    if v["vonis"] == "NETRAL":
        konfl = f"{naik} bahan naik, {turun} turun, {len(F) - naik - turun} netral dari {len(F)}"
    else:
        konfl = f"{naik if tanda > 0 else turun} dari {len(F)} bahan searah"
    rows = [f"🧭 <b>{judul}: {JUDUL[v['vonis']]}</b>\nKonfluensi makro: <b>{konfl}</b>  ·  suara {v['skor']:+d} dari ±{v['maks']}"
            + (f"  ·  kompas {html.escape(str(v['kompas']))}" if v.get("kompas") else "")]
    if not v.get("lengkap"):
        rows.append("⚠️ Data belum lengkap (sebagian sumber gagal dibaca), vonis ditahan di TRANSISI.")
    try:          # QC 111: umur vonis. Uji v226/v227: vonis berganti rata-rata tiap 8 jam, vonis 3 hari lebih stabil tapi lebih jelek
        d_ = _baca()
        if d_.get("calon") == v["vonis"] and d_.get("calon_t"):
            j_ = (time.time() - float(d_["calon_t"])) / 3600
            rows.append(f"⏱ Vonis ini berlaku sejak {j_:.1f} jam lalu. Rata-rata vonis berganti tiap 8 jam (uji 2022-2026). Posisi yang sudah jalan "
                        "TIDAK perlu ditutup karena vonis berubah: ikuti SL, TP, dan pesan Himbauan atau Hidung Abdul saja.")
    except Exception:
        pass
    try:          # QC 109: angka asli dominasi, selalu tampil
        rows.append(baris_dominasi(v))
    except Exception as ex:
        print("[WARN] vonis dominasi", ex)
    u = v.get("umur")
    ukur = "📏 <b>Ukuran posisi:</b> " + UKURAN[v["vonis"]]
    if v.get("bj") is not None and v["vonis"] == "NETRAL":
        ukur += f" Sisi BTC 4J sekarang: <b>{'LONG' if v['bj'] > 0 else 'SHORT'}</b> ({v['bj']:+.1f}% dari EMA 50)."
    if u:
        fase = v.get("fase") or ""
        ket = ("⏳ jenuh jual, SHORT baru ditahan robot" if fase == "TURUN" else "⏳ jenuh beli, LONG baru ditahan robot sampai hari ke-7" if fase == "NAIK"
               else "tren muda, sinyal searah paling bagus (uji PF 1.6-1.9)" if u[1] <= 2 else "tren berjalan")
        ukur = f"⏳ <b>Umur tren:</b> BTC 4J sudah {u[1]:.1f} hari {'di atas' if u[0] > 0 else 'di bawah'} EMA 50  ·  {ket}\n" + ukur
    rows.append(ukur)
    try:
        ns = nasib(v, tag)
        rows.append("👤 <b>NASIB POSISI YANG JALAN</b>\n" + ("\n".join(ns) if ns else "Tidak ada posisi yang sedang jalan."))
    except Exception as ex:
        print("[WARN] vonis posisi", ex)
    try:
        st = siap_tembak(v)
        if st:
            rows.append("🎯 <b>SIAP TEMBAK DETIK INI</b> (sinyal valid robot, searah " + ("vonis" if v["vonis"] != "NETRAL" else "sisi BTC, ukuran ringan") + ")\n"
                        + "\n".join(f"{i}. {k_}\n{b_}" for i, (k_, b_) in enumerate(st, 1)))
        else:
            rows.append("🎯 <b>SIAP TEMBAK DETIK INI</b>\nBelum ada. Sinyal searah yang masih terbuka harganya sudah lari lebih dari 0.25R, terkoreksi lebih "
                        "dari 0.40R, atau belum ada pemicu baru. Tunggu candle 4J berikutnya atau tekan 📡 Sinyal 4J.")
    except Exception as ex:
        print("[WARN] vonis siap tembak", ex)
    fr = [f"{'🟢' if s > 0 else '🔴' if s < 0 else '⚪'} {nm}: {html.escape(nilai)}  ({s * w:+d})" for nm, nilai, s, w in F]
    rows.append("<b>Suara tiap bahan</b>\n" + "\n".join(fr))
    if v["catatan"]:
        rows.append("<b>Kerumunan (tidak ikut suara)</b>\n" + "\n".join("• " + html.escape(c) for c in v["catatan"]))
    if v["kuat"]:
        rows.append("💪 Terkuat 24 jam: " + ", ".join(f"{s} {c:+.1f}%" for s, c in v["kuat"])
                    + "\n🥀 Terlemah 24 jam: " + ", ".join(f"{s} {c:+.1f}%" for s, c in v["lemah"]))
    return "\n\n".join(rows)


def cek(now=None, v=None):
    """Dipanggil tiap menit, bekerja tiap 15 menit. Kabar saat vonis berubah ke LONG atau SHORT dan bertahan 2 pemeriksaan.
    Return list pesan."""
    if os.environ.get("QSE_VONIS", "1") == "0":
        return []
    now = now or time.time()
    d = _baca()
    if v is None and now - d.get("t", 0) < 900:
        return []
    d["t"] = now
    try:
        v = v or hitung()
    except Exception as ex:
        print("[WARN] vonis hitung", ex)
        _tulis(d)
        return []
    out = []
    baru = v["vonis"]
    if baru == d.get("calon"):
        d["n"] = d.get("n", 0) + 1
    else:
        d["calon"], d["n"], d["calon_t"] = baru, 1, now          # QC 111: catat sejak kapan vonis ini berlaku
    resmi = d.get("resmi")
    if resmi is None:
        d["resmi"] = baru          # jalan pertama: catat saja
    elif baru != resmi and d["n"] >= 2 and v.get("lengkap"):
        d["resmi"] = baru
        if baru in ("LONG", "SHORT") and now - d.get("kirim", 0) >= 4 * 3600:
            d["kirim"] = now
            out.append(teks(v, tag=True, judul=f"ARAH PASAR BERUBAH ({resmi} jadi {baru})"))
    d["akhir"] = dict(vonis=baru, skor=v["skor"], maks=v["maks"])
    _tulis(d)
    return out
