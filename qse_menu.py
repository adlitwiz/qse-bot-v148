"""QSE v150 - menu tombol Telegram. Tombol tetap di bawah kolom ketik (reply keyboard) dan tombol di dalam pesan (inline).
Tombol mengirim teks biasa, listener menerjemahkannya ke perintah lama, jadi semua fungsi tetap sama.
Perintah garis miring masih jalan untuk yang sudah hafal. Bot harus admin grup (sudah, untuk pin) supaya teks tombol terbaca."""
import json
import os
import time
import requests
from config import STATE_DIR

PATH = os.path.join(STATE_DIR, "menu.json")
VERSI = 3                 # naikkan kalau tata letak berubah, keyboard dikirim ulang sekali otomatis

# tombol tetap: label -> perintah. None = buka sub menu inline
UTAMA = [["📊 Status", "📡 Sinyal 4J", "💼 Modal"],
         ["📝 Entry", "🎯 Kelola Posisi", "🔔 Alarm"],
         ["🧩 Jalur Sinyal", "🔎 Cek Koin", "📰 Berita"],
         ["📈 Laporan", "😴 Mode Tidur", "❓ Info"]]
LABEL = {"📊 Status": "/status", "📡 Sinyal 4J": "/sinyal4j", "💼 Modal": "/modal", "📝 Entry": None,
         "🎯 Kelola Posisi": None, "🔔 Alarm": None, "🧩 Jalur Sinyal": None, "🔎 Cek Koin": None,
         "📰 Berita": None, "📈 Laporan": None, "😴 Mode Tidur": "/tidur", "❓ Info": "/bantuan"}

