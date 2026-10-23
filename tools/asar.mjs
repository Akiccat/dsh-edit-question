// 读取 Electron app.asar 归档：列出条目 / 抽取文件。
// 用法：
//   node asar.mjs list <archive> [--out <file>] [--depth N] [--prefix <p>]
//   node asar.mjs extract <archive> <outDir> [--prefix <p>] [--exclude <substr>]
import fs from 'node:fs';
import path from 'node:path';

/** 解析 asar 头部，返回 { dataOffset, entries }。 */
function readArchive(archive) {
  const fd = fs.openSync(archive, 'r');
  try {
    const sizeBuf = Buffer.alloc(8);
    fs.readSync(fd, sizeBuf, 0, 8, 0);
    // pickle: [uint32 payloadSize][uint32 value]
    const headerSize = sizeBuf.readUInt32LE(4);
    const headerBuf = Buffer.alloc(headerSize);
    fs.readSync(fd, headerBuf, 0, headerSize, 8);
    // pickle: [uint32 payloadSize][uint32 stringLen][string bytes...]
    const stringLen = headerBuf.readUInt32LE(4);
    const json = headerBuf.subarray(8, 8 + stringLen).toString('utf8');
    const header = JSON.parse(json);
    const dataOffset = 8 + headerSize;
    const entries = [];
    const walk = (node, prefix) => {
      for (const [name, child] of Object.entries(node.files ?? {})) {
        const p = prefix ? `${prefix}/${name}` : name;
        if (child.files) {
          entries.push({ path: p, dir: true, size: 0, offset: 0 });
          walk(child, p);
        } else {
          entries.push({
            path: p,
            dir: false,
            size: Number(child.size ?? 0),
            offset: dataOffset + Number(child.offset ?? 0),
            unpacked: Boolean(child.unpacked),
          });
        }
      }
    };
    walk(header, '');
    return { fd, dataOffset, entries };
  } catch (error) {
    fs.closeSync(fd);
    throw error;
  }
}

const [command, archive, ...rest] = process.argv.slice(2);
const flag = (name, fallback = undefined) => {
  const index = rest.indexOf(`--${name}`);
  return index === -1 ? fallback : rest[index + 1];
};
const has = (name) => rest.includes(`--${name}`);

if (!command || !archive) {
  console.error('usage: node asar.mjs list|extract <archive> [...]');
  process.exit(2);
}

const { fd, entries } = readArchive(archive);
try {
  if (command === 'list') {
    const prefix = flag('prefix', '');
    const depth = Number(flag('depth', 0));
    const scoped = entries.filter((e) => e.path.startsWith(prefix));
    const rows = scoped.map((e) => {
      const parts = e.path.split('/');
      const shown = depth > 0 ? parts.slice(0, depth).join('/') : e.path;
      return { path: e.path, size: e.size, dir: e.dir, shown };
    });
    const out = flag('out');
    if (has('top')) {
      const seen = new Map();
      for (const e of scoped) {
        const rel = prefix && e.path.startsWith(prefix) ? e.path.slice(prefix.length) : e.path;
        const parts = rel.split('/');
        const key = parts.slice(0, depth || 1).join('/');
        const bucket = seen.get(key) ?? { key, files: 0, bytes: 0 };
        if (!e.dir) {
          bucket.files += 1;
          bucket.bytes += e.size;
        }
        seen.set(key, bucket);
      }
      const text = [...seen.values()]
        .sort((a, b) => a.key.localeCompare(b.key))
        .map((b) => `${b.files}\t${b.bytes}\t${b.key}`)
        .join('\n');
      if (out) fs.writeFileSync(out, text);
      else console.log(text);
    } else {
      const text = rows.map((r) => `${r.dir ? 'd' : 'f'}\t${r.size}\t${r.path}`).join('\n');
      if (out) fs.writeFileSync(out, text);
      else console.log(text);
    }
    console.error(`entries=${entries.length} matched=${scoped.length}`);
  } else if (command === 'extract') {
    const outDir = rest[0];
    if (!outDir || outDir.startsWith('--')) {
      console.error('extract requires <outDir>');
      process.exit(2);
    }
    const prefix = flag('prefix', '');
    const exclude = flag('exclude');
    const limit = Number(flag('limit', 0));
    let count = 0;
    let bytes = 0;
    for (const e of entries) {
      if (e.dir || e.unpacked) continue;
      if (prefix && !e.path.startsWith(prefix)) continue;
      if (exclude && e.path.includes(exclude)) continue;
      if (limit && count >= limit) break;
      const target = path.join(outDir, e.path);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      const buffer = Buffer.alloc(e.size);
      if (e.size > 0) fs.readSync(fd, buffer, 0, e.size, e.offset);
      fs.writeFileSync(target, buffer);
      count += 1;
      bytes += e.size;
    }
    console.error(`extracted=${count} bytes=${bytes} -> ${outDir}`);
  } else {
    console.error(`unknown command: ${command}`);
    process.exit(2);
  }
} finally {
  fs.closeSync(fd);
}
