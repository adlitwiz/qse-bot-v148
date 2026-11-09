"""QSE v150 - menu tombol Telegram. Tombol tetap di bawah kolom ketik (reply keyboard) dan tombol di dalam pesan (inline).
Tombol mengirim teks biasa, listener menerjemahkannya ke perintah lama, jadi semua fungsi tetap sama.
Semua isi per orang: posisi, status, modal, dan catatan milik orang yang menekan tombol (Rifqi atau Adli).
Keyboard bawah ikut di setiap pesan bot (telegram_notify.send), jadi tidak perlu dipanggil ulang."""
import html
import json
import os
import re
import time
import requests
from config import STATE_DIR

PATH = os.path.join(STATE_DIR, "menu.json")
VERSI = 5                 # naikkan kalau tata letak berubah, keyboard dikirim ulang sekali otomatis

UTAMA = [["📊 Status", "📡 Sinyal 4J", "₿ Cek BTC"],
         ["💼 Modal", "📝 Entry", "🎯 Kelola Posisi"],
         ["🔔 Alarm", "🧩 Jalur Sinyal", "🔎 Cek Koin"],
         ["📰 Berita", "📈 Laporan", "🪰 Lalat Abdul"],
         ["🐙 Otak Gurita", "😴 Mode Tidur", "❓ Info"]]
# label -> perintah. None = buka sub menu inline
LABEL = {"📊 Status": "/status", "📡 Sinyal 4J": "/sinyal4j", "₿ Cek BTC": "/cek BTC", "💼 Modal": None, "📝 Entry": None,
         "🎯 Kelola Posisi": None, "🔔 Alarm": None, "🧩 Jalur Sinyal": None, "🔎 Cek Koin": None,
         "📰 Berita": "/berita", "📈 Laporan": None, "🪰 Lalat Abdul": "/lalat", "🐙 Otak Gurita": "/gurita", "😴 Mode Tidur": "/tidur", "❓ Info": "/bantuan"}
# label lama v150 awal, tetap dikenali kalau keyboard lama masih tampil
LAMA = {"🧠 Otak Lalat": "🪰 Lalat Abdul", "🪰 Otak Lalat": "🪰 Lalat Abdul", "Cek BTC": "₿ Cek BTC"}

# sub menu inline: (teks tombol, data maks 64 byte). "c:/perintah" = jalankan, "t:/perintah" = minta ketik (petunjuk di TANYA),
# "m:nama" = sub menu, "y:/perintah" = konfirmasi dulu
SUB = {
    "📝 Entry": ("📝 <b>CATAT ENTRY</b>\nPilih cara catat. Catatan masuk ke milik kamu sendiri.", [
        [("📋 Tempel blok sinyal", "t:/entry")],
        [("🟢 LONG market", "t:/entry LONG MARKET"), ("🔴 SHORT market", "t:/entry SHORT MARKET")],
        [("⏳ LONG limit", "t:/entry LONG LIMIT"), ("⏳ SHORT limit", "t:/entry SHORT LIMIT")]]),
    "🔔 Alarm": ("🔔 <b>ALARM HARGA</b>", [
        [("🔔 Harga sentuh", "t:/alert"), ("⏳ Candle tutup", "t:/tunggu")],
        [("📋 Daftar alarm", "c:/alert"), ("📋 Daftar tunggu", "c:/tunggu")],
        [("🗑️ Hapus semua alarm", "y:/alert HAPUS SEMUA")]]),
    "🧩 Jalur Sinyal": ("🧩 <b>JALUR SINYAL</b>\nPosisi dan hasil tiap jalur.", [
        [("🧩 Pelengkap Sektor", "c:/pelengkap"), ("📈 Ichimoku", "c:/ichimoku")],
        [("⭐ Order Block", "c:/ob"), ("📈 EMA/RSI/SMC", "c:/strategi")],
        [("📒 Jalur live", "c:/jalur"), ("🌈 Altseason", "c:/altseason")],
        [("🧪 Papan Lab", "c:/lab"), ("📡 Sinyal 1J", "c:/sinyal1j")],
        [("🎯 Rencana Sniper S/R", "c:/rencana"), ("🎚️ Mode sinyal", "c:/mode")]]),
    "🔎 Cek Koin": ("🔎 <b>CEK KOIN</b>", [
        [("₿ BTC", "c:/cek BTC"), ("Ξ ETH", "c:/cek ETH"), ("◎ SOL", "c:/cek SOL")],
        [("🧐 Koin lain", "t:/cek"), ("🧭 Arah dan pola", "t:/arah")],
        [("🧪 Kalibrasi DASBOR", "t:/kalibrasi")]]),
    "📈 Laporan": ("📈 <b>LAPORAN</b>", [
        [("📅 Mingguan", "c:/mingguan"), ("📚 Evaluasi trade", "c:/evaluasi")],
        [("🧪 Uji mundur", "c:/uji"), ("📊 Laporan 4J", "c:/laporan4j")],
        [("👤 Catatan milikku", "c:/milikku"), ("📌 Tes pin", "c:/tespin")]]),
}

