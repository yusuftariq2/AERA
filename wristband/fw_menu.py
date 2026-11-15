"""Send menu keys to the FREE-WILi and print what it replies (no typing in a terminal).

Examples (FREE-WILi plugged in, on its main menu, nothing else using the port):
    python wristband\\fw_menu.py COM7 g b        # GUI -> Controls
    python wristband\\fw_menu.py COM7 g e        # GUI -> ControlProperties
    python wristband\\fw_menu.py COM7 g c        # GUI -> Panels
    python wristband\\fw_menu.py COM7 g b h      # GUI -> Controls -> Help

Each key is sent followed by Enter. It always starts from the Main Menu.
"""
import re
import sys
import time

import serial

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def read_for(port, seconds):
    end = time.time() + seconds
    chunks = []
    while time.time() < end:
        data = port.read(port.in_waiting or 1)
        if data:
            chunks.append(data)
    return ANSI.sub("", b"".join(chunks).decode("utf-8", errors="ignore"))


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return
    port_name, keys = sys.argv[1], sys.argv[2:]
    with serial.Serial(port_name, 115200, timeout=0.1) as port:
        # Turn the menu back on (the wristband script turns it off) and go to the Main Menu.
        # Same order the freewili library uses: back out, then the "menu on" byte.
        port.write(b"q\nq\n\x03")
        time.sleep(0.3)
        port.write(b"\n")
        read_for(port, 1.0)
        for key in keys:
            port.write(f"{key}\n".encode())
            text = read_for(port, 1.5)
            print(f"\n===== after '{key}' =====")
            print(text.strip() or "(no reply)")
        # Leave it at the Main Menu.
        port.write(b"q\nq\nq\n")
        read_for(port, 0.5)


if __name__ == "__main__":
    main()
