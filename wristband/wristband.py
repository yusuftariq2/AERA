"""BreatheDetroit wristband on a FREE-WILi.

- Every 3 seconds: asks the API for the kid's risk and sets the FREE-WILi LEDs
  to green / yellow / red.
- When the kid presses a FREE-WILi button (they just used their inhaler):
  publishes a puff to AWS IoT on breathe/<deviceId>/puff, the same topic as the
  ESP32 touch pad. The LEDs flash white to confirm.

Setup (C's laptop):
  pip install freewili boto3 requests
  aws configure                # your IAM user needs the AWSIoTDataAccess policy
  Plug the FREE-WILi in with the kit's USB cable and turn it on.

Run:
  python wristband.py --mock    # no AWS needed: cycles colors, prints button presses
  python wristband.py --mock --led-chip none   # buttons only, skip LEDs
  python wristband.py --api https://abc123.execute-api.us-east-1.amazonaws.com \
                      --endpoint xxxx-ats.iot.us-east-1.amazonaws.com

You can also set BREATHE_API_URL and BREATHE_IOT_ENDPOINT instead of the flags.
Don't use the RED button for puffs: holding it turns the FREE-WILi off.
"""
import argparse
import json
import os
import time

import boto3
import requests
from freewili import FreeWili
from freewili.types import FreeWiliProcessorType

NUM_LEDS = 7  # board LEDs 0-6
COLORS = {
    "green": (0, 60, 0),
    "yellow": (70, 45, 0),
    "red": (90, 0, 0),
    "unknown": (0, 0, 40),  # blue = can't reach the API
    "white": (60, 60, 60),
    "off": (0, 0, 0),
}
IGNORE_BUTTONS = {"RED", "UNKNOWN"}  # buttons are WHITE, YELLOW, GREEN, BLUE, RED
POLL_SECONDS = 3.0
BUTTON_CHECK_SECONDS = 0.1
PUFF_COOLDOWN_SECONDS = 2.0
LED_CHIP = FreeWiliProcessorType.Display     # set by --led-chip (None = no LEDs)
BUTTON_CHIP = FreeWiliProcessorType.Main     # set by --button-chip


def unwrap(value, what):
    """freewili calls return Result objects (Ok/Err). Return the value or raise a clear error."""
    if hasattr(value, "is_ok") and hasattr(value, "unwrap"):
        if value.is_ok():
            return value.unwrap()
        raise RuntimeError(f"{what} failed: {getattr(value, 'err_value', value)}")
    return value


def set_color(device, name):
    """Set all board LEDs. Returns False (and stops early) if the FREE-WILi doesn't answer."""
    if LED_CHIP is None:
        return False
    r, g, b = COLORS.get(name, COLORS["unknown"])
    for led in range(NUM_LEDS):
        try:
            res = device.set_board_leds(led, r, g, b, processor=LED_CHIP)
        except Exception as exc:
            print("LED error:", exc)
            return False
        if hasattr(res, "is_err") and res.is_err():
            print("LED error:", getattr(res, "err_value", res))
            return False
    return True


def newly_pressed(device, previous):
    """Return names of buttons that went from released to pressed since the last check."""
    states = unwrap(device.read_all_buttons(processor=BUTTON_CHIP), "read_all_buttons")
    pressed = []
    for color, state in states.items():
        name = str(getattr(color, "name", color)).upper()
        down = bool(state)
        if down and not previous.get(name) and name not in IGNORE_BUTTONS:
            pressed.append(name)
        previous[name] = down
    return pressed


def fetch_risk(api_url, device_id):
    try:
        resp = requests.get(f"{api_url}/status/{device_id}", timeout=3)
        resp.raise_for_status()
        return resp.json().get("risk", "unknown")
    except Exception as exc:
        print("API error:", exc)
        return "unknown"


