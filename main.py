"""QSE v148 Bot - pindai semua perpetual USDT Bybit, kirim sinyal ke Telegram.
Jadwal: tiap jam (TF 1J), dan tiap candle 4H tutup (TF 4J + 1J). Paksa semua TF: python main.py semua"""
import os
import sys
import csv
import json
import time
import datetime as dt
import traceback
import warnings
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

from config import STATE_DIR, TV_BARS, H1_BARS, FETCH_THREADS, PROC_WORKERS, ONLY_SYMBOLS, FP, TFS

os.makedirs(STATE_DIR, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(STATE_DIR, "numba_cache"))
warnings.filterwarnings("ignore")

import bybit_fetch as B
import qse_fixprofit as FX
import telegram_notify as TG

MIN_BARS = 300
H4 = 4 * 3600 * 1000
_BTC = {}


def _init(btc):
    global _BTC
    _BTC = btc
    warnings.filterwarnings("ignore")


def _work(sym, tick, pk, tfs):
    import qse_scan
    out, err = [], None
    for tf in tfs:
        try:
            if tf == "240":
                df = pk["h4c"]
                if len(df) < MIN_BARS:
                    continue
                out.append(qse_scan.process(sym, df, pk["h1c"], pk["d"], pk["w"], _BTC["h4c"], tick, "240",
                                            lim_h=FP["limit_hours"]))
            else:
                df = pk["h1c"].iloc[-(TV_BARS - 1):]
                if len(df) < MIN_BARS:
                    continue
                out.append(qse_scan.process(sym, df, None, pk["d"], pk["w"], _BTC["h4"], tick, "60", pk["h4"],
                                            _BTC["h1c"], lim_h=FP["limit_hours"]))
        except Exception:
            err = traceback.format_exc(limit=3)
    return out, err


def _split(df, iv_ms):
    now = int(time.time() * 1000)
    ts = df.index.values.astype("datetime64[ms]").astype("int64")
    return df[ts + iv_ms <= now]


def fetch(sym, run4):
    if run4:
        h4 = B.get_klines(sym, "240", TV_BARS, closed_only=False)
        n1 = (H1_BARS - 1) if H1_BARS > 0 else len(h4) * 4 + 400
    else:
        h4 = B.get_klines(sym, "240", 1600, closed_only=False)
        n1 = TV_BARS
    h1 = B.get_klines(sym, "60", max(n1, TV_BARS), closed_only=False)
    return dict(h4=h4, h4c=_split(h4, H4).iloc[-(TV_BARS - 1):], h1c=_split(h1, 3600000),
                d=B.get_klines(sym, "D", 1500, closed_only=False), w=B.get_klines(sym, "W", 400, closed_only=False))


def main():
    t0 = time.time()
    now = dt.datetime.now(dt.timezone.utc)
    semua = len(sys.argv) > 1 and sys.argv[1] == "semua"
    run4 = "240" in TFS and (semua or now.hour % 4 == 0)
    tfs = [t for t in TFS if t == "60" or (t == "240" and run4)]
    if not tfs:
        print("Bukan jadwal TF yang aktif, selesai.")
        return
    syms = B.get_symbols()
    if ONLY_SYMBOLS:
        syms = {s: syms[s] for s in ONLY_SYMBOLS if s in syms}
    tickers = B.get_tickers()
    print(f"Simbol {len(syms)} | TF {tfs}")
    b4 = B.get_klines("BTCUSDT", "240", TV_BARS, closed_only=False)
    b1 = B.get_klines("BTCUSDT", "60", TV_BARS, closed_only=True)
    btc = dict(h4=b4, h4c=_split(b4, H4).iloc[-(TV_BARS - 1):], h1c=b1)
    led = FX.load()
    results, events, fail = [], [], 0
    workers = PROC_WORKERS or os.cpu_count() or 1
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(btc,)) as pool, \
            ThreadPoolExecutor(max_workers=FETCH_THREADS) as net:
        fn = {net.submit(fetch, s, run4): s for s in syms}
        fc = {}
        for i, f in enumerate(as_completed(fn), 1):
            s = fn[f]
            try:
                pk = f.result()
            except Exception as ex:
                fail += 1
                print(f"[ERROR] ambil {s}: {ex}")
                if "403" in str(ex):
                    sys.exit(1)
                continue
            events += [(ev, dict(it)) for ev, it in FX.update(led, s, pk["h1c"])]
            fc[pool.submit(_work, s, syms[s], pk, tfs)] = s
            if i % 100 == 0:
                print(f"  data {i}/{len(syms)} | {time.time() - t0:.0f}s")
        for f in as_completed(fc):
            out, err = f.result()
            if err:
                fail += 1
                print(f"[ERROR] {fc[f]}\n{err}")
            results += out

    res_map = {(r["symbol"], r["tf"]): r for r in results}
    events += [(ev, dict(it)) for ev, it in FX.recheck(led, res_map, tfs)]
    sel, drop = FX.select(results, tickers, led)
    tag_of = {id(s): (FX.register(led, r, s) or "sudah dikirim") for r, s in sel}
    n_baru = sum(1 for t in tag_of.values() if t != "sudah dikirim")
    for tf in tfs:
        blocks = _pesan_tf(tf, results, sel, tag_of, led, events, syms, now)
        TG.send(blocks)
        for b in blocks:
            print(b, "\n")
    FX.save(led)
    _dump(results)
    print(f"Selesai {time.time() - t0:.0f}s | hasil {len(results)} | gagal {fail}")


