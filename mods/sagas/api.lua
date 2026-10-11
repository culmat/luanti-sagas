-- Public API. Content packs call sagas.register_landmark() from their generated registry.lua.
local util = sagas.util
local vocab = sagas.vocab

util.reject_level = "error" -- tests lower this while registering invalid definitions on purpose

local function fail(id, msg, ...)
	util.log(util.reject_level, "landmark %s not registered: " .. msg, tostring(id), ...)
	return false
end

local function vec(v)
	return type(v) == "table" and type(v.x) == "number" and type(v.y) == "number" and type(v.z) == "number"
end

-- Register a landmark. Returns true on success; invalid definitions are logged and skipped so that one
-- broken landmark never stops a server from starting.
function sagas.register_landmark(def)
	local id = def.id
	if type(id) ~= "string" or not id:match("^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$") then
		return fail(id, "id must look like modname:name (e.g. sagas_ruins:cathedral)")
	end
	if sagas.registered_landmarks[id] then
		return fail(id, "duplicate id")
	end
	if type(def.schematic) ~= "string" or not util.read_file(def.schematic) then
		return fail(id, "schematic file %s not found", tostring(def.schematic))
	end
	if not vec(def.size) or def.size.x < 1 or def.size.y < 1 or def.size.z < 1 then
		return fail(id, "size must be a vector of positive numbers")
	end
	def.anchor = def.anchor or { x = math.floor(def.size.x / 2), y = 0, z = math.floor(def.size.z / 2) }
	if not vec(def.anchor) then
		return fail(id, "anchor must be a vector")
	end
	def.site = def.site or { "plain" }
	if type(def.site) == "string" then
		def.site = { def.site }
	end
	def.site_parsed = {}
	for _, expr in ipairs(def.site) do
		local prims = {}
		local layers = 0
		for prim in expr:gmatch("[^+%s]+") do
			if not vocab.site_set[prim] then
				return fail(id, "unknown site primitive %s", prim)
			end
			if vocab.layer_set[prim] then
				layers = layers + 1
			end
			prims[#prims + 1] = prim
		end
		if #prims == 0 or layers > 1 then
			return fail(id, "invalid site expression %q", expr)
		end
		def.site_parsed[#def.site_parsed + 1] = prims
	end
	def.exposure = def.exposure or "any"
	if not vocab.exposure_set[def.exposure] then
		return fail(id, "unknown exposure %s", tostring(def.exposure))
	end
	def.biomes = def.biomes or { "any" }
	for _, tag in ipairs(def.biomes) do
		if not vocab.biome_set[tag] then
			return fail(id, "unknown biome tag %s", tostring(tag))
		end
	end
	def.rarity = math.max(1, math.floor(tonumber(def.rarity) or 400))
	def.y_min = tonumber(def.y_min) or -31000
	def.y_max = tonumber(def.y_max) or 31000
	def.rotation = def.rotation or "random"
	def.foundation = math.max(0, math.min(64, tonumber(def.foundation) or 12))
	if def.clear_above == nil then
		def.clear_above = true
	end
	def.materials = def.materials or {}
	def.materials.context = def.materials.context or "surroundings"
	def.materials.overrides = def.materials.overrides or {}
	for class, target in pairs(def.materials.overrides) do
		if not vocab.classes[class] or (target ~= "fixed" and not vocab.classes[target]) then
			return fail(id, "invalid material override %s = %s", tostring(class), tostring(target))
		end
	end
	local limits = vocab.chunk_limits
	local fits = math.max(def.size.x, def.size.z) <= limits.footprint and def.size.y <= limits.height
	if not fits and not def.large then
		return fail(id, "size %dx%dx%d exceeds a mapchunk; set large = true", def.size.x, def.size.y, def.size.z)
	end
	if def.min_distance == nil or def.min_distance <= 0 then
		def.min_distance = def.rarity >= 400 and 3 * math.max(def.size.x, def.size.z) or 0
	end
	def.saga = def.saga or id:match("^([^:]+)"):gsub("^sagas_", "")
	def.salt = util.hash32(id) % 16777216
	def.enabled = not (util.settings.disabled[id] or util.settings.disabled[def.saga])
	sagas.registered_landmarks[id] = def
	sagas.landmark_list[#sagas.landmark_list + 1] = def
	return true
end

-- fn(id, anchor, box {min=, max=}, rotation, game_info) runs after every placement (mapgen or command).
-- Use it to add loot or mobs; the area is written already.
function sagas.register_on_placed(fn)
	assert(type(fn) == "function", "sagas.register_on_placed expects a function")
	sagas.registered_on_placed[#sagas.registered_on_placed + 1] = fn
end

-- Full id for a name typed by a player: the full id, saga:name, or a unique short name.
function sagas.resolve_id(name)
	if not name or name == "" then
		return nil
	end
	if sagas.registered_landmarks[name] then
		return name
	end
	local saga, short = name:match("^([^:]+):(.+)$")
	if saga and sagas.registered_landmarks["sagas_" .. saga .. ":" .. short] then
		return "sagas_" .. saga .. ":" .. short
	end
	local found
	for id in pairs(sagas.registered_landmarks) do
		if id:match(":(.+)$") == name then
			if found then
				return nil -- ambiguous
			end
			found = id
		end
	end
	return found
end

-- Place landmark `id` with its anchor at `pos`. opts: rot (0/90/180/270), foundation (depth),
-- clear_above (bool). Returns p1, p2 or nil, error.
function sagas.place(id, pos, opts)
	id = sagas.resolve_id(id) or id
	local def = sagas.registered_landmarks[id]
	if not def then
		return nil, "unknown landmark " .. tostring(id)
	end
	opts = opts or {}
	local rot = opts.rot
	if rot == nil or rot == "random" then
		rot = def.rotation == "random" and ({ 0, 90, 180, 270 })[math.random(1, 4)] or tonumber(def.rotation) or 0
	end
	opts.rot = tonumber(rot) or 0
	local p1, p2 = sagas.placement.place(def, vector.round(pos), opts)
	return p1, p2
end

core.register_on_mods_loaded(function()
	for _, def in ipairs(sagas.landmark_list) do
		def.biome_filter = sagas.biomes.filter(def.biomes)
	end
	table.sort(sagas.landmark_list, function(a, b)
		if a.rarity ~= b.rarity then
			return a.rarity > b.rarity
		end
		return a.id < b.id
	end)
	util.log("action", "%d landmark(s) registered (%s materials)", #sagas.landmark_list, sagas.materials.game)
end)
