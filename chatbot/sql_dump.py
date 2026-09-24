from __future__ import annotations
import os
import re
import json
import difflib
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from openai import OpenAI
import time
from dotenv import load_dotenv
load_dotenv()

from langfuse_integration import tracker, trace_function
DEBUG              = True
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or os.getenv("GEMINI_API_KEY", "")
LOCAL_LLM_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENROUTER_MODELS: List[str] = [
    "gemma-4-26b-a4b-it",
]
OPENROUTER_MODEL   = OPENROUTER_MODELS[0]

SQL_DUMP_PATH   = "db7.sql"
TOP_K           = 4
MAX_CONTEXT_CHARS = 20000

QUERY_STOPWORDS: frozenset = frozenset({
    "who", "is", "are", "what", "where","which", "roll", "rollno", "roll_no", "no",
    "number", "numbers", "division", "divisions", "div", "divs", "group",
    "groups", "grp", "grps", "batch", "batches", "class", "classes", "for",
    "student", "students", "faculty", "faculties", "professor", "professors",
    "teacher", "teachers", "email", "mail", "phone", "contact", "mobile",
    "cabin", "office", "location", "designation", "department", "dept",
    "qualification", "phd", "research", "resarch", "reseach",
    "reasearch", "resesarch", "rsearch", "interest", "intrest", "intrst",
    "interst", "college", "timetable", "schedule", "post", "title", "of",
    "the", "please", "detail", "details", "info", "information", "can",
    "tell", "give", "all", "about", "find", "get", "me", "us", "you",
    "just", "name", "names", "only", "list", "show", "any", "with", "from",
    "this", "that", "his", "her", "their", "a", "an", "in", "on", "at",
    "to", "and", "or", "by", "his", "her", "hers", "theirs", "my", "mine",
    "our", "ours", "your", "yours",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "today", "tomorrow", "yesterday", "week", "daily", "weekly",
    "dr", "mr", "ms", "mrs", "prof", "sir", "maam", "madam", "mam"
})

ROLL_RE = re.compile(r"\b(\d{2}bcp\d+[a-z]?)\b", re.IGNORECASE)

DEFAULT_WEIGHTS: Dict[str, float] = {
    "token_overlap":  2.0,
    "field_exact":    3.0,
    "semantic_blend": 1.5,
}

FACULTY_KEYWORDS: List[str] = [
    "faculty", "faculties", "professor", "professors",
    "teacher", "teachers", "staff", "lecturer", "lecturers",
]

STUDENT_KEYWORDS: List[str] = [
    "student", "students", "learner", "learners",
]

SYSTEM_PROMPT = """You are a friendly academic assistant for PDEU.

- Answer ONLY from tool results. Never invent or assume names, roll numbers, emails, phones, cabins, or other data.
- If no tool match: "I don't have that information in the database."
- Stay limited to academic student, faculty, and timetable queries. No general knowledge or coding help.
- Admin and faculty users may access student data from semesters 5 and 7, as well as all faculty data.
- For ANY question mentioning timetable, schedule, class timing, free slots, or "when is X's lecture" —
  ALWAYS call get_timetable or get_free_slots. Never answer a timetable question from memory or general
  knowledge, even if it seems simple. If the question names a division or semester but no specific person,
  pass `division` and/or `semester` to get_timetable instead of leaving it empty.
- Be natural and conversational. Greet warmly. Don't repeat information unless asked.
- When listing multiple records, number them and include ALL records returned by the tool—never truncate.
- Show timetables day-by-day.
- Use plain English field names (e.g., "Roll Number"). Remove subject codes such as "20CP401T -".
- Format divisions as "Division 1" and groups as "Group 1".
"""
#Value ne safely string ma convert kare chhe
def _safe_text(v: Any) -> str:
    if v is None:
        return "Not available"
    t = str(v).strip()
    return t if t else "Not available"

# User ni query mathi important name-related words extract kare chhe
def _name_tokens(text: str) -> List[str]:
    return [
        w for w in re.findall(r"[a-z]+", text.lower())
        if w not in QUERY_STOPWORDS and len(w) >= 2
    ]

#lower text ma convert kare chhe
def _tokenize(text: str) -> Set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

#only sub name rakhse.subject code hoi to remove
def _clean_subject_name(raw: str) -> str:
    return re.sub(r"^\d+[A-Z]+\d+[A-Z]*\s*[-–]\s*", "", raw).strip()

