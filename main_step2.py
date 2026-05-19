# main_step2.py
from pathlib import Path

INPUT_FILE = Path("output/step1_raw.txt")
OUTPUT_FILE = Path("output/step2_draft.md")

if not INPUT_FILE.exists():
    raise RuntimeError("❌ STEP 1 결과(step1_raw.txt)가 없습니다.")

print("2️⃣ STEP 2: 여행 초안 생성 중...")

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    raw = f.read()

draft = f"""# 사가 여행 3박 4일 기록 (초안)

이번 여행은 사진을 따라 하루씩 정리해봤다.

## 사진 기반 여행 기록

{raw}

## 느낀 점
사진을 다시 보니 그때의 공기와 분위기가 다시 떠오른다.
"""

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write(draft)

print(f"✅ STEP 2 완료 → {OUTPUT_FILE}")
