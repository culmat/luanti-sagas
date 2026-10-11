# Where to find models

Checked 2026-10-11. Licences change: always confirm on the model's own page and record it in
`saga.toml`. `sagas scout` searches several of these sources for you (see docs/scouting/).

Accepted licences: **CC0, CC-BY, CC-BY-SA, MIT**. Never NC ("non-commercial") or ND ("no derivatives").

## Good sources

| Source | Licence | How | Notes |
|---|---|---|---|
| [Sketchfab](https://sketchfab.com/search?features=downloadable&type=models) | per model: filter CC0, CC-BY, CC-BY-SA | search with "Downloadable" and set the licence filter; download glTF (login needed, so `manual = true`) | The richest pool of photogrammetry: castles, towers, abbeys, pagodas, stave churches, Egyptian statues, megaliths, lighthouses, mines. CC0 architecture is rare, CC-BY common. Labels are sometimes wrong: read the description. |
| [Smithsonian Open Access 3D](https://3d.si.edu) | CC0 when the record says so | GLB downloads, often Draco-compressed (supported) | Skeletons, fossils, statues, artefacts. The Smithsonian also publishes CC0 copies on Sketchfab. Check the record's usage ("CC0"); the package for an object is not always the object you expect. |
| [Wikimedia Commons](https://commons.wikimedia.org/w/index.php?search=filetype%3A3d+castle&ns6=1) | per file (CC-BY-SA, CC-BY, CC0) | STL downloads, no login | Several real castle scans. No colour: use material rules by height and normal. |
| [Europeana](https://www.europeana.eu) | filter type "3D" and "can be reused" | GLB often hosted on Zenodo | Heritage buildings and objects; quality varies. |
| [Poly Haven](https://polyhaven.com/models) | CC0 | glTF with textures, no login | Rocks, cliffs, trees, roots, piers, doors: good for nature sagas and dwarven halls. |
| [0 A.D.](https://github.com/0ad/0ad) (Wildfire Games) | CC-BY-SA 3.0 (art) | DAE meshes in `art/meshes/structural/`, textures named by the actor XML in `art/actors/structures/<civ>/` | Coherent buildings of many ancient civilisations (Britons, Gauls, Iberians, Romans, Athenians, Ptolemies, Kushites, Persians, Mauryas, Han). Use `extra_files`, `voxel.texture` and `voxel.alpha = "ignore"` (alpha is player colour). Keep in share-alike themes. |
| [Millennium A.D.](https://github.com/0ADMods/millenniumad) | CC-BY-SA 3.0 (art) | like 0 A.D. | Medieval civilisations: Norse (longhouses), Anglo-Saxons, Byzantines, Carolingians. Credit "The Council of Modders, Fallen Empire Studio, Scion Development" and link wildfiregames.com. |
| [OpenGameArt](https://opengameart.org/art-search-advanced?field_art_type_tid%5B%5D=10&field_art_licenses_tid%5B%5D=4) | filter CC0 / CC-BY / CC-BY-SA | direct downloads | Mostly game kits; some realistic packs such as the 3TD Fantasy Ruins Pack (CC0) used in `sagas_ruins`. |
| [swissBUILDINGS3D 2.0](https://opendata.swiss/en/dataset/swissbuildings3d-2-0) | free use with attribution "©swisstopo" | DXF tiles per area | Real Swiss buildings and castles (e.g. Chillon) as untextured roofs and walls; colour by material rules. Experimental lane. |

## Use with care or skip

| Source | Why |
|---|---|
| Open Heritage 3D / CyArk | licence per dataset, mostly non-commercial |
| MyMiniFactory "Scan the World" | per object; many are non-commercial. Only objects marked CC0 or CC-BY. |
| Thingiverse, Printables | often non-commercial, toy-like style |
| Trimble 3D Warehouse (SketchUp) | its terms do not allow redistribution |
| TurboSquid, CGTrader, other marketplaces | paid licences forbid redistribution |
| Minecraft schematics | no licence; only with the builder's written CC0/CC-BY permission |
| AI text-to-3D | allowed with disclosure (`source.ai = "generated"`); check the tool's output terms. Hunyuan3D's licence excludes the EU, UK and South Korea, so it cannot be used. |
| Film and game characters | trademark and copyright, even if a scan is labelled CC |

## Starter candidates

Verified 2026-10-11 on Sketchfab; CC-BY 4.0 unless noted. Re-check the licence before promoting one.

| Theme | Candidates |
|---|---|
| medieval | Haldenstein castle ruin (Grisons), Torre Escaletes watchtower, Torre di Coreallo (Liguria coast), Rocca Calascio (peak) |
| viking | Oseberg ship, Gislinge boat, Heddal stave church; Millennium A.D. Norse buildings (CC-BY-SA) |
| asian | Chulamanee pagoda (Thailand), Kokura castle (Japan), Jinshan temple Cishou pagoda |
| egyptian | Re-inscribed sphinx of Amenemhat III, Temple of Aksha, Triad of Menkaure |
| antique | Poseidon temple at Sounion, votary figure (Minneapolis Institute of Art, CC0) |
| prehistoric | Anta Grande do Zambujeiro dolmen (CC0), Stonehenge, Arbor Low henge |
| gothic | Rievaulx Abbey, St Mary's Abbey (York), Abbey of San Galgano |
| nautical | Tillamook Rock lighthouse, stern of the SS Rifle wreck (CC0, Scottish Maritime Museum); Poly Haven pier (CC0) |
| dwarven | Ferriere mines (lower tunnels), Dognecea mine mouths; Poly Haven rock faces (CC0) |
| elven | Skovfogedegen oak (scan); Poly Haven trees and roots (CC0) |
| alpine | Castle of Tarasp, Schloss Hallwyl, Lenzburg; swissBUILDINGS3D Chillon |
| creatures | Guardian lion (Minneapolis Institute of Art, CC0), Koma Inu pair (Cleveland Museum of Art, CC0), St Margaret with the dragon (noe-3d.at, CC0) |
