"""生成市场展示用的 4 张截图，画面里不含任何真实工作内容。

两个问题都在这里解决：
  1. 原先直接截全屏，把侧边栏的会话标题、工作区名一起截了进去 —— 现在统一裁掉左侧
     侧边栏列（x < SIDEBAR），只保留主对话区；
  2. 原先拿 `shots/edit-button-in-row.png` 当上传图，而那张图本身是真实工作会话的
     截图（带内部 GitLab 地址），于是每张展示图里又把它显示一遍 —— 现在改用 Pillow
     现画的两张中性示例图。

用法：
    python shots-market.py [base] [--probe]
"""

import base64
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = "http://127.0.0.1:55471/"
for arg in sys.argv[1:]:
    if arg.startswith("http"):
        BASE = arg
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")
SHOTS = ROOT / "shots"
SAMPLE_A = SHOTS / "sample-image.png"
SAMPLE_B = SHOTS / "sample-image-b.png"
TEXT = "图片重发自检：请只回复两个字：收到"
PROBE = "--probe" in sys.argv

VIEWPORT = {"width": 1440, "height": 900}
SIDEBAR = 280

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\segoeui.ttf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def make_sample(path: Path, caption: str, background: str, ink: str, accent: str) -> None:
    width, height = 800, 450
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 40, width - 40, height - 40), radius=24, outline=accent, width=4)
    draw.rectangle((44, 44, width - 44, 150), fill=accent)
    draw.text((80, 78), "Sample", font=load_font(40), fill="#ffffff")
    draw.text((80, 210), caption, font=load_font(64), fill=ink)
    draw.text((80, 310), "shot for the plugin listing", font=load_font(28), fill="#8a8f98")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    print(f"  sample: {path.name} ({path.stat().st_size} B)")


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


def send(page, text: str) -> None:
    composer = page.wait_for_selector("[contenteditable=true]", timeout=30000)
    composer.click()
    page.keyboard.type(text)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def shot(page, name: str, clip=None) -> None:
    """所有截图都从 SIDEBAR 右侧开始，侧边栏永远不进画面。"""
    left, top = SIDEBAR, 0
    right, bottom = VIEWPORT["width"], VIEWPORT["height"]
    if clip:
        left = max(left, int(clip["x"]))
        top = max(top, int(clip["y"]))
        right = min(right, int(clip["x"] + clip["width"]))
        bottom = min(bottom, int(clip["y"] + clip["height"]))
    region = {"x": left, "y": top, "width": right - left, "height": bottom - top}
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path), clip=region)
    print(f"  screenshot: shots/{name}.png ({path.stat().st_size} B, {region['width']}x{region['height']})")


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


def main() -> None:
    make_sample(SAMPLE_A, "示例图片 A", "#eef2f7", "#1f2933", "#4f7cff")
    make_sample(SAMPLE_B, "示例图片 B", "#f6f0ea", "#2b2118", "#e0894a")

    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT)
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda err: errors.append(str(err)))
        boot(page)
        if PROBE:
            page.screenshot(path=str(SHOTS / "_probe-full.png"))
            shot(page, "_probe-cropped")
            print("  probe written; stopping")
            browser.close()
            return
        print("1) new session + image A")
        new_session(page)
        page.set_input_files("input[type=file]", str(SAMPLE_A))
        page.wait_for_timeout(2000)
        send(page, TEXT)
        print(f"  turn 1 completed: {wait_completed(page, 1)}")
        page.wait_for_timeout(1500)
        print("2) capture the row with the edit button")
        box = page.evaluate(
            """() => {
                 const flow = [...document.querySelectorAll('[data-chat-flow-kind="user"]')].pop();
                 if (!flow) return null;
                 const r = flow.getBoundingClientRect();
                 return { x: r.x, y: r.y, width: r.width, height: r.height };
               }"""
        )
        print(f"  user row box: {box}")
        if box:
            # 行的左侧有一片页面自带的模糊装饰，把裁切起点収到气泡附近
            indent = box["width"] * 0.15
            shot(
                page,
                "edit-button-in-row",
                clip={
                    "x": box["x"] + indent - 12,
                    "y": box["y"] - 8,
                    "width": box["width"] - indent + 24,
                    "height": box["height"] + 16,
                },
            )
        print("3) open the editor")
        button = edit_buttons(page)[-1]
        button.scroll_into_view_if_needed()
        button.hover()
        page.wait_for_timeout(300)
        button.click()
        page.wait_for_selector("div[role=dialog]", timeout=15000)
        page.wait_for_timeout(700)
        shot(page, "e2e-image-03-dialog")
        print("4) paste image B into the dialog")
        payload = {"base64": base64.b64encode(SAMPLE_B.read_bytes()).decode(), "name": "sample-b.png"}
        print(f"  paste result: {page.evaluate(PASTE_JS, payload)}")
        page.wait_for_timeout(500)
        shot(page, "e2e-paste-01-dialog")
        print("5) submit")
        dialog = page.query_selector("div[role=dialog]")
        for element in dialog.query_selector_all("button"):
            if "丢弃后续并重发" in (element.inner_text() or ""):
                element.click()
                break
        page.wait_for_timeout(20000)
        shot(page, "e2e-image-05-after-submit")
        if errors:
            print("--- page errors ---")
            for line in errors:
                print(line)
        browser.close()


if __name__ == "__main__":
    main()
