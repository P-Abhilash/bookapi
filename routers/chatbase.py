# routers/chatbase.py
from fastapi import APIRouter, Request
import os, httpx

router = APIRouter(prefix="/chatbase", tags=["Chatbase"])

CHATBASE_API_KEY = os.getenv("CHATBASE_API_KEY")
CHATBASE_AGENT_ID = os.getenv("CHATBASE_AGENT_ID")

@router.post("/message")
async def chatbase_message(request: Request):
    data = await request.json()
    user_message = data.get("message")

    payload = {
        "agent_id": CHATBASE_AGENT_ID,
        "messages": [{"role": "user", "content": user_message}]
    }

    headers = {
        "Authorization": f"Bearer {CHATBASE_API_KEY}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://www.chatbase.co/api/v1/chat",
            json=payload,
            headers=headers
        )
        return response.json()
