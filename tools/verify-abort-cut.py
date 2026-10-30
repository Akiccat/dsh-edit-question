"""复现假设：上一轮被「停止」后，编辑下一轮时切点是否退化成 0。

用法：
    python verify-abort-cut.py [base]
输出：cut probe 日志 + 新会话的消息条数。
"""

import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = "http://127.0.0.1:58254/"
for arg in sys.argv[1:]:
    if arg.startswith("http"):
        BASE = arg
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")


def cookie_pair():
    out = subprocess.run(
        [NODE, str(HERE / "auth-cookie.mjs"), AUTHORITY], capture_output=True, text=True, check=True
    ).stdout.strip()
    return out.split("=", 1)


def edit_buttons(page):
    return [b for b in page.query_selector_all("button") if "编辑提问" in (b.inner_text() or "")]


def wait_turns(page, turns, timeout=180000):
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        text = page.evaluate("() => document.body.innerText || ''")
        if f"{turns} 轮" in text and len(edit_buttons(page)) >= turns:
            return True
        page.wait_for_timeout(1500)
    return False


def send(page, text):
    composer = page.wait_for_selector("[contenteditable=true]", timeout=30000)
    composer.click()
    page.keyboard.type(text)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def stop_running(page):
    for button in page.query_selector_all("button"):
        label = (button.get_attribute("aria-label") or "") + " " + (button.inner_text() or "")
        if "停止" in label:
            button.click()
            return True
    return False


def user_texts(page):
    return page.evaluate("""() => [...document.querySelectorAll('[data-chat-flow-kind="user"]')]
        .map(el => (el.innerText || '').replace('\\u270e', '').replace('\\u7f16\\u8f91\\u63d0\\u95ee', '').replace(/\\s+/g, ' ').trim())""")


def main():
    name, value = cookie_pair()
    logs = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        page.on("console", lambda msg: logs.append(msg.text) if "cut probe" in (msg.text or "") else None)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector("[contenteditable=true]", timeout=90000)
        page.wait_for_timeout(3000)
        for element in page.query_selector_all("button"):
            if "新会话" in (element.inner_text() or ""):
                element.click()
                page.wait_for_timeout(1500)
                break

        send(page, "第一轮：只回复数字 1")
        print("round 1:", wait_turns(page, 1))

        send(page, "第二轮：先执行 pwsh 命令 Start-Sleep -Seconds 25，再回复数字 2")
        print("round 2 sent, stopping shortly...")
        page.wait_for_timeout(4000)
        stopped = stop_running(page)
        print("stop clicked:", stopped)
        page.wait_for_timeout(8000)
        print("round 2 settled, edit buttons:", len(edit_buttons(page)))

        send(page, "第三轮：只回复数字 3")
        print("round 3:", wait_turns(page, 3, timeout=240000))

        button = edit_buttons(page)[-1]
        button.scroll_into_view_if_needed()
        button.hover()
        page.wait_for_timeout(300)
        button.click()
        page.wait_for_selector("div[role=dialog]", timeout=15000)
        page.wait_for_timeout(800)
        for line in logs[-3:]:
            print("PROBE:", line)
        area = page.wait_for_selector("div[role=dialog] textarea", timeout=10000)
        area.click()
        page.keyboard.press("Control+A")
        page.keyboard.type("第三轮改了：只回复数字 3")
        dialog = page.query_selector("div[role=dialog]")
        for element in dialog.query_selector_all("button"):
            if "丢弃后续并重发" in (element.inner_text() or ""):
                element.click()
                break
        page.wait_for_function("""() => (document.body.innerText || '').includes('(2)')""", timeout=90000)
        page.wait_for_timeout(12000)
        texts = user_texts(page)
        print(f"child messages: {len(texts)}")
        for line in texts:
            print("   -", line[:50])
        browser.close()


if __name__ == "__main__":
    main()
