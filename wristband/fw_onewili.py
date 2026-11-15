"""Use FREE-WILi's official OneWili wire format (from github.com/freewili/onewili):
each command is ONE line:  0x02 + path-with-backslashes + " args" + "\\n"
e.g.  \\x02g\\s 0 0 60 0 8000 0\\n   (LED 0 green)

Step 1 proves the format over USB. Step 2 turns on UART API mode the same way.
Step 3 sends the same lines over the BottleNose wire.

    python wristband\\fw_onewili.py COM11
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
    return [l for l in b.decode("utf-8", "replace").splitlines() if l.startswith("[")]


with serial.Serial(FW_PORT, 115200, timeout=0.1) as fw, serial.Serial(BN_PORT, 115200, timeout=0.1) as bn:
    read_for(fw, 0.5)
    print("1) USB, OneWili format: LED 1 GREEN + text 'USB OK'")
    fw.write(line("g\\s", "0 0 60 0 8000 0"))
    print("  ", frames(read_for(fw, 1.0)))
    fw.write(line("g\\p", "USB OK"))
    print("  ", frames(read_for(fw, 1.0)))

    def wire_test(tag, led):
        read_for(bn, 0.3)
        bn.write(line("g\\s", f"{led} 0 0 60 8000 0"))
        a = read_for(bn, 1.5)
        bn.write(line("g\\p", tag))
        b = read_for(bn, 1.5)
        print(f"   LED {led + 1} BLUE -> {a[:150]!r}")
        print(f"   text {tag!r} -> {b[:150]!r}")
        return bool(a.strip() or b.strip())

    print("\n2) Wire test with API mode as it is now")
    if wire_test("WIRE A", 1):
        print("==> THE WATCH ANSWERED OVER THE WIRE")
        sys.exit()

    for attempt in (1, 2):
        print(f"\n3.{attempt}) Toggle UART API mode over USB (i\\u\\t), then wire test")
        fw.write(line("i\\u\\t"))
        print("   t ->", frames(read_for(fw, 1.0)))
        time.sleep(0.5)
        if wire_test(f"WIRE {attempt}", 1 + attempt):
            print("==> THE WATCH ANSWERED OVER THE WIRE")
            sys.exit()
print("\nNo answer over the wire. Paste this to Claude, and say whether LED 1 turned green and 'USB OK' showed.")
