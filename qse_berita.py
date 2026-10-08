"""QSE v148 - PENJAGA BERITA. Tidak mengubah vonis teknikal, hanya menahan atau memperingatkan.
  1. Kalender ekonomi: berita besar USD berdampak tinggi (CPI, FOMC, NFP, PCE, dan sejenisnya)
  2. Pengumuman Bybit: koin yang diumumkan delisting dikeluarkan dari sinyal
  3. Detektor guncangan: BTC bergerak jauh di luar kebiasaan dalam 1 sampai 3 jam
Semua sumber gagal dengan aman: kalau tidak bisa diambil, bot tetap jalan tanpa penjaga itu."""
import datetime as dt
import json
import os
import re
import time
import numpy as np
import requests
from config import STATE_DIR, BYBIT_URL

CACHE = os.path.join(STATE_DIR, "berita.json")
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
JAM = 3600 * 1000
WIB = dt.timezone(dt.timedelta(hours=7))
SEBELUM, SESUDAH = 2 * JAM, 1 * JAM          # jendela jeda berita


def _load():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(c):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CACHE + ".tmp", "w") as f:
        json.dump(c, f)
    os.replace(CACHE + ".tmp", CACHE)


def jam_wib(ms):
    return dt.datetime.fromtimestamp(ms / 1000, WIB).strftime("%d/%m %H:%M WIB")


# ---------------- 1. kalender ekonomi ----------------
def kalender():
    c = _load()
    now = int(time.time() * 1000)
    if now - c.get("kal_ts", 0) < 3 * JAM and "kal" in c:
        return c["kal"]
    try:
        r = requests.get(FF_URL, timeout=15, headers={"User-Agent": "Mozilla/5.0 qse-bot"})
        ev = []
        for x in r.json():
            if x.get("country") == "USD" and x.get("impact") == "High":
                t = dt.datetime.fromisoformat(x["date"]).timestamp() * 1000
                ev.append(dict(judul=x.get("title", "berita USD"), ts=int(t)))
        c["kal"], c["kal_ts"] = sorted(ev, key=lambda e: e["ts"]), now
        _save(c)
    except Exception as ex:
        print("[WARN] kalender ekonomi:", ex)
    return c.get("kal", [])


def jeda(now_ms=None):
    """Berita besar yang jendela jedanya sedang aktif (2 jam sebelum sampai 1 jam sesudah)."""
    now_ms = now_ms or int(time.time() * 1000)
    return next((e for e in kalender() if e["ts"] - SEBELUM <= now_ms <= e["ts"] + SESUDAH), None)


def hari_ini(now_ms=None):
    now_ms = now_ms or int(time.time() * 1000)
    d = dt.datetime.fromtimestamp(now_ms / 1000, WIB).date()
    return [e for e in kalender() if dt.datetime.fromtimestamp(e["ts"] / 1000, WIB).date() == d]


def pengingat(now_ms=None):
    """Berita besar dalam 75 menit ke depan yang belum diingatkan. Tiap berita hanya sekali."""
    now_ms = now_ms or int(time.time() * 1000)
    c = _load()
    sudah = set(c.get("ingat", []))
    out = [e for e in kalender() if 0 < e["ts"] - now_ms <= 75 * 60000 and f"{e['ts']}{e['judul']}" not in sudah]
    if out:
        c["ingat"] = (list(sudah) + [f"{e['ts']}{e['judul']}" for e in out])[-200:]
        _save(c)
    return out


# ---------------- 2. pengumuman Bybit ----------------
def delisting():
    """Simbol yang diumumkan delisting oleh Bybit dalam 45 hari terakhir."""
    c = _load()
    now = int(time.time() * 1000)
    if now - c.get("del_ts", 0) < 3 * JAM and "del" in c:
        return set(c["del"])
    try:
        r = requests.get(BYBIT_URL + "/v5/announcements/index",
                         params={"locale": "en-US", "type": "delistings", "limit": 50}, timeout=15)
        syms = set()
        for it in r.json().get("result", {}).get("list", []):
            ts = int(it.get("dateTimestamp") or it.get("publishTime") or now)
            if now - ts > 45 * 86400000:
                continue
            teks = f"{it.get('title', '')} {it.get('description', '')}".upper()
            syms |= set(re.findall(r"\b([A-Z0-9]{2,20}USDT)\b", teks))
        c["del"], c["del_ts"] = sorted(syms), now
        _save(c)
    except Exception as ex:
        print("[WARN] pengumuman Bybit:", ex)
    return set(c.get("del", []))


# ---------------- 3. detektor guncangan ----------------
def guncang(btc1h):
    """BTC 1 jam: candle terakhir lebih dari 2,5 ATR atau gerak 3 jam lebih dari 3,5 ATR."""
    try:
        h, l, c = (btc1h[k].values.astype(float) for k in ("high", "low", "close"))
        if len(c) < 30:
            return None
        tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
        a = tr[-15:-1].mean()
        rng, g3 = h[-1] - l[-1], c[-1] - c[-4]
        if a > 0 and (rng > 2.5 * a or abs(g3) > 3.5 * a):
            pct = float((c[-1] / c[-4] - 1) * 100)
            return dict(arah="naik" if pct > 0 else "turun", pct=pct, x=float(max(rng, abs(g3)) / a))
    except Exception as ex:
        print("[WARN] detektor guncangan:", ex)
    return None
