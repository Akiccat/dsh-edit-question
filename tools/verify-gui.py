"""在真实 GUI 中验证「编辑提问并重发」插件。

用法：
    python verify-gui.py probe           # 只读探测：加载页面、确认插件与按钮、打开对话框后取消
    python verify-gui.py e2e             # 端到端：新建测试会话 -> 提问 -> 编辑重发 -> 校验分支

认证：dsh web 只接受启动令牌或签名 cookie，启动令牌只存在于进程内，因此这里用
tools/auth-cookie.mjs 按同一算法现签一个 cookie 注入浏览器上下文。脚本不做任何删除操作。
"""
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BASE = "http://127.0.0.1:19387/"
NODE = r"D:\deepseekH\resources\runtime\primary-runtime\dependencies\node\bin\node.exe"
SHOTS = ROOT / "shots"


def cookie_pair() -> tuple[str, str]:
    """调用 node 现签一个浏览器会话 cookie，返回 (name, value)。"""
    out = subprocess.run(
        [NODE, str(HERE / "auth-cookie.mjs")], capture_output=True, text=True, check=True
    ).stdout.strip()
    name, value = out.split("=", 1)
    return name, value


class Session:
    """一次浏览器会话，负责收集控制台输出与页面错误。"""

    def __init__(self, page):
        self.page = page
        self.console: list[str] = []
        self.errors: list[str] = []
        page.on("console", lambda msg: self.console.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: self.errors.append(str(err)))

    def dump(self) -> None:
        """打印控制台与页面错误（只保留与本插件相关或报错的行）。"""
        print("--- console (plugin + errors) ---")
        for line in self.console:
            if "dsh-edit-question" in line or "[error]" in line or "[warning]" in line:
                print(line)
        print("--- page errors ---")
        for line in self.errors:
            print(line)

    def shot(self, name: str) -> None:
        """截图到 shots/<name>.png。"""
        SHOTS.mkdir(exist_ok=True)
        self.page.screenshot(path=str(SHOTS / f"{name}.png"), full_page=False)
        print(f"screenshot: shots/{name}.png")


def dismiss_notice(page) -> None:
    """关闭首访欢迎/预备说明浮层（它带遮罩，会拦截所有点击）。"""
    modal = page.query_selector("div[role=presentation]")
    if modal is None:
        print("notice: none")
        return
    text = (modal.inner_text() or "").replace("\n", " ")[:200]
    labels = page.evaluate(
        """() => [...document.querySelectorAll('div[role=presentation] button')]
             .map((b) => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter((t) => t !== '')"""
    )
    print(f"notice: text={text!r}")
    print(f"notice buttons: {labels}")
    for wanted in ("继续", "我知道了", "知道了", "开始使用", "确认", "我明白了", "完成", "下一步", "关闭"):
        if wanted in labels:
            page.click(f"div[role=presentation] button:has-text('{wanted}')")
            page.wait_for_timeout(1200)
            print(f"notice: dismissed with {wanted}; still present: {page.query_selector('div[role=presentation]') is not None}")
            return
    page.keyboard.press("Escape")
    page.wait_for_timeout(800)
    print("notice: escaped")


def boot(page) -> None:
    """打开 GUI 并等待应用外壳就绪（输入区是 contenteditable，不是 textarea）。"""
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("[contenteditable=true], textarea", timeout=90000)
    page.wait_for_timeout(3000)
    dismiss_notice(page)


def boot_entries(page) -> list[str]:
    """读取 __DSH_BOOT__ 里的客户端条目 id。"""
    return page.evaluate("() => (globalThis.__DSH_BOOT__?.entries ?? []).map((e) => e.id)")


def button_texts(page) -> list[str]:
    """列出页面上可见按钮的文本。"""
    return page.evaluate(
        """() => [...document.querySelectorAll('button')]
             .filter((b) => b.offsetParent !== null)
             .map((b) => (b.innerText || b.getAttribute('aria-label') || b.title || '').trim())
             .filter((t) => t !== '')"""
    )


def edit_buttons(page):
    """返回轮尾「编辑提问」按钮句柄列表。"""
    return [b for b in page.query_selector_all("button") if "编辑提问" in (b.inner_text() or "")]


