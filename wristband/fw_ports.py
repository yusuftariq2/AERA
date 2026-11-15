"""Show which COM port is which FREE-WILi chip, and print the main chip's menus.

    python wristband\\fw_ports.py
"""
import re
import time

import serial
from freewili import FreeWili

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def read_for(port, seconds):
    end, out = time.time() + seconds, b""
    while time.time() < end:
        out += port.read(4096)
    return ANSI.sub("", out.decode("utf-8", "replace"))


device = FreeWili.find_first().expect("No FREE-WILi found")
print("Device:", device)
for name in ("main_serial", "display_serial"):
    s = getattr(device, name, None)
    print(f"  {name}: {s.serial_port.port if s else None}")

main_name = device.main_serial.serial_port.port
print(f"\nMain chip is on {main_name}. Its menus:\n")
with serial.Serial(main_name, 115200, timeout=0.1) as p:
    p.write(b"q\nq\n\x03")
    time.sleep(0.3)
    p.write(b"\n")
    print("===== main menu =====")
    print(read_for(p, 1.5).strip()[-1500:])
    p.write(b"x\n")
    print("\n===== after 'x' =====")
    print(read_for(p, 1.5).strip()[-1500:])
    p.write(b"q\nq\n")
    read_for(p, 0.3)
