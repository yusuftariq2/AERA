"""Confirm: with UART API mode ON, commands sent over the BottleNose wire run on the watch.
(The watch sends its replies to USB, so we read those here to see Ok/Invalid.)

    python wristband\\fw_onewili2.py COM11
"""
import sys
import time

import serial

FW_PORT = "COM7"
BN_PORT = sys.argv[1]


def read_for(port, seconds):
    end, out = time.time() + seconds, b""
    while time.time() < end:
        out += port.read(4096)
    return out


def line(path, args=""):
    return b"\x02" + path.encode() + (b" " + args.encode() if args else b"") + b"\n"


def frames(b):
    return [l for l in b.decode("utf-8", "replace").splitlines() if l.startswith("[") and "fcrc" not in l]


def wire(fw, bn, label, path, args):
    bn.write(b"\n")  # flush any half line on the wire
    time.sleep(0.1)
    read_for(fw, 0.2)
    bn.write(line(path, args))
    got = frames(read_for(fw, 1.5))
    print(f"   WIRE {label}: {got}")
    return any(" Ok " in g for g in got)


with serial.Serial(FW_PORT, 115200, timeout=0.1) as fw, serial.Serial(BN_PORT, 115200, timeout=0.1) as bn:
    read_for(fw, 0.5)
    read_for(bn, 0.2)
    for attempt in (1, 2):
        print(f"\nAttempt {attempt}: wire test (WATCH THE SCREEN)")
        ok = wire(fw, bn, "LED 2 BLUE", "g\\s", "1 0 0 60 8000 0")
        ok = wire(fw, bn, "text", "g\\p", "WIRELESS!") or ok
        if ok:
            print("\n==> SUCCESS: the BottleNose controls the watch over the wire.")
            print("    API mode is now ON. Don't toggle it again.")
            break
        print("   no Ok yet -> toggling API mode ON (i\\u\\t over USB)")
        fw.write(line("i\\u\\t"))
        print("   t ->", frames(read_for(fw, 1.0)))
        time.sleep(0.5)
print("\nDone. Tell Claude: did LED 2 go blue and 'WIRELESS!' show? Paste this output.")
