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


def _skor_ket(ket):
    """Ambil angka skor dari keterangan catatan jalur, contoh 'skor 72, 15 menit'."""
    import re
    m = re.search(r"skor (\d+)", ket or "")
    return int(m.group(1)) if m else None


def asal_saran(sym, arah, harga, r=None):
    """Dari saran mana entry ini dan berapa skor setup saran itu.
    Urutan cek: saran utama di scan terakhir, catatan saran robot (utama, 1J, cadangan, fib, siklus),
    jalur momentum dan news, Ichimoku, lalu Golden Zone Hunter. Return dict(jalur, pola, skor)."""
    r = r or hasil_robot(sym)
    a = (r or {}).get("atr") or 0
    rb = ramal_btc4()
    pu = rb["p_up"] if rb else None
    dekat = lambda e, k: e is not None and (not a or abs(e - harga) <= k * a)
    try:
        import qse_fixprofit as FX
        for it in sorted(FX.load()["open"].values(), key=lambda v: -(v.get("sent_ts") or 0)):
            if it["sym"] == sym and it["arah"] == arah and dekat(it["entry"], 1.0):
                j = ("saran trendline" if it.get("tt") else "saran cadangan" if it.get("cadangan") else "saran siklus" if it.get("siklus")
                     else "saran cadangan 2" if it.get("cad2") else "saran fib" if it.get("fib")
                     else "saran 1J" if it.get("tf") == "60" else "saran utama")
                sk = it.get("skor")
                if sk is None and r:
                    s = next((x for x in r["saran"] if x["pola"] == it["pola"] and x["arah"] == arah), None)
                    sk = skor_setup(r, s, pu) if s else None
                return dict(jalur=j, pola=it["pola"], skor=sk)
    except Exception:
        pass
    if r and a:
        for s in r["saran"]:
            if s["arah"] == arah and s["eksekusi"] and dekat(s["entry"], 0.5):
                return dict(jalur="saran utama", pola=s["pola"], skor=skor_setup(r, s, pu))
    try:
        import qse_catat as CT
        for it in sorted(CT._baca()["open"], key=lambda v: -v.get("t", 0)):
            if it["sym"] == sym and it["arah"] == arah and dekat(it["entry"], 1.0):
                j = "saran momentum" if it["jalur"] == "momentum" else "saran news" if it["jalur"].startswith("news") \
                    else "saran " + it["jalur"]
                return dict(jalur=j, pola=CT.NAMA.get(it["jalur"], it["jalur"]), skor=_skor_ket(it.get("ket")))
    except Exception:
        pass
    try:
        import qse_ichimoku as IC
        for it in IC.lihat()["open"].values():
            if it["sym"] == sym and it["arah"] == arah:
                return dict(jalur="saran ichimoku", pola="Ichimoku TK Awan Trail", skor=None)
    except Exception:
        pass
    try:
        import qse_ob as OB
        for it in OB.lihat()["open"].values():
            if it["sym"] == sym and arah == "LONG":
                return dict(jalur="saran orderblock", pola="Order Block + Volume", skor=None)
    except Exception:
        pass
    try:
        import qse_strat as ST
        for k, cfg in ST.STRAT.items():
            for it in ST.lihat(k)["open"].values():
                if it["sym"] == sym and it["arah"] == arah:
                    return dict(jalur="saran " + k, pola=cfg["nama"], skor=None)
    except Exception:
        pass
    try:
        with open(os.path.join(STATE_DIR, "sentuh_fib.json")) as f:
            g = json.load(f).get("sinyal", {}).get(sym)
        if g and g["arah"] == arah and time.time() - g["t"] <= 2 * 86400 and dekat(g["entry"], 1.0):
            return dict(jalur="saran GZH", pola="Golden Zone Hunter", skor=g.get("skor"))
    except Exception:
        pass
    return dict(jalur="manual", pola="manual", skor=None)


def posisi_koin(sym):
    """Posisi atau order kamu (/entry) di koin ini."""
    return [dict(asal="trade kamu", arah=it["arah"], status=it["status"], entry=it["entry"], sl=it["sl"],
                 tp1=it["tp1"], tp2=it["tp2"]) for it in _load()["open"].values() if it["sym"] == sym]


NM_ST = {"MENUNGGU": "order belum terisi", "TERISI": "posisi jalan", "TP1": "sudah TP1, SL di entry"}


# ---------------- skor setup dan ramalan BTC 4 jam (satu sumber untuk robot, /entry, dan /status) ----------------
def skor_setup(r, s, p_up=None):
    """Skor setup 0-100, rumus yang sama dengan urutan sinyal robot: WR pola (batas bawah Wilson), rapor, mutu,
    peluang terisi, ramalan BTC 4 jam, ramalan arah koin, dan golden moment."""
    n = s.get("win", 0) + s.get("loss", 0)
    p = s["win"] / n if n else 0.0
    wil = ((p + 1.9208 / n - 1.96 * ((p * (1 - p) + 0.9604 / n) / n) ** 0.5) / (1 + 3.8416 / n)) if n else 0.0
    sk = max(0.0, wil) * 35
    sk += 15 if r.get("rapor") == "A" else 9
    sk += 12 if s.get("mutu") == "A" else 6
    sk += 10 * min(100.0, s.get("p_isi") or 0) / 100
    if p_up is not None:
        up = p_up if s["arah"] == "LONG" else 100 - p_up
        sk += 10 if up >= 55 else 5 if up > 45 else 0
    sk += max(0.0, min(10.0, (s.get("p_arah", 50) - 50) * 0.5))
    sk += 8 if s.get("golden") else 0
    return int(round(min(100.0, sk)))


RB_BARS = 3200          # 3000 candle sejarah + 200 candle pemanasan EMA
_RB4 = {}


def _ramal(df):
    import numpy as np
    import qse_ta as T
    df = df.iloc[-RB_BARS:]
    c = df["close"].values.astype(float)
    h, l = df["high"].values.astype(float), df["low"].values.astype(float)
    if len(c) < 300:
        return None
    e20, e50 = T.ema(c, 20), T.ema(c, 50)
    st = np.where((c > e20) & (e20 > e50), 1, np.where((c < e20) & (e20 < e50), -1, 0))
    mom = np.r_[False, c[1:] > c[:-1]]
    L = len(c) - 1
    up = c[1:] > c[:-1]
    lo = max(0, L - 3000)
    sel = (st[lo:L] == st[L]) & (mom[lo:L] == mom[L])
    if sel.sum() < 60:
        sel = st[lo:L] == st[L]
    p = float(up[lo:L][sel].mean() * 100) if sel.sum() else 50.0
    a = float(T.atr(h, l, c, 14)[L])
    return dict(p_up=p, n=int(sel.sum()), atr=a, atr_pct=a / c[L] * 100)


def ramal_btc4(df=None):
    """Peluang candle BTC 4J berikutnya naik (%) dari sejarah kondisi tren dan momentum yang sama.
    df = candle BTC 4J yang sudah tutup (dari scan). Tanpa df: ambil sendiri, hasil disimpan 10 menit."""
    if df is None:
        if time.time() - _RB4.get("t", 0) < 600:
            return _RB4.get("v")
        _RB4["t"] = time.time()          # gagal pun ditunggu 10 menit, supaya loop tidak mengulang ambil data
        try:
            import bybit_fetch as B
            df = B.get_klines("BTCUSDT", "240", RB_BARS, closed_only=True, cache=False)
        except Exception as ex:
            print("[WARN] ramalan BTC 4J:", ex)
            return _RB4.get("v")
    try:
        v = _ramal(df)
    except Exception as ex:
        print("[WARN] ramalan BTC 4J:", ex)
        return _RB4.get("v")
    _RB4.update(t=time.time(), v=v)
    return v


def btc_melawan(arah):
    """Alasan BTC 1 jam melawan arah ini. Dipakai gerbang sinyal, /entry, GZH, dan /status.
    Ramalan BTC 4 jam TIDAK dipakai sebagai penghalang: diuji di 112 koin 2022-2026 (36 kombinasi teknik),
    menahan sinyal saat ramalan melawan selalu menurunkan PF (rata -0.07). BTC 1 jam searah menaikkan PF di 70% kombinasi.
    Return list teks pendek. Kosong = tidak melawan."""
    naik, ch3 = btc_1j()
    if naik is not None and naik != (arah == "LONG"):
        return [f"BTC 1 jam {'naik' if naik else 'turun'} ({ch3:+.1f}% 3 jam)"]
    return []


def kelas_setup(arah, skor=None, wr=None, rr2=None, rapor=None, golden=False, longgar=False, tambahan=None, jalur=None):
    """Satu label untuk tiap saran sebelum entry: WAJIB ENTRY, AMAN BANGET, HIGH RISK HIGH RETURN, atau BERISIKO.
    Return (label, ikon, alasan, lot)."""
    risiko = []
    if longgar:
        risiko.append("sinyal longgar")
    risiko += btc_melawan(arah)
    bd = berita_depan(3)
    if bd:
        risiko.append(f"berita besar {bd['judul']} dalam 3 jam")
    if rapor and rapor not in ("A", "B", "A+"):
        risiko.append(f"rapor robot {rapor}")
    if skor is not None and skor < 55 and jalur != "saran utama":
        risiko.append("setup lemah")          # saran 4J: uji 5 tahun, skor 55 ke bawah justru lebih baik
    risiko += tambahan or []
    if risiko:
        return "BERISIKO", "🟠", "; ".join(risiko), "0.25x sampai 0.5x lot, atau lewati"
    if wr is not None and wr < 45 and (rr2 or 0) >= 2:
        return ("HIGH RISK HIGH RETURN", "🎲", f"WR sekitar {wr:.0f}%, target sampai {rr2:.1f}R, sering rugi kecil dan sesekali untung besar",
                "1x lot, siap rugi beruntun" if jalur and tingkat_bukti(jalur, arah, skor)[0].startswith("TERBUKTI")
                else "0.5x lot, siap rugi beruntun")
    if jalur and tingkat_bukti(jalur, arah, skor)[0] != "TERBUKTI" and (skor or 0) >= 60:
        # uji 5 tahun 108 koin: label AMAN BANGET lama di saran 4J WR 22%, skor tinggi tidak menjamin menang
        return ("BERISIKO", "🟠", "jalur ini belum terbukti di backtest",
                tingkat_bukti(jalur, arah, skor)[2])
    if (skor or 0) >= 70 and (rapor in ("A", "A+") or golden) and (wr or 0) >= 55:
        return ("WAJIB ENTRY", "🔥", f"skor {skor}, rapor {rapor}{', golden moment' if golden else ''}, WR pola {wr:.0f}%, "
                f"BTC dan berita aman", "1x lot normal, tetap pasang SL")
    if (skor or 0) >= 60 and (wr or 0) >= 50:
        return ("AMAN BANGET", "🛡️", f"skor {skor}, WR pola {wr:.0f}%, BTC dan berita aman", "1x lot normal")
    return "BERISIKO", "🟠", "skor atau WR pola belum cukup tinggi", "0.5x lot"


_KTX = {}
_SIK = {}
HALVING = [(2012, 11, 28), (2016, 7, 9), (2020, 5, 11), (2024, 4, 20)]


