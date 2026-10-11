-- Landmarks larger than a mapchunk. The world is split into 512x512 cells; each cell gets at most one
-- deterministic candidate column per large landmark. When the mapchunk containing that column's surface
-- is generated, the landmark's box is emerged and, once complete, the site is checked on the real
-- terrain and the landmark placed on the live map. States live in mod storage ("L:<id>:<cx>:<cz>" =
-- pending | placed | rejected) so a restart resumes pending placements.
local util = sagas.util
local large = { cell = 512 }
sagas.large = large

local storage = sagas.records.storage
local seed = core.get_mapgen_setting("seed") or "0"
local CHUNK_AREA = (512 / 80) ^ 2

local function key(def, cx, cz)
	return ("L:%s:%d:%d"):format(def.id, cx, cz)
end

-- Candidate anchor column and rotation of def in cell (cx, cz), or nil.
function large.candidate(def, cx, cz)
	local pr = PcgRandom(util.hash32(seed, def.id, cx, cz) % 2147483647)
	local chance = math.min(1, CHUNK_AREA / math.max(1, def.rarity * sagas.engine.scale))
	if pr:next(1, 1000000) > chance * 1000000 then
		return nil
	end
	local m = math.max(def.size.x, def.size.z)
	local lo, hi = math.ceil(m / 2) + 8, large.cell - math.ceil(m / 2) - 8
	if lo > hi then
		return nil
	end
	local rot = def.rotation == "random" and ({ 0, 90, 180, 270 })[pr:next(1, 4)] or tonumber(def.rotation) or 0
	return { x = cx * large.cell + pr:next(lo, hi), z = cz * large.cell + pr:next(lo, hi), rot = rot }
end

-- Heightmap-free context over a VoxelManip for site predicates.
local function vm_ctx(def, data, area)
	local kinds = sagas.sites.kinds()
	local tops = {}
	local ctx = {
		minp = { x = area.MinEdge.x, y = area.MinEdge.y, z = area.MinEdge.z },
		maxp = { x = area.MaxEdge.x, y = area.MaxEdge.y, z = area.MaxEdge.z },
		emin = area.MinEdge,
		emax = area.MaxEdge,
		water_level = tonumber(core.get_mapgen_setting("water_level")) or 1,
		mg_name = core.get_mapgen_setting("mg_name"),
		mg_spflags = core.get_mapgen_setting("mgv7_spflags"),
		area = area,
		data = data,
	}
	function ctx.H(x, z)
		if not area:contains(x, area.MinEdge.y, z) then
			return nil
		end
		local k = x .. "," .. z
		if tops[k] == nil then
			tops[k] = false
			for y = area.MaxEdge.y - 1, area.MinEdge.y + 1, -1 do
				local kd = kinds[data[area:index(x, y, z)]]
				if kd and kd.solid then
					tops[k] = y
					break
				end
			end
		end
		return tops[k] or nil
	end
	function ctx.biome(x, z)
		local bd = core.get_biome_data({ x = x, y = ctx.H(x, z) or 0, z = z })
		return bd and bd.biome
	end
	function ctx.node(x, y, z)
		if area:contains(x, y, z) then
			return data[area:index(x, y, z)]
		end
	end
	return ctx
end

-- The box to emerge and inspect: the footprint plus a margin, and a tall vertical window around the
-- surface height reported by the heightmap (the real surface may differ, e.g. in Mineclonia).
local function window(def, rec)
	local p1, p2 = util.bbox(def, { x = rec.x, y = rec.y, z = rec.z }, rec.rot)
	local margin = 16
	return { x = p1.x - margin, y = p1.y - def.foundation - 48, z = p1.z - margin },
		{ x = p2.x + margin, y = p2.y + 48, z = p2.z + margin },
		p1,
		p2
end

