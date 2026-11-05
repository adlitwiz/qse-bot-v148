"""QSE v150 - kirim laporan ke Telegram (token & chat id dari environment / GitHub Secrets)."""
import html
import json
import re
import math
import os
import time
import requests

API = "https://api.telegram.org/bot{t}/sendMessage"


def _aksi(metode, **data):
    token, chat_id = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{metode}", data={"chat_id": chat_id, **data}, timeout=15)
        js = r.json()
        if not js.get("ok"):
            print("[WARN] Telegram", metode, js.get("description"))
            return js.get("description") or "gagal"
    except Exception as ex:
        print("[WARN] Telegram", metode, ex)
        return str(ex)
    return None


def pin(mid):
    """Sematkan pesan (bot harus admin grup dengan izin pin). Gagal tidak masalah."""
    if mid:
        return _aksi("pinChatMessage", message_id=mid, disable_notification=True)


def unpin(mid):
    if mid:
        _aksi("unpinChatMessage", message_id=mid)


_RAPAT = ("↳", "━", "SL:", "TP1:", "TP2:", "TP:")


GARIS_PANJANG = "━━━━━━━━━━━━━━━━━━"
JUDUL_BAGIAN = ("💡", "🛠", "⚠️ <b>", "👍", "📏", "🧭", "⏰ <b>", "🔎", "🌐 <b>", "❓", "📐", "🙈", "📋", "🗂",
                "📈 <b>", "🛡", "🎯 <b>", "🟢 <b>", "🔴 <b>", "🟡 <b>", "🔵 <b>", "🟠 <b>", "Rapor A/B lainnya", "<b>", "🔹", "⚪", "📊 <b>", "🤖 <b>", "⛔")


def _rapi_struktur(b):
    """Blok yang sudah tersusun (punya garis panjang): spasi hanya sebelum judul bagian, supaya poin tetap rapat."""
    out, dalam = [], 0
    for ln in b.split("\n"):
        s = ln.strip()
        if (out and out[-1].strip() and not dalam and s.startswith(JUDUL_BAGIAN)
                and not out[-1].strip().startswith("━")):
            out.append("")
        out.append(ln)
        dalam += ln.count("<code>") + ln.count("<pre>") - ln.count("</code>") - ln.count("</pre>")
    return "\n".join(out)


def _rapi(b):
    # semua pesan memakai spasi terstruktur: baris kosong hanya sebelum judul bagian dan sebelum item baru
    # (baris berawalan ikon arah atau nomor tebal), poin dan baris lanjutan tetap rapat
    return _rapi_struktur(b)
    """Beri baris kosong di antara kalimat supaya enak dibaca. Baris lanjutan (↳), garis, dan SL/TP tetap
    menempel ke baris atasnya. Isi <code>/<pre> yang memanjang beberapa baris tidak diubah."""
    out, dalam = [], 0
    for ln in b.split("\n"):
        s = ln.strip()
        if (out and s and out[-1].strip() and not dalam and not s.startswith(_RAPAT)
                and not out[-1].strip().startswith("━")):
            out.append("")
        out.append(ln)
        dalam += ln.count("<code>") + ln.count("<pre>") - ln.count("</code>") - ln.count("</pre>")
        dalam = max(dalam, 0)
    return "\n".join(out)


def _titik_potong(b, maks):
    """Posisi potong untuk blok kepanjangan: baris kosong dulu, lalu batas baris, dan tidak pernah di dalam tag
    <pre>, <code>, <b>, <i> (potongan di dalam tag membuat Telegram menolak format dan pesan jadi teks polos)."""
    def aman(k):
        s = b[:k]
        return all(s.count(f"<{t}>") == s.count(f"</{t}>") for t in ("pre", "code", "b", "i"))
    for sep in ("\n\n", "\n"):
        k = b.rfind(sep, 0, maks)
        while k > 0:
            if aman(k):
                return k
            k = b.rfind(sep, 0, k)
    return maks


def pecah_blok(b, maks=3800):
    """Blok panjang dipotong jadi beberapa bagian yang masing-masing aman dikirim (format HTML utuh)."""
    out = []
    while len(b) > maks:
        k = _titik_potong(b, maks)
        out.append(b[:k].rstrip("\n"))
        b = b[k:].lstrip("\n")
    out.append(b)
    return out


