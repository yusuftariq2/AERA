# AERA

A $40 bedside air monitor and a FREE-WILi wristband that warn parents of Detroit kids with asthma before a bad day, log inhaler use, and show school nurses who's at risk. Built on AWS IoT Core, Lambda, DynamoDB, SNS, API Gateway, Amplify and Bedrock.

Monitors asthma triggers and alerts caregivers. Not a medical device.

## Folders

| Folder | Owner | What's in it |
| --- | --- | --- |
| `firmware/breathe_device/` | A | ESP32 sketch: CCS811 + DHT11 + touch pad + LEDs, sends to AWS IoT |
| `firmware/tools/serial_bridge.py` | A | Fallback if the ESP32 can't reach AWS over WiFi |
| `cloud/` | B | Risk Lambda, API Lambda, and `SETUP.md` (step-by-step console setup) |
| `dashboard/` | C | React (Vite) parent + nurse dashboard |
| `wristband/` | C | FREE-WILi wristband script |
| `pitch/` | Everyone | Slides, screenshots, demo video |

## Messages (don't change after Checkpoint 1)

- Topics: `breathe/<deviceId>/telemetry` and `breathe/<deviceId>/puff`
- Telemetry: `{"deviceId": "kid-001", "ts": 1763136000, "tvoc": 180, "eco2": 650, "tempC": 21.3, "humidity": 45}`
- Puff: `{"deviceId": "kid-001", "ts": 1763136042, "event": "puff"}`
- Risk: TVOC under 220 ppb = green, 220–660 = yellow, above 660 = red. Bumped up one level if humidity is over 60% or there were 2+ puffs in 24 hours.

## Quick start

**A (firmware)**
1. Open `firmware/breathe_device/breathe_device.ino` in Arduino IDE.
2. Copy `secrets.example.h` to `secrets.h` and fill in the hotspot WiFi, the IoT endpoint and the 3 certificates from B.
3. Board: ESP32 Dev Module → pick the port → Upload → open Serial Monitor at **115200**.
4. You should see `CCS811 found`, then `WiFi connected`, `connected` (AWS), and a JSON line every 5 seconds.
5. Wiring is in the build plan's Wiring table. LEDs: green → GPIO 18, yellow → 19, red → 23, each through a 220–330 Ω resistor.

**B (cloud)**: follow `cloud/SETUP.md` top to bottom. Each step ends with a test.

**C (dashboard)**
1. Copy `src/App.jsx`, `src/App.css` and `src/index.css` into your Vite app's `src/` folder, replacing the defaults.
2. `npm install` → `npm run dev`. With no API URL it runs on fake data, so you can work right now.
3. When B gives you the Invoke URL: copy `.env.example` to `.env`, set `VITE_API_URL=...`, and restart `npm run dev`.
4. Deploy: Amplify console → **Create new app → GitHub** → pick the repo and branch → check **"My app is a monorepo"** → app root `dashboard` → add environment variable `VITE_API_URL` → Deploy.

**C (wristband)**
1. `pip install freewili boto3 requests`
2. Test the FREE-WILi alone: `python wristband/wristband.py --mock`. The LEDs cycle green, yellow, red, and button presses print.
3. Live: `python wristband/wristband.py --api <Invoke URL> --endpoint <IoT endpoint>`

## Demo-day checklist

- Plug the CCS811 in 20+ minutes before judging so its readings settle.
- ESP32 on the phone hotspot (2.4 GHz, "Maximize Compatibility" on iPhone).
- Dashboard open, wristband script running, a phone on loud showing alert emails.
- Hairspray or deodorant for the spike. No smoke or flames indoors.
