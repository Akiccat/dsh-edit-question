# dsh-edit-question —— 编辑提问并重发

在 DeepSeek Harness Web GUI 的每条用户提问旁加一个「✎ 编辑提问」入口：改完原文后从这条提问重新开始，
该提问之后的对话不再进入新会话的上下文，界面直接切到新会话。

- **图片兼容**：原提问里的图片会随重发一起带上（内容寻址复用同一个附件，不重复占空间），在对话框里逐张预览、可单独删掉不想重发的那张；也可以在编辑框里**直接粘贴补充图片**。
- **两个出口**：对话框里二选一——保留原会话（新旧并存）或删除原会话（新会话建好后归档原会话，列表里只留新的）。**默认选中「删除原会话」**，需要留档时手动切回保留。

![编辑提问对话框](https://raw.githubusercontent.com/Akiccat/dsh-edit-question/main/shots/e2e-image-03-dialog.png)

## 为什么是 fork 而不是原地截断

DSH 没有「删除会话中某段历史」的官方能力：会话文件是多帧拼接的 zstd 追加日志（带内核写租约），外部改写会破坏
租约与 seq 连续性；`surfaceOp: replace` 只能让模型「看不见」，记录仍在界面上。所以本插件用官方唯一的「从某点重开」语义
`ctx.sessions.fork({ sessionId, atSeq })` 复制前缀生成子会话，再在子会话里重发编辑后的提问。

切点取**上一轮的 `turn/end`**：第 1 轮用 `0`（原提问自己的 `agent/inbox/spliced` 在 `turn/start` 之前，从它之后开始会把旧提问带进新会话），
第 N>1 轮用第 N-1 轮结束的 seq。

> 长会话的历史是**分页加载**的（打开时只取最后一页，页边界切在某一轮的 `turn/start` 上）。如果窗口里最靠前的那一轮不是第 1 轮，
> 它的「上一轮」就不在快照里，切点无从计算。这时不会退回 `0`（那等于新会话从零开始、丢掉全部历史），
> 而是提示先点对话顶部的「加载更早」补齐，再重新打开编辑器。

## 安装

### 从 npm（尚未发布）

> 这个包还没发布到 npm（计划中）。发布之后一行即可：

```sh
dsh plugin --profile <profile> add dsh-edit-question
```

在那之前请用下面的手工挂载方式。

### 手工挂载（源码）

```powershell
# 1) 让 profile 能解析到这个包：目录联接（junction，不需要管理员权限）
New-Item -ItemType Junction -Path "$HOME\.dsh\profiles\desktop\node_modules\dsh-edit-question" `
  -Target "<本仓库路径>"
```

```yaml
# 2) 在 profile 的 cordis.patch.yml 末尾追加
- insert:
    - id: edit-question
      name: dsh-edit-question
```

`cordis.patch.yml` 受 HMR 监视：改完即热重组，**不需要重启应用**；浏览器端代码在刷新页面后生效。

> ⚠️ 不要同时使用两种方式：`package.json` 里的 `dsh.bundle.patch`（供 `dsh plugin add` 用）与 profile 里的手工 `insert` 行
> 会用同一个 id 挂载两次，启动时报错。迁移到 bundle 安装前，先删掉 profile 里那行 `- id: edit-question`。

## 用法

1. 把鼠标移到任意一轮的提问气泡上，动作行里点「✎ 编辑提问」；
2. 修改文本，可选：粘贴图片补充、或删掉已补的图；
3. 确认「保留原会话」或「删除原会话」（默认删除）；
4. 点「丢弃后续并重发」，界面切换到新会话。

![在原会话上打开编辑器：原文、原图提示、两个出口](https://raw.githubusercontent.com/Akiccat/dsh-edit-question/main/shots/e2e-paste-01-dialog.png)

![重发后：新会话带图，原会话按选择保留或归档](https://raw.githubusercontent.com/Akiccat/dsh-edit-question/main/shots/e2e-image-05-after-submit.png)

## 已知限制

- 「删除原会话」实际调用的是 DSH 原生**归档**（`uiWorkspace.archiveSession`，没有物理删除会话的接口），可在「已归档」里恢复；
  要彻底删掉得自己清理 `~/.dsh/sessions/` 下对应目录。
- 文件类附件（非图片）不重发：它的上传回执（`receiptId`）只对原会话有效，对话框会单独提示。
- 当前模型需支持图片输入，否则宿主会在 prompt 准入时拒绝并给出提示。
- 编辑很靠前的轮次时，如果该轮或它的上一轮还没加载进当前分页窗口，对话框会提示先点「加载更早」：
  切点必须落在上一轮的 `turn/end` 上，算不出来时宁可拦住，也不会静默把历史丢成「从零开始」。
- 入口位置依赖宿主 DOM 契约（`data-chat-flow-kind` / `data-chat-turn` / `data-clock`），宿主改版时会自动退回轮尾一行（功能不受影响）。

## 开发

- `docs/DEVELOPMENT.md`：实现细节、宿主 API 依据、验证工具清单与实测记录。
- `tools/`：Playwright 端到端脚本（`e2e-image-edit.py`、`e2e-paste-image.py`）、会话日志读取（`read-session.mjs`）、
  DOM 探测（`probe-*.py`）等，都不参与插件运行。

## 许可

MIT