# v150: pesan bot tanpa perintah garis miring. Perintah diganti nama tombol menu dalam kurung siku.
TOMBOL = {
    "sinyal4j": "📡 Sinyal 4J", "sinyal4": "📡 Sinyal 4J", "sinyal": "📡 Sinyal 4J", "status": "📊 Status", "modal": "💼 Modal",
    "cek": "🔎 Cek Koin", "cekdetail": "🔎 Cek Koin", "arah": "🔎 Cek Koin", "kalibrasi": "🔎 Cek Koin",
    "kabar": "📰 Berita", "viral": "📰 Berita", "berita": "📰 Berita", "news": "📰 Berita", "trending": "📰 Berita",
    "entry": "📝 Entry", "tp": "🎯 Kelola Posisi", "tutup": "🎯 Kelola Posisi", "modify": "🎯 Kelola Posisi",
    "modif": "🎯 Kelola Posisi", "sl": "🎯 Kelola Posisi", "slok": "🎯 Kelola Posisi", "tpall": "🎯 Kelola Posisi",
    "slall": "🎯 Kelola Posisi", "tpsemua": "🎯 Kelola Posisi", "slsemua": "🎯 Kelola Posisi", "batal": "🎯 Kelola Posisi",
    "hapus": "🎯 Kelola Posisi", "pindah": "🎯 Kelola Posisi", "ubah": "🎯 Kelola Posisi", "serok": "🎯 Kelola Posisi",
    "milikku": "📊 Status", "punyaku": "📊 Status", "alert": "🔔 Alarm", "tunggu": "🔔 Alarm",
    "pelengkap": "🧩 Jalur Sinyal", "sektor": "🧩 Jalur Sinyal", "jalur": "🧩 Jalur Sinyal", "rekapjalur": "🧩 Jalur Sinyal",
    "ichimoku": "🧩 Jalur Sinyal", "ob": "🧩 Jalur Sinyal", "orderblock": "🧩 Jalur Sinyal", "strategi": "🧩 Jalur Sinyal",
    "strat": "🧩 Jalur Sinyal", "smc": "🧩 Jalur Sinyal", "altseason": "🧩 Jalur Sinyal", "lab": "🧩 Jalur Sinyal",
    "papan": "🧩 Jalur Sinyal", "sinyal1j": "🧩 Jalur Sinyal", "sinyal1": "🧩 Jalur Sinyal", "mode": "🧩 Jalur Sinyal",
    "mingguan": "📈 Laporan", "pekan": "📈 Laporan", "evaluasi": "📈 Laporan", "uji": "📈 Laporan", "laporan4j": "📈 Laporan",
    "laporan": "📈 Laporan", "susul": "📈 Laporan", "tespin": "📈 Laporan", "ujimomentum": "📈 Laporan", "ujimom": "📈 Laporan",
    "tidur": "😴 Mode Tidur", "bangun": "😴 Mode Tidur", "bantuan": "❓ Info", "help": "❓ Info", "start": "❓ Info",
    "menu": "tombol menu bawah", "lalat": "🪰 Otak Lalat", "scan": "📡 Sinyal 4J", "tren": "🔎 Cek Koin",
    "rsi": "🔎 Cek Koin", "ticker": "🔎 Cek Koin",
}
_RX_KATA = re.compile(r"(?i)\b(kirim|ketik|pakai|gunakan|jalankan|panggil)\s+(?=/[a-z])")
_RX_CMD = re.compile(r"(?<![<\w:/.%\d~])/([a-z][a-z0-9_]*)")


def tanpa_slash(teks):
    if not teks or "/" not in teks:
        return teks
    teks = _RX_KATA.sub("tekan ", teks)

    def ganti(m):
        k = m.group(1).lower()
        lb = TOMBOL.get(k)
        return f"[{lb}]" if lb else k
    return _RX_CMD.sub(ganti, teks)


def _markup(teks, markup, terakhir):
    """Tombol per potongan pesan: 📋 Salin Setup untuk blok sinyal di potongan itu, ditambah tombol balasan di potongan terakhir.
    Potongan terakhir tanpa tombol apa pun membawa keyboard menu bawah supaya menu selalu tampil."""
    try:
        import qse_menu as _QM
        salin = _QM.baris_salin(teks)
    except Exception:
        salin = []
    rows = [[{"text": t, "copy_text": {"text": d[2:][:256]}} for t, d in r] for r in salin]
    if markup and markup.get("inline_keyboard"):
        rows += markup["inline_keyboard"]
    elif markup:
        return markup
    if rows:
        return {"inline_keyboard": rows}
    return _keyboard() if terakhir else None


