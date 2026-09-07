"""
ga_engine.py
Pure Python scheduling engine extracted from the original Tkinter
desktop app (Finalone_1_-1-1_fixed-2.py). No GUI / Tk / openpyxl
dependency here at all -- this module only reads CSVs and runs the
Genetic Algorithm. The Flask backend (app.py) imports this module
and exposes it over HTTP; the CourseTable / TimetableApp Tkinter
classes from the original file were intentionally NOT copied here.
"""
import random
import copy
import colorsys
import csv
import os
import hashlib
import math
from datetime import date, datetime, timedelta

# Folder that holds department.csv / faculty.csv / courses.csv /
# semester_dates.csv / exam_dates.csv. Overridden by app.py before any
# of the load_*() functions below are called, so the same engine code
# works no matter where the Flask app is launched from.
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _data_path(filename):
    return os.path.join(DATA_DIR, filename)

# ============================================================
# STATIC DATA
# ============================================================

def load_departments():
    departments=[]

    with open(_data_path("department.csv"), "r", encoding="utf-8") as file:
        reader=csv.DictReader(file)

        for row in reader:
            departments.append(row["Department"])

    return departments

DEPARTMENTS = load_departments()

# ---- SHIFTS ------------------------------------------------
# Shift 1 runs all 5 classes. Shift 2 only runs the 3 UG classes.
# Every class in the code is now addressed with a composite key
# "Shift X::Class Name" (see ckey/key_shift/key_class helpers) so that
# "UG 1st Year" in Shift 1 and "UG 1st Year" in Shift 2 are kept as two
# completely separate timetables (different students, different faculty
# assignment, own generation run) even though they share a display name.

SHIFT_LABELS = ["Shift 1", "Shift 2"]

# Extra option shown ONLY in the "Lab Timetable" shift dropdown - lets the
# user see both shifts' lab hours together in one combined table.
LAB_COMBINED_LABEL = "Shift 1 & Shift 2"

SHIFT_CLASS_LIST = {
    "Shift 1": ["UG 1st Year", "UG 2nd Year", "UG 3rd Year", "PG 1st Year", "PG 2nd Year"],
    "Shift 2": ["UG 1st Year", "UG 2nd Year", "UG 3rd Year"],
}


def ckey(shift, cname):
    return f"{shift}::{cname}"


def key_shift(k):
    return k.split("::", 1)[0]


def key_class(k):
    return k.split("::", 1)[1]


ALL_KEYS = [ckey(s, c) for s in SHIFT_LABELS for c in SHIFT_CLASS_LIST[s]]

# Only 2 physical lab rooms exist for the whole department, shared by
# whichever classes are running (within the SAME shift, since two
# different shifts never run at the same real clock time). So at any
# given (day, period) inside one shift, at most this many classes may be
# doing a lab session at once.
LAB_ROOMS = 2

CLASS_NAMES = ["UG 1st Year", "UG 2nd Year", "UG 3rd Year", "PG 1st Year", "PG 2nd Year"]

CLASS_TO_YEARKEY = {
    "UG 1st Year": "1st UG",
    "UG 2nd Year": "2nd UG",
    "UG 3rd Year": "3rd UG",
    "PG 1st Year": "1st PG",
    "PG 2nd Year": "2nd PG",
}

# Short labels used in the combined "All Timetable" / "Faculty Timetable"
# views (matches the college's own printed timetable abbreviations).
CLASS_ABBR = {
    "UG 1st Year": "I BSc",
    "UG 2nd Year": "II BSc",
    "UG 3rd Year": "III BSc",
    "PG 1st Year": "I MSc",
    "PG 2nd Year": "II MSc",
}

# Odd / Even semester mapping (all classes run together, so the whole
# college is either in an ODD term or an EVEN term at any given time).
SEM_ODD = {"1st UG": "I", "2nd UG": "III", "3rd UG": "V", "1st PG": "I", "2nd PG": "III"}
SEM_EVEN = {"1st UG": "II", "2nd UG": "IV", "3rd UG": "VI", "1st PG": "II", "2nd PG": "IV"}

def load_faculties():
    faculty=[]

    with open(_data_path("faculty.csv"), "r", encoding="utf-8") as file:
        reader=csv.DictReader(file)

        for row in reader:
            faculty.append(row["FacultyName"])

    return faculty

FACULTIES = load_faculties()

def default_hours_for(course_name):
    """Fallback hours/week, used ONLY when a course in courses.csv has no
    Hours value filled in: an Internship gets 0 hours (so it never
    occupies a slot on the day/period grid), a Lab gets 3 hours/week, and
    every other course gets 1 hour/week."""
    n = course_name.strip().lower()
    if "internship" in n:
        return 0
    if "lab" in n:
        return 3
    return 1


def load_courses_csv():
    """Reads courses.csv and builds three parallel structures:

    - COURSE_PRESETS[shift][dept][year_key][sem] -> [course names...]
    - COURSE_HOURS[shift][dept][year_key][sem]    -> {course name: hours}
    - COURSE_FACULTY[shift][dept][year_key][sem]  -> {course name: faculty name}

    courses.csv columns: Shift, Department, Semester, Class, Course, Faculty, Hours
    The "Hours" column is OPTIONAL per row - if it is left blank (or the
    column doesn't exist in the CSV at all), the hours/week for that
    course falls back to default_hours_for(course) automatically.
    The "Faculty" column is also OPTIONAL per row - if it is left blank
    (or the column doesn't exist at all), the faculty is left blank and
    still has to be picked by hand in the app, exactly like before."""

    data = {}
    hours_data = {}
    faculty_data = {}

    with open(_data_path("courses.csv"), newline="", encoding="utf-8") as file:

        reader = csv.DictReader(file)

        for row in reader:

            shift = (row.get("Shift") or "").strip()
            dept = (row.get("Department") or "").strip()
            sem = (row.get("Semester") or "").strip()
            cls = (row.get("Class") or "").strip()
            course = (row.get("Course") or "").strip()
            hours_raw = (row.get("Hours") or "").strip()
            faculty_raw = (row.get("Faculty") or "").strip()

            # skip blank / separator rows in the CSV
            if not shift or not dept or not sem or not cls or not course:
                continue

            # CSV "Class" column stores the long name ("UG 1st Year") but
            # the rest of the app looks courses up by the short year-key
            # ("1st UG") via CLASS_TO_YEARKEY, so convert it here.
            year_key = CLASS_TO_YEARKEY.get(cls, cls)

            if shift not in data:
                data[shift] = {}
                hours_data[shift] = {}
                faculty_data[shift] = {}

            if dept not in data[shift]:
                data[shift][dept] = {}
                hours_data[shift][dept] = {}
                faculty_data[shift][dept] = {}

            if year_key not in data[shift][dept]:
                data[shift][dept][year_key] = {}
                hours_data[shift][dept][year_key] = {}
                faculty_data[shift][dept][year_key] = {}

            if sem not in data[shift][dept][year_key]:
                data[shift][dept][year_key][sem] = []
                hours_data[shift][dept][year_key][sem] = {}
                faculty_data[shift][dept][year_key][sem] = {}

            data[shift][dept][year_key][sem].append(course)

            if hours_raw.isdigit():
                hours_data[shift][dept][year_key][sem][course] = int(hours_raw)
            else:
                hours_data[shift][dept][year_key][sem][course] = default_hours_for(course)

            faculty_data[shift][dept][year_key][sem][course] = faculty_raw

    return data, hours_data, faculty_data

COURSE_PRESETS, COURSE_HOURS, COURSE_FACULTY = load_courses_csv()

DEFAULT_COURSES = [f"Subject {i}" for i in range(1, 9)] + ["Lab 1", "Lab 2"]

DAYS = ["I", "II", "III", "IV", "V", "VI"]
PERIODS = ["9:00-9:55", "9:55-10:50", "10:50-11:45", "LUNCH", "12:15-1:10", "1:10-2:05"]
LUNCH_IDX = PERIODS.index("LUNCH")

# ============================================================
# ACADEMIC CALENDAR / DAY-ORDER LOOKUP
# ============================================================
# Day Order (I..VI, same labels as DAYS above) cycles continuously
# through working days only - it does NOT reset every calendar week.
# Working days = Monday-Friday, excluding government holidays below.
# When Day VI is reached, the very next working day starts again at I.
#
# The 4 semester dates below are read from "semester_dates.csv" (same
# folder as this .py file), NOT hardcoded, so they can be updated every
# year just by editing that CSV. Expected file format - header row plus
# exactly one row for ODD and one row for EVEN:
#
#   Semester,StartDate,EndDate
#   ODD,15-06-2026,30-10-2026
#   EVEN,01-12-2026,10-04-2027
#
# Dates must be written as DD-MM-YYYY, same as the "Enter Date" box.

