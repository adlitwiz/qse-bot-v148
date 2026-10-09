"""QSE v148 - NEWS KE TRADE. Dipanggil listener tiap 15 menit.
Sumber: RSS media kripto (Cointelegraph, CoinDesk, Decrypt, Cryptonews), Google News, dan Reddit (sosmed).
Tiap berita: dicocokkan ke koin Bybit, dinilai dampaknya (positif/negatif, kuat/lemah), diterjemahkan ke bahasa Indonesia,
lalu disambungkan ke hasil engine QSE koin itu. Saran entry hanya keluar kalau arah berita dan engine searah.
Berita makro (Fed, ETF, regulasi, perang) dipetakan ke BTC. Tiap judul dikirim sekali."""
import html
import json
import os
import re
import time
import datetime as dt
import requests
import telegram_notify as TG
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "news.json")
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) qse-bot/1.0"}
WIB = dt.timezone(dt.timedelta(hours=7))
SUMBER = (
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Decrypt", "https://decrypt.co/feed"),
    ("Cryptonews", "https://cryptonews.com/news/feed/"),
    ("Google News", "https://news.google.com/rss/search?q=crypto+OR+bitcoin+when:3h&hl=en-US&gl=US&ceid=US:en"),
    ("Reddit r/CryptoCurrency", "https://www.reddit.com/r/CryptoCurrency/hot/.rss?limit=25"),
    ("Reddit r/Bitcoin", "https://www.reddit.com/r/Bitcoin/hot/.rss?limit=15"),
)
NAMA = {
    "BTC": ("bitcoin", "btc"), "ETH": ("ethereum", "ether", "eth"), "SOL": ("solana", "sol"), "XRP": ("xrp", "ripple"),
    "BNB": ("bnb", "binance coin"), "DOGE": ("dogecoin", "doge"), "ADA": ("cardano", "ada"), "TRX": ("tron", "trx"),
    "AVAX": ("avalanche", "avax"), "LINK": ("chainlink",), "DOT": ("polkadot",), "TON": ("toncoin", "ton"),
    "SUI": ("sui",), "LTC": ("litecoin", "ltc"), "SHIB": ("shiba inu", "shib"), "PEPE": ("pepe",), "NEAR": ("near protocol",),
    "APT": ("aptos",), "ARB": ("arbitrum",), "OP": ("optimism",), "HBAR": ("hedera", "hbar"), "XLM": ("stellar", "xlm"),
    "UNI": ("uniswap",), "AAVE": ("aave",), "ENA": ("ethena",), "HYPE": ("hyperliquid",), "WLD": ("worldcoin",),
    "TIA": ("celestia",), "INJ": ("injective",), "FIL": ("filecoin",), "ICP": ("internet computer",), "ETC": ("ethereum classic",),
}
MAKRO = ("fed ", "fomc", "powell", "rate cut", "rate hike", "interest rate", "cpi", "inflation", "jobs report", "payroll",
         "etf", "sec ", "tariff", "war ", "sanction", "trump", "treasury", "recession", "liquidat", "stablecoin")
POS = {"approve": 2, "approval": 2, "etf inflow": 2, "inflows": 2, "partnership": 1, "launch": 1, "listing": 1, "lists": 1,
       "surge": 2, "soar": 2, "rally": 2, "jump": 1, "bullish": 2, "record high": 2, "all-time high": 2, "ath": 1,
       "rate cut": 2, "adopt": 1, "buys": 1, "accumulat": 1, "upgrade": 1, "wins": 1, "dismiss": 1, "breakout": 1,
       "gains": 1, "rebound": 1, "recover": 1, "reserve": 1, "eases": 1}
NEG = {"hack": 3, "exploit": 3, "lawsuit": 2, "sues": 2, "ban ": 2, "bans": 2, "delist": 3, "crash": 3, "plunge": 2,
       "dump": 2, "bearish": 2, "outflow": 2, "sell-off": 2, "selloff": 2, "liquidat": 2, "rate hike": 2, "fraud": 2,
       "drops": 1, "falls": 1, "slides": 1, "slump": 2, "warning": 1, "probe": 1, "investigat": 1, "halt": 2,
       "depeg": 3, "bankrupt": 3, "tariff": 1, "war ": 2, "sanction": 1, "unlock": 1, "fear": 1, "decline": 1}


