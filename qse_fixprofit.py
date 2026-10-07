"""QSE v148 - FIX PROFIT: saringan tambahan di atas vonis DASBOR + buku catatan sinyal live yang belajar dari hasil nyata.
Engine tidak diubah. Lapisan ini hanya memutuskan sinyal mana yang layak dikirim."""
import fcntl
import json
import os
import time
from config import FP, RAPOR_OK, STATE_DIR, MAX_SIGNALS

LEDGER = os.path.join(STATE_DIR, "ledger.json")
ANTRIAN = os.path.join(STATE_DIR, "batal_antrian.json")
TF_MS = 4 * 3600 * 1000


def load():
    try:
        with open(LEDGER) as f:
            return json.load(f)
    except Exception:
        return {"open": {}, "closed": []}


def save(led):
    os.makedirs(STATE_DIR, exist_ok=True)
    led["closed"] = led["closed"][-3000:]
    tmp = LEDGER + ".tmp"
    with open(tmp, "w") as f:
        json.dump(led, f)
    os.replace(tmp, LEDGER)


def _close(led, key, it, res, why, ts):
    it.update(status="SELESAI", result_r=round(res, 3), why=why, closed_ts=ts)
    led["closed"].append(it)
    led["open"].pop(key, None)


def update(led, sym, df):
    """Cek sinyal koin ini dengan candle 1H yang sudah tutup. Return daftar event."""
    ev = []
    ts = df.index.values.astype("datetime64[ms]").astype("int64")
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    for key in [k for k, v in led["open"].items() if v["sym"] == sym]:
        it = led["open"][key]
        L = it["arah"] == "LONG"
        e, sl, t1, t2 = it["entry"], it["sl"], it["tp1"], it["tp2"]
        risk = max(abs(e - sl), 1e-12)
        r1, r2 = abs(t1 - e) / risk, abs(t2 - e) / risk
        start = it.get("start_ts", it["sent_ts"] + TF_MS)
        exp = it.get("exp_ts", start + FP["limit_hours"] * 3600000)
        for i in range(len(ts)):
            if ts[i] < start or ts[i] <= it["last_ts"]:
                continue
            it["last_ts"] = int(ts[i])
            if it["status"] == "MENUNGGU":
                if ts[i] >= exp:
                    _close(led, key, it, 0.0, "tidak terisi %g jam" % FP["limit_hours"], int(ts[i]))
                    it["status"] = "BATAL"
                    ev.append(("BATAL", it))
                    break
                if it["order"] in ("CONDITIONAL STOP", "STOP"):
                    kena = cl[i] > e if L else cl[i] < e
                else:
                    kena = lo[i] <= e if L else hi[i] >= e
                if not kena:
                    continue
                it["status"] = "TERISI"
                it["fill_ts"] = int(ts[i])
                ev.append(("TERISI", it))
            if it["status"] in ("TERISI", "TP1"):
                stop = e if it["status"] == "TP1" else sl
                hs = lo[i] <= stop if L else hi[i] >= stop
                h1 = hi[i] >= t1 if L else lo[i] <= t1
                h2 = hi[i] >= t2 if L else lo[i] <= t2
                if it["status"] == "TERISI":
                    if hs:
                        _close(led, key, it, -1.0, "SL", int(ts[i]))
                        ev.append(("SL", it))
                        break
                    if h1:
                        it["status"] = "TP1"
                        ev.append(("TP1", it))
                        if h2:
                            _close(led, key, it, 0.5 * r1 + 0.5 * r2, "TP2", int(ts[i]))
                            ev.append(("TP2", it))
                            break
                else:
                    if hs:
                        _close(led, key, it, 0.5 * r1, "BE", int(ts[i]))
                        ev.append(("BE", it))
                        break
                    if h2:
                        _close(led, key, it, 0.5 * r1 + 0.5 * r2, "TP2", int(ts[i]))
                        ev.append(("TP2", it))
                        break
    return ev


