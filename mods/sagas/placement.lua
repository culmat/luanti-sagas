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
	vm:set_data(data)
	vm:set_param2_data(param2s)
	return p1, p2, filled
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
