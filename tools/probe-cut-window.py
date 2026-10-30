"""实测长会话的 timeline 窗口：滚到历史中段点「编辑提问」，看 turnOrder 是否只含最近若干轮。

会话按页加载（maxMessages 500 / turnWindow minMessages 50、minTurns 2），
窗口里的第一轮往往不是会话的第一轮。若 probe 显示 index=0 而 turnId>1，
说明旧代码会把这一轮当成首轮、切点退化成 0。
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
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
    page = ctx.new_page()
    page.on("console", lambda m: logs.append(m.text) if "cut probe" in (m.text or "") else None)
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("[contenteditable=true]", timeout=90000)
    page.wait_for_timeout(3000)
    row = page.wait_for_selector(f"[data-row-key='session:{TARGET}']", timeout=20000)
    row.click()
    page.wait_for_timeout(6000)
    page.mouse.move(700, 400)
    for _ in range(6):
        page.mouse.wheel(0, -2400)
        page.wait_for_timeout(1200)
    page.wait_for_timeout(2000)
    buttons = [b for b in page.query_selector_all("button") if "编辑提问" in (b.inner_text() or "")]
    print("edit buttons visible:", len(buttons))
    for index, button in enumerate(buttons[:4]):
        try:
            button.scroll_into_view_if_needed()
            button.hover()
            page.wait_for_timeout(400)
            button.click()
            page.wait_for_timeout(1200)
            dialog = page.query_selector("div[role=dialog]")
            print(f"--- click #{index} dialog={dialog is not None}")
            if logs:
                print("PROBE:", logs[-1][:400])
            if dialog is not None:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                if page.query_selector("div[role=dialog]") is not None:
                    for b in page.query_selector_all("div[role=dialog] button"):
                        if "取消" in (b.inner_text() or ""):
                            b.click()
                            page.wait_for_timeout(400)
                            break
        except Exception as error:
            print("click failed:", error)
    browser.close()