def recheck(led, res_map, tfs_now):
    """Batalkan LIMIT yang belum terisi bila vonis robot berubah atau peluang terisi turun."""
    ev = []
    for key in list(led["open"].keys()):
        it = led["open"][key]
        tf = it.get("tf", "240")
        if it["status"] != "MENUNGGU" or tf not in tfs_now:
            continue
        r = res_map.get((it["sym"], tf))
        if r is None:
            continue
        if it.get("fib"):
            p = r.get("pasar") or {}
            if not (p.get("in_gp") and p.get("zona_searah") and p.get("arah") == it["arah"]) and \
                    abs((r.get("live") or r["close"]) - it["entry"]) > 1.0 * r["atr"]:
                _close(led, key, it, 0.0, "harga keluar dari golden pocket", r["time"])
                it["status"] = "BATAL"
                ev.append(("BATAL", it))
            continue
        if it.get("siklus"):
            sk = (r.get("siklus") or {}).get("saran")
            if not sk or sk["arah"] != it["arah"]:
                _close(led, key, it, 0.0, "pola kembar tidak lagi searah", r["time"])
                it["status"] = "BATAL"
                ev.append(("BATAL", it))
            continue
        if it.get("cadangan"):
            p = r.get("pasar") or {}
            why = ""
            if r["rapor"] not in ("A", "B"):
                why = "rapor turun ke %s" % r["rapor"]
            elif p.get("arah") != it["arah"]:
                why = "bias robot berbalik ke %s" % p.get("arah")
            elif not p.get("btc_ok"):
                why = "BTC 4J melawan"
            elif not p.get("zona_searah") and abs((r.get("live") or r["close"]) - it["entry"]) > 1.5 * r["atr"]:
                why = "harga keluar dari zona emas"
            if why:
                _close(led, key, it, 0.0, why, r["time"])
                it["status"] = "BATAL"
                ev.append(("BATAL", it))
            continue
        same = [s for s in r["saran"] if s["pola"] == it["pola"] and s["arah"] == it["arah"]]
        ok = [s for s in same if (s["eksekusi"] or (it.get("cad2") and s["mutu"] in ("A", "B"))) and not s["sudah_masuk"]]
        why = ""
        if r["rapor"] not in RAPOR_OK:
            why = "rapor turun ke %s" % r["rapor"]
        elif not ok:
            why = "vonis berubah: " + (same[0]["alasan"] if same else "saran hilang")
        elif ok[0]["p_isi"] < FP["min_fill"] * 0.8:
            why = "peluang terisi turun ke %d%%" % round(ok[0]["p_isi"])
        if why:
            _close(led, key, it, 0.0, why, r["time"])
            it["status"] = "BATAL"
            ev.append(("BATAL", it))
    return ev


def stats(led, days=30):
    lim = (time.time() - days * 86400) * 1000
    cl = [c for c in led["closed"] if c.get("why") in ("SL", "BE", "TP2") and c.get("closed_ts", 0) >= lim]
    n = len(cl)
    win = sum(1 for c in cl if c["result_r"] > 0)
    net = sum(c["result_r"] for c in cl)
    return n, (win / n * 100 if n else 0.0), net


def _muted(led, sym, pola, arah):
    now = time.time() * 1000
    cl = [c for c in led["closed"] if c.get("why") in ("SL", "BE", "TP2")]
    s = [c for c in cl if c["sym"] == sym][-FP["mute_after_sl"]:]
    if len(s) == FP["mute_after_sl"] and all(c["why"] == "SL" for c in s) and \
            now - s[-1]["closed_ts"] < FP["mute_days"] * 86400000:
        return "koin jeda, %d SL live beruntun" % FP["mute_after_sl"]
    p = [c for c in cl if c["pola"] == pola and c["arah"] == arah]
    if len(p) >= FP["pat_min_trades"] and sum(c["result_r"] for c in p) < 0:
        return "pola rugi di trade live"
    return ""


def _p_live(s, gap_atr, kunci="p_tab", awal="p_isi"):
    tab = s.get(kunci)
    if not tab:
        return s[awal]
    grid = [i / 10 for i in range(len(tab))]
    if gap_atr <= 0:
        return 100.0
    if gap_atr >= grid[-1]:
        return tab[-1]
    k = int(gap_atr * 10)
    w = gap_atr * 10 - k
    return tab[k] * (1 - w) + tab[k + 1] * w


