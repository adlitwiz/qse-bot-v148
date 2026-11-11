"""QSE v174 NYAWA DAN TRAUMA (QC 72, 11 Nov 2026, permintaan user). Robot punya HP (0-100) dan memori trauma per koin x teknik x arah
x kondisi BTC. TP menambah HP dan kepercayaan, SL memukul HP dan dicatat ke memori trauma beserta pola candle penyebabnya.
Sumber: trade kertas robot yang selesai (qse_strat 7 teknik, Ichimoku, Order Block), dibaca ulang tiap menit oleh sinkron().
ATURAN KAPOK (yang memblokir sinyal) dipilih dari uji riset/upgrade/run_v174_rusak.py bagian 3, 30 ribu sinyal 2023-2026:
  kombinasi koin x teknik x arah sesudah 2 SL berturut-turut: -0.025 / +0.077 / +0.189 / +0.028R. TIDAK lebih jelek dari rata-rata
  (-0.011 / +0.121 / +0.167 / +0.011R), jadi TIDAK dipakai untuk memblokir.
  koin x arah (semua teknik) sesudah 3 SL beruntun: -0.187 / -0.082 / +0.189 / -0.169R. Rugi di 3 dari 4 tahun: INI yang dipakai.
Blokir berlaku 14 hari sejak SL ketiga, lepas lebih cepat begitu ada trade menang di koin dan arah itu. Matikan: QSE_KAPOK=0.
Memori disimpan di state/nyawa.json (bukan profil_koin.json, karena file itu ikut tertimpa tiap git pull)."""
import json
import os
import time

from config import STATE_DIR

F = os.path.join(STATE_DIR, "nyawa.json")
HP_MAKS, HP_TP, HP_SL, HP_SL_TANDA = 100.0, 3.0, 8.0, 15.0
KAPOK_N, KAPOK_HARI = 3, 14


