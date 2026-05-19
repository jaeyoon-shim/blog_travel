import requests
from bs4 import BeautifulSoup
from openai import OpenAI
import config
from collections import defaultdict

client = OpenAI(api_key=config.OPENAI_API_KEY)

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
        [권장 구성]: 제목 -> 여행 경로 요약(지도) -> 장소별 [사진+글] 반복 -> 마무리 총평/팁
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
    
    prompt = f"""
    당신은 네이버 블로그 여행 인플루언서입니다. 제공된 초안을 바탕으로 '상위 10개 블로그의 구성'을 모방하여 최종 원고를 작성하세요.

    [포스팅 구성 가이드]
    - 도입부: 여행의 동기와 설레는 감정 전달
    - 요약 섹션: 이번 {region} 여행의 전체 경로를 한눈에 보여주는 텍스트 요약
    - 본문: [사진:파일명] -> 해당 사진에 대한 다정한 설명 -> [장소 지도 정보] 형태의 흐름 유지
    - 마무리: 여행 꿀팁과 다음 여행을 기약하는 인사

    [SEO 및 구성 데이터]
    {seo_info}

    [초안 내용]
    {raw_draft}
    """

    response = client.chat.completions.create(
        model=config.MODEL_NAME,
        messages=[{"role": "system", "content": "다정한 구어체(~했어요)를 사용하며 네이버 블로그 최적화 구성을 잘 지키는 인플루언서입니다."},
                  {"role": "user", "content": prompt}],
        temperature=0.8
    )
    return response.choices[0].message.content