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
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor

from config import (STATE_DIR, TV_BARS, H1_BARS, FETCH_THREADS, PROC_WORKERS, ONLY_SYMBOLS, FP, TFS,
                    SCAN_MIN_TURNOVER, MAX_MENIT, CEK_JAM, ALARM_KONF, RAPOR_OK)

os.makedirs(STATE_DIR, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(STATE_DIR, "numba_cache"))
warnings.filterwarnings("ignore")

import bybit_fetch as B
import qse_fixprofit as FX
import qse_perintah as QP
import qse_saya as SY
import qse_skill as SK
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
                h4 = pk["h4"]
                live = h4.iloc[-TV_BARS:] if len(h4) > len(df) and _ms(h4.index[-1]) + H4 > time.time() * 1000 else None
                out.append(qse_scan.process(sym, df, pk["h1c"], pk["d"], pk["w"], _BTC["h4c"], tick, "240",
                                            lim_h=FP["limit_hours"], btc_live=_BTC["h4"], df_live=live,
                                            h1_live=pk.get("h1")))
            else:
                df = pk["h1c"].iloc[-(TV_BARS - 1):]
                if len(df) < MIN_BARS:
                    continue
                out.append(qse_scan.process(sym, df, None, pk["d"], pk["w"], _BTC["h4"], tick, "60", pk["h4"],
                                            _BTC["h1c"], lim_h=FP["limit_hours"], btc_live=_BTC["h4"]))
        except Exception:
            err = traceback.format_exc(limit=3)
    return out, err


