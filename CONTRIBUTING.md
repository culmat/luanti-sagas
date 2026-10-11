# Contributing

Thank you for helping the Luanti world feel less anonymous. You don't need to code to contribute a saga.

## Add a saga in 15 minutes

1. **Find a model** you like that has a free licence: CC0, CC-BY or CC-BY-SA (or MIT).
   No "NC" (non-commercial) and no "ND" (no derivatives): ContentDB does not allow them.
   [docs/sources.md](docs/sources.md) lists good places to look, and
   [docs/scouting/](docs/scouting/) holds candidates others found; `sagas scout promote <id>` turns one
   into a `saga.toml` for you (then continue at step 4). To search Sketchfab and the Smithsonian yourself,
   `avanti secrets setup` ([avanti-luanti](https://github.com/culmat/avanti-luanti)) stores your free tokens.
2. **Set up the tools** (Python 3.12+ and [uv](https://docs.astral.sh/uv/); no Blender needed):
   ```sh
   git clone https://github.com/culmat/luanti-sagas && cd luanti-sagas/tools && uv sync && cd ..
   alias sagas="uv run --project tools sagas"
   ```
3. **Scaffold** `content/<theme>/<id>/saga.toml`:
   ```sh
   sagas new watchtower --theme medieval --url https://sketchfab.com/3d-models/... \
       --license CC-BY-4.0 --author "Jane Doe" --file watchtower.zip --member scene.gltf --manual
   ```
4. **Get the model**: `sagas fetch medieval/watchtower` downloads it, or for sites that need a login
   (Sketchfab) download it yourself and run `sagas fetch medieval/watchtower --from ~/Downloads/watchtower.zip`.
   Downloads stay in `sources/`, which is never committed.
5. **Look inside**: `sagas inspect medieval/watchtower` shows parts, materials, textures and size.
6. **Voxelize and build**: `sagas voxelize medieval/watchtower` then `sagas build medieval`.
   Open `content/medieval/watchtower/preview.png` and adjust `saga.toml` until it looks right
   (size, up axis, material rules, ruin options). Rebuild with `sagas voxelize --force`.
7. **Say where it belongs**: fill `[placement]` with your hints, in words (`hints`) and as fields
   (`site`, `exposure`, `biomes`, `rarity`). See [docs/placement.md](docs/placement.md).
8. **Check**: `sagas lint medieval/watchtower`.
9. **Commit** `saga.toml`, `voxels.vx.gz`, `preview.png` and the regenerated `mods/sagas_medieval/`,
   then open a pull request. CI rebuilds everything and runs the game tests.

Try it in game: copy `mods/` into your Luanti mods folder (it is the `sagas_pack` modpack), enable it
for a creative world, and use `/saga place watchtower` while pointing at the ground.

## Four ways in

| Lane | You provide | Source kind |
|---|---|---|
| Link a model | a free model + `saga.toml` | `mesh` (glTF, OBJ, DAE, STL, PLY) |
| Build in game | your build, exported with `/saga mark` + `/saga export <name>` | `handbuilt` (the `.mts` from `<world>/sagas/`) |
| No install | a MagicaVoxel `.vox` or a voxel point list (`x, y, z[, r, g, b]`, e.g. from drububu.com) next to `saga.toml` | `vox`, `voxels` |
| Curate | better materials, placement hints, lore for existing sagas | edit `saga.toml` |

Hand-built sagas are licensed by you: choose CC0 or CC-BY-SA-4.0 in `saga.toml`. Copy the exported
`.mts` next to `saga.toml` and set `kind = "handbuilt"` and `file = "<name>.mts"`. The tools map the game's
nodes back to material classes (stairs and slabs become their base material, wool and concrete keep
their colour), so your build adapts to every game. `sagas voxelize` lists nodes it could not map;
add a rule such as `match = { part = "mymod:roof_tile" }` with `class = "roof_red"`.

## Rules that keep the project publishable

- **Licences**: every saga names its source URL, author and SPDX licence. `sagas lint` rejects anything
  else. If a page says "free" without a licence, ask the author or skip it.
- **Share-alike stays together**: CC-BY-SA sources make a whole pack CC-BY-SA, so keep them in their own
  theme (like `antiquity` for 0 A.D. art).
- **No trademarks or characters** (film dragons, game mascots, brand buildings).
- **AI**: set `source.ai = "generated"` and name the tool in `notes` when a model was generated with AI.
- **Fair gameplay**: realistic buildings use material classes; precious classes (gold, emerald) need an
  explicit, small `value_budget`. Diamond or mese never appear.
- **Size**: sagas should fit a mapchunk (72 x 96 x 72 nodes). Bigger ones need `large = true`.
- **Never commit downloaded models.** Only `saga.toml`, `voxels.vx.gz`, `preview.png` and generated packs.

## Pull request checklist

- [ ] Licence is CC0, CC-BY, CC-BY-SA or MIT, with author and URL in `saga.toml`
- [ ] `sagas lint` passes and `preview.png` looks right
- [ ] Placement hints describe where the saga belongs
- [ ] AI use declared (or `ai = "none"`)
- [ ] Commits are signed off (`git commit -s`, see DCO below)

## Code contributions

- Tools: `cd tools && uv run pytest && uv run ruff check . && uv run ruff format --check .`
- Mod: `luacheck mods`, `stylua --check mods/sagas`, and `avanti test mods`
  ([avanti-luanti](https://github.com/culmat/avanti-luanti)) for the headless game tests.
- The vocabulary (classes, sites, biome tags) lives in `tools/src/sagas/data/vocabulary.json`;
  run `sagas sync-core` after changing it so the mod gets the same copy.

## Developer Certificate of Origin

By signing off a commit (`git commit -s`) you certify that you wrote it or have the right to submit
it under the project's licences, as described at https://developercertificate.org/.

## Conduct

Be kind and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
