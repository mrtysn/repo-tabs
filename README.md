# st-tabs

Sourcetree ordered tab groups. Switches Sourcetree's open tab set between `work`, `personal`, and `all` by rewriting `~/Library/Application Support/SourceTree/openWindowList` (the file Sourcetree reads its open tabs from on launch), quitting Sourcetree first if it is running and relaunching it after. Tabs are alphabetical within each group.

## Usage

```
st-tabs work        open only active work repos
st-tabs personal    open only active personal repos
st-tabs all         open both groups (work first)
st-tabs focus       interactive selector: active status, groups, new repos
```

## Configuration

The repo list lives in `~/.config/st-tabs/repos.txt` (one path per line, `#` comments), seeded from the currently open tabs on first run. A path containing `/dev/personal/` is classified as personal, everything else as work. Append explicit tags in brackets to override or multi-tag:

```
/path/to/repo  [work personal]
```

A repo tagged `inactive` stays in the list but is never opened — the mechanism behind `focus`: pick the projects you're focusing on, park the rest without losing them.

## Focus mode

`st-tabs focus` opens a checklist over the repo list:

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
