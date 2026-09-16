const preferenceKey = "canvas-archive-preferences";

function loadPreferences() {
  try {
    return JSON.parse(localStorage.getItem(preferenceKey) || "{}");
  } catch {
    return {};
  }
}

const preferences = loadPreferences();
const state = {
  archive: null,
  course: null,
  inbox: null,
  searchResults: null,
  query: "",
  term: preferences.term || "all",
  sort: preferences.sort || "recent",
  density: preferences.density || "comfortable",
};

const view = document.querySelector("#view");
const search = document.querySelector("#global-search");
const refreshButton = document.querySelector("#refresh-button");
const densityButton = document.querySelector("#density-button");
let searchTimer;

const escapeHtml = (value = "") => String(value)
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

const normalize = (value) => String(value || "").toLocaleLowerCase();
const number = (value) => new Intl.NumberFormat().format(value || 0);
const score = (value) => value === null || value === undefined || value === "" ? "-" : Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 });
const date = (value, options = { month: "short", day: "numeric", year: "numeric" }) => {
  if (!value) return "Not available";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? "Not available" : parsed.toLocaleDateString(undefined, options);
};
const bytes = (value) => {
  if (!value) return "0 KB";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
};

function currentRoute() {
  const route = location.hash.replace(/^#\//, "") || "courses";
  const [name, id, tab] = route.split("/");
  return { name, id, tab };
}

function savePreferences() {
  localStorage.setItem(preferenceKey, JSON.stringify({
    term: state.term,
    sort: state.sort,
    density: state.density,
    query: state.query,
  }));
}

function applyDensity() {
  document.body.dataset.density = state.density;
  densityButton.textContent = state.density === "compact" ? "Comfortable view" : "Compact view";
}

function setChrome() {
  const archive = state.archive;
  document.querySelector("#nav-course-count").textContent = archive.totals.courses;
  document.querySelector("#nav-feedback-count").textContent = archive.totals.comments;
  document.querySelector("#nav-file-count").textContent = archive.totals.files;
  document.querySelector("#nav-inbox-count").textContent = archive.totals.conversations;
  document.querySelector("#footer-archive").textContent = archive.archive_name;
  const sync = document.querySelector("#sync-state");
  sync.className = `sync-state ${archive.complete ? "complete" : "live"}`;
  sync.innerHTML = `<span></span><div><b>${archive.complete ? "Archive complete" : "Export in progress"}</b><small>Refreshed ${date(archive.updated_at, { hour: "numeric", minute: "2-digit" })}</small></div>`;
  const active = currentRoute().name === "course" || currentRoute().name === "search" ? "courses" : currentRoute().name;
  document.querySelectorAll(".sidebar nav a").forEach((link) => link.classList.toggle("active", link.dataset.view === active));
}

function pageHeading(title, description) {
  return `<div class="page-heading"><h1>${escapeHtml(title)}</h1><p>${escapeHtml(description)}</p></div>`;
}

function loadingState(label = "Loading archive") {
  return `<div class="loading-skeleton" aria-label="${escapeHtml(label)}">
    <div class="skeleton-title"></div>
    <div class="skeleton-line"></div>
    <div class="skeleton-row"></div><div class="skeleton-row"></div><div class="skeleton-row"></div>
  </div>`;
}

function emptyState(title, body) {
  return `<div class="empty-state"><strong>${escapeHtml(title)}</strong><p>${escapeHtml(body)}</p></div>`;
}

function stateLabel(course) {
  const labels = {
    ready: ["Ready", "ready"],
    exporting: ["Exporting", "pending"],
    limited: ["Access limited", "warning"],
    unavailable: ["Unavailable", "warning"],
  };
  return labels[course.data_state] || ["Unknown", "muted"];
}

function feedbackLabel(course) {
  if (course.comments_state === "ready") return `${course.comment_count} comments`;
  if (course.comments_state === "empty") return "No comments";
  if (course.comments_state === "exporting") return "Comments pending";
  return "Comments unavailable";
}

function effectiveScore(course) {
  return course.final_score ?? course.current_score;
}

function sortCourses(courses) {
  return [...courses].sort((left, right) => {
    if (state.sort === "name") return left.name.localeCompare(right.name);
    if (state.sort === "term") return String(right.term_start || "").localeCompare(String(left.term_start || ""));
    if (state.sort === "grade") return (effectiveScore(right) ?? -Infinity) - (effectiveScore(left) ?? -Infinity);
    return String(right.latest_activity || right.term_start || "").localeCompare(String(left.latest_activity || left.term_start || ""));
  });
}

function courseRow(course) {
  const [label, style] = stateLabel(course);
  const value = effectiveScore(course);
  const grade = course.final_grade ?? course.current_grade;
  return `<a class="course-row" href="#/course/${course.id}/assignments">
    <div class="course-main"><strong>${escapeHtml(course.name)}</strong><span>${escapeHtml(course.code || `Canvas course ${course.id}`)}</span></div>
    <div data-label="Term">${escapeHtml(course.term)}</div>
    <div data-label="Grade" class="numeric">${grade ? escapeHtml(grade) : value === null || value === undefined ? "Not shown" : `${score(value)}%`}</div>
    <div data-label="Submissions" class="numeric">${course.submission_count}</div>
    <div data-label="Feedback">${escapeHtml(feedbackLabel(course))}</div>
    <div data-label="Status"><span class="data-state ${style}">${label}</span></div>
  </a>`;
}

function courseList(courses) {
  if (!courses.length) return emptyState("No courses found", "Try another term or wait for the export to add more courses.");
  return `<div class="course-list">
    <div class="course-list-head"><span>Course</span><span>Term</span><span>Grade</span><span>Submissions</span><span>Feedback</span><span>Status</span></div>
    ${courses.map(courseRow).join("")}
  </div>`;
}

function renderCourses() {
  const terms = [...new Set(state.archive.courses.map((course) => course.term))];
  if (state.term !== "all" && !terms.includes(state.term)) state.term = "all";
  const courses = sortCourses(state.archive.courses.filter((course) => state.term === "all" || course.term === state.term));
  view.innerHTML = `${pageHeading("Courses", "All accessible courses with their grades, submissions, feedback, and export status.")}
    ${state.archive.complete ? "" : `<div class="notice pending"><strong>Export in progress</strong><span>New course records will appear automatically.</span></div>`}
    <div class="toolbar">
      <div class="term-filters" role="group" aria-label="Filter by term">
        <button class="filter-chip ${state.term === "all" ? "active" : ""}" data-term="all">All terms</button>
        ${terms.map((term) => `<button class="filter-chip ${state.term === term ? "active" : ""}" data-term="${escapeHtml(term)}">${escapeHtml(term)}</button>`).join("")}
      </div>
      <label class="sort-control">Sort <select id="course-sort"><option value="recent">Recent activity</option><option value="term">Newest term</option><option value="name">Course name</option><option value="grade">Highest grade</option></select></label>
    </div>
    ${courseList(courses)}`;
  const select = view.querySelector("#course-sort");
  select.value = state.sort;
  select.addEventListener("change", () => {
    state.sort = select.value;
    savePreferences();
    renderCourses();
  });
  view.querySelectorAll("[data-term]").forEach((button) => button.addEventListener("click", () => {
    state.term = button.dataset.term;
    savePreferences();
    renderCourses();
  }));
}

function feedbackItem(item) {
  const authorLabel = item.author_type === "self" ? "Your reply" : item.author_name || "Instructor or peer";
  return `<article class="feedback-item">
    <div class="feedback-meta"><a href="#/course/${item.course_id}/feedback">${escapeHtml(item.course_name)}</a><span>${date(item.created_at)}</span></div>
    <h3>${escapeHtml(item.assignment_name || "Assignment feedback")}</h3>
    <p>${escapeHtml(item.comment || "No written comment")}</p>
    <small>${escapeHtml(authorLabel)}</small>
  </article>`;
}

function renderFeedback() {
  const received = state.archive.feedback.filter((item) => item.author_type !== "self");
  const replies = state.archive.feedback.filter((item) => item.author_type === "self");
  const pending = !state.archive.complete && !state.archive.feedback.length;
  view.innerHTML = `${pageHeading("Feedback", "Instructor and peer feedback is separated from your own replies.")}
    ${pending ? `<div class="notice pending"><strong>Feedback is still exporting</strong><span>This page will update when comments arrive.</span></div>` : ""}
    <section class="section-block"><div class="section-heading"><h2>Instructor and peer feedback</h2><span>${received.length}</span></div>
      ${received.length ? `<div class="feedback-grid">${received.map(feedbackItem).join("")}</div>` : emptyState("No instructor feedback", state.archive.complete ? "Canvas returned no written comments." : "Comments have not arrived yet.")}
    </section>
    <section class="section-block"><div class="section-heading"><h2>Your replies</h2><span>${replies.length}</span></div>
      ${replies.length ? `<div class="feedback-grid">${replies.map(feedbackItem).join("")}</div>` : emptyState("No replies", "You did not reply in the exported assignment comment threads.")}
    </section>`;
}

function fileTable(files) {
  if (!files.length) return emptyState("No files available", "Files may still be downloading or Canvas did not return any files.");
  return `<div class="table-wrap"><table class="file-table"><thead><tr><th>File</th><th>Type</th><th>Course or source</th><th>Size</th><th></th></tr></thead><tbody>
    ${files.map((file) => `<tr><td><a href="${file.url}" target="_blank" rel="noopener">${escapeHtml(file.display_name || file.name)}</a></td><td>${escapeHtml(file.kind.toUpperCase())}</td><td>${escapeHtml(file.course_name || "Archive")}</td><td>${bytes(file.size)}</td><td><a class="button-link" href="${file.url}" target="_blank" rel="noopener">Open</a></td></tr>`).join("")}
  </tbody></table></div>`;
}

function renderFiles() {
  view.innerHTML = `${pageHeading("Files", "Submitted work, personal files, discussion attachments, and Inbox attachments.")}${fileTable(state.archive.files)}`;
}

async function renderInbox() {
  if (!state.inbox) {
    view.innerHTML = loadingState("Loading Inbox");
    const response = await fetch("/api/inbox");
    if (!response.ok) throw new Error("Could not load Inbox data");
    state.inbox = await response.json();
  }
  view.innerHTML = `${pageHeading("Inbox", "Message threads returned by the Canvas API, including archived conversations when available.")}
    ${state.inbox.length ? `<div class="inbox-list">${state.inbox.map((conversation) => `<details class="conversation">
      <summary><div><strong>${escapeHtml(conversation.subject)}</strong><span>${escapeHtml(conversation.context_name || conversation.participants.join(", "))}</span></div><small>${conversation.messages.length} messages</small></summary>
      <div class="message-thread">${conversation.messages.map((message) => `<article class="message"><header><strong>${escapeHtml(message.author)}</strong><time>${date(message.created_at)}</time></header><p>${escapeHtml(message.body)}</p>${message.attachments.map((attachment) => attachment.url ? `<a class="attachment-link" href="${attachment.url}" target="_blank">${escapeHtml(attachment.name)}</a>` : "").join("")}</article>`).join("")}</div>
    </details>`).join("")}</div>` : emptyState(state.archive.complete ? "No conversations found" : "Inbox export pending", state.archive.complete ? "Canvas did not return any Inbox conversations." : "Inbox messages are exported after course records.")}`;
}

function renderOverview() {
  const limited = state.archive.courses.filter((course) => ["limited", "unavailable"].includes(course.data_state));
  const recent = sortCourses(state.archive.courses).slice(0, 6);
  view.innerHTML = `${pageHeading("Overview", `Archive status for ${state.archive.profile.name}.`)}
    <div class="overview-summary">
      <div><strong>${number(state.archive.totals.courses)}</strong><span>Courses</span></div>
      <div><strong>${number(state.archive.totals.submissions)}</strong><span>Submissions</span></div>
      <div><strong>${number(state.archive.totals.comments)}</strong><span>Comments</span></div>
      <div><strong>${number(state.archive.totals.files)}</strong><span>Files</span></div>
    </div>
    <section class="section-block"><div class="section-heading"><h2>Recently active courses</h2><a href="#/courses">View all</a></div>${courseList(recent)}</section>
    ${limited.length ? `<section class="section-block"><div class="section-heading"><h2>Records needing attention</h2><span>${limited.length}</span></div><div class="notice warning"><strong>Some Canvas data was unavailable</strong><span>Open the affected course to see whether Canvas denied access or the export is incomplete.</span></div>${courseList(limited)}</section>` : ""}`;
}

function assignmentBadges(item) {
  const badges = [];
  if (item.feedback_types.rubric) badges.push('<span class="tag lavender">Rubric</span>');
  if (item.feedback_types.comments) badges.push(`<span class="tag peach">${item.comments.length} comments</span>`);
  if (item.feedback_types.annotation_file) badges.push('<span class="tag mint">Annotated file</span>');
  else if (item.feedback_types.annotation_referenced) badges.push('<span class="tag yellow">Annotation referenced</span>');
  return badges.join("");
}

function assignmentRecord(item) {
  const status = item.excused ? "Excused" : item.missing ? "Missing" : item.late ? "Late" : item.submitted_at ? "Submitted" : "No submission";
  const firstFile = item.attachments.find((attachment) => attachment.url);
  return `<details class="assignment">
    <summary>
      <div class="assignment-title"><strong>${escapeHtml(item.name)}</strong><span>${date(item.due_at)} | ${status}</span><div class="tag-row">${assignmentBadges(item)}</div></div>
      <div class="assignment-grade"><strong>${score(item.score)}</strong><span>of ${score(item.points_possible)}</span></div>
      ${firstFile ? `<a class="quick-file" href="${firstFile.url}" target="_blank" rel="noopener">Open file</a>` : '<span class="quick-file disabled">No file</span>'}
    </summary>
    <div class="assignment-body">
      ${item.description ? `<p>${escapeHtml(item.description)}</p>` : ""}
      ${item.body ? `<section><h4>Text submission</h4><p>${escapeHtml(item.body)}</p></section>` : ""}
      ${item.attachments.length ? `<section><h4>Submitted files</h4>${item.attachments.map((attachment) => attachment.url ? `<a class="attachment-link" href="${attachment.url}" target="_blank" rel="noopener">${escapeHtml(attachment.name)}</a>` : `<span class="attachment-link disabled">${escapeHtml(attachment.name)} unavailable</span>`).join("")}</section>` : ""}
      ${item.comments.length ? `<section><h4>Comments</h4>${item.comments.map((comment) => `<div class="comment"><div><strong>${escapeHtml(comment.author_type === "self" ? "You" : comment.author || "Instructor or peer")}</strong><span>${date(comment.created_at)}</span></div><p>${escapeHtml(comment.text)}</p></div>`).join("")}</section>` : ""}
    </div>
  </details>`;
}

function rubricRows(rows) {
  return rows.map((row) => `<div class="rubric-row"><strong>${escapeHtml(row.description || "Criterion")}</strong><span>${score(row.points)} of ${score(row.points_possible)}</span><p>${escapeHtml(row.comments || row.long_description || "No written note")}</p></div>`).join("");
}

function courseFeedback(assignments, complete) {
  const items = assignments.filter((item) => item.feedback_types.comments || item.feedback_types.rubric || item.feedback_types.annotation_file || item.feedback_types.annotation_referenced);
  if (!items.length) return emptyState(complete ? "No feedback found" : "Feedback is still exporting", complete ? "Canvas returned no comments, rubric results, or annotation files for this course." : "Refresh after the export reaches this course.");
  return `<div class="course-feedback-list">${items.map((item) => {
    const received = item.comments.filter((comment) => comment.author_type !== "self");
    const replies = item.comments.filter((comment) => comment.author_type === "self");
    return `<section class="feedback-record"><div class="feedback-record-head"><div><h3>${escapeHtml(item.name)}</h3><div class="tag-row">${assignmentBadges(item)}</div></div><div class="assignment-grade"><strong>${score(item.score)}</strong><span>of ${score(item.points_possible)}</span></div></div>
      ${received.length ? `<div class="feedback-group"><h4>Instructor and peer feedback</h4>${received.map((comment) => `<div class="comment"><div><strong>${escapeHtml(comment.author || "Instructor or peer")}</strong><span>${date(comment.created_at)}</span></div><p>${escapeHtml(comment.text)}</p></div>`).join("")}</div>` : ""}
      ${replies.length ? `<div class="feedback-group"><h4>Your replies</h4>${replies.map((comment) => `<div class="comment self"><div><strong>You</strong><span>${date(comment.created_at)}</span></div><p>${escapeHtml(comment.text)}</p></div>`).join("")}</div>` : ""}
      ${item.feedback_types.rubric ? `<div class="feedback-group"><h4>Rubric</h4>${rubricRows(item.rubric)}</div>` : ""}
      ${item.feedback_types.annotation_file ? `<div class="notice success"><strong>Annotated file available</strong><span>Open the marked file from the Files tab.</span></div>` : item.feedback_types.annotation_referenced ? `<div class="notice pending"><strong>Annotation referenced</strong><span>The comment mentions annotations, but no annotated PDF was present in the export.</span></div>` : ""}
    </section>`;
  }).join("")}</div>`;
}

function courseAvailability(summary) {
  if (summary.data_state === "ready") return "";
  if (summary.data_state === "exporting") return `<div class="notice pending"><strong>Course still exporting</strong><span>Some assignments, comments, or files may not be available yet.</span></div>`;
  if (summary.data_state === "limited") return `<div class="notice warning"><strong>Canvas access limited</strong><span>Canvas refused one or more records for this course. This is different from an empty result.</span></div>`;
  return `<div class="notice warning"><strong>Course data unavailable</strong><span>The export finished without a complete assignment record for this course.</span></div>`;
}

async function renderCourse(courseId, tab = "assignments") {
  if (!state.course || String(state.course.summary.id) !== String(courseId)) {
    view.innerHTML = loadingState("Loading course");
    const response = await fetch(`/api/course/${encodeURIComponent(courseId)}`);
    if (!response.ok) throw new Error("This course is not available in the archive yet.");
    state.course = await response.json();
  }
  const { summary, assignments, files } = state.course;
  const activeTab = ["assignments", "feedback", "files"].includes(tab) ? tab : "assignments";
  let content;
  if (activeTab === "feedback") content = courseFeedback(assignments, state.archive.complete);
  else if (activeTab === "files") content = fileTable(files);
  else content = assignments.length ? `<div class="assignment-list">${assignments.map(assignmentRecord).join("")}</div>` : emptyState(summary.data_state === "exporting" ? "Assignments are still exporting" : "No assignments found", summary.data_state === "exporting" ? "This view will update automatically." : "Canvas returned no assignment records for this course.");

  const value = effectiveScore(summary);
  view.innerHTML = `<a class="back-link" href="#/courses">Back to courses</a>
    <section class="course-header"><div><span>${escapeHtml(summary.term)}</span><h1>${escapeHtml(summary.name)}</h1><p>${escapeHtml(summary.code || `Canvas course ${summary.id}`)}</p></div><div class="course-total"><strong>${value === null || value === undefined ? "Not shown" : `${score(value)}%`}</strong><span>Recorded total</span></div></section>
    ${courseAvailability(summary)}
    <nav class="course-tabs" aria-label="Course record sections">
      <a class="${activeTab === "assignments" ? "active" : ""}" href="#/course/${summary.id}/assignments">Assignments <span>${assignments.length}</span></a>
      <a class="${activeTab === "feedback" ? "active" : ""}" href="#/course/${summary.id}/feedback">Feedback <span>${summary.comment_count}</span></a>
      <a class="${activeTab === "files" ? "active" : ""}" href="#/course/${summary.id}/files">Files <span>${files.length}</span></a>
    </nav>
    <div class="course-content">${content}</div>`;
  view.querySelectorAll(".quick-file:not(.disabled)").forEach((link) => link.addEventListener("click", (event) => event.stopPropagation()));
}

function resultSection(title, items, renderer) {
  if (!items.length) return "";
  return `<section class="search-group"><div class="section-heading"><h2>${escapeHtml(title)}</h2><span>${items.length}</span></div><div class="search-result-list">${items.map(renderer).join("")}</div></section>`;
}

async function renderSearch() {
  if (state.query.trim().length < 2) {
    view.innerHTML = `${pageHeading("Search", "Enter at least two characters to search the complete archive.")}${emptyState("Start typing", "Search covers courses, assignments, feedback, files, and Inbox messages.")}`;
    return;
  }
  view.innerHTML = loadingState("Searching archive");
  const response = await fetch(`/api/search?q=${encodeURIComponent(state.query)}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Search could not be completed.");
  state.searchResults = await response.json();
  const groups = state.searchResults.groups;
  view.innerHTML = `${pageHeading(`Results for “${state.query}”`, `${state.searchResults.total} matches across the archive.`)}
    ${state.searchResults.total ? [
      resultSection("Courses", groups.courses, courseRow),
      resultSection("Assignments", groups.assignments, (item) => `<a class="search-result" href="#/course/${item.course_id}/assignments"><div><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.course_name)} | Due ${date(item.due_at)}</span></div><small>${score(item.score)} of ${score(item.points_possible)}</small></a>`),
      resultSection("Feedback", groups.feedback, (item) => `<a class="search-result" href="#/course/${item.course_id}/feedback"><div><strong>${escapeHtml(item.assignment_name)}</strong><span>${escapeHtml(item.course_name)} | ${escapeHtml(item.author_name || "Canvas user")}</span><p>${escapeHtml(item.comment)}</p></div></a>`),
      resultSection("Files", groups.files, (item) => `<a class="search-result" href="${item.url}" target="_blank" rel="noopener"><div><strong>${escapeHtml(item.display_name || item.name)}</strong><span>${escapeHtml(item.course_name || "Archive")} | ${bytes(item.size)}</span></div><small>Open</small></a>`),
      resultSection("Messages", groups.messages, (item) => `<a class="search-result" href="#/inbox"><div><strong>${escapeHtml(item.subject)}</strong><span>${escapeHtml(item.context_name || "Canvas Inbox")}</span><p>${escapeHtml(item.snippet || "Matching conversation")}</p></div></a>`),
    ].join("") : emptyState("No results", "Try a course name, assignment title, instructor, filename, or phrase from a comment.")}`;
}

async function render() {
  if (!state.archive) return;
  setChrome();
  const route = currentRoute();
  try {
    if (route.name === "overview") renderOverview();
    else if (route.name === "feedback") renderFeedback();
    else if (route.name === "files") renderFiles();
    else if (route.name === "inbox") await renderInbox();
    else if (route.name === "search") await renderSearch();
    else if (route.name === "course" && route.id) await renderCourse(route.id, route.tab);
    else renderCourses();
  } catch (error) {
    view.innerHTML = `<div class="error-panel"><h2>View unavailable</h2><p>${escapeHtml(error.message)}</p><button type="button" id="retry-button">Try again</button></div>`;
    view.querySelector("#retry-button")?.addEventListener("click", () => loadArchive(true));
  }
}

async function loadArchive(showLoading = true) {
  if (showLoading) view.innerHTML = loadingState();
  try {
    const response = await fetch("/api/archive", { cache: "no-store" });
    if (!response.ok) throw new Error("The archive server did not return data.");
    state.archive = await response.json();
    state.course = null;
    state.inbox = null;
    state.searchResults = null;
    await render();
  } catch (error) {
    view.innerHTML = `<div class="error-panel"><h2>Could not read the archive</h2><p>${escapeHtml(error.message)}</p><button type="button" id="retry-button">Try again</button></div>`;
    view.querySelector("#retry-button")?.addEventListener("click", () => loadArchive(true));
  }
}

window.addEventListener("hashchange", () => {
  const route = currentRoute();
  if (route.name !== "search") {
    state.query = "";
    search.value = "";
    savePreferences();
  }
  if (route.name !== "course") state.course = null;
  render();
});

search.addEventListener("input", () => {
  state.query = search.value.trim();
  savePreferences();
  window.clearTimeout(searchTimer);
  searchTimer = window.setTimeout(() => {
    if (state.query.length >= 2) {
      state.searchResults = null;
      if (currentRoute().name !== "search") location.hash = "#/search";
      else renderSearch();
    } else if (currentRoute().name === "search") {
      renderSearch();
    }
  }, 300);
});

document.addEventListener("keydown", (event) => {
  if (event.key === "/" && document.activeElement !== search) {
    event.preventDefault();
    search.focus();
  }
});

densityButton.addEventListener("click", () => {
  state.density = state.density === "compact" ? "comfortable" : "compact";
  applyDensity();
  savePreferences();
});

refreshButton.addEventListener("click", () => loadArchive(false));

applyDensity();
if (currentRoute().name === "search" && preferences.query) {
  state.query = preferences.query;
  search.value = preferences.query;
}
loadArchive();
setInterval(() => {
  if (state.archive && !state.archive.complete) loadArchive(false);
}, 12000);
