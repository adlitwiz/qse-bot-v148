"""QSE v148 - TRADE KAMU: catatan entry pribadi dari perintah /entry, pemantauan per menit,
peringatan kasus besar, konsultasi entry, dan statistik WR harian, mingguan, bulanan."""
import fcntl
import json
import os
import time
import requests
from config import STATE_DIR, BYBIT_URL, P

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


# ---------------- data pasar ringan ----------------
def harga_live(sym):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear", "symbol": sym}, timeout=15)
        lst = r.json().get("result", {}).get("list", [])
        return float(lst[0]["lastPrice"]) if lst else 0.0
    except Exception:
        return 0.0


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


# ---------------- konsultasi ----------------
def nilai(sym, arah, entry=None):
    """Penilaian robot untuk rencana entry. Return (label, alasan[], hasil_robot, harga_live)."""
    r = hasil_robot(sym)
    px = harga_live(sym)
    if r is None:
        return "TANPA DATA", ["koin ini belum ada di scan 4 jam terakhir"], None, px
    L = arah == "LONG"
    merah, kuning, hijau = [], [], []
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
    arah = arah or ps.get("arah", "LONG")
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
    if ps.get("zona_searah"):
        lo, hi = ps["gp"] if ps.get("in_gp") else ps["gz"]
        rows.append(f"Zona emas {'GP' if ps.get('in_gp') else 'GZ'} {fp(min(lo, hi), t)}-{fp(max(lo, hi), t)} | "
                    f"batal {fp(ps['batal'], t)}")
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


def parse_entry(args):
    """/entry long limit AUSDT 1.022 [sl 0.99] [tp1 1.05] [tp2 1.08]"""
    arah = order = sym = None
    nums, kv, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a in ("LONG", "BUY", "L"):
            arah = "LONG"
        elif a in ("SHORT", "SELL", "S"):
            arah = "SHORT"
        elif a in ("LIMIT", "MARKET", "MKT"):
            order = "MARKET" if a != "LIMIT" else "LIMIT"
        elif a in ("SL", "TP", "TP1", "TP2") and i + 1 < len(args) and _angka(args[i + 1]) is not None:
            kv["TP1" if a == "TP" else a] = _angka(args[i + 1])
            i += 1
        elif _angka(a) is not None:
            nums.append(_angka(a))
        else:
            sym = a if a.endswith("USDT") else a + "USDT"
        i += 1
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
    now = int(time.time() * 1000)

    def simpan(d):
        d["seq"] += 1
        tid = f"{sym}#{d['seq']}"
        d["open"][tid] = dict(id=tid, no=d["seq"], sym=sym, arah=arah, order=order, entry=harga, sl=sl, tp1=tp1,
                              tp2=tp2, atr=a_now, tick=t, sumber=sumber, nilai=label, created_ts=now,
                              last_ts=now, status="TERISI" if order == "MARKET" else "MENUNGGU",
                              fill_ts=now if order == "MARKET" else 0, alert=[])
        return d["seq"]
    no = ubah(simpan)
    fee_r = 2 * FEE / 100 * harga / risk
    rows = [f"<b>TRADE KAMU #{no} TERCATAT</b>",
            f"{sym} {arah} {order}" + (" (sudah terisi)" if order == "MARKET" else " (menunggu terisi)"),
            f"<pre>Entry {fp(harga, t)}\nSL    {fp(sl, t)}  -1.00R\nTP1   {fp(tp1, t)}  +{abs(tp1 - harga) / risk:.2f}R\n"
            f"TP2   {fp(tp2, t)}  +{abs(tp2 - harga) / risk:.2f}R</pre>",
            f"SL dan TP dari {sumber}. Fee pulang pergi sekitar {fee_r:.2f}R.",
            f"<b>Penilaian robot: {label}</b>"]
    rows += ["➡️ " + x for x in alasan]
    rows.append("Robot memantau tiap menit dan mengabari saat terisi, TP1, TP2, SL, atau ada kasus besar. "
                "Keluar lebih awal: /tutup " + sym.replace("USDT", "") + " HARGA")
    return "\n".join(rows)


