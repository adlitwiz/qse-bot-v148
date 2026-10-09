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
    for it in re.findall(r"<(?:item|entry)>(.*?)</(?:item|entry)>", x, re.S)[:25]:
        t = re.search(r"<title[^>]*>(.*?)</title>", it, re.S)
        if not t:
            continue
        ln = re.search(r"<link[^>]*?(?:href=\"([^\"]+)\"[^>]*/?>|>(.*?)</link>)", it, re.S)
        d = re.search(r"<(?:description|summary|content)[^>]*>(.*?)</(?:description|summary|content)>", it, re.S)
        out.append(dict(sumber=nama, judul=_bersih(t.group(1)),
                        link=(ln.group(1) or ln.group(2) or "").strip() if ln else "",
                        isi=_bersih(d.group(1))[:400] if d else ""))
    return out


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


def _saran(sym, arah, now):
    """Sambungkan arah berita dengan engine. Return teks saran."""
    r = _hasil(sym)
    akhir = dt.datetime.fromtimestamp((int(now // 14400) + 1) * 14400, WIB)
    batas = akhir.strftime("%d/%m %H:%M WIB")
    if not r:
        return f"👀 {sym} belum ada di scan robot. Jangan entry dari berita saja."
    t = r["tick"]
    eng = (r.get("pasar") or {}).get("arah") or r.get("bias")
    for x in r.get("saran") or []:
        if x["arah"] == arah and x["eksekusi"] and not x.get("sudah_masuk") and x["mutu"] in ("A", "B"):
            return (f"✅ <b>SARAN ENTRY {arah} {sym}</b> (berita dan engine searah)\n"
                    f"↳ {x['order']} di <code>{TG.fp(x['entry'], t)}</code> | SL <code>{TG.fp(x['sl'], t)}</code> | "
                    f"TP1 <code>{TG.fp(x['tp1'], t)}</code> | TP2 <code>{TG.fp(x['tp2'], t)}</code>\n"
                    f"↳ pola {TG.e(x['pola'])} mutu {x['mutu']}, rapor robot {r['rapor']}. Berlaku sampai {batas}.")
    if eng == arah:
        gp = (r.get("pasar") or {}).get("gp")
        zona = f" Zona tunggu {TG.fp(min(gp), t)} sampai {TG.fp(max(gp), t)}." if gp else ""
        return (f"🟡 {arah} {sym} searah bias engine, tapi belum ada saran valid (rapor {r['rapor']}).{zona} "
                f"Entry hanya kalau harga masuk zona dan ada candle konfirmasi searah, sebelum {batas}.")
    return f"⛔ Engine {sym} condong {eng or '-'}, berlawanan dengan berita. Jangan entry dari berita ini."


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
            arah, kuat = _nilai(b["judul"] + " " + b["isi"][:200])
            if not arah:
                continue
            koin = _koin(b["judul"] + " " + b["isi"][:200], simbol)
            if not koin:
                continue
            inti = terjemah(b["judul"])
            ringkas = terjemah(b["isi"][:300]) if b["isi"] and len(b["isi"]) > 40 else ""
            arah_t = "LONG" if arah > 0 else "SHORT"
            rows = [f"🗞️ <b>{TG.e(inti)}</b>",
                    f"↳ {TG.e(b['sumber'])} | dampak {'POSITIF' if arah > 0 else 'NEGATIF'} {kuat} untuk {', '.join(koin)}"]
            if ringkas:
                rows.append(f"↳ Intinya: {TG.e(ringkas[:280])}")
            if b["link"]:
                rows.append(f"↳ {TG.e(b['link'])}")
            for base in koin:
                sym = base + "USDT"
                hp = _harga(sym)
                rows.append((f"💲 {sym} sekarang {TG.fp(hp, (_hasil(sym) or {}).get('tick', 0.0001))}. " if hp else "")
                            + f"Arah dari berita: {arah_t}.")
                rows.append(_saran(sym, arah_t, now))
            out.append("\n".join(rows))
    c["kirim"] = list(sudah)[-1500:]
    _save(c)
    return out