def _baca():
    try:
        with open(F) as f:
            d = json.load(f)
    except Exception:
        d = {}
    d.setdefault("hp", HP_MAKS); d.setdefault("kombinasi", {}); d.setdefault("koin", {}); d.setdefault("sudah", []); d.setdefault("log", [])
    return d


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    d["sudah"] = d["sudah"][-3000:]; d["log"] = d["log"][-200:]
    with open(F + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(F + ".tmp", F)


def catat(d, sym, k, arah, R, t=None, btc="", pola="", tanda=False):
    """Satu trade selesai. R > 0.05 = menang (TP), R < -0.5 = SL, di antaranya impas. tanda = SL terjadi sesudah tanda lawan terlihat."""
    t = t or time.time()
    kb = d["kombinasi"].setdefault(f"{sym}|{k}|{arah}|{btc}", dict(n=0, menang=0, sl=0, trauma=0.0, percaya=0.0, pola=[]))
    kn = d["koin"].setdefault(f"{sym}|{arah}", dict(beruntun=0, t_sl=0, n=0))
    kb["n"] += 1; kn["n"] += 1
    if R > 0.05:
        d["hp"] = min(HP_MAKS, d["hp"] + HP_TP)
        kb["menang"] += 1; kb["percaya"] += 1; kb["trauma"] = max(0.0, kb["trauma"] - 1)
        kn["beruntun"] = 0
    elif R < -0.5:
        d["hp"] = max(0.0, d["hp"] - (HP_SL_TANDA if tanda else HP_SL))
        kb["sl"] += 1; kb["trauma"] += 2 if tanda else 1; kb["percaya"] = max(0.0, kb["percaya"] - 1)
        if pola:
            kb["pola"] = (kb["pola"] + [pola])[-5:]
        kn["beruntun"] += 1; kn["t_sl"] = t
    d["log"].append(dict(t=t, sym=sym, k=k, arah=arah, R=round(R, 2), hp=round(d["hp"], 1), pola=pola))


def sinkron():
    """Baca trade kertas robot yang baru selesai dan masukkan ke nyawa. Return jumlah trade baru."""
    import qse_strat as ST
    sumber = []
    for k in ST.STRAT:
        try:
            sumber.append((k, ST.lihat(k).get("closed", [])))
        except Exception:
            pass
    for nm, mod in (("ichimoku", "qse_ichimoku"), ("orderblock", "qse_ob")):
        try:
            sumber.append((nm, __import__(mod).lihat().get("closed", [])))
        except Exception:
            pass
    d = _baca(); sudah = set(d["sudah"]); baru = []
    for k, cl in sumber:
        for it in cl:
            if it.get("R") is None or not it.get("sym") or not it.get("arah"):
                continue
            kunci = f"{k}|{it['sym']}|{it['arah']}|{int(it.get('t', 0))}"
            if kunci in sudah:
                continue
            baru.append((it.get("selesai", 0), kunci, k, it))
    for _, kunci, k, it in sorted(baru, key=lambda z: z[0]):
        bj = it.get("btc_j")
        catat(d, it["sym"], k, it["arah"], float(it["R"]), t=it.get("selesai"), btc=("" if bj is None else "atas" if bj > 0 else "bawah"),
              pola=it.get("pola_lawan", ""), tanda=bool(it.get("pola_lawan")))
        d["sudah"].append(kunci)
    if baru:
        _tulis(d)
    return len(baru)


def hati(d=None):
    """v180 QC 77: suasana hati robot dari HP dan 10 trade terakhir. Dipakai bubble 🧠 untuk mengatur keberanian keputusan.
    Return dict(ikon, nama, hp, sebab, maks) dengan maks = jumlah posisi baru yang disarankan per jam."""
    d = d or _baca()
    hp = d["hp"]
    r = [x["R"] for x in d["log"][-10:]]
    mn = sum(1 for x in r if x > 0.05); kl = sum(1 for x in r if x < -0.5)
    beruntun = 0
    for x in reversed(r):
        if x < -0.5:
            beruntun += 1
        else:
            break
    rk = f"10 trade terakhir {mn} menang, {kl} SL" if r else "belum ada trade tercatat"
    if hp < 50 or beruntun >= 3:
        return dict(ikon="💔", nama="DEFENSIF", hp=hp, maks=1, sebab=f"{rk}" + (f", {beruntun} SL beruntun" if beruntun >= 3 else "") + ". Hanya Kelas Utama, satu posisi baru")
    if hp < 75 or kl > mn:
        return dict(ikon="🧡", nama="WASPADA", hp=hp, maks=1, sebab=f"{rk}. Utamakan Kelas Utama, kelas ringan ukuran kecil")
    if hp >= 90 and mn >= kl + 3:
        return dict(ikon="💚", nama="PERCAYA DIRI", hp=hp, maks=2, sebab=f"{rk}. Aturan ukuran tetap, jangan menambah risiko")
    return dict(ikon="❤️", nama="TENANG", hp=hp, maks=2, sebab=f"{rk}. Ikuti kelas tiap sinyal")


def kapok(sym, arah, now=None):
    """Alasan blokir (teks) kalau koin dan arah ini sedang kapok, atau ''."""
    if os.environ.get("QSE_KAPOK", "1") == "0":
        return ""
    kn = _baca()["koin"].get(f"{sym}|{arah}")
    now = now or time.time()
    if kn and kn["beruntun"] >= KAPOK_N and now - kn["t_sl"] <= KAPOK_HARI * 86400:
        sisa = KAPOK_HARI - (now - kn["t_sl"]) / 86400
        return (f"kapok: {sym.replace('USDT', '')} {arah} sudah {kn['beruntun']} SL beruntun, diblokir {sisa:.0f} hari lagi "
                f"(uji: sesudah 3 SL beruntun rugi di 3 dari 4 tahun)")
    return ""


def baris(sym, k, arah, btc=""):
    """Baris kartu: kepercayaan atau trauma kombinasi ini. Kosong kalau belum ada riwayat live."""
    kb = _baca()["kombinasi"].get(f"{sym}|{k}|{arah}|{btc}")
    if not kb or not kb["n"]:
        return ""
    if kb["trauma"] >= 2:
        pl = f", pola penyebab: {', '.join(kb['pola'][-2:])}" if kb["pola"] else ""
        return f"🩹 Memori trauma: kombinasi ini {kb['sl']} SL dari {kb['n']} trade live{pl}"
    if kb["percaya"] >= 2:
        return f"💚 Kepercayaan: kombinasi ini {kb['menang']} menang dari {kb['n']} trade live"
    return ""


def teks():
    d = _baca(); hp = d["hp"]
    isi = int(round(hp / 10))
    blok = [(k, v) for k, v in d["koin"].items() if v["beruntun"] >= KAPOK_N and time.time() - v["t_sl"] <= KAPOK_HARI * 86400]
    tr = sorted(((k, v) for k, v in d["kombinasi"].items() if v["trauma"] >= 2), key=lambda z: -z[1]["trauma"])[:5]
    pc = sorted(((k, v) for k, v in d["kombinasi"].items() if v["percaya"] >= 2), key=lambda z: -z[1]["percaya"])[:5]
    nm = lambda k: " ".join(x for x in k.replace("USDT", "").split("|") if x)
    rows = [f"❤️ <b>NYAWA ROBOT: {hp:.0f}/100 HP</b>  {'█' * isi}{'░' * (10 - isi)}",
            f"TP menambah {HP_TP:g} HP, SL memotong {HP_SL:g} HP ({HP_SL_TANDA:g} kalau SL datang sesudah tanda lawan terlihat). {len(d['log'])} trade tercatat."]
    rows.append("⛔ Kapok (diblokir): " + (", ".join(f"{nm(k)} ({v['beruntun']} SL beruntun)" for k, v in blok) if blok else "tidak ada"))
    if tr:
        rows.append("🩹 Trauma terbesar: " + ", ".join(f"{nm(k)} ({v['sl']} SL dari {v['n']})" for k, v in tr))
    if pc:
        rows.append("💚 Paling dipercaya: " + ", ".join(f"{nm(k)} ({v['menang']} menang dari {v['n']})" for k, v in pc))
    return "\n".join(rows)
