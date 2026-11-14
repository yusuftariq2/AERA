"""breathe-risk Lambda.

Triggered by the IoT Rule for every MQTT message on breathe/<deviceId>/telemetry
and breathe/<deviceId>/puff. It:
  1. scores risk (green / yellow / red),
  2. saves the reading or puff to the BreatheReadings table,
  3. updates the kid's latest state in the BreatheState table,
  4. sends an SNS alert when risk is red (at most once per 10 minutes per kid).

Runtime: Python 3.12. Handler: lambda_function.lambda_handler
Environment variables:
  READINGS_TABLE   BreatheReadings
  STATE_TABLE      BreatheState
  ALERT_TOPIC_ARN  arn:aws:sns:us-east-1:<account>:breathe-alerts
  KID_NAMES        {"kid-001": "Jayden"}
"""
import json
import os
import time
from decimal import Decimal

import boto3

READINGS_TABLE = os.environ.get("READINGS_TABLE", "BreatheReadings")
STATE_TABLE = os.environ.get("STATE_TABLE", "BreatheState")
ALERT_TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")
KID_NAMES = json.loads(os.environ.get("KID_NAMES", '{"kid-001": "Jayden"}'))

# Risk rule (keep in sync with the device and the build plan)
TVOC_YELLOW = 220          # ppb
TVOC_RED = 661             # ppb, red = above 660
HUMIDITY_BUMP = 60         # % humidity bumps risk up one level
PUFFS_BUMP = 2             # 2+ puffs in 24 h bumps risk up one level
ALERT_COOLDOWN_MS = 10 * 60 * 1000
DAY_MS = 24 * 60 * 60 * 1000
LEVELS = ["green", "yellow", "red"]

dynamodb = boto3.resource("dynamodb")
readings = dynamodb.Table(READINGS_TABLE)
states = dynamodb.Table(STATE_TABLE)
sns = boto3.client("sns")


def _plain(obj):
    """json.dumps helper: turn DynamoDB Decimals back into int/float."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def to_python(obj):
    return json.loads(json.dumps(obj, default=_plain))


def to_ddb(obj):
    """DynamoDB needs Decimal instead of float."""
    return json.loads(json.dumps(obj, default=_plain), parse_float=Decimal)


def num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score(latest, puff_count):
    """Return (risk, reasons). This is a demo heuristic, not a clinical score."""
    tvoc = num(latest.get("tvoc"))
    if tvoc is None:
        level = 0
    elif tvoc >= TVOC_RED:
        level = 2
    elif tvoc >= TVOC_YELLOW:
        level = 1
    else:
        level = 0

    reasons = []
    humidity = num(latest.get("humidity"))
    if humidity is not None and humidity > HUMIDITY_BUMP:
        reasons.append("humidity over 60%")
    if puff_count >= PUFFS_BUMP:
        reasons.append(f"{puff_count} inhaler puffs in 24 hours")
    if reasons:
        level = min(level + 1, 2)
    return LEVELS[level], reasons


def send_alert(device_id, latest, reasons):
    name = KID_NAMES.get(device_id, device_id)
    tvoc = latest.get("tvoc", "?")
    extra = f" ({', '.join(reasons)})" if reasons else ""
    message = (
        f"BreatheDetroit alert: the air in {name}'s room is RED. "
        f"VOCs are at {tvoc} ppb{extra}. "
        f"Open a window, move away from sprays or fumes, and keep {name}'s inhaler close."
    )
    sns.publish(TopicArn=ALERT_TOPIC_ARN, Subject=f"Air quality alert for {name}", Message=message)


def lambda_handler(event, context):
    print("event:", json.dumps(event))
    device_id = event.get("deviceId")
    if not device_id:
        return {"ok": False, "error": "message has no deviceId"}

    is_puff = event.get("event") == "puff" or event.get("kind") == "puff"
    now_ms = int(time.time() * 1000)

    state = to_python(states.get_item(Key={"deviceId": device_id}).get("Item") or {"deviceId": device_id})
    puff_times = [t for t in state.get("puffTimes", []) if now_ms - t < DAY_MS]
    latest = state.get("latest", {})

    if is_puff:
        puff_times.append(now_ms)
        item = {"deviceId": device_id, "ts": now_ms, "kind": "puff", "source": event.get("source", "device")}
    else:
        latest = {k: event[k] for k in ("tvoc", "eco2", "tempC", "humidity") if event.get(k) is not None}
        item = {"deviceId": device_id, "ts": now_ms, "kind": "reading", **latest}

    risk, reasons = score(latest, len(puff_times))
    item["risk"] = risk
    readings.put_item(Item=to_ddb(item))

    last_alert = state.get("lastAlertMs", 0)
    alerted = False
    if risk == "red" and ALERT_TOPIC_ARN and now_ms - last_alert >= ALERT_COOLDOWN_MS:
        try:
            send_alert(device_id, latest, reasons)
            last_alert = now_ms
            alerted = True
        except Exception as exc:  # never lose the reading because an alert failed
            print("SNS publish failed:", repr(exc))

    state.update(
        {
            "name": KID_NAMES.get(device_id, device_id),
            "latest": latest,
            "risk": risk,
            "reasons": reasons,
            "puffTimes": puff_times,
            "lastAlertMs": last_alert,
            "updatedMs": now_ms,
        }
    )
    states.put_item(Item=to_ddb(state))
    return {"ok": True, "risk": risk, "alerted": alerted}