def probe() -> None:
    """只读探测：插件是否加载、入口是否渲染、对话框是否正确回填与计算切点。"""
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        sess = Session(page)
        boot(page)
        entries = boot_entries(page)
        print(f"boot entries: {len(entries)}; has plugin: {'dsh-edit-question' in entries}")
        loaded = page.evaluate(
            "() => globalThis.__DSH_MODULES__ ? Object.keys(globalThis.__DSH_MODULES__).filter((k) => k.includes('edit-question')) : 'no __DSH_MODULES__'"
        )
        print(f"module registry hit: {loaded}")
        page.wait_for_timeout(2000)
        buttons = edit_buttons(page)
        print(f"edit buttons rendered: {len(buttons)}")
        print("visible buttons: " + " | ".join(button_texts(page)[:40]))
        sess.shot("probe-01-boot")
        if not buttons:
            print("NO EDIT BUTTON - stopping")
            sess.dump()
            browser.close()
            return
        first = buttons[0]
        first.scroll_into_view_if_needed()
        first.hover()
        page.wait_for_timeout(300)
        first.click()
        page.wait_for_selector("div[role=dialog]", timeout=10000)
        page.wait_for_timeout(500)
        state = page.evaluate(
            """() => {
                 const dialog = document.querySelector('div[role=dialog]');
                 const area = dialog.querySelector('textarea');
                 return { title: dialog.innerText.split('\\n').slice(0, 3), value: area.value, len: area.value.length };
               }"""
        )
        print("dialog preview: " + json.dumps(state, ensure_ascii=False)[:400])
        sess.shot("probe-02-dialog")
        sess.dump()
        browser.close()


def diag() -> None:
    """诊断模式：只加载页面并导出控制台、错误、可见文本与元素统计。"""
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        sess = Session(page)
        page.goto(BASE, wait_until="domcontentloaded")
        page.wait_for_timeout(12000)
        print("--- all console ---")
        for line in sess.console[:80]:
            print(line)
        print("--- page errors ---")
        for line in sess.errors[:20]:
            print(line)
        stats = page.evaluate(
            """() => ({
                 title: document.title,
                 ready: document.readyState,
                 rootChildren: document.getElementById('root')?.children.length ?? -1,
                 bodyChildren: document.body.children.length,
                 hasBoot: typeof globalThis.__DSH_BOOT__ !== 'undefined',
                 entries: (globalThis.__DSH_BOOT__?.entries ?? []).length,
                 textareas: document.querySelectorAll('textarea').length,
                 buttons: document.querySelectorAll('button').length,
                 editable: document.querySelectorAll('[contenteditable=true]').length,
                 bodyText: (document.body.innerText || '').slice(0, 1200),
               })"""
        )
        print("--- stats ---")
        for key, item in stats.items():
            if key == "bodyText":
                continue
            print(f"{key}: {item}")
        print("--- body text ---")
        print(stats["bodyText"])
        sess.shot("diag-01")
        browser.close()


def click_text(page, text: str, timeout: int = 15000) -> bool:
    """点击可见的、文本包含指定字样的按钮或列表项。"""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for element in page.query_selector_all("button, [role=button], [role=menuitem], li, div"):
            try:
                if element.is_visible() and text in (element.inner_text() or "") and len(element.inner_text()) < 80:
                    element.click()
                    return True
            except Exception:
                continue
        page.wait_for_timeout(500)
    return False


def wait_edit_button(page, timeout: int = 240000):
    """等待轮尾「编辑提问」入口出现，返回其句柄。"""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        buttons = edit_buttons(page)
        if buttons:
            return buttons[0]
        page.wait_for_timeout(1000)
    return None


def send(page, text: str) -> None:
    """在当前会话的输入区输入并回车发送。"""
    composer = page.wait_for_selector("[contenteditable=true]", timeout=30000)
    composer.click()
    page.keyboard.type(text)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def wait_completed(page, turns: int, timeout: int = 300000) -> bool:
    """等待前 turns 轮真正结束：底部状态栏轮次数达到 turns，且每轮都已渲染出轮尾入口。"""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        text = page.evaluate("() => document.body.innerText || ''")
        if f"{turns} 轮" in text and len(edit_buttons(page)) >= turns:
            return True
        page.wait_for_timeout(2000)
    return False


def edit_turn(page, turn_index: int, new_text: str, shot_prefix: str) -> str:
    """点开第 turn_index 轮（从 1 开始）的「编辑提问」，改文本并提交重发。"""
    buttons = edit_buttons(page)
    print(f"  edit buttons: {len(buttons)} (target turn {turn_index})")
    button = buttons[turn_index - 1]
    button.scroll_into_view_if_needed()
    button.click()
    page.wait_for_selector("div[role=dialog]", timeout=10000)
    page.wait_for_timeout(400)
    original = page.eval_on_selector("div[role=dialog] textarea", "el => el.value")
    print(f"  dialog original text: {original!r}")
    page.screenshot(path=str(SHOTS / f"{shot_prefix}-dialog.png"))
    area = page.query_selector("div[role=dialog] textarea")
    area.click()
    page.keyboard.press("Control+A")
    page.keyboard.type(new_text)
    page.wait_for_timeout(300)
    for element in page.query_selector_all("div[role=dialog] button"):
        if "丢弃后续并重发" in (element.inner_text() or ""):
            element.click()
            break
    return original


