"""Reboot the FREE-WILi (so UART API mode takes effect at startup), then talk to it
only through the BottleNose wire. No menu navigation after the reboot.

    python wristband\\fw_uart_api3.py COM11
"""
import sys
import time

import serial

FW_PORT = "COM7"
BN_PORT = sys.argv[1]


def read_for(port, seconds):
    end, out = time.time() + seconds, b""
    while time.time() < end:
        try:
            out += port.read(4096)
        except serial.SerialException:  # the watch rebooted and its USB port went away: expected
            time.sleep(seconds)
            break
    return out


print("Rebooting the FREE-WILi (Hardware > Settings > Software Reset)...")
fw = serial.Serial(FW_PORT, 115200, timeout=0.1)
if True:
    fw.write(b"q\nq\nq\nq\n\x03")
    time.sleep(0.3)
    fw.write(b"\n")
    read_for(fw, 0.8)
    for k in (b"h\n", b"s\n", b"1\n"):
        fw.write(k)
        time.sleep(0.5)
        print("  ", read_for(fw, 0.6).decode("utf-8", "replace").strip().splitlines()[-1:] or "")

try:
    fw.close()
except Exception:
    pass
print("Waiting 12 s for it to boot (DON'T touch the watch)...")
time.sleep(12)

with serial.Serial(BN_PORT, 115200, timeout=0.1) as bn:
    print("Bytes the watch sent on the wire during boot:", read_for(bn, 2.0)[:300])
    for label, data in (
        ("enter", b"\r\n"),
        ("ctrl-C enter", b"\x03\r\n"),
        ("LED 1 green", b"g\ns\n0 0 60 0 8000 0\n"),
        ("LED 2 blue (menu-off first)", b"\x02g\ns\n1 0 0 60 8000 0\n"),
        ("text BOOT OK", b"g\np\nBOOT OK\n"),
    ):
        bn.write(data)
        got = read_for(bn, 2.0)
        print(f"  {label}: {got[:200]!r}")
print("\nDone. Tell Claude if any LED lit / text showed, and paste this output.")