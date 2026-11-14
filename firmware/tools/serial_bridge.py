"""Fallback if the ESP32 can't reach AWS IoT over WiFi.

The ESP32 prints one JSON line per reading/puff over USB. This script reads those
lines on a laptop and publishes them to AWS IoT Core, so the rest of the system
works exactly the same.

1. In breathe_device.ino set:  #define USE_AWS false   and upload.
2. Close the Arduino Serial Monitor (only one program can use the port).
3. pip install pyserial boto3
4. python serial_bridge.py --port COM3 --endpoint xxxx-ats.iot.us-east-1.amazonaws.com
   (Mac port looks like /dev/cu.usbserial-0001 or /dev/cu.SLAB_USBtoUART)

Uses your AWS CLI login (aws configure). Your IAM user needs iot:Publish
(the AWSIoTDataAccess managed policy works).
"""
import argparse
import json
import time

import boto3
import serial


def main() -> None:
    parser = argparse.ArgumentParser(description="ESP32 USB -> AWS IoT bridge")
    parser.add_argument("--port", required=True, help="Serial port, e.g. COM3 or /dev/cu.usbserial-0001")
    parser.add_argument("--endpoint", required=True, help="AWS IoT data endpoint (no https://)")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    iot = boto3.client("iot-data", region_name=args.region, endpoint_url=f"https://{args.endpoint}")
    ser = serial.Serial(args.port, args.baud, timeout=2)
    print(f"Listening on {args.port}. Press Ctrl+C to stop.")

    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        if not line.startswith("{"):
            print("  esp32:", line)  # normal debug text from the board
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = "puff" if data.get("event") == "puff" else "telemetry"
        data["ts"] = int(time.time())  # board has no clock without WiFi
        topic = f"breathe/{data.get('deviceId', 'kid-001')}/{kind}"
        try:
            iot.publish(topic=topic, qos=1, payload=json.dumps(data))
            print(f"-> {topic} {data}")
        except Exception as exc:  # keep running if one publish fails
            print("Publish failed:", exc)


if __name__ == "__main__":
    main()