def e2e(scenario: str) -> None:
    """端到端场景：first = 编辑首轮提问；second = 编辑第二轮的提问。"""
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        sess = Session(page)
        boot(page)
        print(f"scenario: {scenario}")
        send(page, "请只回复两个字：收到")
        print("  waiting for turn 1")
        print("  turn 1 completed:", wait_completed(page, 1))
        expected_turns = 1
        if scenario == "second":
            send(page, "请只回复两个字：明白")
            print("  waiting for turn 2")
            print("  turn 2 completed:", wait_completed(page, 2))
            expected_turns = 2
        sess.shot(f"e2e-{scenario}-01-before-edit")
        target = 2 if scenario == "second" else 1
        replacement = "请只回复两个字：好的" if target == 1 else "请只回复两个字：明白了吗"
        original = edit_turn(page, target, replacement, f"e2e-{scenario}-02")
        print(f"  edited turn {target}: {original!r} -> {replacement!r}")
        page.wait_for_timeout(9000)
        sess.shot(f"e2e-{scenario}-03-after-submit")
        print("--- plugin console ---")
        for line in sess.console:
            if "dsh-edit-question" in line:
                print(line)
        print("--- page errors ---")
        for line in sess.errors:
            print(line)
        body = page.evaluate("() => (document.body.innerText || '').slice(0, 2000)")
        print("--- pane text ---")
        print(body)
        browser.close()


def rowinfo() -> None:
    """诊断：打印侧边栏里测试会话行的结构，用于确认删除入口。"""
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        boot(page)
        page.wait_for_timeout(4000)
        print("expand all:", click_text(page, "展开其余", timeout=8000))
        print("expand 未分组:", click_text(page, "未分组", timeout=5000))
        page.wait_for_timeout(4000)
        titles = page.evaluate(
            """() => [...document.querySelectorAll('*')]
                 .map((e) => (e.innerText || '').trim())
                 .filter((t) => t !== '' && t.length < 40 && t.includes('回复两个字'))"""
        )
        print(f"sidebar title candidates: {sorted(set(titles))}")
        info = page.evaluate(
            """() => {
                 const out = [];
                 for (const element of document.querySelectorAll('*')) {
                   const text = (element.innerText || '').trim();
                   if (!text.startsWith('请只回复两个字')) continue;
                   if (text.length > 60) continue;
                   const row = element.closest('[role=button], li, [class*=item], [class*=row]') ?? element;
                   out.push({
                     tag: element.tagName,
                     cls: element.className.toString().slice(0, 60),
                     text: text.slice(0, 40),
                     rowCls: (row.className || '').toString().slice(0, 60),
                     rowButtons: [...row.querySelectorAll('button')].map((b) => (b.getAttribute('aria-label') || b.title || b.innerText || '').trim()),
                     html: row.outerHTML.slice(0, 600),
                   });
                 }
                 return out.slice(0, 4);
               }"""
        )
        for index, item in enumerate(info):
            print(f"--- row {index} ---")
            for key, val in item.items():
                print(f"{key}: {val}")
        browser.close()


def rendered_rows(page) -> list[str]:
    """当前侧边栏实际渲染出来的会话行 id。"""
    return page.evaluate(
        """() => [...document.querySelectorAll('[data-row-key^="session:"]')]
             .map((e) => e.getAttribute('data-row-key').replace('session:', ''))"""
    )


def find_row(page, session_id: str, steps: int = 60):
    """在虚拟化侧边栏里滚动查找指定会话行，返回选择器或 None。"""
    # DOM 里 data-row-key 的值是 "session:<完整会话 id>"（含 session- 前缀）。
    full = session_id if session_id.startswith("session-") else f"session-{session_id}"
    selector = f'div[data-row-key="session:{full}"]'
    if page.query_selector(selector) is not None:
        return selector
    for direction in ("down", "up"):
        for _ in range(steps):
            page.evaluate(
                """(dir) => {
                     const row = document.querySelector('[data-row-key^="session:"]');
                     let node = row?.parentElement;
                     while (node && node !== document.body) {
                       const style = getComputedStyle(node);
                       if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && node.scrollHeight > node.clientHeight + 4) break;
                       node = node.parentElement;
                     }
                     (node ?? document.scrollingElement).scrollBy(0, dir === 'down' ? 320 : -320);
                   }""",
                direction,
            )
            page.wait_for_timeout(220)
            if page.query_selector(selector) is not None:
                return selector
    return None


