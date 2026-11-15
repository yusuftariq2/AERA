"""BreatheDetroit wristband on a FREE-WILi OG (firmware ogfw 024 / display 020).

What it does (over USB, through the laptop):
  - Screen: short pages that rotate every 2 s: "AIR BAD" -> "VOC 683" -> "PUFFS 2"
  - LEDs:   a 7-LED bar graph of the VOC level, colored green / yellow / red
  - Button: HOLD the WHITE, YELLOW, GREEN or BLUE button while taking the inhaler.
            On release it logs a puff to AWS IoT with how long it was held (durationMs).

All commands go to the FREE-WILi MAIN serial port. This firmware's LED command takes
6 numbers (LED R G B duration mode), which is why the stock freewili set_board_leds()
(4 numbers) returned "Invalid". We send the 6-number form ourselves.

Setup (laptop):
  pip install freewili boto3 requests
  aws configure                 # IAM user with AWSIoTDataAccess, region us-east-2

Run:
  python wristband\\wristband.py --mock      # no AWS: fake readings, button presses print
  python wristband\\wristband.py --api https://xxxx.execute-api.us-east-2.amazonaws.com ^
                                 --endpoint xxxx-ats.iot.us-east-2.amazonaws.com --region us-east-2

Keep the FREE-WILi on its main menu (not inside an app like the timer).
Don't use the RED button for puffs: holding it turns the FREE-WILi off.
"""
import argparse
import json
import os
import random
import time

import boto3
import requests
from freewili import FreeWili

