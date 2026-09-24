from __future__ import annotations
import contextlib
import io
import re
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from mcp.server.fastmcp import FastMCP as MCPServer  # mcp SDK < 2.0
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer  # mcp SDK >= 2.0

_real_stdout = sys.stdout
with contextlib.redirect_stdout(sys.stderr):
    from sql_dump import (
    SQLDumpRAG,
    ROLL_RE,
    _safe_text,
    _name_tokens,
    _clean_subject_name,
    _get_student_subjects,
    _student_subject_keys,
    _normalize_key,
    _split_group_components,
    _extract_division_keys,
    _extract_day_filters,
    _extract_time_filters,
    _row_matches_time,
    _time_to_minutes,
)

mcp = MCPServer("pdeu-campus-data")

# Loaded once at process start (this runs as its own subprocess).
rag = SQLDumpRAG("db7.sql")
with contextlib.redirect_stdout(sys.stderr):
    rag.load()


SUBJECT_CODE_NAMES: Dict[str, str] = {
    "20cp401t": "Machine Learning", "20cp401p": "Machine Learning Lab",
    "23cp403t": "Internet of Things", "23cp403p": "Internet of Things Lab",
    "20cp405t": "Natural Language Processing", "20cp405p": "Natural Language Processing Lab",
    "20cp406t": "BlockChain Technology", "20cp406p": "BlockChain Technology Lab",
    "20cp408t": "Agile Methodology & DevOps", "20cp408p": "Agile Methodology & DevOps Lab",
    "20cp411t": "Digital Forensics", "20cp411p": "Digital Forensics Lab",
    "20cp412t": "Pattern Recognition", "20cp412p": "Pattern Recognition Lab",
    "20cp415t": "Service-Oriented Architecture",
    "20cp417t": "Information Retrieval",
    "23cp402t": "Data Intelligence & Modelling",
    "MOOC — NPTEL / SWAYAM / MOOC Course": "MOOC — NPTEL / SWAYAM / MOOC Course",
    "24CS301T": "Introduction to Artificial Intelligence",
    "24CS302T": "Computer Networks",
    "24CS302P": "Computer Networks Laboratory",
    "24CS303T": "Compiler Design",
    "24CS303P": "Compiler Design Laboratory",
    "24CS304T": "Operating System",
    "24CS304P": "Operating System Laboratory",
    "24CS331T": "Data Mining and Data Warehousing",
    "24CS333T": "Computer Graphics",
    "24CS335T": "Advanced Data Structure and Algorithms",
}

COURSE_COORDINATOR_BY_CODE: Dict[str, int] = {
    "20cp401t": 14, "20cp401p": 14,
    "23cp403t": 18, "23cp403p": 18,
    "20cp408t": 19, "20cp408p": 19,
    "20cp406t": 17, "20cp406p": 17,
    "20cp405t": 35, "20cp405p": 35,
    "20cp411t": 41, "20cp411p": 41,
    "20cp412t": 42, "20cp412p": 42,
    "23cp402t": 30,
    "20cp417t": 37,
    "20cp415t": 28,
    "MOOC — NPTEL / SWAYAM / MOOC Course": 20,
    "24CS301T": 43,
    "24CS302T": 20,"24CS302P": 20,
    "24CS303T": 21, "24CS303P": 21,
    "24CS304T": 5, "24CS304P": 5,
    "24CS331T": 16,
    "24CS333T": 38,
    
}