def _ms(ts):
    return int(ts.value // 1_000_000)


def _open_syms():
    try:
        return {v["sym"] for v in FX.load()["open"].values()}
    except Exception:
        return set()


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
    return dict(h4=h4, h4c=_split(h4, H4).iloc[-(TV_BARS - 1):], h1c=_split(h1, 3600000), h1=h1,
                d=B.get_klines(sym, "D", 1500, closed_only=False), w=B.get_klines(sym, "W", 400, closed_only=False))


STATE = os.path.join(STATE_DIR, "state.json")


def _st_load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def _st_update(upd):
    """Ubah sebagian state dengan kunci file, aman dipakai bersamaan dengan qse_listener.py."""
    import fcntl
    with open(STATE + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = _st_load()
        st.update(upd)
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f)
        os.replace(STATE + ".tmp", STATE)


def _listener_hidup():
    try:
        return time.time() - os.path.getmtime(os.path.join(STATE_DIR, "listener.alive")) < 180
    except OSError:
        return False


def perintah():
    """Cadangan bila qse_listener.py tidak aktif: proses perintah Telegram saat bot jalan."""
    if _listener_hidup():
        return
    st = _st_load()
    cmds, off = TG.ambil_perintah(st.get("tg_offset", 0))
    if off != st.get("tg_offset", 0):
        _st_update({"tg_offset": off})
    if cmds:
        print("Perintah diproses:", QP.proses(cmds, dari_main=True))


def trade_saya():
    """Pantau trade kamu (/entry). Aman walau listener juga jalan, tiap candle hanya diproses sekali."""
    try:
        pesan = SY.pantau()
    except Exception as ex:
        print("[WARN] pantau trade kamu:", ex)
        return
    if pesan:
        TG.send(["<b>QSE v148 | TRADE KAMU</b>\n" + "\n".join(pesan)])


def main():
    now = dt.datetime.now(dt.timezone.utc)
    semua = len(sys.argv) > 1 and sys.argv[1] == "semua"
    tutup4 = (int(time.time() * 1000) // H4) * H4          # jam tutup candle 4J terakhir
    st = _st_load()
    run4 = "240" in TFS and (semua or tutup4 > st.get("scan4", 0))
    tfs = [t for t in TFS if t == "60" or (t == "240" and run4)]
    try:
        perintah()
        if tfs:
            scan(now, run4, tfs)
            if run4:
                _st_update({"scan4": tutup4})
        else:
            pantau(now)
            if CEK_JAM and "240" in TFS:
                cek_cepat(now)
    except SystemExit:
        raise
    except Exception as ex:
        traceback.print_exc()
        TG.send([f"<b>QSE v148 | BOT GAGAL JALAN</b>\n{TG.e(type(ex).__name__)}: {TG.e(str(ex)[:300])}\n"
                 f"Cek log di tab Actions GitHub."])
        raise


def cek_cepat(now):
    """Tiap jam di tengah candle 4J: nilai ulang koin rapor A/B (dan koin yang punya order menunggu) memakai
    candle 4J yang sedang berjalan, persis seperti panel DASBOR. Kirim hanya sinyal baru, entry yang bergeser,
    pembatalan, dan alarm zona emas. Rapor dan pilihan pola tetap dari candle tutup, jadi kualitas tidak berubah."""
    t0 = time.time()
    path = os.path.join(STATE_DIR, "screening_terbaru.json")
    try:
        with open(path) as f:
            lama = json.load(f)
    except Exception:
        print("Belum ada hasil scan 4 jam, cek per jam dilewati.")
        return
    led = FX.load()
    FX.antrian_terapkan(led)
    target = {r["symbol"] for r in lama if r.get("tf", "240") == "240" and r["rapor"] in RAPOR_OK}
    target |= {v["sym"] for v in led["open"].values() if v["status"] == "MENUNGGU" and v.get("tf", "240") == "240"}
    if not target:
        return
    syms = B.get_symbols()
    tickers = B.get_tickers()
    target = [s for s in target if s in syms]
    b4 = B.get_klines("BTCUSDT", "240", TV_BARS, closed_only=False)
    b1 = B.get_klines("BTCUSDT", "60", TV_BARS, closed_only=True)
    _init(dict(h4=b4, h4c=_split(b4, H4).iloc[-(TV_BARS - 1):], h1c=b1))
    results, events = [], []
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as net:
        for s, f in [(s, net.submit(fetch, s, True)) for s in target]:
            try:
                pk = f.result()
            except Exception as ex:
                print(f"[ERROR] ambil {s}: {ex}")
                continue
            events += [(ev, dict(it)) for ev, it in FX.update(led, s, pk["h1c"])]
            out, err = _work(s, syms[s], pk, ["240"])
            if err:
                print(f"[ERROR] {s}\n{err}")
            results += out
    for r in results:
        r["tk"] = tickers.get(r["symbol"])
        lp = (tickers.get(r["symbol"]) or {}).get("last", 0)
        if lp > 0:
            r["live"] = lp
    res_map = {(r["symbol"], r["tf"]): r for r in results}
    events += [(ev, dict(it)) for ev, it in FX.recheck(led, res_map, ["240"])]
    sel, _ = FX.select(results, tickers, led)
    for r, x in sel:
        x["skor"] = _skor(r, x, None)
    sel.sort(key=lambda z: (z[1]["golden"], z[1]["skor"]), reverse=True)
    jalan = {(it["sym"], it.get("tf", "240")) for it in led["open"].values() if it["status"] in ("TERISI", "TP1")}
    sel = [(r, x) for r, x in sel if (r["symbol"], r["tf"]) not in jalan]
    events += [(ev, dict(it)) for ev, it in FX.ganti(led, sel)]
    tag_of = {id(x): (FX.register(led, r, x) or "sudah dikirim") for r, x in sel}
    baru = [(r, x) for r, x in sel if tag_of[id(x)] in ("BARU", "UPDATE")]
    # alarm zona emas untuk trading manual, sekali per koin per candle 4J
    st = _st_load()
    sudah = st.get("alarm_zona", {})
    tutup = int(time.time() * 1000) // H4 * H4
    alarm = []
    ada = {r["symbol"] for r, _ in sel}
    for r in results:
        p = r.get("pasar") or {}
        if r["symbol"] in ada or r["rapor"] not in ("A", "B") or not p.get("zona_searah") or not p.get("btc_ok"):
            continue
        n_k = SK.konfirmasi(r.get("skill"), p["arah"])[0]
        if n_k >= ALARM_KONF and sudah.get(r["symbol"]) != tutup:
            sudah[r["symbol"]] = tutup
            lo, hi = p["gp"] if p.get("in_gp") else p["gz"]
            alarm.append(f"➡️ <b>{TG.e(r['symbol'])} {p['arah']}</b> | rapor {r['rapor']} | harga masuk "
                         f"{'golden pocket' if p.get('in_gp') else 'golden zone'} {TG.fp(min(lo, hi), r['tick'])}-"
                         f"{TG.fp(max(lo, hi), r['tick'])} | konf {n_k}/8 | batal {TG.fp(p['batal'], r['tick'])} | "
                         f"{TG.e(_status_dasbor(r))}")
    _st_update({"alarm_zona": {k: v for k, v in sudah.items() if v >= tutup - H4}})
    FX.antrian_terapkan(led)
    FX.save(led)
    # perbarui hasil scan untuk /cek tanpa menghapus koin lain
    peta = {(r["symbol"], r["tf"]): r for r in results}
    lama = [peta.pop((r["symbol"], r.get("tf", "240")), r) for r in lama] + list(peta.values())
    with open(path, "w") as f:
        json.dump(lama, f, default=float)
    if not (baru or events or alarm):
        print(f"Cek per jam {len(results)} koin, tidak ada perubahan. {time.time() - t0:.0f}s")
        return
    jam = now.astimezone(WIB).strftime("%d/%m %H:%M WIB")
    blocks = [f"<b>QSE v148 | CEK PER JAM TF 4J</b> | {jam}\n"
              f"Candle 4J berjalan dinilai ulang untuk {len(results)} koin rapor A/B"]
    if baru:
        blocks.append(f"<b>SINYAL BARU DI TENGAH CANDLE ({len(baru)})</b>")
        for i, (r, x) in enumerate(baru, 1):
            st_ = f"{x['mutu']} EKSEKUSI, " + ("SINYAL BARU" if tag_of[id(x)] == "BARU" else "ENTRY DIPERBARUI")
            if x.get("tersentuh"):
                st_ += ", entry pernah tersentuh"
            blocks.append(_blok(i, r, x, st_, led))
    if events:
        blocks.append("<b>UPDATE ORDER</b>\n" + "\n".join("➡️ " + TG.hasil(ev, it, syms) for ev, it in events))
    if alarm:
        blocks.append("<b>ALARM ZONA EMAS UNTUK ENTRY MANUAL</b>\n"
                      "Harga baru masuk zona emas di koin rapor A/B dengan konfirmasi skill tinggi. "
                      "Cek chart dan tunggu candle konfirmasi searah.\n" + "\n".join(alarm))
    TG.send(blocks)
    for b in blocks:
        print(b, "\n")
    print(f"Cek per jam selesai {time.time() - t0:.0f}s")


def pantau(now):
    """Run tiap jam di antara candle 4J: hanya cek order terbuka (terisi, TP1, TP2, SL, batal waktu)."""
    trade_saya()
    led = FX.load()
    FX.antrian_terapkan(led)
    syms = sorted({v["sym"] for v in led["open"].values()})
    if not syms:
        print("Tidak ada order terbuka, selesai.")
        return
    ticks = B.get_symbols()
    events = []
    for s in syms:
        try:
            events += [(ev, dict(it)) for ev, it in FX.update(led, s, B.get_klines(s, "60", 300))]
        except Exception as ex:
            print(f"[ERROR] pantau {s}: {ex}")
    FX.antrian_terapkan(led)
    FX.save(led)
    if not events:
        print(f"Pantau {len(syms)} order, tidak ada perubahan.")
        return
    jam = now.astimezone(WIB).strftime("%d/%m %H:%M WIB")
    blocks = [f"<b>QSE v148 | PANTAU ORDER</b> | {jam}\n" + "\n".join("➡️ " + TG.hasil(ev, it, ticks) for ev, it in events),
              _ringkas_open(led)]
    TG.send(blocks)
    for b in blocks:
        print(b, "\n")


def _ringkas_open(led):
    return TG.ringkas_open(led)


def scan(now, run4, tfs):
    t0 = time.time()
    import qse_engine
    if not qse_engine.NUMBA_OK:
        print("[PERINGATAN] numba tidak terpasang, engine jalan sekitar 50x lebih lambat. "
              "Jalankan: $HOME/qse_state/venv/bin/pip install numba")
    syms = B.get_symbols()
    tickers = B.get_tickers()
    if ONLY_SYMBOLS:
        syms = {s: syms[s] for s in ONLY_SYMBOLS if s in syms}
    elif SCAN_MIN_TURNOVER > 0 and tickers:
        syms = {s: t for s, t in syms.items()
                if tickers.get(s, {}).get("turnover", 0) >= SCAN_MIN_TURNOVER or s in _open_syms()}
    order = sorted(syms, key=lambda s: -tickers.get(s, {}).get("turnover", 0))
    print(f"Simbol dihitung {len(order)} | TF {tfs}")
    b4 = B.get_klines("BTCUSDT", "240", TV_BARS, closed_only=False)
    b1 = B.get_klines("BTCUSDT", "60", TV_BARS, closed_only=True)
    btc = dict(h4=b4, h4c=_split(b4, H4).iloc[-(TV_BARS - 1):], h1c=b1)
    _init(btc)
    led = FX.load()
    FX.antrian_terapkan(led)
    results, events, fail, basi = [], [], 0, 0
    exp4 = (int(time.time() * 1000) // H4) * H4 - H4
    workers = PROC_WORKERS or os.cpu_count() or 1
    pool = ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(btc,)) if workers > 1 else None
    batas = t0 + MAX_MENIT * 60
    CH = 24
    chunks = [order[i:i + CH] for i in range(0, len(order), CH)]
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as net:
        nxt = [(s, net.submit(fetch, s, run4)) for s in chunks[0]] if chunks else []
        for ci in range(len(chunks)):
            cur = nxt
            nxt = [(s, net.submit(fetch, s, run4)) for s in chunks[ci + 1]] \
                if ci + 1 < len(chunks) and time.time() < batas else []
            jobs = []
            for s, f in cur:
                try:
                    pk = f.result()
                except Exception as ex:
                    fail += 1
                    print(f"[ERROR] ambil {s}: {ex}")
                    if "403" in str(ex):
                        sys.exit(1)
                    continue
                events += [(ev, dict(it)) for ev, it in FX.update(led, s, pk["h1c"])]
                if "240" in tfs and (len(pk["h4c"]) == 0 or _ms(pk["h4c"].index[-1]) < exp4):
                    basi += 1          # koin berhenti trading atau data belum lengkap
                    continue
                jobs.append((s, pool.submit(_work, s, syms[s], pk, tfs) if pool else _work(s, syms[s], pk, tfs)))
            for s, j in jobs:
                out, err = j.result() if pool else j
                if err:
                    fail += 1
                    print(f"[ERROR] {s}\n{err}")
                results += out
            print(f"  {min((ci + 1) * CH, len(order))}/{len(order)} koin | {time.time() - t0:.0f}s")
            if not nxt:
                if ci + 1 < len(chunks):
                    print(f"[INFO] batas {MAX_MENIT:g} menit tercapai, sisa koin dilewati run ini.")
                break
    if pool:
        pool.shutdown()

    try:
        live = B.get_tickers()
    except Exception:
        live = tickers
    for r in results:
        lp = live.get(r["symbol"], {}).get("last", 0)
        if lp > 0:
            r["live"] = lp
    tickers = live or tickers
    if basi:
        print(f"[INFO] {basi} koin dilewati karena candle terakhir tidak lengkap")
    res_map = {(r["symbol"], r["tf"]): r for r in results}
    trade_saya()
    try:
        waspada = SY.cek_4j(res_map)
    except Exception as ex:
        print("[WARN] cek trade kamu:", ex)
        waspada = []
    waspada += FX.peringatan(led, res_map)
    if waspada:
        TG.send(["<b>QSE v148 | PERINGATAN POSISI</b>\n" + "\n".join(waspada)])
    events += [(ev, dict(it)) for ev, it in FX.recheck(led, res_map, tfs)]
    for r in results:
        r["tk"] = tickers.get(r["symbol"])
    rb = ramal_btc(btc["h4c"]) if "240" in tfs else None
    sel, drop = FX.select(results, tickers, led)
    for r, x in sel:
        x["skor"] = _skor(r, x, rb)
    sel.sort(key=lambda z: (z[1]["golden"], z[1]["skor"]), reverse=True)
    jalan = {(it["sym"], it.get("tf", "240")) for it in led["open"].values() if it["status"] in ("TERISI", "TP1")}
    sel = [(r, x) for r, x in sel if (r["symbol"], r["tf"]) not in jalan]     # posisi jalan, cegah entry ganda
    events += [(ev, dict(it)) for ev, it in FX.ganti(led, sel)]
    tag_of = {id(s): (FX.register(led, r, s) or "sudah dikirim") for r, s in sel}
    for tf in tfs:
        blocks = _pesan_tf(tf, results, sel, tag_of, led, events, syms, now, tfs, rb)
        if fail > max(5, 0.05 * len(order)):
            blocks[0] += f"\nData tidak lengkap: {fail} koin gagal diambil atau dihitung"
        TG.send(blocks)
        for b in blocks:
            print(b, "\n")
    FX.antrian_terapkan(led)
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


def _uang(x):
    return f"{x / 1e6:,.1f} jt" if x >= 1e6 else f"{x / 1e3:,.0f} rb"


def _skor(r, s, rb):
    """Skor prioritas 0-100 dari statistik nyata: WR pola (Wilson), rapor robot, mutu, peluang terisi,
    ramalan BTC 4 jam, dan ramalan arah koin. Dipakai untuk urutan dan ringkasan."""
    n = s["win"] + s["loss"]
    p = s["win"] / n if n else 0.0
    wil = ((p + 1.9208 / n - 1.96 * ((p * (1 - p) + 0.9604 / n) / n) ** 0.5) / (1 + 3.8416 / n)) if n else 0.0
    sk = max(0.0, wil) * 35
    sk += 15 if r["rapor"] == "A" else 9
    sk += 12 if s["mutu"] == "A" else 6
    sk += 10 * min(100.0, s["p_isi"]) / 100
    if rb:
        up = rb["p_up"] if s["arah"] == "LONG" else 100 - rb["p_up"]
        sk += 10 if up >= 55 else 5 if up > 45 else 0
    sk += max(0.0, min(10.0, (s.get("p_arah", 50) - 50) * 0.5))
    sk += 8 if s["golden"] else 0
    return int(round(min(100.0, sk)))


def ramal_btc(btc):
    """Ramalan BTC 4 jam: peluang candle 4J berikutnya naik pada kondisi tren dan momentum yang sama."""
    import qse_ta as T
    import numpy as np
    c = btc["close"].values.astype(float)
    h, l = btc["high"].values.astype(float), btc["low"].values.astype(float)
    if len(c) < 300:
        return None
    e20, e50 = T.ema(c, 20), T.ema(c, 50)
    st = np.where((c > e20) & (e20 > e50), 1, np.where((c < e20) & (e20 < e50), -1, 0))
    mom = np.r_[False, c[1:] > c[:-1]]
    L = len(c) - 1
    up = c[1:] > c[:-1]
    lo = max(0, L - 3000)
    sel = (st[lo:L] == st[L]) & (mom[lo:L] == mom[L])
    if sel.sum() < 60:
        sel = st[lo:L] == st[L]
    p = float(up[lo:L][sel].mean() * 100) if sel.sum() else 50.0
    a = float(T.atr(h, l, c, 14)[L])
    return dict(p_up=p, n=int(sel.sum()), atr=a, atr_pct=a / c[L] * 100)


def _blok_ramal(rb):
    if not rb:
        return ""
    p = rb["p_up"]
    arah = "condong naik, LONG lebih aman" if p >= 55 else "condong turun, SHORT lebih aman" if p <= 45 \
        else "seimbang, tidak ada arah kuat"
    atr = f"{rb['atr']:,.0f}" if rb["atr"] >= 100 else f"{rb['atr']:.4g}"
    return (f"<b>RAMALAN BTC 4 JAM KE DEPAN</b>\n"
            f"Candle berikutnya naik {p:.0f}% (dari {rb['n']} kondisi mirip)\n"
            f"Gerak khas 4 jam: plus minus {atr} USDT ({rb['atr_pct']:.1f}%)\n"
            f"Kesimpulan: {arah}")


def _blok(no, r, s, status, led=None):
    t = r["tick"]
    g = "GOLDEN MOMENT | " if s["golden"] else ""
    z = " | zona emas" if s["zona_emas"] else ""
    jam_c = r["tf_ms"] / 3600000
    rows = [f"➡️ <b>{no}. {TG.e(r['symbol'])} {s['arah']}</b> | skor {s.get('skor', 0)}/100",
            f"Rapor robot {r['rapor']} ({r['trd']} trade, WR {r['wr']:.0f}%, PF {r['pf']:.2f})",
            f"Pola: {TG.e(s['pola'])} | mutu {s['mutu']}{z}",
            f"Pola ini: {s['win']} TP / {s['loss']} SL | WR {s['wr']:.0f}% | {s['net_r']:+.1f}R",
            f"Status: {g}{TG.e(status)}",
            _tabel(s, t),
            "<b>Ramalan</b>",
            f"Candle 4 jam berikutnya searah {s.get('p_arah', 50):.0f}% (dari {s.get('n_arah', 0)} kondisi mirip)",
            f"Gerak khas 4 jam: plus minus {TG.fp(r['atr'] * (4 / jam_c) ** 0.5, t)} "
            f"({r['atr'] * (4 / jam_c) ** 0.5 / r['close'] * 100:.1f}%)"]
    if s["order"] != "MARKET":
        rows.append(f"Peluang terisi: 4 jam {s.get('p_isi4', 0):.0f}% | 24 jam {s['p_isi']:.0f}%")
    if s.get("dur", 0) > 0:
        rows.append(f"Estimasi sampai hasil: sekitar {s['dur']:.0f} candle ({s['dur'] * jam_c:.0f} jam)")
    if r.get("skill"):
        rows.append(SK.ringkas(r["skill"], s["arah"], lambda x: TG.fp(x, t)))
    tk = r.get("tk")
    if tk:
        rows.append(f"Pasar: volume 24j {_uang(tk['turnover'])} USDT | funding {tk['funding'] * 100:+.4f}% | "
                    f"spread {tk['spread']:.2f}%")
    key = "%s|%s|%s|%s" % (r["symbol"], r["tf"], s["pola"], s["arah"])
    it = (led or {}).get("open", {}).get(key)
    if s["order"] == "MARKET":
        rows.append("Cara: eksekusi MARKET sekarang, pasang SL dan TP1 langsung.")
    else:
        batas = _jam(it["exp_ts"]) if it and it.get("exp_ts") else "24 jam"
        rows.append(f"Cara: pasang LIMIT di entry. Batal otomatis {batas}.")
    rows.append("Di TP1 tutup separuh, geser SL ke entry, sisanya ke TP2.")
    slp = abs(s["entry"] - s["sl"]) / s["entry"] if s["entry"] > 0 else 1
    lev = max(1, min(FP["lev_cap"], int(1 / (slp * 1.3 + 0.006))))
    rows.append(f"Leverage maks {lev}x isolated. SL {slp * 100:.1f}% dari entry, likuidasi tetap di luar SL.")
    if FP["risk_usdt"] > 0:
        qty = FP["risk_usdt"] / max(abs(s["entry"] - s["sl"]), t)
        rows.append(f"Lot risiko {FP['risk_usdt']:g} USDT: {qty:.4g} koin | nilai {qty * s['entry']:,.0f} USDT")
    rows.append(f'<a href="https://www.tradingview.com/chart/?symbol=BYBIT:{r["symbol"]}.P">Chart {TG.e(r["symbol"])}.P</a>')
    return "\n".join(rows)


def _rekap(led, now, hari=1, judul="REKAP KEMARIN", why_ok=("SL", "BE", "TP2")):
    b = int(dt.datetime(now.year, now.month, now.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    a = b - hari * 86400000
    cl = [c for c in led["closed"] if c.get("why") in why_ok and a <= c.get("closed_ts", 0) < b]
    if not cl:
        return f"<b>{judul}</b>\nTidak ada trade yang selesai."
    net = sum(c["result_r"] for c in cl)
    win = sum(1 for c in cl if c["result_r"] > 0)
    rows = [f"<b>{judul}</b> | {len(cl)} trade | WR {win / len(cl) * 100:.0f}% | {net:+.2f}R"]
    if hari == 1:
        rows += [f"➡️ {TG.e(c['sym'])} {c['arah']} | {TG.e(c.get('pola', c.get('order', 'manual')))} | {c['why']} {c['result_r']:+.2f}R" for c in cl]
    else:
        per = {}
        for c in cl:
            k = c.get("pola", "manual")
            per.setdefault(k, [0, 0.0])
            per[k][0] += 1
            per[k][1] += c["result_r"]
        urut = sorted(per.items(), key=lambda z: -z[1][1])
        rows.append("Pola terbaik: " + ", ".join(f"{TG.e(k)} {v[1]:+.1f}R ({v[0]})" for k, v in urut[:3]))
        rows.append("Pola terburuk: " + ", ".join(f"{TG.e(k)} {v[1]:+.1f}R ({v[0]})" for k, v in urut[-3:][::-1]))
    return "\n".join(rows)


def _status_dasbor(r):
    """Status saran koin ini di panel DASBOR."""
    xs = [x for x in r["saran"] if not x["sudah_masuk"]]
    if not xs:
        return "posisi robot aktif" if r["saran"] else "tanpa saran"
    x = next((y for y in xs if y["eksekusi"]), xs[0])
    if x["eksekusi"]:
        why = x.get("saring") or x.get("buang") or ("mutu " + x["mutu"])
        return f"saran {x['pola']} EKSEKUSI, ditahan: {why}"
    return f"saran {x['pola']} TAHAN: {x['alasan']}"


def _aplus(r):
    return r["rapor"] == "A" and r["trd"] >= 20 and r["wr"] >= 65 and r["pf"] >= 1.8


def _pantauan(rs, sig, kode):
    """Bagian 3: pasar rapor A/B tanpa saran, untuk analisa manual. Hanya koin likuid."""
    ada = {r["symbol"] for r, _ in sig}
    pool = [r for r in rs if r["rapor"] in ("A", "B") and r["symbol"] not in ada and r.get("pasar")
            and (not r.get("tk") or r["tk"]["turnover"] >= FP["min_turnover"])]
    pool.sort(key=lambda r: (r["rapor"] != "A", -SK.konfirmasi(r.get("skill"), r["pasar"]["arah"])[0], -r["wr"], -r["pf"]))

    def baris(r, zona=False):
        p, t = r["pasar"], r["tick"]
        z = ""
        if zona or p["zona_searah"]:
            lo, hi = p["gp"] if p["in_gp"] else p["gz"]
            z = f" | {'GP' if p['in_gp'] else 'GZ'} {TG.fp(min(lo, hi), t)}-{TG.fp(max(lo, hi), t)}"
        return (f"➡️ {TG.e(r['symbol'])} {p['arah']} | rapor {r['rapor']} {r['trd']}trd WR{r['wr']:.0f}% PF{r['pf']:.2f}"
                f"{z} | batal {TG.fp(p['batal'], t)} | ADX {p['adx']:.0f} | konf {SK.konfirmasi(r.get('skill'), p['arah'])[0]}/8"
                f" | {TG.e(_status_dasbor(r))}")

    zona = [r for r in pool if r["pasar"]["zona_searah"] and r["pasar"]["btc_ok"]]
    momen = [r for r in pool if r["rapor"] == "A" and r["pasar"]["btc_selaras"] and r["pasar"]["bentuk"]]
    aplus = [r for r in pool if _aplus(r)]
    lengkap = [r for r in aplus if r in zona and r in momen]
    grup = [("LENGKAP: A+, zona emas, momen emas", lengkap, True),
            ("MOMEN EMAS: rapor A, BTC selaras, bentuk pasar searah", momen, False),
            ("ZONA EMAS: harga di golden pocket atau golden zone searah bias", zona, True),
            ("A+: rapor A, min 20 trade, WR 65, PF 1.8", aplus, False)]
    nL = sum(1 for r in pool if r["pasar"]["arah"] == "LONG")
    nOk = sum(1 for r in pool if r["pasar"]["btc_ok"])
    nZ = sum(1 for r in pool if r["pasar"]["zona_searah"])
    out = [f"<b>3. PANTAUAN MANUAL TF {kode} (di luar sinyal valid)</b>\n"
           "Pasar rapor A/B yang tidak ada di bagian 1. Ujung tiap baris = status saran di DASBOR. "
           "Entry manual hanya bila harga masuk zona dan candle konfirmasi searah.\n"
           f"Bias koin: LONG {nL}, SHORT {len(pool) - nL} | diizinkan BTC {nOk} | di zona emas {nZ}"]
    for judul, xs, zn in grup:
        if xs:
            out.append(f"<b>{judul} ({len(xs)})</b>\n" + "\n".join(baris(r, zn) for r in xs[:12]))
    if not any(xs for _, xs, _ in grup):
        out.append("Kategori LENGKAP, MOMEN EMAS, ZONA EMAS, dan A+ kosong di candle ini. "
                   "Biasanya karena arah bias koin ditahan BTC atau harga belum masuk zona.")
    rA = [r["symbol"] for r in pool if r["rapor"] == "A"]
    rB = [r["symbol"] for r in pool if r["rapor"] == "B"]
    if rA or rB:
        out.append("<b>Semua rapor A/B di luar sinyal valid</b>\n" + (f"A: {', '.join(rA)}\n" if rA else "") + (f"B: {', '.join(rB)}" if rB else ""))
    if len(out) == 1:
        out.append("Belum ada pasar rapor A/B yang likuid di candle ini.")
    return ["\n\n".join(out[:2])] + out[2:] if len(out) > 1 else out


def _pesan_tf(tf, results, sel, tag_of, led, events, syms, now, tfs=("240", "60"), rb=None):
    judul, kode = NAMA[tf]
    rs = [r for r in results if r["tf"] == tf]
    sig = [(r, s) for r, s in sel if r["tf"] == tf]
    ev = [(e, it) for e, it in events if it.get("tf", "240") == tf
          or (tf == tfs[-1] and it.get("tf", "240") not in tfs)]    # order TF lain yang berubah di run ini
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
        head.append(f"{TG.e(bt['btc'])} | peluang naik 24 jam {bt['bProb']:.0f}%")
        alt = next((r for r in rs if "BTC" not in r["symbol"]), bt)
        head.append(f"Arah yang diizinkan BTC: {alt.get('izin', '-')}")
    head.append(f"Dipindai {len(rs)} koin | rapor A {len(rA)} | rapor B {len(rB)}")
    head.append(f"Sinyal valid {len(sig)} | baru {baru} | masih valid {len(sig) - baru}")
    st_open = {}
    for it in led["open"].values():
        st_open[it["status"]] = st_open.get(it["status"], 0) + 1
    if st_open:
        nm = {"MENUNGGU": "menunggu terisi", "TERISI": "posisi jalan", "TP1": "sudah TP1"}
        head.append("Order terbuka: " + ", ".join(f"{v} {nm.get(k, k)}" for k, v in st_open.items()))
    alasan = {}
    for r in rs:
        if r["rapor"] in ("A", "B"):
            for x in r["saran"]:
                if x["mutu"] in ("A", "B") and not x["eksekusi"]:
                    alasan[x["alasan"]] = alasan.get(x["alasan"], 0) + 1
    if alasan and not sig:
        top = sorted(alasan.items(), key=lambda z: -z[1])[:3]
        head.append("Penahan utama: " + ", ".join(f"{TG.e(k)} {v}" for k, v in top))
    out = ["\n".join(head)]
    if rb and tf == "240":
        out.append(_blok_ramal(rb))
    tutup_dt = dt.datetime.fromtimestamp(tutup / 1000, dt.timezone.utc) if tutup else now
    if tf == "240" and tutup_dt.hour == 0:
        out.append(_rekap(led, tutup_dt))
        out.append(_rekap(SY.lihat(), tutup_dt, 1, "REKAP TRADE KAMU KEMARIN", ("SL", "BE", "TP2", "TUTUP")))
        if tutup_dt.weekday() == 0:
            out.append(_rekap(led, tutup_dt, 7, "REKAP 7 HARI"))
    if sig:
        out.append("<b>RINGKASAN SINYAL</b>\n" + "\n".join(
            f"{i}. {TG.e(r['symbol'])} {s['arah']} | {s['order']} | mutu {s['mutu']} | skor {s.get('skor', 0)}"
            + (" | GOLDEN" if s["golden"] else "") for i, (r, s) in enumerate(sig, 1)))
    out.append(f"<b>1. SINYAL VALID TF {kode} ({len(sig)})</b>" +
               ("" if sig else "\nBelum ada sinyal yang lolos semua syarat di candle ini."))
    for i, (r, s) in enumerate(sig, 1):
        tg = tag_of[id(s)]
        st = f"{s['mutu']} EKSEKUSI, " + ("SINYAL BARU" if tg in ("BARU", "UPDATE") else "masih valid")
        if s.get("tersentuh"):
            st += ", entry pernah tersentuh"
        out.append(_blok(i, r, s, st, led))
    out.append(f"<b>2. UPDATE ORDER ({len(ev)})</b>\n" +
               ("\n".join("➡️ " + TG.hasil(e, it, syms) for e, it in ev) if ev else "Tidak ada perubahan order."))
    out += _pantauan(rs, sig, kode)
    if tahan or buang:
        rows = [f"<b>4. HAMPIR, BELUM VALID ({len(tahan) + len(buang)})</b>"]
        rows += [f"➡️ {TG.e(r['symbol'])} {s['arah']} | {TG.e(s['pola'])} | {TG.e(s['saring'])}" for r, s in tahan[:10]]
        rows += [f"➡️ {TG.e(r['symbol'])} {s['arah']} | {TG.e(s['pola'])} | {TG.e(s['buang'])}" for r, s in buang[:15]]
        out.append("\n".join(rows))
    sig_cl = [c for c in led["closed"] if c.get("why") in ("SL", "BE", "TP2")]
    out.append("WR sinyal robot: " + SY.ringkas(sig_cl, ("SL", "BE", "TP2")) +
               "\nWR trade kamu: " + SY.ringkas(SY.lihat()["closed"]))
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
