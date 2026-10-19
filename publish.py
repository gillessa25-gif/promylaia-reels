#!/usr/bin/env python3
"""Cloud publisher: runs on GitHub Actions every 15 minutes (Mac can be off).
Publishes the reels of schedule.json that are due (at <= now < at + 36 h) to @gilless_ai through Composio.
Idempotent: a reel whose caption is already among the latest posts is skipped."""
import json, os, sys, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

KEY = os.environ.get("COMPOSIO_API_KEY", "")
BASE = "https://backend.composio.dev/api/v3"
IG_USER_ID = "28326356453714182"
EXPECTED = "gilless_ai"
LATE = timedelta(hours=36)


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"x-api-key": KEY, "content-type": "application/json", "user-agent": "promylaia-publisher"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        return {"successful": False, "error": f"HTTP {e.code}: {e.read().decode()[:300]}"}
    except Exception as e:  # network
        return {"successful": False, "error": str(e)[:300]}


def account_id():
    res = api("GET", "/connected_accounts?toolkit_slugs=instagram&statuses=ACTIVE&limit=10")
    items = res.get("items") or res.get("data") or []
    for it in items:
        return it.get("id") or it.get("nanoid")
    raise SystemExit(f"no active Instagram connection: {json.dumps(res)[:300]}")


def execute(acct, slug, args):
    res = api("POST", f"/tools/execute/{slug}", {"connected_account_id": acct, "arguments": args})
    data = res.get("data") if isinstance(res.get("data"), dict) else res
    ok = res.get("successful", True) and not res.get("error")
    return ok, data, res.get("error")


def first_line(caption):
    return caption.split("\n")[0].strip()


def main():
    if not KEY:
        raise SystemExit("COMPOSIO_API_KEY secret is missing")
    now = datetime.now(timezone.utc)
    if os.environ.get("CHECK") == "1":  # connection test: no publishing
        acct = account_id()
        ok, info, err = execute(acct, "INSTAGRAM_GET_USER_INFO", {})
        print(f"CHECK account={'found' if acct else None} user={info.get('username') if ok else err}")
        ok, media, err = execute(acct, "INSTAGRAM_GET_IG_USER_MEDIA", {"ig_user_id": IG_USER_ID, "limit": 3, "fields": "id,timestamp"})
        print(f"CHECK media ok={ok} count={len((media or {}).get('data') or [])} err={err}")
        return
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.json")) as f:
        items = json.load(f)
    due = [i for i in items if datetime.fromisoformat(i["at"]) <= now < datetime.fromisoformat(i["at"]) + LATE]
    print(f"{now.isoformat(timespec='seconds')} due: {[i['id'] for i in due]}")
    if not due:
        return
    acct = account_id()
    ok, info, err = execute(acct, "INSTAGRAM_GET_USER_INFO", {})
    if not ok or (info.get("username") != EXPECTED and str(info.get("id")) != IG_USER_ID):
        raise SystemExit(f"ABORT account check failed: {err or info}")
    ok, media, err = execute(acct, "INSTAGRAM_GET_IG_USER_MEDIA", {"ig_user_id": IG_USER_ID, "limit": 15, "fields": "id,caption,timestamp"})
    posted = {first_line(m.get("caption") or "") for m in (media.get("data") or [])} if ok else None
    if posted is None:
        raise SystemExit(f"ABORT cannot list recent media: {err}")
    for it in due:
        if first_line(it["caption"]) in posted:
            print(f"{it['id']} already published, skip")
            continue
        ok, c, err = execute(acct, "INSTAGRAM_POST_IG_USER_MEDIA", {"ig_user_id": IG_USER_ID, "media_type": "REELS", "video_url": it["video_url"], "caption": it["caption"], "share_to_feed": True, "thumb_offset": 500})
        cid = (c or {}).get("id") or (c or {}).get("creation_id")
        if not ok or not cid:
            print(f"{it['id']} ERROR container: {err or c}")
            continue
        ok, p, err = execute(acct, "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH", {"ig_user_id": IG_USER_ID, "creation_id": cid, "max_wait_seconds": 300, "poll_interval_seconds": 5})
        mid = (p or {}).get("id")
        print(f"{it['id']} {'PUBLISHED ' + str(mid) if ok and mid else 'ERROR publish: ' + str(err or p)}")


if __name__ == "__main__":
    main()
