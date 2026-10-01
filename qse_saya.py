"""QSE v148 - TRADE KAMU: catatan entry pribadi dari perintah /entry, pemantauan per menit,
peringatan kasus besar, konsultasi entry, dan statistik WR harian, mingguan, bulanan."""
import fcntl
import json
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
                    j = "saran cadangan" if it.get("cadangan") else "saran siklus" if it.get("siklus") else "saran utama"
                    hasil = (j, it["pola"])
                    break
        except Exception:
            pass
    return hasil if dengan_pola else hasil[0]


def posisi_koin(sym):
    """Semua posisi atau order terbuka di koin ini: trade kamu (/entry) dan sinyal robot yang dipantau."""
    out = []
    for it in _load()["open"].values():
        if it["sym"] == sym:
            out.append(dict(asal="trade kamu", arah=it["arah"], status=it["status"], entry=it["entry"],
                            sl=it["sl"], tp1=it["tp1"], tp2=it["tp2"]))
    try:
        import qse_fixprofit as FX
        for it in FX.load()["open"].values():
            if it["sym"] == sym:
                out.append(dict(asal=f"sinyal robot {it['pola']}", arah=it["arah"], status=it["status"],
                                entry=it["entry"], sl=it["sl"], tp1=it["tp1"], tp2=it["tp2"]))
    except Exception:
        pass
    return out


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


def konsultasi(sym, arah=None, entry=None):
    r = hasil_robot(sym)
    px = harga_live(sym)
    t = tick_of(r, px or 1)
    if r is None:
        return f"<b>KONSULTASI {sym}</b>\nKoin ini belum ada di scan 4 jam terakhir. Cek nama koinnya, contoh /cek DOT"
    ps = r.get("pasar", {})
    pos = posisi_koin(sym)
    arah = arah or (pos[0]["arah"] if pos else ps.get("arah", "LONG"))
    rows_pos = []
    for p in pos:
        risk = max(abs(p["entry"] - p["sl"]), 1e-12)
        gerak = ((px - p["entry"]) if p["arah"] == "LONG" else (p["entry"] - px)) / risk if px else 0.0
        rows_pos.append(f"➡️ {p['arah']} {p['asal']} | {NM_ST.get(p['status'], p['status'])} | entry {fp(p['entry'], t)} "
                        f"SL {fp(p['sl'], t)} TP1 {fp(p['tp1'], t)}" +
                        (f" | sekarang {gerak:+.2f}R" if p["status"] != "MENUNGGU" and px else ""))
        if ps.get("arah") and ps["arah"] != p["arah"]:
            rows_pos.append(f"   Bias robot sekarang {ps['arah']}, berlawanan dengan posisi ini. Pilihan: tutup di profit kecil, "
                            f"geser SL ke entry, atau biarkan sampai SL atau TP. Jangan buka {ps['arah']} di koin yang sama.")
    rows = [f"<b>KONSULTASI {sym} {arah}</b>",
            f"Harga sekarang {fp(px, t) if px else '-'} | robot: rapor {r['rapor']} ({r['trd']} trade, WR {r['wr']:.0f}%, "
            f"PF {r['pf']:.2f}) | bias {ps.get('arah', '-')}",
            f"{r['btc']} | yang diizinkan: {r.get('izin', '-')}"]
    for s in r["saran"][:3]:
        v = "EKSEKUSI" if s["eksekusi"] else "TAHAN " + s["alasan"]
        rows.append(f"Saran {s['slot']} {s['arah']} {s['pola']} mutu {s['mutu']} {v} | E {fp(s['entry'], t)} "
                    f"SL {fp(s['sl'], t)} TP1 {fp(s['tp1'], t)} TP2 {fp(s['tp2'], t)}")
    if not r["saran"]:
        rows.append("Robot belum punya saran untuk koin ini.")
    if rows_pos:
        rows.append("<b>Posisi terbuka di koin ini</b>")
        rows += rows_pos
    if ps.get("zona_searah"):
        lo, hi = ps["gp"] if ps.get("in_gp") else ps["gz"]
        rows.append(f"Zona emas {'GP' if ps.get('in_gp') else 'GZ'} {fp(min(lo, hi), t)}-{fp(max(lo, hi), t)} | "
                    f"batal {fp(ps['batal'], t)}")
    sk = r.get("siklus") or {}
    if sk and not sk.get("error"):
        rows.append("<b>Siklus pasar</b>")
        if sk.get("c4P") is not None:
            rows.append(f"Arah: 4J naik {sk['c4P']:.0f}% | 1D naik {(sk.get('cDP') or 50):.0f}% | BTC naik {r.get('bProb', 50):.0f}%")
        fl = sk.get("aliran") or {}
        if fl:
            dana = "DANA MASUK" if fl["skor"] >= 2 else "DANA KELUAR" if fl["skor"] <= -2 else "NETRAL"
            rows.append(f"Aliran dana: {dana} skor {fl['skor']:+d} | CMF {fl['cmf']:.2f} | MFI {fl['mfi']:.0f} | "
                        f"CVD {'naik' if fl['cvd_up'] else 'turun'}")
        pk = sk.get("pola")
        if pk:
            rows.append(f"Pola kembar: {pk['n']} pola mirip | sesudahnya naik {pk['up'] * 100:.0f}% | "
                        f"teruji {pk['hitN']}/{pk['hitT']} tepat")
        mu = sk.get("musim") or {}
        if mu.get("hari"):
            b_, w_ = mu["hari"]["terbaik"], mu["hari"]["terburuk"]
            rows.append(f"Musiman hari: terbaik {b_[0]} {b_[1]:+.2f}% WR {b_[2]:.0f}%, terburuk {w_[0]} {w_[1]:+.2f}%")
        if mu.get("jam"):
            b_, w_ = mu["jam"]["terbaik"], mu["jam"]["terburuk"]
            rows.append(f"Musiman jam WIB: terbaik {b_[0]} {b_[1]:+.2f}%, terburuk {w_[0]} {w_[1]:+.2f}%")
        pv = sk.get("pivot")
        if pv:
            import qse_siklus as SIK
            tx = f"Siklus besar: terakhir {pv['jenis']} {SIK.tgl(pv['t'])} di {fp(pv['p'], t)}"
            if pv.get("berikut"):
                tx += (f". {pv['berikut']} berikutnya sekitar {SIK.tgl(pv['t1'])} (±{pv['sd'] / 86400000:.0f} hari) "
                       f"di {fp(pv['lo'], t)}-{fp(pv['hi'], t)}")
            rows.append(tx)
        if sk.get("saran"):
            x = sk["saran"]
            rows.append(f"Saran siklus: {x['arah']} {x['order']} di {fp(x['entry'], t)} | SL {fp(x['sl'], t)} | "
                        f"TP1 {fp(x['tp1'], t)} | TP2 {fp(x['tp2'], t)}")
    if r.get("skill"):
        rows.append("<b>Skill tambahan</b>")
        rows += SK.detail(r["skill"], arah, lambda x: fp(x, t))
    label, alasan, _, _ = nilai(sym, arah, entry)
    rows.append(f"<b>Penilaian {arah}: {label}</b>")
    rows += ["➡️ " + a for a in alasan]
    saran = {"SEJALAN": "Boleh entry, ikuti SL dan TP robot atau pasang LIMIT di zona emas.",
             "HATI-HATI": "Kalau tetap masuk, pakai setengah lot dan SL wajib terpasang.",
             "BERISIKO": "Sebaiknya tunggu. Kondisi utama sedang melawan arah ini.",
             "NETRAL": "Robot belum punya pendapat kuat. Tunggu saran atau zona emas."}[label]
    rows.append(saran)
    return "\n".join(rows)


