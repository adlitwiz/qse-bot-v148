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

from config import P, BYBIT_URL
from config import (STATE_DIR, TV_BARS, H1_BARS, FETCH_THREADS, PROC_WORKERS, ONLY_SYMBOLS, FP, TFS,
                    SCAN_MIN_TURNOVER, MAX_MENIT, CEK_JAM, ALARM_KONF, RAPOR_OK, CEK_1J)

os.makedirs(STATE_DIR, exist_ok=True)
os.environ.setdefault("NUMBA_CACHE_DIR", os.path.join(STATE_DIR, "numba_cache"))
warnings.filterwarnings("ignore")

import bybit_fetch as B
import qse_fixprofit as FX
import qse_perintah as QP
import qse_saya as SY
import qse_skill as SK
import qse_berita as BR
import qse_siklus as SIK
import qse_alarm as AL
import qse_uji as QU
import qse_modal as MD
import qse_pola as PL
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
        TG.send(["👤 <b>QSE v148 | TRADE KAMU</b>\n\n" + "\n".join(pesan)])


def scan_sekarang():
    """Dipanggil /scan lewat listener: nilai ulang koin rapor A/B di 4J dan 1J dengan harga terkini, kirim hasilnya."""
    import fcntl
    now = dt.datetime.now(dt.timezone.utc)
    lk = open(os.path.join(STATE_DIR, ".lock"), "a")
    try:
        fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        TG.send(["🔎 <b>QSE v148 | SCAN SEKARANG</b>\nScan terjadwal sedang berjalan. Hasilnya ikut terkirim sebentar lagi."])
        return
    try:
        cek_cepat(now, paksa=True)
        if CEK_1J:
            cek_1j(now, paksa=True)
    except Exception:
        TG.send(["🔎 <b>QSE v148 | SCAN SEKARANG</b>\nScan gagal: " + TG.e(traceback.format_exc()[-300:])])
    finally:
        fcntl.flock(lk, fcntl.LOCK_UN)


