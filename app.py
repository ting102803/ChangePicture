import streamlit as st
import hashlib
from pathlib import Path
import image_processor
from image_processor import process_image
import concurrent.futures
import zipfile
import io
from file_utils import unique_filename

st.set_page_config(
    page_title="ChangePicture",
    page_icon="📸",
    layout="centered"
)

# 처리 모듈 수정도 캐시 키에 반영해 디버깅 중 이전 결과가 남지 않게 합니다.
processor_revision = hashlib.sha256(Path(image_processor.__file__).read_bytes()).hexdigest()

st.title("📸 ChangePicture")
st.subheader("한글 문서 사진을 자동 회전시키고, 용량을 최적화합니다.")
st.write("한글 OCR로 방향을 판단하고, 메타데이터를 제거하여 1MB(1,000,000바이트) 이하의 JPG로 변환합니다. 방향 판단이 불확실하면 결과를 확인하도록 알려드립니다.")

with st.sidebar:
    st.header("⚙️ 설정 및 관리")
    if st.button("🗑️ 이미지 처리 캐시 초기화", help="이전에 변환했던 이미지 캐시(메모리)를 모두 지웁니다."):
        st.cache_data.clear()
        st.success("캐시가 초기화되었습니다!")

uploaded_files = st.file_uploader("이미지 파일을 업로드하세요 (JPG, PNG, JPEG) - 여러 장 선택 가능", type=['jpg', 'jpeg', 'png'], accept_multiple_files=True)

compress_only = st.checkbox("🔄 그림 회전 없이 용량 압축만 하기 (빠른 처리)", value=False, help="이 옵션을 켜면 시간이 오래 걸리는 이미지 회전(OCR) 과정을 생략하고 파일 용량만 빠르게 줄입니다. 업로드 전에 체크하세요.")
use_exif = st.checkbox("스마트폰 기본 회전 정보(EXIF) 적용", value=False, disabled=compress_only, help="OCR 전에 EXIF 방향을 적용합니다. 끄면 원본 픽셀 방향에서 OCR로 판단합니다. 압축 전용 모드는 EXIF를 픽셀에 반영해 원본 표시 방향을 유지합니다.")

@st.cache_data(show_spinner=False, ttl=3600, max_entries=64)
def process_and_cache_image(file_bytes, filename, use_exif, compress_only, processor_revision):
    warnings = []
    processed_bytes, new_filename = process_image(file_bytes, filename, use_exif, compress_only, warnings=warnings)
    return {
        "success": True,
        "processed_bytes": processed_bytes,
        "new_filename": new_filename,
        "warnings": warnings,
        "original_size_kb": len(file_bytes) / 1024,
        "processed_size_kb": len(processed_bytes) / 1024
    }

if uploaded_files:
    st.write(f"총 {len(uploaded_files)}개의 파일이 업로드되었습니다.")
    
    processed_results = []
    
    with st.spinner("이미지를 병렬로 처리하는 중입니다. 잠시만 기다려주세요..."):
        def process_single_file(uploaded_file):
            file_bytes = uploaded_file.getvalue()
            # 캐시된 처리 결과 가져오기
            try:
                result = process_and_cache_image(file_bytes, uploaded_file.name, use_exif, compress_only, processor_revision)
            except Exception as e:
                # 실패는 캐시하지 않아 설치/일시 오류를 해결한 후 재시도할 수 있습니다.
                result = {"success": False, "error": str(e)}
            
            # uploaded_file 객체는 캐시할 수 없으므로 결과 딕셔너리에 따로 추가
            result_copy = result.copy()
            result_copy["uploaded_file"] = uploaded_file
            return result_copy

        # ThreadPoolExecutor를 사용한 병렬 처리
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            # map을 사용하여 업로드된 순서대로 결과를 반환받습니다.
            processed_results = list(executor.map(process_single_file, uploaded_files))

    # 성공적으로 처리된 파일들만 필터링
    successful_results = [res for res in processed_results if res["success"]]
    used_names = set()
    for res in successful_results:
        res["new_filename"] = unique_filename(res["new_filename"], used_names)
    
    # 여러 파일이 성공적으로 처리되었다면 전체 다운로드(ZIP) 버튼 제공
    if len(successful_results) > 1:
        st.write("---")
        st.subheader("📦 전체 파일 다운로드")
        
        # 메모리에 ZIP 파일 생성
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for res in successful_results:
                zip_file.writestr(res["new_filename"], res["processed_bytes"])
        
        zip_buffer.seek(0) # 버퍼의 시작 위치로 이동
        
        st.download_button(
            label=f"💾 {len(successful_results)}개 최적화된 이미지 모두 다운로드 (ZIP)",
            data=zip_buffer,
            file_name="optimized_images.zip",
            mime="application/zip",
            width="stretch"
        )

    # 개별 이미지 결과 출력
    for idx, res in enumerate(processed_results):
        uploaded_file = res["uploaded_file"]
        st.write("---")
        st.subheader(f"파일 {idx+1}: {uploaded_file.name}")
        
        if res["success"]:
            for warning in res["warnings"]:
                st.warning(warning)
            col1, col2 = st.columns(2)
            with col1:
                st.write("### 원본 이미지")
                st.image(uploaded_file, width="stretch")
                st.caption(f"원본 용량: {res['original_size_kb']:.2f} KB")

            with col2:
                st.write("### 처리된 이미지")
                st.image(res["processed_bytes"], width="stretch")
                st.caption(f"변환된 용량: {res['processed_size_kb']:.2f} KB")
                
                # 피드백 메시지
                if res['processed_size_kb'] < res['original_size_kb']:
                    st.success("용량 최적화 성공!")
                else:
                    st.info("이미 최적화된 용량이거나 변환으로 인한 용량 유지.")
                    
                st.download_button(
                    label=f"💾 개별 다운로드 ({res['new_filename']})",
                    data=res["processed_bytes"],
                    file_name=res["new_filename"],
                    mime="image/jpeg",
                    key=f"download_single_{idx}_{res['new_filename']}"
                )
        else:
            st.error(f"이미지 처리 중 오류가 발생했습니다: {res['error']}")
