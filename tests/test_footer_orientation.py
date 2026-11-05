import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import image_processor as processor


def data(text="", confidence=96, left=180):
    return {
        "text": [text], "conf": [confidence],
        "left": [left], "top": [80], "width": [40], "height": [30],
        "block_num": [1], "par_num": [1], "line_num": [1],
    }


class FooterOrientationTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("L", (1000, 2000), "white")

    def test_footer_corrects_upside_down_without_table_ocr(self):
        responses = [data(), data(), data("2/4"), data()]
        with patch.object(processor.pytesseract, "image_to_data", side_effect=responses) as ocr:
            self.assertEqual(processor.detect_orientation_by_ocr(self.image), 180)
            self.assertEqual(ocr.call_count, 4)
            self.assertTrue(all(c.kwargs["lang"] == "eng" for c in ocr.call_args_list))

    def test_ambiguous_footer_does_not_choose_a_direction(self):
        with patch.object(processor.pytesseract, "image_to_data", return_value=data("2/4")):
            self.assertIsNone(processor._detect_footer_orientation(self.image))

    def test_dates_low_confidence_invalid_fraction_and_offcenter_are_rejected(self):
        responses = [data("26/10/15"), data("2/4", 30), data("8/2"), data("2/4", left=0)]
        with patch.object(processor.pytesseract, "image_to_data", side_effect=responses):
            self.assertIsNone(processor._detect_footer_orientation(self.image))

    def test_fraction_inside_a_text_line_is_rejected(self):
        with patch.object(processor.pytesseract, "image_to_data", return_value=data("합계 2/4")):
            self.assertIsNone(processor._detect_footer_orientation(self.image))

    def test_missing_english_data_falls_back_to_korean_path(self):
        error = processor.pytesseract.TesseractError(1, "missing eng")
        with patch.object(processor.pytesseract, "image_to_data", side_effect=error):
            self.assertIsNone(processor._detect_footer_orientation(self.image))


if __name__ == "__main__":
    unittest.main()
