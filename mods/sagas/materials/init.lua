-- Material classes -> game nodes.
--
-- Schematics contain placeholders (sagas:m_<class>) and the palette node. After a schematic is
-- blitted into a VoxelManip, `materials.apply` swaps every placeholder for the node chosen for this
-- site: with context "surroundings" the stone classes use the stone family of the site (desert
-- stone in deserts, sandstone, deepslate, ...) and the wood classes the wood of the biome; with
-- "fixed" they use the game's default table. Any class without a registered candidate keeps its
-- placeholder, so a missing node is visible but never "unknown".
local util = sagas.util
local materials = {}
sagas.materials = materials

local modpath = sagas.modpath .. "/materials/"
local tables
if core.get_modpath("default") then
	tables = dofile(modpath .. "minetest_game.lua")
	materials.game = "minetest_game"
elseif core.get_modpath("mcl_core") then
	tables = dofile(modpath .. "mcl.lua")
	materials.game = core.get_modpath("mcl_trees") and "mineclonia" or "mineclone2"
else
	tables = { fixed = {}, families = {}, family_of_node = {}, woods = {}, wood_of_tag = {} }
	materials.game = "generic"
end
materials.tables = tables
local generic = dofile(modpath .. "generic.lua")

-- class -> family member used with context "surroundings"
local FAMILY_MEMBER = { rock = "rock", stone = "stone", cobble = "cobble", moss = "mossy", marble = "smooth" }
local WOOD_MEMBER = { wood = "planks", log = "log" }

local function real_name(name)
	local seen = 0
	while core.registered_aliases[name] and seen < 8 do
		name = core.registered_aliases[name]
		seen = seen + 1
	end
	return name
end

-- First registered candidate -> {name=, cid=, param2=} (nil if none).
local function pick(candidates)
	for _, c in ipairs(candidates or {}) do
		local name, param2 = c, nil
		if type(c) == "table" then
			name, param2 = c.name, c.param2
		end
		name = real_name(name)
		if core.registered_nodes[name] then
			return { name = name, cid = core.get_content_id(name), param2 = param2 }
		end
	end
end

local resolved = { fixed = {}, families = {}, woods = {}, placeholder = {}, debris = {} }
materials.resolved = resolved

local function resolve_all()
	for _, class in ipairs(sagas.vocab.class_names) do
		local ph = "sagas:m_" .. class
		resolved.placeholder[class] = { name = ph, cid = core.get_content_id(ph) }
		local t
		if class == "water" then
			t = util.settings.real_water and pick(tables.fixed.real_water) or pick({ "sagas:water" })
		elseif class ~= "debris" then
			t = pick(tables.fixed[class]) or pick(generic.candidates(class))
		end
		if not t and class ~= "debris" then
			util.log("warning", "no node for class %s in this game; its placeholder stays visible", class)
		end
		resolved.fixed[class] = t or resolved.placeholder[class]
	end
	for fname, members in pairs(tables.families) do
		local f = { sandy = members.sandy }
		local complete = true
		for _, member in ipairs({ "rock", "stone", "cobble", "mossy", "smooth" }) do
			f[member] = pick({ members[member] })
			complete = complete and f[member] ~= nil
		end
		if complete then
			resolved.families[fname] = f
		else
			util.debug("stone family %s incomplete in this game, skipped", fname)
		end
	end
	local function list(v)
		return type(v) == "table" and v or { v }
	end
	for wname, members in pairs(tables.woods) do
		local w = { planks = pick(list(members.planks)), log = pick(list(members.log)) }
		if w.planks and w.log then
			resolved.woods[wname] = w
		end
	end
	resolved.gravel = pick(tables.fixed.gravel) or pick(generic.candidates("gravel"))
	resolved.color_cid = core.get_content_id("sagas:color")
end

