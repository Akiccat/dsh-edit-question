"""
只读探测：打印侧栏会话列表的行 key 与标题，用于定位要验证的目标会话。

用法：
    python probe-sessions.py [base] [--menu <row-key>]

--menu 会悬停该行并打印行内按钮的 aria-label/title，用于确认归档/删除入口。
"""
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
ARGS = [arg for arg in sys.argv[1:] if arg.startswith("http")]
BASE = ARGS[0] if ARGS else "http://127.0.0.1:51211/"
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")
MENU = None
if "--menu" in sys.argv:
    MENU = sys.argv[sys.argv.index("--menu") + 1]
ARCHIVE = None
if "--archive" in sys.argv:
    ARCHIVE = sys.argv[sys.argv.index("--archive") + 1]

SCRIPT = r"""
() => {
  const rows = [...document.querySelectorAll('[data-row-key]')].map((row) => ({
    key: row.getAttribute('data-row-key'),
    text: (row.innerText || '').replace(/\n+/g, ' | ').slice(0, 70),
  }));
  return { url: location.href, rows };
}
"""


def cookie_pair():
    out = subprocess.run(
        [NODE, str(HERE / "auth-cookie.mjs"), AUTHORITY], capture_output=True, text=True, check=True
    ).stdout.strip()
    return out.split("=", 1)


def main() -> None:
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_selector("[contenteditable=true], textarea", timeout=90000)
        page.wait_for_timeout(4000)
        modal = page.query_selector("div[role=presentation]")
        if modal is not None:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
        data = page.evaluate(SCRIPT)
        print(json.dumps(data, ensure_ascii=False, indent=1))
        print(f"page errors: {errors}")
        if MENU is not None:
            row = page.query_selector(f'[data-row-key="{MENU}"]')
            print(f"menu row found: {row is not None}")
            if row is not None:
                row.hover()
                page.wait_for_timeout(800)
                buttons = page.evaluate(
                    """(key) => {
                         const row = document.querySelector(`[data-row-key="${key}"]`);
                         if (row === null) return [];
                         return [...row.querySelectorAll('button')].map((b) => ({
                           label: (b.getAttribute('aria-label') || b.title || b.innerText || '').trim(),
                           visible: b.offsetParent !== null,
                           hit: b.getBoundingClientRect().width > 0,
                         }));
                       }""",
                    MENU,
                )
                print(f"row buttons: {json.dumps(buttons, ensure_ascii=False)}")
                page.screenshot(path=str(HERE.parent / "shots" / "probe-row-menu.png"))
        if ARCHIVE is not None:
            print(f"archive key: {ARCHIVE}")
            handle = page.evaluate_handle(
                """(key) => [...document.querySelectorAll('[data-row-key]')]
                     .find((row) => row.getAttribute('data-row-key') === key) ?? null""",
                ARCHIVE,
            )
            row = handle.as_element()
            print(f"archive row found: {row is not None}")
            if row is not None:
                row.hover()
                page.wait_for_timeout(600)
                clicked = False
                for element in row.query_selector_all("button"):
                    label = (element.get_attribute("aria-label") or "") + (element.inner_text() or "")
                    if "归档会话" in label:
                        element.click()
                        clicked = True
                        break
                page.wait_for_timeout(2500)
                still = page.evaluate(
                    """(key) => [...document.querySelectorAll('[data-row-key]')]
                         .some((row) => row.getAttribute('data-row-key') === key)""",
                    ARCHIVE,
                )
                print(f"archive clicked: {clicked}; row still listed: {still}")
        browser.close()


if __name__ == "__main__":
    main()
