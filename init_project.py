import os

BASE_DIR = "travel_blog_auto"

dirs = [
    "input/mybox_photos",
    "output/drafts",
    "metadata",
    "location",
    "content",
    "style",
    "prompts",
]

files = {
    "metadata/exif_parser.py": "",
    "location/reverse_geocode.py": "",
    "content/route_builder.py": "",
    "content/wiki_summary.py": "",
    "content/photo_story.py": "",
    "style/style_extractor.py": "",
    "prompts/region_intro.txt": "",
    "prompts/route_intro.txt": "",
    "prompts/photo_story.txt": "",
    "main.py": "",
    "requirements.txt": ""
}

def main():
    os.makedirs(BASE_DIR, exist_ok=True)

    for d in dirs:
        os.makedirs(os.path.join(BASE_DIR, d), exist_ok=True)

    for path, content in files.items():
        full_path = os.path.join(BASE_DIR, path)
        if not os.path.exists(full_path):
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)

    print("✅ travel_blog_auto 프로젝트 구조 생성 완료")

if __name__ == "__main__":
    main()
