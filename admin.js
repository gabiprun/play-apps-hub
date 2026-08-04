/* Admin edit mode.
   The page holds no secret in the clear: admin.json carries a GitHub token
   encrypted under the admin password (PBKDF2-SHA256 -> AES-256-GCM). Unlocking
   decrypts it in memory only, and edits are committed straight to the repo via
   the GitHub Contents API. Wrong password => GCM auth failure => no token. */

const Admin = {
  cfg: null,
  token: null,
  links: {},

  get unlocked() {
    return !!this.token;
  },

  async loadConfig() {
    try {
      this.cfg = await (await fetch('admin.json?t=' + Date.now())).json();
      return true;
    } catch {
      return false;
    }
  },

  async unlock(password) {
    const dec = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
    const { kdf, iv, ciphertext } = this.cfg;

    const material = await crypto.subtle.importKey(
      'raw', new TextEncoder().encode(password), 'PBKDF2', false, ['deriveKey']);
    const key = await crypto.subtle.deriveKey(
      { name: 'PBKDF2', salt: dec(kdf.salt), iterations: kdf.iterations, hash: kdf.hash },
      material, { name: 'AES-GCM', length: 256 }, false, ['decrypt']);

    let plain;
    try {
      plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: dec(iv) }, key, dec(ciphertext));
    } catch {
      throw new Error('Wrong password.');
    }

    const token = new TextDecoder().decode(plain);
    const probe = await fetch(`https://api.github.com/repos/${this.cfg.repo}`, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json' },
    });
    if (!probe.ok) {
      throw new Error(`Token rejected by GitHub (${probe.status}). It may have expired.`);
    }

    this.token = token;
  },

  lock() {
    this.token = null;
  },

  /* Read-modify-write a JSON file in the repo through the Contents API. */
  async commit(path, obj, message) {
    const api = `https://api.github.com/repos/${this.cfg.repo}/contents/${path}`;
    const headers = {
      Authorization: `Bearer ${this.token}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
    };

    const head = await fetch(`${api}?ref=main&t=${Date.now()}`, { headers });
    if (!head.ok) throw new Error(`Could not read ${path} (${head.status})`);
    const sha = (await head.json()).sha;

    const body = new TextEncoder().encode(JSON.stringify(obj, null, 2) + '\n');
    let bin = '';
    body.forEach((b) => (bin += String.fromCharCode(b)));

    const put = await fetch(api, {
      method: 'PUT',
      headers,
      body: JSON.stringify({ message, content: btoa(bin), sha, branch: 'main' }),
    });
    if (!put.ok) {
      const detail = await put.text();
      throw new Error(`Save failed (${put.status}): ${detail.slice(0, 160)}`);
    }
  },

  async saveLinks(links) {
    const payload = {
      _comment:
        "Internal-testing opt-in links. No Google API exposes these - copy from Play Console > Testing > Internal testing > Testers tab > 'Copy link'. Key = package name.",
      ...links,
    };
    await this.commit('links.json', payload, 'admin: update internal test links');
  },

  async addPackage(pkg, packages) {
    const next = Array.from(new Set([...packages, pkg])).sort();
    await this.commit(
      'packages.json',
      {
        _comment:
          'Fallback app list, used when the Play Developer Reporting API is not enabled. Add a package name here when you publish a new app.',
        packages: next,
      },
      `admin: add ${pkg}`
    );
    return next;
  },
};