TANYA = {
    "/entry": "Tempel blok sinyal dari kartu robot (Entry, SL, TP1, TP2), lalu kirim.",
    "/entry LONG MARKET": "Ketik nama koin, contoh: SOL",
    "/entry SHORT MARKET": "Ketik nama koin, contoh: SOL",
    "/entry LONG LIMIT": "Ketik koin dan harga limit, contoh: SOL 150.2",
    "/entry SHORT LIMIT": "Ketik koin dan harga limit, contoh: SOL 160.5",
    "/alert": "Ketik koin dan harga, contoh: BTC 60000",
    "/tunggu": "Ketik koin, atas/bawah, harga, TF. Contoh: SOL atas 150 4j",
    "/cek": "Ketik nama koin, contoh: SOL",
    "/arah": "Ketik nama koin, contoh: SOL",
    "/kalibrasi": "Ketik nama koin, contoh: ETHFI",
    "/modal": "Ketik modal dalam dolar, contoh: 155",
    "/modal ENTRY": "Ketik entry per koin dalam dolar, contoh: 150",
    "/modal LEV": "Ketik leverage, contoh: 10",
    "/modal RISIKO": "Ketik risiko persen modal per trade, contoh: 1",
}


def _st(upd=None):
    try:
        with open(PATH) as f:
            d = json.load(f)
    except Exception:
        d = {}
    if upd is not None:
        d.update(upd)
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(PATH + ".tmp", "w") as f:
            json.dump(d, f)
        os.replace(PATH + ".tmp", PATH)
    return d


def _api(metode, **data):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return {}
    data.setdefault("chat_id", chat)
    data = {k: v for k, v in data.items() if v is not None}
    for k, v in list(data.items()):
        if isinstance(v, (dict, list)):
            data[k] = json.dumps(v, ensure_ascii=False)
    try:
        js = requests.post(f"https://api.telegram.org/bot{token}/{metode}", data=data, timeout=15).json()
        if not js.get("ok") and "reply_markup" in data and metode in ("sendMessage", "editMessageText"):
            print("[WARN] menu", metode, js.get("description"))
            d2 = dict(data); d2["reply_markup"] = json.dumps(_tanpa_salin(json.loads(data["reply_markup"])))
            js = requests.post(f"https://api.telegram.org/bot{token}/{metode}", data=d2, timeout=15).json()
        return js
    except Exception as ex:
        print("[WARN] menu", metode, ex)
        return {}


def keyboard():
    return {"keyboard": [[{"text": t} for t in r] for r in UTAMA], "resize_keyboard": True, "is_persistent": True,
            "input_field_placeholder": "Pilih menu QSE di bawah"}


def _inline(rows):
    out = []
    for r in rows:
        b = []
        for t, d in r:
            if d.startswith("s:"):
                b.append({"text": t, "copy_text": {"text": d[2:][:256]}})
            else:
                b.append({"text": t, "callback_data": d.encode()[:64].decode(errors="ignore")})
        out.append(b)
    return {"inline_keyboard": out}


def _tanpa_salin(mk):
    """Cadangan kalau Telegram lama menolak tombol salin: buang tombol copy_text."""
    rows = [[b for b in r if "copy_text" not in b] for r in mk.get("inline_keyboard", [])]
    rows = [r for r in rows if r]
    return {"inline_keyboard": rows} if rows else keyboard()


