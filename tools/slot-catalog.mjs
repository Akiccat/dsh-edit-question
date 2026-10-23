// 解析 dsh-cordis-client-runner 内嵌的 slot 声明目录，输出扩展点总表。
// 用法：node slot-catalog.mjs <client.js> [filter]
import fs from 'node:fs';

const [file, filter] = process.argv.slice(2);
if (!file) {
  console.error('usage: node slot-catalog.mjs <client.js> [filter]');
  process.exit(2);
}
const lines = fs.readFileSync(file, 'utf8').split('\n');
const entries = [];
let current = null;
const field = /^\s*([a-zA-Z]+): (.*)$/;

for (const line of lines) {
  const keyMatch = /^\s*key: "([^"]+)",\s*$/.exec(line);
  if (keyMatch && current === null) {
    current = { key: keyMatch[1] };
    continue;
  }
  if (current === null) continue;
  const match = field.exec(line);
  if (match) {
    const [, name, raw] = match;
    if (name === 'key' && /^"/.test(raw)) {
      entries.push(current);
      current = { key: raw.slice(1, -1) };
      continue;
    }
    if (current[name] === undefined && raw.length < 400) {
      current[name] = raw.replace(/,$/, '').replace(/^"|"$/g, '');
    }
  }
  if (/^\s*}\s*$/.test(line) && current.occupants !== undefined) {
    // entry closed
  }
  if (/^\s*\},?\s*$/.test(line) && current.key !== undefined && current.declaredBy !== undefined) {
    entries.push(current);
    current = null;
  }
}
if (current !== null) entries.push(current);

const isSlot = (entry) => ['single', 'list', 'keyed', 'chain'].includes(entry.kind) && entry.declaredBy !== undefined;
const slots = entries.filter(isSlot);
const matched = filter ? slots.filter((entry) => entry.key.includes(filter)) : slots;
console.log(`entries=${entries.length} slots=${slots.length} matched=${matched.length}`);
if (process.argv.includes('--full')) {
  console.log(JSON.stringify(matched, null, 2));
  process.exit(0);
}
for (const entry of matched) {
  console.log(`\n### ${entry.key}\n  kind=${entry.kind} scope=${entry.scope}\n  declaredBy=${entry.declaredBy}\n  summary=${entry.summary}`);
}
