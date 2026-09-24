from fastapi import FastAPI, Header, HTTPException, Cookie
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from app import (
    SQLDumpRAG, LlamaHandler, ConversationState,
    is_greeting, is_academic_query, _name_tokens,
    _append_history,
)
from langfuse_integration import tracker
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

import jwt

app = FastAPI()

# CORS: must list exact origin(s) — a wildcard ("*") cannot be combined with
# allow_credentials=True, and we need credentials on so the browser will
# actually send the httpOnly auth cookie to this API.
# Comma-separated list, e.g. FRONTEND_ORIGIN="http://localhost,http://localhost:80"
_allowed_origins = [
    o.strip() for o in os.environ.get("FRONTEND_ORIGIN", "http://localhost").split(",") if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _verify_token(token: str) -> dict:
    return jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])


def _authenticate(authorization: Optional[str], auth_cookie: Optional[str]) -> dict:
    """Accept the session either via httpOnly cookie (normal browser flow)
    or an Authorization: Bearer header (useful for non-browser/API clients).
    """
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif auth_cookie:
        token = auth_cookie

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        return _verify_token(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token.")

# Load once at startup
rag = SQLDumpRAG("db7.sql")
rag.load()
# Single shared instance for the whole process lifetime — this is what makes
# the persistent MCP session in LlamaHandler actually pay off. Do NOT
# instantiate a new LlamaHandler per-request, or every request pays the
# subprocess-spawn + initialize() cost again.
llama_handler   = LlamaHandler(rag)
use_llm = LlamaHandler.is_available()

# ── "my lecture" / "right now" personalization ─────────────────────────────
IST = ZoneInfo("Asia/Kolkata")

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_RELATIVE_DAY_RE = re.compile(r"\b(today|tonight|tomorrow|yesterday)\b", re.IGNORECASE)
_NOW_RE = re.compile(r"\b(right now|just now|at the moment|currently|now)\b", re.IGNORECASE)
_FIRST_PERSON_RE = re.compile(r"\b(my|mine)\b", re.IGNORECASE)

# ── NEW: semester-mention detector, used for the role/batch access guard ───
# Matches "sem 7", "semester 7", "7th sem", "sem-5", etc.
_SEM_RE = re.compile(
    r"\bsem(?:ester)?\.?\s*-?\s*(\d)\b|\b(\d)(?:st|nd|rd|th)\s*sem",
    re.IGNORECASE,
)


def _requested_sem(question: str) -> Optional[int]:
    m = _SEM_RE.search(question)
    if not m:
        return None
    return int(m.group(1) or m.group(2))


def _personalize_query(question: str, user_name: str | None) -> str:
    """Rewrite pronouns/relative time into concrete text the existing
    name + day/time matching in mapping_handler already understands.

    - "my" / "mine"           -> the logged-in user's name
    - "today" / "tonight"     -> current weekday name
    - "tomorrow" / "yesterday"-> relative weekday name
    - "now" / "right now" /
      "currently" / etc.      -> current HH:MM (IST), plus today's weekday
                                  if no day was already mentioned
    """
    q = question
    now = datetime.now(IST)

    def _day_repl(m: "re.Match[str]") -> str:
        word = m.group(1).lower()
        if word in ("today", "tonight"):
            return now.strftime("%A")
        if word == "tomorrow":
            return (now + timedelta(days=1)).strftime("%A")
        return (now - timedelta(days=1)).strftime("%A")  # yesterday

    q = _RELATIVE_DAY_RE.sub(_day_repl, q)

    if _NOW_RE.search(q):
        q = _NOW_RE.sub(now.strftime("%H:%M"), q)
        if not re.search(r"\b(" + "|".join(_DAY_NAMES) + r")\b", q, re.IGNORECASE):
            q = f"{q} {now.strftime('%A')}"

    if user_name and user_name.strip():
        q = _FIRST_PERSON_RE.sub(user_name.strip(), q)

    return q


# Per-session state (keyed by session_id)
sessions: dict = {}

def get_session(session_id: str):
    if session_id not in sessions:
        sessions[session_id] = {"history": [], "state": ConversationState()}
    return sessions[session_id]


# ── Request/response schemas ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: Optional[str] = None
    session_id: str = "default"
    user_id: Optional[str] = None
    user_name: Optional[str] = None


class ChatResponse(BaseModel):
    reply: str


class ResetRequest(BaseModel):
    session_id: str = "default"


class ResetResponse(BaseModel):
    status: str


@app.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    authorization: Optional[str] = Header(default=None),
    authToken: Optional[str] = Cookie(default=None),
):
    claims = _authenticate(authorization, authToken)

    role = str(claims.get("role") or "").strip().lower()
    allowed_sem = claims.get("allowed_sem")
    if role not in {"student", "faculty", "admin"}:
        raise HTTPException(status_code=403, detail="Unsupported account role.")
    if role == "student" and allowed_sem not in {5, 7}:
        raise HTTPException(status_code=403, detail="Student account has no valid semester scope.")
    if role != "student":
        allowed_sem = None

    user_q     = (body.message or "").strip()
    session_id = body.session_id or "default"
    user_id    = str(claims.get("username") or claims.get("sub") or "").strip().lower()
    user_name  = claims.get("name")

    if not user_q:
        return ChatResponse(reply="Please type a message.")

    # Resolve "my"/"mine" to the logged-in user's name, and "now"/"today"/etc.
    # to a concrete day/time, before anything else looks at the question.
    resolved_q = _personalize_query(user_q, user_name)

    sess    = get_session(session_id)
    history = sess["history"]
    state   = sess["state"]

    _append_history(history, "user", resolved_q)

    with tracker.trace(
        name="handle-chatbot-message",
        input_str=resolved_q,
        session_id=session_id,
        user_id=user_id,
        tags=["qa-chatbot"]
    ) as trace:
        if user_q.lower() in {"exit", "quit", "bye"}:
            reply = "Bye! Have a great day!"

        elif is_greeting(resolved_q):
            reply = "Hi! How can I help you with student and faculty info?"

        elif (
            not is_academic_query(resolved_q)
            and not _name_tokens(resolved_q)
            and not state.pending_matches
            and not re.fullmatch(r"\s*\d+\s*", resolved_q)
        ):
            reply = "I'm designed only for academic queries about PDEU students and faculty."

        # ── NEW: role/batch/semester guard ──────────────────────────────
        # Students can only ask about their own batch's semester. Faculty
        # info is never restricted. Faculty/admin accounts have
        # allowed_sem = None, so this branch never fires for them.
        elif (
            role == "student"
            and allowed_sem is not None
            and (requested_sem := _requested_sem(resolved_q)) is not None
            and requested_sem != int(allowed_sem)
        ):
            reply = (
                f"You're only able to view semester {allowed_sem} student data. "
                f"Faculty information is always available."
            )

        elif use_llm:
            # Mapping handler routing disabled — every query now goes through
            # LlamaHandler, which resolves it via MCP tool calls
            # (get_teaching_assignments, get_timetable, get_free_slots, lookup_person).
            #
            # `handle()` is now a coroutine (see llama_handler.py) so the
            # persistent MCP session it opens on first use stays alive across
            # requests instead of being torn down and rebuilt every time.
            reply = await llama_handler.handle(
                resolved_q, history[:-1], trace_id=None,
                role=role, allowed_sem=allowed_sem,
            ) or "I couldn't generate an answer. Please try rephrasing."

        else:
            reply = "I could not find that information in the database."

        if trace:
            trace.update(output=reply)

    _append_history(history, "bot", reply)
    return ChatResponse(reply=reply)


@app.post("/reset", response_model=ResetResponse)
def reset(
    body: ResetRequest,
    authorization: Optional[str] = Header(default=None),
    authToken: Optional[str] = Cookie(default=None),
):
    # Require a valid session so a guessed/sniffed session_id alone can't be
    # used to wipe someone else's in-progress conversation.
    _authenticate(authorization, authToken)
    session_id = body.session_id or "default"
    if session_id in sessions:
        del sessions[session_id]
    return ResetResponse(status="reset")


@app.on_event("shutdown")
async def _shutdown_llama_handler():
    """Close the persistent MCP subprocess/session cleanly when the API
    process shuts down, instead of leaving mcp_tools.py orphaned."""
    await llama_handler.close()


if __name__ == "__main__":
    import uvicorn
    print(f"[OK] LLM {'ON' if use_llm else 'OFF - mapping only'}")
    print("[OK] Chatbot API running on http://localhost:5001")
    uvicorn.run(app, host="0.0.0.0", port=5001)
