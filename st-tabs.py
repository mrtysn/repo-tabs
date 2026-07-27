#!/usr/bin/env python3
# DESC: Sourcetree ordered tab groups
"""st-tabs — switch Sourcetree's open tab set between work / personal / all.

Usage:
    st-tabs work        open only work repos
    st-tabs personal    open only personal repos
    st-tabs all         open both groups (work first)

Rewrites ~/Library/Application Support/SourceTree/openWindowList (the file
Sourcetree reads its open tabs from on launch), quitting Sourcetree first if
it is running and relaunching it after. Tabs are alphabetical within group.

Repo list lives in ~/.config/st-tabs/repos.txt (one path per line, # comments;
seeded from the current open tabs on first run). A path containing
/dev/personal/ is classified as personal, everything else as work. Append
explicit tags in brackets to override or multi-tag:

    /Users/mert/dev/personal/agents-shared  [work personal]
"""

import os
import shutil
import subprocess
import sys
import time
from plistlib import UID, load, dump, FMT_BINARY

WINDOW_LIST = os.path.expanduser(
    "~/Library/Application Support/SourceTree/openWindowList")
CONFIG = os.path.expanduser("~/.config/st-tabs/repos.txt")
DEFAULT_RECT = "{{54, 0}, {2506, 1415}}"


def read_entries(path):
    """Parse tab entries ({path, tab_index, rect}) out of the archived plist."""
    with open(path, "rb") as f:
        pl = load(f)
    objs = pl["$objects"]
    deref = lambda u: objs[u.data]
    entries = []
    for o in objs:
        if isinstance(o, dict) and "NS.keys" in o:
            keys = [deref(k) for k in o["NS.keys"]]
            if "path" in keys and "tab_index" in keys:
                entries.append(dict(zip(keys, [deref(v) for v in o["NS.objects"]])))
    entries.sort(key=lambda e: e.get("tab_index", 0))
    return entries


def build_plist(paths, rect):
    """Construct the NSKeyedArchiver plist Sourcetree expects."""
    objects = ["$null", None]  # index 1 reserved for the root array
    def add(o):
        objects.append(o)
        return UID(len(objects) - 1)

    key_path, key_tab, key_rect = add("path"), add("tab_index"), add("rect")
    rect_uid = add(rect)
    dict_class = add({
        "$classes": ["NSMutableDictionary", "NSDictionary", "NSObject"],
        "$classname": "NSMutableDictionary",
    })
    entry_uids = []
    for i, p in enumerate(paths):
        p_uid, i_uid = add(p), add(i)
        entry_uids.append(add({
            "$class": dict_class,
            "NS.keys": [key_path, key_tab, key_rect],
            "NS.objects": [p_uid, i_uid, rect_uid],
        }))
    array_class = add({
        "$classes": ["NSMutableArray", "NSArray", "NSObject"],
        "$classname": "NSMutableArray",
    })
    objects[1] = {"$class": array_class, "NS.objects": entry_uids}
    return {
        "$archiver": "NSKeyedArchiver",
        "$version": 100000,
        "$objects": objects,
        "$top": {"root": UID(1)},
    }


def load_config():
    if not os.path.exists(CONFIG):
        paths = [e["path"] for e in read_entries(WINDOW_LIST)]
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            f.write("# st-tabs repo list — one path per line.\n"
                    "# Paths containing /dev/personal/ count as personal, the rest as work.\n"
                    "# Override or multi-tag with brackets: /path/to/repo  [work personal]\n")
            f.write("\n".join(sorted(paths)) + "\n")
        print(f"seeded {CONFIG} from current open tabs")
    repos = []  # (path, tags)
    with open(CONFIG) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            tags = None
            if line.endswith("]") and "[" in line:
                line, _, tag_part = line.rpartition("[")
                tags = set(tag_part.rstrip("]").split())
                bad = tags - {"work", "personal"}
                if bad:
                    sys.exit(f"unknown tag(s) {sorted(bad)} in {CONFIG}")
                line = line.strip()
            if tags is None:
                tags = {"personal" if "/dev/personal/" in line else "work"}
            repos.append((line, tags))
    missing = [p for p, _ in repos if not os.path.isdir(p)]
    if missing:
        sys.exit("not a directory (fix in %s):\n  %s" % (CONFIG, "\n  ".join(missing)))
    return repos


def sourcetree_running():
    return subprocess.run(["pgrep", "-x", "SourceTree"],
                          capture_output=True).returncode == 0


def quit_sourcetree():
    subprocess.run(["osascript", "-e", 'tell application "SourceTree" to quit'],
                   check=True)
    for _ in range(30):
        if not sourcetree_running():
            return
        time.sleep(0.5)
    sys.exit("Sourcetree did not quit (unsaved dialog open?) — tabs unchanged")


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else None
    if mode not in ("work", "personal", "all"):
        sys.exit("usage: st-tabs work|personal|all")

    repos = load_config()
    by_name = lambda p: os.path.basename(p).lower()
    personal = sorted((p for p, t in repos if "personal" in t), key=by_name)
    work = sorted((p for p, t in repos if "work" in t), key=by_name)
    both = work + [p for p in personal if p not in work]
    selected = {"work": work, "personal": personal, "all": both}[mode]
    if not selected:
        sys.exit(f"no {mode} repos in {CONFIG}")

    if sourcetree_running():
        quit_sourcetree()  # quitting rewrites openWindowList; edit only after

    rect = DEFAULT_RECT
    if os.path.exists(WINDOW_LIST):
        entries = read_entries(WINDOW_LIST)
        if entries:
            rect = entries[0].get("rect", DEFAULT_RECT)
        shutil.copy2(WINDOW_LIST, WINDOW_LIST + ".bak")

    with open(WINDOW_LIST, "wb") as f:
        dump(build_plist(selected, rect), f, fmt=FMT_BINARY)

    subprocess.run(["open", "-a", "SourceTree"], check=True)
    print(f"{mode}: " + ", ".join(os.path.basename(p) for p in selected))


if __name__ == "__main__":
    main()
