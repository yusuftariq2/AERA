"""Test the wire between the FREE-WILi and the BottleNose in both directions.

Needs BOTH on USB: FREE-WILi (COM7) and the BottleNose running bottlenose_bridge_test.
    python wristband\\fw_uart_hello.py COM11
"""
import re
import sys
import time

import serial

FW_PORT = "COM7"
BN_PORT = sys.argv[1]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def read_for(port, seconds):
    end, out = time.time() + seconds, b""
    while time.time() < end:
        out += port.read(4096)
    return out


def text(b):
    return ANSI.sub("", b.decode("utf-8", "replace"))


def key(fw, k, wait=1.2):
    fw.write(f"{k}\n".encode())
    time.sleep(0.15)
    return text(read_for(fw, wait))


def find_letter(menu, *words):
    for line in menu.splitlines():
        m = re.match(r"\s*([a-z0-9])\s*[)=]\s*(.+)", line.strip(), re.I)
        if m and any(w in m.group(2).lower() for w in words):
            return m.group(1), m.group(2).strip()
    return None, None


with serial.Serial(FW_PORT, 115200, timeout=0.1) as fw, serial.Serial(BN_PORT, 115200, timeout=0.1) as bn:
    fw.write(b"q\nq\n\x03")
    time.sleep(0.3)
    fw.write(b"\n")
    read_for(fw, 1.0)

    print("1) Setting FREE-WILi UART module back to default...")
    for k in ("h", "s", "u", "m", "0"):
        out = key(fw, k, 0.8)
    print("   ", "Module [default]" if "default" in out else out.strip()[-200:])
    for _ in range(4):
        key(fw, "q", 0.3)

    print("\n2) Finding the UART menu under io...")
    io_menu = key(fw, "i")
    letter, label = find_letter(io_menu, "uart")
    print("    io menu:\n" + "\n".join("      " + l for l in io_menu.strip().splitlines()[-25:]))
    if not letter:
        print("No UART entry found under io. Send Claude this output.")
        sys.exit()
    uart_menu = key(fw, letter)
    print(f"    UART menu ({letter} = {label}):\n" + "\n".join("      " + l for l in uart_menu.strip().splitlines()[-25:]))

    print("\n3) FREE-WILi -> BottleNose")
    w, wl = find_letter(uart_menu, "write", "send", "transmit")
    read_for(bn, 0.3)
    if w:
        fw.write(f"{w}\n".encode())
        time.sleep(0.2)
        fw.write(b"HELLO FROM FREEWILI\n")
        got = read_for(bn, 2.0)
        print(f"    used '{w} = {wl}'. BottleNose received: {got!r}")
        print("    ==> WIRE WORKS this direction" if b"HELLO" in got else "    ==> nothing arrived")
        print("    FREE-WILi said:", text(read_for(fw, 0.5)).strip()[-200:])
    else:
        print("    no write option found")

    print("\n4) BottleNose -> FREE-WILi")
    bn.write(b"HELLO FROM BOTTLENOSE\n")
    time.sleep(0.5)
    r, rl = find_letter(uart_menu, "read", "receive", "rx")
    if r:
        out = key(fw, r, 2.0)
        print(f"    used '{r} = {rl}'. FREE-WILi shows:\n      " + out.strip()[-400:].replace("\n", "\n      "))
        print("    ==> WIRE WORKS this direction" if "HELLO" in out else "    ==> no HELLO seen")
    else:
        print("    no read option found")
    for _ in range(5):
        key(fw, "q", 0.2)
print("\nDone. Paste all of this to Claude.")
