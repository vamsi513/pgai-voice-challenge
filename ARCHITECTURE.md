# Architecture

## What this is

An outbound caller that plays a patient persona on the phone with a voice
bot under test, using OpenAI's Realtime API for speech in and out, Twilio
for the actual phone call, and a thin FastAPI server gluing the two
together over websockets.

Call flow: `call_trigger.py` places a call via the Twilio REST API with
`record=True` → Twilio dials the target number → once answered, Twilio
POSTs to `/connect-call`, which returns `<Connect><Stream>` TwiML pointing
back at our own `/media-stream` websocket → Twilio opens that websocket
and starts streaming G.711 μ-law audio both ways → the server relays that
audio to/from a second websocket connection to the OpenAI Realtime API,
translating event shapes between the two protocols.

## Why the Realtime API over chained STT → LLM → TTS

A chained pipeline (Whisper → GPT → a TTS engine) gives more control over
each stage individually, but adds a full round trip of latency per turn
and makes barge-in awkward - you'd need to explicitly cancel three
separate systems mid-flight instead of one. Phone conversations are
latency-sensitive enough that the extra hops are noticeable. The Realtime
API keeps speech-to-speech in one model and one connection, with turn
detection and interruption handling built in (`input_audio_buffer.speech_started`),
which is a closer match to how an actual phone conversation behaves. The
tradeoff is less visibility into intermediate text unless you also
request transcript events, which is why the server explicitly asks for
`session.audio.input.transcription` and reads the `response.output_audio_transcript`
events rather than only the audio.

## Why `<Connect><Stream>` and not `<Start><Stream>`

`<Start><Stream>` opens a one-way stream - Twilio sends the server audio
but the server can't send audio back on it. `<Connect><Stream>` bridges
the stream bidirectionally into the call itself, which is required for
the bot to actually speak. Using `<Start>` here would have looked correct
in testing (the bot would "hear" the other side) while silently being
unable to talk back.

## Why Twilio

Twilio Voice plus Media Streams is the most direct path to programmatic
outbound calling with real-time audio access - REST API call creation,
built-in dual-channel recording, and a websocket media stream that
requires no telephony infrastructure of our own. The alternatives (a SIP
trunk directly to a carrier, or another CPaaS) mostly trade Twilio's
higher per-minute cost for more setup work, which isn't worth it for
~10-15 test calls.

## Recording

Recording is triggered via the REST API call (`record=True`,
`recording_channels="dual"`) rather than a `<Record>` TwiML verb, because
the REST API's dual-channel option is what puts the agent's audio and our
injected bot audio on separate channels in the same file - a TwiML
`<Record>` inside the stream would instead capture a single mixed track
and wouldn't run for the call's full duration.

## Steering behavior

Each persona prompt in `scenarios.py` explicitly instructs the model to
steer the conversation back toward its scenario goal if the agent's
response derails it - this isn't just "have a natural chat," it's a
directed test case with an intended outcome the persona actively works
toward.
