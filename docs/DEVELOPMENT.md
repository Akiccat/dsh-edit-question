> 本文件是插件开发工作区的原始开发笔记，文中路径以该工作区的 `scripts/dsh-edit-message-plugin/` 为准；本仓库根目录对应其中的 `pkg/`，`tools/`、`shots/` 已随本仓库一并提供。

# dsh-edit-question —— 「编辑提问并重发」插件

在 DSH Web GUI 的每一轮对话底部加一个「✎ 编辑提问」入口：点开后可以修改**当时那条提问**的原文，
确认重发时从这条提问重新开始——该提问之后的所有对话（回答、工具调用、后续轮次）都不会进入新会话的上下文，
界面也直接切到这条提问重开的新会话。

- 图片兼容：原提问里的图片会随重发一起带到新会话（按内容寻址复用同一个附件，不重复占空间）；文件附件仍不重发。
- 对话框里还能**补充图片**：直接 `Ctrl+V` 粘贴或点「+ 添加图片」，缩略图带 `×` 可移除，重发时按「原图在前、补充在后」一起发出。
- 两个出口：对话框里二选一——**保留原会话**（新旧并存）或**删除原会话**（新会话建好后归档原会话，列表里只留新的）。

- 插件包：`pkg/`（宿主半边 `pkg/lib/index.js` 为空实现，全部逻辑在浏览器半边 `pkg/lib/client.js`）
- 运行前提：DSH 桌面版 0.2.0-rc.2（`@deepseek-ai/dsh-client-ui-chat` 提供 `conversation.chat.turnTail` 插槽与 `useChat` 工具包）
- 安装位置：`C:\Users\Samuel\.dsh\profiles\desktop`（profile 的 `node_modules` 目录联接 + `cordis.patch.yml` 的 insert 行）

## 为什么是 fork 而不是原地截断

DSH 没有「删除会话中某段历史」的官方能力，三条路都被排除：

| 方案 | 结论 |
| --- | --- |
| 原地改写会话文件（`session.v4.jsonl.zstd`） | 会话文件是**多帧拼接的 zstd 追加日志**，seq 连续、带内核写租约（flock / Windows 命名信号量）。外部改写会破坏写入租约、seq 连续性与投影缓存，不可行。 |
| 用 `surfaceOp: replace` 覆盖历史 | 只能让**模型**看不到被覆盖内容（空 content 投影为 null），无法从界面记录里移除，用户会看到「记录还在但模型失忆」的错位状态。 |
| 启动一个新会话再重发 | 会丢掉该提问**之前**的对话，与「从当前提问重新开始」不符。 |

因此采用官方唯一的「从某点重开」语义：`ctx.sessions.fork({ sessionId, atSeq })` —— 复制 `0..atSeq` 前缀生成子会话，
再在子会话里用编辑后的文本发起新一轮。原会话保持只读不变（留在会话列表中，标题相同但新会话带 ` (1)` 后缀）。

## 切点（atSeq）规则

切点必须落在**上一轮已完成的边界**上，这是本插件唯一需要小心的地方：

| 编辑的轮次 | 切点 | 原因 |
| --- | --- | --- |
| 第 1 轮 | `0` | 没有可继承的历史。**不能**用 `turn.start.seq - 1`：提交提问时宿主会先写一条 `agent/inbox/spliced`（把提问放进 agent 收件箱），该事件正好在 `turn/start` 之前；从它之后开始 fork 会把**原提问带进新会话**，导致新会话先执行一次旧提问、编辑后的文本变成第 2 轮（已实测复现，故改用 0）。 |
| 第 N>1 轮 | 第 N-1 轮的 `turn/end` 事件 seq | 轮次边界上收件箱已被消费干净，前缀正好是该提问之前的全部对话；该提问自己的 `agent/inbox/spliced` 在其后，不会被继承。 |

## 交互与实现要点

- 入口位置：该轮**开场提问**那条用户消息的「时间 + 复制」动作行里（`✎ 编辑提问` 紧跟复制图标），
  不再是轮尾单独一行（截图见 `shots/edit-button-in-row.png`）。
