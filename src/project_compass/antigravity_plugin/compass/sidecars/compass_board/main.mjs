import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import http from 'node:http';
import { dirname, join, delimiter } from 'node:path';
import { fileURLToPath } from 'node:url';
import { SidecarApp, Response } from 'sidecar_sdk';
import {
  computePythonSourceFingerprint,
  createHotReloadTracker,
  resolveWatchPackageDir,
} from './hot_reload.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const RUNTIME_CONFIG_PATH = join(__dirname, 'runtime_config.json');

function loadRuntimeConfig() {
  try {
    if (existsSync(RUNTIME_CONFIG_PATH)) {
      const parsed = JSON.parse(readFileSync(RUNTIME_CONFIG_PATH, 'utf-8'));
      if (parsed && typeof parsed === 'object') return parsed;
    }
  } catch {
    // Fall back to environment variables / PATH Python resolution.
  }
  return {};
}

const runtimeCfg = loadRuntimeConfig();
const watchPackageDir = resolveWatchPackageDir(runtimeCfg);
const hotReload = createHotReloadTracker({ watchDir: watchPackageDir, throttleMs: 1000 });
const internalSecret = randomBytes(24).toString('hex');
let activeProjectPath = null;
let pythonChild = null;
let backendPort = null;
let backendPromise = null;
let lastRestartFailureAt = 0;
let consecutiveFailures = 0;
let shuttingDown = false;

function escapeHtml(text) {
  return String(text ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function killChild(child) {
  if (!child) return;
  try {
    child.stdin?.end();
  } catch {
    // Ignore already-closed pipe.
  }
  try {
    if (!child.killed && child.exitCode === null) {
      child.kill('SIGTERM');
    }
  } catch {
    // Process already exited.
  }
}

function buildBackendEnv() {
  const env = { ...process.env };
  env.COMPASS_SIDECAR_INTERNAL_SECRET = internalSecret;
  env.PYTHONUNBUFFERED = '1';
  const configuredPyPath = String(runtimeCfg.pythonpath || '').trim();
  if (configuredPyPath) {
    const existing = String(env.PYTHONPATH || '').trim();
    const parts = existing ? existing.split(delimiter).filter(Boolean) : [];
    if (!parts.includes(configuredPyPath)) {
      env.PYTHONPATH = [configuredPyPath, ...parts].join(delimiter);
    }
  }
  return env;
}

function stopBackendChild(immediate = false) {
  shuttingDown = true;
  const child = pythonChild;
  pythonChild = null;
  backendPort = null;
  backendPromise = null;
  if (!child) return;
  try {
    child.stdin?.end();
  } catch {
    // Ignore already-closed pipe.
  }
  if (immediate) {
    killChild(child);
    return;
  }
  setTimeout(() => {
    killChild(child);
  }, 600).unref?.();
}

process.on('SIGINT', () => {
  stopBackendChild(true);
  process.exit(0);
});
process.on('SIGTERM', () => {
  stopBackendChild(true);
  process.exit(0);
});
process.on('exit', () => {
  stopBackendChild(true);
});

function spawnBackendChild() {
  return new Promise((resolve, reject) => {
    const pythonExe = String(
      process.env.COMPASS_PYTHON ||
      runtimeCfg.python ||
      (process.platform === 'win32' ? 'python' : 'python3')
    ).trim();
    const initialProject = String(
      activeProjectPath ||
      process.env.PROJECT_COMPASS_PROJECT_PATH ||
      runtimeCfg.default_project_path ||
      process.cwd()
    ).trim();
    const launchFingerprint = watchPackageDir ? computePythonSourceFingerprint(watchPackageDir) : '';
    const child = spawn(
      pythonExe,
      ['-u', '-m', 'project_compass.sidecar_backend', '--sidecar-child', '--project-path', initialProject],
      {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: buildBackendEnv(),
        windowsHide: true,
      },
    );
    pythonChild = child;

    let settled = false;
    let lineBuf = '';
    const errChunks = [];
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      lineBuf = '';
      consecutiveFailures += 1;
      lastRestartFailureAt = Date.now();
      hotReload.markFailed();
      backendPromise = null;
      killChild(child);
      reject(new Error(`Compass sidecar backend startup timeout. ${errChunks.join('')}`));
    }, 10000);

    child.stdout.on('data', (chunk) => {
      if (settled) return;
      lineBuf += chunk.toString('utf-8');
      const nl = lineBuf.indexOf('\n');
      if (nl === -1) return;
      const line = lineBuf.slice(0, nl).trim();
      lineBuf = '';
      try {
        const info = JSON.parse(line);
        const port = Number(info?.port || 0);
        if (!port) throw new Error('missing port');
        settled = true;
        clearTimeout(timer);
        consecutiveFailures = 0;
        backendPort = port;
        backendPromise = null;
        hotReload.markLoaded(launchFingerprint);
        resolve(port);
      } catch (err) {
        settled = true;
        clearTimeout(timer);
        consecutiveFailures += 1;
        lastRestartFailureAt = Date.now();
        hotReload.markFailed();
        backendPromise = null;
        killChild(child);
        reject(new Error(`Invalid backend handshake line '${line}': ${err.message}`));
      }
    });

    child.stderr.on('data', (chunk) => {
      if (errChunks.length < 16) errChunks.push(chunk.toString('utf-8'));
    });

    child.on('error', (err) => {
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        lineBuf = '';
        consecutiveFailures += 1;
        lastRestartFailureAt = Date.now();
        hotReload.markFailed();
        backendPromise = null;
        killChild(child);
        reject(err);
      }
    });

    child.on('exit', (code) => {
      const wasCurrentChild = pythonChild === child;
      if (wasCurrentChild) {
        pythonChild = null;
        backendPort = null;
      }
      if (!settled) {
        settled = true;
        clearTimeout(timer);
        lineBuf = '';
        consecutiveFailures += 1;
        lastRestartFailureAt = Date.now();
        hotReload.markFailed();
        backendPromise = null;
        reject(new Error(`Compass sidecar backend exited (${code}). ${errChunks.join('')}`));
      } else if (!shuttingDown && wasCurrentChild) {
        consecutiveFailures += 1;
        lastRestartFailureAt = Date.now();
      }
    });
  });
}

