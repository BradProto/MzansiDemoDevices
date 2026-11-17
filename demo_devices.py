"""Standalone SSS1/SSS2 live simulator, Python 3.10+, no dependencies.

Preview: python stores_live_private.py
Run continuously: python -u stores_live_private.py --send
Run two hours: python -u stores_live_private.py --send --duration-minutes 120
Contains production device keys; share privately. No historical writes.
"""

import argparse
import json
import logging
import math
import signal
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

API_URL = "https://devices.mzansisense.co.za"
STOP = threading.Event()
KEYS = {
    "SSS1": {
        "doors": "XamF_3CVLW0ykrKqwa0ytU1WOYTvuZ6CES7VqhOChkc",
        "fridges": "SsS3s9_A1zaooJtQQ6CSKo89kI-H-GoelT3Gg2QvS_Y",
        "freezers": "7gRu6KjhCV2dLAEvatmpZaF74I7Oxj8tazkF6jH6WS8",
        "humidity": "zr_SNyJWbGLXD1BnOUHXEt5H9-Lto_MTImcFLXnUIHw",
        "alarm": "5OOeAgc4EPV_mwEb9UZTRTDwrPK4txvWL3U28FD6LCU",
        "solar": "ERwvk9blZ-86mpwyuLXhX2I2PhYcyTGyHMpS88jNbWc",
    },
    "SSS2": {
        "fridges": "cA-yAbL35ldSLJKbYTDZWkedOaJkIIUorAxzmI0ya_8",
        "freezers": "M0xVTfqpJE9ZnTMzF-k8Xy0mgvkyHBEC-ajeHhtnrw8",
        "doors": "BAoi46IACO7etDq9x1uVhoUeZLO_nVP6mhq-fJrePtk",
        "solar": "AfPQBMfAI0LQCoLdqlXt62iPJ2-JWO6sDKoiM54GnDk",
        "alarm": "sgdPvs1H1a_dPzWqGFqSAGqJ2Z-nNCoytP5pPMQ45r8",
        "humidity": "JJ3E2NMaWTm0yeLvKWGVmXsB8Qns2oy39-6A4SyXLhs",
    },
}

DEVICE_IDS = {
    'SSS1': {
        'doors': '1b4f0224-3c02-40d8-bf16-326b22bdf9db', 
        'fridges': 'f09bc9ef-1cf2-4111-8135-0d0f74634e9f', 
        'freezers': 'cabe7565-c45b-46ed-a3c9-32c84461f328', 
        'humidity': '28855355-712c-4672-92cb-714e21356e89', 
        'alarm': 'da1d5984-c2fa-48af-937e-1241bcf6e350', 
        'solar': '95a846b9-ab9b-4370-b410-e9b9438272f6'}, 
    'SSS2': {
        'doors': '5f3901ab-6fba-40e9-87a8-70e111a53a20', 
        'fridges': '46246741-058c-4e6a-8ce1-3ceed5ba8550', 
        'freezers': '25812d9c-9f7c-4a14-8c77-7161047471a0', 
        'humidity': '62c612c0-944b-43d9-a16d-513d01ef7930', 
        'alarm': '8e48a9c4-9343-4908-9f97-095bfebf87ec', 
        'solar': '434f46e2-0aee-4b33-9b81-d8d58c863b09'}
}