- 为什么用 portal：这行由宿主的 `UserMessageNodeView` 直接渲染，没有对外插槽（`conversation.chat.turnTail`
  只提供轮尾、动作行**之前**的位置），所以插件仍注册在 `conversation.chat.turnTail`，拿到 turn 后用
  `createPortal` 把按钮搬进 `[data-chat-flow-kind="user"][data-chat-turn=N] [data-clock="start"]`。
  这两个属性是宿主做滚动定位与悬停淡入用的公共 DOM 契约，比哈希类名稳定；找不到该行（虚拟化回收、
  该轮提问不在 DOM）时自动退回原来的轮尾一行。
- 该行是 28px 高的 flex 行（gap 8px），按钮按 22px 高、零外边距适配；点击时 `stopPropagation`，
  避免触发宿主的行级点击。
- 老轮次的行默认 `opacity:0`，悬停消息才淡入（宿主行为，与时间/复制一致）；最新一条提问的行常显。
- 对话框：`conversation.input.overlay` 插槽，用 `react-dom` 的 `createPortal` 挂到 `document.body`（插槽位于输入框子树内，
  直接渲染会被祖先的层叠/裁剪上下文限制），`z-index: 1200` 高于应用最大层级。
- 只用浏览器静态基座表内的模块（`react`、`react-dom`、`@deepseek-ai/dsh-client-store`），
  不 require 任何 Harness Client 包；控件自写，样式只用 `--dsw-*` 主题 token。
- 会话定位：`useChat(locations.getTurn(turnId))` → 该轮第一个 `kind === "user"` 节点即开场提问，其 `data.content` 的文本分片为原文、`type === "image"` 分片为要重发的图片。
- 图片重发：会话日志里的图片分片是 `{type:"image", attachment:{attachmentId:"sha256:…", mediaType, width, height, bytes}}`。
  提交前先在**原会话**上 `binding.session.readAttachment(attachmentId)` 读回字节（`session.attachment` 只授权给日志里引用过它的会话），
  转成 `{type:"image", mediaType, data:<base64>}` 交给 `prompt`；宿主 `ctx.attachments.admitPromptContent()` 会按内容寻址重新入库，
  因此新会话拿到的是**同一个 attachmentId**，不会重复占用空间。
- 补充图片：对话框的 `textarea` 监听 `paste`，只在 `clipboardData` 里真有 `image/*` 文件时 `preventDefault`（纯文本粘贴不受影响），
  `File.arrayBuffer()` → `base64` 后存进编辑器状态；缩略图用 `data:` URL 直接渲染（不用 `createObjectURL`，省掉 revoke）。
  隐藏的 `<input type="file" accept="image/*" multiple>` 走同一个 `ingest`，按钮文案见 `dialog.addImage`；单张上限 10 MB、最多 10 张。
- 两个出口：`removeOriginal` 状态来自对话框的二选一，默认「保留原会话」。选「删除」时在 **fork + prompt 都成功之后**调用
  `ctx.uiWorkspace.archiveSession(sessionId, {stopActivity:true})`——DSH 没有物理删除会话的接口（`dsh-session-persistence-jsonl` 明确「seam 无删除接口」），
  归档是原生唯一的「从列表移除」语义，可在「已归档」里恢复；归档失败只记 `console.warn`，不影响新会话。
- 提交链路：`readAttachment`（有图片时）→ `ctx.sessions.fork({sessionId, atSeq, increaseTitle:true})` → `ctx.sessions.using(childId, {source:"edit-question"}, …)`
  → `binding.session.prompt([...imageParts, {type:"text", text}], "queue")` →（可选归档原会话）→ `ctx.uiWorkspace.openSession(childId)`。
- 每个会话一份编辑器状态（`createSnapshotStore`），通过插槽 `hooks: { editor }` 暴露为 `useEditor`；文本经过词典服务（zh/en）。

## 安装 / 卸载

安装（等价于 `plugin_manager` 的 `install_bundle` 手工版，因为本会话没有该工具）：

```powershell
# 1) 让 profile 能解析到包：目录联接（junction，不需要管理员权限）
New-Item -ItemType Junction -Path 'C:\Users\Samuel\.dsh\profiles\desktop\node_modules\dsh-edit-question' `
  -Target 'D:\AIWorkSpace-ds-harness\scripts\dsh-edit-message-plugin\pkg'
