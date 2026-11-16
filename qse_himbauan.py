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


# QC 104 PERUBAHAN ARAH BTC 4J (riset/upgrade/run_v206_balik_arah.py, hasil_v206_balik_arah.txt). Posisi siaran yang sedang jalan,
# aturan keluar live, biaya 0.15%, beda lawan tahan, kejadian baru (tepi naik), jeda 24 jam:
#   BTC 4J tutup lebih dari 0.5% di BAWAH EMA 50, posisi LONG untung >= +0.3R ditutup: latih +39.2R, uji +64.9R, 12 bln +7.2R, 6 bln +5.6R.
#   EMA 20 memotong ke ATAS EMA 50 di BTC 4J, posisi SHORT untung >= +0.3R ditutup : latih +14.0R, uji +21.0R, 12 bln +24.4R, 6 bln +12.8R.
# DITOLAK: cutloss posisi minus saat arah berubah (semua varian gagal minimal satu periode), menutup SHORT saat BTC naik di atas EMA 50
# (-90R sampai -233R), EMA 20 potong ke bawah untuk LONG (6 bln -0.7R), BTC gerak 3% dalam 12 jam, batas 1% dari EMA 50.
BALIK_JARAK = 0.5
BALIK_R = 0.3
JENIS.update({
    "balik_turun": dict(ikon="📉", judul="ARAH BTC BERUBAH TURUN", lawan="LONG", amb=BALIK_R,
                        sebab="BTC 4 jam baru saja tutup {jr:+.2f}% dari EMA 50 (lewat batas -0.5%). Sisi BTC pindah ke bawah.",
                        uji="Uji Jul 2022-Okt 2026: lebih baik dari tahan di latih, uji, 12 bulan, 6 bulan (+39R, +65R, +7R, +6R). "
                            "Cutloss posisi minus di saat ini TIDAK terbukti, jadi yang minus ditahan."),
    "balik_naik": dict(ikon="📈", judul="ARAH BTC BERUBAH NAIK", lawan="SHORT", amb=BALIK_R,
                       sebab="EMA 20 baru saja memotong ke atas EMA 50 di BTC 4 jam (BTC {jr:+.2f}% dari EMA 50). Tren pendek berbalik naik.",
                       uji="Uji Jul 2022-Okt 2026: lebih baik dari tahan di latih, uji, 12 bulan, 6 bulan (+14R, +21R, +24R, +13R). "
                           "Cutloss posisi minus di saat ini TIDAK terbukti, jadi yang minus ditahan."),
})


def _ema(x, n):
    k = 2 / (n + 1)
    o = [float(x[0])]
    for v in x[1:]:
        o.append(o[-1] + k * (float(v) - o[-1]))
    return o


def kondisi4j(c):
    """c = close candle 4J BTC yang sudah tutup. Return (dict jenis -> (nyala sekarang, nyala candle sebelumnya), jarak % ke EMA 50)."""
    e50, e20 = _ema(c, 50), _ema(c, 20)
    jr = [(float(c[i]) / e50[i] - 1) * 100 for i in (-2, -1)]
    return {"balik_turun": (jr[1] < -BALIK_JARAK, jr[0] < -BALIK_JARAK),
            "balik_naik": (e20[-1] > e50[-1], e20[-2] > e50[-2])}, jr[1]


