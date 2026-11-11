#!/usr/bin/env node
/**
 * 人体解剖 3D 图谱 - 本地开发服务器
 *
 * 相比 `python -m http.server` 的改进：
 *   1. 对小体积文本/二进制资源做 gzip（模型包 83MB -> 60MB）
 *   2. /models /js 走强缓存（immutable），刷新不再重新下载
 *   3. 支持 ETag / 304、HTTP keep-alive
 *
 * 用法:
 *   node server.js            # 默认 3000 端口
 *   node server.js 8080
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const ROOT = __dirname;
const PORT = Number(process.argv[2] || process.env.PORT || 3000);
const HOST = process.env.HOST || '127.0.0.1';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.txt': 'text/plain; charset=utf-8',
  '.obj': 'text/plain; charset=utf-8',
  '.bin': 'application/octet-stream',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.ico': 'image/x-icon',
  '.map': 'application/json; charset=utf-8',
};

// 只压缩这些类型（.obj 本来就不走这条路，留作兜底）
const COMPRESSIBLE = new Set(['.html', '.js', '.css', '.json', '.svg', '.txt', '.bin', '.obj']);

const gzipCache = new Map(); // realpath -> { mtimeMs, size, buf }

function gzipSyncCached(file, stat) {
  const hit = gzipCache.get(file);
  if (hit && hit.mtimeMs === stat.mtimeMs && hit.size === stat.size) return hit.buf;
  const raw = fs.readFileSync(file);
  const buf = zlib.gzipSync(raw, { level: 6 });
  gzipCache.set(file, { mtimeMs: stat.mtimeMs, size: stat.size, buf });
  return buf;
}

function cacheControl(ext, pathname) {
  if (pathname === '/' || ext === '.html') return 'no-cache';
  // manifest 里带内容哈希，必须每次校验，否则重建模型后浏览器仍用旧包
  if (/manifest\.json$/.test(pathname)) return 'no-cache';
  if (/^\/(models|js)\//.test(pathname)) return 'public, max-age=31536000, immutable';
  if (ext === '.json') return 'no-cache';
  return 'public, max-age=86400';
}

const server = http.createServer((req, res) => {
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  } catch {
    res.writeHead(400).end('Bad Request');
    return;
  }
  if (pathname.endsWith('/')) pathname += 'index.html';

  const filePath = path.join(ROOT, path.normalize(pathname).replace(/^([/\\])+/, ''));
  if (!filePath.startsWith(ROOT)) {
    res.writeHead(403).end('Forbidden');
    return;
  }

  fs.stat(filePath, (err, stat) => {
    if (err || !stat.isFile()) {
      res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }).end('404 Not Found');
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const etag = `W/"${stat.size.toString(16)}-${Math.floor(stat.mtimeMs).toString(16)}"`;
    const headers = {
      'Content-Type': MIME[ext] || 'application/octet-stream',
      'Cache-Control': cacheControl(ext, pathname),
      ETag: etag,
      Vary: 'Accept-Encoding',
    };

    if (req.headers['if-none-match'] === etag) {
      res.writeHead(304, headers).end();
      return;
    }

    const accept = req.headers['accept-encoding'] || '';
    const canGzip = COMPRESSIBLE.has(ext) && /\bgzip\b/.test(accept) && stat.size > 1024;

    if (canGzip) {
      const gzPath = filePath + '.gz';
      fs.stat(gzPath, (gzErr, gzStat) => {
        // 优先用构建阶段预压缩好的 .gz（且不比源文件旧）
        if (!gzErr && gzStat.isFile() && gzStat.mtimeMs >= stat.mtimeMs - 1000) {
          headers['Content-Encoding'] = 'gzip';
          headers['Content-Length'] = gzStat.size;
          res.writeHead(200, headers);
          if (req.method === 'HEAD') return res.end();
          fs.createReadStream(gzPath).pipe(res);
          return;
        }

        let body;
        try {
          body = gzipSyncCached(filePath, stat);
        } catch {
          res.writeHead(500).end('Compression failed');
          return;
        }
        headers['Content-Encoding'] = 'gzip';
        headers['Content-Length'] = body.length;
        res.writeHead(200, headers);
        res.end(req.method === 'HEAD' ? undefined : body);
      });
      return;
    }

    headers['Content-Length'] = stat.size;
    res.writeHead(200, headers);
    if (req.method === 'HEAD') {
      res.end();
      return;
    }
    fs.createReadStream(filePath).pipe(res);
  });
});

server.keepAliveTimeout = 30000;
server.listen(PORT, HOST, () => {
  console.log(`\n  人体解剖 3D 图谱  ->  http://${HOST}:${PORT}\n`);
  console.log(`  静态根目录: ${ROOT}`);
  console.log(`  已启用 gzip / 强缓存，首次加载后刷新走 304\n`);
});