SUBJECT_ALIASES: Dict[str, str] = {
    "machine learning": "20cp401t", "machine learning lab": "20cp401p",
    "ml": "20cp401t", "ml lab": "20cp401p",

    "internet of things": "23cp403t", "internet of things lab": "23cp403p",
    "iot": "23cp403t", "iot lab": "23cp403p",

    "agile methodology & devops": "20cp408t", "agile methodology & devops lab": "20cp408p",
    "devops": "20cp408t", "amd": "20cp408t", "agile": "20cp408t",
    "agile methodology": "20cp408t", "devops lab": "20cp408p", "agile lab": "20cp408p",

    "blockchain technology": "20cp406t", "blockchain technology lab": "20cp406p",
    "blockchain": "20cp406t", "bt": "20cp406t", "bt lab": "20cp406p", "blockchain lab": "20cp406p",

    "natural language processing": "20cp405t", "natural language processing lab": "20cp405p",
    "nlp": "20cp405t", "nlp lab": "20cp405p",

    "digital forensics": "20cp411t", "digital forensics lab": "20cp411p",
    "df": "20cp411t", "df lab": "20cp411p",

    "pattern recognition": "20cp412t", "pattern recognition lab": "20cp412p",
    "pr": "20cp412t", "pr lab": "20cp412p", "pattern lab": "20cp412p", "pattern": "20cp412t",

    "data intelligence": "23cp402t", "data intelligence & modelling": "23cp402t",
    "di": "23cp402t", "dim": "23cp402t",

    "information retrieval": "20cp417t", "ir": "20cp417t",

    "service oriented architecture": "20cp415t", "service-oriented architecture": "20cp415t",
    "soa": "20cp415t",

    "introduction to artificial intelligence": "24CS301T",  "ai": "24CS301T", "iai": "24CS301T",

    "computer networks": "24CS302T",  "cn": "24CS302T",
    "computer networks lab": "24CS302P", "cn lab": "24CS302P",

    "24CS303T" : "compiler design" , "cd": "24CS303T",
    "24CS303P" : "compiler design laboratory" , "cd lab": "24CS303P",

    "24CS304T" : "operating system", "os": "24CS304T",
    "24CS304P" : "operating system laboratory", "os lab": "24CS304P",

    "24CS331T" : "data mining and data warehousing" , "dmdw": "24CS331T",
    "24CS331T" : "data mining", "24CS331T" : "data warehousing" ,

    "24CS333T" : "computer graphics" , "cg": "24CS333T",

    "24CS335T" : "advanced data structure and algorithms" , "adsa": "24CS335T"
}

