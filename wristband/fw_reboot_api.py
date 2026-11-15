"""Reboot the FREE-WILi (clears a jammed UART), turn UART API mode on, then listen.
Keep the BottleNose running its watch firmware the whole time.

    python wristband\\fw_reboot_api.py
"""
import time

import serial


def listen(fw, seconds):
    end, n = time.time() + seconds, 0
    while time.time() < end:
        try:
            data = fw.read(4096)
        except serial.SerialException:
            return n
        for line in data.decode("utf-8", "replace").splitlines():
            if line.startswith("[") and "fcrc" not in line:
                print("  ", line)
                n += 1
    return n


print("1) Rebooting the FREE-WILi...")
try:
    with serial.Serial("COM7", 115200, timeout=0.2) as fw:
        fw.write(b"\x02h\\s\\1\n")  # Hardware > Settings > Software Reset
        listen(fw, 2)
except serial.SerialException:
    pass
print("   waiting 15 s for it to boot...")
time.sleep(15)

with serial.Serial("COM7", 115200, timeout=0.2) as fw:
    listen(fw, 1)
    for attempt in (1, 2):
        print(f"\n2.{attempt}) Toggling UART API mode, listening 25 s (WATCH THE SCREEN)")
        fw.write(b"\x02i\\u\\t\n")
        n = listen(fw, 25)
        if n > 2:
            print(f"\n==> {n} replies: the watch is running the BottleNose's commands. API mode is ON.")
            break
        print(f"   only {n} replies")
print("\nDone. Paste this to Claude and say what the screen showed.")
