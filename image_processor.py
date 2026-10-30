import io
import os
from PIL import Image, ImageOps
import pytesseract
import re

# 여러 이미지와 Tesseract 내부 병렬 처리가 CPU를 중복 점유하지 않게 합니다.
os.environ.setdefault('OMP_THREAD_LIMIT', '1')

# Windows의 경우 Tesseract-OCR 경로 명시적 지정 및 로컬 tessdata 설정
tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(tesseract_path):
    pytesseract.pytesseract.tesseract_cmd = tesseract_path

# 로컬 tessdata 폴더를 사용하도록 TESSDATA_PREFIX 설정
local_tessdata = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tessdata')
if os.path.isfile(os.path.join(local_tessdata, 'kor.traineddata')):
    os.environ['TESSDATA_PREFIX'] = local_tessdata

TARGET_SIZE = 1_000_000  # 제출 사이트의 십진수 1MB 제한도 충족합니다.
OCR_TIMEOUT = 20


def detect_orientation_by_ocr(image: Image.Image, warnings=None) -> int:
    """
    4방향 회전 스캔(--psm 4)을 사용하여 이미지의 정확한 회전 각도를 감지합니다.
    Tesseract OSD는 한국어 표/영수증에서 180도 오작동이 잦아 사용하지 않습니다.
    하단에 페이지 번호(예: 1/2)가 발견되면 해당 방향을 강력히 우선시합니다.
    """
    best_angle = 0
    max_score = -1
    scores = []
    
    # OCR용 사본만 축소합니다. 작은 이미지는 확대하지 않습니다.
    temp_img = image.copy()
    temp_img.thumbnail((2000, 2000))
    temp_img = temp_img.convert('L')
    temp_img = ImageOps.autocontrast(temp_img)
    
    for angle in [0, 90, 180, 270]:
        rotated = temp_img.rotate(angle, expand=True)
        try:
            # PSM 4: 다양한 크기의 텍스트가 있는 단일 열 레이아웃 가정.
            # (PSM 3는 표가 누워있을 때 세로쓰기 한글로 오인하여 완벽하게 읽어내는 치명적 문제가 있어 4로 변경)
            data = pytesseract.image_to_data(rotated, lang='kor', config='--psm 4', output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT)
            
            # 한글 글자 수 세기 및 환각 방지 (페이지 번호가 없는 문서를 위함)
            full_text = " ".join([str(t) for t in data['text'] if str(t).strip()])
            
            # 1. 병원 문서 키워드 점수 (오인식할 수 있으므로 점수 차이도 검사)
            keywords = ['진료비', '산정내역', '환자', '병원', '합계', '금액', '코드', '명칭', '처방', '급여', '비급여', '영수증', '주민번호', '등록번호', '요양기관']
            keyword_count = sum(full_text.count(kw) for kw in keywords)
            keyword_score = keyword_count * 2000
            
            # 2. 포맷된 숫자 점수 (콤마가 포함된 금액 등, 가로 표 선 환각 차단)
            formatted_numbers = len(re.findall(r'\b\d{1,3}(?:,\d{3})+\b', full_text))
            number_score = formatted_numbers * 500
            
            # 3. 날짜 포맷 점수
            dates = len(re.findall(r'\b\d{2,4}[-./]\d{1,2}[-./]\d{1,2}\b', full_text))
            date_score = dates * 500
            
            # 4. 일반 한글 단어 점수 (최소한의 가중치)
            words = re.findall(r'[가-힣]{2,}', full_text)
            word_score = sum(len(w) for w in words) * 10
            
            # 5. 좌표 기반 페이지 번호 검사 (추가 크롭 없이 전체 OCR 데이터에서 찾기)
            cur_height = rotated.height
            cur_width = rotated.width
            page_num_score = 0
            
            for i in range(len(data['text'])):
                text = str(data['text'][i]).strip()
                if not text: continue
                
                # 페이지 번호 형태 (예: 1/2, -1-)
                if re.match(r'^([1-9][0-9]?/[1-9][0-9]?|-[1-9][0-9]?-|page[1-9][0-9]?)$', text, re.IGNORECASE):
                    x = data['left'][i]
                    y = data['top'][i]
                    # 현재 회전된 상태에서 하단 20%, 중앙 40% 이내에 위치하는지 검증
                    if y > cur_height * 0.8 and (cur_width * 0.3 < x < cur_width * 0.7):
                        page_num_score = 10000
                        break
                        
            score = keyword_score + number_score + date_score + word_score + page_num_score
            scores.append(score)
            
            # 콘솔 에러 방지를 위해 점수만 깔끔하게 출력
            print(f"Angle {angle}: Score {score} (Keywords: {keyword_count}, Numbers: {formatted_numbers}, Dates: {dates}, PageNum: {page_num_score > 0})")
            
            if score > max_score:
                max_score = score
                best_angle = angle
        except Exception as e:
            raise RuntimeError(
                "자동 회전 OCR에 실패했습니다. Tesseract 설치와 한국어 데이터(kor)를 "
                "확인하거나 압축 전용 모드를 사용하세요. 상세: " + str(e)
            ) from e
            
    # 유의미한 텍스트가 거의 없으면 원본 유지
    ranked = sorted(scores, reverse=True)
    # 초기 보수적 기준입니다. 실제 문서 표본으로 조정해야 합니다.
    if max_score < 100 or ranked[0] - ranked[1] < max(50, ranked[0] * 0.15):
        if warnings is not None:
            warnings.append("문자 인식량이 적거나 방향별 점수가 비슷해 OCR 회전을 생략했습니다. 결과 방향을 확인하세요.")
        return 0
        
    return best_angle

