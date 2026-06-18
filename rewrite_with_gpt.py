import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import config
from collections import defaultdict

client = OpenAI(api_key=config.OPENAI_API_KEY)

def get_reference_style(url):
    """참고 URL에서 문체 샘플 추출"""
    if not url:
        return "다정한 구어체 (~했어요, ~였답니다)"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        # 네이버 블로그 특수 처리
        if "blog.naver.com" in url:
            if "PostView" not in url:
                res = requests.get(url, headers=headers, timeout=5)
                soup = BeautifulSoup(res.text, 'html.parser')
                iframe = soup.find('iframe', id='mainFrame')
                if iframe:
                    url = "https://blog.naver.com" + iframe['src']
            
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            content = soup.select_one('.se-main-container') or soup.select_one('#postViewArea')
            text = content.get_text(separator=' ', strip=True) if content else soup.get_text()
        else:
            res = requests.get(url, headers=headers, timeout=5)
            soup = BeautifulSoup(res.text, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            
        return text[:1500] # 문체 분석을 위해 충분한 양 추출
    except Exception as e:
        print(f"⚠️ 문체 분석용 페이지 접속 실패: {e}")
        return "다정한 구어체 (~했어요, ~였답니다)"

def get_wiki_info(region):
    """특정 지역에 대한 핵심 위키 정보 생성 (요약, 특산물, 명물, 관광지)"""
    prompt = f"""
    {region}에 대한 핵심 여행 정보를 다음 형식으로 정리해 주세요.
    결과는 반드시 한국어로 작성하고, 네이버 블로그 포스팅 최상단에 들어갈 정보성 박스임을 고려하세요.

    [형식]
    ### 📍 {region} 여행 전 꼭 알아야 할 핵심 정보
    - **지역 소개**: (5줄 내외의 요약 설명)
    - **주요 특산품/특산물**: (대표적인 것 3-5개)
    - **명물/추천 먹거리**: (꼭 먹어봐야 할 음식 3-5개)
    - **대표 관광지**: (가장 유명한 명소 3-5개)
    """

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "친절한 여행 백과사전이자 가이드입니다."},
                  {"role": "user", "content": prompt}],
        temperature=0.5
    )
    return response.choices[0].message.content

