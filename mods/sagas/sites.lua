-- Site predicates: where does a saga fit? Pure functions over a context `ctx`:
--   ctx.minp, ctx.maxp        chunk being generated (the saga footprint must stay inside x/z)
--   ctx.water_level
--   ctx.H(x, z)               surface y (top solid node) or nil if unknown / outside the chunk
--   ctx.biome(x, z)           biome id or nil
--   ctx.node(x, y, z)         content id or nil (outside the loaded area)
--   ctx.kind                  cid -> kind flags table, see sites.kinds()
-- A site expression is a list of alternatives, each a list of primitives that must all hold
-- ("cliff+coast" = {"cliff", "coast"}). Each primitive returns ok, y; y is the anchor height it wants
-- (nil = no opinion). The first non-nil y wins; otherwise the footprint median height is used.
local util = sagas.util
local sites = {}
sagas.sites = sites

local floor, max, min, sqrt = math.floor, math.max, math.min, math.sqrt

-- Per content id: solid ground? vegetation? water? Built once after mods are loaded.
local kinds = {}
function sites.kinds()
	return kinds
end

core.register_on_mods_loaded(function()
	local function cid_of_alias(alias)
		local n = core.registered_aliases[alias]
		return n and core.registered_nodes[n] and core.get_content_id(n)
	end
	local river = cid_of_alias("mapgen_river_water_source")
	local sea = cid_of_alias("mapgen_water_source")
	for name, def in pairs(core.registered_nodes) do
		local cid = core.get_content_id(name)
		local g = def.groups or {}
		local k = {}
		local veg = (g.tree or 0) > 0
			or (g.leaves or 0) > 0
			or (g.plant or 0) > 0
			or (g.flora or 0) > 0
			or (g.sapling or 0) > 0
			or (g.snowy or 0) > 0 and def.drawtype ~= "normal"
			or (g.grass or 0) > 0
			or (g.flower or 0) > 0
			or def.buildable_to and def.drawtype ~= "normal" and def.liquidtype == "none"
		k.veg = veg and name ~= "air"
		k.leaves = (g.leaves or 0) > 0
		k.liquid = def.liquidtype ~= nil and def.liquidtype ~= "none"
		k.flowing = def.liquidtype == "flowing"
		k.water = (g.water or 0) > 0
		k.solid = def.walkable ~= false and not k.liquid and not k.veg and name ~= "air" and name ~= "ignore"
		kinds[cid] = k
	end
	if river then
		kinds[river].river = true
	end
	if sea then
		kinds[sea].sea = true
	end
	sites.has_river_water = river ~= nil and river ~= sea
end)

local function kind(ctx, x, y, z)
	local cid = ctx.node(x, y, z)
	return cid and kinds[cid]
end

-- Footprint (x/z box) of a saga anchored at (x, z) with rotation rot.
function sites.footprint(def, x, z, rot)
	local p1, p2 = util.bbox(def, { x = x, y = 0, z = z }, rot)
	return p1, p2
end

