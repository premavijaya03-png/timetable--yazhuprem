/* =====================================================================
   Automatic Timetable Generator — front-end logic
   Screens: home, timetable, dayorder, settings (+ 3 settings sub-pages)
   ===================================================================== */

// ---------------------------------------------------------------
// Screen navigation
// ---------------------------------------------------------------
const screens = document.querySelectorAll(".screen");
const navStack = ["screen-home"];

function showScreen(id) {
  screens.forEach((s) => s.classList.toggle("hidden", s.id !== id));
  window.scrollTo(0, 0);
}

function goTo(id) {
  navStack.push(id);
  showScreen(id);
  onScreenEnter(id);
}

function goBack() {
  if (navStack.length > 1) navStack.pop();
  const id = navStack[navStack.length - 1];
  showScreen(id);
  if (id === "screen-home") loadHomeDayOrderWidget();
}

document.querySelectorAll("[data-nav]").forEach((btn) => {
  btn.addEventListener("click", () => goTo(btn.dataset.nav));
});
document.querySelectorAll("[data-back]").forEach((btn) => {
  btn.addEventListener("click", goBack);
});

function onScreenEnter(id) {
  if (id === "screen-timetable") loadMetaOnce();
  if (id === "screen-dayorder") autoLoadTodayDayOrder();
  if (id === "screen-settings-faculty") loadFacultySettings();
  if (id === "screen-settings-course") loadCourseSettings();
  if (id === "screen-settings-dates") loadDatesSettings();
  if (id === "screen-overview-faculty") loadOverviewFacultyMeta();
  if (id === "screen-overview-course") loadOverviewCourseMeta();
  if (id === "screen-overview-dates") loadOverviewDatesMeta();
}

// ---------------------------------------------------------------
// TIMETABLE screen
// ---------------------------------------------------------------
const deptSelect = document.getElementById("tt-dept");
const shiftSelect = document.getElementById("tt-shift");
const termSelect = document.getElementById("tt-term");
const sharedLabCheckbox = document.getElementById("tt-shared-lab");
const generateBtn = document.getElementById("generateBtn");
const statusEl = document.getElementById("status");
const outputEl = document.getElementById("output");
const downloadRow = document.getElementById("downloadRow");
const downloadBtn = document.getElementById("downloadBtn");
const ttSubPanel = document.getElementById("ttSubPanel");
const subtypeButtons = document.querySelectorAll(".subtype-btn");

const VIEW_TITLES = {
  all: "Master Timetable",
  student: "Student Timetable",
  faculty: "Faculty Timetable",
  lab: "Lab Timetable",
  exam: "Exam Timetable",
};

let metaLoaded = false;
let hasGenerated = false;
let activeView = null;
let genParams = null; // {department, shift, term, shared_lab} used for the last successful generate
let cache = { all: null, lab: null, classes: [], faculty: [], examTypes: [] };
let LAB_COMBINED_LABEL = "Shift 1 & Shift 2"; // overwritten from /api/meta once loaded

async function loadMetaOnce() {
  if (metaLoaded) return;
  const res = await fetch("/api/meta");
  const meta = await res.json();
  deptSelect.innerHTML = meta.departments.map((d) => `<option value="${d}">${d}</option>`).join("");
  shiftSelect.innerHTML = meta.shifts.map((s) => `<option value="${s}">${s}</option>`).join("");
  if (meta.lab_combined_label) LAB_COMBINED_LABEL = meta.lab_combined_label;
  metaLoaded = true;
}

async function callJson(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || `Server error (${res.status})`);
  return res.json();
}

async function runGenerate() {
  generateBtn.disabled = true;
  statusEl.textContent = "Running genetic algorithm... this can take a few seconds.";
  outputEl.innerHTML = "";
  ttSubPanel.innerHTML = "";
  downloadRow.classList.add("hidden");
  activeView = null;
  subtypeButtons.forEach((b) => b.classList.remove("active"));

  const base = { department: deptSelect.value, shift: shiftSelect.value, term: termSelect.value, shared_lab: !!sharedLabCheckbox.checked };

  try {
    const [allData, labData, classData, facultyData, examRes] = await Promise.all([
      callJson("/api/all", base),
      callJson("/api/lab", base),
      callJson("/api/class-list", { shift: base.shift }),
      callJson("/api/faculty-list", base),
      fetch("/api/exam-types").then((r) => r.json()),
    ]);

    cache.all = allData;
    cache.lab = labData;
    cache.classes = classData.classes || [];
    cache.faculty = facultyData.faculty || [];
    cache.examTypes = examRes.exam_types || [];
    genParams = base;
    hasGenerated = true;

    subtypeButtons.forEach((b) => (b.disabled = false));
    statusEl.textContent = `Ready — ${base.shift}, ${base.department}, ${base.term === "ODD" ? "Odd" : "Even"} Semester. Tap a timetable below.`;
  } catch (e) {
    statusEl.textContent = `Error: ${e.message}`;
  } finally {
    generateBtn.disabled = false;
  }
}
generateBtn.addEventListener("click", runGenerate);

function selectSubtype(view) {
  if (!hasGenerated) return;
  activeView = view;
  subtypeButtons.forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  outputEl.innerHTML = "";
  downloadRow.classList.add("hidden");
  statusEl.textContent = "";
  renderSubPanel(view);
}
subtypeButtons.forEach((b) => b.addEventListener("click", () => selectSubtype(b.dataset.view)));