def fix_orientation(image: Image.Image, use_exif: bool = True, warnings=None) -> Image.Image:
    """
    한글 OCR을 활용하여 이미지 방향을 정방향으로 교정합니다.
    """
    # 1. EXIF 기반 회전 (사용자가 옵션으로 켜둔 경우)
    if use_exif:
        try:
            image = ImageOps.exif_transpose(image)
        except Exception as e:
            raise ValueError("EXIF 방향 정보를 적용하지 못했습니다.") from e

    # 2. 한글 OCR 점수 기반 회전
    print("Detecting orientation using Korean OCR...")
    correct_angle = detect_orientation_by_ocr(image, warnings)
    if correct_angle != 0:
        print(f"Rotating image by {correct_angle} degrees to correct orientation.")
        image = image.rotate(correct_angle, expand=True)

    return image


def process_image(file_bytes: bytes, original_filename: str, use_exif: bool = True, compress_only: bool = False, *, warnings=None) -> tuple[bytes, str]:
    """방향을 교정하고 메타데이터 없는 1,000,000바이트 이하 JPG를 반환합니다.

    압축 전용 모드는 EXIF 방향을 픽셀에 적용해 원본의 표시 방향을 유지합니다.
    warnings를 전달하면 불확실한 OCR 방향 판단 메시지를 수집합니다.
    """
    with Image.open(io.BytesIO(file_bytes)) as source:
        source.load()
        image = source.copy()

    if compress_only:
        image = ImageOps.exif_transpose(image)
    else:
        image = fix_orientation(image, use_exif, warnings)

    # 투명 PNG는 흰 배경에 합성합니다.
    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    else:
        image = image.convert("RGB")

    # EXIF/GPS/ICC 등 원본 메타데이터가 자동 전달되지 않게 제거합니다.
    image.info.clear()
    filename = original_filename.replace("\\", "/").rsplit("/", 1)[-1]
    base_name, _ = os.path.splitext(filename)
    new_filename = f"{base_name or 'image'}.jpg"

    original_dimensions = image.size
    # 문서 가독성을 위해 품질 40 미만 대신 해상도를 단계적으로 줄입니다.
    while True:
        for quality in range(95, 39, -5):
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=quality, optimize=True)
            encoded = output.getvalue()
            if len(encoded) <= TARGET_SIZE:
                if warnings is not None and image.size != original_dimensions:
                    warnings.append("1MB 제한을 맞추기 위해 이미지 해상도를 줄였습니다. 작은 글자의 가독성을 확인하세요.")
                return encoded, new_filename
        width, height = image.size
        new_size = (max(1, int(width * 0.85)), max(1, int(height * 0.85)))
        if new_size == image.size:
            raise ValueError("목표 용량 이하로 이미지를 압축하지 못했습니다.")
        image = image.resize(new_size, Image.Resampling.LANCZOS)
