# repo-tabs

Switches Sourcetree's open tab set between `work`, `personal`, and `all` by rewriting `~/Library/Application Support/SourceTree/openWindowList` (the file Sourcetree reads its open tabs from on launch), quitting Sourcetree first if it is running and relaunching it after. Tabs are alphabetical within each group.

## Usage

```
repo-tabs work        open only active work repos
repo-tabs personal    open only active personal repos
repo-tabs all         open both groups (work first)
repo-tabs focus       interactive selector: active status, groups, new repos
repo-tabs lazy MODE   open the MODE group as iTerm tabs running lazygit
```

`lazy` takes the same `work|personal|all` groups but opens an iTerm2 window with one tab per repo running [lazygit](https://github.com/jesseduffield/lazygit), instead of touching Sourcetree.

`lazy` themes its tabs: each tab gets an iTerm tab-chip color by group (work cyan, personal pink — constants at the top of the script), the terminal background declared by the active theme's `# terminal-bg:` comment, and optionally a per-group lazygit theme. Group themes are set with `lg-theme work <name>` / `lg-theme personal <name>` (`default` clears one) and are overlaid per tab via `LG_CONFIG_FILE`, leaving the global config untouched.

`lazy` records the iTerm session id of every tab it opens in `~/.config/repo-tabs/sessions.json`; `close` kills exactly those sessions on demand — `repo-tabs close` (everything tracked), `close work` / `close personal` (by group), or `close <repo-name>` (one tab). Tabs you closed by hand are pruned from the file automatically.

`watch` polls iTerm2 for the focused tab and runs `git fetch` in the matching repo when its tab gains focus, at most once per cooldown window (`repo-tabs watch 30` = 30 minutes, default 15; last-fetch time is read from `.git/FETCH_HEAD`). `lazy` starts a watcher automatically if none is running; pair it with `git.autoFetch: false` in lazygit's config so fetching happens only on focus. Stop it with `pkill -f "repo-tabs.* watch"`.

## Configuration

The repo list lives in `~/.config/repo-tabs/repos.txt` (one path per line, `#` comments), seeded from the currently open tabs on first run. A path containing `/dev/personal/` is classified as personal, everything else as work. Append explicit tags in brackets to override or multi-tag:

```
/path/to/repo  [work personal]
```

A repo tagged `inactive` stays in the list but is never opened — the mechanism behind `focus`: pick the projects you're focusing on, park the rest without losing them.

## Focus mode

`repo-tabs focus` opens a checklist over the repo list:

| Key | Action |
|---|---|
| `↑`/`↓` or `k`/`j` | move |
| `space` | toggle active/inactive |
| `w` / `p` | toggle work / personal group tag |
| `a` | register a new repo by path |
| `enter` | save and exit |
| `q` / `esc` | cancel, config untouched |

## License

AGPL-3.0
