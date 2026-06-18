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
        
        # 4. iframe 전환 (대기 로직 추가)
        print("⏳ 에디터 로딩 대기 중...")
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        wait = WebDriverWait(driver, 20)
        try:
            wait.until(EC.frame_to_be_available_and_switch_to_it((By.ID, "mainFrame")))
            print("✅ mainFrame 전환 완료")
        except Exception as e:
            print(f"⚠️ mainFrame 전환 실패: {e}")

        # 팝업 닫기 (여러 종류의 팝업 대응)
        time.sleep(3)
        popups = [".se-popup-button-cancel", ".se-help-guide-close-button", ".se-toolbar-help-close-button"]
        for popup in popups:
            try:
                driver.find_element(By.CSS_SELECTOR, popup).click()
                print(f"✅ 팝업 닫기 완료: {popup}")
                time.sleep(1)
            except:
                pass

        # 5. 제목 입력 (더 견고한 선택자 사용)
        print(f"📝 제목 입력 시작: {title[:10]}...")
        cmd_key = Keys.COMMAND if os.name == 'posix' else Keys.CONTROL
        try:
            title_selectors = [
                (By.CSS_SELECTOR, ".se-documentTitle .se-bare-textarea"),
                (By.XPATH, "//textarea[contains(@placeholder, '제목')]"),
                (By.XPATH, "//span[contains(text(), '제목')]/..")
            ]
            
            title_element = None
            for selector in title_selectors:
                try:
                    title_element = driver.find_element(*selector)
                    if title_element: break
                except: continue
            
            if title_element:
                title_element.click()
                time.sleep(1)
                pyperclip.copy(title)
                ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
                print("✅ 제목 입력 완료")
            else:
                raise Exception("제목 입력 영역을 찾을 수 없습니다.")
        except Exception as e:
            print(f"⚠️ 제목 입력 실패: {e}")

        # 6. 본문 입력
        print("📝 본문 입력 중...")
        try:
            content_selectors = [
                (By.CSS_SELECTOR, ".se-main-container"),
                (By.CSS_SELECTOR, ".se-content"),
                (By.CSS_SELECTOR, ".se-component-content")
            ]
            content_area = None
            for selector in content_selectors:
                try:
                    content_area = driver.find_element(*selector)
                    if content_area: break
                except: continue
            
            if content_area:
                content_area.click()
                time.sleep(1)
                pyperclip.copy(content)
                ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
                print("✅ 본문 입력 완료")
                time.sleep(3)
            else:
                print("⚠️ 본문 입력 영역을 찾지 못했습니다.")
        except Exception as e:
            print(f"⚠️ 본문 입력 실패: {e}")

        # 7. 발행 버튼 클릭 (중요: iframe 밖으로 빠져나가야 함)
        print("🚀 발행 버튼 클릭 시도...")
        driver.switch_to.default_content() # iframe 탈출
        time.sleep(1)
        
        try:
            # 발행 버튼 클릭
            publish_btn = driver.find_element(By.CLASS_NAME, "publish_btn")
            publish_btn.click()
            time.sleep(2)
            
            # 최종 확인 버튼 클릭
            confirm_btn = driver.find_element(By.CLASS_NAME, "confirm_btn")
            confirm_btn.click()
            
            print("✅ 블로그 포스팅 완료! (5초 후 종료됩니다)")
            time.sleep(5)
        except Exception as e:
            print(f"❌ 발행 버튼 클릭 실패: {e}")
            print("💡 수동으로 '발행' 버튼을 눌러주세요.")
            time.sleep(10) # 수동 조치 시간 제공

    except Exception as e:
        print(f"❌ 업로드 중 에러 발생: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    # 최종 원고 파일 경로
    FINAL_POST_PATH = os.path.join("output", "step3_final.md")
    
    if not os.path.exists(FINAL_POST_PATH):
        print(f"❌ 오류: 최종 원고 파일({FINAL_POST_PATH})이 없습니다. STEP 3를 먼저 실행하세요.")
    else:
        with open(FINAL_POST_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if not lines:
            print("❌ 오류: 원고 내용이 비어 있습니다.")
        else:
            # 첫 번째 줄을 제목으로 사용 (보통 # 제목 형식)
            title = lines[0].strip().replace("# ", "").replace("#", "")
            # 나머지를 본문으로 사용
            content = "".join(lines[1:]).strip()
            
            if not title:
                title = "나의 여행 기록"
                
            upload_post(title, content)