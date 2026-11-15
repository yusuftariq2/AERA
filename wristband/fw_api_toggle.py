"""Toggle UART API mode once (official OneWili command), then listen 40 s.
If the BottleNose's commands start showing up as [g\\s ... Ok] / [g\\p ... Ok], it's ON.
If nothing shows, run this once more (it was ON and this switched it OFF).

    python wristband\\fw_api_toggle.py
"""
import time

import serial

with serial.Serial("COM7", 115200, timeout=0.2) as fw:
    fw.read(4096)
    fw.write(b"\x02i\\u\\t\n")
    print("Toggled UART API mode. Listening 40 s (WATCH THE SCREEN)...")
    end, count = time.time() + 40, 0
    while time.time() < end:
        for line in fw.read(4096).decode("utf-8", "replace").splitlines():
            if line.startswith("[") and "fcrc" not in line:
                print(line)
                count += 1
print(f"\nDone: {count} replies. If the watch updated, API mode is ON. If 0-1 replies, run this once more.")