def main():
    now = dt.datetime.now(dt.timezone.utc)
    if len(sys.argv) > 1 and sys.argv[1] == "--scan":
        scan_sekarang()
        return
    import fcntl
    _kunci = open(os.path.join(STATE_DIR, ".main.lock"), "a")
    try:
        fcntl.flock(_kunci, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("main.py lain sedang jalan, run ini dilewati.")
        return
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
                if CEK_1J:
                    cek_1j(now)
        else:
            jam_ini = int(time.time() // 3600)
            if _st_load().get("jam_cek") == jam_ini and not semua:
                print("Cek per jam untuk jam ini sudah jalan.")
                return
            _st_update({"jam_cek": jam_ini})
            pantau(now)
            if CEK_JAM and "240" in TFS:
                cek_cepat(now)
            if CEK_1J:
                cek_1j(now)
            uji_mingguan()
    except SystemExit:
        raise
    except Exception as ex:
        traceback.print_exc()
        TG.send([f"<b>QSE v148 | BOT GAGAL JALAN</b>\n{TG.e(type(ex).__name__)}: {TG.e(str(ex)[:300])}\n"
                 f"Cek log di tab Actions GitHub."])
        raise


def _evaluasi_saran(led, now):
    """Hasil semua saran robot kemarin dan 7 hari (simulasi dari level saran, bukan trade kamu)."""
    b = int(dt.datetime(now.year, now.month, now.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    rows = ["📊 <b>EVALUASI SARAN ROBOT</b> (simulasi level saran, bukan trade kamu)"]
    for nama, a in (("Kemarin", b - 86400000), ("7 hari", b - 7 * 86400000)):
        cl = [c for c in led["closed"] if c.get("why") in ("SL", "BE", "TP2") and a <= c.get("closed_ts", 0) < b]
        if not cl:
            rows.append(f"{nama}: belum ada saran yang selesai")
            continue
        g = {}
        for c in cl:
            j = ("cadangan" if c.get("cadangan") else "siklus" if c.get("siklus") else "fib" if c.get("fib")
                 else "cadangan 2" if c.get("cad2") else "1J" if c.get("tf") == "60" else "utama")
            g.setdefault(f"{c['pola']} ({j})", []).append(c["result_r"])

        def st(x):
            w = [v for v in x if v > 0]
            rugi = -sum(v for v in x if v < 0)
            return len(x), len(w) / len(x) * 100, (sum(w) / rugi if rugi > 0 else 9.9), sum(x)
        semua = [v for x in g.values() for v in x]
        n, wr, pf, net = st(semua)
        rows.append(f"{nama}: {n} saran | WR {wr:.0f}% | PF {pf:.2f} | rata {net / n:+.2f}R | total {net:+.2f}R")
        if len(g) > 1:
            urut = sorted(((k, st(v)) for k, v in g.items()), key=lambda z: -z[1][3])
            k, s_ = urut[0]
            rows.append(f"↳ profit terbanyak: {TG.e(k)} {s_[3]:+.2f}R ({s_[0]} saran, PF {s_[2]:.2f})")
            akur = max(((k, st(v)) for k, v in g.items() if len(v) >= 2), key=lambda z: (z[1][1], z[1][2]), default=None)
            if akur:
                rows.append(f"↳ paling akurat: {TG.e(akur[0])} WR {akur[1][1]:.0f}% PF {akur[1][2]:.2f} ({akur[1][0]} saran)")
    return "\n".join(rows)


def _pin(ids):
    """Sematkan pesan sinyal. Bila gagal (bot belum admin), kabari sekali sehari dengan cara memperbaikinya."""
    if not ids:
        return
    st = _st_load()
    if st.get("pin_id"):
        TG.unpin(st["pin_id"])
    err = TG.pin(ids[0])
    if err:
        if time.time() - st.get("pin_warn", 0) > 86400:
            TG.send([f"⚠️ <b>QSE v148 | PIN GAGAL</b>\nTelegram: {TG.e(str(err))}\nJadikan bot admin grup dengan izin "
                     f"<b>Sematkan pesan</b> (Pin messages), lalu sinyal berikutnya otomatis disematkan."])
            _st_update({"pin_warn": time.time()})
        return
    _st_update({"pin_id": ids[0]})


def _konteks_berita(b1):
    """Kalender, delisting, dan guncangan BTC. Guncangan menahan sinyal baru 3 jam."""
    now_ms = int(time.time() * 1000)
    st = _st_load()
    g = BR.guncang(b1) if b1 is not None and len(b1) else None
    tahan = st.get("guncang_sampai", 0)
    kirim = None
    if g:
        if now_ms > tahan:
            kirim = g
        tahan = max(tahan, now_ms + 3 * 3600000)
        _st_update({"guncang_sampai": tahan})
    return dict(jeda=BR.jeda(now_ms), hari=BR.hari_ini(now_ms), delist=BR.delisting(),
                tahan=tahan if now_ms < tahan else 0, guncang=g, kirim_guncang=kirim)


def _saring_berita(sel, ctx):
    out = []
    for r, x in sel:
        why = ""
        if r["symbol"] in ctx["delist"]:
            why = "pengumuman delisting Bybit"
        elif ctx["tahan"]:
            why = "pasar bergejolak, sinyal baru ditahan sampai " + BR.jam_wib(ctx["tahan"])
        elif ctx["jeda"]:
            why = f"jeda berita {ctx['jeda']['judul']} {BR.jam_wib(ctx['jeda']['ts'])}"
        if why:
            x["buang"] = why
            continue
        out.append((r, x))
    return out


def _berita_baris(ctx):
    rows = []
    if ctx["hari"]:
        rows.append("Berita hari ini: " + ", ".join(f"{TG.e(e['judul'])} {BR.jam_wib(e['ts'])[6:]}"
                                                    for e in ctx["hari"][:5]))
    if ctx["jeda"]:
        rows.append(f"⚠️ JEDA BERITA {TG.e(ctx['jeda']['judul'])}: sinyal baru ditahan")
    if ctx["tahan"]:
        rows.append("⚠️ PASAR BERGEJOLAK: sinyal baru ditahan sampai " + BR.jam_wib(ctx["tahan"]))
    return rows


def _cad_status(led):
    """Hasil saran cadangan. Mati otomatis bila setelah 30 trade WR di bawah 50% atau PF di bawah 1.2."""
    cl = [c for c in led["closed"] if c.get("cadangan") and c.get("why") in ("SL", "BE", "TP2")]
    n = len(cl)
    menang = sum(c["result_r"] for c in cl if c["result_r"] > 0)
    kalah = -sum(c["result_r"] for c in cl if c["result_r"] < 0)
    wr = sum(1 for c in cl if c["result_r"] > 0) / n * 100 if n else 0
    pf = menang / kalah if kalah > 0 else (9.9 if menang > 0 else 0)
    mati = n >= 30 and (wr < 50 or pf < 1.2)
    return dict(n=n, wr=wr, pf=pf, mati=mati, cl=cl)


def _cadangan(results, sel, led, tickers, ctx, rb, maks=3, konf_min=6):
    """Saran cadangan dari koin rapor A/B di zona emas searah bias, izin BTC, konfirmasi skill tinggi."""
    if _cad_status(led)["mati"] or ctx["tahan"] or ctx["jeda"] or not QU.aktif("cadangan"):
        return []
    st = _st_load()
    tutup = str(int(time.time() * 1000) // H4 * H4)
    sisa = maks - st.get("cad_n", {}).get(tutup, 0)
    if sisa <= 0:
        return []
    ada = {r["symbol"] for r, _ in sel} | _posisi_kamu()
    ada |= {v["sym"] for v in led["open"].values() if v.get("cadangan") and v["status"] == "MENUNGGU"}
    cand = []
    for r in results:
        p, sk = r.get("pasar") or {}, r.get("skill")
        if (r["tf"] != "240" or r["rapor"] not in ("A", "B") or r["symbol"] in ada or r["symbol"] in ctx["delist"]
                or not p.get("zona_searah") or not p.get("btc_ok") or not sk):
            continue
        arah = p["arah"]
        n_k, _, ok = SK.konfirmasi(sk, arah)
        if n_k < konf_min:
            continue
        tk = tickers.get(r["symbol"]) or {}
        if tk and (tk.get("turnover", 0) < FP["min_turnover"] or tk.get("spread", 0) > FP["max_spread_pct"]):
            continue
        if FX._muted(led, r["symbol"], "Cadangan zona emas", arah):
            continue
        L = arah == "LONG"
        c, a = r.get("live") or r["close"], r["atr"]
        lo, hi = sorted(p["gp"] if p.get("in_gp") else p["gz"])
        mid = (lo + hi) / 2
        if L:
            if c < lo - 0.5 * a or c > hi + 0.25 * a:
                continue
            order, e = ("MARKET", c) if c <= mid else ("LIMIT", mid)
        else:
            if c > hi + 0.5 * a or c < lo - 0.25 * a:
                continue
            order, e = ("MARKET", c) if c >= mid else ("LIMIT", mid)
        base = p["batal"] - a * P["slBuf"] if L else p["batal"] + a * P["slBuf"]
        dist = (e - base) if L else (base - e)
        if not dist > 0:
            dist = a * 1.5
        dist = min(max(dist, a * P["slMinA"]), a * P["slMaxA"])
        sl = e - dist if L else e + dist
        tp1 = e + 0.8 * dist if L else e - 0.8 * dist
        lv = sk.get("res" if L else "sup") or []
        tp2 = next((x for x in lv if (x - e if L else e - x) >= 1.2 * dist and (x - e if L else e - x) <= 3 * dist),
                   e + 1.8 * dist if L else e - 1.8 * dist)
        tab = next((x.get("p_tab") for x in r["saran"] if x["arah"] == arah and x.get("p_tab")), None)
        tab4 = next((x.get("p_tab4") for x in r["saran"] if x["arah"] == arah and x.get("p_tab4")), None)
        gap = abs(c - e) / a if a > 0 else 0
        dummy = dict(p_tab=tab, p_isi=100.0, p_tab4=tab4, p_isi4=100.0)
        p24 = 100.0 if order == "MARKET" else (FX._p_live(dummy, gap) if tab else None)
        p4 = 100.0 if order == "MARKET" else (FX._p_live(dummy, gap, "p_tab4", "p_isi4") if tab4 else None)
        if order == "LIMIT" and p24 is not None and p24 < FP["min_fill"]:
            continue
        risk = abs(e - sl)
        x = dict(cadangan=True, pola="Cadangan zona emas", alasan_pola="zona emas + skill tambahan", arah=arah,
                 mutu="C", golden=False, zona_emas=True, order=order, entry=e, sl=sl, tp1=tp1, tp2=tp2,
                 rr1=abs(tp1 - e) / risk, rr2=abs(tp2 - e) / risk, p_isi=p24, p_isi4=p4, p_tab=tab, p_tab4=tab4,
                 win=0, loss=0, wr=0.0, net_r=0.0, ev=0.0, dur=0.0, tersentuh=False, eksekusi=True,
                 sudah_masuk=False, slot=0, breakout=False, konf=n_k, konf_ok=ok,
                 p_arah=next((y.get("p_arah") for y in r["saran"] if y["arah"] == arah), 50.0),
                 n_arah=next((y.get("n_arah") for y in r["saran"] if y["arah"] == arah), 0))
        x["skor"] = n_k * 8 + (10 if r["rapor"] == "A" else 4) + (5 if order == "MARKET" else 0)
        cand.append((r, x))
    cand.sort(key=lambda z: (z[1]["konf"], z[0]["rapor"] == "A", z[0]["wr"]), reverse=True)
    return cand[:sisa]


def _catat_cadangan(led, cad):
    """Daftarkan saran cadangan ke catatan, hitung jatah per candle. Return daftar (r, x, tag)."""
    out = []
    for r, x in cad:
        tag = FX.register(led, r, x)
        if tag:
            out.append((r, x, tag))
    if out:
        st = _st_load()
        tutup = str(int(time.time() * 1000) // H4 * H4)
        n = dict(st.get("cad_n", {}))
        n[tutup] = n.get(tutup, 0) + sum(1 for _, _, t in out if t == "BARU")
        _st_update({"cad_n": {k: v for k, v in n.items() if int(k) >= int(tutup) - 6 * H4}})
    return out


def _posisi_kamu():
    """Koin yang sedang kamu pegang (dari /entry): posisi jalan atau sudah TP1."""
    return {v["sym"] for v in SY.lihat()["open"].values() if v["status"] in ("TERISI", "TP1")}


def _catat_jalur(led, items, kunci):
    """Daftarkan saran jalur tambahan (cadangan atau siklus), hitung jatah per candle. Return (r, x, tag)."""
    out = []
    for r, x in items:
        tag = FX.register(led, r, x)
        if tag:
            out.append((r, x, tag))
    if out:
        st = _st_load()
        tutup = str(int(time.time() * 1000) // H4 * H4)
        n = dict(st.get(kunci, {}))
        n[tutup] = n.get(tutup, 0) + sum(1 for _, _, t in out if t == "BARU")
        _st_update({kunci: {k: v for k, v in n.items() if int(k) >= int(tutup) - 6 * H4}})
    return out


def _siklus_saran(results, sel, cad, led, tickers, ctx, maks=3):
    """Saran dari QSE SIKLUS: pola kembar teruji + arah 4J dan 1D + aliran dana (dengan OI) + BTC searah."""
    if ctx["tahan"] or ctx["jeda"] or not QU.aktif("siklus"):
        return []
    st = _st_load()
    tutup = str(int(time.time() * 1000) // H4 * H4)
    sisa = maks - st.get("sik_n", {}).get(tutup, 0)
    if sisa <= 0:
        return []
    ada = {r["symbol"] for r, _ in sel} | {r["symbol"] for r, _, _ in cad} | _posisi_kamu()
    cand = []
    for r in results:
        sk = (r.get("siklus") or {}).get("saran")
        if not sk or r["tf"] != "240" or r["symbol"] in ada or r["symbol"] in ctx["delist"]:
            continue
        tk = tickers.get(r["symbol"]) or {}
        if tk and (tk.get("turnover", 0) < FP["min_turnover"] or tk.get("spread", 0) > FP["max_spread_pct"]):
            continue
        if FX._muted(led, r["symbol"], "Siklus pola kembar", sk["arah"]):
            continue
        L = sk["arah"] == "LONG"
        c = r.get("live") or r["close"]
        if (L and (c <= sk["sl"] or c >= sk["tp1"])) or ((not L) and (c >= sk["sl"] or c <= sk["tp1"])):
            continue
        ch, oisk = SIK.oi_skor(r["symbol"], BYBIT_URL, r["siklus"]["pr_ch"])
        dana = r["siklus"]["aliran"]["skor"] + oisk
        if (L and dana < 0) or ((not L) and dana > 0):
            continue
        r["siklus"]["aliran"]["oi"], r["siklus"]["aliran"]["skor_oi"] = ch, dana
        order, e = sk["order"], sk["entry"]
        if order == "MARKET" or (L and c <= e) or ((not L) and c >= e):
            order, e = "MARKET", c
        risk = abs(e - sk["sl"])
        if risk <= 0:
            continue
        pk = r["siklus"]["pola"]
        x = dict(siklus=True, pola="Siklus pola kembar", alasan_pola="pola kembar teruji", arah=sk["arah"], mutu="S",
                 golden=False, zona_emas=False, order=order, entry=e, sl=sk["sl"], tp1=sk["tp1"], tp2=sk["tp2"],
                 rr1=abs(sk["tp1"] - e) / risk, rr2=abs(sk["tp2"] - e) / risk, p_isi=100.0 if order == "MARKET" else None,
                 p_isi4=None, win=0, loss=0, wr=0.0, net_r=0.0, ev=0.0, dur=0.0, tersentuh=False, eksekusi=True,
                 sudah_masuk=False, slot=0, breakout=False, dana=dana, hitR=sk["hitR"],
                 naik=pk["up"] * 100, nM=pk["n"], uji=f"{pk['hitN']}/{pk['hitT']}")
        cand.append((r, x))
    cand.sort(key=lambda z: (z[1]["hitR"], abs(z[1]["naik"] - 50), z[1]["nM"]), reverse=True)
    return cand[:sisa]


def _konfluensi(r, arah, zona=False):
    """Faktor pendukung di luar syarat v148. Tidak menyaring, hanya menambah keyakinan."""
    L = arah == "LONG"
    ok = []
    if zona:
        ok.append("zona emas")
    if r.get("skill") and SK.konfirmasi(r["skill"], arah)[0] >= 6:
        ok.append("skill 6/8+")
    sk = r.get("siklus") or {}
    pk = sk.get("pola") or {}
    if pk.get("n", 0) >= 3 and ((pk["up"] >= 0.67) if L else (pk["up"] <= 0.33)):
        ok.append("pola kembar")
    fl = (sk.get("aliran") or {}).get("skor", 0)
    if (fl >= 2) if L else (fl <= -2):
        ok.append("aliran dana")
    c4, cd = sk.get("c4P"), sk.get("cDP")
    if c4 is not None and cd is not None and ((c4 >= 55 and cd >= 55) if L else (c4 <= 45 and cd <= 45)):
        ok.append("arah 4J dan 1D")
    ch = (r.get("pola_chart") or {}).get("chart") or {}
    if ch.get("arah") == ("NAIK" if L else "TURUN"):
        ok.append(ch["nama"])
    return len(ok), ok


def _lev_maks(x):
    slp = abs(x["entry"] - x["sl"]) / x["entry"] if x["entry"] > 0 else 1
    return max(1, min(FP["lev_cap"], int(1 / (slp * 1.3 + 0.006))))


def _alasan_cad(rs, ctx):
    if not QU.aktif("cadangan"):
        return "Tidak ada: jalur ini dimatikan uji mundur karena hasil 6 bulannya jelek."
    if ctx and (ctx["tahan"] or ctx["jeda"]):
        return "Tidak ada: sinyal baru sedang ditahan (jeda berita atau pasar bergejolak)."
    z = [r for r in rs if r["rapor"] in ("A", "B") and (r.get("pasar") or {}).get("zona_searah")
         and r["pasar"].get("btc_ok")]
    if not z:
        return "Tidak ada: belum ada koin rapor A/B di zona emas yang diizinkan BTC."
    best = max(SK.konfirmasi(r.get("skill"), r["pasar"]["arah"])[0] for r in z)
    return (f"Tidak ada: {len(z)} koin di zona emas, konfirmasi skill tertinggi {best}/8, "
            f"butuh minimal 6/8. Koinnya ada di bagian 3 untuk analisa manual.")


def _alasan_sik(rs, ctx):
    if not QU.aktif("siklus"):
        return "Tidak ada: jalur ini dimatikan uji mundur karena hasil 6 bulannya jelek."
    if ctx and (ctx["tahan"] or ctx["jeda"]):
        return "Tidak ada: sinyal baru sedang ditahan (jeda berita atau pasar bergejolak)."
    n = sum(1 for r in rs if ((r.get("siklus") or {}).get("saran")))
    if n:
        return f"Tidak ada: {n} kandidat pola kembar tertahan aliran dana, likuiditas, atau posisi kamu."
    return ("Tidak ada: belum ada pola kembar yang teruji dan searah dengan arah 4J, 1D, aliran dana, dan BTC. "
            "Syaratnya ketat, jadi jalur ini jarang muncul.")


def _blok_sik(no, r, x, tag, led):
    t, sk = r["tick"], r["siklus"]
    pk, fl = sk["pola"], sk["aliran"]
    arah_txt = "naik" if x["arah"] == "LONG" else "turun"
    rows = [f"🔵 <b>{no}. {TG.e(r['symbol'])} {x['arah']}</b> | SIKLUS",
            f"Pola kembar: {pk['n']} pola mirip, sesudahnya {arah_txt} "
            f"{x['naik'] if x['arah'] == 'LONG' else 100 - x['naik']:.0f}% | teruji {x['uji']} tepat",
            f"Arah 4J naik {sk['c4P']:.0f}% | 1D naik {sk['cDP']:.0f}% | BTC naik {r['bProb']:.0f}%",
            f"Aliran dana skor {x['dana']:+d}/4 | CMF {fl['cmf']:.2f} | MFI {fl['mfi']:.0f} | CVD {'naik' if fl['cvd_up'] else 'turun'}"
            + (f" | OI {fl['oi']:+.1f}%" if fl.get("oi") is not None else ""),
            f"Status: {'SARAN BARU' if tag == 'BARU' else 'ENTRY DIPERBARUI'}",
            _tabel(x, t)]
    if x["order"] == "MARKET":
        rows.append(f"Cara: MARKET sekarang, lot {SY.lot_jalur('saran siklus'):g}x lot normal, langsung pasang SL dan TP1")
    else:
        key = "%s|%s|%s|%s" % (r["symbol"], r["tf"], x["pola"], x["arah"])
        it = (led or {}).get("open", {}).get(key)
        rows.append(f"Cara: LIMIT di EMA20, lot {SY.lot_jalur('saran siklus'):g}x lot normal, batal otomatis "
                    f"{_jam(it['exp_ts']) if it and it.get('exp_ts') else '24 jam'}")
    rows.append("Kelola: TP1 tutup separuh, SL ke entry, sisa ke TP2")
    bl = MD.baris_lot(x["entry"], x["sl"], SY.lot_jalur("saran siklus"), _lev_maks(x))
    if bl:
        rows.append(bl)
    rows.append("Catatan: dari pola harga masa lalu, konfirmasi di DASBOR sebelum entry")
    rows.append(f'<a href="https://www.tradingview.com/chart/?symbol=BYBIT:{r["symbol"]}.P">Chart {TG.e(r["symbol"])}.P</a>')
    return "\n".join(rows)


def _konf_candle(p, arah):
    return SY.konfirmasi_candle(p, arah)[0]


def _fib_saran(results, sudah, led, tickers, ctx, maks=3):
    """Saran skill tambahan: harga di golden pocket 0.618-0.65 searah bias, konfirmasi skill minimal 5/8,
    candle konfirmasi, BTC mengizinkan. SL di luar ujung kaki fib plus ekor candle khas koin, TP1 ujung kaki, TP2 1.272."""
    if ctx["tahan"] or ctx["jeda"] or not QU.aktif("fib"):
        return []
    st = _st_load()
    tutup = str(int(time.time() * 1000) // H4 * H4)
    sisa = maks - st.get("fib_n", {}).get(tutup, 0)
    if sisa <= 0:
        return []
    cand = []
    for r in results:
        p, sk = r.get("pasar") or {}, r.get("skill")
        if (r["tf"] != "240" or r["symbol"] in sudah or r["symbol"] in ctx["delist"] or r["rapor"] == "D buruk"
                or not p.get("in_gp") or not p.get("zona_searah") or not p.get("btc_ok") or not sk):
            continue
        arah = p["arah"]
        L = arah == "LONG"
        n_k, _, ok = SK.konfirmasi(sk, arah)
        if n_k < 5 or not _konf_candle(p, arah):
            continue
        tk = tickers.get(r["symbol"]) or {}
        if tk and (tk.get("turnover", 0) < FP["min_turnover"] or tk.get("spread", 0) > FP["max_spread_pct"]):
            continue
        if FX._muted(led, r["symbol"], "Fib golden pocket", arah):
            continue
        c, a = r.get("live") or r["close"], r["atr"]
        w = ((r.get("pola_chart") or {}).get("wick") or {}).get("bawah" if L else "atas", 0.45)
        buf = max(0.45, w + 0.1) * a
        sl = p["fib_lo"] - buf if L else p["fib_hi"] + buf
        tp1 = p["fib_hi"] if L else p["fib_lo"]
        tp2 = p["e127"]
        risk = abs(c - sl)
        if risk <= 0 or risk > 3 * a or (L and not (sl < c < tp1 < tp2)) or ((not L) and not (sl > c > tp1 > tp2)):
            continue
        rr1, rr2 = abs(tp1 - c) / risk, abs(tp2 - c) / risk
        if rr1 < 0.8 or rr2 < 1.5:
            continue
        x = dict(fib=True, pola="Fib golden pocket", alasan_pola="0.618-0.65 + skill", arah=arah, mutu="F", golden=False,
                 zona_emas=True, order="MARKET", entry=c, sl=sl, tp1=tp1, tp2=tp2, rr1=rr1, rr2=rr2, p_isi=100.0,
                 p_isi4=100.0, win=0, loss=0, wr=0.0, net_r=0.0, ev=0.0, dur=0.0, tersentuh=False, eksekusi=True,
                 sudah_masuk=False, slot=0, breakout=False, konf=n_k, konf_ok=ok)
        cand.append((r, x))
    cand.sort(key=lambda z: (z[1]["konf"], z[0]["rapor"] in ("A", "B"), z[1]["rr2"]), reverse=True)
    return cand[:sisa]


def _cadangan2(results, sudah, led, tickers, ctx, maks=3):
    """Saran cadangan 2: rapor robot A/B dan saran mutu A/B yang di DASBOR masih TAHAN (alasan ditulis).
    Tetap lewat semua saringan harga dan fix profit. Lot kecil."""
    if ctx["tahan"] or ctx["jeda"]:
        return []
    st = _st_load()
    tutup = str(int(time.time() * 1000) // H4 * H4)
    sisa = maks - st.get("cad2_n", {}).get(tutup, 0)
    if sisa <= 0:
        return []
    keras = ("harga sudah lewat", "rapor", "SL", "spike", "jebakan", "sudah")
    salinan = []
    for r in results:
        if r["tf"] != "240" or r["rapor"] not in ("A", "B") or r["symbol"] in sudah or r["symbol"] in ctx["delist"]:
            continue
        sar = []
        for x in r["saran"]:
            if x["eksekusi"] or x["sudah_masuk"] or x["mutu"] not in ("A", "B") or any(k in x["alasan"] for k in keras):
                continue
            y = dict(x, eksekusi=True, cad2=True, alasan_tahan=x["alasan"])
            sar.append(y)
        if sar:
            salinan.append(dict(r, saran=sar))
    sel, _ = FX.select(salinan, tickers, led)
    for r, x in sel:
        x["skor"] = _skor(r, x, None)
    sel.sort(key=lambda z: z[1]["skor"], reverse=True)
    return sel[:sisa]


def _blok_fib(no, r, x, tag, led):
    t = r["tick"]
    p = r["pasar"]
    rows = [f"📐 <b>{no}. {TG.e(r['symbol'])} {x['arah']}</b> | SKILL FIB | konf {x['konf']}/8",
            f"Rapor robot {r['rapor']} | {r['trd']} trade | WR {r['wr']:.0f}%",
            TG.e(SY.fib_teks(r)),
            f"Skill searah: {', '.join(x['konf_ok'])} | candle: {TG.e(SY.konfirmasi_candle(p, x['arah'])[1])}",
            f"Status: {'SARAN BARU' if tag == 'BARU' else 'ENTRY DIPERBARUI'}",
            _tabel(x, t)]
    rows += [TG.e(z) for z in PL.teks(r.get("pola_chart"))]
    rows.append(_baris_waktu(r, x))
    rows.append(f"Cara: MARKET sekarang, lot {SY.lot_jalur('saran fib'):g}x lot normal, SL di luar ekor candle khas koin ini")
    rows.append("Kelola: TP1 di puncak kaki fib, tutup separuh, SL ke entry, sisa ke extension 1.272")
    bl = MD.baris_lot(x["entry"], x["sl"], SY.lot_jalur("saran fib"), _lev_maks(x))
    if bl:
        rows.append(bl)
    rows.append(f'<a href="https://www.tradingview.com/chart/?symbol=BYBIT:{r["symbol"]}.P">Chart {TG.e(r["symbol"])}.P</a>')
    return "\n".join(rows)


def _blok_cad2(no, r, x, tag, led):
    b = _blok(no, r, x, f"{x['mutu']} TAHAN di DASBOR ({x['alasan_tahan']}), dikirim sebagai CADANGAN 2", led)
    return b.replace(f"<b>{no}. ", f"<b>🟠 {no}. ", 1) + f"\nCatatan: lot {SY.lot_jalur('saran cadangan 2'):g}x, karena DASBOR masih TAHAN"


def _baris_waktu(r, x):
    jam_c = r["tf_ms"] / 3600000
    e1 = SY.estimasi_jam(x["tp1"] - x["entry"], r["atr"], jam_c)
    e2 = SY.estimasi_jam(x["tp2"] - x["entry"], r["atr"], jam_c)
    return (f"Perkiraan tersentuh: TP1 {SY.teks_waktu(e1)} ({SY.perkiraan_hari(e1)}) | "
            f"TP2 {SY.teks_waktu(e2)} ({SY.perkiraan_hari(e2)})")


def _blok_cad(no, r, x, tag, led):
    t = r["tick"]
    rows = [f"🟡 <b>{no}. {TG.e(r['symbol'])} {x['arah']}</b> | CADANGAN",
            f"Rapor robot {r['rapor']} | {r['trd']} trade | WR {r['wr']:.0f}% | PF {r['pf']:.2f}",
            "Dasar: zona emas searah bias, BTC mengizinkan",
            f"Skill searah {x['konf']}/8: {', '.join(x['konf_ok'])}",
            f"Status: {'SARAN BARU' if tag == 'BARU' else 'ENTRY DIPERBARUI'}",
            _tabel(x, t)]
    if x["order"] == "MARKET":
        rows.append(f"Cara: MARKET sekarang, lot {SY.lot_jalur('saran cadangan'):g}x lot normal, langsung pasang SL dan TP1")
    else:
        key = "%s|%s|%s|%s" % (r["symbol"], r["tf"], x["pola"], x["arah"])
        it = (led or {}).get("open", {}).get(key)
        if x.get("p_isi") is not None and x.get("p_isi4") is not None:
            rows.append(f"Peluang terisi 4 jam {x['p_isi4']:.0f}% | 24 jam {x['p_isi']:.0f}%")
        rows.append(f"Cara: LIMIT di entry, lot {SY.lot_jalur('saran cadangan'):g}x lot normal, batal otomatis "
                    f"{_jam(it['exp_ts']) if it and it.get('exp_ts') else '24 jam'}")
    rows.append("Kelola: TP1 tutup separuh, SL ke entry, sisa ke TP2")
    bl = MD.baris_lot(x["entry"], x["sl"], SY.lot_jalur("saran cadangan"), _lev_maks(x))
    if bl:
        rows.append(bl)
    rows.append("Catatan: belum lolos backtest v148")
    rows.append(f'<a href="https://www.tradingview.com/chart/?symbol=BYBIT:{r["symbol"]}.P">Chart {TG.e(r["symbol"])}.P</a>')
    return "\n".join(rows)


def _wr_baris(led):
    """Winrate hanya dari trade yang benar-benar kamu entry (/entry), plus status uji mundur jalur tambahan."""
    d = SY.lihat()
    out = f"{GARIS}\n" + SY.ringkas_rapi("📈 WR TRADE KAMU", d["closed"]) + "\n\n" + SY.wr_jalur(d["closed"])
    if QU.lihat():
        out += "\n\n" + QU.ringkas()
    return out


def cek_1j(now, jalur_aktif=True, paksa=False):
    """Saran TF 1J selektif: hanya koin rapor 4J A/B, arah 1J searah bias 4J, lolos semua syarat v148 di chart 1 jam.
    Statistik rapor robot 1J dicatat sebagai uji jalur 1J. Tidak menghapus cek per jam TF 4J."""
    t0 = time.time()
    try:
        with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
            lama = json.load(f)
    except Exception:
        return
    r4 = {r["symbol"]: r for r in lama if r.get("tf", "240") == "240" and r["rapor"] in ("A", "B")}
    if not r4:
        return
    syms = B.get_symbols()
    tickers = B.get_tickers()
    b4 = B.get_klines("BTCUSDT", "240", TV_BARS, closed_only=False)
    b1 = B.get_klines("BTCUSDT", "60", TV_BARS, closed_only=True)
    _init(dict(h4=b4, h4c=_split(b4, H4).iloc[-(TV_BARS - 1):], h1c=b1))
    led = FX.load()
    FX.antrian_terapkan(led)
    hasil = []
    for sym in [s for s in r4 if s in syms]:
        try:
            pk = fetch(sym, True)
            out, err = _work(sym, syms[sym], pk, ["60"])
            if err:
                print(f"[ERROR] 1J {sym}\n{err}")
            hasil += out
        except Exception as ex:
            print(f"[ERROR] 1J {sym}: {ex}")
    QU.catat_1j([r for r in hasil if r["rapor"] in ("A", "B")])
    for r in hasil:
        r["tk"] = tickers.get(r["symbol"])
        lp = (tickers.get(r["symbol"]) or {}).get("last", 0)
        if lp > 0:
            r["live"] = lp
        bias4 = (r4[r["symbol"]].get("pasar") or {}).get("arah")
        for x in r["saran"]:
            if bias4 and x["arah"] != bias4:
                x["eksekusi"] = False          # 1J wajib searah bias 4J
                x["alasan"] = "lawan bias 4J"
        r["rapor_1j"] = r["rapor"]
        if r["rapor"] in ("A", "B"):                 # syarat ganda: rapor 4J A/B dan rapor 1J A/B
            r["rapor"] = r4[r["symbol"]]["rapor"]
    events = [(ev, dict(it)) for ev, it in FX.recheck(led, {(r["symbol"], r["tf"]): r for r in hasil}, ["60"])]
    events = [(ev, it) for ev, it in events if ev == "BATAL"]
    baru = []
    if jalur_aktif and QU.aktif("1j"):
        sel, _ = FX.select(hasil, tickers, led)
        for r, x in sel:
            x["skor"] = _skor(r, x, None)
        jalan = _posisi_kamu()
        sel = [(r, x) for r, x in sel if r["symbol"] not in jalan]
        ctx = _konteks_berita(b1)
        sel = _saring_berita(sel, ctx)
        sel.sort(key=lambda z: (z[1]["golden"], z[1]["skor"]), reverse=True)
        for r, x in sel[:3]:
            tag = FX.register(led, r, x)
            if tag:
                baru.append((r, x, tag))
            elif paksa:
                baru.append((r, x, "MASIH"))
    FX.antrian_terapkan(led)
    FX.save(led)
    if not (baru or events or paksa):
        print(f"Cek TF 1J {len(hasil)} koin, tidak ada saran baru. {time.time() - t0:.0f}s")
        return
    jam = now.astimezone(WIB).strftime("%d/%m %H:%M WIB")
    judul = "🔎 <b>QSE v148 | SCAN SEKARANG TF 1J</b>" if paksa else "🕐 <b>QSE v148 | SARAN TF 1J</b>"
    blocks = [f"{judul}\n{jam}\n"
              f"Syarat ganda: rapor 4J A/B, rapor 1J A/B, dan searah bias 4J | dinilai {len(hasil)} koin"]
    if not jalur_aktif or not QU.aktif("1j"):
        blocks.append("Jalur TF 1J sedang dimatikan uji mundur karena hasil historisnya jelek.")
    if baru:
        blocks.append(f"{GARIS}\n🆕 <b>SARAN TF 1J ({len(baru)})</b>")
        st_ = {"BARU": "SINYAL BARU", "UPDATE": "ENTRY DIPERBARUI", "MASIH": "masih valid"}
        blocks += [_blok(i, r, x, f"{x['mutu']} EKSEKUSI, " + st_.get(tg, tg), led) for i, (r, x, tg) in enumerate(baru, 1)]
    elif paksa:
        blocks.append("Belum ada saran TF 1J yang lolos semua syarat di harga sekarang.")
    if events:
        blocks.append(f"{GARIS}\n❌ <b>SARAN 1J DIBATALKAN</b>\n" + "\n".join(TG.hasil(ev, it, syms) for ev, it in events))
    TG.send(blocks)
    for b in blocks:
        print(b, "\n")


def uji_mingguan(paksa=False):
    """Uji mundur saran cadangan dan siklus, seminggu sekali di run per jam (bukan jam scan 4 jam)."""
    u = QU.lihat()
    if not paksa and u and time.time() * 1000 - u.get("ts", 0) < 7 * 86400000:
        return
    try:
        with open(os.path.join(STATE_DIR, "screening_terbaru.json")) as f:
            lama = json.load(f)
    except Exception:
        return
    tickers = B.get_tickers()
    syms = B.get_symbols()
    pilih = [r["symbol"] for r in lama if r.get("tf", "240") == "240" and r["rapor"] in ("A", "B")]
    pilih += [s for s, _ in sorted(tickers.items(), key=lambda z: -z[1].get("turnover", 0))[:20]]
    daftar = [(s, syms[s]) for s in dict.fromkeys(pilih) if s in syms][:45]
    b4 = B.get_klines("BTCUSDT", "240", TV_BARS)

    def ambil(sym):
        return (B.get_klines(sym, "240", TV_BARS - 1), B.get_klines(sym, "60", (TV_BARS - 1) * 4 + 400),
                B.get_klines(sym, "D", 1500, closed_only=False), B.get_klines(sym, "W", 400, closed_only=False))
    print(f"Uji mundur {len(daftar)} koin...")
    u = QU.jalankan(daftar, ambil, b4)
    TG.send([QU.ringkas(u) + "\n\nJalur yang hasilnya jelek otomatis berhenti mengirim saran."])


def _blok_posisi_analisa(it, r):
    vonis, alasan, aksi, _ = SY.analisa_posisi(it, r, (r or {}).get("live"))
    px = (r or {}).get("live") or 0
    fl = SY.floating(it, px) if px else None
    ik = {"MASIH SESUAI ANALISA": "✅", "MELEMAH": "⚠️", "BERBALIK": "🛑"}.get(vonis, "•")
    head = f"{IKON.get(it['arah'], '')} <b>{TG.e(it['sym'])} {it['arah']}</b> | {SY.NM_POS.get(it['status'], it['status'])}"
    if fl:
        head += f" | {fl['pct']:+.2f}% | {fl['r']:+.2f}R"
    return f"{head}\n{ik} {vonis}\nKenapa: {TG.e('; '.join(alasan[:6]))}\nSaran: {TG.e(aksi)}"


def _cek_posisi_berubah(res_map):
    """Kabari bila vonis analisa posisi kamu berubah (misalnya dari MASIH SESUAI ke MELEMAH atau BERBALIK)."""
    out = []
    ganti = {}
    for k, it in SY.lihat()["open"].items():
        if it["status"] not in ("TERISI", "TP1"):
            continue
        r = res_map.get(it["sym"]) or SY.hasil_robot(it["sym"])
        if not r:
            continue
        vonis = SY.analisa_posisi(it, r, r.get("live"))[0]
        if it.get("vonis_pos") and vonis != it["vonis_pos"]:
            out.append(_blok_posisi_analisa(it, r) + f"\nSebelumnya: {it['vonis_pos']}")
        if vonis != it.get("vonis_pos"):
            ganti[k] = vonis
    if ganti:
        def f(d):
            for k, v in ganti.items():
                if k in d["open"]:
                    d["open"][k]["vonis_pos"] = v
        SY.ubah(f)
    return out


def _kartu_jam(results, b1, led):
    """Kartu ringkas yang selalu ada tiap jam: BTC, posisi kamu, saran aktif, koin paling bergerak."""
    rows = []
    try:
        c = b1["close"].values
        ch1, ch3 = (c[-1] / c[-2] - 1) * 100, (c[-1] / c[-4] - 1) * 100
        bt = next((r["btc"] for r in results), "")
        rows.append(f"₿ {TG.e(bt)} | 1 jam {ch1:+.2f}% | 3 jam {ch3:+.2f}%")
    except Exception:
        pass
    pos = [it for it in SY.lihat()["open"].values() if it["status"] in ("TERISI", "TP1")]
    if pos:
        peta = {r["symbol"]: r for r in results}
        bag = []
        for it in pos:
            px = (peta.get(it["sym"]) or {}).get("live")
            fl = SY.floating(it, px) if px else None
            bag.append(f"{it['sym']} {it['arah']} " + (f"{fl['pct']:+.1f}% ({fl['r']:+.2f}R)" if fl else "-"))
        rows.append("👤 Posisi: " + " | ".join(bag))
    aktif = [v for v in led["open"].values() if v["status"] == "MENUNGGU"]
    rows.append(f"📡 Saran LIMIT aktif: {len(aktif)} (ketik /sinyal4j)")
    gerak = []
    for r in results:
        o = ((r.get("pasar") or {}).get("k_now") or (0,))[0]
        if o and r.get("live") and r["rapor"] in ("A", "B"):
            gerak.append(((r["live"] / o - 1) * 100, r["symbol"]))
    if gerak:
        gerak.sort(key=lambda z: -abs(z[0]))
        rows.append("🚀 Paling bergerak sejak candle 4J dibuka: " + ", ".join(f"{sy} {g:+.1f}%" for g, sy in gerak[:3]))
    return "\n".join(rows)


def cek_cepat(now, paksa=False):
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
    target |= {v["sym"] for v in SY.lihat()["open"].values()}        # posisi kamu selalu dipantau
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
    jalan = _posisi_kamu()
    sel = [(r, x) for r, x in sel if r["symbol"] not in jalan]
    ctx = _konteks_berita(b1)
    sel = _saring_berita(sel, ctx)
    events += [(ev, dict(it)) for ev, it in FX.ganti(led, sel)]
    tag_of = {id(x): (FX.register(led, r, x) or "sudah dikirim") for r, x in sel}
    baru = [(r, x) for r, x in sel if tag_of[id(x)] in ("BARU", "UPDATE")]
    cad = _catat_jalur(led, _cadangan(results, sel, led, tickers, ctx, None), "cad_n")
    sik = _catat_jalur(led, _siklus_saran(results, sel, cad, led, tickers, ctx), "sik_n")
    sudah = ({r["symbol"] for r, _ in sel} | {r["symbol"] for r, _, _ in cad} | {r["symbol"] for r, _, _ in sik}
             | _posisi_kamu())
    fib = _catat_jalur(led, _fib_saran(results, sudah, led, tickers, ctx), "fib_n")
    sudah |= {r["symbol"] for r, _, _ in fib}
    cad2 = _catat_jalur(led, _cadangan2(results, sudah, led, tickers, ctx), "cad2_n")
    events = [(ev, it) for ev, it in events if ev == "BATAL"]
    info = []
    for e in BR.pengingat():
        info.append(f"⚠️ BERITA BESAR {TG.e(e['judul'])} {BR.jam_wib(e['ts'])}. Sinyal baru ditahan mulai 2 jam "
                    f"sebelum sampai 1 jam sesudah rilis. Posisi jalan: kunci profit atau geser SL ke entry sebelum rilis.")
    if ctx["kirim_guncang"]:
        g = ctx["kirim_guncang"]
        info.append(f"⚠️ PASAR BERGEJOLAK: BTC {'NAIK' if g['pct'] > 0 else 'TURUN'} tajam, {g['x']:.1f} kali gerak normal, 3 jam terakhir {g['pct']:+.1f}%. "
                    f"Sinyal baru ditahan 3 jam. Posisi jalan: kunci profit atau geser SL ke entry.")
    # alarm zona emas untuk trading manual, sekali per koin per candle 4J
    st = _st_load()
    sudah = st.get("alarm_zona", {})
    tutup = int(time.time() * 1000) // H4 * H4
    alarm = []
    ada = {r["symbol"] for r, _ in sel} | {r["symbol"] for r, _, _ in cad} | {r["symbol"] for r, _, _ in sik}
    for r in results:
        p = r.get("pasar") or {}
        if r["symbol"] in ada or r["rapor"] not in ("A", "B") or not p.get("zona_searah") or not p.get("btc_ok"):
            continue
        n_k = SK.konfirmasi(r.get("skill"), p["arah"])[0]
        if n_k >= ALARM_KONF and (paksa or sudah.get(r["symbol"]) != tutup):
            if not paksa:
                sudah[r["symbol"]] = tutup
            zi = SY.info_zona(r) or {}
            alarm.append(f"{IKON.get(p['arah'], '')} <b>{TG.e(r['symbol'])} {p['arah']}</b> | rapor {r['rapor']} | konf {n_k}/8\n"
                         + (TG.e(zi["teks"]) + "\n" if zi.get("teks") else "")
                         + f"DASBOR: {TG.e(_status_dasbor(r))}")
    _st_update({"alarm_zona": {k: v for k, v in sudah.items() if v >= tutup - H4}})
    pos_berubah = _cek_posisi_berubah({r["symbol"]: r for r in results})
    FX.antrian_terapkan(led)
    FX.save(led)
    # perbarui hasil scan untuk /cek tanpa menghapus koin lain
    peta = {(r["symbol"], r["tf"]): r for r in results}
    lama = [peta.pop((r["symbol"], r.get("tf", "240")), r) for r in lama] + list(peta.values())
    with open(path, "w") as f:
        json.dump(lama, f, default=float)
    masih = [(r, x) for r, x in sel if tag_of[id(x)] == "sudah dikirim"] if paksa else []
    jam = now.astimezone(WIB).strftime("%d/%m %H:%M WIB")
    judul = "🔎 <b>QSE v148 | SCAN SEKARANG TF 4J</b>" if paksa else "⏱️ <b>QSE v148 | CEK PER JAM TF 4J</b>"
    blocks = [f"{judul}\n{jam}\n" + _kartu_jam(results, b1, led)]
    if paksa and not (baru or masih or cad or sik or fib or cad2):
        blocks.append("Belum ada saran 4J baru yang lolos semua syarat di harga sekarang.")
    if masih:
        blocks.append(f"{GARIS}\n✅ <b>SARAN 4J MASIH VALID ({len(masih)})</b>")
        blocks += [_blok(i, r, x, f"{x['mutu']} EKSEKUSI, masih valid", led) for i, (r, x) in enumerate(masih, 1)]
    if info:
        blocks.append(f"{GARIS}\n⚠️ <b>PERINGATAN PASAR</b>\n" + "\n".join(info))
    if pos_berubah:
        blocks.append(f"{GARIS}\n👤 <b>ANALISA POSISI KAMU BERUBAH</b>\n\n" + "\n\n".join(pos_berubah))
    if baru:
        blocks.append(f"{GARIS}\n🆕 <b>SINYAL BARU DI TENGAH CANDLE ({len(baru)})</b>")
        for i, (r, x) in enumerate(baru, 1):
            st_ = f"{x['mutu']} EKSEKUSI, " + ("SINYAL BARU" if tag_of[id(x)] == "BARU" else "ENTRY DIPERBARUI")
            if x.get("tersentuh"):
                st_ += ", entry pernah tersentuh"
            blocks.append(_blok(i, r, x, st_, led))
    if fib:
        blocks.append(f"{GARIS}\n📐 <b>SARAN SKILL FIB 0.618-0.65 ({len(fib)})</b>")
        blocks += [_blok_fib(i, r, x, tg, led) for i, (r, x, tg) in enumerate(fib, 1)]
    if cad2:
        blocks.append(f"{GARIS}\n🟠 <b>SARAN CADANGAN 2 ({len(cad2)})</b>\nRapor A/B, saran mutu A/B yang di DASBOR masih TAHAN.")
        blocks += [_blok_cad2(i, r, x, tg, led) for i, (r, x, tg) in enumerate(cad2, 1)]
    if cad:
        blocks.append(f"{GARIS}\n🟡 <b>SARAN CADANGAN ({len(cad)})</b>\nDari zona emas dan skill tambahan.")
        blocks += [_blok_cad(i, r, x, tg, led) for i, (r, x, tg) in enumerate(cad, 1)]
    if sik:
        blocks.append(f"{GARIS}\n🔵 <b>SARAN SIKLUS ({len(sik)})</b>\nDari pola kembar dan siklus pasar.")
        blocks += [_blok_sik(i, r, x, tg, led) for i, (r, x, tg) in enumerate(sik, 1)]
    if events:
        blocks.append(f"{GARIS}\n❌ <b>SARAN DIBATALKAN</b>\n" + "\n".join(TG.hasil(ev, it, syms) for ev, it in events))
    if alarm:
        blocks.append(f"{GARIS}\n🥇 <b>ALARM ZONA EMAS UNTUK ENTRY MANUAL</b>\n"
                      "Cek chart dan tunggu candle konfirmasi searah\n\n" + "\n\n".join(alarm))
    prospek = [(r, x) for r, x in baru if x.get("golden") or _konfluensi(r, x["arah"], x.get("zona_emas"))[0] >= 3
               or x["mutu"] == "A"]
    if prospek:
        _pin(TG.send([f"🎯 <b>QSE v148 | SINYAL PROSPEK 4 JAM</b>\n{jam}\nSinyal baru di tengah candle dengan mutu A, "
                      f"GOLDEN, atau konfluensi tinggi."] +
                     [_blok(i, r, x, f"{x['mutu']} EKSEKUSI, SINYAL BARU", led) for i, (r, x) in enumerate(prospek, 1)]) or [])
    TG.send(blocks)
    for b in blocks:
        print(b, "\n")
    print(f"Cek per jam selesai {time.time() - t0:.0f}s")


def pantau(now):
    """Run tiap jam di antara candle 4J: pantau trade kamu, perbarui catatan saran tanpa pesan."""
    trade_saya()
    if not _listener_hidup():          # cadangan bila listener mati: alarm harga dicek tiap jam
        try:
            kena = AL.cek()
            if kena:
                TG.send(["🔔 <b>QSE v148 | ALARM HARGA</b>\n\n" + "\n\n".join(kena)])
        except Exception as ex:
            print("[WARN] alarm:", ex)
    led = FX.load()
    FX.antrian_terapkan(led)
    for s in sorted({v["sym"] for v in led["open"].values()}):
        try:
            FX.update(led, s, B.get_klines(s, "60", 300))
        except Exception as ex:
            print(f"[ERROR] pantau {s}: {ex}")
    FX.antrian_terapkan(led)
    FX.save(led)


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
    ctx = _konteks_berita(btc.get("h1c"))
    for it in SY.lihat()["open"].values():
        if it["sym"] in ctx["delist"]:
            waspada.append(f"⚠️ <b>{TG.e(it['sym'])} {it['arah']}</b>\n↳ Bybit mengumumkan delisting koin ini. "
                           f"Tutup posisi atau batalkan order sebelum tanggal delisting.")
    if ctx["kirim_guncang"]:
        g = ctx["kirim_guncang"]
        waspada.append(f"⚠️ PASAR BERGEJOLAK: BTC {'NAIK' if g['pct'] > 0 else 'TURUN'} tajam, {g['x']:.1f} kali gerak normal, 3 jam terakhir {g['pct']:+.1f}%. "
                       f"Sinyal baru ditahan 3 jam. Posisi jalan: kunci profit atau geser SL ke entry.")
    if waspada:
        TG.send(["⚠️ <b>QSE v148 | PERINGATAN POSISI</b>\n\n" + "\n\n".join(waspada)])
    events += [(ev, dict(it)) for ev, it in FX.recheck(led, res_map, tfs)]
    for r in results:
        r["tk"] = tickers.get(r["symbol"])
    rb = ramal_btc(btc["h4c"]) if "240" in tfs else None
    sel, drop = FX.select(results, tickers, led)
    for r, x in sel:
        x["skor"] = _skor(r, x, rb)
    sel.sort(key=lambda z: (z[1]["golden"], z[1]["skor"]), reverse=True)
    jalan = _posisi_kamu()
    sel = [(r, x) for r, x in sel if r["symbol"] not in jalan]     # koin yang kamu pegang, cegah entry ganda
    sel = _saring_berita(sel, ctx)
    events += [(ev, dict(it)) for ev, it in FX.ganti(led, sel)]
    tag_of = {id(s): (FX.register(led, r, s) or "sudah dikirim") for r, s in sel}
    cad = _catat_jalur(led, _cadangan(results, sel, led, tickers, ctx, rb), "cad_n")
    sik = _catat_jalur(led, _siklus_saran(results, sel, cad, led, tickers, ctx), "sik_n")
    sudah = ({r["symbol"] for r, _ in sel} | {r["symbol"] for r, _, _ in cad} | {r["symbol"] for r, _, _ in sik}
             | _posisi_kamu())
    fib = _catat_jalur(led, _fib_saran(results, sudah, led, tickers, ctx), "fib_n")
    sudah |= {r["symbol"] for r, _, _ in fib}
    cad2 = _catat_jalur(led, _cadangan2(results, sudah, led, tickers, ctx), "cad2_n")
    events = [(ev, it) for ev, it in events if ev == "BATAL"]      # hanya saran yang dibatalkan yang dikabarkan
    for tf in tfs:
        blocks, sinyal, ada = _pesan_tf(tf, results, sel, tag_of, led, events, syms, now, tfs, rb, ctx, cad, sik,
                                        fib, cad2)
        if fail > max(5, 0.05 * len(order)):
            blocks[0] += f"\nData tidak lengkap: {fail} koin gagal diambil atau dihitung"
        if ada:
            _pin(TG.send(sinyal) or [])
        TG.send(blocks)
        for b in sinyal + blocks:
            print(b, "\n")
    FX.antrian_terapkan(led)
    FX.save(led)
    _dump(results)
    print(f"Selesai {time.time() - t0:.0f}s | hasil {len(results)} | gagal {fail}")


WIB = dt.timezone(dt.timedelta(hours=7))
IKON = {"LONG": "🟢", "SHORT": "🔴"}
GARIS = "━━━━━━━━━━━━━━━━"
NAMA = {"240": ("4 JAM", "4J"), "60": ("1 JAM", "1J")}


def _jam(ms):
    return dt.datetime.fromtimestamp(ms / 1000, WIB).strftime("%d/%m %H:%M WIB")


def _tabel(s, t):
    risk = max(abs(s["entry"] - s["sl"]), t)
    pc = lambda v: abs(v - s["entry"]) / s["entry"] * 100 if s["entry"] else 0
    rows = [("Entry", s["entry"], s["order"]), ("SL", s["sl"], "-1.00R  -%.1f%%" % pc(s["sl"])),
            ("TP1", s["tp1"], "%+.2fR  +%.1f%%" % (abs(s["tp1"] - s["entry"]) / risk, pc(s["tp1"]))),
            ("TP2", s["tp2"], "%+.2fR  +%.1f%%" % (abs(s["tp2"] - s["entry"]) / risk, pc(s["tp2"])))]
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
    ikon, arah = ("📈", "condong naik, LONG lebih aman") if p >= 55 else \
        ("📉", "condong turun, SHORT lebih aman") if p <= 45 else ("➖", "seimbang, tidak ada arah kuat")
    atr = f"{rb['atr']:,.0f}" if rb["atr"] >= 100 else f"{rb['atr']:.4g}"
    return (f"🔮 <b>RAMALAN BTC 4 JAM</b>\n"
            f"Candle berikutnya naik {p:.0f}% ({rb['n']} kondisi mirip)\n"
            f"Gerak khas ±{atr} USDT ({rb['atr_pct']:.1f}%)\n"
            f"Kesimpulan: {arah}")


def _blok(no, r, s, status, led=None):
    t = r["tick"]
    jam_c = r["tf_ms"] / 3600000
    rows = []
    if s["golden"]:
        rows.append("🌟 <b>GOLDEN MOMENT</b>")
    rows += [f"{IKON.get(s['arah'], '')} <b>{no}. {TG.e(r['symbol'])} {s['arah']}</b> | skor {s.get('skor', 0)}/100"
             + (" | TF 1J" if r["tf"] == "60" else ""),
             (f"Rapor robot 4J {r['rapor']} | rapor 1J {r.get('rapor_1j', '-')} | {r['trd']} trade | WR {r['wr']:.0f}% | PF {r['pf']:.2f}"
              if r["tf"] == "60" else f"Rapor robot {r['rapor']} | {r['trd']} trade | WR {r['wr']:.0f}% | PF {r['pf']:.2f}"),
             f"Pola {TG.e(s['pola'])} | mutu {s['mutu']}" + (" | zona emas" if s["zona_emas"] else ""),
             f"Riwayat pola {s['win']} TP / {s['loss']} SL | WR {s['wr']:.0f}% | {s['net_r']:+.1f}R",
             f"Status: {TG.e(status)}",
             _tabel(s, t)]
    g4 = r["atr"] * (4 / jam_c) ** 0.5
    rows.append(f"Ramalan: candle berikutnya searah {s.get('p_arah', 50):.0f}% | gerak ±{TG.fp(g4, t)} ({g4 / r['close'] * 100:.1f}%)")
    if s["order"] != "MARKET":
        rows.append(f"Peluang terisi 4 jam {s.get('p_isi4', 0):.0f}% | 24 jam {s['p_isi']:.0f}%")
    if s.get("dur", 0) > 0:
        rows.append(f"Perkiraan hasil ±{s['dur']:.0f} candle ({s['dur'] * jam_c:.0f} jam) dari riwayat pola")
    rows.append(_baris_waktu(r, s))
    hk = SY.hari_ini_koin(r, s["arah"])
    if hk:
        rows.append(TG.e(hk))
    rows += [TG.e(z) for z in PL.teks(r.get("pola_chart"))]
    pt = r.get("pola_top") or []
    if pt:
        rows.append("Pola terbaik koin ini: " + ", ".join(f"{TG.e(z['pola'])} {'B' if z['arah'] == 'LONG' else 'S'} "
                                                         f"{z['net_r']:+.1f}R" for z in pt[:3]))
    sa = SY.sl_aman(r, s["arah"], s["entry"], s["sl"])
    if sa:
        rows.append(TG.e(sa))
    if r.get("skill"):
        n_k, tot, ok = SK.konfirmasi(r["skill"], s["arah"])
        rows.append(f"Konfirmasi skill {n_k}/{tot}" + (f": {', '.join(ok)}" if ok else ""))
    nk, kf = _konfluensi(r, s["arah"], s["zona_emas"])
    if nk:
        rows.append(f"Konfluensi {nk}/6" + (" TINGGI" if nk >= 3 else "") + f": {', '.join(kf)}")
    tk = r.get("tk")
    if tk:
        rows.append(f"Volume 24j {_uang(tk['turnover'])} | funding {tk['funding'] * 100:+.4f}% | "
                    f"spread {tk['spread']:.2f}%")
    key = "%s|%s|%s|%s" % (r["symbol"], r["tf"], s["pola"], s["arah"])
    it = (led or {}).get("open", {}).get(key)
    if s["order"] == "MARKET":
        rows.append("Cara: MARKET sekarang, langsung pasang SL dan TP1")
    else:
        rows.append(f"Cara: LIMIT di entry, batal otomatis {_jam(it['exp_ts']) if it and it.get('exp_ts') else '24 jam'}")
    rows.append("Kelola: TP1 tutup separuh, SL ke entry, sisa ke TP2")
    jl = "saran 1J" if r["tf"] == "60" else "saran utama"
    if SY.lot_jalur(jl) != 1.0:
        rows.append(f"Lot: {SY.lot_jalur(jl):g}x lot normal" + (" (saran TF 1J)" if r["tf"] == "60" else " (dari hasil trade kamu)"))
    slp = abs(s["entry"] - s["sl"]) / s["entry"] if s["entry"] > 0 else 1
    lev = max(1, min(FP["lev_cap"], int(1 / (slp * 1.3 + 0.006))))
    rows.append(f"Leverage maks {lev}x isolated | SL {slp * 100:.1f}% dari entry")
    bl = MD.baris_lot(s["entry"], s["sl"], SY.lot_jalur("saran 1J" if r["tf"] == "60" else "saran utama"), lev)
    if bl:
        rows.append(bl)
    elif FP["risk_usdt"] > 0:
        qty = FP["risk_usdt"] / max(abs(s["entry"] - s["sl"]), t)
        rows.append(f"Lot risiko {FP['risk_usdt']:g} USDT: {qty:.4g} koin | nilai {qty * s['entry']:,.0f} USDT")
    rows.append(f'<a href="https://www.tradingview.com/chart/?symbol=BYBIT:{r["symbol"]}.P">Chart {TG.e(r["symbol"])}.P</a>')
    return "\n".join(rows)


def _rekap(led, now, hari=1, judul="REKAP KEMARIN", why_ok=("SL", "BE", "TP2")):
    b = int(dt.datetime(now.year, now.month, now.day, tzinfo=dt.timezone.utc).timestamp() * 1000)
    a = b - hari * 86400000
    cl = [c for c in led["closed"] if c.get("why") in why_ok and a <= c.get("closed_ts", 0) < b]
    if not cl:
        return f"🗓️ <b>{judul}</b>\nTidak ada trade yang selesai."
    net = sum(c["result_r"] for c in cl)
    win = sum(1 for c in cl if c["result_r"] > 0)
    rows = [f"🗓️ <b>{judul}</b>", f"{len(cl)} trade | WR {win / len(cl) * 100:.0f}% | {net:+.2f}R"]
    ik = {"TP2": "🏆", "BE": "⚖️", "SL": "🛑", "TUTUP": "✋"}
    if hari == 1:
        rows += [f"{ik.get(c['why'], '•')} {TG.e(c['sym'])} {c['arah']} | {TG.e(c.get('pola', c.get('order', 'manual')))} | "
                 f"{c['why']} {c['result_r']:+.2f}R" for c in cl]
    else:
        per = {}
        for c in cl:
            k = c.get("pola", "manual")
            per.setdefault(k, [0, 0.0])
            per[k][0] += 1
            per[k][1] += c["result_r"]
        urut = sorted(per.items(), key=lambda z: -z[1][1])
        rows.append("Terbaik: " + ", ".join(f"{TG.e(k)} {v[1]:+.1f}R ({v[0]})" for k, v in urut[:3]))
        rows.append("Terburuk: " + ", ".join(f"{TG.e(k)} {v[1]:+.1f}R ({v[0]})" for k, v in urut[-3:][::-1]))
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
    """Bagian 3: pasar rapor A/B di luar sinyal valid. Tiap koin tampil sekali dengan label kategorinya."""
    ada = {r["symbol"] for r, _ in sig}
    pool = [r for r in rs if r["rapor"] in ("A", "B") and r["symbol"] not in ada and r.get("pasar")
            and (not r.get("tk") or r["tk"]["turnover"] >= FP["min_turnover"])]
    kat = {}
    for r in pool:
        p = r["pasar"]
        tg = []
        z = p["zona_searah"] and p["btc_ok"]
        m = r["rapor"] == "A" and p["btc_selaras"] and p["bentuk"]
        ap = _aplus(r)
        if z and m and ap:
            tg.append("Lengkap")
        if m:
            tg.append("Momen emas")
        if z:
            tg.append("Zona emas")
        if ap:
            tg.append("A+")
        kat[r["symbol"]] = tg
    pilih = [r for r in pool if kat[r["symbol"]]]
    pilih.sort(key=lambda r: (-len(kat[r["symbol"]]), -SK.konfirmasi(r.get("skill"), r["pasar"]["arah"])[0], -r["wr"]))
    nL = sum(1 for r in pool if r["pasar"]["arah"] == "LONG")
    nOk = sum(1 for r in pool if r["pasar"]["btc_ok"])
    hit = lambda lbl: sum(1 for r in pool if lbl in kat[r["symbol"]])
    head = (f"{GARIS}\n🔭 <b>3. PANTAUAN MANUAL</b> (di luar sinyal valid)\n"
            f"Bias koin: LONG {nL} | SHORT {len(pool) - nL} | diizinkan BTC {nOk}\n"
            f"Lengkap {hit('Lengkap')} | Momen emas {hit('Momen emas')} | Zona emas {hit('Zona emas')} | A+ {hit('A+')}\n"
            "Entry manual hanya bila harga di zona dan ada candle konfirmasi searah")
    out = [head]
    tampil = [r for r in pool if r["rapor"] == "A" or kat[r["symbol"]]]
    tampil.sort(key=lambda r: (r["rapor"] != "A", -len(kat[r["symbol"]]),
                               -SK.konfirmasi(r.get("skill"), r["pasar"]["arah"])[0], -r["wr"]))
    for r in tampil[:20]:
        p = r["pasar"]
        n_k = SK.konfirmasi(r.get("skill"), p["arah"])[0]
        zi = SY.info_zona(r) or {}
        out.append(f"{IKON.get(p['arah'], '')} <b>{TG.e(r['symbol'])} {p['arah']}</b> | rapor {r['rapor']} | "
                   f"WR {r['wr']:.0f}% | PF {r['pf']:.2f} | konf {n_k}/8 | ADX {p['adx']:.0f}\n"
                   + (f"Kategori: {', '.join(kat[r['symbol']])}\n" if kat[r["symbol"]] else "")
                   + (TG.e(zi["teks"]) + "\n" if zi.get("teks") else "")
                   + f"DASBOR: {TG.e(_status_dasbor(r))}")
    pilih = tampil
    if not pilih:
        out.append("Belum ada koin yang masuk kategori. Biasanya karena bias koin ditahan BTC atau harga belum di zona.")
    lain = [r for r in pool if r not in tampil[:20]]
    rA = [r["symbol"] for r in lain if r["rapor"] == "A"]
    rB = [r["symbol"] for r in lain if r["rapor"] == "B"]
    if rA or rB:
        out.append("<b>Rapor A/B lainnya</b>\n" + (f"A: {', '.join(rA)}\n" if rA else "") + (f"B: {', '.join(rB)}" if rB else ""))
    return out


def _pesan_tf(tf, results, sel, tag_of, led, events, syms, now, tfs=("240", "60"), rb=None, ctx=None, cad=None, sik=None,
              fib=None, cad2=None):
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
                    tahan.append((r, s, s["saring"]))
                elif s.get("buang"):
                    buang.append((r, s, s["buang"]))
    rA = [r for r in rs if r["rapor"] == "A"]
    rB = [r for r in rs if r["rapor"] == "B"]
    tutup = rs[0]["time"] + rs[0]["tf_ms"] if rs else 0
    baru = sum(1 for r, s in sig if tag_of[id(s)] != "sudah dikirim")
    cad = [z for z in (cad or []) if z[0]["tf"] == tf]
    head = [f"📊 <b>QSE v148 | LAPORAN {judul}</b>",
            f"Candle {kode} tutup {_jam(tutup)}" if tutup else now.astimezone(WIB).strftime("%d/%m %H:%M WIB"),
            ""]
    bt = next((r for r in results if r["tf"] == "240"), rs[0] if rs else None)
    if bt:
        alt = next((r for r in rs if "BTC" not in r["symbol"]), bt)
        head.append(f"{TG.e(bt['btc'])} | peluang naik 24 jam {bt['bProb']:.0f}%")
        head.append(f"Arah diizinkan: {alt.get('izin', '-')}")
    head.append(f"Dipindai {len(rs)} koin | rapor A {len(rA)} | rapor B {len(rB)}")
    head.append(f"Sinyal valid {len(sig)} | baru {baru} | masih valid {len(sig) - baru}" +
                (f" | cadangan {len(cad)}" if cad else "") + (f" | siklus {len(sik)}" if sik else ""))
    sik = [z for z in (sik or []) if z[0]["tf"] == tf]
    fib = [z for z in (fib or []) if z[0]["tf"] == tf]
    cad2 = [z for z in (cad2 or []) if z[0]["tf"] == tf]
    st_open = {}
    for it in SY.lihat()["open"].values():
        st_open[it["status"]] = st_open.get(it["status"], 0) + 1
    if st_open:
        nm = {"MENUNGGU": "menunggu terisi", "TERISI": "posisi jalan", "TP1": "sudah TP1"}
        head.append("Trade kamu: " + ", ".join(f"{v} {nm.get(k, k)}" for k, v in st_open.items()))
    if ctx and tf == "240":
        head += _berita_baris(ctx)
    mst = MD.status()
    if mst["rem"]:
        head.append("⛔ " + mst["alasan"])
    alasan = {}
    for r in rs:
        if r["rapor"] in ("A", "B"):
            for x in r["saran"]:
                if x["mutu"] in ("A", "B") and not x["eksekusi"]:
                    alasan[x["alasan"]] = alasan.get(x["alasan"], 0) + 1
    if alasan and not sig:
        top = sorted(alasan.items(), key=lambda z: -z[1])[:3]
        head.append("Penahan utama: " + ", ".join(f"{TG.e(k)} {v}" for k, v in top))
    eks = [(r, x) for r in rs for x in r["saran"] if x["eksekusi"] and not x["sudah_masuk"]]
    eks_ab = [(r, x) for r, x in eks if x["mutu"] in ("A", "B")]
    eks_rp = [(r, x) for r, x in eks_ab if r["rapor"] in ("A", "B")]
    head.append(f"Corong saran: EKSEKUSI di DASBOR {len({r['symbol'] for r, _ in eks})} koin | mutu A/B "
                f"{len({r['symbol'] for r, _ in eks_ab})} | rapor robot A/B {len({r['symbol'] for r, _ in eks_rp})} | "
                f"lolos harga dan fix profit {len(sig)}")
    out = ["\n".join(head)]
    if rb and tf == "240":
        out.append(_blok_ramal(rb))
    tutup_dt = dt.datetime.fromtimestamp(tutup / 1000, dt.timezone.utc) if tutup else now
    if tf == "240" and tutup_dt.hour == 0:
        out.append(_rekap(SY.lihat(), tutup_dt, 1, "REKAP TRADE KAMU KEMARIN", ("SL", "BE", "TP2", "TUTUP")))
        out.append(_evaluasi_saran(led, tutup_dt))
        if tutup_dt.weekday() == 0:
            out.append(_rekap(SY.lihat(), tutup_dt, 7, "REKAP 7 HARI TRADE KAMU", ("SL", "BE", "TP2", "TUTUP")))
            if len(SY._selesai()) >= 5:
                out.append(SY.evaluasi())
    so = []
    if sig or cad or sik or fib or cad2:
        rows = ["📋 <b>RINGKASAN</b>"]
        mst = MD.status()
        sisa_slot = max(0, MD.lihat()["posisi"] - mst["n_posisi"])
        rows.append(f"Urutan = prioritas. Slot posisi tersisa {sisa_slot} dari {MD.lihat()['posisi']}"
                    + (f" | ⛔ {mst['alasan']}" if mst["rem"] else ""))
        rows += [f"{IKON.get(s['arah'], '')} {TG.e(r['symbol'])} {s['arah']} | {s['order']} | mutu {s['mutu']} | "
                 f"skor {s.get('skor', 0)} | konfluensi {_konfluensi(r, s['arah'], s['zona_emas'])[0]}/6"
                 + (" | 🌟 GOLDEN" if s["golden"] else "") for r, s in sig]
        rows += [f"🟡 {TG.e(r['symbol'])} {x['arah']} | {x['order']} | cadangan | konf {x['konf']}/8" for r, x, _ in cad]
        rows += [f"🔵 {TG.e(r['symbol'])} {x['arah']} | {x['order']} | siklus | teruji {x['uji']}" for r, x, _ in sik]
        rows += [f"📐 {TG.e(r['symbol'])} {x['arah']} | MARKET | fib 0.618-0.65 | konf {x['konf']}/8" for r, x, _ in fib]
        rows += [f"🟠 {TG.e(r['symbol'])} {x['arah']} | {x['order']} | cadangan 2 | {TG.e(x['alasan_tahan'])}" for r, x, _ in cad2]
        so.append("\n".join(rows))
    so.append(f"{GARIS}\n🎯 <b>1. SINYAL VALID ({len(sig)})</b>" +
               ("" if sig else "\nBelum ada sinyal yang lolos semua syarat di candle ini."))
    for i, (r, s) in enumerate(sig, 1):
        tg = tag_of[id(s)]
        st = f"{s['mutu']} EKSEKUSI, " + ("SINYAL BARU" if tg in ("BARU", "UPDATE") else "masih valid")
        if s.get("tersentuh"):
            st += ", entry pernah tersentuh"
        so.append(_blok(i, r, s, st, led))
    so.append(f"{GARIS}\n🟡 <b>1B. SARAN CADANGAN ({len(cad)})</b>\n" +
               ("Dari zona emas dan skill tambahan." if cad else _alasan_cad(rs, ctx)))
    so += [_blok_cad(i, r, x, tg, led) for i, (r, x, tg) in enumerate(cad, 1)]
    so.append(f"{GARIS}\n🔵 <b>1C. SARAN SIKLUS ({len(sik)})</b>\n" +
               ("Dari pola kembar dan siklus pasar." if sik else _alasan_sik(rs, ctx)))
    so += [_blok_sik(i, r, x, tg, led) for i, (r, x, tg) in enumerate(sik, 1)]
    if fib:
        so.append(f"{GARIS}\n📐 <b>1D. SARAN SKILL FIB 0.618-0.65 ({len(fib)})</b>\nGolden pocket + skill tambahan + candle konfirmasi.")
        so += [_blok_fib(i, r, x, tg, led) for i, (r, x, tg) in enumerate(fib, 1)]
    if cad2:
        so.append(f"{GARIS}\n🟠 <b>1E. SARAN CADANGAN 2 ({len(cad2)})</b>\nRapor A/B dan saran mutu A/B yang di DASBOR masih TAHAN.")
        so += [_blok_cad2(i, r, x, tg, led) for i, (r, x, tg) in enumerate(cad2, 1)]
    pos = [it for it in SY.lihat()["open"].values() if it["status"] in ("TERISI", "TP1")]
    if pos and tf == "240":
        peta = {r["symbol"]: r for r in rs}
        out.append(f"{GARIS}\n👤 <b>ANALISA POSISI KAMU ({len(pos)})</b>")
        out += [_blok_posisi_analisa(it, peta.get(it["sym"]) or SY.hasil_robot(it["sym"])) for it in pos]
    if ev:
        out.append(f"{GARIS}\n❌ <b>2. SARAN DIBATALKAN ({len(ev)})</b>\n" + "\n".join(TG.hasil(e, it, syms) for e, it in ev))
    fl = [r for r in rs if (r.get("pasar") or {}).get("in_gp") and r["rapor"] != "D buruk"
          and (not r.get("tk") or r["tk"]["turnover"] >= FP["min_turnover"])]
    if fl:
        fl.sort(key=lambda r: (r["rapor"] not in ("A", "B"), -SK.konfirmasi(r.get("skill"), r["pasar"]["arah"])[0]))
        rows = [f"{GARIS}\n📐 <b>KOIN DI FIB 0.618-0.65 ({len(fl)})</b>"]
        for r in fl[:10]:
            p = r["pasar"]
            searah = "searah bias" if p["zona_searah"] else "melawan bias"
            rows.append(f"{IKON.get(p['arah'], '')} <b>{TG.e(r['symbol'])}</b> rapor {r['rapor']} | bias {p['arah']}, {searah} | "
                        f"konf {SK.konfirmasi(r.get('skill'), p['arah'])[0]}/8\n↳ {TG.e(SY.fib_teks(r))}")
        out.append("\n".join(rows))
    out += _pantauan(rs, sig + [(r, x) for r, x, _ in cad] + [(r, x) for r, x, _ in sik], kode)
    rendah = {}
    for r, x in eks_ab:
        if r["rapor"] not in ("A", "B") and r["symbol"] not in rendah:
            rendah[r["symbol"]] = (r, x)
    if rendah:
        rows = [f"{GARIS}\n⚪ <b>EKSEKUSI DI DASBOR, RAPOR ROBOT RENDAH ({len(rendah)})</b>\n"
                "Bukan saran. Polanya bagus, tapi robot sering rugi di koin ini dalam backtest."]
        urut = sorted(rendah.values(), key=lambda z: (z[1]["mutu"] != "A", -z[0]["wr"]))
        for r, x in urut[:8]:
            rows.append(f"{IKON.get(x['arah'], '')} {TG.e(r['symbol'])} {x['arah']} | mutu {x['mutu']} | "
                        f"{TG.e(x['pola'])}\n↳ rapor robot {r['rapor']} ({r['trd']} trade, WR {r['wr']:.0f}%, PF {r['pf']:.2f})")
        out.append("\n".join(rows))
    if tahan or buang:
        rows = [f"{GARIS}\n⏳ <b>4. HAMPIR, BELUM VALID ({len(tahan) + len(buang)})</b>"]
        for r, s, why in (tahan[:10] + buang[:15]):
            rows.append(f"{IKON.get(s['arah'], '')} {TG.e(r['symbol'])} {s['arah']} | {TG.e(s['pola'])}\n↳ {TG.e(why)}")
        out.append("\n".join(rows))
    out.append(_wr_baris(led))
    ada = bool(sig or cad or sik or fib or cad2)
    if ada:
        btc_l = next((r["btc"] for r in results if r["tf"] == "240"), "")
        so.insert(0, f"🎯 <b>QSE v148 | SINYAL {judul}</b>\nCandle {kode} tutup {_jam(tutup)}\n{TG.e(btc_l)}\n"
                     f"Laporan lengkap ada di pesan 📊 berikutnya.")
        return out, so, True
    return out[:1] + so + out[1:], [], False


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