def kirim_menu(teks="🤖 <b>QSE v150 | MENU</b>\nSemua fitur ada di tombol bawah. Tombol ikut muncul di setiap pesan robot."):
    js = _api("sendMessage", text=teks, parse_mode="HTML", reply_markup=keyboard())
    if js.get("ok"):
        _st({"versi": VERSI})
    return js.get("ok", False)


def pastikan_menu():
    """Dipanggil saat listener mulai: kirim keyboard sekali per versi tata letak."""
    if _st().get("versi") != VERSI:
        kirim_menu()


# ---------- per orang ----------
def _nama(uid, nama=""):
    if nama:
        return nama
    try:
        import qse_saya as SY
        return str(SY.nama_pengguna(uid))
    except Exception:
        return ""


def _posisi(uid, nama=""):
    """Posisi milik uid. Return list item open."""
    import qse_saya as SY
    try:
        if uid is not None:
            SY.pakai(str(uid), nama)
        return list(SY.lihat()["open"].values())
    except Exception:
        return []
    finally:
        SY.pakai(None)


def _posisi_rows(uid, nama=""):
    """Satu posisi = dua baris: judul (cek koin) lalu 3 tombol aksi. Tidak terpotong di layar HP."""
    rows = []
    for v in _posisi(uid, nama)[:6]:
        s = v.get("sym", "?"); a = str(v.get("arah", "")).upper(); k = s.replace("USDT", "")
        st = {"MENUNGGU": "⏳ antre", "TERISI": "jalan", "TP1": "✅ TP awal kena"}.get(v.get("status"), v.get("status", ""))
        ent = v.get("entry")
        rows.append([(f"{'🟢' if a.startswith('L') else '🔴'} {k} {a} · {st}" + (f" · {ent:g}" if isinstance(ent, (int, float)) else ""),
                      f"c:/cek {k}")])
        if v.get("status") == "MENUNGGU":
            rows.append([("❌ Batal order", f"y:/batal {k}"), ("✏️ Ubah", f"t:/ubah {k}")])
        else:
            rows.append([("💰 TP 50%", f"c:/tp {k} 50%"), ("🛡️ SL ke entry", f"c:/modify {k} SL ENTRY")])
            rows.append([("🏆 TP penuh", f"y:/tp {k} 100%"), ("✋ Tutup", f"y:/tutup {k}")])
    if not rows:
        rows.append([("📭 Belum ada posisi. Lihat sinyal", "c:/sinyal4j")])
    else:
        rows.append([("💰 TP semua", "y:/tpall"), ("🛑 Cut semua", "y:/slall")])
    rows.append([("🔄 Segarkan", "m:🎯 Kelola Posisi"), ("📊 Status", "c:/status")])
    return rows


def _modal_rows():
    return [[("✏️ Isi / ganti modal", "t:/modal")],
            [("⚙️ 3x", "c:/modal LEV 3"), ("5x", "c:/modal LEV 5"), ("10x", "c:/modal LEV 10"), ("20x", "c:/modal LEV 20")],
            [("💵 $50", "c:/modal ENTRY 50"), ("$100", "c:/modal ENTRY 100"), ("$150", "c:/modal ENTRY 150"), ("$200", "c:/modal ENTRY 200")],
            [("🟨 Ringan $50", "c:/modal RINGAN 50"), ("$75", "c:/modal RINGAN 75"), ("$100", "c:/modal RINGAN 100"), ("✍️ Ringan lain", "t:/modal RINGAN")],
            [("✍️ Entry lain", "t:/modal ENTRY"), ("✍️ Leverage lain", "t:/modal LEV"), ("🤖 Entry otomatis", "c:/modal ENTRY 0")],
            [("🎚️ Risiko 0.5%", "c:/modal RISIKO 0.5"), ("1%", "c:/modal RISIKO 1"), ("2%", "c:/modal RISIKO 2")],
            [("📋 Detail slot dan rem", "c:/modal"), ("🔄 Segarkan", "m:💼 Modal")]]


def _modal_teks(uid, nama=""):
    import qse_saya as SY
    import qse_modal as MD
    try:
        if uid is not None:
            SY.pakai(str(uid), nama)
        prof = MD.baris_profil(None)
    except Exception as ex:
        prof = f"Profil tidak terbaca: {ex}"
    finally:
        SY.pakai(None)
    return (f"💼 <b>MODAL · {html.escape(_nama(uid, nama))}</b>\n{prof}\n\n"
            "Leverage dan entry per koin: tekan angka di bawah. Contoh leverage 10 dan entry $150, margin terpakai $15 per koin.\n"
            "🤖 Entry otomatis = besar posisi dihitung dari risiko persen supaya rugi tetap sama.")


