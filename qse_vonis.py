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
Saklar QSE_VONIS=0 mematikan kabar otomatis. Perintah /pasar tetap jalan."""
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
                kompas=k.get("status"), t=time.time())


IKON = {"LONG": "🟢", "SHORT": "🔴", "NETRAL": "⚪"}
ARTI = {
    "LONG": ("Arus mendukung LONG altcoin. Ambil sinyal LONG Kelas Utama. SHORT hanya konfluensi 2+ teknik, ukuran ringan. "
             "Posisi SHORT yang jalan: jangan ditambah, pastikan SL terpasang."),
    "SHORT": ("Arus mendukung SHORT altcoin. Ambil sinyal SHORT Kelas Utama. LONG hanya konfluensi 2+ teknik, ukuran ringan. "
              "Posisi LONG yang jalan: jangan ditambah, pastikan SL terpasang."),
    "NETRAL": ("Arah campur, belum ada pihak yang menang. Sinyal dua arah tetap boleh, pilih yang searah sisi BTC 4J dan konfluensi 2+ teknik "
               "(uji saat BTC netral: 2+ teknik searah PF 1.6-2.9, melawan sisi BTC PF 0.7-1.4). Jangan besarkan ukuran."),
}


def _posisi(vonis, tag=False):
    """Baris posisi yang melawan vonis. tag=True: semua orang, pemilik di-tag. tag=False: orang yang sedang aktif saja."""
    if vonis not in ("LONG", "SHORT"):
        return []
    import qse_saya as SY

    def isi():
        d = SY._load()
        out = []
        for it in d["open"].values():
            if it.get("status") in ("TERISI", "TP1") and it["arah"] != vonis:
                px = SY.harga_live(it["sym"])
                fl = SY.floating(it, px) if px else None
                out.append(f"{'🟢' if it['arah'] == 'LONG' else '🔴'} {it['sym']} {it['arah']}" + (f" {fl['r']:+.2f}R" if fl else ""))
        return [("Posisi melawan vonis: " + ", ".join(out))] if out else []
    if not tag:
        return isi()

    @SY.per_orang
    def _isi_arah():
        return isi()
    return _isi_arah()


def teks(v=None, tag=False, judul="VONIS PASAR DETIK INI"):
    v = v or hitung()
    rows = [f"🧭 <b>{judul}: {IKON[v['vonis']]} {'NETRAL' if v['vonis'] == 'NETRAL' else v['vonis'] + ' ALTCOIN'}</b>  ·  suara {v['skor']:+d} dari ±{v['maks']}"
            + (f"  ·  kompas {html.escape(str(v['kompas']))}" if v.get("kompas") else "")]
    if not v.get("lengkap"):
        rows.append("⚠️ Data belum lengkap (sebagian sumber gagal dibaca), vonis ditahan di NETRAL.")
    rows.append(ARTI[v["vonis"]])
    fr = []
    for nm, nilai, s, w in v["faktor"]:
        fr.append(f"{'🟢' if s > 0 else '🔴' if s < 0 else '⚪'} {nm}: {html.escape(nilai)}  ({s * w:+d})")
    rows.append("<b>Suara tiap bahan</b>\n" + "\n".join(fr))
    if v["catatan"]:
        rows.append("<b>Kerumunan (tidak ikut suara)</b>\n" + "\n".join("• " + html.escape(c) for c in v["catatan"]))
    if v["kuat"]:
        rows.append("💪 Terkuat 24 jam: " + ", ".join(f"{s} {c:+.1f}%" for s, c in v["kuat"])
                    + "\n🥀 Terlemah 24 jam: " + ", ".join(f"{s} {c:+.1f}%" for s, c in v["lemah"]))
    try:
        ps = _posisi(v["vonis"], tag)
        if ps:
            rows.append("\n".join(ps) + "\nTidak perlu ditutup hanya karena vonis. Ikuti SL dan TP, kecuali ada pesan Gawat, Hidung Abdul, atau Himbauan.")
    except Exception as ex:
        print("[WARN] vonis posisi", ex)
    rows.append("Vonis = ringkasan keadaan pasar, bukan sinyal entry. Yang teruji di data: sisi BTC 4J (bobot terbesar). Bahan lain konteks.")
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
        d["calon"], d["n"] = baru, 1
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