def _resolve_subject_code(text: str) -> Optional[str]:
    """Resolve free text (full course name, alias/abbreviation, or course code) to its 
    canonical course code. Use the same resolver for both `get_course_coordinator` and 
    `get_teaching_assignments`, so aliases like "df" work consistently for both queries."""
    q = text.lower().strip()
    if not q:
        return None
    code_match = re.search(r"\b\d{2}cp\d{3}[tp]?\b", q, flags=re.IGNORECASE)
    if code_match:
        return code_match.group(0).lower()
    if q in SUBJECT_ALIASES:
        return SUBJECT_ALIASES[q]
    # Longest alias first so e.g. "digital forensics lab" isn't shadowed by
    # the shorter "digital forensics" matching first.
    for name in sorted(SUBJECT_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", q):
            return SUBJECT_ALIASES[name]
    return None


# ── shared helpers ───────────────────────────────────────────────────────

def _faculty_rows() -> List[Dict[str, Any]]:
    return rag.rows_by_table.get("faculty", [])


def _student_rows(access_role: str = "admin", allowed_sem: Optional[int] = None) -> List[Dict[str, Any]]:
    rows = rag.rows_by_table.get("student", [])
    if access_role == "student":
        return [row for row in rows if int(row.get("semester", 0)) == int(allowed_sem or 0)]
    return rows


def _timetable_rows(
    access_role: str = "admin", allowed_sem: Optional[int] = None, faculty_query: bool = False
) -> List[Dict[str, Any]]:
    rows = rag.rows_by_table.get("timetable", [])
    if access_role == "student" and not faculty_query:
        return [row for row in rows if int(row.get("semester", 0)) == int(allowed_sem or 0)]
    return rows


def _faculty_name_map() -> Dict[str, str]:
    return {str(f.get("id")): _safe_text(f.get("name")) for f in _faculty_rows()}


def _division_key(text: str) -> Optional[str]:
    """'Division 5' / 'div-5' / '5' -> 'div5'."""
    keys = _extract_division_keys(text)
    if keys:
        return next(iter(keys))
    m = re.search(r"\b(\d{1,2})\b", text)
    return f"div{m.group(1)}" if m else None


def _division_value(value: Any) -> str:
    """Normalize stored numeric divisions and labels such as 'Div-1'."""
    text = str(value or "").strip().lower()
    match = re.search(r"(?:div(?:ision)?\s*[- ]?\s*)?(\d{1,2})\b", text)
    return f"div{match.group(1)}" if match else _normalize_key(value)


def _find_faculty(name_or_id: str) -> Optional[Dict[str, Any]]:
    tokens = _name_tokens(name_or_id)
    if not tokens:
        return None
    for f in _faculty_rows():
        fname = str(f.get("name", "")).lower()
        if all(tok in fname for tok in tokens):
            return f
    return None


def _find_student(
    query: str, access_role: str = "admin", allowed_sem: Optional[int] = None
) -> Optional[Dict[str, Any]]:
    roll_m = ROLL_RE.search(query.lower())
    if roll_m:
        roll = roll_m.group(1)
        for s in _student_rows(access_role, allowed_sem):
            if str(s.get("roll_no", s.get("roll", ""))).lower() == roll:
                return s
    tokens = _name_tokens(query)
    if tokens:
        for s in _student_rows(access_role, allowed_sem):
            sname = str(s.get("name", "")).lower()
            if all(tok in sname for tok in tokens):
                return s
    return None


def _tt_row_faculty_name(row: Dict[str, Any], fac_map: Dict[str, str]) -> str:
    return fac_map.get(str(row.get("faculty_id", "")), "Unknown")

_FACULTY_REVERSE_COLS: Tuple[str, ...] = (
    "email", "phone", "cabin", "designation",
    "qualification", "phd_subject", "college", "research_interest",
)


_CABIN_STOPWORDS: frozenset = frozenset({
    "block", "floor", "cubical", "cubicle", "admin", "ground", "office", "cabin",
})

_ORDINAL_WORDS: Dict[str, str] = {
    "first": "1", "second": "2", "third": "3", "fourth": "4", "fifth": "5",
    "sixth": "6", "seventh": "7", "eighth": "8", "ninth": "9", "tenth": "10",
}
_ORDINAL_SUFFIX_RE = re.compile(r"\b(\d+)(?:st|nd|rd|th)\b")


def _normalize_ordinals(text: str) -> str:
    text = _ORDINAL_SUFFIX_RE.sub(r"\1", text)
    for word, num in _ORDINAL_WORDS.items():
        text = re.sub(rf"\b{word}\b", num, text)
    return text


def _reverse_match(stored_value: str, query: str) -> bool:
    """Check whether a stored column value is referenced in the query.
    Phone numbers match by digits; other columns use normalized,
    word-bounded substring matching."""
    if not stored_value or len(stored_value) < 3:
        return False
    digits = re.sub(r"\D", "", stored_value)
    if len(digits) >= 10 and digits in re.sub(r"\D", "", query):
        return True
    val_norm = _normalize_ordinals(re.sub(r"\s+", " ", stored_value.strip().lower()))
    q_norm = _normalize_ordinals(re.sub(r"\s+", " ", query.strip().lower()))
    if re.search(rf"\b{re.escape(val_norm)}\b", q_norm):
        return True

    _split = lambda t: re.findall(r"[a-z]+|[0-9]+", t)
    val_tokens = {t for t in _split(val_norm) if t not in _CABIN_STOPWORDS}
    q_tokens = set(_split(q_norm))
    if val_tokens and val_tokens <= q_tokens:
        return True
 
    digit_tokens = {t for t in val_tokens if t.isdigit() and len(t) >= 2}
    if digit_tokens and digit_tokens <= q_tokens:
        return True
    return False


# ── tools ────────────────────────────────────────────────────────────────

MAX_ROWS = 25


def _cap_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    if len(rows) > MAX_ROWS:
        return rows[:MAX_ROWS] + [{
            "note": f"{len(rows) - MAX_ROWS} more matching rows omitted — "
                     f"ask a narrower question (add a division, day, or name) to see them."
        }]
    return rows


def _trim_fields(out: Dict[str, Any], fields: str) -> Dict[str, Any]:
    """If the caller asked for specific fields, return only those (plus name/
    type, which are always kept for context). Keeps the tool backward
    compatible: an empty `fields` still returns the full record."""
    if not fields:
        return out
    keep = {f.strip().lower() for f in fields.split(",") if f.strip()}
    keep |= {"name", "type", "error"}
    return {k: v for k, v in out.items() if k.lower() in keep}


@mcp.tool()
def lookup_person(
    query: str, fields: str = "", access_role: str = "admin", allowed_sem: Optional[int] = None
) -> Dict[str, Any]:
    """Resolve a student or faculty member by name or roll number.
      Return their record and type. If only specific fields are needed, pass them via 
      `fields` (e.g. `"cabin"` or `"email,phone"`) to return only those fields."""
    student = _find_student(query, access_role, allowed_sem)
    if student:
        out = dict(student)
        out["type"] = "student"
        out["subjects"] = _get_student_subjects(student)
        return _trim_fields(out, fields)
    faculty = _find_faculty(query)
    if faculty:
        out = dict(faculty)
        out["type"] = "faculty"
        return _trim_fields(out, fields)
    return {"error": f"No student or faculty found matching '{query}'."}


@mcp.tool()
def find_person_by_attribute(
    value: str, fields: str = "", access_role: str = "admin", allowed_sem: Optional[int] = None
) -> Dict[str, Any]:
    """Resolve a faculty member by attributes such as phone, email, cabin, designation,
      qualification, college, or research interest. For cabin/office queries, 
      pass the value exactly as provided, whether it is a room ID or free-text area 
      description. Use `fields` to return only the required columns."""
    matches: List[Dict[str, Any]] = []
    for row in _faculty_rows():
        for col in _FACULTY_REVERSE_COLS:
            if _reverse_match(_safe_text(row.get(col)), value):
                matches.append(row)
                break
    if not matches:
        return {"error": f"No faculty found matching attribute '{value}'."}
    if len(matches) == 1:
        out = dict(matches[0])
        out["type"] = "faculty"
        return _trim_fields(out, fields)
    return {"matches": [
        {"name": _safe_text(r.get("name")), "designation": _safe_text(r.get("designation"))}
        for r in matches
    ]}


@mcp.tool()
def list_people(
    type: str, division: str = "", group: str = "", department: str = "",
    access_role: str = "admin", allowed_sem: Optional[int] = None,
) -> Dict[str, Any]:
    """List students or faculty. For students, filter by division (e.g. "Div-1",
 "division 1") and/or group (e.g. "G9", "group 9") — these are separate
 fields, a student's group is nested inside their division. For faculty,
 filter by department. Use this for roster or count questions (e.g. "list
 all students in div 5", "how many students in G9", "list of faculty").
Returns a total count plus up to MAX_ROWS matching records."""
    is_student = type.strip().lower().startswith("stud")
    rows = _student_rows(access_role, allowed_sem) if is_student else _faculty_rows()

    if is_student and division:
        dk = _division_key(division)
        rows = [r for r in rows if _division_value(r.get("division")) == dk]
    if is_student and group:
        want = _split_group_components(group)
        rows = [r for r in rows if _split_group_components(r.get("group_name")) & want]
    if department:
        dep_norm = department.strip().lower()
        rows = [r for r in rows if dep_norm in str(r.get("department", "")).lower()]

    if not rows:
        return {"count": 0, "people": [{"error": "No matching records found."}]}

    if is_student:
        people = [
            {"name": _safe_text(r.get("name")), "roll_no": _safe_text(r.get("roll_no")),
             "division": _safe_text(r.get("division")), "group": _safe_text(r.get("group_name"))}
            for r in rows
        ]
    else:
        people = [
            {"name": _safe_text(r.get("name")), "designation": _safe_text(r.get("designation"))}
            for r in rows
        ]
    # Unlike the other list-shaped tools, a roster request explicitly wants
    # the full list — don't apply MAX_ROWS/_cap_rows here.
    return {"count": len(rows), "people": people}


@mcp.tool()
def get_course_coordinator(
    subject: str, access_role: str = "admin", allowed_sem: Optional[int] = None
) -> Dict[str, Any]:
    """Return the official course coordinator for a subject by name, alias, or code.
    Returns subject, faculty, and designation. Use only for coordinator queries,
    not teaching assignments."""
    code = _resolve_subject_code(subject)
    fid = COURSE_COORDINATOR_BY_CODE.get(code) if code else None
    if fid is None:
        return {"error": f"No course coordinator mapping found for '{subject}'."}

    fac_row = next((f for f in _faculty_rows() if str(f.get("id")) == str(fid)), None)
    if not fac_row:
        return {"error": f"Coordinator faculty record not found for '{subject}'."}

    return {
        "subject": SUBJECT_CODE_NAMES.get(code, code.upper()),
        "faculty": _safe_text(fac_row.get("name")),
        "designation": _safe_text(fac_row.get("designation")),
    }


@mcp.tool()
def get_teaching_assignments(
    person: str = "", subject: str = "", division: str = "",
    access_role: str = "admin", allowed_sem: Optional[int] = None,
) -> List[Dict[str, str]]:
    """"Return teaching assignments by faculty, student, subject, or division.
    Supports partial subject names and returns faculty, subject, division, and group."""
    fac_map = _faculty_name_map()
    rows = _timetable_rows(access_role, allowed_sem)
    div_key = _division_key(division) if division else None
    subj_norm = subject.strip().lower()
    subj_code = _resolve_subject_code(subject) if subject else None
    subj_canonical = SUBJECT_CODE_NAMES.get(subj_code, "").lower() if subj_code else ""

    student_subject_keys: Optional[Set[str]] = None
    student_div: Optional[str] = None
    student_group: Optional[Set[str]] = None
    faculty_match: Optional[Dict[str, Any]] = None

    if person:
        student = _find_student(person, access_role, allowed_sem)
        if student:
            student_subject_keys = _student_subject_keys(student)
            student_div = _division_value(student.get("division"))
            student_group = _split_group_components(student.get("group_name"))
        else:
            faculty_match = _find_faculty(person)

    seen = set()
    out: List[Dict[str, str]] = []
    for row in rows:
        fname = _tt_row_faculty_name(row, fac_map)
        row_subj = _clean_subject_name(_safe_text(row.get("subject")))
        row_div = _division_value(row.get("division"))

        if faculty_match and str(row.get("faculty_id")) != str(faculty_match.get("id")):
            continue
        if student_subject_keys is not None:
            if row_subj.lower() not in student_subject_keys:
                continue
            if student_div and row_div != student_div:
                continue
            if student_group and not (_split_group_components(row.get("group_name")) & student_group):
                continue
        if div_key and row_div != div_key:
            continue
        if subj_canonical:
            if subj_canonical not in row_subj.lower():
                continue
        elif subj_norm and subj_norm not in row_subj.lower():
            continue

        key = (fname, row_subj, _safe_text(row.get("division")))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "faculty": fname,
            "subject": row_subj,
            "division": _safe_text(row.get("division")),
            "group": _safe_text(row.get("group_name")),
        })

    if not out:
        return [{"error": "No matching teaching assignments found."}]
    return _cap_rows(out)