STUDENT_SUBJECT_FIELDS: List[str] = [f"sub{i}" for i in range(1, 10)]

#badha available subjects collect kare
def _get_student_subjects(row: Dict[str, Any]) -> List[str]:
    """Return the non-empty sub1..sub9 subject values for a student row, in order."""
    out: List[str] = []
    for f in STUDENT_SUBJECT_FIELDS:
        v = str(row.get(f, "") or "").strip()
        if v:
            out.append(v)
    return out

#subject lower text ma convert kare chhe
def _student_subject_keys(row: Dict[str, Any]) -> Set[str]:
    """Normalized (cleaned, lowercased) subject names for a student, used to match timetable rows."""
    return {_clean_subject_name(s).lower() for s in _get_student_subjects(row)}

def _normalize_key(v: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower().strip())

#Group value mathi G1, G2 jeva individual group components identify kare 
def _split_group_components(v: Any) -> Set[str]:
    raw = str(v or "").lower().strip()
    c = set(re.findall(r"g\d+", raw))
    return c if c else ({_normalize_key(raw)} if _normalize_key(raw) else set())

#div identify
def _extract_division_keys(query: str) -> Set[str]:
    return {
        f"div{m.group(1)}"
        for m in re.finditer(r"\b(?:div(?:ision)?)[\s\-]*(\d{1,2})\b", query.lower())
    }

#grp identify
def _extract_group_keys(query: str) -> Set[str]:
    q = query.lower()
    keys: Set[str] = {m.group(0) for m in re.finditer(r"\bg\d+(?:g\d+)?\b", q)}
    keys |= {
        f"g{m.group(1)}"
        for m in re.finditer(r"\b(?:group|grp|batch)[\s\-]*(\d{1,2})\b", q)
    }
    return keys

#day identify
def _extract_day_filters(query: str) -> Set[str]:
    days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    return {d for d in days if d in query.lower()}

def _time_to_minutes(v: Any) -> Optional[int]:
    t = str(v or "").strip().lower()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::\d{2})?$", t)
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
        return hh * 60 + mm if 0 <= hh <= 23 and 0 <= mm <= 59 else None
    m2 = re.match(r"^(\d{1,2})\s*(am|pm)$", t)
    if not m2:
        return None
    hh = int(m2.group(1))
    if m2.group(2) == "am":
        hh = 0 if hh == 12 else hh
    else:
        hh = 12 if hh == 12 else hh + 12
    return hh * 60

