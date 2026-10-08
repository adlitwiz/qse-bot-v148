"""QSE v148 - MANAJEMEN MODAL.
/modal 1000 risk 1        set modal 1000 USDT, risiko 1% per trade (lot normal = 10 USDT risiko)
/modal rem 3 posisi 3     rem harian -3R dan maksimal 3 posisi sekaligus
/modal                    lihat pengaturan dan kondisi rem sekarang"""
import json
import os
import time
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "modal.json")
BAWAAN = dict(modal=0.0, risk=1.0, rem=3.0, posisi=3, risiko_buka=3.0)


def lihat():
    try:
        with open(FILE) as f:
            return {**BAWAAN, **json.load(f)}
    except Exception:
        return dict(BAWAAN)


def _simpan(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(FILE + ".tmp", FILE)


def _angka(x):
    try:
        return float(x.replace(",", ".").rstrip("%"))
    except ValueError:
        return None


def perintah(args):
    d = lihat()
    i = 0
    ubah = False
    while i < len(args):
        a = args[i]
        nxt = _angka(args[i + 1]) if i + 1 < len(args) else None
        if a in ("RISK", "RISIKO") and nxt:
            d["risk"], i, ubah = nxt, i + 2, True
        elif a == "REM" and nxt:
            d["rem"], i, ubah = nxt, i + 2, True
        elif a in ("POSISI", "MAKS") and nxt:
            d["posisi"], i, ubah = int(nxt), i + 2, True
        elif a in ("BUKA", "RISIKOBUKA") and nxt:
            d["risiko_buka"], i, ubah = nxt, i + 2, True
        elif _angka(a) is not None and i == 0:
            d["modal"], i, ubah = _angka(a), i + 1, True
        else:
            i += 1
    if ubah:
        _simpan(d)
    st = status()
    rows = ["<b>Pengaturan modal</b>",
            f"Modal {d['modal']:,.0f} USDT | risiko {d['risk']:g}% per trade = {lot_normal():,.2f} USDT" if d["modal"] > 0
            else "Modal belum diisi. Contoh: /modal 1000 risk 1",
            f"Rem harian -{d['rem']:g}R | maksimal {d['posisi']} posisi | maksimal risiko terbuka {d['risiko_buka']:g}R",
            "",
            "<b>Kondisi sekarang</b>",
            f"Hasil hari ini {st['hari_ini']:+.2f}R | posisi terbuka {st['n_posisi']} | risiko terbuka {st['risiko']:.2f}R",
            ("⛔ " + st["alasan"]) if st["rem"] else "✅ Boleh entry"]
    return "\n".join(rows)


def lot_normal():
    d = lihat()
    return d["modal"] * d["risk"] / 100 if d["modal"] > 0 else 0.0


def status():
    """Rem harian dan penjaga eksposur dari trade kamu (/entry)."""
    import qse_saya as SY
    d = lihat()
    data = SY.lihat()
    now = int(time.time() * 1000)
    awal = (now + 7 * 3600000) // 86400000 * 86400000 - 7 * 3600000
    hari = sum(c["result_r"] for c in data["closed"] if c.get("why") in ("SL", "BE", "TP2", "TUTUP")
               and c.get("closed_ts", 0) >= awal)
    hari += sum(SY._real(it) for it in data["open"].values() if it["status"] in ("TERISI", "TP1"))
    buka = [it for it in data["open"].values()]
    risiko = 0.0
    for it in buka:
        sl_di_entry = it["status"] == "TP1" and not it.get("sl_manual") or abs(it["sl"] - it["entry"]) < 1e-12
        if not sl_di_entry:
            risiko += SY._sisa(it) * abs(it["entry"] - it["sl"]) / SY._risk0(it)
    alasan = ""
    if hari <= -d["rem"]:
        alasan = f"REM HARIAN: hasil hari ini {hari:+.2f}R, sebaiknya berhenti trading sampai besok"
    elif len(buka) >= d["posisi"]:
        alasan = f"BATAS POSISI: sudah {len(buka)} posisi atau order terbuka (maks {d['posisi']})"
    elif risiko >= d["risiko_buka"]:
        alasan = f"BATAS RISIKO: risiko terbuka {risiko:.1f}R (maks {d['risiko_buka']:g}R)"
    return dict(hari_ini=hari, n_posisi=len(buka), risiko=risiko, rem=bool(alasan), alasan=alasan)


def baris_lot(entry, sl, kali=1.0, lev=None):
    """Satu baris ukuran posisi untuk saran. Kosong bila modal belum diisi."""
    ln = lot_normal()
    if ln <= 0 or entry <= 0 or abs(entry - sl) <= 0:
        return ""
    risk_usdt = ln * kali
    qty = risk_usdt / abs(entry - sl)
    nilai = qty * entry
    teks = f"Ukuran: {kali:g}x lot | risiko {risk_usdt:,.2f} USDT | {qty:,.4g} koin | nilai {nilai:,.0f} USDT"
    if lev:
        teks += f" | margin {nilai / lev:,.1f} USDT di {lev}x"
    return teks