@mcp.tool()
def get_timetable(
    room: str = "", day: str = "", time: str = "", entity: str = "",
    division: str = "", semester: Optional[int] = None,
    access_role: str = "admin", allowed_sem: Optional[int] = None,
) -> List[Dict[str, str]]:
    """Return timetable entries filtered by room, day, time, person, division, or semester.
    Supports faculty/student names or roll numbers and returns day, time, subject,
    faculty, division, group, and room. Use `division` (e.g. "Division 3") and/or
    `semester` (e.g. 5 or 7) for broad requests like "sem 5 timetable" or
    "division 3 timetable" that don't name a specific person."""
    fac_map = _faculty_name_map()
    is_faculty_query = bool(entity) and _find_faculty(entity) is not None
    rows = _timetable_rows(access_role, allowed_sem, faculty_query=is_faculty_query)

    days = _extract_day_filters(day) if day else set()
    times = _extract_time_filters(time) if time else []
    room_norm = re.sub(r"[^A-Z0-9]", "", room.upper()) if room else ""
    div_filter = _division_key(division) if division else None

    student_subject_keys: Optional[Set[str]] = None
    student_div: Optional[str] = None
    student_group: Optional[Set[str]] = None
    faculty_id: Optional[str] = None

    if entity:
        student = _find_student(entity, access_role, allowed_sem)
        if student:
            student_subject_keys = _student_subject_keys(student)
            student_div = _division_value(student.get("division"))
            student_group = _split_group_components(student.get("group_name"))
        else:
            faculty = _find_faculty(entity)
            if faculty:
                faculty_id = str(faculty.get("id"))

    out: List[Dict[str, str]] = []
    for row in rows:
        if days and str(row.get("day_of_week", "")).lower() not in days:
            continue
        if times and not _row_matches_time(row, times):
            continue
        if room_norm:
            row_room = re.sub(r"[^A-Z0-9]", "", str(row.get("classroom", "")).upper())
            if row_room != room_norm:
                continue
        if div_filter and _division_value(row.get("division")) != div_filter:
            continue
        if semester is not None and int(row.get("semester", 0)) != int(semester):
            continue
        if faculty_id and str(row.get("faculty_id")) != faculty_id:
            continue
        if student_subject_keys is not None:
            row_subj = _clean_subject_name(_safe_text(row.get("subject"))).lower()
            if row_subj not in student_subject_keys:
                continue
            if student_div and _division_value(row.get("division")) != student_div:
                continue
            if student_group and not (_split_group_components(row.get("group_name")) & student_group):
                continue

        out.append({
            "day": _safe_text(row.get("day_of_week")),
            "start_time": _safe_text(row.get("start_time")),
            "end_time": _safe_text(row.get("end_time")),
            "subject": _clean_subject_name(_safe_text(row.get("subject"))),
            "faculty": _tt_row_faculty_name(row, fac_map),
            "division": _safe_text(row.get("division")),
            "group": _safe_text(row.get("group_name")),
            "room": _safe_text(row.get("classroom")),
        })

    if not out:
        return [{"error": "No matching timetable entries found."}]
    return _cap_rows(out)


