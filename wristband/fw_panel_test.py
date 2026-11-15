"""Build a persistent watch screen (panel + big text + bar graph) over USB with the
official OneWili commands, then update it. If this stays on screen, the BottleNose
can send the exact same lines over the wire.

    python wristband\\fw_panel_test.py
"""
import time

import serial


def frames(b):
    return [l for l in b.decode("utf-8", "replace").splitlines() if l.startswith("[") and "fcrc" not in l]


def send(fw, label, path_args, wait=0.6):
    fw.write(b"\x02" + path_args.encode() + b"\n")
    end, out = time.time() + wait, b""
    while time.time() < end:
        out += fw.read(4096)
    got = [f for f in frames(out) if f.startswith("[" + path_args.split()[0])] or frames(out)
    ok = any(" Ok " in f or f.endswith(" 1]") for f in got)
    print(f"{'OK ' if ok else '?? '} {label:<28} {path_args!r:<48} {got[-1:] }")
    return ok


with serial.Serial("COM7", 115200, timeout=0.1) as fw:
    fw.read(4096)
    print("Building the screen (watch the FREE-WILi)...")
    send(fw, "add panel (black, menu)", "g\\c\\a 0 0 0x000000 1")
    # big text: try a few font settings until one is accepted
    for ft, fs in ((1, 2), (0, 2), (1, 1), (0, 1), (0, 0)):
        if send(fw, f"add text font {ft}/{fs}", f"g\\b\\e 0 20 20 {ft} {fs} 0xFFFFFF 0x000000 FAIR"):
            break
    send(fw, "add bargraph", "g\\b\\f 1 20 120 280 50 0 1000 0xFFA000")
    send(fw, "set menu PUFF on green", "g\\c\\f 2 PUFF")
    shown = send(fw, "show panel 0", "g\\c\\c 0")
    if not shown:
        send(fw, "show panel 1", "g\\c\\c 1")

    print("\nUpdating every 2 s for 20 s. Does the screen STAY (no white, no 'p')?")
    for i, (word, voc, color) in enumerate([("GOOD", 150, "0x00C000"), ("FAIR", 450, "0xFFA000"),
                                            ("BAD!", 850, "0xFF0000"), ("FAIR", 500, "0xFFA000"),
                                            ("GOOD", 120, "0x00C000")] * 2):
        send(fw, f"text -> {word}", f"g\\e\\a 0 {word}", 0.3)
        send(fw, f"bar -> {voc}", f"g\\e\\b 1 {voc}", 0.3)
        time.sleep(1.4)
print("\nDone. Tell Claude: did a black screen with the word + a bar show, and did it stay?")
