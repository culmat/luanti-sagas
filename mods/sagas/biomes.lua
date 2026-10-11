-- Biome tags (desert, forest, taiga, ...) -> the biomes of the running game.
--
-- Tags come from explicit per-game tables first, then from keywords in the biome name, then from the
-- heat/humidity point. Variants (_ocean, _under, _beach, _shore, _dunes) only get the ocean/beach tags.
local biomes = {}
sagas.biomes = biomes

local EXPLICIT = {
	-- Minetest Game (default/mapgen.lua)
	cold_desert = { "desert", "snow" },
	desert = { "desert" },
	sandstone_desert = { "desert" },
	savanna = { "savanna" },
	grassland = { "grassland" },
	snowy_grassland = { "grassland", "snow" },
	deciduous_forest = { "forest" },
	coniferous_forest = { "forest", "taiga" },
	taiga = { "taiga", "snow" },
	tundra = { "tundra", "snow" },
	tundra_highland = { "tundra", "snow", "mountain" },
	icesheet = { "snow" },
	rainforest = { "jungle", "forest" },
	rainforest_swamp = { "swamp", "jungle" },
	-- Mineclonia / VoxeLibre (mcl_biomes)
	Desert = { "desert" },
	Mesa = { "desert" },
	MesaBryce = { "desert" },
	MesaPlateauF = { "desert" },
	MesaPlateauFM = { "desert" },
	Savanna = { "savanna" },
	SavannaM = { "savanna" },
	Plains = { "grassland" },
	SunflowerPlains = { "grassland" },
	Meadow = { "grassland", "mountain" },
	Forest = { "forest" },
	FlowerForest = { "forest" },
	BirchForest = { "forest" },
	BirchForestM = { "forest" },
	RoofedForest = { "forest" },
	CherryGrove = { "forest", "mountain" },
	PaleGarden = { "forest" },
	Jungle = { "jungle", "forest" },
	JungleM = { "jungle", "forest" },
	JungleEdge = { "jungle" },
	JungleEdgeM = { "jungle" },
	BambooJungle = { "jungle", "forest" },
	BambooJungleM = { "jungle", "forest" },
	BambooJungleEdge = { "jungle" },
	BambooJungleEdgeM = { "jungle" },
	Taiga = { "taiga", "forest" },
	MegaTaiga = { "taiga", "forest" },
	MegaSpruceTaiga = { "taiga", "forest" },
	ColdTaiga = { "taiga", "snow", "forest" },
	Grove = { "taiga", "snow", "mountain" },
	IcePlains = { "tundra", "snow" },
	IcePlainsSpikes = { "tundra", "snow" },
	ExtremeHills = { "mountain" },
	ExtremeHillsM = { "mountain" },
	["ExtremeHills+"] = { "mountain", "forest" },
	SnowySlopes = { "mountain", "snow" },
	FrozenPeaks = { "mountain", "snow" },
	JaggedPeaks = { "mountain", "snow" },
	StonyPeaks = { "mountain" },
	Swampland = { "swamp" },
	MangroveSwamp = { "swamp" },
	MushroomIsland = { "mushroom" },
	StoneBeach = { "beach", "mountain" },
}

local KEYWORDS = {
	{ "desert", "desert" },
	{ "mesa", "desert" },
	{ "badland", "desert" },
	{ "savanna", "savanna" },
	{ "plain", "grassland" },
	{ "grass", "grassland" },
	{ "meadow", "grassland" },
	{ "steppe", "grassland" },
	{ "forest", "forest" },
	{ "wood", "forest" },
	{ "birch", "forest" },
	{ "jungle", "jungle" },
	{ "rainforest", "jungle" },
	{ "bamboo", "jungle" },
	{ "taiga", "taiga" },
	{ "conifer", "taiga" },
	{ "spruce", "taiga" },
	{ "pine", "taiga" },
	{ "snow", "snow" },
	{ "ice", "snow" },
	{ "frozen", "snow" },
	{ "glacier", "snow" },
	{ "tundra", "tundra" },
	{ "mountain", "mountain" },
	{ "hill", "mountain" },
	{ "peak", "mountain" },
	{ "alp", "mountain" },
	{ "highland", "mountain" },
	{ "swamp", "swamp" },
	{ "marsh", "swamp" },
	{ "bog", "swamp" },
	{ "mangrove", "swamp" },
	{ "mushroom", "mushroom" },
}

local SEA_VARIANTS = { "_deep_ocean$", "_ocean$", "_beach_water$", "_underground$", "_under$" }
local BEACH_VARIANTS = { "_beach$", "_shore$", "_dunes$", "_sandlevel$", "Shore$" }
local TOP_VARIANTS = { "_snowtop$", "_grasstop$" }

local by_name = {} -- biome name -> set of tags
local by_id = {} -- biome id -> set of tags

local function classify(name, def)
	for _, pat in ipairs(SEA_VARIANTS) do
		if name:find(pat) then
			return pat:find("ocean") and { ocean = true } or {}
		end
	end
	for _, pat in ipairs(BEACH_VARIANTS) do
		if name:find(pat) then
			return { beach = true }
		end
	end
	local base = name
	local extra = {}
	for _, pat in ipairs(TOP_VARIANTS) do
		if name:find(pat) then
			base = name:gsub(pat, "")
			extra.mountain = true
		end
	end
	local tags = {}
	if EXPLICIT[base] then
		for _, t in ipairs(EXPLICIT[base]) do
			tags[t] = true
		end
	else
		local lower = base:lower()
		for _, kv in ipairs(KEYWORDS) do
			if lower:find(kv[1], 1, true) then
				tags[kv[2]] = true
			end
		end
		if next(tags) == nil then
			local heat, hum = def.heat_point or 50, def.humidity_point or 50
			if heat >= 80 and hum <= 35 then
				tags.desert = true
			elseif heat >= 75 and hum <= 55 then
				tags.savanna = true
			elseif heat >= 75 then
				tags.jungle = true
			elseif heat <= 15 then
				tags.snow = true
			elseif heat <= 35 and hum >= 55 then
				tags.taiga = true
			elseif hum >= 85 then
				tags.swamp = true
			elseif hum >= 60 then
				tags.forest = true
			else
				tags.grassland = true
			end
		end
	end
	for t in pairs(extra) do
		tags[t] = true
	end
	return tags
end

local function resolve()
	for name, def in pairs(core.registered_biomes) do
		local tags = classify(name, def)
		by_name[name] = tags
		local id = core.get_biome_id(name)
		if id then
			by_id[id] = tags
		end
	end
end

function biomes.tags_of_name(name)
	return by_name[name] or {}
end

function biomes.tags_of_id(id)
	return by_id[id] or {}
end

-- Set of biome ids matching any of the tags, or nil for "any" (no filter).
function biomes.filter(tags)
	local want = {}
	for _, t in ipairs(tags or {}) do
		if t == "any" then
			return nil
		end
		want[t] = true
	end
	if next(want) == nil then
		return nil
	end
	local ids = {}
	for id, set in pairs(by_id) do
		for t in pairs(want) do
			if set[t] then
				ids[id] = true
				break
			end
		end
	end
	return ids
end

biomes.classify = classify
core.register_on_mods_loaded(resolve)