WIB = dt.timezone(dt.timedelta(hours=7))
NAMA = {"240": ("4 JAM", "4J"), "60": ("1 JAM", "1J")}


def _jam(ms):
    return dt.datetime.fromtimestamp(ms / 1000, WIB).strftime("%d/%m %H:%M WIB")


def _tabel(s, t):
    risk = max(abs(s["entry"] - s["sl"]), t)
    rows = [("Entry", s["entry"], s["order"]), ("SL", s["sl"], "-1.00R"),
            ("TP1", s["tp1"], "%+.2fR" % (abs(s["tp1"] - s["entry"]) / risk)),
            ("TP2", s["tp2"], "%+.2fR" % (abs(s["tp2"] - s["entry"]) / risk))]
    px = [TG.fp(v, t) for _, v, _ in rows]
    w = max(len(p) for p in px)
    w2 = max(len(x) for _, _, x in rows)
    return "<pre>" + "\n".join(f"{k:<5} {p:>{w}}  {x:>{w2}}" for (k, _, x), p in zip(rows, px)) + "</pre>"


def _blok(no, r, s, status, led=None):
    t = r["tick"]
    g = "GOLDEN MOMENT | " if s["golden"] else ""
    z = " | zona emas" if s["zona_emas"] else ""
    rows = [f"➡️ <b>{no}. {TG.e(r['symbol'])} {s['arah']}</b>",
            f"Rapor robot {r['rapor']} ({r['trd']} trade, WR {r['wr']:.0f}%, PF {r['pf']:.2f})",
            f"Pola: {TG.e(s['pola'])} | mutu {s['mutu']}{z}",
            f"Pola ini: {s['win']} TP / {s['loss']} SL | WR {s['wr']:.0f}% | {s['net_r']:+.1f}R",
            f"Status: {g}{TG.e(status)}",
            _tabel(s, t)]
    key = "%s|%s|%s|%s" % (r["symbol"], r["tf"], s["pola"], s["arah"])
    it = (led or {}).get("open", {}).get(key)
    if s["order"] == "MARKET":
        rows.append("Cara: eksekusi MARKET sekarang, pasang SL dan TP1 langsung.")
    else:
        batas = _jam(it["exp_ts"]) if it and it.get("exp_ts") else "24 jam"
        rows.append(f"Cara: pasang LIMIT di entry. Peluang terisi {s['p_isi']:.0f}%. Batal otomatis {batas}.")
    rows.append("Di TP1 tutup separuh, geser SL ke entry, sisanya ke TP2.")
    if FP["risk_usdt"] > 0:
        qty = FP["risk_usdt"] / max(abs(s["entry"] - s["sl"]), t)
        rows.append(f"Lot risiko {FP['risk_usdt']:g} USDT: {qty:.4g} koin | nilai {qty * s['entry']:,.0f} USDT")
    rows.append(f'<a href="https://www.tradingview.com/chart/?symbol=BYBIT:{r["symbol"]}.P">Chart {TG.e(r["symbol"])}.P</a>')
    return "\n".join(rows)


def _rekap(led, now):
    a = int(dt.datetime(now.year, now.month, now.day, tzinfo=dt.timezone.utc).timestamp() * 1000) - 86400000
    b = a + 86400000
    cl = [c for c in led["closed"] if c.get("why") in ("SL", "BE", "TP2") and a <= c.get("closed_ts", 0) < b]
    if not cl:
        return "<b>REKAP KEMARIN</b>\nTidak ada trade yang selesai."
    net = sum(c["result_r"] for c in cl)
    win = sum(1 for c in cl if c["result_r"] > 0)
    rows = [f"<b>REKAP KEMARIN</b> | {len(cl)} trade | WR {win / len(cl) * 100:.0f}% | {net:+.2f}R"]
    rows += [f"➡️ {TG.e(c['sym'])} {c['arah']} TF {NAMA.get(c.get('tf', '240'), ('', '4J'))[1]} | "
             f"{TG.e(c['pola'])} | {c['why']} {c['result_r']:+.2f}R" for c in cl]
    return "\n".join(rows)