DAMPAK = {  # backtest 2022-01 s/d 2026-10: reaksi BTC (persen) setelah berita jenis ini, data jam Binance
    'BANK_CRISIS': dict(n=3, b4=None, b24=-2.42, b72=-0.63, naik=0, dd=-4.05, up=0.26, alt24=0.59),
    'BANK_RESCUE': dict(n=1, b4=4.8, b24=13.22, b72=14.81, naik=100, dd=-0.81, up=15.17, alt24=-6.16),
    'CORPORATE_BUY': dict(n=3, b4=None, b24=-1.48, b72=0.85, naik=33, dd=-2.43, up=1.74, alt24=1.84),
    'CORPORATE_SELL': dict(n=1, b4=None, b24=-3.08, b72=-12.94, naik=0, dd=-4.06, up=0.57, alt24=1.76),
    'CPI_COOL': dict(n=24, b4=0.55, b24=0.79, b72=0.76, naik=58, dd=-1.81, up=2.66, alt24=1.39),
    'CPI_HOT': dict(n=19, b4=-0.92, b24=-0.75, b72=-1.94, naik=42, dd=-3.84, up=2.19, alt24=-0.01),
    'CPI_INLINE': dict(n=13, b4=1.42, b24=1.78, b72=3.29, naik=85, dd=-1.16, up=3.59, alt24=0.28),
    'ETF_POSITIVE': dict(n=8, b4=-1.36, b24=1.41, b72=-0.87, naik=50, dd=-2.2, up=3.51, alt24=1.24),
    'EXCHANGE_COLLAPSE': dict(n=9, b4=None, b24=-6.49, b72=-8.44, naik=0, dd=-8.58, up=1.03, alt24=-1.22),
    'FOMC_CUT': dict(n=6, b4=-0.65, b24=-0.54, b72=-0.05, naik=50, dd=-3.1, up=1.87, alt24=-0.88),
    'FOMC_HIKE': dict(n=12, b4=0.25, b24=0.16, b72=-0.38, naik=42, dd=-3.3, up=3.42, alt24=2.39),
    'FOMC_HOLD': dict(n=20, b4=-0.2, b24=-0.94, b72=-0.93, naik=45, dd=-2.92, up=1.93, alt24=0.27),
    'GOV_SELLING': dict(n=2, b4=None, b24=-3.62, b72=-6.31, naik=0, dd=-6.78, up=0.43, alt24=-0.72),
    'HACK': dict(n=17, b4=-0.03, b24=0.01, b72=-0.29, naik=29, dd=-1.75, up=1.83, alt24=-0.25),
    'HALVING': dict(n=1, b4=0.22, b24=1.76, b72=4.7, naik=100, dd=-1.14, up=2.51, alt24=4.12),
    'MACRO_SHOCK': dict(n=6, b4=0.32, b24=-0.57, b72=-1.59, naik=33, dd=-4.61, up=1.86, alt24=0.23),
    'POLITICS_PROCRYPTO': dict(n=6, b4=None, b24=3.36, b72=3.0, naik=67, dd=-1.46, up=5.26, alt24=2.13),
    'REG_NEGATIVE': dict(n=9, b4=None, b24=-1.21, b72=1.02, naik=33, dd=-3.36, up=1.69, alt24=-1.67),
    'REG_POSITIVE': dict(n=9, b4=None, b24=0.96, b72=-0.38, naik=67, dd=-1.7, up=2.84, alt24=2.38),
    'STABLECOIN_DEPEG': dict(n=3, b4=None, b24=-4.97, b72=0.09, naik=33, dd=-6.95, up=1.31, alt24=-2.71),
    'TARIFF_RELIEF': dict(n=6, b4=None, b24=1.97, b72=1.66, naik=67, dd=-2.98, up=3.65, alt24=0.8),
    'TARIFF_TRADEWAR': dict(n=5, b4=-5.04, b24=-3.03, b72=-3.85, naik=0, dd=-5.21, up=0.8, alt24=-3.54),
    'WAR': dict(n=10, b4=None, b24=-0.81, b72=-0.23, naik=40, dd=-3.79, up=1.54, alt24=-1.86),
    'WAR_DAMAI': dict(n=3, b4=None, b24=3.6, b72=4.16, naik=100, dd=-1.39, up=4.27, alt24=1.63),
}
LABEL = {"BANK_CRISIS": "krisis bank", "BANK_RESCUE": "penyelamatan bank", "CORPORATE_BUY": "perusahaan beli BTC",
         "CORPORATE_SELL": "perusahaan jual BTC", "CPI_COOL": "inflasi AS lebih rendah dari perkiraan",
         "CPI_HOT": "inflasi AS lebih tinggi dari perkiraan", "CPI_INLINE": "inflasi AS sesuai perkiraan",
         "ETF_POSITIVE": "kabar baik ETF", "EXCHANGE_COLLAPSE": "bursa atau lender kripto kolaps",
         "FOMC_CUT": "The Fed turunkan suku bunga", "FOMC_HIKE": "The Fed naikkan suku bunga", "FOMC_HOLD": "The Fed tahan suku bunga",
         "GOV_SELLING": "pemerintah atau Mt. Gox lepas BTC", "HACK": "peretasan besar", "HALVING": "halving",
         "MACRO_SHOCK": "guncangan makro", "POLITICS_PROCRYPTO": "kebijakan politik pro kripto",
         "REG_NEGATIVE": "regulasi atau gugatan negatif", "REG_POSITIVE": "regulasi positif",
         "STABLECOIN_DEPEG": "stablecoin lepas patokan", "TARIFF_RELIEF": "tarif dilonggarkan",
         "TARIFF_TRADEWAR": "tarif atau perang dagang", "WAR": "perang atau serangan militer", "WAR_DAMAI": "gencatan senjata atau damai"}