def cleanup(ids: list[str], apply: bool) -> None:
    """删除本次验证产生的测试会话（逐条按 data-row-key 精确定位，dry-run 只打印菜单项）。"""
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        boot(page)
        page.wait_for_timeout(3000)
        print("expand:", click_text(page, "展开其余", timeout=8000))
        print("ungrouped:", click_text(page, "未分组", timeout=6000))
        page.wait_for_timeout(4000)
        rows = rendered_rows(page)
        print(f"rendered rows: {len(rows)}")
        print("row ids:", rows)
        for session_id in ids:
            row = find_row(page, session_id)
            if row is None:
                print(f"{session_id}: row not found (rendered={len(rendered_rows(page))}), skipped")
                continue
            # 行操作按钮只在悬停时显形，直接点会被判定 not visible，故先悬停再用 JS 派发点击。
            page.hover(row)
            page.wait_for_timeout(400)
            page.eval_on_selector(f'{row} button[aria-label*="操作"]', "el => el.click()")
            page.wait_for_timeout(900)
            items = page.evaluate(
                """() => [...document.querySelectorAll('[role=menuitem], [role=menu] button, [role=menu] div')]
                     .filter((e) => e.offsetParent !== null)
                     .map((e) => (e.innerText || '').trim()).filter((t) => t !== '' && t.length < 20)"""
            )
            print(f"{session_id}: menu items = {items}")
            if not apply:
                page.keyboard.press("Escape")
                page.wait_for_timeout(400)
                continue
            target = None
            for element in page.query_selector_all("[role=menuitem], [role=menu] button, [role=menu] div"):
                if element.is_visible() and "删除" in (element.inner_text() or ""):
                    target = element
                    break
            if target is None:
                print(f"{session_id}: no 删除 item, skipped")
                page.keyboard.press("Escape")
                continue
            target.click()
            page.wait_for_timeout(1200)
            confirm = None
            for element in page.query_selector_all("button"):
                if element.is_visible() and (element.inner_text() or "").strip() in ("删除", "确认", "确定", "删除会话"):
                    confirm = element
                    break
            if confirm is not None:
                print(f"{session_id}: confirming with {confirm.inner_text()!r}")
                confirm.click()
                page.wait_for_timeout(2500)
            else:
                print(f"{session_id}: no confirm dialog")
            gone = page.query_selector(row) is None
            print(f"{session_id}: removed = {gone}")
        browser.close()


def menuinfo(session_id: str) -> None:
    """诊断（只读）：打开一个会话，打印会话头部按钮与「⋯」菜单项，确认是否有删除入口。"""
    name, value = cookie_pair()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": name, "value": value, "domain": "127.0.0.1", "path": "/"}])
        page = ctx.new_page()
        boot(page)
        page.wait_for_timeout(3000)
        click_text(page, "展开其余", timeout=8000)
        click_text(page, "未分组", timeout=6000)
        page.wait_for_timeout(3000)
        row = find_row(page, session_id)
        print(f"row: {row}")
        if row is None:
            browser.close()
            return
        page.click(row)
        page.wait_for_timeout(4000)
        labels = page.evaluate(
            """() => [...document.querySelectorAll('button')]
                 .map((b) => (b.getAttribute('aria-label') || b.title || b.innerText || '').trim())
                 .filter((t) => t !== '' && t.length < 30)"""
        )
        print(f"buttons: {labels}")
        for element in page.query_selector_all("button"):
            label = (element.get_attribute("aria-label") or element.get_attribute("title") or "").strip()
            if element.is_visible() and label == "更多操作":
                print(f"clicking header button: {label!r}")
                page.eval_on_selector("button[aria-label='更多操作']", "el => el.click()")
                page.wait_for_timeout(1200)
                break
        items = page.evaluate(
            """() => [...document.querySelectorAll('[role=menuitem], [role=menu] button, [role=menu] div')]
                 .filter((e) => e.offsetParent !== null)
                 .map((e) => (e.innerText || '').trim()).filter((t) => t !== '' && t.length < 24)"""
        )
        print(f"menu items: {items}")
        page.screenshot(path=str(SHOTS / "menuinfo.png"))
        browser.close()


def main() -> None:
    """按命令行参数选择验证阶段。"""
    mode = sys.argv[1] if len(sys.argv) > 1 else "probe"
    started = time.time()
    if mode == "probe":
        probe()
    elif mode == "diag":
        diag()
    elif mode == "rowinfo":
        rowinfo()
    elif mode == "menuinfo":
        menuinfo(sys.argv[2])
    elif mode == "cleanup":
        cleanup([arg for arg in sys.argv[2:] if not arg.startswith("--")], "--apply" in sys.argv)
    elif mode == "e2e":
        e2e(sys.argv[2] if len(sys.argv) > 2 else "first")
    else:
        print(f"unknown mode: {mode}")
    print(f"done in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