function renderSubPanel(view) {
  if (view === "all") {
    ttSubPanel.innerHTML = "";
    renderAllTimetable(cache.all);
    downloadRow.classList.remove("hidden");
    return;
  }
  if (view === "lab") {
    ttSubPanel.innerHTML = `
      <div class="sub-panel">
        <h3 class="panel-title">Lab Timetable</h3>
        <div class="field-row">
          <label>View
            <select id="subLabSelect">
              <option value="Shift 1">Shift 1</option>
              <option value="Shift 2">Shift 2</option>
              <option value="${LAB_COMBINED_LABEL}">${LAB_COMBINED_LABEL} (combined print)</option>
            </select>
          </label>
        </div>
        <button class="show-btn" id="subShowBtn">Show Timetable</button>
      </div>`;
    document.getElementById("subLabSelect").value = genParams.shift;
    document.getElementById("subShowBtn").addEventListener("click", async () => {
      const labView = document.getElementById("subLabSelect").value;
      statusEl.textContent = "Loading...";
      try {
        if (labView === LAB_COMBINED_LABEL) {
          const data = await callJson("/api/lab-combined", {
            department: genParams.department, term: genParams.term, shared_lab: genParams.shared_lab,
          });
          renderLabTimetableCombined(data);
        } else {
          const data = await callJson("/api/lab", {
            department: genParams.department, term: genParams.term, shift: labView, shared_lab: genParams.shared_lab,
          });
          renderLabTimetable(data);
        }
        downloadRow.classList.remove("hidden");
        statusEl.textContent = "";
      } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
      }
    });
    // Show the already-generated shift's lab data right away, no extra tap needed.
    renderLabTimetable(cache.lab);
    downloadRow.classList.remove("hidden");
    return;
  }
  if (view === "student") {
    ttSubPanel.innerHTML = `
      <div class="sub-panel">
        <h3 class="panel-title">Student Timetable</h3>
        <div class="field-row">
          <label>Class
            <select id="subClassSelect">${cache.classes.map((c) => `<option value="${c}">${c}</option>`).join("") || "<option>No classes</option>"}</select>
          </label>
        </div>
        <button class="show-btn" id="subShowBtn">Show Timetable</button>
      </div>`;
    document.getElementById("subShowBtn").addEventListener("click", async () => {
      const className = document.getElementById("subClassSelect").value;
      if (!className) return;
      statusEl.textContent = "Loading...";
      try {
        const data = await callJson("/api/student", { ...genParams, class_name: className });
        renderStudentTimetable(data);
        downloadRow.classList.remove("hidden");
        statusEl.textContent = "";
      } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
      }
    });
    return;
  }
  if (view === "faculty") {
    ttSubPanel.innerHTML = `
      <div class="sub-panel">
        <h3 class="panel-title">Faculty Timetable</h3>
        <div class="field-row">
          <label>Faculty
            <select id="subFacultySelect">${cache.faculty.map((f) => `<option value="${f}">${f}</option>`).join("") || "<option value=''>No faculty found</option>"}</select>
          </label>
        </div>
        <button class="show-btn" id="subShowBtn" ${cache.faculty.length ? "" : "disabled"}>Show Timetable</button>
      </div>`;
    document.getElementById("subShowBtn").addEventListener("click", async () => {
      const faculty = document.getElementById("subFacultySelect").value;
      if (!faculty) return;
      statusEl.textContent = "Loading...";
      try {
        const data = await callJson("/api/faculty", { ...genParams, faculty });
        renderFacultyTimetable(data);
        downloadRow.classList.remove("hidden");
        statusEl.textContent = "";
      } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
      }
    });
    return;
  }
  if (view === "exam") {
    ttSubPanel.innerHTML = `
      <div class="sub-panel">
        <h3 class="panel-title">Exam Timetable</h3>
        <div class="field-row">
          <label>Exam Type
            <select id="subExamSelect">${cache.examTypes.map((t) => `<option value="${t}">${t}</option>`).join("")}</select>
          </label>
        </div>
        <button class="show-btn" id="subShowBtn">Show Timetable</button>
      </div>`;
    document.getElementById("subShowBtn").addEventListener("click", async () => {
      const examType = document.getElementById("subExamSelect").value;
      statusEl.textContent = "Loading...";
      try {
        const data = await callJson("/api/exam", { ...genParams, exam_type: examType });
        renderExamTimetable(data);
        downloadRow.classList.remove("hidden");
        statusEl.textContent = "";
      } catch (e) {
        statusEl.textContent = `Error: ${e.message}`;
      }
    });
    return;
  }
}

function periodHeaderRow(periods) {
  return "<tr><th>Day / Time</th>" + periods.map((p) => `<th>${p === "LUNCH" ? "LUNCH BREAK" : p}</th>`).join("") + "</tr>";
}

function cellHtml(cell) {
  if (cell.lunch) return `<td class="lunch">🍽 Lunch</td>`;
  if (cell.empty) return `<td class="empty">—</td>`;
  const facultyLine = cell.faculty ? `<span class="faculty-name">${cell.faculty}</span>` : "";
  return `<td colspan="${cell.colspan}" style="background:${cell.color}">
      <span class="course-name">${cell.name}</span>${facultyLine}
    </td>`;
}

function makeTable(periods) {
  const table = document.createElement("table");
  table.className = "timetable";
  const thead = document.createElement("thead");
  thead.innerHTML = periodHeaderRow(periods);
  table.appendChild(thead);
  return table;
}

function wrapScroll(table) {
  const wrap = document.createElement("div");
  wrap.className = "timetable-scroll";
  wrap.appendChild(table);
  return wrap;
}

// ---------- Master ("All") Timetable ----------
function renderAllTimetable(data) {
  outputEl.innerHTML = "";
  const scoreLine = document.createElement("p");
  scoreLine.className = "score-line";
  scoreLine.textContent =
    data.score === 0
      ? `${data.shift} — ✅ perfect schedule (no clashes)`
      : `${data.shift} — ⚠️ penalty score ${data.score} (some soft preferences unmet)`;
  outputEl.appendChild(scoreLine);

  if (data.unplaced && data.unplaced.length) {
    const warn = document.createElement("div");
    warn.className = "unplaced-warning";
    warn.innerHTML =
      "<strong>Could not be fully scheduled:</strong><br>" +
      data.unplaced.map((u) => `• ${u.class}: ${u.course}${u.faculty ? ` (${u.faculty})` : ""}`).join("<br>");
    outputEl.appendChild(warn);
  }

  const block = document.createElement("div");
  block.className = "class-block";
  const table = document.createElement("table");
  table.className = "timetable";
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>Day</th><th>Class</th>" +
    data.periods.map((p) => `<th>${p === "LUNCH" ? "LUNCH BREAK" : p}</th>`).join("") +
    "</tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  data.days_json.forEach((dayBlock) => {
    dayBlock.class_rows.forEach((crow, idx) => {
      const tr = document.createElement("tr");
      let html = "";
      if (idx === 0) html += `<td class="daycell" rowspan="${dayBlock.class_rows.length}">${dayBlock.day}</td>`;
      html += `<td class="classcell">${crow.class_abbr}</td>`;
      html += crow.cells.map(cellHtml).join("");
      tr.innerHTML = html;
      tbody.appendChild(tr);
    });
  });
  table.appendChild(tbody);
  block.appendChild(wrapScroll(table));
  outputEl.appendChild(block);
}