def load_semester_dates():
    """Reads semester_dates.csv and returns
    (odd_start, odd_end, even_start, even_end) as date objects."""
    parsed = {}
    with open(_data_path("semester_dates.csv"), "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            sem = (row.get("Semester") or "").strip().upper()
            start_raw = (row.get("StartDate") or "").strip()
            end_raw = (row.get("EndDate") or "").strip()
            if sem not in ("ODD", "EVEN") or not start_raw or not end_raw:
                continue
            parsed[sem] = (
                datetime.strptime(start_raw, "%d-%m-%Y").date(),
                datetime.strptime(end_raw, "%d-%m-%Y").date(),
            )

    if "ODD" not in parsed or "EVEN" not in parsed:
        raise ValueError(
            'semester_dates.csv must have one "ODD" row and one "EVEN" row '
            'with StartDate/EndDate columns in DD-MM-YYYY format.'
        )

    return parsed["ODD"][0], parsed["ODD"][1], parsed["EVEN"][0], parsed["EVEN"][1]


ODD_SEM_START, ODD_SEM_END, EVEN_SEM_START, EVEN_SEM_END = load_semester_dates()

# Total working days in one semester (used for the Working-Days-remaining
# and Percentage-complete figures shown under "check Day Order for a date").
TOTAL_WORKING_DAYS = 90

# Tamil Nadu Government holidays that fall inside the two semester
# windows above (source: official 2026 TN Govt holiday list, G.O. Ms.
# No. 708). The Jan/2027 dates (Pongal cluster, Republic Day) follow
# the usual fixed pattern but the state's official 2027 order had not
# been issued yet as of when this list was put together - please
# re-check and edit this dict once that notification is out.
GOVT_HOLIDAYS = {
    date(2026, 6, 26): "Muharram",
    date(2026, 8, 15): "Independence Day",
    date(2026, 8, 26): "Milad-un-Nabi",
    date(2026, 9, 4): "Krishna Jayanthi",
    date(2026, 9, 14): "Vinayakar Chathurthi",
    date(2026, 10, 2): "Gandhi Jayanthi",
    date(2026, 10, 19): "Ayutha Pooja",
    date(2026, 10, 20): "Vijaya Dashami",
    date(2026, 12, 25): "Christmas",
    date(2027, 1, 1): "New Year's Day",
    date(2027, 1, 14): "Bhogi (tentative)",
    date(2027, 1, 15): "Thai Pongal (tentative)",
    date(2027, 1, 16): "Thiruvalluvar Day (tentative)",
    date(2027, 1, 17): "Uzhavar Thirunal (tentative)",
    date(2027, 1, 26): "Republic Day",
}


def get_day_order(target_date):
    """Returns (day_order_label, sem_name, week_no, working_done,
    is_holiday, holiday_reason) for a given calendar date.

    - day_order_label is one of DAYS ("I".."VI"), or None when the date
      itself is not a working day (Saturday / Sunday / a government
      holiday) - in that case is_holiday is True and holiday_reason
      explains why.
    - sem_name / week_no / working_done are still returned even on a
      holiday date, based on how many working days have been completed
      up to (but not including) that date, so Week / Working Days /
      Percentage keep working correctly for holidays too.
    - working_done = how many working days of this semester have been
      completed as of target_date (the college's first working day
      counts as day 1 -> Day Order I).
    - week_no = ceil(working_done / 7) - weeks are counted in blocks of
      7 *working* days from the semester's first working day, not
      calendar weeks (so 3 working days in = Week 1, 12 working days in
      = Week 2, and so on).
    - Returns (None, None, None, None, False, reason) when the date
      falls outside both semester windows entirely.
    """
    if ODD_SEM_START <= target_date <= ODD_SEM_END:
        sem_start, sem_name = ODD_SEM_START, "Odd Semester"
    elif EVEN_SEM_START <= target_date <= EVEN_SEM_END:
        sem_start, sem_name = EVEN_SEM_START, "Even Semester"
    else:
        return None, None, None, None, False, "This date falls outside both semester periods."

    is_holiday = False
    holiday_reason = None
    if target_date.weekday() >= 5:
        is_holiday = True
        holiday_reason = "Saturday" if target_date.weekday() == 5 else "Sunday"
    elif target_date in GOVT_HOLIDAYS:
        is_holiday = True
        holiday_reason = GOVT_HOLIDAYS[target_date]

    # Count working days from the start of this semester up to and
    # including target_date (a holiday date itself never adds to the
    # count), then map onto the I..VI cycle.
    working_day_count = 0
    d = sem_start
    while d <= target_date:
        if d.weekday() < 5 and d not in GOVT_HOLIDAYS:
            working_day_count += 1
        d += timedelta(days=1)

    week_no = max(1, math.ceil(working_day_count / 7)) if working_day_count > 0 else 1

    if is_holiday:
        return None, sem_name, week_no, working_day_count, True, holiday_reason

    order_idx = (working_day_count - 1) % len(DAYS)
    return DAYS[order_idx], sem_name, week_no, working_day_count, False, None


def get_day_order_info(date_str):
    """JSON-friendly wrapper around get_day_order() for the "Day Order"
    web card. Accepts either DD-MM-YYYY (typed input) or YYYY-MM-DD
    (what an HTML <input type="date"> sends) and returns a dict with
    the same Date/Day/Semester/Day-Order, Week/Working-Days/Balance and
    Percentage figures the desktop app's Step 3 panel shows.
    """
    raw = (date_str or "").strip()
    target = None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            target = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue
    if target is None:
        return {"ok": False, "error": "Please enter a valid date (DD-MM-YYYY)."}

    order, sem_name, week_no, working_done, is_holiday, reason = get_day_order(target)

    if sem_name is None:
        return {"ok": False, "error": reason}

    order_txt = "Holiday" if is_holiday else order
    remaining = max(0, TOTAL_WORKING_DAYS - working_done)
    completed_for_pct = min(working_done, TOTAL_WORKING_DAYS)
    percent = round((completed_for_pct / TOTAL_WORKING_DAYS) * 100)

    return {
        "ok": True,
        "date": target.strftime("%d-%m-%Y"),
        "weekday": target.strftime("%A"),
        "semester": sem_name,
        "day_order": order_txt,
        "is_holiday": is_holiday,
        "holiday_reason": reason if is_holiday else None,
        "week_no": week_no,
        "working_done": working_done,
        "remaining": remaining,
        "total_working_days": TOTAL_WORKING_DAYS,
        "percent": percent,
    }

# Courses that must NEVER appear twice on the same day (hard rule, never
# relaxed under any circumstance). Matched case-insensitively against the
# course name.
HARD_ONE_PER_DAY = {"language", "english", "tamil"}


def is_hard_one_per_day(course_name):
    n = course_name.strip().lower()
    return any(kw in n for kw in HARD_ONE_PER_DAY)


# Courses that must NEVER be listed on the "Exam Timetable"
#(Labs, Internship, Extension Activity, General Studies, Project, Values Education). Everything
# else - including Language / English - DOES appear on the exam
# timetable. Matched case-insensitively (substring match) against the
# course name.
EXAM_EXCLUDE_KEYWORDS = ["lab", "internship", "extension activity", "general studies", "project", "value education"]


def is_exam_excluded(course_name, is_lab=False, hours=None):
    n = course_name.strip().lower()
    if is_lab:
        return True
    if hours is not None:
        try:
            if float(hours) <= 0:
                return True
        except (TypeError, ValueError):
            pass
    return any(kw in n for kw in EXAM_EXCLUDE_KEYWORDS)


# ---- EXAM DATES (exam_dates.csv) ---------------------------
# Columns required:  ExamType, Semester, DayOrder, Date, Day
#   ExamType -> "Internal 1" / "Internal 2" / "Model"  (must match EXAM_TYPES)
#   Semester -> "ODD" or "EVEN"  (must match the Term dropdown at the top
#                of the app - Odd-semester classes get their dates from
#                the ODD rows, Even-semester classes get theirs from the
#                EVEN rows, for the SAME ExamType)
#   DayOrder -> "I".."VI"  (which day-order of the regular student
#                timetable this exam-date stands in for - this is how the
#                app knows WHICH paper falls on this date: whatever paper
#                that class's 2-hour block landed on for that day-order)
#   Date     -> the real calendar date, e.g. 21.03.2025  (shown as-is)
#   Day      -> weekday name, e.g. Friday  (shown as-is, optional)
#
# One row per exam-date. Each (ExamType, Semester) combination usually
# needs up to 6 rows (DayOrder I..VI), e.g.:
#
#   ExamType,Semester,DayOrder,Date,Day
#   Internal 1,ODD,I,21.03.2025,Friday
#   Internal 1,ODD,II,24.03.2025,Monday
#   Internal 1,ODD,III,25.03.2025,Tuesday
#   Internal 1,ODD,IV,26.03.2025,Wednesday
#   Internal 1,ODD,V,27.03.2025,Thursday
#   Internal 1,ODD,VI,29.03.2025,Saturday
#   Internal 1,EVEN,I,18.08.2025,Monday
#   Internal 1,EVEN,II,19.08.2025,Tuesday
#   ...
#   Internal 2,ODD,I,...
#   Model,EVEN,I,...
#
# The file is OPTIONAL at startup - if it's missing, EXAM_DATES stays
# empty and the Exam Timetable view just shows a message asking for it.
EXAM_TYPES = ["Internal 1", "Internal 2", "Model"]


def load_exam_dates():
    """Returns {(exam_type, term): [ {day_order, date, day}, ... ]}
    term is always "ODD" or "EVEN" (normalized upper-case), matching the
    Term dropdown (self.term_var) already used elsewhere in the app to
    decide which semester's courses to load."""
    data = {}
    if not os.path.exists(_data_path("exam_dates.csv")):
        return data
    with open(_data_path("exam_dates.csv"), newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            exam_type = (row.get("ExamType") or "").strip()
            term = (row.get("Semester") or "").strip().upper()
            day_order = (row.get("DayOrder") or "").strip().upper()
            date = (row.get("Date") or "").strip()
            day = (row.get("Day") or "").strip()
            if not exam_type or term not in ("ODD", "EVEN") or not day_order or not date:
                continue
            data.setdefault((exam_type, term), []).append(
                {"day_order": day_order, "date": date, "day": day})
    return data


EXAM_DATES = load_exam_dates()


def reload_data():
    """Re-reads every CSV (courses, faculty, department, semester dates,
    exam dates) from disk and refreshes the module-level caches above.

    Why this exists: all the CSV data is loaded ONCE, when this module
    is first imported (i.e. when the Flask server starts). Editing a
    .csv file afterwards does NOT update those in-memory values, and
    Flask's debug auto-reloader only restarts the server for .py file
    changes - never for .csv changes - so without this function the
    app would keep serving stale/old data until the server process is
    manually stopped and started again. app.py calls this before every
    request so CSV edits show up immediately on the next Generate
    click, no restart needed.
    """
    global DEPARTMENTS, FACULTIES, COURSE_PRESETS, COURSE_HOURS, COURSE_FACULTY
    global ODD_SEM_START, ODD_SEM_END, EVEN_SEM_START, EVEN_SEM_END, EXAM_DATES

    DEPARTMENTS = load_departments()
    FACULTIES = load_faculties()
    COURSE_PRESETS, COURSE_HOURS, COURSE_FACULTY = load_courses_csv()
    ODD_SEM_START, ODD_SEM_END, EVEN_SEM_START, EVEN_SEM_END = load_semester_dates()
    EXAM_DATES = load_exam_dates()
    _SHIFT1_LAB_CACHE.clear()


# contiguous runs of teaching periods (used to keep lab blocks from
# spanning across the lunch break)
SEGMENTS = []
_run = []
for _i, _p in enumerate(PERIODS):
    if _p == "LUNCH":
        if _run:
            SEGMENTS.append(_run)
        _run = []
    else:
        _run.append(_i)
if _run:
    SEGMENTS.append(_run)
MAX_BLOCK_LEN = max(len(s) for s in SEGMENTS)

BG = "#f5f0e8"
HEADER_BG = "#1e3a5f"
TABLE_HDR = "#6b8f5e"
ROW_EVEN = "#eef5fb"
ROW_ODD = "#ffffff"
BTN_OK = "#1e3a5f"
BTN_GEN = "#1e3a5f"
LAB_CLR = "#f5d4a0"
# Used ONLY in the single-Faculty Timetable view (_render_faculty_single):
# every Lab Hour cell, for EVERY faculty, shows this one same dark color
# (instead of the per-class pastel color), so lab periods stand out
# clearly no matter which faculty's timetable is being viewed.
FACULTY_LAB_DARK_CLR = "#1b2a4a"   # dark blue
THEORY_CLR = "#dbe7f0"   # fallback color used when a session has no faculty assigned
FREE_CLR = "#d9f2d9"     # color used for "FREE" cells in the faculty timetable

# Fixed distinct pastel color per CLASS, used only in the combined Faculty
# Timetable view so each class is visually separated no matter which
# faculty is being viewed.
CLASS_COLORS = {
    "UG 1st Year": "#f6c6c6",
    "UG 2nd Year": "#c6e6f6",
    "UG 3rd Year": "#d6f6c6",
    "PG 1st Year": "#f6e3c6",
    "PG 2nd Year": "#e0c6f6",
}

# ============================================================
# FACULTY -> COLOR (different hue per faculty, all light/pastel)
# ============================================================


def generate_faculty_shades(faculty_list, hue_shift=0.0, light=0.83, sat=0.50):
    """Give every distinct faculty their own LIGHT pastel color, but with a
    DIFFERENT hue per faculty (not all one blue family). Lightness and
    saturation are kept the same for everyone so every color stays light
    and easy on the eyes, while the hue spacing (golden-ratio step) keeps
    consecutive faculty visually distinct from one another.

    `hue_shift` rotates the whole palette by a fixed amount. This lets us
    generate a SECOND palette for the same faculty list (e.g. one for
    THEORY sessions, another for LAB sessions) that is still light/pastel
    but visually distinct from the first palette, so a faculty's theory
    paper and their lab no longer end up looking like the same color."""
    colors = {}
    n = len(faculty_list)
    if n == 0:
        return colors

    golden_ratio_conjugate = 0.618033988749895
    start_hue = 0.05          # skip pure red so it doesn't look like a warning color

    for i, fac in enumerate(faculty_list):
        hue = (start_hue + hue_shift + i * golden_ratio_conjugate) % 1.0
        r, g, b = colorsys.hls_to_rgb(hue, light, sat)
        colors[fac] = '#%02x%02x%02x' % (int(r * 255), int(g * 255), int(b * 255))
    return colors


# ============================================================
# GENETIC ALGORITHM CORE  (pure functions, no Tk dependency)
# ============================================================
# All hard-rule logic from the original version is kept exactly as it
# was. The only additions are:
#   1) every function now takes an explicit `class_names` list instead of
#      reading the old global CLASS_NAMES constant, so it can be run once
#      per SHIFT (each shift is generated completely independently, since
#      two shifts never occupy the same real clock time);
#   2) a new hard rule -> at most LAB_ROOMS (2) classes within the SAME
#      shift may be doing a lab at the same (day, period), because only 2
#      physical lab rooms exist.

DAY_PATTERNS = {
    # 1-hour theory periods: any single non-lunch period
    1: [(p,) for p in range(len(PERIODS)) if p != LUNCH_IDX],
    # 2-hour blocks: either two consecutive morning periods, or the two
    # afternoon periods
    2: [(0, 1), (1, 2), (4, 5)],
    # 3-hour blocks: three legal options -
    #   (0, 1, 2) -> the whole morning run, truly back-to-back, no break.
    #   (1, 2, 4) -> hours II, III, IV - periods II and III, then a lunch
    #                break, then IV.
    #   (2, 4, 5) -> hours III, IV, V - period III, then a lunch break,
    #                then IV and V. This one (like (1, 2, 4)) DOES have
    #                the lunch break sitting in the middle (by design -
    #                it's fine for a lab to pause for lunch and continue
    #                afterward), but it still counts as ONE continuous
    #                3-hour lab session for that class/day, same as the
    #                morning option.
    # Having 3 valid patterns instead of 1 raises the weekly capacity for
    # 3-hour labs to 6 days x 2 rooms x 3 patterns = 36 slots (instead of
    # 12), which is the main fix for the lab-room shortage that was
    # leaving the odd class's lab unable to find a slot at all.
    3: [(0, 1, 2), (1, 2, 4), (2, 4, 5)],
}


def split_lab_hours(hours, max_len=MAX_BLOCK_LEN, prefer_two_hour_blocks=False):
    """Split a lab's total weekly hours into separate blocks, each block
    no longer than max_len periods (so it never has to cross lunch),
    and each block ends up on a DIFFERENT day.

    `prefer_two_hour_blocks=True` (used ONLY for Shift 2) lets a lab whose
    hours would otherwise become multiple 3-hour blocks (e.g. 6 -> [3,3])
    split into all 2-hour blocks instead (6 -> [2,2,2]). The 3-hour block
    can use either of the 2 patterns for a 3-hour block - (0,1,2) or
    (2,4,5), see DAY_PATTERNS - so with only LAB_ROOMS (2)
    physical rooms there are just 6 days x 2 rooms = 12 such slots for the
    WHOLE college (both shifts combined). Splitting Shift 2's 6-hour labs
    into 2-hour blocks instead frees up the 2-hour patterns - (0,1), (1,2),
    (4,5) - which have 3x the slots (6 days x 2 rooms x 3 patterns = 36),
    easing the shortage without touching Shift 1 at all.

    Shift 1 NEVER uses this flag - its 6-hour labs always stay [3,3], no
    other option, exactly as before. The LAB_ROOMS=2 hard cap (never more
    than 2 classes in a lab at the same real time, across both shifts) is
    unchanged and still enforced everywhere."""
    hours = max(2, hours)
    if prefer_two_hour_blocks and hours % 2 == 0:
        return [2] * (hours // 2)
    blocks = []
    remaining = hours
    while remaining > 0:
        blk = min(max_len, remaining)
        if remaining - blk == 1 and blk > 2:
            blk -= 1
        blocks.append(blk)
        remaining -= blk
    return blocks


def split_theory_hours(hours, always_one_hour=False):
    """Split a THEORY course's total weekly hours into per-day blocks:

    - `always_one_hour=True` (used for Language / English) -> EVERY hour
      always stays its own separate 1-hour block, on its own day, no
      matter how many total hours/week it has (2 hours -> [1, 1] split
      across 2 different days, 1 hour -> [1] on its own). It must NEVER
      get a 2-hour continuous block.
    - otherwise, hours <= 2 -> every hour stays its own separate 1-hour
      block (each lands on a different day), exactly like before.
    - otherwise, hours > 2  -> ONE 2-hour continuous block (same day,
      back-to-back periods) plus the remaining hours as separate 1-hour
      blocks, each landing on its own different day.

    e.g. (normal theory) 6 hours/week -> [2, 1, 1, 1, 1]  (one day gets a
    2-hr continuous session, the other 4 hours each get their own day.)
    e.g. (normal theory) 3 hours/week -> [2, 1]
    e.g. (normal theory) 2 hours/week -> [1, 1]
    e.g. (normal theory) 1 hour/week  -> [1]
    e.g. (Language/English) 6 hours/week -> [1, 1, 1, 1, 1, 1]
    e.g. (Language/English) 2 hours/week -> [1, 1]
    e.g. (Language/English) 1 hour/week  -> [1]
    """
    hours = max(1, hours)
    if always_one_hour or hours <= 2:
        return [1] * hours
    return [2] + [1] * (hours - 2)


def build_sessions(course_list, shift=None):
    """course_list: list of dicts {name, faculty, hours, is_lab}
    `shift`: "Shift 1" or "Shift 2" - only Shift 2 is allowed to split a
    6-hour (or other even-hour) lab into 2-hour blocks (2,2,2) instead of
    forcing 3-hour blocks (3,3). Shift 1 is untouched - its 6-hour labs
    always stay [3,3], exactly as before.
    Returns list of session dicts: {course_idx, name, faculty, is_lab, length}"""
    sessions = []
    prefer_two = (shift == "Shift 2")
    for idx, c in enumerate(course_list):
        if c["hours"] <= 0:
            # 0 hrs/week means this course does NOT belong on the
            # classroom day/period grid at all (e.g. "Internship", which
            # happens outside normal class hours). Skip it completely so
            # it never occupies a slot and never shows up in the
            # "could not be scheduled" warning.
            continue
        if c["is_lab"]:
            for length in split_lab_hours(c["hours"], prefer_two_hour_blocks=prefer_two):
                sessions.append({"course_idx": idx, "name": c["name"], "faculty": c["faculty"],
                                  "is_lab": True, "length": length})
        else:
            hours = max(1, min(c["hours"], len(DAYS)))
            # Language / English must NEVER get a 2-hour continuous
            # block - always split into separate 1-hour-per-day blocks,
            # regardless of how many total hours/week it has.
            force_one_hour = is_hard_one_per_day(c["name"])
            for length in split_theory_hours(hours, always_one_hour=force_one_hour):
                sessions.append({"course_idx": idx, "name": c["name"], "faculty": c["faculty"],
                                  "is_lab": False, "length": length})
    return sessions


def _attempt_place(s, occupied_set, course_days_dict, faculty_occ_set, lab_occ_dict, lab_occ_baseline=None, rng=None):
    """Try to find a legal (day, periods) for ONE session under the HARD
    rules (never relaxed):
    1) no overlap within its own class (occupied_set),
    2) the assigned faculty is never double-booked (faculty_occ_set,
       shared across every class IN THE SAME SHIFT),
    3) a course in HARD_ONE_PER_DAY (Language / English) never appears
       twice on the same day,
    4) if this session is a LAB, at most LAB_ROOMS classes (within the
       same shift) may be doing a lab at that same (day, period) - only
       LAB_ROOMS physical lab rooms exist (lab_occ_dict). `lab_occ_baseline`
       (optional) adds in how many of those same LAB_ROOMS are ALREADY
       taken up by a DIFFERENT shift at that (day, period) - since there
       are only LAB_ROOMS physical lab rooms in total for the whole
       college, shared by every shift, not just this one.

    `periods` is an explicit tuple of period-indices for that day (e.g.
    (0,1,2) for a full morning lab, or (2,4,5) for the III/IV/V pattern
    which intentionally pauses for lunch in the middle). Most patterns in
    DAY_PATTERNS are a truly continuous, unbroken run of periods; the one
    exception is the (2,4,5) 3-hour pattern, which is allowed to have the
    lunch break sitting in the middle by design.

    The only thing ever relaxed (and only for courses NOT in
    HARD_ONE_PER_DAY) is a course repeating on the same day. The faculty
    rule and the lab-room rule are NEVER relaxed.

    Returns (day, periods) if a legal slot was found, else None.
    """
    special = is_hard_one_per_day(s["name"])
    patterns = DAY_PATTERNS.get(s["length"], [])
    combos = [(d, periods) for d in range(len(DAYS)) for periods in patterns]
    (rng or random).shuffle(combos)

    def faculty_free(d, periods):
        if not s["faculty"]:
            return True
        return all((s["faculty"], d, p) not in faculty_occ_set for p in periods)

    def lab_free(d, periods):
        if not s["is_lab"]:
            return True
        for p in periods:
            used = lab_occ_dict.get((d, p), 0)
            if lab_occ_baseline:
                used += lab_occ_baseline.get((d, p), 0)
            if used >= LAB_ROOMS:
                return False
        return True

    # pass 1: cell free + same-day rule + faculty free + lab-room free (all hard)
    for d, periods in combos:
        cells = [(d, p) for p in periods]
        if any(c in occupied_set for c in cells):
            continue
        if d in course_days_dict.get(s["course_idx"], set()):
            continue
        if not faculty_free(d, periods):
            continue
        if not lab_free(d, periods):
            continue
        return d, periods

    # pass 2: relax same-day rule ONLY for non-special courses; faculty
    # rule and lab-room rule stay hard, always.
    if not special:
        for d, periods in combos:
            cells = [(d, p) for p in periods]
            if any(c in occupied_set for c in cells):
                continue
            if not faculty_free(d, periods):
                continue
            if not lab_free(d, periods):
                continue
            return d, periods

    return None


def _commit(assignment, cname, si, s, d, periods, occupied, course_days, faculty_occ, lab_occ):
    for p in periods:
        occupied[cname].add((d, p))
    course_days[cname].setdefault(s["course_idx"], set()).add(d)
    if s["faculty"]:
        for p in periods:
            faculty_occ.add((s["faculty"], d, p))
    if s["is_lab"]:
        for p in periods:
            lab_occ[(d, p)] = lab_occ.get((d, p), 0) + 1
    assignment[cname][si] = (d, periods)


def random_init_individual(all_sessions, class_names, max_attempts=8, lab_occ_baseline=None, rng=None):
    """Build one full individual (every class in `class_names`, i.e. one
    shift) together, sharing a single faculty_occ set (no faculty double
    booking) and a single lab_occ counter (no more than LAB_ROOMS classes
    in a lab at the same day/period), both scoped to this one shift.
    `lab_occ_baseline` (optional) additionally reserves however many of
    those LAB_ROOMS are already used up by ANOTHER shift at that same
    (day, period), since the physical lab rooms are shared college-wide.

    KEY FIX: sessions are placed LONGEST-FIRST (3-hour / 2-hour lab blocks
    before 1-hour theory periods). Labs need a full free segment, so if
    short theory sessions grab slots first at random, big lab blocks can
    run out of room and end up unplaced. Placing the hardest-to-fit
    sessions first, while the most slots are still free, fixes that.

    A few random restarts are tried, keeping whichever attempt leaves the
    fewest sessions unplaced (ideally zero)."""
    best_assignment = None
    best_unplaced_count = None

    for _attempt in range(max_attempts):
        global_items = []
        for cname in class_names:
            for i, s in enumerate(all_sessions[cname]):
                global_items.append((cname, i, s))
        (rng or random).shuffle(global_items)
        global_items.sort(key=lambda x: -x[2]["length"])  # longest blocks first

        assignment = {cname: [None] * len(all_sessions[cname]) for cname in class_names}
        occupied = {cname: set() for cname in class_names}
        course_days = {cname: {} for cname in class_names}
        faculty_occ = set()
        lab_occ = {}

        for cname, si, s in global_items:
            result = _attempt_place(s, occupied[cname], course_days[cname], faculty_occ, lab_occ,
                                     lab_occ_baseline, rng=rng)
            if result is not None:
                d, periods = result
                _commit(assignment, cname, si, s, d, periods, occupied, course_days, faculty_occ, lab_occ)

        unplaced_count = sum(1 for cn in class_names for a in assignment[cn] if a is None)
        if best_unplaced_count is None or unplaced_count < best_unplaced_count:
            best_assignment = assignment
            best_unplaced_count = unplaced_count
        if unplaced_count == 0:
            break

    return best_assignment


def _continuous_run_penalty(run, period_slot):
    """Part of the mandatory-break rule: `run` is one maximal list of
    back-to-back period indices a single faculty is teaching on one day
    (no LUNCH or free period inside it). If that run is 3+ periods long
    and is NOT one single continuous lab block, it means the faculty is
    teaching straight through without the required 1-hour break -
    penalize the excess length."""
    if len(run) <= 2:
        return 0
    slot_ids = {id(period_slot[p]) for p in run}
    first_slot = period_slot[run[0]]
    is_one_lab_block = (len(slot_ids) == 1 and first_slot["is_lab"])
    if is_one_lab_block:
        return 0
    return 800 * (len(run) - 2)


def evaluate(individual, all_sessions, class_names, lab_occ_baseline=None):
    """Lower is better. 0 == perfect timetable (and nothing left unplaced)."""
    penalty = 0
    grids = {}
    unplaced = {}
    for cname in class_names:
        sessions = all_sessions[cname]
        assignment = individual[cname]
        grid = [[None] * len(PERIODS) for _ in DAYS]
        course_day_count = {}
        missing = []
        for s, slot in zip(sessions, assignment):
            if slot is None:
                # never scheduled (kept this way rather than breaking a
                # hard rule) - heavily penalized so the GA keeps trying
                # to find an arrangement that fits everything in.
                penalty += 5000
                missing.append(s)
                continue
            d, periods = slot
            for p in periods:
                if grid[d][p] is not None:
                    penalty += 1000  # double-booked within the same class
                grid[d][p] = s
            key = (s["course_idx"], d)
            course_day_count[key] = course_day_count.get(key, 0) + 1
        for _key, count in course_day_count.items():
            if count > 1:
                # A course (e.g. a theory paper split as one 2-hour block
                # + separate 1-hour days) landing MORE THAN ONCE on the
                # SAME day is almost always wrong - it means the same
                # faculty/subject shows up twice in one day's order
                # instead of being spread across different days. Weighted
                # as heavily as the other "should basically never happen"
                # soft rules so the GA fights hard to avoid it.
                penalty += 1500 * (count - 1)
        grids[cname] = grid
        if missing:
            unplaced[cname] = missing

    # ------------------------------------------------------------------
    # Same-day rule for THEORY papers: on any one day, a class may have
    # at most ONE paper occupying a 2-hour-or-longer continuous block.
    # Two DIFFERENT theory papers both landing a 2-hour continuous block
    # on the same day is not allowed, even though each one individually
    # is a legal block.
    # ------------------------------------------------------------------
    for cname in class_names:
        grid = grids[cname]
        for d in range(len(DAYS)):
            seen_blocks = set()
            long_block_count = 0
            p = 0
            while p < len(PERIODS):
                if p == LUNCH_IDX:
                    p += 1
                    continue
                slot = grid[d][p]
                if slot is None or slot["is_lab"]:
                    p += 1
                    continue
                span = 1
                while (p + span < len(PERIODS) and p + span != LUNCH_IDX
                       and grid[d][p + span] is slot):
                    span += 1
                if span >= 2 and id(slot) not in seen_blocks:
                    seen_blocks.add(id(slot))
                    long_block_count += 1
                p += span
            if long_block_count > 1:
                penalty += 4000 * (long_block_count - 1)

    # ------------------------------------------------------------------
    # Faculty daily-workload soft rule: for EVERY faculty, on EVERY day
    # (across all classes in this shift, since one faculty can teach more
    # than one class):
    #   - a faculty never teaches THEORY continuously for more than 2
    #     hours without a break (structurally guaranteed already, since
    #     every theory session is built at most 2 periods long - see
    #     split_theory_hours), but their TOTAL theory hours that day
    #     (possibly across more than one paper) must not exceed 3,
    #   - a faculty's total LAB hours that day must not exceed 3 (one lab
    #     block, since a lab block is already at most 3 periods long),
    #   - if a faculty already has a lab that day, they may take at most
    #     ONE additional theory class that same day (any number of hours,
    #     still capped at 3 total),
    #   - at least ONE free (non-teaching, non-lunch) period that day.
    # This is enforced as a (heavily weighted) PENALTY rather than a hard
    # placement rule, so the GA is pushed toward - but never blocked from
    # finding - a timetable that satisfies it, exactly like every other
    # soft rule in this function.
    faculty_day = {}
    for cname in class_names:
        grid = grids[cname]
        for d in range(len(DAYS)):
            seen_ids_today = set()
            for p in range(len(PERIODS)):
                if p == LUNCH_IDX:
                    continue
                slot = grid[d][p]
                if slot is None or not slot["faculty"]:
                    continue
                info = faculty_day.setdefault((slot["faculty"], d),
                                               {"lab_hours": 0, "theory_hours": 0,
                                                "theory_sessions": 0, "periods": set(),
                                                "period_slot": {}})
                info["periods"].add(p)
                info["period_slot"][p] = slot
                sid = id(slot)
                if sid not in seen_ids_today:
                    seen_ids_today.add(sid)
                    if slot["is_lab"]:
                        info["lab_hours"] += slot["length"]
                    else:
                        info["theory_hours"] += slot["length"]
                        info["theory_sessions"] += 1

    TEACHING_PERIODS_PER_DAY = len(PERIODS) - 1  # everything except LUNCH
    for (_fac, _d), info in faculty_day.items():
        theory_hours = info["theory_hours"]
        lab_hours = info["lab_hours"]
        theory_sessions = info["theory_sessions"]
        periods_used = len(info["periods"])

        # On a day with NO lab, a faculty's total theory workload should
        # not exceed 2 hours. On a day WITH a lab, they may additionally
        # take at most one extra theory class, with total theory still
        # capped at 3 hours that day (the lab itself is capped separately
        # below at 3 hours).
        theory_cap = 3 if lab_hours > 0 else 2
        if theory_hours > theory_cap:
            penalty += 900 * (theory_hours - theory_cap)
        if lab_hours > 3:
            penalty += 900 * (lab_hours - 3)
        if lab_hours > 0 and theory_sessions > 1:
            penalty += 900 * (theory_sessions - 1)

        free_periods = TEACHING_PERIODS_PER_DAY - periods_used
        if free_periods < 1:
            penalty += 1000 * (1 - free_periods)

        # Mandatory-break rule: a faculty must never teach 3+ periods in
        # a row without at least a 1-hour gap, UNLESS that whole
        # back-to-back run is a single continuous LAB block (which is
        # allowed to run up to 3 periods long by design). Two hours of
        # theory must always be followed by a break before the next
        # class, never straight into a 3rd (or more) period.
        ps = sorted(info["periods"])
        run = []
        for p in ps:
            if run and p == run[-1] + 1:
                run.append(p)
            else:
                penalty += _continuous_run_penalty(run, info["period_slot"])
                run = [p]
        penalty += _continuous_run_penalty(run, info["period_slot"])

    # Faculty-double-booking safety net. With the hard rule now enforced at
    # every placement step this should never actually fire, but it is kept
    # as a defensive check in case of any future code changes.
    for d in range(len(DAYS)):
        for p in range(len(PERIODS)):
            if p == LUNCH_IDX:
                continue
            fac_count = {}
            lab_count = 0
            for cname in class_names:
                slot = grids[cname][d][p]
                if slot and slot["faculty"]:
                    fac_count[slot["faculty"]] = fac_count.get(slot["faculty"], 0) + 1
                if slot and slot["is_lab"]:
                    lab_count += 1
            for _fac, count in fac_count.items():
                if count > 1:
                    penalty += 600 * (count - 1)
            # Lab-room safety net: more than LAB_ROOMS classes in a lab at
            # the same time inside this shift - PLUS however many of those
            # same rooms another shift is already using at that same
            # (day, period) - should never happen either. This is only
            # ever reachable via crossover mixing two parents' per-class
            # assignments (the placement functions themselves already
            # enforce this as a hard rule), so it is weighted as heavily
            # as an unplaced session to make sure the GA always prefers
            # ANY individual that respects the single shared lab's real
            # capacity over one that doesn't.
            combined_lab_count = lab_count + (lab_occ_baseline.get((d, p), 0) if lab_occ_baseline else 0)
            if combined_lab_count > LAB_ROOMS:
                penalty += 5000 * (combined_lab_count - LAB_ROOMS)
    return penalty, grids, unplaced


def tournament(scored, k=4, rng=None):
    sample = (rng or random).sample(scored, min(k, len(scored)))
    sample.sort(key=lambda x: x[0])
    return sample[0][1]


def crossover(p1, p2, class_names, rng=None):
    child = {}
    for cname in class_names:
        child[cname] = copy.deepcopy(p1[cname] if (rng or random).random() < 0.5 else p2[cname])
    return child


def mutate(ind, all_sessions, class_names, rate=0.2, lab_occ_baseline=None, rng=None):
    r = rng or random
    order = list(class_names)
    r.shuffle(order)
    for cname in order:
        if r.random() >= rate:
            continue
        sessions = all_sessions[cname]
        assignment = ind[cname]
        if not sessions:
            continue
        k = r.randint(1, max(1, len(sessions) // 3))
        idxs = list(r.sample(range(len(sessions)), min(k, len(sessions))))
        # KEY FIX: re-place the longest (hardest-to-fit, e.g. lab blocks)
        # sessions first, so they get first pick of the freed-up slots.
        idxs.sort(key=lambda i: -sessions[i]["length"])
        idxs_set = set(idxs)

        # global faculty occupancy + lab-room occupancy from every class
        # IN THIS SHIFT, EXCLUDING the sessions we are about to re-place,
        # so we can legally re-place them without clashing with any other
        # class's faculty or over-filling the 2 shared lab rooms.
        faculty_occ = set()
        lab_occ = {}
        for cn in class_names:
            secs = all_sessions[cn]
            asg = ind[cn]
            for i, s in enumerate(secs):
                if cn == cname and i in idxs_set:
                    continue
                slot = asg[i]
                if slot is None:
                    continue
                d, periods = slot
                if s["faculty"]:
                    for p in periods:
                        faculty_occ.add((s["faculty"], d, p))
                if s["is_lab"]:
                    for p in periods:
                        lab_occ[(d, p)] = lab_occ.get((d, p), 0) + 1

        occupied = set()
        course_days = {}
        for i, s in enumerate(sessions):
            if i in idxs_set:
                continue
            slot = assignment[i]
            if slot is None:
                continue
            d, periods = slot
            for p in periods:
                occupied.add((d, p))
            course_days.setdefault(s["course_idx"], set()).add(d)

        for i in idxs:
            s = sessions[i]
            result = _attempt_place(s, occupied, course_days, faculty_occ, lab_occ, lab_occ_baseline, rng=r)
            if result is not None:
                d, periods = result
                for p in periods:
                    occupied.add((d, p))
                course_days.setdefault(s["course_idx"], set()).add(d)
                if s["faculty"]:
                    for p in periods:
                        faculty_occ.add((s["faculty"], d, p))
                if s["is_lab"]:
                    for p in periods:
                        lab_occ[(d, p)] = lab_occ.get((d, p), 0) + 1
                assignment[i] = (d, periods)
            else:
                # No further relaxation - leave unplaced rather than break
                # a hard rule (faculty double-booking, lab-room overflow,
                # or Language/English twice in a day).
                assignment[i] = None

        ind[cname] = assignment


def run_ga(all_sessions, class_names, generations=250, pop_size=60, progress_cb=None, lab_occ_baseline=None, rng=None):
    """Runs the GA for ONE shift (`class_names` = that shift's classes)
    and returns (best_individual, best_grids, best_score, best_unplaced).
    `lab_occ_baseline` (optional): a {(day, period): count} dict of how
    many of the LAB_ROOMS physical lab rooms are already committed to a
    DIFFERENT shift at that (day, period) - so this shift's own labs
    never push the COMBINED total (this shift + the other shift) past
    LAB_ROOMS at the same real (day, period).
    `rng` (optional): a `random.Random(seed)` instance to draw all
    randomness from. ALWAYS pass this explicitly from a caller that has
    seeded it - see the big comment above `_run_shift_generation` for
    why: falling back to the global `random` module is only a safety
    net for direct/manual calls, never for the web app's own code
    paths, since the global module is shared (and therefore unsafe)
    across concurrent requests."""
    r = rng or random
    population = [random_init_individual(all_sessions, class_names, lab_occ_baseline=lab_occ_baseline, rng=r)
                  for _ in range(pop_size)]

    best_ind, best_grids, best_score, best_unplaced = None, None, None, {}
    for gen in range(generations):
        scored = []
        for ind in population:
            score, grids, unplaced = evaluate(ind, all_sessions, class_names, lab_occ_baseline)
            scored.append((score, ind, grids, unplaced))
        scored.sort(key=lambda x: x[0])

        if best_score is None or scored[0][0] < best_score:
            best_score = scored[0][0]
            best_ind = copy.deepcopy(scored[0][1])
            best_grids = scored[0][2]
            best_unplaced = scored[0][3]

        if progress_cb and gen % 10 == 0:
            progress_cb(gen, generations, best_score)

        if best_score == 0:
            break

        elite_n = max(2, pop_size // 4)
        elite = [copy.deepcopy(s[1]) for s in scored[:elite_n]]
        new_pop = elite
        pool = [(s[0], s[1]) for s in scored]
        while len(new_pop) < pop_size:
            p1 = tournament(pool, rng=r)
            p2 = tournament(pool, rng=r)
            child = crossover(p1, p2, class_names, rng=r)
            mutate(child, all_sessions, class_names, lab_occ_baseline=lab_occ_baseline, rng=r)
            new_pop.append(child)
        population = new_pop

    return best_ind, best_grids, best_score, best_unplaced


def _fallback_lab_split(length):
    """Emergency fallback for a lab block that could not be placed as ONE
    continuous block, even after several fresh GA restarts. Instead of
    leaving that class's lab missing from the timetable, break it into
    smaller pieces (each still lands on its own different day, exactly
    like any other multi-block lab):
        length 3 -> [2, 1]
        length 2 -> [1, 1]
    Any other length has nothing smaller to fall back to and is returned
    unchanged."""
    if length == 3:
        return [2, 1]
    if length == 2:
        return [1, 1]
    return [length]


def _apply_fallback_split(all_sessions, class_keys, unplaced):
    """Rebuilds `all_sessions` IN PLACE: every session object referenced
    in `unplaced` (i.e. one the GA genuinely could not find any legal
    slot for, even after several fresh restarts) that is a lab block of
    length 2 or 3 gets replaced by its smaller _fallback_lab_split()
    pieces, each becoming its own separate session competing for its own
    day. This only ever touches the specific sessions that failed -
    every other session keeps its normal, preferred continuous block.

    This is what makes Shift 2's "try a continuous block like Shift 1
    first, only split it across days if it truly doesn't fit" rule work,
    and also doubles as the safety net that guarantees no class's lab
    silently ends up missing from the timetable.

    Returns True if anything was changed (worth another GA run), else
    False."""
    changed = False
    for key in class_keys:
        missing = unplaced.get(key) or []
        for s in missing:
            if not s.get("is_lab") or s["length"] not in (2, 3):
                continue
            sessions = all_sessions[key]
            try:
                idx = next(i for i, x in enumerate(sessions) if x is s)
            except StopIteration:
                continue
            pieces = _fallback_lab_split(s["length"])
            if pieces == [s["length"]]:
                continue
            new_sessions = [
                {"course_idx": s["course_idx"], "name": s["name"], "faculty": s["faculty"],
                 "is_lab": True, "length": L}
                for L in pieces
            ]
            sessions[idx:idx + 1] = new_sessions
            changed = True
    return changed


# ============================================================
# WEB-FACING HELPERS (new — not in the original Tkinter app)
# These build on the pure engine functions above to turn
# "shift + department + term" into a ready-to-render timetable,
# without needing the Tkinter CourseTable UI to hand-pick courses.
# ============================================================

def default_course_list_for(shift, dept, cname, term):
    """Course list ({name, faculty, hours, is_lab}) for one class, taken
    from courses.csv presets. Falls back to DEFAULT_COURSES (no faculty
    assigned) if courses.csv has nothing for this shift/dept/class/term,
    so the app still produces a demo timetable on first run."""
    year_key = CLASS_TO_YEARKEY.get(cname, cname)
    sem_map = SEM_ODD if term == "ODD" else SEM_EVEN
    sem = sem_map.get(year_key)

    names = COURSE_PRESETS.get(shift, {}).get(dept, {}).get(year_key, {}).get(sem, [])
    hours_map = COURSE_HOURS.get(shift, {}).get(dept, {}).get(year_key, {}).get(sem, {})
    faculty_map = COURSE_FACULTY.get(shift, {}).get(dept, {}).get(year_key, {}).get(sem, {})

    if not names:
        names = DEFAULT_COURSES
        hours_map, faculty_map = {}, {}

    return [
        {
            "name": name,
            "faculty": faculty_map.get(name, ""),
            "hours": hours_map.get(name, default_hours_for(name)),
            "is_lab": "lab" in name.lower(),
        }
        for name in names
    ]


def _build_shift_sessions(shift, dept, term):
    """Shared course/session-building step for one shift (no GA run
    yet). Returns (class_names, class_keys, all_courses, all_sessions,
    course_colors, lab_colors, seed) - factored out of
    _run_shift_generation so the Shift-1-lab-occupancy pre-pass (see
    _shift1_lab_occupancy below) can reuse exactly the same course/
    session-building logic without duplicating it."""
    class_names = SHIFT_CLASS_LIST[shift]
    class_keys = [ckey(shift, c) for c in class_names]

    all_courses = {ckey(shift, c): default_course_list_for(shift, dept, c, term) for c in class_names}

    used_faculty = set()
    for courses in all_courses.values():
        for c in courses:
            if c["faculty"]:
                used_faculty.add(c["faculty"])
    ordered = [f for f in FACULTIES if f in used_faculty] + [f for f in used_faculty if f not in FACULTIES]
    course_colors = generate_faculty_shades(ordered, hue_shift=0.0, light=0.86, sat=0.45)
    lab_colors = generate_faculty_shades(ordered, hue_shift=0.5, light=0.80, sat=0.55)

    all_sessions = {k: build_sessions(all_courses[k], shift=shift) for k in class_keys}

    parts = []
    for cname in class_names:
        for c in all_courses[ckey(shift, cname)]:
            parts.append(f"{cname}|{c['name']}|{c['faculty']}|{c['hours']}|{c['is_lab']}")
    signature = "\n".join(sorted(parts))
    seed = int(hashlib.md5(signature.encode("utf-8")).hexdigest(), 16) % (2 ** 32)

    return class_names, class_keys, all_courses, all_sessions, course_colors, lab_colors, seed


# Only 1 physical lab exists (shared by whichever classes are running),
# and Shift 1 and Shift 2 classes run at the SAME real clock times (two
# parallel batches), not one after another - so the (day, period) grid
# positions line up 1-to-1 between the two shifts. Shift 2's lab
# sessions must therefore be generated AFTER Shift 1's, so Shift 2 can
# see exactly which (day, period) slots of the shared lab Shift 1 has
# already used, and never push the COMBINED usage past LAB_ROOMS at the
# same (day, period). This cache avoids re-running Shift 1's GA every
# single time a Shift-2 view is requested for the same department/term
# (the GA is seeded deterministically from the course data, so re-runs
# for the same input always land on the same schedule anyway).
_SHIFT1_LAB_CACHE = {}


def _shift1_lab_occupancy(dept, term, generations, pop_size):
    """Runs (or reuses a cached run of) Shift 1's GA for this department
    + term and returns a {(day, period): count} dict of how many of the
    LAB_ROOMS shared lab slots Shift 1 is using at each (day, period) -
    this becomes the lab_occ_baseline passed into Shift 2's GA run."""
    cache_key = (dept, term, generations, pop_size)
    cached = _SHIFT1_LAB_CACHE.get(cache_key)
    if cached is not None:
        return cached

    class_names, class_keys, all_courses, all_sessions, _cc, _lc, seed = (
        _build_shift_sessions("Shift 1", dept, term))
    rng = random.Random(seed)
    best_ind, best_grids, best_score, best_unplaced = run_ga(
        all_sessions, class_keys, generations=generations, pop_size=pop_size, rng=rng)

    lab_occ = {}
    for cname in class_names:
        grid = best_grids.get(ckey("Shift 1", cname))
        if grid is None:
            continue
        for d in range(len(DAYS)):
            for p in range(len(PERIODS)):
                slot = grid[d][p]
                if slot is not None and slot["is_lab"]:
                    lab_occ[(d, p)] = lab_occ.get((d, p), 0) + 1

    _SHIFT1_LAB_CACHE[cache_key] = lab_occ
    return lab_occ


def _run_shift_generation(shift, dept, term, generations=150, pop_size=50, shared_lab=False):
    """Shared pipeline: build courses -> build sessions -> GA -> grids.
    Used by the timetable / faculty / exam views below so all three stay
    consistent with each other (same seed -> same generated schedule).

    `shared_lab` (default False): Shift 1 and Shift 2 normally each have
    their own lab room and are generated fully independently - this
    matches the department having 2 separate physical labs, one used by
    each shift. Pass `shared_lab=True` ONLY for a department where both
    shifts genuinely share the SAME single lab at the same real clock
    times - in that case Shift 1 is generated first and Shift 2 is
    generated around Shift 1's lab usage (see _shift1_lab_occupancy) so
    the combined usage of the one shared lab never exceeds LAB_ROOMS at
    the same (day, period).

    Returns (class_names, all_courses, best_grids, best_score, best_unplaced,
    course_colors, lab_colors)."""
    class_names, class_keys, all_courses, all_sessions, course_colors, lab_colors, seed = (
        _build_shift_sessions(shift, dept, term))

    lab_occ_baseline = None
    if shared_lab and shift == "Shift 2":
        lab_occ_baseline = _shift1_lab_occupancy(dept, term, generations, pop_size)

    # A dedicated random.Random(seed) instance, NOT the global `random`
    # module. The global module's state is shared across every thread
    # the web server is running (Flask/waitress serve concurrent
    # requests on a thread pool), so two GA runs happening at the same
    # moment - e.g. the Master/"All" view and the Lab view, which the
    # front-end deliberately fires off together - would otherwise both
    # be pulling from and corrupting the SAME global random sequence.
    # That silently broke the "same seed -> same generated schedule"
    # guarantee this function's docstring promises: two views built
    # from identical course/faculty data could land on two DIFFERENT
    # schedules purely because of how their requests happened to
    # interleave in time. A local `rng` object is only ever touched by
    # the one request that created it, so it stays reproducible no
    # matter what else the server is doing at the same time.
    rng = random.Random(seed)
    best_ind, best_grids, best_score, best_unplaced = run_ga(
        all_sessions, class_keys, generations=generations, pop_size=pop_size,
        lab_occ_baseline=lab_occ_baseline, rng=rng)

    retry = 0
    while best_unplaced and retry < 2:
        retry += 1
        ind2, grids2, score2, unplaced2 = run_ga(
            all_sessions, class_keys, generations=generations, pop_size=pop_size,
            lab_occ_baseline=lab_occ_baseline, rng=rng)
        if score2 < best_score:
            best_ind, best_grids, best_score, best_unplaced = ind2, grids2, score2, unplaced2

    # Last resort for a lab block that still could not find a legal
    # continuous slot even after the retries above (e.g. a shared lab
    # is too full at that point in the week): break that specific
    # lab's block into smaller pieces (3hrs -> 2+1, 2hrs -> 1+1, each
    # still landing on its own separate day) rather than leaving the
    # class without that lab session at all, then run the GA again.
    # When `shared_lab` is on, the shared lab is a genuinely tight
    # resource, so this is repeated - splitting down further each round
    # (3 -> 2+1 -> 1+1+1) - until every lab block that CAN fit somewhere
    # does, squeezing the maximum possible fill out of the one shared
    # lab instead of stopping after a single split pass.
    split_rounds = 3 if shared_lab else 1
    for _ in range(split_rounds):
        if not best_unplaced:
            break
        changed = _apply_fallback_split(all_sessions, class_keys, best_unplaced)
        if not changed:
            break
        ind3, grids3, score3, unplaced3 = run_ga(
            all_sessions, class_keys, generations=generations, pop_size=pop_size,
            lab_occ_baseline=lab_occ_baseline, rng=rng)
        if score3 < best_score:
            best_ind, best_grids, best_score, best_unplaced = ind3, grids3, score3, unplaced3

    return class_names, all_courses, best_grids, best_score, best_unplaced, course_colors, lab_colors


def list_faculty_for_shift(shift, dept, term):
    """Faculty names actually used by this shift/department/term's
    courses -- for populating the Faculty Timetable dropdown."""
    class_names = SHIFT_CLASS_LIST[shift]
    fac = set()
    for cname in class_names:
        for c in default_course_list_for(shift, dept, cname, term):
            f = (c["faculty"] or "").strip()
            if f and not f.isdigit():
                fac.add(f)
    return sorted(fac)


def list_faculty_for_class_overview(shift, dept, cname):
    """Faculty names teaching ONE class (any term, Odd or Even) --
    used by the Home > Overview > Faculty screen, which only asks for
    Shift + Class (no term / no GA run needed)."""
    fac = set()
    for term in ("ODD", "EVEN"):
        for c in default_course_list_for(shift, dept, cname, term):
            f = (c["faculty"] or "").strip()
            if f and not f.isdigit():
                fac.add(f)
    return sorted(fac)


def get_semester_date_range(term):
    """Returns {"start": "DD-MM-YYYY", "end": "DD-MM-YYYY"} for the
    given term ("ODD"/"EVEN") -- used by Home > Overview > Dates >
    College Dates."""
    if term == "ODD":
        start, end = ODD_SEM_START, ODD_SEM_END
    else:
        start, end = EVEN_SEM_START, EVEN_SEM_END
    return {
        "start": start.strftime("%d-%m-%Y") if start else "",
        "end": end.strftime("%d-%m-%Y") if end else "",
    }


def get_exam_dates_overview(exam_type, term):
    """Returns [{day_order, date, day}, ...] for the given exam type
    ("Internal 1" / "Internal 2" / "Model") and term ("ODD"/"EVEN"),
    sorted by Day Order (I..VI) -- used by Home > Overview > Dates."""
    rows = EXAM_DATES.get((exam_type, term), [])
    order_index = {d: i for i, d in enumerate(DAYS)}
    return sorted(rows, key=lambda r: order_index.get(r["day_order"], 99))


def generate_shift_timetable(shift, dept, term, generations=150, pop_size=50, shared_lab=False):
    """Runs the full pipeline for ONE shift and returns a JSON-safe dict
    (one table per class, theory + lab combined, matching the desktop
    app's per-class grid). This is the single-shift, no-cross-shift-
    baseline version -- good enough for the web MVP (one view). The
    desktop app's `_generate()` chains both shifts together with a
    shared lab-room counter; that can be added here later the same way
    if Shift 2 needs to be generated together with Shift 1."""
    class_names, all_courses, best_grids, best_score, best_unplaced, course_colors, lab_colors = (
        _run_shift_generation(shift, dept, term, generations, pop_size, shared_lab))

    def cell_color(slot):
        if slot["is_lab"]:
            return lab_colors.get(slot["faculty"], LAB_CLR) if slot["faculty"] else LAB_CLR
        return course_colors.get(slot["faculty"], THEORY_CLR) if slot["faculty"] else THEORY_CLR

    grids_json = {}
    for cname in class_names:
        grid = best_grids[ckey(shift, cname)]
        day_rows = []
        for d_i, day in enumerate(DAYS):
            row = []
            p_i = 0
            while p_i < len(PERIODS):
                if p_i == LUNCH_IDX:
                    row.append({"lunch": True, "colspan": 1})
                    p_i += 1
                    continue
                slot = grid[d_i][p_i]
                if slot is None:
                    row.append({"empty": True, "colspan": 1})
                    p_i += 1
                    continue
                span = 1
                while (p_i + span < len(PERIODS) and p_i + span != LUNCH_IDX
                       and grid[d_i][p_i + span] is slot):
                    span += 1
                row.append({
                    "name": slot["name"],
                    "faculty": slot["faculty"] or "",
                    "is_lab": slot["is_lab"],
                    "color": cell_color(slot),
                    "colspan": span,
                })
                p_i += span
            day_rows.append({"day": day, "cells": row})
        grids_json[cname] = day_rows

    unplaced_json = []
    for k, missing in (best_unplaced or {}).items():
        for s in missing:
            unplaced_json.append({"class": key_class(k), "course": s["name"], "faculty": s["faculty"] or ""})

    return {
        "shift": shift,
        "department": dept,
        "term": term,
        "days": DAYS,
        "periods": PERIODS,
        "lunch_index": LUNCH_IDX,
        "classes": class_names,
        "class_abbr": CLASS_ABBR,
        "grids": grids_json,
        "score": best_score,
        "unplaced": unplaced_json,
    }


def generate_faculty_timetable(shift, dept, term, faculty, generations=150, pop_size=50, shared_lab=False):
    """One combined table for ONE faculty across every class in this
    shift: for every day/period, which class they're teaching (or FREE).
    Mirrors the desktop app's _render_faculty_single."""
    class_names, all_courses, best_grids, best_score, best_unplaced, course_colors, lab_colors = (
        _run_shift_generation(shift, dept, term, generations, pop_size, shared_lab))

    combined = [[None] * len(PERIODS) for _ in DAYS]
    for cname in class_names:
        grid = best_grids.get(ckey(shift, cname))
        if grid is None:
            continue
        for d in range(len(DAYS)):
            for p in range(len(PERIODS)):
                slot = grid[d][p]
                if slot is not None and slot.get("faculty") == faculty:
                    combined[d][p] = (cname, slot)

    day_rows = []
    for d_i, day in enumerate(DAYS):
        row = []
        p_i = 0
        while p_i < len(PERIODS):
            if p_i == LUNCH_IDX:
                row.append({"lunch": True, "colspan": 1})
                p_i += 1
                continue
            cell = combined[d_i][p_i]
            if cell is None:
                row.append({"free": True, "colspan": 1})
                p_i += 1
                continue
            cname, slot = cell
            span = 1
            while (p_i + span < len(PERIODS) and p_i + span != LUNCH_IDX
                   and combined[d_i][p_i + span] is not None
                   and combined[d_i][p_i + span][1] is slot
                   and combined[d_i][p_i + span][0] == cname):
                span += 1
            if slot["is_lab"]:
                color = FACULTY_LAB_DARK_CLR
                text_color = "#ffffff"
            else:
                color = CLASS_COLORS.get(cname, THEORY_CLR)
                text_color = "#1a1a1a"
            row.append({
                "name": slot["name"],
                "class_abbr": CLASS_ABBR.get(cname, cname),
                "is_lab": slot["is_lab"],
                "color": color,
                "text_color": text_color,
                "colspan": span,
            })
            p_i += span
        day_rows.append({"day": day, "cells": row})

    return {
        "shift": shift,
        "department": dept,
        "term": term,
        "faculty": faculty,
        "days": DAYS,
        "periods": PERIODS,
        "lunch_index": LUNCH_IDX,
        "grid": day_rows,
        "free_color": FREE_CLR,
    }


def _compute_exam_day_map(grid):
    """For each course, find EVERY day-order it appears on in the real
    timetable, along with the block length (span) and starting period
    index that day. This lets the exam scheduler try every day the
    course genuinely has a continuous 2-hour block, in order, before
    ever falling back to a single-hour occurrence -- and always use
    the REAL hour(s) for whichever day actually gets picked, instead
    of copying a label from a different day.
    Returns {course_name: {day_label: (span, start_period_index)}},
    keeping the longest span seen for a given (course, day) pair."""
    by_course = {}
    for d_i, day in enumerate(DAYS):
        p_i = 0
        while p_i < len(PERIODS):
            if p_i == LUNCH_IDX:
                p_i += 1
                continue
            slot = grid[d_i][p_i]
            if slot is None:
                p_i += 1
                continue
            span = 1
            while (p_i + span < len(PERIODS) and p_i + span != LUNCH_IDX
                   and grid[d_i][p_i + span] is slot):
                span += 1
            name = slot["name"]
            day_map = by_course.setdefault(name, {})
            cur = day_map.get(day)
            if cur is None or span > cur[0]:
                day_map[day] = (span, p_i)
            p_i += span
    return by_course


# Non-lunch period indices, in order -- these are what get numbered
# "Hour I", "Hour II", ... for exam purposes (the lunch slot is skipped).
_EXAM_HOUR_PERIODS = [i for i in range(len(PERIODS)) if i != LUNCH_IDX]
_EXAM_HOUR_ROMANS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]


def _exam_hour_label(start_p_i, span):
    """Given the starting period index (in the regular class grid) and
    how many periods the block spans, return the real exam-hour label,
    e.g. "II" for a single hour or "II & III" for a continuous 2-hour
    block -- based on where that course actually falls in the day,
    not just a plain count from Hour I."""
    if start_p_i is None:
        return ""
    labels = []
    p_i = start_p_i
    covered = 0
    while covered < span and p_i < len(PERIODS):
        if p_i != LUNCH_IDX:
            if p_i in _EXAM_HOUR_PERIODS:
                pos = _EXAM_HOUR_PERIODS.index(p_i)
                labels.append(_EXAM_HOUR_ROMANS[pos] if pos < len(_EXAM_HOUR_ROMANS) else str(pos + 1))
            covered += 1
        p_i += 1
    return " & ".join(labels)


def generate_exam_timetable(shift, dept, term, exam_type, generations=150, pop_size=50, shared_lab=False):
    """Cross-class exam schedule for ONE shift + ONE exam type (Internal
    1 / Internal 2 / Model) + term. Mirrors the desktop app's
    _build_exam_schedule + _render_exam_table. Needs exam_dates.csv to
    have rows for (exam_type, term) -- if it doesn't, returns an empty
    date_rows list and the frontend shows a "no dates" message, same as
    the desktop app."""
    class_names, all_courses, best_grids, best_score, best_unplaced, course_colors, lab_colors = (
        _run_shift_generation(shift, dept, term, generations, pop_size, shared_lab))

    date_rows = EXAM_DATES.get((exam_type, term), [])
    result = {
        "shift": shift,
        "department": dept,
        "term": term,
        "exam_type": exam_type,
        "classes": class_names,
        "class_abbr": CLASS_ABBR,
        "date_rows": date_rows,
        "rows": [],
    }
    if not date_rows:
        return result

    all_rows = list(range(len(date_rows)))
    rows_by_day_order = {}
    for idx, row in enumerate(date_rows):
        rows_by_day_order.setdefault(row["day_order"], []).append(idx)

    items = []
    for cname in class_names:
        grid = best_grids.get(ckey(shift, cname))
        if grid is None:
            continue
        courses = all_courses[ckey(shift, cname)]
        exam_map = _compute_exam_day_map(grid)
        for c in courses:
            if is_exam_excluded(c["name"], c.get("is_lab"), c.get("hours")):
                continue
            day_map = exam_map.get(c["name"], {})
            # Every day this course actually meets, ordered so that
            # days with a genuine continuous 2-hour (or longer) block
            # come first -- these are tried first as the exam day. Only
            # if ALL of those days are already taken (by another paper
            # of the same class) do we fall back to a day where the
            # course only has a single-hour occurrence, using that
            # day's own real hour, never a borrowed one.
            day_candidates = sorted(day_map.items(), key=lambda kv: -kv[1][0])
            has_block = bool(day_candidates) and day_candidates[0][1][0] >= 2
            items.append({"class": cname, "course": c["name"], "faculty": c["faculty"],
                           "day_candidates": day_candidates, "has_block": has_block})

    fac_load = {}
    for it in items:
        fac_load[it["faculty"]] = fac_load.get(it["faculty"], 0) + 1
    items.sort(key=lambda it: (not it["has_block"],
                                -fac_load.get(it["faculty"], 0), it["class"], it["course"]))

    # RULE: a class can have AT MOST ONE exam on any given day, no
    # matter which hour it falls at in the real timetable -- so
    # class_rows_used is a simple set of "this row/day is already
    # taken for this class", not a per-hour range. Faculty, on the
    # other hand, genuinely can invigilate/teach different classes at
    # different hours the same day, so faculty availability still uses
    # the exact occupied PERIOD RANGE per (row, faculty). A block with
    # no known start position is treated as occupying the whole day
    # for that faculty (safe fallback for the rare item with no info).
    class_rows_used = {c: set() for c in class_names}
    faculty_rows_used = {}
    cell_map = {}
    class_row_load = {c: {} for c in class_names}  # row -> count, for least-loaded fallback

    def _fac_overlaps(rng, existing):
        if not existing:
            return False
        if rng is None:
            return True
        s, e = rng
        for (os_, oe_) in existing:
            if os_ is None or oe_ is None:
                return True
            if s < oe_ and os_ < e:
                return True
        return False

    for it in items:
        cname, course, fac = it["class"], it["course"], it["faculty"]
        day_candidates = it["day_candidates"]  # [(day_label, (span, start_p_i)), ...] best-first

        chosen = None
        chosen_span = 1
        chosen_start = None

        # Pass 1: try every day the course genuinely meets, best block
        # (longest continuous span) first. A day is only skipped if the
        # class already has an exam there that day, or the faculty is
        # already busy at the overlapping hours that day.
        for day_label, (span, start_p_i) in day_candidates:
            rng = (start_p_i, start_p_i + span)
            for r in rows_by_day_order.get(day_label, []):
                if r in class_rows_used[cname]:
                    continue
                if fac and _fac_overlaps(rng, faculty_rows_used.get(fac, {}).get(r, [])):
                    continue
                chosen, chosen_span, chosen_start = r, span, start_p_i
                break
            if chosen is not None:
                break

        # Pass 2: every day the course meets is already booked for this
        # class (rare) -- fall back to any other free day-order. No
        # real hour is known for that day, so leave the label blank
        # rather than showing a borrowed/incorrect hour.
        if chosen is None:
            for r in all_rows:
                if r in class_rows_used[cname]:
                    continue
                if fac and _fac_overlaps(None, faculty_rows_used.get(fac, {}).get(r, [])):
                    continue
                chosen, chosen_span, chosen_start = r, 1, None
                break

        if chosen is None:
            # Truly every day-order is already used for this class
            # (more theory papers than available exam dates). Last
            # resort: least-loaded day, even if it means a second exam
            # that day.
            chosen = min(all_rows, key=lambda r: class_row_load[cname].get(r, 0))
            chosen_span, chosen_start = 1, None

        hour_label = _exam_hour_label(chosen_start, chosen_span)
        rng = None if chosen_start is None else (chosen_start, chosen_start + chosen_span)

        class_rows_used[cname].add(chosen)
        class_row_load[cname][chosen] = class_row_load[cname].get(chosen, 0) + 1
        if fac:
            faculty_rows_used.setdefault(fac, {}).setdefault(chosen, []).append(rng)
        cell_map.setdefault((chosen, cname), []).append((course, fac, hour_label))

    rows_json = []
    for r_i, row in enumerate(date_rows):
        row_cells = {}
        for cname in class_names:
            entries = cell_map.get((r_i, cname), [])
            row_cells[cname] = [
                {"course": course, "faculty": fac or "", "hour_label": hour_label}
                for course, fac, hour_label in entries
            ]
        rows_json.append({"date": row["date"], "day": row.get("day", ""), "day_order": row.get("day_order", ""), "cells": row_cells})

    result["rows"] = rows_json
    return result


def list_classes_for_shift(shift):
    """Classes in this shift, for the Student Timetable dropdown."""
    return SHIFT_CLASS_LIST.get(shift, [])


def _grid_cells_json(grid, cell_color_fn, lab_only=False):
    """One day-row list ({"day","cells":[...]}) from a single class's
    grid -- shared by the Student Timetable and (per-class-row) by the
    All / Lab Timetable master tables below."""
    any_found = False
    day_rows = []
    for d_i, day in enumerate(DAYS):
        row = []
        p_i = 0
        while p_i < len(PERIODS):
            if p_i == LUNCH_IDX:
                row.append({"lunch": True, "colspan": 1})
                p_i += 1
                continue
            slot = grid[d_i][p_i]
            if slot is None or (lab_only and not slot["is_lab"]):
                row.append({"empty": True, "colspan": 1})
                p_i += 1
                continue
            span = 1
            while (p_i + span < len(PERIODS) and p_i + span != LUNCH_IDX
                   and grid[d_i][p_i + span] is slot):
                span += 1
            any_found = True
            row.append({
                "name": slot["name"],
                "faculty": slot["faculty"] or "",
                "is_lab": slot["is_lab"],
                "color": cell_color_fn(slot),
                "colspan": span,
            })
            p_i += span
        day_rows.append({"day": day, "cells": row})
    return day_rows, any_found


def generate_student_timetable(shift, dept, term, class_name, generations=150, pop_size=50, shared_lab=False):
    """ONE selected class's timetable -- mirrors _render_class_table /
    the desktop app's "Student Timetable" mode."""
    class_names, all_courses, best_grids, best_score, best_unplaced, course_colors, lab_colors = (
        _run_shift_generation(shift, dept, term, generations, pop_size, shared_lab))

    def cell_color(slot):
        if slot["is_lab"]:
            return lab_colors.get(slot["faculty"], LAB_CLR) if slot["faculty"] else LAB_CLR
        return course_colors.get(slot["faculty"], THEORY_CLR) if slot["faculty"] else THEORY_CLR

    grid = best_grids.get(ckey(shift, class_name))
    if grid is None:
        return {"shift": shift, "department": dept, "term": term, "class": class_name,
                "days": DAYS, "periods": PERIODS, "lunch_index": LUNCH_IDX, "rows": [], "found": False}

    rows, _ = _grid_cells_json(grid, cell_color)
    return {
        "shift": shift, "department": dept, "term": term, "class": class_name,
        "days": DAYS, "periods": PERIODS, "lunch_index": LUNCH_IDX,
        "rows": rows, "found": True,
    }


def _master_table_json(shift, dept, term, best_grids, class_names, cell_color, lab_only=False):
    """Shared builder for the "All Timetable" and "Lab Timetable" master
    tables: one block of class-rows per day, day label spans the block
    -- mirrors _render_all_combined / _render_lab_combined."""
    any_found = False
    days_json = []
    for d_i, day in enumerate(DAYS):
        class_rows = []
        for cname in class_names:
            grid = best_grids.get(ckey(shift, cname))
            if grid is None:
                continue
            cells = []
            p_i = 0
            while p_i < len(PERIODS):
                if p_i == LUNCH_IDX:
                    cells.append({"lunch": True, "colspan": 1})
                    p_i += 1
                    continue
                slot = grid[d_i][p_i]
                if slot is None or (lab_only and not slot["is_lab"]):
                    cells.append({"empty": True, "colspan": 1})
                    p_i += 1
                    continue
                span = 1
                while (p_i + span < len(PERIODS) and p_i + span != LUNCH_IDX
                       and grid[d_i][p_i + span] is slot):
                    span += 1
                any_found = True
                cells.append({
                    "name": slot["name"],
                    "faculty": slot["faculty"] or "",
                    "is_lab": slot["is_lab"],
                    "color": cell_color(slot),
                    "colspan": span,
                })
                p_i += span
            class_rows.append({"class": cname, "class_abbr": CLASS_ABBR.get(cname, cname), "cells": cells})
        days_json.append({"day": day, "class_rows": class_rows})
    return days_json, any_found


def generate_all_timetable(shift, dept, term, generations=150, pop_size=50, shared_lab=False):
    """Master combined table -- every class in the shift, grouped by
    day, matching the college's printed master timetable. Mirrors the
    desktop app's "All Timetable" mode / _render_all_combined."""
    class_names, all_courses, best_grids, best_score, best_unplaced, course_colors, lab_colors = (
        _run_shift_generation(shift, dept, term, generations, pop_size, shared_lab))

    def cell_color(slot):
        if slot["is_lab"]:
            return lab_colors.get(slot["faculty"], LAB_CLR) if slot["faculty"] else LAB_CLR
        return course_colors.get(slot["faculty"], THEORY_CLR) if slot["faculty"] else THEORY_CLR

    days_json, _ = _master_table_json(shift, dept, term, best_grids, class_names, cell_color)

    unplaced_json = []
    for k, missing in (best_unplaced or {}).items():
        for s in missing:
            unplaced_json.append({"class": key_class(k), "course": s["name"], "faculty": s["faculty"] or ""})

    return {
        "shift": shift, "department": dept, "term": term,
        "days": DAYS, "periods": PERIODS, "lunch_index": LUNCH_IDX,
        "days_json": days_json, "score": best_score, "unplaced": unplaced_json,
    }


def generate_lab_timetable(shift, dept, term, generations=150, pop_size=50, shared_lab=False):
    """Same master layout as generate_all_timetable, but every non-lab
    cell is blanked so only Lab Hours remain. Mirrors _render_lab_combined."""
    class_names, all_courses, best_grids, best_score, best_unplaced, course_colors, lab_colors = (
        _run_shift_generation(shift, dept, term, generations, pop_size, shared_lab))

    def cell_color(slot):
        return lab_colors.get(slot["faculty"], LAB_CLR) if slot["faculty"] else LAB_CLR

    days_json, any_found = _master_table_json(shift, dept, term, best_grids, class_names, cell_color, lab_only=True)

    return {
        "shift": shift, "department": dept, "term": term,
        "days": DAYS, "periods": PERIODS, "lunch_index": LUNCH_IDX,
        "days_json": days_json, "any_found": any_found,
    }


def generate_lab_timetable_combined(dept, term, generations=150, pop_size=50, shared_lab=False):
    """Shift 1's Lab Timetable and Shift 2's Lab Timetable, generated and
    returned TOGETHER as one bundle so the app can print/view both
    shifts' lab schedules side by side (the LAB_COMBINED_LABEL option in
    the Lab Timetable dropdown). Each shift's own lab schedule is
    unaffected by this - `shared_lab` only controls whether Shift 2's
    generation itself accounts for Shift 1's lab usage (see
    _run_shift_generation); the combining done here is purely for
    display/printing."""
    shift1 = generate_lab_timetable("Shift 1", dept, term, generations, pop_size, shared_lab)
    shift2 = generate_lab_timetable("Shift 2", dept, term, generations, pop_size, shared_lab)
    return {
        "department": dept, "term": term, "shared_lab": shared_lab,
        "days": DAYS, "periods": PERIODS, "lunch_index": LUNCH_IDX,
        "shift1": shift1, "shift2": shift2,
        "any_found": bool(shift1["any_found"] or shift2["any_found"]),
    }
