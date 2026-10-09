"""QSE v148 - TRADE KAMU: catatan entry pribadi dari perintah /entry, pemantauan per menit,
peringatan kasus besar, konsultasi entry, dan statistik WR harian, mingguan, bulanan."""
import fcntl
import json
import math
import os
import time
import requests
from config import STATE_DIR, BYBIT_URL, P
import qse_skill as SK

SAYA = os.path.join(STATE_DIR, "saya.json")
HASIL = os.path.join(STATE_DIR, "screening_terbaru.json")
WIB_MS = 7 * 3600 * 1000
JAM = 3600 * 1000
FEE = 0.055


# ---------------- penyimpanan ----------------
def _load():
    try:
        with open(SAYA) as f:
            d = json.load(f)
        d.setdefault("open", {})
        d.setdefault("closed", [])
        d.setdefault("seq", 0)
        return d
    except Exception:
        return {"open": {}, "closed": [], "seq": 0}


def ubah(fn):
    """Baca, ubah, simpan catatan trade kamu dengan kunci file. fn(data) -> hasil."""
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(SAYA + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = _load()
        hasil = fn(d)
        d["closed"] = d["closed"][-3000:]
        with open(SAYA + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(SAYA + ".tmp", SAYA)
        return hasil


def lihat():
    return _load()


def _jam_wib(ms):
    return time.strftime("%d/%m %H:%M WIB", time.gmtime(ms / 1000 + 7 * 3600))


# ---------------- data pasar ringan ----------------
def harga_live(sym):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear", "symbol": sym}, timeout=15)
        lst = r.json().get("result", {}).get("list", [])
        return float(lst[0]["lastPrice"]) if lst else 0.0
    except Exception:
        return 0.0


def harga_semua():
    try:
        r = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear"}, timeout=15)
        return {x["symbol"]: float(x["lastPrice"]) for x in r.json().get("result", {}).get("list", [])
                if x.get("lastPrice")}
    except Exception:
        return {}


def _kline(sym, iv, limit=1000):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/kline",
                         params={"category": "linear", "symbol": sym, "interval": iv, "limit": limit}, timeout=15)
        rows = r.json().get("result", {}).get("list", [])
    except Exception:
        return []
    out = [(int(x[0]), float(x[2]), float(x[3]), float(x[4])) for x in rows]
    return sorted(out)


def atr_4j(sym):
    k = _kline(sym, "240", 60)
    if len(k) < 20:
        return 0.0
    tr = [k[0][1] - k[0][2]] + [max(h - l, abs(h - k[i - 1][3]), abs(l - k[i - 1][3]))
                                for i, (_, h, l, _) in enumerate(k) if i > 0]
    a = sum(tr[:14]) / 14
    for x in tr[14:]:
        a = (a * 13 + x) / 14
    return a


def hasil_robot(sym):
    """Hasil scan 4 jam terakhir untuk koin ini (dari screening_terbaru.json)."""
    try:
        with open(HASIL) as f:
            for r in json.load(f):
                if r["symbol"] == sym and r.get("tf", "240") == "240":
                    return r
    except Exception:
        pass
    return None


def tick_of(r, harga):
    if r and r.get("tick"):
        return r["tick"]
    s = f"{harga:.10f}".rstrip("0")
    d = len(s.split(".")[1]) if "." in s else 0
    return 10 ** -max(2, min(8, d))


def fp(x, t):
    import math
    d = max(0, int(round(-math.log10(t)))) if t > 0 else 4
    return f"{round(x / t) * t:.{d}f}" if t > 0 else f"{x:.6g}"


# ---------------- posisi terbuka ----------------
def jalur_saran(sym, arah, harga, r=None, dengan_pola=False):
    """Dari mana entry ini: saran utama, cadangan, siklus, atau manual (plus nama polanya)."""
    r = r or hasil_robot(sym)
    a = (r or {}).get("atr") or 0
    hasil = ("manual", "manual")
    if r and a:
        for s in r["saran"]:
            if s["arah"] == arah and s["eksekusi"] and abs(s["entry"] - harga) <= 0.5 * a:
                hasil = ("saran utama", s["pola"])
                break
    if hasil[0] == "manual":
        try:
            import qse_fixprofit as FX
            for it in FX.load()["open"].values():
                if it["sym"] == sym and it["arah"] == arah and (not a or abs(it["entry"] - harga) <= a):
                    j = ("saran cadangan" if it.get("cadangan") else "saran siklus" if it.get("siklus")
                         else "saran cadangan 2" if it.get("cad2") else "saran fib" if it.get("fib")
                         else "saran 1J" if it.get("tf") == "60" else "saran utama")
                    hasil = (j, it["pola"])
                    break
        except Exception:
            pass
    return hasil if dengan_pola else hasil[0]


def posisi_koin(sym):
    """Posisi atau order kamu (/entry) di koin ini."""
    return [dict(asal="trade kamu", arah=it["arah"], status=it["status"], entry=it["entry"], sl=it["sl"],
                 tp1=it["tp1"], tp2=it["tp2"]) for it in _load()["open"].values() if it["sym"] == sym]


NM_ST = {"MENUNGGU": "order belum terisi", "TERISI": "posisi jalan", "TP1": "sudah TP1, SL di entry"}


# ---------------- konsultasi ----------------
def nilai(sym, arah, entry=None):
    """Penilaian robot untuk rencana entry. Return (label, alasan[], hasil_robot, harga_live)."""
    r = hasil_robot(sym)
    px = harga_live(sym)
    if r is None:
        return "TANPA DATA", ["koin ini belum ada di scan 4 jam terakhir"], None, px
    L = arah == "LONG"
    merah, kuning, hijau = [], [], []
    for p in posisi_koin(sym):
        if p["arah"] != arah:
            merah.append(f"kamu masih punya {p['arah']} terbuka ({p['asal']}, {NM_ST.get(p['status'], p['status'])}). "
                         f"Membuka {arah} sekarang berarti dua arah")
        else:
            kuning.append(f"sudah ada {p['arah']} terbuka di koin ini ({p['asal']}), jangan tambah lot tanpa rencana")
    izin = r.get("izin", "LONG dan SHORT")
    if izin != "LONG dan SHORT" and not izin.startswith(arah):
        merah.append(f"BTC 4J melawan, yang diizinkan {izin}")
    try:
        import qse_modal as MD
        st = MD.status()
        if st["rem"]:
            merah.append(st["alasan"])
    except Exception:
        pass
    if r["rapor"] == "D buruk":
        merah.append(f"rapor robot D ({r['trd']} trade, WR {r['wr']:.0f}%)")
    elif r["rapor"] in ("A", "B"):
        hijau.append(f"rapor robot {r['rapor']} ({r['trd']} trade, WR {r['wr']:.0f}%)")
    else:
        kuning.append(f"rapor robot {r['rapor']}")
    ps = r.get("pasar", {})
    if ps.get("arah") and ps["arah"] != arah:
        kuning.append(f"bias robot {ps['arah']}, berlawanan")
    elif ps.get("arah"):
        hijau.append(f"searah bias robot {arah}")
    lawan = [s for s in r["saran"] if s["eksekusi"] and s["arah"] != arah and not s["sudah_masuk"]]
    if lawan:
        merah.append(f"robot EKSEKUSI arah sebaliknya ({lawan[0]['pola']})")
    sama = [s for s in r["saran"] if s["arah"] == arah]
    if any(s["eksekusi"] for s in sama):
        hijau.append("ada saran robot EKSEKUSI searah")
    if ps.get("zona_searah"):
        hijau.append("harga di zona emas searah")
    if entry and px and r.get("atr"):
        jauh = ((px - entry) if L else (entry - px)) / r["atr"]
        if jauh > 2.5:
            kuning.append(f"entry {jauh:.1f} ATR dari harga, sulit terisi hari ini")
        elif jauh < -0.3:
            kuning.append("harga sudah melewati entry")
    label = "BERISIKO" if merah else "HATI-HATI" if kuning else "SEJALAN" if hijau else "NETRAL"
    return label, merah + kuning + hijau, r, px


RAPOR_ARTI = {"A": "robot sering untung di koin ini", "B": "hasil robot cukup bagus di koin ini",
              "C": "hasil robot biasa saja di koin ini", "D buruk": "robot sering rugi di koin ini",
              "SAMPEL KURANG": "data robot di koin ini belum cukup"}


def konsultasi(sym, arah=None, entry=None):
    import qse_fundamental as FD
    r = hasil_robot(sym)
    px = harga_live(sym)
    t = tick_of(r, px or 1)
    if r is None:
        return f"<b>CEK {sym}</b>\nKoin ini belum ada di scan 4 jam terakhir. Cek nama koinnya, contoh /cek DOT"
    ps = r.get("pasar", {})
    pos = posisi_koin(sym)
    arah = arah or (pos[0]["arah"] if pos else ps.get("arah", "LONG"))
    label, alasan, _, _ = nilai(sym, arah, entry)
    fund, catat_f = FD.teks_fundamental(sym)
    deriv, catat_d = FD.teks_derivatif(sym)

    # ---- kesimpulan yang mudah dipahami ----
    eks = [x for x in r["saran"] if x["eksekusi"] and not x["sudah_masuk"]]
    kal = [f"Robot melihat {sym} condong {ps.get('arah', '-')} di 4 jam. Rapor {r['rapor']}, "
           f"{RAPOR_ARTI.get(r['rapor'], 'data robot terbatas')} ({r['trd']} trade, WR {r['wr']:.0f}%)."
           + (" Tenang, teknik lain tetap aku uji di sejarah koin ini, hasilnya ada di bagian Backtest." if r["trd"] < 12 else "")]
    if eks:
        x = eks[0]
        kal.append(f"Ada saran {x['pola']} {x['arah']} yang sedang EKSEKUSI di {fp(x['entry'], t)}.")
    elif r["saran"]:
        x = r["saran"][0]
        kal.append(f"Saran terbaiknya {x['pola']} {x['arah']} masih TAHAN karena {x['alasan']}.")
    else:
        kal.append("Belum ada saran entry dari robot.")
    kal.append(f"BTC 4 jam {r['btc'].replace('BTC 4J ', '').lower()}, yang aman sekarang {r.get('izin', '-')}.")
    if ps.get("zona_searah"):
        kal.append("Harga sedang di zona emas searah bias, area entry yang bagus kalau ada candle konfirmasi.")
    kecil = [x for x in (catat_f, catat_d) if x]
    if kecil:
        kal.append("Catatan pasar: " + ", ".join(kecil) + ".")
    try:
        import qse_berita as BR
        hari = BR.hari_ini()
        jd = BR.jeda()
        if jd:
            kal.append(f"Sedang jeda berita {jd['judul']}, sebaiknya tunggu sampai satu jam setelah rilis.")
        elif hari:
            kal.append(f"Hari ini ada berita besar {hari[0]['judul']} jam {BR.jam_wib(hari[0]['ts'])[6:]}, "
                       f"hindari entry baru 2 jam sebelumnya.")
    except Exception:
        BR = None
    aksi = {"SEJALAN": "Boleh entry, ikuti SL dan TP robot atau pasang LIMIT di zona emas.",
            "HATI-HATI": "Kalau tetap masuk, pakai setengah lot dan SL wajib terpasang.",
            "BERISIKO": "Sebaiknya tunggu. Kondisi utama sedang melawan arah ini.",
            "NETRAL": "Robot belum punya pendapat kuat. Tunggu saran atau zona emas."}[label]
    p24 = ""
    try:
        d24 = FD.derivatif(sym).get("p24")
        p24 = f" | 24 jam {d24:+.1f}%" if d24 is not None else ""
    except Exception:
        pass
    blok = [f"Harga {fp(px, t) if px else '-'}{p24}",
            "<b>Kesimpulan</b>\n" + " ".join(kal) + f"\n\nPenilaian {arah}: <b>{label}</b>. {aksi}"]

    # ---- saran robot ----
    rows = ["<b>Saran robot</b>"]
    for x in r["saran"][:3]:
        v = "EKSEKUSI" if x["eksekusi"] else "TAHAN, " + x["alasan"]
        rows.append(f"{x['slot']}. {x['arah']} {x['pola']} | mutu {x['mutu']} | {v}\n"
                    f"Entry {fp(x['entry'], t)} | SL {fp(x['sl'], t)} | TP1 {fp(x['tp1'], t)} | TP2 {fp(x['tp2'], t)}")
    if not r["saran"]:
        rows.append("Belum ada saran.")
    blok.append("\n".join(rows))

    # ---- posisi kamu ----
    if pos:
        rows = ["<b>Posisi kamu di koin ini</b>"]
        for p in pos:
            risk = max(abs(p["entry"] - p["sl"]), 1e-12)
            gerak = ((px - p["entry"]) if p["arah"] == "LONG" else (p["entry"] - px)) / risk if px else 0.0
            rows.append(f"{p['arah']} {p['asal']} | {NM_ST.get(p['status'], p['status'])} | entry {fp(p['entry'], t)}"
                        + (f" | sekarang {gerak:+.2f}R" if p["status"] != "MENUNGGU" and px else ""))
        for it in [v for v in _load()["open"].values() if v["sym"] == sym and v["status"] in ("TERISI", "TP1")]:
            vonis, alasan_v, aksi, _ = analisa_posisi(it, r, px)
            rows.append(f"Analisa: {vonis}\nKenapa: {'; '.join(alasan_v[:6])}\nSaran: {aksi}")
        blok.append("\n".join(rows))

    # ---- teknikal ----
    rows = ["<b>Teknikal</b>",
            f"Rapor robot {r['rapor']} | {r['trd']} trade | WR {r['wr']:.0f}% | PF {r['pf']:.2f} | bias {ps.get('arah', '-')}",
            f"{r['btc']} | yang diizinkan: {r.get('izin', '-')}"]
    zi = info_zona(r, px)
    if zi and zi.get("teks"):
        rows.append("Zona emas: " + zi["teks"])
    ft = fib_teks(r)
    if ft:
        rows.append(ft)
    try:
        import qse_pola as PL
        rows += PL.teks(r.get("pola_chart"))
    except Exception:
        pass
    hk = hari_ini_koin(r, arah)
    if hk:
        rows.append(hk)
    blok.append("\n".join(rows))
    pt = pola_top_teks(r)
    if pt:
        blok.append("\n".join(["<b>Pola terbaik koin ini sepanjang sejarah (sama dengan tabel POLA TERBAIK)</b>"] + pt))

    # ---- siklus ----
    sk = r.get("siklus") or {}
    if sk and not sk.get("error"):
        rows = ["<b>Siklus pasar</b>"]
        if sk.get("c4P") is not None:
            rows.append(f"Peluang naik: 4 jam {sk['c4P']:.0f}% | harian {(sk.get('cDP') or 50):.0f}% | BTC {r.get('bProb', 50):.0f}%")
        fl = sk.get("aliran") or {}
        if fl:
            dana = "dana masuk" if fl["skor"] >= 2 else "dana keluar" if fl["skor"] <= -2 else "netral"
            rows.append(f"Aliran dana {dana} (skor {fl['skor']:+d}) | CMF {fl['cmf']:.2f} | MFI {fl['mfi']:.0f} | "
                        f"CVD {'naik' if fl['cvd_up'] else 'turun'}")
        pk = sk.get("pola")
        if pk and pk["n"]:
            rows.append(f"Pola kembar: {pk['n']} pola mirip di masa lalu, sesudahnya naik {pk['up'] * 100:.0f}% "
                        f"(teruji {pk['hitN']}/{pk['hitT']} tepat)")
        mu = sk.get("musim") or {}
        if mu.get("hari"):
            b_, w_ = mu["hari"]["terbaik"], mu["hari"]["terburuk"]
            rows.append(f"Hari terbaik {b_[0]} ({b_[1]:+.2f}%), terburuk {w_[0]} ({w_[1]:+.2f}%)")
        if mu.get("jam"):
            b_, w_ = mu["jam"]["terbaik"], mu["jam"]["terburuk"]
            rows.append(f"Jam terbaik {b_[0]} WIB ({b_[1]:+.2f}%), terburuk {w_[0]} WIB ({w_[1]:+.2f}%)")
        pv = sk.get("pivot")
        if pv:
            import qse_siklus as SIK
            tx = f"Siklus besar: terakhir {pv['jenis'].lower()} {SIK.tgl(pv['t'])} di {fp(pv['p'], t)}"
            if pv.get("berikut"):
                tx += (f". Perkiraan {pv['berikut'].lower()} berikutnya sekitar {SIK.tgl(pv['t1'])} "
                       f"(±{pv['sd'] / 86400000:.0f} hari) di {fp(pv['lo'], t)}-{fp(pv['hi'], t)}")
            rows.append(tx)
        if sk.get("saran"):
            x = sk["saran"]
            rows.append(f"Saran siklus: {x['arah']} {x['order']} di {fp(x['entry'], t)} | SL {fp(x['sl'], t)} | "
                        f"TP1 {fp(x['tp1'], t)} | TP2 {fp(x['tp2'], t)}")
        blok.append("\n".join(rows))

    # ---- skill ----
    if r.get("skill"):
        blok.append("\n".join(["<b>Skill tambahan</b>"] + SK.detail(r["skill"], arah, lambda x: fp(x, t))))

    # ---- fundamental, derivatif, kalender ----
    blok.append(backtest_teks(r))
    blok.append("\n".join(["<b>Fundamental</b>"] + fund))
    blok.append("\n".join(["<b>Pasar derivatif Bybit</b>"] + deriv))
    rows = ["<b>Kalender, makro, dan berita</b>"]
    try:
        import qse_makro as MK
        mb = MK.baris()
        if mb:
            rows.append(__import__("html").escape(mb))
        rows += ["Berita: " + __import__("html").escape(b) for b in MK.berita(3)]
    except Exception:
        pass
    try:
        import qse_berita as BR
        hari = BR.hari_ini()
        rows += [f"{e['judul']} jam {BR.jam_wib(e['ts'])[6:]}" for e in hari[:5]] or ["Tidak ada berita besar USD hari ini."]
        if sym in BR.delisting():
            rows.append("Bybit mengumumkan delisting koin ini. Jangan buka posisi baru.")
    except Exception:
        rows.append("Kalender tidak bisa diambil.")
    blok.append("\n".join(rows))

    # ---- alasan penilaian ----
    blok.append("\n".join([f"<b>Alasan penilaian {arah}</b>"] + ["➡️ " + x for x in alasan]))
    return f"<b>CEK {sym} {arah}</b>\n" + "\n\n".join(blok)


def saran_aktif(tf="240"):
    """Daftar saran robot yang masih aktif di TF tertentu, dengan harga sekarang dan jaraknya ke entry."""
    import qse_fixprofit as FX
    led = FX.load()
    now = int(time.time() * 1000)
    umur = 4 * JAM if tf == "240" else JAM
    items = [v for v in led["open"].values() if v.get("tf", "240") == tf and
             (v["status"] == "MENUNGGU" or now - v.get("created_ts", v.get("start_ts", 0)) <= umur)]
    nama = "4 JAM" if tf == "240" else "1 JAM"
    if not items:
        return f"Tidak ada saran TF {nama} yang aktif sekarang. Ketik /scan untuk scan dengan harga terkini."
    harga = harga_semua()
    rows = [f"<b>Saran TF {nama} aktif ({len(items)})</b>"]
    for i, v in enumerate(items, 1):
        rr = hasil_robot(v["sym"])
        t = v.get("tick") or (rr or {}).get("tick") or 10 ** -max(2, 5 - len(str(int(v["entry"]))))
        px = harga.get(v["sym"], 0)
        jalur = "CADANGAN" if v.get("cadangan") else "SIKLUS" if v.get("siklus") else "UTAMA"
        ik = "🟡" if v.get("cadangan") else "🔵" if v.get("siklus") else ("🟢" if v["arah"] == "LONG" else "🔴")
        jarak = abs(px - v["entry"]) / v["entry"] * 100 if px else 0
        st = "menunggu terisi" if v["status"] == "MENUNGGU" else "MARKET baru dikirim"
        rows.append(f"{ik} <b>{i}. {v['sym']} {v['arah']} {v.get('order', '')}</b> | {jalur} | {v['pola']}\n"
                    f"Entry {fp(v['entry'], t)} | SL {fp(v['sl'], t)} | TP1 {fp(v['tp1'], t)} | TP2 {fp(v['tp2'], t)}\n"
                    f"Harga sekarang {fp(px, t) if px else '-'} | jarak ke entry {jarak:.2f}% | {st}")
    return "\n\n".join(rows)


def _angka(x):
    try:
        return float(x.replace(",", "."))
    except ValueError:
        return None


def _waktu(tok_tgl, tok_jam, now_ms):
    """Ubah '02:00' atau '29/09' + '23:10' (WIB) jadi milidetik UTC. Jam di masa depan dianggap kemarin."""
    import datetime as dt
    wib = dt.timezone(dt.timedelta(hours=7))
    now = dt.datetime.fromtimestamp(now_ms / 1000, wib)
    try:
        hh, mm = (int(x) for x in tok_jam.split(":")) if tok_jam else (now.hour, now.minute)
        if tok_tgl:
            d, m = (int(x) for x in tok_tgl.split("/")[:2])
            t = dt.datetime(now.year, m, d, hh, mm, tzinfo=wib)
            if t > now:
                t = t.replace(year=now.year - 1)
        else:
            t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if t > now:
                t -= dt.timedelta(days=1)
        return int(t.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def parse_entry(args):
    """/entry long limit AUSDT 1.022 [sl 0.99] [tp1 1.05] [tp2 1.08] [terisi [29/09] [02:00]]"""
    arah = order = sym = None
    nums, kv, i = [], {}, 0
    terisi, tgl, jam = False, None, None
    while i < len(args):
        a = args[i]
        if a in ("LONG", "BUY", "L"):
            arah = "LONG"
        elif a in ("SHORT", "SELL", "S"):
            arah = "SHORT"
        elif a in ("LIMIT", "MARKET", "MKT"):
            order = "MARKET" if a != "LIMIT" else "LIMIT"
        elif a in ("TERISI", "FILLED", "SUDAH", "ISI"):
            terisi = True
        elif a in ("JAM", "PADA", "DI"):
            pass
        elif ":" in a:
            jam = a
        elif "/" in a:
            tgl = a
        elif a in ("LEV", "LEVERAGE") and i + 1 < len(args) and _angka(args[i + 1].rstrip("X")) is not None:
            kv["LEV"] = _angka(args[i + 1].rstrip("X"))
            i += 1
        elif a.endswith("X") and len(a) > 1 and _angka(a[:-1]) is not None:
            kv["LEV"] = _angka(a[:-1])
        elif a in ("SL", "TP", "TP1", "TP2") and i + 1 < len(args) and _angka(args[i + 1]) is not None:
            kv["TP1" if a == "TP" else a] = _angka(args[i + 1])
            i += 1
        elif _angka(a) is not None:
            nums.append(_angka(a))
        else:
            sym = a if a.endswith("USDT") else a + "USDT"
        i += 1
    kv.update(terisi=terisi or bool(jam or tgl), tgl=tgl, jam=jam)
    return arah, order or ("LIMIT" if nums else "MARKET"), sym, (nums[0] if nums else None), kv


def entry(args):
    arah, order, sym, harga, kv = parse_entry(args)
    if not arah or not sym:
        return ("Format: /entry long limit AUSDT 1.022\n"
                "Tambahan opsional: sl 0.99 tp1 1.05 tp2 1.08. Tanpa harga dianggap MARKET di harga sekarang.")
    px = harga_live(sym)
    if px <= 0:
        return f"{sym} tidak ditemukan di perpetual Bybit."
    if harga is None:
        harga = px
        order = "MARKET"
    L = arah == "LONG"
    now = int(time.time() * 1000)
    isi_ts = None
    if kv.get("terisi"):
        isi_ts = _waktu(kv.get("tgl"), kv.get("jam"), now) if (kv.get("jam") or kv.get("tgl")) else now
        if isi_ts is None:
            return "Format waktu salah. Contoh: terisi 02:00 atau terisi 29/09 23:10 (jam WIB)"
    elif order == "MARKET":
        isi_ts = now
    elif (L and px <= harga) or ((not L) and px >= harga):
        isi_ts = now          # LIMIT yang harganya sudah dilewati pasti langsung terisi
    catatan_isi = ""
    if isi_ts is not None and order == "LIMIT" and not kv.get("terisi"):
        catatan_isi = "Harga sekarang sudah melewati entry, jadi LIMIT ini dicatat langsung terisi."
    r = hasil_robot(sym)
    t = tick_of(r, px)
    sumber = "kamu"
    sl, tp1, tp2 = kv.get("SL"), kv.get("TP1"), kv.get("TP2")
    a_ref = (r or {}).get("atr") or 0.0
    cocok = [s for s in (r["saran"] if r else []) if s["arah"] == arah
             and a_ref > 0 and abs(s["entry"] - harga) <= 0.5 * a_ref
             and ((s["sl"] < harga) if L else (s["sl"] > harga))]
    if sl is None:
        if cocok:
            s = next((x for x in cocok if x["eksekusi"]), cocok[0])
            sl, tp1, tp2 = s["sl"], tp1 or s["tp1"], tp2 or s["tp2"]
            sumber = f"robot ({s['pola']}, entry robot {fp(s['entry'], t)})"
        else:
            a = (r or {}).get("atr") or atr_4j(sym)
            if a <= 0:
                return "Data ATR belum ada. Tulis SL sendiri, contoh /entry long limit AUSDT 1.022 sl 0.99"
            ps = (r or {}).get("pasar", {})
            jarak = abs(harga - ps["batal"]) + a * P["slBuf"] if ps.get("batal") and ps.get("arah") == arah else a * 1.5
            jarak = min(max(jarak, a * P["slMinA"]), a * P["slMaxA"])
            sl = harga - jarak if L else harga + jarak
            sumber = "otomatis (swing dan ATR, gaya robot)"
    risk = abs(harga - sl)
    if risk <= 0 or (L and sl >= harga) or ((not L) and sl <= harga):
        return "SL harus di bawah entry untuk LONG dan di atas entry untuk SHORT."
    if risk < harga * 0.001:
        return "SL terlalu dekat dengan entry (kurang dari 0.1%). Hasil R jadi tidak masuk akal, pakai SL yang lebih jauh."
    tp1 = tp1 or (harga + risk * 0.8 if L else harga - risk * 0.8)
    tp2 = tp2 or (harga + risk * 1.8 if L else harga - risk * 1.8)
    a_now = (r or {}).get("atr") or atr_4j(sym) or risk
    label, alasan, _, _ = nilai(sym, arah, harga)
    jalur, pola_asal = jalur_saran(sym, arah, harga, r, dengan_pola=True)

    def simpan(d):
        d["seq"] += 1
        tid = f"{sym}#{d['seq']}"
        d["open"][tid] = dict(id=tid, no=d["seq"], sym=sym, arah=arah, order=order, entry=harga, sl=sl, tp1=tp1,
                              tp2=tp2, atr=a_now, tick=t, sumber=sumber, nilai=label,
                              created_ts=isi_ts or now, last_ts=isi_ts or now,
                              status="TERISI" if isi_ts is not None else "MENUNGGU",
                              fill_ts=isi_ts or 0, alert=[], lev=kv.get("LEV"), risk0=abs(harga - sl),
                              sisa=1.0, real=0.0, jalur=jalur, pola=pola_asal)
        return d["seq"]
    ubah(simpan)
    fee_r = 2 * FEE / 100 * harga / risk
    n_open = len(_load()["open"])
    rows = [f"<b>TRADE KAMU TERCATAT</b> (trade terbuka ke-{n_open})",
            f"{sym} {arah} {order}" + (f" (sudah terisi, sejak {_jam_wib(isi_ts)})" if isi_ts is not None
                                       else " (menunggu terisi)"),
            f"<pre>Entry {fp(harga, t)}\nSL    {fp(sl, t)}  -1.00R\nTP1   {fp(tp1, t)}  +{abs(tp1 - harga) / risk:.2f}R\n"
            f"TP2   {fp(tp2, t)}  +{abs(tp2 - harga) / risk:.2f}R</pre>",
            f"Asal entry: {jalur}" + (f" ({pola_asal})" if pola_asal != "manual" else "") +
            f" | lot disarankan {lot_jalur(jalur):g}x lot normal",
            f"SL dan TP dari {sumber}. Fee pulang pergi sekitar {fee_r:.2f}R.",
            f"<b>Penilaian robot: {label}</b>"]
    try:
        import qse_modal as MD
        bl = MD.baris_lot(harga, sl, lot_jalur(jalur), int(kv["LEV"]) if kv.get("LEV") else None)
        if bl:
            rows.insert(4, bl)
    except Exception:
        pass
    if kv.get("LEV"):
        rows.insert(4, f"Leverage {kv['LEV']:g}x dicatat, /status menampilkan ROE.")
    rows += ["➡️ " + x for x in alasan]
    if r and r.get("skill"):
        rows.append(SK.ringkas(r["skill"], arah, lambda x: fp(x, t)))
    if catatan_isi:
        rows.append(catatan_isi)
    if isi_ts is not None and now - isi_ts > 5 * 60000:
        rows.append("Candle sejak jam terisi ikut dicek. Kalau TP atau SL sudah kena di rentang itu, kabarnya menyusul dalam 1 menit.")
    rows.append("Robot memantau tiap menit dan mengabari saat terisi, TP1, TP2, SL, atau ada kasus besar. "
                "Keluar lebih awal: /tutup " + sym.replace("USDT", "") + " HARGA")
    return "\n".join(rows)


# ---------------- /tutup /batal ----------------
def _parse_tutup(args):
    """KOIN [long|short] [30%] [harga]. Angka tanpa % dibaca persen bila <= 100 dan jauh dari harga sekarang."""
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    pct, harga, arah = 100.0, None, None
    px = None
    for a in args[1:]:
        if a in ("LONG", "SHORT"):
            arah = a
        elif a.endswith("%") and _angka(a[:-1]) is not None:
            pct = _angka(a[:-1])
        elif _angka(a) is not None:
            x = _angka(a)
            if px is None:
                px = harga_live(sym) or 0
            if x <= 100 and (not px or abs(x - px) / px > 0.3):
                pct = x
            else:
                harga = x
    return sym, max(0.0, min(100.0, pct)), harga, arah


def tutup(args, label="TUTUP"):
    """/tp KOIN [30%] [harga], /sl KOIN [50%] [harga], /tutup KOIN [harga]. Tanpa harga = harga sekarang."""
    if not args:
        return "Format: /tp AUSDT 30% atau /sl AUSDT 100% atau /tp AUSDT 50% 1.050"
    sym, pct, harga, arah = _parse_tutup(args)
    live = harga_live(sym)
    px = harga or live
    if not px:
        return f"Harga {sym} tidak bisa diambil, tulis harganya, contoh /tp {args[0]} 50% 1.050"
    if harga and live and abs(harga - live) / live > 0.3:
        return (f"Harga {harga:g} terlalu jauh dari harga sekarang {live:g}. Kalau maksudnya persen, "
                f"tulis dengan tanda %, contoh /sl {args[0]} 100%")
    now = int(time.time() * 1000)

    def f(d):
        rows = []
        for k in [k for k, v in d["open"].items() if v["sym"] == sym and (arah is None or v["arah"] == arah)]:
            it = d["open"][k]
            t = it["tick"]
            if it["status"] in ("TERISI", "TP1") and abs(_r_at(it, px)) > 15:
                rows.append(f"{sym} {it['arah']}: hasil {_r_at(it, px):+.1f}R tidak masuk akal, perintah dibatalkan. "
                            f"Cek lagi harganya.")
                continue
            if it["status"] == "MENUNGGU":
                if pct >= 100:
                    it = d["open"].pop(k)
                    it.update(status="BATAL", why="batal manual", result_r=0.0, closed_ts=now)
                    d["closed"].append(it)
                    rows.append(f"{sym} {it['arah']} belum terisi, order dibatalkan (tidak dihitung)")
                else:
                    rows.append(f"{sym} {it['arah']} belum terisi, tidak ada posisi yang bisa ditutup sebagian")
                continue
            r = _tutup_bagian(it, pct / 100, px)
            if it["sisa"] <= 0.001:
                it = d["open"].pop(k)
                it.update(status="SELESAI", why="TUTUP", result_r=round(_real(it), 3), exit=px, closed_ts=now)
                d["closed"].append(it)
                rows.append(f"{sym} {it['arah']} ditutup penuh di {fp(px, t)}\nHasil bagian ini {r:+.2f}R | total trade {it['result_r']:+.2f}R")
            else:
                rows.append(f"{sym} {it['arah']} {label} {pct:g}% di {fp(px, t)}\nHasil bagian ini {r:+.2f}R | "
                            f"sisa posisi {it['sisa'] * 100:.0f}% | sudah direalisasi {_real(it):+.2f}R")
        return rows
    rows = ubah(f)
    return "\n\n".join(rows) if rows else f"Tidak ada trade kamu yang terbuka di {sym}" + (f" {arah}." if arah else ".")


def serok(args):
    """/serok KOIN long|short [harga] [lot 0.5]: tambah posisi di harga lebih baik dari entry.
    Lot tambahan dibatasi supaya total rugi kalau kena SL maksimal 1,5R dari risiko awal."""
    if len(args) < 2:
        return "Format: /serok PENDLE short 2.60 atau /serok PENDLE short (harga sekarang)"
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    arah = next((a for a in args[1:] if a in ("LONG", "SHORT")), None)
    angka = [_angka(a) for a in args[1:] if a not in ("LONG", "SHORT", "LOT") and _angka(a) is not None]
    lot_minta = None
    if "LOT" in args:
        i = args.index("LOT")
        lot_minta = _angka(args[i + 1]) if i + 1 < len(args) else None
        angka = [x for x in angka if x != lot_minta]
    px = angka[0] if angka else harga_live(sym)
    if not px:
        return "Harga tidak bisa diambil, tulis harganya."

    def f(d):
        it = next((v for v in d["open"].values() if v["sym"] == sym and v["status"] in ("TERISI", "TP1")
                   and (arah is None or v["arah"] == arah)), None)
        if not it:
            return f"Tidak ada posisi jalan {sym}" + (f" {arah}" if arah else "") + "."
        L = it["arah"] == "LONG"
        t = it["tick"]
        if (L and px >= it["entry"]) or ((not L) and px <= it["entry"]):
            return f"Serok hanya di harga lebih baik dari entry {fp(it['entry'], t)}."
        sl = it["entry"] if it["status"] == "TP1" and not it.get("sl_manual") else it["sl"]
        if (L and px <= sl) or ((not L) and px >= sl):
            return "Harga serok sudah melewati SL. Tutup posisi dulu, jangan serok."
        it["risk0"], it["sisa"], it["real"] = _risk0(it), _sisa(it), _real(it)
        rugi_sl = it["real"] + it["sisa"] * _r_at(it, sl)
        r_add = ((sl - px) if L else (px - sl)) / it["risk0"]
        maks = (1.5 + rugi_sl) / -r_add if r_add < 0 else 0
        if maks <= 0.01:
            return f"Tidak bisa serok: rugi kalau kena SL sudah {rugi_sl:+.2f}R, batasnya -1.5R."
        x = min(lot_minta, maks) if lot_minta else maks
        e_baru = (it["sisa"] * it["entry"] + x * px) / (it["sisa"] + x)
        it.setdefault("serok", []).append(dict(harga=px, lot=x, ts=int(time.time() * 1000)))
        it["entry"], it["sisa"] = e_baru, it["sisa"] + x
        rugi_baru = it["real"] + it["sisa"] * _r_at(it, sl)
        return (f"{sym} {it['arah']} serok di {fp(px, t)}, tambah {x:.2f}x lot awal"
                + (f" (dibatasi dari {lot_minta:g}x)" if lot_minta and lot_minta > maks else "") +
                f"\nEntry rata-rata baru {fp(e_baru, t)} | ukuran sekarang {it['sisa']:.2f}x lot awal"
                f"\nKalau kena SL {fp(sl, t)}: {rugi_baru:+.2f}R. TP tetap, cek lagi dengan /status")
    return ubah(f)


def hapus(args):
    """/hapus KOIN [long|short]: buang catatan trade selesai terakhir di koin itu (untuk data yang salah)."""
    if not args:
        return "Format: /hapus PENDLE atau /hapus PENDLE short"
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    arah = next((a for a in args[1:] if a in ("LONG", "SHORT")), None)

    def f(d):
        for i in range(len(d["closed"]) - 1, -1, -1):
            c = d["closed"][i]
            if c["sym"] == sym and (arah is None or c["arah"] == arah):
                return d["closed"].pop(i)
        return None
    c = ubah(f)
    if not c:
        return f"Tidak ada catatan trade selesai di {sym}" + (f" {arah}." if arah else ".")
    return (f"Catatan dihapus: {sym} {c['arah']} | {c.get('why', '-')} {c.get('result_r', 0):+.2f}R. "
            f"WR dan evaluasi sudah dihitung ulang tanpa trade ini.")


def ubah_level(args):
    """/ubah KOIN sl 0.99 tp1 1.05 tp2 1.08, atau /ubah KOIN sl entry untuk geser SL ke titik impas."""
    if not args:
        return "Format: /ubah AUSDT sl 0.99 tp1 1.05 tp2 1.08 atau /ubah AUSDT sl entry"
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    arah_f = next((a for a in args[1:] if a in ("LONG", "SHORT")), None)
    args = [a for a in args if a not in ("LONG", "SHORT")]
    baru, i = {}, 1
    while i < len(args) - 1:
        k, v = args[i], args[i + 1]
        if k in ("SL", "TP", "TP1", "TP2"):
            key = {"TP": "tp1"}.get(k, k.lower())
            baru[key] = "ENTRY" if v in ("ENTRY", "BE") else _angka(v)
            i += 2
        else:
            i += 1
    if not baru or any(v is None for v in baru.values()):
        return "Format: /ubah AUSDT sl 0.99 tp1 1.05 tp2 1.08 atau /ubah AUSDT sl entry"

    def f(d):
        rows = []
        for it in [v for v in d["open"].values() if v["sym"] == sym and (arah_f is None or v["arah"] == arah_f)]:
            it["risk0"] = _risk0(it)
            it["sisa"], it["real"] = _sisa(it), _real(it)
            L = it["arah"] == "LONG"
            for k, v in baru.items():
                val = it["entry"] if v == "ENTRY" else v
                if k == "sl" and it["status"] == "MENUNGGU" and ((L and val >= it["entry"]) or ((not L) and val <= it["entry"])):
                    rows.append(f"{sym}: SL harus di bawah entry untuk LONG dan di atas entry untuk SHORT")
                    continue
                it[k] = val
                if k == "sl":
                    it["sl_manual"] = True
                    if it["status"] == "MENUNGGU":
                        it["risk0"] = abs(it["entry"] - val)
            t = it["tick"]
            rows.append(f"{sym} {it['arah']} diperbarui\nSL {fp(it['sl'], t)} | TP1 {fp(it['tp1'], t)} | TP2 {fp(it['tp2'], t)}")
        return rows
    rows = ubah(f)
    return "\n\n".join(rows) if rows else f"Tidak ada trade kamu yang terbuka di {sym}."


def batal(sym):
    def f(d):
        n = 0
        for k in [k for k, v in d["open"].items() if v["sym"] == sym and v["status"] == "MENUNGGU"]:
            it = d["open"].pop(k)
            it.update(status="BATAL", why="batal manual", result_r=0.0, closed_ts=int(time.time() * 1000))
            d["closed"].append(it)
            n += 1
        jalan = sum(1 for v in d["open"].values() if v["sym"] == sym)
        return n, jalan
    return ubah(f)


# ---------------- model posisi: sisa ukuran dan hasil yang sudah direalisasi ----------------
def _risk0(it):
    return it.get("risk0") or max(abs(it["entry"] - it["sl"]), 1e-12)


def _sisa(it):
    if "sisa" in it:
        return it["sisa"]
    return 0.5 if it["status"] == "TP1" else 1.0


def _real(it):
    if "real" in it:
        return it["real"]
    return 0.5 * abs(it["tp1"] - it["entry"]) / _risk0(it) if it["status"] == "TP1" else 0.0


def _r_at(it, px):
    return ((px - it["entry"]) if it["arah"] == "LONG" else (it["entry"] - px)) / _risk0(it)


def _tutup_bagian(it, frac, px):
    """Tutup frac (0-1) dari SISA posisi di harga px. Return R yang direalisasi dari bagian ini."""
    sisa = _sisa(it)
    bag = sisa * min(max(frac, 0.0), 1.0)
    r = bag * _r_at(it, px)
    it["real"] = _real(it) + r
    it["sisa"] = sisa - bag
    it["risk0"] = _risk0(it)
    return r


# ---------------- pemantauan ----------------
def _jalan(it, rows, iv):
    """Proses candle (ts, high, low, close) untuk satu trade. Return daftar (event, teks)."""
    ev = []
    L = it["arah"] == "LONG"
    e = it["entry"]
    for ts, hi, lo, cl in rows:
        if ts <= it["last_ts"] - iv:
            continue
        it["last_ts"] = ts + iv
        if it["status"] == "MENUNGGU":
            if not (lo <= e if L else hi >= e):
                continue
            it["status"], it["fill_ts"] = "TERISI", ts
            it.setdefault("risk0", max(abs(e - it["sl"]), 1e-12))
            ev.append(("TERISI", "ORDER TERISI"))
        if it["status"] in ("TERISI", "TP1"):
            sl, t1, t2 = it["sl"], it["tp1"], it["tp2"]
            if it["status"] == "TP1" and not it.get("sl_manual"):
                sl = e
            if (lo <= sl) if L else (hi >= sl):
                _tutup_bagian(it, 1.0, sl)
                res = _real(it)
                why = "SL" if res < 0 else "BE"
                it.update(status="SELESAI", why=why, result_r=round(res, 3), closed_ts=ts)
                ev.append((why, f"kena SL di {fp(sl, it['tick'])}, selesai {res:+.2f}R" if why == "SL" else
                           f"harga balik ke SL {fp(sl, it['tick'])} (sudah di titik aman), keluar dengan {res:+.2f}R"))
                return ev
            if it["status"] == "TERISI" and ((hi >= t1) if L else (lo <= t1)):
                r = _tutup_bagian(it, 0.5, t1)
                it["status"], it["tp1_ts"] = "TP1", ts
                ev.append(("TP1", f"KENA TP1, separuh ditutup {r:+.2f}R. Geser SL ke entry {fp(e, it['tick'])}"))
            if it["status"] == "TP1" and ((hi >= t2) if L else (lo <= t2)):
                _tutup_bagian(it, 1.0, t2)
                res = _real(it)
                it.update(status="SELESAI", why="TP2", result_r=round(res, 3), closed_ts=ts)
                ev.append(("TP2", f"KENA TP2, selesai {res:+.2f}R"))
                return ev
    return ev


def pantau():
    """Cek semua trade kamu dengan candle 1 menit. Aman dipanggil tiap menit. Return daftar pesan."""
    d0 = _load()
    if not d0["open"]:
        return []
    data = {}
    for sym in {v["sym"] for v in d0["open"].values()}:
        data[sym] = (_kline(sym, "1", 1000), _kline(sym, "60", 200))
    now = int(time.time() * 1000)

    def f(d):
        pesan = []
        for k in list(d["open"].keys()):
            it = d["open"][k]
            m1, h1 = data.get(it["sym"], ([], []))
            m1 = [x for x in m1 if x[0] + 60000 <= now]
            h1 = [x for x in h1 if x[0] + JAM <= now]
            awal = m1[0][0] if m1 else now
            ev = _jalan(it, [x for x in h1 if x[0] + JAM <= awal], JAM) if it["last_ts"] < awal else []
            ev += _jalan(it, m1, 60000)
            px = m1[-1][3] if m1 else 0
            if it["status"] == "MENUNGGU":
                if now - it["created_ts"] > 24 * JAM and "24j" not in it["alert"]:
                    it["alert"].append("24j")
                    ev.append(("INFO", f"LIMIT belum terisi 24 jam. Pertimbangkan batal: /batal {it['sym'].replace('USDT', '')}"))
                jauh = ((px - it["entry"]) if it["arah"] == "LONG" else (it["entry"] - px)) / max(it["atr"], 1e-12)
                if px and jauh > 2.5 and "jauh" not in it["alert"]:
                    it["alert"].append("jauh")
                    ev.append(("INFO", f"LIMIT kejauhan, harga sudah {jauh:.1f} ATR dari entry. Peluang terisi hari ini kecil."))
            if it["status"] == "TP1" and px:
                ev += _trailing(it, h1, px)
            ik = {"TERISI": "📥", "TP1": "💰", "TP2": "🏆", "SL": "🛑", "BE": "⚖️", "INFO": "⚠️", "TRAIL": "📈"}
            for e, txt in ev:
                pesan.append(f"{ik.get(e, '•')} <b>{it['sym']} {it['arah']}</b>\n↳ {txt} | entry {fp(it['entry'], it['tick'])}")
            if it["status"] == "SELESAI":
                d["closed"].append(d["open"].pop(k))
        return pesan
    return ubah(f)


def _trailing(it, h1, px):
    """Saran trailing stop setelah TP1: puncak sejak TP1 dikurangi 1,5 ATR 4J (chandelier).
    Hanya dikirim bila mengunci lebih baik minimal 0,25 ATR dari SL sekarang atau saran sebelumnya."""
    a = it.get("atr") or 0
    if a <= 0:
        return []
    L = it["arah"] == "LONG"
    mulai = it.get("tp1_ts") or it.get("fill_ts") or 0
    bars = [x for x in h1 if x[0] >= mulai - JAM]
    if len(bars) < 2:
        return []
    trail = (max(x[1] for x in bars) - 1.5 * a) if L else (min(x[2] for x in bars) + 1.5 * a)
    stop = it["sl"] if it.get("sl_manual") else it["entry"]
    acuan = max(stop, it.get("trail_saran", stop)) if L else min(stop, it.get("trail_saran", stop))
    lebih = (trail - acuan) if L else (acuan - trail)
    aman = (px - trail) if L else (trail - px)
    if lebih < 0.25 * a or aman < 0.3 * a:
        return []
    it["trail_saran"] = trail
    kunci = _real(it) + _sisa(it) * _r_at(it, trail)
    t = it["tick"]
    return [("TRAIL", f"TRAILING STOP: geser SL ke {fp(trail, t)}, total trade terkunci {kunci:+.2f}R. "
                      f"Ketik /ubah {it['sym'].replace('USDT', '')} sl {fp(trail, t)}")]


def cek_4j(res_map):
    """Dipanggil tiap scan 4 jam: kasus besar yang melawan trade kamu. Tiap kasus dikabari sekali."""
    def f(d):
        pesan = []
        for it in d["open"].values():
            r = res_map.get((it["sym"], "240"))
            if not r:
                continue
            arah = it["arah"]
            kasus = []
            izin = r.get("izin", "LONG dan SHORT")
            if izin != "LONG dan SHORT" and not izin.startswith(arah):
                kasus.append(("btc", f"BTC 4J berbalik melawan {arah}, yang diizinkan {izin}"))
            ps = r.get("pasar", {})
            if ps.get("arah") and ps["arah"] != arah:
                kasus.append(("bias", f"bias robot untuk koin ini berbalik ke {ps['arah']}"))
            lw = [s for s in r["saran"] if s["eksekusi"] and s["arah"] != arah and not s["sudah_masuk"]]
            if lw:
                kasus.append(("lawan", f"robot memberi EKSEKUSI arah sebaliknya ({lw[0]['pola']})"))
            if r["rapor"] == "D buruk":
                kasus.append(("rapor", "rapor robot koin ini turun ke D"))
            aktif = {k for k, _ in kasus}
            it["alert"] = [a for a in it["alert"] if a not in ("btc", "bias", "lawan", "rapor") or a in aktif]
            for k, txt in kasus:
                if k not in it["alert"]:
                    it["alert"].append(k)
                    saran = ("Kalau posisi sudah jalan, pertimbangkan kunci profit atau perketat SL."
                             if it["status"] != "MENUNGGU" else "Order belum terisi, pertimbangkan batal.")
                    pesan.append(f"⚠️ <b>{it['sym']} {arah}</b>\n↳ {txt}. {saran}")
        return pesan
    return ubah(f)


# ---------------- statistik ----------------
def _periode():
    now = int(time.time() * 1000)
    hari = (now + WIB_MS) // 86400000 * 86400000 - WIB_MS
    return [("hari ini", hari), ("7 hari", now - 7 * 86400000), ("30 hari", now - 30 * 86400000)]


def ringkas(closed, why_ok=("SL", "BE", "TP2", "TUTUP")):
    rows = []
    for nama, a in _periode():
        cl = [c for c in closed if c.get("why") in why_ok and c.get("closed_ts", 0) >= a]
        n = len(cl)
        w = sum(1 for c in cl if c["result_r"] > 0)
        net = sum(c["result_r"] for c in cl)
        rows.append(f"{nama}: {n} trade, WR {w / n * 100 if n else 0:.0f}%, {net:+.2f}R")
    return " | ".join(rows)


def ringkas_rapi(judul, closed, why_ok=("SL", "BE", "TP2", "TUTUP")):
    rows = [f"<b>{judul}</b>"]
    for nama, a in _periode():
        cl = [c for c in closed if c.get("why") in why_ok and c.get("closed_ts", 0) >= a]
        n = len(cl)
        w = sum(1 for c in cl if c["result_r"] > 0)
        net = sum(c["result_r"] for c in cl)
        rows.append(f"{nama.capitalize()}: {n} trade | WR {w / n * 100 if n else 0:.0f}% | {net:+.2f}R")
    return "\n".join(rows)


def floating(it, px):
    """Untung atau rugi berjalan. Return dict persen harga, R total (realisasi + berjalan), ROE, sisa, atau None."""
    if not px or it["status"] not in ("TERISI", "TP1"):
        return None
    e = it["entry"]
    pct = ((px - e) if it["arah"] == "LONG" else (e - px)) / e * 100
    sisa, real = _sisa(it), _real(it)
    r = real + sisa * _r_at(it, px)
    lev = it.get("lev")
    return dict(pct=pct, r=r, real=real, sisa=sisa, roe=pct * lev if lev else None, lev=lev)


NM_POS = {"MENUNGGU": "menunggu terisi", "TERISI": "posisi jalan", "TP1": "sudah TP1, SL di entry"}


def blok_posisi(no, it, px, judul_extra=""):
    t = it.get("tick") or tick_of(None, it["entry"])
    ik = "🟢" if it["arah"] == "LONG" else "🔴"
    rows = [f"{ik} <b>{no}. {it['sym']} {it['arah']} {it.get('order', '')}</b>{judul_extra}",
            f"Status: {NM_POS.get(it['status'], it['status'])}",
            f"Entry {fp(it['entry'], t)} | harga sekarang {fp(px, t) if px else '-'}"]
    fl = floating(it, px)
    if fl:
        tanda = "🟩 Floating UNTUNG" if fl["r"] >= 0 else "🟥 Floating RUGI"
        teks = f"{tanda}: {fl['pct']:+.2f}% | total {fl['r']:+.2f}R"
        if fl["roe"] is not None:
            teks += f" | ROE {fl['roe']:+.1f}% di {fl['lev']:g}x"
        rows.append(teks)
        if fl["sisa"] < 0.999:
            rows.append(f"Sisa posisi {fl['sisa'] * 100:.0f}% | sudah direalisasi {fl['real']:+.2f}R")
    elif it["status"] == "MENUNGGU" and px:
        jarak = abs(px - it["entry"]) / it["entry"] * 100
        rows.append(f"Jarak harga ke entry: {jarak:.2f}%")
    if it["status"] == "TP1" and not it.get("sl_manual"):
        rows.append(f"SL sudah di entry {fp(it['entry'], t)} | TP2 {fp(it['tp2'], t)}")
    else:
        rows.append(f"SL {fp(it['sl'], t)} | TP1 {fp(it['tp1'], t)} | TP2 {fp(it['tp2'], t)}")
    return "\n".join(rows)


def status_saya(harga=None):
    d = _load()
    harga = harga if harga is not None else harga_semua()
    op = list(d["open"].values())
    blok = [f"━━━━━━━━━━━━━━━━\n👤 <b>TRADE KAMU ({len(op)})</b>"]
    if not op:
        blok.append("Tidak ada trade terbuka.")
    tot = 0.0
    for i, it in enumerate(op, 1):
        bp = blok_posisi(i, it, harga.get(it["sym"], 0.0), f" | nilai saat entry {it['nilai']}")
        if it["status"] in ("TERISI", "TP1"):
            try:
                vonis, alasan_v, aksi, _ = analisa_posisi(it, None, harga.get(it["sym"]) or None)
                bp += f"\nAnalisa sekarang: {vonis}. {aksi}"
            except Exception:
                pass
        blok.append(bp)
        fl = floating(it, harga.get(it["sym"], 0.0))
        tot += fl["r"] if fl else 0.0
    if any(floating(it, harga.get(it["sym"], 0.0)) for it in op):
        blok.append(f"{'🟩' if tot >= 0 else '🟥'} Total floating trade kamu: {tot:+.2f}R")
    blok.append(ringkas_rapi("📈 WR TRADE KAMU", d["closed"]))
    blok.append(wr_jalur(d["closed"]))
    return "\n\n".join(blok)


def wr_jalur(closed, hari=30):
    """WR 30 hari trade kamu dipisah menurut asal entry."""
    a = int(time.time() * 1000) - hari * 86400000
    rows = [f"<b>Menurut asal entry ({hari} hari)</b>"]
    for j in ("saran utama", "saran 1J", "saran cadangan", "saran cadangan 2", "saran fib", "saran siklus", "manual"):
        x = [c for c in closed if c.get("why") in ("SL", "BE", "TP2", "TUTUP") and c.get("closed_ts", 0) >= a
             and c.get("jalur", "manual") == j]
        if x:
            w = sum(1 for c in x if c["result_r"] > 0)
            rows.append(f"{j.capitalize()}: {len(x)} trade | WR {w / len(x) * 100:.0f}% | {sum(c['result_r'] for c in x):+.2f}R")
    if len(rows) == 1:
        rows.append("Belum ada trade yang selesai.")
    return "\n".join(rows)


# ---------------- belajar dari trade kamu ----------------
LOT_DASAR = {"saran utama": 1.0, "saran 1J": 0.5, "saran cadangan": 0.5, "saran cadangan 2": 0.25, "saran fib": 0.5,
             "saran siklus": 0.5, "manual": 0.5}
SELESAI = ("SL", "BE", "TP2", "TUTUP")


def _selesai(hari=90):
    a = int(time.time() * 1000) - hari * 86400000
    return [c for c in _load()["closed"] if c.get("why") in SELESAI and c.get("closed_ts", 0) >= a]


def _stat(x):
    n = len(x)
    w = sum(1 for c in x if c["result_r"] > 0)
    net = sum(c["result_r"] for c in x)
    return dict(n=n, wr=w / n * 100 if n else 0, avg=net / n if n else 0, net=net)


def lot_jalur(jalur):
    """Pengali lot dari hasil trade kamu sendiri. Baru menyesuaikan setelah 10 trade di jalur itu."""
    dasar = LOT_DASAR.get(jalur, 0.5)
    st = _stat([c for c in _selesai() if c.get("jalur", "manual") == jalur])
    if st["n"] < 10:
        return dasar
    if st["avg"] >= 0.3 and st["wr"] >= 55:
        k = 1.5
    elif st["avg"] >= 0.1:
        k = 1.25
    elif st["avg"] < 0:
        k = 0.5
    else:
        k = 1.0
    return round(min(1.5, dasar * k) * 4) / 4 or 0.25


def evaluasi(hari=90):
    """Teks evaluasi trade kamu: per asal entry, pola, koin, hari, dan jam WIB."""
    cl = _selesai(hari)
    if not cl:
        return "Belum ada trade yang selesai dalam 90 hari. Catat entry dengan /entry supaya bisa dievaluasi."
    tot = _stat(cl)
    rows = [f"<b>📚 EVALUASI TRADE KAMU ({hari} hari)</b>",
            f"{tot['n']} trade | WR {tot['wr']:.0f}% | rata {tot['avg']:+.2f}R | total {tot['net']:+.2f}R"]

    def grup(judul, kunci, min_n=2, maks=4):
        g = {}
        for c in cl:
            g.setdefault(kunci(c), []).append(c)
        st = [(k, _stat(v)) for k, v in g.items() if len(v) >= min_n]
        if not st:
            return
        st.sort(key=lambda z: -z[1]["avg"])
        rows.append(f"\n<b>{judul}</b>")
        for k, s_ in st[:maks]:
            rows.append(f"{k}: {s_['n']} trade | WR {s_['wr']:.0f}% | rata {s_['avg']:+.2f}R")
        if len(st) > maks:
            k, s_ = st[-1]
            rows.append(f"Terlemah {k}: {s_['n']} trade | rata {s_['avg']:+.2f}R")

    def wib(c):
        return (c.get("fill_ts") or c.get("created_ts") or c.get("closed_ts", 0)) + 7 * 3600000
    hari_nm = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]
    grup("Asal entry", lambda c: c.get("jalur", "manual").capitalize(), 1)
    grup("Pola", lambda c: c.get("pola", "manual"))
    grup("Koin", lambda c: c["sym"])
    grup("Hari masuk", lambda c: hari_nm[int((wib(c) // 86400000 + 4) % 7)])
    grup("Jam masuk (WIB)", lambda c: f"{int(wib(c) % 86400000 // 3600000) // 4 * 4:02d}-{int(wib(c) % 86400000 // 3600000) // 4 * 4 + 4:02d}")
    rows.append("\n<b>Lot disarankan</b>")
    for j in ("saran utama", "saran 1J", "saran cadangan", "saran cadangan 2", "saran fib", "saran siklus", "manual"):
        n = sum(1 for c in cl if c.get("jalur", "manual") == j)
        rows.append(f"{j.capitalize()}: {lot_jalur(j):g}x lot normal" + ("" if n >= 10 else f" (bawaan, baru {n}/10 trade)"))
    return "\n".join(rows)


# ---------------- estimasi waktu, zona emas, analisa posisi ----------------
def estimasi_jam(jarak, atr, tf_jam=4):
    """Perkiraan kasar waktu harga menempuh jarak tertentu dari volatilitas sekarang (pola acak: waktu ~ jarak kuadrat)."""
    if atr <= 0:
        return None
    s1 = atr / math.sqrt(tf_jam)
    return (abs(jarak) / s1) ** 2


def teks_waktu(jam):
    if jam is None:
        return "-"
    if jam < 1:
        return f"±{max(5, int(round(jam * 60 / 5) * 5))} menit"
    if jam < 48:
        return f"±{jam:.0f} jam"
    if jam < 24 * 7:
        return f"±{jam / 24:.0f} hari"
    return "lebih dari seminggu"


def konfirmasi_candle(p, arah):
    """Candle konfirmasi searah: candle berjalan tutup di 60% atas (LONG) atau bawah (SHORT) dan searah,
    atau candle tutup terakhir punya ekor penolakan minimal 40% range dan searah."""
    L = arah == "LONG"
    o, h, l, c = p.get("k_now") or (0, 0, 0, 0)
    rg = h - l
    if rg > 0 and ((c > o and (c - l) / rg >= 0.6) if L else (c < o and (h - c) / rg >= 0.6)):
        return True, "candle berjalan " + ("hijau dan tutup di atas" if L else "merah dan tutup di bawah")
    o, h, l, c = p.get("k_prev") or (0, 0, 0, 0)
    rg = h - l
    if rg > 0 and ((c > o and (min(o, c) - l) / rg >= 0.4) if L else (c < o and (h - max(o, c)) / rg >= 0.4)):
        return True, "candle sebelumnya menolak " + ("turun (ekor bawah panjang)" if L else "naik (ekor atas panjang)")
    return False, "belum ada candle konfirmasi"


def info_zona(r, px=None):
    """Jarak harga ke golden zone, estimasi tersentuh, konfirmasi candle, dan saran MARKET manual bila sudah siap."""
    p = r.get("pasar") or {}
    if not p:
        return None
    arah = p["arah"]
    L = arah == "LONG"
    c = px or r.get("live") or r["close"]
    a = r["atr"]
    t = r["tick"]
    lo, hi = sorted(p["gz"])
    glo, ghi = sorted(p["gp"])
    if (L and c < p["batal"]) or ((not L) and c > p["batal"]):
        return dict(teks=f"Harga sudah tembus batas batal {fp(p['batal'], t)}, setup zona emas gugur", siap=False)
    if lo <= c <= hi:
        jarak, posisi = 0.0, ("di dalam golden pocket" if glo <= c <= ghi else "di dalam golden zone")
    else:
        jarak = ((c - hi) if c > hi else (lo - c)) if L else ((lo - c) if c < lo else (c - hi))
        posisi = None
    out = dict(lo=lo, hi=hi, jarak_pct=abs(jarak) / c * 100 if c else 0, siap=False)
    tf_jam = r["tf_ms"] / 3600000
    if posisi:
        teks = f"GZ {fp(lo, t)}-{fp(hi, t)} | harga {posisi} | batal {fp(p['batal'], t)}"
    else:
        arah_zona = (c > hi) if L else (c < lo)
        if not arah_zona:
            return dict(teks=f"GZ {fp(lo, t)}-{fp(hi, t)} | harga sudah lewat zona ke arah berlawanan", siap=False)
        teks = (f"GZ {fp(lo, t)}-{fp(hi, t)} | jarak {out['jarak_pct']:.2f}% | perkiraan tersentuh "
                f"{teks_waktu(estimasi_jam(jarak, a, tf_jam))} | batal {fp(p['batal'], t)}")
    ok, alasan_c = konfirmasi_candle(p, arah)
    out["konf_candle"] = alasan_c
    if posisi and ok and p.get("btc_ok"):
        base = p["batal"] - a * 0.45 if L else p["batal"] + a * 0.45
        dist = (c - base) if L else (base - c)
        dist = min(max(dist if dist > 0 else a * 1.5, a * 1.0), a * 2.5)
        sl = c - dist if L else c + dist
        tp1 = c + 0.8 * dist if L else c - 0.8 * dist
        lv = (r.get("skill") or {}).get("res" if L else "sup") or []
        tp2 = next((x for x in lv if 1.2 * dist <= (x - c if L else c - x) <= 3 * dist), c + 1.8 * dist if L else c - 1.8 * dist)
        out.update(siap=True, entry=c, sl=sl, tp1=tp1, tp2=tp2)
        teks += (f"\nCandle: {alasan_c}\nSaran MARKET manual: entry {fp(c, t)} | SL {fp(sl, t)} | TP1 {fp(tp1, t)} | "
                 f"TP2 {fp(tp2, t)} | lot {lot_jalur('manual'):g}x")
    else:
        teks += f"\nCandle: {alasan_c}" + ("" if p.get("btc_ok") else " | BTC belum mengizinkan arah ini")
        # rencana harga tetap diberikan supaya jelas: LIMIT di tengah golden pocket, SL di bawah batas batal
        e = (glo + ghi) / 2
        if posisi:
            e = c
        base = p["batal"] - a * 0.45 if L else p["batal"] + a * 0.45
        dist = (e - base) if L else (base - e)
        dist = min(max(dist if dist > 0 else a * 1.5, a * 1.0), a * 2.5)
        sl = e - dist if L else e + dist
        tp1 = e + 0.8 * dist if L else e - 0.8 * dist
        lv = (r.get("skill") or {}).get("res" if L else "sup") or []
        tp2 = next((x for x in lv if 1.2 * dist <= (x - e if L else e - x) <= 3 * dist), e + 1.8 * dist if L else e - 1.8 * dist)
        out.update(rencana=dict(order="MARKET" if posisi else "LIMIT", entry=e, sl=sl, tp1=tp1, tp2=tp2))
        teks += (f"\nRencana {'MARKET' if posisi else 'LIMIT'} {arah}: entry {fp(e, t)} | SL {fp(sl, t)} | "
                 f"TP1 {fp(tp1, t)} | TP2 {fp(tp2, t)}"
                 f"\n↳ pasang hanya setelah candle konfirmasi searah"
                 + ("" if p.get("btc_ok") else " dan BTC mengizinkan") + ". Kalau candle tutup tembus batal, lewati.")
    out["teks"] = teks
    return out


def analisa_posisi(it, r=None, px=None):
    """Apakah trade kamu masih sesuai analisa robot. Return (vonis, alasan, aksi, skor)."""
    r = r or hasil_robot(it["sym"])
    px = px or harga_live(it["sym"])
    if not r:
        return "TIDAK ADA DATA", ["koin belum ada di scan terakhir"], "Pantau manual.", 0
    arah = it["arah"]
    L = arah == "LONG"
    p = r.get("pasar") or {}
    a = r["atr"] or 1e-12
    t = r["tick"]
    skor, alasan = 0, []
    if p.get("arah") == arah:
        skor += 1
        alasan.append(f"bias robot masih {arah}")
    elif p.get("arah"):
        skor -= 2
        alasan.append(f"bias robot berbalik ke {p['arah']}")
    izin = r.get("izin", "")
    if izin == "LONG dan SHORT" or izin.startswith(arah):
        skor += 1
        alasan.append("BTC 4J mengizinkan arah ini")
    else:
        skor -= 1
        alasan.append(f"BTC 4J melawan, yang diizinkan {izin}")
    eks = [x for x in r["saran"] if x["eksekusi"]]
    if any(x["arah"] == arah for x in eks):
        skor += 1
        alasan.append("ada saran robot EKSEKUSI searah")
    if any(x["arah"] != arah for x in eks):
        skor -= 2
        alasan.append("ada saran robot EKSEKUSI berlawanan")
    if p.get("zona_searah") and p.get("arah") == arah:
        skor += 1
        alasan.append("harga di zona emas searah")
    if (L and px and px < p.get("batal", 0)) or ((not L) and px and px > p.get("batal", 1e18)):
        skor -= 2
        alasan.append(f"struktur patah, harga tembus batas {fp(p['batal'], t)}")
    if r.get("skill"):
        nk = SK.konfirmasi(r["skill"], arah)[0]
        if nk >= 5:
            skor += 1
            alasan.append(f"skill tambahan searah {nk}/8")
        elif nk <= 2:
            skor -= 1
            alasan.append(f"skill tambahan lemah {nk}/8")
    sk = r.get("siklus") or {}
    if sk.get("c4P") is not None:
        c4 = sk["c4P"]
        if (c4 >= 55) if L else (c4 <= 45):
            skor += 1
            alasan.append(f"peluang 4 jam searah ({c4:.0f}% naik)")
        elif (c4 <= 45) if L else (c4 >= 55):
            skor -= 1
            alasan.append(f"peluang 4 jam melawan ({c4:.0f}% naik)")
    fl = (sk.get("aliran") or {}).get("skor")
    if fl is not None:
        if (fl >= 2) if L else (fl <= -2):
            skor += 1
            alasan.append("aliran dana searah")
        elif (fl <= -2) if L else (fl >= 2):
            skor -= 1
            alasan.append("aliran dana melawan")
    if r["rapor"] == "D buruk":
        skor -= 2
        alasan.append("rapor robot turun ke D")
    if px:
        g = ((px - it["entry"]) if L else (it["entry"] - px)) / a
        if g < 0:
            alasan.insert(0, f"harga {abs(g):.1f} ATR melawan entry, " +
                          ("masih dalam gerak normal 4J" if abs(g) < 1 else "sudah di luar gerak normal 4J"))
    if skor >= 3:
        vonis, aksi = "MASIH SESUAI ANALISA", "Tahan. Biarkan SL dan TP bekerja."
    elif skor >= 0:
        vonis, aksi = "MELEMAH", "Tahan dengan SL tetap, jangan tambah lot. Kalau sudah untung, geser SL ke entry."
    else:
        vonis, aksi = "BERBALIK", (f"Pertimbangkan kurangi risiko: /sl {it['sym'].replace('USDT', '')} 50% "
                                   f"atau geser SL lebih dekat dengan /ubah.")
    return vonis, alasan, aksi, skor


# ---------------- tahap 2: perkiraan hari, hari ini, pola terbaik, kalibrasi ----------------
HARI_NM = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"]


def perkiraan_hari(jam):
    """Jam dari sekarang -> 'Selasa malam' (WIB)."""
    if jam is None:
        return "-"
    ts = time.time() + jam * 3600 + 7 * 3600
    d = int((ts // 86400 + 4) % 7)
    h = int(ts % 86400 // 3600)
    bagian = "dini hari" if h < 5 else "pagi" if h < 11 else "siang" if h < 15 else "sore" if h < 18 else "malam"
    return f"{HARI_NM[d]} {bagian}"


def hari_ini_koin(r, arah):
    """Apakah hari ini termasuk hari bagus atau buruk untuk arah ini di koin ini (statistik candle 4J per hari WIB)."""
    mu = ((r.get("siklus") or {}).get("musim") or {}).get("hari") or {}
    semua = mu.get("semua") or {}
    if len(semua) < 5:
        return ""
    hari = HARI_NM[int(((time.time() + 7 * 3600) // 86400 + 4) % 7)]
    if hari not in semua:
        return ""
    urut = sorted(semua.items(), key=lambda z: z[1][0], reverse=(arah == "LONG"))
    rank = [k for k, _ in urut].index(hari)
    avg, wr = semua[hari]
    kelas = "bagus" if rank <= 1 else "buruk" if rank >= len(urut) - 2 else "biasa"
    return (f"Hari ini {hari}: rata candle {avg:+.2f}%, naik {wr:.0f}% | termasuk hari {kelas} untuk {arah} di koin ini "
            f"(terbaik {urut[0][0]}, terburuk {urut[-1][0]})")


def pola_top_teks(r, n=5):
    rows = []
    for p in (r.get("pola_top") or [])[:n]:
        rows.append(f"{p['pola']} {'B' if p['arah'] == 'LONG' else 'S'} | {p['net_r']:+.1f}R | {p['win']}/{p['loss']} | "
                    f"WR {p['wr']:.0f}% | PF {p['pf']:.2f}")
    return rows


def kalibrasi_teks(sym):
    """Angka bot untuk dicocokkan baris per baris dengan DASBOR TradingView di chart 4 jam."""
    sym = sym if sym.endswith("USDT") else sym + "USDT"
    r = hasil_robot(sym)
    if not r:
        return f"{sym} belum ada di scan 4 jam terakhir."
    t = r["tick"]
    rows = [f"<b>KALIBRASI {sym} TF 4J</b>",
            f"Candle uji {(r.get('candle') or 0) - (r.get('mulai') or 0)} (sama dengan angka 'candle' di DASBOR) | "
            f"total {r.get('candle', '-')} candle | "
            f"candle pertama {time.strftime('%d/%m/%Y', time.gmtime((r.get('awal_ts') or 0) / 1000 + 7 * 3600))} | "
            f"mulai uji {time.strftime('%d/%m/%Y %H:%M', time.gmtime((r.get('uji_ts') or 0) / 1000 + 7 * 3600))} WIB",
            f"Baris 16 Rapor robot: {r['rapor']} | {r['trd']}trd WR{r['wr']:.0f} PF{r['pf']:.2f} {r['net_r']:+.1f}R",
            f"Bias {r['bias']} | {r['btc']} | lolos {r.get('lolos', '-')}", "",
            "<b>POLA TERBAIK</b> (minimal 12 trade, sama seperti tabel DASBOR)"] + (pola_top_teks(r) or ["belum ada"]) + ["", "<b>SARAN</b>"]
    if not r["saran"]:
        rows.append("Sm1 sampai Sm5 kosong (mencari pola)")
    for x in r["saran"][:3]:
        rows.append(f"Sm{x['slot']} {x['pola']} | {x['mutu']} {'EKSEKUSI' if x['eksekusi'] else 'TAHAN, ' + x['alasan']} | "
                    f"E {fp(x['entry'], t)} SL {fp(x['sl'], t)} TP1 {fp(x['tp1'], t)} TP2 {fp(x['tp2'], t)}")
    rows.append("\nBandingkan dengan DASBOR di chart 4 jam (baris 16, tabel POLA TERBAIK, kolom Sm1). "
                "Kalau ada yang beda, kirim screenshot DASBOR dan pesan ini ke Claude.")
    return "\n".join(rows)


def sl_aman(r, arah, entry, sl):
    """Cek apakah SL rawan tersentuh ekor candle. Return teks atau ''."""
    w = ((r.get("pola_chart") or {}).get("wick") or {})
    a = r.get("atr") or 0
    if not w or a <= 0:
        return ""
    ekor = w["bawah" if arah == "LONG" else "atas"]
    p = r.get("pasar") or {}
    batal = p.get("batal")
    jarak = abs(entry - sl) / a
    teks = f"Ekor candle koin ini biasanya sampai {ekor:.2f} ATR ({ekor * a / entry * 100:.1f}%)"
    if batal and ((arah == "LONG" and sl > batal - ekor * a) or (arah == "SHORT" and sl < batal + ekor * a)):
        alt = batal - (ekor + 0.1) * a if arah == "LONG" else batal + (ekor + 0.1) * a
        if abs(entry - alt) / a <= 3.0:
            teks += (f". SL {jarak:.1f} ATR rawan kena ekor, SL aman alternatif {fp(alt, r['tick'])} "
                     f"({abs(entry - alt) / entry * 100:.1f}%, kecilkan lot supaya risiko tetap sama)")
    return teks


# ---------------- peringatan dini dan BTC berbalik (dipanggil listener tiap 15 menit) ----------------
def _ema(xs, n):
    k, e = 2 / (n + 1), xs[0]
    for x in xs[1:]:
        e = x * k + e * (1 - k)
    return e


def peringatan_dini():
    """Dipanggil listener tiap menit. Tiap trade jalan dinilai bertingkat, tiap tingkat dikirim sekali:
    1 = mulai melawan (0.25 ATR atau 0.8%) dan ada tanda balik arah 15 menit / 1 jam / BTC
    2 = sudah 40% jalan ke SL atau minus 1.5%, apa pun alasannya
    3 = sudah 70% jalan ke SL. Kalau harga balik untung 0.3 ATR, tingkat direset."""
    d = _load()
    jalan = [it for it in d["open"].values() if it["status"] in ("TERISI", "TP1")]
    pesan = []
    if not jalan:
        if d.get("btc_1j") is not None:
            ubah(lambda dd: dd.update(btc_1j=None))
        return pesan
    try:
        btc = _kline("BTCUSDT", "60", 60)
        cls = [x[3] for x in btc[:-1]]
        e20 = _ema(cls[-40:], 20)
        btc_naik = cls[-1] > e20
        ch3 = (cls[-1] / cls[-4] - 1) * 100 if len(cls) > 4 else 0
    except Exception:
        btc, btc_naik, ch3 = None, None, 0
    st_btc = d.get("btc_1j")
    if btc_naik is not None and st_btc is not None and btc_naik != st_btc and jalan:
        kena = [it for it in jalan if (it["arah"] == "LONG") != btc_naik]
        if kena:
            pesan.append(f"⚠️ <b>BTC 1 JAM BERBALIK {'NAIK' if btc_naik else 'TURUN'}</b> (3 jam terakhir {ch3:+.1f}%)\n↳ posisi "
                         + ", ".join(f"{it['sym']} {it['arah']}" for it in kena)
                         + " jadi lebih berisiko. Pertimbangkan geser SL ke entry kalau sudah untung, atau kurangi lot.")
    try:
        b15 = _kline("BTCUSDT", "15", 8)[:-1]
        btc15 = (b15[-1][3] / b15[-4][3] - 1) * 100 if len(b15) >= 4 else 0.0
    except Exception:
        btc15 = 0.0
    ganti = {}
    for it in jalan:
        px = harga_live(it["sym"])
        a = it.get("atr") or 0
        if not px or a <= 0:
            continue
        kunci = it.get("id", it["sym"])
        L = it["arah"] == "LONG"
        rugi = (it["entry"] - px) if L else (px - it["entry"])      # positif = harga melawan posisi
        lv_lama = it.get("dini_lv", 1 if it.get("dini") else 0)
        if rugi <= -0.3 * a:
            if lv_lama:
                ganti[kunci] = 0              # harga balik ke arah untung: peringatan berikutnya boleh keluar lagi
            continue
        if rugi <= 0:
            continue
        lawan = rugi / a
        pct = rugi / it["entry"] * 100
        risk = it.get("risk0") or abs(it["entry"] - it["sl"]) or a
        ke_sl = rugi / risk
        alasan = []
        try:
            k15 = _kline(it["sym"], "15", 10)[:-1]          # hanya candle 15 menit yang sudah tutup
            if len(k15) >= 5:
                c0, c1, c2 = k15[-1][3], k15[-2][3], k15[-3][3]
                lo4, hi4 = min(x[2] for x in k15[-5:-1]), max(x[1] for x in k15[-5:-1])
                if (L and c0 < lo4) or ((not L) and c0 > hi4):
                    alasan.append("struktur 15 menit patah")
                if (L and c0 < c1 < c2) or ((not L) and c0 > c1 > c2):
                    alasan.append("2 candle 15 menit berturut melawan")
        except Exception:
            pass
        try:
            k1 = _kline(it["sym"], "60", 8)[:-1]
            if len(k1) >= 4:
                c_, low3, hi3 = k1[-1][3], min(x[2] for x in k1[-4:-1]), max(x[1] for x in k1[-4:-1])
                if (L and c_ < low3) or ((not L) and c_ > hi3):
                    alasan.append("struktur 1 jam patah")
        except Exception:
            pass
        if (L and btc15 <= -0.3) or ((not L) and btc15 >= 0.3):
            alasan.append(f"BTC 45 menit {btc15:+.2f}%")
        elif btc_naik is not None and btc_naik != L:
            alasan.append(f"BTC 1 jam melawan ({ch3:+.1f}% 3 jam)")
        if ke_sl >= 0.7:
            lv = 3
        elif ke_sl >= 0.4 or pct >= 1.5:
            lv = 2
        elif (lawan >= 0.25 or pct >= 0.8) and alasan:
            lv = 1
        else:
            lv = 0
        if lv <= lv_lama:
            continue
        kd = it["sym"].replace("USDT", "")
        sar = {1: f"Tanda balik arah muncul. Siapkan rencana keluar, geser SL lebih dekat kalau struktur makin rusak.",
               2: f"Sudah {ke_sl * 100:.0f}% jalan ke SL. Pertimbangkan /sl {kd} {it['arah'].lower()} 50% sekarang, "
                  f"jangan tunggu minus besar.",
               3: f"Sudah {ke_sl * 100:.0f}% jalan ke SL. Keluar sekarang dengan /sl {kd} {it['arah'].lower()}, "
                  f"atau biarkan SL bekerja. Jangan geser SL menjauh."}[lv]
        judul = {1: "PERINGATAN DINI", 2: "PERINGATAN DINI TINGKAT 2", 3: "BAHAYA, DEKAT SL"}[lv]
        pesan.append(f"{'⚠️' if lv < 3 else '🚨'} <b>{judul} {it['sym']} {it['arah']}</b>\n"
                     f"↳ harga {px:.6g} melawan {lawan:.2f} ATR (-{pct:.2f}%)"
                     + (", " + ", ".join(alasan) if alasan else "") + f".\n↳ {sar}")
        ganti[kunci] = lv

    if (btc_naik is not None and btc_naik != st_btc) or ganti:
        def f(dd):
            if btc_naik is not None:
                dd["btc_1j"] = btc_naik
            for v in dd["open"].values():
                k = v.get("id", v["sym"])
                if k in ganti:
                    v["dini_lv"] = ganti[k]
                    v["dini"] = ganti[k] > 0
        ubah(f)
    return pesan


def psikologis(p):
    """Angka bulat terdekat (kelipatan setengah satuan terbesar) bila jaraknya di bawah 1,5%."""
    if p <= 0:
        return None
    m = 10 ** math.floor(math.log10(p))
    lv = round(p / (m / 2)) * (m / 2)
    return lv if lv > 0 and abs(lv - p) / p <= 0.015 else None


def fib_teks(r):
    """Fib retracement 0.618/0.65, extension, dan angka psikologis untuk koin ini."""
    p = r.get("pasar") or {}
    if not p.get("fib_hi"):
        return ""
    t = r["tick"]
    c = r.get("live") or r["close"]
    lo, hi = sorted(p["gp"])
    naik = p["leg"] == "naik"
    tx = (f"Fib kaki {'naik' if naik else 'turun'} {fp(p['fib_lo'], t)}-{fp(p['fib_hi'], t)} | 0.618-0.65 {fp(lo, t)}-{fp(hi, t)}"
          + (" (harga di sini)" if lo <= c <= hi else f" (jarak {min(abs(c - lo), abs(c - hi)) / c * 100:.1f}%)")
          + f" | extension 1.272 {fp(p['e127'], t)}, 1.618 {fp(p['e161'], t)}")
    ps = psikologis(c)
    if ps:
        tx += f" | dekat angka psikologis {fp(ps, t)}"
    return tx


def nilai_gzh(r):
    """Skor setup Golden Zone Hunter 0-100 dari semua aspek. Return (skor, arah, alasan_plus, alasan_minus, bt)."""
    g = r.get("gzh") or {}
    L = g.get("puncak")
    arah = "LONG" if L else "SHORT"
    bt = g.get("bt") or {}
    if bt.get("n", 0) < 8 and g.get("bt1j"):
        bt = g["bt1j"]
    plus, minus, sk = [], [], 0
    if bt.get("n", 0) >= 8 and bt["pf"] >= 1.5 and bt["wr"] >= 55:
        sk += 30
        plus.append(f"backtest GZH koin ini kuat ({bt['n']}x, WR {bt['wr']:.0f}%, PF {bt['pf']:.2f})")
    elif bt.get("n", 0) >= 8 and bt["pf"] >= 1.2:
        sk += 20
        plus.append(f"backtest GZH koin ini untung ({bt['n']}x, WR {bt['wr']:.0f}%, PF {bt['pf']:.2f})")
    else:
        minus.append(f"backtest GZH koin ini belum terbukti ({bt.get('n', 0)}x, WR {bt.get('wr', 0):.0f}%, "
                     f"PF {bt.get('pf', 0):.2f})")
    p = r.get("pasar") or {}
    if p.get("arah") == arah:
        sk += 15
        plus.append(f"bias robot {arah} searah")
    else:
        minus.append(f"bias robot {p.get('arah', '-')}, berlawanan")
    izin = r.get("izin", "")
    if izin == "LONG dan SHORT" or izin.startswith(arah):
        sk += 10
        plus.append("BTC 4J mengizinkan")
    else:
        minus.append(f"BTC 4J melawan ({izin})")
    rp = r.get("rapor", "")
    if rp in ("A", "B"):
        sk += 10
        plus.append(f"rapor robot {rp}")
    elif rp == "C":
        sk += 5
    else:
        minus.append(f"rapor robot {rp}")
    if r.get("skill"):
        nk = SK.konfirmasi(r["skill"], arah)[0]
        sk += round(nk / 8 * 15)
        (plus if nk >= 5 else minus).append(f"skill tambahan {nk}/8")
    si = r.get("siklus") or {}
    c4, cd = si.get("c4P"), si.get("cDP")
    if c4 is not None and cd is not None:
        if (c4 >= 55 and cd >= 50) if L else (c4 <= 45 and cd <= 50):
            sk += 10
            plus.append(f"peluang 4J {c4:.0f}% naik, harian {cd:.0f}%")
        else:
            minus.append(f"peluang 4J {c4:.0f}% naik, harian {cd:.0f}%")
    fl = (si.get("aliran") or {}).get("skor")
    if fl is not None and ((fl >= 1) if L else (fl <= -1)):
        sk += 5
        plus.append("aliran dana searah")
    try:
        import qse_makro as MK
        if MK.kali_lot(arah) >= 1:
            sk += 5
        else:
            minus.append("tekanan makro AS untuk LONG")
    except Exception:
        sk += 5
    return min(100, sk), arah, plus, minus, bt


GZH_DEKAT_ATR = 0.5      # peringatan GZH MENDEKAT saat harga tinggal 0.5 ATR dari 0.618


def sentuh_fib(min_skor=70):
    """Notif saat harga menyentuh 0.618 Golden Zone Hunter, hanya bila setup layak:
    sentuhan pertama di kaki fib itu, datang dari sisi 0, skor semua aspek minimal 70 dan backtest GZH koin ini untung.
    Satu koin paling sering sekali per 24 jam."""
    try:
        with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
            lama = json.load(f)
    except Exception:
        return []
    cal = [r for r in lama if r.get("tf", "240") == "240" and r.get("gzh") and not r["gzh"].get("sudah")]
    if not cal:
        return []
    harga = harga_semua()
    fpath = os.path.join(STATE_DIR, "sentuh_fib.json")
    try:
        with open(fpath) as f:
            st = json.load(f)
    except Exception:
        st = {}
    px_lama, sudah, koin = st.get("px", {}), st.get("sudah", {}), st.get("koin", {})
    dekat = st.get("dekat", {})
    now = time.time()
    out = []
    for r in cal:
        sym, px = r["symbol"], harga.get(r["symbol"])
        if not px:
            continue
        g, t = r["gzh"], r["tick"]
        lv = g["levels"]
        L = g["puncak"]
        e = lv["0.618"]
        p0 = px_lama.get(sym)
        px_lama[sym] = px
        kunci = f"{sym}|{g['start']:.10g}|{g['end']:.10g}"
        if kunci not in sudah and kunci not in dekat and now - koin.get(sym, 0) >= 86400:
            a0 = g.get("atr") or r["atr"]
            jr = ((px - e) if L else (e - px)) / a0 if a0 else 99.0
            if 0 < jr <= GZH_DEKAT_ATR:          # peringatan persiapan, sekali per kaki fib
                dekat[kunci] = int(now)
                sk0, ar0, _, _, bt0 = nilai_gzh(r)
                if sk0 >= min_skor and bt0.get("n", 0) >= 8 and bt0.get("pf", 0) >= 1.2:
                    out.append(f"👀 <b>GZH MENDEKAT {sym} {ar0}</b> | skor setup {sk0}/100\n"
                               f"Harga {fp(px, t)}, tinggal {jr:.1f} ATR ({abs(px - e) / px * 100:.1f}%) dari fib 0.618 di "
                               f"{fp(e, t)}. Siapkan order. Aku kabari lagi saat harga menyentuh dan saat candle 4J tutup.")
        if p0 is None or kunci in sudah:
            continue
        datang = (p0 > e >= px) if L else (p0 < e <= px)
        if not datang:
            continue
        sudah[kunci] = int(now)          # kaki ini sudah tersentuh, tidak dipakai lagi
        if now - koin.get(sym, 0) < 86400:
            continue
        skor, arah, plus, minus, bt = nilai_gzh(r)
        if skor < min_skor or bt.get("n", 0) < 8 or bt.get("pf", 0) < 1.2:
            print(f"[GZH] {sym} disentuh tapi tidak dikirim, skor {skor}")
            continue
        koin[sym] = int(now)
        a = g.get("atr") or r["atr"]
        sl = lv["1.0"] - 0.2 * a if L else lv["1.0"] + 0.2 * a
        tp1, tp2 = lv["0.0"], lv["-0.236"]
        risk = abs(e - sl)
        pc = lambda x: abs(x - e) / e * 100
        kelas = "LAYAK BANGET DIIKUTI" if skor >= 80 else "LAYAK DIIKUTI"
        jam = bt.get("jam")
        out.append(
            f"{'🟢' if L else '🔴'} <b>{sym} {arah}</b> | skor setup {skor}/100, {kelas}\n"
            f"Harga baru turun menyentuh fib 0.618 di {fp(e, t)}, ini sentuhan pertama di kaki fib ini. "
            if L else
            f"{'🟢' if L else '🔴'} <b>{sym} {arah}</b> | skor setup {skor}/100, {kelas}\n"
            f"Harga baru naik menyentuh fib 0.618 di {fp(e, t)}, ini sentuhan pertama di kaki fib ini. ")
        out[-1] += (f"Titik 0 ada di {'atas' if L else 'bawah'} ({fp(lv['0.0'], t)}), jadi harapannya harga "
                    f"{'mantul naik' if L else 'mantul turun'} lagi ke sana.\n"
                    f"<pre>Entry {fp(e, t)}\nSL    {fp(sl, t)}  -1.00R  -{pc(sl):.1f}%\n"
                    f"TP1   {fp(tp1, t)}  +{abs(tp1 - e) / risk:.2f}R  +{pc(tp1):.1f}%\n"
                    f"TP2   {fp(tp2, t)}  +{abs(tp2 - e) / risk:.2f}R  +{pc(tp2):.1f}%</pre>\n"
                    f"Yang bikin yakin: {'; '.join(plus)}\n"
                    + (f"Yang perlu diwaspadai: {'; '.join(minus)}\n" if minus else "")
                    + (f"Di sejarah koin ini setup yang sama rata-rata selesai sekitar {jam:.0f} jam.\n" if jam else "")
                    + (f"Bias robot dan BTC 4J searah {arah}: boleh serok 1/4 lot sekarang di {fp(e, t)} dengan SL di atas. "
                       f"Sisanya masuk saat GZH TERKONFIRMASI, tutup yang 1/4 kalau GZH BATAL.\n"
                       if (r.get("pasar") or {}).get("arah") == arah
                       and (r.get("izin", "") == "LONG dan SHORT" or r.get("izin", "").startswith(arah))
                       else "Bias robot atau BTC belum searah, jangan serok dulu.\n")
                    + f"Aku pantau candle 4J ini. Begitu tutup, aku kirim GZH TERKONFIRMASI "
                    f"(tutup {'di atas' if L else 'di bawah'} {fp(e, t)}, langsung masuk) atau GZH BATAL. "
                    f"Cek detail: /cek {sym.replace('USDT', '')}")
        try:
            import qse_alarm as _AL
            _AL.tambah_gzh(sym, L, e, sl, tp1, tp2, t)
        except Exception as ex:
            print("[WARN] gzh tunggu", ex)
    batas = now - 7 * 86400
    with open(fpath + ".tmp", "w") as f:
        json.dump(dict(px=px_lama, sudah={k: v for k, v in sudah.items() if v > batas},
                       dekat={k: v for k, v in dekat.items() if v > batas},
                       koin={k: v for k, v in koin.items() if v > batas}), f)
    os.replace(fpath + ".tmp", fpath)
    return out[:5]


def _st_txt(nama, b, tf=""):
    if not b or not b.get("n"):
        return f"{nama}: belum pernah muncul di sejarah koin ini"
    nilai = "untung" if b["pf"] >= 1.2 else "impas" if b["pf"] >= 0.95 else "rugi"
    return (f"{nama}: {int(b['n'])}x | WR {b['wr']:.0f}% | PF {b['pf']:.2f} | rata {b['avg']:+.2f}R"
            + (f" ({tf})" if tf else "") + f", {nilai}" + (" (sampel kecil)" if b["n"] < 8 else ""))


def backtest_teks(r):
    """Backtest semua teknik di koin ini, supaya tidak ada koin tanpa data uji."""
    rows = ["<b>Backtest semua teknik di koin ini</b>"]
    rows.append(f"Robot v148 (pelacak 5 saran, sama dengan DASBOR): {r['trd']} trade | WR {r['wr']:.0f}% | "
                f"PF {r['pf']:.2f} | {r['net_r']:+.1f}R"
                + (", koin ini masih baru jadi pelacak belum sempat entry" if r["trd"] == 0 else ""))
    pt = r.get("pola_top") or r.get("pola_kecil") or []
    if pt:
        rows.append("90 pola terbaik: " + ", ".join(f"{p['pola']} {'B' if p['arah'] == 'LONG' else 'S'} "
                                                  f"{p['win']}/{p['loss']} {p['net_r']:+.1f}R" for p in pt[:3])
                    + (" (sampel kecil)" if not r.get("pola_top") else ""))
    g = r.get("gzh") or {}
    if g.get("bt"):
        rows.append(_st_txt("Golden Zone Hunter", g["bt"], g["bt"].get("tf", "4J")))
        if g.get("bt1j"):
            rows.append(_st_txt("Golden Zone Hunter", g["bt1j"], "1J, karena sampel 4J sedikit"))
    ch = (r.get("pola_chart") or {}).get("chart") or {}
    if ch.get("n"):
        rows.append(f"Chart pattern {ch['nama']}: {ch['n']}x, berhasil {ch['wr']:.0f}%")
    try:
        import qse_uji as QU
        u = QU.uji_koin(r["symbol"], r["tick"])
        tf = u.get("tf", "4J")
        rows += [_st_txt("Zona emas + skill (cadangan)", u["cadangan"], tf), _st_txt("Fib golden pocket", u["fib"], tf),
                 _st_txt("Siklus pola kembar", u["siklus"], tf)]
    except Exception as ex:
        rows.append(f"Uji zona emas, fib, dan siklus gagal dihitung: {str(ex)[:80]}")
    rows.append("PF di atas 1.2 artinya teknik itu untung di koin ini. Di bawah 1, teknik itu sering rugi di sini.")
    return "\n".join(rows)
