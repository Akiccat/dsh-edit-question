/**
 * 「编辑提问并重发」插件 —— 浏览器半边。
 *
 * 交互：每轮**开场提问**那条用户消息的「时间 + 复制」动作行里出现一个「编辑提问」入口
 * （该行由宿主渲染、没有对外插槽，因此用 portal 注入；找不到这条行时退回轮尾单独一行），
 * 点击后弹出对话框，里面是该轮开场提问的原文；确认重发时：
 *   1. 用 ctx.sessions.fork 以「该提问之前的最后一个已完成轮次」为切点，另存一个继承前缀的新会话；
 *   2. 在新会话里用编辑后的文本发起新一轮；
 *   3. 打开新会话。
 * 这样从这条提问开始往后的对话记录既不在新会话的上下文里，也不会被当成有效历史，
 * 而原会话保持只读不变（DSH 没有原地截断会话的官方能力，fork 是唯一受支持的「从某点重开」语义）。
 *
 * 本文件是打包产物格式：向 window.__ModuleLoader__ 注册一个惰性 CommonJS 工厂。
 * 只 require 浏览器静态基座表内的模块（react / react-dom / dsh-client-store），
 * 不 require 任何 Harness Client 包，控件与样式自写并只使用主题 token。
 */
window.__ModuleLoader__.load({
  id: "dsh-edit-question",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;
    Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });

    const react = require("react");
    const reactDom = require("react-dom");
    const { createSnapshotStore } = require("@deepseek-ai/dsh-client-store");
    const h = react.createElement;

    /** 本插件拥有的词典命名空间。 */
    const NS = "editQuestion";

    const zh = {
      "action.edit": "编辑提问",
      "action.tooltip": "修改这条提问后重发，并从这条提问重新开始对话",
      "dialog.title": "编辑提问并重发",
      "dialog.hint": "重发后将从这条提问重新开始：这条提问之后的全部对话都不会再进入上下文。",
      "dialog.note": "新会话继承这条提问之前的对话，标题带 (1)。",
      "dialog.images": "原提问带的图片会随本次重发一起带上。",
      "dialog.files": "原提问还带文件附件；文件不支持重发，只重发图片与文本。",
      "dialog.addImage": "+ 添加图片",
      "dialog.paste": "也可以直接在这里粘贴图片（Ctrl+V）。",
      "dialog.removeImage": "移除这张图片",
      "dialog.keep": "保留原会话",
      "dialog.keepHint": "新旧两份对话都留在会话列表里。",
      "dialog.remove": "删除原会话",
      "dialog.removeHint": "新会话建好后归档原会话，列表里只留新的（可在「已归档」里恢复）。",
      "dialog.cancel": "取消",
      "dialog.submit": "丢弃后续并重发",
      "dialog.sending": "正在重发…",
      "dialog.close": "关闭",
      "error.noTarget": "无法定位这条提问（可能已被压缩或被移除）",
      "error.fork": "创建新会话失败",
      "error.prompt": "发送失败",
      "error.attachment": "读取原提问的图片失败",
      "error.imageTooLarge": "图片太大，单张上限 10 MB",
      "error.imageCount": "一次最多补充 10 张图片",
      "error.unknown": "未知错误",
    };

    const en = {
      "action.edit": "Edit question",
      "action.tooltip": "Edit this question and resend, restarting the conversation from it",
      "dialog.title": "Edit question and resend",
      "dialog.hint": "Resending restarts from this question: everything after it leaves the context.",
      "dialog.note": "The new session inherits the earlier conversation and gets a (1) title.",
      "dialog.images": "The images attached to the original question are resent with it.",
      "dialog.files": "The original question also carried file attachments; files are not resent, only images and text.",
      "dialog.addImage": "+ Add images",
      "dialog.paste": "You can also paste images here (Ctrl+V).",
      "dialog.removeImage": "Remove this image",
      "dialog.keep": "Keep the original session",
      "dialog.keepHint": "Both the old and the new conversation stay in the list.",
      "dialog.remove": "Delete the original session",
      "dialog.removeHint": "Once the new session exists the original is archived, so only the new one stays listed (recoverable from Archived).",
      "dialog.cancel": "Cancel",
      "dialog.submit": "Discard and resend",
      "dialog.sending": "Resending…",
      "dialog.close": "Close",
      "error.noTarget": "This question cannot be located (it may be compacted or removed)",
      "error.fork": "Could not create the new session",
      "error.prompt": "Send failed",
      "error.attachment": "Could not read the original images",
      "error.imageTooLarge": "Image is too large (10 MB per image)",
      "error.imageCount": "At most 10 added images per resend",
      "error.unknown": "Unknown error",
    };

    /** 依赖的 Cordis 服务：插槽注册表、会话控制器、工作区导航与词典。 */
    const inject = ["slots", "sessions", "uiWorkspace", "locale"];

    /** 空图片列表：稳定引用，避免订阅回调每次返回新数组。 */
    const EMPTY_IMAGES = Object.freeze([]);

    /** 补充图片的数量与单张字节上限（宿主还会用自己的 imageLimits 再校验一次）。 */
    const MAX_ADDED_IMAGES = 10;
    const MAX_ADDED_IMAGE_BYTES = 10 * 1024 * 1024;

    /** 关闭态编辑器状态。 */
    const CLOSED = Object.freeze({
      open: false,
      text: "",
      busy: false,
      error: null,
      atSeq: -1,
      userSeq: -1,
      /** 原提问里的图片引用（可重发）。 */
      images: EMPTY_IMAGES,
      /** 对话框里补充的图片：{ mediaType, data(base64), preview(dataURL), name }。 */
      extraImages: EMPTY_IMAGES,
      /** 原提问里是否有无法重发的 file 分片。 */
      files: false,
      /** 是否在重发成功后归档原会话。 */
      removeOriginal: false,
    });

    /**
     * 取轮次标识：owner 传下来的 turn 是 TurnLocation（其 .turn 才是轮次号），
     * 但不同版本可能直接给数字，两种都接受。
     * @param turn - 轮次位置对象或轮次号。
     * @returns 轮次号，无法识别时为 undefined。
     */
    function turnIdOf(turn) {
      if (typeof turn === "number") return turn;
      if (turn !== null && typeof turn === "object" && typeof turn.turn === "number") return turn.turn;
      return undefined;
    }

    /**
     * 找出该轮的开场提问节点（Chat 快照里 kind === "user" 的第一个节点）。
     * @param snapshot - Chat 快照。
     * @param turnId - 轮次号。
     * @returns 用户消息节点，找不到时 undefined。
     */
    function openingUserNode(snapshot, turnId) {
      if (snapshot === undefined || turnId === undefined) return undefined;
      const locations = snapshot.locations;
      const nodes = snapshot.nodes;
      if (locations === undefined || nodes === undefined) return undefined;
      const keys = locations.getTurn(turnId);
      if (!Array.isArray(keys)) return undefined;
      for (const key of keys) {
        const node = nodes.get(key);
        if (node !== undefined && node.kind === "user") return node;
      }
      return undefined;
    }

    /**
     * 拼接消息的文本分片（图片/附件分片不参与）。
     * @param content - 消息内容分片数组。
     * @returns 纯文本。
     */
    function textOf(content) {
      if (!Array.isArray(content)) return "";
      const parts = [];
      for (const part of content) {
        if (part !== null && typeof part === "object" && part.type === "text" && typeof part.text === "string") parts.push(part.text);
      }
      return parts.join("\n");
    }

    /**
     * 提取消息里可重发的图片引用。
     * 会话日志里图片分片形如 { type: "image", attachment: { attachmentId, mediaType, width, height, bytes, name } }，
     * attachmentId 是内容寻址的持久引用（sha256:…），重发时读回字节再交给新会话即可复用。
     * @param content - 消息内容分片数组。
     * @returns 图片引用列表（顺序与消息一致）。
     */
    function imageRefsIn(content) {
      const refs = [];
      if (!Array.isArray(content)) return refs;
      for (const part of content) {
        if (part === null || typeof part !== "object" || part.type !== "image") continue;
        const attachment = part.attachment;
        if (attachment === null || typeof attachment !== "object") continue;
        if (typeof attachment.attachmentId !== "string" || attachment.attachmentId === "") continue;
        refs.push({
          attachmentId: attachment.attachmentId,
          mediaType: typeof attachment.mediaType === "string" ? attachment.mediaType : "image/png",
          name: typeof attachment.name === "string" ? attachment.name : "image.png",
        });
      }
      return refs;
    }

    /**
     * 是否含有无法重发的 file 分片（文件回执只对原会话有效）。
     * @param content - 消息内容分片数组。
     * @returns 含 file 分片时为 true。
     */
    function hasFilePart(content) {
      if (!Array.isArray(content)) return false;
      return content.some((part) => part !== null && typeof part === "object" && part.type === "file");
    }

    /**
     * 字节转 base64（分块，避免超长参数把调用栈撑爆）。
     * @param bytes - 图片字节。
     * @returns base64 字符串。
     */
    function base64Of(bytes) {
      let binary = "";
      const chunk = 0x8000;
      for (let index = 0; index < bytes.length; index += chunk) {
        binary += String.fromCharCode(...bytes.subarray(index, index + chunk));
      }
      return btoa(binary);
    }

    /** 注入动作行后的按钮标记：同时作为样式钩子，避免依赖宿主的哈希类名。 */
    const ROW_MARK = "data-dsh-edit-question";

    /**
     * 找本轮开场提问的「时间 + 复制」动作行（宿主私有渲染，没有对外插槽）。
     * 宿主在消息流条目上标注 data-chat-flow-kind / data-chat-turn，动作行本身标注 data-clock
     * （用户消息为 start），这两个属性是它做滚动定位与悬停淡入用的公共契约，比哈希类名稳定；
     * 同一轮若有多条用户消息（排队插话），querySelector 取第一条，即该轮的开场提问。
     * @param turnId - 轮次号。
     * @returns 动作行元素；该提问不在 DOM 中（虚拟化回收或尚未渲染）时为 null。
     */
    function findActionRow(turnId) {
      if (turnId === undefined) return null;
      const item = document.querySelector(`[data-chat-flow-kind="user"][data-chat-turn="${String(turnId)}"]`);
      if (item === null || item.hasAttribute("hidden")) return null;
      return item.querySelector("[data-clock=\"start\"]");
    }

    /**
     * 跟踪动作行元素：挂载时解析一次，之后用 childList 观察（虚拟化回收、重渲染换掉节点后重新解析）。
     * 目标仍然挂在文档上就直接返回，流式渲染期间不会反复查询；只有真的换了元素才 setState。
     * @param turnId - 轮次号。
     * @returns 当前可用的动作行；找不到时为 null（此时按钮退回轮尾单独一行）。
     */
    function useActionRow(turnId) {
      const [row, setRow] = react.useState(null);
      react.useEffect(() => {
        if (turnId === undefined) return undefined;
        let current = null;
        let frame = 0;
        const settle = () => {
          if (current !== null && current.isConnected) return;
          const next = findActionRow(turnId);
          current = next;
          setRow((previous) => (previous === next ? previous : next));
        };
        settle();
        const observer = new MutationObserver(() => {
          if (frame !== 0) return;
          frame = window.requestAnimationFrame(() => {
            frame = 0;
            settle();
          });
        });
        observer.observe(document.body, { childList: true, subtree: true });
        return () => {
          observer.disconnect();
          if (frame !== 0) window.cancelAnimationFrame(frame);
        };
      }, [turnId]);
      return row;
    }

    /**
     * fork 切点。必须是「提问之前的最后一个已完成轮次」的 turn/end 事件 seq：
     * 该边界上 agent inbox 已被消费干净，切点之后的提问不会被继承。
     * 首轮没有可继承的历史，切到 0（只保留会话元信息事件，不含任何提问），
     * 否则会落在提交提问时写入 inbox 的 agent/inbox/spliced 上，使原提问在新会话里再执行一次。
     * @param snapshot - Chat 快照。
     * @param turnId - 轮次号。
     * @returns 切点 seq（找不到上一轮时为 0）。
     */
    function cutSeqOf(snapshot, turnId) {
      if (snapshot === undefined || turnId === undefined) return 0;
      const timeline = snapshot.timeline;
      if (timeline === undefined || !Array.isArray(timeline.turnOrder) || timeline.turns === undefined) return 0;
      const index = timeline.turnOrder.indexOf(turnId);
      if (index > 0) {
        const previous = timeline.turns.get(timeline.turnOrder[index - 1]);
        const end = previous === undefined ? undefined : previous.end;
        if (end !== undefined && typeof end.seq === "number" && end.seq > 0) return end.seq;
      }
      return 0;
    }

    /**
     * 生成可读的错误文本。
     * @param error - 任意抛出物。
     * @returns 文本。
     */
    function describe(error) {
      if (error === null || error === undefined) return "";
      if (typeof error === "string") return error;
      if (typeof error.message === "string" && error.message !== "") return error.message;
      return String(error);
    }

    /**
     * 建立一个会话的编辑器状态与动作（每个会话一份）。
     * @param ctx - 客户端根上下文。
     * @param sessionId - 会话标识。
     * @returns 编辑器：状态源 + 打开/编辑/提交/关闭动作。
     */
    function createEditor(ctx, sessionId) {
      const store = createSnapshotStore(CLOSED);
      const patch = (fields) => {
        store.set({ ...store.getSnapshot(), ...fields });
      };
      return {
        store,
        /**
         * 打开编辑器。
         * @param input - 目标提问：切点 seq、用户消息 seq、原文、图片引用、是否含文件回执。
         */
        open(input) {
          store.set({
            open: true,
            text: input.text,
            busy: false,
            error: null,
            atSeq: input.atSeq,
            userSeq: input.userSeq,
            images: Array.isArray(input.images) ? input.images : [],
            extraImages: EMPTY_IMAGES,
            files: input.files === true,
            removeOriginal: false,
          });
        },
        /** 关闭编辑器并丢弃草稿。 */
        dismiss() {
          if (store.getSnapshot().busy) return;
          store.set(CLOSED);
        },
        /**
         * 更新草稿文本。
         * @param text - 新文本。
         */
        edit(text) {
          patch({ text });
        },
        /**
         * 追加对话框里补充的图片（由组件读成 base64 后交过来）。
         * @param images - 追加项：{ mediaType, data, preview, name }。
         */
        addImages(images) {
          if (!Array.isArray(images) || images.length === 0) return;
          const current = store.getSnapshot().extraImages;
          patch({ extraImages: [...current, ...images].slice(0, MAX_ADDED_IMAGES) });
        },
        /**
         * 移除一张补充的图片。
         * @param index - 补充列表里的下标。
         */
        removeImage(index) {
          const current = store.getSnapshot().extraImages;
          patch({ extraImages: current.filter((_, position) => position !== index) });
        },
        /**
         * 选择重发后是否归档原会话。
         * @param removeOriginal - true 表示新会话建好后归档原会话。
         */
        setRemoveOriginal(removeOriginal) {
          patch({ removeOriginal });
        },
        /**
         * 提交：读回原提问的图片 → fork 出截断后的新会话 → 在新会话重发 →（可选）归档原会话 → 打开新会话。
         * 错误只记录「错误码 + 细节」，文案由对话框组件按当前语言渲染。
         */
        async submit() {
          const state = store.getSnapshot();
          if (state.busy) return;
          const text = state.text.trim();
          const images = state.images;
          const extra = state.extraImages;
          if (text === "" && images.length === 0 && extra.length === 0) return;
          // fork 的 atSeq 必须是真实存在的事件 seq：切点由按钮侧算好，缺失时退化为 0（只继承会话元信息）。
          const atSeq = state.atSeq >= 0 ? state.atSeq : 0;
          if (state.userSeq < 0) {
            patch({ error: { code: "noTarget", detail: "" } });
            return;
          }
          patch({ busy: true, error: null });
          // 补充的图片已经在对话框里读成 base64，直接按 content part 组装。
          const addedParts = extra.map((image) => ({ type: "image", mediaType: image.mediaType, data: image.data }));
          // 原图要在原会话上读：session.attachment 只授权给日志里引用过它的会话，fork 出的新会话还没有这条引用。
          let imageParts = addedParts;
          if (images.length > 0) {
            try {
              const originalParts = await ctx.sessions.using(sessionId, { source: "edit-question" }, async (reference) => {
                const binding = await reference.ready;
                const parts = [];
                for (const image of images) {
                  const result = await binding.session.readAttachment(image.attachmentId);
                  if (result.ok !== true) throw new Error(result.error === undefined ? image.attachmentId : describe(result.error));
                  parts.push({ type: "image", mediaType: image.mediaType, data: base64Of(result.value.data) });
                }
                return parts;
              });
              imageParts = [...originalParts, ...addedParts];
            } catch (error) {
              patch({ busy: false, error: { code: "attachment", detail: describe(error) } });
              console.error("[dsh-edit-question] read attachment failed:", error);
              return;
            }
          }
          let childId;
          try {
            childId = await ctx.sessions.fork({ sessionId, atSeq, increaseTitle: true });
            console.info(`[dsh-edit-question] forked ${sessionId} at seq ${String(atSeq)} -> ${childId}`);
          } catch (error) {
            patch({ busy: false, error: { code: "fork", detail: describe(error) } });
            console.error("[dsh-edit-question] fork failed:", error);
            return;
          }
          try {
            await ctx.sessions.using(childId, { source: "edit-question" }, async (reference) => {
              const binding = await reference.ready;
              await binding.session.prompt([...imageParts, { type: "text", text }], "queue");
            });
          } catch (error) {
            // 会话已经建好，只是首发失败：保留 childId 让用户能在新会话里手动重发。
            patch({ busy: false, error: { code: "prompt", detail: describe(error) } });
            console.error("[dsh-edit-question] prompt failed:", error);
            return;
          }
          // 归档（DSH 没有物理删除会话的接口）失败不影响新会话：只记录告警。
          if (state.removeOriginal && typeof ctx.uiWorkspace.archiveSession === "function") {
            try {
              await ctx.uiWorkspace.archiveSession(sessionId, { stopActivity: true });
              console.info(`[dsh-edit-question] archived original ${sessionId}`);
            } catch (error) {
              console.warn("[dsh-edit-question] archive original failed:", error);
            }
          }
          store.set(CLOSED);
          ctx.uiWorkspace.openSession(childId);
        },
      };
    }

    /** 轮尾退化位置的按钮样式（拿不到动作行时用）：右对齐并贴在该轮动作行之上。 */
    const tailActionStyle = {
      display: "inline-flex",
      alignItems: "center",
      gap: "4px",
      margin: "0 0 2px auto",
      padding: "1px 6px",
      border: "1px solid transparent",
      borderRadius: "var(--dsw-radius-sm, 6px)",
      background: "transparent",
      color: "var(--dsw-alias-label-tertiary, #8a8f98)",
      font: "inherit",
      fontSize: "var(--dsw-font-xs-13, 12px)",
      lineHeight: "18px",
      cursor: "pointer",
      opacity: 0.85,
    };

    /**
     * 注入用户消息动作行后的按钮样式：该行是 28px 高的 flex 行（时间 + 复制图标，gap 8px），
     * 所以按钮只占 22px 高、不加外边距，保持与图标同一基线。
     */
    const rowActionStyle = {
      display: "inline-flex",
      alignItems: "center",
      gap: "4px",
      height: "22px",
      margin: 0,
      padding: "0 5px",
      border: "1px solid transparent",
      borderRadius: "var(--dsw-radius-sm, 6px)",
      background: "transparent",
      color: "var(--dsw-alias-label-tertiary, #8a8f98)",
      font: "inherit",
      fontSize: "var(--dsw-font-xs-13, 12px)",
      lineHeight: "18px",
      whiteSpace: "nowrap",
      cursor: "pointer",
      opacity: 0.9,
    };

    /** 悬停态（两种位置共用）：提亮文字并铺一层浅背景，与宿主图标按钮的 hover 一致。 */
    const hoverStyle = {
      color: "var(--dsw-alias-label-primary, #1f2329)",
      background: "var(--dsw-alias-interactive-bg-hover, rgba(0,0,0,.05))",
      opacity: 1,
    };

    /**
     * 「编辑提问」入口：先做能力守卫，再交给内部组件（内部无条件调用全部 hook）。
     * @param props - 轮次位置、会话标准工具包与注入的编辑器动作。
     * @returns 按钮；该轮没有可定位的提问或缺少工具包时返回 null。
     */
    function EditQuestionAction(props) {
      if (typeof props.useChat !== "function" || props.t === undefined) return null;
      return h(EditQuestionActionButton, props);
    }

    /**
     * 「编辑提问」按钮本体：渲染到该轮提问的「时间 + 复制」动作行里；拿不到该行时退回轮尾一行。
     * @param props - 轮次位置、会话标准工具包与注入的编辑器动作。
     * @returns 按钮；该轮没有可定位的提问时返回 null。
     */
    function EditQuestionActionButton(props) {
      const { turn, sessionId, useChat, t, openEditor, editDraft } = props;
      const turnId = turnIdOf(turn);
      const row = useActionRow(turnId);
      // 选择器只返回原始值，避免每次渲染产生新对象导致的重复订阅。
      const userSeq = useChat((snapshot) => {
        const node = openingUserNode(snapshot, turnId);
        return node === undefined ? -1 : node.data.seq;
      });
      const atSeq = useChat((snapshot) => cutSeqOf(snapshot, turnId));
      const draft = useChat((snapshot) => {
        const node = openingUserNode(snapshot, turnId);
        return node === undefined ? "" : textOf(node.data.content);
      });
      // 图片/文件分片留到点击时再解析：useChat 的 selector 每次返回新数组会让宿主每帧判定「变了」，
      // 因此这里只订阅一个稳定标量，把最新 content 存在 ref 里。
      const openingContent = react.useRef(null);
      useChat((snapshot) => {
        const node = openingUserNode(snapshot, turnId);
        openingContent.current = node === undefined ? null : node.data.content;
        return node === undefined ? 0 : 1;
      });
      const hover = react.useState(false);
      const hovered = hover[0];
      const setHovered = hover[1];
      if (userSeq < 0) return null;
      const base = row === null ? tailActionStyle : rowActionStyle;
      const button = h("button", {
        type: "button",
        [ROW_MARK]: "",
        title: t("action.tooltip"),
        style: hovered ? { ...base, ...hoverStyle } : base,
        onMouseEnter: () => { setHovered(true); },
        onMouseLeave: () => { setHovered(false); },
        onClick: (event) => {
          // 按钮在消息条目内部：阻止冒泡，避免触发宿主的选中/跳转等行级点击。
          event.stopPropagation();
          const images = imageRefsIn(openingContent.current);
          const files = hasFilePart(openingContent.current);
          console.info(`[dsh-edit-question] open editor session=${sessionId} turn=${String(turnId)} userSeq=${String(userSeq)} cut=${String(atSeq)} images=${String(images.length)}`);
          editDraft(draft);
          openEditor({ atSeq, userSeq, text: draft, images, files });
        },
      }, h("span", { "aria-hidden": true, style: { fontSize: "12px" } }, "✎"), t("action.edit"));
      // 注入宿主的用户消息动作行（时间 + 复制）；portal 保证事件与 React 状态仍归本组件。
      return row === null ? button : reactDom.createPortal(button, row);
    }

    /** 对话框外层的全屏遮罩。 */
    const backdropStyle = {
      position: "fixed",
      inset: "0",
      zIndex: 1200,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--dsw-alias-bg-mask-1, rgba(0, 0, 0, .45))",
      fontFamily: "var(--dsw-font-family, inherit)",
    };

    /** 对话框面板。 */
    const panelStyle = {
      width: "min(640px, calc(100vw - 48px))",
      maxHeight: "calc(100vh - 96px)",
      overflow: "auto",
      padding: "16px",
      border: "1px solid var(--dsw-alias-border-l2, rgba(0, 0, 0, .1))",
      borderRadius: "var(--dsw-radius-panel, 12px)",
      background: "var(--dsw-alias-bg-layer-2, #fff)",
      boxShadow: "var(--dsw-elevation-panel, 0 8px 32px rgba(0, 0, 0, .18))",
      color: "var(--dsw-alias-label-primary, #1f2329)",
      fontSize: "13px",
    };

    /** 次要按钮（取消）。 */
    const secondaryButtonStyle = {
      padding: "5px 12px",
      border: "1px solid var(--dsw-alias-border-l2, rgba(0, 0, 0, .12))",
      borderRadius: "var(--dsw-radius-md, 8px)",
      background: "var(--dsw-alias-bg-layer-1, transparent)",
      color: "var(--dsw-alias-label-primary, #1f2329)",
      font: "inherit",
      cursor: "pointer",
    };

    /** 主按钮（丢弃后续并重发）。 */
    const primaryButtonStyle = {
      padding: "5px 12px",
      border: "1px solid transparent",
      borderRadius: "var(--dsw-radius-md, 8px)",
      background: "var(--dsw-alias-button-primary-fill, #4d6bfe)",
      color: "var(--dsw-alias-label-primary-foreground, #fff)",
      font: "inherit",
      fontWeight: 500,
      cursor: "pointer",
    };

    /**
     * 对话框里的二选一卡片（保留原会话 / 删除原会话）。
     * @param props - 选中态、标题、说明、点击动作与禁用态。
     * @returns 可点击的选项卡片。
     */
    function OptionCard(props) {
      const { selected, label, hint, disabled, onSelect } = props;
      const box = {
        flex: "1 1 0",
        display: "flex",
        flexDirection: "column",
        gap: "2px",
        padding: "8px 10px",
        textAlign: "left",
        border: `1px solid ${selected ? "var(--dsw-alias-border-selected, #4d6bfe)" : "var(--dsw-alias-border-l2, rgba(0, 0, 0, .12))"}`,
        borderRadius: "var(--dsw-radius-md, 8px)",
        background: selected ? "var(--dsw-alias-bg-selected, rgba(77, 107, 254, .08))" : "transparent",
        color: "var(--dsw-alias-label-primary, #1f2329)",
        font: "inherit",
        cursor: disabled ? "default" : "pointer",
        opacity: disabled ? 0.5 : 1,
      };
      return h("button", {
        type: "button",
        style: box,
        disabled,
        "aria-pressed": selected ? "true" : "false",
        onClick: () => { if (!disabled) onSelect(); },
      },
        h("span", { style: { fontWeight: 500 } }, label),
        h("span", { style: { fontSize: "12px", lineHeight: "17px", color: "var(--dsw-alias-label-tertiary, #8a8f98)" } }, hint),
      );
    }

    /**
     * 一张可移除的补充图片缩略图。
     * @param props - 图片、下标与移除动作。
     * @returns 64×64 缩略图 + 右上角移除按钮。
     */
    function ExtraImage(props) {
      const { image, onRemove, label } = props;
      return h("div", { style: { position: "relative", width: "64px", height: "64px" } },
        h("img", {
          src: image.preview,
          alt: image.name,
          style: {
            width: "100%",
            height: "100%",
            objectFit: "cover",
            borderRadius: "var(--dsw-radius-sm, 6px)",
            border: "1px solid var(--dsw-alias-border-l2, rgba(0, 0, 0, .12))",
          },
        }),
        h("button", {
          type: "button",
          "aria-label": label,
          title: label,
          onClick: onRemove,
          style: {
            position: "absolute",
            top: "-6px",
            right: "-6px",
            width: "18px",
            height: "18px",
            padding: "0",
            lineHeight: "16px",
            borderRadius: "9px",
            border: "none",
            background: "rgba(0, 0, 0, .62)",
            color: "#fff",
            fontSize: "12px",
            cursor: "pointer",
          },
        }, "×"),
      );
    }

    /**
     * 编辑提问对话框：读取该会话的编辑器状态，渲染草稿、重发选项与提交动作。
     * @param props - 编辑器状态 hook 与注入动作。
     * @returns 打开时的全屏对话框，否则 null。
     */
    function EditQuestionDialog(props) {
      const { useEditor, editDraft, submitDraft, dismissEditor, setRemoveOriginal, addImages, removeImage, archiveAvailable, t } = props;
      const state = useEditor((snapshot) => snapshot);
      const area = react.useRef(null);
      const picker = react.useRef(null);
      const [imageNotice, setImageNotice] = react.useState(null);
      react.useEffect(() => {
        if (state.open && area.current !== null) {
          area.current.focus();
          const end = area.current.value.length;
          area.current.setSelectionRange(end, end);
        }
      }, [state.open]);
      if (!state.open || t === undefined) return null;
      /**
       * 读入用户补充的图片：校验数量与单张字节上限，转成 base64 交给编辑器。
       * @param files - 来自粘贴或文件选择的图片。
       */
      const ingest = async (files) => {
        const room = MAX_ADDED_IMAGES - state.extraImages.length;
        if (files.length > room) {
          setImageNotice(t("error.imageCount"));
          return;
        }
        const accepted = [];
        let tooLarge = false;
        for (const file of files) {
          if (!file.type.startsWith("image/")) continue;
          if (file.size > MAX_ADDED_IMAGE_BYTES) {
            tooLarge = true;
            continue;
          }
          const bytes = new Uint8Array(await file.arrayBuffer());
          const mediaType = file.type === "" ? "image/png" : file.type;
          const data = base64Of(bytes);
          accepted.push({ mediaType, data, preview: `data:${mediaType};base64,${data}`, name: file.name === "" ? "image.png" : file.name });
        }
        setImageNotice(tooLarge ? t("error.imageTooLarge") : null);
        addImages(accepted);
      };
      /**
       * 剪贴板里带图片时拦下默认粘贴，改成「补充图片」；纯文本粘贴保持原样。
       * @param event - 粘贴事件。
       */
      const onPaste = (event) => {
        const clip = event.clipboardData;
        if (clip === null || clip === undefined) return;
        const files = [];
        for (const item of clip.items) {
          if (item.kind !== "file" || !item.type.startsWith("image/")) continue;
          const file = item.getAsFile();
          if (file !== null) files.push(file);
        }
        if (files.length === 0) return;
        event.preventDefault();
        void ingest(files);
      };
      const stop = (event) => { event.stopPropagation(); };
      const failure = state.error === null ? null : `${t(`error.${state.error.code}`)}${state.error.detail === "" ? "" : `：${state.error.detail}`}`;
      const blank = state.text.trim() === "" && state.images.length === 0 && state.extraImages.length === 0;
      const panel = h("div", {
        style: panelStyle,
        role: "dialog",
        "aria-modal": "true",
        "aria-label": t("dialog.title"),
        onKeyDown: (event) => {
          stop(event);
          if (event.key === "Escape") dismissEditor();
          if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) void submitDraft();
        },
        onKeyUp: stop,
        onKeyPress: stop,
      },
        h("div", { style: { display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" } },
          h("div", { style: { fontSize: "14px", fontWeight: 600 } }, t("dialog.title")),
        ),
        h("div", { style: { color: "var(--dsw-alias-label-secondary, #5c6068)", lineHeight: "19px", marginBottom: "10px" } }, t("dialog.hint")),
        h("textarea", {
          ref: area,
          value: state.text,
          readOnly: state.busy,
          spellCheck: false,
          rows: 6,
          style: {
            width: "100%",
            boxSizing: "border-box",
            minHeight: "96px",
            maxHeight: "40vh",
            padding: "8px 10px",
            border: "1px solid var(--dsw-alias-border-l2, rgba(0, 0, 0, .12))",
            borderRadius: "var(--dsw-radius-md, 8px)",
            background: "var(--dsw-alias-bg-layer-1, #fff)",
            color: "var(--dsw-alias-label-primary, #1f2329)",
            font: "inherit",
            lineHeight: "20px",
            resize: "vertical",
          },
          onChange: (event) => { editDraft(event.target.value); },
          onPaste,
        }),
        state.images.length > 0 ? h("div", { style: { marginTop: "8px", color: "var(--dsw-alias-label-secondary, #5c6068)" } }, t("dialog.images")) : null,
        state.files ? h("div", { style: { marginTop: "8px", color: "var(--dsw-alias-state-warn-label, #b7791f)" } }, t("dialog.files")) : null,
        state.extraImages.length > 0 ? h("div", { style: { display: "flex", flexWrap: "wrap", gap: "10px", marginTop: "10px" } },
          state.extraImages.map((image, index) => h(ExtraImage, {
            key: `${index}:${image.name}`,
            image,
            label: t("dialog.removeImage"),
            onRemove: () => { removeImage(index); },
          })),
        ) : null,
        h("div", { style: { display: "flex", alignItems: "center", gap: "10px", marginTop: "10px" } },
          h("button", {
            type: "button",
            style: { ...secondaryButtonStyle, padding: "3px 9px" },
            disabled: state.busy || state.extraImages.length >= MAX_ADDED_IMAGES,
            onClick: () => { if (picker.current !== null) picker.current.click(); },
          }, t("dialog.addImage")),
          h("span", { style: { color: "var(--dsw-alias-label-tertiary, #8a8f98)" } }, t("dialog.paste")),
          h("input", {
            ref: picker,
            type: "file",
            accept: "image/*",
            multiple: true,
            style: { display: "none" },
            onChange: (event) => {
              const files = event.target.files === null ? [] : [...event.target.files];
              event.target.value = "";
              void ingest(files);
            },
          }),
        ),
        imageNotice === null ? null : h("div", { style: { marginTop: "6px", color: "var(--dsw-alias-state-warn-label, #b7791f)" } }, imageNotice),
        h("div", { style: { display: "flex", gap: "8px", marginTop: "12px" } },
          h(OptionCard, {
            selected: state.removeOriginal !== true,
            label: t("dialog.keep"),
            hint: t("dialog.keepHint"),
            disabled: state.busy,
            onSelect: () => { setRemoveOriginal(false); },
          }),
          h(OptionCard, {
            selected: state.removeOriginal === true,
            label: t("dialog.remove"),
            hint: t("dialog.removeHint"),
            disabled: state.busy || !archiveAvailable,
            onSelect: () => { setRemoveOriginal(true); },
          }),
        ),
        h("div", { style: { marginTop: "8px", color: "var(--dsw-alias-label-tertiary, #8a8f98)" } }, t("dialog.note")),
        state.error === null ? null : h("div", { style: { marginTop: "8px", color: "var(--dsw-alias-label-error, #d93026)" } }, failure),
        h("div", { style: { display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "14px" } },
          h("button", { type: "button", style: secondaryButtonStyle, disabled: state.busy, onClick: () => { dismissEditor(); } }, t("dialog.cancel")),
          h("button", {
            type: "button",
            style: state.busy || blank ? { ...primaryButtonStyle, opacity: 0.6, cursor: "default" } : primaryButtonStyle,
            disabled: state.busy || blank,
            onClick: () => { void submitDraft(); },
          }, state.busy ? t("dialog.sending") : t("dialog.submit")),
        ),
      );
      // 挂到 body：本插槽位于输入框子树内，直接渲染会被祖先的层叠/裁剪上下文限制。
      return reactDom.createPortal(
        h("div", {
          style: backdropStyle,
          onMouseDown: (event) => { if (event.target === event.currentTarget) dismissEditor(); },
        }, panel),
        document.body,
      );
    }

    /**
     * 客户端插件主体：注册词典、每个会话一份编辑器、轮尾入口与对话框两个插槽条目。
     * @param ctx - 客户端根上下文。
     */
    function apply(ctx) {
      ctx.effect(() => ctx.locale.register(NS, { zh, en }), "dsh-edit-question: dictionaries");
      const editors = new Map();
      /**
       * 取（或建）某会话的编辑器。
       * @param sessionId - 会话标识。
       * @returns 编辑器。
       */
      const editorFor = (sessionId) => {
        let editor = editors.get(sessionId);
        if (editor === undefined) {
          editor = createEditor(ctx, sessionId);
          editors.set(sessionId, editor);
        }
        return editor;
      };
      ctx.effect(() => () => { editors.clear(); }, "dsh-edit-question: per-session editors");
      // 入口：宿主只在「已完成轮次」的轮尾给我们插槽（owner props 提供 turn/seq/openFile，
      // 会话标准工具包提供 sessionId/useChat/t），按钮再由 portal 搬到该轮提问的动作行里。
      ctx.slots.inject("conversation.chat.turnTail", () => ctx.slots.register({
        name: "conversation.chat.turnTail",
        id: "edit-question",
        order: 20,
        locale: NS,
        inject: (sessionId) => {
          const editor = editorFor(sessionId);
          return {
            hooks: { editor: editor.store },
            openEditor: (input) => { editor.open(input); },
            editDraft: (text) => { editor.edit(text); },
          };
        },
      }, EditQuestionAction));
      // 对话框：与反馈对话框同处输入区浮层，但通过 portal 渲染到 body。
      ctx.slots.inject("conversation.input.overlay", () => ctx.slots.register({
        name: "conversation.input.overlay",
        id: "edit-question-dialog",
        order: 3,
        locale: NS,
        inject: (sessionId) => {
          const editor = editorFor(sessionId);
          return {
            hooks: { editor: editor.store },
            editDraft: (text) => { editor.edit(text); },
            submitDraft: () => editor.submit(),
            dismissEditor: () => { editor.dismiss(); },
            setRemoveOriginal: (value) => { editor.setRemoveOriginal(value); },
            addImages: (images) => { editor.addImages(images); },
            removeImage: (index) => { editor.removeImage(index); },
            archiveAvailable: typeof ctx.uiWorkspace.archiveSession === "function",
          };
        },
      }, EditQuestionDialog));
    }

    exports.apply = apply;
    exports.inject = inject;
    return module.exports;
  },
});