-- Stone family and wood of a site: biome node_stone first, then the nodes found under the footprint.
-- `samples` is a list of node names found below the surface (may be empty).
function materials.site_context(biome_name, samples)
	local family
	local bdef = biome_name and core.registered_biomes[biome_name]
	if bdef and bdef.node_stone then
		family = tables.family_of_node[real_name(bdef.node_stone)]
	end
	if not family and samples then
		local votes, best, best_n = {}, nil, 0
		for _, name in ipairs(samples) do
			local f = tables.family_of_node[name]
			if f then
				votes[f] = (votes[f] or 0) + 1
				if votes[f] > best_n then
					best, best_n = f, votes[f]
				end
			end
		end
		family = best
	end
	if family and not resolved.families[family] then
		family = nil
	end
	local wood
	local tags = biome_name and sagas.biomes.tags_of_name(biome_name) or {}
	for _, tag in ipairs({ "jungle", "swamp", "savanna", "desert", "taiga", "snow", "tundra", "mountain", "forest" }) do
		if tags[tag] and tables.wood_of_tag[tag] and resolved.woods[tables.wood_of_tag[tag]] then
			wood = tables.wood_of_tag[tag]
			break
		end
	end
	return { family = family or (resolved.families.stone and "stone"), wood = wood or tables.wood_of_tag.any }
end

local function debris_mix(fam)
	local mix = {}
	local function add(t, weight)
		if t then
			for _ = 1, weight do
				mix[#mix + 1] = t
			end
		end
	end
	if fam then
		add(fam.cobble, 3)
		add(fam.mossy, 2)
	else
		add(resolved.fixed.cobble, 3)
		add(resolved.fixed.moss, 2)
	end
	add(resolved.gravel, fam and fam.sandy and 1 or 4)
	add(resolved.fixed.dirt, fam and fam.sandy and 1 or 2)
	if #mix == 0 then
		add(resolved.placeholder.debris, 1)
	end
	return mix
end

local function class_target(class, ctx, overrides, depth)
	local over = overrides[class]
	if over and over ~= "fixed" and depth < 4 then
		return class_target(over, ctx, overrides, depth + 1)
	end
	local fixed_only = over == "fixed" or ctx.context == "fixed"
	if class == "debris" then
		return { mix = debris_mix(not fixed_only and resolved.families[ctx.family or ""] or nil) }
	end
	if not fixed_only then
		local fam = resolved.families[ctx.family or ""]
		if fam and FAMILY_MEMBER[class] then
			return fam[FAMILY_MEMBER[class]]
		end
		if fam and fam.sandy and class == "sandstone" then
			return fam.stone
		end
		local wood = resolved.woods[ctx.wood or ""]
		if wood and WOOD_MEMBER[class] then
			return wood[WOOD_MEMBER[class]]
		end
	end
	return resolved.fixed[class]
end

local cache = {}

-- Remap table for saga def at a site: placeholder cid -> {cid=, param2=} or {mix = {...}}.
function materials.remap(def, ctx)
	ctx = ctx or {}
	local context = def.materials and def.materials.context or "surroundings"
	local key = table.concat({ def.id, context, ctx.family or "", ctx.wood or "" }, "|")
	if cache[key] then
		return cache[key]
	end
	local overrides = def.materials and def.materials.overrides or {}
	local c = { family = ctx.family, wood = ctx.wood, context = context }
	local map = {}
	for _, class in ipairs(sagas.vocab.class_names) do
		local t = class_target(class, c, overrides, 0)
		local ph = resolved.placeholder[class]
		if t and t.cid ~= ph.cid then
			map[ph.cid] = t
		end
	end
	cache[key] = map
	return map
end

-- Swap placeholders inside p1..p2 of a VoxelManip (data/param2 arrays already read).
function materials.apply(data, param2s, area, p1, p2, map, pr)
	local changed = 0
	for z = p1.z, p2.z do
		for y = p1.y, p2.y do
			local vi = area:index(p1.x, y, z)
			for _ = p1.x, p2.x do
				local t = map[data[vi]]
				if t then
					if t.mix then
						t = t.mix[pr:next(1, #t.mix)]
					end
					data[vi] = t.cid
					param2s[vi] = t.param2 or 0
					changed = changed + 1
				end
				vi = vi + 1
			end
		end
	end
	return changed
end

-- Node used under a saga where the ground falls away: the site's rock, or the fixed rock when the
-- saga uses fixed materials.
function materials.foundation_target(def, ctx)
	local context = def and def.materials and def.materials.context or "surroundings"
	local fam = context ~= "fixed" and resolved.families[ctx and ctx.family or ""]
	return fam and fam.rock or resolved.fixed.rock
end

core.register_on_mods_loaded(resolve_all)
