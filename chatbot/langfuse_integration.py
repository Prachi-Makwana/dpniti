import os
import threading
import uuid
import json
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()

try:
    from langfuse import Langfuse, get_client, propagate_attributes
    _LANGFUSE_IMPORTABLE = True
except ImportError:
    Langfuse = get_client = propagate_attributes = None  # type: ignore
    _LANGFUSE_IMPORTABLE = False

_local = threading.local()


def _get_stack() -> List[Any]:
    if not hasattr(_local, "stack"):
        _local.stack = []
    return _local.stack


class LangfuseTracker:
    def __init__(self) -> None:
        self.enabled = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
        self.public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
        self.secret_key = os.getenv("LANGFUSE_SECRET_KEY")
        self.host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

        self.client = None
        if self.enabled and _LANGFUSE_IMPORTABLE and self.public_key and self.secret_key:
            try:
                # Constructing Langfuse(...) registers the process-wide client;
                # get_client() returns that singleton from anywhere in the app.
                Langfuse(
                    public_key=self.public_key,
                    secret_key=self.secret_key,
                    host=self.host,
                    flush_at=1,
                    flush_interval=0.1,
                )
                self.client = get_client()
                print(f"[Langfuse] Initialized tracing to {self.host}")
            except Exception as e:
                print(f"[Langfuse Error] Failed to initialize: {e}")
                self.enabled = False
        else:
            if self.enabled and not _LANGFUSE_IMPORTABLE:
                print("[Langfuse Warning] langfuse python package not installed. Tracing disabled.")
            else:
                print("[Langfuse] Tracing is disabled (or keys are missing in .env)")
            self.enabled = False

        # Session and trace tracking
        self._current_session_id = str(uuid.uuid4())
        # trace_id -> {"span": observation, "span_cm": ctx mgr, "attr_cm": ctx mgr}
        self._active_traces: Dict[str, Dict[str, Any]] = {}

    def _attr_ctx(self, trace_name: str, session_id: Optional[str],
                  user_id: Optional[str] = None, tags: Optional[List[str]] = None):
        """Build a propagate_attributes() context manager, only passing set values."""
        kwargs: Dict[str, Any] = {"trace_name": trace_name}
        if session_id:
            kwargs["session_id"] = session_id
        if user_id:
            kwargs["user_id"] = user_id
        if tags:
            kwargs["tags"] = tags
        return propagate_attributes(**kwargs)

    @contextmanager
    def trace(self, name: str, input_str: Optional[str] = None, session_id: Optional[str] = None,
               user_id: Optional[str] = None, tags: Optional[List[str]] = None):
        """Context manager to start a top-level trace (used by the Flask API)."""
        if not self.enabled or not self.client:
            yield None
            return

        sid = session_id or self._current_session_id
        attr_cm = self._attr_ctx(name, sid, user_id, tags)
        attr_cm.__enter__()
        stack = _get_stack()
        try:
            with self.client.start_as_current_observation(
                name=name, as_type="span", input=input_str
            ) as span_obj:
                stack.append(span_obj)
                try:
                    yield span_obj
                finally:
                    if stack and stack[-1] is span_obj:
                        stack.pop()
        finally:
            try:
                attr_cm.__exit__(None, None, None)
            except Exception:
                pass
            try:
                self.client.flush()
            except Exception:
                pass

    @contextmanager
    def span(self, name: str, input_data: Optional[Any] = None):
        """Context manager to start a span under the active observation, if any."""
        if not self.enabled or not self.client:
            yield None
            return

        stack = _get_stack()
        parent = stack[-1] if stack else None

        span_obj = (parent.start_observation(name=name, as_type="span", input=input_data)
                    if parent else
                    self.client.start_observation(name=name, as_type="span", input=input_data))

        stack.append(span_obj)
        try:
            yield span_obj
        finally:
            if stack and stack[-1] is span_obj:
                stack.pop()
            try:
                span_obj.end()
            except Exception:
                pass

    # Compatibility methods for existing app.py code
    def start_session(self, use_llm: bool = False, use_openrouter: bool = False) -> None:
        self._current_session_id = f"cli_session_{uuid.uuid4().hex[:8]}"

    def end_session(self, turn_count: int, status: str = "completed") -> None:
        pass

    def start_turn(self, user_q: str, turn_count: int) -> str:
        """Starts a new root observation for a CLI conversation turn."""
        if not self.enabled or not self.client:
            return f"dummy_{uuid.uuid4()}"

        attr_cm = self._attr_ctx(
            "handle-chatbot-message", self._current_session_id, tags=["qa-chatbot", "cli"]
        )
        attr_cm.__enter__()

        span_cm = self.client.start_as_current_observation(
            name="handle-chatbot-message", as_type="span", input=user_q
        )
        span_obj = span_cm.__enter__()

        tid = str(uuid.uuid4())
        self._active_traces[tid] = {"span_cm": span_cm, "span": span_obj, "attr_cm": attr_cm}
        _get_stack().append(span_obj)
        return tid

    def end_turn(self, trace_id: str, bot_response: str, handler_used: str) -> None:
        """Completes a trace turn."""
        entry = self._active_traces.pop(trace_id, None)
        if not entry:
            return

        span_obj = entry["span"]
        try:
            # Tags can no longer be set after the fact in v4 (they only apply
            # within propagate_attributes' scope at creation time), so record
            # which handler answered as metadata instead.
            span_obj.update(output=bot_response, metadata={"handler_used": handler_used})
        except Exception:
            pass

        stack = _get_stack()
        if stack and stack[-1] is span_obj:
            stack.pop()

        try:
            entry["span_cm"].__exit__(None, None, None)
        except Exception:
            pass
        try:
            entry["attr_cm"].__exit__(None, None, None)
        except Exception:
            pass

        try:
            self.client.flush()
        except Exception:
            pass

    def record_event(self, trace_id: str, name: str, input_data: Optional[Any] = None,
                      output_data: Optional[Any] = None, level: str = "DEFAULT") -> None:
        """NO-OP function because events are strictly not wanted in the Langfuse dashboard."""
        pass

    def span_retrieval(self, trace_id: str, query: str, top_k: int) -> Any:
        entry = self._active_traces.get(trace_id)
        parent = entry["span"] if entry else None
        if not parent:
            return None
        try:
            return parent.start_observation(
                name="retrieval", as_type="span", input={"query": query, "top_k": top_k}
            )
        except Exception:
            return None

    def span_mapping(self, trace_id: str, question: str) -> Any:
        entry = self._active_traces.get(trace_id)
        parent = entry["span"] if entry else None
        if not parent:
            return None
        try:
            return parent.start_observation(name="mapping-handler", as_type="span", input=question)
        except Exception:
            return None

    def span_llm(self, trace_id: str, user_question: str, context_chars: int, model: str) -> Any:
        entry = self._active_traces.get(trace_id)
        parent = entry["span"] if entry else None
        if not parent:
            return None
        try:
            return parent.start_observation(
                name="llm-generation",
                as_type="generation",
                model=model,
                input=user_question,
                metadata={"context_chars": str(context_chars)},
            )
        except Exception:
            return None

    def end_span(self, span_obj: Any, output: Optional[Any] = None, error: Optional[str] = None) -> None:
        if not span_obj:
            return
        try:
            out_val = output
            if isinstance(output, dict):
                out_val = json.dumps(output, default=str)
            if error:
                span_obj.update(output=out_val, level="ERROR", status_message=error)
            else:
                span_obj.update(output=out_val)
        except Exception:
            pass
        finally:
            try:
                span_obj.end()
            except Exception:
                pass

    def ask_and_record_feedback(self, trace_id: str) -> None:
        """Dummy to avoid blocking the CLI when run."""
        pass


