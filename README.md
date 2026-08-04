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

Paste it as the value for that package in `links.json` and push. Apps without a link show a
disabled "Test link not set" button and still link to their Play Store page.

Pushing `links.json` is enough on its own — the page reads it directly and lets it override
`apps.json`, so a new link is live on the next Pages build (~1 min) without waiting for the
Play sync to fold it in.

There is deliberately **no in-browser editing**: a static site has nowhere safe to keep a
GitHub token, and standing up a backend just to edit a handful of URLs wasn't worth it.
Editing is a `links.json` push.

## Credentials

The Action uses repo secret `PLAY_SERVICE_ACCOUNT` — the JSON body of
`play-894@centered-carver-498907-d3.iam.gserviceaccount.com`. **This repo is public; never
commit the key file itself.**

## Note on privacy

GitHub Pages content is publicly readable — private Pages sites require GitHub Enterprise.
The page carries `noindex` + `robots.txt` so it stays out of search results, but the URL is
effectively an unlisted link, not a protected one. For a real login gate, this would need to
move behind Cloudflare Access on the home server like the other apps.
