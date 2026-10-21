#!/usr/bin/env python3
"""Cloud publisher: runs on GitHub Actions every 15 minutes (Mac can be off).
Publishes the reels of schedule.json that are due (at <= now < at + 36 h) to @gilless_ai through Composio.
Idempotent: a reel whose caption is already among the latest posts is skipped."""
import json, os, subprocess, sys, time
from datetime import datetime, timedelta, timezone

KEY = os.environ.get("COMPOSIO_API_KEY", "")
IG_USER_ID = "28326356453714182"
EXPECTED = "gilless_ai"
LATE = timedelta(hours=36)


def account_id():
    return "default"  # the CLI session (logged in with the user API key) resolves the connected Instagram account


def execute(acct, slug, args):
    try:
        out = subprocess.run(["composio", "execute", slug, "-d", json.dumps(args)], capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        res = json.loads(out.stdout)
    except Exception as e:
        return False, {}, f"cli error: {str(e)[:200]} {(locals().get('out') and (out.stdout + out.stderr)[:300]) or ''}"
    if res.get("storedInFile") and res.get("outputFilePath"):
        with open(res["outputFilePath"]) as f:
            res = json.load(f)
    data = res.get("data") if isinstance(res.get("data"), dict) else res
    return bool(res.get("successful", True)) and not res.get("error"), data, res.get("error")


def first_line(caption):
    return caption.split("\n")[0].strip()


def main():
    now = datetime.now(timezone.utc)
    if os.environ.get("CHECK") == "2":  # container-only diagnostic: create a container (not published) and show the raw response
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule.json")) as f:
            it = json.load(f)[-1]
        ok, c, err = execute("default", "INSTAGRAM_POST_IG_USER_MEDIA", {"ig_user_id": IG_USER_ID, "media_type": "REELS", "video_url": it["video_url"], "caption": "diag", "share_to_feed": False, "cover_url": it["cover_url"]})
        print("DIAG container ok=", ok, "err=", err, "raw=", json.dumps(c)[:300])
        return
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
        ok, c, err = execute(acct, "INSTAGRAM_POST_IG_USER_MEDIA", {"ig_user_id": IG_USER_ID, "media_type": "REELS", "video_url": it["video_url"], "caption": it["caption"], "share_to_feed": True, **({"cover_url": it["cover_url"]} if it.get("cover_url") else {"thumb_offset": 500})})
        cid = (c or {}).get("id") or (c or {}).get("creation_id")
        if cid is not None and not str(cid).isdigit():
            print(f"{it['id']} WARN container id not numeric: {str(cid)[:30]!r} keys={list((c or {}).keys())}")
        if not ok or not cid:
            print(f"{it['id']} ERROR container: {err or c}")
            continue
        ok, p, err = execute(acct, "INSTAGRAM_POST_IG_USER_MEDIA_PUBLISH", {"ig_user_id": IG_USER_ID, "creation_id": cid, "max_wait_seconds": 300, "poll_interval_seconds": 5})
        mid = (p or {}).get("id")
        print(f"{it['id']} {'PUBLISHED ' + str(mid) if ok and mid else 'ERROR publish: ' + str(err or p)}")


if __name__ == "__main__":
    main()