-- Height statistics over the footprint, sampled every `step` nodes. nil if any surface is unknown.
local function stats(ctx, p1, p2)
	local step = max(1, floor(max(p2.x - p1.x, p2.z - p1.z) / 12))
	local hs = {}
	local sum = 0
	for z = p1.z, p2.z, step do
		for x = p1.x, p2.x, step do
			local h = ctx.H(x, z)
			if not h then
				return nil
			end
			hs[#hs + 1] = h
			sum = sum + h
		end
	end
	table.sort(hs)
	local mean = sum / #hs
	local var = 0
	for _, h in ipairs(hs) do
		var = var + (h - mean) ^ 2
	end
	return {
		min = hs[1],
		max = hs[#hs],
		mean = mean,
		sd = sqrt(var / #hs),
		median = hs[floor((#hs + 1) / 2)],
		n = #hs,
	}
end
sites.stats = stats

-- Heights on the ring of radius r (Chebyshev) around the footprint; unknown columns are skipped.
local function ring(ctx, p1, p2, r, step)
	local out = {}
	step = step or 2
	for x = p1.x - r, p2.x + r, step do
		out[#out + 1] = ctx.H(x, p1.z - r)
		out[#out + 1] = ctx.H(x, p2.z + r)
	end
	for z = p1.z - r, p2.z + r, step do
		out[#out + 1] = ctx.H(p1.x - r, z)
		out[#out + 1] = ctx.H(p2.x + r, z)
	end
	local hs = {}
	for _, h in pairs(out) do
		hs[#hs + 1] = h
	end
	return hs
end

local function count_nodes(ctx, p1, p2, ylo, yhi, d, step, pred)
	local n = 0
	for x = p1.x - d, p2.x + d, step do
		for z = p1.z - d, p2.z + d, step do
			for y = ylo, yhi do
				local k = kind(ctx, x, y, z)
				if k and pred(k) then
					n = n + 1
				end
			end
		end
	end
	return n
end

local P = {}
sites.primitives = P

function P.plain(ctx, def, p1, p2, s)
	if s and s.min >= ctx.water_level and s.sd <= 1.5 and s.max - s.min <= 4 then
		return true, s.median
	end
	return false
end

function P.slope(ctx, def, p1, p2, s)
	if not s or s.min < ctx.water_level then
		return false
	end
	local grade = (s.max - s.min) / max(1, max(p2.x - p1.x, p2.z - p1.z))
	return grade >= 0.3 and grade <= 1.2, s.median
end

function P.ridge(ctx, def, p1, p2, s)
	if not s or s.min < ctx.water_level then
		return false
	end
	local cx, cz = floor((p1.x + p2.x) / 2), floor((p1.z + p2.z) / 2)
	local hc = ctx.H(cx, cz)
	local r = floor(max(p2.x - p1.x, p2.z - p1.z) / 2) + 6
	local function drop(dx, dz)
		local a, b = ctx.H(cx - dx, cz - dz), ctx.H(cx + dx, cz + dz)
		return a and b and hc - a >= 4 and hc - b >= 4
	end
	return hc ~= nil and (drop(r, 0) or drop(0, r)), s.median
end

function P.peak(ctx, def, p1, p2, s)
	if not s or s.sd > 3 or s.min < ctx.water_level then
		return false
	end
	local top = s.max
	local r = max(12, floor(max(p2.x - p1.x, p2.z - p1.z) / 2) + 4)
	local inner = ring(ctx, p1, p2, floor(r / 2), 3)
	for _, h in ipairs(inner) do
		if h > top then
			return false
		end
	end
	local outer = ring(ctx, p1, p2, r, 3)
	if #outer < 4 then
		return false
	end
	local lowest = math.huge
	for _, h in ipairs(outer) do
		lowest = min(lowest, h)
	end
	return top - lowest >= 8, s.median
end

function P.cliff(ctx, def, p1, p2, s)
	if not s or s.sd > 2 or s.min < ctx.water_level then
		return false
	end
	local base = s.median
	local function edge(xs, dx, dz)
		local hits, total = 0, 0
		for _, xz in ipairs(xs) do
			local x, z = xz[1], xz[2]
			local deepest
			for d = 1, 4 do
				local h = ctx.H(x + dx * d, z + dz * d)
				if h then
					deepest = min(deepest or h, h)
				end
			end
			if deepest then
				total = total + 1
				if base - deepest >= 6 then
					hits = hits + 1
				end
			end
		end
		return total > 0 and hits >= max(2, total * 0.4)
	end
	local north, south, east, west = {}, {}, {}, {}
	for x = p1.x, p2.x, 2 do
		south[#south + 1] = { x, p1.z }
		north[#north + 1] = { x, p2.z }
	end
	for z = p1.z, p2.z, 2 do
		west[#west + 1] = { p1.x, z }
		east[#east + 1] = { p2.x, z }
	end
	local ok = edge(south, 0, -1) or edge(north, 0, 1) or edge(west, -1, 0) or edge(east, 1, 0)
	return ok, base
end

function P.coast(ctx, def, p1, p2, s)
	if not s or s.min < ctx.water_level or s.sd > 2.5 then
		return false
	end
	local w = ctx.water_level
	for _, h in ipairs(ring(ctx, p1, p2, 6, 2)) do
		if h < w - 1 then
			return true
		end
	end
	for _, h in ipairs(ring(ctx, p1, p2, 12, 3)) do
		if h < w - 1 then
			return true
		end
	end
	return false
end

function P.river(ctx, def, p1, p2, s)
	if not s or not sites.has_river_water then
		return false
	end
	local n = count_nodes(ctx, p1, p2, s.median - 6, s.median + 1, 10, 2, function(k)
		return k.river
	end)
	return n >= 12
end

function P.lake(ctx, def, p1, p2, s)
	if not s then
		return false
	end
	local w = ctx.water_level
	local n = count_nodes(ctx, p1, p2, max(w + 1, s.median - 8), s.median, 12, 3, function(k)
		return k.water and not k.flowing
	end)
	return n >= 12
end

function P.waterfall(ctx, def, p1, p2, s)
	if not s then
		return false
	end
	local n = count_nodes(ctx, p1, p2, s.median - 12, s.median + 6, 10, 2, function(k)
		return k.flowing and k.water
	end)
	if n < 6 then
		return false
	end
	for _, h in ipairs(ring(ctx, p1, p2, 8, 2)) do
		if s.median - h >= 6 then
			return true
		end
	end
	return false
end

function P.underwater(ctx, def, p1, p2, s)
	if not s or s.sd > 2 then
		return false
	end
	return s.max <= ctx.water_level - def.size.y - 2, s.median
end

-- anywhere the surface at the anchor column is known (the rest of the footprint may be unknown)
function P.any(ctx, def, p1, p2, s)
	if s then
		return true, s.median
	end
	local h = ctx.H(floor((p1.x + p2.x) / 2), floor((p1.z + p2.z) / 2))
	return h ~= nil, h
end

-- Layer sites do not need the surface: they scan the loaded nodes.
local function solid_at(ctx, x, y, z)
	local k = kind(ctx, x, y, z)
	return k and k.solid
end

local function air_at(ctx, x, y, z)
	local cid = ctx.node(x, y, z)
	return cid == core.CONTENT_AIR
end

-- y values from y0 towards `last` (step -1 or 1), then the rest of the range: covers every height
-- once, starting at a random one so that different tries find different caves.
local function column_order(ylo, yhi, y0, step)
	local out = {}
	if step < 0 then
		for y = y0, ylo, -1 do
			out[#out + 1] = y
		end
		for y = yhi, y0 + 1, -1 do
			out[#out + 1] = y
		end
	else
		for y = y0, yhi do
			out[#out + 1] = y
		end
		for y = ylo, y0 - 1 do
			out[#out + 1] = y
		end
	end
	return out
end

function P.cave_floor(ctx, def, p1, p2, s, pr)
	local cx, cz = floor((p1.x + p2.x) / 2), floor((p1.z + p2.z) / 2)
	local h = def.size.y
	local ylo, yhi = max(ctx.minp.y + 1, def.y_min), min(ctx.maxp.y - h, def.y_max)
	if ylo > yhi then
		return false
	end
	local y0 = pr and pr:next(ylo, yhi) or yhi
	for _, y in ipairs(column_order(ylo, yhi, y0, -1)) do
		if solid_at(ctx, cx, y, cz) and air_at(ctx, cx, y + 1, cz) then
			local corners = 0
			for _, c in ipairs({ { p1.x, p1.z }, { p2.x, p1.z }, { p1.x, p2.z }, { p2.x, p2.z } }) do
				if solid_at(ctx, c[1], y, c[2]) or solid_at(ctx, c[1], y - 1, c[2]) then
					corners = corners + 1
				end
			end
			local free = 0
			for dy = 1, h, max(1, floor(h / 6)) do
				if air_at(ctx, cx, y + dy, cz) then
					free = free + 1
				end
			end
			if corners >= 3 and free >= 4 then
				return true, y
			end
		end
	end
	return false
end

function P.cave_ceiling(ctx, def, p1, p2, s, pr)
	local cx, cz = floor((p1.x + p2.x) / 2), floor((p1.z + p2.z) / 2)
	local h = def.size.y
	local ylo, yhi = max(ctx.minp.y + h, def.y_min), min(ctx.maxp.y - 1, def.y_max)
	if ylo > yhi then
		return false
	end
	local y0 = pr and pr:next(ylo, yhi) or ylo
	for _, y in ipairs(column_order(ylo, yhi, y0, 1)) do
		if solid_at(ctx, cx, y, cz) and air_at(ctx, cx, y - 1, cz) then
			local corners = 0
			for _, c in ipairs({ { p1.x, p1.z }, { p2.x, p1.z }, { p1.x, p2.z }, { p2.x, p2.z } }) do
				if solid_at(ctx, c[1], y, c[2]) or solid_at(ctx, c[1], y + 1, c[2]) then
					corners = corners + 1
				end
			end
			if corners >= 3 and air_at(ctx, cx, y - floor(h / 2), cz) then
				-- the top layer of the schematic replaces the ceiling's lowest node
				return true, y - (def.size.y - 1 - def.anchor.y)
			end
		end
	end
	return false
end

function P.carve(ctx, def, p1, p2, s, pr)
	local h = def.size.y
	local ylo, yhi = max(ctx.minp.y + 2, def.y_min), min(ctx.maxp.y - h - 2, def.y_max)
	if ylo > yhi then
		return false
	end
	local y0 = pr and pr:next(ylo, yhi) or ylo
	local step = max(2, floor(max(p2.x - p1.x, p2.z - p1.z) / 6))
	for x = p1.x, p2.x, step do
		for z = p1.z, p2.z, step do
			for y = y0 - 1, y0 + h + 1, 3 do
				if not solid_at(ctx, x, y, z) then
					return false
				end
			end
			local sh = ctx.H(x, z)
			if sh and sh < y0 + h + 6 then
				return false
			end
		end
	end
	return true, y0
end

function P.floatland(ctx, def, p1, p2, s)
	if ctx.mg_name ~= "v7" or not (ctx.mg_spflags or ""):find("floatlands") then
		return false
	end
	local fmin = tonumber(core.get_mapgen_setting("mgv7_floatland_ymin")) or 1280
	if not s or s.min < fmin or s.sd > 2.5 then
		return false
	end
	return true, s.median
end

-- exposure ----------------------------------------------------------------------------------------

function sites.exposure_ok(ctx, def, p1, p2, s, y, layer)
	local e = def.exposure or "any"
	if e == "any" then
		return true
	end
	if e == "hidden" then
		if layer then
			return true
		end
		if not s then
			return false
		end
		local around = ring(ctx, p1, p2, 16, 4)
		if #around > 0 then
			local sum = 0
			for _, h in ipairs(around) do
				sum = sum + h
			end
			if s.median - sum / #around <= -4 then
				return true -- valley
			end
		end
		local covered, total = 0, 0
		for x = p1.x - 6, p2.x + 6, 4 do
			for z = p1.z - 6, p2.z + 6, 4 do
				local h = ctx.H(x, z)
				if h then
					total = total + 1
					for dy = 2, 8, 2 do
						local k = kind(ctx, x, h + dy, z)
						if k and k.leaves then
							covered = covered + 1
							break
						end
					end
				end
			end
		end
		return total > 0 and covered >= total * 0.5
	end
	-- prominent: nothing higher close by, or water on one side
	if layer or not s then
		return false
	end
	local higher = 0
	local near = ring(ctx, p1, p2, 10, 3)
	for _, h in ipairs(near) do
		if h > y + 1 then
			higher = higher + 1
		end
		if h < ctx.water_level - 1 then
			return true
		end
	end
	return #near > 0 and higher <= #near * 0.1
end

-- evaluation --------------------------------------------------------------------------------------

-- Returns anchor y and the matching site expression, or nil.
function sites.evaluate(def, ctx, x, z, rot, pr)
	local p1, p2 = sites.footprint(def, x, z, rot)
	if p1.x < ctx.minp.x or p2.x > ctx.maxp.x or p1.z < ctx.minp.z or p2.z > ctx.maxp.z then
		return nil
	end
	local s = stats(ctx, p1, p2)
	for i, alt in ipairs(def.site_parsed) do
		local ok, y, layer = true, nil, false
		for _, prim in ipairs(alt) do
			local good, want = P[prim](ctx, def, p1, p2, s, pr)
			if not good then
				ok = false
				break
			end
			if y == nil and want ~= nil then
				y = want
			end
			if sagas.vocab.layer_set[prim] then
				layer = true
			end
		end
		if ok then
			y = y or (s and s.median)
			if y and sites.exposure_ok(ctx, def, p1, p2, s, y, layer) then
				return floor(y), def.site[i]
			end
		end
	end
	return nil
end
