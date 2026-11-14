"""breathe-api Lambda, behind an API Gateway HTTP API.

Routes:
  GET /status/{deviceId}   latest reading, risk, puffs in 24 h, last 60 readings
  GET /kids                every kid, red first (nurse view)
  GET /summary/{deviceId}  plain-English daily summary from Amazon Bedrock (stretch goal)

Runtime: Python 3.12. Handler: lambda_function.lambda_handler. Timeout: 15 seconds.
Environment variables:
  READINGS_TABLE  BreatheReadings
  STATE_TABLE     BreatheState
  MODEL_ID        (optional) a Bedrock model or inference profile ID you have access to
"""
import json
import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

READINGS_TABLE = os.environ.get("READINGS_TABLE", "BreatheReadings")
STATE_TABLE = os.environ.get("STATE_TABLE", "BreatheState")
MODEL_ID = os.environ.get("MODEL_ID", "")

DAY_MS = 24 * 60 * 60 * 1000
ONLINE_WINDOW_MS = 30 * 1000
RISK_ORDER = {"red": 0, "yellow": 1, "green": 2}
HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}

dynamodb = boto3.resource("dynamodb")
readings = dynamodb.Table(READINGS_TABLE)
states = dynamodb.Table(STATE_TABLE)


def _plain(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    raise TypeError(f"Not JSON serializable: {type(obj)}")


def to_python(obj):
    return json.loads(json.dumps(obj, default=_plain))


def respond(status, body):
    return {"statusCode": status, "headers": HEADERS, "body": json.dumps(body, default=_plain)}


def now_ms():
    return int(time.time() * 1000)


def kid_summary(state):
    """Shape one BreatheState item for the API."""
    state = to_python(state)
    now = now_ms()
    puffs = [t for t in state.get("puffTimes", []) if now - t < DAY_MS]
    updated = state.get("updatedMs", 0)
    return {
        "deviceId": state["deviceId"],
        "name": state.get("name", state["deviceId"]),
        "risk": state.get("risk", "green"),
        "reasons": state.get("reasons", []),
        "latest": state.get("latest", {}),
        "puffs24h": len(puffs),
        "lastPuffMs": max(puffs) if puffs else None,
        "updatedMs": updated,
        "online": now - updated < ONLINE_WINDOW_MS,
    }


def get_status(device_id):
    item = states.get_item(Key={"deviceId": device_id}).get("Item")
    if not item:
        return None
    result = kid_summary(item)
    resp = readings.query(
        KeyConditionExpression=Key("deviceId").eq(device_id),
        ScanIndexForward=False,  # newest first
        Limit=150,
    )
    items = to_python(resp.get("Items", []))
    history = [
        {k: i.get(k) for k in ("ts", "tvoc", "eco2", "tempC", "humidity", "risk")}
        for i in items
        if i.get("kind") == "reading"
    ][:60]
    history.reverse()  # oldest first, for the chart
    result["history"] = history
    return result


def list_kids():
    items = states.scan().get("Items", [])
    kids = [kid_summary(i) for i in items]
    kids.sort(key=lambda k: (RISK_ORDER.get(k["risk"], 3), -k["puffs24h"]))
    return kids


def summarize(device_id):
    if not MODEL_ID:
        return {"summary": "Bedrock summary is off. Set MODEL_ID on the breathe-api Lambda to turn it on."}
    status = get_status(device_id)
    if not status:
        return {"summary": "No data for this device yet."}

    tvocs = [h["tvoc"] for h in status["history"] if h.get("tvoc") is not None]
    facts = {
        "name": status["name"],
        "current_risk": status["risk"],
        "risk_reasons": status["reasons"],
        "latest": status["latest"],
        "inhaler_puffs_last_24h": status["puffs24h"],
        "recent_voc_ppb_avg": round(sum(tvocs) / len(tvocs)) if tvocs else None,
        "recent_voc_ppb_max": max(tvocs) if tvocs else None,
        "voc_bands_ppb": "green under 220, yellow 220-660, red above 660",
    }
    prompt = (
        "You write short, friendly updates for the parent of a child with asthma in Detroit. "
        "Using ONLY the data below, write 3 short sentences: how the indoor air has been, "
        "any pattern with inhaler use, and one practical tip (for example ventilation or avoiding sprays). "
        "Do not diagnose or give medical advice. If inhaler use is frequent, suggest checking in with "
        "the child's doctor.\n\nData: " + json.dumps(facts)
    )
    bedrock = boto3.client("bedrock-runtime")
    resp = bedrock.converse(
        modelId=MODEL_ID,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": 250, "temperature": 0.3},
    )
    text = resp["output"]["message"]["content"][0]["text"]
    return {"summary": text.strip()}


def lambda_handler(event, context):
    route = event.get("routeKey", "")
    params = event.get("pathParameters") or {}
    try:
        if route == "GET /kids":
            return respond(200, list_kids())
        if route == "GET /status/{deviceId}":
            status = get_status(params.get("deviceId", ""))
            if status is None:
                return respond(404, {"error": "no data for this device yet"})
            return respond(200, status)
        if route == "GET /summary/{deviceId}":
            return respond(200, summarize(params.get("deviceId", "")))
        return respond(404, {"error": f"unknown route: {route}"})
    except Exception as exc:
        print("ERROR:", repr(exc))
        return respond(500, {"error": str(exc)})