def _keyboard():
    if os.environ.get("QSE_KEYBOARD", "1") == "0":
        return None
    try:
        import qse_menu as _QM
        return _QM.keyboard()
    except Exception:
        return None


def send(blocks, token=None, chat_id=None, markup=None):
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[INFO] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID kosong, pesan hanya dicetak.")
        return
    msgs, cur = [], ""
    pecah = []
    for b in blocks:
        pecah += pecah_blok(_rapi(tanpa_slash(b)))              # blok kepanjangan: potong di baris kosong, di luar tag HTML
    for b in pecah:
        if len(cur) + len(b) + 2 > 3800 and cur:
            msgs.append(cur)
            cur = ""
        cur += b + "\n\n"
    if cur.strip():
        msgs.append(cur)
    ids = []
    for q, m in enumerate(msgs):
        data = {"chat_id": chat_id, "text": m, "parse_mode": "HTML", "disable_web_page_preview": True}
        mk = _markup(m, markup if q == len(msgs) - 1 else None, q == len(msgs) - 1)
        if mk:
            data["reply_markup"] = json.dumps(mk, ensure_ascii=False)
        for k in range(4):
            try:
                r = requests.post(API.format(t=token), data=data, timeout=20)
                if r.status_code == 200:
                    ids.append(r.json().get("result", {}).get("message_id"))
                    break
                if r.status_code == 429:
                    time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
                    continue
                print("[WARN] Telegram", r.status_code, r.text[:200])
                if r.status_code == 400 and "reply_markup" in data and "parse" not in r.text.lower():
                    data.pop("reply_markup", None)            # tombol ditolak: kirim tanpa tombol supaya pesan tidak hilang
                    continue
                if r.status_code == 400 and "parse" in r.text.lower():
                    # tag HTML rusak: kirim ulang sebagai teks polos supaya sinyal tidak hilang
                    import re as _re
                    polos = html.unescape(_re.sub(r"<[^>]+>", "", m))
                    d2 = {k_: v_ for k_, v_ in data.items() if k_ != "parse_mode"}
                    d2["text"] = polos
                    r2 = requests.post(API.format(t=token), data=d2, timeout=20)
                    if r2.status_code == 200:
                        ids.append(r2.json().get("result", {}).get("message_id"))
                break
            except Exception as e:
                print("[WARN] Telegram", e)
                time.sleep(3)
        time.sleep(1.1)
    return ids


def fp(x, tick):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "-"
    d = max(0, int(round(-math.log10(tick)))) if tick > 0 else 4
    if tick > 0:
        x = round(x / tick) * tick
    return f"{x:.{d}f}"


def e(s):
    return html.escape(str(s))


def sinyal(r, s, tag, risk_usdt=0.0):
    t = r["tick"]
    head = ("GOLDEN MOMENT | " if s["golden"] else "") + f"{r['symbol']} {s['arah']}"
    lab = f"Rapor robot {r['rapor']} | Mutu pola {s['mutu']} | EKSEKUSI" + (" | Zona emas" if s["zona_emas"] else "")
    rows = [
        f"➡️ <b>{e(head)}</b>" + (f"  [{tag}]" if tag else ""),
        e(lab),
        f"Pola: {e(s['pola'])} ({e(s['alasan_pola'])})",
        f"Order: {e(s['order'])} | Saran {s['slot']}" + (" | entry pernah tersentuh" if s.get("tersentuh") else ""),
        f"Entry: <code>{fp(s['entry'], t)}</code>",
        f"SL: <code>{fp(s['sl'], t)}</code>",
        f"TP1: <code>{fp(s['tp1'], t)}</code> (+{s['rr1']:.2f}R, tutup separuh)",
        f"TP2: <code>{fp(s['tp2'], t)}</code> (+{s['rr2']:.2f}R, SL geser ke entry)",
        f"Pola {s['win']}TP/{s['loss']}SL | WR {s['wr']:.0f}% | PF {s['pf']:.2f} | {s['net_r']:+.1f}R | E {s['ev']:+.2f}R",
        f"Robot {r['trd']} trade | WR {r['wr']:.0f}% | PF {r['pf']:.2f} | {r['net_r']:+.1f}R",
        f"{e(r['btc'])} naik {r['bProb']:.0f}% | {e(r['regime'])} | jarak {s['jarak_atr']:.1f} ATR | peluang isi {s['peluang']}%",
    ]
    if risk_usdt > 0:
        risk = max(abs(s["entry"] - s["sl"]), t)
        qty = risk_usdt / risk
        rows.append(f"Lot risiko {risk_usdt:g} USDT: {qty:.4g} koin, nilai posisi {qty * s['entry']:,.0f} USDT")
    rows.append(f'<a href="https://www.tradingview.com/chart/?symbol=BYBIT:{r["symbol"]}.P">Buka chart</a> | {e(r["feed"])}')
    return "\n".join(rows)


