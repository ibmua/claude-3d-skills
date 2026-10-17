// Image derivatives requested by visible UI only. No scan, Blender or standing worker.
import fs from 'node:fs/promises';
import localFs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
const script = fileURLToPath(new URL('./tools/image_thumbnail.py', import.meta.url));
const pending = new Map();
let running = 0;
const waiters = [];
async function slot() { if (running >= 2) await new Promise(resolve => waiters.push(resolve)); running++; }
function release() { running--; waiters.shift()?.(); }
const thumbnailFile = (source, cacheRoot, width, stat) => path.join(cacheRoot, 'images',
  createHash('sha256').update(`webp-v1:${source}:${stat.size}:${stat.mtimeMs}:${width}`).digest('hex') + '.webp');
export async function imageThumbnail(source, cacheRoot, requestedWidth, sourceStamp) {
  const width = [160, 320, 640].includes(+requestedWidth) ? +requestedWidth : 320;
  if (!/\.(png|jpe?g|webp)$/i.test(source)) throw Object.assign(new Error('unsupported image'), { status: 415 });
  // Catalog image URLs already pin a file version. A matching local derivative
  // may be served even while SSHFS metadata reads are stalled. A miss still
  // reads/validates the source and uses its actual stamps, never the supplied hint.
  if (Number.isInteger(sourceStamp?.size) && sourceStamp.size > 0 && sourceStamp.size <= 128 * 1024 * 1024 && Number.isFinite(sourceStamp.mtimeMs) && sourceStamp.mtimeMs > 0) {
    const cached = thumbnailFile(source, cacheRoot, width, sourceStamp);
    if (localFs.statSync(cached, { throwIfNoEntry: false })?.isFile()) return cached;
  }
  const stat = await fs.stat(source);
  if (!stat.isFile() || stat.size > 128 * 1024 * 1024) throw Object.assign(new Error('image too large'), { status: 413 });
  const file = thumbnailFile(source, cacheRoot, width, stat);
  const key = file;
  if (await fs.stat(file).catch(() => null)) return file;
  if (!pending.has(key)) {
    const work = (async () => {
      await slot();
      const temporary = file + '.' + randomUUID() + '.tmp';
      try {
        await fs.mkdir(path.dirname(file), { recursive: true });
        await new Promise((resolve, reject) => {
          const child = spawn(process.env.THUMBNAIL_PYTHON || 'python3', [script, source, temporary, String(width)], { stdio: ['ignore', 'ignore', 'pipe'] });
          let err = '';
          child.stderr.on('data', chunk => { err = (err + chunk).slice(-2000); });
          child.on('error', reject);
          const timeout = setTimeout(() => { child.kill(); reject(new Error('thumbnail conversion timed out')); }, 20000);
          child.on('close', code => { clearTimeout(timeout); code === 0 ? resolve() : reject(new Error(err || `thumbnail conversion exited ${code}`)); });
        });
        // A file changed during conversion must be requested again, never cached as the new source.
        const after = await fs.stat(source);
        if (after.size !== stat.size || after.mtimeMs !== stat.mtimeMs) throw new Error('image changed; retry');
        await fs.rename(temporary, file); return file;
      } finally { await fs.rm(temporary, { force: true }); release(); }
    })();
    pending.set(key, work); work.finally(() => pending.delete(key)).catch(() => {});
  }
  return pending.get(key);
}
