#!/usr/bin/env python3
"""Downloads finished call recordings from Twilio as MP3 files.

Recordings are saved as recordings/<CallSid>.mp3 - the same CallSid used
for the matching transcript in transcripts/, so a call's audio and
transcript are easy to line up.

Usage:
    python download_recordings.py              # download every recording not already saved locally
    python download_recordings.py <call_sid>    # download the recording for one specific call
"""
import os
import sys

import requests
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")


def download_recording(recording):
    out_path = os.path.join(RECORDINGS_DIR, f"{recording.call_sid}.mp3")
    if os.path.exists(out_path):
        print(f"skipping {recording.call_sid}, already downloaded")
        return

    media_url = f"https://api.twilio.com{recording.uri.replace('.json', '.mp3')}"
    resp = requests.get(media_url, auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN))
    resp.raise_for_status()

    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(resp.content)
    print(f"downloaded {out_path} ({len(resp.content)} bytes)")


def main():
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        sys.exit("missing required env vars: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN")

    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

    call_sid = sys.argv[1] if len(sys.argv) > 1 else None
    recordings = client.recordings.list(call_sid=call_sid) if call_sid else client.recordings.list()

    if not recordings:
        print("no recordings found")
        return

    for recording in recordings:
        download_recording(recording)


if __name__ == "__main__":
    main()
