"""QSE v148 - kirim laporan ke Telegram (token & chat id dari environment / GitHub Secrets)."""
import html
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
        requests.post(f"https://api.telegram.org/bot{token}/{metode}", data={"chat_id": chat_id, **data}, timeout=15)
    except Exception as ex:
        print("[WARN] Telegram", metode, ex)


def pin(mid):
    """Sematkan pesan (bot harus admin grup dengan izin pin). Gagal tidak masalah."""
    if mid:
        _aksi("pinChatMessage", message_id=mid, disable_notification=True)


def unpin(mid):
    if mid:
        _aksi("unpinChatMessage", message_id=mid)


def send(blocks, token=None, chat_id=None):
    token = token or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[INFO] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID kosong, pesan hanya dicetak.")
        return
    msgs, cur = [], ""
    for b in blocks:
        if len(cur) + len(b) + 2 > 3800 and cur:
            msgs.append(cur)
            cur = ""
        cur += b + "\n\n"
    if cur.strip():
        msgs.append(cur)
    ids = []
    for m in msgs:
        for k in range(4):
            try:
                r = requests.post(API.format(t=token), data={"chat_id": chat_id, "text": m, "parse_mode": "HTML",
                                                             "disable_web_page_preview": True}, timeout=20)
                if r.status_code == 200:
                    ids.append(r.json().get("result", {}).get("message_id"))
                    break
                if r.status_code == 429:
                    time.sleep(int(r.json().get("parameters", {}).get("retry_after", 5)) + 1)
                    continue
                print("[WARN] Telegram", r.status_code, r.text[:200])
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
        out.append((parts[0].split("@")[0].lower(), [p.upper() for p in parts[1:]]))
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