def analyze_naver_structure(region):
    """네이버 상위 블로그의 제목 및 포스팅 구성 패턴 분석"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    search_url = f"https://search.naver.com/search.naver?query={region}+여행+코스+후기"
    
    try:
        res = requests.get(search_url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        titles = [t.get_text() for t in soup.select('.api_txt_lines.total_tit')[:10]]
        
        # 기획안에 따른 권장 구성 가이드 주입
        structure_hint = f"""
        [상위 노출 제목 패턴]: {', '.join(titles)}
        [권장 구성]: 지역 소개(위키) -> 제목 -> 도입부 -> 여행 경로 요약(지도) -> 장소별 [사진+글] 반복 -> 동영상/꿀팁 -> 마무리 총평
        """
        return structure_hint
    except:
        return "제목: [지역] 여행 코스 완벽 정리, 구성: 사진과 글의 조화로운 배치"

def draft_step2_logic(metadata_items):
    """날짜별/장소별 그룹화 및 리뷰 서사 생성"""
    daily_data = defaultdict(list)
    for item in metadata_items:
        date_part = item.get('date', '날짜미상').split(' ')[0]
        daily_data[date_part].append(item)

    full_timeline_text = ""
    for i, date in enumerate(sorted(daily_data.keys()), 1):
        full_timeline_text += f"\n### [Day {i} : {date}]\n"
        for entry in daily_data[date]:
            full_timeline_text += f"- 장소: {entry['place']} | 시간: {entry.get('date','').split(' ')[1]} | 지역: {entry['region']}\n"
            full_timeline_text += f"  (이미지: {entry['filename']})\n"

    prompt = f"""
    당신은 여행의 모든 순간을 기록하는 감성 여행 작가입니다. 
    다음 사진 데이터를 바탕으로 풍성한 여행 초안을 작성하세요.

    [작성 규칙]
    1. 모든 장소명은 반드시 '한글명 (원문명)' 형식을 지킬 것.
    2. 데이터에 기반하여 해당 장소의 특징과 예상되는 리뷰(분위기, 맛, 풍경 등)를 상상하여 감성적으로 서술할 것.
    3. 사진 파일명을 본문의 적절한 위치에 [사진:파일명] 형태로 삽입할 것.

    [사진 데이터]
    {full_timeline_text}
    """
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "풍성한 서사와 한글/원문 병기가 핵심인 여행 에세이 작가입니다."},
                  {"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message.content

def final_rewrite_step3(raw_draft, region):
    """네이버 블로그 상위 10개 구성 모방 및 최종 문체 적용"""
    seo_info = analyze_naver_structure(region)
    wiki_info = get_wiki_info(region)
    
    # [추가] 참고 문체 분석 (config.REFERENCE_URL 사용)
    style_sample = get_reference_style(config.REFERENCE_URL)
    
    prompt = f"""
    당신은 네이버 블로그 여행 인플루언서입니다. 제공된 초안을 바탕으로 '상위 10개 블로그의 구성'을 모방하여 최종 원고를 작성하세요.
    특히, 아래 [참고 문체 스타일]을 분석하여 말투, 종결어미, 단어 선택 등을 최대한 비슷하게 복제하여 작성해 주세요.

    [참고 문체 스타일]
    {style_sample}

    [포스팅 구성 가이드]
    1. 최상단: {region} 위키 정보 섹션 (제공된 wiki_info 활용)
    2. 도입부: 여행의 동기와 설레는 감정 전달
    3. 요약 섹션: 이번 {region} 여행의 전체 경로를 한눈에 보여주는 텍스트 요약
    4. 본문: [사진:파일명] -> 해당 사진에 대한 다정한 설명 -> [장소 지도 정보] 형태의 흐름 유지 (최소 5회 이상 반복)
    5. 중간/후반: [동영상 삽입 위치 추천] - 여행의 현장감을 느낄 수 있는 동영상을 넣으면 좋은 위치에 표시
    6. 마무리: 여행 꿀팁과 다음 여행을 기약하는 인사

    [SEO 및 구성 데이터]
    {seo_info}

    [지역 위키 정보]
    {wiki_info}

    [초안 내용]
    {raw_draft}
    """

    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[{"role": "system", "content": "제공된 참고 문체를 완벽하게 모방하여 작성하는 네이버 블로그 여행 전문 작가입니다."},
                  {"role": "user", "content": prompt}],
        temperature=0.8
    )
    return response.choices[0].message.content

def rewrite_draft(input_path, output_path):
    """main_step3.py 등에서 호출하는 통합 리라이팅 함수"""
    from pathlib import Path
    import json
    import re

    input_path = Path(input_path)
    output_path = Path(output_path)

    if not input_path.exists():
        print(f"❌ 오류: 입력 파일 {input_path}이 없습니다.")
        return

    # metadata.json에서 지역 정보 가져오기
    region = "일본 여행" # 기본값
    try:
        with open("metadata.json", "r", encoding="utf-8") as f:
            metadata = json.load(f)
            # '지역 미정' 및 '위치 정보 오류' 필터링
            exclude_terms = ["지역 미정", "위치 정보 오류", "장소 미정", "위치 정보 미정"]
            regions = [item['region'] for item in metadata if item['region'] not in exclude_terms]

            if regions:
                from collections import Counter
                region = Counter(regions).most_common(1)[0][0]
            else:
                # 메타데이터에 지역 정보가 없으면 사진 파일 경로에서 폴더명 추출 시도
                first_file = metadata[0]['file'] if metadata else ""
                if first_file:
                    # 폴더 구조에서 지역명으로 추측되는 단어 추출 (예: '2024.05 사가' -> '사가')
                    match = re.search(r'([가-힣]{2,})', Path(first_file).parent.name)
                    if match:
                        region = match.group(1)
    except:
        pass

    with open(input_path, "r", encoding="utf-8") as f:
        raw_draft = f.read()

    print(f"📝 {region} 기반으로 최종 원고 생성 중...")
    final_post = final_rewrite_step3(raw_draft, region)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_post)

    return final_post