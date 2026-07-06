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
    하단에 페이지 번호(예: 1/2)가 발견되면 해당 방향을 강력히 우선시합니다.
    """
    best_angle = 0
    max_score = -1
    
    # 해상도 상향 (너무 작으면 인식 실패, 너무 크면 속도 저하)
    temp_img = image.copy()
    temp_img.thumbnail((2000, 2000))
    temp_img = temp_img.convert('L')
    temp_img = ImageOps.autocontrast(temp_img)
    
    for angle in [0, 90, 180, 270]:
        rotated = temp_img.rotate(angle, expand=True)
        try:
            # PSM 4 옵션: 단일 텍스트 블록 가정.
            # (PSM 3는 표가 누워있을 때 세로쓰기 한글로 오인하여 완벽하게 읽어내는 치명적 문제가 있어 4로 변경)
            data = pytesseract.image_to_data(rotated, lang='kor', config='--psm 4', output_type=pytesseract.Output.DICT)
            
            # 한글 글자 수 세기 및 환각 방지 (페이지 번호가 없는 문서를 위함)
            full_text = " ".join([str(t) for t in data['text'] if str(t).strip()])
            
            # 1. 도메인 특화 키워드 점수 (환각으로는 절대 만들어질 수 없는 완벽한 기준)
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
            
            # 콘솔 에러 방지를 위해 점수만 깔끔하게 출력
            print(f"Angle {angle}: Score {score} (Keywords: {keyword_count}, Numbers: {formatted_numbers}, Dates: {dates}, PageNum: {page_num_score > 0})")
            
            if score > max_score:
                max_score = score
                best_angle = angle
        except Exception as e:
            print(f"OCR failed for angle {angle}: {e}")
            
    # 유의미한 텍스트가 거의 없으면 원본 유지
    if max_score < 5:
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


def process_image(file_bytes: bytes, original_filename: str, use_exif: bool = True, compress_only: bool = False) -> tuple[bytes, str]:
    """
    이미지를 받아 방향을 교정하고, 용량을 1MB 이하로 최적화합니다.
    (이미 1MB 이하라면 화질을 굳이 낮추지 않고 반환)
    """
    # 원본 파일 크기
    original_size = len(file_bytes)
    
    # 1. 이미지 열기
    image = Image.open(io.BytesIO(file_bytes))
    
    # EXIF 메타데이터 보존용 (압축 전용일 경우 원본 방향 유지)
    original_exif = image.info.get('exif')
    
    # 2. 방향 교정
    if not compress_only:
        image = fix_orientation(image, use_exif)
        # 픽셀 회전이 발생했으므로 기존 회전 메타데이터(EXIF)가 더 이상 맞지 않음
        original_exif = None
    
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
    save_kwargs = {"format": "JPEG", "quality": quality}
    if original_exif:
        save_kwargs["exif"] = original_exif
        
    image.save(output_io, **save_kwargs)
    
    # 용량 최적화 루프
    # 만약 원본이 1MB 이상이었거나, 저장했는데 1MB가 넘는다면 최적화 수행
    if original_size > TARGET_SIZE or output_io.tell() > TARGET_SIZE:
        while output_io.tell() > TARGET_SIZE and quality > 10:
            quality -= 5
            output_io = io.BytesIO()  # 버퍼 비우기
            save_kwargs["quality"] = quality
            image.save(output_io, **save_kwargs)
            
    return output_io.getvalue(), new_filename
