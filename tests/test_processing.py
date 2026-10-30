import ast
import io
import random
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont, ImageOps
import image_processor as processor
from file_utils import unique_filename


def encode(image, fmt="PNG", **kwargs):
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **kwargs)
    return buffer.getvalue()


def ocr_data(text):
    return {"text": [text], "left": [50], "top": [50]}


class ProcessingTests(unittest.TestCase):
    def test_large_noise_fits_limit_and_resizes(self):
        image = Image.frombytes("RGB", (2600, 2600), random.Random(42).randbytes(2600 * 2600 * 3))
        warnings = []
        result, _ = processor.process_image(encode(image), "large.png", compress_only=True, warnings=warnings)
        self.assertLessEqual(len(result), 1_000_000)
        self.assertLess(Image.open(io.BytesIO(result)).width, image.width)
        self.assertTrue(warnings)

    def test_transparent_png_becomes_white(self):
        result, name = processor.process_image(encode(Image.new("RGBA", (30, 30), (0, 0, 0, 0))), "a.png", compress_only=True)
        output = Image.open(io.BytesIO(result))
        self.assertEqual(output.mode, "RGB")
        self.assertEqual(output.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(name, "a.jpg")

    def test_palette_transparency_becomes_white(self):
        image = Image.new("P", (20, 20), 0)
        image.putpalette([0, 0, 0] * 256)
        result, _ = processor.process_image(encode(image, transparency=0), "p.png", compress_only=True)
        self.assertEqual(Image.open(io.BytesIO(result)).getpixel((0, 0)), (255, 255, 255))

    def test_exif_orientation_preserved_and_metadata_removed(self):
        image = Image.new("RGB", (80, 40), "red")
        ImageDraw.Draw(image).rectangle((0, 0, 39, 39), fill="blue")
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                exif = Image.Exif()
                exif[274] = orientation
                exif[270] = "private description"
                original = encode(image, "JPEG", exif=exif)
                expected = ImageOps.exif_transpose(Image.open(io.BytesIO(original)))
                result, _ = processor.process_image(original, "a.jpg", use_exif=False, compress_only=True)
                output = Image.open(io.BytesIO(result))
                self.assertEqual(output.size, expected.size)
                self.assertFalse(output.getexif())
                for point in [(5, 5), (output.width - 6, output.height - 6)]:
                    self.assertLess(max(abs(a - b) for a, b in zip(output.getpixel(point), expected.getpixel(point))), 20)

    def test_compress_only_never_calls_ocr(self):
        with patch.object(processor.pytesseract, "image_to_data", side_effect=AssertionError("OCR called")):
            processor.process_image(encode(Image.new("RGB", (20, 20))), "a.jpg", compress_only=True)

    def test_ocr_failure_is_reported(self):
        with patch.object(processor.pytesseract, "image_to_data", side_effect=RuntimeError("timeout")):
            with self.assertRaisesRegex(RuntimeError, "OCR"):
                processor.process_image(encode(Image.new("RGB", (20, 20))), "a.jpg")

    def test_partial_ocr_failure_is_not_used_as_a_valid_comparison(self):
        with patch.object(processor.pytesseract, "image_to_data", side_effect=[ocr_data("병원"), RuntimeError("timeout")]):
            with self.assertRaises(RuntimeError):
                processor.detect_orientation_by_ocr(Image.new("RGB", (100, 100)))

    def test_ambiguous_direction_keeps_original_with_warning(self):
        warnings = []
        with patch.object(processor.pytesseract, "image_to_data", return_value=ocr_data("병원")):
            self.assertEqual(processor.detect_orientation_by_ocr(Image.new("RGB", (100, 100)), warnings), 0)
        self.assertTrue(warnings)

    def test_sparse_text_keeps_original_with_warning(self):
        warnings = []
        with patch.object(processor.pytesseract, "image_to_data", side_effect=[ocr_data(""), ocr_data(""), ocr_data("가나"), ocr_data("")]):
            self.assertEqual(processor.detect_orientation_by_ocr(Image.new("RGB", (100, 100)), warnings), 0)
        self.assertTrue(warnings)

    def test_clear_direction_rotates_and_applies_timeout(self):
        with patch.object(processor.pytesseract, "image_to_data", side_effect=[ocr_data(""), ocr_data("병원 합계 금액"), ocr_data(""), ocr_data("")]) as ocr:
            output = processor.fix_orientation(Image.new("RGB", (120, 80)), use_exif=False)
            self.assertEqual(output.size, (80, 120))
            self.assertEqual(ocr.call_args.kwargs["timeout"], processor.OCR_TIMEOUT)

    def test_corrupt_input_fails(self):
        with self.assertRaises(Exception):
            processor.process_image(b"not an image", "a.jpg", compress_only=True)

    def test_duplicate_names_and_existing_suffixes(self):
        used = set()
        names = [unique_filename(name, used) for name in ["a.jpg", "A.JPG", "a_2.jpg", "a.jpg"]]
        self.assertEqual(len(set(name.casefold() for name in names)), 4)

    def test_upload_paths_are_removed(self):
        result, name = processor.process_image(encode(Image.new("RGB", (20, 20))), "../folder/a.png", compress_only=True)
        self.assertEqual(name, "a.jpg")


class CacheTests(unittest.TestCase):
    def test_contents_options_source_revision_and_manual_clear(self):
        import streamlit as st
        tree = ast.parse((Path(processor.__file__).parent / "app.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "process_and_cache_image")
        process = Mock(return_value=(b"output", "a.jpg"))
        namespace = {"st": st, "process_image": process}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "app.py", "exec"), namespace)
        cached = namespace["process_and_cache_image"]
        cached.clear()
        cached(b"first", "a.jpg", False, True, "revision1")
        cached(b"first", "a.jpg", False, True, "revision1")
        self.assertEqual(process.call_count, 1)
        cached(b"changed", "a.jpg", False, True, "revision1")
        cached(b"changed", "a.jpg", True, True, "revision1")
        cached(b"changed", "a.jpg", True, True, "revision2")
        self.assertEqual(process.call_count, 4)
        st.cache_data.clear()
        cached(b"changed", "a.jpg", True, True, "revision2")
        self.assertEqual(process.call_count, 5)
        process.side_effect = RuntimeError("temporary error")
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                cached(b"error", "a.jpg", False, False, "revision2")
        self.assertEqual(process.call_count, 7)
        cached.clear()


class AppTests(unittest.TestCase):
    def test_startup_options_and_cache_button(self):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(Path(processor.__file__).parent / "app.py")).run()
        self.assertFalse(app.exception)
        app.checkbox[0].check().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.checkbox[1].disabled)
        app.sidebar.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertTrue(app.success)


if __name__ == "__main__":
    unittest.main()
