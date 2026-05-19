import streamlit as st
import time
from image_processor import process_image

st.set_page_config(
    page_title="ChangePicture",
    page_icon="📸",
    layout="centered"
)

st.title("📸 ChangePicture")
st.subheader("한글 문서 사진을 자동 회전시키고, 용량을 최적화합니다.")
st.write("이미지를 업로드하면 자동으로 올바른 방향으로 회전하고, 불필요한 메타데이터를 제거하여 1MB 이하의 JPG 파일로 변환합니다.")

uploaded_file = st.file_uploader("이미지 파일을 업로드하세요 (JPG, PNG, JPEG)", type=['jpg', 'jpeg', 'png'])

use_exif = st.checkbox("스마트폰 기본 회전 정보(EXIF) 적용", value=False, help="이 옵션을 끄면 스마트폰 센서가 잘못 기록한 방향 정보를 무시하고 가로 방향을 유지합니다.")

if uploaded_file is not None:
    st.write("---")
    
    col1, col2 = st.columns(2)
    with col1:
        st.write("### 원본 이미지")
        st.image(uploaded_file, use_column_width=True)
        original_size_kb = uploaded_file.size / 1024
        st.caption(f"원본 용량: {original_size_kb:.2f} KB")

    with st.spinner("이미지 처리 중... (방향 교정 및 용량 최적화)"):
        # 파일 바이트 읽기
        file_bytes = uploaded_file.getvalue()
        
        # 처리
        try:
            processed_bytes, new_filename = process_image(file_bytes, uploaded_file.name, use_exif)
            
            with col2:
                st.write("### 처리된 이미지")
                st.image(processed_bytes, use_column_width=True)
                processed_size_kb = len(processed_bytes) / 1024
                st.caption(f"변환된 용량: {processed_size_kb:.2f} KB")
                
                # 피드백 메시지
                if processed_size_kb < original_size_kb:
                    st.success("용량 최적화 성공!")
                else:
                    st.info("이미 최적화된 용량이거나 변환으로 인한 용량 유지.")
                    
                st.download_button(
                    label="💾 최적화된 이미지 다운로드",
                    data=processed_bytes,
                    file_name=new_filename,
                    mime="image/jpeg"
                )
        except Exception as e:
            st.error(f"이미지 처리 중 오류가 발생했습니다: {e}")
