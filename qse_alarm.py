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
        d = _lihat()
        if not d["list"]:
            return "Belum ada alarm harga. Contoh: /alert BTC 60000"
        rows = [f"<b>Alarm aktif ({len(d['list'])})</b>"]
        for a in d["list"]:
            arah = "naik ke" if a["arah"] == "naik" else "turun ke"
            rows.append(f"🔔 {a['sym']} {arah} {_fp(a['harga'])}" + (f" | {a['catatan']}" if a.get("catatan") else ""))
        return "\n".join(rows)
    if args[0] == "HAPUS":
        target = args[1] if len(args) > 1 else ""
        sym = target if target.endswith("USDT") or target in ("SEMUA", "ALL") else target + "USDT"

        def f(d):
            n0 = len(d["list"])
            d["list"] = [] if target in ("SEMUA", "ALL") else [a for a in d["list"] if a["sym"] != sym]
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


def cek():
    """Dipanggil tiap menit. Return daftar pesan alarm yang kena (dan alarm itu dihapus)."""
    d0 = _lihat()
    if not d0["list"]:
        return []
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
        out, sisa = [], []
        for a in d["list"]:
            rows = [c for c in candle.get(a["sym"], []) if c[0] + 60000 > a["last_ts"]]
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
