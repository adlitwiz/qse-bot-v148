"""QSE v150 KOMPAS PASAR (9 Nov 2026, permintaan user). Satu sumber arah untuk Cek BTC, Arah, laporan 4J, lalat, gurita, dan jalur.
Bahan: BTC 15m, 1J, 4J (harga lawan EMA 20 dan EMA 50), BTC.D, dan USDT.D.
USDT.D dan BTC.D dibaca dua cara:
 1. Angka asli dari CoinGecko (persen kapitalisasi), disimpan tiap baca supaya perubahan 24 jam terlihat.
 2. Indeks cepat dari candle 1J Bybit: kapitalisasi total kira-kira = BTC 62%, ETH 12%, XRP 5%, BNB 4%, SOL 3%, DOGE 1%.
    Pasokan USDT hampir tetap dalam hitungan jam, jadi USDT.D naik = kapitalisasi total turun. Indeks ini punya EMA dan resistance.
Aturan (status):
 FOKUS SHORT   : USDT.D naik (di atas EMA 20 dan 50, atau tembus tertinggi 24 jam) dan BTC di bawah EMA 50 1J. Hindari LONG.
 WASPADA SHORT : BTC di bawah EMA 50 1J dan 15m tidak naik. Hindari LONG koin umum.
Kartu LONG jalur saat dua status itu: peringatan dan lot 0.5x (label()).
 FOKUS LONG    : USDT.D turun dan BTC di atas EMA 50 1J. Kalau BTC.D juga turun, pintu LONG altcoin terbuka penuh.
 CONDONG LONG  : BTC 1J dan 4J naik, USDT.D belum turun.
 NETRAL        : sisanya.
Uji gerbang 2023-2026: riset/upgrade/hasil_v161.txt bagian 5 dan hasil_v161_lalat.txt bagian c."""
import json
import os
import time

import numpy as np

try:
    from config import STATE_DIR
except Exception:
    STATE_DIR = "."

F = os.path.join(STATE_DIR, "kompas.json")
BOBOT = {"BTCUSDT": 0.62, "ETHUSDT": 0.12, "XRPUSDT": 0.05, "BNBUSDT": 0.04, "SOLUSDT": 0.03, "DOGEUSDT": 0.01}
_C = {}


def _ema(x, n):
    x = np.asarray(x, float)
    out = np.empty(len(x))
    a = 2 / (n + 1)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _kl(sym, iv, n):
    from qse_saya import _kline
    k = _kline(sym, iv, n)
    return [r for r in k][:-1] if k else []          # candle terakhir masih berjalan


def _tf(c):
    """+1 harga > EMA20 > EMA50, -1 harga < EMA20 < EMA50, 0 campur."""
    e20, e50 = _ema(c, 20), _ema(c, 50)
    if c[-1] > e20[-1] > e50[-1]:
        return 1, e20[-1], e50[-1]
    if c[-1] < e20[-1] < e50[-1]:
        return -1, e20[-1], e50[-1]
    return 0, e20[-1], e50[-1]


def _indeks(rows_map):
    """Log indeks kapitalisasi total dan log BTC lawan altcoin dari candle 1J yang sama waktunya."""
    ts = None
    for s, r in rows_map.items():
        t = {x[0] for x in r}
        ts = t if ts is None else ts & t
    ts = sorted(ts or [])
    if len(ts) < 60:
        return None, None, None
    lg = {s: np.log(np.array([dict((x[0], x[3]) for x in r)[t] for t in ts], float)) for s, r in rows_map.items()}
    tot = sum(BOBOT[s] * (lg[s] - lg[s][0]) for s in lg) / sum(BOBOT[s] for s in lg)
    alt_w = {s: BOBOT[s] for s in lg if s != "BTCUSDT"}
    alt = sum(w * (lg[s] - lg[s][0]) for s, w in alt_w.items()) / sum(alt_w.values())
    return np.array(ts), -tot, (lg["BTCUSDT"] - lg["BTCUSDT"][0]) - alt


def _cg():
    """Angka asli BTC.D dan USDT.D (CoinGecko), cache 5 menit, riwayat disimpan untuk perubahan 24 jam."""
    c = _C.get("cg")
    if c and time.time() - c[0] < 300:
        return c[1]
    v = None
    try:
        import requests
        m = requests.get("https://api.coingecko.com/api/v3/global", timeout=10,
                         headers={"User-Agent": "qse-bot/150"}).json()["data"]["market_cap_percentage"]
        v = dict(btc=float(m["btc"]), usdt=float(m.get("usdt") or 0))
    except Exception:
        v = None
    _C["cg"] = (time.time(), v)
    if v:
        try:
            d = _baca()
            d["cg"] = [x for x in d.get("cg", []) if time.time() - x[0] < 3 * 86400] + [[time.time(), v["btc"], v["usdt"]]]
            _tulis(d)
        except Exception:
            pass
    return v


