"""Ekspor data candle untuk kalibrasi di Claude. Pakai: python ekspor_data.py NOMUSDT ETHFIUSDT PENDLEUSDT
Hasil: ~/qse_kalibrasi.zip (candle 4J, 1J, D, W koin itu + BTC), kirim file ini ke Claude."""
import os
import sys
import zipfile
import bybit_fetch as B
from config import TV_BARS

out = os.path.expanduser("~/qse_kalibrasi.zip")
syms = [s.upper() if s.upper().endswith("USDT") else s.upper() + "USDT" for s in sys.argv[1:]] or ["NOMUSDT", "ETHFIUSDT"]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for sym in syms + ["BTCUSDT"]:
        for iv, n in (("240", TV_BARS), ("60", TV_BARS * 4 + 400), ("D", 1500), ("W", 400)):
            df = B.get_klines(sym, iv, n, closed_only=False)
            z.writestr(f"{sym}_{iv}.csv", df.to_csv())
            print(sym, iv, len(df), "candle")
print("Selesai:", out)
