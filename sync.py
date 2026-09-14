#!/usr/bin/env python3
"""Pull every app in the Play developer account into apps.json + icons/.

Run locally:   python3 sync.py
In CI:         PLAY_SERVICE_ACCOUNT=<json blob> python3 sync.py

Discovery order:
  1. Play Developer Reporting API (apps.search) - picks up new apps automatically.
     Needs the API enabled on the Cloud project; falls through silently if not.
  2. packages.json - the manual list. Add a line when you publish a new app.
"""

import json
import os
import pathlib
import ssl
import sys
import urllib.request
from datetime import datetime, timezone

from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = pathlib.Path(__file__).parent
ICONS = ROOT / "icons"
# Local runs read the key from disk; CI passes it in PLAY_SERVICE_ACCOUNT.
# The default is the real ~/dev path — the old Desktop one only worked
# because Desktop is now a symlink into ~/dev.
LOCAL_KEY = os.environ.get(
    "PLAY_SERVICE_ACCOUNT_FILE",
    str(pathlib.Path.home() / "dev/Vibe coded projects/homevault/app/play-service-account.json"),
)

# Highest track wins for the headline badge.
TRACK_RANK = {"production": 4, "beta": 3, "alpha": 2, "internal": 1}


def summarise_tracks(tracks):
    """Reduce the Play tracks payload to (per-track rows, best track).

    Pure: no API calls, no I/O. Drafts are skipped entirely — a draft release
    is not something anyone can install, so it must not set the headline badge
    or appear in the per-track list. `best` is (rank, track name, version) for
    the highest-ranked track, or None when nothing is live.

    Split out of fetch_app so the badge ordering is testable; see test_sync.py.
    """
    rows = []
    best = None
    for track in tracks:
        live = [r for r in track.get("releases", []) if r.get("status") != "draft"]
        if not live:
            continue
        name = track["track"]
        release = live[0]
        rows.append(
            {
                "track": TRACK_LABEL.get(name, name),
                "version": release.get("name"),
                "status": release.get("status"),
            }
        )
        rank = TRACK_RANK.get(name, 0)
        if best is None or rank > best[0]:
            best = (rank, name, release.get("name"))
    return rows, best


def app_sort_key(app):
    """Highest track first, then title A-Z (case-insensitively)."""
    return (-TRACK_RANK.get(app.get("statusKind"), 0), (app.get("title") or "").lower())
TRACK_LABEL = {
    "production": "Production",
    "beta": "Open testing",
    "alpha": "Closed testing",
    "internal": "Internal testing",
}


