# Automatic Timetable Generator — Web Edition (skeleton)

This is the web version of your Tkinter desktop app. The scheduling
logic (Genetic Algorithm, session-building, hard/soft rules) is
**copied unchanged** from your `.py` file into `ga_engine.py` — it was
already written as plain functions with no Tkinter dependency, so
nothing about *how* the timetable is generated has changed.

## What works right now

The home screen is a card dashboard (matching a "Quick Actions" app
layout) with 5 cards. Tapping one opens that view's own filter panel +
Generate button + result table, with a Back button to return home:

- **All Timetable** (`POST /api/all`) — master combined table: every
  class in the shift, grouped by day (the "Day" column spans the
  class-rows under it), matching the college's printed master
  timetable. Mirrors `_render_all_combined`.
- **Student Timetable** (`POST /api/student`, class list from
  `POST /api/class-list`) — pick one class, see just its grid. Mirrors
  `_render_class_table`.
- **Faculty Timetable** (`POST /api/faculty`, dropdown from
  `POST /api/faculty-list`) — one faculty's combined schedule across
  every class in the shift, with FREE periods marked. Mirrors
  `_render_faculty_single`.
- **Lab Timetable** (`POST /api/lab`) — same master-table layout as
  All Timetable, but every non-lab cell is blanked so only Lab Hours
  remain. Mirrors `_render_lab_combined`.
- **Exam Timetable** (`POST /api/exam`, types from `GET /api/exam-types`)
  — cross-class exam schedule for Internal 1 / Internal 2 / Model,
  built from `data/exam_dates.csv`. Mirrors `_build_exam_schedule` /
  `_render_exam_table`.

All five re-run the same seeded GA, so they always agree with each
other (same course data -> same generated schedule every time).

Sample CSVs in `data/` (Computer Science, a handful of courses, plus
`exam_dates.csv` with sample Internal 1/2 and Model exam dates) so you
can run it immediately and see all five views working.

## Run it — PC only

```bash
pip install flask --break-system-packages   # if not already installed
python app.py
```

Open **http://127.0.0.1:5000** in a browser, pick Department / Shift /
Term, click **Generate Timetable**.

## Run it — Phone + PC together over WiFi (permanent-app style)

1. Make sure your phone and this PC are on the **same WiFi network**.
2. Double-click **`Start_Timetable_App.bat`** in this folder (Windows
   only). It installs `flask`/`waitress` if missing, starts the server,
   and opens the app on this PC automatically. The terminal window it
   opens prints two links, e.g.:
   ```
   On this PC:      http://127.0.0.1:5000
   On phone/other PCs on the SAME WiFi: http://192.168.1.7:5000
   ```
3. **First time only:** Windows Firewall will pop up asking to allow
   Python — click **Allow access** (tick both Private/Public networks
   if it asks). Without this, the phone can't reach the PC.
4. On your phone's browser, type the second link shown (the
   `192.168.x.x:5000` one) — bookmark it or add it to your phone's
   home screen for one-tap access going forward.
5. Leave the terminal window open (minimised is fine) while you want
   the app reachable — closing it stops the server. To have it start
   automatically every time this PC turns on, put a shortcut to
   `Start_Timetable_App.bat` in your Windows Startup folder
   (`Win+R` → `shell:startup` → drop the shortcut in there).

Editing any CSV in `data/` while the server is running takes effect on
the very next Generate click — no restart needed (see `app.py`'s
`before_request` hook / `ga_engine.reload_data()`).

## Replace with your real data

Swap the files in `data/` with your actual ones (same column formats
as the desktop app expects):

- `department.csv`, `faculty.csv`, `courses.csv`, `semester_dates.csv`
- `exam_dates.csv` (optional — needed later for the Exam Timetable view)

## Not built yet (next steps)

1. **Shift 2 + cross-shift lab-room sharing** — right now each shift
   is generated independently; the desktop app runs Shift 1 first,
   then feeds its lab-room usage into Shift 2's GA run
   (`cross_shift_lab_occ`) so the 2 physical lab rooms are never
   double-booked across shifts.
2. Editable courses (right now the web version pulls straight from
   `courses.csv`, skipping the desktop app's editable `CourseTable`
   grid — could add an "Edit Courses" page before Generate)

## File map

```
app.py                  Flask routes
ga_engine.py             GA engine — copied from your .py, CSV loading points
                          at data/ instead of the current working directory
                          + reload_data() so CSV edits apply without a restart
data/*.csv                Sample data — replace with your real files
templates/index.html      Page shell (6 cards incl. Day Order)
static/style.css          Styling (matches your original color scheme)
static/app.js             Fetches the /api/* routes, renders tables,
                            builds the Download file, Day Order card
Start_Timetable_App.bat   One-click launcher, WiFi-reachable, for
                            Windows — see "Run it — Phone + PC" above
```
