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

        # 5. 제목 입력 및 본문으로 이동 (Tab 활용)
        print(f"📝 제목 입력 시작: {title[:10]}...")
        cmd_key = Keys.COMMAND if os.name == 'posix' else Keys.CONTROL
        try:
            # 제목 영역 클릭 시도
            title_selectors = [
                (By.CSS_SELECTOR, ".se-documentTitle .se-bare-textarea"),
                (By.XPATH, "//textarea[contains(@placeholder, '제목')]"),
                (By.CSS_SELECTOR, ".se-placeholder.se-ff-nanumbarungothic") # 제목 플레이스홀더
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
                
                # 제목 입력
                pyperclip.copy(title)
                ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
                print("✅ 제목 입력 완료")
                time.sleep(1)
                
                # Tab 키를 눌러 본문 영역으로 이동 (가장 확실함)
                print("⌨️ Tab 키로 본문 이동 중...")
                ActionChains(driver).send_keys(Keys.TAB).perform()
                time.sleep(1)
                
                # 기존 내용 삭제 (Ctrl+A -> Backspace)
                ActionChains(driver).key_down(cmd_key).send_keys('a').key_up(cmd_key).send_keys(Keys.BACKSPACE).perform()
                time.sleep(1)
                
                # 본문 입력
                print("📝 본문 내용 붙여넣기 중...")
                pyperclip.copy(content)
                ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
                print("✅ 본문 입력 완료")
                time.sleep(3)
            else:
                raise Exception("제목 영역을 찾을 수 없습니다.")
        except Exception as e:
            print(f"⚠️ 에디터 입력 실패: {e}")

        # 7. 발행 버튼 클릭 (iframe 밖으로 빠져나가야 함)
        print("🚀 발행 프로세스 시작...")
        driver.switch_to.default_content() # iframe 탈출
        time.sleep(1)
        
        try:
            # 1) '발행' 버튼 찾기 및 클릭
            publish_selectors = [
                (By.CLASS_NAME, "publish_btn"),
                (By.XPATH, "//button[contains(., '발행')]"),
                (By.CSS_SELECTOR, "button.publish_btn")
            ]
            
            publish_btn = None
            for selector in publish_selectors:
                try:
                    publish_btn = driver.find_element(*selector)
                    if publish_btn: break
                except: continue
                
            if publish_btn:
                publish_btn.click()
                print("✅ 1단계 발행 버튼 클릭 완료")
                time.sleep(2)
                
                # 2) 최종 '발행' 버튼 클릭 (팝업 내)
                confirm_btn = driver.find_element(By.XPATH, "//button[contains(@class, 'confirm_btn') or contains(., '발행')]")
                confirm_btn.click()
                print("✅ 최종 발행 완료!")
            else:
                print("⚠️ 발행 버튼을 찾지 못했습니다. 수동으로 눌러주세요.")
            
            print("✨ 모든 작업이 완료되었습니다! (5초 후 종료)")
            time.sleep(5)
        except Exception as e:
            print(f"❌ 최종 발행 중 오류: {e}")
            print("💡 본문은 입력되었으니 수동으로 '발행' 버튼을 눌러 마무리해주세요.")
            time.sleep(10)

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