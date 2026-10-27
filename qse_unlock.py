"""QSE v148 - JADWAL TOKEN UNLOCK (27 Okt 2026).

Sumber: dataset unlock DefiLlama (gratis, tanpa kunci API): jadwal vesting tiap proyek yang disusun dari dokumen resmi.
Yang dipakai hanya unlock cliff (sekali buka di satu tanggal). Ukurannya dibanding pasokan yang sudah terbuka sehari
sebelumnya (pendekatan pasokan beredar). Peta proyek ke koin dikirim bersama robot (unlock_peta.json, 373 proyek),
proyek baru dipelajari otomatis. Data disegarkan tiap 7 hari di thread sendiri, gagal pun robot tetap jalan.

Uji 2021 - Okt 2026 (riset/berita, 111 koin populasi sinyal, 35 koin punya data DefiLlama):
- 510 unlock cliff >= 1% pasokan terbuka: 7 hari sebelum unlock koin rata-rata -2.9% lawan BTC (median -3.0%, turun di 65%
  kejadian), padahal koin yang sama biasanya -1.1% per 7 hari. 2021-23 -2.4%, 2024-26 -3.3%. Sesudah unlock -1.5% (dekat biasa).
- Sinyal LONG jalur dengan unlock >= 1% dalam 7 hari sesudah entry: 17 trade, PF 0.28 (2021-23 0.45, 2024-26 0.22), total
  -2.5R. LONG lain di koin yang sama PF 1.51 dan 2.81. Ambang 0.5% dan 2% hasilnya searah (PF 0.40 dan 0.46).
- SHORT di saat yang sama PF 1.86 (1.14 dan 2.29), SHORT lain 1.25 dan 1.81: tidak konsisten di 2021-23, jadi info saja.
Dipasang: LONG baru ditahan kalau koin itu unlock >= 1% dalam 7 hari. SHORT dan posisi jalan: info."""
import json
import os
import threading
import time

import requests

from config import STATE_DIR, BYBIT_URL

DIR = os.path.dirname(os.path.abspath(__file__))
PETA = os.path.join(DIR, "unlock_peta.json")
CACHE = os.path.join(STATE_DIR, "unlock.json")
SUMBER = "https://defillama-datasets.llama.fi"
UA = {"User-Agent": "Mozilla/5.0 qse-bot"}
MIN_PCT = 1.0            # unlock >= 1% pasokan terbuka
HARI_TAHAN = 7           # LONG baru ditahan kalau unlock dalam 7 hari
SIMPAN_HARI = 45         # kejadian yang disimpan: 2 hari lalu sampai 45 hari ke depan
SEGAR_HARI = 7
_KUNCI = threading.Lock()
_MEM = {}