def _order_live(r, s):
    """Ubah saran jadi order yang bisa dipasang sekarang, memakai harga live saat pesan dibuat.
    MARKET bila harga di entry, LIMIT bila masih ada gap dan peluang terisi cukup. Return alasan buang atau ''."""
    c = r.get("live") or r["close"]
    a, e = r["atr"], s["entry"]
    L = s["arah"] == "LONG"
    if s["tersentuh"]:
        if s["sl_kena"]:
            return "SL sudah tersentuh"
        if s["tp1_kena"]:
            return "TP1 sudah tercapai"
    if (L and c <= s["sl"]) or ((not L) and c >= s["sl"]):
        return "harga sudah lewat SL"
    if (L and c >= s["tp1"]) or ((not L) and c <= s["tp1"]):
        return "harga sudah lewat TP1"
    gap = (c - e) if L else (e - c)
    if abs(c - e) <= FP["market_atr"] * a:
        risk = abs(c - s["sl"])
        s.update(order="MARKET", entry=c, jarak_atr=0.0, peluang=99, p_isi=100.0, p_isi4=100.0,
                 rr1=abs(s["tp1"] - c) / risk, rr2=abs(s["tp2"] - c) / risk)
        s["ev"] = s["wr"] / 100 * s["rr1"] - (1 - s["wr"] / 100)
        return ""
    if gap > 0:
        if gap > FP["limit_max_atr"] * a:
            return "harga sudah jauh dari entry"
        s["p_isi"] = _p_live(s, gap / a if a > 0 else 99)
        s["p_isi4"] = _p_live(s, gap / a if a > 0 else 99, "p_tab4", "p_isi4")
        s["jarak_atr"] = gap / a if a > 0 else 99
        if s["p_isi"] < FP["min_fill"]:
            return "limit kejauhan, peluang terisi %d%%" % round(s["p_isi"])
        s["order"] = "LIMIT"
        return ""
    if s["breakout"] and FP["kirim_stop"]:
        s["order"] = "STOP"
        return ""
    return "menunggu harga tembus entry" if s["breakout"] else "harga sudah lewat entry"


def select(results, tickers, led):
    """Pilih sinyal yang dikirim. Return (dikirim, jumlah disaring, alasan_saring)."""
    cand, drop = [], {}

    def tolak(why):
        drop[why] = drop.get(why, 0) + 1

    for r in results:
        if r["rapor"] not in RAPOR_OK:
            continue
        tk = tickers.get(r["symbol"], {})
        for s in r["saran"]:
            if not s["eksekusi"] or s["sudah_masuk"] or s["mutu"] not in ("A", "B"):
                continue
            why = _order_live(r, s)
            if why:
                tolak(why)
                s["buang"] = why
                continue
            if FP["on"]:
                risk = max(abs(s["entry"] - s["sl"]), r["tick"])
                fee_r = 2 * FP["fee_pct"] / 100 * s["entry"] / risk
                why = ""
                if FP["skip_tunggu"] and s["order"] == "TUNGGU":
                    why = "order TUNGGU, entry terlalu jauh"
                elif tk and tk["turnover"] < FP["min_turnover"]:
                    why = "volume 24 jam sepi"
                elif tk and tk["spread"] > FP["max_spread_pct"]:
                    why = "spread lebar"
                elif tk and s["arah"] == "LONG" and tk["funding"] > FP["max_funding"]:
                    why = "funding terlalu positif"
                elif tk and s["arah"] == "SHORT" and tk["funding"] < -FP["max_funding"]:
                    why = "funding terlalu negatif"
                elif s["rr1"] - fee_r < FP["min_tp1_net_r"]:
                    why = "TP1 terlalu dekat"
                elif s["ev"] <= 0:
                    why = "ekspektasi pola negatif"
                else:
                    why = _muted(led, r["symbol"], s["pola"], s["arah"])
                if why:
                    tolak(why)
                    s["saring"] = why
                    continue
                s["fee_r"] = fee_r
            else:
                s["fee_r"] = 0.0
            s["prio"] = (s["golden"], r["rapor"] == "A", s["mutu"] == "A", s["order"] == "MARKET",
                         r["tf"] == "240", s["p_isi"], s["net_r"])
            cand.append((r, s))
    cand.sort(key=lambda x: x[1]["prio"], reverse=True)
    out, nd, dipakai = [], {"LONG": 0, "SHORT": 0}, set()
    for r, s in cand:
        if (r["symbol"], r["tf"]) in dipakai:
            s["kalah"] = True          # satu koin satu sinyal per TF, ambil saran terbaik
            continue
        if FP["on"] and nd[s["arah"]] >= FP["max_same_dir"]:
            tolak("batas sinyal searah")
            s["saring"] = "batas sinyal searah"
            continue
        if len(out) >= MAX_SIGNALS:
            tolak("batas jumlah pesan")
            s["saring"] = "batas jumlah pesan"
            continue
        nd[s["arah"]] += 1
        dipakai.add((r["symbol"], r["tf"]))
        out.append((r, s))
    return out, drop


def ganti(led, sel):
    """Batalkan LIMIT lama di koin dan TF yang sama bila saran terbaiknya sekarang berbeda."""
    ev = []
    pilih = {(r["symbol"], r["tf"]): (s["pola"], s["arah"]) for r, s in sel}
    for key in list(led["open"].keys()):
        it = led["open"][key]
        k = (it["sym"], it.get("tf", "240"))
        if it["status"] == "MENUNGGU" and k in pilih and pilih[k] != (it["pola"], it["arah"]):
            _close(led, key, it, 0.0, "diganti saran lebih baik: " + pilih[k][0], it["last_ts"])
            it["status"] = "BATAL"
            ev.append(("BATAL", it))
    return ev


