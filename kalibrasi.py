"""Cocokkan bot dengan DASBOR. Pakai: python kalibrasi.py AUCTIONUSDT TRXUSDT
Buka koin yang sama di TradingView: BYBIT:<KOIN>.P, timeframe 4 jam, indikator QSE v148 DASBOR.
Bandingkan baris 16 Rapor robot dan panel STATUS dengan tabel ini, lalu pakai setelan yang paling cocok."""
import sys
import warnings
import config
import bybit_fetch as B
import qse_scan

warnings.filterwarnings("ignore")


def main(syms):
    ticks = B.get_symbols()
    btc = B.get_klines("BTCUSDT", "240", config.TV_BARS - 1)
    for sym in syms:
        if sym not in ticks:
            print(sym, "tidak ada di perpetual USDT Bybit")
            continue
        df = B.get_klines(sym, "240", config.TV_BARS - 1)
        h1 = B.get_klines(sym, "60", len(df) * 4 + 400)
        dD = B.get_klines(sym, "D", 1500, closed_only=False)
        dW = B.get_klines(sym, "W", 400, closed_only=False)
        print(f"\n{sym}  BYBIT:{sym}.P  4 jam  candle {len(df)}")
        for bars in (0, 5000):
            for mode in ("first", "last"):
                config.H1_INTRABAR = mode
                hh = h1 if bars == 0 else h1.iloc[-(bars - 1):]
                r = qse_scan.process(sym, df, hh, dD, dW, btc, ticks[sym])
                sar = " | ".join(f"S{s['slot']} {s['arah'][0]} {s['pola']} {s['mutu']} "
                                 f"{'EKSEKUSI' if s['eksekusi'] else 'TAHAN ' + s['alasan']} E {s['entry']:.6g}"
                                 for s in r["saran"]) or "belum ada saran"
                print(f"  QSE_H1_BARS={bars:<5} QSE_H1_INTRABAR={mode:<5} | rapor {r['rapor']} {r['trd']}trd "
                      f"WR{r['wr']:.0f} PF{r['pf']:.2f} {r['net_r']:+.1f}R | lolos {r['lolos']} | {sar}")


if __name__ == "__main__":
    main([s.upper() for s in sys.argv[1:]] or ["BTCUSDT"])
