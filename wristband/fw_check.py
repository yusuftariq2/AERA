"""Quick FREE-WILi check: what USB ports pyfwfinder sees, and which chip answers LED/button commands.

Run with the FREE-WILi plugged in and on its main menu:
    python wristband\fw_check.py
"""
import os
import time

import pyfwfinder as fwf
from freewili import FreeWili
from freewili.types import FreeWiliProcessorType as Proc

print("== What pyfwfinder sees ==")
for dev in fwf.find_all():
    print(f"{dev.name}  type={dev.device_type}  serial={dev.serial}")
    for usb in dev.usb_devices:
        print(f"    {str(usb.kind):32} port={usb.port}  name={usb.name}")

print("\n== Talking to it ==")
device = FreeWili.find_first().expect("No FREE-WILi found")
print(device)
device.open().expect("Could not open")

for proc in (Proc.Display, Proc.Main):
    started = time.time()
    result = device.set_board_leds(0, 60, 60, 60, processor=proc)
    print(f"{proc.name:8} LED 0 white -> {result}  ({time.time() - started:.1f} s)")
    started = time.time()
    result = device.read_all_buttons(processor=proc)
    print(f"{proc.name:8} buttons     -> {result}  ({time.time() - started:.1f} s)")

print("\nDone. Look for 'Ok(' above, and tell Claude which chip (Display or Main) it was on.")
os._exit(0)  # skip the library's slow close
