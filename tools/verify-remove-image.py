"""回归验证：在编辑对话框里删掉原图后，重发的新会话不再带这张图。

这条路径容易只改到 UI 而漏掉提交逻辑，所以单独验：
    1. 新建会话，上传一张图并提问；
    2. 打开「编辑提问」，确认原图缩略图出现；
    3. 点掉那张缩略图的 ×，确认缩略图消失；
    4. 提交，检查新会话的首条用户消息里图片数为 0。

用法：
    python verify-remove-image.py [base]
"""

import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = "http://127.0.0.1:63246/"
for arg in sys.argv[1:]:
    if arg.startswith("http"):
        BASE = arg
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")
SHOTS = ROOT / "shots"
IMAGE = SHOTS / "sample-image.png"
TEXT = "删除原图回归：请只回复两个字：收到"


def cookie_pair():
    out = subprocess.run(
        [NODE, str(HERE / "auth-cookie.mjs"), AUTHORITY], capture_output=True, text=True, check=True
    ).stdout.strip()
    return out.split("=", 1)


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


def thumbs(page) -> int:
    return page.evaluate("""() => document.querySelectorAll('div[role=dialog] img[src^="data:"]').length""")


def main() -> None:
    name, value = cookie_pair()
    failures: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        boot(page)
        new_session(page)
        page.set_input_files("input[type=file]", str(IMAGE))
        page.wait_for_timeout(2000)
        composer = page.wait_for_selector("[contenteditable=true]", timeout=30000)
        composer.click()
        page.keyboard.type(TEXT)
        page.wait_for_timeout(300)
        page.keyboard.press("Enter")
        print(f"1) turn completed: {wait_completed(page, 1)}")
        sent = page.evaluate("""() => document.querySelectorAll('[data-chat-flow-kind="user"] img').length""")
        print(f"   images in the sent message: {sent}")
        if sent < 1:
            failures.append("uploaded image did not land in the message")

        button = edit_buttons(page)[-1]
        button.scroll_into_view_if_needed()
        button.hover()
        page.wait_for_timeout(300)
        button.click()
        page.wait_for_selector("div[role=dialog]", timeout=15000)
        page.wait_for_timeout(1200)
        before = thumbs(page)
        print(f"2) original thumbnails shown: {before}")
        if before != 1:
            failures.append(f"expected 1 original thumbnail, got {before}")

        page.screenshot(path=str(SHOTS / "verify-remove-before.png"))
        # 缩略图右上角的移除按钮
        remove_buttons = page.query_selector_all("div[role=dialog] button[aria-label='移除这张图片']")
        print(f"   remove buttons: {len(remove_buttons)}")
        if not remove_buttons:
            failures.append("remove button not found")
        else:
            remove_buttons[0].click()
            page.wait_for_timeout(600)
        after = thumbs(page)
        print(f"3) thumbnails after removing: {after}")
        if after != 0:
            failures.append(f"thumbnail still present after removal: {after}")
        page.screenshot(path=str(SHOTS / "verify-remove-after.png"))

        dialog = page.query_selector("div[role=dialog]")
        for element in dialog.query_selector_all("button"):
            if "丢弃后续并重发" in (element.inner_text() or ""):
                element.click()
                break
        page.wait_for_timeout(20000)
        resent = page.evaluate("""() => document.querySelectorAll('[data-chat-flow-kind="user"] img').length""")
        print(f"4) images in the resent message: {resent}")
        if resent != 0:
            failures.append(f"removed image was resent anyway: {resent}")

        print("--- page errors ---")
        for line in errors:
            print(line)
        browser.close()

    print("RESULT:", "PASS" if not failures else "FAIL")
    for item in failures:
        print(" -", item)


if __name__ == "__main__":
    main()
