-- Records of placed sagas: mod storage (persistent) plus an AreaStore index for position queries.
local util = sagas.util
local storage = core.get_mod_storage()
local records = {}
sagas.records = records

local MAX_RECORDS = 5000
local index = AreaStore()
local by_key = {} -- storage key -> record
local order = {} -- storage keys, oldest first

local function add_to_index(key, rec)
	rec.area_id = index:insert_area(rec.p1, rec.p2, key)
	by_key[key] = rec
end

-- Load existing records (keys "r:<x>,<y>,<z>"; large-landmark states use "L:" keys, see large.lua).
local fields = storage:to_table().fields
local keys = {}
for key in pairs(fields) do
	if key:sub(1, 2) == "r:" then
		keys[#keys + 1] = key
	end
end
table.sort(keys, function(a, b)
	local ra, rb = core.parse_json(fields[a]) or {}, core.parse_json(fields[b]) or {}
	return (ra.t or 0) < (rb.t or 0)
end)
for _, key in ipairs(keys) do
	local rec = core.parse_json(fields[key])
	if type(rec) == "table" and rec.p1 and rec.p2 then
		add_to_index(key, rec)
		order[#order + 1] = key
	end
end

-- biome: biome name at the anchor (looked up from the biome noise when not given).
function records.add(id, anchor, p1, p2, rot, site, biome)
	local key = "r:" .. util.pos_key(anchor)
	if not biome then
		local bd = core.get_biome_data(anchor)
		biome = bd and core.get_biome_name(bd.biome) or nil
	end
	local rec = { id = id, anchor = anchor, p1 = p1, p2 = p2, rot = rot, site = site, biome = biome, t = os.time() }
	if by_key[key] then
		index:remove_area(by_key[key].area_id)
	else
		order[#order + 1] = key
	end
	add_to_index(key, rec)
	local saved = { id = id, anchor = anchor, p1 = p1, p2 = p2, rot = rot, site = site, biome = biome, t = rec.t }
	storage:set_string(key, core.write_json(saved))
	while #order > MAX_RECORDS do
		local old = table.remove(order, 1)
		if by_key[old] then
			index:remove_area(by_key[old].area_id)
			by_key[old] = nil
		end
		storage:set_string(old, "")
	end
	return rec
end

function records.remove_at(anchor)
	local key = "r:" .. util.pos_key(anchor)
	local rec = by_key[key]
	if rec then
		index:remove_area(rec.area_id)
		by_key[key] = nil
		storage:set_string(key, "")
		for i, k in ipairs(order) do
			if k == key then
				table.remove(order, i)
				break
			end
		end
	end
end

-- Records whose box contains pos.
function records.at(pos)
	local out = {}
	for _, area in pairs(index:get_areas_for_pos(pos, true, true) or {}) do
		local rec = by_key[area.data]
		if rec then
			out[#out + 1] = rec
		end
	end
	return out
end

-- Records whose box intersects the box p1..p2.
function records.in_box(p1, p2)
	local out = {}
	for _, area in pairs(index:get_areas_in_area(p1, p2, true, true, true) or {}) do
		local rec = by_key[area.data]
		if rec then
			out[#out + 1] = rec
		end
	end
	return out
end

-- A new landmark box p1..p2 may not overlap any placed landmark, and must keep `distance` nodes (horizontally)
-- from other instances of the same landmark id.
function records.spacing_ok(id, p1, p2, distance)
	if #records.in_box(p1, p2) > 0 then
		return false
	end
	local d = distance or 0
	if d <= 0 then
		return true
	end
	local q1 = { x = p1.x - d, y = p1.y - 256, z = p1.z - d }
	local q2 = { x = p2.x + d, y = p2.y + 256, z = p2.z + d }
	for _, rec in ipairs(records.in_box(q1, q2)) do
		if rec.id == id then
			return false
		end
	end
	return true
end

function records.count()
	return #order
end

-- All records, oldest first (a new list; the records themselves are shared, do not modify them).
-- With id, only records of that landmark.
function records.all(id)
	local out = {}
	for _, key in ipairs(order) do
		local rec = by_key[key]
		if rec and (not id or rec.id == id) then
			out[#out + 1] = rec
		end
	end
	return out
end

local function hdist(a, b)
	local dx, dz = a.x - b.x, a.z - b.z
	return math.sqrt(dx * dx + dz * dz)
end
records.hdist = hdist

-- Records sorted by horizontal distance of their anchor from pos (nearest first), optionally only
-- of landmark id and within radius. Returns the list and a parallel list of distances.
function records.nearest(pos, id, radius)
	local list, dist = {}, {}
	for _, rec in ipairs(records.all(id)) do
		local d = hdist(pos, rec.anchor)
		if not radius or d <= radius then
			list[#list + 1] = rec
			dist[rec] = d
		end
	end
	table.sort(list, function(a, b)
		return dist[a] < dist[b]
	end)
	local ds = {}
	for i, rec in ipairs(list) do
		ds[i] = dist[rec]
	end
	return list, ds
end

-- Per landmark id: { count, nn_mean, nn_min }, where nn is the horizontal distance from each copy to
-- the nearest other copy of the same landmark (nil with fewer than two copies).
function records.spread()
	local groups = {}
	for _, rec in ipairs(records.all()) do
		groups[rec.id] = groups[rec.id] or {}
		table.insert(groups[rec.id], rec.anchor)
	end
	local out = {}
	for id, anchors in pairs(groups) do
		local s = { count = #anchors }
		if #anchors > 1 then
			local sum, min = 0, math.huge
			for i, a in ipairs(anchors) do
				local best = math.huge
				for j, b in ipairs(anchors) do
					if i ~= j then
						best = math.min(best, hdist(a, b))
					end
				end
				sum = sum + best
				min = math.min(min, best)
			end
			s.nn_mean, s.nn_min = sum / #anchors, min
		end
		out[id] = s
	end
	return out
end

records.storage = storage