def _ssl_context():
    """System python3 on macOS ships no CA bundle; certifi comes with the API client."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


def credentials(scopes):
    blob = os.environ.get("PLAY_SERVICE_ACCOUNT")
    if blob:
        return service_account.Credentials.from_service_account_info(
            json.loads(blob), scopes=scopes
        )
    return service_account.Credentials.from_service_account_file(LOCAL_KEY, scopes=scopes)


def discover_packages():
    """Auto-discover via the Reporting API, else fall back to packages.json."""
    try:
        rep = build(
            "playdeveloperreporting",
            "v1beta1",
            credentials=credentials(["https://www.googleapis.com/auth/playdeveloperreporting"]),
            cache_discovery=False,
        )
        found, token = [], None
        while True:
            resp = rep.apps().search(pageToken=token).execute() if token else rep.apps().search().execute()
            found += [a["packageName"] for a in resp.get("apps", [])]
            token = resp.get("nextPageToken")
            if not token:
                break
        if found:
            print(f"discovered {len(found)} apps via Reporting API")
            return sorted(set(found))
    except Exception as exc:
        print(f"Reporting API unavailable ({str(exc)[:90]}...), using packages.json")

    return json.loads((ROOT / "packages.json").read_text())["packages"]


def download_icon(url, package):
    """Cache the Play icon in the repo so the site has no external dependencies."""
    dest = ICONS / f"{package}.png"
    try:
        req = urllib.request.Request(f"{url}=s256", headers={"User-Agent": "play-apps-hub"})
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
            data = r.read()
        if len(data) > 500:
            dest.write_bytes(data)
            return f"icons/{package}.png"
    except Exception as exc:
        print(f"  icon download failed: {str(exc)[:80]}")
    return f"icons/{package}.png" if dest.exists() else None


# Attempts per Play call. googleapiclient backs off exponentially on 5xx and
# 429, which absorbs the sporadic 503s the Publisher API returns.
API_RETRIES = 4


def is_missing(exc):
    """True when Play answered 4xx: the thing genuinely isn't there.

    A 404 on the en-US listing or the icon means the app has none yet, and a
    bare card is the honest result. Anything else -- a 5xx or 429 that outlasted
    the retries, a network failure -- says nothing about the app, so the whole
    fetch should fail and main() keeps the last published entry instead of
    publishing a blank card.
    """
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status is not None and 400 <= int(status) < 500 and int(status) != 429


def carry_forward(package, previous, links):
    """The last published entry for a package whose Play fetch just failed.

    On 2026-09-13 a run of 503s dropped four apps off the hub: a failed fetch
    simply left the app out, and the Action published the shorter list. Keeping
    the previous entry means an API outage changes nothing on the page. The test
    link is re-read from links.json exactly as for a fresh entry, so a link edit
    still lands. None when there is nothing to keep (a package never synced).

    Pure: no API calls, no I/O. See test_sync.py.
    """
    old = previous.get(package)
    if old is None:
        return None
    return {**old, "testUrl": links.get(package) or None}


def load_previous_apps():
    """The entries in the apps.json about to be replaced, keyed by package."""
    try:
        return {a["package"]: a for a in json.loads((ROOT / "apps.json").read_text())["apps"]}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def fetch_app(svc, package, links):
    entry = {
        "package": package,
        "title": package,
        "shortDescription": "",
        "icon": None,
        "status": "No listing yet",
        "statusKind": "none",
        "version": None,
        "tracks": [],
        "storeUrl": f"https://play.google.com/store/apps/details?id={package}",
        "testUrl": links.get(package) or None,
    }

    edit_id = svc.edits().insert(packageName=package, body={}).execute(num_retries=API_RETRIES)["id"]
    try:
        try:
            listing = svc.edits().listings().get(
                packageName=package, editId=edit_id, language="en-US"
            ).execute(num_retries=API_RETRIES)
            entry["title"] = listing.get("title") or package
            entry["shortDescription"] = listing.get("shortDescription", "")
        except Exception as exc:
            if not is_missing(exc):
                raise

        try:
            images = svc.edits().images().list(
                packageName=package, editId=edit_id, language="en-US", imageType="icon"
            ).execute(num_retries=API_RETRIES)
            if images.get("images"):
                entry["icon"] = download_icon(images["images"][0]["url"], package)
        except Exception as exc:
            if not is_missing(exc):
                raise

        tracks = svc.edits().tracks().list(packageName=package, editId=edit_id).execute(
            num_retries=API_RETRIES
        )
        entry["tracks"], best = summarise_tracks(tracks.get("tracks", []))
        if best:
            entry["status"] = TRACK_LABEL.get(best[1], best[1])
            entry["statusKind"] = best[1]
            entry["version"] = best[2]
    finally:
        try:
            svc.edits().delete(packageName=package, editId=edit_id).execute()
        except Exception:
            pass

    return entry


def main():
    links = json.loads((ROOT / "links.json").read_text())
    packages = discover_packages()
    previous = load_previous_apps()
    svc = build(
        "androidpublisher",
        "v3",
        credentials=credentials(["https://www.googleapis.com/auth/androidpublisher"]),
        cache_discovery=False,
    )

    apps, kept = [], []
    for package in packages:
        try:
            entry = fetch_app(svc, package, links)
            print(f"  {entry['title']} - {entry['status']} {entry['version'] or ''}")
        except Exception as exc:
            print(f"  {package} FAILED: {str(exc)[:120]}")
            entry = carry_forward(package, previous, links)
            if entry is None:
                continue
            kept.append(package)
            print("    kept its last published entry")
        apps.append(entry)

    apps.sort(key=app_sort_key)
    payload = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "apps": apps,
    }
    (ROOT / "apps.json").write_text(json.dumps(payload, indent=2) + "\n")
    carried = f", {len(kept)} carried forward ({', '.join(kept)})" if kept else ""
    print(f"wrote apps.json - {len(apps)} apps{carried}")
    return 0 if apps else 1


if __name__ == "__main__":
    sys.exit(main())