# ---------------- /tutup /batal ----------------
def tutup(args):
    if not args:
        return "Format: /tutup KOIN [HARGA], contoh /tutup AUSDT 1.050"
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    harga = _angka(args[1]) if len(args) > 1 else None
    px = harga or harga_live(sym)

    def f(d):
        rows = []
        for k in [k for k, v in d["open"].items() if v["sym"] == sym]:
            it = d["open"].pop(k)
            if it["status"] == "MENUNGGU":
                it.update(status="BATAL", why="batal manual", result_r=0.0, closed_ts=int(time.time() * 1000))
                rows.append(f"➡️ #{it['no']} {sym} belum terisi, dibatalkan (tidak dihitung)")
            else:
                risk = max(abs(it["entry"] - it["sl"]), 1e-12)
                gerak = ((px - it["entry"]) if it["arah"] == "LONG" else (it["entry"] - px)) / risk
                r1 = abs(it["tp1"] - it["entry"]) / risk
                res = 0.5 * r1 + 0.5 * gerak if it["status"] == "TP1" else gerak
                it.update(status="SELESAI", why="TUTUP", result_r=round(res, 3), exit=px, closed_ts=int(time.time() * 1000))
                rows.append(f"➡️ #{it['no']} {sym} {it['arah']} ditutup di {fp(px, it['tick'])} | {res:+.2f}R")
            d["closed"].append(it)
        return rows
    rows = ubah(f)
    return "\n".join(rows) if rows else f"Tidak ada trade kamu yang terbuka di {sym}."


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


# ---------------- pemantauan ----------------
def _jalan(it, rows, iv):
    """Proses candle (ts, high, low, close) untuk satu trade. Return daftar (event, teks)."""
    ev = []
    L = it["arah"] == "LONG"
    e, sl, t1, t2 = it["entry"], it["sl"], it["tp1"], it["tp2"]
    risk = max(abs(e - sl), 1e-12)
    r1, r2 = abs(t1 - e) / risk, abs(t2 - e) / risk
    for ts, hi, lo, cl in rows:
        if ts <= it["last_ts"] - iv:
            continue
        it["last_ts"] = ts + iv
        if it["status"] == "MENUNGGU":
            if not (lo <= e if L else hi >= e):
                continue
            it["status"], it["fill_ts"] = "TERISI", ts
            ev.append(("TERISI", "ORDER TERISI"))
        if it["status"] == "TERISI":
            if (lo <= sl) if L else (hi >= sl):
                it.update(status="SELESAI", why="SL", result_r=-1.0, closed_ts=ts)
                ev.append(("SL", "KENA SL -1.00R"))
                return ev
            if (hi >= t1) if L else (lo <= t1):
                it["status"] = "TP1"
                ev.append(("TP1", f"KENA TP1 +{r1:.2f}R. Tutup separuh, geser SL ke entry {fp(e, it['tick'])}"))
        if it["status"] == "TP1":
            if (hi >= t2) if L else (lo <= t2):
                res = 0.5 * r1 + 0.5 * r2
                it.update(status="SELESAI", why="TP2", result_r=round(res, 3), closed_ts=ts)
                ev.append(("TP2", f"KENA TP2, selesai {res:+.2f}R"))
                return ev
            if (lo <= e) if L else (hi >= e):
                res = 0.5 * r1
                it.update(status="SELESAI", why="BE", result_r=round(res, 3), closed_ts=ts)
                ev.append(("BE", f"kembali ke entry setelah TP1, selesai {res:+.2f}R"))
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
            for e, txt in ev:
                pesan.append(f"➡️ #{it['no']} <b>{it['sym']} {it['arah']}</b> | {txt} | entry {fp(it['entry'], it['tick'])}")
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
                    pesan.append(f"➡️ #{it['no']} <b>{it['sym']} {arah}</b> | {txt}. {saran}")
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


def status_saya():
    d = _load()
    rows = [f"<b>Trade kamu terbuka ({len(d['open'])})</b>"]
    nm = {"MENUNGGU": "menunggu terisi", "TERISI": "posisi jalan", "TP1": "sudah TP1, SL di entry"}
    for it in d["open"].values():
        rows.append(f"➡️ #{it['no']} {it['sym']} {it['arah']} {it['order']} | entry {fp(it['entry'], it['tick'])} | "
                    f"{nm.get(it['status'], it['status'])} | nilai robot {it['nilai']}")
    if not d["open"]:
        rows.append("Tidak ada.")
    rows.append("WR trade kamu: " + ringkas(d["closed"]))
    return "\n".join(rows)
