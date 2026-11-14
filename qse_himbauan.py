"""QC 100 🧭 HIMBAUAN BTC. Info duluan untuk posisi yang sedang jalan, bukan sinyal entry.
Tiap jam robot membaca data futures BTCUSDT Binance:
  rasio akun LONG/SHORT ritel (globalLongShortAccountRatio 5 menit) dan rata funding 3 hari (9 funding terakhir).
Himbauan dikirim saat kondisi BARU menyala (tepi naik), paling sering sekali per 24 jam per jenis:
  🔻 RAWAN DUMP: rasio L/S >= 2.29 (10% tertinggi latih). Posisi LONG yang untung minimal +0.5R ditutup, sisanya tahan.
  🔺 RAWAN PUMP: funding 3 hari <= 0.0011% (10% terendah latih). Posisi SHORT yang untung minimal +0.5R ditutup, sisanya tahan.
Riset v201/v202 (riset/upgrade/run_v202_himbauan.py, hasil_v202_himbauan.txt): ambang dipilih di latih Jul 2022-2024,
posisi siaran yang sedang jalan, aturan keluar live, biaya 0.15%, beda lawan tahan:
  RAWAN DUMP, LONG >= +0.5R ditutup: latih +19.1R, uji 2025-Okt 2026 +5.4R, 12 bulan +3.9R, 6 bulan +5.1R.
  RAWAN PUMP, SHORT >= +0.5R ditutup: latih +63.3R, uji +59.6R, 12 bulan +10.0R, 6 bulan +8.9R.
Ditolak (gagal salah satu periode): L/S rendah untuk SHORT, funding tinggi, OI naik + harga, pasokan stablecoin, ambang 5%.
Saklar QSE_HIMBAUAN=0 mati."""
import json
import os
import time

STATE_DIR = os.environ.get("QSE_STATE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"))
PATH = os.path.join(STATE_DIR, "himbauan.json")
LS_DUMP = 2.2928           # rasio akun L/S BTC, kuantil 90% latih
FUND_PUMP = 0.000011       # rata 9 funding terakhir, kuantil 10% latih (0.0011%)
AMBANG_R = 0.5
JEDA = 86400
JENIS = {
    "dump": dict(ikon="🔻", judul="BTC RAWAN DUMP", lawan="LONG",
                 sebab="Akun ritel yang LONG di BTC sangat ramai (rasio L/S {ls:.2f}, batas {b:.2f}).",
                 uji="Uji Jul 2022-Okt 2026: lebih baik dari tahan di latih, uji, 12 bulan, 6 bulan (+19R, +5R, +4R, +5R)."),
    "pump": dict(ikon="🔺", judul="BTC RAWAN PUMP", lawan="SHORT",
                 sebab="Funding BTC 3 hari sangat rendah ({f:.4f}%, batas {b:.4f}%). Banyak yang SHORT, rawan short squeeze.",
                 uji="Uji Jul 2022-Okt 2026: lebih baik dari tahan di latih, uji, 12 bulan, 6 bulan (+63R, +60R, +10R, +9R)."),
}


def hidup():
    return os.environ.get("QSE_HIMBAUAN", "1") != "0"


