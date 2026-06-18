from PIL import Image
import win32clipboard
import io

# 테스트할 이미지 경로를 넣어주세요
img = Image.open(r"D:\project\blog_writer2\logs\debug\tistory_write_page_1771823556.png")
output = io.BytesIO()
img.convert("RGB").save(output, "BMP")
data = output.getvalue()[14:]

win32clipboard.OpenClipboard()
win32clipboard.EmptyClipboard()
win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
win32clipboard.CloseClipboard()

print("클립보드에 이미지 복사 완료! 네이버 블로그에서 Ctrl+V 해보세요")