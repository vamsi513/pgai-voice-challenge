import asyncio
import json
import logging
import os
import time
from pathlib import Path

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import Connect, VoiceResponse

from scenarios import get_scenario

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pgai-voice")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-mini")
OPENAI_REALTIME_URL = f"wss://api.openai.com/v1/realtime?model={OPENAI_REALTIME_MODEL}"

TRANSCRIPTS_DIR = Path(__file__).parent / "transcripts"

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/connect-call")
async def connect_call(request: Request):
    """Twilio calls this webhook once the outbound call is answered.

    Returns TwiML that bridges the call's audio to our websocket media
    stream. Must use <Connect><Stream>, not <Start><Stream> - Start is
    receive-only and the bot would never be able to speak.
    """
    scenario_id = request.query_params.get("scenario", "1_simple_appointment")
    call_id = request.query_params.get("call_id", "")

    stream_url = f"{PUBLIC_BASE_URL.replace('https://', 'wss://').replace('http://', 'ws://')}/media-stream"

    response = VoiceResponse()
    connect = Connect()
    stream = connect.stream(url=stream_url)
    stream.parameter(name="scenario", value=scenario_id)
    stream.parameter(name="call_id", value=call_id)
    response.append(connect)

    return Response(content=str(response), media_type="application/xml")


def build_session_update(instructions: str) -> dict:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "instructions": instructions,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "turn_detection": {
                        "type": "server_vad",
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 500,
                    },
                    "transcription": {"model": "whisper-1"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": "marin",
                },
            },
        },
    }


class Transcript:
    """Accumulates a call's turns and writes them to disk after every turn.

    Writing on every turn (not just at the end) means a transcript is still
    usable on disk if the call drops or the server crashes mid-conversation.
    """

    def __init__(self, call_id: str, scenario_id: str):
        self.call_id = call_id or f"test-{int(time.time())}"
        self.scenario_id = scenario_id
        self.turns = []
        self.path = TRANSCRIPTS_DIR / f"{self.call_id}.json"

    def add_turn(self, role: str, text: str):
        if not text:
            return
        self.turns.append({"role": role, "text": text, "ts": time.time()})
        self.save()

    def save(self):
        self.path.write_text(
            json.dumps(
                {
                    "call_id": self.call_id,
                    "scenario_id": self.scenario_id,
                    "turns": self.turns,
                },
                indent=2,
            )
        )


@app.websocket("/media-stream")
async def media_stream(twilio_ws: WebSocket):
    """Bridges audio between a Twilio <Stream> and the OpenAI Realtime API.

    Twilio sends/receives base64 G.711 u-law audio over its own websocket
    protocol (start/media/stop events). We relay raw audio bytes in both
    directions and translate event shapes between the two APIs.
    """
    await twilio_ws.accept()

    stream_sid = None
    scenario_id = "default"
    call_id = ""
    transcript = None
    bot_transcript_buffer = ""

    openai_ws = await websockets.connect(
        OPENAI_REALTIME_URL,
        additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
    )

    try:
        async def twilio_to_openai():
            nonlocal stream_sid, scenario_id, call_id, transcript
            async for raw in twilio_ws.iter_text():
                data = json.loads(raw)
                event = data.get("event")

                if event == "start":
                    stream_sid = data["start"]["streamSid"]
                    params = data["start"].get("customParameters", {})
                    scenario_id = params.get("scenario", "default")
                    call_id = params.get("call_id", "")
                    transcript = Transcript(call_id, scenario_id)
                    scenario = get_scenario(scenario_id)
                    await openai_ws.send(
                        json.dumps(build_session_update(scenario["instructions"]))
                    )
                    logger.info(
                        "stream started sid=%s scenario=%s call_id=%s",
                        stream_sid,
                        scenario_id,
                        call_id,
                    )
                elif event == "media":
                    await openai_ws.send(
                        json.dumps(
                            {
                                "type": "input_audio_buffer.append",
                                "audio": data["media"]["payload"],
                            }
                        )
                    )
                elif event == "stop":
                    logger.info("stream stopped sid=%s", stream_sid)
                    break

        async def openai_to_twilio():
            nonlocal bot_transcript_buffer
            async for raw in openai_ws:
                event = json.loads(raw)
                event_type = event.get("type")

                if event_type == "response.output_audio.delta":
                    await twilio_ws.send_json(
                        {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {"payload": event["delta"]},
                        }
                    )
                elif event_type == "response.output_audio_transcript.delta":
                    bot_transcript_buffer += event.get("delta", "")
                elif event_type == "response.output_audio_transcript.done":
                    if transcript:
                        transcript.add_turn("bot", bot_transcript_buffer.strip())
                    bot_transcript_buffer = ""
                elif event_type == "conversation.item.input_audio_transcription.completed":
                    if transcript:
                        transcript.add_turn("agent", event.get("transcript", "").strip())
                elif event_type == "input_audio_buffer.speech_started":
                    # caller started talking while the bot's audio was still
                    # playing out on the Twilio side - stop the model from
                    # generating more audio and flush what Twilio has queued
                    # so playback stops immediately instead of finishing the
                    # current sentence over the caller
                    logger.info("barge-in detected, clearing playback buffer")
                    await openai_ws.send(json.dumps({"type": "response.cancel"}))
                    await twilio_ws.send_json({"event": "clear", "streamSid": stream_sid})
                elif event_type == "error":
                    logger.error("openai realtime error: %s", event)

        await asyncio.gather(twilio_to_openai(), openai_to_twilio())
    except WebSocketDisconnect:
        logger.info("twilio websocket disconnected")
    finally:
        await openai_ws.close()
