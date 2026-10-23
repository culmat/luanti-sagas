-- Automatic placement during map generation.
--
-- No engine decorations are used (Mineclonia disables them in some modes); instead every generated
-- mapchunk rolls a deterministic die per landmark (1 in rarity * sagas_rarity_scale), then tries a few
-- positions and rotations, evaluates the landmark's site expression on the chunk heightmap and nodes,
-- and places the landmark into the mapgen VoxelManip. Works the same in Minetest Game, Mineclonia and
-- VoxeLibre; landmarks larger than a mapchunk are handled by large.lua.
local util = sagas.util
local sites = sagas.sites
local materials = sagas.materials
local placement = sagas.placement
local engine = {
	mode = "sampler",
	scale = util.settings.rarity_scale,
	only = nil, -- set of ids (tests)
	placed = 0,
	chunks = 0, -- mapchunks generated while placement was on
	survey = util.settings.survey,
	-- id -> {rolls, tries, biome, site, box, spacing, placed}: what happened to real placement attempts
	stats = {},
	-- id -> {chunks, fit, tries, biome, site, box, spacing, biomes = {name -> {tries, fit}}}: dry runs
	-- of every landmark in every chunk while engine.survey is on (sagas_survey)
	probe = {},
}
sagas.engine = engine

local REASONS = { "biome", "site", "box", "spacing" }
engine.REASONS = REASONS

local function counters(t, id)
	local c = t[id]
	if not c then
		c = { rolls = 0, surface_rolls = 0, chunks = 0, fit = 0, tries = 0, placed = 0, biomes = {} }
		for _, r in ipairs(REASONS) do
			c[r] = 0
		end
		t[id] = c
	end
	return c
end
engine.counters = counters

local ROTATIONS = { 0, 90, 180, 270 }
local TRIES = 6
local data_buf = {}

local function water_level()
	return tonumber(core.get_mapgen_setting("water_level")) or 1
end

-- For tests and commands: engine.configure({rarity_scale = 0.01, only = {"ruins:temple"}}).
function engine.configure(opts)
	if opts.rarity_scale then
		engine.scale = opts.rarity_scale
	end
	if opts.only ~= nil then
		engine.only = opts.only and util.set(opts.only) or nil
	end
	if opts.mode then
		engine.mode = opts.mode
	end
	if opts.survey ~= nil then
		engine.survey = opts.survey
	end
end

local function make_ctx(minp, maxp, emin, emax, heightmap, biomemap, area)
	local csx = maxp.x - minp.x + 1
	local ctx = {
		minp = minp,
		maxp = maxp,
		emin = emin,
		emax = emax,
		water_level = water_level(),
		mg_name = core.get_mapgen_setting("mg_name"),
		mg_spflags = core.get_mapgen_setting("mgv7_spflags"),
		area = area,
	}
	function ctx.H(x, z)
		if x < minp.x or x > maxp.x or z < minp.z or z > maxp.z then
			return nil
		end
		local h = heightmap[(z - minp.z) * csx + (x - minp.x) + 1]
		if not h or h < minp.y or h >= maxp.y then
			return nil
		end
		return h
	end
	function ctx.biome(x, z)
		if not biomemap or x < minp.x or x > maxp.x or z < minp.z or z > maxp.z then
			return nil
		end
		return biomemap[(z - minp.z) * csx + (x - minp.x) + 1]
	end
	function ctx.node(x, y, z)
		if ctx.data and area:contains(x, y, z) then
			return ctx.data[area:index(x, y, z)]
		end
	end
	return ctx
end
engine.make_ctx = make_ctx

local function rotation_of(def, pr)
	if def.rotation == "random" then
		return ROTATIONS[pr:next(1, 4)]
	end
	return tonumber(def.rotation) or 0
end

-- Try to place def in the chunk; returns true when placed. With vm == nil only evaluate (survey):
-- returns true when the landmark would fit. c is the counter table (engine.stats or engine.probe entry).
local function try_saga(def, pr, ctx, vm, c)
	for _ = 1, TRIES do
		local rot = rotation_of(def, pr)
		local rs = util.rotated_size(def.size, rot)
		local ra = util.rotate_local(def.anchor, def.size, rot)
		local xlo, xhi = ctx.minp.x + ra.x, ctx.maxp.x - (rs.x - 1 - ra.x)
		local zlo, zhi = ctx.minp.z + ra.z, ctx.maxp.z - (rs.z - 1 - ra.z)
		if xlo > xhi or zlo > zhi then
			return false
		end
		local x, z = pr:next(xlo, xhi), pr:next(zlo, zhi)
		local biome = ctx.biome(x, z)
		local bname = biome and core.get_biome_name(biome)
		local bc
		c.tries = c.tries + 1
		if not vm and bname then
			bc = c.biomes[bname] or { tries = 0, fit = 0 }
			c.biomes[bname] = bc
			bc.tries = bc.tries + 1
		end
		local reason
		if def.biome_filter and not (biome and def.biome_filter[biome]) then
			reason = "biome"
		else
			local y, site = sites.evaluate(def, ctx, x, z, rot, pr)
			if not (y and y >= def.y_min and y <= def.y_max) then
				reason = "site"
			else
				local anchor = { x = x, y = y, z = z }
				local p1, p2 = util.bbox(def, anchor, rot)
				if p1.y - def.foundation < ctx.emin.y or p2.y > ctx.emax.y then
					reason = "box"
				elseif not sagas.records.spacing_ok(def.id, p1, p2, def.min_distance) then
					reason = "spacing"
				elseif not vm then
					if bc then
						bc.fit = bc.fit + 1
					end
					return true
				else
					local mctx = materials.site_context(bname, placement.samples(ctx.data, ctx.area, p1, p2, y))
					placement.place_on_vm(vm, ctx.area, def, anchor, {
						rot = rot,
						foundation = def.foundation,
						clear_above = def.clear_above,
						ctx = mctx,
						pr = pr,
					})
					ctx.data = vm:get_data(data_buf)
					sagas.records.add(def.id, anchor, p1, p2, rot, site, bname)
					engine.placed = engine.placed + 1
					c.placed = c.placed + 1
					util.debug("placed %s at %s (%s, rot %d)", def.id, core.pos_to_string(anchor), site, rot)
					core.after(0, placement.run_callbacks, def, anchor, p1, p2, rot)
					return true
				end
			end
		end
		c[reason] = c[reason] + 1
	end
	return false
