"""QSE v148 - ALARM HARGA. /alert BTC 60000 [catatan], /alert untuk daftar, /alert hapus BTC atau /alert hapus semua.
Dicek tiap menit oleh qse_listener.py memakai candle 1 menit, jadi sumbu candle yang menyentuh level ikut terdeteksi."""
import fcntl
import json
import os
import time
import requests
from config import STATE_DIR, BYBIT_URL

FILE = os.path.join(STATE_DIR, "alarm.json")


def _ubah(fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(FILE) as f:
                d = json.load(f)
        except Exception:
            d = {"seq": 0, "list": []}
        hasil = fn(d)
        with open(FILE + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(FILE + ".tmp", FILE)
        return hasil


def _lihat():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {"seq": 0, "list": []}


def _harga(sym):
    try:
        r = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear", "symbol": sym}, timeout=10)
        lst = r.json().get("result", {}).get("list", [])
        return float(lst[0]["lastPrice"]) if lst else 0.0
    except Exception:
        return 0.0


def _angka(x):
    try:
        return float(x.replace(",", "."))
    except ValueError:
        return None


def _fp(x):
    return f"{x:,.2f}" if x >= 100 else f"{x:.6g}"


def perintah(args):
    if not args:
        lst = [a for a in _lihat()["list"] if a.get("jenis", "sentuh") == "sentuh"]
        if not lst:
            return "Belum ada alarm harga. Contoh: /alert BTC 60000"
        rows = [f"<b>Alarm aktif ({len(lst)})</b>"]
        for a in lst:
            arah = "naik ke" if a["arah"] == "naik" else "turun ke"
            rows.append(f"🔔 {a['sym']} {arah} {_fp(a['harga'])}" + (f" | {a['catatan']}" if a.get("catatan") else ""))
        return "\n".join(rows)
    if args[0] == "HAPUS":
        target = args[1] if len(args) > 1 else ""
        sym = target if target.endswith("USDT") or target in ("SEMUA", "ALL") else target + "USDT"

        def f(d):
            n0 = len(d["list"])
            d["list"] = [a for a in d["list"] if a.get("jenis", "sentuh") != "sentuh"
                         or (target not in ("SEMUA", "ALL") and a["sym"] != sym)]
            return n0 - len(d["list"])
        n = _ubah(f)
        return f"{n} alarm dihapus."
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    lv = _angka(args[1]) if len(args) > 1 else None
    if lv is None or lv <= 0:
        return "Format: /alert BTC 60000 atau /alert BTC 60000 tembus resisten"
    px = _harga(sym)
    if not px:
        return f"{sym} tidak ditemukan di perpetual Bybit."
    arah = "naik" if lv > px else "turun"
    catatan = " ".join(args[2:]).lower()

    def f(d):
        d["seq"] += 1
        d["list"].append(dict(id=d["seq"], sym=sym, harga=lv, arah=arah, catatan=catatan,
                              dibuat=int(time.time() * 1000), last_ts=int(time.time() * 1000)))
    _ubah(f)
    return (f"🔔 Alarm dipasang: {sym} {'naik ke' if arah == 'naik' else 'turun ke'} {_fp(lv)}\n"
            f"Harga sekarang {_fp(px)}. Kamu dikabari begitu harga menyentuh level itu.")


# ---------------- alarm candle tutup: /tunggu SOL atas 150 4j ----------------
TF = {"4J": ("240", 4 * 3600000, "4J"), "4H": ("240", 4 * 3600000, "4J"), "1J": ("60", 3600000, "1J"),
      "1H": ("60", 3600000, "1J"), "15M": ("15", 900000, "15M"),
      "D": ("D", 86400000, "1D"), "1D": ("D", 86400000, "1D")}
BERLAKU_HARI = 7


def tunggu(args):
    """/tunggu SOL atas 150 4j = kabari saat candle 4J TUTUP di atas 150. Tanpa TF = 4J."""
    if not args:
        d = [a for a in _lihat()["list"] if a.get("jenis") in ("tutup", "gzh")]
        if not d:
            return ("Belum ada alarm candle tutup. Contoh: /tunggu SOL atas 150 4j\n"
                    "Arah: atas atau bawah. TF: 15m, 1j, 4j, 1d. Hapus: /tunggu hapus SOL")
        rows = [f"<b>Menunggu candle tutup ({len(d)})</b>"]
        for a in d:
            if a["jenis"] == "gzh":
                rows.append(f"📐 {a['sym']} GZH {'LONG' if a['L'] else 'SHORT'}: candle 4J tutup {'di atas' if a['L'] else 'di bawah'} "
                            f"{_fp(a['harga'])}")
            else:
                rows.append(f"⏳ {a['sym']} candle {a['tf_nama']} tutup di {a['arah']} {_fp(a['harga'])}"
                            + (f" | {a['catatan']}" if a.get("catatan") else ""))
        return "\n".join(rows)
    if args[0] == "HAPUS":
        target = args[1] if len(args) > 1 else ""
        sym = target if target.endswith("USDT") or target in ("SEMUA", "ALL") else target + "USDT"

        def f(d):
            n0 = len(d["list"])
            d["list"] = [a for a in d["list"] if a.get("jenis") not in ("tutup", "gzh")
                         or (target not in ("SEMUA", "ALL") and a["sym"] != sym)]
            return n0 - len(d["list"])
        return f"{_ubah(f)} alarm candle tutup dihapus."
    sym = args[0] if args[0].endswith("USDT") else args[0] + "USDT"
    arah = next((("atas" if a in ("ATAS", "DIATAS", "NAIK", "LONG") else "bawah") for a in args[1:]
                 if a in ("ATAS", "DIATAS", "NAIK", "LONG", "BAWAH", "DIBAWAH", "TURUN", "SHORT")), None)
    lv = next((_angka(a) for a in args[1:] if _angka(a) is not None and a not in TF), None)
    tf = next((TF[a] for a in args[1:] if a in TF), TF["4J"])
    if not arah or lv is None or lv <= 0:
        return "Format: /tunggu SOL atas 150 4j atau /tunggu BTC bawah 60000 1j"
    px = _harga(sym)
    if not px:
        return f"{sym} tidak ditemukan di perpetual Bybit."
    sekarang = int(time.time() * 1000)

    def f(d):
        d["seq"] += 1
        d["list"].append(dict(id=d["seq"], jenis="tutup", sym=sym, harga=lv, arah=arah, tf=tf[0], tf_ms=tf[1],
                              tf_nama=tf[2], catatan=" ".join(a for a in args[1:] if a not in TF and _angka(a) is None
                                                            and a not in ("ATAS", "BAWAH")).lower(),
                              dibuat=sekarang, last_ts=sekarang // tf[1] * tf[1] - tf[1]))
    _ubah(f)
    return (f"⏳ Siap. Aku kabari saat candle {tf[2]} {sym} TUTUP di {arah} {_fp(lv)}.\n"
            f"Harga sekarang {_fp(px)}. Sumbu yang cuma lewat tidak dihitung, harus harga tutup. "
            f"Alarm hangus sendiri setelah {BERLAKU_HARI} hari.")


def tambah_gzh(sym, L, e, sl, tp1, tp2, tick, skor=None, wr=None, dikirim=True):
    """Dipanggil Golden Zone Hunter saat harga menyentuh 0.618: nilai candle 4J tempat sentuhan terjadi saat tutup."""
    sekarang = int(time.time() * 1000)

    def f(d):
        if any(a.get("jenis") == "gzh" and a["sym"] == sym for a in d["list"]):
            return
        d["seq"] += 1
        d["list"].append(dict(id=d["seq"], jenis="gzh", sym=sym, L=bool(L), harga=float(e), sl=float(sl), tp1=float(tp1),
                              tp2=float(tp2), tick=float(tick), tf="240", tf_ms=4 * 3600000, skor=skor, wr=wr, dikirim=bool(dikirim),
                              candle=sekarang // (4 * 3600000) * (4 * 3600000), dibuat=sekarang))
    _ubah(f)


def _tutup_candle(sym, tf, tf_ms):
    """Candle yang sudah tutup: list (start_ms, close)."""
    try:
        r = requests.get(BYBIT_URL + "/v5/market/kline",
                         params={"category": "linear", "symbol": sym, "interval": tf, "limit": 10}, timeout=10)
        now = time.time() * 1000
        return sorted((int(x[0]), float(x[4])) for x in r.json().get("result", {}).get("list", [])
                      if int(x[0]) + tf_ms <= now)
    except Exception:
        return None


def _pesan_gzh(a, cl):
    import telegram_notify as TG
    L, t = a["L"], a["tick"]
    if not ((cl > a["harga"]) if L else (cl < a["harga"])):
        return (f"❌ <b>GZH BATAL  ·  {a['sym']} {'LONG' if L else 'SHORT'}</b>\n"
                f"Jangan entry. Candle 4J tutup {'di bawah' if L else 'di atas'} 0.618 ({TG.fp(a['harga'], t)}).")
    risk = abs(cl - a["sl"])
    if risk <= 0 or ((a["tp1"] <= cl) if L else (a["tp1"] >= cl)):          # tp1 di sini = titik 0 fib
        return (f"⚠️ <b>GZH {a['sym']}</b> candle tutup memantul di {TG.fp(cl, t)}, tapi harga sudah melewati titik 0 fib. "
                f"Lewati.")
    import qse_saya as SY
    arah = "LONG" if L else "SHORT"
    bd = SY.berita_depan(3)
    if bd:
        return (f"⏸️ <b>GZH {a['sym']} {arah}</b>: candle 4J tutup memantul di {TG.fp(cl, t)}, tapi ada berita besar "
                f"{TG.e(bd['judul'])} dalam 3 jam. Lewati.")
    tp = cl + SY.GZH_TP_R * risk if L else cl - SY.GZH_TP_R * risk
    try:
        import qse_catat as CT
        CT.tambah("gzh", a["sym"], arah, cl, a["sl"], tp, tp, berlaku_jam=4, ket="GZH konfirmasi")
    except Exception as ex:
        print("[WARN] catat gzh", ex)
    return (f"{'🟢' if L else '🔴'} <b>GZH TERKONFIRMASI  ·  {a['sym']} {arah}</b>\n"
            f"{SY.layak('saran GZH', arah, a.get('skor'))}\n"
            + SY.blok_salin(cl, a["sl"], tp, tp, "MARKET", t, sym=a["sym"], arah=arah) + "\n"
            f"Masuk MARKET sekarang. Tutup penuh di TP (2R). 10 hari belum kena, tutup manual.")


def _cek_tutup(d0):
    """Alarm candle tutup dan konfirmasi GZH. Return (pesan, set id selesai, dict id -> last_ts baru)."""
    out, selesai, maju = [], set(), {}
    now = time.time() * 1000
    cache = {}
    for a in d0["list"]:
        if a.get("jenis") not in ("tutup", "gzh"):
            continue
        if now - a["dibuat"] > BERLAKU_HARI * 86400000:
            selesai.add(a["id"])
            continue
        k = (a["sym"], a["tf"])
        if k not in cache:
            cache[k] = _tutup_candle(a["sym"], a["tf"], a["tf_ms"])
        rows = cache[k]
        if not rows:
            continue
        if a["jenis"] == "gzh":
            c = next((cl for ts, cl in rows if ts == a["candle"]), None)
            if c is not None:
                p = _pesan_gzh(a, c)
                if p:
                    out.append(p)
                selesai.add(a["id"])
            elif rows[-1][0] > a["candle"]:
                selesai.add(a["id"])          # candle sentuhan terlewat (bot mati), jangan kirim terlambat
            continue
        for ts, cl in rows:
            if ts <= a["last_ts"]:
                continue
            maju[a["id"]] = ts
            if (cl > a["harga"]) if a["arah"] == "atas" else (cl < a["harga"]):
                out.append(f"⏳ <b>{a['sym']} candle {a['tf_nama']} TUTUP di {a['arah']} {_fp(a['harga'])}</b>\n"
                           f"↳ harga tutup {_fp(cl)}" + (f" | {a['catatan']}" if a.get("catatan") else ""))
                selesai.add(a["id"])
                break
    return out, selesai, maju


def cek():
    """Dipanggil tiap menit. Return daftar pesan alarm yang kena (dan alarm itu dihapus)."""
    d0 = _lihat()
    if not d0["list"]:
        return []
    out_t, selesai, maju = _cek_tutup(d0)
    if selesai or maju:
        def g(d):
            for a in d["list"]:
                if a["id"] in maju:
                    a["last_ts"] = maju[a["id"]]
            d["list"] = [a for a in d["list"] if a["id"] not in selesai]
        _ubah(g)
        d0 = _lihat()
    d0 = dict(d0, list=[a for a in d0["list"] if a.get("jenis", "sentuh") == "sentuh"])
    if not d0["list"]:
        return out_t
    candle = {}
    for sym in {a["sym"] for a in d0["list"]}:
        try:
            r = requests.get(BYBIT_URL + "/v5/market/kline",
                             params={"category": "linear", "symbol": sym, "interval": "1", "limit": 120}, timeout=10)
            candle[sym] = sorted((int(x[0]), float(x[2]), float(x[3]), float(x[4]))
                                 for x in r.json().get("result", {}).get("list", []))
        except Exception:
            candle[sym] = []

    def f(d):
        out, sisa = list(out_t), []
        for a in d["list"]:
            if a.get("jenis", "sentuh") != "sentuh":
                sisa.append(a)
                continue
            rows =[c for c in candle.get(a["sym"], []) if c[0] + 60000 > a["last_ts"]]
            kena = None
            for ts, hi, lo, cl in rows:
                if (a["arah"] == "naik" and hi >= a["harga"]) or (a["arah"] == "turun" and lo <= a["harga"]):
                    kena = cl
                    break
            if rows:
                a["last_ts"] = rows[-1][0]
            if kena is not None:
                out.append(f"🔔 <b>{a['sym']}</b> {'naik' if a['arah'] == 'naik' else 'turun'} menyentuh {_fp(a['harga'])}\n"
                           f"↳ harga sekarang {_fp(kena)}" + (f" | {a['catatan']}" if a.get("catatan") else ""))
            else:
                sisa.append(a)
        d["list"] = sisa
        return out
    return _ubah(f)