function restartBackendForCodeChange() {
  const oldChild = pythonChild;
  pythonChild = null;
  backendPort = null;
  consecutiveFailures = 0;
  if (oldChild) {
    try {
      oldChild.stdin?.end();
    } catch {
      // Ignore already-closed pipe.
    }
    setTimeout(() => {
      killChild(oldChild);
    }, 400).unref?.();
  }
  return ensureBackend({ forceReloadCheck: false });
}

function ensureBackend({ forceReloadCheck = false } = {}) {
  if (shuttingDown) {
    return Promise.reject(new Error('Compass sidecar is shutting down'));
  }
  if (backendPort && pythonChild && pythonChild.exitCode === null) {
    if (watchPackageDir && hotReload.checkForChange({ force: forceReloadCheck }).changed) {
      return restartBackendForCodeChange();
    }
    return Promise.resolve(backendPort);
  }
  if (backendPromise) {
    return backendPromise;
  }

  // Assign promise synchronously before cooldown wait so concurrent startup calls share one spawn.
  const promise = (async () => {
    const backoffMs = consecutiveFailures > 0
      ? Math.min(15000, 250 * (2 ** Math.min(consecutiveFailures - 1, 6)))
      : 0;
    const waitMs = Math.max(0, backoffMs - (Date.now() - lastRestartFailureAt));
    if (waitMs > 0) {
      await new Promise((r) => setTimeout(r, waitMs));
    }
    if (shuttingDown) {
      throw new Error('Compass sidecar is shutting down');
    }
    return spawnBackendChild();
  })();

  backendPromise = promise;
  promise.catch(() => {
    if (backendPromise === promise) {
      backendPromise = null;
    }
  });
  return promise;
}

function forwardToBackend(method, pathAndQuery, bodyObj = null, { forceReloadCheck = false } = {}) {
  return ensureBackend({ forceReloadCheck }).then((port) => new Promise((resolve, reject) => {
    const bodyText = bodyObj !== null ? JSON.stringify(bodyObj) : null;
    const headers = {
      Host: `127.0.0.1:${port}`,
      'X-Compass-Sidecar-Secret': internalSecret,
    };
    if (bodyText !== null) {
      headers['Content-Type'] = 'application/json';
      headers['Content-Length'] = Buffer.byteLength(bodyText, 'utf-8');
    }
    const req = http.request(
      {
        hostname: '127.0.0.1',
        port,
        path: pathAndQuery,
        method,
        headers,
        timeout: 15000,
      },
      (resp) => {
        const chunks = [];
        resp.on('data', (c) => chunks.push(c));
        resp.on('end', () => {
          resolve({
            status: resp.statusCode || 200,
            headers: resp.headers || {},
            body: Buffer.concat(chunks),
          });
        });
      },
    );
    req.on('timeout', () => {
      req.destroy(new Error('backend request timeout'));
    });
    req.on('error', (err) => reject(err));
    if (bodyText !== null) req.write(bodyText);
    req.end();
  }));
}

