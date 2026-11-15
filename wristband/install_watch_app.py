"""Copy the BreatheDetroit watch app onto the FREE-WILi and start it.

Your FREE-WILi OG firmware keeps file upload under Hardware > Files (h > x > f)
and script launch under Scripting > Launch Script (s > a), so this script sends
those paths itself instead of the library's newer-firmware shortcuts.

    taskkill /F /IM python.exe
    python wristband\\install_watch_app.py
"""
import os
import pathlib
import sys
import time
import zlib

from freewili import FreeWili

APP = pathlib.Path(__file__).parent / "breathe.wasm"
TARGET = "/scripts/breathe.wsm"


def frame(port, timeout, what):
    res = port._wait_for_response_frame(timeout_sec=timeout, what_msg=what)
    if res.is_ok():
        rf = res.ok_value
        print(f"   {what}: {'OK' if rf.is_ok() else 'FAILED'} {rf.response!r}")
        return rf.is_ok()
    print(f"   {what}: no reply ({res.err_value})")
    return False


def upload(port, app=APP):
    # OG firmware uses 8.3 names: apps must end in .wsm (3 letters) to show as runnable
    target = f"/scripts/{app.stem[:8]}.wsm"
    data = app.read_bytes()
    crc = zlib.crc32(data)
    port._set_menu_enabled(False)
    port._empty_all()
    print(f"Uploading {app.name} ({len(data)} bytes) to {target} ...")
    port.serial_port.send(f"h\nx\nf\n{target} {len(data)} {crc}", delay_sec=0.0)
    if not frame(port, 6.0, "start transfer"):
        return False
    port.serial_port.send(data, False, delay_sec=0.0)
    time.sleep(0.5)
    while (ev := port._wait_for_event_response_frame(1)).is_ok():
        print("   device:", ev.ok_value.response)
    return frame(port, 10.0, "finish transfer")


def launch(port):
    for name in ("breathe.wsm", TARGET):
        port._set_menu_enabled(False)
        port._empty_all()
        port.serial_port.send(f"s\na\n{name}", delay_sec=0.0)
        if frame(port, 3.0, f"launch {name}"):
            return True
    return False


def main():
    device = FreeWili.find_first().expect("No FREE-WILi found (on, main menu, plugged in?)")
    print("Connected:", device)
    port = device.main_serial
    port.stay_open = True
    port.open().expect("could not open main port")

    extra = [pathlib.Path(a) for a in sys.argv[1:]]
    if extra:  # e.g. python wristband\install_watch_app.py wristband\tests\t_a.wasm ...
        for app in extra:
            print("OK" if upload(port, app) else "FAILED", app.name, "\n")
            time.sleep(1.0)
        print("Done. On the watch: Scripting > pick each file to run it.")
    elif upload(port):
        time.sleep(0.5)
        if launch(port):
            print("\nApp started. The watch should show the BreatheDetroit screen.")
        else:
            print("\nUploaded, but auto-start didn't confirm. Start it on the watch:")
            print("  Scripting > Launch Script > breathe.wasm (or check the screen first).")
    else:
        print("\nUpload failed. Send Claude this output.")
    try:
        port._set_menu_enabled(True)
    except Exception:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()