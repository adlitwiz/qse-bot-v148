"""QSE v148 - ALTSEASON METER (masuk laporan 4 jam dan perintah /altseason).
Keranjang altcoin besar (ETH, SOL, XRP, DOGE, ADA, LINK, AVAX, BNB, LTC) dibandingkan dengan BTC.
Statistik di bawah dari backtest harian Jan 2022 sampai Okt 2026 (data Binance): apakah keranjang alt
mengalahkan BTC dalam 14 hari berikutnya, dikelompokkan menurut arah alt/BTC 7 hari terakhir dan arah BTC 30 hari."""
import math
import requests
from config import BYBIT_URL

ALT = ("ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "LINKUSDT", "AVAXUSDT", "BNBUSDT", "LTCUSDT")
# (alt/BTC 7 hari naik, BTC 30 hari naik) -> (jumlah hari, peluang alt menang 14 hari, rata selisih %)
SEJARAH = {(True, True): (425, 47, +0.2), (True, False): (296, 29, -2.6),
           (False, True): (497, 45, -0.5), (False, False): (481, 44, -1.2)}
DASAR = 42


def _harian(sym, n=40):
    r = requests.get(BYBIT_URL + "/v5/market/kline", timeout=10,
                     params={"category": "linear", "symbol": sym, "interval": "D", "limit": n})
    rows = sorted(r.json()["result"]["list"], key=lambda x: int(x[0]))
    return [float(x[4]) for x in rows]


def ukur():
    btc = _harian("BTCUSDT")
    if len(btc) < 32:
        return None
    lr = []
    for s in ALT:
        try:
            c = _harian(s)
        except Exception:
            continue
        if len(c) >= 32:
            lr.append(c)
    if len(lr) < 5:
        return None
    # indeks keranjang = rata log return harian, dibanding BTC
    def ret(c, k):
        return math.log(c[-1] / c[-1 - k])
    alt7 = sum(ret(c, 7) for c in lr) / len(lr)
    rasio7 = (alt7 - ret(btc, 7)) * 100
    btc30 = (btc[-1] / btc[-31] - 1) * 100
    return dict(rasio7=rasio7, btc30=btc30, alt7=(math.exp(alt7) - 1) * 100, btc7=(btc[-1] / btc[-8] - 1) * 100)


def teks():
    try:
        m = ukur()
    except Exception:
        m = None
    if not m:
        return ""
    kn, bn = m["rasio7"] > 0, m["btc30"] > 0
    n, p, ex = SEJARAH[(kn, bn)]
    if kn and bn:
        rezim, saran = "alt menguat dan BTC naik", "rezim paling baik untuk alt di sejarah ini, tapi peluangnya tetap di bawah 50%. Pilih alt rapor A/B saja."
    elif kn and not bn:
        rezim, saran = "alt naik saat BTC turun", "JEBAKAN ALT. Di sejarah ini rezim terburuk, alt biasanya kalah dari BTC. Hindari LONG alt."
    elif bn:
        rezim, saran = "BTC naik, alt tertinggal", "peluang alt mengejar sedikit di atas rata rata. Tetap selektif, BTC masih lebih aman."
    else:
        rezim, saran = "alt dan BTC sama sama lemah", "utamakan BTC atau tunggu. Alt cenderung kalah."
    return (f"🌈 <b>ALTSEASON METER</b>\n"
            f"Keranjang 9 alt besar 7 hari {m['alt7']:+.1f}% vs BTC {m['btc7']:+.1f}% (selisih {m['rasio7']:+.1f}%) | "
            f"BTC 30 hari {m['btc30']:+.1f}%\n"
            f"Rezim: {rezim}\n"
            f"Sejarah 2022-2026 ({n} hari mirip): alt mengalahkan BTC dalam 14 hari berikutnya {p}% "
            f"(rata rata semua hari {DASAR}%), selisih rata {ex:+.1f}%\n"
            f"↳ {saran}")