# kategori yang bisa jadi SARAN NEWS MANDIRI (walau engine berlawanan): minimal 5 kejadian, BTC 24 jam rata rata
# bergerak minimal 1.5%, dan arahnya konsisten (naik di 65% kejadian atau lebih, atau turun di 65% atau lebih).
# Backtest jalur ini (entry 1 jam setelah berita, LIMIT 0.25 ATR, SL di balik ayunan khas, TP 1R dan 2R, tahan 24 jam):
# 28 trade, WR 68%, PF 2.29, rata +0.37R. Ini in-sample, jadi tetap dicatat live dan berhenti sendiri kalau jelek.
BT_MANDIRI = "28 trade, WR 68%, PF 2.29, rata +0.37R (2022-2026)"
KUNCI = [  # urutan penting: yang lebih khusus dulu
    ("STABLECOIN_DEPEG", (("depeg", "de-peg", "loses peg", "lost its peg", "loses its peg"),)),
    ("EXCHANGE_COLLAPSE", (("halts withdrawals", "pauses withdrawals", "suspends withdrawals", "freezes withdrawals",
                            "files for bankruptcy", "chapter 11", "insolven", "collapse"),)),
    ("HACK", (("hack", "exploit", "drained", "stolen", "heist"),)),
    ("TARIFF_RELIEF", (("tariff", "trade war", "trade deal"), ("pause", "delay", "postpone", "truce", "deal", "exempt", "lift",
                                                             "strike down", "strikes down", "struck down", "drop", "roll back",
                                                             "rollback", "cut tariff", "cuts tariff", "reduce", "eases"))),
    ("TARIFF_TRADEWAR", (("tariff", "trade war"),)),
    ("FOMC_CUT", (("fed ", "fomc", "federal reserve", "powell", "warsh"), ("cuts rate", "rate cut", "cuts interest", "lowers rate",
                                                                         "cut rates", "cuts by"))),
    ("FOMC_HIKE", (("fed ", "fomc", "federal reserve", "powell", "warsh"), ("raises rate", "rate hike", "hikes rate", "raises interest",
                                                                          "hike rates", "hikes by"))),
    ("FOMC_HOLD", (("fed ", "fomc", "federal reserve", "powell", "warsh"), ("holds rate", "keeps rate", "leaves rate",
                                                                          "rates unchanged", "holds steady", "on hold"))),
    ("CPI_HOT", (("cpi", "inflation"), ("hotter", "higher than expected", "above expectation", "above forecast", "accelerat",
                                        "sticky", "rises more than"))),
    ("CPI_COOL", (("cpi", "inflation"), ("cooler", "lower than expected", "below expectation", "below forecast", "eases",
                                         "slows", "softer", "cools"))),
    ("CPI_INLINE", (("cpi",), ("in line", "as expected", "matches", "meets expectation"))),
    ("WAR_DAMAI", (("ceasefire", "peace deal", "peace agreement", "truce"),)),
    ("WAR", (("missile", "airstrike", "air strike", "invasion", "invades", "military strike", "strikes on", "declares war",
              "attack on", "launches strikes", "bomb"),)),
    ("ETF_POSITIVE", (("etf",), ("approv", "launch", "inflow", "filing", "files for", "record"))),
    ("REG_NEGATIVE", (("sues", "lawsuit", "charges", "crackdown", "bans ", "ban on", "sanction", "indict", "cloture fails",
                       "bill fails", "rejects"),)),
    ("REG_POSITIVE", (("clarity act", "genius act", "market structure", "dismiss", "drops case", "drops lawsuit",
                       "regulatory clarity", "approves", "signs", "passes"), ("crypto", "bitcoin", "stablecoin", "sec", "digital asset"))),
    ("POLITICS_PROCRYPTO", (("strategic bitcoin reserve", "crypto reserve", "bitcoin reserve", "pro-crypto", "crypto executive order"),)),
    ("GOV_SELLING", (("mt. gox", "mt gox", "government sells", "government moves", "seized bitcoin", "seized btc"),)),
    ("CORPORATE_SELL", (("sells bitcoin", "sold bitcoin", "sells btc", "sold btc"),)),
    ("CORPORATE_BUY", (("buys", "acquires", "purchases", "adds"), ("bitcoin", "btc"))),
    ("BANK_CRISIS", (("bank",), ("collapse", "fails", "failure", "seized", "bank run", "run on"))),
    ("MACRO_SHOCK", (("recession", "bank of japan", "boj ", "yen carry", "government shutdown", "stock market crash",
                      "global selloff", "global sell-off", "black monday"),)),
    ("HALVING", (("halving",),)),
]


