"""Just hold the FREE-WILi's USB port open and print what it says, for 30 seconds.
Tests whether wire (BottleNose) commands only run while a computer has the port open.

    python wristband\\fw_listen.py
"""
import time

import serial

with serial.Serial("COM7", 115200, timeout=0.2) as fw:
    end = time.time() + 30
    while time.time() < end:
        data = fw.read(4096)
        for line in data.decode("utf-8", "replace").splitlines():
            if line.startswith("[") and "fcrc" not in line:
                print(line)
print("Done. Did the watch screen change while this ran?")
