import unittest

from export_canvas import extract_own_discussion_entries, parse_next_link, submission_rows


class ExportCanvasTests(unittest.TestCase):
    def test_parse_next_link(self):
        header = (
            '<https://canvas.example/api/v1/courses?page=1>; rel="current", '
            '<https://canvas.example/api/v1/courses?page=2>; rel="next"'
        )
        self.assertEqual(
            parse_next_link(header),
            "https://canvas.example/api/v1/courses?page=2",
        )

    def test_submission_rows_preserve_grades_and_comments(self):
        submissions = [
            {
                "assignment_id": 10,
                "score": 9,
                "grade": "9",
                "assignment": {"id": 10, "name": "Essay", "points_possible": 10},
                "submission_comments": [
                    {"id": 20, "author_name": "Instructor", "comment": "Good work"}
                ],
            }
        ]
        grades, comments = submission_rows(submissions, 1, "Course")
        self.assertEqual(grades[0]["assignment_name"], "Essay")
        self.assertEqual(grades[0]["comment_count"], 1)
        self.assertEqual(comments[0]["comment"], "Good work")

    def test_discussion_export_selects_only_current_user(self):
        view = {
            "view": [
                {
                    "id": 1,
                    "user_id": 42,
                    "message": "Mine",
                    "replies": [{"id": 2, "user_id": 99, "message": "Not mine"}],
                },
                {"id": 3, "user_id": 99, "message": "Other"},
            ]
        }
        entries = extract_own_discussion_entries(view, 42)
        self.assertEqual([entry["id"] for entry in entries], [1])


if __name__ == "__main__":
    unittest.main()
