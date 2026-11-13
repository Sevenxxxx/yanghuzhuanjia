"""规范引用命名的纯函数回归：书架标题太长、编号紧凑，不能把编号当名称用。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from roadexpert.specs import citation_of, display_std_no, standard_name  # noqa: E402
from roadexpert.delivery_check import citation_name_missing  # noqa: E402


class StandardNameTests(unittest.TestCase):
    def test_strips_index_prefix_and_number_suffix(self):
        self.assertEqual(
            standard_name("154-公路沥青路面养护技术规范-JTG5142-2019", "JTG5142-2019"),
            "公路沥青路面养护技术规范",
        )

    def test_strips_dotted_prefix(self):
        self.assertEqual(
            standard_name("125-公路交通安全设施施工技术规范-JTGT3671-2021", "JTGT3671-2021"),
            "公路交通安全设施施工技术规范",
        )

    def test_keeps_title_when_shape_is_unfamiliar(self):
        title = "14.GB 51038-2015 城市道路交通标志和标线设置规范"
        self.assertEqual(standard_name(title, ""), "GB 51038-2015 城市道路交通标志和标线设置规范")

    def test_does_not_cut_a_name_that_ends_with_digits(self):
        self.assertEqual(standard_name("公路养护技术规范2020"), "公路养护技术规范2020")


class DisplayStdNoTests(unittest.TestCase):
    def test_spaces_between_letters_and_digits(self):
        self.assertEqual(display_std_no("JTG5142-2019"), "JTG 5142—2019")

    def test_restores_slash_and_keeps_part_number(self):
        self.assertEqual(display_std_no("JTGT5142-01-2021"), "JTG/T 5142-01—2021")

    def test_keeps_plain_codes(self):
        self.assertEqual(display_std_no("GB51038-2015"), "GB 51038—2015")

    def test_empty_and_odd_values(self):
        self.assertEqual(display_std_no(""), "")
        self.assertEqual(display_std_no(None), "")
        self.assertEqual(display_std_no("内部规定"), "内部规定")


class CitationTests(unittest.TestCase):
    def test_citation_includes_name_and_number(self):
        self.assertEqual(
            citation_of("155-公路沥青路面预防养护技术规范-JTGT5142-01-2021", "JTGT5142-01-2021"),
            "《公路沥青路面预防养护技术规范》（JTG/T 5142-01—2021）",
        )

    def test_citation_without_number_keeps_book_title_marks(self):
        self.assertEqual(
            citation_of("公路安全生命防护工程实施技术指南（试行）", ""),
            "《公路安全生命防护工程实施技术指南（试行）》",
        )


class CitationNameMissingTests(unittest.TestCase):
    def test_named_first_mention_is_fine(self):
        text = "《公路沥青路面养护技术规范》（JTG 5142—2019）第 6.1.2 条规定……"
        self.assertEqual(citation_name_missing(text), [])

    def test_bare_number_is_flagged(self):
        text = "依据 JTG 5142—2019 第 6.1.2 条，应先治基层。"
        self.assertEqual(citation_name_missing(text), ["JTG 5142—2019"])

    def test_later_mentions_may_omit_the_name(self):
        text = ("《公路沥青路面养护技术规范》（JTG 5142—2019）第 6.1.2 条要求先治基层。"
                "同规范 JTG 5142—2019 第 6.2.7 条另外规定……")
        self.assertEqual(citation_name_missing(text), [])

    def test_name_in_another_sentence_still_flags_first_code(self):
        text = "《公路沥青路面养护技术规范》另有要求。见 JTG 5142—2019。"
        self.assertEqual(citation_name_missing(text), ["JTG 5142—2019"])


if __name__ == "__main__":
    unittest.main()