def main():
    parser = argparse.ArgumentParser(description="FREE-WILi wristband for BreatheDetroit")
    parser.add_argument("--api", default=os.environ.get("BREATHE_API_URL", ""), help="API Gateway invoke URL")
    parser.add_argument("--endpoint", default=os.environ.get("BREATHE_IOT_ENDPOINT", ""), help="AWS IoT data endpoint")
    parser.add_argument("--device", default=os.environ.get("BREATHE_DEVICE_ID", "kid-001"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument("--mock", action="store_true", help="test the FREE-WILi without AWS")
    parser.add_argument("--led-chip", choices=["display", "main", "none"], default="display",
                        help="chip for the LED command (see fw_check.py); 'none' skips LEDs")
    parser.add_argument("--button-chip", choices=["display", "main"], default="main",
                        help="chip for reading buttons (see fw_check.py)")
    args = parser.parse_args()
    global LED_CHIP, BUTTON_CHIP
    chips = {"display": FreeWiliProcessorType.Display, "main": FreeWiliProcessorType.Main, "none": None}
    LED_CHIP = chips[args.led_chip]
    BUTTON_CHIP = chips[args.button_chip]
    api_url = args.api.rstrip("/")

    if not args.mock and (not api_url or not args.endpoint):
        parser.error("give --api and --endpoint (or run with --mock to test the FREE-WILi alone)")

    iot = None
    if not args.mock:
        iot = boto3.client("iot-data", region_name=args.region, endpoint_url=f"https://{args.endpoint}")

    try:
        device = FreeWili.find_first().expect("No FREE-WILi found. Is it turned on and plugged in by USB?")
        device.open().expect("Found the FREE-WILi but couldn't open it. Close the FREE-WILi GUI and try again.")
    except Exception as exc:
        print(exc)
        return

    print(f"FREE-WILi connected. Wristband for {args.device}. Press Ctrl+C to stop.")
    mock_cycle = ["green", "yellow", "red"]
    previous_buttons = {}
    risk = "unknown"
    last_poll = 0.0
    last_puff = 0.0

    leds_ok = False
    try:
        if LED_CHIP is None:
            print("LEDs off (--led-chip none). Risk shows in this window only.")
        else:
            print(f"Testing LEDs on {LED_CHIP.name} chip (should flash white)...")
            started = time.time()
            leds_ok = set_color(device, "white")
            if leds_ok:
                print(f"LEDs OK ({time.time() - started:.1f} s).")
            else:
                print("LEDs didn't answer, so continuing WITHOUT LEDs (risk shows in this window).\n"
                      "Ask the FREE-WILi team to update the display firmware to fix the LEDs.")
        started = time.time()
        try:
            unwrap(device.read_all_buttons(processor=BUTTON_CHIP), "read_all_buttons")
            print(f"Buttons OK on {BUTTON_CHIP.name} chip ({time.time() - started:.1f} s). Running. Press Ctrl+C to stop.")
        except Exception as exc:
            print(f"Button read failed on {BUTTON_CHIP.name} chip: {exc}")
        time.sleep(0.5)
        while True:
            now = time.time()

            if now - last_poll >= POLL_SECONDS:
                last_poll = now
                new_risk = mock_cycle[int(now / POLL_SECONDS) % 3] if args.mock else fetch_risk(api_url, args.device)
                if new_risk != risk:
                    print(f"Risk: {new_risk}")
                    risk = new_risk
                if leds_ok:
                    set_color(device, risk)

            try:
                pressed = newly_pressed(device, previous_buttons)
            except Exception as exc:
                print("Button read error:", exc)
                pressed = []

            if pressed and now - last_puff >= PUFF_COOLDOWN_SECONDS:
                last_puff = now
                print(f"Puff logged ({pressed[0]} button)")
                if iot is not None:
                    payload = {"deviceId": args.device, "ts": int(now), "event": "puff", "source": "wristband"}
                    try:
                        iot.publish(topic=f"breathe/{args.device}/puff", qos=1, payload=json.dumps(payload))
                    except Exception as exc:
                        print("Publish failed:", exc)
                if leds_ok:
                    for _ in range(2):  # flash white to confirm
                        set_color(device, "white")
                        time.sleep(0.15)
                        set_color(device, "off")
                        time.sleep(0.15)
                    set_color(device, risk)

            time.sleep(BUTTON_CHECK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        # Only touch the LEDs on the way out if they were answering; otherwise exit right away.
        if leds_ok:
            set_color(device, "off")
        try:
            device.close(restore_menu=leds_ok)
        except Exception:
            pass
        os._exit(0)  # don't wait on the library's background threads


if __name__ == "__main__":
    main()
