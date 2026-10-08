"""QSE v152 - NEWS KE TRADE. Berita dibaca dengan kamus kata kunci (gratis), lalu dicocokkan dengan engine QSE.
News hanya FILTER: saran entry keluar kalau arah berita dan saran engine searah. Kalau berlawanan, bot bilang TAHAN.
Kalau engine belum punya saran untuk koin itu, bot hanya memberi pantauan, tidak memberi entry dari berita saja."""
import datetime as dt
import json
import os
import re
import time
from config import STATE_DIR

WIB = dt.timezone(dt.timedelta(hours=7))
H4 = 4 * 3600 * 1000

NAMA = {
    "bitcoin": "BTC", "btc": "BTC", "ether": "ETH", "ethereum": "ETH", "eth": "ETH", "ripple": "XRP", "xrp": "XRP",
    "solana": "SOL", "sol": "SOL", "dogecoin": "DOGE", "doge": "DOGE", "cardano": "ADA", "ada": "ADA",
    "bnb": "BNB", "binance coin": "BNB", "tron": "TRX", "trx": "TRX", "avalanche": "AVAX", "avax": "AVAX",
    "chainlink": "LINK", "link": "LINK", "polkadot": "DOT", "dot": "DOT", "litecoin": "LTC", "ltc": "LTC",
    "shiba": "SHIB", "shib": "SHIB", "toncoin": "TON", "ton": "TON", "sui": "SUI", "aptos": "APT", "apt": "APT",
    "arbitrum": "ARB", "arb": "ARB", "optimism": "OP", "near": "NEAR", "pepe": "PEPE", "hyperliquid": "HYPE",
    "hype": "HYPE", "pendle": "PENDLE", "ethena": "ENA", "ena": "ENA", "uniswap": "UNI", "aave": "AAVE",
    "stellar": "XLM", "xlm": "XLM", "hedera": "HBAR", "hbar": "HBAR", "filecoin": "FIL", "injective": "INJ",
    "render": "RENDER", "bonk": "BONK", "worldcoin": "WLD", "wld": "WLD", "ondo": "ONDO", "jupiter": "JUP",
    "celestia": "TIA", "sei": "SEI", "polygon": "POL", "pol": "POL", "ethfi": "ETHFI", "ether.fi": "ETHFI",
}
# koin yang namanya kata umum, wajib huruf besar di judul
KAPITAL = {"HYPE", "RENDER", "LINK", "DOT", "TON", "SOL", "OP", "NEAR", "UNI", "SEI", "POL", "APT", "ARB", "ADA", "SUI"}
PASAR = ("fed ", "fomc", "powell", "rate cut", "rate hike", "cpi", "inflation", "jobs report", "payroll", "tariff",
         "crypto market", "crypto stocks", "liquidat", "etf flows", "spot etf", "treasury", "dollar")

POS = {
    "approv": 3, "etf launch": 3, "listing on": 2, "lists ": 2, "will list": 2, "partnership": 2, "partners with": 2,
    "inflow": 2, "surge": 2, "soar": 2, " rall": 2, "jump": 2, "record high": 3, "all-time high": 3, " ath ": 2,
    "adopt": 2, "buys": 2, "bought": 2, "accumulat": 2, "upgrade": 1, "mainnet": 1, "rate cut": 3, "dovish": 2,
    "bullish": 2, "integrat": 1, " wins": 2, "dismiss": 2, "settle": 1, "reserve": 2, "breakout": 2, "rebound": 1,
    "recover": 1, " gain": 1, "climb": 1, "short squeeze": 2, "burn": 1, "buyback": 2,
}
NEG = {
    "hack": 3, "exploit": 3, "drain": 3, "delist": 3, "lawsuit": 2, " sues": 2, "charged": 2, " ban": 2, "outflow": 2,
    "crash": 3, "plunge": 3, "dump": 2, "liquidat": 2, "sell-off": 2, "selloff": 2, "rate hike": 3, "hawkish": 2,
    "bearish": 2, "investigat": 2, "fraud": 3, "bankrupt": 3, "depeg": 3, "halt": 2, "unlock": 2, "reject": 2,
    "delay": 1, "tariff": 2, " war ": 2, "slump": 2, "tumble": 2, "drop": 1, "fall": 1, "sink": 2, "fear": 1,
    "selling": 1, "whale sells": 2, "attack": 2, "probe": 2, " fined": 1,
}
TIDAK = ("not ", "no ", "denies", "denied", "fails to", "won't", "without")