// ---------- Lab Timetable ----------
function buildLabBlock(data, titleText) {
  const block = document.createElement("div");
  block.className = "class-block";
  if (titleText) {
    const heading = document.createElement("h3");
    heading.textContent = titleText;
    block.appendChild(heading);
  }
  if (!data.any_found) {
    const msg = document.createElement("p");
    msg.className = "unplaced-warning";
    msg.textContent = "No Lab Hours found in this shift's generated timetable.";
    block.appendChild(msg);
    return block;
  }
  const table = document.createElement("table");
  table.className = "timetable";
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>Day</th><th>Class</th>" +
    data.periods.map((p) => `<th>${p === "LUNCH" ? "LUNCH BREAK" : p}</th>`).join("") +
    "</tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  data.days_json.forEach((dayBlock) => {
    dayBlock.class_rows.forEach((crow, idx) => {
      const tr = document.createElement("tr");
      let html = "";
      if (idx === 0) html += `<td class="daycell" rowspan="${dayBlock.class_rows.length}">${dayBlock.day}</td>`;
      html += `<td class="classcell">${crow.class_abbr}</td>`;
      html += crow.cells.map(cellHtml).join("");
      tr.innerHTML = html;
      tbody.appendChild(tr);
    });
  });
  table.appendChild(tbody);
  block.appendChild(wrapScroll(table));
  return block;
}

function renderLabTimetable(data) {
  outputEl.innerHTML = "";
  outputEl.appendChild(buildLabBlock(data, null));
}

function renderLabTimetableCombined(data) {
  outputEl.innerHTML = "";
  const s1 = data.shift1, s2 = data.shift2;

  if (!s1.any_found && !s2.any_found) {
    const block = document.createElement("div");
    block.className = "class-block";
    const msg = document.createElement("p");
    msg.className = "unplaced-warning";
    msg.textContent = "No Lab Hours found in either shift's generated timetable.";
    block.appendChild(msg);
    outputEl.appendChild(block);
    return;
  }

  const block = document.createElement("div");
  block.className = "class-block";
  const heading = document.createElement("h3");
  heading.textContent = "Shift 1 & Shift 2 — Lab Timetable";
  block.appendChild(heading);

  const table = document.createElement("table");
  table.className = "timetable";
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>Day</th><th>Class</th>" +
    data.periods.map((p) => `<th>${p === "LUNCH" ? "LUNCH BREAK" : p}</th>`).join("") +
    "</tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  data.days.forEach((day, d_i) => {
    const s1Rows = (s1.days_json[d_i] ? s1.days_json[d_i].class_rows : []).map((r) => ({ ...r, class_abbr: `${r.class_abbr} (Shift 1)` }));
    const s2Rows = (s2.days_json[d_i] ? s2.days_json[d_i].class_rows : []).map((r) => ({ ...r, class_abbr: `${r.class_abbr} (Shift 2)` }));
    const rows = [...s1Rows, ...s2Rows];
    if (!rows.length) return;
    rows.forEach((crow, idx) => {
      const tr = document.createElement("tr");
      let html = "";
      if (idx === 0) html += `<td class="daycell" rowspan="${rows.length}">${day}</td>`;
      html += `<td class="classcell">${crow.class_abbr}</td>`;
      html += crow.cells.map(cellHtml).join("");
      tr.innerHTML = html;
      tbody.appendChild(tr);
    });
  });
  table.appendChild(tbody);
  block.appendChild(wrapScroll(table));
  outputEl.appendChild(block);
}

// ---------- Student Timetable ----------
function renderStudentTimetable(data) {
  outputEl.innerHTML = "";
  if (!data.found) {
    const msg = document.createElement("p");
    msg.className = "unplaced-warning";
    msg.textContent = "No timetable generated for this class yet.";
    outputEl.appendChild(msg);
    return;
  }
  const block = document.createElement("div");
  block.className = "class-block";
  const heading = document.createElement("h3");
  heading.textContent = `${data.shift} — ${data.class}`;
  block.appendChild(heading);

  const table = makeTable(data.periods);
  const tbody = document.createElement("tbody");
  data.rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="daycell">${row.day}</td>` + row.cells.map(cellHtml).join("");
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  block.appendChild(wrapScroll(table));
  outputEl.appendChild(block);
}

// ---------- Faculty Timetable ----------
function facultyCellHtml(cell, freeColor) {
  if (cell.lunch) return `<td class="lunch">🍽 Lunch</td>`;
  if (cell.free) return `<td style="background:${freeColor};color:#2e7d32;font-weight:bold">FREE</td>`;
  return `<td colspan="${cell.colspan}" style="background:${cell.color};color:${cell.text_color}">
      <span class="course-name">${cell.class_abbr}</span>
      <span class="faculty-name">${cell.name}</span>
    </td>`;
}

function renderFacultyTimetable(data) {
  outputEl.innerHTML = "";
  const heading = document.createElement("p");
  heading.className = "score-line";
  heading.textContent = `${data.faculty} — ${data.shift}, ${data.department}`;
  outputEl.appendChild(heading);

  const block = document.createElement("div");
  block.className = "class-block";
  const table = makeTable(data.periods);
  const tbody = document.createElement("tbody");
  data.grid.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td class="daycell">${row.day}</td>` +
      row.cells.map((c) => facultyCellHtml(c, data.free_color)).join("");
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  block.appendChild(wrapScroll(table));
  outputEl.appendChild(block);
}

