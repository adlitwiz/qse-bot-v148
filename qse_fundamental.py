"""QSE v148 - FUNDAMENTAL DAN DERIVATIF untuk /cek.
  1. CoinGecko (gratis, tanpa key): market cap, peringkat, FDV, suplai beredar, jarak dari ATH, performa, kategori
  2. Bybit: funding, open interest 24 jam, rasio akun long dan short, volume, umur listing
Semua dibaca ulang paling cepat 6 jam sekali (cache). Kalau sumber gagal, bagian itu dilewati."""
import json
import os
import re
import time
import requests
from config import STATE_DIR, BYBIT_URL

CACHE = os.path.join(STATE_DIR, "fundamental.json")
CG = "https://api.coingecko.com/api/v3"
UA = {"User-Agent": "Mozilla/5.0 qse-bot", "accept": "application/json"}


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


def _base(sym):
    b = sym[:-4] if sym.endswith("USDT") else sym
    return re.sub(r"^(1000000|100000|10000|1000|100)", "", b)


def coingecko(sym):
    c = _load()
    k = "cg_" + sym
    if k in c and time.time() - c[k].get("_ts", 0) < 6 * 3600:
        return c[k]
    base = _base(sym)
    try:
        r = requests.get(f"{CG}/search", params={"query": base}, headers=UA, timeout=15).json()
        cand = [x for x in r.get("coins", []) if x.get("symbol", "").upper() == base.upper()]
        cand.sort(key=lambda x: x.get("market_cap_rank") or 10 ** 9)
        if not cand:
            return None
        cid = cand[0]["id"]
        d = requests.get(f"{CG}/coins/{cid}", headers=UA, timeout=15, params=dict(
            localization="false", tickers="false", market_data="true", community_data="false",
            developer_data="false", sparkline="false")).json()
        md = d.get("market_data") or {}
        usd = lambda x: (md.get(x) or {}).get("usd")
        out = dict(_ts=time.time(), nama=d.get("name", base), id=cid, rank=d.get("market_cap_rank"),
                   kategori=[x for x in (d.get("categories") or []) if x][:3],
                   mcap=usd("market_cap"), fdv=usd("fully_diluted_valuation"), vol=usd("total_volume"),
                   beredar=md.get("circulating_supply"), total=md.get("total_supply"), maks=md.get("max_supply"),
                   ath=usd("ath"), ath_pct=usd("ath_change_percentage"),
                   ath_tgl=((md.get("ath_date") or {}).get("usd") or "")[:10],
                   p7=md.get("price_change_percentage_7d"), p30=md.get("price_change_percentage_30d"),
                   p1y=md.get("price_change_percentage_1y"))
        c[k] = out
        _save(c)
        return out
    except Exception as ex:
        print("[WARN] coingecko:", ex)
        return c.get(k)


def derivatif(sym):
    out = {}
    try:
        t = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear", "symbol": sym},
                         timeout=10).json()["result"]["list"][0]
        out.update(funding=float(t.get("fundingRate") or 0) * 100, oi_usd=float(t.get("openInterestValue") or 0),
                   vol=float(t.get("turnover24h") or 0), p24=float(t.get("price24hPcnt") or 0) * 100)
    except Exception:
        pass
    try:
        r = requests.get(BYBIT_URL + "/v5/market/open-interest", timeout=10, params=dict(
            category="linear", symbol=sym, intervalTime="1h", limit=25)).json()["result"]["list"]
        oi = [float(x["openInterest"]) for x in sorted(r, key=lambda x: int(x["timestamp"]))]
        if len(oi) >= 25 and oi[0] > 0:
            out["oi_ch"] = (oi[-1] - oi[0]) / oi[0] * 100
    except Exception:
        pass
    try:
        r = requests.get(BYBIT_URL + "/v5/market/account-ratio", timeout=10, params=dict(
            category="linear", symbol=sym, period="1h", limit=1)).json()["result"]["list"]
        if r:
            out["long_pct"] = float(r[0]["buyRatio"]) * 100
    except Exception:
        pass
    try:
        r = requests.get(BYBIT_URL + "/v5/market/instruments-info", timeout=10,
                         params=dict(category="linear", symbol=sym)).json()["result"]["list"]
        if r and r[0].get("launchTime"):
            out["umur"] = (time.time() * 1000 - int(r[0]["launchTime"])) / 86400000
    except Exception:
        pass
    return out


