// 从超大编译产物中截取 marker 附近的窗口，便于阅读（只读）。
// 用法：node window.mjs <file> <marker> [beforeLines] [afterLines]
import fs from 'node:fs';

const [file, marker, before = '40', after = '120'] = process.argv.slice(2);
if (!file || !marker) {
  console.error('usage: node window.mjs <file> <marker> [before] [after]');
  process.exit(2);
}
const lines = fs.readFileSync(file, 'utf8').split('\n');
const hits = [];
lines.forEach((line, index) => {
  if (line.includes(marker)) hits.push(index);
});
if (hits.length === 0) {
  console.error(`marker not found: ${marker}`);
  process.exit(1);
}
const beforeCount = Number(before);
const afterCount = Number(after);
const emitted = new Set();
for (const hit of hits.slice(0, 6)) {
  const start = Math.max(0, hit - beforeCount);
  const end = Math.min(lines.length, hit + afterCount + 1);
  if (emitted.has(start)) continue;
  emitted.add(start);
  console.log(`\n===== hit at line ${hit + 1} (window ${start + 1}-${end}) =====`);
  for (let index = start; index < end; index += 1) {
    console.log(`${index + 1}: ${lines[index]}`);
  }
}
console.error(`total hits: ${hits.length} at lines ${hits.slice(0, 20).map((h) => h + 1).join(', ')}`);
