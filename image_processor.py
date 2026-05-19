import io
import os
from PIL import Image, ImageOps
import pytesseract
import re

# Windows의 경우 Tesseract-OCR 경로 명시적 지정 및 로컬 tessdata 설정
tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = tesseract_path

# 로컬 tessdata 폴더를 사용하도록 TESSDATA_PREFIX 설정
local_tessdata = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tessdata')
if os.path.exists(local_tessdata):
    os.environ['TESSDATA_PREFIX'] = local_tessdata

def detect_orientation_by_ocr(image: Image.Image) -> int:
    """
    4방향 회전 스캔(--psm 4)을 사용하여 이미지의 정확한 회전 각도를 감지합니다.
    Tesseract OSD는 한국어 표/영수증에서 180도 오작동이 잦아 사용하지 않습니다.
    """
    best_angle = 0
    max_korean_chars = -1
    
    # 해상도 상향 (너무 작으면 인식 실패, 너무 크면 속도 저하)
    temp_img = image.copy()
    temp_img.thumbnail((2000, 2000))
    temp_img = temp_img.convert('L')
    temp_img = ImageOps.autocontrast(temp_img)
    
    for angle in [0, 90, 180, 270]:
        rotated = temp_img.rotate(angle, expand=True)
        try:
            # PSM 4 옵션: 가변 크기의 단일 텍스트 열로 가정.
            # 표가 많은 문서에서 가로/세로 판별 능력이 가장 뛰어남.
            text = pytesseract.image_to_string(rotated, lang='kor', config='--psm 4')
            korean_chars = len(re.findall(r'[가-힣]', text))
            print(f"Angle {angle}: {korean_chars} Korean characters found")
            
            if korean_chars > max_korean_chars:
                max_korean_chars = korean_chars
                best_angle = angle
        except Exception as e:
            print(f"OCR failed for angle {angle}: {e}")
            
    # 인식된 한글이 너무 적으면 원본 유지
    if max_korean_chars < 5:
        print("Not enough Korean text detected to determine rotation. Keeping original.")
        return 0
        
    return best_angle

def fix_orientation(image: Image.Image, use_exif: bool = True) -> Image.Image:
    """
    한글 OCR을 활용하여 이미지 방향을 정방향으로 교정합니다.
    """
    # 1. EXIF 기반 회전 (사용자가 옵션으로 켜둔 경우)
    if use_exif:
        try:
            image = ImageOps.exif_transpose(image)
        except Exception as e:
            print(f"EXIF transpose failed: {e}")

    # 2. 한글 인식량 기반 회전 (가장 확실한 방법)
    print("Detecting orientation using Korean OCR...")
    correct_angle = detect_orientation_by_ocr(image)
    if correct_angle != 0:
        print(f"Rotating image by {correct_angle} degrees to correct orientation.")
        image = image.rotate(correct_angle, expand=True)

    return image


def process_image(file_bytes: bytes, original_filename: str, use_exif: bool = True) -> tuple[bytes, str]:
    """
    이미지를 받아 방향을 교정하고, 용량을 1MB 이하로 최적화합니다.
    (이미 1MB 이하라면 화질을 굳이 낮추지 않고 반환)
    """
    # 원본 파일 크기
    original_size = len(file_bytes)
    
    # 1. 이미지 열기
    image = Image.open(io.BytesIO(file_bytes))
    
    # 2. 방향 교정
    image = fix_orientation(image, use_exif)
    
    # 3. 메타데이터 제거 및 RGB 변환 (JPG 저장을 위함)
    if image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    elif image.mode != "RGB":
        image = image.convert("RGB")
        
    # 출력 파일명 결정 (기존 확장자를 무시하고 .jpg로 설정)
    base_name, _ = os.path.splitext(original_filename)
    new_filename = f"{base_name}.jpg"

    # 만약 원본이 이미 1MB 이하라면, 메타데이터 날리고 최고품질로 저장하여 반환
    # (단, 저장 후 다시 커질 수 있으므로 확인 필요)
    TARGET_SIZE = 1 * 1024 * 1024  # 1MB
    
    output_io = io.BytesIO()
    
    # 초기 시도: 품질 95
    quality = 95
    image.save(output_io, format="JPEG", quality=quality)
    
    # 용량 최적화 루프
    # 만약 원본이 1MB 이상이었거나, 저장했는데 1MB가 넘는다면 최적화 수행
    if original_size > TARGET_SIZE or output_io.tell() > TARGET_SIZE:
        while output_io.tell() > TARGET_SIZE and quality > 10:
            quality -= 5
            output_io = io.BytesIO()  # 버퍼 비우기
            image.save(output_io, format="JPEG", quality=quality)
            
    return output_io.getvalue(), new_filename