NUM_LEDS = 7
LED_DURATION_MS = 5000     # value that worked in the serial test; we refresh before it matters
LED_BRIGHTNESS = 60
VOC_FULL_SCALE = 1000      # ppb that lights all 7 LEDs
RISK_RGB = {
    "green": (0, LED_BRIGHTNESS, 0),
    "yellow": (LED_BRIGHTNESS, LED_BRIGHTNESS // 2, 0),
    "red": (LED_BRIGHTNESS, 0, 0),
    "unknown": (0, 0, LED_BRIGHTNESS),   # blue = no data / can't reach the API
}
IGNORE_BUTTONS = {"RED", "UNKNOWN"}
POLL_SECONDS = 2.0          # how often to ask the API for fresh data
BUTTON_CHECK_SECONDS = 0.1
MIN_HOLD_MS = 150           # ignore accidental taps shorter than this


def unwrap(value, what):
    """freewili calls return Result objects (Ok/Err). Return the value or raise a clear error."""
    if hasattr(value, "is_ok") and hasattr(value, "unwrap"):
        if value.is_ok():
            return value.unwrap()
        raise RuntimeError(f"{what} failed: {getattr(value, 'err_value', value)}")
    return value


class Watch:
    """Talks to the FREE-WILi MAIN port using the command formats this firmware accepts."""

    def __init__(self, device):
        self.main = device.main_serial
        if self.main is None:
            raise RuntimeError("FREE-WILi main port not found")
        self.main.stay_open = True
        unwrap(self.main.open(), "open main port")
        self.last_text = None
        self.last_leds = None

    def _command(self, cmd):
        self.main._set_menu_enabled(False)  # framed replies, no menu text
        self.main._empty_all()
        self.main.serial_port.send(cmd)
        return self.main._handle_final_response_frame()

    def set_led(self, index, r, g, b):
        return self._command(f"g\ns\n{index} {r} {g} {b} {LED_DURATION_MS} 0")

    def show_bar(self, risk, tvoc):
        """Light a bar of LEDs proportional to VOC, in the risk color. Only resend on change."""
        if tvoc is None:
            lit = 0
        else:
            lit = max(1, min(NUM_LEDS, round(float(tvoc) / VOC_FULL_SCALE * NUM_LEDS)))
        color = RISK_RGB.get(risk, RISK_RGB["unknown"])
        state = (lit, color)
        if state == self.last_leds:
            return True
        ok = True
        for i in range(NUM_LEDS):
            r, g, b = color if i < lit else (0, 0, 0)
            res = self.set_led(i, r, g, b)
            if hasattr(res, "is_err") and res.is_err():
                print("LED error:", getattr(res, "err_value", res))
                ok = False
                break
        if ok:
            self.last_leds = state
        return ok

    def flash(self, rgb=(LED_BRIGHTNESS, LED_BRIGHTNESS, LED_BRIGHTNESS)):
        for i in range(NUM_LEDS):
            self.set_led(i, *rgb)
        time.sleep(0.2)
        self.last_leds = None  # force the bar to redraw next time

    def show_text(self, text):
        if text == self.last_text:
            return True
        res = self.main.show_text_display(text)
        if hasattr(res, "is_err") and res.is_err():
            print("Text error:", getattr(res, "err_value", res))
            return False
        self.last_text = text
        return True

    def buttons(self):
        """Return {name: is_down} for the five buttons."""
        states = unwrap(self.main.read_all_buttons(), "read_all_buttons")
        return {str(getattr(c, "name", c)).upper(): bool(s) for c, s in states.items()}

    def close(self):
        try:
            for i in range(NUM_LEDS):
                self.set_led(i, 0, 0, 0)
            self._command("g\nt")  # Reset Display: clear our text overlay
        except Exception:
            pass
        try:
            self.main.close(restore_menu=True)
        except Exception:
            pass


def fetch_status(api_url, device_id):
    try:
        resp = requests.get(f"{api_url}/status/{device_id}", timeout=3)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print("API error:", exc)
        return None


def mock_status(state):
    """Fake readings that drift and sometimes spike, so you can test without AWS."""
    state["tvoc"] = max(20, min(1100, state["tvoc"] * 0.85 + 30 + (600 if random.random() < 0.1 else 0)))
    tvoc = round(state["tvoc"])
    risk = "red" if tvoc > 660 else "yellow" if tvoc >= 220 else "green"
    return {"risk": risk, "latest": {"tvoc": tvoc}, "puffs24h": state["puffs"]}


SCREEN_MAX_CHARS = 8        # the OG screen fits about 7-8 characters per line at its text size


def screen_pages(status):
    """Short pages that fit the watch screen; the loop rotates through them."""
    if not status:
        return ["NO DATA"]
    risk = status.get("risk", "unknown")
    tvoc = (status.get("latest") or {}).get("tvoc")
    word = {"green": "GOOD", "yellow": "FAIR", "red": "BAD"}.get(risk, "?")
    pages = [f"AIR {word}"]
    pages.append(f"VOC {tvoc}" if tvoc is not None else "VOC --")
    pages.append(f"PUFFS {status.get('puffs24h', 0)}")
    return [p[:SCREEN_MAX_CHARS] for p in pages]


def main():
    parser = argparse.ArgumentParser(description="FREE-WILi wristband for BreatheDetroit")
    parser.add_argument("--api", default=os.environ.get("BREATHE_API_URL", ""), help="API Gateway invoke URL")
    parser.add_argument("--endpoint", default=os.environ.get("BREATHE_IOT_ENDPOINT", ""), help="AWS IoT data endpoint")
    parser.add_argument("--device", default=os.environ.get("BREATHE_DEVICE_ID", "kid-001"))
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-2"))
    parser.add_argument("--mock", action="store_true", help="test the FREE-WILi without AWS")
    args = parser.parse_args()
    api_url = args.api.rstrip("/")

    if not args.mock and (not api_url or not args.endpoint):
        parser.error("give --api and --endpoint (or run with --mock to test the FREE-WILi alone)")

    iot = None
    if not args.mock:
        iot = boto3.client("iot-data", region_name=args.region, endpoint_url=f"https://{args.endpoint}")

    try:
        device = FreeWili.find_first().expect("No FREE-WILi found. Is it on, on the main menu, and plugged in by USB?")
        watch = Watch(device)
    except Exception as exc:
        print(exc)
        os._exit(1)

    print(f"FREE-WILi connected. Wristband for {args.device}. Ctrl+C to stop.")
    print("Hold WHITE/YELLOW/GREEN/BLUE while 'taking the inhaler', then let go.")
    mock_state = {"tvoc": 150.0, "puffs": 0}
    status = None
    last_poll = 0.0
    page_index = 0
    hold_text_until = 0.0  # keep "PUFF 1.2s" on screen briefly
    pressed_at = {}  # button name -> time it went down

    try:
        watch.show_text("HELLO")
        while True:
            now = time.time()

            if now - last_poll >= POLL_SECONDS:
                last_poll = now
                status = mock_status(mock_state) if args.mock else fetch_status(api_url, args.device)
                risk = (status or {}).get("risk", "unknown")
                tvoc = ((status or {}).get("latest") or {}).get("tvoc")
                watch.show_bar(risk, tvoc)
                if now >= hold_text_until:
                    pages = screen_pages(status)
                    watch.show_text(pages[page_index % len(pages)])
                    page_index += 1

            try:
                down = watch.buttons()
            except Exception as exc:
                print("Button read error:", exc)
                down = {}

            for name, is_down in down.items():
                if name in IGNORE_BUTTONS:
                    continue
                if is_down and name not in pressed_at:
                    pressed_at[name] = now
                elif not is_down and name in pressed_at:
                    held_ms = int((now - pressed_at.pop(name)) * 1000)
                    if held_ms < MIN_HOLD_MS:
                        continue
                    print(f"Puff logged: {name} held {held_ms / 1000:.1f} s")
                    if args.mock:
                        mock_state["puffs"] += 1
                    elif iot is not None:
                        payload = {
                            "deviceId": args.device,
                            "ts": int(now),
                            "event": "puff",
                            "source": "wristband",
                            "durationMs": held_ms,
                        }
                        try:
                            iot.publish(topic=f"breathe/{args.device}/puff", qos=1, payload=json.dumps(payload))
                        except Exception as exc:
                            print("Publish failed:", exc)
                    watch.show_text(f"PUFF {held_ms / 1000:.1f}s"[:SCREEN_MAX_CHARS])
                    watch.flash()
                    hold_text_until = now + 2.0
                    page_index = 2  # show the new PUFFS count next
                    last_poll = now - POLL_SECONDS + 2.0  # next screen refresh in 2 s

            time.sleep(BUTTON_CHECK_SECONDS)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        watch.close()
        os._exit(0)  # don't wait on the library's background threads


if __name__ == "__main__":
    main()