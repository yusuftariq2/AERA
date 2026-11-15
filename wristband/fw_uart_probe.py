"""Send test commands to the FREE-WILi's UART through the BottleNose bridge.

    python wristband\\fw_uart_probe.py COM12      (use the BottleNose's COM port)

Watch the FREE-WILi: each test lights a different LED or shows text.
"""
import sys
import time

import serial

TESTS = [
    ("A  LED 1 GREEN  (s + args)", b"s\n0 0 60 0 8000 0\n"),
    ("B  LED 2 BLUE   (g s + args)", b"g\ns\n1 0 0 60 8000 0\n"),
    ("C  LED 3 RED    (menu-off byte, g s)", b"\x02g\ns\n2 60 0 0 8000 0\n"),
    ("D  LED 4 WHITE  (one line, spaces)", b"g s 3 40 40 40 8000 0\n"),
    ("E  TEXT 'UART E' (g p)", b"g\np\nUART E\n"),
    ("F  TEXT 'UART F' (p)", b"p\nUART F\n"),
]


def read_for(port, seconds):
    end, out = time.time() + seconds, b""
    while time.time() < end:
        out += port.read(4096)
    return out


port_name = sys.argv[1]
with serial.Serial(port_name, 115200, timeout=0.1) as p:
    time.sleep(1.0)
    print("idle bytes from watch:", read_for(p, 1.0)[:300])
    for label, data in TESTS:
        print(f"\n=== {label} ===")
        p.write(data)
        reply = read_for(p, 2.5)
        print("reply:", reply[:400] if reply else "(nothing)")
print("\nDone. Tell Claude which LEDs (1-4, counting from the first) lit and whether text appeared.")
