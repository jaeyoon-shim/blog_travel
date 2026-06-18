# 여행 블로그 자동화 프로젝트 (Travel Blog Auto) 기능명세 및 구조

이 프로젝트는 여행 사진의 메타데이터(EXIF)를 추출하고, 이를 기반으로 GPT를 활용하여 네이버 블로그 포스팅을 자동 생성 및 업로드하는 도구입니다.

## 1. 주요 기능 (Key Features)

### 1단계: 사진 분석 및 메타데이터 추출 (`organize_photo.py`, `exif_utils.py`, `location_resolver.py`)
- **EXIF 추출**: 사진 파일에서 촬영 일시, 기종, GPS 좌표 추출.
- **위치 역지오코딩 (Reverse Geocoding)**: GPS 좌표를 기반으로 실제 장소명(한글/현지어 병기)과 지역 정보 획득.
- **데이터 구조화**: 분석된 데이터를 `metadata.json`으로 저장.

### 2단계: 블로그 초안 생성 (`rewrite_with_gpt.py` - `draft_step2_logic`)
- **데이터 그룹화**: 날짜별, 시간순으로 사진과 장소 정보를 그룹화.
- **감성적 서사 부여**: GPT-4o-mini를 사용하여 장소별 특징과 분위기를 상상한 감성적인 초안 작성.
- **이미지 배치**: 본문의 적절한 위치에 `[사진:파일명]` 태그 삽입.

### 3단계: SEO 최적화 및 최종 원고 작성 (`rewrite_with_gpt.py` - `final_rewrite_step3`)
- **상위 블로그 분석**: 네이버 검색 결과 상위 블로그의 제목 패턴과 구성을 실시간 분석하여 가이드 주입.
- **최종 리라이팅**: 분석된 SEO 패턴을 적용하여 도입부, 요약, 본문(사진+설명+지도), 마무리 꿀팁으로 구성된 최종 원고 생성.

### 4단계: 네이버 블로그 자동 업로드 (`blog_uploader.py`, `main.py`)
- **셀레늄(Selenium) 자동화**: 네이버 로그인 및 글쓰기 페이지 진입.
- **캡차 우회**: 클립보드 복사-붙여넣기 방식을 사용하여 자동 로그인 및 내용 입력.
- **자동 발행**: 제목과 본문을 입력하고 실제 발행 버튼까지 자동 클릭.

---

## 2. 프로젝트 구조 (Directory Structure)

```text
C:\Users\나야\Desktop\블로그\travel_blog_auto\
├── main.py                 # 실행 메인 스크립트 (통합 및 업로드 담당)
├── main_step1~3.py         # 단계별 개별 실행 테스트용 스크립트
├── blog_uploader.py        # 네이버 블로그 업로드 로직 (Selenium)
├── rewrite_with_gpt.py     # GPT 연동 초안 및 최종 원고 생성 로직
├── location_resolver.py    # Geopy 기반 주소 변환
├── exif_utils.py           # 사진 EXIF 데이터 추출 유틸
├── organize_photo.py       # 사진 분석 프로세스 총괄
├── config.py / .env        # API 키 및 로그인 정보 관리
├── requirements.txt        # 필요 라이브러리 목록
│
├── input/                  # 원본 사진 파일 저장 (mybox_photos/)
├── output/                 # 중간 결과물 및 최종 원고 저장 (.md, .json, .txt)
├── metadata/               # 분석된 메타데이터 저장
├── drafts/                 # 생성된 초안 파일 보관
├── prompts/                # GPT 페르소나 및 프롬프트 관리 (예정)
└── style/                  # 블로그 스타일 가이드 (예정)
```

---

## 3. 워크플로우 (Workflow)

1.  **사진 준비**: `input/mybox_photos` 폴더에 여행 사진 업로드.
2.  **분석 실행**: `organize_photo.py` 실행 → `metadata.json` 생성.
3.  **초안 및 원고 생성**: GPT를 통해 감성 초안 및 SEO 최적화 원고 생성 (MD 파일).
4.  **자동 업로드**: `main.py` 실행 → 네이버 로그인 후 최종 원고 내용을 본문에 입력 및 발행.

---

## 4. 설정 사항 (Configuration)

- **.env**: `NAVER_ID`, `NAVER_PW`, `OPENAI_API_KEY` 설정 필수.
- **config.py**: OpenAI 모델명 (`gpt-4o` 등) 및 기타 상수 관리.
