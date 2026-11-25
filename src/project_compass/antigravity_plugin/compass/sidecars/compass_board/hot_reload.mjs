import { existsSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

const SKIP_DIR_NAMES = new Set([
  '__pycache__',
  'web',
  'antigravity_plugin',
  '.git',
  'node_modules',
]);

/**
 * Resolve the local `project_compass` Python source directory to watch for
 * hot-restart, or null when watching is disabled (`COMPASS_HOT_RELOAD=0`).
 */
export function resolveWatchPackageDir(runtimeCfg, env = process.env) {
  if (String(env?.COMPASS_HOT_RELOAD ?? '').trim() === '0') {
    return null;
  }
  const pyRoot = String(runtimeCfg?.pythonpath || '').trim();
  if (!pyRoot) {
    return null;
  }
  const pkgDir = join(pyRoot, 'project_compass');
  try {
    if (existsSync(pkgDir) && statSync(pkgDir).isDirectory()) {
      return pkgDir;
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * Compute a deterministic fingerprint across all `.py` files under `pkgDir`
 * (mtimeMs + size) with bounded recursion depth.
 */
export function computePythonSourceFingerprint(pkgDir, maxDepth = 4) {
  if (!pkgDir) return '';
  const records = [];

  function walk(dir, relPrefix, depth) {
    if (depth > maxDepth) return;
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const name = entry.name;
      if (SKIP_DIR_NAMES.has(name)) continue;
      const fullPath = join(dir, name);
      const relPath = relPrefix ? `${relPrefix}/${name}` : name;
      if (entry.isDirectory()) {
        walk(fullPath, relPath, depth + 1);
      } else if (entry.isFile() && name.endsWith('.py')) {
        try {
          const st = statSync(fullPath);
          records.push(`${relPath}:${Math.trunc(st.mtimeMs)}:${st.size}`);
        } catch {
          // Ignore transient files being swapped by atomic saves.
        }
      }
    }
  }

  walk(pkgDir, '', 0);
  if (!records.length) return '';
  records.sort();
  return records.join('|');
}

/**
 * Create a throttled tracker that detects whether Python source files on disk
 * differ from the snapshot loaded when the backend child process spawned.
 */
export function createHotReloadTracker({ watchDir, throttleMs = 1000, now = Date.now } = {}) {
  let loadedFingerprint = '';
  let lastCheckAt = 0;

  return {
    get loadedFingerprint() {
      return loadedFingerprint;
    },
    markLoaded(fp) {
      loadedFingerprint = String(fp || '');
      lastCheckAt = Number(now());
    },
    markFailed() {
      loadedFingerprint = '';
      lastCheckAt = 0;
    },
    checkForChange({ force = false } = {}) {
      if (!watchDir) {
        return { changed: false, fingerprint: '' };
      }
      const ts = Number(now());
      if (!force && lastCheckAt > 0 && ts - lastCheckAt < throttleMs) {
        return { changed: false, fingerprint: loadedFingerprint };
      }
      lastCheckAt = ts;
      const currentFp = computePythonSourceFingerprint(watchDir);
      if (!currentFp) {
        return { changed: false, fingerprint: loadedFingerprint };
      }
      if (!loadedFingerprint) {
        return { changed: true, fingerprint: currentFp };
      }
      return {
        changed: currentFp !== loadedFingerprint,
        fingerprint: currentFp,
      };
    },
  };
}