function buildQuery(data) {
  if (!data || typeof data !== 'object') return '';
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(data)) {
    if (v !== undefined && v !== null && String(v) !== '') {
      params.append(k, String(v));
    }
  }
  const qs = params.toString();
  return qs ? `?${qs}` : '';
}

const app = new SidecarApp();

for (const pagePath of ['/', '/index.html']) {
  app.page(pagePath, async () => {
    try {
      const resp = await forwardToBackend('GET', '/', null, { forceReloadCheck: true });
      let html = resp.body.toString('utf-8');
      if (!html.includes('/preload.js') && html.includes('</head>')) {
        html = html.replace('</head>', '  <script src="/preload.js"></script>\n</head>');
      }
      return new Response(html, { contentType: 'text/html; charset=utf-8', status: resp.status });
    } catch (err) {
      return new Response(
        `<!doctype html><html lang="zh-CN"><body><main style="padding:16px;font-family:sans-serif"><h2>Compass 副栏启动失败</h2><p>${escapeHtml(err?.message || err)}</p></main></body></html>`,
        { contentType: 'text/html; charset=utf-8', status: 503 },
      );
    }
  });
}

for (const staticPath of ['/app.js', '/styles.css', '/logo.svg', '/favicon.svg']) {
  app.page(staticPath, async () => {
    try {
      const resp = await forwardToBackend('GET', staticPath);
      return new Response(resp.body, {
        contentType: String(resp.headers['content-type'] || 'text/plain; charset=utf-8'),
        status: resp.status,
      });
    } catch (err) {
      return new Response(String(err?.message || err), {
        contentType: 'text/plain; charset=utf-8',
        status: 503,
      });
    }
  });
}

for (const getRoute of ['/api/state', '/api/health', '/api/evidence', '/api/export', '/api/projects', '/api/projects/scan-status']) {
  app.api(getRoute, async (data) => {
    try {
      const resp = await forwardToBackend('GET', `${getRoute}${buildQuery(data)}`);
      const headers = {};
      if (resp.headers['content-disposition']) {
        headers['Content-Disposition'] = String(resp.headers['content-disposition']);
      }
      return new Response(resp.body, {
        contentType: String(resp.headers['content-type'] || 'application/json; charset=utf-8'),
        status: resp.status,
        headers,
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err?.message || err) }), {
        contentType: 'application/json; charset=utf-8',
        status: 503,
      });
    }
  }, 'GET');
}

for (const postRoute of [
  '/api/projects/activate',
  '/api/projects/scan',
  '/api/projects/scan-status',
  '/api/notes',
  '/api/review',
  '/api/dispatch',
  '/api/investigate',
  '/api/llm-mode',
  '/api/rescan',
  '/api/refresh',
  '/api/extract',
  '/api/query-stats/clear',
]) {
  app.api(postRoute, async (data) => {
    try {
      const resp = await forwardToBackend('POST', postRoute, data || {}, {
        forceReloadCheck: postRoute === '/api/refresh',
      });
      if (postRoute === '/api/projects/activate' && resp.status < 400) {
        try {
          const parsed = JSON.parse(resp.body.toString('utf-8'));
          const nextPath = String(parsed?.project?.path || data?.path || '').trim();
          if (nextPath) activeProjectPath = nextPath;
        } catch {
          // Ignore non-JSON body.
        }
      }
      return new Response(resp.body, {
        contentType: String(resp.headers['content-type'] || 'application/json; charset=utf-8'),
        status: resp.status,
      });
    } catch (err) {
      return new Response(JSON.stringify({ error: String(err?.message || err) }), {
        contentType: 'application/json; charset=utf-8',
        status: 503,
      });
    }
  }, 'POST');
}

app.run().then(() => {
  ensureBackend().catch(() => {});
});
