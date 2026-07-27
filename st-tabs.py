#!/usr/bin/env python3
# DESC: Sourcetree ordered tab groups
"""st-tabs — switch Sourcetree's open tab set between work / personal / all.

Usage:
    st-tabs work        open only active work repos
    st-tabs personal    open only active personal repos
    st-tabs all         open both groups (work first)
    st-tabs focus       interactive selector: active status, groups, new repos
    st-tabs lazy MODE   open the MODE group as iTerm tabs running lazygit

Rewrites ~/Library/Application Support/SourceTree/openWindowList (the file
Sourcetree reads its open tabs from on launch), quitting Sourcetree first if
it is running and relaunching it after. Tabs are alphabetical within group.

Repo list lives in ~/.config/st-tabs/repos.txt (one path per line, # comments;
seeded from the current open tabs on first run). A path containing
/dev/personal/ is classified as personal, everything else as work. Append
explicit tags in brackets to override or multi-tag:

    /Users/mert/dev/personal/agents-shared  [work personal]

A repo tagged `inactive` stays in the list but is never opened. `focus` edits
the list in a checklist UI: space toggles active, w/p toggle group tags, a
registers a new repo path.
"""

import curses
import os
import shlex
import shutil
import subprocess
import sys
import time
from plistlib import UID, load, dump, FMT_BINARY

WINDOW_LIST = os.path.expanduser(
    "~/Library/Application Support/SourceTree/openWindowList")
CONFIG = os.path.expanduser("~/.config/st-tabs/repos.txt")
DEFAULT_RECT = "{{54, 0}, {2506, 1415}}"
HEADER = ("# st-tabs repo list — one path per line.\n"
          "# Paths containing /dev/personal/ count as personal, the rest as work.\n"
          "# Tags in brackets override: /path/to/repo  [work personal inactive]\n"
          "# 'inactive' repos stay listed but are never opened.\n")


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


def auto_group(path):
    return {"personal" if "/dev/personal/" in path else "work"}


def load_config(strict=True):
    if not os.path.exists(CONFIG):
        paths = [e["path"] for e in read_entries(WINDOW_LIST)]
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w") as f:
            f.write(HEADER)
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
                bad = tags - {"work", "personal", "inactive"}
                if bad:
                    sys.exit(f"unknown tag(s) {sorted(bad)} in {CONFIG}")
                line = line.strip()
            if not tags or not tags & {"work", "personal"}:
                tags = (tags or set()) | auto_group(line)
            repos.append((line, tags))
    missing = [p for p, _ in repos if not os.path.isdir(p)]
    if strict and missing:
        sys.exit("not a directory (fix in %s):\n  %s" % (CONFIG, "\n  ".join(missing)))
    return repos


def save_config(repos):
    with open(CONFIG, "w") as f:
        f.write(HEADER)
        for path, tags in sorted(repos, key=lambda r: r[0]):
            if tags == auto_group(path):
                f.write(path + "\n")
            else:
                f.write(f"{path}  [{' '.join(sorted(tags))}]\n")


def prompt(stdscr, label):
    h, w = stdscr.getmaxyx()
    curses.echo()
    curses.curs_set(1)
    stdscr.addstr(h - 1, 0, label)
    stdscr.clrtoeol()
    text = stdscr.getstr(h - 1, len(label), w - len(label) - 2).decode()
    curses.noecho()
    curses.curs_set(0)
    return text.strip()


