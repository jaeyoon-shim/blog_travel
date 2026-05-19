import time
import os
import pyperclip
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains

# .env 로드
from dotenv import load_dotenv
load_dotenv()

NAVER_ID = os.getenv('NAVER_ID')
NAVER_PW = os.getenv('NAVER_PW')

def clipboard_input(driver, xpath, user_input):
    """클립보드를 이용한 입력 (캡차 우회용)"""
    pyperclip.copy(user_input)
    driver.find_element(By.XPATH, xpath).click()
    
    # Mac은 COMMAND, Windows는 CONTROL 키 사용
    cmd_key = Keys.COMMAND if os.name == 'posix' else Keys.CONTROL
    ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
    time.sleep(1)

def upload_post(title, content):
    """
    네이버 블로그에 접속하여 제목과 본문을 입력하고 발행합니다.
    """
    if not NAVER_ID or not NAVER_PW:
        print("❌ 오류: .env 파일에 NAVER_ID 또는 NAVER_PW가 없습니다.")
        return

    print("🚀 네이버 자동 업로드 프로세스 시작...")
    
    # 크롬 옵션 (자동화 탐지 방지)
    chrome_options = Options()
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.implicitly_wait(10)

    try:
        # 1. 네이버 로그인 페이지 이동
        driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(2)

        # 2. 아이디/비번 입력 (클립보드 방식)
        clipboard_input(driver, '//*[@id="id"]', NAVER_ID)
        clipboard_input(driver, '//*[@id="pw"]', NAVER_PW)
        
        driver.find_element(By.ID, "log.login").click()
        time.sleep(3)

        # (선택) 기기 등록 '등록안함' 클릭
        try:
            driver.find_element(By.ID, "new.dontsave").click()
        except:
            pass

        # 3. 블로그 글쓰기 진입
        print("📝 글쓰기 페이지로 이동합니다...")
        driver.get("https://blog.naver.com/GoBlogWrite.naver")
        time.sleep(5)

        # 4. iframe 전환 (중요!)
        try:
            driver.switch_to.frame("mainFrame")
        except:
            print("⚠️ mainFrame 전환 실패 (또는 이미 전환됨)")

        # 팝업 닫기 (작성 중인 글 취소 등)
        try:
            driver.find_element(By.CSS_SELECTOR, ".se-popup-button-cancel").click()
        except:
            pass

        # 5. 제목 입력
        print(f"📝 제목 입력: {title[:10]}...")
        title_area = driver.find_element(By.XPATH, "//span[contains(text(), '제목')]")
        title_area.click()
        
        pyperclip.copy(title)
        cmd_key = Keys.COMMAND if os.name == 'posix' else Keys.CONTROL
        ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
        time.sleep(1)

        # 6. 본문 입력
        print("📝 본문 입력 중...")
        content_area = driver.find_element(By.CSS_SELECTOR, ".se-main-container")
        content_area.click()
        
        pyperclip.copy(content)
        ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
        time.sleep(3)

        # 7. 발행 버튼 클릭
        print("🚀 발행 버튼 클릭...")
        driver.find_element(By.CLASS_NAME, "publish_btn").click()
        time.sleep(1)
        
        # 최종 발행 (여기서 실제로 올라감)
        driver.find_element(By.CLASS_NAME, "confirm_btn").click()
        
        print("✅ 블로그 포스팅 완료! (5초 후 종료됩니다)")
        time.sleep(5)

    except Exception as e:
        print(f"❌ 업로드 중 에러 발생: {e}")
    finally:
        driver.quit()