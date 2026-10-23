"""端到端验证：在「编辑提问」对话框里粘贴/添加新图片，重发时与原文一起带上。

用法：
    python e2e-paste-image.py [base]

流程：
    1. 新建会话，上传图片 A 提问，等该轮完成；
    2. 打开该轮「编辑提问」，用粘贴（ClipboardEvent）补充图片 B，确认缩略图出现；
    3. 提交（保留原会话），检查新会话的首条用户消息里有 2 张图；
    4. 打印插件日志与页面错误。
"""
import base64
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = "http://127.0.0.1:51211/"
for arg in sys.argv[1:]:
    if arg.startswith("http"):
        BASE = arg
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")
SHOTS = ROOT / "shots"
IMAGE_A = SHOTS / "sample-image.png"
IMAGE_B = SHOTS / "sample-image-b.png"
TEXT = "粘贴补充图片自检：请只回复两个字：收到"

PASTE_JS = r"""
async (payload) => {
  const binary = atob(payload.base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const file = new File([bytes], payload.name, { type: 'image/png' });
  const transfer = new DataTransfer();
  transfer.items.add(file);
  const area = document.querySelector('div[role=dialog] textarea');
  if (area === null) return { ok: false, reason: 'no textarea' };
  area.focus();
  const event = new ClipboardEvent('paste', { bubbles: true, cancelable: true });
  Object.defineProperty(event, 'clipboardData', { value: transfer });
  area.dispatchEvent(event);
  await new Promise((resolve) => setTimeout(resolve, 800));
  return { ok: true, thumbnails: document.querySelectorAll('div[role=dialog] img[src^="data:"]').length };
}
"""


def cookie_pair():
    out = subprocess.run(
        [NODE, str(HERE / "auth-cookie.mjs"), AUTHORITY], capture_output=True, text=True, check=True
    ).stdout.strip()
    return out.split("=", 1)


def shot(page, name: str) -> None:
    SHOTS.mkdir(exist_ok=True)
    page.screenshot(path=str(SHOTS / f"{name}.png"))
    print(f"  screenshot: shots/{name}.png")


def boot(page) -> None:
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("[contenteditable=true], textarea", timeout=90000)
    page.wait_for_timeout(3000)
    modal = page.query_selector("div[role=presentation]")
    if modal is not None:
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)


def edit_buttons(page):
    return [b for b in page.query_selector_all("button") if "编辑提问" in (b.inner_text() or "")]


def wait_completed(page, turns: int, timeout: int = 240000) -> bool:
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        text = page.evaluate("() => document.body.innerText || ''")
        if f"{turns} 轮" in text and len(edit_buttons(page)) >= turns:
            return True
        page.wait_for_timeout(2000)
    return False


def new_session(page) -> None:
    for element in page.query_selector_all("button"):
        if "新会话" in (element.inner_text() or ""):
            element.click()
            page.wait_for_timeout(1500)
            return
    raise RuntimeError("新会话 button not found")


def send(page, text: str) -> None:
    composer = page.wait_for_selector("[contenteditable=true]", timeout=30000)
    composer.click()
    page.keyboard.type(text)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def main() -> None:
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        console: list[str] = []
        errors: list[str] = []
        page.on("console", lambda msg: console.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: errors.append(str(err)))
        boot(page)
        print("1) new session + question with image A")
        new_session(page)
        page.set_input_files("input[type=file]", str(IMAGE_A))
        page.wait_for_timeout(2000)
        send(page, TEXT)
        print(f"  turn 1 completed: {wait_completed(page, 1)}")
        page.wait_for_timeout(1200)
        print("2) open editor + paste image B")
        button = edit_buttons(page)[-1]
        button.scroll_into_view_if_needed()
        button.hover()
        page.wait_for_timeout(300)
        button.click()
        page.wait_for_selector("div[role=dialog]", timeout=15000)
        page.wait_for_timeout(600)
        payload = {"base64": base64.b64encode(IMAGE_B.read_bytes()).decode(), "name": "pasted.png"}
        result = page.evaluate(PASTE_JS, payload)
        print(f"  paste result: {result}")
        shot(page, "e2e-paste-01-dialog")
        print("3) submit")
        dialog = page.query_selector("div[role=dialog]")
        for element in dialog.query_selector_all("button"):
            if "丢弃后续并重发" in (element.inner_text() or ""):
                element.click()
                break
        page.wait_for_timeout(20000)
        shot(page, "e2e-paste-02-after-submit")
        images = page.evaluate(
            """() => [...document.querySelectorAll('[data-chat-flow-kind="user"] img')].length"""
        )
        print(f"  new session user images: {images}")
        body = page.evaluate("() => (document.body.innerText || '').slice(0, 600)")
        print(f"  body head: {body[:300]!r}")
        print("--- plugin console ---")
        for line in console:
            if "dsh-edit-question" in line:
                print(line)
        print("--- page errors ---")
        for line in errors:
            print(line)
        browser.close()


if __name__ == "__main__":
    main()