def _uang(x):
    if x is None:
        return "-"
    for v, s in ((1e9, " miliar"), (1e6, " juta"), (1e3, " ribu")):
        if abs(x) >= v:
            return f"${x / v:,.1f}{s}"
    return f"${x:,.0f}"


def teks_fundamental(sym):
    """Baris fundamental yang mudah dibaca, plus satu kalimat ringkas untuk kesimpulan."""
    f = coingecko(sym)
    if not f:
        return ["Data fundamental belum tersedia untuk koin ini."], ""
    rows = []
    rk = f.get("rank")
    kelas = ("koin besar" if rk and rk <= 20 else "koin menengah" if rk and rk <= 100 else
             "koin kecil" if rk and rk <= 300 else "koin mikro, geraknya bisa sangat liar")
    rows.append(f"{f['nama']} | market cap {_uang(f.get('mcap'))}" + (f" (peringkat #{rk})" if rk else "") + f", {kelas}")
    if f.get("kategori"):
        rows.append("Kategori: " + ", ".join(f["kategori"]))
    pend = ""
    if f.get("beredar") and (f.get("maks") or f.get("total")):
        tot = f.get("maks") or f.get("total")
        pct = f["beredar"] / tot * 100 if tot else 0
        if pct:
            rows.append(f"Suplai beredar {pct:.0f}% dari total" +
                        (". Sisa suplai masih besar, pelepasan token bisa jadi tekanan jual jangka panjang" if pct < 50 else ""))
            if pct < 50:
                pend = "suplai beredar baru sebagian"
    if f.get("fdv") and f.get("mcap"):
        rasio = f["fdv"] / f["mcap"]
        if rasio > 1.5:
            rows.append(f"Nilai penuh (FDV) {rasio:.1f} kali market cap sekarang")
    if f.get("ath_pct") is not None:
        rows.append(f"Harga {abs(f['ath_pct']):.0f}% di bawah rekor tertinggi ({f.get('ath_tgl', '-')})")
    perf = [(n, f.get(k)) for n, k in (("7 hari", "p7"), ("30 hari", "p30"), ("1 tahun", "p1y")) if f.get(k) is not None]
    if perf:
        rows.append("Performa: " + " | ".join(f"{n} {v:+.1f}%" for n, v in perf))
    return rows, pend


def teks_derivatif(sym):
    d = derivatif(sym)
    if not d:
        return ["Data derivatif Bybit tidak bisa diambil."], ""
    rows, catatan = [], ""
    if "funding" in d:
        fr = d["funding"]
        if fr >= 0.03:
            arti = "tinggi, posisi LONG ramai dan rawan koreksi tajam"
            catatan = "funding tinggi, LONG ramai"
        elif fr <= -0.03:
            arti = "negatif dalam, posisi SHORT ramai dan rawan short squeeze"
            catatan = "funding negatif, SHORT ramai"
        else:
            arti = "normal"
        rows.append(f"Funding {fr:+.4f}% per 8 jam, {arti}")
    if "long_pct" in d:
        lp = d["long_pct"]
        rows.append(f"Akun LONG {lp:.0f}% vs SHORT {100 - lp:.0f}%" +
                    (". Mayoritas LONG, waspada kalau harga mulai turun" if lp >= 65 else
                     ". Mayoritas SHORT, bahan bakar untuk naik tajam" if lp <= 35 else ""))
    if "oi_ch" in d and "p24" in d:
        oi, pr = d["oi_ch"], d["p24"]
        if pr > 0 and oi > 0:
            arti = "kenaikan didukung posisi baru, tren lebih kuat"
        elif pr > 0:
            arti = "naik karena SHORT menutup posisi, dorongannya lebih lemah"
        elif oi > 0:
            arti = "ada tekanan jual baru"
        else:
            arti = "LONG sedang keluar dari pasar"
        rows.append(f"24 jam: harga {pr:+.1f}%, open interest {oi:+.1f}%, artinya {arti}")
    if "vol" in d:
        rows.append(f"Volume 24 jam {_uang(d['vol'])} | open interest {_uang(d.get('oi_usd'))}")
    if d.get("umur") is not None and d["umur"] < 120:
        rows.append(f"Baru listing di Bybit {d['umur']:.0f} hari lalu, gerak koin baru biasanya lebih liar")
    return rows, catatan
