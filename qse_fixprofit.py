"""QSE v148 - FIX PROFIT: saringan tambahan di atas vonis DASBOR + buku catatan sinyal live yang belajar dari hasil nyata.
Engine tidak diubah. Lapisan ini hanya memutuskan sinyal mana yang layak dikirim."""
import json
import os
import time
from config import FP, RAPOR_OK, STATE_DIR, MAX_SIGNALS

LEDGER = os.path.join(STATE_DIR, "ledger.json")
TF_MS = 4 * 3600 * 1000
EXP_BARS = 60


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
    """Cek sinyal lama koin ini dengan candle 4H yang sudah tutup. Return daftar event hasil."""
    ev = []
    ts = df.index.values.astype("datetime64[ms]").astype("int64")
    hi, lo, cl = df["high"].values, df["low"].values, df["close"].values
    for key in [k for k, v in led["open"].items() if v["sym"] == sym]:
        it = led["open"][key]
        L = it["arah"] == "LONG"
        e, sl, t1, t2 = it["entry"], it["sl"], it["tp1"], it["tp2"]
        risk = max(abs(e - sl), 1e-12)
        r1, r2 = abs(t1 - e) / risk, abs(t2 - e) / risk
        for i in range(len(ts)):
            if ts[i] <= it["last_ts"]:
                continue
            it["last_ts"] = int(ts[i])
            if it["status"] == "MENUNGGU":
                if (ts[i] - it["sent_ts"]) / TF_MS > EXP_BARS:
                    it.update(status="BATAL", why="kadaluarsa", closed_ts=int(ts[i]), result_r=0.0)
                    led["closed"].append(it)
                    led["open"].pop(key, None)
                    ev.append(("BATAL", it))
                    break
                if it["order"] == "CONDITIONAL STOP":
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
            if not s["eksekusi"] or s["sudah_masuk"]:
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
                    why = "TP1 habis dimakan fee"
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
            tier = 3 if s["golden"] else 2 if r["rapor"] == "A" else 1
            s["prio"] = (tier, s["mutu"] == "A", s["zona_emas"], s["peluang"], s["net_r"])
            cand.append((r, s))
    cand.sort(key=lambda x: x[1]["prio"], reverse=True)
    out, nd = [], {"LONG": 0, "SHORT": 0}
    for r, s in cand:
        if FP["on"] and nd[s["arah"]] >= FP["max_same_dir"]:
            tolak("batas sinyal searah")
            s["saring"] = "batas sinyal searah"
            continue
        if len(out) >= MAX_SIGNALS:
            tolak("batas jumlah pesan")
            s["saring"] = "batas jumlah pesan"
            continue
        nd[s["arah"]] += 1
        out.append((r, s))
    return out, drop


def register(led, r, s):
    """Catat sinyal. Return 'BARU', 'UPDATE', atau '' bila sama persis dengan yang sudah dikirim."""
    key = "%s|%s|%s" % (r["symbol"], s["pola"], s["arah"])
    old = led["open"].get(key)
    if old and old["status"] != "MENUNGGU":
        return ""
    if old and abs(old["entry"] - s["entry"]) <= r["atr"] * 0.3 and abs(old["sl"] - s["sl"]) <= r["atr"] * 0.3:
        return ""
    led["open"][key] = dict(sym=r["symbol"], pola=s["pola"], arah=s["arah"], entry=s["entry"], sl=s["sl"],
                            tp1=s["tp1"], tp2=s["tp2"], order=s["order"], sent_ts=r["time"], last_ts=r["time"],
                            status="TERISI" if s["order"] == "MARKET" else "MENUNGGU", golden=s["golden"],
                            rapor=r["rapor"], fill_ts=r["time"] if s["order"] == "MARKET" else 0)
    return "UPDATE" if old else "BARU"
