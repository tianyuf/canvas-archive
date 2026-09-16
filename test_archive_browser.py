import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from archive_browser import ArchiveHandler, ArchiveModel, plain_text


class ArchiveBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "account").mkdir()
        (self.root / "account" / "profile.json").write_text(
            json.dumps({"id": 5, "name": "Test Student", "primary_email": "private@example.com"}),
            encoding="utf-8",
        )
        (self.root / "account" / "enrollments.json").write_text(
            json.dumps(
                [
                    {
                        "course_id": 42,
                        "enrollment_state": "completed",
                        "grades": {"final_score": 95, "final_grade": "A"},
                    }
                ]
            ),
            encoding="utf-8",
        )
        course = self.root / "courses" / "42-Test Course"
        (course / "submission-files").mkdir(parents=True)
        (course / "course.json").write_text(
            json.dumps(
                {
                    "id": 42,
                    "name": "Test Course",
                    "course_code": "TEST-1",
                    "term": {"name": "Autumn 2025", "start_at": "2025-09-01T00:00:00Z"},
                }
            ),
            encoding="utf-8",
        )
        assignment = {"id": 7, "name": "Essay", "points_possible": 10, "rubric": []}
        (course / "assignments.json").write_text(json.dumps([assignment]), encoding="utf-8")
        (course / "submissions.json").write_text(
            json.dumps(
                [
                    {
                        "assignment_id": 7,
                        "assignment": assignment,
                        "score": 9.5,
                        "submitted_at": "2025-09-02T00:00:00Z",
                        "submission_comments": [
                            {"id": 1, "author_name": "Instructor", "comment": "Strong work"},
                            {"id": 2, "author_id": 5, "author_name": "Test Student", "comment": "Thank you"},
                        ],
                        "attachments": [{"id": 99, "display_name": "essay.pdf", "size": 3}],
                    }
                ]
            ),
            encoding="utf-8",
        )
        (course / "comments.csv").write_text(
            "course_id,course_name,assignment_id,assignment_name,comment_id,author_name,created_at,comment\n"
            "42,Test Course,7,Essay,1,Instructor,2025-09-03T00:00:00Z,Strong work\n",
            encoding="utf-8",
        )
        (course / "submission-files" / "99-essay.pdf").write_bytes(b"pdf")

    def tearDown(self):
        self.temporary.cleanup()

    def test_snapshot_omits_private_profile_fields(self):
        snapshot = ArchiveModel(self.root).snapshot()
        self.assertEqual(snapshot["profile"], {"name": "Test Student", "short_name": None, "time_zone": None})
        self.assertEqual(snapshot["totals"]["courses"], 1)
        self.assertEqual(snapshot["totals"]["comments"], 1)
        self.assertFalse(snapshot["complete"])

    def test_course_combines_grade_comment_and_local_file(self):
        course = ArchiveModel(self.root).course(42)
        self.assertEqual(course["summary"]["final_grade"], "A")
        self.assertEqual(course["assignments"][0]["comments"][0]["text"], "Strong work")
        self.assertEqual(course["assignments"][0]["comments"][1]["author_type"], "self")
        self.assertEqual(course["assignments"][0]["attachments"][0]["url"], "/files/courses/42-Test%20Course/submission-files/99-essay.pdf")

    def test_search_groups_archive_results(self):
        results = ArchiveModel(self.root).search("essay")
        self.assertEqual(results["total"], 3)
        self.assertEqual(results["groups"]["assignments"][0]["name"], "Essay")
        self.assertEqual(results["groups"]["files"][0]["display_name"], "essay.pdf")

    def test_http_api_and_file_allowlist(self):
        ArchiveHandler.model = ArchiveModel(self.root)
        server = ThreadingHTTPServer(("127.0.0.1", 0), ArchiveHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(base + "/api/archive") as response:
                self.assertEqual(json.load(response)["totals"]["courses"], 1)
            with urllib.request.urlopen(base + "/api/search?q=essay") as response:
                self.assertEqual(json.load(response)["groups"]["assignments"][0]["name"], "Essay")
            with urllib.request.urlopen(base + "/files/courses/42-Test%20Course/submission-files/99-essay.pdf") as response:
                self.assertEqual(response.read(), b"pdf")
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(base + "/files/account/profile.json")
            self.assertEqual(blocked.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()

    def test_plain_text_removes_canvas_html(self):
        self.assertEqual(plain_text("<p>Hello &amp; <strong>goodbye</strong></p>"), "Hello & goodbye")


if __name__ == "__main__":
    unittest.main()