end

-- Whether the landmark's sites need the terrain surface inside the chunk (no layer primitive).
local function needs_surface(def)
	if def.needs_surface == nil then
		def.needs_surface = true
		for _, alt in ipairs(def.site_parsed) do
			for _, prim in ipairs(alt) do
				if sagas.vocab.layer_set[prim] then
					def.needs_surface = false
				end
			end
		end
	end
	return def.needs_surface
end
engine.needs_surface = needs_surface

-- Survey: evaluate every enabled landmark in this chunk without placing (separate random stream, so
-- real placement is unchanged). Chunks without terrain surface only count for layer sites.
local function probe_chunk(ctx, minp, maxp, blockseed)
	local cx, cz = math.floor((minp.x + maxp.x) / 2), math.floor((minp.z + maxp.z) / 2)
	local surface = ctx.H(cx, cz) ~= nil
	for _, def in ipairs(sagas.landmark_list) do
		if
			def.enabled
			and not def.large
			and def.y_max >= minp.y
			and def.y_min <= maxp.y
			and (surface or not needs_surface(def))
			and (not engine.only or engine.only[def.id])
		then
			local c = counters(engine.probe, def.id)
			c.chunks = c.chunks + 1
			if try_saga(def, PcgRandom(blockseed + def.salt + 7919), ctx, nil, c) then
				c.fit = c.fit + 1
			end
		end
	end
end

function engine.on_generated(minp, maxp, blockseed)
	if engine.mode ~= "sampler" then
		return
	end
	engine.chunks = engine.chunks + 1
	local rolls = {}
	for _, def in ipairs(sagas.landmark_list) do
		if
			def.enabled
			and not def.large
			and def.y_max >= minp.y
			and def.y_min <= maxp.y
			and (not engine.only or engine.only[def.id])
		then
			local pr = PcgRandom(blockseed + def.salt)
			local n = math.max(1, math.floor(def.rarity * engine.scale + 0.5))
			if pr:next(1, n) == 1 then
				rolls[#rolls + 1] = { def = def, pr = pr }
			end
		end
	end
	if #rolls == 0 and not engine.survey then
		return
	end
	local heightmap = core.get_mapgen_object("heightmap")
	local vm, emin, emax = core.get_mapgen_object("voxelmanip")
	if not vm then
		return
	end
	local area = VoxelArea(emin, emax)
	local ctx = make_ctx(minp, maxp, emin, emax, heightmap or {}, core.get_mapgen_object("biomemap"), area)
	ctx.data = vm:get_data(data_buf)
	if engine.survey then
		probe_chunk(ctx, minp, maxp, blockseed)
	end
	local surface = ctx.H(math.floor((minp.x + maxp.x) / 2), math.floor((minp.z + maxp.z) / 2)) ~= nil
	local placed = 0
	for _, roll in ipairs(rolls) do
		if placed >= util.settings.max_per_chunk then
			break
		end
		local c = counters(engine.stats, roll.def.id)
		c.rolls = c.rolls + 1
		if surface then
			c.surface_rolls = c.surface_rolls + 1
		end
		if try_saga(roll.def, roll.pr, ctx, vm, c) then
			placed = placed + 1
		end
	end
	if placed > 0 then
		vm:calc_lighting()
		vm:write_to_map()
		vm:update_liquids()
	end
end

core.register_on_mods_loaded(function()
	if util.settings.disable_mapgen then
		engine.mode = "off"
	elseif core.get_mapgen_setting("mg_name") == "singlenode" then
		engine.mode = "off"
	elseif rawget(_G, "mcl_levelgen") and mcl_levelgen.levelgen_enabled then
		engine.mode = "off"
	end
	if engine.mode == "off" then
		util.log("action", "automatic placement is off in this world (mapgen or setting); /saga place still works")
	end
	if #util.settings.only > 0 then
		local ids = {}
		for _, name in ipairs(util.settings.only) do
			ids[#ids + 1] = sagas.resolve_id(name) or name
		end
		engine.configure({ only = ids })
		util.log("action", "sagas_only: placing only %s", table.concat(ids, ", "))
	end
end)

core.register_on_generated(function(minp, maxp, blockseed)
	engine.on_generated(minp, maxp, blockseed)
end)
