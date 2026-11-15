"""Try UART API mode in each combination and see if the watch answers over the wire.

    python wristband\\fw_uart_api2.py COM11
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


def usb_keys(fw, *keys, wait=0.7):
    out = ""
    for k in keys:
        fw.write(f"{k}\n".encode())
        time.sleep(0.15)
        out = text(read_for(fw, wait))
    for _ in range(5):
        fw.write(b"q\n")
        time.sleep(0.05)
    read_for(fw, 0.4)
    return out


def probe(bn, tag, led):
    """Send a wake-up and a few commands over the wire; return True if the watch answered."""
    read_for(bn, 0.3)
    answered = False
    for label, data in (
        ("wake (ctrl-C + enter)", b"\x03\r\n"),
        ("menu q enter", b"q\r\n"),
        (f"LED {led + 1} (\\n)", f"g\ns\n{led} 0 60 60 8000 0\n".encode()),
        (f"LED {led + 1} (\\r\\n)", f"g\r\ns\r\n{led} 60 0 60 8000 0\r\n".encode()),
        ("text", f"g\np\n{tag}\n".encode()),
    ):
        bn.write(data)
        got = read_for(bn, 1.5)
        print(f"   [{tag}] {label}: {got[:160]!r}")
        answered = answered or bool(got.strip())
    return answered


with serial.Serial(FW_PORT, 115200, timeout=0.1) as fw, serial.Serial(BN_PORT, 115200, timeout=0.1) as bn:
    fw.write(b"q\nq\n\x03")
    time.sleep(0.3)
    fw.write(b"\n")
    read_for(fw, 1.0)

    print("Turning OFF UART read events (they can grab incoming bytes)...")
    st = usb_keys(fw, "i", "u")
    if "stream : 1" in st:
        usb_keys(fw, "i", "u", "r")

    print("\nA) module=gui, API mode as-is")
    usb_keys(fw, "h", "s", "u", "m", "1")
    if probe(bn, "A GUI", 0):
        print("==> WATCH ANSWERED in A"); sys.exit()

    print("\nB) module=gui, toggle API mode")
    print("   t says:", usb_keys(fw, "i", "u", "t").strip()[-80:])
    if probe(bn, "B GUI+API", 1):
        print("==> WATCH ANSWERED in B"); sys.exit()

    print("\nC) module=default, API mode (same state as B)")
    usb_keys(fw, "h", "s", "u", "m", "0")
    if probe(bn, "C API", 2):
        print("==> WATCH ANSWERED in C"); sys.exit()

    print("\nD) module=default, toggle API mode again")
    print("   t says:", usb_keys(fw, "i", "u", "t").strip()[-80:])
    if probe(bn, "D API2", 3):
        print("==> WATCH ANSWERED in D"); sys.exit()

    print("\nNo answer in any mode. Setting module back to default.")
print("\nDone. Tell Claude which LEDs lit (1-4) / any text, and paste this output.")
