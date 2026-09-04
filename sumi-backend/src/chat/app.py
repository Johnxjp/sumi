"""FastAPI backend of the web chat: one conversation, replies streamed as server-sent events."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import logfire
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.bootstrap import build_agent, register_tools
from src.chat.stream import stream_reply
from src.retrieval.retrieve import get_default_retriever
from src.tools.registry import registry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    get_default_retriever().load_models()
    yield


app = FastAPI(title="sumi chat", lifespan=lifespan)
# Makes the request the root span, so the agent's spans nest underneath it.
logfire.instrument_fastapi(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

register_tools()
# The server's console is its log: print every model turn and tool call.
agent = build_agent(verbose=True)


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
def chat(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        stream_reply(agent, registry.tools, request.message),
        media_type="text/event-stream",
    )


@app.post("/api/reset")
def reset() -> dict[str, bool]:
    agent.clear_conversation_history()
    return {"ok": True}