// ---------- Exam Timetable ----------
function renderExamTimetable(data) {
  outputEl.innerHTML = "";
  if (!data.date_rows || !data.date_rows.length) {
    const msg = document.createElement("p");
    msg.className = "unplaced-warning";
    msg.textContent = `No dates found for "${data.exam_type}" (${data.term} Semester) in exam_dates.csv. Add rows in Settings → Manage Dates → Exam Dates.`;
    outputEl.appendChild(msg);
    return;
  }

  const block = document.createElement("div");
  block.className = "class-block";
  const heading = document.createElement("h3");
  heading.textContent = `${data.exam_type} — ${data.shift}`;
  block.appendChild(heading);

  const table = document.createElement("table");
  table.className = "timetable";
  const thead = document.createElement("thead");
  thead.innerHTML =
    "<tr><th>Date</th>" +
    data.classes.map((c) => `<th>${data.class_abbr[c] || c}</th>`).join("") +
    "</tr>";
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  data.rows.forEach((row) => {
    const tr = document.createElement("tr");
    let cells = `<td class="daycell">${row.date}${row.day ? `<br>${row.day}` : ""}${row.day_order ? `<br>${row.day_order}` : ""}</td>`;
    data.classes.forEach((cname) => {
      const entries = row.cells[cname] || [];
      if (!entries.length) {
        cells += `<td class="empty">---</td>`;
      } else {
        const html = entries
          .map((e) => `<div><b>${e.course}</b><br>${e.faculty || "-"}${e.hour_label ? `<br>${e.hour_label}` : ""}</div>`)
          .join("<hr style='opacity:0.3'>");
        cells += `<td>${html}</td>`;
      }
    });
    tr.innerHTML = cells;
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  block.appendChild(wrapScroll(table));
  outputEl.appendChild(block);
}

// ---------- Download (standalone HTML file) ----------
const DOWNLOAD_TABLE_CSS = `
  body{font-family:Arial,Helvetica,sans-serif;margin:24px;color:#1a1a1a;background:#fff;}
  h1{font-size:18px;color:#4c1d95;margin:0 0 4px;}
  .meta{font-size:12px;color:#666;margin:0 0 18px;}
  .class-block{margin-bottom:24px;}
  .class-block h2,.class-block h3{background:#4c1d95;color:#fff;margin:0;padding:10px 16px;font-size:15px;}
  table.timetable{border-collapse:collapse;width:100%;}
  table.timetable th,table.timetable td{border:1px solid #ddd;padding:8px 6px;text-align:center;font-size:12px;vertical-align:middle;}
  table.timetable thead th{background:#8b5cf6;color:#fff;font-weight:bold;}
  table.timetable td.daycell{background:#4c1d95;color:#fff;font-weight:bold;}
  table.timetable td.classcell{background:#ede9fe;font-weight:bold;}
  table.timetable td.lunch{background:#fff3cd;color:#856404;font-weight:bold;}
  table.timetable td.empty{color:#aaa;}
  table.timetable td .course-name{font-weight:bold;display:block;}
  table.timetable td .faculty-name{display:block;font-size:10.5px;opacity:0.8;}
  .score-line{font-size:13px;color:#444;margin-bottom:10px;}
  .unplaced-warning{background:#fff3cd;border:1px solid #ffe08a;color:#7a5b00;padding:10px 14px;border-radius:6px;margin-bottom:14px;font-size:12.5px;}
  .day-order-box{border:1px solid #e3e3e3;border-radius:8px;padding:16px 20px;}
  .day-order-box h3{background:none;color:#4c1d95;padding:0 0 10px;font-size:17px;}
  .day-order-body p{margin:6px 0;font-size:13.5px;}
  @media print { body{margin:8px;} }
`;

function slugify(text) {
  return (text || "file").toString().trim().replace(/[^a-z0-9]+/gi, "_").replace(/^_+|_+$/g, "");
}

function downloadFilename() {
  const parts = [VIEW_TITLES[activeView] || "Timetable"];
  if (genParams) parts.push(genParams.shift);
  return slugify(parts.join("_")) + ".html";
}

function triggerDownload() {
  if (!outputEl.innerHTML.trim()) return;
  const title = VIEW_TITLES[activeView] || "Timetable";
  const stamp = new Date().toLocaleString();
  const fullHtml = `<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>${title}</title>
<style>${DOWNLOAD_TABLE_CSS}</style>
</head><body>
<h1>${title}</h1>
<p class="meta">Automatic Timetable Generator — downloaded ${stamp}</p>
${outputEl.innerHTML}
</body></html>`;

  const blob = new Blob([fullHtml], { type: "text/html" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = downloadFilename();
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
downloadBtn.addEventListener("click", triggerDownload);

// ---------------------------------------------------------------
// DAY ORDER screen
// ---------------------------------------------------------------
const dayOrderDate = document.getElementById("dayOrderDate");
const checkDayOrderBtn = document.getElementById("checkDayOrderBtn");
const doStatus = document.getElementById("doStatus");
const doOutput = document.getElementById("doOutput");

checkDayOrderBtn.addEventListener("click", () => runDayOrderCheck());

async function runDayOrderCheck() {
  if (!dayOrderDate.value) {
    const today = new Date();
    dayOrderDate.value = today.toISOString().slice(0, 10);
  }
  doStatus.textContent = "Checking...";
  doOutput.innerHTML = "";
  try {
    const data = await callJson("/api/day-order", { date: dayOrderDate.value });
    renderDayOrder(data);
    doStatus.textContent = "";
  } catch (e) {
    doStatus.textContent = `Error: ${e.message}`;
  }
}

// Auto-show TODAY's Day Order the moment this screen opens - same idea
// as a phone showing today's date by itself, no tap needed. The date
// box is reset to today every time you come back to this screen; pick
// a different date + "Check Day Order" any time to look up another day.
function autoLoadTodayDayOrder() {
  const today = new Date();
  dayOrderDate.value = today.toISOString().slice(0, 10);
  runDayOrderCheck();
}

function renderDayOrder(data) {
  doOutput.innerHTML = "";
  const box = document.createElement("div");
  box.className = "class-block day-order-box";

  const heading = document.createElement("h3");
  heading.textContent = data.is_holiday
    ? `${data.date} — ${data.weekday} (Holiday)`
    : `${data.date} — ${data.weekday}`;
  box.appendChild(heading);

  const body = document.createElement("div");
  body.className = "day-order-body";

  const line1 = data.is_holiday
    ? `Semester: ${data.semester} &nbsp;&nbsp; Day Order: <b>Holiday</b> (${data.holiday_reason})`
    : `Semester: ${data.semester} &nbsp;&nbsp; Day Order: <b>${data.day_order}</b>`;
  const line2 = `Week: ${data.week_no} &nbsp;&nbsp; No. of Working Days: ${data.working_done} &nbsp;&nbsp; Balance Working Days: ${data.remaining}`;
  const line3 = `Semester Completed: <b>${data.percent}%</b> (${data.working_done}/${data.total_working_days} working days)`;

  body.innerHTML = `<p>${line1}</p><p>${line2}</p><p>${line3}</p>`;
  box.appendChild(body);

  const barWrap = document.createElement("div");
  barWrap.className = "day-order-progress";
  const bar = document.createElement("div");
  bar.className = "day-order-progress-fill";
  bar.style.width = `${Math.min(100, data.percent)}%`;
  barWrap.appendChild(bar);
  box.appendChild(barWrap);

  doOutput.appendChild(box);
}

// ---------------------------------------------------------------
// HOME screen — "Today's Day Order" widget
// Shows today's Day Order right on the home screen automatically
// (no tap needed), and re-checks it whenever the app becomes visible
// again (e.g. reopened the next day) so it always reflects "today".
// ---------------------------------------------------------------
const homeDayOrderWidget = document.getElementById("homeDayOrderWidget");
let homeDoLastDate = null;

async function loadHomeDayOrderWidget() {
  if (!homeDayOrderWidget) return;
  const today = new Date();
  const todayStr = today.toISOString().slice(0, 10);
  homeDoLastDate = todayStr;
  homeDayOrderWidget.innerHTML = `<div class="home-do-widget loading">Checking today's Day Order…</div>`;
  try {
    const data = await callJson("/api/day-order", { date: todayStr });
    renderHomeDayOrderWidget(data);
  } catch (e) {
    homeDayOrderWidget.innerHTML = `<div class="home-do-widget loading">Day Order unavailable</div>`;
  }
}

function renderHomeDayOrderWidget(data) {
  const dateLabel = `${data.date} — ${data.weekday}`;
  const orderHtml = data.is_holiday
    ? `<span class="home-do-order holiday">Holiday</span>`
    : `<span class="home-do-order">Day ${data.day_order}</span>`;
  homeDayOrderWidget.innerHTML = `
    <div class="home-do-widget">
      <div class="home-do-left">
        <span class="home-do-date">${dateLabel}</span>
        <span class="home-do-label">${data.semester}</span>
      </div>
      ${orderHtml}
    </div>`;
  updateAppIconBadge(data);
}

// Best-effort: put today's Day Order number on the app's HOME-SCREEN
// icon badge (the little red dot with a number you see on Mail/Messages
// app icons). This is NOT the same as a clock face redrawing itself —
// no web app (installed/PWA or not) is allowed to repaint its own
// home-screen icon artwork; the OS never exposes that to a website for
// security reasons, on Android, iOS or desktop. The Badge API below is
// the closest real equivalent: it can only show a plain number (no
// "IV", no roman numerals), and only works once this app is actually
// installed to the home screen, and only on platforms that support it
// (Chrome/Edge on Windows/ChromeOS/Android; not supported on iOS
// Safari at all). Where it isn't supported this silently does nothing
// — the in-app widget above is still the reliable way to see the Day
// Order.
function updateAppIconBadge(data) {
  if (!("setAppBadge" in navigator)) return;
  try {
    if (data.is_holiday) {
      navigator.clearAppBadge().catch(() => {});
      return;
    }
    const romanToNum = { I: 1, II: 2, III: 3, IV: 4, V: 5, VI: 6 };
    const n = romanToNum[data.day_order];
    if (n) navigator.setAppBadge(n).catch(() => {});
  } catch (e) {
    /* Badge API not available on this platform - ignore */
  }
}

// Re-check if the calendar date has rolled over while the app was
// open in the background (mirrors how a phone's app icon updates
// its date on its own overnight).
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  const nowStr = new Date().toISOString().slice(0, 10);
  if (nowStr !== homeDoLastDate) loadHomeDayOrderWidget();
});

loadHomeDayOrderWidget();

// ---------------------------------------------------------------
// OVERVIEW — Faculty / Course / Dates (read-only, no login needed)
// ---------------------------------------------------------------
const ovFacShift = document.getElementById("ovFacShift");
const ovFacClass = document.getElementById("ovFacClass");
const ovFacultyOutput = document.getElementById("ovFacultyOutput");
const ovCourseTerm = document.getElementById("ovCourseTerm");
const ovCourseShift = document.getElementById("ovCourseShift");
const ovCourseClass = document.getElementById("ovCourseClass");
const ovCourseOutput = document.getElementById("ovCourseOutput");
const ovDatesTerm = document.getElementById("ovDatesTerm");
const ovDatesCategory = document.getElementById("ovDatesCategory");
const ovDatesOutput = document.getElementById("ovDatesOutput");

let overviewMetaLoaded = false;
let overviewClassesByShift = {};

async function ensureOverviewMeta() {
  if (overviewMetaLoaded) return;
  const res = await fetch("/api/settings/options");
  const data = await res.json();
  overviewClassesByShift = data.classes_by_shift || {};
  const shiftOptions = (data.shifts || []).map((s) => `<option value="${s}">${s}</option>`).join("");
  if (ovFacShift) ovFacShift.innerHTML = shiftOptions;
  if (ovCourseShift) ovCourseShift.innerHTML = shiftOptions;
  overviewMetaLoaded = true;
}

function populateOverviewClassDropdown(selectEl, shift) {
  const classes = overviewClassesByShift[shift] || [];
  selectEl.innerHTML = classes.map((c) => `<option value="${c}">${c}</option>`).join("");
}

// ---- Overview: Faculty ----
async function loadOverviewFacultyMeta() {
  await ensureOverviewMeta();
  populateOverviewClassDropdown(ovFacClass, ovFacShift.value);
  await refreshOverviewFaculty();
}

async function refreshOverviewFaculty() {
  const shift = ovFacShift.value;
  const className = ovFacClass.value;
  if (!className) { ovFacultyOutput.innerHTML = ""; return; }
  ovFacultyOutput.innerHTML = `<p class="status">Loading...</p>`;
  try {
    const data = await callJson("/api/overview/faculty", { shift, class_name: className });
    const fac = data.faculty || [];
    if (!fac.length) {
      ovFacultyOutput.innerHTML = `<p class="small-note">No faculty found for ${shift} — ${className}.</p>`;
      return;
    }
    ovFacultyOutput.innerHTML = `
      <div class="class-block">
        <h3>${shift} — ${className}</h3>
        <div style="padding:12px 14px;">
          ${fac.map((f) => `<div class="edit-row"><span style="flex:1;">${f}</span></div>`).join("")}
        </div>
      </div>`;
  } catch (e) {
    ovFacultyOutput.innerHTML = `<p class="unplaced-warning">Error: ${e.message}</p>`;
  }
}
if (ovFacShift) {
  ovFacShift.addEventListener("change", () => {
    populateOverviewClassDropdown(ovFacClass, ovFacShift.value);
    refreshOverviewFaculty();
  });
  ovFacClass.addEventListener("change", refreshOverviewFaculty);
}

// ---- Overview: Course ----
async function loadOverviewCourseMeta() {
  await ensureOverviewMeta();
  populateOverviewClassDropdown(ovCourseClass, ovCourseShift.value);
  await refreshOverviewCourse();
}

async function refreshOverviewCourse() {
  const term = ovCourseTerm.value;
  const shift = ovCourseShift.value;
  const className = ovCourseClass.value;
  if (!className) { ovCourseOutput.innerHTML = ""; return; }
  ovCourseOutput.innerHTML = `<p class="status">Loading...</p>`;
  try {
    const data = await callJson("/api/overview/courses", { term, shift, class_name: className });
    const courses = data.courses || [];
    if (!courses.length) {
      ovCourseOutput.innerHTML = `<p class="small-note">No papers found for ${shift} — ${className} (${term === "ODD" ? "Odd" : "Even"} Semester).</p>`;
      return;
    }
    const rows = courses.map((c) => `
      <tr>
        <td style="text-align:left;">${c.name}</td>
        <td>${c.faculty || "-"}</td>
        <td>${c.hours}</td>
      </tr>`).join("");
    ovCourseOutput.innerHTML = `
      <div class="class-block">
        <h3>${shift} — ${className} (${term === "ODD" ? "Odd" : "Even"} Semester)</h3>
        <div class="timetable-scroll">
          <table class="timetable">
            <thead><tr><th>Paper</th><th>Faculty</th><th>Hours / Week</th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </div>`;
  } catch (e) {
    ovCourseOutput.innerHTML = `<p class="unplaced-warning">Error: ${e.message}</p>`;
  }
}
if (ovCourseShift) {
  ovCourseTerm.addEventListener("change", refreshOverviewCourse);
  ovCourseShift.addEventListener("change", () => {
    populateOverviewClassDropdown(ovCourseClass, ovCourseShift.value);
    refreshOverviewCourse();
  });
  ovCourseClass.addEventListener("change", refreshOverviewCourse);
}

// ---- Overview: Dates ----
function loadOverviewDatesMeta() {
  refreshOverviewDates();
}

async function refreshOverviewDates() {
  const term = ovDatesTerm.value;
  const category = ovDatesCategory.value;
  ovDatesOutput.innerHTML = `<p class="status">Loading...</p>`;
  try {
    const data = await callJson("/api/overview/dates", { term, category });
    const termLabel = term === "ODD" ? "Odd" : "Even";
    if (category === "College Dates") {
      if (!data.start && !data.end) {
        ovDatesOutput.innerHTML = `<p class="small-note">No dates set yet for ${termLabel} Semester.</p>`;
        return;
      }
      ovDatesOutput.innerHTML = `
        <div class="class-block">
          <h3>College Dates — ${termLabel} Semester</h3>
          <div style="padding:14px 16px;">
            <p>Starting Date: <b>${data.start || "-"}</b></p>
            <p>Ending Date: <b>${data.end || "-"}</b></p>
          </div>
        </div>`;
      return;
    }
    const rows = data.rows || [];
    if (!rows.length) {
      ovDatesOutput.innerHTML = `<p class="small-note">No ${category} dates found for ${termLabel} Semester.</p>`;
      return;
    }
    const trs = rows.map((r) => `<tr><td>${r.day_order}</td><td>${r.date}</td><td>${r.day || "-"}</td></tr>`).join("");
    ovDatesOutput.innerHTML = `
      <div class="class-block">
        <h3>${category} — ${termLabel} Semester</h3>
        <div class="timetable-scroll">
          <table class="timetable">
            <thead><tr><th>Day Order</th><th>Date</th><th>Day</th></tr></thead>
            <tbody>${trs}</tbody>
          </table>
        </div>
      </div>`;
  } catch (e) {
    ovDatesOutput.innerHTML = `<p class="unplaced-warning">Error: ${e.message}</p>`;
  }
}
if (ovDatesTerm) {
  ovDatesTerm.addEventListener("change", refreshOverviewDates);
  ovDatesCategory.addEventListener("change", refreshOverviewDates);
}

// ---------------------------------------------------------------
// SETTINGS — Admin login (protects Manage Faculty / Course / Dates)
// ---------------------------------------------------------------
const adminUserId = document.getElementById("adminUserId");
const adminPassword = document.getElementById("adminPassword");
const adminLoginBtn = document.getElementById("adminLoginBtn");
const adminLoginStatus = document.getElementById("adminLoginStatus");

function isAuthError(data) {
  return !!(data && data.error === "Admin login required");
}

function goToAdminLogin() {
  if (navStack[navStack.length - 1] !== "screen-settings-login") {
    goTo("screen-settings-login");
  }
}

if (adminLoginBtn) {
  adminLoginBtn.addEventListener("click", async () => {
    const userId = adminUserId.value.trim();
    const password = adminPassword.value;
    adminLoginBtn.disabled = true;
    adminLoginStatus.textContent = "Checking...";
    adminLoginStatus.className = "save-status";
    try {
      const res = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userId, password }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        adminLoginStatus.textContent = data.error || "Invalid User ID or Password";
        adminLoginStatus.className = "save-status err";
        return;
      }
      adminUserId.value = "";
      adminPassword.value = "";
      adminLoginStatus.textContent = "";
      goTo("screen-settings");
    } catch (e) {
      adminLoginStatus.textContent = `Error: ${e.message}`;
      adminLoginStatus.className = "save-status err";
    } finally {
      adminLoginBtn.disabled = false;
    }
  });
  [adminUserId, adminPassword].forEach((el) => {
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter") adminLoginBtn.click();
    });
  });
}