def buka_sub(nama, mid=None, uid=None, nm=""):
    nama = LAMA.get(nama, nama)
    if nama == "🎯 Kelola Posisi":
        teks = (f"🎯 <b>KELOLA POSISI · {html.escape(_nama(uid, nm))}</b>\nPosisi milik kamu saja. Tutup dan semua posisi minta konfirmasi.")
        rows = _posisi_rows(uid, nm)
    elif nama == "💼 Modal":
        teks, rows = _modal_teks(uid, nm), _modal_rows()
    elif nama in SUB:
        teks, rows = SUB[nama]
    else:
        return
    if mid:
        js = _api("editMessageText", message_id=mid, text=teks, parse_mode="HTML", reply_markup=_inline(rows))
        if js.get("ok") or "not modified" in str(js.get("description", "")):
            return
    _api("sendMessage", text=teks, parse_mode="HTML", reply_markup=_inline(rows))


# ---------- tombol di bawah balasan perintah ----------
_RX_PRE = re.compile(r"<pre>(.*?)</pre>", re.S)
_RX_JUDUL = re.compile(r"^\s*([A-Z0-9]{2,20}USDT)\s+(LONG|SHORT)", re.M)


def baris_salin(teks, maks=6):
    """Tombol 📋 Salin Setup untuk tiap blok <pre> berjudul 'KOINUSDT LONG/SHORT'. Sekali tekan, teks setup tersalin."""
    rows, sudah = [], set()
    for blk in _RX_PRE.findall(teks or ""):
        isi = html.unescape(re.sub(r"<[^>]+>", "", blk)).strip()
        m = _RX_JUDUL.match(isi)
        if not m or isi in sudah:
            continue
        sudah.add(isi)
        rows.append([(f"📋 Salin Setup {m.group(1).replace('USDT', '')} {m.group(2)}", "s:" + isi)])
        if len(rows) >= maks:
            break
    return rows


def tombol_untuk(cmd, args, isi, uid=None, nama=""):
    """Inline keyboard untuk balasan perintah. None = pakai keyboard menu bawah."""
    k = (args[0] if args else "").replace("USDT", "")
    extra = []          # tombol 📋 Salin Setup ditambah otomatis oleh telegram_notify.send per potongan pesan
    if cmd in ("/status", "/milikku", "/punyaku"):
        extra = _posisi_rows(uid, nama)
    elif cmd in ("/sinyal4j", "/sinyal4", "/sinyal", "/scan", "/rencana"):
        extra = [[("🔄 Segarkan", f"c:{cmd}"), ("📝 Catat entry", "m:📝 Entry"), ("🪰 Pilihan lalat", "c:/lalat")]]
    elif cmd in ("/cek", "/cekdetail", "/arah") and k:
        extra = [[("🔄 Segarkan", f"c:/cek {k}"), ("🧐 Detail", f"c:/cekdetail {k}")], [("🧭 Arah", f"c:/arah {k}"), ("📡 Sinyal 4J", "c:/sinyal4j")]]
    elif cmd == "/modal":
        extra = _modal_rows()
    elif cmd in ("/berita", "/kabar", "/viral", "/news"):
        extra = [[("🔄 Segarkan", "c:/berita"), ("📰 Uji berita ke trade", "c:/beritauji")]]
    elif cmd == "/lalat":
        extra = [[("🔄 Segarkan", "c:/lalat"), ("🧬 Sinapsis lengkap", "c:/lalat SINAPSIS")], [("🍽️ Paksa cari makan", "c:/lalat BURU")],
                 [("⚡ Refleks masuk", "y:/lalat REFLEKS MASUK"), ("⚡ Refleks keluar", "y:/lalat REFLEKS KELUAR")],
                 [("🍽️ Lapar bertingkat nyala/mati", "y:/lalat LAPAR")]]
    elif cmd == "/entry" and "TERCATAT" in (isi or ""):
        import re
        g = re.search(r"([A-Z0-9]+)USDT (LONG|SHORT)", isi)
        try:
            import qse_modal as MD
            p = MD.profil(uid) or {}
        except Exception:
            p = {}
        if g:
            kd, ar = g.group(1), g.group(2)
            u1, u2 = int(p.get("entry") or 150), int(p.get("ringan") or 100)
            extra = [[(f"🟦 Utama {u1} USDT", f"c:/ubah {kd} {ar} USDT {u1}"), (f"🟨 Ringan {u2} USDT", f"c:/ubah {kd} {ar} USDT {u2}")],
                     [("✍️ Isi USDT sendiri", f"t:/ubah {kd} {ar} USDT"), ("⚙️ Leverage", f"t:/ubah {kd} {ar} LEV")],
                     [("🎯 Kelola Posisi", "m:🎯 Kelola Posisi"), ("📊 Status", "c:/status")]]
    elif cmd in ("/tp", "/tutup", "/modify", "/modif", "/sl", "/batal", "/entry", "/ubah", "/serok", "/tpall", "/slall"):
        extra = [[("🎯 Kelola Posisi", "m:🎯 Kelola Posisi"), ("📊 Status", "c:/status")]]
    return _inline(extra) if extra else None


