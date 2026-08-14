#!/usr/bin/env python3
"""Places outbound test calls against the target number via the Twilio REST API.

Recording is triggered here via the REST API (record=True,
recording_channels="dual"), not in TwiML - this is what correctly captures
the agent's audio and our injected bot audio in separate channels.

Usage:
    python call_trigger.py <scenario_id>
    python call_trigger.py --all
    python call_trigger.py --list
"""
import argparse
import os
import sys
import time

from dotenv import load_dotenv
from twilio.rest import Client

from scenarios import SCENARIOS

load_dotenv()

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER")
TARGET_TEST_NUMBER = os.environ.get("TARGET_TEST_NUMBER")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

DONE_STATUSES = {"completed", "busy", "failed", "no-answer", "canceled"}


def place_call(client: Client, scenario_id: str):
    connect_url = f"{PUBLIC_BASE_URL}/connect-call?scenario={scenario_id}"
    call = client.calls.create(
        to=TARGET_TEST_NUMBER,
        from_=TWILIO_FROM_NUMBER,
        url=connect_url,
        record=True,
        recording_channels="dual",
    )
    print(f"placed call {call.sid} for scenario '{scenario_id}' ({SCENARIOS[scenario_id]['name']})")
    return call


def wait_for_completion(client: Client, call_sid: str, poll_seconds: int = 10) -> str:
    while True:
        status = client.calls(call_sid).fetch().status
        if status in DONE_STATUSES:
            print(f"call {call_sid} finished with status: {status}")
            return status
        time.sleep(poll_seconds)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", help="scenario id from scenarios.py")
    parser.add_argument(
        "--all", action="store_true", help="run every scenario in sequence, one call at a time"
    )
    parser.add_argument("--list", action="store_true", help="list available scenario ids and exit")
    args = parser.parse_args()

    if args.list:
        for scenario_id, scenario in SCENARIOS.items():
            print(f"{scenario_id}: {scenario['name']}")
        return

    if not args.all and not args.scenario:
        parser.error("pass a scenario id, or use --all / --list")

    if args.scenario and args.scenario not in SCENARIOS:
        parser.error(f"unknown scenario '{args.scenario}'. run --list to see options")

    missing = [
        name
        for name, value in [
            ("TWILIO_ACCOUNT_SID", TWILIO_ACCOUNT_SID),
            ("TWILIO_AUTH_TOKEN", TWILIO_AUTH_TOKEN),
            ("TWILIO_FROM_NUMBER", TWILIO_FROM_NUMBER),
            ("TARGET_TEST_NUMBER", TARGET_TEST_NUMBER),
            ("PUBLIC_BASE_URL", PUBLIC_BASE_URL),
        ]
        if not value
    ]
    if missing:
        sys.exit(f"missing required env vars: {', '.join(missing)}")

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    scenario_ids = list(SCENARIOS) if args.all else [args.scenario]

    for scenario_id in scenario_ids:
        call = place_call(client, scenario_id)
        wait_for_completion(client, call.sid)


if __name__ == "__main__":
    main()
