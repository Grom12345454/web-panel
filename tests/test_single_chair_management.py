"""One visible chair, with explicit remediation for genuine legacy conflicts."""
import unittest
from types import SimpleNamespace
from services.chair_display import management_leadership_rows


def row(id, student_id, title='Председатель студсовета'):
    student = SimpleNamespace(id=student_id, full_name=f'Студент {student_id}')
    return SimpleNamespace(id=id, student_id=student_id, student=student, position_name=title)


class SingleChairManagementTests(unittest.TestCase):
    def test_legacy_same_person_multiple_directions(self):
        result, candidates, count = management_leadership_rows(
            [row(6, 10), row(3, 10), row(2, 99, 'Глава направления')], lambda x: x)
        self.assertEqual([r.id for r in result], [3, 2])
        self.assertEqual([p.id for p in candidates], [10])
        self.assertEqual(count, 0)

    def test_two_chairholders_shown_only_in_resolution(self):
        result, candidates, count = management_leadership_rows(
            [row(9, 2), row(1, 1), row(4, 3, 'Глава направления')], lambda x: x)
        self.assertEqual([r.id for r in result], [1, 4])
        self.assertEqual([p.id for p in candidates], [1, 2])
        self.assertEqual(count, 1)

    def test_legacy_alias_supported_by_canonical_role(self):
        result, candidates, count = management_leadership_rows(
            [row(1, 4, 'Председатель волонтёрки'), row(2, 5)],
            lambda x: 'Председатель студсовета' if x == 'Председатель волонтёрки' else x)
        self.assertEqual(len(result), 1)
        self.assertEqual(count, 1)


if __name__ == '__main__':
    unittest.main()
