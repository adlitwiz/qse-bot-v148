"""Cocokkan bot dengan DASBOR.
TF 4 jam : python kalibrasi.py AUCTIONUSDT TRXUSDT
TF 1 jam : python kalibrasi.py 60 HBARUSDT KAITOUSDT
Buka koin yang sama di TradingView (BYBIT:<KOIN>.P) dengan timeframe yang sama dan indikator QSE v148 DASBOR.
Bandingkan tepat setelah candle tutup, karena panel TradingView ikut berubah selama candle berjalan."""
import sys
import time
import datetime as dt
import warnings
import config
import bybit_fetch as B
import qse_scan

warnings.filterwarnings("ignore")
WIB = dt.timezone(dt.timedelta(hours=7))


def _cut(df, iv):
    now = int(time.time() * 1000)
    ts = df.index.values.astype("datetime64[ms]").astype("int64")
    return df[ts + iv <= now]


def _cetak(r):
    t = dt.datetime.fromtimestamp((r["time"] + r["tf_ms"]) / 1000, WIB).strftime("%d/%m %H:%M WIB")
    print(f"  candle tutup {t} | rapor {r['rapor']} {r['trd']}trd WR{r['wr']:.0f} PF{r['pf']:.2f} {r['net_r']:+.1f}R "
          f"| bias {r['bias']} | {r['btc']} | lolos {r['lolos']} | golden saran {r['golden'] or '-'}")
    if not r["saran"]:
        print("    belum ada saran")
    for s in r["saran"]:
        v = "EKSEKUSI" if s["eksekusi"] else "TAHAN " + s["alasan"]
        if s["sudah_masuk"]:
            v += " (robot AKTIF)"
        print(f"    Saran {s['slot']} {s['arah']:<5} {s['pola']:<22} mutu {s['mutu']} | {v} | {s['order']} "
              f"E {s['entry']:.6g} SL {s['sl']:.6g} TP1 {s['tp1']:.6g} TP2 {s['tp2']:.6g}")


def main(args):
    tf = "240"
    if args and args[0] in ("60", "240"):
        tf, args = args[0], args[1:]
    syms = [s.upper() for s in args] or ["BTCUSDT"]
    ticks = B.get_symbols()
    H4, H1 = 4 * 3600000, 3600000
    b4 = B.get_klines("BTCUSDT", "240", config.TV_BARS, closed_only=False)
    b1 = B.get_klines("BTCUSDT", "60", config.TV_BARS)
    for sym in syms:
        if sym not in ticks:
            print(sym, "tidak ada di perpetual USDT Bybit")
            continue
        d4 = B.get_klines(sym, "240", config.TV_BARS, closed_only=False)
        dD = B.get_klines(sym, "D", 1500, closed_only=False)
        dW = B.get_klines(sym, "W", 400, closed_only=False)
        if tf == "60":
            h1 = B.get_klines(sym, "60", config.TV_BARS - 1)
            print(f"\n{sym}  BYBIT:{sym}.P  TF 1 jam  candle {len(h1)}")
            _cetak(qse_scan.process(sym, h1, None, dD, dW, b4, ticks[sym], "60", d4, b1, btc_live=b4))
            continue
        df = _cut(d4, H4).iloc[-(config.TV_BARS - 1):]
        h1 = B.get_klines(sym, "60", len(df) * 4 + 400)
        btc = _cut(b4, H4).iloc[-(config.TV_BARS - 1):]
        print(f"\n{sym}  BYBIT:{sym}.P  TF 4 jam  candle {len(df)}")
        for bars in (0, 5000):
            for mode in ("first", "last"):
                config.H1_INTRABAR = mode
                hh = h1 if bars == 0 else h1.iloc[-(bars - 1):]
                print(f" QSE_H1_BARS={bars} QSE_H1_INTRABAR={mode}")
                _cetak(qse_scan.process(sym, df, hh, dD, dW, btc, ticks[sym], btc_live=b4))


if __name__ == "__main__":
    main(sys.argv[1:])
