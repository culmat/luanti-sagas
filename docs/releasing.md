# How contributions reach ContentDB

One maintainer approval is the only human step. Everything after it runs by itself.

```
issue form ──(maintainer: label "accepted")──▶ intake.yml builds the landmark, opens a pull request
pull request ──▶ ci.yml rebuilds and checks ──▶ pictures.yml posts pictures
             ◀── commands.yml applies comments like /size 24
(maintainer approves) ──▶ auto-merge ──▶ deliver.yml on main:
    rebuild packs, previews and gallery data, commit them
    wait for CI (game tests included) on exactly that commit
    release every changed package: GitHub release + ContentDB, version = date
```

| Workflow | When | What |
|---|---|---|
| `intake.yml` | issue labeled `accepted`, or a maintainer comments `/intake` | `sagas intake` builds `content/<saga>/<id>/` from the form; branch `intake/<n>`, contributor as co-author, pull request |
| `ci.yml` | every pull request, pushes to main | rebuilds changed landmarks (fetch, stale voxels, packs), lint, tests, game tests in Minetest Game, Mineclonia and VoxeLibre |
| `pictures.yml` | after CI | preview and "every size next to trees" pictures in one pull request comment (stored on the `previews` branch) |
| `commands.yml` | comments starting with `/` | `sagas command`: change size, site, rarity, door ...; rebuild and push |
| `automerge.yml` | pull request opened | turns on auto-merge: GitHub merges once one code owner approved and CI is green |
| `deliver.yml` | every push to main | `sagas voxelize --stale`, `build`, `catalog`, commit; CI on that commit; then `scripts/deliver.sh` |
| `release.yml` | a manual tag `<pkg>-v<version>` | re-release one package by hand |

## Versions

Each package (`sagas`, `sagas_<saga>`, `sagas_pack`) is released when its files changed since its last
release. The version is the date, `2026.10.24`, then `2026.10.24.2` for a second release that day.
Release notes list new and updated landmarks and thank their contributors (commit authors and
`Co-authored-by`). The core mod goes first, then the packs, then the modpack.

ContentDB imports a git ref: `deliver.sh` commits the package folder (`mods/<pkg>/`) as its own tree,
tags it `cdb/<pkg>/<version>` and calls `avanti cdb release`. Dev files are left out by the folder's
`.gitattributes`.

## Set up once

1. Create each package on ContentDB (`sagas`, `sagas_ruins`, `sagas_antiquity`, `sagas_pack`) with the
   repository URL, screenshots from `avanti screenshot mods`, and submit them for review.
2. Hand a ContentDB token to CI: `avanti secrets setup && avanti secrets push culmat/luanti-sagas`
   ([avanti-luanti](https://github.com/culmat/avanti-luanti)).
3. Run `scripts/setup-repo.sh`: labels, auto-merge, a deploy key for the workflows (secret
   `SAGAS_DEPLOY_KEY`; it pushes the generated files to main and the bot's branches), the ruleset on
   main (one approving code-owner review, green CI; deploy keys may push), and the `contentdb`
   environment without reviewers.

**A new saga** ships in `sagas_pack` right away. Its own package needs to be created on ContentDB once;
until then `deliver.sh` opens an issue saying so, and the next release after that goes out by itself.

**Your own pull requests:** as the only code owner you can't approve yourself; the ruleset lets
repository admins merge their pull requests directly.

## Why not a ContentDB webhook

ContentDB imports a repository root and binds a webhook to one package, so it cannot tell which of
several packages in this monorepo a tag is for (checked in ContentDB's source, 2026-10-11). Native
support (a per-package subfolder and tag pattern) is a proposed upstream feature, tracked in
avanti-luanti's [upstream backlog](https://github.com/culmat/avanti-luanti/blob/main/docs/upstream.md).
If git import is unavailable, `avanti cdb release VERSION mods/<pkg> --zip dist/<pkg>-VERSION.zip`
uploads the zip from the GitHub release instead.
