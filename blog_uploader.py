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
from dotenv import load_dotenv

load_dotenv()

def clipboard_input(driver, xpath, user_input):
    pyperclip.copy(user_input)
    driver.find_element(By.XPATH, xpath).click()
    cmd_key = Keys.COMMAND if os.name == 'posix' else Keys.CONTROL
    ActionChains(driver).key_down(cmd_key).send_keys('v').key_up(cmd_key).perform()
    time.sleep(1)

def upload_to_naver(title, content):
    nid = os.getenv('NAVER_ID')
    npw = os.getenv('NAVER_PW')
    
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        # 1. 로그인
        driver.get("https://nid.naver.com/nidlogin.login")
        time.sleep(2)
        clipboard_input(driver, '//*[@id="id"]', nid)
        clipboard_input(driver, '//*[@id="pw"]', npw)
        driver.find_element(By.ID, "log.login").click()
        time.sleep(3)

        # 2. 글쓰기 페이지
        driver.get("https://blog.naver.com/GoBlogWrite.naver")
        time.sleep(5)
        
        driver.switch_to.frame("mainFrame")
        
        # 팝업 제거
        try: driver.find_element(By.CSS_SELECTOR, ".se-popup-button-cancel").click()
        except: pass

        # 3. 제목 및 본문 입력
        title_area = driver.find_element(By.XPATH, "//span[contains(text(), '제목')]")
        title_area.click()
        pyperclip.copy(title)
        ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        
        content_area = driver.find_element(By.CSS_SELECTOR, ".se-main-container")
        content_area.click()
        pyperclip.copy(content)
        ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(2)

        # 4. 발행
        driver.find_element(By.CLASS_NAME, "publish_btn").click()
        time.sleep(1)
        driver.find_element(By.CLASS_NAME, "confirm_btn").click()
        print("✅ 네이버 블로그 업로드 완료!")
        
    except Exception as e:
        print(f"❌ 업로드 에러: {e}")
    finally:
        driver.quit()