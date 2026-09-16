#!/usr/bin/env python3
"""Local, read-only browser for Canvas personal exports."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import mimetypes
import re
import shutil
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parent
WEB_ROOT = APP_ROOT / "web"
ASSET_DIRECTORIES = {"submission-files", "discussion-attachments", "personal-files", "attachments"}


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError):
        return default


def read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as source:
            return list(csv.DictReader(source))
    except (OSError, csv.Error):
        return []


def as_number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def plain_text(value: Any) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def course_id_from_dir(path: Path) -> int | None:
    match = re.match(r"(\d+)-", path.name)
    return int(match.group(1)) if match else None


def iso_timestamp(timestamp: float) -> str:
    return dt.datetime.fromtimestamp(timestamp, tz=dt.timezone.utc).isoformat()


def latest_export() -> Path | None:
    candidates = [path for path in APP_ROOT.glob("canvas-export-*") if path.is_dir()]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def find_course_dir(root: Path, course_id: int) -> Path | None:
    courses_root = root / "courses"
    for path in courses_root.glob(f"{course_id}-*"):
        if path.is_dir():
            return path
    return None


def asset_url(root: Path, path: Path) -> str:
    relative = path.relative_to(root).as_posix()
    return "/files/" + urllib.parse.quote(relative, safe="/")


def file_record(root: Path, path: Path, course_name: str | None = None) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "display_name": re.sub(r"^\d+-", "", path.name),
        "size": stat.st_size,
        "modified_at": iso_timestamp(stat.st_mtime),
        "kind": path.suffix.lower().lstrip(".") or "file",
        "course_name": course_name,
        "url": asset_url(root, path),
    }


def list_assets(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    courses_root = root / "courses"
    if courses_root.exists():
        for course_dir in courses_root.iterdir():
            if not course_dir.is_dir():
                continue
            course = read_json(course_dir / "course.json", {})
            course_name = course.get("name") or course_dir.name.partition("-")[2]
            for asset_dir_name in ("submission-files", "discussion-attachments"):
                asset_dir = course_dir / asset_dir_name
                if asset_dir.exists():
                    for path in asset_dir.rglob("*"):
                        if path.is_file() and not path.name.endswith(".part"):
                            results.append(file_record(root, path, course_name))
    for base, label in ((root / "personal-files", "Personal files"), (root / "inbox" / "attachments", "Inbox")):
        if base.exists():
            for path in base.rglob("*"):
                if path.is_file() and not path.name.endswith(".part"):
                    results.append(file_record(root, path, label))
    return sorted(results, key=lambda item: item["modified_at"], reverse=True)


def enrollment_map(root: Path) -> dict[int, dict[str, Any]]:
    enrollments = read_json(root / "account" / "enrollments.json", [])
    result: dict[int, dict[str, Any]] = {}
    for enrollment in enrollments:
        course_id = enrollment.get("course_id")
        if course_id is not None:
            result[int(course_id)] = enrollment
    return result


def course_summary(
    root: Path,
    course_dir: Path,
    enrollments: dict[int, dict[str, Any]],
    *,
    export_complete: bool = False,
    export_errors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    course_id = course_id_from_dir(course_dir)
    course = read_json(course_dir / "course.json", {})
    submissions = read_json(course_dir / "submissions.json", [])
    assignments = read_json(course_dir / "assignments.json", [])
    comments = read_csv(course_dir / "comments.csv")
    posts = read_json(course_dir / "my-discussion-posts.json", [])
    quiz_submissions = read_json(course_dir / "quiz-submissions.json", [])
    enrollment = enrollments.get(course_id or -1, {})
    grades = enrollment.get("grades") or {}

    graded = [item for item in submissions if item.get("score") is not None]
    earned = sum(as_number(item.get("score")) or 0 for item in graded)
    possible = sum(as_number((item.get("assignment") or {}).get("points_possible")) or 0 for item in graded)
    dates = [
        item.get("graded_at") or item.get("submitted_at")
        for item in submissions
        if item.get("graded_at") or item.get("submitted_at")
    ]
    term = course.get("term") or {}
    name = course.get("name") or course_dir.name.partition("-")[2].replace("_", " ")
    local_files = []
    for asset_dir_name in ("submission-files", "discussion-attachments"):
        asset_dir = course_dir / asset_dir_name
        if asset_dir.exists():
            local_files.extend(path for path in asset_dir.rglob("*") if path.is_file())

    course_errors = [
        item for item in (export_errors or [])
        if str(course_id) in f"{item.get('label', '')} {item.get('error', '')}"
    ]
    core_error_labels = (
        f"course {course_id} details",
        f"course {course_id} assignments",
        f"course {course_id} submissions and comments",
    )
    core_errors = [
        item for item in course_errors
        if any(label in str(item.get("label") or "").lower() for label in core_error_labels)
    ]
    core_ready = (course_dir / "assignments.json").exists() and (course_dir / "submissions.json").exists()
    if core_errors:
        data_state = "limited"
    elif core_ready:
        data_state = "ready"
    elif export_complete:
        data_state = "unavailable"
    else:
        data_state = "exporting"

    comments_file_exists = (course_dir / "comments.csv").exists()
    if comments:
        comments_state = "ready"
    elif comments_file_exists:
        comments_state = "empty"
    elif export_complete:
        comments_state = "unavailable"
    else:
        comments_state = "exporting"

    annotation_files = [
        path for path in local_files
        if "annotat" in path.name.lower() or "marked" in path.name.lower()
    ]
    annotation_referenced = any(
        "annotat" in str(comment.get("comment") or "").lower()
        for submission in submissions
        for comment in submission.get("submission_comments") or []
    )

    return {
        "id": course_id,
        "name": name,
        "code": course.get("course_code"),
        "term": term.get("name") or "Term unavailable",
        "term_start": term.get("start_at") or course.get("start_at"),
        "term_end": term.get("end_at") or course.get("end_at"),
        "workflow_state": course.get("workflow_state"),
        "enrollment_state": enrollment.get("enrollment_state"),
        "current_score": grades.get("current_score"),
        "current_grade": grades.get("current_grade"),
        "final_score": grades.get("final_score"),
        "final_grade": grades.get("final_grade"),
        "assignment_count": len(assignments),
        "submission_count": len(submissions),
        "graded_count": len(graded),
        "comment_count": len(comments),
        "discussion_count": len(posts),
        "quiz_attempt_count": len(quiz_submissions),
        "file_count": len(local_files),
        "annotation_file_count": len(annotation_files),
        "annotation_referenced": annotation_referenced,
        "points_earned": round(earned, 2),
        "points_possible_graded": round(possible, 2),
        "latest_activity": max(dates) if dates else None,
        "data_state": data_state,
        "comments_state": comments_state,
        "access_errors": [item.get("label") for item in core_errors],
        "supplemental_error_count": len(course_errors) - len(core_errors),
    }


class ArchiveModel:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._snapshot_cache: tuple[float, dict[str, Any]] | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            if self._snapshot_cache and now - self._snapshot_cache[0] < 2:
                return self._snapshot_cache[1]

            profile = read_json(self.root / "account" / "profile.json", {})
            manifest_path = self.root / "manifest.json"
            manifest = read_json(manifest_path, {})
            export_errors = manifest.get("errors", [])
            enrollments = enrollment_map(self.root)
            courses_root = self.root / "courses"
            course_dirs = sorted(
                (path for path in courses_root.iterdir() if path.is_dir()),
                key=lambda path: path.name.lower(),
            ) if courses_root.exists() else []
            course_by_dir = {
                path: course_summary(
                    self.root,
                    path,
                    enrollments,
                    export_complete=manifest_path.exists(),
                    export_errors=export_errors,
                )
                for path in course_dirs
            }
            courses = list(course_by_dir.values())
            courses.sort(key=lambda item: item.get("term_start") or "", reverse=True)

            feedback: list[dict[str, Any]] = []
            profile_names = {
                str(profile.get("name") or "").casefold(),
                str(profile.get("short_name") or "").casefold(),
            } - {""}
            for course_dir, course in course_by_dir.items():
                for row in read_csv(course_dir / "comments.csv"):
                    is_self = str(row.get("author_name") or "").casefold() in profile_names
                    feedback.append(
                        {
                            "course_id": course["id"],
                            "course_name": row.get("course_name") or course["name"],
                            "assignment_id": row.get("assignment_id"),
                            "assignment_name": row.get("assignment_name"),
                            "author_name": row.get("author_name"),
                            "author_type": "self" if is_self else "other",
                            "created_at": row.get("created_at"),
                            "comment": row.get("comment"),
                        }
                    )
            feedback.sort(key=lambda item: item.get("created_at") or "", reverse=True)
            files = list_assets(self.root)
            inbox = read_json(self.root / "inbox" / "conversation-index.json", [])

            latest_mtime = self.root.stat().st_mtime
            for path in (self.root / "account", self.root / "courses", self.root / "inbox"):
                if path.exists():
                    latest_mtime = max(latest_mtime, path.stat().st_mtime)
            result = {
                "archive_name": self.root.name,
                "complete": manifest_path.exists(),
                "updated_at": iso_timestamp(latest_mtime),
                "profile": {
                    "name": profile.get("name") or profile.get("short_name") or "Canvas user",
                    "short_name": profile.get("short_name"),
                    "time_zone": profile.get("time_zone"),
                },
                "courses": courses,
                "feedback": feedback,
                "files": files,
                "inbox": [
                    {
                        "id": item.get("id"),
                        "subject": item.get("subject") or "No subject",
                        "context_name": item.get("context_name"),
                        "last_message": item.get("last_message"),
                        "last_message_at": item.get("last_message_at"),
                        "message_count": item.get("message_count") or 0,
                        "participants": [participant.get("name") for participant in item.get("participants", [])],
                    }
                    for item in inbox
                ],
                "totals": {
                    "courses": len(courses),
                    "assignments": sum(item["assignment_count"] for item in courses),
                    "submissions": sum(item["submission_count"] for item in courses),
                    "comments": len(feedback),
                    "files": len(files),
                    "conversations": len(inbox),
                },
                "errors": export_errors,
            }
            self._snapshot_cache = (now, result)
            return result

    def course(self, course_id: int) -> dict[str, Any] | None:
        course_dir = find_course_dir(self.root, course_id)
        if course_dir is None:
            return None
        manifest_path = self.root / "manifest.json"
        manifest = read_json(manifest_path, {})
        summary = course_summary(
            self.root,
            course_dir,
            enrollment_map(self.root),
            export_complete=manifest_path.exists(),
            export_errors=manifest.get("errors", []),
        )
        assignments = read_json(course_dir / "assignments.json", [])
        submissions = read_json(course_dir / "submissions.json", [])
        assignment_map = {item.get("id"): item for item in assignments}
        submission_map = {item.get("assignment_id"): item for item in submissions}
        all_ids = list(dict.fromkeys([*assignment_map.keys(), *submission_map.keys()]))

        local_assets: dict[str, Path] = {}
        for asset_dir_name in ("submission-files", "discussion-attachments"):
            asset_dir = course_dir / asset_dir_name
            if asset_dir.exists():
                for path in asset_dir.rglob("*"):
                    if path.is_file():
                        local_assets[path.name.split("-", 1)[0]] = path

        records: list[dict[str, Any]] = []
        profile = read_json(self.root / "account" / "profile.json", {})
        profile_id = profile.get("id")
        profile_names = {
            str(profile.get("name") or "").casefold(),
            str(profile.get("short_name") or "").casefold(),
        } - {""}
        for assignment_id in all_ids:
            assignment = assignment_map.get(assignment_id) or {}
            submission = submission_map.get(assignment_id) or {}
            if not assignment:
                assignment = submission.get("assignment") or {}
            comments = []
            for comment in submission.get("submission_comments") or []:
                author = comment.get("author_name") or (comment.get("author") or {}).get("display_name")
                is_self = comment.get("author_id") == profile_id or str(author or "").casefold() in profile_names
                comments.append(
                    {
                        "id": comment.get("id"),
                        "author": author,
                        "author_type": "self" if is_self else "other",
                        "created_at": comment.get("created_at"),
                        "text": comment.get("comment") or plain_text(comment.get("html_comment")),
                    }
                )
            rubric = []
            assessment = submission.get("rubric_assessment") or {}
            for criterion in assignment.get("rubric") or []:
                result = assessment.get(str(criterion.get("id"))) or assessment.get(criterion.get("id")) or {}
                rubric.append(
                    {
                        "description": criterion.get("description"),
                        "long_description": plain_text(criterion.get("long_description")),
                        "points_possible": criterion.get("points"),
                        "points": result.get("points"),
                        "comments": result.get("comments"),
                        "rating": result.get("rating_id"),
                    }
                )
            attachments = []
            for attachment in submission.get("attachments") or []:
                local = local_assets.get(str(attachment.get("id")))
                attachments.append(
                    {
                        "name": attachment.get("display_name") or attachment.get("filename"),
                        "size": attachment.get("size"),
                        "content_type": attachment.get("content-type"),
                        "url": asset_url(self.root, local) if local else None,
                        "has_document_preview": bool(attachment.get("preview_url")),
                        "is_annotation_file": bool(
                            local and ("annotat" in local.name.lower() or "marked" in local.name.lower())
                        ),
                    }
                )
            annotation_referenced = any("annotat" in str(comment.get("text") or "").lower() for comment in comments)
            records.append(
                {
                    "id": assignment_id,
                    "name": assignment.get("name") or f"Assignment {assignment_id}",
                    "description": plain_text(assignment.get("description")),
                    "due_at": assignment.get("due_at"),
                    "points_possible": assignment.get("points_possible"),
                    "score": submission.get("score"),
                    "grade": submission.get("grade"),
                    "submitted_at": submission.get("submitted_at"),
                    "graded_at": submission.get("graded_at"),
                    "workflow_state": submission.get("workflow_state"),
                    "late": submission.get("late"),
                    "missing": submission.get("missing"),
                    "excused": submission.get("excused"),
                    "attempt": submission.get("attempt"),
                    "body": plain_text(submission.get("body")),
                    "comments": comments,
                    "rubric": rubric,
                    "attachments": attachments,
                    "feedback_types": {
                        "comments": bool(comments),
                        "rubric": any(row.get("points") is not None or row.get("comments") for row in rubric),
                        "annotation_file": any(item.get("is_annotation_file") for item in attachments),
                        "annotation_referenced": annotation_referenced,
                    },
                }
            )
        records.sort(key=lambda item: (item.get("due_at") or "9999", item.get("name") or ""))

        discussions = read_json(course_dir / "my-discussion-posts.json", [])
        quiz_submissions = read_json(course_dir / "quiz-submissions.json", [])
        return {
            "summary": summary,
            "assignments": records,
            "discussions": [
                {
                    "topic_id": item.get("topic_id"),
                    "topic_title": item.get("topic_title"),
                    "created_at": (item.get("entry") or {}).get("created_at"),
                    "message": plain_text((item.get("entry") or {}).get("message")),
                }
                for item in discussions
            ],
            "quizzes": [
                {
                    "id": item.get("id"),
                    "quiz_id": item.get("quiz_id"),
                    "attempt": item.get("attempt"),
                    "score": item.get("score"),
                    "kept_score": item.get("kept_score"),
                    "started_at": item.get("started_at"),
                    "finished_at": item.get("finished_at"),
                    "workflow_state": item.get("workflow_state"),
                }
                for item in quiz_submissions
            ],
            "files": [
                file_record(self.root, path, summary["name"])
                for path in local_assets.values()
            ],
        }

    def search(self, query: str) -> dict[str, Any]:
        needle = query.strip().casefold()
        empty = {"courses": [], "assignments": [], "feedback": [], "files": [], "messages": []}
        if len(needle) < 2:
            return {"query": query, "groups": empty, "total": 0}

        snapshot = self.snapshot()
        groups: dict[str, list[dict[str, Any]]] = {key: [] for key in empty}
        for course in snapshot["courses"]:
            if needle in " ".join(str(course.get(key) or "") for key in ("name", "code", "term")).casefold():
                groups["courses"].append(course)
            detail = self.course(course["id"])
            if not detail:
                continue
            for assignment in detail["assignments"]:
                haystack = " ".join(
                    [
                        str(assignment.get("name") or ""),
                        str(assignment.get("description") or ""),
                        str(assignment.get("body") or ""),
                    ]
                ).casefold()
                if needle in haystack:
                    groups["assignments"].append(
                        {
                            "course_id": course["id"],
                            "course_name": course["name"],
                            "id": assignment.get("id"),
                            "name": assignment.get("name"),
                            "due_at": assignment.get("due_at"),
                            "score": assignment.get("score"),
                            "points_possible": assignment.get("points_possible"),
                            "comment_count": len(assignment.get("comments") or []),
                        }
                    )

        groups["feedback"] = [
            item for item in snapshot["feedback"]
            if needle in " ".join(
                str(item.get(key) or "")
                for key in ("comment", "course_name", "assignment_name", "author_name")
            ).casefold()
        ]
        groups["files"] = [
            item for item in snapshot["files"]
            if needle in f"{item.get('display_name', '')} {item.get('course_name', '')} {item.get('kind', '')}".casefold()
        ]
        for conversation in self.inbox():
            matching_messages = [
                message for message in conversation["messages"]
                if needle in f"{message.get('author', '')} {message.get('body', '')}".casefold()
            ]
            if needle in f"{conversation.get('subject', '')} {conversation.get('context_name', '')}".casefold() or matching_messages:
                groups["messages"].append(
                    {
                        "id": conversation.get("id"),
                        "subject": conversation.get("subject"),
                        "context_name": conversation.get("context_name"),
                        "snippet": (matching_messages[0].get("body") if matching_messages else "")[:280],
                    }
                )

        groups = {key: value[:50] for key, value in groups.items()}
        return {"query": query, "groups": groups, "total": sum(len(value) for value in groups.values())}

    def inbox(self) -> list[dict[str, Any]]:
        conversations = read_json(self.root / "inbox" / "conversations.json", [])
        attachment_dir = self.root / "inbox" / "attachments"
        local_assets: dict[str, Path] = {}
        if attachment_dir.exists():
            for path in attachment_dir.rglob("*"):
                if path.is_file():
                    local_assets[path.name.split("-", 1)[0]] = path
        results = []
        for conversation in conversations:
            participants = {item.get("id"): item.get("name") for item in conversation.get("participants", [])}
            messages = []
            for message in reversed(conversation.get("messages", [])):
                attachments = []
                for attachment in message.get("attachments") or []:
                    local = local_assets.get(str(attachment.get("id")))
                    attachments.append(
                        {
                            "name": attachment.get("display_name") or attachment.get("filename"),
                            "url": asset_url(self.root, local) if local else None,
                        }
                    )
                messages.append(
                    {
                        "id": message.get("id"),
                        "author": participants.get(message.get("author_id"), "Unknown sender"),
                        "created_at": message.get("created_at"),
                        "body": plain_text(message.get("body")),
                        "attachments": attachments,
                    }
                )
            results.append(
                {
                    "id": conversation.get("id"),
                    "subject": conversation.get("subject") or "No subject",
                    "context_name": conversation.get("context_name"),
                    "participants": list(participants.values()),
                    "messages": messages,
                }
            )
        return results


class ArchiveHandler(BaseHTTPRequestHandler):
    model: ArchiveModel

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/api/archive":
            self.send_json(self.model.snapshot())
            return
        if path == "/api/inbox":
            self.send_json(self.model.inbox())
            return
        if path == "/api/search":
            query = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
            self.send_json(self.model.search(query))
            return
        if path.startswith("/api/course/"):
            try:
                course_id = int(path.rsplit("/", 1)[-1])
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Invalid course ID")
                return
            course = self.model.course(course_id)
            if course is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Course not found")
            else:
                self.send_json(course)
            return
        if path.startswith("/files/"):
            self.serve_archive_file(urllib.parse.unquote(path[len("/files/"):]))
            return
        if path == "/":
            self.serve_web_file("index.html")
            return
        if path.startswith("/assets/"):
            self.serve_web_file(path[len("/assets/"):])
            return
        self.serve_web_file("index.html")

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def serve_web_file(self, relative: str) -> None:
        target = (WEB_ROOT / relative).resolve()
        if not target.is_relative_to(WEB_ROOT) or not target.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.serve_file(target, inline=True)

    def serve_archive_file(self, relative: str) -> None:
        target = (self.model.root / relative).resolve()
        if (
            not target.is_relative_to(self.model.root)
            or not target.is_file()
            or not any(part in ASSET_DIRECTORIES for part in target.relative_to(self.model.root).parts)
        ):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.serve_file(target, inline=target.suffix.lower() in {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".gif"})

    def serve_file(self, target: Path, *, inline: bool) -> None:
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        try:
            size = target.stat().st_size
            source = target.open("rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        disposition = "inline" if inline else "attachment"
        ascii_name = target.name.encode("ascii", errors="ignore").decode("ascii").replace('"', "") or "download"
        utf8_name = urllib.parse.quote(target.name)
        self.send_header(
            "Content-Disposition",
            f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{utf8_name}',
        )
        self.end_headers()
        with source:
            shutil.copyfileobj(source, self.wfile, length=1024 * 1024)

    def log_message(self, format: str, *args: Any) -> None:
        if args and str(args[1]) not in {"200", "304"}:
            super().log_message(format, *args)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Browse a Canvas personal export locally.")
    parser.add_argument("archive", nargs="?", type=Path, help="export directory; defaults to the latest")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="do not open a browser automatically")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.archive.expanduser().resolve() if args.archive else latest_export()
    if root is None or not root.is_dir():
        print("No Canvas export directory found.")
        return 1
    ArchiveHandler.model = ArchiveModel(root)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ArchiveHandler)
    url = f"http://127.0.0.1:{args.port}"
    print(f"Browsing {root}")
    print(f"Open {url}")
    print("Press Ctrl-C to stop.")
    if not args.no_open:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