def kategori(teks):
    """Jenis berita (kunci DAMPAK) dari judul dan ringkasan, atau None."""
    low = " " + teks.lower() + " "
    for k, grup in KUNCI:
        if all(any(w in low for w in g) for g in grup):
            return k
    return None


def arah_sejarah(k):
    """+1 kalau sejarah jenis berita ini condong naik, -1 condong turun, 0 campur."""
    d = DAMPAK.get(k)
    if not d or d["n"] < 5:
        return FACE.get(k, 0)
    if d["naik"] >= 60 and d["b24"] > 0:
        return 1
    if d["naik"] <= 40 and d["b24"] < 0:
        return -1
    return FACE.get(k, 0) if k in ("HACK", "REG_NEGATIVE", "REG_POSITIVE", "WAR") else 0


FACE = {"BANK_CRISIS": -1, "BANK_RESCUE": 1, "CORPORATE_BUY": 1, "CORPORATE_SELL": -1, "CPI_COOL": 1, "CPI_HOT": -1,
        "ETF_POSITIVE": 1, "EXCHANGE_COLLAPSE": -1, "FOMC_CUT": 1, "FOMC_HIKE": -1, "GOV_SELLING": -1, "HACK": -1,
        "HALVING": 1, "MACRO_SHOCK": -1, "POLITICS_PROCRYPTO": 1, "REG_NEGATIVE": -1, "REG_POSITIVE": 1,
        "STABLECOIN_DEPEG": -1, "TARIFF_RELIEF": 1, "TARIFF_TRADEWAR": -1, "WAR": -1, "WAR_DAMAI": 1}


