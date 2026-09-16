#!/usr/bin/env python3
"""Export the Canvas data visible to the authenticated user."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable


USER_AGENT = "canvas-personal-export/1.0"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class CanvasError(RuntimeError):
    pass


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not send a Canvas bearer token to a cross-host download URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old_host = urllib.parse.urlsplit(req.full_url).netloc
        new_host = urllib.parse.urlsplit(newurl).netloc
        if old_host.lower() != new_host.lower():
            redirected.remove_header("Authorization")
        return redirected


class CanvasAPI:
    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.base_host = urllib.parse.urlsplit(self.base_url).netloc.lower()
        self.token = token
        self.errors: list[dict[str, Any]] = []
        self.opener = urllib.request.build_opener(SafeRedirectHandler())

    def _request(self, url: str) -> tuple[Any, Any]:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if urllib.parse.urlsplit(url).netloc.lower() == self.base_host:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(
            url,
            headers=headers,
        )
        for attempt in range(6):
            try:
                response = self.opener.open(request, timeout=60)
                raw = response.read()
                return json.loads(raw.decode("utf-8")), response.headers
            except urllib.error.HTTPError as exc:
                if exc.code in RETRY_STATUSES and attempt < 5:
                    delay = int(exc.headers.get("Retry-After", min(2**attempt, 30)))
                    time.sleep(delay)
                    continue
                detail = exc.read(2000).decode("utf-8", errors="replace")
                raise CanvasError(f"HTTP {exc.code} for {url}: {detail}") from exc
            except urllib.error.URLError as exc:
                if attempt < 5:
                    time.sleep(min(2**attempt, 30))
                    continue
                raise CanvasError(f"Network error for {url}: {exc.reason}") from exc
        raise CanvasError(f"Request failed after retries: {url}")

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        optional: bool = False,
        paginate: bool = True,
        label: str | None = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}/api/v1{path}"
        if params:
            separator = "&" if "?" in url else "?"
            url += separator + urllib.parse.urlencode(params, doseq=True)

        try:
            data, headers = self._request(url)
            if not paginate or not isinstance(data, list):
                return data

            results = list(data)
            next_url = parse_next_link(headers.get("Link", ""))
            while next_url:
                page, headers = self._request(next_url)
                if not isinstance(page, list):
                    raise CanvasError(f"Expected a list while paginating {url}")
                results.extend(page)
                next_url = parse_next_link(headers.get("Link", ""))
            return results
        except CanvasError as exc:
            if not optional:
                raise
            item = {"label": label or path, "error": str(exc)}
            self.errors.append(item)
            print(f"  skipped {item['label']}: {short_error(str(exc))}", file=sys.stderr)
            return None

    def download(self, url: str, destination: Path, *, label: str) -> bool:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        headers = {"User-Agent": USER_AGENT}
        if urllib.parse.urlsplit(url).netloc.lower() == self.base_host:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=120) as response, temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            temporary.replace(destination)
            return True
        except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
            temporary.unlink(missing_ok=True)
            self.errors.append({"label": label, "error": str(exc)})
            print(f"  skipped {label}: {short_error(str(exc))}", file=sys.stderr)
            return False


def parse_next_link(link_header: str) -> str | None:
    for part in link_header.split(","):
        match = re.match(r'\s*<([^>]+)>;\s*rel="?([^";]+)"?', part)
        if match and match.group(2) == "next":
            return match.group(1)
    return None


def short_error(message: str) -> str:
    first_line = message.splitlines()[0]
    return first_line[:240] + ("..." if len(first_line) > 240 else "")


def safe_name(value: str, fallback: str = "item") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", value).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or fallback


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def unique_by_id(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[Any, dict[str, Any]] = {}
    for item in items:
        key = item.get("id")
        if key is not None:
            unique[key] = item
    return list(unique.values())


def find_downloads(value: Any) -> Iterable[tuple[str, str, str]]:
    if isinstance(value, dict):
        url = value.get("url")
        filename = value.get("filename") or value.get("display_name")
        if isinstance(url, str) and url.startswith("http") and isinstance(filename, str):
            file_id = str(value.get("id") or "file")
            yield url, filename, file_id
        for child in value.values():
            yield from find_downloads(child)
    elif isinstance(value, list):
        for child in value:
            yield from find_downloads(child)


def download_payload_files(api: CanvasAPI, payload: Any, destination: Path) -> int:
    seen: set[str] = set()
    downloaded = 0
    for url, filename, file_id in find_downloads(payload):
        if url in seen:
            continue
        seen.add(url)
        target = destination / f"{safe_name(file_id)}-{safe_name(filename, 'file')}"
        if target.exists() or api.download(url, target, label=f"file {filename}"):
            downloaded += 1
    return downloaded


def extract_own_discussion_entries(payload: Any, user_id: int) -> list[dict[str, Any]]:
    entries: dict[Any, dict[str, Any]] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("user_id") == user_id and "id" in value and "message" in value:
                entries[value["id"]] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return list(entries.values())


def export_conversations(api: CanvasAPI, root: Path) -> list[dict[str, Any]]:
    print("Exporting Inbox conversations...")
    regular = api.get("/conversations", optional=True, label="Inbox conversations") or []
    archived = api.get(
        "/conversations",
        {"scope": "archived"},
        optional=True,
        label="archived Inbox conversations",
    ) or []
    summaries = unique_by_id([*regular, *archived])
    details: list[dict[str, Any]] = []
    for index, conversation in enumerate(summaries, start=1):
        conversation_id = conversation.get("id")
        print(f"  conversation {index}/{len(summaries)}", end="\r", flush=True)
        detail = api.get(
            f"/conversations/{conversation_id}",
            {"auto_mark_as_read": "false"},
            optional=True,
            paginate=False,
            label=f"conversation {conversation_id}",
        )
        if detail:
            details.append(detail)
    if summaries:
        print(" " * 60, end="\r")
    write_json(root / "inbox" / "conversation-index.json", summaries)
    write_json(root / "inbox" / "conversations.json", details)
    download_payload_files(api, details, root / "inbox" / "attachments")
    return details


def export_quizzes(api: CanvasAPI, course_id: int, course_dir: Path, user_id: int) -> None:
    quizzes = api.get(
        f"/courses/{course_id}/quizzes",
        optional=True,
        label=f"course {course_id} classic quizzes",
    )
    if quizzes is None:
        return
    write_json(course_dir / "quizzes.json", quizzes)
    attempts: list[dict[str, Any]] = []
    questions: dict[str, Any] = {}
    for quiz in quizzes:
        quiz_id = quiz.get("id")
        response = api.get(
            f"/courses/{course_id}/quizzes/{quiz_id}/submissions",
            optional=True,
            paginate=False,
            label=f"quiz {quiz_id} submissions",
        )
        if not response:
            continue
        submissions = response.get("quiz_submissions", []) if isinstance(response, dict) else response
        for submission in submissions:
            if submission.get("user_id") not in (None, user_id):
                continue
            attempts.append(submission)
            submission_id = submission.get("id")
            question_data = api.get(
                f"/quiz_submissions/{submission_id}/questions",
                optional=True,
                paginate=False,
                label=f"quiz submission {submission_id} answers",
            )
            if question_data is not None:
                questions[str(submission_id)] = question_data
    write_json(course_dir / "quiz-submissions.json", attempts)
    write_json(course_dir / "quiz-answers.json", questions)


def export_discussions(api: CanvasAPI, course_id: int, course_dir: Path, user_id: int) -> None:
    topics = api.get(
        f"/courses/{course_id}/discussion_topics",
        optional=True,
        label=f"course {course_id} discussions",
    )
    if topics is None:
        return
    write_json(course_dir / "discussion-topics.json", topics)
    own_entries: list[dict[str, Any]] = []
    for topic in topics:
        topic_id = topic.get("id")
        view = api.get(
            f"/courses/{course_id}/discussion_topics/{topic_id}/view",
            optional=True,
            paginate=False,
            label=f"discussion {topic_id}",
        )
        if view is None:
            continue
        for entry in extract_own_discussion_entries(view, user_id):
            own_entries.append(
                {
                    "topic_id": topic_id,
                    "topic_title": topic.get("title"),
                    "entry": entry,
                }
            )
    write_json(course_dir / "my-discussion-posts.json", own_entries)
    download_payload_files(api, own_entries, course_dir / "discussion-attachments")


def submission_rows(
    submissions: list[dict[str, Any]], course_id: int, course_name: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    grades: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    for submission in submissions:
        assignment = submission.get("assignment") or {}
        assignment_id = submission.get("assignment_id") or assignment.get("id")
        assignment_name = assignment.get("name") or f"Assignment {assignment_id}"
        submission_comments = submission.get("submission_comments") or []
        grades.append(
            {
                "course_id": course_id,
                "course_name": course_name,
                "assignment_id": assignment_id,
                "assignment_name": assignment_name,
                "due_at": assignment.get("due_at"),
                "points_possible": assignment.get("points_possible"),
                "score": submission.get("score"),
                "grade": submission.get("grade"),
                "graded_at": submission.get("graded_at"),
                "submitted_at": submission.get("submitted_at"),
                "workflow_state": submission.get("workflow_state"),
                "attempt": submission.get("attempt"),
                "late": submission.get("late"),
                "missing": submission.get("missing"),
                "excused": submission.get("excused"),
                "comment_count": len(submission_comments),
            }
        )
        for comment in submission_comments:
            comments.append(
                {
                    "course_id": course_id,
                    "course_name": course_name,
                    "assignment_id": assignment_id,
                    "assignment_name": assignment_name,
                    "comment_id": comment.get("id"),
                    "author_name": comment.get("author_name")
                    or (comment.get("author") or {}).get("display_name"),
                    "created_at": comment.get("created_at"),
                    "comment": comment.get("comment"),
                }
            )
    return grades, comments


def export_course(
    api: CanvasAPI,
    root: Path,
    course_id: int,
    fallback_course: dict[str, Any],
    user_id: int,
    *,
    include_files: bool,
    include_discussions: bool,
    include_quizzes: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    course = api.get(
        f"/courses/{course_id}",
        {
            "include[]": [
                "term",
                "total_scores",
                "current_grading_period_scores",
                "syllabus_body",
                "course_progress",
            ]
        },
        optional=True,
        paginate=False,
        label=f"course {course_id} details",
    ) or fallback_course
    course_name = course.get("name") or course.get("course_code") or f"course-{course_id}"
    course_dir = root / "courses" / f"{course_id}-{safe_name(course_name)}"
    course_dir.mkdir(parents=True, exist_ok=True)
    write_json(course_dir / "course.json", course)

    assignments = api.get(
        f"/courses/{course_id}/assignments",
        {"include[]": ["submission", "rubric"], "order_by": "position"},
        optional=True,
        label=f"course {course_id} assignments",
    ) or []
    write_json(course_dir / "assignments.json", assignments)

    submissions = api.get(
        f"/courses/{course_id}/students/submissions",
        {
            "student_ids[]": [user_id],
            "include[]": [
                "submission_history",
                "submission_comments",
                "submission_html_comments",
                "rubric_assessment",
                "assignment",
                "course",
                "user",
                "sub_assignment_submissions",
                "peer_review_submissions",
                "student_entered_score",
            ],
        },
        optional=True,
        label=f"course {course_id} submissions and comments",
    ) or []
    write_json(course_dir / "submissions.json", submissions)

    grades, comments = submission_rows(submissions, course_id, course_name)
    write_csv(course_dir / "grades.csv", grades, GRADE_FIELDS)
    write_csv(course_dir / "comments.csv", comments, COMMENT_FIELDS)
    if include_files:
        download_payload_files(api, submissions, course_dir / "submission-files")
    if include_discussions:
        export_discussions(api, course_id, course_dir, user_id)
    if include_quizzes:
        export_quizzes(api, course_id, course_dir, user_id)
    return grades, comments


GRADE_FIELDS = [
    "course_id",
    "course_name",
    "assignment_id",
    "assignment_name",
    "due_at",
    "points_possible",
    "score",
    "grade",
    "graded_at",
    "submitted_at",
    "workflow_state",
    "attempt",
    "late",
    "missing",
    "excused",
    "comment_count",
]

COMMENT_FIELDS = [
    "course_id",
    "course_name",
    "assignment_id",
    "assignment_name",
    "comment_id",
    "author_name",
    "created_at",
    "comment",
]


def parse_args() -> argparse.Namespace:
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser(
        description="Export the Canvas data visible to your account.",
    )
    parser.add_argument("--base-url", default="https://canvas.stanford.edu")
    parser.add_argument("--output", type=Path, default=Path(f"canvas-export-{timestamp}"))
    parser.add_argument(
        "--course-id",
        action="append",
        type=int,
        help="export only this course ID; may be repeated",
    )
    parser.add_argument("--no-files", action="store_true", help="do not download attachments")
    parser.add_argument("--no-messages", action="store_true", help="do not export Canvas Inbox")
    parser.add_argument("--no-discussions", action="store_true", help="do not export your discussion posts")
    parser.add_argument("--no-quizzes", action="store_true", help="do not attempt classic quiz exports")
    return parser.parse_args()


def get_token() -> str:
    token = os.environ.get("CANVAS_ACCESS_TOKEN", "").strip()
    if token:
        return token
    if not sys.stdin.isatty():
        raise CanvasError("Set CANVAS_ACCESS_TOKEN when running non-interactively.")
    token = getpass.getpass("Canvas access token (input hidden): ").strip()
    if not token:
        raise CanvasError("No Canvas access token was provided.")
    return token


def main() -> int:
    args = parse_args()
    try:
        token = get_token()
        api = CanvasAPI(args.base_url, token)
        print(f"Authenticating with {api.base_url}...")
        profile = api.get("/users/self/profile", paginate=False)
        user_id = profile["id"]
        print(f"Authenticated as {profile.get('name') or profile.get('login_id') or user_id}")

        root = args.output.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / "account" / "profile.json", profile)
        settings = api.get("/users/self/settings", optional=True, paginate=False, label="user settings")
        write_json(root / "account" / "settings.json", settings)

        enrollments = api.get(
            "/users/self/enrollments",
            {
                "state[]": ["active", "invited", "creation_pending", "completed", "inactive"],
                "include[]": ["current_points", "uuid"],
            },
            optional=True,
            label="course enrollments and totals",
        ) or []
        write_json(root / "account" / "enrollments.json", enrollments)

        active_courses = api.get(
            "/courses",
            {
                "include[]": [
                    "term",
                    "total_scores",
                    "current_grading_period_scores",
                    "syllabus_body",
                    "course_progress",
                ]
            },
            optional=True,
            label="active courses",
        ) or []
        write_json(root / "account" / "active-courses.json", active_courses)

        course_map = {course["id"]: course for course in active_courses if course.get("id") is not None}
        for enrollment in enrollments:
            course_id = enrollment.get("course_id")
            if course_id is not None:
                course_map.setdefault(course_id, {"id": course_id, "enrollments": [enrollment]})
        course_ids = sorted(course_map)
        if args.course_id:
            selected = set(args.course_id)
            course_ids = [course_id for course_id in course_ids if course_id in selected]
            for course_id in selected:
                course_map.setdefault(course_id, {"id": course_id})
            course_ids = sorted(selected)

        print(f"Found {len(course_ids)} course(s).")
        all_grades: list[dict[str, Any]] = []
        all_comments: list[dict[str, Any]] = []
        for index, course_id in enumerate(course_ids, start=1):
            print(f"Exporting course {index}/{len(course_ids)}: {course_id}")
            grades, comments = export_course(
                api,
                root,
                course_id,
                course_map[course_id],
                user_id,
                include_files=not args.no_files,
                include_discussions=not args.no_discussions,
                include_quizzes=not args.no_quizzes,
            )
            all_grades.extend(grades)
            all_comments.extend(comments)

        write_csv(root / "all-grades.csv", all_grades, GRADE_FIELDS)
        write_csv(root / "all-comments.csv", all_comments, COMMENT_FIELDS)

        if not args.no_messages:
            export_conversations(api, root)

        activity = api.get(
            "/users/self/activity_stream",
            {"only_active_courses": "false"},
            optional=True,
            label="account activity stream",
        )
        write_json(root / "account" / "activity-stream.json", activity)

        personal_files = api.get(
            "/users/self/files",
            optional=True,
            label="personal files",
        ) or []
        folders = api.get(
            "/users/self/folders",
            optional=True,
            label="personal file folders",
        ) or []
        write_json(root / "account" / "files.json", personal_files)
        write_json(root / "account" / "folders.json", folders)
        if not args.no_files:
            print(f"Downloading {len(personal_files)} personal file(s)...")
            download_payload_files(api, personal_files, root / "personal-files")

        finished_at = dt.datetime.now(dt.timezone.utc).isoformat()
        manifest = {
            "base_url": api.base_url,
            "exported_at": finished_at,
            "user_id": user_id,
            "course_count": len(course_ids),
            "grade_row_count": len(all_grades),
            "comment_row_count": len(all_comments),
            "errors": api.errors,
            "limitations": [
                "The archive contains only data exposed to this account by the Canvas API.",
                "New Quizzes, external tools, and DocViewer annotations may require separate manual downloads.",
                "Deleted data and courses blocked by institutional retention settings cannot be recovered.",
            ],
        }
        write_json(root / "manifest.json", manifest)
        print(f"Export complete: {root}")
        print(f"Grades: {len(all_grades)}; comments: {len(all_comments)}; skipped items: {len(api.errors)}")
        return 0
    except (CanvasError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
