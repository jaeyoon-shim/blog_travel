# main_step3.py
from pathlib import Path
from rewrite_with_gpt import rewrite_draft

INPUT_FILE = Path("output/step2_draft.md")
OUTPUT_FILE = Path("output/step3_final.md")

if not INPUT_FILE.exists():
    raise RuntimeError("❌ STEP 2 결과(step2_draft.md)가 없습니다.")

print("3️⃣ STEP 3: GPT 블로그 최적화 중...")

rewrite_draft(INPUT_FILE, OUTPUT_FILE)

print(f"✅ STEP 3 완료 → {OUTPUT_FILE}")