def _baca():
    try:
        with open(PATH) as f:
            return json.load(f)
    except Exception:
        return {"jam": 0, "nyala": {}, "kirim": {}, "data": {}}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(PATH + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(PATH + ".tmp", PATH)


def ambil():
    """Return (rasio L/S, rata funding 3 hari) BTCUSDT. Binance Futures dulu. Kalau Binance tidak terjangkau dari server:
    funding dari Bybit (biasanya hampir sama), rasio L/S None (himbauan dump dilewati karena ambang khusus data Binance)."""
    import requests
    ls = None
    try:
        j = requests.get("https://fapi.binance.com/futures/data/globalLongShortAccountRatio",
                         params=dict(symbol="BTCUSDT", period="5m", limit=1), timeout=8).json()
        ls = float(j[-1]["longShortRatio"])
    except Exception as ex:
        print("[WARN] himbauan L/S Binance", ex)
    fr = []
    try:
        f = requests.get("https://fapi.binance.com/fapi/v1/fundingRate", params=dict(symbol="BTCUSDT", limit=9), timeout=8).json()
        fr = [float(x["fundingRate"]) for x in f][-9:]
    except Exception:
        try:
            import config as CF
            f = requests.get(f"{CF.BYBIT_URL}/v5/market/funding/history", params=dict(category="linear", symbol="BTCUSDT", limit=9),
                             timeout=8).json()["result"]["list"]
            fr = [float(x["fundingRate"]) for x in f][:9]
        except Exception as ex:
            print("[WARN] himbauan funding", ex)
    f3 = sum(fr) / len(fr) if len(fr) == 9 else None
    if ls is None and f3 is None:
        raise ValueError("data L/S dan funding tidak terjangkau")
    return ls, f3


def kondisi(ls, f3):
    return {"dump": ls is not None and ls >= LS_DUMP, "pump": f3 is not None and f3 <= FUND_PUMP}


def baris_posisi(lawan, harga=None):
    """Baris per orang untuk posisi yang melawan himbauan."""
    import qse_saya as SY

    @SY.per_orang
    def _isi():
        d = SY._load()
        jalan = [it for it in d["open"].values() if it["status"] in ("TERISI", "TP1") and it["arah"] == lawan]
        hp = harga or SY.harga_live
        rows = []
        for it in jalan:
            px = hp(it["sym"])
            fl = SY.floating(it, px) if px else None
            kd = it["sym"].replace("USDT", "")
            if fl and fl["r"] >= AMBANG_R:
                rows.append(f"✅ <b>{it['sym']} {lawan}</b> untung {fl['r']:+.2f}R. <b>TUTUP sekarang</b> dengan MARKET, lalu /tutup {kd} HARGA")
            elif fl and fl["r"] > 0:
                rows.append(f"⏸️ <b>{it['sym']} {lawan}</b> untung kecil {fl['r']:+.2f}R. Tahan, SL tetap.")
            else:
                rows.append(f"⏸️ <b>{it['sym']} {lawan}</b> " + (f"minus {fl['r']:+.2f}R. " if fl else "") + "Tahan, biarkan SL bekerja.")
        return rows
    return _isi()


def pesan(jenis, ls, f3, harga=None):
    j = JENIS[jenis]
    sebab = j["sebab"].format(ls=ls or 0, f=(f3 or 0) * 100, b=LS_DUMP if jenis == "dump" else FUND_PUMP * 100)
    rows = [f"{j['ikon']} <b>HIMBAUAN: {j['judul']}</b>",
            sebab,
            f"Ini info duluan, bukan sinyal entry. Posisi <b>{j['lawan']}</b> yang untung minimal <b>+{AMBANG_R:g}R</b> ditutup sekarang "
            f"supaya profit tidak hilang. Untung kecil dan posisi minus ditahan dengan SL tetap.",
            f"🧪 {j['uji']}"]
    try:
        ps = baris_posisi(j["lawan"], harga)
    except Exception as ex:
        print("[WARN] himbauan posisi", ex)
        ps = []
    rows.append("\n".join(ps) if ps else f"Tidak ada posisi {j['lawan']} jalan yang tercatat.")
    return "\n\n".join(rows)


def cek(now=None, data=None, harga=None):
    """Dipanggil tiap menit, membaca data sekali per jam (menit ke-1 atau lebih). data = (ls, f3) untuk tes. Return list jenis terkirim."""
    if not hidup():
        return []
    now = now or time.time()
    d = _baca()
    jam = int(now // 3600)
    if data is None and (d.get("jam") == jam or now % 3600 < 60):
        return []
    d["jam"] = jam
    try:
        ls, f3 = data if data is not None else ambil()
    except Exception as ex:
        print("[WARN] himbauan ambil", ex)
        _tulis(d)
        return []
    d["data"] = dict(ls=ls, f3=f3, t=now)
    awal = not d.get("nyala")
    k = kondisi(ls, f3)
    out = []
    for jenis, on in k.items():
        dulu = d["nyala"].get(jenis, False)
        d["nyala"][jenis] = on
        if awal or not on or dulu or now - d["kirim"].get(jenis, 0) < JEDA:
            continue
        d["kirim"][jenis] = now
        try:
            import telegram_notify as TG
            TG.send(["🧭 <b>QSE v150 | HIMBAUAN BTC</b>\n\n" + pesan(jenis, ls, f3, harga)])
        except Exception as ex:
            print("[WARN] himbauan kirim", ex)
        out.append(jenis)
        print(f"[HIMBAUAN] {jenis} ls {ls} f3 {f3}", flush=True)
    _tulis(d)
    return out


def rapor():
    d = _baca()
    x = d.get("data") or {}
    rows = ["🧭 <b>HIMBAUAN BTC</b> (info duluan untuk posisi jalan, bukan sinyal entry)"]
    if x:
        ls, f3 = x["ls"], x["f3"]
        k = kondisi(ls, f3)
        rows.append(f"Rasio akun L/S BTC {ls:.2f} (rawan dump kalau >= {LS_DUMP:.2f}): {'🔻 MENYALA' if k['dump'] else 'aman'}" if ls is not None
                    else "Rasio akun L/S BTC: Binance tidak terjangkau dari server, himbauan dump tidak aktif.")
        rows.append(f"Funding BTC rata 3 hari {f3 * 100:.4f}% (rawan pump kalau <= {FUND_PUMP * 100:.4f}%): {'🔺 MENYALA' if k['pump'] else 'aman'}"
                    if f3 is not None else "Funding BTC: data tidak terjangkau.")
        rows.append(f"Data {time.strftime('%d %b %H:%M', time.gmtime(x['t'] + 7 * 3600))} WIB.")
    else:
        rows.append("Belum ada data. Robot membaca Binance tiap jam.")
    rows.append("Himbauan dikirim saat kondisi baru menyala, paling sering sekali per 24 jam. "
                "Aksi teruji: tutup posisi yang melawan himbauan kalau untung minimal +0.5R, sisanya tahan.")
    return "\n".join(rows)
