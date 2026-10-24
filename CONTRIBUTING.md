# Contributing

You can add a landmark to Luanti worlds from your web browser: no install, no git, no code. You
need a free [GitHub account](https://github.com/signup) and a 3D model with a free licence. Every
contribution is welcome and you can do it on your own. A bot does the technical work, a
maintainer looks at it once, and then it reaches players on ContentDB by itself, credited to you.

A **saga** is a theme (ruins, antiquity, vikings ...) and a **landmark** is one structure in it, made
from one 3D model. See what exists in the [gallery](https://culmat.github.io/luanti-sagas/).

## Add a landmark in your browser

1. **Find a model** with a free licence: CC0, CC-BY, CC-BY-SA or MIT. "NC" (non-commercial) and "ND"
   (no derivatives) don't work, and neither do film or game characters and brands. Good places:
   [Sketchfab](https://sketchfab.com/search?features=downloadable&type=models) (filter by licence),
   [Poly Haven](https://polyhaven.com/models) and
   [Smithsonian 3D](https://3d.si.edu/). More in [docs/sources.md](docs/sources.md); ideas others found
   wait in [docs/scouting/](docs/scouting/).
2. **Fill in the form** [Add a landmark](https://github.com/culmat/luanti-sagas/issues/new?template=model-found.yml):
   the link, the author, the licence, the saga, how big it should be and where it belongs, in your own
   words ("on sea cliffs in the cold north, rare"). If the site needs a login to download (Sketchfab
   does), download the model and drag the zip into the form.
3. **Wait for the licence check.** A maintainer looks at the licence and labels the issue `accepted`.
   The bot then builds your landmark and opens a pull request, a page for this one change.
4. **Look at the pictures.** A few minutes later the pull request shows your landmark from four
   sides, and next to a player and the game's trees at several sizes.
5. **Change it by writing comments**, one command per line:

   | Comment | Does |
   |---|---|
   | `/size 24` | longest side in nodes (a player is 2 tall, trees 8 to 17) |
   | `/bigger`, `/smaller` | a quarter bigger or smaller |
   | `/site cliff+coast plain` | where it stands, best first ([the words](docs/placement.md)) |
   | `/rarity rare` | `common`, `rare`, `legendary` or a number |
   | `/biomes tundra snow` | climate |
   | `/door +z` | cut a doorway on one side (`+x`, `-x`, `+z`, `-z`), `/door none` keeps it closed |
   | `/turn 90`, `/up z` | turn it, or stand it up if it lies on its side |
   | `/title ...`, `/lore ...` | its name and a line of lore |
   | `/help` | all commands |

   The bot answers, rebuilds and posts new pictures.
6. **Done.** When it looks right, a maintainer approves. It is merged and released to ContentDB on
   its own, usually within the hour. The release notes and the landmark's credits name you.

## Small changes to existing landmarks

Better lore, placement or size for a landmark that exists: open its `landmark.toml` in
[content/](content/) on GitHub, click the pencil, change the text and choose *Propose changes*.
The fields are explained in [docs/pipeline.md](docs/pipeline.md). CI rebuilds it and shows the
pictures in your pull request.

No model, but an idea? Use the [Landmark idea](https://github.com/culmat/luanti-sagas/issues/new?template=saga-request.yml)
form. Something broken in the game? The [bug form](https://github.com/culmat/luanti-sagas/issues/new?template=bug.yml).

## The rules

- **Free licences only**, with the author named: CC0, CC-BY, CC-BY-SA or MIT.
- **Share-alike stays together**: CC-BY-SA models go into a share-alike saga (like `antiquity`).
- **No trademarks or characters**: no film dragons, game mascots or brand buildings.
- **Say when AI made it**: choose "AI-generated" in the form and name the tool.
- **Fair play**: landmarks don't hand out diamonds, mese or piles of gold.

By opening an issue or pull request you agree that your contribution is published under the
licence of the model (for text and hand-built work: the licence of the saga), crediting you.

## More ways in

| You want to | Read |
|---|---|
| work on your computer with the tools and git, try it in the game | [docs/contributing-with-tools.md](docs/contributing-with-tools.md) |
| let an AI coding agent build it with you | [docs/contributing-with-tools.md#with-a-coding-agent](docs/contributing-with-tools.md#with-a-coding-agent) |
| build a landmark in the game and export it | [docs/contributing-with-tools.md#build-in-the-game](docs/contributing-with-tools.md#build-in-the-game) |
| change the mod or the tools (code) | [docs/contributing-with-tools.md#code](docs/contributing-with-tools.md#code) |
| know how releases work | [docs/releasing.md](docs/releasing.md) |

## Conduct

Be kind and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
