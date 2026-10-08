"""QSE - LAPISAN MAKRO (filter risiko, BUKAN penentu arah).
  1. Yield US Treasury 10 tahun (FRED DGS10) dan indeks dolar luas (FRED DTWEXBGS), data harian gratis tanpa key
  2. Judul berita terbaru Cointelegraph dan Cryptonews (RSS), hanya untuk dibaca
Aturan: bila yield naik minimal 15 bp dalam 5 hari kerja DAN dolar naik minimal 0,5% dalam 5 hari kerja,
status TEKANAN MAKRO: lot LONG yang disarankan dipotong setengah dan muncul peringatan. Vonis DASBOR tidak diubah.
Ambang ini titik awal, belum terbukti. Matikan dengan QSE_MAKRO=0."""
import csv
import io
import json
import os
import re
import time
import requests
from config import STATE_DIR

CACHE = os.path.join(STATE_DIR, "makro.json")
AKTIF = os.environ.get("QSE_MAKRO", "1") == "1"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id="
RSS = (("Cointelegraph", "https://cointelegraph.com/rss"), ("Cryptonews", "https://cryptonews.com/news/feed/"))
UA = {"User-Agent": "Mozilla/5.0 qse-bot"}


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


def _fred(seri):
    r = requests.get(FRED + seri, headers=UA, timeout=20)
    rows = [x for x in csv.reader(io.StringIO(r.text))][1:]
    out = [(d, float(v)) for d, v in rows if v not in (".", "")]
    return out[-60:]


def status():
    """Kondisi makro terbaru. Cache 6 jam. Return dict atau None bila data gagal diambil."""
    if not AKTIF:
        return None
    c = _load()
    if time.time() - c.get("ts", 0) < 6 * 3600 and c.get("st"):
        return c["st"]
    try:
        y, d = _fred("DGS10"), _fred("DTWEXBGS")
        if len(y) < 6 or len(d) < 6:
            return c.get("st")
        y5 = (y[-1][1] - y[-6][1]) * 100
        d5 = (d[-1][1] / d[-6][1] - 1) * 100
        tekan = y5 >= 15 and d5 >= 0.5
        longgar = y5 <= -15 and d5 <= -0.5
        st = dict(yield10=y[-1][1], y5=y5, tgl_y=y[-1][0], dolar=d[-1][1], d5=d5, tgl_d=d[-1][0],
                  rezim="TEKANAN MAKRO" if tekan else "MAKRO LONGGAR" if longgar else "NETRAL")
        c.update(ts=time.time(), st=st)
        _save(c)
        return st
    except Exception as ex:
        print("[WARN] makro:", ex)
        return c.get("st")


def kali_lot(arah):
    """Pengali lot dari kondisi makro: LONG dipotong setengah saat TEKANAN MAKRO."""
    st = status()
    return 0.5 if st and st["rezim"] == "TEKANAN MAKRO" and arah == "LONG" else 1.0


def baris():
    st = status()
    if not st:
        return ""
    ikon = "⚠️ " if st["rezim"] == "TEKANAN MAKRO" else ""
    return (f"{ikon}Makro AS: yield 10Y {st['yield10']:.2f}% ({st['y5']:+.0f} bp 5 hari) | dolar {st['d5']:+.2f}% 5 hari | "
            f"{st['rezim']}" + (", lot LONG dipotong setengah" if st["rezim"] == "TEKANAN MAKRO" else ""))


def berita(n=4):
    """Judul berita terbaru dari Cointelegraph dan Cryptonews. Cache 1 jam."""
    if not AKTIF:
        return []
    c = _load()
    if time.time() - c.get("ts_b", 0) < 3600 and c.get("berita"):
        return c["berita"][:n]
    out = []
    for nama, url in RSS:
        try:
            x = requests.get(url, headers=UA, timeout=15).text
            for it in re.findall(r"<item>(.*?)</item>", x, re.S)[:3]:
                m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
                if m:
                    out.append(f"{nama}: {re.sub(r'<[^>]+>', '', m.group(1)).strip()}")
        except Exception as ex:
            print("[WARN] rss", nama, ex)
    if out:
        c.update(ts_b=time.time(), berita=out)
        _save(c)
    return out[:n]


KUNCI = {
    "Fed dan suku bunga": ("fed ", "fomc", "powell", "rate cut", "rate hike", "interest rate", "federal reserve"),
    "Yield dan dolar": ("yield", "treasury", "bond", "dollar", "dxy"),
    "Data ekonomi AS": ("cpi", "inflation", "jobs report", "nonfarm", "payroll", "pce", "gdp", "unemployment"),
    "ETF dan institusi": ("etf", "blackrock", "outflow", "inflow", "microstrategy", "strategy buys"),
    "Regulasi": ("sec ", "cftc", "regulat", "lawsuit", "ban ", "bill", "congress", "senate"),
    "Geopolitik": ("tariff", "war", "iran", "sanction", "china", "trump", "missile", "conflict"),
    "Risiko bursa dan stablecoin": ("hack", "exploit", "delist", "bankrupt", "depeg", "withdrawals halted", "tether", "usdc"),
    "Likuidasi": ("liquidat", "crash", "plunge", "dump"),
}


def berita_baru():
    """Berita baru berdampak besar (cocok kata kunci) sejak pengecekan sebelumnya. Tiap judul hanya dikirim sekali."""
    if not AKTIF:
        return []
    c = _load()
    sudah = set(c.get("kirim", []))
    awal = not sudah
    out = []
    for nama, url in RSS:
        try:
            x = requests.get(url, headers=UA, timeout=15).text
        except Exception as ex:
            print("[WARN] rss", nama, ex)
            continue
        for it in re.findall(r"<item>(.*?)</item>", x, re.S)[:15]:
            m = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
            ln = re.search(r"<link>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</link>", it, re.S)
            if not m:
                continue
            judul = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if judul in sudah:
                continue
            sudah.add(judul)
            low = " " + judul.lower() + " "
            kat = [k for k, kws in KUNCI.items() if any(w in low for w in kws)]
            if kat and not awal:
                out.append(dict(sumber=nama, judul=judul, link=(ln.group(1).strip() if ln else ""), kategori=kat))
    c["kirim"] = list(sudah)[-400:]
    _save(c)
    return out[:6]
