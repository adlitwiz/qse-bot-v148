"""Cetak isi mesin bot di setiap candle 4J sekitar tanggal tertentu, untuk dicocokkan dengan label debug DASBOR v150.
Pakai: ~/qse_state/venv/bin/python banding.py PENDLEUSDT
Bandingkan baris per baris dengan label abu-abu di chart BYBIT:PENDLEUSDT.P 4J (QSE v150 DASBOR)."""
import sys
import time
import datetime as dt
import warnings
import numpy as np
import config
import bybit_fetch as B
import qse_features as F
import qse_engine as E
import qse_scan as S

warnings.filterwarnings("ignore")
WIB = dt.timezone(dt.timedelta(hours=7))
H4 = 4 * 3600000
TANGGAL = [(2026, 9, 2), (2026, 9, 6), (2026, 9, 18), (2026, 10, 4)]
P = 33  # Tembus Trendline
KEYS = ("close", "high", "low", "atr", "cLa", "cSa", "kOKL", "kOKS", "okL", "okS", "g0L", "g0S", "mktOk", "slLv",
        "slSv", "rgIdx", "trending", "ranging", "pPr")
KEYS2 = ("biasLg", "lvL", "lvS", "sw8L", "sw8H", "wkBL", "wkBS", "obU", "obD", "capMove", "d1", "btcOkL", "btcOkS",
         "isSpk", "trapU", "trapD")


def _cut(df):
    now = int(time.time() * 1000)
    ts = df.index.values.astype("datetime64[ms]").astype("int64")
    return df[ts + H4 <= now]


def f2(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def main(sym):
    ticks = B.get_symbols()
    tick = float(ticks[sym])
    d4 = B.get_klines(sym, "240", config.TV_BARS, closed_only=False)
    dD = B.get_klines(sym, "D", 1500, closed_only=False)
    dW = B.get_klines(sym, "W", 400, closed_only=False)
    b4 = B.get_klines("BTCUSDT", "240", config.TV_BARS, closed_only=False)
    df = _cut(d4).iloc[-(config.TV_BARS - 1):]
    btc = _cut(b4).iloc[-(config.TV_BARS - 1):]
    h1 = B.get_klines(sym, "60", len(df) * 4 + 400)
    config.H1_INTRABAR = "first"
    v = F.build(df, h1, dD, dW, btc, sym, tick)
    ts = np.asarray(v["ts"]).astype(np.int64)
    mu = S.mulai_uji(ts, H4)
    barNo = (ts // H4).astype(np.int64)
    print(f"{sym} candle {len(ts)} mulai uji {mu} | bandingkan dengan label debug DASBOR v150\n")
    for (y, m, d) in TANGGAL:
        t0 = int(dt.datetime(y, m, d, tzinfo=WIB).timestamp() * 1000)
        idx = np.where((ts >= t0 - 86400000) & (ts < t0 + 86400000))[0]
        for t in idx:
            if t < mu:
                continue
            a = [v[k][:t + 1] for k in KEYS] + [barNo[:t + 1]] + [v[k][:t + 1] for k in KEYS2]
            r = E.run(mu, *a, S.BRK, S.FAM, S.TPV, S.PARR, tick)
            (rkId, rkDr, vlSt, vlId, vlDir, vlE, vlS, vlP, vlP2, vlTy, vlBar, vlDb, vlTc, vlMae, vlDn, vlLs, vlLsR,
             vlCnt, vlRes, s1A, sSc, sJ, sWb, sNn, sEx, sPF, wnA, lsA, ntA, pfA, wrA, bnA, pvA, hafL, hafS,
             *_rest) = r
            wkt = dt.datetime.fromtimestamp(ts[t] / 1000, WIB).strftime("%d/%m %H:%M")
            rk = " ".join(f"{int(rkId[k])}{'L' if rkDr[k] else 'S'}" for k in range(5))
            vl = " ".join(f"{int(vlSt[k])}/{int(vlId[k])}/{int(vlDir[k])}" for k in range(5))
            q = P + 90
            print(f"{wkt} bias {'B' if v['biasLg'][t] else 'S'} btcL {int(bool(v['btcOkL'][t]))} "
                  f"btcS {int(bool(v['btcOkS'][t]))}")
            print(f"  rk {rk}")
            print(f"  vl {vl}")
            print(f"  TT L {int(wnA[P])}/{int(lsA[P])} net {f2(ntA[P])} pv {int(pvA[P])} ban {int(bnA[P])} | "
                  f"S {int(wnA[q])}/{int(lsA[q])} net {f2(ntA[q])} pv {int(pvA[q])} ban {int(bnA[q])}")
            print(f"  sc {sSc[P]:.1f} wb {sWb[P]:.1f} ex {f2(sEx[P])} pf {f2(sPF[P])}\n")


if __name__ == "__main__":
    main((sys.argv[1] if len(sys.argv) > 1 else "PENDLEUSDT").upper())
