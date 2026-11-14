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


def unwrap(value, what):
    """freewili calls return Result objects (Ok/Err). Return the value or raise a clear error."""
    if hasattr(value, "is_ok") and hasattr(value, "unwrap"):
        if value.is_ok():
            return value.unwrap()
        raise RuntimeError(f"{what} failed: {getattr(value, 'err_value', value)}")
    return value


def set_color(device, name):
    r, g, b = COLORS.get(name, COLORS["unknown"])
    for led in range(NUM_LEDS):
        try:
            device.set_board_leds(led, r, g, b)
        except Exception as exc:  # one bad LED call shouldn't stop the loop
            print("LED error:", exc)
            return


def newly_pressed(device, previous):
    """Return names of buttons that went from released to pressed since the last check."""
    states = unwrap(device.read_all_buttons(), "read_all_buttons")
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
    args = parser.parse_args()
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

    try:
        set_color(device, "white")
        time.sleep(0.5)
        while True:
            now = time.time()

            if now - last_poll >= POLL_SECONDS:
                last_poll = now
                new_risk = mock_cycle[int(now / POLL_SECONDS) % 3] if args.mock else fetch_risk(api_url, args.device)
                if new_risk != risk:
                    print(f"Risk: {new_risk}")
                    risk = new_risk
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
        set_color(device, "off")
        device.close()


if __name__ == "__main__":
    main()
