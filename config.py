import os
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TARGET_FOLDER = os.getenv("TARGET_FOLDER")
REFERENCE_URL = os.getenv("REFERENCE_URL")

# 출력 폴더 설정
OUTPUT_DIR = r"C:\Users\나야\Desktop\블로그\travel_blog_auto\output"
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

MODEL_NAME = "gpt-4o"