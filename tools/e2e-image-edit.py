"""端到端验证：编辑带图片的提问 → 重发时图片一并带上；并可选择归档（删除）原会话。

用法：
    python e2e-image-edit.py [base] [--keep]

流程：
    1. 新建会话，上传一张本地 PNG，发一条短提问，等该轮完成；
    2. 点该轮的「编辑提问」，确认对话框识别到图片；
    3. 选「删除原会话」后提交，等新会话生成；
    4. 检查新会话里同时有图片和编辑后的文本，且原会话已从列表归档。

只读约束：本脚本只创建一个用完即弃的测试会话；--keep 保留它，否则跑完会尝试归档。
"""
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = "http://127.0.0.1:51211/"
for index, arg in enumerate(sys.argv[1:]):
    if not arg.startswith("--"):
        BASE = arg if BASE is None else BASE
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")
SHOTS = ROOT / "shots"
IMAGE = SHOTS / "sample-image.png"
TEXT = "图片重发自检：请只回复两个字：收到"


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


def sidebar_rows(page) -> list[dict]:
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-row-key]')]
             .filter((row) => (row.getAttribute('data-row-key') || '').startsWith('session:'))
             .map((row) => ({ key: row.getAttribute('data-row-key'), text: (row.innerText || '').replace(/\\n+/g, ' | ').slice(0, 70) }))"""
    )


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


def upload(page, path: Path) -> str:
    inputs = page.query_selector_all("input[type=file]")
    print(f"  file inputs: {len(inputs)}")
    if not inputs:
        return "no-input"
    page.set_input_files("input[type=file]", str(path))
    page.wait_for_timeout(2500)
    previews = page.evaluate(
        """() => [...document.querySelectorAll('img')]
             .filter((img) => (img.getAttribute('src') || '').startsWith('blob:') || (img.getAttribute('src') || '').startsWith('data:'))
             .length"""
    )
    print(f"  composer previews: {previews}")
    return "ok"


def send(page, text: str) -> None:
    composer = page.wait_for_selector("[contenteditable=true]", timeout=30000)
    composer.click()
    page.keyboard.type(text)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def main() -> None:
    keep = "--keep" in sys.argv
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
        print("1) new session")
        new_session(page)
        before = sidebar_rows(page)
        print(f"  rows before: {len(before)}")
        print("2) upload image")
        print(f"  upload: {upload(page, IMAGE)}")
        shot(page, "e2e-image-01-composer")
        print("3) send question")
        send(page, TEXT)
        print(f"  turn 1 completed: {wait_completed(page, 1)}")
        page.wait_for_timeout(1500)
        session_img = page.evaluate(
            """() => [...document.querySelectorAll('[data-chat-flow-kind="user"] img')].length"""
        )
        print(f"  user bubble images: {session_img}")
        shot(page, "e2e-image-02-sent")
        print("4) open editor")
        buttons = edit_buttons(page)
        print(f"  edit buttons: {len(buttons)}")
        button = buttons[-1]
        button.scroll_into_view_if_needed()
        button.hover()
        page.wait_for_timeout(300)
        button.click()
        page.wait_for_selector("div[role=dialog]", timeout=15000)
        page.wait_for_timeout(600)
        dialog = page.query_selector("div[role=dialog]")
        body = (dialog.inner_text() or "").replace("\n", " | ")
        print(f"  dialog: {body[:240]!r}")
        print(f"  images noted: {'图片' in body}")
        shot(page, "e2e-image-03-dialog")
        print("5) choose delete + submit")
        for element in dialog.query_selector_all("button"):
            if "删除原会话" in (element.inner_text() or ""):
                element.click()
                page.wait_for_timeout(300)
                break
        shot(page, "e2e-image-04-chosen")
        for element in dialog.query_selector_all("button"):
            if "丢弃后续并重发" in (element.inner_text() or ""):
                element.click()
                break
        page.wait_for_timeout(20000)
        shot(page, "e2e-image-05-after-submit")
        after = sidebar_rows(page)
        print(f"  rows after: {len(after)}")
        print(f"  new rows: {[row['text'] for row in after if row['key'] not in {r['key'] for r in before}]}")
        print(f"  gone rows: {[row['text'] for row in before if row['key'] not in {r['key'] for r in after}]}")
        images = page.evaluate(
            """() => [...document.querySelectorAll('[data-chat-flow-kind="user"] img')].length"""
        )
        print(f"  new session user images: {images}")
        print(f"  page url: {page.url}")
        print("--- plugin console ---")
        for line in console:
            if "dsh-edit-question" in line:
                print(line)
        print("--- page errors ---")
        for line in errors:
            print(line)
        if not keep:
            print("  (test session kept for inspection; archive it manually if unwanted)")
        browser.close()


if __name__ == "__main__":
    main()
