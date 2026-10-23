// 读取 .dsh 会话 JSONL（zstd）并打印事件概览。
// 用法：node inspect-session.mjs <session.v4.jsonl.zstd> [--limit N] [--full]
import fs from 'node:fs';
import zlib from 'node:zlib';

const [file, ...rest] = process.argv.slice(2);
if (!file) {
  console.error('usage: node inspect-session.mjs <session.v4.jsonl.zstd> [--limit N] [--full]');
  process.exit(2);
}
const limitIndex = rest.indexOf('--limit');
const limit = limitIndex === -1 ? 40 : Number(rest[limitIndex + 1]);
const full = rest.includes('--full');

const raw = fs.readFileSync(file);
const text = file.endsWith('.zstd') ? zlib.zstdDecompressSync(raw).toString('utf8') : raw.toString('utf8');
const lines = text.split('\n').filter((line) => line.trim() !== '');

let seq = 0;
for (const line of lines.slice(0, limit)) {
  let event;
  try {
    event = JSON.parse(line);
  } catch {
    console.log(`${seq}\t<unparsable ${line.length} bytes>`);
    seq += 1;
    continue;
  }
  const type = event.type ?? event.kind ?? '?';
  const seqField = event.seq ?? event.data?.seq ?? '';
  if (full) {
    console.log(`--- line ${seq} (seq=${seqField}) ---`);
    console.log(JSON.stringify(event, null, 2).slice(0, 4000));
  } else {
    const summary = {};
    for (const key of ['seq', 'type', 'role', 'source', 'id', 'turnId', 'stepId', 'messageId']) {
      if (event[key] !== undefined) summary[key] = event[key];
    }
    const data = event.data ?? event.payload;
    if (data && typeof data === 'object') {
      summary.dataKeys = Object.keys(data).slice(0, 10);
      if (typeof data.text === 'string') summary.textHead = data.text.slice(0, 60);
      if (data.content !== undefined) {
        summary.contentType = Array.isArray(data.content) ? 'array' : typeof data.content;
        if (Array.isArray(data.content) && data.content[0] && typeof data.content[0] === 'object') {
          summary.contentKeys = Object.keys(data.content[0]).slice(0, 8);
          if (typeof data.content[0].text === 'string') summary.contentText = data.content[0].text.slice(0, 60);
        }
      }
      if (data.reason !== undefined) summary.reason = JSON.stringify(data.reason).slice(0, 80);
    }
    console.log(`${seq}\t${type}\t${JSON.stringify(summary)}`);
  }
  seq += 1;
}
console.log(`\ntotal events: ${lines.length}`);