@mcp.tool()
def get_free_slots(
    entity: str, day: str, access_role: str = "admin", allowed_sem: Optional[int] = None
) -> Dict[str, Any]:
    """Return free/busy slots for a student or faculty member on a given day.
    Schedule range: 09:00-18:00. Returns busy and free time ranges."""
    days = _extract_day_filters(day)
    if not days:
        return {"error": f"Could not recognize a weekday in '{day}'."}
    day_name = next(iter(days))

    rows = get_timetable(
        entity=entity, day=day_name, access_role=access_role, allowed_sem=allowed_sem
    )  # type: ignore[arg-type]
    if rows and "error" in rows[0]:
        busy_intervals: List[tuple] = []
    else:
        busy_intervals = []
        for r in rows:
            if "start_time" not in r or "end_time" not in r:
                continue  # skip the "N more rows omitted" note, if present
            s, e = _time_to_minutes(r["start_time"]), _time_to_minutes(r["end_time"])
            if s is not None and e is not None and e > s:
                busy_intervals.append((s, e))

    busy_intervals.sort()
    merged: List[tuple] = []
    for s, e in busy_intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    DAY_START, DAY_END = 9 * 60, 18 * 60
    free: List[tuple] = []
    cursor = DAY_START
    for s, e in merged:
        if s > cursor:
            free.append((cursor, min(s, DAY_END)))
        cursor = max(cursor, e)
    if cursor < DAY_END:
        free.append((cursor, DAY_END))

    def _fmt(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    return {
        "day": day_name.title(),
        "busy": [f"{_fmt(s)}-{_fmt(e)}" for s, e in merged],
        "free": [f"{_fmt(s)}-{_fmt(e)}" for s, e in free if e > s],
    }


if __name__ == "__main__":
    mcp.run()  # stdio transport