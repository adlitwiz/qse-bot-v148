"""QSE v150 QC 129 - OTAK UMUM: lapisan kecerdasan umum (Claude API) di atas QSE.
QSE tetap otak spesialis: sinyal, lot, SL, dan TP hanya dari aturan yang lolos uji 4 periode. Otak umum TIDAK mengubah aturan,
tidak membuka atau menutup posisi. Tugasnya membaca konteks yang sudah dihitung robot (kartu /cek, vonis, posisi, otopsi) lalu
menjelaskan logika dengan bahasa manusia: mana yang searah, mana yang bertentangan, apa yang perlu diwaspadai.
Aktif kalau ANTHROPIC_API_KEY ada di .env VPS. Model QSE_LLM_MODEL (bawaan claude-sonnet-5-5), maks QSE_LLM_MAKS_HARI panggilan
per hari (bawaan 40). Tanpa kunci: perintah /pikir menjelaskan cara mengaktifkan."""
import html
import json
import os
import re
import time
import requests
from config import STATE_DIR

FILE = os.path.join(STATE_DIR, "otak_umum.json")
API = "https://api.anthropic.com/v1/messages"
SISTEM = ("Kamu Otak Umum robot sinyal kripto QSE v150 milik Qinay. QSE adalah otak spesialis: semua aturan sinyal, lot, SL, dan TP "
          "sudah diuji di data 2022-2026 (latih, uji, 12 bulan, 6 bulan) sesudah biaya. Kamu TIDAK boleh menyuruh melanggar aturan "
          "teruji itu, tidak boleh mengarang angka, dan tidak memberi jaminan profit. Tugasmu: baca konteks dari robot, jelaskan "
          "logikanya dengan bahasa Indonesia sederhana, kalimat aktif dan pendek, tanpa markdown, tanpa tanda bintang, maksimal 5 poin "
          "bernomor. Sebutkan mana yang searah, mana yang bertentangan, risiko utama, dan satu tindakan yang sesuai aturan robot. "
          "Kalau datanya tidak cukup, katakan tidak cukup.")


def kunci():
    return os.environ.get("ANTHROPIC_API_KEY", "").strip()


def aktif():
    return bool(kunci()) and os.environ.get("QSE_OTAK_UMUM", "1") != "0"


def _jatah():
    hari = time.strftime("%Y-%m-%d", time.gmtime(time.time() + 7 * 3600))
    try:
        with open(FILE) as f:
            d = json.load(f)
    except Exception:
        d = {}
    if d.get("hari") != hari:
        d = {"hari": hari, "n": 0}
    return d


def _pakai(d):
    d["n"] = d.get("n", 0) + 1
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(FILE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(FILE + ".tmp", FILE)


def bersih(teks):
    """Buang tag HTML Telegram supaya konteks hemat token."""
    return html.unescape(re.sub(r"<[^>]+>", "", teks or ""))


def tanya(pertanyaan, konteks="", maks_token=700, post=None):
    """Panggil Claude. Return teks jawaban atau None (mati, jatah habis, atau gagal). post untuk tes."""
    if not aktif():
        return None
    d = _jatah()
    if d.get("n", 0) >= int(os.environ.get("QSE_LLM_MAKS_HARI", "40") or 40):
        return None
    body = {"model": os.environ.get("QSE_LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": maks_token, "system": SISTEM,
            "messages": [{"role": "user", "content": (f"KONTEKS DARI ROBOT:\n{bersih(konteks)[:7000]}\n\n" if konteks else "") + pertanyaan}]}
    try:
        r = (post or requests.post)(API, headers={"x-api-key": kunci(), "anthropic-version": "2023-06-01",
                                                  "content-type": "application/json"}, data=json.dumps(body), timeout=60)
        js = r.json()
        if getattr(r, "status_code", 200) != 200:
            print("[WARN] otak umum", js.get("error", js))
            return None
        _pakai(d)
        return "".join(b.get("text", "") for b in js.get("content", []) if b.get("type") == "text").strip() or None
    except Exception as ex:
        print("[WARN] otak umum", ex)
        return None


def _rapi(j):
    j = j.replace("**", "").replace("##", "").replace("#", "")
    return html.escape(j)


def pikir(args):
    """/pikir KOIN [pertanyaan]: robot membaca kartu /cek koin itu dan posisimu, lalu otak umum menjelaskan logikanya."""
    if not kunci():
        return ("🧠 <b>OTAK UMUM belum aktif</b>\nTambahkan baris ANTHROPIC_API_KEY=kunci_kamu di file .env VPS, lalu restart robot. "
                "Kunci dibuat di console.anthropic.com. Biaya dihitung per pemakaian, maksimal 40 panggilan per hari (QSE_LLM_MAKS_HARI).")
    if not args:
        return "Format: /pikir BTC atau /pikir SOL kenapa skornya kecil"
    import qse_saya as SY
    sym = args[0].upper().replace("USDT", "") + "USDT"
    tanyaan = " ".join(args[1:]) or "Bagaimana kondisi koin ini sekarang, dan apa yang sebaiknya saya lakukan sesuai aturan robot?"
    konteks = SY.konsultasi(sym)
    try:
        konteks += "\n\nPOSISI SAYA:\n" + "\n".join(f"{v['sym']} {v['arah']} {v['status']} entry {v['entry']} SL {v['sl']}"
                                                  for v in SY.lihat()["open"].values())
    except Exception as _ex:
        __import__("config").diam("qse_otak_umum.py:100", _ex)
    j = tanya(f"Koin {sym}. Pertanyaan: {tanyaan}", konteks)
    if not j:
        return "🧠 Otak umum tidak menjawab (jatah harian habis atau koneksi gagal). Kartu /cek tetap jadi acuan."
    return f"🧠 <b>OTAK UMUM · {sym}</b>\n{_rapi(j)}\n\n<i>Penjelasan saja. Sinyal, lot, SL, dan TP tetap dari aturan teruji robot.</i>"


def otopsi(prompt_teks):
    """Jawaban singkat untuk prompt otopsi rugi (dipanggil qse_otopsi kalau aktif). Return baris teks atau ''."""
    j = tanya("Ini otopsi trade rugi dari robot. Jelaskan dalam maksimal 4 poin: kenapa kemungkinan rugi, apakah ini rugi wajar "
              "dari sistem yang teruji atau tanda masalah, dan apa yang perlu diperhatikan di trade berikutnya. Jangan usulkan aturan "
              "baru tanpa uji.", prompt_teks, maks_token=500)
    return f"🧠 <b>Otak umum:</b>\n{_rapi(j)}" if j else ""
