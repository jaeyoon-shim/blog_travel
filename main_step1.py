# main_step1.py
from pathlib import Path
from PIL import Image
from PIL.ExifTags import TAGS

PHOTO_DIR = Path("photos")
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "step1_raw.txt"


def extract_exif(image_path: Path) -> dict:
    data = {}
    try:
        img = Image.open(image_path)
        exif = img._getexif()
        if exif:
            for tag_id, value in exif.items():
                tag = TAGS.get(tag_id, tag_id)
                data[tag] = value
    except Exception:
        pass
    return data


print("1️⃣ STEP 1: 사진 데이터 추출 중...")

lines = []

for img_path in sorted(PHOTO_DIR.glob("*.jpg")):
    exif = extract_exif(img_path)

    lines.append(f"[사진] {img_path.name}")
    lines.append(f"- 촬영일: {exif.get('DateTimeOriginal', '알 수 없음')}")
    lines.append(f"- 카메라: {exif.get('Model', '알 수 없음')}")
    lines.append("")

if not lines:
    raise RuntimeError("❌ photos 폴더에 jpg 파일이 없습니다.")

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"✅ STEP 1 완료 → {OUTPUT_FILE}")
