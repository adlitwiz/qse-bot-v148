"""QSE v148 - kirim laporan ke Telegram (token & chat id dari environment / GitHub Secrets)."""
import html
import math
import os
import time
import requests

API = "https://api.telegram.org/bot{t}/sendMessage"


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
    for m in msgs:
        for k in range(4):
            try:
                r = requests.post(API.format(t=token), data={"chat_id": chat_id, "text": m, "parse_mode": "HTML",
                                                             "disable_web_page_preview": True}, timeout=20)
                if r.status_code == 200:
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
        f"<b>{e(head)}</b>" + (f"  [{tag}]" if tag else ""),
        e(lab),
        f"Pola: {e(s['pola'])} ({e(s['alasan_pola'])})",
        f"Order: {e(s['order'])} | Saran {s['slot']}",
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
    arti = {"TERISI": "ORDER TERISI", "TP1": "KENA TP1, tutup separuh, SL ke entry", "TP2": "KENA TP2, selesai",
            "SL": "KENA SL -1R", "BE": "keluar di entry setelah TP1", "BATAL": "BATAL, 60 candle tidak tersentuh"}[ev]
    r = f" ({it['result_r']:+.2f}R)" if "result_r" in it and ev in ("TP2", "SL", "BE") else ""
    return f"{e(it['sym'])} {it['arah']} {e(it['pola'])}: {arti}{r} | E {fp(it['entry'], t)}"