# ---------------- /entry ----------------
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
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    pct, harga = 100.0, None
    for a in args[1:]:
        if a.endswith("%") and _angka(a[:-1]) is not None:
            pct = _angka(a[:-1])
        elif _angka(a) is not None:
            harga = _angka(a)
    return sym, max(0.0, min(100.0, pct)), harga


def tutup(args, label="TUTUP"):
    """/tp KOIN [30%] [harga], /sl KOIN [50%] [harga], /tutup KOIN [harga]. Tanpa harga = harga sekarang."""
    if not args:
        return "Format: /tp AUSDT 30% atau /sl AUSDT 100% atau /tp AUSDT 50% 1.050"
    sym, pct, harga = _parse_tutup(args)
    px = harga or harga_live(sym)
    if not px:
        return f"Harga {sym} tidak bisa diambil, tulis harganya, contoh /tp {args[0]} 50% 1.050"
    now = int(time.time() * 1000)

    def f(d):
        rows = []
        for k in [k for k, v in d["open"].items() if v["sym"] == sym]:
            it = d["open"][k]
            t = it["tick"]
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
    return "\n\n".join(rows) if rows else f"Tidak ada trade kamu yang terbuka di {sym}."


def ubah_level(args):
    """/ubah KOIN sl 0.99 tp1 1.05 tp2 1.08, atau /ubah KOIN sl entry untuk geser SL ke titik impas."""
    if not args:
        return "Format: /ubah AUSDT sl 0.99 tp1 1.05 tp2 1.08 atau /ubah AUSDT sl entry"
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
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
        for it in [v for v in d["open"].values() if v["sym"] == sym]:
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
                ev.append((why, f"kena SL di {fp(sl, it['tick'])}, selesai {res:+.2f}R"))
                return ev
            if it["status"] == "TERISI" and ((hi >= t1) if L else (lo <= t1)):
                r = _tutup_bagian(it, 0.5, t1)
                it["status"] = "TP1"
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
            ik = {"TERISI": "📥", "TP1": "💰", "TP2": "🏆", "SL": "🛑", "BE": "⚖️", "INFO": "⚠️"}
            for e, txt in ev:
                pesan.append(f"{ik.get(e, '•')} <b>{it['sym']} {it['arah']}</b>\n↳ {txt} | entry {fp(it['entry'], it['tick'])}")
            if it["status"] == "SELESAI":
                d["closed"].append(d["open"].pop(k))
        return pesan
    return ubah(f)


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
        blok.append(blok_posisi(i, it, harga.get(it["sym"], 0.0), f" | nilai robot {it['nilai']}"))
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
    for j in ("saran utama", "saran cadangan", "saran siklus", "manual"):
        x = [c for c in closed if c.get("why") in ("SL", "BE", "TP2", "TUTUP") and c.get("closed_ts", 0) >= a
             and c.get("jalur", "manual") == j]
        if x:
            w = sum(1 for c in x if c["result_r"] > 0)
            rows.append(f"{j.capitalize()}: {len(x)} trade | WR {w / len(x) * 100:.0f}% | {sum(c['result_r'] for c in x):+.2f}R")
    if len(rows) == 1:
        rows.append("Belum ada trade yang selesai.")
    return "\n".join(rows)


# ---------------- belajar dari trade kamu ----------------
LOT_DASAR = {"saran utama": 1.0, "saran cadangan": 0.5, "saran siklus": 0.5, "manual": 0.5}
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
    for j in ("saran utama", "saran cadangan", "saran siklus", "manual"):
        n = sum(1 for c in cl if c.get("jalur", "manual") == j)
        rows.append(f"{j.capitalize()}: {lot_jalur(j):g}x lot normal" + ("" if n >= 10 else f" (bawaan, baru {n}/10 trade)"))
    return "\n".join(rows)
