import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from twilio.twiml.voice_response import Connect, VoiceResponse

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pgai-voice")

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

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
