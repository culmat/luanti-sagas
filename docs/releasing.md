# How contributions reach ContentDB

One maintainer approval is the only human step. Everything after it runs by itself.

```
issue form ──(maintainer: label "accepted")──▶ intake.yml builds the landmark, opens a pull request
pull request ──▶ ci.yml rebuilds and checks ──▶ pictures.yml posts pictures
             ◀── commands.yml applies comments like /size 24
(maintainer approves) ──▶ auto-merge ──▶ deliver.yml on main:
    rebuild packs, previews and gallery data, commit them
    wait for CI (game tests included) on exactly that commit
    release the modpack if it changed: GitHub release + ContentDB, version = date
```

| Workflow | When | What |
|---|---|---|
| `intake.yml` | issue labeled `accepted`, or a maintainer comments `/intake` | `sagas intake` builds `content/<saga>/<id>/` from the form; branch `intake/<n>`, contributor as co-author, pull request |
| `ci.yml` | every pull request, pushes to main | rebuilds changed landmarks (fetch, stale voxels, packs), lint, tests, game tests in Minetest Game, Mineclonia and VoxeLibre |
| `pictures.yml` | after CI | preview and "every size next to trees" pictures in one pull request comment (stored on the `previews` branch) |
| `commands.yml` | comments starting with `/` | `sagas command`: change size, site, rarity, door ...; rebuild and push |
| `automerge.yml` | pull request opened | turns on auto-merge: GitHub merges once one code owner approved and CI is green |
| `deliver.yml` | every push to main, and every 15 minutes | `sagas voxelize --stale`, `build`, `catalog`, commit; CI on that commit; then `scripts/deliver.sh`; the tag `deliver/last` marks what is out |
| `release.yml` | a manual tag `v<version>` | release the modpack by hand |

Auto-merge merges in the name of whoever turned it on. For the bot's pull requests that is the
workflow token, whose merges start no workflow, so `deliver.yml` also runs every 15 minutes and picks
them up; a run with nothing new ends after a few seconds. Merges by people deliver at once.

## One package

ContentDB gets one package, **culmat/sagas**: the modpack in `mods/` (`modpack.conf` names it) with the
`sagas` mod and every saga, each its own mod. Players switch off themes they don't want in the world's
mod settings, and mods that need the API still declare `depends = sagas`. A new saga ships with the
next release, no new package to create. `sagas build` writes the package's ContentDB details,
`mods/.cdb.json`: a section per saga with its landmarks and art licence; the package's art licence is
the strictest of them (CC-BY-SA as soon as one saga is share-alike).

## Versions

The modpack is released when its exported files changed since the last release. The version is the
date, tag `v2026.10.24`, then `v2026.10.24.2` for a second release that day. Release notes list new and
updated landmarks per saga and changes to the `sagas` mod, and thank the contributors (commit authors
and `Co-authored-by`). Tags of single packages before 2026-10-24 (`sagas_ruins-v...`) are history.

ContentDB imports a git ref: `deliver.sh` commits the modpack folder (`mods/`) as its own tree, tags it
`cdb/sagas/<version>` and calls `avanti cdb release`. Dev files are left out by `.gitattributes`.

## Set up once

1. Create the package on ContentDB: a modpack named `sagas` with the repository URL, screenshots from
   `avanti screenshot mods`, and submit it for review.
2. Hand a ContentDB token to CI: `avanti secrets setup && avanti secrets push culmat/luanti-sagas`
   ([avanti-luanti](https://github.com/culmat/avanti-luanti)).
3. Run `scripts/setup-repo.sh`: labels, auto-merge, a deploy key for the workflows (secret
   `SAGAS_DEPLOY_KEY`; it pushes the generated files to main and the bot's branches), the ruleset on
   main (one approving code-owner review, green CI; deploy keys may push), and the `contentdb`
   environment without reviewers.

**People with write access** push to any branch, `main` included, without a pull request; the
ruleset only binds external contributors. A push to main is delivered like a merge: CI with the game
tests must pass on that commit before anything is released.

## Why not a ContentDB webhook

ContentDB imports a repository root and binds a webhook to one package, so it cannot tell which of
several packages in this monorepo a tag is for (checked in ContentDB's source, 2026-10-11). Native
support (a per-package subfolder and tag pattern) is a proposed upstream feature, tracked in
avanti-luanti's [upstream backlog](https://github.com/culmat/avanti-luanti/blob/main/docs/upstream.md).
If git import is unavailable, `avanti cdb release VERSION mods/<pkg> --zip dist/<pkg>-VERSION.zip`
uploads the zip from the GitHub release instead.
