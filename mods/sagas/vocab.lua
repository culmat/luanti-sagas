-- The shared vocabulary (classes, sites, biome tags). Written by `sagas sync-core` from the tools.
local raw = sagas.util.read_file(sagas.modpath .. "/vocabulary.json")
assert(raw, "sagas: vocabulary.json missing")
local vocab = core.parse_json(raw)
assert(type(vocab) == "table" and vocab.format == 1, "sagas: vocabulary.json is invalid")

sagas.vocab = vocab
vocab.class_names = {}
for name in pairs(vocab.classes) do
	vocab.class_names[#vocab.class_names + 1] = name
end
table.sort(vocab.class_names)

vocab.site_set = {}
for _, group in pairs(vocab.sites) do
	for _, s in ipairs(group) do
		vocab.site_set[s] = true
	end
end
vocab.layer_set = sagas.util.set(vocab.sites.layer)
vocab.biome_set = sagas.util.set(vocab.biome_tags)
vocab.exposure_set = sagas.util.set(vocab.exposure)
