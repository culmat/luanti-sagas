# forge/: notes for coding agents

Saga Forge, the contributor app (user docs: [docs/saga-forge.md](../docs/saga-forge.md)). One Go
binary that installs the tools, serves a browser UI on 127.0.0.1, and drives the sagas and avanti
CLIs. Go 1.26+, `CGO_ENABLED=0`, builds for linux/darwin/windows × amd64/arm64 with `go build` alone.

## Rules

- **No duplicated logic.** Landmark work happens in `sagas` (Python), launching Luanti in
  `avanti play`. Forge calls their command lines (`sagas --json …`, `avanti … --print-command`),
  never reimplements them. When Forge needs something new from a tool, add it to that tool (with a
  test there), then call it. Bump `FORGE_API` in `tools/src/sagas/cli.py` and `setup.ForgeAPI` together
  when the JSON a command prints changes incompatibly.
- **Shared Go code lives in luanthetti's `pkg/`** (`localweb`, `jobs`, `paths`, `installs`,
  `luanticonf`). Import it; fix it there.
- **The local server is the security boundary.** Every `/api/` route sits behind `localweb.Guard`
  (token, Host, Origin, JSON). `/view/` and `/files/` are read-only and refuse cross-site requests.
  The UI is vanilla JS with no inline code (CSP `script-src 'self'`); only the proxied viewer page
  gets `'unsafe-inline'`.
- **Drafts are branches** `forge/<name>` of Forge's own clone. Only `content/` is ever committed;
  `Tidy` drops what builds write to `mods/` and `docs/`. In clone mode (`--folder`) Forge never
  switches branches, commits or cleans.
- **Submitting goes through the GitHub REST API** (`internal/github`), with the device-flow token
  in the keychain. It never pushes with git credentials. Tests use the fake GitHub in
  `github_test.go`; never point tests at github.com.
- **Never start Luanti in tests or experiments without the maintainer's consent**: it opens a window.
- Wording in the UI: plain words for people who never used git ("draft", "send it", "my work").

## Layout

| Path | What |
|---|---|
| `cmd/sagaforge` | flags, `setup`/`doctor`/`version`, one running instance per home |
| `internal/home` | Forge's folder and the environment every tool runs with |
| `internal/setup` | pinned, checksum-verified uv and jq; clones; ldg; the tools' venv |
| `internal/tools` | runs `sagas --json` and `avanti`, decodes their output |
| `internal/workspace` | drafts as git branches (git CLI) |
| `internal/github` | device flow, fork, blobs/tree/commit, pull requests |
| `internal/luanti` | tours via `avanti play --print-command` |
| `internal/app` | what the UI can do; long work runs as jobs |
| `internal/web` | routes, viewer proxy, embedded UI (`static/`) |

## Testing

```sh
go vet ./... && go test ./...
gofmt -l .
GOOS=windows go build ./... && GOOS=linux go build ./...
go run ./cmd/sagaforge --home "$(mktemp -d)" setup      # real downloads, about 2 minutes
```

Until luanthetti's `pkg/` is on GitHub, a local `go.work` (gitignored) points at a luanthetti checkout:
`go work init . ../../luanthetti`.