def hasil(ev, it, tick_map):
    t = tick_map.get(it["sym"], 0.0001)
    tf = "1J" if it.get("tf") == "60" else "4J"
    ikon = {"TERISI": "📥", "TP1": "💰", "TP2": "🏆", "SL": "🛑", "BE": "⚖️", "BATAL": "❌"}.get(ev, "•")
    arti = {"TERISI": "ORDER TERISI", "TP1": "KENA TP1, tutup separuh, SL geser ke entry", "TP2": "KENA TP2, selesai",
            "SL": "KENA SL", "BE": "keluar di entry setelah TP1"}
    txt = (f"saran dibatalkan: {it.get('why', '')}. Kalau LIMIT-nya sudah kamu pasang, batalkan juga"
           if ev == "BATAL" else arti[ev])
    r = f" ({it['result_r']:+.2f}R)" if ev in ("TP2", "SL", "BE") and "result_r" in it else ""
    cad = " | CADANGAN" if it.get("cadangan") else " | SIKLUS" if it.get("siklus") else ""
    return (f"{ikon} <b>{e(it['sym'])} {it['arah']}</b> TF {tf}{cad} | {e(it['pola'])}\n"
            f"↳ {e(txt)}{r} | entry {fp(it['entry'], t)}")

def ambil_perintah(offset, token=None, chat_id=None):
    """Baca perintah /batal, /status, /bantuan dari grup. Return (daftar (perintah, argumen), offset baru)."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = str(chat_id or os.environ.get("TELEGRAM_CHAT_ID") or "")
    if not token or not chat_id:
        return [], offset
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                         params={"offset": offset, "timeout": 0, "allowed_updates": '["message"]'}, timeout=20)
        data = r.json().get("result", [])
    except Exception as ex:
        print("[WARN] getUpdates", ex)
        return [], offset
    out = []
    for u in data:
        offset = max(offset, u["update_id"] + 1)
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != chat_id:
            continue
        txt = (m.get("text") or "").strip()
        if not txt.startswith("/"):
            continue
        parts = txt.split()
        fr = m.get("from") or {}
        out.append((parts[0].split("@")[0].lower(), [p.upper() for p in parts[1:]], str(fr.get("id", "")) or None,
                    " ".join(x for x in (fr.get("first_name"), fr.get("last_name")) if x) or fr.get("username") or ""))
    return out, offset


def ringkas_open(led):
    op = list(led["open"].values())
    if not op:
        return "Order terbuka: tidak ada."
    rows = [f"<b>Order terbuka ({len(op)})</b>"]
    for it in op:
        st = {"MENUNGGU": "menunggu terisi", "TERISI": "posisi jalan", "TP1": "TP1 kena, SL di entry"}.get(it["status"], it["status"])
        rows.append(f"➡️ {e(it['sym'])} {it['arah']} | {e(it['pola'])} | {st}")
    return "\n".join(rows)


BANTUAN = ("Perintah QSE Bot:\n"
           "/batal KOIN = hapus order koin itu dari catatan, contoh /batal DOT\n"
           "/status = daftar order terbuka dan hasil live\n"
           "/bantuan = daftar perintah ini")


def kirim_foto(png, caption="", token=None, chat_id=None):
    """Kirim satu gambar PNG dengan caption HTML (maks 1024 karakter terlihat). Return message_id atau None."""
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not png:
        return None
    for k in range(3):
        try:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto", data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
                              files={"photo": ("sinyal.png", png, "image/png")}, timeout=30)
            if r.status_code == 200:
                return r.json().get("result", {}).get("message_id")
            if r.status_code == 429:
                time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
                continue
            print("[WARN] Telegram foto", r.status_code, r.text[:200])
            return None
        except Exception as ex:
            print("[WARN] Telegram foto", ex)
            time.sleep(3)
    return None


def panjang_terlihat(s):
    import re as _re
    return len(html.unescape(_re.sub(r"<[^>]+>", "", s)))
