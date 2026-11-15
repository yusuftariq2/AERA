"""1) Check FREE-WILi -> BottleNose (bytes as hex), 2) turn on UART API mode,
3) send real watch commands from the BottleNose side and see what the watch does.

    python wristband\\fw_uart_api.py COM11
"""
import re
import sys
import time

import serial

FW_PORT = "COM7"
BN_PORT = sys.argv[1]
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

TESTS = [
    ("LED 1 GREEN  (g s)", b"g\ns\n0 0 60 0 8000 0\n"),
    ("LED 2 BLUE   (menu-off byte + g s)", b"\x02g\ns\n1 0 0 60 8000 0\n"),
    ("TEXT 'WIFI OK' (g p)", b"g\np\nWIFI OK\n"),
    ("READ BUTTONS (g u)", b"g\nu\n"),
]


def read_for(port, seconds):
    end, out = time.time() + seconds, b""
    while time.time() < end:
        out += port.read(4096)
    return out


def text(b):
    return ANSI.sub("", b.decode("utf-8", "replace"))


def key(fw, k, wait=1.0):
    fw.write(f"{k}\n".encode())
    time.sleep(0.15)
    return text(read_for(fw, wait))


with serial.Serial(FW_PORT, 115200, timeout=0.1) as fw, serial.Serial(BN_PORT, 115200, timeout=0.1) as bn:
    fw.write(b"q\nq\n\x03")
    time.sleep(0.3)
    fw.write(b"\n")
    read_for(fw, 1.0)

    print("1) FREE-WILi -> BottleNose (bytes)")
    for fmt, payload in (("hex", "48 45 4C 4C 4F 0A"), ("decimal", "72 69 76 76 79 10")):
        key(fw, "i", 0.6)
        key(fw, "u", 0.6)
        read_for(bn, 0.2)
        fw.write(b"w\n")
        time.sleep(0.3)
        fw.write(f"{payload}\n".encode())
        got = read_for(bn, 1.5)
        reply = text(read_for(fw, 0.5)).strip()[-120:]
        print(f"   {fmt}: BottleNose got {got!r}   watch said: {reply!r}")
        for _ in range(4):
            key(fw, "q", 0.2)

    print("\n2) Turning on UART API mode (io > UART > t)")
    key(fw, "i", 0.6)
    key(fw, "u", 0.6)
    out = key(fw, "t", 1.0)
    print("   ", out.strip()[-300:].replace("\n", "\n    "))
    if "Enter" in out and "[" in out.splitlines()[-1]:
        print("    (it asked for a value, sending 1)")
        print("   ", key(fw, "1", 1.0).strip()[-200:])
    for _ in range(4):
        key(fw, "q", 0.2)

    print("\n3) Sending watch commands from the BottleNose (WATCH THE LEDs AND SCREEN)")
    read_for(bn, 0.5)
    for label, data in TESTS:
        bn.write(data)
        got = read_for(bn, 2.0)
        print(f"   {label}: reply on BottleNose side: {got[:300]!r}")
print("\nDone. Tell Claude which LEDs lit / text showed, and paste this output.")
