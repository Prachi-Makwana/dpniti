
from __future__ import annotations

import re
from typing import Dict, List

from langfuse_integration import tracker

from sql_dump import (
    SQLDumpRAG,
    ConversationState,
    SQL_DUMP_PATH,
    TOP_K,
    OPENROUTER_MODEL,
    OPENROUTER_MODELS,
    OPENROUTER_API_KEY,
    LOCAL_LLM_BASE_URL,
    SYSTEM_PROMPT,
    _append_history,
    _name_tokens,
    is_greeting,
    is_academic_query,
)
from llama_handler import LlamaHandler

# Main chatbot function
async def main() -> None:
    print("=" * 60)
    print("  ACADEMIC CHATBOT  —  (FAISS + MiniLM + OpenRouter)")
    print("  With LangFuse Observability")
    print("=" * 60)

    print("\nLoading SQL dump...", end=" ", flush=True)
    rag = SQLDumpRAG(SQL_DUMP_PATH)
    rag.load()
    print(f"done.  Tables: {', '.join(sorted(rag.rows_by_table.keys()))}")
    print(f"       Records: {sum(len(rows) for rows in rag.rows_by_table.values())}")

    llama_handler   = LlamaHandler(rag)

    use_llm = LlamaHandler.is_available()
    if use_llm:
        print(f"[OK] OpenRouter API ({OPENROUTER_MODEL}) reachable — LLM handler ON.")
    else:
        print("[!] OpenRouter not reachable — Mapping handler only.")

    tracker.start_session(use_llm=use_llm, use_openrouter=True)

    print("\nChatbot ready. Type 'exit' to quit.")
    print("Hello! How can I help you today?\n")

    history: List[Dict[str, str]] = []
    state      = ConversationState()
    turn_count = 0

    while True:
        try:
            user_q = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBot: Goodbye!")
            tracker.end_session(turn_count, status="ended_by_user")
            break

        if not user_q:
            continue

        turn_count += 1
        _append_history(history, "user", user_q)
        tid = tracker.start_turn(user_q, turn_count)

        # Exit
        if user_q.lower() in {"exit", "quit", "bye"}:
            bot_response = "Bye! Have a great day!"
            _append_history(history, "bot", bot_response)
            tracker.end_turn(tid, bot_response, "exit")
            print(f"Bot: {bot_response}")
            break

        # Greeting
        if is_greeting(user_q):
            bot_response = "Hi! How can I help you with student and faculty info?"
            _append_history(history, "bot", bot_response)
            tracker.end_turn(tid, bot_response, "greeting")
            print(f"Bot: {bot_response}\n")
            continue

        # Out-of-scope check
        if (
            not is_academic_query(user_q)
            and not _name_tokens(user_q)
            and not state.pending_matches
            and not re.fullmatch(r"\s*\d+\s*", user_q)
        ):
            bot_response = "I'm designed only for academic queries about PDEU students and faculty."
            _append_history(history, "bot", bot_response)
            tracker.end_turn(tid, bot_response, "out_of_scope")
            print(f"Bot: {bot_response}\n")
            continue

        handler_used = "no_handler"

        
        if use_llm:
            print("[Answered by: OPENROUTER]")
            bot_response = await llama_handler.handle(user_q, history[:-1], trace_id=tid)
            if not bot_response:
                bot_response = "I couldn't generate an answer. Please try rephrasing."
            handler_used = "openrouter_complex"
        else:
            bot_response = "I could not find that information in the database."

        _append_history(history, "bot", bot_response)
        tracker.end_turn(tid, bot_response, handler_used)
        tracker.ask_and_record_feedback(tid)
        print(f"Bot: {bot_response}\n")

    tracker.end_session(turn_count)
    await llama_handler.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())