def kuat_mandiri(k):
    d = DAMPAK.get(k)
    return bool(d) and d["n"] >= 5 and abs(d["b24"]) >= 1.5 and (d["naik"] >= 65 or d["naik"] <= 35)


def sejarah_teks(k):
    d = DAMPAK.get(k)
    if not d:
        return ""
    t = (f"📚 Sejarah 2022-2026, {LABEL.get(k, k)} ({d['n']} kejadian): BTC 24 jam rata rata {d['b24']:+.2f}%, "
         f"naik di {d['naik']}% kejadian, 3 hari {d['b72']:+.2f}%. Turun terdalam rata rata {d['dd']:.1f}% dan naik tertinggi "
         f"+{d['up']:.1f}% dalam 24 jam. Altcoin dibanding BTC {d['alt24']:+.2f}%.")
    if d["n"] < 5:
        t += " Sampel kecil, anggap petunjuk saja."
    elif arah_sejarah(k) == 0:
        t += " Arahnya campur, berita jenis ini lebih sering bikin harga bergoyang daripada searah."
    return t


def _load():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(c):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(c, f)
    os.replace(FILE + ".tmp", FILE)


def _bersih(s):
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s or "")
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\xa0", " ").strip()


def _ambil(nama, url):
    try:
        x = requests.get(url, headers=UA, timeout=15).text
    except Exception as ex:
        print("[WARN] news", nama, ex)
        return []
    out = []
    for it in re.findall(r"<(?:item|entry)(?:\s[^>]*)?>(.*?)</(?:item|entry)>", x, re.S)[:25]:
        t = re.search(r"<title[^>]*>(.*?)</title>", it, re.S)
        if not t:
            continue
        ln = re.search(r"<link[^>]*?(?:href=\"([^\"]+)\"[^>]*/?>|>(.*?)</link>)", it, re.S)
        d = re.search(r"<(?:description|summary|content)[^>]*>(.*?)</(?:description|summary|content)>", it, re.S)
        pb = re.search(r"<(?:pubDate|published|updated|dc:date)[^>]*>(.*?)</(?:pubDate|published|updated|dc:date)>", it, re.S)
        out.append(dict(sumber=nama, judul=_bersih(t.group(1)),
                        link=(ln.group(1) or ln.group(2) or "").strip() if ln else "",
                        isi=_bersih(d.group(1))[:400] if d else "", pub=_waktu(pb.group(1)) if pb else None))
    return out


def _waktu(s):
    """Waktu terbit berita (epoch detik) dari format RSS atau Atom. Gagal = None."""
    s = _bersih(s)
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s).timestamp()
    except Exception:
        pass
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def terjemah(teks):
    """Terjemah ke bahasa Indonesia (Google Translate publik). Gagal = teks asli."""
    if not teks:
        return ""
    try:
        r = requests.get("https://translate.googleapis.com/translate_a/single", timeout=10,
                         params=dict(client="gtx", sl="auto", tl="id", dt="t", q=teks[:600])).json()
        return "".join(x[0] for x in r[0] if x and x[0]).strip() or teks
    except Exception:
        return teks


def _nilai(teks):
    low = " " + teks.lower() + " "
    p = sum(w for k, w in POS.items() if k in low)
    n = sum(w for k, w in NEG.items() if k in low)
    s = p - n
    if s == 0:
        return 0, ""
    kuat = "KUAT" if abs(s) >= 3 else "SEDANG" if abs(s) == 2 else "LEMAH"
    return (1 if s > 0 else -1), kuat


