"""Round E chat API. Main thread (Task 3) ships the conversational core;
Subagent A (Tasks 4–5) extends history/resumption on the durable store.

All endpoints sit behind the ``global.chat`` feature flag — OFF means these
refuse with 409 BEFORE any query runs, not merely a hidden button (6.8).
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.chat.service import stream_message
from app.chat.store import get_chat_store
from app.flags.registry import require_feature

router = APIRouter(prefix="/api/chat", tags=["chat"],
                   dependencies=[Depends(require_feature("global.chat"))])


class MessageRequest(BaseModel):
    text: str
    page_context: dict | None = None


class ConversationCreate(BaseModel):
    title: str = ""


class TitleUpdate(BaseModel):
    title: str


@router.post("/conversations")
def create_conversation(body: ConversationCreate | None = None) -> dict:
    return get_chat_store().create_conversation((body.title if body else "") or "")


@router.get("/conversations")
def list_conversations() -> dict:
    return {"conversations": get_chat_store().list_conversations()}


@router.get("/conversations/{conversation_id}")
def conversation_detail(conversation_id: str) -> dict:
    store = get_chat_store()
    conv = store.conversation(conversation_id)
    if conv is None:
        raise HTTPException(404, f"unknown conversation '{conversation_id}'")
    return {**conv, "messages": store.conversation_messages(conversation_id)}


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: TitleUpdate) -> dict:
    row = get_chat_store().set_title(conversation_id, body.title)
    if row is None:
        raise HTTPException(404, f"unknown conversation '{conversation_id}'")
    return row


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    if not get_chat_store().delete_conversation(conversation_id):
        raise HTTPException(404, f"unknown conversation '{conversation_id}'")
    return {"deleted": conversation_id}


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, body: MessageRequest) -> StreamingResponse:
    """SSE stream: guardrail -> step* -> answer -> done. The reasoning steps
    stream AS THEY HAPPEN (spec 3.7) — they are the actual tool calls made."""
    if get_chat_store().conversation(conversation_id) is None:
        raise HTTPException(404, f"unknown conversation '{conversation_id}'")

    def _frames():
        try:
            for event in stream_message(conversation_id, body.text,
                                        body.page_context):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001 — the stream must end honestly
            yield ("data: " + json.dumps(
                {"event": "error", "detail": f"{type(exc).__name__}: {exc}"})
                + "\n\n")

    return StreamingResponse(_frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
