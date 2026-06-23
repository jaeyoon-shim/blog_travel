# Lessons Learned

프로젝트 작업 중 얻은 교훈과 미적용 백로그. (전역 규칙: 에이전트 실수/교훈은 여기 기록)

---

## 2026-06-22 ~ 06-24 — 무료 모드 전환 + 발행 검증

### 교훈

1. **외부 발행의 공개설정은 "안전 기본값"이어야 한다 (안전 버그)**
   - `_set_visibility`의 `vis_map`이 영문 키(`private`/`public`)만 인식했는데, 앱 기본값은 한글 `"비공개"` → 매핑 실패 → 폴백이 **`전체공개`**(공개!)였다.
   - 즉 사용자가 "비공개"를 골라도 **전체공개로 발행**되는 사고 위험.
   - **교훈**: 되돌리기 어려운 외부 작업(발행 등)에서 알 수 없는 입력은 **가장 안전한 값(비공개)** 으로 폴백. 기본값을 절대 "공개"로 두지 말 것. → `_visibility_target()`로 추출 + 한글/영문 인식 + unknown→비공개.

2. **폴백 경로는 주 경로와 "동일한 데이터 계약"을 채워야 한다 (무료 모드의 조용한 품질 저하)**
   - Google Maps → Nominatim 폴백 시 `_nominatim_geocode`가 `city/region/country`를 안 채워(`_google_geocode`는 채움) → 지역 감지 실패 → 위키 박스가 "홋카이도 삿포로" 환각.
   - 또 POI 확정 시 번역 스킵 로직이 "Google Places=한글명" 전제 → Nominatim 원문 일본어(`篠崎八幡神社`)가 제목/본문 누출.
   - **교훈**: 폴백을 추가하면, 폴백이 반환하는 dict가 주 경로와 **같은 필드 계약**을 만족하는지, 그리고 그 값을 소비하는 **모든 다운스트림**을 점검할 것.

3. **LLM에 "개수 할당"을 강요하면 환각한다**
   - 위키 박스 프롬프트의 `specialties/foods/spots 각 3~5개`가 환각 주원인(개수 채우려 인접지 명소를 지어냄).
   - **교훈**: `0~N개, 확실한 것만, 없으면 빈 배열` + `temperature=0`. 개수 하한을 두지 말 것.

4. **Windows cp949 콘솔에서 이모지 로그 크래시** (미해결, 백로그 #6)
   - `logger.info("✅ ...")` / `print("🔬 ...")`가 `UnicodeEncodeError`로 스크립트를 죽인다.
   - 임시 회피: 스크립트 진입부 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.

5. **네트워크/Selenium 로직에서 순수 결정 부분을 staticmethod로 추출 → 유닛테스트**
   - `_pick_admin`(주소→행정구역), `_dedupe_separators`(구분선 정규화), `_visibility_target`(공개설정 매핑) 추출로 네트워크 없이 회귀 테스트 가능해짐. `tests/test_quality.py` 관례 활용.

### 검증된 사실
- 무료 모드(Google 키 비활성화)에서 전체 파이프라인 정상 + 실제 네이버 **비공개 발행 성공**.
- 자동 로그인은 네이버 보안에 막힘 → `selenium_profile` 세션 + 수동 로그인 폴백(180초)으로 통과. 한 번 로그인하면 세션 저장.

### 미적용 백로그
- **#4 무료 모드 가시성**: 무료 모드일 때 로그 배너 + UI에 "상호명 정확도 낮음, 검수 권장" 노출. (지금은 조용히 품질 저하)
- **#6 로그 인코딩**: 로깅 핸들러/스트림에 UTF-8 + `errors="replace"` 적용 (Windows 안정성).
- **리팩터**: "장소 이름 해석" 책임이 6개 메서드(`_nominatim_geocode`/`_google_geocode`/`_make_place_name`/`_translate_to_korean`/`_koreanize_region`/`_detect_region`)에 분산. `core.py` 2,600줄 God-class 2개. AI 작업 전 `/refactor-audit` 권장.
- 상세 리뷰: `docs/reviews/2026-06-22-free-mode-review.md`
