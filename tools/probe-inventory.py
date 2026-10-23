"""只读探测：打开「设置 → 内置插件 → 全局插件」，列出与本插件相关的卡片并截图。

用法：
    python probe-inventory.py [base] [out.png] [关键字]

流程：会话页 → 侧栏「更多」→「设置」→「内置插件」→「插件列表」→ 展开「全局插件」分组。
只读操作：不点任何启停开关、不写设置。
"""
import json
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:51211/"
OUT = sys.argv[2] if len(sys.argv) > 2 else str(HERE / "probe-inventory.png")
QUERY = sys.argv[3] if len(sys.argv) > 3 else "编辑提问"
AUTHORITY = BASE.split("//", 1)[1].rstrip("/")

CLICK_TEXT = r"""
(wanted) => {
  const nodes = [...document.querySelectorAll('button, a, [role=menuitem], [role=tab], [role=option], li, div, span')]
    .filter((el) => {
      const rect = el.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && (el.innerText || '').trim() === wanted;
    });
  const hit = nodes[nodes.length - 1];
  if (hit === undefined) return false;
  hit.click();
  return true;
}
"""

EXPAND_GLOBAL = r"""
() => {
  const section = document.querySelector('[data-plugin-scope="global"]');
  if (section === null) return 'no-section';
  const toggle = section.querySelector('[aria-expanded]');
  if (toggle === null) return 'no-toggle';
  const state = toggle.getAttribute('aria-expanded');
  if (state !== 'true') toggle.click();
  return `expanded(${state})`;
}
"""

FIND_CARDS = r"""
(query) => {
  const section = document.querySelector('[data-plugin-scope="global"]');
  if (section === null) return [];
  const needle = query.toLowerCase();
  return [...section.querySelectorAll('li')]
    .map((li) => ({
      lines: (li.innerText || '').trim().split('\n').filter((line) => line.trim() !== ''),
      element: li,
    }))
    .filter((row) => row.lines.join(' ').toLowerCase().includes(needle))
    .map((row) => {
      const rect = row.element.getBoundingClientRect();
      return { lines: row.lines.slice(0, 4), box: [Math.round(rect.x), Math.round(rect.y)] };
    });
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
        page.wait_for_timeout(3500)
        print(f"open 更多: {page.evaluate(CLICK_TEXT, '更多')}")
        page.wait_for_timeout(900)
        print(f"open 设置: {page.evaluate(CLICK_TEXT, '设置')}")
        page.wait_for_timeout(1500)
        print(f"open 内置插件: {page.evaluate(CLICK_TEXT, '内置插件')}")
        page.wait_for_timeout(2500)
        print(f"global group: {page.evaluate(EXPAND_GLOBAL)}")
        page.wait_for_timeout(1200)
        cards = page.evaluate(FIND_CARDS, QUERY)
        print(f"cards matching {QUERY!r}: {json.dumps(cards, ensure_ascii=False, indent=1)}")
        card = page.locator('[data-plugin-scope="global"] li').filter(has_text=QUERY).first
        if card.count() == 0:
            print("card not found: screenshot the whole page instead")
            page.screenshot(path=OUT)
        else:
            card.scroll_into_view_if_needed()
            page.wait_for_timeout(700)
            box = card.bounding_box()
            if box is None:
                page.screenshot(path=OUT)
            else:
                page.screenshot(
                    path=OUT,
                    clip={
                        "x": max(0, box["x"] - 300),
                        "y": max(0, box["y"] - 90),
                        "width": min(1440, box["width"] + 620),
                        "height": box["height"] + 180,
                    },
                )
        print(f"screenshot: {OUT}")
        print(f"page errors: {errors}")
        browser.close()


if __name__ == "__main__":
    main()
