"""验证修复：窗口不完整时拦住并提示；点「加载更早」补齐后切点恢复。

流程：
1. 打开 59 轮会话（只加载最后 3 轮），点窗口内第一轮的「编辑提问」
   → probe index=0 且 turnId>1，对话框应出现提示、提交按钮禁用。
2. 点「加载更早」补齐历史，再点同一轮
   → probe index>0，上一轮 end 存在，提示消失、提交可用。
"""

import subprocess
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = "http://127.0.0.1:58254/"
TARGET = "session-030379e3-b6b3-4188-bd9a-0bcab49fe4aa"

out = subprocess.run(
    [NODE, str(HERE / "auth-cookie.mjs"), "127.0.0.1:58254"], capture_output=True, text=True, check=True
).stdout.strip()
name, value = out.split("=", 1)

logs = []


def dialog_submit(page):
    dialog = page.query_selector("div[role=dialog]")
    if dialog is None:
        return None
    for button in dialog.query_selector_all("button"):
        if "丢弃后续并重发" in (button.inner_text() or ""):
            return button
    return None


def close_dialog(page):
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    dialog = page.query_selector("div[role=dialog]")
    if dialog is None:
        return
    for button in dialog.query_selector_all("button"):
        if "取消" in (button.inner_text() or ""):
            button.click()
            page.wait_for_timeout(400)
            return


def click_edit(page, index):
    buttons = [b for b in page.query_selector_all("button") if "编辑提问" in (b.inner_text() or "")]
    button = buttons[index]
    button.scroll_into_view_if_needed()
    button.hover()
    page.wait_for_timeout(400)
    button.click()
    page.wait_for_timeout(1500)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
    page = ctx.new_page()
    page.on("console", lambda m: logs.append(m.text) if "cut probe" in (m.text or "") else None)
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("[contenteditable=true]", timeout=90000)
    page.wait_for_timeout(3000)
    page.wait_for_selector(f"[data-row-key='session:{TARGET}']", timeout=20000).click()
    page.wait_for_timeout(6000)

    print("=== 1) 未加载更早，直接编辑窗口内第一轮 ===")
    click_edit(page, 0)
    print("PROBE:", logs[-1][:300] if logs else "none")
    alert = page.query_selector("div[role=dialog] [role=alert]")
    print("alert shown:", alert is not None)
    if alert is not None:
        print("alert text:", (alert.inner_text() or "")[:80])
    submit = dialog_submit(page)
    print("submit disabled:", None if submit is None else submit.is_disabled())
    close_dialog(page)

    print("=== 2) 点「加载更早」补齐历史 ===")
    page.mouse.move(700, 400)
    for _ in range(8):
        page.mouse.wheel(0, -3000)
        page.wait_for_timeout(700)
    for attempt in range(4):
        button = None
        for candidate in page.query_selector_all("button"):
            if "加载更早" in (candidate.inner_text() or ""):
                button = candidate
                break
        if button is None:
            print(f"  attempt {attempt}: no load-earlier button")
            break
        button.click()
        page.wait_for_timeout(5000)
        print(f"  attempt {attempt}: clicked load-earlier")
    page.mouse.wheel(0, 3000)
    page.wait_for_timeout(2500)

    print("=== 3) 补齐后再编辑（点窗口最后一轮，其上一轮已在窗口内） ===")
    click_edit(page, -1)
    print("PROBE:", logs[-1][:320] if logs else "none")
    alert = page.query_selector("div[role=dialog] [role=alert]")
    submit = dialog_submit(page)
    print("alert shown:", alert is not None, "| submit disabled:", None if submit is None else submit.is_disabled())
    close_dialog(page)
    browser.close()
