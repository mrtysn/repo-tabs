#!/usr/bin/env python3
# DESC: Repo tab groups for Sourcetree and lazygit
"""repo-tabs — open your work / personal repo groups as tabs.

Usage:
    repo-tabs work        open active work repos as iTerm tabs running lazygit
    repo-tabs personal    same for personal repos
    repo-tabs all         both groups (work first)
    repo-tabs st MODE     open the MODE group in Sourcetree instead
    repo-tabs focus       interactive selector: active status, groups, new repos
    repo-tabs watch [MIN] fetch repos when their tab gains focus, cooldown MIN
                          minutes (default 15); auto-started by the default mode
    repo-tabs close [SEL] close tabs this tool opened: work|personal|all (default)
                          or a repo name

The default (lazygit) mode opens one iTerm tab per repo — named, group-colored,
themed per group (see lg-theme). `st` rewrites ~/Library/Application
Support/SourceTree/openWindowList (the file Sourcetree reads its open tabs from
on launch), quitting Sourcetree first if it is running and relaunching it
after. Tabs are alphabetical within group.

Repo list lives in ~/.config/repo-tabs/repos.txt (one path per line, # comments;
seeded from the current open tabs on first run). A path containing
/dev/personal/ is classified as personal, everything else as work. Append
explicit tags in brackets to override or multi-tag:

    /Users/mert/dev/personal/agents-shared  [work personal]

A repo tagged `inactive` stays in the list but is never opened. `focus` edits
the list in a checklist UI: space toggles active, w/p toggle group tags, a
registers a new repo path.
"""

import curses
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from plistlib import UID, load, dump, FMT_BINARY

WINDOW_LIST = os.path.expanduser(
    "~/Library/Application Support/SourceTree/openWindowList")
CONFIG = os.path.expanduser("~/.config/repo-tabs/repos.txt")
SESSIONS = os.path.expanduser("~/.config/repo-tabs/sessions.json")
LAZYGIT_CONFIG = os.path.expanduser(
    "~/Library/Application Support/lazygit/config.yml")