def _sentimen(judul):
    low = " " + judul.lower() + " "
    neg_kal = any(w in low for w in TIDAK)
    p = sum(v for k, v in POS.items() if k in low)
    n = sum(v for k, v in NEG.items() if k in low)
    if neg_kal and p:
        p, n = 0, n + p
    elif neg_kal and n:
        p, n = n, 0
    skor = p - n
    return skor, ("POSITIF" if skor > 0 else "NEGATIF" if skor < 0 else "NETRAL")


def _koin(judul):
    out = []
    low = judul.lower()
    for k, s in NAMA.items():
        if s in KAPITAL and k == s.lower():
            if re.search(r"\b" + re.escape(s) + r"\b", judul):
                out.append(s)
        elif re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", low):
            out.append(s)
    out += [t for t in re.findall(r"\b([A-Z]{2,10})\b", judul) if t in set(NAMA.values())]
    out = list(dict.fromkeys(out))
    if not out and any(w in " " + low + " " for w in PASAR):
        out = ["BTC"]
    return out[:3]


def relevan(judul):
    """Berita masuk hitungan kalau menyebut koin dan punya arah sentimen."""
    return bool(_koin(judul)) and _sentimen(judul)[0] != 0


def _scan():
    try:
        p = os.path.join(STATE_DIR, "screening_terbaru.json")
        with open(p) as f:
            return {r["symbol"]: r for r in json.load(f) if r.get("tf", "240") == "240"}, os.path.getmtime(p)
    except Exception:
        return {}, 0


def _jam(ms):
    return dt.datetime.fromtimestamp(ms / 1000, WIB).strftime("%d/%m %H:%M WIB")


def saran(judul, e=lambda s: s, delist=()):
    """Baris teks: dampak berita, koin, dan keputusan entry dari gabungan news dan engine."""
    skor, arti = _sentimen(judul)
    koin = _koin(judul)
    if not koin or skor == 0:
        return ""
    kuat = "KUAT" if abs(skor) >= 3 else "SEDANG" if abs(skor) == 2 else "LEMAH"
    arah = "LONG" if skor > 0 else "SHORT"
    scan, mt = _scan()
    now = int(time.time() * 1000)
    sampai = (now // H4 + 1) * H4
    umur = (time.time() - mt) / 60 if mt else 999
    rows = [f"↳ Dampak {arti} {kuat} untuk {', '.join(koin)}. Arah dari berita: {arah}."]
    for k in koin:
        sym = k + "USDT"
        r = scan.get(sym)
        if sym in delist:
            rows.append(f"⛔ {sym}: ada pengumuman delisting Bybit, jangan entry.")
            continue
        if not r:
            rows.append(f"👀 {sym}: belum ada di scan QSE. Pantau saja, jangan entry dari berita saja.")
            continue
        sr = [s for s in r.get("saran", []) if not s.get("sudah_masuk")]
        cocok = [s for s in sr if s.get("arah") == arah]
        lawan = [s for s in sr if s.get("arah") != arah]
        ok = [s for s in cocok if s.get("eksekusi")]
        rap = f"rapor {r.get('rapor', '-')}"
        if ok:
            s = ok[0]
            rows.append(f"✅ <b>SARAN ENTRY {arah} {e(sym)}</b> (news + engine searah, {rap}, {e(s.get('pola', ''))})\n"
                        f"   Entry {s['entry']:.6g} | SL {s['sl']:.6g} | TP1 {s['tp1']:.6g} | TP2 {s['tp2']:.6g} | "
                        f"order {e(str(s.get('order', '-')))}\n"
                        f"   Pasang sekarang {_jam(now)}, berlaku sampai {_jam(sampai)}. "
                        f"Harga scan {r.get('close', 0):.6g} ({umur:.0f} menit lalu).")
        elif cocok:
            s = cocok[0]
            rows.append(f"🟡 {e(sym)}: engine searah ({arah} di {s['entry']:.6g}) tapi belum layak eksekusi: "
                        f"{e(str(s.get('alasan', '-')))}. Tunggu.")
        elif lawan:
            s = lawan[0]
            rows.append(f"🛑 <b>TAHAN {e(sym)}</b>: berita bilang {arah}, engine bilang {s['arah']} "
                        f"({e(s.get('pola', ''))}). Arah bertentangan, jangan entry.")
        else:
            rows.append(f"👀 {e(sym)}: engine belum punya saran ({rap}). Pantau, jangan entry dari berita saja.")
    return "\n".join(rows)
