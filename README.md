# pgai-voice-challenge

A voice-bot testing tool. It places outbound calls via Twilio to a target
test number, bridges live audio to OpenAI's Realtime API so it can hold a
natural spoken conversation playing a "patient" persona, records and
transcribes each call, and leaves behind per-call transcripts and audio
for writing up a bug report on the other side's responses.

See [ARCHITECTURE.md](ARCHITECTURE.md) for how it's built and why.

## Prerequisites

- Python 3.10+
- A Twilio account with a phone number capable of outbound calls
- An OpenAI API key with access to the Realtime API
- A way to expose your local server to the internet for Twilio's webhooks
  (e.g. [ngrok](https://ngrok.com/)) - or a real deployed host

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:

- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` - from your Twilio console
- `TARGET_TEST_NUMBER` - the number you're testing (the voice bot under test)
- `OPENAI_API_KEY` - your OpenAI key
- `OPENAI_REALTIME_MODEL` - defaults to `gpt-realtime-mini` to keep cost down across many test calls; use `gpt-realtime` for higher quality
- `PUBLIC_BASE_URL` - the public URL Twilio can reach your server at (your ngrok URL, or your deployed host)

## Running

1. Start the server:

   ```bash
   uvicorn server:app --reload --port 8000
   ```

2. In another terminal, expose it publicly and point `PUBLIC_BASE_URL` in
   `.env` at that address:

   ```bash
   ngrok http 8000
   ```

3. Confirm it's up:

   ```bash
   curl https://your-ngrok-url.ngrok-free.app/health
   ```

## Placing test calls

List available scenarios:

```bash
python call_trigger.py --list
```

Run one scenario:

```bash
python call_trigger.py 6_sunday_appointment_test
```

Run all 10 scenarios back to back (each call runs to completion before the
next one starts):

```bash
python call_trigger.py --all
```

Each call gets recorded (dual-channel, agent and bot on separate tracks)
and its transcript is written live to `transcripts/<CallSid>.json` as the
call happens.

## Pulling down recordings

Once calls have finished:

```bash
python download_recordings.py
```

This saves `recordings/<CallSid>.mp3` for every call not already
downloaded, matching the `CallSid` used in the transcript filename so a
call's audio and transcript are easy to line up.

## Project layout

```
server.py              FastAPI app: Twilio webhook + websocket bridge to OpenAI Realtime
scenarios.py            10 patient persona/scenario definitions
call_trigger.py          Places outbound calls via the Twilio REST API
download_recordings.py    Pulls finished recordings as MP3
bug_reports/BUGS.md      Bug report written up after reviewing real calls
transcripts/             Per-call JSON transcripts
recordings/              Per-call MP3s
```