# sub menu inline: (teks tombol, data maks 64 byte). "c:/perintah" = jalankan, "t:/perintah" = minta ketik (petunjuk di TANYA), "m:nama" = sub menu, "y:" = konfirmasi
SUB = {
    "📝 Entry": ("📝 <b>CATAT ENTRY</b>\nPilih cara catat.", [
        [("📋 Tempel blok sinyal", "t:/entry")],
        [("🟢 LONG market", "t:/entry LONG MARKET"),
         ("🔴 SHORT market", "t:/entry SHORT MARKET")],
        [("⏳ LONG limit", "t:/entry LONG LIMIT"),
         ("⏳ SHORT limit", "t:/entry SHORT LIMIT")]]),
    "🔔 Alarm": ("🔔 <b>ALARM HARGA</b>", [
        [("🔔 Harga sentuh", "t:/alert"),
         ("⏳ Candle tutup", "t:/tunggu")],
        [("📋 Daftar alarm", "c:/alert"), ("📋 Daftar tunggu", "c:/tunggu")],
        [("🗑️ Hapus semua alarm", "c:/alert HAPUS SEMUA")]]),
    "🧩 Jalur Sinyal": ("🧩 <b>JALUR SINYAL</b>\nPosisi dan hasil tiap jalur.", [
        [("🧩 Pelengkap Sektor", "c:/pelengkap"), ("📈 Ichimoku", "c:/ichimoku")],
        [("⭐ Order Block", "c:/ob"), ("📈 Strategi EMA/RSI/SMC", "c:/strategi")],
        [("📒 Jalur live", "c:/jalur"), ("🌈 Altseason", "c:/altseason")],
        [("🧪 Papan Lab", "c:/lab"), ("📡 Sinyal 1J", "c:/sinyal1j")],
        [("🎚️ Mode sinyal", "c:/mode")]]),
    "🔎 Cek Koin": ("🔎 <b>CEK KOIN</b>", [
        [("🧐 Analisa lengkap", "t:/cek"),
         ("🧭 Arah dan pola", "t:/arah")],
        [("🧪 Kalibrasi DASBOR", "t:/kalibrasi")]]),
    "📰 Berita": ("📰 <b>BERITA</b>", [
        [("📰 Kabar terbaru", "c:/kabar"), ("🔥 Viral 6 jam", "c:/viral 6")],
        [("📰 Uji news ke trade", "c:/berita")]]),
    "📈 Laporan": ("📈 <b>LAPORAN</b>", [
        [("📅 Mingguan", "c:/mingguan"), ("📚 Evaluasi trade", "c:/evaluasi")],
        [("🧪 Uji mundur", "c:/uji"), ("📊 Laporan 4J susulan", "c:/laporan4j")],
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
    for k, v in list(data.items()):
        if isinstance(v, (dict, list)):
            data[k] = json.dumps(v, ensure_ascii=False)
    try:
        return requests.post(f"https://api.telegram.org/bot{token}/{metode}", data=data, timeout=15).json()
    except Exception as ex:
        print("[WARN] menu", metode, ex)
        return {}


def keyboard():
    return {"keyboard": [[{"text": t} for t in r] for r in UTAMA], "resize_keyboard": True, "is_persistent": True,
            "input_field_placeholder": "Pilih menu QSE di bawah"}


def _inline(rows):
    return {"inline_keyboard": [[{"text": t, "callback_data": d[:64]} for t, d in r] for r in rows]}


def kirim_menu(teks="🤖 <b>QSE v150 | MENU</b>\nSemua fitur ada di tombol bawah. Tidak perlu ketik perintah garis miring."):
    js = _api("sendMessage", text=teks, parse_mode="HTML", reply_markup=keyboard())
    if js.get("ok"):
        _st({"versi": VERSI})
    return js.get("ok", False)


def pastikan_menu():
    """Dipanggil saat listener mulai: kirim keyboard sekali per versi tata letak."""
    if _st().get("versi") != VERSI:
        kirim_menu()


def _posisi_rows():
    import qse_saya as SY
    rows = []
    try:
        op = SY.lihat()["open"].values()
    except Exception:
        op = []
    for v in list(op)[:8]:
        s = v.get("sym", "?"); a = str(v.get("arah", "")).upper()[:5]; k = s.replace("USDT", "")
        rows.append([(f"{'🟢' if a.startswith('L') else '🔴'} {k}", f"c:/cek {k}"), ("💰 TP 50%", f"c:/tp {k} 50%"),
                     ("🛡️ SL entry", f"c:/modify {k} SL ENTRY"), ("✋ Tutup", f"y:/tutup {k}")])
    rows.append([("💰 TP semua", "y:/tpall"), ("🛑 Cut semua", "y:/slall"), ("🔄 Segarkan", "m:🎯 Kelola Posisi")])
    return rows


def buka_sub(nama, mid=None):
    if nama == "🎯 Kelola Posisi":
        teks, rows = "🎯 <b>KELOLA POSISI</b>\nTombol per posisi kamu. Tutup dan semua posisi minta konfirmasi.", _posisi_rows()
    elif nama in SUB:
        teks, rows = SUB[nama]
    else:
        return
    if mid:
        _api("editMessageText", message_id=mid, text=teks, parse_mode="HTML", reply_markup=_inline(rows))
    else:
        _api("sendMessage", text=teks, parse_mode="HTML", reply_markup=_inline(rows))


def _cmd(teks):
    p = teks.split()
    return p[0].lower(), p[1:]


def dari_pesan(txt, uid, reply_to=None):
    """Teks biasa dari grup -> (perintah, argumen) atau None. Tombol tetap, atau jawaban atas permintaan ketik."""
    txt = (txt or "").strip()
    if txt in LABEL:
        _st({"tunggu": {k: v for k, v in _st().get("tunggu", {}).items() if k != str(uid)}})
        if LABEL[txt]:
            return _cmd(LABEL[txt])
        buka_sub(txt)
        return None
    tg = _st().get("tunggu", {}).get(str(uid))
    if tg and time.time() - tg["t"] < 600 and txt and not txt.startswith("/"):
        d = _st(); d["tunggu"].pop(str(uid), None); _st(d)
        c, a = _cmd(tg["cmd"])
        return c, a + txt.split()
    return None


def dari_tombol(cq):
    """callback_query -> (perintah, argumen) atau None. Jawab tombol supaya jam pasir di Telegram hilang."""
    data = cq.get("data") or ""; uid = str((cq.get("from") or {}).get("id", ""))
    mid = (cq.get("message") or {}).get("message_id")
    _api("answerCallbackQuery", callback_query_id=cq.get("id"), chat_id=None)
    jenis, isi = data[:1], data[2:]
    if jenis == "c":
        return _cmd(isi)
    if jenis == "m":
        buka_sub(isi, mid)
        return None
    if jenis == "t":
        cmd, petunjuk = isi, TANYA.get(isi, "Ketik isinya")
        d = _st(); d.setdefault("tunggu", {})[uid] = {"cmd": cmd, "t": time.time()}; _st(d)
        _api("sendMessage", text=f"✍️ {petunjuk}\n(berlaku 10 menit)", reply_markup={"force_reply": True, "selective": False})
        return None
    if jenis == "y":
        _api("sendMessage", text=f"Yakin jalankan <b>{isi.replace('/', '').upper()}</b> di harga sekarang?", parse_mode="HTML",
             reply_markup=_inline([[("✅ Ya, jalankan", f"c:{isi}"), ("❌ Batal", "x:")]]))
        return None
    if jenis == "x" and mid:
        _api("deleteMessage", message_id=mid)
    return None
