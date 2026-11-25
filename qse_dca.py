"""QSE v150 QC 135 - CEKLIS BELI BTC SPOT (DCA Senin dan beli kedua saat koreksi).
Pesan jadwal beli dikirim dengan tombol ✅ per orang dan ✅ semua, lalu disematkan supaya tidak tenggelam. Tiap tombol mengubah pesan
(daftar siapa yang sudah beli). Kalau semua anggota sudah ceklis, pin dilepas. Belum semua sampai 20:00 WIB: pengingat sekali.
Aturan waktu beli tidak berubah (uji 2018-2026: beli rutin mingguan, beli tambahan saat koreksi hasilnya sama dengan hari tetap)."""
import json
import os
import time
import telegram_notify as TG
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "dca.json")


def _baca():
    try:
        with open(FILE) as f:
            return json.load(f)
    except Exception:
        return {"pesan": {}}


def _tulis(d):
    os.makedirs(STATE_DIR, exist_ok=True)
    d["pesan"] = dict(list(d["pesan"].items())[-20:])
    with open(FILE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(FILE + ".tmp", FILE)


def anggota():
    """(uid, nama) semua anggota yang punya catatan robot."""
    import qse_saya as SY
    out = []
    for u in SY.daftar_pengguna():
        if u:
            out.append((str(u), SY.nama_pengguna(u)))
    return out


def tombol(kunci):
    return {"inline_keyboard": [[{"text": "✅ Saya sudah beli", "callback_data": f"d:ok:{kunci}"[:64]},
                                 {"text": "✅ Semua sudah beli", "callback_data": f"d:all:{kunci}"[:64]}]]}


def _isi(p):
    sudah = p.get("sudah", {})
    ang = anggota()
    belum = [nm for u, nm in ang if u not in sudah]
    baris = ("\n\n✅ <b>Sudah beli:</b> " + ", ".join(sudah.values())) if sudah else "\n\n⬜ Belum ada yang ceklis."
    if sudah and belum:
        baris += "\n⬜ <b>Belum:</b> " + ", ".join(belum)
    elif sudah and not belum:
        baris += "\n🎉 Semua sudah beli minggu ini."
    return p["teks"] + baris


def kirim(teks, kunci):
    """Kirim pesan jadwal beli dengan tombol ceklis, sematkan. Return id pesan atau None."""
    d = _baca()
    p = dict(teks=teks, sudah={}, t=time.time(), ingat=False)
    ids = TG.send([_isi(p)], markup=tombol(kunci)) or []
    p["mid"] = ids[0] if ids else None
    if p["mid"]:
        try:
            TG.pin(p["mid"])
        except Exception as ex:
            print("[WARN] dca pin", ex)
    d["pesan"][kunci] = p
    _tulis(d)
    return p["mid"]


def _segarkan(p, kunci):
    if not p.get("mid"):
        return
    try:
        import qse_menu as QM
        selesai = all(u in p.get("sudah", {}) for u, _ in anggota())
        QM._api("editMessageText", message_id=p["mid"], text=_isi(p), parse_mode="HTML",
                reply_markup=json.dumps({"inline_keyboard": []} if selesai else tombol(kunci)))
        if selesai:
            TG.unpin(p["mid"])
    except Exception as ex:
        print("[WARN] dca edit", ex)


def dari_update(cq, uid, nama):
    """Dipanggil listener untuk tombol. Return True kalau tombol milik ceklis DCA."""
    data = (cq or {}).get("data") or ""
    if not data.startswith("d:"):
        return False
    _, jenis, kunci = (data.split(":", 2) + ["", ""])[:3]
    d = _baca(); p = d["pesan"].get(kunci)
    try:
        import qse_menu as QM
        QM._api("answerCallbackQuery", callback_query_id=cq.get("id"), chat_id=None,
                text="Tercatat sudah beli" if jenis == "ok" else "Tercatat semua sudah beli")
    except Exception as _ex:
        __import__("config").diam("qse_dca.py:98", _ex)
    if not p:
        return True
    p.setdefault("sudah", {})
    if jenis == "all":
        for u, nm in anggota():
            p["sudah"][u] = nm
        p["sudah"].setdefault(str(uid), nama or "anggota")
    else:
        p["sudah"][str(uid)] = nama or "anggota"
    d["pesan"][kunci] = p
    _tulis(d)
    _segarkan(p, kunci)
    return True


def ingat(now=None):
    """20:00 WIB: pesan beli hari ini yang belum diceklis semua anggota diingatkan sekali. Return list teks."""
    now = now or time.time()
    if not (13 * 3600 <= now % 86400 <= 14 * 3600):          # 20:00-21:00 WIB
        return []
    d = _baca(); out = []
    for kunci, p in d["pesan"].items():
        if p.get("ingat") or now - p.get("t", 0) > 20 * 3600:
            continue
        belum = [nm for u, nm in anggota() if u not in p.get("sudah", {})]
        if belum:
            p["ingat"] = True
            out.append(f"🪙 <b>PENGINGAT BELI BTC</b>: {', '.join(belum)} belum ceklis beli hari ini. "
                       "Tekan ✅ di pesan yang disematkan kalau sudah beli.")
    if out:
        _tulis(d)
    return out
