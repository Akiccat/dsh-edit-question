// 读取 DSH 会话文件（多帧 zstd 拼接的 JSONL），打印每帧事件概要。
// 用法：node read-session.mjs <session.v4.jsonl.zstd> [--limit N] [--types] [--grep <text>]
import fs from 'node:fs';
import zlib from 'node:zlib';

const [file, ...rest] = process.argv.slice(2);
if (!file) {
  console.error('usage: node read-session.mjs <file> [--limit N] [--types] [--grep text]');
  process.exit(2);
}
const flag = (name, fallback) => {
  const index = rest.indexOf(`--${name}`);
  return index === -1 ? fallback : rest[index + 1];
};
const limit = Number(flag('limit', 60));
const grepText = flag('grep', undefined);
const typesOnly = rest.includes('--types');

const raw = fs.readFileSync(file);
const magic = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
const offsets = [];
for (let index = 0; index + 4 <= raw.length; index += 1) {
  if (raw[index] === 0x28 && raw[index + 1] === 0xb5 && raw[index + 2] === 0x2f && raw[index + 3] === 0xfd) offsets.push(index);
}
const events = [];
const problems = [];
for (let index = 0; index < offsets.length; index += 1) {
  const start = offsets[index];
  const end = index + 1 < offsets.length ? offsets[index + 1] : raw.length;
  try {
    const text = zlib.zstdDecompressSync(raw.subarray(start, end)).toString('utf8');
    for (const line of text.split('\n')) {
      if (line.trim() === '') continue;
      try {
        events.push(JSON.parse(line));
      } catch {
        problems.push(`non-JSON in frame ${index}: ${line.slice(0, 80)}`);
      }
    }
  } catch (error) {
    problems.push(`frame ${index} (${start}-${end}) failed: ${error.message}`);
  }
}

if (typesOnly) {
  const counts = new Map();
  for (const event of events) counts.set(event.type, (counts.get(event.type) ?? 0) + 1);
  for (const [type, count] of [...counts.entries()].sort((a, b) => b[1] - a[1])) console.log(`${count}\t${type}`);
  console.log(`\nframes=${offsets.length} events=${events.length} problems=${problems.length}`);
  if (problems.length > 0) console.log(problems.slice(0, 5).join('\n'));
  process.exit(0);
}

let seq = 0;
for (const event of events) {
  seq += 1;
  if (grepText !== undefined && !JSON.stringify(event).includes(grepText)) continue;
  if (seq > limit) break;
  if (rest.includes('--raw')) {
    console.log(`${seq}\t${JSON.stringify(event)}`);
    continue;
  }
  const summary = { seq: event.seq, type: event.type };
  const data = event.data ?? {};
  if (data.id !== undefined) summary.id = typeof data.id === 'string' ? data.id.slice(0, 12) : data.id;
  if (data.turn !== undefined) summary.turn = data.turn;
  if (data.step !== undefined) summary.step = data.step;
  if (data.source !== undefined) summary.source = data.source?.kind ?? data.source;
  if (Array.isArray(data.content)) summary.content = data.content.map((part) => (part.type === 'text' ? `text:${String(part.text).slice(0, 40)}` : part.type)).join('|');
  if (data.message !== undefined && typeof data.message === 'object') {
    summary.messageKeys = Object.keys(data.message).slice(0, 8);
    if (Array.isArray(data.message.content)) summary.content = data.message.content.map((part) => (part.type === 'text' ? `text:${String(part.text).slice(0, 40)}` : part.type)).join('|');
  }
  if (data.reason !== undefined) summary.reason = JSON.stringify(data.reason).slice(0, 60);
  if (data.meta !== undefined) summary.metaKeys = Object.keys(data.meta).slice(0, 6);
  console.log(`${seq}\t${JSON.stringify(summary)}`);
}
console.log(`\nframes=${offsets.length} events=${events.length} problems=${problems.length}`);
if (problems.length > 0) console.log(problems.slice(0, 5).join('\n'));