def register(led, r, s):
    """Catat sinyal. Return 'BARU', 'UPDATE', atau '' bila sama dengan yang sudah dikirim."""
    key = "%s|%s|%s|%s" % (r["symbol"], r["tf"], s["pola"], s["arah"])
    old = led["open"].get(key)
    if old and old["status"] != "MENUNGGU":
        return ""
    if old and abs(old["entry"] - s["entry"]) <= r["atr"] * 0.3 and abs(old["sl"] - s["sl"]) <= r["atr"] * 0.3:
        return ""
    start = r["time"] + r["tf_ms"]
    mk = s["order"] == "MARKET"
    led["open"][key] = dict(sym=r["symbol"], tf=r["tf"], pola=s["pola"], arah=s["arah"], entry=s["entry"],
                            sl=s["sl"], tp1=s["tp1"], tp2=s["tp2"], order=s["order"], sent_ts=r["time"],
                            start_ts=start, last_ts=start - 1,
                            exp_ts=start + int((8 if r["tf"] == "60" else FP["limit_hours"]) * 3600000),
                            status="TERISI" if mk else "MENUNGGU", golden=s["golden"], rapor=r["rapor"],
                            fill_ts=start if mk else 0, p_isi=s["p_isi"], cadangan=bool(s.get("cadangan")),
                            siklus=bool(s.get("siklus")), cad2=bool(s.get("cad2")), fib=bool(s.get("fib")))
    return "UPDATE" if old else "BARU"


def batal_manual(led, sym):
    """Hapus semua order koin ini dari catatan (tidak dihitung di hasil live). Return jumlah order."""
    keys = [k for k, v in led["open"].items() if v["sym"] == sym]
    for k in keys:
        it = led["open"].pop(k)
        it.update(status="BATAL", why="batal manual", result_r=0.0, closed_ts=int(time.time() * 1000))
        led["closed"].append(it)
    return len(keys)


def _antrian(fn):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(ANTRIAN + ".lock", "a") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            with open(ANTRIAN) as f:
                data = json.load(f)
        except Exception:
            data = []
        data, hasil = fn(data)
        with open(ANTRIAN + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(ANTRIAN + ".tmp", ANTRIAN)
        return hasil


def antrian_tambah(sym):
    return _antrian(lambda d: (d + [{"sym": sym, "ts": int(time.time() * 1000)}], None))


def antrian_lihat():
    return _antrian(lambda d: (d, [x["sym"] for x in d]))


def antrian_terapkan(led):
    """Terapkan /batal yang masuk saat bot sedang scan. Dipanggil sebelum ledger disimpan."""
    syms = _antrian(lambda d: ([], [x["sym"] for x in d]))
    for s in syms:
        batal_manual(led, s)
    return syms


def peringatan(led, res_map):
    """Posisi sinyal robot yang sudah jalan: kabari sekali bila BTC, bias, atau robot berbalik melawan."""
    pesan = []
    for it in led["open"].values():
        if it["status"] not in ("TERISI", "TP1"):
            continue
        r = res_map.get((it["sym"], it.get("tf", "240")))
        if not r:
            continue
        arah = it["arah"]
        kasus = []
        izin = r.get("izin", "LONG dan SHORT")
        if izin != "LONG dan SHORT" and not izin.startswith(arah):
            kasus.append(("btc", f"BTC 4J berbalik melawan {arah}"))
        ps = r.get("pasar", {})
        if ps.get("arah") and ps["arah"] != arah:
            kasus.append(("bias", f"bias robot berbalik ke {ps['arah']}"))
        if any(s["eksekusi"] and s["arah"] != arah and not s["sudah_masuk"] for s in r["saran"]):
            kasus.append(("lawan", "robot memberi EKSEKUSI arah sebaliknya"))
        al = it.setdefault("alert", [])
        aktif = {k for k, _ in kasus}
        it["alert"] = [a for a in al if a in aktif]
        for k, txt in kasus:
            if k not in it["alert"]:
                it["alert"].append(k)
                pesan.append(f"⚠️ <b>{it['sym']} {arah}</b> sinyal robot {it['pola']}\n↳ {txt}. "
                             f"Pertimbangkan kunci profit atau geser SL ke entry. Jangan buka arah sebaliknya di koin ini.")
    return pesan
