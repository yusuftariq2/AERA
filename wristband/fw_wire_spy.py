"""Turn on UART read events and print exactly what bytes the BottleNose is sending to the watch.

    python wristband\\fw_wire_spy.py
"""
import time

import serial


def decode_event(line):
    # [*uart1 <ts> <seq> 48 45 4c ... 1]  -> bytes
    parts = line.strip("[]").split()
    hexes = [p for p in parts[3:-1] if len(p) == 2]
    try:
        return bytes(int(h, 16) for h in hexes)
    except ValueError:
        return b""


with serial.Serial("COM7", 115200, timeout=0.2) as fw:
    fw.read(4096)
    fw.write(b"\x02i\\u\\r\n")
    print("UART read events toggled. Listening 15 s...")
    end, events = time.time() + 15, 0
    while time.time() < end:
        for line in fw.read(4096).decode("utf-8", "replace").splitlines():
            if "fcrc" in line or not line.startswith("["):
                continue
            if line.startswith("[*uart"):
                events += 1
                print("WIRE BYTES:", decode_event(line))
            else:
                print(line)
    if events == 0:
        print("\nNo wire bytes seen. Toggling read events once more and listening 10 s...")
        fw.write(b"\x02i\\u\\r\n")
        end = time.time() + 10
        while time.time() < end:
            for line in fw.read(4096).decode("utf-8", "replace").splitlines():
                if line.startswith("[*uart"):
                    events += 1
                    print("WIRE BYTES:", decode_event(line))
                elif line.startswith("[") and "fcrc" not in line:
                    print(line)
print(f"\nDone: {events} wire events. Paste this to Claude.")