```

```yaml
# 2) 在 profile 的 cordis.patch.yml 末尾追加（本仓库已追加，备份见 cordis.patch.yml.bak-before-edit-question）
- insert:
    - id: edit-question
      name: dsh-edit-question
```

profile 的 `cordis.patch.yml` 受 HMR 监视：改完即热重组，**不需要重启应用**；浏览器端代码在刷新页面后生效
（客户端包按内容哈希发版，宿主按新哈希提供 `plugins/??dsh-edit-question/client.js&rev=…`）。

卸载：删掉 `cordis.patch.yml` 里的 insert 行与那个 junction 即可；插件不写任何其他状态。

## 打包 / 上架插件市场

`pkg/` 已经是可直接发布的形态，不需要构建（`lib/*.js` 就是运行时代码）：

| 项 | 内容 |
| --- | --- |
| `dsh.bundle.patch` | `./cordis.patch.yml` —— 这是 `dsh plugin add` 能识别的前提；**只有 `dsh.client` 不算是可安装插件**（官方列表最常见的拒收原因） |
| `cordis.patch.yml` | 一行 `insert`（`id: edit-question`, `name: dsh-edit-question`），安装时自动挂载，不用再手改 profile |
| `dsh.client` | `platform: web` + 4 个 inject 包（session-controller / ui-chat / ui-conversation / ui-workspace） |
| `files` | `lib`、`locale`、`cordis.patch.yml`、`README.md`、`LICENSE`（`shots/` 与 `tools/` 不进包） |
| `publishConfig.access` | `public`（scoped 包才会用到，留着无害） |

```powershell
cd scripts\dsh-edit-message-plugin\pkg
npm pack --dry-run     # 实测 0.1.0：16.1 KB / 7 个文件（LICENSE、README.md、cordis.patch.yml、lib/{client,index}.js、locale/{en,zh}.json、package.json）
npm publish --access public   # 需要先 npm login；包名 dsh-edit-question 目前未被占用
```

上架到 dsh-market：市场本身不维护插件目录，它实时读 [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin)
的 `plugins.json`。收录方式是给那个仓库提 **一个** PR 文件 `data/plugins/<owner>__<repo>.yml`（**不要**改 README，README 是脚本生成的）。

> 代码仓库已建：<https://github.com/Akiccat/dsh-edit-question>（public，带 `dsh-plugin` topic，MIT）。
> npm 尚未发布（需要 `npm login` 后 `cd pkg && npm publish --access public`）。

```yaml
url: https://github.com/Akiccat/dsh-edit-question   # 必须与仓库地址完全一致
name: Akiccat/dsh-edit-question
category: session                                   # 备选：ui
description:
  en: 'Edit a sent question and resend it: images are re-attached, the conversation restarts from that turn, and the original session can be kept or archived.'
  zh: '编辑已发送的提问并重发：图片一并带上，从该提问重新开始，原会话可选保留或归档。'
```

收录条件（官方 contributing.md）：仓库要在一周内创建满 1 天、带 `dsh-plugin` topic、`package.json` 声明 `dsh.bundle`、
代码真实可用；有 npm 包会被 CI 自动采集版本与下载量（yml 里手写 `npm:` 会被校验拒绝）。上架通常一天内生效。

⚠️ 从手工安装迁移到 `dsh plugin add dsh-edit-question` 时，**先删掉 profile 自己 `cordis.patch.yml` 里那行 `- id: edit-question`**，
否则 bundle patch 与手工行会用同一个 id 挂载两次，启动时报错。

## 在内置插件列表里的显示

「设置 → 内置插件 → 插件列表」列的是 Loader 里所有非 group 条目（见 `dsh-host-plugin-inventory` 的 `readPluginInventory`），
本插件是 `insert` 出来的普通条目，所以出现在**「全局插件」**分组里（该分组默认收起；「会话插件」分组只是 Agent 预设的组合行）。

- 标题/描述来自 `locale/en.json`、`locale/zh.json` 的 `meta.title` / `meta.description`；缺失时才回退到
  `package.json` 的 `name`（去掉 `dsh-` 前缀）和顶层 `description`。`package.json` 里那个 `meta` 字段**不参与**这里的显示。
- 这两个文件要通过 `exports` 暴露（`"./locale/*.json": "./locale/*.json"`），否则宿主解析 `${name}/locale/en.json` 会失败并静默回退。
- 依赖 Node 的包解析，**改了 `exports` 或新增 locale 文件后要重启应用**（进程内 `package.json` 解析结果是缓存的），
  只刷新页面不够；改 locale 的文案内容则重开设置页即可。

## 已知限制

- **「删除原会话」= 归档**：DSH 没有物理删除会话的 seam，本插件调用的是原生归档（`archiveSession`），会话文件仍在磁盘上，可在「已归档」里恢复。想要彻底删除得在归档后自己清理 `~/.dsh/sessions/` 对应目录。
- **补充图片的形状限制**：只接受浏览器给出的 `image/*`（PNG/JPEG/WebP/GIF 等），单张 ≤ 10 MB、最多 10 张；宿主侧 `imageLimits` 还会再校验一次，超限的错误会显示在对话框里。
- **文件附件不重发**：原提问带 `type:"file"` 分片时只重发图片与文本（文件的 `receiptId` 只对原会话有效），对话框会提示。
- **模型必须支持图片**：宿主在 prompt 准入时会检查当前模型的 `inputModalities`，不支持图片的模型会直接拒绝（错误显示在对话框里）。
- **排队消息**：若在被编辑轮次运行时你又排了消息（收件箱非空），fork 会把队列一并继承。
- **非用户提问的轮次**：由通知/系统消息触发的轮次，其开场 `user` 节点可能是系统文本，对话框会如实展示将要重发的内容。
- **入口位置依赖宿主 DOM 契约**：靠 `data-chat-flow-kind` / `data-chat-turn` / `data-clock` 找动作行，
  宿主改版若改了这几个属性，按钮会自动退回轮尾一行（功能不受影响，只是位置回到旧样式）。
- 插件不修改 DSH 核心包，也不改 `.dsh` 下除 profile 自身 `node_modules` / `cordis.patch.yml` 之外的文件。

## 验证工具

`tools/` 下是本插件的开发/验证工具（都不参与插件运行）：

| 文件 | 用途 |
| --- | --- |
| `tools/asar.mjs` | 读取 `app.asar`（list / extract），用于把 DSH 包解到 `.ref/` 里做只读参考 |
| `tools/window.mjs` | 在超大压缩包文件里按标记打印行窗口（`node window.mjs <file> <marker> [before] [after]`） |
| `tools/slot-catalog.mjs` | 解析客户端插槽目录（`--full` 输出全部 90 个插槽） |
| `tools/read-session.mjs` | 多帧 zstd 会话日志读取（`--types` / `--limit` / `--grep` / `--raw`） |
| `tools/auth-cookie.mjs` | 按 `dsh-client-connection` 的算法，用 `~/.dsh/.credentials.yaml` 里的持久密钥现签一个 web 会话 cookie（自动化验证用；启动令牌只存在于进程内，外部拿不到） |
| `tools/verify-gui.py` | Playwright 端到端验证，模式：`diag`（页面结构诊断）/ `probe`（插件入口探测）/ `rowinfo`、`menuinfo`（侧边栏与会话头部菜单结构诊断）/ `cleanup <会话id…> [--apply]`（会话列表清理，只读 dry-run 默认）/ `e2e first`、`e2e second`（两个端到端场景） |
| `tools/probe-layout.py` | 只读探测消息行 DOM：`python probe-layout.py [base] [out.png] [会话标题] [focus\|click]`，`focus` 把首条用户消息滚到中间并截动作行，`click` 点开入口验证 portal 后的事件与对话框 |
| `tools/probe-sessions.py` | 只读探测侧栏会话列表：打印每行的 `data-row-key` 与标题；`--menu <row-key>` 列出该行按钮，`--archive <row-key>` 归档一行（用于清理验证产生的临时会话） |
| `tools/e2e-image-edit.py` | 端到端验证图片重发与两个出口：新建会话 → 上传图片 → 提问 → 编辑提问（选「删除原会话」）→ 校验新会话含图片、原会话被归档 |
| `tools/e2e-paste-image.py` | 端到端验证「补充图片」：新建会话上传图 A 提问 → 打开编辑对话框用 `ClipboardEvent` 粘贴图 B → 提交 → 校验新会话首条消息含 2 张图 |
| `tools/probe-inventory.py` | 只读探测「设置 → 内置插件 → 全局插件」：`python probe-inventory.py [base] [out.png] [关键字]`，列出命中卡片并截图，用于确认插件是否被 Loader 收录及其显示名 |
| `shots/` | 验证截图（对话框、两个场景重发后的新会话、页面诊断图、`edit-button-in-row.png` 入口落位） |
| `tools/e2e-first.log`、`tools/e2e-second.log` | 两次端到端运行的完整控制台输出（插件日志、页面错误、界面文本） |
| `.ref/` | 从 `app.asar` 抽出的只读参考树（DSH 官方包与插件开发技能文档） |

已实测（真实 GUI + 会话日志双重证据）：

```powershell
$env:PYTHONIOENCODING='utf-8'
C:\Python314\python.exe tools\verify-gui.py e2e first    # 编辑第 1 轮提问
C:\Python314\python.exe tools\verify-gui.py e2e second   # 编辑第 2 轮提问
C:\Python314\python.exe tools/e2e-image-edit.py          # 图片重发 + 「删除原会话」出口
C:\Python314\python.exe tools/e2e-paste-image.py         # 对话框里粘贴补充图片
node tools\read-session.mjs 'C:\Users\Samuel\.dsh\sessions\--D-AIWorkSpace-ds-harness--\session-<子会话id>\session.v4.jsonl.zstd' --limit 40 --raw
```

- `e2e first`：父会话 `session-4e7a8baa`（1 轮）→ 编辑第 1 轮 → 子会话 `session-6891464f` 只含「请只回复两个字：好的」及其回答，
  原提问与回答完全不在事件日志里（插件日志 `turn=1 userSeq=8 cut=0`）。
- `e2e second`：父会话 `session-1699fb3a`（2 轮）→ 编辑第 2 轮 → 子会话 `session-bc1aa794` 继承 `seq 0..18`（第 1 轮完整保留），
  随后是编辑后的「请只回复两个字：明白了吗」，原第 2 轮（`请只回复两个字：明白`）及其回答未被继承
  （插件日志 `turn=2 userSeq=23 cut=18`，切点即第 1 轮 `turn/end`）。
- `e2e-image-edit`：新建会话上传 `shots/edit-button-in-row.png` 并提问 → 编辑该轮提问（对话框显示「原提问带的图片会随本次重发一起带上」）
  → 选「删除原会话」提交 → 插件日志 `forked … at seq 0 -> session-c3f0e3ca`、`archived original session-e4663fbd`，
  新会话日志的 user 消息为 `[image sha256:557a65d7…, text 图片重发自检：请只回复两个字：收到]`（附件 id 与原图一致，即内容寻址复用），
  侧栏原测试会话行消失、只剩新会话的 `(1)` 行。
- `e2e-paste-image`：新建会话上传图 A 提问 → 打开编辑对话框 `paste` 图 B（`paste result: {'ok': True, 'thumbnails': 1}`）→ 提交（保留原会话），
  新会话首条用户消息渲染出 **2 张图**（原图 + 补充图）并正常收到回复，无 page error；会话日志里是
  `[image sha256:557a65d7…(790×168, 13424B), image sha256:25829929…(1440×900, 80885B), text 粘贴补充图片自检…]`，
  即「原图按内容寻址复用 + 补充图新入库」的预期顺序。

验证会在会话列表里留下若干测试会话（标题多为「请只回复两个字…」或「图片重发自检…」）。实测 DSH 0.2.0-rc.2 的 Web GUI 只在
侧边栏行菜单提供「重命名 / 置顶 / 归档」、会话头部「更多操作」只提供「下载 Session 日志 / 反馈」，
**没有物理删除会话的入口**，因此这些测试会话需要手工归档；`tools/probe-sessions.py --archive <row-key>` 可以批量归档。
