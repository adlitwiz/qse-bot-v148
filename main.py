"""QSE v148 Bot - pindai semua perpetual USDT Bybit tiap candle 4H tutup, kirim sinyal ke Telegram.
Jalankan: python main.py   (lihat config.py untuk pengaturan lewat environment)."""
import os
import sys
import csv
import json
import time
import datetime as dt
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

from config import STATE_DIR, TV_BARS, H1_BARS, FETCH_THREADS, PROC_WORKERS, ONLY_SYMBOLS, FP, SEND_EMPTY

os.makedirs(STATE_DIR, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(STATE_DIR, "numba_cache"))
warnings.filterwarnings("ignore")

import bybit_fetch as B
import qse_fixprofit as FX
import telegram_notify as TG

MIN_BARS = 300
_BTC = None


def _init(btc):
    global _BTC
    _BTC = btc
    warnings.filterwarnings("ignore")


def _work(sym, tick, df, h1, dD, dW):
    import qse_scan
    try:
        return qse_scan.process(sym, df, h1, dD, dW, _BTC, tick), None
    except Exception:
        return None, traceback.format_exc(limit=3)


def fetch(sym):
    df = B.get_klines(sym, "240", TV_BARS - 1)
    if len(df) < MIN_BARS:
        return sym, None
    h1 = B.get_klines(sym, "60", (H1_BARS - 1) if H1_BARS > 0 else len(df) * 4 + 400)
    dD = B.get_klines(sym, "D", 1500, closed_only=False)
    dW = B.get_klines(sym, "W", 400, closed_only=False)
    return sym, (df, h1, dD, dW)


def main():
    t0 = time.time()
    syms = B.get_symbols()
    if ONLY_SYMBOLS:
        syms = {s: syms[s] for s in ONLY_SYMBOLS if s in syms}
    tickers = B.get_tickers()
    print(f"Simbol perpetual USDT: {len(syms)}")
    btc = B.get_klines("BTCUSDT", "240", TV_BARS - 1)
    if len(btc) < MIN_BARS:
        sys.exit("[FATAL] data BTCUSDT kurang")
    led = FX.load()
    results, events, fail, skip = [], [], 0, 0
    workers = PROC_WORKERS or os.cpu_count() or 1
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(btc,)) as pool, \
            ThreadPoolExecutor(max_workers=FETCH_THREADS) as net:
        futs_net = {net.submit(fetch, s): s for s in syms}
        futs_cpu = {}
        for i, f in enumerate(as_completed(futs_net), 1):
            s = futs_net[f]
            try:
                _, data = f.result()
            except Exception as ex:
                fail += 1
                print(f"[ERROR] ambil {s}: {ex}")
                if "403" in str(ex):
                    sys.exit(1)
                continue
            if data is None:
                skip += 1
                continue
            events += [(ev, dict(it)) for ev, it in FX.update(led, s, data[0])]
            futs_cpu[pool.submit(_work, s, syms[s], *data)] = s
            if i % 50 == 0:
                print(f"  data {i}/{len(syms)} | {time.time() - t0:.0f}s")
        for f in as_completed(futs_cpu):
            s = futs_cpu[f]
            r, err = f.result()
            if err:
                fail += 1
                print(f"[ERROR] {s}\n{err}")
            else:
                results.append(r)

    sel, drop = FX.select(results, tickers, led)
    blocks = []
    run_t = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    baru = []
    for r, s in sel:
        tag = FX.register(led, r, s)
        if tag:
            baru.append(TG.sinyal(r, s, tag, FP["risk_usdt"]))
    n30, wr30, net30 = FX.stats(led)
    nA = sum(1 for r in results if r["rapor"] == "A")
    nB = sum(1 for r in results if r["rapor"] == "B")
    nG = sum(1 for r in results if r["golden"])
    head = (f"<b>QSE v148 Bot</b> | {run_t}\n"
            f"Dipindai {len(results)} koin | rapor A {nA} | rapor B {nB} | golden {nG}\n"
            f"Sinyal baru {len(baru)} | aktif dipantau {len(led['open'])}")
    if drop:
        head += "\nDisaring fix profit: " + ", ".join(f"{k} {v}" for k, v in sorted(drop.items(), key=lambda x: -x[1]))
    head += f"\nHasil live 30 hari: {n30} trade | WR {wr30:.0f}% | {net30:+.1f}R"
    blocks.append(head)
    blocks += baru
    pantau = _pantau(results)
    if pantau:
        blocks.append(pantau)
    if events:
        blocks.append("<b>Update sinyal sebelumnya</b>\n" + "\n".join(TG.hasil(ev, it, syms) for ev, it in events))
    if baru or events or SEND_EMPTY:
        TG.send(blocks)
    for b in blocks:
        print(b.replace("<b>", "").replace("</b>", ""), "\n")
    FX.save(led)
    _dump(results)
    print(f"Selesai {time.time() - t0:.0f}s | ok {len(results)} gagal {fail} lewati {skip}")