local function finish(def, k, rec)
	local current = core.parse_json(storage:get_string(k))
	if type(current) == "table" and current.state ~= "pending" then
		return -- already handled (idempotent: an emerge may complete twice)
	end
	local w1, w2 = window(def, rec)
	local vm = core.get_voxel_manip(w1, w2)
	local emin, emax = vm:get_emerged_area()
	local area = VoxelArea(emin, emax)
	local data = vm:get_data()
	local ctx = vm_ctx(def, data, area)
	local y, site = sagas.sites.evaluate(def, ctx, rec.x, rec.z, rec.rot, PcgRandom(util.hash32(k)))
	local reason
	if not y then
		reason = "site " .. table.concat(def.site, " | ") .. " does not hold"
	else
		local p1, p2 = util.bbox(def, { x = rec.x, y = y, z = rec.z }, rec.rot)
		if not sagas.records.spacing_ok(def.id, p1, p2, def.min_distance) then
			local near = {}
			for _, r in ipairs(sagas.records.in_box(p1, p2)) do
				near[#near + 1] = r.id .. "@" .. core.pos_to_string(r.anchor)
			end
			reason = "too close to another landmark (" .. table.concat(near, ", ") .. ")"
		end
	end
	if reason then
		storage:set_string(k, core.write_json({ state = "rejected", reason = reason }))
		util.log("action", "large landmark %s at %d,%d rejected: %s", def.id, rec.x, rec.z, reason)
		return
	end
	local anchor = { x = rec.x, y = y, z = rec.z }
	sagas.placement.place(def, anchor, { rot = rec.rot, site = site })
	storage:set_string(k, core.write_json({ state = "placed", x = rec.x, y = y, z = rec.z, rot = rec.rot }))
	util.debug("large landmark %s placed at %s", def.id, core.pos_to_string(anchor))
end

local function emerge(def, k, rec)
	local w1, w2 = window(def, rec)
	local failed = false
	core.emerge_area(w1, w2, function(_, action, remaining)
		if action == core.EMERGE_CANCELLED or action == core.EMERGE_ERRORED then
			failed = true
		end
		if remaining == 0 and not failed then
			local ok, err = pcall(finish, def, k, rec)
			if not ok then
				util.log("error", "large landmark %s failed: %s", def.id, tostring(err))
				storage:set_string(k, core.write_json({ state = "rejected" }))
			end
		end
	end)
end

function large.on_generated(minp, maxp)
	if sagas.engine.mode ~= "sampler" or not util.settings.large_enable then
		return
	end
	local heightmap
	local csx = maxp.x - minp.x + 1
	for _, def in ipairs(sagas.landmark_list) do
		if
			def.large
			and def.enabled
			and def.y_max >= minp.y
			and def.y_min <= maxp.y
			and (not sagas.engine.only or sagas.engine.only[def.id])
		then
			for cx = math.floor(minp.x / large.cell), math.floor(maxp.x / large.cell) do
				for cz = math.floor(minp.z / large.cell), math.floor(maxp.z / large.cell) do
					local c = large.candidate(def, cx, cz)
					if c and c.x >= minp.x and c.x <= maxp.x and c.z >= minp.z and c.z <= maxp.z then
						local k = key(def, cx, cz)
						if storage:get_string(k) == "" then
							heightmap = heightmap or core.get_mapgen_object("heightmap")
							local h = heightmap and heightmap[(c.z - minp.z) * csx + (c.x - minp.x) + 1]
							if h and h >= minp.y and h < maxp.y and h >= def.y_min and h <= def.y_max then
								local rec = { state = "pending", x = c.x, y = h, z = c.z, rot = c.rot, t = os.time() }
								storage:set_string(k, core.write_json(rec))
								core.after(0, emerge, def, k, rec)
							end
						end
					end
				end
			end
		end
	end
end

-- Stored state of def in cell (cx, cz): nil, or {state = "pending" | "placed" | "rejected", ...}.
function large.state(def, cx, cz)
	local raw = storage:get_string(key(def, cx, cz))
	return raw ~= "" and core.parse_json(raw) or nil
end

-- Placements that were pending when the server stopped (collected at load, before any generation).
local function pending_at_load()
	local out = {}
	for k, v in pairs(storage:to_table().fields) do
		if k:sub(1, 2) == "L:" then
			local rec = core.parse_json(v)
			if type(rec) == "table" and rec.state == "pending" then
				out[#out + 1] = k
			end
		end
	end
	return out
end

function large.resume(keys)
	for _, k in ipairs(keys) do
		local rec = core.parse_json(storage:get_string(k))
		local id = k:match("^L:(.+):%-?%d+:%-?%d+$")
		local def = id and sagas.registered_landmarks[id]
		if type(rec) == "table" and rec.state == "pending" and def then
			emerge(def, k, rec)
		end
	end
end

core.register_on_generated(function(minp, maxp)
	large.on_generated(minp, maxp)
end)

core.register_on_mods_loaded(function()
	local keys = pending_at_load()
	if #keys > 0 then
		core.after(3, large.resume, keys)
	end
end)
