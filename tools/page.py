#!/usr/bin/env python3
"""Pager helper for exporting a cloud session's events to disk.

  page.py <session_id> <saved_result_file>      file a page that the harness saved to disk
  page.py <session_id> --inline <first_id> <has_more>   note a page that came back inline

Prints the cursor for the next (older) page, or DONE.
"""
import json, os, sys, shutil

DATA = os.environ.get("SPOTTER_DATA", "/home/user/spotter-data")

def main():
    sid = sys.argv[1]
    out = os.path.join(DATA, "corpus", sid)
    os.makedirs(out, exist_ok=True)
    if sys.argv[2] == "--inline":
        first_id, has_more = sys.argv[3], sys.argv[4].lower() == "true"
        with open(os.path.join(out, "_inline.log"), "a") as f:
            f.write(json.dumps({"first_id": first_id, "has_more": has_more}) + "\n")
        n = "?"
    else:
        raw = open(sys.argv[2]).read()
        i, j = raw.find('{"ccr"'), raw.rfind("}")
        page = json.loads(raw[i:j + 1])["ccr"]
        first_id, has_more = page.get("first_id"), bool(page.get("has_more"))
        n = len(page.get("data", []))
        with open(os.path.join(out, f"{first_id}.json"), "w") as f:
            json.dump(page, f)
    if has_more:
        print(f"events={n} MORE -> call list_events again with before_id={first_id}")
    else:
        open(os.path.join(out, "_complete"), "w").write("ok\n")
        print(f"events={n} DONE (session fully exported)")

if __name__ == "__main__":
    main()