def cek4j(now=None, df=None, harga=None):
    """Sekali tiap candle 4J BTC baru tutup. df = (list ts ms, list close) untuk tes. Return list jenis terkirim."""
    if not hidup() or os.environ.get("QSE_BALIK", "1") == "0":
        return []
    now = now or time.time()
    d = _baca()
    if df is None and (now % 14400 < 90 or d.get("c4") == int(now // 14400)):
        return []
    try:
        if df is None:
            import qse_strat as ST
            x = ST._k4("BTCUSDT", 400)
            ts, c = [int(v) for v in x.index], [float(v) for v in x["close"].values]
        else:
            ts, c = df
        if len(c) < 120:
            return []
    except Exception as ex:
        print("[WARN] himbauan 4j", ex)
        return []
    d["c4"] = int(now // 14400)
    if d.get("c4_ts") == ts[-1]:
        _tulis(d)
        return []
    awal = d.get("c4_ts") is None
    d["c4_ts"] = ts[-1]
    k, jr = kondisi4j(c)
    d["jr"] = jr
    out = []
    d.setdefault("kirim", {})
    for jenis, (on, dulu) in k.items():
        if awal or not on or dulu or now - d["kirim"].get(jenis, 0) < JEDA:
            continue
        d["kirim"][jenis] = now
        try:
            import telegram_notify as TG
            TG.send(["🧭 <b>QSE v150 | PERUBAHAN ARAH</b>\n\n" + pesan(jenis, None, None, harga, jr=jr)])
        except Exception as ex:
            print("[WARN] himbauan kirim", ex)
        out.append(jenis)
        print(f"[HIMBAUAN] {jenis} BTC {jr:+.2f}% dari EMA 50", flush=True)
    _tulis(d)
    return out


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
    LS_AKTIF.update(amb=LS_DUMP, sumber="Binance")
    if ls is None:          # QC 104b cadangan Bybit: rasio akun 4 jam, ambang = kuantil 90% dari 500 titik (83 hari) sebelumnya
        try:
            import config as CF
            rows = requests.get(f"{CF.BYBIT_URL}/v5/market/account-ratio",
                                params=dict(category="linear", symbol="BTCUSDT", period="4h", limit=500), timeout=8).json()["result"]["list"]
            rows = sorted(rows, key=lambda z: int(z["timestamp"]))
            r = [float(z["buyRatio"]) / max(float(z["sellRatio"]), 1e-9) for z in rows]
            amb = ambang_gulir(r[:-1])
            if amb is not None:
                ls = r[-1]
                LS_AKTIF.update(amb=amb, sumber="Bybit")
        except Exception as ex:
            print("[WARN] himbauan L/S Bybit", ex)
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


# QC 104b: saat Binance tidak terjangkau dari server, rasio L/S memakai Bybit dengan ambang bergulir. Uji ambang bergulir di data
# Binance (riset/upgrade/run_v208_ls_gulir.py, hasil_v208_ls_gulir.txt), LONG untung >= +0.5R ditutup, beda lawan tahan:
#   kuantil 90% dari 500 titik 4 jam: latih +10.8R, uji +11.7R, 12 bulan +3.1R, 6 bulan +3.1R (60 dan 83 hari per jam juga lolos,
#   30 hari gagal di latih). Catatan: diuji di data Binance, kerumunan Bybit bisa berbeda, jadi ini cadangan, bukan sumber utama.
LS_AKTIF = {"amb": LS_DUMP, "sumber": "Binance"}


def ambang_gulir(riw, q=0.9, minimal=250):
    """Kuantil q dari riwayat rasio (tanpa titik sekarang). None kalau riwayat kurang dari minimal."""
    x = sorted(float(v) for v in riw)
    if len(x) < minimal:
        return None
    pos = q * (len(x) - 1)
    i = int(pos)
    return x[i] + (x[min(i + 1, len(x) - 1)] - x[i]) * (pos - i)


def kondisi(ls, f3, amb=None):
    amb = LS_AKTIF["amb"] if amb is None else amb
    return {"dump": ls is not None and ls >= amb, "pump": f3 is not None and f3 <= FUND_PUMP}


def baris_posisi(lawan, harga=None, amb=None):
    """Baris per orang untuk posisi yang melawan himbauan."""
    amb = AMBANG_R if amb is None else amb
    import qse_saya as SY

    @SY.per_orang
    def _isi_himbauan():
        d = SY._load()
        jalan = [it for it in d["open"].values() if it["status"] in ("TERISI", "TP1") and it["arah"] == lawan]
        hp = harga or SY.harga_live
        rows = []
        for it in jalan:
            px = hp(it["sym"])
            fl = SY.floating(it, px) if px else None
            kd = it["sym"].replace("USDT", "")
            if fl and fl["r"] >= amb:
                rows.append(f"✅ <b>{it['sym']} {lawan}</b> untung {fl['r']:+.2f}R. <b>TUTUP sekarang</b> dengan MARKET, lalu /tutup {kd} HARGA")
            elif fl and fl["r"] > 0:
                rows.append(f"⏸️ <b>{it['sym']} {lawan}</b> untung kecil {fl['r']:+.2f}R. Tahan, SL tetap.")
            else:
                rows.append(f"⏸️ <b>{it['sym']} {lawan}</b> " + (f"minus {fl['r']:+.2f}R. " if fl else "") + "Tahan, biarkan SL bekerja.")
        return rows
    return _isi_himbauan()


def pesan(jenis, ls, f3, harga=None, jr=0.0):
    j = JENIS[jenis]
    amb = j.get("amb", AMBANG_R)
    sebab = j["sebab"].format(ls=ls or 0, f=(f3 or 0) * 100, b=LS_AKTIF["amb"] if jenis == "dump" else FUND_PUMP * 100, jr=jr or 0)
    rows = [f"{j['ikon']} <b>HIMBAUAN: {j['judul']}</b>",
            sebab,
            f"Ini info duluan, bukan sinyal entry. Posisi <b>{j['lawan']}</b> yang untung minimal <b>+{amb:g}R</b> ditutup sekarang "
            f"supaya profit tidak hilang. Untung kecil dan posisi minus ditahan dengan SL tetap.",
            f"🧪 {j['uji']}"]
    try:
        ps = baris_posisi(j["lawan"], harga, amb)
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
    d["data"] = dict(ls=ls, f3=f3, t=now, amb=LS_AKTIF["amb"], sumber=LS_AKTIF["sumber"])
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
        amb = x.get("amb") or LS_DUMP
        k = kondisi(ls, f3, amb)
        rows.append(f"Rasio akun L/S BTC {ls:.2f} dari {x.get('sumber') or 'Binance'} (rawan dump kalau >= {amb:.2f}"
                    + (", ambang 10% teratas 83 hari" if x.get("sumber") == "Bybit" else "") + f"): {'🔻 MENYALA' if k['dump'] else 'aman'}"
                    if ls is not None else "Rasio akun L/S BTC: Binance dan Bybit tidak terjangkau dari server, himbauan dump tidak aktif.")
        rows.append(f"Funding BTC rata 3 hari {f3 * 100:.4f}% (rawan pump kalau <= {FUND_PUMP * 100:.4f}%): {'🔺 MENYALA' if k['pump'] else 'aman'}"
                    if f3 is not None else "Funding BTC: data tidak terjangkau.")
        rows.append(f"Data {time.strftime('%d %b %H:%M', time.gmtime(x['t'] + 7 * 3600))} WIB.")
    else:
        rows.append("Belum ada data. Robot membaca Binance tiap jam.")
    if d.get("jr") is not None:
        rows.append(f"BTC 4 jam {d['jr']:+.2f}% dari EMA 50. Kabar PERUBAHAN ARAH dikirim saat BTC baru tutup lebih dari 0.5% di bawah EMA 50 "
                    "(LONG untung >= +0.3R ditutup) atau EMA 20 baru memotong ke atas EMA 50 (SHORT untung >= +0.3R ditutup).")
    rows.append("Himbauan dikirim saat kondisi baru menyala, paling sering sekali per 24 jam, dan pemilik posisi di-tag. "
                "Aksi teruji: tutup posisi yang melawan himbauan kalau untungnya cukup, sisanya tahan. Cutloss posisi minus tidak terbukti.")
    return "\n".join(rows)