def _pantau(results, maks=25):
    """Koin rapor A/B yang punya saran bernilai A/B dan entry jelas."""
    rows = []
    for r in results:
        if r["rapor"] not in ("A", "B"):
            continue
        ss = [x for x in r["saran"] if x["mutu"] in ("A", "B") and x["entry"] == x["entry"] and x["entry"] > 0]
        if not ss:
            continue
        s = next((x for x in ss if x["eksekusi"]), ss[0])
        rows.append((r, s))
    if not rows:
        return ""
    rows.sort(key=lambda x: (not x[1]["eksekusi"], x[0]["rapor"] != "A", x[1]["mutu"] != "A", -x[1]["peluang"]))
    out = ["<b>Pantauan rapor A/B dengan saran entry</b>"]
    for r, s in rows[:maks]:
        if s["sudah_masuk"]:
            vonis = "posisi robot AKTIF"
        elif s["eksekusi"]:
            vonis = s["mutu"] + " EKSEKUSI" + (", disaring: " + s["saring"] if s.get("saring") else "")
        else:
            vonis = "TAHAN, " + s["alasan"]
        if s["golden"]:
            vonis = "GOLDEN MOMENT, " + vonis
        t = r["tick"]
        out.append(f"{TG.e(r['symbol'])} {s['arah']} | rapor {r['rapor']} {r['trd']}trd WR{r['wr']:.0f}% | "
                   f"{TG.e(s['pola'])} | {TG.e(vonis)} | {TG.e(s['order'])} E {TG.fp(s['entry'], t)} "
                   f"SL {TG.fp(s['sl'], t)} TP1 {TG.fp(s['tp1'], t)} TP2 {TG.fp(s['tp2'], t)}")
    if len(rows) > maks:
        out.append(f"dan {len(rows) - maks} koin lain di screening_terbaru.csv")
    return "\n".join(out)


def _dump(results):
    rows = []
    for r in results:
        base = {k: r[k] for k in ("symbol", "rapor", "trd", "wr", "pf", "net_r", "bias", "regime", "golden", "lolos", "close")}
        if not r["saran"]:
            rows.append(base)
        for s in r["saran"]:
            rows.append({**base, **{k: s[k] for k in ("slot", "pola", "arah", "eksekusi", "alasan", "mutu", "order",
                                                     "entry", "sl", "tp1", "tp2", "rr1", "rr2", "peluang", "ev")}})
    keys = sorted({k for x in rows for k in x}, key=lambda k: list(rows[0].keys()).index(k) if rows and k in rows[0] else 99)
    path = os.path.join(STATE_DIR, "screening_terbaru.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(STATE_DIR, "screening_terbaru.json"), "w") as f:
        json.dump(results, f, default=float)


if __name__ == "__main__":
    main()
