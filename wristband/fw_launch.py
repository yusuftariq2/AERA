"""Launch an app on the FREE-WILi from the console and print everything it says.

    python wristband\\fw_launch.py breathe.wsm
"""
import re
import sys
import time

import serial

PORT = "COM7"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
name = sys.argv[1] if len(sys.argv) > 1 else "breathe.wsm"


def read_for(port, seconds):
    end, out = time.time() + seconds, b""
    while time.time() < end:
        out += port.read(4096)
    return ANSI.sub("", out.decode("utf-8", "replace"))


with serial.Serial(PORT, 115200, timeout=0.1) as p:
    p.write(b"q\nq\n\x03")
    time.sleep(0.3)
    p.write(b"\n")
    read_for(p, 1.0)
    for candidate in (f"/scripts/{name}", name):
        print(f"===== WASM Debug Start {candidate} (watch the screen/LEDs) =====")
        p.write(f"q\nq\nq\ns\nw\nc\n{candidate} 0\n".encode())  # 0 = don't start paused
        print(read_for(p, 4.0).strip()[-2500:] or "(no reply)")
        print(f"----- continue -----")
        p.write(b"f\n")
        print(read_for(p, 8.0).strip()[-2500:] or "(no reply)")
        print("----- locals -----")
        p.write(b"i\n")
        print(read_for(p, 2.0).strip()[-1500:] or "(no reply)")
        p.write(b"t\nq\nq\nq\n")
        read_for(p, 1.0)