# Instantiate the singleton tracker
tracker = LangfuseTracker()


def trace_function(name: Optional[str] = None):
    """Decorator to automatically log function calls as spans inside the active trace."""
    def decorator(func):
        func_name = name or func.__name__

        def wrapper(*args, **kwargs):
            if not tracker.enabled or not tracker.client:
                return func(*args, **kwargs)

            stack = _get_stack()
            parent = stack[-1] if stack else None

            # Fallback to the most recent active trace if the stack is empty
            # (e.g. from app.py's CLI mapping path).
            if not parent and tracker._active_traces:
                parent = list(tracker._active_traces.values())[-1]["span"]

            if not parent:
                return func(*args, **kwargs)

            # Determine input info
            input_val = None
            if args:
                first_arg = args[0]
                if len(args) > 1 and hasattr(first_arg, "__class__") and first_arg.__class__.__name__ in (
                    "MappingHandler", "LlamaHandler", "SQLDumpRAG"
                ):
                    input_val = args[1]
                else:
                    input_val = first_arg
            else:
                input_val = kwargs

            if input_val is not None and not isinstance(input_val, (str, int, float, bool)):
                try:
                    input_val = json.dumps(input_val, default=str)
                except Exception:
                    input_val = str(input_val)

            span_obj = parent.start_observation(name=func_name, as_type="span", input=input_val)
            stack.append(span_obj)
            try:
                result = func(*args, **kwargs)

                output_val = result
                if output_val is not None and not isinstance(output_val, (str, int, float, bool)):
                    try:
                        output_val = json.dumps(output_val, default=str)
                    except Exception:
                        output_val = str(output_val)

                span_obj.update(output=output_val)
                span_obj.end()
                return result
            except Exception as e:
                try:
                    span_obj.update(level="ERROR", status_message=str(e))
                    span_obj.end()
                except Exception:
                    pass
                raise
            finally:
                if stack and stack[-1] is span_obj:
                    stack.pop()
        return wrapper
    return decorator