def _cg_24j():
    d = _baca().get("cg", [])
    if len(d) < 2:
        return None
    now = d[-1]
    lama = min(d, key=lambda x: abs(x[0] - (now[0] - 86400)))
    if now[0] - lama[0] < 6 * 3600:
        return None
    return dict(btc=now[1] - lama[1], usdt=now[2] - lama[2], jam=(now[0] - lama[0]) / 3600)


def _baca():
    try:
        with open(F) as f:
            return json.load(f)
    except Exception:
        return {}


def _tulis(d):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(F + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(F + ".tmp", F)
    except Exception as ex:
        print("[WARN] kompas tulis", ex)


def hitung(rows15=None, rows1=None, rows4=None, basket=None):
    """Return dict kompas. Argumen hanya untuk uji (data candle buatan); live mengambil dari Bybit."""
    c15 = np.array([x[3] for x in (rows15 if rows15 is not None else _kl("BTCUSDT", "15", 200))], float)
    c1 = np.array([x[3] for x in (rows1 if rows1 is not None else _kl("BTCUSDT", "60", 200))], float)
    c4 = np.array([x[3] for x in (rows4 if rows4 is not None else _kl("BTCUSDT", "240", 200))], float)
    if min(len(c15), len(c1), len(c4)) < 60:
        return None
    s15, _, _ = _tf(c15)
    s1, e20_1, e50_1 = _tf(c1)
    s4, _, _ = _tf(c4)
    bawah50 = c1[-1] < e50_1
    if basket is None:
        basket = {s: _kl(s, "60", 200) for s in BOBOT}
    _, ud, bd = _indeks({s: r for s, r in basket.items() if r})
    u = dict(naik=False, turun=False, tembus=False, ch24=None)
    b = dict(naik=False, turun=False, ch24=None)
    if ud is not None:
        e20, e50 = _ema(ud, 20), _ema(ud, 50)
        u["tembus"] = bool(ud[-1] > ud[-25:-1].max())
        u["naik"] = bool((ud[-1] > e20[-1] > e50[-1]) or u["tembus"])
        u["turun"] = bool(ud[-1] < e20[-1] < e50[-1])
        u["ch24"] = float((np.exp(ud[-1] - ud[-25]) - 1) * 100)          # % perubahan relatif USDT.D 24 jam
        f20, f50 = _ema(bd, 20), _ema(bd, 50)
        b["naik"] = bool(bd[-1] > f20[-1] > f50[-1])
        b["turun"] = bool(bd[-1] < f20[-1] < f50[-1])
        b["ch24"] = float((np.exp(bd[-1] - bd[-25]) - 1) * 100)
    if u["naik"] and bawah50:
        st, ik = "FOKUS SHORT", "🔴"
        aksi = "HINDARI LONG baru. Uang ditarik ke tunai. Utamakan SHORT di resistance dan tembusan ke bawah."
    elif bawah50 and s15 <= 0:
        st, ik = "WASPADA SHORT", "🟠"
        aksi = "BTC di bawah EMA 50 1J. HINDARI LONG koin umum, SHORT diutamakan. LONG hanya koin medali dengan SL disiplin."
    elif u["turun"] and not bawah50:
        st, ik = "FOKUS LONG", "🟢"
        aksi = ("Uang masuk ke kripto. Pintu LONG terbuka" + (", altcoin paling kuat (BTC.D turun)." if b["turun"] else
                                                              ", utamakan BTC dan koin besar (BTC.D belum turun)."))
    elif s1 > 0 and s4 > 0:
        st, ik = "CONDONG LONG", "🟢"
        aksi = "BTC 1J dan 4J naik, USDT.D belum turun. LONG boleh, SHORT hanya yang berlabel kuat."
    else:
        st, ik = "NETRAL", "⚪"
        aksi = "Arah campur. Ikuti sinyal robot dua arah, lot normal."
    skor = 20 * s15 + 30 * s1 + 30 * s4 + (-20 if u["naik"] else 20 if u["turun"] else 0)
    return dict(status=st, ikon=ik, aksi=aksi, skor=int(skor), s15=s15, s1=s1, s4=s4, btc=float(c1[-1]), ema50_1j=float(e50_1),
                ema20_1j=float(e20_1), bawah50=bool(bawah50), usdt=u, btcd=b, t=time.time(),
                blok_long=st in ("FOKUS SHORT", "WASPADA SHORT"), blok_long_medali=st == "FOKUS SHORT" and u["tembus"])


def kompas(maks_umur=60):
    c = _C.get("k")
    if c and time.time() - c[0] < maks_umur:
        return c[1]
    try:
        k = hitung()
    except Exception as ex:
        print("[WARN] kompas", ex)
        k = None
    if k:
        _C["k"] = (time.time(), k)
        d = _baca()
        d["akhir"] = k
        _tulis(d)
    elif c:
        return c[1]
    return k


def izin(arah, medali=False):
    """(boleh, alasan). Satu-satunya gerbang arah pasar. Mati dengan env QSE_KOMPAS=0."""
    if os.environ.get("QSE_KOMPAS", "1") != "1" or arah != "LONG":
        return True, ""
    k = kompas()
    if not k:
        return True, ""
    if medali:
        return (False, f"kompas {k['status']}, USDT.D tembus resistance") if k["blok_long_medali"] else (True, "")
    return (False, f"kompas {k['status']}") if k["blok_long"] else (True, "")


def _ar(x):
    return "▲ naik" if x > 0 else "▼ turun" if x < 0 else "• campur"


def blok(k=None, singkat=False):
    """Teks kompas. singkat=True untuk header laporan dan Arah."""
    k = k or kompas()
    if not k:
        return "🧭 Kompas pasar belum terbaca (data Bybit gagal)."
    u, b = k["usdt"], k["btcd"]
    cg = _cg() if not singkat else None
    ch = _cg_24j() if not singkat else None
    head = f"🧭 <b>KOMPAS PASAR: {k['ikon']} {k['status']}</b>  ·  skor {k['skor']:+d}/100"
    if singkat:
        return (head + f"\n15m {_ar(k['s15'])} · 1J {_ar(k['s1'])} · 4J {_ar(k['s4'])} · USDT.D "
                + ("▲ naik" if u["naik"] else "▼ turun" if u["turun"] else "• datar") + " · BTC.D "
                + ("▲" if b["naik"] else "▼" if b["turun"] else "•") + f"\n➡️ {k['aksi']}")
    rows = [head, "",
            f"₿ BTC {k['btc']:,.0f}  ·  EMA 20 1J {k['ema20_1j']:,.0f}  ·  EMA 50 1J {k['ema50_1j']:,.0f} "
            f"({'DI BAWAH' if k['bawah50'] else 'di atas'}, {(k['btc'] / k['ema50_1j'] - 1) * 100:+.2f}%)",
            f"15 menit {_ar(k['s15'])}  ·  1 jam {_ar(k['s1'])}  ·  4 jam {_ar(k['s4'])}",
            "💵 USDT.D " + (f"{cg['usdt']:.2f}%" if cg and cg.get("usdt") else "")
            + (f" ({ch['usdt']:+.2f} poin {ch['jam']:.0f} jam)" if ch else "")
            + f"  ·  indeks 24 jam {u['ch24']:+.2f}%" if u["ch24"] is not None else "💵 USDT.D belum terbaca",
            "   " + ("🔺 NAIK" + (" dan TEMBUS resistance 24 jam" if u["tembus"] else "") + ": uang ditarik ke tunai" if u["naik"] else
                     "🔻 TURUN: uang masuk ke kripto" if u["turun"] else "➖ datar"),
            "🪙 BTC.D " + (f"{cg['btc']:.2f}%" if cg else "") + (f" ({ch['btc']:+.2f} poin)" if ch else "")
            + (f"  ·  BTC lawan altcoin 24 jam {b['ch24']:+.2f}%" if b["ch24"] is not None else ""),
            "   " + ("🔺 NAIK: BTC lebih kuat dari altcoin" if b["naik"] else "🔻 TURUN: altcoin lebih kuat" if b["turun"] else "➖ datar"),
            "", f"➡️ <b>{k['aksi']}</b>",
            ("⛔ Kartu LONG jalur selama status ini diberi peringatan dan turun ke KELAS RINGAN. Uji 2023-2026: blokir total tidak konsisten "
             "menaikkan hasil, jadi pilihan akhir di tangan kamu." if k["blok_long"] else "✅ Sinyal LONG dan SHORT boleh keluar.")]
    return "\n".join(rows)


def label(arah):
    """(kali_lot, teks) untuk kartu sinyal. LONG saat kompas FOKUS/WASPADA SHORT: lot 0.5x dan peringatan.
    Uji v161: memblokir LONG saat kompas merah tidak konsisten di semua teknik (lalat medali dan sinyal jatuh justru lebih jelek
    kalau diblokir, GZH lama dan teknik baru membaik di sebagian periode), jadi kartu tetap dikirim dengan lot dipotong."""
    if arah != "LONG" or os.environ.get("QSE_KOMPAS", "1") != "1":
        return 1.0, ""
    k = kompas()
    if not k or not k["blok_long"]:
        return 1.0, ""
    return 0.5, f"⛔ <b>KOMPAS {k['status']}</b>: LONG ini melawan arus uang (USDT.D/BTC 1J). 🟨 KELAS RINGAN, SL wajib."
