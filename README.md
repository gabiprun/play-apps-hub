# App Hub — app.prundaru.ca

Static directory of every app in the Play developer account, for sharing test builds
with the team. Live at **https://app.prundaru.ca** (GitHub Pages).

## How it stays current

`sync.py` talks to the Google Play Developer API and writes `apps.json` + `icons/`:

- **title / short description** — `edits().listings()`
- **icon** — `edits().images()`, downloaded into `icons/` so the page has no external deps
- **track + version** — `edits().tracks()`, highest live track wins the badge

A scheduled Action (`.github/workflows/sync.yml`) reruns it **every 6 hours**, plus on
manual dispatch and on any push that touches `packages.json` / `links.json` / `sync.py`.
It commits only when something actually changed.

Run it by hand: `python3 sync.py` (uses the local service-account key), or
`gh workflow run sync.yml`.

## Adding a new app

Add its package name to `packages.json` and push. Everything else — name, icon,
description, track, version — comes from Play on the next sync.

To skip that manual step entirely, enable the **Google Play Developer Reporting API** on
Cloud project `centered-carver-498907-d3` (990773981467). `sync.py` already tries
`apps.search()` first and will then discover new apps on its own; it silently falls back
to `packages.json` while the API is off.

## Internal-test links

No Google API exposes the tester opt-in URL, so `links.json` holds them by hand:

> Play Console → app → Testing → Internal testing → **Testers** tab → *Copy link*

Set it either from the site's admin mode (below) or by editing `links.json` and pushing.
Apps without a link show a disabled "Test link not set" button and still link to their
Play Store page.

## Admin edit mode

The **Admin** button on the site unlocks in-browser editing of the test links and lets you
add a package — no local checkout needed, works from a phone.

There is no backend: `admin.json` holds a GitHub token encrypted with AES-256-GCM under a
key derived from the admin password (PBKDF2-SHA256, 600k iterations). The password decrypts
it in memory only and the page commits through the GitHub Contents API. A wrong password
fails the GCM auth tag, so no token ever comes out.

**Setup:**

1. Create a **fine-grained** PAT at github.com/settings/personal-access-tokens/new —
   *Resource owner* your account, *Only select repositories* → `play-apps-hub`,
   *Repository permissions* → **Contents: Read and write**, nothing else. Set an expiry.
2. `python3 make_admin.py` — paste the token, choose a long random password.
3. Commit and push the generated `admin.json`.

Rotate by rerunning step 2–3 with a fresh token. Revoking the PAT on GitHub instantly kills
edit mode regardless of who holds the password.

**Threat model, plainly:** this repo is public, so anyone can download `admin.json` and
attempt an offline brute force. 600k PBKDF2 iterations make that slow, but the password is
the only barrier — use a generated one, not a memorable phrase. Worst case if it falls: write
access to this one repo, and nothing else. The token cannot touch other repos or your account.

## Credentials

The Action uses repo secret `PLAY_SERVICE_ACCOUNT` — the JSON body of
`play-894@centered-carver-498907-d3.iam.gserviceaccount.com`. **This repo is public; never
commit the key file itself.**

## Note on privacy

GitHub Pages content is publicly readable — private Pages sites require GitHub Enterprise.
The page carries `noindex` + `robots.txt` so it stays out of search results, but the URL is
effectively an unlisted link, not a protected one. For a real login gate, this would need to
move behind Cloudflare Access on the home server like the other apps.