def _load():
    try:
        with open(CACHE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(c):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(CACHE + ".tmp", "w") as f:
        json.dump(c, f)
    os.replace(CACHE + ".tmp", CACHE)


def _get(path, timeout=60):
    r = requests.get(f"{SUMBER}/{path}", timeout=timeout, headers=UA)
    r.raise_for_status()
    return r.json()


def _peta():
    """{slug: [gecko_id, SIMBOL, nama]} dari file bawaan plus yang dipelajari."""
    try:
        with open(PETA) as f:
            p = json.load(f)
    except Exception:
        p = {}
    p.update(_load().get("peta_baru", {}))
    return p


def _simbol_bybit(s, ada):
    for c in (f"{s}USDT", f"1000{s}USDT", f"{s}1000USDT", f"10000{s}USDT", f"1000000{s}USDT"):
        if c in ada:
            return c
    return None


def _perp_bybit():
    r = requests.get(BYBIT_URL + "/v5/market/tickers", params={"category": "linear"}, timeout=20)
    return {x["symbol"] for x in r.json().get("result", {}).get("list", []) if x["symbol"].endswith("USDT")}


def kejadian(d, dari, sampai):
    """Unlock cliff dari satu dataset DefiLlama dalam rentang waktu (detik). Return list (t, pct, token, kategori)."""
    tot = {}
    for a in (d.get("documentedData") or {}).get("data", []):
        for p in a.get("data", []):
            tot[p["timestamp"]] = tot.get(p["timestamp"], 0.0) + (p.get("unlocked") or 0.0)
    if not tot:
        return []
    ts = sorted(tot)
    out = []
    for e in (d.get("metadata") or {}).get("unlockEvents", []):
        t = e.get("timestamp") or 0
        if not (dari <= t <= sampai):
            continue
        cl = e.get("cliffAllocations") or []
        jml = sum(c.get("amount") or 0 for c in cl)
        if jml <= 0:
            continue
        acuan = t - 86400                       # pasokan terbuka sehari sebelum unlock
        lo, hi = 0, len(ts) - 1
        k = -1
        while lo <= hi:
            m = (lo + hi) // 2
            if ts[m] <= acuan:
                k, lo = m, m + 1
            else:
                hi = m - 1
        if k < 0 or tot[ts[k]] <= 0:
            continue
        kat = sorted({c.get("category") or "" for c in cl} - {""})
        out.append((int(t), round(jml / tot[ts[k]] * 100, 2), jml, ",".join(kat)))
    return out


def segarkan(paksa=False, log=print):
    """Unduh jadwal unlock proyek yang koinnya ada di perpetual Bybit. Paling sering tiap 7 hari. Return jumlah koin."""
    if not _KUNCI.acquire(blocking=False):
        return 0
    try:
        c = _load()
        now = time.time()
        if not paksa and now - c.get("ts", 0) < SEGAR_HARI * 86400 - 3600:
            return len(c.get("ev", {}))
        peta = _peta()
        baru = dict(c.get("peta_baru", {}))
        try:
            daftar = _get("emissionsProtocolsList")
        except Exception as ex:
            log(f"[WARN] unlock daftar: {ex}")
            daftar = list(peta)
        cg = None
        for slug in [s for s in daftar if s not in peta][:40]:          # proyek baru: pelajari koinnya sekali
            try:
                d = _get(f"emissions/{slug}")
                tok = (d.get("metadata") or {}).get("token") or ""
                gid = d.get("gecko_id") or (tok.split("coingecko:")[-1] if tok.startswith("coingecko:") else None)
                if gid and cg is None:
                    r = requests.get("https://api.coingecko.com/api/v3/coins/list", timeout=60, headers=UA)
                    cg = {x["id"]: x["symbol"].upper() for x in r.json()}
                baru[slug] = [gid, (cg or {}).get(gid or ""), d.get("name")]
                time.sleep(0.3)
            except Exception as ex:
                log(f"[WARN] unlock proyek baru {slug}: {ex}")
        peta.update(baru)
        try:
            ada = _perp_bybit()
        except Exception as ex:
            log(f"[WARN] unlock daftar koin Bybit: {ex}")
            return len(c.get("ev", {}))
        per_sym = {}
        for slug, v in peta.items():
            sb = _simbol_bybit((v[1] or "").upper(), ada) if v and v[1] else None
            if sb:
                per_sym.setdefault(sb, set()).add(v[0])
        ganda = {s for s, g in per_sym.items() if len(g) > 1}           # simbol sama, proyek beda: dilewati supaya tidak salah koin
        ev, n_ok = {}, 0
        for slug, v in peta.items():
            sb = _simbol_bybit((v[1] or "").upper(), ada) if v and v[1] else None
            if not sb or sb in ganda:
                continue
            try:
                d = _get(f"emissions/{slug}")
                for t, pct, jml, kat in kejadian(d, now - 2 * 86400, now + SIMPAN_HARI * 86400):
                    if pct >= 0.5:
                        ev.setdefault(sb, []).append([t, pct, jml, v[2] or slug, kat])
                n_ok += 1
                time.sleep(0.3)
            except Exception as ex:
                log(f"[WARN] unlock {slug}: {ex}")
        if n_ok == 0:
            return len(c.get("ev", {}))
        for s in ev:
            ev[s].sort()
        c.update(ts=now, ev=ev, peta_baru=baru, n_proyek=n_ok)
        _save(c)
        _MEM.clear()
        log(f"[UNLOCK] jadwal disegarkan: {n_ok} proyek, {len(ev)} koin punya unlock dalam {SIMPAN_HARI} hari")
        return len(ev)
    finally:
        _KUNCI.release()


def segarkan_latar():
    """Dipanggil berkala: segarkan di thread sendiri kalau data sudah 7 hari."""
    if time.time() - _load().get("ts", 0) >= SEGAR_HARI * 86400 - 3600:
        threading.Thread(target=segarkan, daemon=True).start()


def _ev():
    now = time.time()
    if now - _MEM.get("t", 0) > 300:
        _MEM.update(t=now, ev=_load().get("ev", {}))
    return _MEM.get("ev", {})


def dekat(sym, hari=HARI_TAHAN, min_pct=MIN_PCT, now=None):
    """Unlock >= min_pct dalam `hari` ke depan. Return list dict(t, pct, token, nama) urut waktu."""
    now = now or time.time()
    return [dict(t=e[0], pct=e[1], token=e[2], nama=e[3]) for e in _ev().get(sym, [])
            if now < e[0] <= now + hari * 86400 and e[1] >= min_pct]


def _jam(t):
    return time.strftime("%d/%m %H:%M WIB", time.gmtime(t + 7 * 3600))


def _sisa(t, now):
    j = (t - now) / 3600
    return f"{j:.0f} jam lagi" if j < 48 else f"{j / 24:.0f} hari lagi"


def tolak_long(sym, arah, now=None):
    """LONG baru ditahan kalau unlock >= 1% dalam 7 hari. Return alasan atau ''."""
    if arah != "LONG":
        return ""
    try:
        u = dekat(sym, now=now)
    except Exception:
        return ""
    if not u:
        return ""
    e = u[0]
    return (f"unlock {e['pct']:.1f}% pasokan {_jam(e['t'])}, LONG 7 hari sebelum unlock di uji 2021-2026 PF 0.28")


def teks(sym, arah=None, now=None):
    """Baris info unlock untuk kartu sinyal dan /status, atau ''."""
    now = now or time.time()
    try:
        u = dekat(sym, now=now)
    except Exception:
        return ""
    if not u:
        return ""
    e = u[0]
    dasar = (f"🔓 <b>UNLOCK {e['pct']:.1f}% pasokan {_jam(e['t'])}</b> ({_sisa(e['t'], now)}). Uji 2021-2026: 7 hari sebelum "
             f"unlock koin rata-rata -3% lawan BTC")
    if arah == "LONG":
        return dasar + ". LONG di saat ini PF 0.28, ikuti SL dan jangan tambah posisi"
    if arah == "SHORT":
        return dasar + ", searah SHORT ini"
    return dasar


def kalender(hari=7, min_pct=MIN_PCT, now=None):
    """Semua unlock >= min_pct dalam `hari` ke depan untuk koin perpetual Bybit. Return list dict urut waktu."""
    now = now or time.time()
    out = []
    for s, L in _ev().items():
        for e in L:
            if now < e[0] <= now + hari * 86400 and e[1] >= min_pct:
                out.append(dict(sym=s, t=e[0], pct=e[1], token=e[2], nama=e[3]))
    return sorted(out, key=lambda x: x["t"])


def umur_data():
    """Jam sejak data terakhir disegarkan, atau None."""
    ts = _load().get("ts")
    return (time.time() - ts) / 3600 if ts else None
