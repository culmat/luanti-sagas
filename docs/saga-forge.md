# Saga Forge

Saga Forge is an app for adding and changing landmarks with the mouse. It shows a landmark in 3D next
to trees and a player, lets you try sizes and choose where it appears, opens Luanti to walk around it,
and sends your work to the project. You need no terminal and no git. To send your work, you need a
GitHub account.

> Saga Forge is new. There is no download yet; until the first release, start it from a clone (see
> [For developers](#for-developers)).

## Install

| System | How |
|---|---|
| macOS | `brew install culmat/tap/sagaforge`, or download `sagaforge_<version>_darwin_<arm64 or amd64>.tar.gz` from the releases page |
| Windows | `scoop install sagaforge` (after `scoop bucket add culmat https://github.com/culmat/scoop-bucket`), or download the `windows` zip |
| Linux | download the `linux` archive and put `sagaforge` on your PATH |

**Opening a download for the first time.** Saga Forge isn't signed yet, so the system warns you once:
- **macOS:** in Finder, right-click (or Control-click) `sagaforge`, choose **Open**, then **Open**
  again.
- **Windows:** in the SmartScreen window, click **More info**, then **Run anyway**.

Installs through brew or scoop don't show these warnings.

**Updating.** `sagaforge upgrade` replaces a downloaded Saga Forge with the newest release, after
checking it against the release's checksums. Installs through brew or scoop update with `brew upgrade`
or `scoop update`.

## First start

Start `sagaforge`. It opens your browser at a local address (only your computer can reach it) and
sets itself up once, which takes a few minutes. It fetches:
- git (on Windows through winget; on macOS, Apple's command line tools offer to install it);
- uv, a pinned and checksum-verified download that installs Python 3.12 and the model tools, about
  150 MB;
- copies of the Sagas and avanti projects;
- ldg's package list.

Everything goes into Saga Forge's own folder, except the game copies and ldg's list, which avanti
and ldg keep where they always do:

| System | Folder |
|---|---|
| macOS | `~/Library/Application Support/sagaforge` |
| Windows | `%LOCALAPPDATA%\sagaforge` |
| Linux | `~/.local/share/sagaforge` |

Keep the window that started Saga Forge open while you use it; closing it quits Saga Forge. Starting
it again while it runs opens the running one.

## What you can do

1. **Landmarks:** every landmark of every saga. Open one to turn it in 3D, compare it with the trees
   of your games, and see its size, placement and story.
2. **Add a landmark:** four steps:
   1. Choose a saga, or start a new one.
   2. Give the link to the model and its licence. For sites that need a login, such as Sketchfab,
      download the model yourself and drop the file in. Saga Forge keeps that original with the
      landmark.
   3. Name it, and say in your own words where it belongs. Saga Forge suggests the placement from
      your words.
   4. Choose a rough size. You fine-tune it afterwards in the 3D view.
3. **Change a landmark:** "Change this landmark" starts a draft. Then:
   - **Size:** try sizes in the viewer, and "Use the viewer's size" applies one.
   - **Where it appears:** terrain, climate and how often.
   - **Name and lore**, and **doors** for buildings whose rooms have no way in.
4. **Walk around it in Luanti:** "Start Luanti" opens a creative test world of its own (your worlds
   stay untouched), flying, and searches new land until the landmark appears. Missing games
   (Minetest Game, Mineclonia, VoxeLibre) can be downloaded there.
5. **Send it:** the first time, Saga Forge asks you to sign in to GitHub with a code. It then puts a
   copy of the project in your account and opens a pull request. A maintainer looks at it once, and
   after that it goes into the game by itself ([releasing.md](releasing.md)). With write access to
   the project, it goes straight to main. **My work** lists your drafts and pull requests; "Send the
   changes" updates a pull request.

Each addition or change is a **draft** of its own, so you can work on several and send them
separately. "Bring my draft up to date" takes in what changed in the project meanwhile.

## Settings

- the game for tours;
- the Luanti program (found automatically, or picked by hand);
- lighter graphics for laptops and 4K screens;
- GitHub sign-in and sign-out;
- "Update the tools", which fetches the newest project and tools.

## For developers

Saga Forge is the Go program in [`forge/`](../forge/). It drives the same command line tools you use
by hand:
- `sagas --json …`, `sagas add` and `sagas view --serve` (see
  [contributing-with-tools.md](contributing-with-tools.md#for-programs));
- `avanti play --print-command` and `avanti games`.

It imports packages from [luanthetti](https://github.com/culmat/luanthetti) for the local server,
jobs, app folders and finding Luanti.

```sh
cd forge
go run ./cmd/sagaforge --folder ..      # work in this clone: you commit and push with git
go run ./cmd/sagaforge setup            # or: install the tools into Forge's own folder
go test ./...
```

With `--folder`, Saga Forge works in your clone and leaves git to you: it doesn't make drafts or send
anything.
