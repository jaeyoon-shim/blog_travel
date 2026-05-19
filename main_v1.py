from config import (
    RAW_DRAFT_DIR,
    FINAL_DRAFT_DIR,
    MAP_DIR,
)
from organize_photo import organize_photos
from map_generator import generate_map
from draft_writer import write_raw_draft
from rewrite_with_gpt import rewrite_draft

def main():
    travel_folder = "2024.04.19 오사카 교토"
    travel_name = "오사카_교토_3박4일"

    organized_data = organize_photos(travel_folder)

    map_path = generate_map(
        travel_name,
        organized_data,
        MAP_DIR
    )

    raw_draft = write_raw_draft(
        travel_name,
        organized_data,
        map_path,
        RAW_DRAFT_DIR
    )

    final_draft = rewrite_draft(
        raw_draft,
        FINAL_DRAFT_DIR
    )

    print("✅ 블로그 초안 완성")
    print(final_draft)

if __name__ == "__main__":
    main()