def _koin(teks, simbol):
    """Koin yang disebut di berita. Berita makro tanpa koin dipetakan ke BTC."""
    low = " " + re.sub(r"[^a-z0-9 ]", " ", teks.lower()) + " "
    hit = []
    for base, kata in NAMA.items():
        if any(f" {k} " in low for k in kata) and base + "USDT" in simbol:
            hit.append(base)
    for tok in set(re.findall(r"\$?\b([A-Z]{3,10})\b", teks)):
        if tok + "USDT" in simbol and tok not in hit and tok not in ("THE", "FOR", "AND", "NEW", "ETF", "SEC", "CEO", "USD"):
            hit.append(tok)
    if not hit and any(k in low for k in MAKRO):
        hit = ["BTC"]
    return hit[:2]


def _hasil(sym):
    try:
        with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
            for r in json.load(f):
                if r["symbol"] == sym and r.get("tf", "240") == "240":
                    return r
    except Exception:
        pass
    return None


def _harga(sym):
    try:
        from config import BYBIT_URL
        t = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear", "symbol": sym},
                         timeout=10).json()["result"]["list"][0]
        return float(t["lastPrice"])
    except Exception:
        return None


def _atr1j(sym, pub, now):
    """ATR 1 jam dan gerak harga (persen) sejak berita terbit. Return (atr, gerak_pct, harga) atau None."""
    try:
        from config import BYBIT_URL
        rows = requests.get(BYBIT_URL + "/v5/market/kline", timeout=10, params={"category": "linear", "symbol": sym,
                            "interval": "60", "limit": 40}).json()["result"]["list"]
        k = sorted(([int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4])] for x in rows), key=lambda z: z[0])
    except Exception:
        return None
    if len(k) < 16:
        return None
    tr = [max(k[i][2] - k[i][3], abs(k[i][2] - k[i - 1][4]), abs(k[i][3] - k[i - 1][4])) for i in range(1, len(k))]
    atr = sum(tr[-15:-1]) / 14
    t0 = (pub or now - 7200) * 1000
    awal = next((x[1] for x in k if x[0] + 3600000 > t0), k[-2][1])
    return atr, (k[-1][4] / awal - 1) * 100, k[-1][4]


def _mandiri(sym, arah, kat, pub, now, eng):
    """SARAN NEWS MANDIRI: dipakai saat engine berlawanan atau belum punya saran, tapi sejarah jenis berita ini kuat."""
    import qse_catat as CT
    d = DAMPAK[kat]
    if CT.mati("news_mandiri"):
        return "⛔ Jalur news mandiri sedang dihentikan karena hasil live-nya jelek. Ikuti engine saja."
    if pub and now - pub > 3 * 3600:
        return (f"⏳ Berita sudah {(now - pub) / 3600:.0f} jam. Dampak jenis berita ini biasanya sudah berjalan, "
                f"jangan kejar dari berita ini.")
    m = _atr1j(sym, pub, now)
    if not m:
        return "👀 Data harga gagal diambil, jangan entry dari berita ini dulu."
    atr, gerak, px = m
    L = arah == "LONG"
    if (gerak if L else -gerak) >= 0.6 * abs(d["b24"]):
        return (f"⏳ Harga sudah bergerak {gerak:+.2f}% sejak berita, lebih dari 60% gerak khas jenis berita ini "
                f"({d['b24']:+.2f}%). Terlambat, jangan kejar.")
    adv = (abs(d["dd"]) if L else d["up"]) / 100 * px
    dist = max(1.5 * atr, 1.2 * adv)
    e = px - 0.25 * atr if L else px + 0.25 * atr
    sl, t1, t2 = (e - dist, e + dist, e + 2 * dist) if L else (e + dist, e - dist, e - 2 * dist)
    t = (_hasil(sym) or {}).get("tick", 0.0001 if px < 100 else 0.1)
    batas = dt.datetime.fromtimestamp(now + 7200, WIB).strftime("%d/%m %H:%M WIB")
    CT.tambah("news_mandiri", sym, arah, e, sl, t1, t2, 2.0, LABEL.get(kat, kat))
    pc = lambda x: abs(x - e) / e * 100
    st = CT.statistik("news_mandiri")
    return (f"📰 <b>SARAN NEWS MANDIRI {arah} {sym}</b> (sejarah berita ini lebih kuat dari engine, engine condong {eng or '-'})\n"
            f"<pre>LIMIT {TG.fp(e, t)}\nSL    {TG.fp(sl, t)}  -1.00R  -{pc(sl):.1f}%\n"
            f"TP1   {TG.fp(t1, t)}  +1.00R  +{pc(t1):.1f}%\nTP2   {TG.fp(t2, t)}  +2.00R  +{pc(t2):.1f}%</pre>\n"
            f"↳ Backtest jalur news mandiri: {BT_MANDIRI}."
            + (f" Live: {st['n']} trade, WR {st['wr']:.0f}%, PF {st['pf']:.2f}." if st["n"] else " Live: belum ada trade selesai.")
            + f"\n↳ Pakai setengah lot. Berlaku sampai {batas}, kalau belum terisi batalkan. SL sudah memberi ruang untuk "
            f"goyangan khas jenis berita ini.")


