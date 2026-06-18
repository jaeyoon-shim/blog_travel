import os
import json
import time
from pathlib import Path
from tqdm import tqdm
from organize_photo import process_files
from rewrite_with_gpt import draft_step2_logic, rewrite_draft
from main import upload_post

def progress_bar(desc, duration=2):
    """시각적인 진행 바 시뮬레이션 (API 호출 등에서 사용)"""
    for _ in tqdm(range(100), desc=desc, bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt}"):
        time.sleep(duration / 100)

def main():
    print("\n" + "="*60)
    print("   🌟 여행 블로그 자동화 통합 시스템 (V1.5) 🌟")
    print("="*60)
    
    # 1. 탐색형 폴더 선택 시스템
    print("\n[Step 1] 여행 사진 폴더 탐색 및 선택")
    root_path = Path(r"C:\Users\나야\Desktop\블로그\mybox")
    current_path = root_path
    
    if not root_path.exists():
        print(f"❌ 오류: 루트 폴더를 찾을 수 없습니다 -> {root_path}")
        return

    while True:
        # 하위 폴더 목록 가져오기 (수정일 순 정렬)
        subdirs = [d for d in current_path.iterdir() if d.is_dir()]
        subdirs.sort(key=os.path.getmtime, reverse=True)

        print(f"\n📂 현재 위치: {current_path}")
        print("-" * 50)
        if current_path != root_path:
            print(f" [ 0] ⬅️  .. (상위 폴더로 이동)")
        
        print(f" [ S] ✅ 현재 폴더 선택: '{current_path.name}' 분석 시작")
        
        for i, folder in enumerate(subdirs, 1):
            print(f" [{i:2d}] 📁 {folder.name}")
        print("-" * 50)

        choice = input("👉 번호 입력(이동) 또는 'S' 입력(선택): ").strip().upper()

        if choice == 'S':
            folder_path = str(current_path)
            print(f"\n🚀 선택 완료: {current_path.name} 폴더 분석을 시작합니다.")
            break
        elif choice == '0' and current_path != root_path:
            current_path = current_path.parent
        else:
            try:
                choice_idx = int(choice)
                if 1 <= choice_idx <= len(subdirs):
                    current_path = subdirs[choice_idx - 1]
                else:
                    print("⚠️  잘못된 번호입니다.")
            except ValueError:
                print("⚠️  번호를 입력하거나 'S'를 입력해주세요.")

    start_time = time.time()

    # 2. 사진 분석 및 메타데이터 추출 (tqdm 이미 내장됨)
    print("\n[Step 2] 사진 및 위치 데이터 분석")
    metadata_items = process_files(folder_path)

    # 3. 블로그 초안 생성
    print("\n[Step 3] AI 감성 초안 생성")
    progress_bar("🤖 GPT 초안 작성 중...", 3)
    raw_draft = draft_step2_logic(metadata_items)
    
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    raw_draft_path = output_dir / "step2_draft.md"
    with open(raw_draft_path, "w", encoding="utf-8") as f:
        f.write(raw_draft)

    # 4. 최종 원고 생성
    print("\n[Step 4] 위키 정보 및 SEO 최적화 반영")
    progress_bar("✍️ 최종 원고 리라이팅 중...", 5)
    final_post_path = output_dir / "step3_final.md"
    final_post = rewrite_draft(raw_draft_path, final_post_path)

    end_time = time.time()
    elapsed_time = end_time - start_time

    # 5. 작업 완료 알림 및 업로드 선택
    print("\n" + "✨"*30)
    print(f"✅ 모든 분석 및 원고 작성이 완료되었습니다! (소요시간: {elapsed_time:.1f}초)")
    print(f"📄 최종 원고: {final_post_path}")
    print("✨"*30)
    
    print("\n지금 바로 네이버 블로그에 업로드를 진행할까요? (y/n)")
    choice = input("👉 입력: ").strip().lower()

    if choice == 'y':
        with open(final_post_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        if lines:
            title = lines[0].strip().replace("# ", "").replace("#", "")
            content = "".join(lines[1:]).strip()
            print("\n[Step 5] 네이버 블로그 자동 업로드 시작")
            upload_post(title, content)
        else:
            print("❌ 오류: 원고 내용이 비어 있습니다.")
    else:
        print("\n👋 작업을 종료합니다. 다음 여행 때 만나요!")

if __name__ == "__main__":
    main()