// Leaving Settings back to Home logs the admin out, so opening
// Settings again always asks for the User ID / Password afresh.
const settingsBackBtn = document.getElementById("settingsBackBtn");
if (settingsBackBtn) {
  settingsBackBtn.addEventListener("click", () => {
    fetch("/api/admin/logout", { method: "POST" }).catch(() => {});
  });
}

// ---------------------------------------------------------------
// SETTINGS — Manage Faculty
// ---------------------------------------------------------------
const facultyList = document.getElementById("facultyList");
const addFacultyBtn = document.getElementById("addFacultyBtn");
const saveFacultyBtn = document.getElementById("saveFacultyBtn");
const facultySaveStatus = document.getElementById("facultySaveStatus");
let facultyLoaded = false;

async function loadFacultySettings(force) {
  if (facultyLoaded && !force) return;
  facultyList.innerHTML = "<p class='status'>Loading...</p>";
  const res = await fetch("/api/settings/faculty");
  const data = await res.json();
  if (isAuthError(data)) { goToAdminLogin(); return; }
  facultyList.innerHTML = "";
  (data.rows || []).forEach((r) => addFacultyRow(r.FacultyName));
  facultyLoaded = true;
  facultySaveStatus.textContent = "";
}

function addFacultyRow(value) {
  const row = document.createElement("div");
  row.className = "edit-row";
  row.innerHTML = `
    <input type="text" value="${(value || "").replace(/"/g, "&quot;")}" placeholder="Faculty name">
    <button class="icon-btn" title="Delete">🗑</button>`;
  row.querySelector(".icon-btn").addEventListener("click", () => row.remove());
  facultyList.appendChild(row);
}