def _saran(sym, arah, now, kat=None, pub=None):
    """Sambungkan arah berita dengan engine. Kalau berlawanan, sejarah jenis berita yang menentukan. Return teks."""
    import qse_catat as CT
    r = _hasil(sym)
    akhir = dt.datetime.fromtimestamp((int(now // 14400) + 1) * 14400, WIB)
    batas = akhir.strftime("%d/%m %H:%M WIB")
    eng = ((r.get("pasar") or {}).get("arah") or r.get("bias")) if r else None
    if r:
        t = r["tick"]
        for x in r.get("saran") or []:
            if x["arah"] == arah and x["eksekusi"] and not x.get("sudah_masuk") and x["mutu"] in ("A", "B"):
                CT.tambah("news_searah", sym, arah, x["entry"], x["sl"], x["tp1"], x["tp2"],
                          max(0.5, (akhir.timestamp() - now) / 3600), f"{x['pola']} + berita")
                return (f"✅ <b>SARAN ENTRY {arah} {sym}</b> (berita dan engine searah)\n"
                        f"↳ {x['order']} di <code>{TG.fp(x['entry'], t)}</code> | SL <code>{TG.fp(x['sl'], t)}</code> | "
                        f"TP1 <code>{TG.fp(x['tp1'], t)}</code> | TP2 <code>{TG.fp(x['tp2'], t)}</code>\n"
                        f"↳ pola {TG.e(x['pola'])} mutu {x['mutu']}, rapor robot {r['rapor']}. Berlaku sampai {batas}.")
    if kat and kuat_mandiri(kat) and sym == "BTCUSDT":
        return _mandiri(sym, arah, kat, pub, now, eng)
    if not r:
        return f"👀 {sym} belum ada di scan robot. Jangan entry dari berita saja."
    t = r["tick"]
    if eng == arah:
        gp = (r.get("pasar") or {}).get("gp")
        zona = f" Zona tunggu {TG.fp(min(gp), t)} sampai {TG.fp(max(gp), t)}." if gp else ""
        return (f"🟡 {arah} {sym} searah bias engine, tapi belum ada saran valid (rapor {r['rapor']}).{zona} "
                f"Entry hanya kalau harga masuk zona dan ada candle konfirmasi searah, sebelum {batas}.")
    return (f"⛔ Engine {sym} condong {eng or '-'}, berlawanan dengan berita, dan sejarah jenis berita ini tidak cukup "
            f"konsisten untuk melawan engine. Jangan entry dari berita ini.")


def tes():
    """Perintah /berita: uji semua sumber, terjemahan, dan harga Bybit dari VPS. Tidak mengubah catatan berita."""
    rows, contoh = [], None
    for nama, url in SUMBER:
        b = _ambil(nama, url)
        rows.append(f"{'✅' if b else '❌'} {TG.e(nama)}: {len(b)} berita")
        if b and contoh is None:
            contoh = b[0]
    ok = sum(r.startswith("✅") for r in rows)
    out = "\n".join(rows) + f"\n\nSumber hidup: {ok} dari {len(SUMBER)}"
    if contoh:
        t = terjemah(contoh["judul"])
        out += (f"\n\nContoh: {TG.e(contoh['judul'][:150])}\n↳ terjemahan: {TG.e(t[:150])}"
                + ("" if t != contoh["judul"] else "\n↳ ❌ terjemahan gagal, teks asli dipakai"))
    hp = _harga("BTCUSDT")
    out += f"\n\nHarga BTC dari Bybit: {hp if hp else '❌ gagal'}"
    out += ("\n\nNews ke trade siap jalan. Berita baru dicek tiap 15 menit." if ok and hp
            else "\n\nAda yang gagal. Kirim foto pesan ini ke Claude.")
    return out


def cek(simbol, maks=4):
    """simbol = set simbol Bybit (mis. {'BTCUSDT', ...}). Return daftar pesan siap kirim."""
    c = _load()
    sudah = set(c.get("kirim", []))
    awal = not sudah
    now = time.time()
    out = []
    for nama, url in SUMBER:
        for b in _ambil(nama, url):
            kunci = re.sub(r"\W+", "", b["judul"].lower())[:90]
            if not kunci or kunci in sudah:
                continue
            sudah.add(kunci)
            if awal or len(out) >= maks:
                continue
            teks = b["judul"] + " " + b["isi"][:200]
            kat = kategori(teks)
            arah, kuat = _nilai(teks)
            if kat:
                arah = arah_sejarah(kat) or arah
                dk = DAMPAK.get(kat, {})
                kuat = "KUAT" if kuat_mandiri(kat) else ("SEDANG" if abs(dk.get("b24", 0)) >= 1 else "LEMAH")
            if not arah:
                continue
            koin = _koin(teks, simbol) or (["BTC"] if kat and "BTCUSDT" in simbol else [])
            if not koin:
                continue
            inti = terjemah(b["judul"])
            ringkas = terjemah(b["isi"][:300]) if b["isi"] and len(b["isi"]) > 40 else ""
            arah_t = "LONG" if arah > 0 else "SHORT"
            umur = f" | terbit {(now - b['pub']) / 60:.0f} menit lalu" if b.get("pub") and now >= b["pub"] else ""
            rows = [f"🗞️ <b>{TG.e(inti)}</b>",
                    f"↳ {TG.e(b['sumber'])}{umur} | dampak {'POSITIF' if arah > 0 else 'NEGATIF'} {kuat} untuk {', '.join(koin)}"
                    + (f" | jenis: {LABEL.get(kat, kat)}" if kat else "")]
            if ringkas:
                rows.append(f"↳ Intinya: {TG.e(ringkas[:280])}")
            if b["link"]:
                rows.append(f"↳ {TG.e(b['link'])}")
            if kat:
                rows.append(sejarah_teks(kat))
                a24 = DAMPAK.get(kat, {}).get("alt24", 0)
                if a24 <= -1.5:
                    rows.append("↳ Di sejarah, altcoin biasanya kena lebih parah dari BTC. Hindari LONG alt dulu.")
                elif a24 >= 1.5:
                    rows.append("↳ Di sejarah, altcoin biasanya naik lebih kuat dari BTC setelah berita jenis ini.")
            else:
                rows.append("📚 Jenis berita ini belum ada di sejarah 2022-2026, penilaian hanya dari kata kunci.")
            for base in koin:
                sym = base + "USDT"
                hp = _harga(sym)
                rows.append((f"💲 {sym} sekarang {TG.fp(hp, (_hasil(sym) or {}).get('tick', 0.0001))}. " if hp else "")
                            + f"Arah dari berita: {arah_t}.")
                rows.append(_saran(sym, arah_t, now, kat, b.get("pub")))
            out.append("\n".join(rows))
    c["kirim"] = list(sudah)[-1500:]
    _save(c)
    return out