def focus_ui(stdscr, repos):
    """Checklist over repos (mutated in place). Returns True to save."""
    curses.use_default_colors()  # wrapper's start_color() would otherwise paint the bg ANSI black
    curses.curs_set(0)
    cur = top = 0
    msg = ""
    while True:
        h, w = stdscr.getmaxyx()
        rows = max(1, h - 3)
        cur = max(0, min(cur, len(repos) - 1))
        if cur < top:
            top = cur
        elif cur >= top + rows:
            top = cur - rows + 1
        stdscr.erase()
        stdscr.addstr(0, 0, "space: active  w/p: group  a: add  enter: save  q: cancel"[:w - 1],
                      curses.A_BOLD)
        for i in range(top, min(len(repos), top + rows)):
            path, tags = repos[i]
            mark = " " if "inactive" in tags else "x"
            group = ",".join(t for t in ("work", "personal") if t in tags)
            attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
            if "inactive" in tags:
                attr |= curses.A_DIM
            stdscr.addstr(i - top + 1, 0, f"[{mark}] {group:14} {path}"[:w - 1], attr)
        if msg:
            stdscr.addstr(h - 1, 0, msg[:w - 1], curses.A_BOLD)
        key = stdscr.getch()
        msg = ""
        if key in (curses.KEY_UP, ord("k")):
            cur -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            cur += 1
        elif key == ord(" ") and repos:
            path, tags = repos[cur]
            repos[cur] = (path, tags ^ {"inactive"})
        elif key in (ord("w"), ord("p")) and repos:
            tag = "work" if key == ord("w") else "personal"
            path, tags = repos[cur]
            new = tags ^ {tag}
            if new & {"work", "personal"}:
                repos[cur] = (path, new)
            else:
                msg = "repo needs at least one group"
        elif key == ord("a"):
            path = os.path.expanduser(prompt(stdscr, "path: ")).rstrip("/")
            if not path:
                pass
            elif not os.path.isdir(path):
                msg = f"not a directory: {path}"
            elif any(p == path for p, _ in repos):
                msg = "already listed"
            else:
                repos.append((path, auto_group(path)))
                cur = len(repos) - 1
        elif key in (10, 13, curses.KEY_ENTER):
            return True
        elif key in (27, ord("q")):
            return False


def open_iterm_tabs(paths):
    """One iTerm window, one tab per repo named after it, each running lazygit."""
    lines = ['tell application "iTerm2"',
             'set w to (create window with default profile)']
    for i, p in enumerate(paths):
        # DISABLE_AUTO_TITLE stops the shell retitling the tab on each prompt
        cmd = f"export DISABLE_AUTO_TITLE=true; cd {shlex.quote(p)} && lazygit"
        if i:
            lines += ['tell w', 'create tab with default profile', 'end tell']
        lines.append(f'set s{i} to current session of w')
        lines.append(f'tell s{i} to write text "{cmd}"')
    lines.append('delay 0.5')  # let the shell's own title write land first, then override
    for i, p in enumerate(paths):
        lines.append(f'tell s{i} to set name to "{os.path.basename(p)}"')
    lines += ['activate', 'end tell']
    subprocess.run(["osascript", "-e", "\n".join(lines)], check=True)


def sourcetree_running():
    return subprocess.run(["pgrep", "-x", "Sourcetree"],
                          capture_output=True).returncode == 0


def quit_sourcetree():
    subprocess.run(["osascript", "-e", 'tell application "Sourcetree" to quit'],
                   check=True)
    for _ in range(30):
        if not sourcetree_running():
            return
        time.sleep(0.5)
    sys.exit("Sourcetree did not quit (unsaved dialog open?) — tabs unchanged")


def main():
    args = sys.argv[1:]
    lazy = bool(args) and args[0] == "lazy"
    if lazy:
        args = args[1:]
    mode = args[0] if len(args) == 1 else None
    if mode not in ("work", "personal", "all", "focus") or (lazy and mode == "focus"):
        sys.exit("usage: st-tabs [lazy] work|personal|all  |  st-tabs focus")

    if mode == "focus":
        repos = load_config(strict=False)
        if curses.wrapper(focus_ui, repos):
            save_config(repos)
            active = sum("inactive" not in t for _, t in repos)
            print(f"saved: {len(repos)} repos, {active} active")
        else:
            print("cancelled — config unchanged")
        return

    repos = [(p, t) for p, t in load_config() if "inactive" not in t]
    by_name = lambda p: os.path.basename(p).lower()
    personal = sorted((p for p, t in repos if "personal" in t), key=by_name)
    work = sorted((p for p, t in repos if "work" in t), key=by_name)
    both = work + [p for p in personal if p not in work]
    selected = {"work": work, "personal": personal, "all": both}[mode]
    if not selected:
        sys.exit(f"no active {mode} repos in {CONFIG}")

    if lazy:
        open_iterm_tabs(selected)
        print(f"lazy {mode}: " + ", ".join(os.path.basename(p) for p in selected))
        return

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

    for _ in range(10):  # right after quit, LaunchServices may still point at the dying process
        if subprocess.run(["open", "-a", "Sourcetree"],
                          capture_output=True).returncode == 0:
            break
        time.sleep(0.5)
    else:
        sys.exit("could not relaunch Sourcetree — tabs are written, open it manually")
    print(f"{mode}: " + ", ".join(os.path.basename(p) for p in selected))


if __name__ == "__main__":
    main()
