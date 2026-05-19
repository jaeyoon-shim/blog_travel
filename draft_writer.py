import os

OUTPUT_FOLDER = "drafts"
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def write_raw_draft(items, content_name):
    path = os.path.join(OUTPUT_FOLDER, f"{content_name}_raw.txt")
    with open(path, "w", encoding="utf-8") as f:
        for day in items:
            f.write(f"📅 {day['date']} – {day['region']}\n\n")
            for place in day['places']:
                f.write(f"📍 {place['place']}\n")
                for media in place['items']:
                    f.write(f" - [{media['type']}] {media['filename']} ({media['datetime']})\n")
                f.write("\n")
            f.write("\n")
    return path
