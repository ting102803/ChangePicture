import io
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import image_processor as processor

image = Image.new("RGB", (1100, 1500), "white")
draw = ImageDraw.Draw(image)
font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 42)
lines = [
    "진료비 산정내역 영수증",
    "환자 홍길동 등록번호 123456",
    "요양기관 한국병원",
    "진료 날짜 2026-10-31",
    "명칭 코드 급여 비급여 금액",
    "처방 검사 진료비 120,000",
    "합계 금액 150,000",
]
for row, line in enumerate(lines):
    draw.text((70, 120 + row * 120), line, font=font, fill="black")
draw.text((510, 1400), "1/2", font=font, fill="black")
for angle in [0, 90, 180, 270]:
    expected = (-angle) % 360
    detected = processor.detect_orientation_by_ocr(image.rotate(angle, expand=True))
    assert detected == expected, (angle, detected, expected)
    print(f"REAL_OCR_PASS input={angle} correction={detected}")

warnings = []
blank = Image.new("RGB", (200, 200), "white")
assert processor.detect_orientation_by_ocr(blank, warnings) == 0
assert warnings
print("REAL_OCR_PASS blank image warns without rotation")