addFacultyBtn.addEventListener("click", () => addFacultyRow(""));

saveFacultyBtn.addEventListener("click", async () => {
  const rows = Array.from(facultyList.querySelectorAll(".edit-row input")).map((inp) => ({
    FacultyName: inp.value.trim(),
  }));
  saveFacultyBtn.disabled = true;
  facultySaveStatus.textContent = "Saving...";
  facultySaveStatus.className = "save-status";
  try {
    const res = await fetch("/api/settings/faculty", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");
    facultySaveStatus.textContent = "Saved ✓ — used the next time you generate a timetable.";
    facultySaveStatus.className = "save-status ok";
    metaLoaded = false; // department/shift lists unaffected but keep consistent
    facultyLoaded = false;
    loadFacultySettings(true);
  } catch (e) {
    facultySaveStatus.textContent = `Error: ${e.message}`;
    facultySaveStatus.className = "save-status err";
  } finally {
    saveFacultyBtn.disabled = false;
  }
});

// ---------------------------------------------------------------
// SETTINGS — Manage Course
// ---------------------------------------------------------------
const courseList = document.getElementById("courseList");
const addCourseBtn = document.getElementById("addCourseBtn");
const saveCourseBtn = document.getElementById("saveCourseBtn");
const courseSaveStatus = document.getElementById("courseSaveStatus");
const courseFilterShift = document.getElementById("courseFilterShift");
const courseFilterClass = document.getElementById("courseFilterClass");

let courseLoaded = false;
let courseRows = []; // full dataset kept in memory, each with a stable _id
let courseOptions = null; // {shifts, departments, classes_by_shift, semesters}
let courseIdSeq = 0;

async function loadCourseSettings(force) {
  if (courseLoaded && !force) return;
  courseList.innerHTML = "<p class='status'>Loading...</p>";
  const [optRes, dataRes] = await Promise.all([
    fetch("/api/settings/options").then((r) => r.json()),
    fetch("/api/settings/courses").then((r) => r.json()),
  ]);
  if (isAuthError(dataRes)) { goToAdminLogin(); return; }
  courseOptions = optRes;
  courseRows = (dataRes.rows || []).map((r) => ({ ...r, _id: courseIdSeq++ }));

  courseFilterShift.innerHTML =
    `<option value="">All Shifts</option>` +
    courseOptions.shifts.map((s) => `<option value="${s}">${s}</option>`).join("");
  refreshCourseClassFilter();
  courseFilterShift.addEventListener("change", refreshCourseClassFilter);
  courseFilterClass.addEventListener("change", renderCourseList);

  courseLoaded = true;
  courseSaveStatus.textContent = "";
  renderCourseList();
}

function refreshCourseClassFilter() {
  const shift = courseFilterShift.value;
  const classes = shift ? (courseOptions.classes_by_shift[shift] || []) : uniqueClassesAcrossShifts();
  courseFilterClass.innerHTML = `<option value="">All Classes</option>` + classes.map((c) => `<option value="${c}">${c}</option>`).join("");
  renderCourseList();
}

function uniqueClassesAcrossShifts() {
  const set = new Set();
  Object.values(courseOptions.classes_by_shift).forEach((arr) => arr.forEach((c) => set.add(c)));
  return Array.from(set);
}

function renderCourseList() {
  const shift = courseFilterShift.value;
  const cls = courseFilterClass.value;
  courseList.innerHTML = "";
  const filtered = courseRows.filter(
    (r) => (!shift || r.Shift === shift) && (!cls || r.Class === cls)
  );
  if (!filtered.length) {
    courseList.innerHTML = `<p class="small-note">No courses match this filter.</p>`;
    return;
  }
  filtered.forEach((row) => courseList.appendChild(buildCourseCard(row)));
}

function buildCourseCard(row) {
  const card = document.createElement("div");
  card.className = "course-card";
  card.dataset.id = row._id;
  card.innerHTML = `
    <div class="course-row-top">
      <span class="course-tag">${row.Shift} • Sem ${row.Semester} • ${row.Class}</span>
      <button class="icon-btn" title="Delete">🗑</button>
    </div>
    <div class="course-fields">
      <div class="field-course"><label>Course</label><input type="text" data-field="Course" value="${escapeAttr(row.Course)}"></div>
      <div class="field-faculty"><label>Faculty</label><input type="text" data-field="Faculty" value="${escapeAttr(row.Faculty)}"></div>
      <div class="field-hours"><label>Hours</label><input type="text" data-field="Hours" value="${escapeAttr(row.Hours)}"></div>
    </div>`;
  card.querySelectorAll("input").forEach((inp) => {
    inp.addEventListener("input", () => {
      const target = courseRows.find((r) => r._id === row._id);
      if (target) target[inp.dataset.field] = inp.value;
    });
  });
  card.querySelector(".icon-btn").addEventListener("click", () => {
    courseRows = courseRows.filter((r) => r._id !== row._id);
    card.remove();
  });
  return card;
}

function escapeAttr(v) {
  return (v || "").toString().replace(/"/g, "&quot;");
}

addCourseBtn.addEventListener("click", () => {
  const shift = courseFilterShift.value || (courseOptions.shifts[0] || "");
  const cls = courseFilterClass.value || ((courseOptions.classes_by_shift[shift] || [])[0] || "");
  const newRow = {
    _id: courseIdSeq++,
    Shift: shift,
    Department: (courseOptions.departments[0] || ""),
    Semester: (courseOptions.semesters[0] || "I"),
    Class: cls,
    Course: "",
    Faculty: "",
    Hours: "",
  };
  courseRows.push(newRow);
  courseList.appendChild(buildCourseCard(newRow));
});

saveCourseBtn.addEventListener("click", async () => {
  saveCourseBtn.disabled = true;
  courseSaveStatus.textContent = "Saving...";
  courseSaveStatus.className = "save-status";
  try {
    const rows = courseRows.map(({ _id, ...rest }) => rest);
    const res = await fetch("/api/settings/courses", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");
    courseSaveStatus.textContent = "Saved ✓ — used the next time you generate a timetable.";
    courseSaveStatus.className = "save-status ok";
    courseLoaded = false;
    loadCourseSettings(true);
  } catch (e) {
    courseSaveStatus.textContent = `Error: ${e.message}`;
    courseSaveStatus.className = "save-status err";
  } finally {
    saveCourseBtn.disabled = false;
  }
});

// ---------------------------------------------------------------
// SETTINGS — Manage Dates (Semester Dates + Exam Dates tabs)
// ---------------------------------------------------------------
const tabSemesterBtn = document.getElementById("tabSemesterBtn");
const tabExamBtn = document.getElementById("tabExamBtn");
const semesterDatesPanel = document.getElementById("semesterDatesPanel");
const examDatesPanel = document.getElementById("examDatesPanel");
const semesterDatesList = document.getElementById("semesterDatesList");
const saveSemesterDatesBtn = document.getElementById("saveSemesterDatesBtn");
const semesterDatesSaveStatus = document.getElementById("semesterDatesSaveStatus");
const examDatesList = document.getElementById("examDatesList");
const addExamDateBtn = document.getElementById("addExamDateBtn");
const saveExamDatesBtn = document.getElementById("saveExamDatesBtn");
const examDatesSaveStatus = document.getElementById("examDatesSaveStatus");

let datesLoaded = false;
let examDateRows = [];
let examDateIdSeq = 0;

tabSemesterBtn.addEventListener("click", () => {
  tabSemesterBtn.classList.add("active");
  tabExamBtn.classList.remove("active");
  semesterDatesPanel.classList.remove("hidden");
  examDatesPanel.classList.add("hidden");
});
tabExamBtn.addEventListener("click", () => {
  tabExamBtn.classList.add("active");
  tabSemesterBtn.classList.remove("active");
  examDatesPanel.classList.remove("hidden");
  semesterDatesPanel.classList.add("hidden");
});

async function loadDatesSettings(force) {
  if (datesLoaded && !force) return;
  semesterDatesList.innerHTML = "<p class='status'>Loading...</p>";
  examDatesList.innerHTML = "";
  const [semRes, examRes] = await Promise.all([
    fetch("/api/settings/semester_dates").then((r) => r.json()),
    fetch("/api/settings/exam_dates").then((r) => r.json()),
  ]);
  if (isAuthError(semRes) || isAuthError(examRes)) { goToAdminLogin(); return; }

  semesterDatesList.innerHTML = "";
  const semRows = semRes.rows && semRes.rows.length ? semRes.rows : [
    { Semester: "ODD", StartDate: "", EndDate: "" },
    { Semester: "EVEN", StartDate: "", EndDate: "" },
  ];
  semRows.forEach((r) => semesterDatesList.appendChild(buildSemesterDateRow(r)));

  examDateRows = (examRes.rows || []).map((r) => ({ ...r, _id: examDateIdSeq++ }));
  renderExamDatesList();

  datesLoaded = true;
  semesterDatesSaveStatus.textContent = "";
  examDatesSaveStatus.textContent = "";
}

function buildSemesterDateRow(row) {
  const wrap = document.createElement("div");
  wrap.className = "course-card";
  wrap.dataset.semester = row.Semester;
  wrap.innerHTML = `
    <div class="course-tag">${row.Semester === "ODD" ? "Odd Semester" : "Even Semester"}</div>
    <div class="course-fields">
      <div class="field-course"><label>Start Date (DD-MM-YYYY)</label><input type="text" data-field="StartDate" value="${escapeAttr(row.StartDate)}" placeholder="15-06-2026"></div>
      <div class="field-course"><label>End Date (DD-MM-YYYY)</label><input type="text" data-field="EndDate" value="${escapeAttr(row.EndDate)}" placeholder="30-10-2026"></div>
    </div>`;
  return wrap;
}

saveSemesterDatesBtn.addEventListener("click", async () => {
  const rows = Array.from(semesterDatesList.children).map((card) => ({
    Semester: card.dataset.semester,
    StartDate: card.querySelector('[data-field="StartDate"]').value.trim(),
    EndDate: card.querySelector('[data-field="EndDate"]').value.trim(),
  }));
  saveSemesterDatesBtn.disabled = true;
  semesterDatesSaveStatus.textContent = "Saving...";
  semesterDatesSaveStatus.className = "save-status";
  try {
    const res = await fetch("/api/settings/semester_dates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");
    semesterDatesSaveStatus.textContent = "Saved ✓";
    semesterDatesSaveStatus.className = "save-status ok";
  } catch (e) {
    semesterDatesSaveStatus.textContent = `Error: ${e.message}`;
    semesterDatesSaveStatus.className = "save-status err";
  } finally {
    saveSemesterDatesBtn.disabled = false;
  }
});

function renderExamDatesList() {
  examDatesList.innerHTML = "";
  if (!examDateRows.length) {
    examDatesList.innerHTML = `<p class="small-note">No exam dates yet — add one below.</p>`;
    return;
  }
  examDateRows.forEach((row) => examDatesList.appendChild(buildExamDateCard(row)));
}

function buildExamDateCard(row) {
  const card = document.createElement("div");
  card.className = "course-card";
  card.dataset.id = row._id;
  card.innerHTML = `
    <div class="course-row-top">
      <span class="course-tag">${row.ExamType || "New"} • ${row.Semester || ""} • Day ${row.DayOrder || ""}</span>
      <button class="icon-btn" title="Delete">🗑</button>
    </div>
    <div class="course-fields">
      <div class="field-course"><label>Exam Type</label><input type="text" data-field="ExamType" value="${escapeAttr(row.ExamType)}" placeholder="Internal 1"></div>
      <div class="field-hours"><label>Semester</label>
        <select data-field="Semester"><option value="ODD" ${row.Semester === "ODD" ? "selected" : ""}>ODD</option><option value="EVEN" ${row.Semester === "EVEN" ? "selected" : ""}>EVEN</option></select>
      </div>
      <div class="field-hours"><label>Day Order</label>
        <select data-field="DayOrder">${["I","II","III","IV","V","VI"].map((d) => `<option value="${d}" ${row.DayOrder === d ? "selected" : ""}>${d}</option>`).join("")}</select>
      </div>
      <div class="field-course"><label>Date</label><input type="text" data-field="Date" value="${escapeAttr(row.Date)}" placeholder="21.08.2026"></div>
      <div class="field-course"><label>Day (optional)</label><input type="text" data-field="Day" value="${escapeAttr(row.Day)}" placeholder="Friday"></div>
    </div>`;
  card.querySelectorAll("input, select").forEach((inp) => {
    inp.addEventListener("input", () => {
      const target = examDateRows.find((r) => r._id === row._id);
      if (target) {
        target[inp.dataset.field] = inp.value;
        if (inp.dataset.field === "ExamType" || inp.dataset.field === "Semester" || inp.dataset.field === "DayOrder") {
          card.querySelector(".course-tag").textContent = `${target.ExamType || "New"} • ${target.Semester || ""} • Day ${target.DayOrder || ""}`;
        }
      }
    });
    inp.addEventListener("change", () => inp.dispatchEvent(new Event("input")));
  });
  card.querySelector(".icon-btn").addEventListener("click", () => {
    examDateRows = examDateRows.filter((r) => r._id !== row._id);
    card.remove();
    if (!examDateRows.length) renderExamDatesList();
  });
  return card;
}

addExamDateBtn.addEventListener("click", () => {
  const newRow = { _id: examDateIdSeq++, ExamType: "", Semester: "ODD", DayOrder: "I", Date: "", Day: "" };
  examDateRows.push(newRow);
  if (examDatesList.querySelector(".small-note")) examDatesList.innerHTML = "";
  examDatesList.appendChild(buildExamDateCard(newRow));
});

saveExamDatesBtn.addEventListener("click", async () => {
  saveExamDatesBtn.disabled = true;
  examDatesSaveStatus.textContent = "Saving...";
  examDatesSaveStatus.className = "save-status";
  try {
    const rows = examDateRows.map(({ _id, ...rest }) => rest);
    const res = await fetch("/api/settings/exam_dates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Save failed");
    examDatesSaveStatus.textContent = "Saved ✓";
    examDatesSaveStatus.className = "save-status ok";
    datesLoaded = false;
    loadDatesSettings(true);
  } catch (e) {
    examDatesSaveStatus.textContent = `Error: ${e.message}`;
    examDatesSaveStatus.className = "save-status err";
  } finally {
    saveExamDatesBtn.disabled = false;
  }
});
