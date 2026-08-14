import asyncio
import base64
import json
import logging
import os

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, WebSocket
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import Connect, VoiceResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pgai-voice")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime-mini")
OPENAI_REALTIME_URL = f"wss://api.openai.com/v1/realtime?model={OPENAI_REALTIME_MODEL}"

# placeholder persona used until scenarios.py exists (build stage 7) - lets us
# prove the audio path works end to end with a single hardcoded test case
DEFAULT_INSTRUCTIONS = (
    "You are Alex, a patient calling a medical office to schedule a routine "
    "check-up appointment. You are friendly and speak naturally, like a real "
    "person on the phone, not a script. Keep your turns short. Your goal is "
    "to book an appointment sometime in the next two weeks. If the person "
    "you're speaking with goes off topic or doesn't move the conversation "
    "toward scheduling, politely steer the conversation back toward booking "
    "the appointment."
)

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
    scenario_id = request.query_params.get("scenario", "default")
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

    openai_ws = await websockets.connect(
        OPENAI_REALTIME_URL,
        additional_headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
    )

    try:
        await openai_ws.send(json.dumps(build_session_update(DEFAULT_INSTRUCTIONS)))

        async def twilio_to_openai():
            nonlocal stream_sid, scenario_id, call_id
            async for raw in twilio_ws.iter_text():
                data = json.loads(raw)
                event = data.get("event")

                if event == "start":
                    stream_sid = data["start"]["streamSid"]
                    params = data["start"].get("customParameters", {})
                    scenario_id = params.get("scenario", "default")
                    call_id = params.get("call_id", "")
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
                elif event_type == "error":
                    logger.error("openai realtime error: %s", event)

        await asyncio.gather(twilio_to_openai(), openai_to_twilio())
    except WebSocketDisconnect:
        logger.info("twilio websocket disconnected")
    finally:
        await openai_ws.close()