def _pesan_tf(tf, results, sel, tag_of, led, events, syms, now):
    judul, kode = NAMA[tf]
    rs = [r for r in results if r["tf"] == tf]
    sig = [(r, s) for r, s in sel if r["tf"] == tf]
    ev = [(e, it) for e, it in events if it.get("tf", "240") == tf]
    tahan, buang = [], []
    for r in rs:
        if r["rapor"] not in ("A", "B"):
            continue
        for s in r["saran"]:
            if s["eksekusi"] and not s["sudah_masuk"] and s["mutu"] in ("A", "B"):
                if s.get("saring"):
                    tahan.append((r, s))
                elif s.get("buang"):
                    buang.append((r, s))
    rA = sorted(r["symbol"] for r in rs if r["rapor"] == "A")
    rB = sorted(r["symbol"] for r in rs if r["rapor"] == "B")
    tutup = rs[0]["time"] + rs[0]["tf_ms"] if rs else 0
    baru = sum(1 for r, s in sig if tag_of[id(s)] != "sudah dikirim")
    head = [f"<b>QSE v148 | LAPORAN {judul} (TF {kode})</b>",
            f"Candle {kode} tutup {_jam(tutup)}" if tutup else now.astimezone(WIB).strftime("%d/%m %H:%M WIB")]
    bt = next((r for r in results if r["tf"] == "240"), rs[0] if rs else None)
    if bt:
        head.append(f"{TG.e(bt['btc'])} | peluang naik {bt['bProb']:.0f}%")
    head.append(f"Dipindai {len(rs)} koin | rapor A {len(rA)} | rapor B {len(rB)}")
    head.append(f"Sinyal valid {len(sig)} | baru {baru} | masih valid {len(sig) - baru}")
    out = ["\n".join(head)]
    if tf == "240" and now.hour == 0:
        out.append(_rekap(led, now))
    out.append(f"<b>1. SINYAL VALID TF {kode} ({len(sig)})</b>" +
               ("" if sig else "\nBelum ada sinyal yang lolos semua syarat di candle ini."))
    for i, (r, s) in enumerate(sig, 1):
        tg = tag_of[id(s)]
        st = f"{s['mutu']} EKSEKUSI, " + ("SINYAL BARU" if tg in ("BARU", "UPDATE") else "masih valid")
        if s.get("tersentuh"):
            st += ", entry pernah tersentuh"
        out.append(_blok(i, r, s, st, led))
    out.append(f"<b>2. UPDATE ORDER TF {kode} ({len(ev)})</b>\n" +
               ("\n".join("➡️ " + TG.hasil(e, it, syms) for e, it in ev) if ev else "Tidak ada perubahan order."))
    if rA or rB:
        out.append(f"<b>3. KOIN RAPOR A/B TF {kode}</b>\n" +
                   (f"A: {', '.join(rA)}\n" if rA else "") + (f"B: {', '.join(rB)}" if rB else ""))
    if tahan or buang:
        rows = [f"<b>4. HAMPIR, BELUM VALID ({len(tahan) + len(buang)})</b>"]
        rows += [f"➡️ {TG.e(r['symbol'])} {s['arah']} | {TG.e(s['pola'])} | {TG.e(s['saring'])}" for r, s in tahan[:10]]
        rows += [f"➡️ {TG.e(r['symbol'])} {s['arah']} | {TG.e(s['pola'])} | {TG.e(s['buang'])}" for r, s in buang[:15]]
        out.append("\n".join(rows))
    n30, wr30, net30 = FX.stats(led)
    out.append(f"Live 30 hari semua TF: {n30} trade | WR {wr30:.0f}% | {net30:+.1f}R")
    return out


def _dump(results):
    rows = []
    for r in results:
        base = {k: r[k] for k in ("symbol", "tf", "rapor", "trd", "wr", "pf", "net_r", "bias", "regime", "golden",
                                  "lolos", "close")}
        if not r["saran"]:
            rows.append(base)
        for s in r["saran"]:
            rows.append({**base, **{k: s.get(k) for k in ("slot", "pola", "arah", "eksekusi", "alasan", "mutu", "order",
                                                         "entry", "sl", "tp1", "tp2", "rr1", "rr2", "p_isi", "ev")}})
    if not rows:
        return
    keys = list(dict.fromkeys(k for x in rows for k in x))
    with open(os.path.join(STATE_DIR, "screening_terbaru.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(STATE_DIR, "screening_terbaru.json"), "w") as f:
        json.dump(results, f, default=float)


if __name__ == "__main__":
    main()