# ---------- terjemah pesan dan tombol ----------
def _cmd(teks):
    p = teks.split()
    return p[0].lower(), p[1:]


def dari_pesan(txt, uid, nama=""):
    """Teks biasa dari grup -> (perintah, argumen) atau None. Tombol tetap, atau jawaban atas permintaan ketik."""
    txt = (txt or "").strip()
    txt = LAMA.get(txt, txt)
    if txt in LABEL:
        _st({"tunggu": {k: v for k, v in _st().get("tunggu", {}).items() if k != str(uid)}})
        if LABEL[txt]:
            return _cmd(LABEL[txt])
        buka_sub(txt, uid=uid, nm=nama)
        return None
    tg = _st().get("tunggu", {}).get(str(uid))
    if tg and time.time() - tg["t"] < 600 and txt and not txt.startswith("/"):
        d = _st(); d["tunggu"].pop(str(uid), None); _st(d)
        c, a = _cmd(tg["cmd"])
        return c, a + txt.split()
    return None


def dari_tombol(cq):
    """callback_query -> (perintah, argumen) atau None. Jawab tombol supaya jam pasir di Telegram hilang."""
    data = cq.get("data") or ""
    fr = cq.get("from") or {}
    uid = str(fr.get("id", ""))
    nm = " ".join(x for x in (fr.get("first_name"), fr.get("last_name")) if x) or fr.get("username") or ""
    mid = (cq.get("message") or {}).get("message_id")
    _api("answerCallbackQuery", callback_query_id=cq.get("id"), chat_id=None)
    jenis, isi = data[:1], data[2:]
    if jenis == "c":
        if mid and isi.split(" ")[0] in ("/tutup", "/tp", "/sl", "/batal", "/tpall", "/slall") and "Yakin" in str((cq.get("message") or {}).get("text", "")):
            _api("deleteMessage", message_id=mid)          # hapus pesan konfirmasi, status dikirim ulang oleh perintah
        return _cmd(isi)
    if jenis == "m":
        buka_sub(isi, mid, uid, nm)
        return None
    if jenis == "t":
        cmd, petunjuk = isi, TANYA.get(isi, "Ketik isinya")
        d = _st(); d.setdefault("tunggu", {})[uid] = {"cmd": cmd, "t": time.time()}; _st(d)
        # tanpa force_reply: force_reply menyembunyikan keyboard menu bawah
        _api("sendMessage", text=f"✍️ <b>{html.escape(nm)}</b>, {petunjuk}\nCukup ketik biasa lalu kirim (berlaku 10 menit).",
             parse_mode="HTML", reply_markup=keyboard())
        return None
    if jenis == "y":
        _api("sendMessage", text=f"Yakin jalankan <b>{html.escape(isi.replace('/', '').upper())}</b> di harga sekarang?", parse_mode="HTML",
             reply_markup=_inline([[("✅ Ya, jalankan", f"c:{isi}"), ("❌ Batal", "x:")]]))
        return None
    if jenis == "x" and mid:
        _api("deleteMessage", message_id=mid)
    return None
