import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pgai-voice")

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok"}
