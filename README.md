# st-tabs

Sourcetree ordered tab groups. Switches Sourcetree's open tab set between `work`, `personal`, and `all` by rewriting `~/Library/Application Support/SourceTree/openWindowList` (the file Sourcetree reads its open tabs from on launch), quitting Sourcetree first if it is running and relaunching it after. Tabs are alphabetical within each group.

## Usage

```
st-tabs work        open only work repos
st-tabs personal    open only personal repos
st-tabs all         open both groups (work first)
```

## Configuration

The repo list lives in `~/.config/st-tabs/repos.txt` (one path per line, `#` comments), seeded from the currently open tabs on first run. A path containing `/dev/personal/` is classified as personal, everything else as work. Append explicit tags in brackets to override or multi-tag:

```
/path/to/repo  [work personal]
```

## License

AGPL-3.0
