import unittest
import sys
import types
from unittest.mock import patch

from services.student_validation import normalize_full_name, normalize_phone, student_duplicate_message


class StudentIdentityNormalizationTests(unittest.TestCase):
    def test_full_name_ignores_case_and_repeated_whitespace(self):
        self.assertEqual(
            normalize_full_name("  Иванов   Иван   Ёжевич "),
            normalize_full_name("иванов Иван Ежевич"),
        )

    def test_phone_ignores_punctuation_and_international_00_prefix(self):
        self.assertEqual(
            normalize_phone("+371 (200) 00-000"),
            normalize_phone("00371 200 00 000"),
        )

    def test_empty_phone_does_not_create_a_comparison_key(self):
        self.assertEqual(normalize_phone(""), "")
        self.assertEqual(normalize_phone("   (+-) "), "")

    def test_duplicate_name_and_phone_are_reported(self):
        class Column:
            def __ne__(self, other):
                return ("not_equal", other)

        class FakeQuery:
            def __init__(self, rows):
                self.rows = rows
                self.excluded_id = None

            def with_entities(self, *_columns):
                return self

            def filter(self, condition):
                if condition and condition[0] == "not_equal":
                    self.excluded_id = condition[1]
                return self

            def all(self):
                return [row for row in self.rows if row[0] != self.excluded_id]

        fake_student = type("Student", (), {
            "id": Column(), "full_name": Column(), "phone": Column(),
            "query": FakeQuery([(1, "Иванов Иван", "+371 200-00000")]),
        })
        fake_database = types.ModuleType("database")
        fake_database.Student = fake_student
        with patch.dict(sys.modules, {"database": fake_database}):
            error = student_duplicate_message("иванов   Иван", "00371 200 00000")
            self.assertIn("ФИО", error)
            self.assertIn("телефон", error)

    def test_duplicate_check_can_exclude_the_current_profile(self):
        class Column:
            def __ne__(self, other):
                return ("not_equal", other)

        class FakeQuery:
            def __init__(self, rows):
                self.rows = rows
                self.excluded_id = None

            def with_entities(self, *_columns):
                return self

            def filter(self, condition):
                if condition and condition[0] == "not_equal":
                    self.excluded_id = condition[1]
                return self

            def all(self):
                return [row for row in self.rows if row[0] != self.excluded_id]

        fake_student = type("Student", (), {
            "id": Column(), "full_name": Column(), "phone": Column(),
            "query": FakeQuery([(1, "Иванов Иван", "+371 200-00000")]),
        })
        fake_database = types.ModuleType("database")
        fake_database.Student = fake_student
        with patch.dict(sys.modules, {"database": fake_database}):
            self.assertIsNone(student_duplicate_message(
                "Иванов Иван", "+371 200-00000", exclude_id=1
            ))


if __name__ == "__main__":
    unittest.main()