def values_sss1(kind, stamp, elapsed_minutes):
    """Return typed tag values using South African hours and repeatable cycles.

    Door true means open; motion true means activity. Solar battery power is
    positive on discharge, negative on charge; grid power is positive on import.
    Freezer 6 has periodic reporting gaps, not whole-device offline status.
    """
    local = stamp + timedelta(hours=2)
    hour = local.hour + local.minute / 60
    opened = 7 <= hour < 20
    minute = int(stamp.timestamp() // 60)
    cycle = elapsed_minutes % 60
    if kind == "doors":
        return {f"door_{i}": bool(opened and minute % period < duration)
                for i, period, duration in [(1, 7, 2), (2, 53, 8), (3, 23, 2), (4, 41, 1)]}
    if kind in ("fridges", "freezers"):
        result = {}
        count = 10 if kind == "fridges" else 6
        for i in range(1, count + 1):
            if kind == "freezers" and i == 6 and 35 <= cycle < 45:
                continue
            wave = math.sin(minute / 9 + i)
            warm = max(0, 1 - abs(cycle - (20 if i == 1 else 45)) / 10)
            base = 3.2 + i * .08 if kind == "fridges" else -21 + i * .15
            excursion = (9 if kind == "fridges" else 13) * warm if i <= 2 else 0
            tag = i if kind == "fridges" else i + 10
            result[f"temp_{tag}"] = round(base + .6 * wave + excursion, 2)
        return result
    if kind == "humidity":
        return {"humidity_1": round(57 + 6 * math.sin(minute / 80), 2),
                "humidity_2": round(46 + 4 * math.sin(minute / 100), 2)}
    if kind == "alarm":
        return {"motion_sensor": bool(opened and minute % 13 < 2)}
    sun = max(0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0
    production = 6000 * sun
    load = (3800 if opened else 2100) + 150 * math.sin(minute / 15)
    battery = 700 if production < load else -min(1500, production - load)
    return {"battery_level": round(65 + 20 * math.sin((hour - 9) * math.pi / 12), 2),
            "outside_tempature": round(20 + 7 * math.sin((hour - 8) * math.pi / 12), 2),
            "solar_production": round(production, 2),
            "inverter_battery_power": round(battery, 2),
            "inverter_grid_power": round(load - production - battery, 2),
            "inverter_load_power": round(load, 2)}


def values_sss2(kind, stamp, elapsed_minutes):
    """Return typed tag values using South African hours and repeatable cycles.

    Door true means open; motion true means activity. Solar battery power is
    positive on discharge, negative on charge; grid power is positive on import.
    Freezer 6 has periodic reporting gaps, not whole-device offline status.
    """
    local = stamp + timedelta(hours=2)
    hour = local.hour + local.minute / 60
    opened = 7 <= hour < 20
    minute = int(stamp.timestamp() // 60)
    cycle = elapsed_minutes % 60
    if kind == "doors":
        return {f"door{i}": bool(opened and minute % period < duration)
                for i, period, duration in [(2, 7, 2), (4, 53, 8), (3, 23, 2), (1, 41, 1)]}
    if kind in ("fridges", "freezers"):
        result = {}
        count = 10 if kind == "fridges" else 6
        for i in range(1, count + 1):
            if kind == "freezers" and i == 6 and 35 <= cycle < 45:
                continue
            wave = math.sin(minute / 9 + i)
            warm = max(0, 1 - abs(cycle - (20 if i == 1 else 45)) / 10)
            base = 3.2 + i * .08 if kind == "fridges" else -21 + i * .15
            excursion = (9 if kind == "fridges" else 13) * warm if i <= 2 else 0
            tag = i if kind == "fridges" else i + 10
            result[f"temp{tag}"] = round(base + .6 * wave + excursion, 2)
        return result
    if kind == "humidity":
        return {"humidity1": round(57 + 6 * math.sin(minute / 80), 2),
                "humidity2": round(46 + 4 * math.sin(minute / 100), 2)}
    if kind == "alarm":
        return {"motion_sensor_1": bool(opened and minute % 13 < 2)}
    sun = max(0, math.sin(math.pi * (hour - 6) / 12)) if 6 <= hour <= 18 else 0
    production = 6000 * sun
    load = (3800 if opened else 2100) + 150 * math.sin(minute / 15)
    battery = 700 if production < load else -min(1500, production - load)
    return {"battery_level_2": round(65 + 20 * math.sin((hour - 9) * math.pi / 12), 2),
            "outside_tempature_2": round(20 + 7 * math.sin((hour - 8) * math.pi / 12), 2),
            "solar_production_2": round(production, 2),
            "inverter_battery_power_2": round(battery, 2),
            "inverter_grid_power_2": round(load - production - battery, 2),
            "inverter_load_power_2": round(load, 2)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward device credentials through redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def payload(store, kind, stamp):
    """Build current UTC readings with independent Store 2 anomaly timing."""
    phase = int(stamp.timestamp() // 60) + (17 if store == "SSS2" else 0)
    generator = values_sss1 if store == "SSS1" else values_sss2
    return {"readings": [
        {"tag_name": tag, "value": value, "recorded_at": stamp.isoformat()}
        for tag, value in generator(kind, stamp, phase).items()
    ]}


def send_one(store, kind, stamp):
    """Isolate device failures; send a fresh sample next cycle without replaying.

    A timeout can occur after persistence, so never immediately retry that sample.
    Return success for monitoring while keeping credentials out of log output.
    """
    body = payload(store, kind, stamp)
    request = urllib.request.Request(
        f"{API_URL}/api/mzansi-sense/device-readings/{DEVICE_IDS[store][kind]}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEYS[store][kind]}",
                 "Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=20) as response:
            result = json.load(response)
        if not isinstance(result, dict) or result.get("saved") != len(body["readings"]):
            logging.error("%s %s: unexpected API saved count", store, kind)
            return False
    except urllib.error.HTTPError as error:
        try:
            detail = str(json.loads(error.read(8192)).get("detail", "No detail"))
        except (ValueError, AttributeError):
            detail = "No JSON error detail"
        for secrets in KEYS.values():
            for key in secrets.values():
                detail = detail.replace(key, "[redacted]")
        logging.error("%s %s: HTTP %s: %s", store, kind, error.code, detail)
        return False
    except (OSError, ValueError, TimeoutError):
        logging.error("%s %s: connection/response failed; next cycle uses a new sample", store, kind)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", action="store_true", help="Send live production readings")
    parser.add_argument("--duration-minutes", type=float, help="Default: run until stopped")
    args = parser.parse_args()
    if args.duration_minutes is not None and (not math.isfinite(args.duration_minutes) or args.duration_minutes <= 0):
        parser.error("Duration must be a finite number greater than zero")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    devices = [(store, kind) for store in DEVICE_IDS for kind in DEVICE_IDS[store]]
    if not args.send:
        stamp = datetime.now(timezone.utc)
        for store, kind in devices:
            print(store, kind, DEVICE_IDS[store][kind], json.dumps(payload(store, kind, stamp)))
        print("DRY RUN: no requests sent. Use --send to run continuously.")
        return
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: STOP.set())
    started = time.monotonic()
    deadline = started + args.duration_minutes * 60 if args.duration_minutes else math.inf
    next_tick = started
    logging.info("Sending one device at a time, at least 5 seconds between starts; production alerts may fire")
    index = 0
    successes = 0
    while not STOP.is_set() and time.monotonic() < deadline:
        # Schedule from the actual start: slow requests never cause catch-up bursts.
        request_started = time.monotonic()
        store, kind = devices[index]
        stamp = datetime.now(timezone.utc)
        successes += bool(send_one(store, kind, stamp))
        index += 1
        if index == len(devices):
            logging.info("Cycle complete: %s/%s devices accepted", successes, len(devices))
            index = 0
            successes = 0
        next_tick = request_started + 5
        STOP.wait(max(0, min(next_tick, deadline) - time.monotonic()))
    logging.info("Stopped")


if __name__ == "__main__":
    main()
