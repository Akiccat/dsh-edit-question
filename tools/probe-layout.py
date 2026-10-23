"""只读探测：导出当前 GUI 会话页的消息行 DOM 结构，用于确认「编辑提问」按钮与用户消息元信息行的关系。

用法：
    python probe-layout.py [base] [out.png]
"""
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:51211/"
OUT = sys.argv[2] if len(sys.argv) > 2 else str(HERE / "probe-layout.png")
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")


def cookie_pair():
    out = subprocess.run(
        [NODE, str(HERE / "auth-cookie.mjs"), AUTHORITY], capture_output=True, text=True, check=True
    ).stdout.strip()
    return out.split("=", 1)


SCRIPT = r"""
() => {
  const box = (el) => {
    if (el === null) return null;
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
  };
  const describe = (el) => ({
    tag: el.tagName.toLowerCase(),
    cls: el.className && typeof el.className === 'string' ? el.className : '',
    data: Object.fromEntries([...el.attributes].filter((a) => a.name.startsWith('data-')).map((a) => [a.name, a.value])),
    box: box(el),
  });
  const items = [...document.querySelectorAll('[data-chat-node-key]')].map((item) => ({
    key: item.getAttribute('data-chat-node-key'),
    flowKey: item.getAttribute('data-chat-flow-key'),
    kind: item.getAttribute('data-chat-flow-kind'),
    turn: item.getAttribute('data-chat-turn'),
    hidden: item.hasAttribute('hidden'),
    box: box(item),
    text: (item.innerText || '').replace(/\n+/g, ' | ').slice(0, 80),
    clockRows: [...item.querySelectorAll('[data-clock]')].map(describe),
  }));
  const turnTails = [...document.querySelectorAll('[data-turn-tail]')].map((tail) => ({
    turn: tail.getAttribute('data-turn-tail'),
    reveal: tail.getAttribute('data-actions-reveal'),
    box: box(tail),
    children: [...tail.children].map(describe),
  }));
  const editButtons = [...document.querySelectorAll('button')]
    .filter((b) => (b.innerText || '').includes('编辑提问'))
    .map((b) => ({ box: box(b), parent: describe(b.parentElement), grand: describe(b.parentElement?.parentElement) }));
  const markers = [...document.querySelectorAll('[data-dsh-edit-question]')].map((b) => {
    const item = b.closest('[data-chat-turn]');
    return {
      turn: item?.getAttribute('data-chat-turn'),
      kind: item?.getAttribute('data-chat-flow-kind'),
      clock: b.closest('[data-clock]')?.getAttribute('data-clock'),
    };
  });
  return {
    url: location.href,
    scrollHost: describe(document.querySelector('[data-conversation-scroll]')),
    items,
    turnTails,
    editButtons,
    markers,
  };
}
"""


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
        if len(sys.argv) > 3:
            page.click(f"text={sys.argv[3]}")
            page.wait_for_timeout(4000)
        if len(sys.argv) > 4 and sys.argv[4] == "focus":
            # 把该会话第一条用户消息滚到视口中间，悬停露出动作行，再按行外扩截图。
            page.evaluate(
                """() => {
                  const item = document.querySelector('[data-chat-flow-kind="user"]');
                  if (item !== null) item.scrollIntoView({ block: 'center' });
                }"""
            )
            page.wait_for_timeout(1200)
            item = page.query_selector('[data-chat-flow-kind="user"]')
            if item is not None:
                item.hover()
                page.wait_for_timeout(600)
                box = item.bounding_box()
                row = page.query_selector('[data-chat-flow-kind="user"] [data-clock="start"]')
                row_box = row.bounding_box() if row is not None else None
                print(f"user item box: {box}")
                print(f"clock row box: {row_box}")
                if box is not None:
                    page.screenshot(
                        path=OUT,
                        clip={
                            "x": max(0, box["x"] - 24),
                            "y": max(0, box["y"] - 24),
                            "width": min(1440, box["width"] + 48),
                            "height": min(900, box["height"] + 48),
                        },
                    )
                    print(f"focused screenshot: {OUT}")
        if len(sys.argv) > 4 and sys.argv[4] == "click":
            # 点开第一条用户消息行里的「编辑提问」，确认 portal 后的按钮事件仍可用，然后关掉对话框。
            page.evaluate(
                """() => {
                  const item = document.querySelector('[data-chat-flow-kind="user"]');
                  if (item !== null) item.scrollIntoView({ block: 'center' });
                }"""
            )
            page.wait_for_timeout(1200)
            item = page.query_selector('[data-chat-flow-kind="user"]')
            if item is not None:
                item.hover()
                page.wait_for_timeout(400)
            button = page.query_selector('[data-dsh-edit-question]')
            print(f"button found: {button is not None}")
            if button is not None:
                box = button.bounding_box()
                print(f"button box: {box}")
                button.click()
                page.wait_for_timeout(900)
                dialog = page.query_selector("div[role=dialog]")
                print(f"dialog open: {dialog is not None}")
                if dialog is not None:
                    text = (dialog.inner_text() or "").replace("\n", " | ")[:200]
                    print(f"dialog text: {text!r}")
                    page.screenshot(path=OUT)
                    print(f"dialog screenshot: {OUT}")
                    page.keyboard.press("Escape")
                    page.wait_for_timeout(600)
                    print(f"dialog closed: {page.query_selector('div[role=dialog]') is None}")
                print(f"page errors: {errors}")
        page.wait_for_timeout(1500)
        data = page.evaluate(SCRIPT)
        if not (len(sys.argv) > 4 and sys.argv[4] in ("focus", "click")):
            page.screenshot(path=OUT)
        print(f"screenshot: {OUT}")
        user_items = [i for i in data["items"] if i["kind"] in ("user", "steering")]
        data["userItems"] = user_items
        data.pop("items", None)
        print(f"tail turns: {[t['turn'] for t in data['turnTails']]}")
        print(f"markers: {data['markers']}")
        print(f"edit buttons: {len(data['editButtons'])}")
        print(json.dumps(data, ensure_ascii=False, indent=1)[:12000])
        browser.close()


if __name__ == "__main__":
    main()
