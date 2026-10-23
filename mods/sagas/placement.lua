-- Placing a landmark into a VoxelManip: clear vegetation, blit the schematic, build a foundation, then
-- swap placeholders for this site's materials. Used by the mapgen engine and by `sagas.place`.
local util = sagas.util
local materials = sagas.materials
local placement = {}
sagas.placement = placement

local CLEAR_ABOVE = 16
local saga_cid = {} -- content ids of nodes that come from landmark schematics

core.register_on_mods_loaded(function()
	for _, class in ipairs(sagas.vocab.class_names) do
		saga_cid[core.get_content_id("sagas:m_" .. class)] = true
	end
	saga_cid[core.get_content_id("sagas:color")] = true
end)

local data_buf, param2_buf = {}, {}

-- Node names found below the surface under the footprint (for picking the stone family).
function placement.samples(data, area, p1, p2, y)
	local out = {}
	local step = math.max(2, math.floor(math.max(p2.x - p1.x, p2.z - p1.z) / 6))
	for x = p1.x, p2.x, step do
		for z = p1.z, p2.z, step do
			for dy = 2, 8, 3 do
				if area:contains(x, y - dy, z) then
					out[#out + 1] = core.get_name_from_content_id(data[area:index(x, y - dy, z)])
				end
			end
		end
	end
	return out
end

-- Per landmark: for every schematic column (index z * size.x + x), the lowest placed node's y
-- (`lowest`), or, for a room at ground level, the y of its floor (`floor`): the cell below the
-- room's carved air, which is the terrain itself (-1 or 0). Read once from the schematic file.
local bases = {}
function placement.base(def)
	local b = bases[def.schematic]
	if b then
		return b
	end
	b = { lowest = {}, floor = {} }
	local s = core.read_schematic(def.schematic, { write_yslice_prob = "none" })
	if s and s.data then
		local sx, sy, sz = s.size.x, s.size.y, s.size.z
		for z = 0, sz - 1 do
			for x = 0, sx - 1 do
				local k = z * sx + x
				for y = 0, sy - 1 do
					local n = s.data[(z * sy + y) * sx + x + 1] -- data is ordered z, y, x
					if (n.prob or n.param1 or 255) > 1 then
						if n.name ~= "air" then
							b.lowest[k] = y
						elseif y <= 1 then
							b.floor[k] = y - 1
						end
						break
					end
				end
			end
		end
	end
	bases[def.schematic] = b
	return b
end

-- Anchor a placed landmark to the ground (box corner p1, rotation rot), besides the foundation under
-- its bottom layer: the floor of every ground-level room gets the same foundation, down to
-- `depth` nodes, and a node that hangs exactly one node above the ground gets a support node, so
-- nothing seems to hover. Higher overhangs (eaves, porches, door lintels) stay as they are.
-- Returns the number of nodes filled.
function placement.anchor(data, param2s, area, base, size, p1, rot, depth, fcid)
	local kinds = sagas.sites.kinds()
	local function solid(vi)
		local k = kinds[data[vi]]
		return k and k.solid
	end
	local filled = 0
	local emin = area.MinEdge
	for z = 0, size.z - 1 do
		for x = 0, size.x - 1 do
			local k = z * size.x + x
			local r = util.rotate_local({ x = x, y = 0, z = z }, size, rot)
			local wx, wz = p1.x + r.x, p1.z + r.z
			local low = base.lowest[k]
			if base.floor[k] then
				for y = p1.y + base.floor[k], math.max(emin.y, p1.y - depth), -1 do
					local vi = area:index(wx, y, wz)
					if solid(vi) then
						break
					end
					data[vi], param2s[vi] = fcid, 0
					filled = filled + 1
				end
			elseif low and low > 0 and area:contains(wx, p1.y + low - 2, wz) then
				local vi = area:index(wx, p1.y + low - 1, wz)
				if not solid(vi) and solid(vi - area.ystride) then
					data[vi], param2s[vi] = fcid, 0
					filled = filled + 1
				end
			end
		end
	end
	return filled
end

-- Place def with its anchor at `anchor` into vm (VoxelArea `area`). opts:
--   rot (0/90/180/270), foundation (max depth), clear_above (bool), ctx (materials.site_context), pr (PcgRandom)
-- Returns p1, p2 (placed box) and the number of foundation nodes.
function placement.place_on_vm(vm, area, def, anchor, opts)
	local rot = opts.rot or 0
	local p1, p2 = util.bbox(def, anchor, rot)
	local kinds = sagas.sites.kinds()
	local emax = area.MaxEdge
	local data = vm:get_data(data_buf)
	if opts.clear_above ~= false then
		local top = math.min(emax.y, p2.y + CLEAR_ABOVE)
		local air = core.CONTENT_AIR
		for z = p1.z, p2.z do
			for x = p1.x, p2.x do
				local vi = area:index(x, p1.y, z)
				for _ = p1.y, top do
					local k = kinds[data[vi]]
					if k and k.veg then
						data[vi] = air
					end
					vi = vi + area.ystride
				end
			end
		end
		vm:set_data(data)
	end

	core.place_schematic_on_vmanip(vm, p1, def.schematic, tostring(rot), nil, true, "")

	data = vm:get_data(data_buf)
	local param2s = vm:get_param2_data(param2_buf)
	local depth = opts.foundation or def.foundation or 0
	local filled = 0
	if depth > 0 then
		local fnode = materials.foundation_target(def, opts.ctx)
		filled = placement.anchor(data, param2s, area, placement.base(def), def.size, p1, rot, depth, fnode.cid)
		local emin = area.MinEdge
		for z = p1.z, p2.z do
			for x = p1.x, p2.x do
				if saga_cid[data[area:index(x, p1.y, z)]] then
					for y = p1.y - 1, math.max(emin.y, p1.y - depth), -1 do
						local vi = area:index(x, y, z)
						local k = kinds[data[vi]]
						if k and k.solid then
							break
						end
						data[vi] = fnode.cid
						param2s[vi] = 0
						filled = filled + 1
					end
				end
			end
		end
	end
	local map = materials.remap(def, opts.ctx)
	materials.apply(data, param2s, area, p1, p2, map, opts.pr or PcgRandom(util.hash32(def.id, anchor.x, anchor.z)))
	if opts.ctx and opts.ctx.dust and opts.dust ~= false then
		placement.dust(data, param2s, area, p1, p2, core.get_content_id(opts.ctx.dust))
	end
	vm:set_data(data)
	vm:set_param2_data(param2s)
	return p1, p2, filled
end

-- Nodes that can carry dust: the engine's rule for terrain (cubic and walkable).
local holds_dust = {}
core.register_on_mods_loaded(function()
	local cubic = {
		normal = true,
		allfaces = true,
		allfaces_optional = true,
		glasslike = true,
		glasslike_framed = true,
		glasslike_framed_optional = true,
	}
	for name, def in pairs(core.registered_nodes) do
		if cubic[def.drawtype or "normal"] and def.walkable ~= false then
			holds_dust[core.get_content_id(name)] = true
		end
	end
end)

-- Cover the topmost surface of every column over the footprint p1..p2 with `dust` (a content id),
-- like the mapgen covers terrain in snowy biomes. Clearing the vegetation above a landmark also
-- removes the snow there, so terrain columns in the footprint get theirs back too.
function placement.dust(data, param2s, area, p1, p2, dust)
	local air = core.CONTENT_AIR
	local top = math.min(area.MaxEdge.y - 1, p2.y + CLEAR_ABOVE)
	local covered = 0
	for z = p1.z, p2.z do
		for x = p1.x, p2.x do
			local vi = area:index(x, top, z)
			if data[vi] == air then
				for y = top - 1, math.max(area.MinEdge.y, p1.y - 1), -1 do
					vi = vi - area.ystride
					local c = data[vi]
					if c ~= air then
						if holds_dust[c] and c ~= dust and y < top then
							data[vi + area.ystride] = dust
							param2s[vi + area.ystride] = 0
							covered = covered + 1
						end
						break
					end
				end
			end
		end
	end
	return covered
end

local function run_callbacks(def, anchor, p1, p2, rot)
	local info = core.get_game_info and core.get_game_info() or {}
	for _, fn in ipairs(sagas.registered_on_placed) do
		local ok, err = pcall(fn, def.id, anchor, { min = p1, max = p2 }, rot, info)
		if not ok then
			util.log("error", "on_placed callback failed for %s: %s", def.id, tostring(err))
		end
	end
end
placement.run_callbacks = run_callbacks

local function passable(name)
	local def = core.registered_nodes[name]
	return name ~= "ignore" and def ~= nil and def.walkable == false
end

-- Where someone standing at pos inside the box p1..p2 can stand instead: two nodes beyond the
-- nearest side, on the highest solid node with room for a player. Returns nil if pos is outside
-- the box or the column outside is not loaded.
function placement.exit_spot(p1, p2, pos)
	local x, y, z = math.floor(pos.x + 0.5), math.floor(pos.y + 0.5), math.floor(pos.z + 0.5)
	if x < p1.x or x > p2.x or z < p1.z or z > p2.z or y < p1.y - 1 or y > p2.y then
		return nil
	end
	local exits = {
		{ d = x - p1.x, x = p1.x - 2, z = z },
		{ d = p2.x - x, x = p2.x + 2, z = z },
		{ d = z - p1.z, x = x, z = p1.z - 2 },
		{ d = p2.z - z, x = x, z = p2.z + 2 },
	}
	table.sort(exits, function(a, b)
		return a.d < b.d
	end)
	local e = exits[1]
	for fy = p2.y + 1, p1.y - 16, -1 do
		local below = core.get_node({ x = e.x, y = fy - 1, z = e.z }).name
		if
			below ~= "ignore"
			and not passable(below)
			and passable(core.get_node({ x = e.x, y = fy, z = e.z }).name)
			and passable(core.get_node({ x = e.x, y = fy + 1, z = e.z }).name)
		then
			return { x = e.x, y = fy, z = e.z }
		end
	end
	return nil
end

-- Place on the live map (commands, large landmarks). Returns p1, p2.
function placement.place(def, anchor, opts)
	opts = opts or {}
	local rot = opts.rot or 0
	local p1, p2 = util.bbox(def, anchor, rot)
	local depth = opts.foundation or def.foundation or 0
	local vm = core.get_voxel_manip(
		{ x = p1.x, y = p1.y - depth - 1, z = p1.z },
		{ x = p2.x, y = p2.y + CLEAR_ABOVE, z = p2.z }
	)
	local emin, emax = vm:get_emerged_area()
	local area = VoxelArea(emin, emax)
	if not opts.ctx then
		local bd = core.get_biome_data(anchor)
		local biome_name = bd and core.get_biome_name(bd.biome)
		local data = vm:get_data(data_buf)
		opts.ctx = materials.site_context(biome_name, placement.samples(data, area, p1, p2, anchor.y))
	end
	placement.place_on_vm(vm, area, def, anchor, opts)
	vm:write_to_map(true)
	if util.settings.real_water then
		vm:update_liquids()
	end
	if opts.record ~= false then
		sagas.records.add(def.id, anchor, p1, p2, rot, opts.site or "manual")
	end
	run_callbacks(def, anchor, p1, p2, rot)
	return p1, p2
end