def _extract_time_filters(query: str) -> List[int]:
    q, times = query.lower(), []
    for m in re.finditer(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b", q):
        times.append(int(m.group(1)) * 60 + int(m.group(2)))
    for m in re.finditer(r"\b(\d{1,2})\s*(am|pm)\b", q):
        t = _time_to_minutes(f"{m.group(1)} {m.group(2)}")
        if t is not None:
            times.append(t)
    if not times:
        for m in re.finditer(r"\b(?:at|around|by|after|before|from)\s+(\d{1,2})\b", q):
            hh = int(m.group(1))
            if 0 <= hh <= 23:
                times.append(hh * 60)
    seen: Set[int] = set()
    unique = []
    for t in times:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique

# Timetable row user dwara puchayela time sathe match thay chhe ke nahi te check kare 
def _row_matches_time(row: Dict[str, Any], times: List[int], bare_hour: bool = False) -> bool:
    if not times:
        return True
    s, e = _time_to_minutes(row.get("start_time")), _time_to_minutes(row.get("end_time"))
    if s is None or e is None:
        return False
    for t in times:
        if s <= t < e:
            return True
        if bare_hour and s == t:
            return True
    return False

# Timetable ma aapel group user na required group sathe match kare chhe ke nahi te check kare 
def _row_matches_groups(group_val: Any, req: Set[str]) -> bool:
    if not req:
        return True
    norm = _normalize_key(group_val)
    comp = _split_group_components(group_val)
    return any(r == norm or r in comp for r in req)

#Timetable entry ne sort kare
def _format_timetable_entries(entries: List[Dict[str, Any]]) -> str:
    if not entries:
        return "Not available"
    sorted_e = sorted(entries, key=lambda entry: (
        str(entry.get("day_of_week", "")), str(entry.get("start_time", "")),
        str(entry.get("subject", ""))
    ))

    def _tl(v: Any) -> str:
        t = _safe_text(v)
        m = re.match(r"^(\d{1,2}:\d{2})(?::\d{2})?$", t)
        return m.group(1) if m else t

    lines = []
    for i, e in enumerate(sorted_e, 1):
        subj = _clean_subject_name(_safe_text(e.get("subject")))
        lines.append(
            f"{i}. {_safe_text(e.get('day_of_week'))} | "
            f"{_tl(e.get('start_time'))}-{_tl(e.get('end_time'))} | "
            f"Subject: {subj} | "
            f"Division: {_safe_text(e.get('division'))} | "
            f"Group: {_safe_text(e.get('group_name'))} | "
            f"Room: {_safe_text(e.get('classroom'))}"
        )
    return "\n".join(lines)

def _append_history(history: List[Dict[str, str]], role: str, content: str) -> None:
    history.append({"role": role, "content": content})

def _last_bot_message(history: List[Dict[str, str]]) -> str:
    for item in reversed(history):
        if item.get("role") == "bot":
            return str(item.get("content", ""))
    return ""

#greeting check
@trace_function()
def is_greeting(user_text: str) -> bool:
    t = user_text.lower().strip()
    greetings = {
        "hi", "hii", "hello", "helo", "heyy", "hey",
        "how are you", "good morning", "good afternoon", "good evening","good day", 
        "greetings", "hey there", "hi there", "hello there", "howdy", "hiya", "yo",
          "sup", "what's up", "how's it going",  "how's life", "good night"
    }
    if t in greetings:
        return True
    if len(t.split()) <= 6:
        if re.search(r"\b(hi|hii|hello|helo|heyy|hey)\b", t):
            return True
        if "how are you" in t:
            return True
    return False

#academic query check
@trace_function()
def is_academic_query(user_text: str) -> bool:
    q = user_text.lower()
    if re.search(r"\b\d{2}bcp\d+[a-z]?\b", q):
        return True
    if re.search(r"\b\d{7,}\b", q):
        return True
    keywords = [
        "student","students", "faculty", "faculties", "professor", "teacher", "teachers", "cabin", "office",
        "lecture", "lectures","lec", "class", "classroom", "timetable", "schedule", "subject", "subjects",
        "roll", "roll_no", "division", "group", "department", "email",
        "phone", "research", "interest",  "lab", "labs","where", "when","what",
        "who", "teach", "teaches", "teaching", "qualification", "phd",
        "college", "university", "institute", "designation",
        "him", "her", "his", "them", "their", "same", "detail", "details",
        "full", "complete", "info", "information", "everything", "about","list"
    ]
    return any(k in q for k in keywords)

#llama query check
@trace_function()
def is_llama_query(user_text: str) -> bool:
    q = user_text.lower()

    if re.search(r"\b(timetable|schedule|time table)\s+(of|for)\b", q):
        return False
    if re.search(r"\b(what is|show|give)\s+(the\s+)?(timetable|schedule)\s+(of|for)\b", q):
        return False
    if re.search(r"\b(his|her|their|my)\s+(timetable|schedule|time table|tt)\b", q):
        return False
    if re.search(r"\b(timetable|schedule|time table|tt)\s+(of|for)?\s*(him|her|them)\b", q):
        return False

    if _extract_division_keys(user_text) and re.search(r"\b(faculty|teacher|professor|staff)\b", q):
        return False
    
    if re.search(r"\b(faculty|teacher|professor)\s+(of|for)\b", q):
        return False

    has_timetable_kw = bool(re.search(r"\b(timetable|schedule|time table|tt)\b", q))
    genuine_cross_table_only = [
        "teach", "teaches", "teaching", "taught",
        "who teach", "who takes", "which faculty", "which division", "which group",
        "free slot", "free period", "free time", "not teaching", "available",
        "sitting in", "who is in", "who are in", "helding", "holding",
        "same division", "same div", "same group", "same class",
    ]
    if (
        has_timetable_kw
        and _name_tokens(user_text)
        and not any(k in q for k in genuine_cross_table_only)
    ):
        return False

    cross_table_keywords = [
        "coordinator", "course coordinator",
        "teach", "teaches", "teaching", "taught",
        "timetable", "time table", "schedule",
        "lecture", "lec", "room", "classroom",
        "subject", "which subject", "what subject",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "same division", "same div", "same group",
        "which division", "which group", "who teach", "who takes",
        "free slot", "free period", "free time", "not teaching", "available",
        "sitting in", "who is in", "who are in", "helding", "holding",
        "same division", "same div", "same group", "same class",
        "lab", "lec", "which subject", "what subject", "which div",    ]
    return any(k in q for k in cross_table_keywords)


class ConversationState:
    def __init__(self) -> None:
        self.last_table: str = ""
        self.last_row: Optional[Dict[str, Any]] = None
        self.pending_matches: List[Dict[str, Any]] = []
        self.pending_intent: str = ""

    def set_person(self, table: str, row: Dict[str, Any]) -> None:
        self.last_table = table
        self.last_row = dict(row)
        self.pending_matches = []
        self.pending_intent = ""

    def set_pending_matches(self, matches: List[Dict[str, Any]], intent: str = "") -> None:
        self.pending_matches = matches
        self.pending_intent = intent

    def clear_pending(self) -> None:
        self.pending_matches = []
        self.pending_intent = ""

#  SQL DUMP RAG
class SQLDumpRAG:
    def __init__(self, sql_path: str, config: Optional[Dict[str, Any]] = None) -> None:
        self.sql_path = Path(sql_path)
        self.config = {**DEFAULT_WEIGHTS, **(config or {})}
        self.rows_by_table: Dict[str, List[Dict[str, Any]]] = {}

    def load(self) -> None:
        sql_text = self.sql_path.read_text(encoding="utf-8", errors="ignore")
        self.rows_by_table = self._parse_insert_statements(sql_text)
        print(f"Loaded {sum(len(rows) for rows in self.rows_by_table.values())} rows across "
              f"{len(self.rows_by_table)} tables.")

    def get_faculty_timetable(self, faculty_id: Any) -> List[Dict[str, Any]]:
        if faculty_id is None:
            return []
        return [
            r for r in self.rows_by_table.get("timetable", [])
            if str(r.get("faculty_id", "")) == str(faculty_id)
        ]

    def _parse_insert_statements(self, sql_text: str) -> Dict[str, List[Dict[str, Any]]]:
        pattern = re.compile(
            r"INSERT INTO\s+`(?P<table>[^`]+)`\s*\((?P<cols>.*?)\)\s*VALUES\s*(?P<vals>.*?)(?=\bINSERT INTO\b|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        out: Dict[str, List[Dict[str, Any]]] = {}
        for m in pattern.finditer(sql_text):
            table = m.group("table").strip().lower()
            cols = [c.strip().strip("`") for c in m.group("cols").split(",")]
            for tup in self._split_tuples(m.group("vals")):
                items = self._split_items(tup)
                if len(items) != len(cols):
                    continue
                out.setdefault(table, []).append(
                    dict(zip(cols, [self._parse_sql_value(v) for v in items]))
                )
        return out

    def _split_tuples(self, blob: str) -> List[str]:
        tuples, in_str, escaped, depth, cur = [], False, False, 0, []
        for ch in blob:
            if escaped:
                cur.append(ch); escaped = False; continue
            if ch == "\\":
                cur.append(ch); escaped = True; continue
            if ch == "'":
                in_str = not in_str; cur.append(ch); continue
            if not in_str:
                if ch == "(":
                    if depth == 0:
                        cur = []
                    else:
                        cur.append(ch)
                    depth += 1; continue
                if ch == ")":
                    depth -= 1
                    if depth == 0:
                        tuples.append("".join(cur).strip()); cur = []
                    else:
                        cur.append(ch)
                    continue
            if depth > 0:
                cur.append(ch)
        return tuples

    def _split_items(self, tup: str) -> List[str]:
        items, in_str, escaped, cur = [], False, False, []
        for ch in tup:
            if escaped:
                cur.append(ch); escaped = False; continue
            if ch == "\\":
                cur.append(ch); escaped = True; continue
            if ch == "'":
                in_str = not in_str; cur.append(ch); continue
            if ch == "," and not in_str:
                items.append("".join(cur).strip()); cur = []; continue
            cur.append(ch)
        if cur:
            items.append("".join(cur).strip())
        return items

    def _parse_sql_value(self, v: str) -> Any:
        v = v.strip()
        if v.upper() == "NULL":
            return None
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1].replace("\\'", "'").replace("\\\\", "\\")
        if re.fullmatch(r"-?\d+", v):
            try:
                return int(v)
            except ValueError:
                return v
        if re.fullmatch(r"-?\d+\.\d+", v):
            try:
                return float(v)
            except ValueError:
                return v
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return v
        return v