LAZYGIT_THEMES = os.path.expanduser("~/Library/Application Support/lazygit/themes")
DEFAULT_RECT = "{{54, 0}, {2506, 1415}}"
HEADER = ("# repo-tabs repo list — one path per line.\n"
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


def open_iterm_tabs(paths, groups=None):
    """One iTerm window, one tab per repo named after it, each running lazygit.

    groups maps path -> "work"|"personal"; when `lg-theme <group> <name>` set
    an override, the group's lazygit theme is overlaid via LG_CONFIG_FILE and
    its terminal background applied to the tab.
    Returns [(session_id, path), ...] for the tabs it created."""
    groups = groups or {}
    global_bg = terminal_bg(LAZYGIT_CONFIG)
    lines = ['tell application "iTerm2"', 'set ids to {}',
             'set w to (create window with default profile)']
    for i, p in enumerate(paths):
        g = groups.get(p)
        theme = group_theme(g) if g else None
        theme_file = os.path.join(LAZYGIT_THEMES, f"{theme}.yml") if theme else None
        env = ""
        bg = global_bg
        if theme_file and os.path.exists(theme_file):
            env = f"LG_CONFIG_FILE={shlex.quote(LAZYGIT_CONFIG + ',' + theme_file)} "
            bg = terminal_bg(theme_file) or global_bg
        bg_seq = f"printf '\\\\033]11;%s\\\\007' {shlex.quote(bg)} && " if bg else ""
        # The printf titles the tab (OSC 1) from inside the command line itself,
        # strictly after the shell's preexec retitle — immune to startup timing.
        # DISABLE_AUTO_TITLE stops later prompts from retitling again.
        name = shlex.quote(os.path.basename(p))
        # Leading space: zsh histignorespace keeps launch lines out of history.
        cmd = (f" export DISABLE_AUTO_TITLE=true; cd {shlex.quote(p)} && "
               f"printf '\\\\033]1;%s\\\\007' {name} && {bg_seq}{env}lazygit")
        if i:
            lines += ['tell w', 'create tab with default profile', 'end tell']
        lines.append(f'tell current session of w to write text "{cmd}"')
        lines.append('set end of ids to id of current session of w')
    lines += ['activate', 'end tell', 'return ids']
    out = subprocess.run(["osascript", "-e", "\n".join(lines)],
                         check=True, capture_output=True, text=True)
    ids = [t.strip() for t in out.stdout.strip().split(",") if t.strip()]
    return list(zip(ids, paths)) if len(ids) == len(paths) else []


def terminal_bg(path):
    """Background hex declared via '# terminal-bg:' in a theme/config file."""
    try:
        with open(path) as f:
            for line in f:
                if line.startswith("# terminal-bg:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


def group_theme(group):
    """Per-group theme override set by `lg-theme work|personal <name>`."""
    try:
        with open(os.path.expanduser(f"~/.config/repo-tabs/theme-{group}")) as f:
            return f.read().strip() or None
    except OSError:
        return None


def existing_session_ids():
    out = subprocess.run(
        ["osascript", "-e",
         'tell application "iTerm2" to id of every session of every tab of every window'],
        capture_output=True, text=True)
    return {t.strip() for t in out.stdout.strip().split(",") if t.strip()}


def load_sessions():
    try:
        with open(SESSIONS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_sessions(pairs):
    data = load_sessions()
    live = existing_session_ids()
    data = {sid: p for sid, p in data.items() if sid in live}  # drop stale ids
    data.update(dict(pairs))
    with open(SESSIONS, "w") as f:
        json.dump(data, f, indent=1)


def iterm_window_map():
    """{window_id: {session_id, ...}} for every iTerm window."""
    out = subprocess.run(["osascript", "-e", '''
tell application "iTerm2"
  set acc to ""
  repeat with w in windows
    set acc to acc & (id of w as text) & ":"
    repeat with t in tabs of w
      repeat with s in sessions of t
        set acc to acc & (id of s) & ","
      end repeat
    end repeat
    set acc to acc & "|"
  end repeat
  return acc
end tell'''], capture_output=True, text=True)
    winmap = {}
    for chunk in out.stdout.strip().split("|"):
        if ":" not in chunk:
            continue
        win, _, rest = chunk.partition(":")
        winmap[win.strip()] = {s.strip() for s in rest.split(",") if s.strip()}
    return winmap


def close_window(win_id):
    """Atomically close one window, resolved by id in the same script run."""
    r = subprocess.run(["osascript", "-e", f'''
tell application "iTerm2"
  repeat with w in windows
    if (id of w as text) is "{win_id}" then
      close w
      return "closed"
    end if
  end repeat
end tell
return "missing"'''], capture_output=True, text=True)
    return r.stdout.strip() == "closed"


def close_session(sid):
    """Atomically close one session, resolved by id in the same script run."""
    r = subprocess.run(["osascript", "-e", f'''
tell application "iTerm2"
  repeat with w in windows
    repeat with t in tabs of w
      repeat with s in sessions of t
        if id of s is "{sid}" then
          close s
          return "closed"
        end if
      end repeat
    end repeat
  end repeat
end tell
return "missing"'''], capture_output=True, text=True)
    return r.stdout.strip() == "closed"


def close_sessions(target):
    data = load_sessions()
    if target in ("work", "personal"):
        group = {p for p, t in load_config(strict=False) if target in t}
        victims = {sid for sid, p in data.items() if p in group}
    elif target == "all":
        victims = set(data)
    else:
        victims = {sid for sid, p in data.items() if os.path.basename(p) == target}
    if not victims:
        sys.exit(f"no tracked sessions match {target!r} in {SESSIONS}")
    # Close a whole window in one action when it is provably ours: every
    # session in it is a tracked victim (ownership by recorded id — we created
    # the window). Job names are NOT checked: lazygit constantly spawns git
    # children, so name-based checks flap and degrade closes to per-tab
    # prompts. Partially-owned windows fall back to per-session closes. All
    # closes resolve their target by id inside a single osascript run
    # (AppleScript references are positional; a close invalidates every other
    # collected reference).
    winmap = iterm_window_map()
    all_live = {sid for sess in winmap.values() for sid in sess}
    closed_windows = closed_tabs = 0
    leftovers = set()
    for win, sess in winmap.items():
        v = sess & victims
        if not v:
            continue
        if sess == v:
            closed_windows += close_window(win)
        else:
            leftovers |= v
    for sid in sorted(leftovers):
        closed_tabs += close_session(sid)
    for sid in victims:
        data.pop(sid, None)
    with open(SESSIONS, "w") as f:
        json.dump(data, f, indent=1)
    print(f"closed {closed_windows} window(s) + {closed_tabs} tab(s), "
          f"{len(victims - all_live)} already gone")


def active_tab_name():
    out = subprocess.run(
        ["osascript", "-e",
         'tell application "iTerm2" to name of current session of current window'],
        capture_output=True, text=True)
    if out.returncode != 0:
        return None
    # strip iTerm's "(job)" suffix and any activity-indicator prefix (e.g. "●")
    return out.stdout.strip().split(" (")[0].lstrip("●○•* ")


def watch(cooldown_min):
    """Fetch a repo when its tab gains focus, at most once per cooldown."""
    repos = {}
    for p, _ in load_config(strict=False):
        if subprocess.run(["git", "-C", p, "remote"],
                          capture_output=True, text=True).stdout.strip():
            repos[os.path.basename(p)] = p
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    last = None
    while True:
        path = repos.get(active_tab_name())
        if path and path != last and os.path.isdir(path):
            fetch_head = os.path.join(path, ".git", "FETCH_HEAD")
            try:
                age = time.time() - os.path.getmtime(fetch_head)
            except OSError:
                age = float("inf")  # never fetched
            if age > cooldown_min * 60:
                subprocess.Popen(["git", "-C", path, "fetch", "--quiet"], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        last = path
        time.sleep(3)


def ensure_watcher():
    if subprocess.run(["pgrep", "-f", "repo-tabs[^ ]* watch"],
                      capture_output=True).returncode != 0:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "watch"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)


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
    if args and args[0] == "watch":
        watch(float(args[1]) if len(args) > 1 else 15)
        return
    if args and args[0] == "close":
        close_sessions(args[1] if len(args) > 1 else "all")
        return
    st = bool(args) and args[0] in ("st", "sourcetree")
    if st or (args and args[0] == "lazy"):  # "lazy" kept as legacy alias of default
        args = args[1:]
    mode = args[0] if len(args) == 1 else None
    if mode not in ("work", "personal", "all", "focus") or (st and mode == "focus"):
        sys.exit("usage: repo-tabs [st] work|personal|all  |  repo-tabs focus|watch|close")

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

    if not st:
        ensure_watcher()
        groups = {p: "work" if p in work and mode != "personal" else "personal"
                  for p in selected}
        save_sessions(open_iterm_tabs(selected, groups))
        print(f"{mode}: " + ", ".join(os.path.basename(p) for p in selected))
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
    print(f"st {mode}: " + ", ".join(os.path.basename(p) for p in selected))


if __name__ == "__main__":
    main()