def siklus_btc():
    """Posisi BTC di siklus 4 tahunan halving. Patokan 3 siklus lalu: puncak 370 sampai 550 hari setelah halving,
    dasar bear 770 sampai 915 hari setelah halving. Info saja, sampelnya hanya 3 siklus. Disimpan 6 jam."""
    if time.time() - _SIK.get("t", 0) < 6 * 3600 and _SIK.get("v"):
        return _SIK["v"]
    import calendar
    h = calendar.timegm(HALVING[-1] + (0, 0, 0))
    hari = int((time.time() - h) // 86400)
    if hari < 180:
        fase = "awal bull setelah halving"
    elif hari < 550:
        fase = "bull utama (puncak siklus lalu 370 sampai 550 hari setelah halving)"
    elif hari < 770:
        fase = "bear setelah puncak"
    elif hari < 950:
        fase = "zona dasar bear (dasar siklus lalu 770 sampai 915 hari setelah halving)"
    else:
        fase = "akumulasi menjelang halving berikutnya (perkiraan 2028)"
    teks = f"Siklus BTC: hari ke-{hari} setelah halving April 2024, fase historis {fase}"
    try:
        w = _kline("BTCUSDT", "W", 400)
        cl = [x[3] for x in w]
        if len(cl) >= 200:
            ma = sum(cl[-200:]) / 200
            ath = max(x[1] for x in w)
            teks += (f" | harga {(cl[-1] / ath - 1) * 100:+.0f}% dari puncak | "
                     f"{'di atas' if cl[-1] > ma else 'di bawah'} rata-rata 200 minggu")
    except Exception:
        pass
    _SIK.update(t=time.time(), v=teks)
    return teks


def _tren4j(sym):
    k = _kline(sym, "240", 80)
    cls = [x[3] for x in k[:-1]]
    if len(cls) < 55:
        return "-"
    e20, e50 = _ema(cls[-60:], 20), _ema(cls[-60:], 50)
    return "naik" if cls[-1] > e20 > e50 else "turun" if cls[-1] < e20 < e50 else "campur"


def baris_konteks():
    """Satu baris kondisi pasar sebelum tiap saran: arah BTC (1 jam dan 4 jam), arah altcoin dibanding BTC 24 jam,
    dan arah berita (berita penting 6 jam terakhir dan berita besar USD 3 jam ke depan). Disimpan 5 menit."""
    if time.time() - _KTX.get("t", 0) < 300:
        return _KTX["v"]
    naik, ch3 = btc_1j()
    try:
        b4 = _tren4j("BTCUSDT")
    except Exception:
        b4 = "-"
    btc = f"BTC 1J {'-' if naik is None else 'naik' if naik else 'turun'} ({ch3:+.1f}% 3 jam), 4J {b4}"
    alt = "Altcoin -"
    try:
        r = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear"}, timeout=15).json()
        lst = [x for x in r["result"]["list"] if x["symbol"].endswith("USDT")]
        bt = next(float(x["price24hPcnt"]) * 100 for x in lst if x["symbol"] == "BTCUSDT")
        top = sorted((x for x in lst if x["symbol"] not in ("BTCUSDT", "USDCUSDT")),
                     key=lambda x: -float(x.get("turnover24h") or 0))[:50]
        ch = sorted(float(x["price24hPcnt"]) * 100 for x in top)
        med = ch[len(ch) // 2]
        naik_n = sum(1 for v in ch if v > 0)
        sifat = "lebih kuat dari BTC" if med > bt + 1 else "lebih lemah dari BTC" if med < bt - 1 else "searah BTC"
        alt = f"Altcoin {sifat} (50 alt teratas median {med:+.1f}% 24 jam, {naik_n}/50 naik, BTC {bt:+.1f}%)"
    except Exception:
        pass
    news = "Berita: tidak ada berita penting 6 jam terakhir"
    try:
        with open(os.path.join(STATE_DIR, "news.json")) as f:
            tr = [x for x in json.load(f).get("terakhir", []) if time.time() - x["t"] < 6 * 3600]
        if tr:
            p = sum(1 for x in tr if x["arah"] == "LONG")
            news = (f"Berita 6 jam terakhir: {p} positif, {len(tr) - p} negatif, condong "
                    + ("LONG" if p > len(tr) - p else "SHORT" if p < len(tr) - p else "campur"))
    except Exception:
        pass
    bd = berita_depan(3)
    if bd:
        news += f" | berita besar USD {bd['judul']} dalam 3 jam"
    import html
    v = "🌐 " + html.escape(f"{btc} | {alt} | {news}") + "\n🔄 " + html.escape(siklus_btc())
    _KTX.update(t=time.time(), v=v)
    return v


def blok_salin(entry, sl, tp1=None, tp2=None, order="", tick=None, catatan_tp="", sym=None, arah=None):
    """Blok level yang sama untuk semua sinyal. Tekan lama untuk salin, lalu tempel setelah /entry untuk dicatat."""
    t = tick or tick_of(None, entry)
    risk = abs(entry - sl) or 1e-12
    pc = lambda x: abs(x - entry) / entry * 100
    rows = ([f"{sym} {arah}".strip()] if sym else []) + [f"Entry {fp(entry, t)}" + (f" {order}" if order else ""), f"SL    {fp(sl, t)}  -1.00R  -{pc(sl):.1f}%"]
    for nm, v in ((("TP", tp1),) if tp1 and tp1 == tp2 else (("TP1", tp1), ("TP2", tp2))):
        if v:
            rows.append(f"{nm:<5} {fp(v, t)}  +{abs(v - entry) / risk:.2f}R  +{pc(v):.1f}%")
    if catatan_tp:
        rows.append(f"TP    {catatan_tp}")
    return "<pre>" + "\n".join(rows) + "</pre>"


def baris_kelas(arah, konteks=True, **kw):
    lb, ik, why, lot = kelas_setup(arah, **kw)
    import html
    out = (f"{baris_konteks()}\n" if konteks else "") + f"{ik} <b>PENILAIAN: {lb}</b> | {html.escape(why)} | lot {lot}"
    if kw.get("jalur"):
        out += "\n" + baris_bukti(kw["jalur"], arah, kw.get("skor"))
    return out


# ---------------- tanda bukti tiap jalur (hasil backtest dengan aturan robot) ----------------
# Ichimoku: aturan qse_ichimoku persis, 30 koin perp + funding, Jul 2021 - Sep 2026, batas 8 posisi.
# Saran 4J: mesin dijalankan ulang tiap candle 4J + saringan fix profit + gerbang robot, 108 koin perp, Jul 2021 - Okt 2026.
BUKTI = {
    "saran ichimoku": ("TERBUKTI", "✅", "1x", "backtest 5 tahun 111 koin perp, 20 koin paling likuid: 3084 trade, PF 1.29, "
                       "untung tiap tahun, positif 18 dari 22 kuartal. Sejak 19 Okt 2026 SL 1.5 ATR, trailing 4 ATR: rasio untung/drawdown 5.0 ke 5.9"),
    "saran utama": ("BELUM TERBUKTI", "⚠️", "0.25x", "backtest 5 tahun 108 koin dengan semua syarat robot: 83 trade, PF 0.70; "
                    "2 tahun terakhir 30 koin termasuk sinyal longgar: 30 trade, PF 1.88, 29 di antaranya SHORT"),
    "saran GZH": ("TERBUKTI", "✅", "0.5x", "uji 6 tahun 111 koin, maks 8 posisi: 1825 trade, WR 40%, PF 1.24, aturan dipilih "
                  "dari 2020-2023 (PF 1.24), uji ulang 2024-2026 PF 1.23, turun terdalam 14%. Syarat: searah EMA 200 dan BTC 4J, "
                  "keluar dengan SL berjalan 3 ATR. GZH tanpa syarat PF 0.95, TP tetap 3R gagal di 2024-2026 (PF 0.96). "
                  "Lot 0.5x karena paling lemah di antara jalur terbukti"),
    "saran 1J": ("BELUM TERBUKTI", "⚠️", "0.25x", "uji 2 tahun 30 koin aturan robot (rapor 4J dan 1J A/B, searah bias 4J): "
                 "17 trade, WR 41%, -6.8R. Angka uji mundur 6 bulan di laporan memakai koin yang rapornya sedang bagus, jadi terlalu optimis"),
    "saran cadangan": ("BELUM TERBUKTI", "⚠️", "0.25x", "uji 2 tahun 30 koin aturan robot: 8 trade, WR 38%, PF 0.52, -2.4R"),
    "saran fib": ("BELUM TERBUKTI", "⚠️", "0.25x", "uji 2 tahun 30 koin aturan robot: 6 trade, WR 33%, PF 0.77, -0.9R"),
    "saran siklus": ("JARANG", "❔", "0.25x", "uji 2 tahun 30 koin: tidak ada sinyal yang lolos semua syarat"),
    "saran cadangan 2": ("JARANG", "❔", "0.25x", "uji 2 tahun 30 koin: tidak ada sinyal yang lolos semua syarat"),
    "saran trendline": ("TERBUKTI", "✅", "0.5x", "uji 5 tahun 108 koin semua pola Tembus Trendline di DASBOR, SHORT, harga di "
                        "bawah EMA 200: 691 trade, WR 80%, PF 1.47. Aturan dipilih dari 2021-2023 (PF 1.57), uji ulang "
                        "2024-2026 PF 1.38. 2026 melemah (PF 1.01), jadi lot 0.5x"),
    "saran ema_short": ("TERBUKTI", "✅", "1x", "uji 6 tahun 111 koin, maks 8 posisi: 1812 trade, WR 42%, PF 1.42, aturan dipilih "
                        "dari 2020-2023 (PF 1.37), uji ulang 2024-2026 PF 1.47, untung tiap tahun, turun terdalam 16%"),
    "saran snr_vol": ("TERBUKTI", "✅", "1x", "uji 6 tahun 111 koin, 30 paling likuid, maks 8 posisi: 692 trade, WR 39%, PF 1.33, "
                      "2020-2023 PF 1.26, uji ulang 2024-2026 PF 1.43, turun terdalam 12.5%. SnR tanpa syarat PF 1.09"),
    "saran msb_hpz": ("TERBUKTI", "✅", "1x", "uji 6 tahun 111 koin, 30 paling likuid, maks 8 posisi: 2783 trade, WR 37%, PF 1.27, "
                      "2020-2023 PF 1.32, uji ulang 2024-2026 PF 1.21, turun terdalam 18%. MSB tanpa syarat PF 1.0"),
    "saran smc_choch": ("TERBUKTI", "✅", "1x", "uji 111 koin 2020-2026, 30 paling likuid, maks 8 posisi: 2929 trade, WR 38%, PF 1.25 "
                        "(2020-2023 PF 1.30, 2024-2026 PF 1.19), lalu diuji di data lama yang belum pernah dipakai, Binance spot "
                        "40 koin 2017-2020: 962 trade, PF 1.40, untung tiap tahun. SMC tanpa syarat PF 1.06"),
    "saran mcginley": ("TERBUKTI", "✅", "1x", "uji 6 tahun 111 koin, maks 8 posisi: 3328 trade, WR 40%, PF 1.24, "
                       "2020-2023 PF 1.26, uji ulang 2024-2026 PF 1.23, data lama 2017-2020 PF 1.10, TP tetap 3R"),
    "saran rsi_vol": ("TERBUKTI", "✅", "1x", "uji 6 tahun 111 koin, 30 paling likuid, maks 8 posisi: 2380 trade, WR 40%, PF 1.34, "
                      "2020-2023 PF 1.26, uji ulang 2024-2026 PF 1.45, positif 21 dari 26 kuartal"),
    "saran orderblock": ("TERBUKTI", "✅", "1x", "uji 6 tahun 111 koin perp, LONG, maks 8 posisi: 969 trade, PF 1.45, "
                         "uji ulang 2024-2026 dengan aturan yang dipilih dari 2020-2023: PF 1.26"),
}
BELUM_UJI = ("BELUM DIUJI", "❔", "0.25x", "belum diuji ulang dengan data perp 5 tahun dan aturan robot lengkap")
CT_KEY = {"saran snr_vol": "snr_vol", "saran msb_hpz": "msb_hpz", "saran smc_choch": "smc_choch", "saran mcginley": "mcginley", "saran ema_short": "ema_short", "saran rsi_vol": "rsi_vol", "saran ichimoku": "ichimoku", "saran orderblock": "orderblock", "saran GZH": "GZH", "saran momentum": "momentum", "saran news": "news_searah"}
NAIK_N, NAIK_PF = 30, 1.2          # syarat naik jadi TERBUKTI dari hasil live


def _jalur_led(it):
    return ("saran trendline" if it.get("tt") else "saran cadangan 2" if it.get("cad2") else "saran cadangan" if it.get("cadangan") else "saran fib" if it.get("fib")
            else "saran siklus" if it.get("siklus") else "saran 1J" if it.get("tf") == "60" else "saran utama")


_LR = {}


def _live_robot(jalur):
    """Hasil catatan sinyal robot (ledger fix profit): semua sinyal yang dikirim atau disembunyikan tetap dicatat."""
    if time.time() - _LR.get("t", 0) > 300:
        try:
            import qse_fixprofit as FX
            cl = [c for c in FX.load()["closed"] if c.get("why") in ("SL", "BE", "TP2")]
        except Exception:
            cl = []
        _LR.update(t=time.time(), cl=cl)
    return [c["result_r"] for c in _LR["cl"] if _jalur_led(c) == jalur]


def _live_jalur(jalur):
    """Hasil live jalur ini: trade kamu (/entry), lalu catatan sinyal robot, lalu catatan jalur tambahan.
    Return (n, wr, pf, net) atau None."""
    rs = [c["result_r"] for c in _selesai(3650) if c.get("jalur", "manual") == jalur]
    if len(rs) < NAIK_N:
        rr = _live_robot(jalur)
        if len(rr) > len(rs):
            rs = rr
    if not rs and jalur in CT_KEY:
        try:
            import qse_catat as CT
            s = CT.statistik(CT_KEY[jalur])
            return (s["n"], s["wr"], s["pf"], s["net"]) if s["n"] else None
        except Exception:
            return None
    if not rs:
        return None
    pos, neg = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    return len(rs), sum(1 for r in rs if r > 0) / len(rs) * 100, (pos / neg if neg else 9.9), sum(rs)


def tingkat_bukti(jalur, arah=None, skor=None):
    """Return (tingkat, ikon, lot, alasan). Jalur yang belum terbukti naik jadi TERBUKTI kalau live >= 30 trade dan PF >= 1.2."""
    tk, ik, lot, why = BUKTI.get(jalur, BELUM_UJI)
    if jalur == "saran utama" and arah:
        if arah == "LONG":
            why += ". LONG paling jelek: PF 0.43 dari 35 trade"
        elif skor is not None and skor <= 55:
            tk, ik, lot = "SEDANG DIUJI", "🧪", "0.5x"
            why += (". SHORT skor 55 ke bawah kelompok paling kuat: PF 1.31 dari 39 trade di uji 5 tahun, "
                    "dan di uji 2 tahun skor 53 ke bawah WR 86% dari 22 trade")
        else:
            why += ". SHORT skor di atas 55: PF 0.46 dari 9 trade"
    lv = _live_jalur(jalur)
    if lv and tk != "TERBUKTI" and lv[0] >= NAIK_N and lv[2] >= NAIK_PF:
        tk, ik, lot = "TERBUKTI LIVE", "✅", "1x"
    elif lv and tk == "TERBUKTI" and lv[0] >= 40 and lv[2] < 1.0:
        tk, ik, lot = "MELEMAH DI LIVE", "⚠️", "0.5x"
    return tk, ik, lot, why, lv


IKUT = ("TERBUKTI", "TERBUKTI LIVE", "SEDANG DIUJI")
TAMPIL_SEMUA = os.environ.get("QSE_TAMPIL_SEMUA", "0") == "1"      # 1 = sinyal yang belum terbukti tetap ditampilkan lengkap
GARIS = "━━━━━━━━━━━━━━━━━━"


def layak(jalur, arah=None, skor=None):
    """Satu baris jawaban 'layak entry?' dari label bukti dan hasil live."""
    tk, ik, lot, _, lv = tingkat_bukti(jalur, arah, skor)
    live = f" (live {lv[0]} trade, PF {lv[2]:.2f})" if lv and lv[0] >= 3 else ""
    if tk in ("TERBUKTI", "TERBUKTI LIVE"):
        return f"✅ Layak entry: <b>YA</b>  ·  lot {lot}{live}"
    if tk == "SEDANG DIUJI":
        return f"🧪 Layak entry: <b>BOLEH</b>  ·  lot {lot}, masih diuji{live}"
    if tk == "MELEMAH DI LIVE":
        return f"⚠️ Layak entry: <b>HATI-HATI</b>  ·  lot {lot}, hasil live melemah{live}"
    return f"⚠️ Layak entry: <b>BOLEH COBA, RISIKO TINGGI</b>  ·  lot {lot}, belum terbukti{live}"


def baris_jadwal(tf_ms=4 * 3600000, tutup_ms=None, telat_menit=5):
    """Dua baris jam: sinyal ini dari candle jam berapa dan kapan sinyal berikutnya. Jam WIB.
    Contoh: '🕐 Sinyal candle 4J tutup 15/10 07:00 WIB  ·  dikirim 07:04 WIB' dan '⏭ Berikutnya: 11:00 WIB (masuk sekitar 11:05)'."""
    now = time.time()
    if not tutup_ms:
        tutup_ms = int(now * 1000) // tf_ms * tf_ms
    wib = lambda ms, f: time.strftime(f, time.gmtime(ms / 1000 + 7 * 3600))
    nxt = tutup_ms + tf_ms
    while nxt <= now * 1000:
        nxt += tf_ms
    nama = "4J" if tf_ms == 4 * 3600000 else "1J" if tf_ms == 3600000 else ""
    return (f"🕐 Sinyal candle {nama} tutup {wib(tutup_ms, '%d/%m %H:%M')} WIB  ·  dikirim {wib(now * 1000, '%H:%M')} WIB\n"
            f"⏭ Berikutnya: candle {wib(nxt, '%H:%M')} WIB (masuk sekitar {wib(nxt + telat_menit * 60000, '%H:%M')})")
NAMA_JALUR = {"saran utama": "Sinyal 4J", "saran 1J": "Sinyal 1J", "saran cadangan": "Saran cadangan",
              "saran cadangan 2": "Pola A/B pilihan robot", "saran fib": "Golden zone 0.618", "saran siklus": "Siklus", "saran GZH": "GZH", "saran momentum": "Momentum",
              "saran news": "News", "saran ichimoku": "Ichimoku",
              "saran orderblock": "Order Block + Volume", "saran trendline": "Tembus Trendline searah tren",
              "saran ema_short": "EMA Cross 20/50 SHORT", "saran rsi_vol": "RSI 50 + Volume",
              "saran mcginley": "McGinley 34 + Volume", "saran snr_vol": "SnR Pantul + Volume",
              "saran msb_hpz": "MSB LuxAlgo HPZ", "saran smc_choch": "SMC CHoCH searah tren"}


def boleh_ikut(jalur, arah=None, skor=None):
    """Return (boleh, tingkat, ikon, lot). Boleh diikuti = TERBUKTI, TERBUKTI LIVE, atau SEDANG DIUJI."""
    tk, ik, lot, _, _ = tingkat_bukti(jalur, arah, skor)
    return tk in IKUT, tk, ik, lot


def bukti_pendek(jalur, arah=None, skor=None):
    tk, ik, lot, why, lv = tingkat_bukti(jalur, arah, skor)
    if tk == "TERBUKTI LIVE" and lv:
        return f"live {lv[0]} trade, WR {lv[1]:.0f}%, PF {lv[2]:.2f}"
    if jalur == "saran ichimoku":
        return "uji 5 tahun 111 koin: 3084 trade, PF 1.29, untung tiap tahun"
    if jalur == "saran trendline":
        return "uji 5 tahun 108 koin: 691 trade, WR 80%, PF 1.47, uji ulang 2024-2026 PF 1.38"
    if jalur == "saran ema_short":
        return "uji 6 tahun 111 koin: 1812 trade, PF 1.42, uji ulang 2024-2026 PF 1.47"
    if jalur == "saran snr_vol":
        return "uji 6 tahun, 30 koin likuid: 692 trade, PF 1.33, uji ulang 2024-2026 PF 1.43"
    if jalur == "saran msb_hpz":
        return "uji 6 tahun, 30 koin likuid: 2783 trade, PF 1.27, uji ulang 2024-2026 PF 1.21"
    if jalur == "saran smc_choch":
        return "uji 2017-2026: PF 1.40 (2017-2020), 1.30 (2020-2023), 1.19 (2024-2026)"
    if jalur == "saran mcginley":
        return "uji 6 tahun 111 koin: 3328 trade, PF 1.24, uji ulang 2024-2026 PF 1.23"
    if jalur == "saran rsi_vol":
        return "uji 6 tahun, 30 koin likuid: 2380 trade, PF 1.34, uji ulang 2024-2026 PF 1.45"
    if jalur == "saran orderblock":
        return "uji 6 tahun 111 koin: 969 trade, PF 1.45, uji ulang 2024-2026 PF 1.26"
    if tk == "SEDANG DIUJI":
        return "SHORT kelompok terbaik: PF 1.31 di uji 5 tahun, WR 86% di uji 2 tahun"
    if jalur == "saran utama" and arah == "LONG":
        return "LONG di uji 5 tahun PF 0.43 (35 trade), lebih sering rugi"
    if jalur == "saran utama" and arah == "SHORT":
        return "SHORT kelompok ini di uji 5 tahun PF 0.46, lebih sering SL"
    return why.split(";")[0].split(". ")[0]


def risiko_sekarang(arah, longgar=False):
    """Alasan kondisi pasar saat ini membuat setup lebih berisiko (BTC 1 jam, berita besar, sinyal longgar)."""
    rs = []
    if longgar:
        rs.append("sinyal longgar: syarat sedikit diringankan karena hari ini sepi")
    rs += btc_melawan(arah)
    bd = berita_depan(3)
    if bd:
        rs.append(f"berita besar {bd['judul']} dalam 3 jam")
    return rs


def lot_angka(lot):
    try:
        return float(str(lot).split("x")[0].replace(",", "."))
    except Exception:
        return 0.25


def baris_bukti(jalur, arah=None, skor=None):
    import html
    tk, ik, lot, why, lv = tingkat_bukti(jalur, arah, skor)
    live = (f" | live {lv[0]} trade, WR {lv[1]:.0f}%, PF {lv[2]:.2f}, {lv[3]:+.1f}R" if lv else " | live belum ada trade")
    syarat = "" if tk.startswith("TERBUKTI") else f" | naik jadi TERBUKTI kalau live {NAIK_N} trade dengan PF {NAIK_PF}"
    return f"{ik} <b>BUKTI {html.escape(jalur.upper())}: {tk}</b> | {html.escape(why)}{live}{syarat} | lot maks {lot}"


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
            kuning.append(f"sudah ada {p['arah']} terbuka di koin ini ({p['asal']}), entry ini menambah ukuran posisi")
    izin = r.get("izin", "LONG dan SHORT")
    if izin != "LONG dan SHORT" and not izin.startswith(arah):
        merah.append(f"BTC 4J melawan, yang diizinkan {izin}")
    merah += [x + f", melawan {arah}" for x in btc_melawan(arah)]
    bd = berita_depan(3)
    if bd:
        merah.append(f"berita besar {bd['judul']} dalam 3 jam, pasar bisa berbalik tajam")
    try:
        import qse_modal as MD
        st = MD.status()
        if st["rem"]:
            merah.append(st["alasan"])
    except Exception:
        pass
    # Rapor koin (A/B/C/D) tidak dipakai lagi: uji 30 ribu trade jalur terbukti 2021-2026, rapor D PF 1.27, A 1.17, B 1.26, C 1.20.
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


# Trade kamu dari sinyal jalur terbukti dikelola dengan aturan jalur itu, bukan TP1 0.8R / TP2 1.8R umum.
# Uji 2021-2026 (35 ribu trade): aturan jalur +4568R PF 1.26, TP1/TP2 umum dengan SL ke entry +2371R PF 1.16.
TEKS_IKUT = ("Posisi ini ikut aturan jalur terbukti: SL {sl}, {tp}. Jangan geser SL ke entry dan jangan keluar lebih awal. "
             "Uji 2021-2026: keluar atau kunci lebih awal menurunkan profit 18 sampai 78%.")


def jalur_posisi(sym, arah):
    """Posisi robot jalur terbukti yang searah di koin ini. Return dict (nama, jalur, sl, tp, t) atau None."""
    for x in jalur_aktif(sym):
        if x["arah"] == arah:
            return x
    return None


def _tp_teks(tp, t):
    return f"TP {fp(tp, t)} penuh" if tp else "tanpa TP, pakai SL berjalan"


def jalur_aktif(sym):
    """Sinyal jalur terbukti yang masih berjalan di koin ini (Ichimoku, Order Block, strategi, GZH). List dict."""
    out = []
    try:
        import qse_ichimoku as IC
        out += [dict(nama="Ichimoku", jalur="saran ichimoku", **v) for v in IC.lihat()["open"].values() if v["sym"] == sym]
    except Exception:
        pass
    try:
        import qse_ob as OB
        out += [dict(nama="Order Block + Volume", jalur="saran orderblock", **dict(v, arah="LONG")) for v in OB.lihat()["open"].values()
                if v["sym"] == sym]
    except Exception:
        pass
    try:
        import qse_strat as ST
        for k, cfg in ST.STRAT.items():
            out += [dict(nama=cfg["nama"], jalur="saran " + k, **v) for v in ST.lihat(k)["open"].values() if v["sym"] == sym]
    except Exception:
        pass
    return out


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
    kal = [(tren_teks(sym) or f"{sym} 4J") + "."]
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
    ja = jalur_aktif(sym)
    if ja:
        rows = ["🎯 <b>SINYAL JALUR TERBUKTI DI KOIN INI</b>"]
        for j_ in ja:
            tk_, ik_, lot_, _, _ = tingkat_bukti(j_["jalur"], j_["arah"])
            rows.append(f"{ik_} {j_['nama']} {j_['arah']}  ·  {tk_}  ·  lot {lot_}\n"
                        f"Entry {fp(j_['entry'], t)}  ·  SL sekarang {fp(j_['sl'], t)}"
                        + (f"  ·  TP {fp(j_['tp'], t)}" if j_.get("tp") else "  ·  tanpa TP, SL berjalan"))
        rows.append("Untuk posisi dari jalur ini, ikuti aturan jalur: SL, TP, dan pesan GESER SL. Penilaian umum di bawah "
                    "tidak dipakai, karena di uji 2021-2026 sinyal jalur terbukti yang dinilai BERISIKO oleh /cek tetap untung "
                    "(PF 1.1 sampai 1.5). Jangan keluar lebih awal hanya karena penilaian ini.")
        label_txt = f"Penilaian umum {arah}: {label} (info saja, bukan aturan jalur terbukti)."
    else:
        label_txt = f"Penilaian {arah}: <b>{label}</b>. {aksi}"
    blok = [f"Harga {fp(px, t) if px else '-'}{p24}"] + (["\n".join(rows)] if ja else []) + [
            "<b>Kesimpulan</b>\n" + " ".join(kal) + f"\n\n{label_txt}"]

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
            tren_teks("BTCUSDT") or "-",
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


KATA_ABAI = {"ENTRY", "HARGA", "LONG", "SHORT", "BUY", "SELL", "SL", "TP", "TP1", "TP2", "SKOR", "SETUP", "LAYAK", "DIIKUTI",
             "BANGET", "MARKET", "LIMIT", "STOP", "PENILAIAN", "WAJIB", "AMAN", "BERISIKO", "HIGH", "RISK", "RETURN", "LOT",
             "BARU", "GZH", "TERKONFIRMASI", "ICHIMOKU", "SARAN", "MOMENTUM", "NEWS", "GOLDEN", "MOMENT", "TF", "CANDLE",
             "MKT", "TERISI", "FILLED", "SUDAH", "ISI", "JAM", "PADA", "DI", "LEV", "LEVERAGE", "QSE", "V148", "R", "TAJAM"}


def _sinyal_dari_harga(entry, sl=None):
    """Cari koin dan arah dari harga entry sinyal yang ditempel (semua jalur, 3 hari terakhir). Return (sym, arah) atau None."""
    cocok = lambda e: e and abs(e - entry) / entry <= 0.0005
    calon = []
    try:
        import qse_fixprofit as FX
        led = FX.load()
        for v in list(led["open"].values()) + led["closed"][-300:]:
            if cocok(v.get("entry")) and (time.time() * 1000 - (v.get("sent_ts") or 0)) <= 3 * 86400000:
                calon.append((v["sym"], v["arah"], v.get("sl")))
    except Exception:
        pass
    try:
        import qse_catat as CT
        d = CT._baca()
        calon += [(v["sym"], v["arah"], v.get("sl")) for v in d["open"] + d["closed"][-200:] if cocok(v.get("entry"))]
    except Exception:
        pass
    try:
        with open(os.path.join(STATE_DIR, "sentuh_fib.json")) as f:
            calon += [(k, g["arah"], g.get("sl")) for k, g in json.load(f).get("sinyal", {}).items() if cocok(g.get("entry"))]
    except Exception:
        pass
    try:
        import qse_alarm as AL
        calon += [(a["sym"], "LONG" if a["L"] else "SHORT", a.get("sl")) for a in AL._lihat()["list"]
                  if a.get("jenis") == "gzh" and cocok(a.get("harga"))]
    except Exception:
        pass
    try:
        import qse_ichimoku as IC
        calon += [(v["sym"], v["arah"], v.get("sl0")) for v in IC.lihat()["open"].values() if cocok(v.get("entry"))]
    except Exception:
        pass
    try:
        import qse_ob as OB
        calon += [(v["sym"], "LONG", v.get("sl")) for v in OB.lihat()["open"].values() if cocok(v.get("entry"))]
    except Exception:
        pass
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            calon += [(v["sym"], v["arah"], v.get("sl0")) for v in ST.lihat(k)["open"].values() if cocok(v.get("entry"))]
    except Exception:
        pass
    for r in _peta_robot().values():
        calon += [(r["symbol"], x["arah"], x.get("sl")) for x in r.get("saran", []) if cocok(x.get("entry"))]
    if sl:
        tepat = [c for c in calon if c[2] and abs(c[2] - sl) / sl <= 0.002]
        calon = tepat or calon
    return (calon[0][0], calon[0][1]) if calon else None


def parse_entry(args):
    """/entry long limit AUSDT 1.022 [sl 0.99] [tp1 1.05] [tp2 1.08] [terisi [29/09] [02:00]]
    Bisa juga tempel langsung blok sinyal: Entry 0.12842 SL 0.11815 TP1 0.14362 TP2 0.14942.
    Koin dan arah dicari dari sinyal robot kalau tidak ditulis."""
    import re
    arah = order = sym = None
    nums, kv, i = [], {}, 0
    terisi, tgl, jam = False, None, None
    kandidat = []
    while i < len(args):
        a = args[i]
        nxt = _angka(args[i + 1]) if i + 1 < len(args) else None
        if a in ("LONG", "BUY", "L"):
            arah = arah or "LONG"
        elif a in ("SHORT", "SELL", "S"):
            arah = arah or "SHORT"
        elif a in ("LIMIT", "MARKET", "MKT"):
            order = "MARKET" if a != "LIMIT" else "LIMIT"
        elif a == "STOP" and i > 0 and args[i - 1] in ("TRAILING", "TRAIL"):
            pass                     # "Trailing Stop" dari blok kartu, bukan jenis order
        elif a in ("JARAK", "TRAILING", "TRAIL") and nxt is not None:
            i += 1                   # angka jarak trailing bukan harga
        elif a in ("STOP", "CONDITIONAL", "TRIGGER", "KONDISIONAL"):
            order = "STOP"           # conditional stop: terisi saat harga MENEMBUS entry, bukan saat retest
        elif a in ("TERISI", "FILLED", "SUDAH", "ISI"):
            terisi = True
        elif re.fullmatch(r"\d{1,2}:\d{2}", a):
            jam = a
        elif re.fullmatch(r"\d{1,2}/\d{1,2}(/\d{2,4})?", a):
            tgl = a
        elif a in ("LEV", "LEVERAGE") and i + 1 < len(args) and _angka(args[i + 1].rstrip("X")) is not None:
            kv["LEV"] = _angka(args[i + 1].rstrip("X"))
            i += 1
        elif re.fullmatch(r"\d+(\.\d+)?X", a):
            kv["LEV"] = _angka(a[:-1])
        elif a in ("SL", "TP", "TP1", "TP2") and nxt is not None:
            kv["TP1" if a == "TP" else a] = nxt
            i += 1
        elif a in ("ENTRY", "HARGA", "LIMIT") and nxt is not None:
            kv["ENTRY"] = nxt
            i += 1
        elif re.fullmatch(r"[\d.,]+R|[\d.,]+%|\d+/\d+", a):
            pass                                            # kolom R, persen, dan skor dari blok sinyal
        elif _angka(a) is not None:
            nums.append(_angka(a))
        elif a.endswith("USDT") and len(a) > 4:
            sym = sym or a
        elif re.fullmatch(r"[A-Z0-9]{2,15}", a) and a not in KATA_ABAI:
            kandidat.append(a)
        i += 1
    if not sym and kandidat:
        ada = harga_semua() if len(kandidat) > 1 else {}
        sym = next((k + "USDT" for k in kandidat if not ada or k + "USDT" in ada), None)
    tempel = "ENTRY" in kv
    harga = kv.pop("ENTRY", None) or (nums[0] if nums else None)
    if tempel and order is None:
        terisi = True          # blok sinyal ditempel: dianggap sudah masuk di harga entry itu
    if harga and kv.get("SL"):
        tebak = None if (sym and arah) else _sinyal_dari_harga(harga, kv.get("SL"))
        if tebak:
            sym = sym or tebak[0]
            arah = arah or tebak[1]
        arah = arah or ("LONG" if kv["SL"] < harga else "SHORT")
    kv.update(terisi=terisi or bool(jam or tgl), tgl=tgl, jam=jam)
    return arah, order or ("LIMIT" if harga else "MARKET"), sym, harga, kv


def _jalur_led(it):
    return ("saran trendline" if it.get("tt") else "saran cadangan" if it.get("cadangan") else "saran siklus" if it.get("siklus")
            else "saran cadangan 2" if it.get("cad2") else "saran fib" if it.get("fib")
            else "saran 1J" if it.get("tf") == "60" else "saran utama")


def sinyal_terakhir(sym, arah, harga, hari=3):
    """Sinyal robot paling baru untuk koin dan arah ini (semua jalur, maks `hari` hari lalu)
    yang SL-nya masih di sisi benar dari harga entry kamu dan TP1-nya masih di depan.
    Return dict(pola, entry, sl, tp1, tp2, jalur, skor) atau None."""
    L = arah == "LONG"
    batas = time.time() - hari * 86400
    calon = []
    r = hasil_robot(sym)
    try:
        import qse_fixprofit as FX
        led = FX.load()
        for it in list(led["open"].values()) + led["closed"][-500:]:
            ts = (it.get("sent_ts") or it.get("start_ts") or 0) / 1000
            if it.get("sym") == sym and it.get("arah") == arah and ts >= batas:
                calon.append((ts, dict(it, jalur=_jalur_led(it))))
    except Exception:
        pass
    try:
        import qse_catat as CT
        d = CT._baca()
        for it in d["open"] + d["closed"][-300:]:
            if it.get("sym") == sym and it.get("arah") == arah and it.get("t", 0) >= batas and it.get("jalur") != "ichimoku":
                j = "saran momentum" if it["jalur"] == "momentum" else "saran news" if it["jalur"].startswith("news") \
                    else "saran " + it["jalur"]
                calon.append((it["t"], dict(it, pola=CT.NAMA.get(it["jalur"], it["jalur"]), jalur=j,
                                            skor=_skor_ket(it.get("ket")))))
    except Exception:
        pass
    rb = None
    for s in (r["saran"] if r else []):
        if s["arah"] == arah:
            rb = rb or ramal_btc4()
            calon.append((0.5 if s["eksekusi"] else 0,           # saran EKSEKUSI scan terakhir didahulukan dari TAHAN
                          dict(s, jalur="saran utama" if s["eksekusi"] else "manual",
                               skor=skor_setup(r, s, rb["p_up"] if rb else None))))
    calon.sort(key=lambda z: z[0], reverse=True)
    for _, s in calon:
        if not all((s.get(k) or 0) > 0 for k in ("sl", "tp1", "tp2")):
            continue
        if (L and s["sl"] < harga < s["tp1"] <= s["tp2"]) or ((not L) and s["tp2"] <= s["tp1"] < harga < s["sl"]):
            sk = s.get("skor")
            if sk is None and r:
                x = next((y for y in r["saran"] if y["pola"] == s.get("pola") and y["arah"] == arah), None)
                rb = rb or ramal_btc4()
                sk = skor_setup(r, x, rb["p_up"] if rb else None) if x else None
            return dict(pola=s.get("pola", "-"), entry=s.get("entry", harga), sl=s["sl"], tp1=s["tp1"], tp2=s["tp2"],
                        jalur=s.get("jalur", "saran utama"), skor=sk)
    return None


def entry(args):
    arah, order, sym, harga, kv = parse_entry(args)
    if not arah or not sym:
        if harga and kv.get("SL"):
            return ("Koin tidak ketemu dari harga entry itu. Tambahkan nama koinnya di depan, contoh:\n"
                    "/entry AVNT\nEntry 0.12842\nSL 0.11815 ...")
        return ("Format: /entry long limit AUSDT 1.022\n"
                "Tambahan opsional: sl 0.99 tp1 1.05 tp2 1.08. Tanpa SL dan TP, robot pakai sinyal terakhir koin ini. "
                "Tanpa harga dianggap MARKET di harga sekarang.")
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
    elif order == "STOP" and ((L and px >= harga) or ((not L) and px <= harga)):
        isi_ts = now          # STOP yang harganya sudah ditembus langsung terisi
    elif order != "STOP" and ((L and px <= harga) or ((not L) and px >= harga)):
        isi_ts = now          # LIMIT yang harganya sudah dilewati pasti langsung terisi
    catatan_isi = ""
    if isi_ts is not None and order == "LIMIT" and not kv.get("terisi"):
        catatan_isi = "Harga sekarang sudah melewati entry, jadi LIMIT ini dicatat langsung terisi."
    r = hasil_robot(sym)
    t = min(tick_of(r, px), tick_of(r, harga))
    sumber = "kamu"
    dari_sinyal = None
    sl, tp1, tp2 = kv.get("SL"), kv.get("TP1"), kv.get("TP2")
    jp = jalur_posisi(sym, arah)
    # blok salin kartu jalur ikut ditempel: TP yang sama dengan TP jalur tetap dianggap ikut aturan jalur
    _tpj = (jp or {}).get("tp")
    _sama = lambda v: v is None or bool(_tpj and abs(v - _tpj) <= abs(_tpj) * 0.003)
    ikut_ok = bool(jp and _sama(kv.get("TP1")) and _sama(kv.get("TP2")))
    if ikut_ok:
        kv.pop("TP1", None); kv.pop("TP2", None)
    tp_user = None          # TP cepat atau TP sendiri pada posisi jalur: SL tetap ikut jalur, tutup penuh di TP ini
    if jp and not ikut_ok and kv.get("TP1") is not None and (
            kv.get("TP2") is None or abs(kv["TP2"] - kv["TP1"]) <= abs(kv["TP1"]) * 0.003):
        tp_user = kv.pop("TP1")
        kv.pop("TP2", None)
    if jp and kv.get("TP1") is None and kv.get("TP2") is None:
        sl = sl if sl is not None else jp["sl"]
        far = harga * (100 if L else 0.01)            # TP1/TP2 tidak dipakai: keluar dari SL berjalan atau TP jalur
        tp1 = tp2 = tp_user or jp.get("tp") or far
        sumber = f"jalur {jp['nama']} (aturan jalur terbukti)" + (", TP pilihan kamu" if tp_user else "")
    a_ref = (r or {}).get("atr") or 0.0
    cocok = [s for s in (r["saran"] if r else []) if s["arah"] == arah
             and a_ref > 0 and abs(s["entry"] - harga) <= 0.5 * a_ref
             and ((s["sl"] < harga) if L else (s["sl"] > harga))]
    if sl is None and not cocok:
        # tidak ada saran yang entry-nya dekat: pakai sinyal terakhir koin dan arah ini yang SL-nya masih di sisi benar
        s = sinyal_terakhir(sym, arah, harga)
        if s:
            sl, tp1, tp2 = s["sl"], tp1 or s["tp1"], tp2 or s["tp2"]
            sumber = f"sinyal terakhir robot ({s['pola']}, entry sinyal {fp(s['entry'], t)})"
            dari_sinyal = s
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
    asal = asal_saran(sym, arah, harga, r)
    if jp:
        asal = dict(jalur=jp["jalur"], pola=jp["nama"], skor=None)
    if asal["jalur"] == "manual" and dari_sinyal:          # SL dan TP diambil dari sinyal robot: asal ikut sinyal itu
        asal = dict(jalur=dari_sinyal["jalur"], pola=dari_sinyal["pola"], skor=dari_sinyal["skor"])
    jalur, pola_asal = asal["jalur"], asal["pola"]
    lv_user = {k: kv[k] for k in ("SL", "TP1", "TP2") if kv.get(k) is not None}
    baru_isi = isi_ts is not None and now - isi_ts <= 5 * 60000      # terisi lampau: riwayat candle dicek dulu

    def simpan(d):
        d["seq"] += 1
        tid = f"{sym}#{d['seq']}"
        d["open"][tid] = dict(id=tid, no=d["seq"], sym=sym, arah=arah, order=order, entry=harga, sl=sl, tp1=tp1,
                              tp2=tp2, atr=a_now, tick=t, sumber=sumber, nilai=label,
                              created_ts=isi_ts or now, last_ts=isi_ts or now,
                              status="TERISI" if isi_ts is not None else "MENUNGGU",
                              fill_ts=isi_ts or 0, alert=[], lev=kv.get("LEV"), risk0=abs(harga - sl),
                              sisa=1.0, real=0.0, jalur=jalur, pola=pola_asal, skor=asal["skor"],
                              **(dict(ikut=jp["jalur"], tp_jalur=tp_user or jp.get("tp"), tp_cepat=bool(tp_user))
                                 if jp and kv.get("TP1") is None else {}))
        lama_tp1 = any(v["sym"] == sym and v["arah"] == arah and v["status"] == "TP1" for v in d["open"].values())
        ada_jalan = any(v["sym"] == sym and v["arah"] == arah and v["status"] == "TERISI" and v.get("id") != tid
                        for v in d["open"].values())
        gab = _gabung_semua(d, sym, arah, lv_user) if baru_isi else []
        return gab, lama_tp1, ada_jalan
    gab, lama_tp1, ada_jalan = ubah(simpan)
    fee_r = 2 * FEE / 100 * harga / risk
    n_open = len(_load()["open"])
    kd = sym.replace("USDT", "")
    sk_txt = f" | skor setup {asal['skor']}/100" if asal["skor"] is not None else ""
    ikut = bool(jp and kv.get("TP1") is None)
    tp_j = (tp_user or jp.get("tp")) if ikut else None
    rows = [f"<b>TRADE KAMU TERCATAT</b> (posisi terbuka {n_open})",
            f"{sym} {arah} {order}" + (f" (sudah terisi, sejak {_jam_wib(isi_ts)})" if isi_ts is not None
                                       else " (menunggu terisi)"),
            (f"<pre>Entry {fp(harga, t)}\nSL    {fp(sl, t)}  -1.00R  -{abs(sl - harga) / harga * 100:.2f}%\n"
             + (f"TP    {fp(tp_j, t)}  +{abs(tp_j - harga) / risk:.2f}R  +{abs(tp_j - harga) / harga * 100:.2f}%</pre>" if tp_j
                else "TP    tanpa, pakai SL berjalan jalur</pre>")) if ikut else
            f"<pre>Entry {fp(harga, t)}\nSL    {fp(sl, t)}  -1.00R  -{abs(sl - harga) / harga * 100:.2f}%\n"
            f"TP1   {fp(tp1, t)}  +{abs(tp1 - harga) / risk:.2f}R  +{abs(tp1 - harga) / harga * 100:.2f}%\n"
            f"TP2   {fp(tp2, t)}  +{abs(tp2 - harga) / risk:.2f}R  +{abs(tp2 - harga) / harga * 100:.2f}%</pre>",
            f"Asal entry: {jalur}" + (f" ({pola_asal})" if pola_asal != "manual" else "") + sk_txt +
            f" | lot disarankan {lot_jalur(jalur):g}x lot normal",
            f"SL dan TP dari {sumber}. Fee pulang pergi sekitar {fee_r:.2f}R.",
            (f"✅ <b>JALUR TERBUKTI {jp['nama'].upper()}</b>\n" + TEKS_IKUT.format(sl=fp(sl, t), tp=_tp_teks(tp_j, t))
             + f"\nRobot menyamakan SL kamu dengan SL berjalan jalur tiap menit, dan mengabari saat jalur keluar.") if ikut else
            (f"✅ <b>JALUR TERBUKTI</b>: {bukti_pendek(jalur)}. Ikuti SL dan TP dari sinyal, jangan keluar lebih awal."
             if jalur in JALUR_TERBUKTI() else
             "⚠️ <b>BUKAN DARI JALUR TERBUKTI</b>. Di uji 2021-2026 hanya sinyal jalur terbukti yang untung. "
             "Kalau tetap masuk, pakai lot kecil dan pasang SL.")]
    try:
        import qse_modal as MD
        bl = MD.baris_lot(harga, sl, lot_jalur(jalur), int(kv["LEV"]) if kv.get("LEV") else None)
        if bl:
            rows.insert(4, bl)
    except Exception:
        pass
    if kv.get("LEV"):
        rows.insert(4, f"Leverage {kv['LEV']:g}x dicatat, /status menampilkan ROE.")
    if jp and not kv.get("terisi"):
        try:
            import qse_strat as ST
            kj = jp["jalur"].replace("saran ", "")
            bm = ST.batas_masuk(jp, kj)
            if bm and (not (bm[0] <= harga <= bm[1]) or time.time() > bm[2]):
                rj = abs(jp["entry"] - jp.get("sl0", jp["sl"])) or 1e-12
                lari = (harga - jp["entry"]) * (1 if L else -1) / rj
                rows.append(f"⚠️ <b>ENTRY TELAT</b>: harga {fp(harga, t)} sudah {lari:+.2f}R dari entry robot {fp(jp['entry'], t)}"
                            + (" dan lewat batas waktu" if time.time() > bm[2] else "")
                            + f". Batas aman {fp(bm[0], t)} sampai {fp(bm[1], t)}. Uji 2020-2026: masuk lebih dari 0.5R "
                            f"dari entry robot hasilnya turun. Kalau belum masuk di Bybit, lewati sinyal ini. Kalau sudah, "
                            f"tetap pasang SL dan ikuti aturan jalur.")
        except Exception as ex:
            print("[WARN] batas masuk", ex)
    if order == "STOP" and isi_ts is None:
        rows.append(f"Order STOP: terisi saat harga {'naik menembus' if L else 'turun menembus'} {fp(harga, t)}. "
                    "Robot mengabari saat terisi.")
    for g in gab:
        rows.append("\n" + teks_gabung(g) + "\nSL dan TP mengikuti posisi lama, kecuali yang kamu tulis di /entry ini.")
    if lama_tp1 and not gab:
        rows.append(f"Posisi {sym} {arah} lama sudah TP1 (SL di entry), jadi entry ini dicatat terpisah.")
    if isi_ts is None and ada_jalan:
        rows.append(f"Order ini digabung ke posisi {sym} {arah} yang sudah jalan begitu terisi.")
    if r and r.get("skill"):
        rows.append(SK.ringkas(r["skill"], arah, lambda x: fp(x, t)))
    if catatan_isi:
        rows.append(catatan_isi)
    if isi_ts is not None and not baru_isi:
        rows.append("Candle sejak jam terisi ikut dicek. Kalau TP atau SL sudah kena di rentang itu, kabarnya menyusul dalam 1 menit. "
                    "Kalau masih jalan dan ada posisi lama di koin dan arah yang sama, keduanya digabung otomatis.")
    rows.append("Robot memantau tiap menit dan mengabari saat terisi, TP1, TP2, SL, atau ada kasus besar. "
                f"Ubah SL atau TP: /modify {kd} sl HARGA tp1 HARGA. Keluar lebih awal: /tutup {kd} HARGA")
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
    kunci_lv = ("SL", "TP", "TP1", "TP2", "TRAILING", "TRAIL")
    angka = [_angka(a) for j, a in enumerate(args[1:], 1) if a not in ("LONG", "SHORT", "LOT") and _angka(a) is not None
             and args[j - 1] not in kunci_lv and not a.endswith("%")]
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
        # trade yang masih terbuka (salah entry) dihapus dulu, tanpa masuk ke catatan hasil
        for k in [k for k, v in d["open"].items() if v["sym"] == sym and (arah is None or v["arah"] == arah)]:
            it = d["open"].pop(k)
            return dict(buka=True, arah=it["arah"], status=it.get("status", "-"))
        for i in range(len(d["closed"]) - 1, -1, -1):
            c = d["closed"][i]
            if c["sym"] == sym and (arah is None or c["arah"] == arah):
                return d["closed"].pop(i)
        return None
    c = ubah(f)
    if not c:
        return f"Tidak ada trade terbuka atau catatan selesai di {sym}" + (f" {arah}." if arah else ".")
    if c.get("buka"):
        return (f"Trade terbuka dihapus: {sym} {c['arah']} ({c['status']}). "
                f"Tidak masuk catatan hasil, WR dan evaluasi tidak berubah.")
    return (f"Catatan dihapus: {sym} {c['arah']} | {c.get('why', '-')} {c.get('result_r', 0):+.2f}R. "
            f"WR dan evaluasi sudah dihitung ulang tanpa trade ini.")


def ubah_level(args):
    """/ubah KOIN sl 0.99 tp1 1.05 tp2 1.08, atau /ubah KOIN sl entry untuk geser SL ke titik impas."""
    if not args:
        return "Format: /modify AUSDT sl 0.99 tp1 1.05 tp2 1.08 atau /modify AUSDT sl entry"
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
        return "Format: /modify AUSDT sl 0.99 tp1 1.05 tp2 1.08 atau /modify AUSDT sl entry"

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
            sl_now = it["entry"] if it["status"] == "TP1" and not it.get("sl_manual") else it["sl"]
            rows.append(f"{sym} {it['arah']} diperbarui\nSL {fp(it['sl'], t)} | TP1 {fp(it['tp1'], t)} | TP2 {fp(it['tp2'], t)}\n"
                        f"Kalau kena SL: total {_hasil_di(it, sl_now, 'SL'):+.2f}R"
                        + (f" | TP1: total {_hasil_di(it, it['tp1'], 'TP1'):+.2f}R" if it["status"] != "TP1" else "")
                        + f" | TP2: total {_hasil_di(it, it['tp2'], 'TP2'):+.2f}R")
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


# ---------------- gabung posisi koin dan arah yang sama (seperti Bybit one-way) ----------------
def _gabung_ke(base, it):
    """Tambahkan posisi `it` ke `base`. Tiap trade dicatat 1R risiko, jadi jumlah koin `it` dalam satuan lot awal base
    = sisa_it x risk0_base / risk0_it. Entry jadi rata-rata tertimbang jumlah koin, R yang sudah direalisasi dijumlah.
    SL dan TP mengikuti base. Return tambahan ukuran (x lot awal base)."""
    rb, ri = _risk0(base), _risk0(it)
    x = _sisa(it) * rb / ri
    sb = _sisa(base)
    base["entry"] = (sb * base["entry"] + x * it["entry"]) / (sb + x)
    base["risk0"], base["real"], base["sisa"] = rb, _real(base) + _real(it), sb + x
    base["alert"] = sorted(set(base.get("alert", [])) | set(it.get("alert", [])))
    if not base.get("lev") and it.get("lev"):
        base["lev"] = it["lev"]
    base.setdefault("gabung", []).append(dict(no=it.get("no"), entry=it["entry"], lot=round(x, 4),
                                              ts=it.get("fill_ts") or it.get("created_ts"), jalur=it.get("jalur"),
                                              pola=it.get("pola"), skor=it.get("skor")))
    return x


def _gabung_semua(d, sym=None, arah=None, lv_user=None):
    """Satukan semua posisi TERISI dengan koin dan arah sama. Posisi tertua jadi induk.
    lv_user = {'SL','TP1','TP2'} dari /entry terbaru, dipasang ke posisi gabungan bila sisinya masuk akal.
    Return list dict(base, n, x, catatan)."""
    grup = {}
    for k, v in d["open"].items():
        if v["status"] != "TERISI" or (sym and v["sym"] != sym) or (arah and v["arah"] != arah):
            continue
        grup.setdefault((v["sym"], v["arah"]), []).append(k)
    out = []
    for keys in grup.values():
        if len(keys) < 2:
            continue
        keys.sort(key=lambda k: d["open"][k].get("no", 0))
        base = d["open"][keys[0]]
        x = sum(_gabung_ke(base, d["open"].pop(k)) for k in keys[1:])
        catatan = []
        L = base["arah"] == "LONG"
        e = base["entry"]
        for k, v in (lv_user or {}).items():
            kunci = k.lower()
            benar = (v < e) if (kunci == "sl") == L else (v > e)
            if benar:
                base[kunci] = v
            else:
                catatan.append(f"{k} {fp(v, base['tick'])} tidak dipakai karena salah sisi dari entry rata-rata")
        out.append(dict(base=base, n=len(keys), x=x, catatan=catatan))
    return out


def teks_gabung(g):
    """Satu blok pesan untuk posisi yang baru digabung."""
    b = g["base"]
    t = b["tick"]
    kd = b["sym"].replace("USDT", "")
    r_sl = _real(b) + _sisa(b) * _r_at(b, b["sl"])
    return (f"🔗 <b>{b['sym']} {b['arah']}: {g['n']} entry digabung jadi satu posisi</b>, sama seperti di Bybit.\n"
            f"Entry rata-rata {fp(b['entry'], t)} | ukuran {_sisa(b):.2f}x lot awal\n"
            f"SL {fp(b['sl'], t)} | TP1 {fp(b['tp1'], t)} | TP2 {fp(b['tp2'], t)}\n"
            f"Kalau kena SL: total {r_sl:+.2f}R"
            + ("".join(f"\n{c}" for c in g.get("catatan", [])))
            + f"\nGeser level: /modify {kd} sl HARGA tp1 HARGA tp2 HARGA")


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
            stop = it.get("order") == "STOP"
            if not ((hi >= e if L else lo <= e) if stop else (lo <= e if L else hi >= e)):
                continue
            it["status"], it["fill_ts"] = "TERISI", ts
            it.setdefault("risk0", max(abs(e - it["sl"]), 1e-12))
            ev.append(("TERISI", "ORDER TERISI"))
        if it.get("ikut") and it["status"] == "TERISI":
            sl, tpj = it["sl"], it.get("tp_jalur")
            if (lo <= sl) if L else (hi >= sl):
                _tutup_bagian(it, 1.0, sl)
                res = _real(it)
                why = "SL" if res < 0 else "TP2"
                it.update(status="SELESAI", why=why, result_r=round(res, 3), closed_ts=ts)
                ev.append((why, f"kena SL{' berjalan' if res >= 0 else ''} di {fp(sl, it['tick'])}, selesai {res:+.2f}R"))
                return ev
            if tpj and ((hi >= tpj) if L else (lo <= tpj)):
                _tutup_bagian(it, 1.0, tpj)
                res = _real(it)
                it.update(status="SELESAI", why="TP2", result_r=round(res, 3), closed_ts=ts)
                ev.append(("TP2", f"KENA TP jalur di {fp(tpj, it['tick'])}, tutup penuh, selesai {res:+.2f}R"))
                return ev
            continue
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
                ev.append(("TP1", f"KENA TP1, separuh ditutup {r:+.2f}R. " +
                           (f"SL kamu tetap di {fp(it['sl'], it['tick'])} (SL manual). Mau aman: /modify "
                            f"{it['sym'].replace('USDT', '')} sl entry" if it.get("sl_manual")
                            else f"Geser SL ke entry {fp(e, it['tick'])}")))
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

    peta_j = {}
    for v in d0["open"].values():
        if v["status"] == "TERISI" and (v.get("ikut") or str(v.get("jalur", "")) in JALUR_TERBUKTI()):
            peta_j[(v["sym"], v["arah"])] = jalur_posisi(v["sym"], v["arah"])

    def f(d):
        pesan = []
        for k in list(d["open"].keys()):
            it = d["open"][k]
            kj = (it["sym"], it["arah"])
            if kj in peta_j and it["status"] == "TERISI":
                pesan += _sinkron_jalur(it, peta_j[kj])
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
                if e == "SL":
                    try:
                        import qse_ob as OB
                        OB.antri_sl(it["sym"], it["arah"], it["entry"], it["sl"], it.get("fill_ts") or it.get("created_ts"),
                                    "trade kamu")
                        txt += ". Analisa volume dikirim setelah candle 4J ini tutup"
                    except Exception as ex:
                        print("[WARN] antri SL", ex)
                pesan.append(f"{ik.get(e, '•')} <b>{it['sym']} {it['arah']}</b>\n↳ {txt} | entry {fp(it['entry'], it['tick'])}")
            if it["status"] == "SELESAI":
                d["closed"].append(d["open"].pop(k))
        for g in _gabung_semua(d):          # LIMIT yang baru terisi atau catatan ganda lama: jadikan satu posisi
            pesan.append(teks_gabung(g))
        return pesan
    return ubah(f)


def JALUR_TERBUKTI():
    out = {"saran ichimoku", "saran orderblock", "saran GZH", "saran trendline"}
    try:
        import qse_strat as ST
        out |= {"saran " + k for k in ST.STRAT}
    except Exception:
        pass
    return out


def _sinkron_jalur(it, jp):
    """Trade kamu dari jalur terbukti: pakai SL berjalan dan TP jalur. Return pesan."""
    t = it.get("tick") or 1e-8
    kd = it["sym"].replace("USDT", "")
    L = it["arah"] == "LONG"
    out = []
    if not it.get("ikut"):
        if not jp:
            return out
        it["ikut"], it["tp_jalur"] = jp["jalur"], jp.get("tp")
        it["tp1"] = it["tp2"] = jp.get("tp") or it["entry"] * (100 if L else 0.01)
        out.append(f"🔄 <b>{it['sym']} {it['arah']}</b>\n↳ Posisi ini dari jalur {jp['nama']}. TP1 dan TP2 umum dihapus, "
                   f"sekarang ikut aturan jalur: SL berjalan {fp(jp['sl'], t)}, {_tp_teks(jp.get('tp'), t)}. "
                   f"Uji 2021-2026: aturan jalur +4568R, TP1/TP2 umum +2371R. Samakan di Bybit: "
                   f"/modify {kd} sl {fp(jp['sl'], t)}")
    if jp:
        lebih = (jp["sl"] > it["sl"]) if L else (jp["sl"] < it["sl"])
        if lebih and not it.get("sl_manual"):
            it["sl"] = jp["sl"]
    elif "jalur_keluar" not in it["alert"]:
        it["alert"].append("jalur_keluar")
        cl = _jalur_tutup(it["sym"], it["arah"])
        why = {"SL": "SL berjalan tersentuh", "TP": "TP tersentuh", "WAKTU": "batas waktu habis"}.get((cl or {}).get("status"), "aturan keluar")
        out.append(f"🚨 <b>TUTUP SEKARANG  ·  {it['sym']} {it['arah']}</b>\n↳ Jalur keluar karena {why}"
                   + (f", hasil jalur {cl['R']:+.2f}R" if cl and cl.get("R") is not None else "")
                   + f". Tutup posisi di Bybit dengan MARKET sekarang, lalu catat: /tutup {kd} HARGA. "
                   f"Posisi yang ditahan setelah jalur keluar sudah di luar aturan yang diuji.")
    return out


def _jalur_tutup(sym, arah):
    """Catatan keluar terakhir jalur robot untuk koin dan arah ini."""
    cl = []
    try:
        import qse_ichimoku as IC
        cl += IC.lihat().get("closed", [])
    except Exception:
        pass
    try:
        import qse_ob as OB
        cl += OB.lihat().get("closed", [])
    except Exception:
        pass
    try:
        import qse_strat as ST
        for k in ST.STRAT:
            cl += ST.lihat(k).get("closed", [])
    except Exception:
        pass
    cl = [c for c in cl if c.get("sym") == sym and c.get("arah", "LONG") == arah]
    return max(cl, key=lambda c: c.get("selesai", 0)) if cl else None


def tren_teks(sym):
    """Arah objektif: close 4J terakhir terhadap EMA 50 dan EMA 200. Sama dengan patokan notif arah BTC."""
    try:
        import qse_strat as ST
        df = ST._k4(sym, 400)
        c = df["close"].values.astype(float)
        e50, e200 = float(ST._ema(c, 50)[-1]), float(ST._ema(c, 200)[-1])
        d = lambda e: "di atas" if c[-1] > e else "di bawah"
        return (f"{sym.replace('USDT', '')} 4J {d(e50)} EMA 50 ({(c[-1] / e50 - 1) * 100:+.1f}%) dan {d(e200)} EMA 200 "
                f"({(c[-1] / e200 - 1) * 100:+.1f}%)")
    except Exception:
        return ""


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
            if not r or it.get("ikut") or str(it.get("jalur", "")) in JALUR_TERBUKTI():
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
            aktif = {k for k, _ in kasus}
            it["alert"] = [a for a in it["alert"] if a not in ("btc", "bias", "lawan", "rapor") or a in aktif]
            for k, txt in kasus:
                if k not in it["alert"]:
                    it["alert"].append(k)
                    saran = ("Kalau posisi sudah jalan, tahan sesuai SL dan TP (uji: keluar lebih awal menurunkan profit)."
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
    """WR per periode, plus hasil dalam persen modal dan USDT (dari /modal), dipisah total untung dan total rugi."""
    try:
        import qse_modal as MD
        m = MD.lihat()
        risk_pct, ln = (m["risk"], MD.lot_normal()) if m["modal"] > 0 else (None, 0)
    except Exception:
        risk_pct, ln = None, 0
    rows = [f"<b>{judul}</b>"]
    for nama, a in _periode():
        cl = [c for c in closed if c.get("why") in why_ok and c.get("closed_ts", 0) >= a]
        n = len(cl)
        w = sum(1 for c in cl if c["result_r"] > 0)
        net = sum(c["result_r"] for c in cl)
        up = sum(c["result_r"] for c in cl if c["result_r"] > 0)
        dn = sum(c["result_r"] for c in cl if c["result_r"] < 0)
        teks = f"{'🟩' if net > 0 else '🟥' if net < 0 else '⬜'} <b>{nama.capitalize()}</b>: {n} trade  ·  WR {w / n * 100 if n else 0:.0f}%  ·  {net:+.2f}R"
        if risk_pct:
            teks += (f"\n     {'PROFIT' if net >= 0 else 'RUGI'} {net * risk_pct:+.2f}% modal ({net * ln:+,.2f} USDT)"
                     f"\n     untung +{up * risk_pct:.2f}% (+{up * ln:,.2f} USDT)  ·  rugi -{abs(dn) * risk_pct:.2f}% (-{abs(dn) * ln:,.2f} USDT)")
        else:
            teks += f"\n     untung +{up:.2f}R  ·  rugi -{abs(dn):.2f}R"
        rows.append(teks)
    if not risk_pct:
        rows.append("Isi /modal 1000 risk 0.25 supaya hasil tampil dalam persen modal dan USDT.")
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


def _peta_robot():
    """Hasil scan 4J terakhir per koin, dibaca sekali."""
    try:
        with open(HASIL) as f:
            return {r["symbol"]: r for r in json.load(f) if r.get("tf", "240") == "240"}
    except Exception:
        return {}


def baris_pasar():
    """Kondisi BTC dan berita yang dipakai robot sebelum memberi sinyal."""
    naik, ch3 = btc_1j()
    rb = ramal_btc4()
    bd = berita_depan(3)
    b1 = "-" if naik is None else f"{'naik' if naik else 'turun'} ({ch3:+.1f}% 3 jam)"
    b4 = "-"
    if rb:
        up = rb["p_up"]
        b4 = f"peluang naik {up:.0f}% ({'condong naik' if up >= 55 else 'condong turun' if up <= 45 else 'seimbang'})"
    br = "tidak ada"
    if bd:
        try:
            import qse_berita as BR
            br = f"{bd['judul']} jam {BR.jam_wib(bd['ts'])[6:]}"
        except Exception:
            br = bd["judul"]
    try:
        import qse_strat as ST
        b50 = ST.btc_ema50_teks()
    except Exception:
        b50 = ""
    bt = btc_teknik()
    return (f"🌐 Pasar: {b50 or 'BTC 4J -'} | " + (f"{bt} | " if bt else "") + f"BTC 1 jam {b1} | berita besar 3 jam ke depan: {br}"
            " | Arah BTC hanya info: uji 2021-2026, ikut arah BTC tidak menaikkan hasil jalur terbukti")


def _hasil_di(it, lv, jenis):
    """Total R seluruh trade kalau harga sampai level ini. TP1 menutup separuh sisa, TP2 dihitung lewat TP1 dulu."""
    sisa, real = _sisa(it), _real(it)
    if jenis in ("SL", "TPJ"):
        return real + sisa * _r_at(it, lv)
    if jenis == "TP1":
        return real + 0.5 * sisa * _r_at(it, lv)
    if it["status"] == "TP1":
        return real + sisa * _r_at(it, lv)
    return real + 0.5 * sisa * _r_at(it, it["tp1"]) + 0.5 * sisa * _r_at(it, lv)


def _usdt(R):
    try:
        import qse_modal as MD
        ln = MD.lot_normal()
    except Exception:
        ln = 0
    return f" ({R * ln:+,.1f} USDT)" if ln > 0 else ""


def blok_posisi(no, it, px, r=None, pasar=None):
    """Satu posisi di /status: asal saran, floating, jarak dan hasil di SL TP1 TP2 dengan perkiraan waktu,
    analisa sekarang dengan alasannya, dan risiko dekat (BTC 1 jam, berita 3 jam)."""
    t = it.get("tick") or tick_of(None, it["entry"])
    arah = it["arah"]
    L = arah == "LONG"
    n_gab = len(it.get("gabung", []))
    rows = [GARIS, f"{'🟢' if L else '🔴'} <b>{no}. {it['sym']} {arah}</b>  ·  {it.get('order', '')}"
            + (f"  ·  gabungan {n_gab + 1} entry" if n_gab else ""), GARIS]
    jalur, pola = it.get("jalur", "manual"), it.get("pola", "manual")
    rows.append("📍 Asal: " + ("manual, bukan dari saran robot" if jalur == "manual" else f"{jalur} ({pola})"))
    sisa = _sisa(it)
    nm = NM_POS.get(it["status"], it["status"])
    if it["status"] == "TP1" and it.get("sl_manual"):
        nm = f"sudah TP1, SL manual {fp(it['sl'], t)}"
    rows.append(f"📍 Status: {nm}" + (f"  ·  ukuran {sisa:.2f}x lot awal" if abs(sisa - 1) > 0.005 else ""))
    rows.append(f"📍 Entry {fp(it['entry'], t)}  ·  harga sekarang {fp(px, t) if px else '-'}")
    fl = floating(it, px)
    if fl:
        teks = f"{'🟩 Floating UNTUNG' if fl['r'] >= 0 else '🟥 Floating RUGI'} {fl['pct']:+.2f}%  ·  total {fl['r']:+.2f}R{_usdt(fl['r'])}"
        if fl["roe"] is not None:
            teks += f"  ·  ROE {fl['roe']:+.1f}% di {fl['lev']:g}x"
        rows.append(teks)
        if abs(fl["real"]) > 0.005:
            rows.append(f"💰 Sudah direalisasi {fl['real']:+.2f}R")
    elif it["status"] == "MENUNGGU" and px:
        rows.append(f"⏳ Jarak harga ke entry {abs(px - it['entry']) / it['entry'] * 100:.2f}%")
    jalan = it["status"] in ("TERISI", "TP1")
    acuan = px if (jalan and px) else it["entry"]
    a = (r or {}).get("atr") or it.get("atr") or 0
    sl_now = it["entry"] if it["status"] == "TP1" and not it.get("sl_manual") else it["sl"]
    lv = [("🛑", "SL" + (" (di entry)" if sl_now == it["entry"] and it["status"] == "TP1" else ""), sl_now, "SL")]
    if it.get("ikut"):
        lv[0] = ("🛑", "SL berjalan jalur", sl_now, "SL")
        if it.get("tp_jalur"):
            lv.append(("🏁", "TP jalur (tutup penuh)", it["tp_jalur"], "TPJ"))
    else:
        if it["status"] != "TP1":
            lv.append(("🎯", "TP1", it["tp1"], "TP1"))
        lv.append(("🏁", "TP2", it["tp2"], "TP2"))
    rows.append("📏 <b>Level</b>")
    for ik, nama, harga_lv, jenis in lv:
        R = _hasil_di(it, harga_lv, jenis)
        w = teks_waktu(estimasi_jam(harga_lv - acuan, a, 4)) if (jalan and a) else ""
        dari_e = (harga_lv - it["entry"]) / it["entry"] * 100
        sisa_txt = f"  ·  sisa {(harga_lv - acuan) / acuan * 100:+.2f}%" if (jalan and px) else ""
        rows.append(f"{ik} {nama} {fp(harga_lv, t)}  ·  dari entry {dari_e:+.2f}%{sisa_txt}\n"
                    f"     kena: {R:+.2f}R{_usdt(R)}" + (f"  ·  perkiraan {w}" if w else ""))
    if jalan:
        if it.get("ikut") or str(it.get("jalur", "")) in JALUR_TERBUKTI():
            rows.append("🛠 <b>Aturan</b>: tahan sampai SL atau TP jalur. Jangan keluar lebih awal. Uji 2021-2026: keluar di -0.4R "
                        "profit turun 37%, tutup setengah turun 18%, keluar saat analisa berbalik turun 22%.")
            return "\n".join(rows)
        try:
            an = analisa_lengkap(it, r, px or None)
            ik = {"MASIH SESUAI ANALISA": "✅", "MELEMAH": "⚠️", "BERBALIK": "🛑"}.get(an["vonis"], "🧭")
            rows.append(f"🧭 <b>Analisa sekarang: {ik} {an['vonis']}</b>"
                        + (f" (saat entry {it['nilai']})" if it.get("nilai") else ""))
            rows.append(f"🛠 <b>Saran</b>: {an['aksi']}")
            if an["vonis"] == "MASIH SESUAI ANALISA":
                if an["plus"]:
                    rows += ["💡 <b>Kenapa</b>"] + [f"• {z}" for z in an["plus"][:3]]
                if an["minus"]:
                    rows += ["⚠️ <b>Waspada</b>"] + [f"• {z}" for z in an["minus"][:3]]
            else:
                kenapa = ([an["harga"]] if an["harga"] else []) + an["minus"]
                rows += ["💡 <b>Kenapa</b>"] + [f"• {z}" for z in (kenapa[:4] or ["faktor pendukung berkurang"])]
                if an["plus"]:
                    rows += ["👍 <b>Yang masih mendukung</b>"] + [f"• {z}" for z in an["plus"][:2]]
        except Exception as ex:
            print("[WARN] analisa posisi", ex)
        dekat = []
        naik, ch3 = (pasar or {}).get("btc1", (None, 0.0))
        if naik is not None and naik != L:
            dekat.append(f"BTC 1 jam {'naik' if naik else 'turun'} ({ch3:+.1f}% 3 jam) melawan posisi ini")
        bd = (pasar or {}).get("berita")
        if bd:
            dekat.append(f"berita besar {bd['judul']} dalam 3 jam, pertimbangkan geser SL ke entry kalau sudah untung")
        if dekat:
            rows += ["⏰ <b>Risiko dekat</b>"] + [f"• {z}" for z in dekat]
    return "\n".join(rows)


def status_saya(harga=None):
    d = _load()
    harga = harga if harga is not None else harga_semua()
    op = list(d["open"].values())
    blok = [f"{GARIS}\n👤 <b>TRADE KAMU ({len(op)})</b>"]
    pasar = {}
    if not op:
        blok.append("Tidak ada trade terbuka.")
    else:
        pasar = dict(btc1=btc_1j(), berita=berita_depan(3))
        ket = ["🌐 <b>PASAR</b>\n" + "\n".join("• " + z.strip() for z in baris_pasar().replace("🌐 Pasar: ", "").split(" | ")),
               "ℹ️ Dari entry = jarak level dari harga entry. Sisa = jarak dari harga sekarang. "
               "Kena = hasil seluruh trade kalau harga sampai level itu (TP1 menutup separuh)."]
        try:
            import qse_modal as MD
            if MD.lot_normal() > 0:
                ket.append(f"1R = {MD.lot_normal():,.2f} USDT (risiko per trade di /modal)")
        except Exception:
            pass
        blok.append("\n".join(ket))
    peta = _peta_robot() if op else {}
    tot = 0.0
    ada_fl = False
    for i, it in enumerate(op, 1):
        px = harga.get(it["sym"], 0.0)
        blok.append(blok_posisi(i, it, px, peta.get(it["sym"]), pasar))
        fl = floating(it, px)
        if fl:
            tot += fl["r"]
            ada_fl = True
    if ada_fl:
        blok.append(f"{GARIS}\n{'🟩' if tot >= 0 else '🟥'} <b>Total floating: {tot:+.2f}R{_usdt(tot)}</b>")
    blok.append(f"{GARIS}\n" + ringkas_rapi("📈 WR TRADE KAMU", d["closed"]))
    blok.append(wr_jalur(d["closed"]))
    return "\n\n".join(blok)


URUT_JALUR = ("saran utama", "saran 1J", "saran cadangan", "saran cadangan 2", "saran fib", "saran siklus", "saran GZH",
              "saran momentum", "saran news", "saran ichimoku", "manual")


def wr_jalur(closed, hari=30):
    """WR 30 hari trade kamu dipisah menurut asal entry."""
    a = int(time.time() * 1000) - hari * 86400000
    rows = [f"🗂 <b>Menurut asal entry ({hari} hari)</b>"]
    sel = [c for c in closed if c.get("why") in ("SL", "BE", "TP2", "TUTUP") and c.get("closed_ts", 0) >= a]
    ada = {c.get("jalur", "manual") for c in sel}
    for j in [j for j in URUT_JALUR if j in ada] + sorted(ada - set(URUT_JALUR)):
        x = [c for c in sel if c.get("jalur", "manual") == j]
        w = sum(1 for c in x if c["result_r"] > 0)
        rows.append(f"• {j.capitalize()}: {len(x)} trade  ·  WR {w / len(x) * 100:.0f}%  ·  {sum(c['result_r'] for c in x):+.2f}R")
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
    """Pengali lot dari hasil trade kamu sendiri. Baru menyesuaikan setelah 10 trade di jalur itu.
    Jalur terbukti memakai lot dari bukti uji 5 tahun, tidak diubah oleh beberapa trade pribadi."""
    if jalur in JALUR_TERBUKTI():
        try:
            return lot_angka(boleh_ikut(jalur)[3])
        except Exception:
            return 1.0
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
    ada = {c.get("jalur", "manual") for c in cl}
    for j in [j for j in URUT_JALUR if j in ada or j in LOT_DASAR]:
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


def analisa_lengkap(it, r=None, px=None):
    """Apakah trade kamu masih sesuai analisa robot. Semua faktor dari scan 4J terakhir, jadi vonis hanya berubah
    saat scan baru, tidak naik turun tiap menit. Return dict(vonis, aksi, skor, plus, minus, harga)."""
    r = r or hasil_robot(it["sym"])
    px = px or harga_live(it["sym"])
    if not r:
        return dict(vonis="TIDAK ADA DATA", aksi="Pantau manual.", skor=0, plus=[], minus=["koin belum ada di scan terakhir"],
                    harga="")
    arah = it["arah"]
    L = arah == "LONG"
    p = r.get("pasar") or {}
    a = r["atr"] or 1e-12
    t = r["tick"]
    skor, plus, minus = 0, [], []
    if p.get("arah") == arah:
        skor += 1
        plus.append(f"bias robot masih {arah}")
    elif p.get("arah"):
        skor -= 2
        minus.append(f"bias robot berbalik ke {p['arah']}")
    izin = r.get("izin", "")
    if izin == "LONG dan SHORT" or izin.startswith(arah):
        skor += 1
        plus.append("BTC 4J mengizinkan arah ini")
    else:
        skor -= 1
        minus.append(f"BTC 4J melawan, yang diizinkan {izin}")
    eks = [x for x in r["saran"] if x["eksekusi"]]
    if any(x["arah"] == arah for x in eks):
        skor += 1
        plus.append("ada saran robot EKSEKUSI searah")
    if any(x["arah"] != arah for x in eks):
        skor -= 2
        minus.append("ada saran robot EKSEKUSI berlawanan")
    if p.get("zona_searah") and p.get("arah") == arah:
        skor += 1
        plus.append("harga di zona emas searah")
    if (L and px and px < p.get("batal", 0)) or ((not L) and px and px > p.get("batal", 1e18)):
        skor -= 2
        minus.append(f"struktur patah, harga tembus batas {fp(p['batal'], t)}")
    if r.get("skill"):
        nk = SK.konfirmasi(r["skill"], arah)[0]
        if nk >= 5:
            skor += 1
            plus.append(f"skill tambahan searah {nk}/8")
        elif nk <= 2:
            skor -= 1
            minus.append(f"skill tambahan lemah {nk}/8")
    sk = r.get("siklus") or {}
    if sk.get("c4P") is not None:
        c4 = sk["c4P"]
        if (c4 >= 55) if L else (c4 <= 45):
            skor += 1
            plus.append(f"peluang koin 4 jam searah ({c4:.0f}% naik)")
        elif (c4 <= 45) if L else (c4 >= 55):
            skor -= 1
            minus.append(f"peluang koin 4 jam melawan ({c4:.0f}% naik)")
    fl = (sk.get("aliran") or {}).get("skor")
    if fl is not None:
        if (fl >= 2) if L else (fl <= -2):
            skor += 1
            plus.append("aliran dana searah")
        elif (fl <= -2) if L else (fl >= 2):
            skor -= 1
            minus.append("aliran dana melawan")
    harga = ""
    if px:
        g = ((px - it["entry"]) if L else (it["entry"] - px)) / a
        if g < 0:
            harga = (f"harga {abs(g):.1f} ATR melawan entry, " +
                     ("masih dalam gerak normal 4J" if abs(g) < 1 else "sudah di luar gerak normal 4J"))
    if it.get("ikut") or str(it.get("jalur", "")) in JALUR_TERBUKTI():
        vonis = "MASIH SESUAI ANALISA" if skor >= 3 else "MELEMAH" if skor >= 0 else "BERBALIK"
        return dict(vonis=vonis, aksi="Ikuti aturan jalur terbukti: diam, biarkan SL berjalan dan TP jalur bekerja. Vonis ini info saja, "
                    "uji 2021-2026 keluar atau geser SL ke entry lebih awal menurunkan profit.",
                    skor=skor, plus=plus, minus=minus, harga=harga)
    if skor >= 3:
        vonis, aksi = "MASIH SESUAI ANALISA", "Tahan. Biarkan SL dan TP bekerja."
    elif skor >= 0:
        vonis, aksi = "MELEMAH", "Tahan dengan SL tetap, jangan tambah lot. Kalau sudah untung, geser SL ke entry."
    else:
        vonis, aksi = "BERBALIK", (f"Pertimbangkan kurangi risiko: /sl {it['sym'].replace('USDT', '')} {arah.lower()} 50% "
                                   f"atau geser SL lebih dekat dengan /modify.")
    return dict(vonis=vonis, aksi=aksi, skor=skor, plus=plus, minus=minus, harga=harga)


def analisa_posisi(it, r=None, px=None):
    """Bentuk lama: (vonis, alasan, aksi, skor). Alasan yang melawan ditaruh paling depan."""
    a = analisa_lengkap(it, r, px)
    return a["vonis"], ([a["harga"]] if a["harga"] else []) + a["minus"] + a["plus"], a["aksi"], a["skor"]


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


_BTC1 = {}


def btc_1j():
    """Arah BTC 1 jam: close candle tutup terakhir di atas EMA20 = naik. Return (naik|None, ubah 3 jam %).
    Ukuran yang SAMA dipakai gerbang sinyal dan peringatan dini, jadi sinyal tidak lahir melawan BTC lalu langsung diperingatkan."""
    if time.time() - _BTC1.get("t", 0) < 60:
        return _BTC1["naik"], _BTC1["ch3"]
    try:
        btc = _kline("BTCUSDT", "60", 60)
        cls = [x[3] for x in btc[:-1]]
        naik = cls[-1] > _ema(cls[-40:], 20)
        ch3 = (cls[-1] / cls[-4] - 1) * 100 if len(cls) > 4 else 0.0
    except Exception:
        naik, ch3 = None, 0.0
    _BTC1.update(t=time.time(), naik=naik, ch3=ch3)
    return naik, ch3


_AKTIF = {}


def arah_aktif(sym):
    """Semua arah yang sedang aktif di koin ini dari SEMUA jalur: trade kamu, saran robot (utama, 1J, cadangan,
    fib, siklus), momentum dan news, Ichimoku, dan GZH yang menunggu candle tutup. Return list (arah, asal).
    Peta semua koin dibangun sekali per 30 detik supaya loop sinyal tidak membaca file berulang."""
    if time.time() - _AKTIF.get("t", 0) >= 30:
        peta = {}
        tambah = lambda sy, ar, asal: peta.setdefault(sy, []).append((ar, asal))
        for v in _load()["open"].values():
            tambah(v["sym"], v["arah"], "trade kamu")
        try:
            import qse_fixprofit as FX
            for v in FX.load()["open"].values():
                if v["status"] in ("MENUNGGU", "TERISI", "TP1"):
                    tambah(v["sym"], v["arah"], "saran robot")
        except Exception:
            pass
        try:
            import qse_catat as CT
            for v in CT._baca()["open"]:
                tambah(v["sym"], v["arah"], "saran " + v["jalur"])
        except Exception:
            pass
        try:
            import qse_ichimoku as IC
            for v in IC.lihat()["open"].values():
                tambah(v["sym"], v["arah"], "Ichimoku")
        except Exception:
            pass
        try:
            import qse_ob as OB
            for v in OB.lihat()["open"].values():
                tambah(v["sym"], "LONG", "Order Block")
        except Exception:
            pass
        try:
            import qse_strat as ST
            for k, cfg in ST.STRAT.items():
                for v in ST.lihat(k)["open"].values():
                    tambah(v["sym"], v["arah"], cfg["nama"])
        except Exception:
            pass
        try:
            import qse_alarm as AL
            for a in AL._lihat()["list"]:
                if a.get("jenis") == "gzh":
                    tambah(a["sym"], "LONG" if a["L"] else "SHORT", "GZH")
        except Exception:
            pass
        _AKTIF.update(t=time.time(), peta=peta)
    return list(_AKTIF["peta"].get(sym, []))


def cek_lintas(sym, arah):
    """Penjaga yang sama untuk semua jalur: jangan membalik arah koin yang masih aktif di jalur mana pun,
    dan jangan buka sinyal baru 3 jam sebelum berita besar USD. Return alasan ditahan, kosong bila lolos."""
    lawan = next((asal for a, asal in arah_aktif(sym) if a != arah), None)
    if lawan:
        return f"masih ada {('LONG' if arah == 'SHORT' else 'SHORT')} aktif di koin ini ({lawan}), robot tidak membalik arah"
    bd = berita_depan(3)
    if bd:
        return f"berita besar {bd['judul']} dalam 3 jam"
    return ""


_BD = {}


def berita_depan(jam=3):
    """Berita besar USD dalam `jam` ke depan (kalender ekonomi). None bila tidak ada.
    Kalender dibaca paling sering sekali per menit, gagal pun ditunggu, supaya loop sinyal tidak tertahan."""
    now = int(time.time() * 1000)
    if now - _BD.get("t", 0) >= 60000:
        _BD["t"] = now
        try:
            import qse_berita as BR
            _BD["kal"] = BR.kalender()
        except Exception:
            _BD.setdefault("kal", [])
    return next((e for e in _BD.get("kal", []) if 0 < e["ts"] - now <= jam * JAM), None)


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
    btc_naik, ch3 = btc_1j()
    st_btc = d.get("btc_1j")
    # Peringatan "BTC 1 jam berbalik" dimatikan. Uji 2021-2026 (35 ribu trade jalur terbukti): BTC 1J berbalik melawan
    # di 94% trade, jadi bukan tanda bahaya. Geser SL ke entry saat itu menurunkan profit 18%, tutup setengah 39%, tutup penuh 78%.
    if False:
        kena = []
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
        else:                     # tingkat 1 (mulai melawan) dimatikan: gerak normal, tidak perlu aksi
            lv = 0
        if lv <= lv_lama:
            continue
        kd = it["sym"].replace("USDT", "")
        ar = it["arah"].lower()
        t = it.get("tick") or 1e-8
        sl_now = it["entry"] if it["status"] == "TP1" and not it.get("sl_manual") else it["sl"]
        # Uji 2021-2026 jalur terbukti: tutup setengah di -0.4R profit turun 18%, keluar di -0.4R turun 37%,
        # tutup setengah di -0.7R turun 9%, keluar di -0.7R turun 19%. Yang terbaik: diam, biarkan SL bekerja.
        if lv == 2:
            sar = ("Diam, biarkan SL bekerja. Jangan geser SL menjauh. Uji 5 tahun: keluar atau kurangi lot di titik ini "
                   "menurunkan profit 18 sampai 37%.")
        else:
            sar = ("Diam, biarkan SL bekerja. Jangan geser SL menjauh. Uji 5 tahun: keluar di titik ini menurunkan profit 19%, "
                   "karena sebagian posisi balik untung.")
        judul = {2: "RUGI MEMBESAR, TETAP TAHAN", 3: "DEKAT SL, TETAP TAHAN"}[lv]
        pesan.append(f"{'⚠️' if lv < 3 else '🚨'} <b>{it['sym']} {it['arah']} {judul}</b> (tingkat {lv} dari 3)\n"
                     f"Entry {fp(it['entry'], t)} | sekarang {fp(px, t)} | SL {fp(sl_now, t)}\n"
                     f"Rugi berjalan -{pct:.2f}% atau -{ke_sl:.2f}R ({ke_sl * 100:.0f}% jalan ke SL)\n"
                     + (f"Penyebab: {', '.join(alasan)}\n" if alasan else "")
                     + f"Saran: {sar}")
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
GZH_MAKS_HARI = 4        # sinyal sentuh GZH paling banyak per hari (WIB), supaya tidak banjir saat pasar bergerak serentak
GZH_SKOR_DEKAT = 80      # (lama) peringatan MENDEKAT hanya untuk setup skor tinggi
_BTC_GZ = {}


def gzh_searah(arah, close, e200):
    """Syarat GZH dari uji 6 tahun 111 koin: searah tren besar (close vs EMA 200 4J) dan searah BTC 4J (close vs EMA 50).
    Return (lolos, alasan)."""
    L = arah == "LONG"
    if e200 and ((close > e200) != L):
        return False, f"lawan tren besar (harga {'di bawah' if L else 'di atas'} EMA 200)"
    if time.time() - _BTC_GZ.get("t", 0) > 600:
        try:
            import qse_strat as ST
            _BTC_GZ.update(t=time.time(), naik=ST.btc_naik())
        except Exception:
            _BTC_GZ.update(t=time.time(), naik=None)
    bn = _BTC_GZ.get("naik")
    if bn is not None and bn != L:
        return False, f"BTC 4J {'turun' if L else 'naik'} (di {'bawah' if L else 'atas'} EMA 50)"
    return True, ""


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
    sinyal = st.get("sinyal", {})          # sinyal GZH terkirim, untuk asal entry dan skor di /status
    hari = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600))
    jatah = st.get("jatah", {}) if st.get("jatah", {}).get("hari") == hari else {"hari": hari, "n": 0}
    now = time.time()
    out = []
    try:
        cal.sort(key=lambda r: -nilai_gzh(r)[0])          # jatah harian dipakai setup skor tertinggi dulu
    except Exception:
        pass
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
                if (TAMPIL_SEMUA or gzh_searah(ar0, r["close"], r.get("e200"))[0]) and jatah["n"] < GZH_MAKS_HARI:
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
        ok_s, why_s = gzh_searah(arah, px, r.get("e200"))
        if not TAMPIL_SEMUA and not ok_s:
            print(f"[GZH] {sym} {arah} disentuh, tidak dikirim: {why_s}")
            continue
        why = cek_lintas(sym, arah)
        if why:
            print(f"[GZH] {sym} {arah} ditahan: {why}")
            continue
        if jatah["n"] >= GZH_MAKS_HARI:
            print(f"[GZH] {sym} skor {skor} tidak dikirim, jatah {GZH_MAKS_HARI} sinyal hari ini habis")
            continue
        jatah["n"] += 1
        koin[sym] = int(now)
        a = g.get("atr") or r["atr"]
        sl = lv["1.0"] - 0.2 * a if L else lv["1.0"] + 0.2 * a
        sinyal[sym] = dict(arah=arah, entry=e, sl=sl, tp1=lv["0.0"], tp2=lv["0.0"], skor=skor, t=int(now))
        _, tkb, ik, lot_b = boleh_ikut("saran GZH", arah, skor)
        jam_k = time.strftime("%H:%M", time.gmtime((int(now // 14400) + 1) * 14400 + 7 * 3600))
        out.append(f"👀 <b>GZH DISENTUH  ·  {sym} {arah}</b>\n"
                   f"Belum entry. Tunggu candle 4J tutup jam {jam_k} WIB.\n"
                   f"Kalau tutup {'di atas' if L else 'di bawah'} {fp(e, t)} dan masih searah tren dan BTC, robot kirim "
                   f"GZH TERKONFIRMASI dengan entry dan SL.")
        try:
            import qse_alarm as _AL
            _AL.tambah_gzh(sym, L, e, sl, lv["0.0"], lv["0.0"], t, skor=skor, wr=bt.get("wr"), dikirim=True)
        except Exception as ex:
            print("[WARN] gzh tunggu", ex)
    batas = now - 7 * 86400
    with open(fpath + ".tmp", "w") as f:
        json.dump(dict(px=px_lama, sudah={k: v for k, v in sudah.items() if v > batas},
                       dekat={k: v for k, v in dekat.items() if v > batas},
                       koin={k: v for k, v in koin.items() if v > batas},
                       sinyal={k: v for k, v in sinyal.items() if v["t"] > now - 3 * 86400}, jatah=jatah), f)
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


def kartu_sl(tidur=False):
    """Kartu SL terbaru semua posisi kamu, dipakai untuk pin SL tiap 4J, /tidur, dan pesan jam 22:00 WIB.
    Uji 2021-2026 jalur trailing (Ichimoku, EMA, RSI, MSB, 16.7 ribu trade, data 1 jam):
    geser SL tiap candle 4J +1933R PF 1.26, geser terlewat saat tidur 22-06 WIB +2102R PF 1.28,
    Trailing Stop Bybit jarak tetap 3 ATR +2474R PF 1.31. Return (teks, tanda) atau ("", None)."""
    jalan = [it for it in _load()["open"].values() if it["status"] in ("TERISI", "TP1")]
    if not jalan:
        return "", None
    rows, tanda = [], []
    for it in sorted(jalan, key=lambda v: v["sym"]):
        t = it.get("tick") or 1e-8
        jp = jalur_posisi(it["sym"], it["arah"])
        sl = jp["sl"] if jp else it["sl"]
        L = it["arah"] == "LONG"
        if not jp and not it.get("sl_manual") and it["status"] == "TP1":
            sl = it["entry"]
        tanda.append((it["sym"], it["arah"], round(sl, 10)))
        ik = "🟢" if L else "🔴"
        if jp and not jp.get("tp"):
            jarak = (jp.get("trail_atr", 3.0) / jp.get("sl_atr", 2.0)) * (jp.get("risk") or abs(jp["entry"] - jp.get("sl0", jp["sl"])))
            rj = jp.get("risk") or abs(jp["entry"] - jp.get("sl0", jp["sl"]))
            if jp.get("trail_pct_2r") and jp.get("best") and abs(jp["best"] - jp["entry"]) >= 2 * rj:
                jarak = jp["trail_pct_2r"] * jp["entry"]          # MSB setelah untung 2R: trailing 5% harga
            rows.append(f"{ik} <b>{it['sym']} {it['arah']}</b>  ·  {TG_e(jp['nama'])}\n"
                        f"<pre>{it['sym']} {it['arah']}\nSL       {fp(sl, t)}\nTrailing {fp(jarak, t)} ({jarak / it['entry'] * 100:.1f}%)</pre>\n"
                        f"Pasang Trailing Stop Bybit jarak {fp(jarak, t)}. Bybit menggeser SL sendiri, aman ditinggal tidur.")
        elif jp:
            rows.append(f"{ik} <b>{it['sym']} {it['arah']}</b>  ·  {TG_e(jp['nama'])}\n"
                        f"<pre>{it['sym']} {it['arah']}\nSL {fp(sl, t)}\nTP {fp(jp['tp'], t)}</pre>\n"
                        "SL dan TP tetap. Pastikan keduanya terpasang di Bybit, lalu tinggal saja.")
        else:
            rows.append(f"{ik} <b>{it['sym']} {it['arah']}</b>  ·  manual\n"
                        f"<pre>{it['sym']} {it['arah']}\nSL  {fp(sl, t)}\nTP1 {fp(it['tp1'], t)}\nTP2 {fp(it['tp2'], t)}</pre>\n"
                        "Pastikan SL terpasang di Bybit.")
    kepala = ("😴 <b>QSE v148 | SIAP TIDUR</b>\nCek tiap posisi di bawah, samakan di Bybit, lalu tinggal tidur."
              if tidur else "📌 <b>QSE v148 | SL TERBARU POSISI KAMU</b>\nDisematkan dan diperbarui tiap candle 4J tutup.")
    kaki = ("Kenapa aman: semua SL tersimpan di server Bybit, jalan walau HP mati. Uji 2021-2026: Trailing Stop Bybit "
            "+2474R, geser manual tiap 4J +1933R, geser terlewat saat tidur +2102R. Tidur tidak merugikan.\n"
            "Sinyal jam 23:00 dan 03:00 WIB masih bisa kamu ikuti pagi di laporan 07:05, selama harga masih dekat entry robot."
            ) if tidur else "Untuk jalur tanpa TP, Trailing Stop Bybit lebih bagus dari geser manual (uji 2021-2026: +2474R lawan +1933R)."
    return kepala + "\n\n" + "\n\n".join(rows) + "\n\n" + kaki, tanda


def TG_e(x):
    import telegram_notify as TG
    return TG.e(x)


def sinyal_jalur(jam=False):
    """/scan dan /sinyal4j: sinyal jalur terbukti yang bisa diikuti SEKARANG, aturan sama dengan pesan 4 jam:
    sinyal maks 2 candle 4J dan harga masih dalam 0.5R dari entry robot (EMA, RSI, McGinley, SnR, SMC, Ichimoku),
    MSB, Order Block, dan GZH hanya sinyal candle terakhir. Koin yang kamu pegang tidak ditampilkan."""
    import qse_strat as ST
    sumber = []
    try:
        import qse_ichimoku as IC
        sumber.append(("ichimoku", "Ichimoku", IC.lihat()["open"].values()))
    except Exception:
        pass
    try:
        import qse_ob as OB
        sumber.append(("orderblock", "Order Block", OB.lihat()["open"].values()))
    except Exception:
        pass
    for k, cfg in ST.STRAT.items():
        sumber.append((k, cfg["nama"], ST.lihat(k)["open"].values()))
    telat_ok = {"ema_short", "rsi_vol", "mcginley", "snr_vol", "smc_choch", "ichimoku"}
    pegang = {v["sym"] for v in _load()["open"].values() if v["status"] in ("TERISI", "TP1")}
    now = time.time()
    tutup = int(now // 14400) * 14400
    kartu = []
    for k, nama, items in sumber:
        for it in items:
            if it["sym"] in pegang:
                continue
            L = it["arah"] == "LONG"
            t = it.get("tick") or 1e-8
            baru = it.get("t", 0) >= tutup - 60
            px = harga_live(it["sym"]) or 0
            risk = it.get("risk") or abs(it["entry"] - it.get("sl0", it["sl"]))
            d = ((px - it["entry"]) * (1 if L else -1) / risk) if (px and risk) else None
            umur = (now - it.get("t", now)) / 14400
            sl = it["sl"]
            if baru and d is not None:
                baru = abs(d) <= 0.5 and ((px > sl) if L else (px < sl))       # harga sudah lari: tidak ditampilkan
            masih = (k in telat_ok and umur <= 2.1 and d is not None and abs(d) <= 0.5 and ((px > sl) if L else (px < sl))
                     and not (it.get("tp") and ((px >= it["tp"]) if L else (px <= it["tp"]))))
            if not (baru or masih):
                continue
            if it.get("tp"):
                tp = fp(it["tp"], t)
            else:
                jr = it.get("trail_atr", 3.0) / it.get("sl_atr", 2.0) * risk if risk else 0
                tp = (f"tanpa, Trailing Stop Bybit jarak {fp(jr, t)} ({jr / it['entry'] * 100:.1f}%)" if jr
                      else "tanpa, pakai SL berjalan")
            ket = "🆕 sinyal candle ini" if baru else f"harga masih dekat entry robot {fp(it['entry'], t)} ({d:+.2f}R)"
            if it.get("combo"):
                ket += f"  ·  ⭐ COMBO {len(it['combo']) + 1}"
            if it.get("combo_raja"):
                ket += "  ·  👑 COMBO RAJA"
            if it.get("combo_fix"):
                ket += "  ·  💎 COMBO FIX PROFIT"
            if it.get("combo_emas"):
                ket += "  ·  🏆 COMBO EMAS"
            if it.get("pullback"):
                ket += "  ·  🔁 pullback"
            if len(it.get("mutu_plus") or []) >= 3:
                ket += "  ·  💎 mutu tinggi"
            kartu.append((ST.prioritas(k, it), f"{'🟢' if L else '🔴'} <b>{it['sym']} {it['arah']}</b>  ·  {nama}  ·  MARKET  ·  {ket}\n"
                         f"<pre>{it['sym']} {it['arah']}\nEntry {fp(px or it['entry'], t)} MARKET\nSL    {fp(sl, t)}\nTP    {tp}</pre>"
                         + "".join("\n" + z for z in ST.batas_masuk_teks(it, k) + ST.tp_cepat_teks(it))))
    kepala = "📡 <b>QSE v148 | SINYAL JALUR TERBUKTI SEKARANG</b>"
    # order Tembus Trendline yang masih menunggu (STOP atau LIMIT, berlaku 24 jam): ikut ditampilkan supaya sama dengan cek per jam
    tunggu = []
    try:
        import qse_fixprofit as FX
        for v in FX.load()["open"].values():
            if v.get("status") != "MENUNGGU" or not v.get("tt") or v["sym"] in pegang:
                continue
            t = v.get("tick") or tick_of(None, v["entry"])
            px = harga_live(v["sym"]) or 0
            sisa = (v.get("exp_ts", 0) / 1000 - now) / 3600
            if sisa <= 0:
                continue
            jarak = f", harga sekarang {fp(px, t)} ({abs(px - v['entry']) / v['entry'] * 100:.1f}% dari entry)" if px else ""
            tunggu.append(f"⏳ <b>{v['sym']} {v['arah']}</b>  ·  Tembus Trendline  ·  order {v.get('order', '')} menunggu{jarak}, "
                          f"berlaku {sisa:.0f} jam lagi\n<pre>{v['sym']} {v['arah']}\nEntry {fp(v['entry'], t)} {v.get('order', '')}\n"
                          f"SL    {fp(v['sl'], t)}\nTP1   {fp(v['tp1'], t)}\nTP2   {fp(v['tp2'], t)}</pre>")
    except Exception as ex:
        print("[WARN] sinyal4j trendline", ex)
    blok_tunggu = ("\n\n⏳ <b>ORDER MENUNGGU TERISI</b> (Tembus Trendline, pasang order ini di Bybit, bukan MARKET)\n\n"
                   + "\n\n".join(tunggu)) if tunggu else ""
    kartu.sort(key=lambda z: z[0], reverse=True)          # prioritas: label terbukti dulu, lalu PF jalur
    kartu = [f"{ST.medali(i)} <b>PRIORITAS {i}</b>  ·  {ST.label_prioritas(p)}  ·  PF jalur {p[1]:.2f}\n{x}"
             for i, (p, x) in enumerate(kartu, 1)]
    if jam:          # dipakai cek per jam: hanya kartu yang masih valid, format sama dan bisa disalin (maks 5, pesan tidak terpotong)
        return "\n\n".join(kartu[:5]) + (f"\n\n+{len(kartu) - 5} sinyal valid lain, ketik /sinyal4j" if len(kartu) > 5 else "")
    if not kartu:
        return (kepala + "\nBelum ada sinyal MARKET jalur terbukti yang bisa diikuti di harga sekarang. Sinyal baru dikirim tiap "
                "candle 4J tutup (03, 07, 11, 15, 19, 23 WIB lewat 5 menit)." + blok_tunggu)
    return (kepala + "\nHanya sinyal yang masih valid di harga sekarang (dalam 0.5R dari entry robot dan belum lewat batas waktu), "
            "urut dari prioritas 1.\n\n" + "\n\n".join(kartu) + blok_tunggu)



def siaga_berita():
    """60-75 menit sebelum CPI atau FOMC: posisi yang sedang untung ditutup, yang rugi ditahan.
    Uji 2022-2026, 4366 posisi jalur terbukti yang melewati CPI/FOMC (data 1 jam):
    tahan semua +2439R, tutup semua 1 jam sebelum +2602R, tutup yang untung saja +2712R.
    Posisi rugi yang ditutup justru lebih jelek (-388R lawan -278R ditahan). Berita lain belum bisa diuji."""
    try:
        import qse_berita as BR
        kal = BR.kalender()
    except Exception:
        return []
    now = int(time.time() * 1000)
    ev = [e for e in kal if 60 * 60000 <= e["ts"] - now <= 75 * 60000
          and any(k in e["judul"].upper() for k in ("CPI", "FOMC", "FEDERAL FUNDS", "INTEREST RATE", "FED "))]
    if not ev:
        return []
    e = ev[0]
    kunci = f"siaga{e['ts']}"
    d = _load()
    if kunci in d.get("siaga", []):
        return []
    ubah(lambda dd: dd.update(siaga=(dd.get("siaga", []) + [kunci])[-50:]))
    jalan = [it for it in d["open"].values() if it["status"] in ("TERISI", "TP1")]
    if not jalan:
        return [f"📅 <b>{e['judul']}</b> sekitar 1 jam lagi. Tidak ada posisi jalan. Sinyal baru ditahan sampai 1 jam sesudah rilis."]
    rows = [f"📅 <b>{e['judul']}</b> sekitar 1 jam lagi.\nAturan teruji: posisi UNTUNG ditutup sekarang, posisi RUGI ditahan dengan SL tetap. "
            "Uji 2022-2026 (4366 posisi): tahan semua +2439R, tutup yang untung saja +2712R."]
    for it in jalan:
        px = harga_live(it["sym"])
        fl = floating(it, px) if px else None
        kd = it["sym"].replace("USDT", "")
        if fl and fl["r"] > 0:
            rows.append(f"✅ <b>{it['sym']} {it['arah']}</b> untung {fl['r']:+.2f}R. TUTUP sekarang dengan MARKET, lalu /tutup {kd} HARGA")
        else:
            rows.append(f"⏸️ <b>{it['sym']} {it['arah']}</b> " + (f"rugi {fl['r']:+.2f}R" if fl else "") + ". Tahan, biarkan SL bekerja.")
    return rows


def btc_teknik():
    """Kondisi BTC 4J menurut tiap teknik. Info saja. Uji 2021-2026: 6/6 naik diikuti BTC naik 24 jam kemudian 51.3%,
    sama dengan rata-rata semua candle (51.3%). 0/6 diikuti BTC turun 46.4%. Tidak meramal arah."""
    try:
        import numpy as np
        import qse_strat as ST
        import qse_ichimoku as IC
        df = ST._k4("BTCUSDT", 600)
        h, l, c = (df[k].values.astype(float) for k in ("high", "low", "close"))
        md = ST._mcginley(c[-600:])
        tk = (IC._hh(h, 9) + IC._ll(l, 9)) / 2
        kj = (IC._hh(h, 26) + IC._ll(l, 26)) / 2
        sa = ((tk + kj) / 2)[-27]
        sb = ((IC._hh(h, 52) + IC._ll(l, 52)) / 2)[-27]
        st = [("EMA50", c[-1] > ST._ema(c, 50)[-1]), ("EMA200", c[-1] > ST._ema(c, 200)[-1]),
              ("EMA20/50", ST._ema(c, 20)[-1] > ST._ema(c, 50)[-1]), ("McGinley", c[-1] > md[-1]),
              ("Ichimoku", c[-1] > np.nanmax([sa, sb])), ("RSI", ST._rsi(c)[-1] > 50)]
        n = sum(1 for _, v in st if v)
        return ("BTC 4J per teknik: " + ", ".join(f"{k} {'naik' if v else 'turun'}" for k, v in st)
                + f" = {n}/6 naik. Info kondisi saja: uji 2021-2026, 6/6 naik diikuti BTC naik 24 jam kemudian 51%, "
                  "sama dengan rata-rata, jadi tidak dipakai menyaring sinyal")
    except Exception as ex:
        print("[WARN] btc teknik", ex)
        return ""


def cek_jalur(sym, arah=None, entry=None):
    """/cek (21 Okt 2026): narasi singkat yang hanya memakai hal teruji. Gambaran koin, sinyal jalur dan validitasnya,
    posisi kamu, kesiapan combo dan mutu untuk LONG dan SHORT, waktu, lalu kesimpulan aksi."""
    import qse_strat as ST
    import qse_porto as PO
    px = harga_live(sym) or 0
    if not px:
        return f"Harga {sym} tidak ditemukan. Cek nama koinnya, contoh /cek SOL"
    t = tick_of(hasil_robot(sym), px)
    now = time.time()
    df = ST._k4(sym, 600)
    nama = sym.replace("USDT", "")
    rows = [f"<b>CEK {nama}</b>" + (f"  ·  rencana {arah}" if arah else "")]
    # 1. gambaran koin
    if df is not None and len(df) > 210:
        c = df["close"].values.astype(float)
        h, l, v = (df[k].values.astype(float) for k in ("high", "low", "volume"))
        e20, e50, e200 = ST._ema(c, 20)[-1], ST._ema(c, 50)[-1], ST._ema(c, 200)[-1]
        a = ST._atr(h, l, c)[-1]
        ch24 = (px / c[-7] - 1) * 100 if len(c) > 7 else 0
        vp = (v[-101:-1] <= v[-1]).mean() * 100
        besar = "naik" if px > e200 else "turun"
        pendek = "naik" if e20 > e50 else "turun"
        rows += ["", "📍 <b>GAMBARAN</b>",
                 f"Harga {fp(px, t)}, {ch24:+.1f}% dalam 24 jam. Tren besar {besar} (harga {'di atas' if px > e200 else 'di bawah'} "
                 f"EMA 200 4J), tren pendek {pendek} (EMA 20 {'di atas' if e20 > e50 else 'di bawah'} EMA 50)"
                 + (". Tren besar dan pendek searah." if besar == pendek else ", jadi sedang pullback atau awal pembalikan."),
                 f"Gerak normal per candle 4J sekitar {a / px * 100:.1f}% ({fp(a, t)}). Volume candle terakhir lebih besar dari "
                 f"{vp:.0f}% candle sebelumnya" + (", termasuk tinggi." if vp >= 80 else ".")]
    # 1b. tentang koin
    try:
        rows += ["", "📘 <b>TENTANG KOIN</b>"] + tentang_koin(sym, df, px)
    except Exception as ex:
        print("[WARN] tentang koin", ex)
    # 1c. berita terbaru
    try:
        import qse_news as NW
        bk = NW.berita_koin(sym)
        rows += ["", "📰 <b>BERITA TERBARU</b> (3 hari, info saja, bukan alasan entry)"] + (bk or ["Tidak ada berita penting tentang koin ini."])
    except Exception as ex:
        print("[WARN] berita koin", ex)
    # 2. sinyal jalur terbukti
    valid, lewat = [], []
    for it in jalur_aktif(sym):
        k = it["jalur"].replace("saran ", "")
        L = it["arah"] == "LONG"
        bm = ST.batas_masuk(it, k)
        sl_now = it.get("sl", it.get("sl0"))
        ok = bool(bm) and bm[0] <= px <= bm[1] and now <= bm[2] and ((px > sl_now) if L else (px < sl_now))
        lb = ST.label_nama(it)
        rj = it.get("risk") or abs(it["entry"] - it.get("sl0", it["sl"]))
        if it.get("tp"):
            keluar = f"TP {fp(it['tp'], t)}"
        else:
            jr = it.get("trail_atr", 3.0) / it.get("sl_atr", 2.0) * rj
            keluar = f"tanpa TP, Trailing Stop jarak {fp(jr, t)} ({jr / it['entry'] * 100:.1f}%)"
        judul = (f"{'🟢' if L else '🔴'} <b>{it['nama']} {it['arah']}</b>"
                 + (f"  ·  ⭐ {' + '.join(lb)}" if lb else ""))
        if ok:
            blok = (judul + f"\n<pre>{sym} {it['arah']}\nEntry {fp(px, t)} MARKET\nSL    {fp(sl_now, t)}\nTP    "
                    + (fp(it['tp'], t) if it.get("tp") else keluar) + "</pre>\n" + "\n".join(ST.batas_masuk_teks(it, k)))
            valid.append((ST.prioritas(k, it), blok, it["arah"]))
        else:
            why = ("sudah lewat batas waktu" if bm and now > bm[2] else
                   f"harga sudah {abs(px - it['entry']) / (rj or 1e-12):.1f}R dari entry robot" if bm else "sudah tidak valid")
            lewat.append(judul + f"\nEntry robot {fp(it['entry'], t)}, SL sekarang {fp(sl_now, t)}, {keluar}. "
                         f"Untuk entry baru {why}, jadi lewati. Kalau sudah pegang, ikuti SL dan TP jalur.")
    valid.sort(key=lambda z: z[0], reverse=True)
    rows += ["", "🎯 <b>SINYAL JALUR TERBUKTI</b>"]
    if valid:
        rows.append(f"Ada {len(valid)} sinyal yang masih valid di harga sekarang, urut dari prioritas tertinggi.")
        for _, x, _ in valid:
            rows += ["", x]
    if lewat:
        for x in lewat:
            rows += ["", x]
    if not valid and not lewat:
        rows.append("Belum ada. Tidak satu pun dari 10 teknik terbukti memberi sinyal di koin ini dalam 2 candle 4J terakhir.")
    # 3. posisi kamu
    pos = [v for v in _load()["open"].values() if v["sym"] == sym]
    if pos:
        rows += ["", "👤 <b>POSISI KAMU</b>"]
        for v in pos:
            fl = floating(v, px)
            rows.append(f"{v['arah']} {NM_ST.get(v['status'], v['status'])}, entry {fp(v['entry'], t)}, SL {fp(v['sl'], t)}"
                        + (f", berjalan {fl['r']:+.2f}R" if fl else "")
                        + (". Ikut aturan jalur, tahan sampai SL atau TP." if v.get("ikut") else "."))
    # 4. kesiapan sinyal
    rows += ["", "🔬 <b>KALAU NANTI MUNCUL SINYAL</b>"]
    for a in ([arah] if arah else ["LONG", "SHORT"]):
        try:
            _, mp, mm = ST.mutu(df, a)
            cb = ST._combo(df, "cek", a, ST.btc_naik(), sym) if df is not None else []
            jl = [x for x in cb if ST.nama_ke_kunci(x)]
            if ST.mutu_buang(mp, mm):
                mutu_t = f"mutu rendah ({', '.join(mm)}), sinyal {a} di candle ini akan dibuang robot"
            elif len(mp) >= 3:
                mutu_t = f"MUTU TINGGI ({', '.join(mp)})"
            else:
                mutu_t = (f"mutu normal, {len(mp)} dari 4 kondisi plus" + (f" ({', '.join(mp)})" if mp else "")
                          + (f", minus: {', '.join(mm)}" if mm else ""))
            if len(jl) >= 5:
                cb_t = f"sudah {len(jl)} teknik searah, sinyal baru bisa jadi COMBO RAJA"
            elif jl:
                cb_t = f"{len(jl)} teknik sudah searah ({', '.join(jl)}), sinyal baru akan ber-COMBO"
            else:
                cb_t = "belum ada teknik lain yang searah, sinyal baru kemungkinan tanpa label combo"
            rows.append(f"• {a}: {mutu_t}. Untuk combo, {cb_t}.")
        except Exception as ex:
            print("[WARN] cek mutu", ex)
    # 5. waktu
    nxt = (int(now // 14400) + 1) * 14400
    waktu = [f"Candle 4J berikutnya tutup jam {time.strftime('%H:%M', time.gmtime(nxt + 7 * 3600))} WIB, sinyal baru dicek saat itu."]
    hh = PO.hari()
    if hh == "senin":
        waktu.append("Hari ini Senin: hanya sinyal COMBO EMAS, COMBO FIX, COMBO RAJA, atau COMBO 3+ yang dikirim.")
    elif hh == "akhir_pekan":
        waktu.append("Akhir pekan: sinyal tetap dikirim dengan lot setengah.")
    bd = berita_depan(3)
    if bd:
        waktu.append(f"Berita besar USD {bd['judul']} dalam 3 jam, sinyal baru ditahan sampai 1 jam sesudah rilis.")
    try:
        waktu.append("BTC: " + ST.btc_ema50_teks().split(" ", 1)[1] + ". Info saja, tidak dipakai menyaring sinyal.")
    except Exception:
        pass
    rows += ["", "🕐 <b>WAKTU DAN PASAR</b>"] + waktu
    # 6. kesimpulan
    rows += ["", "✅ <b>KESIMPULAN</b>"]
    lawan = [x for x in valid if arah and x[2] != arah]
    searah = [x for x in valid if not arah or x[2] == arah]
    if lawan and not searah:
        rows.append(f"Sinyal terbukti di {nama} justru {lawan[0][2]}, berlawanan dengan rencana {arah} kamu. Jangan {arah}. "
                    f"Kalau mau masuk, ikuti sinyal {lawan[0][2]} di atas.")
    elif searah:
        rows.append(f"Ada sinyal valid. Ambil yang paling atas: salin blok Entry, SL, dan TP ke /entry, pasang SL dan TP atau "
                    f"Trailing Stop di Bybit, lalu biarkan sampai kena.")
    elif pos:
        rows.append("Tidak ada sinyal baru. Posisi kamu tetap ikuti SL dan TP, jangan keluar lebih awal.")
    else:
        rows.append(f"Belum ada alasan untuk entry {nama} sekarang. Di uji 2021-2026 hanya sinyal dari teknik terbukti yang "
                    f"untung, jadi tunggu sinyal muncul di laporan 4J atau cek lagi dengan /sinyal4j.")
    if entry and arah and not valid:
        rows.append(f"Rencana {arah} di {fp(entry, t)} tidak didukung sinyal terbukti.")
    if sym == "BTCUSDT":
        try:
            rows += ["", spot_btc()]
        except Exception as ex:
            print("[WARN] spot btc", ex)
    rows += ["", f"Analisa lama yang lebih panjang: /cekdetail {nama}"]
    return "\n".join(rows)


def tentang_koin(sym, df, px):
    """Profil koin untuk /cek: bidang, peringkat, market cap, likuiditas di Bybit, gerak harian, performa, hari terbaik
    (aturan teruji robot), dan riwayat sinyal robot di koin ini. Return list baris."""
    import qse_fundamental as FD
    out = []
    f = {}
    try:
        f = FD.coingecko(sym) or {}
    except Exception:
        pass
    if f:
        rk = f.get("rank")
        kelas = ("koin besar" if rk and rk <= 20 else "koin menengah" if rk and rk <= 100 else
                 "koin kecil" if rk and rk <= 300 else "koin mikro, geraknya bisa sangat liar")
        out.append(f"{f.get('nama', sym)}" + (f" bergerak di bidang {', '.join(f['kategori'][:3])}" if f.get("kategori") else "")
                   + f". Market cap {FD._uang(f.get('mcap'))}" + (f", peringkat #{rk}" if rk else "") + f", termasuk {kelas}.")
        perf = [(n, f.get(k)) for n, k in (("7 hari", "p7"), ("30 hari", "p30"), ("1 tahun", "p1y")) if f.get(k) is not None]
        if perf or f.get("ath_pct") is not None:
            out.append("Riwayat harga: " + ", ".join(f"{n} {v:+.1f}%" for n, v in perf)
                       + (f". Saat ini {abs(f['ath_pct']):.0f}% di bawah rekor tertinggi ({f.get('ath_tgl', '-')})"
                          if f.get("ath_pct") is not None else "") + ".")
    try:
        import bybit_fetch as B
        tk = B.get_tickers()
        urut = sorted((v["turnover"], s_) for s_, v in tk.items() if s_.endswith("USDT"))[::-1]
        pos = next((i for i, (_, s_) in enumerate(urut, 1) if s_ == sym), None)
        if pos:
            out.append(f"Likuiditas: peringkat {pos} dari {len(urut)} koin futures Bybit menurut nilai transaksi 24 jam "
                       f"({FD._uang(tk[sym]['turnover'])})" + (". Makin likuid, makin bagus hasil teknik robot di uji."
                                                                if pos <= 50 else ". Di luar 50 besar, sebagian teknik robot tidak dipakai di koin ini."))
    except Exception:
        pass
    if df is not None and len(df) > 200:
        h, l, c = (df[k].values.astype(float) for k in ("high", "low", "close"))
        hari_ = [(h[i:i + 6].max() - l[i:i + 6].min()) / c[i + 5] * 100 for i in range(len(c) - 180, len(c) - 5, 6)]
        ch = [abs(c[i + 6] / c[i] - 1) * 100 for i in range(len(c) - 186, len(c) - 6, 6)]
        if hari_:
            out.append(f"Gerak harian 30 hari terakhir: rentang rata-rata {sum(hari_) / len(hari_):.1f}% per hari, perubahan "
                       f"rata-rata {sum(ch) / len(ch):.1f}% per hari.")
    out.append("Hari terbaik untuk sinyal (uji semua koin 2021-2026): Selasa sampai Jumat (PF 1.32-1.50). Senin hanya sinyal "
               "combo, akhir pekan lot setengah. Aturan ini berlaku sama untuk semua koin.")
    try:
        import qse_catat as CT
        rs = [c_["R"] for _, _, c_ in CT._tutup_terbukti() if c_.get("sym") == sym]
        if rs:
            out.append(f"Riwayat sinyal robot di koin ini (live): {len(rs)} trade, WR {sum(r > 0 for r in rs) / len(rs) * 100:.0f}%, "
                       f"total {sum(rs):+.1f}R.")
    except Exception:
        pass
    return out


def spot_btc():
    """Bagian SPOT BTC di /cek BTC. Uji BTC harian Agu 2017 - Okt 2026.
    Skor tren 0-3 (harga di atas EMA200 harian, tren mingguan naik, RSI harian di atas 60), 30 dan 90 hari ke depan:
    2017-21: skor 3 +14.0% (naik 67%) / +48.3%, skor 2 +3.6% / +16.3%, skor 1 -1.0% / +21.3%, skor 0 +4.5% / +12.2%.
    2022-26: skor 3 +5.9% (naik 58%) / +11.7%, skor 2 +3.2% / +7.6%, skor 1 -1.1% / +9.8%, skor 0 +0.5% / +3.6%.
    Cara beli (100 per minggu, 2018-2026): DCA +416%, hanya saat RSI<30 +369%, hanya saat tren mingguan naik +385%,
    hanya di bawah EMA200 +390%. Tidak ada aturan waktu beli yang mengalahkan DCA. Hari dan jam beli beda < 1%."""
    import json
    import bybit_fetch as B
    import pandas as pd
    D = B._raw("BTCUSDT", "D", 400)
    c = D["close"].values.astype(float)
    if len(c) < 210:
        return ""
    px = c[-1]
    e200 = pd.Series(c).ewm(span=200, adjust=False).mean().values[-1]
    d = pd.Series(c).diff()
    up = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = float((100 - 100 / (1 + up / dn)).iloc[-1])
    w = pd.Series(c[::-1][::7][::-1])
    wk_naik = bool(w.iloc[-1] > w.ewm(span=20, adjust=False).mean().iloc[-1])
    dd = px / c[-90:].max() - 1
    skor = int(px > e200) + int(wk_naik) + int(rsi > 60)
    sej = {3: ("tren kuat", "+14.0% (naik 67%)", "+5.9% (naik 58%)"),
           2: ("tren cukup", "+3.6% (naik 46%)", "+3.2% (naik 50%)"),
           1: ("tren lemah", "-1.0% (naik 40%)", "-1.1% (naik 45%)"),
           0: ("tren turun", "+4.5% (naik 56%)", "+0.5% (naik 57%)")}[skor]
    try:
        with open(os.path.join(STATE_DIR, "state.json")) as f:
            n_dca = json.load(f).get("dca_n", 0)
    except Exception:
        n_dca = 0
    rows = ["🪙 <b>SPOT BTC</b> (beli untuk disimpan)",
            "",
            f"Kondisi tren sekarang skor {skor}/3 ({sej[0]}): harga {'di atas' if px > e200 else 'di bawah'} EMA200 harian "
            f"({(px / e200 - 1) * 100:+.1f}%), tren mingguan {'naik' if wk_naik else 'turun'}, RSI harian {rsi:.0f}. "
            f"Harga {dd * 100:+.0f}% dari puncak 90 hari.",
            f"Sejarah 30 hari setelah kondisi skor {skor}: {sej[1]} di 2017-2021, {sej[2]} di 2022-2026. "
            f"Rata-rata semua hari: +6.1% dan +2.3%. Skor 3 paling bagus di kedua periode, artinya BTC yang sedang kuat "
            f"cenderung lanjut, bukan malah turun.",
            "",
            "Cara beli yang paling untung di uji 2018-2026 adalah beli rutin tiap minggu dengan jumlah sama (+416%). "
            "Semua cara menunggu waktu beli kalah: tunggu RSI di bawah 30 (+369%), hanya saat tren naik (+385%), "
            "hanya di bawah EMA200 (+390%). Hari dan jam beli tidak berpengaruh, bedanya kurang dari 1%.",
            "",
            f"✅ Jadwal kamu: beli Rp100.000 tiap Senin pagi" + (f", sudah {n_dca} minggu berjalan" if n_dca else "")
            + ". Tetap beli berapa pun skor tren minggu ini. Skor di atas hanya gambaran, bukan alasan menunda atau menambah."]
    return "\n".join(rows)


def kabar_profit():
    """Dipanggil listener tiap menit. Kabar saat posisi kamu jalan ke arah untung, tiap tahap sekali:
    posisi ber-TP tetap: 25%, 50%, dan 90% jarak ke TP (100% = pesan KENA TP yang sudah ada).
    posisi trailing (tanpa TP): untung berjalan +1R, +2R, +3R, dengan SL jalur terbaru dan profit yang sudah terkunci.
    Info saja: uji 2021-2026 menutup lebih awal (TP cepat 1R) menurunkan total profit sekitar separuh."""
    d = _load()
    pesan, tandai = [], {}
    for k, it in d["open"].items():
        if it["status"] not in ("TERISI", "TP1"):
            continue
        px = harga_live(it["sym"])
        if not px:
            continue
        L = it["arah"] == "LONG"
        t = it.get("tick") or tick_of(None, px)
        risk = it.get("risk0") or abs(it["entry"] - it["sl"]) or 1e-12
        untung = (px - it["entry"]) if L else (it["entry"] - px)
        sudah = list(it.get("tp_tahap") or [])
        tp = it.get("tp_jalur") if it.get("ikut") else (it.get("tp2") if it.get("tp2") else None)
        jauh = (tp - it["entry"]) * (1 if L else -1) if tp else 0
        if tp and jauh > 0 and jauh < risk * 50:
            prog = untung / jauh
            for lv, nm in ((0.9, "90"), (0.5, "50"), (0.25, "25")):
                if prog >= lv and nm not in sudah:
                    sudah += [x for x in ("25", "50", "90") if float(x) / 100 <= lv and x not in sudah]
                    pesan.append(f"{'🎯' if nm == '90' else '📈'} <b>{it['sym']} {it['arah']}  ·  {nm}% MENUJU TP</b>\n"
                                 f"↳ Harga {fp(px, t)}, TP {fp(tp, t)} ({untung / risk:+.2f}R berjalan). "
                                 + ("Hampir sampai, biarkan order TP di Bybit yang menutup. " if nm == "90" else "Biarkan jalan. ")
                                 + "Jangan tutup manual: uji 2021-2026 keluar lebih awal menurunkan total profit sekitar separuh.")
                    break
        elif not tp:
            r_now = untung / risk
            for lv in (3, 2, 1):
                nm = f"{lv}R"
                if r_now >= lv and nm not in sudah:
                    sudah += [f"{x}R" for x in range(1, lv + 1) if f"{x}R" not in sudah]
                    jp = jalur_posisi(it["sym"], it["arah"])
                    sl_j = jp["sl"] if jp else it["sl"]
                    kunci_r = ((sl_j - it["entry"]) if L else (it["entry"] - sl_j)) / risk
                    pesan.append(f"📈 <b>{it['sym']} {it['arah']}  ·  UNTUNG +{lv}R</b>\n"
                                 f"↳ Harga {fp(px, t)} ({r_now:+.2f}R). SL jalur sekarang {fp(sl_j, t)}"
                                 + (f", profit terkunci {kunci_r:+.2f}R" if kunci_r > 0 else "")
                                 + ". Trailing Stop Bybit menggeser SL sendiri, biarkan jalan sampai kena.")
                    break
        if sudah != list(it.get("tp_tahap") or []):
            tandai[k] = sudah
    if tandai:
        def f(dd):
            for k, v in tandai.items():
                if k in dd["open"]:
                    dd["open"][k]["tp_tahap"] = v
        ubah(f)
    return pesan
