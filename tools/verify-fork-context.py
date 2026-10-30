"""验证 fork 切点：多轮会话里编辑「第 3 轮」时，新会话必须保留前 2 轮上下文。

区分两种可能：
    - 设计如此：编辑第 1 轮 → 切点 0 → 新会话没有任何历史；
    - 真 bug：编辑第 N>1 轮也切到 0 → 前缀丢失。
用法：
    python verify-fork-context.py [base]
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
ROUNDS = ["第一轮：只回复数字 1", "第二轮：只回复数字 2", "第三轮：只回复数字 3"]
EDITED = "第三轮改了：只回复数字 3"


def cookie_pair():
    out = subprocess.run(
        [NODE, str(HERE / "auth-cookie.mjs"), AUTHORITY], capture_output=True, text=True, check=True
    ).stdout.strip()
    return out.split("=", 1)


def boot(page):
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("[contenteditable=true], textarea", timeout=90000)
    page.wait_for_timeout(3000)
    modal = page.query_selector("div[role=presentation]")
    if modal is not None:
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)


def edit_buttons(page):
    return [b for b in page.query_selector_all("button") if "编辑提问" in (b.inner_text() or "")]


def wait_completed(page, turns, timeout=180000):
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        text = page.evaluate("() => document.body.innerText || ''")
        if f"{turns} 轮" in text and len(edit_buttons(page)) >= turns:
            return True
        page.wait_for_timeout(2000)
    return False


def user_texts(page):
    return page.evaluate("""() => [...document.querySelectorAll('[data-chat-flow-kind="user"]')]
        .map(el => (el.innerText || '').replace('\\u270e', '').replace('\\u7f16\\u8f91\\u63d0\\u95ee', '').replace(/\\s+/g, ' ').trim())""")


def main():
    name, value = cookie_pair()
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        boot(page)
        for element in page.query_selector_all("button"):
            if "新会话" in (element.inner_text() or ""):
                element.click()
                page.wait_for_timeout(1500)
                break

        composer = page.wait_for_selector("[contenteditable=true]", timeout=30000)
        for index, text in enumerate(ROUNDS, start=1):
            composer.click()
            page.keyboard.type(text)
            page.wait_for_timeout(300)
            page.keyboard.press("Enter")
            ok = wait_completed(page, index)
            print(f"round {index} completed: {ok}")
            if not ok:
                failures.append(f"round {index} did not finish")
        before = user_texts(page)
        print(f"parent user messages: {len(before)}")
        for line in before:
            print("   -", line[:60])

        # 编辑第 3 轮
        button = edit_buttons(page)[-1]
        button.scroll_into_view_if_needed()
        button.hover()
        page.wait_for_timeout(300)
        button.click()
        page.wait_for_selector("div[role=dialog]", timeout=15000)
        page.wait_for_timeout(1000)
        area = page.wait_for_selector("div[role=dialog] textarea", timeout=10000)
        area.click()
        page.keyboard.press("Control+A")
        page.keyboard.type(EDITED)
        page.wait_for_timeout(300)
        dialog = page.query_selector("div[role=dialog]")
        for element in dialog.query_selector_all("button"):
            if "丢弃后续并重发" in (element.inner_text() or ""):
                element.click()
                break

        page.wait_for_function("""() => (document.body.innerText || '').includes('(2)')""", timeout=90000)
        page.wait_for_timeout(12000)
        after = user_texts(page)
        print(f"child user messages: {len(after)}")
        for line in after:
            print("   -", line[:60])

        if len(after) != 3:
            failures.append(f"child should carry 2 prefix turns + edited one, got {len(after)}")
        if not any("第一轮" in line for line in after):
            failures.append("round 1 missing from the child session")
        if not any("第二轮" in line for line in after):
            failures.append("round 2 missing from the child session")
        if not any("第三轮改了" in line for line in after):
            failures.append("edited round 3 text missing")
        if any("第三轮：只回复" in line for line in after):
            failures.append("the old round 3 text is still present")

        page.screenshot(path=str(HERE.parent / "shots" / "verify-fork-context.png"))
        print("--- page errors ---")
        for line in errors:
            print(line)
        browser.close()

    print("RESULT:", "PASS" if not failures else "FAIL")
    for item in failures:
        print(" -", item)


if __name__ == "__main__":
    main()
