/**
 * 为本地 DSH Web GUI 生成合法浏览器会话 cookie。
 *
 * 背景：dsh 的 web 服务只接受两种认证输入——进程启动令牌（`?token=`，随机生成且只存在于进程内，
 * 外部拿不到）或由本机 `.credentials.yaml` 里持久化签名密钥签发的 cookie。本脚本按
 * dsh-client-connection 的算法重新签发一个 cookie，用于自动化验证（Playwright / HTTP 探测）。
 *
 * 用法：node auth-cookie.mjs [authority] [days]
 *   authority 默认 127.0.0.1:19387；days 默认 1（必须不超过 web 配置的 cookieMaxAgeDays）。
 * 输出：一行 `name=value`，可直接作为 Cookie 请求头。
 */
import { createHash, createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/** web 服务使用的 cookie 前缀与负载版本。 */
const COOKIE_PREFIX = "dsh-auth-";
const PAYLOAD_VERSION = 1;

/**
 * base64url 编码（无填充），与 dsh 内部实现一致。
 * @param value - 字节缓冲。
 * @returns base64url 字符串。
 */
function encodeBase64Url(value) {
  return Buffer.from(value).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/u, "");
}

/**
 * base64url 解码。
 * @param value - base64url 字符串。
 * @returns 字节缓冲。
 */
function decodeBase64Url(value) {
  const padded = value.replaceAll("-", "+").replaceAll("_", "/");
  return Buffer.from(padded, "base64");
}

/**
 * 从 `.credentials.yaml` 中取出 client-connection/browser-session 的签名密钥。
 * 文件是严格的小型 YAML：只包含 credentials 映射，这里用最小的行解析避免引入 YAML 依赖。
 * @param text - 文件内容。
 * @returns 32 字节密钥。
 */
function readSecret(text) {
  const lines = text.split(/\r?\n/u);
  const start = lines.findIndex((line) => /^\s*client-connection\/browser-session:\s*$/u.test(line));
  if (start === -1) throw new Error("credentials: client-connection/browser-session record not found");
  for (let index = start + 1; index < lines.length; index += 1) {
    const line = lines[index];
    if (line.trim() !== "" && !line.startsWith(" ") && !line.startsWith("\t")) break;
    const match = /^\s+secret:\s*"?([A-Za-z0-9_-]+)"?\s*$/u.exec(line);
    if (match !== null) {
      const decoded = decodeBase64Url(match[1]);
      if (decoded.byteLength !== 32) throw new Error(`credentials: unexpected secret length ${String(decoded.byteLength)}`);
      return decoded;
    }
  }
  throw new Error("credentials: secret field not found in the browser-session record");
}

const authority = process.argv[2] ?? "127.0.0.1:19387";
const days = Number(process.argv[3] ?? "1");
const text = readFileSync(join(homedir(), ".dsh", ".credentials.yaml"), "utf8");
const secret = readSecret(text);
const issuedAt = Date.now();
const expiresAt = issuedAt + days * 24 * 60 * 60 * 1000;
const body = encodeBase64Url(Buffer.from(JSON.stringify({ version: PAYLOAD_VERSION, authority, issuedAt, expiresAt }), "utf8"));
const name = COOKIE_PREFIX + encodeBase64Url(createHash("sha256").update(authority).digest());
const value = `v1.${body}.${encodeBase64Url(createHmac("sha256", secret).update(body).digest())}`;
process.stdout.write(`${name}=${value}\n`);
