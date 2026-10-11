-- In-engine tests, run by `avanti test` in every supported game (https://github.com/BuckarooBanzay/mtt).
local util = sagas.util
local FIX = sagas.modpath .. "/test/fixtures/"
local expected = core.parse_json(util.read_file(FIX .. "expected.json"))

-- Test sagas: disabled for mapgen except where a test enables them.
assert(sagas.register({
	id = "sagas:test_box",
	title = "Test box",
	schematic = FIX .. "box.mts",
	size = { x = 7, y = 5, z = 7 },
	anchor = { x = 3, y = 0, z = 3 },
	site = { "any" },
	rarity = 1,
	rotation = "0",
	foundation = 6,
	materials = { context = "fixed" },
}))
assert(sagas.register({
	id = "sagas:test_arrow",
	schematic = FIX .. "arrow.mts",
	size = { x = 3, y = 1, z = 2 },
	anchor = { x = 0, y = 0, z = 0 },
	rarity = 1,
	rotation = "0",
	foundation = 0,
	clear_above = false,
	materials = { context = "fixed" },
}))
sagas.registered["sagas:test_box"].enabled = false
sagas.registered["sagas:test_arrow"].enabled = false

local function name_at(pos)
	return core.get_node(pos).name
end

local function fill(p1, p2, name)
	local vm = core.get_voxel_manip(p1, p2)
	local emin, emax = vm:get_emerged_area()
	local area = VoxelArea(emin, emax)
	local data = vm:get_data()
	local cid = core.get_content_id(name)
	for i in area:iterp(p1, p2) do
		data[i] = cid
	end
	vm:set_data(data)
	vm:write_to_map(true)
end

mtt.register("sagas: invalid definitions are rejected, not fatal", function(callback)
	util.reject_level = "action"
	assert(
		sagas.register({ id = "sagas:test_missing", schematic = FIX .. "nope.mts", size = vector.new(1, 1, 1) })
			== false
	)
	assert(sagas.register({
		id = "sagas:test_huge",
		schematic = FIX .. "box.mts",
		size = { x = 200, y = 5, z = 7 },
	}) == false, "a saga larger than a mapchunk needs large = true")
	assert(sagas.register({
		id = "sagas:test_badsite",
		schematic = FIX .. "box.mts",
		size = { x = 7, y = 5, z = 7 },
		site = { "volcano" },
	}) == false)
	assert(sagas.register({ id = "bad id" }) == false)
	util.reject_level = "error"
	assert(sagas.resolve_id("test_box") == "sagas:test_box", "short names resolve")
	callback()
end)

mtt.register("sagas: placeholder and palette nodes are registered", function(callback)
	for _, class in ipairs(sagas.vocab.class_names) do
		assert(core.registered_nodes["sagas:m_" .. class], "missing placeholder for " .. class)
	end
	local c = core.registered_nodes["sagas:color"]
	assert(c and c.paramtype2 == "color" and c.palette == "sagas_palette.png")
	assert(core.registered_nodes["sagas:water"].liquid_range == 0)
	callback()
end)

mtt.register("sagas: every material class resolves to a game node", function(callback)
	local missing = {}
	for _, class in ipairs(sagas.vocab.class_names) do
		local t = sagas.materials.resolved.fixed[class]
		if class ~= "debris" and (not t or t.name:find("^sagas:m_")) then
			missing[#missing + 1] = class
		end
	end
	assert(#missing == 0, "unresolved classes in " .. sagas.materials.game .. ": " .. table.concat(missing, ", "))
	callback()
end)

mtt.register("sagas: stone and wood families follow the site", function(callback)
	local game = sagas.materials.game
	local remap = sagas.materials.remap
	local stone_cid = core.get_content_id("sagas:m_stone")
	local function stone_name(ctx)
		local t = remap({ id = "sagas:test_fam" .. (ctx.family or "") .. (ctx.wood or ""), materials = {} }, ctx)
		return core.get_name_from_content_id(t[stone_cid].cid)
	end
	if game == "minetest_game" then
		assert(sagas.materials.site_context("desert", {}).family == "desert_stone")
		assert(sagas.materials.site_context("taiga", {}).wood == "pine")
		assert(stone_name({ family = "desert_stone" }) == "default:desert_stonebrick")
		assert(stone_name({ family = "stone" }) == "default:stonebrick")
	else
		assert(sagas.materials.site_context("Desert", {}).family == "sandstone")
		assert(sagas.materials.site_context("Taiga", {}).wood == "spruce")
		assert(
			sagas.materials.site_context(nil, { "mcl_deepslate:deepslate", "mcl_deepslate:deepslate" }).family
				== "deepslate"
		)
		assert(stone_name({ family = "sandstone" }) == "mcl_core:sandstonesmooth")
	end
	-- fixed context ignores the site
	local fixed = remap({ id = "sagas:test_fixed", materials = { context = "fixed" } }, { family = "nonsense" })
	assert(fixed[stone_cid].name == sagas.materials.resolved.fixed.stone.name)
	callback()
end)

mtt.register("sagas: Luanti reads schematics written by the sagas tools", function(callback)
	for name, exp in pairs(expected) do
		local s = core.read_schematic(FIX .. name .. ".mts", { write_yslice_prob = "none" })
		assert(s, name .. ": read_schematic failed")
		assert(s.size.x == exp.size[1] and s.size.y == exp.size[2] and s.size.z == exp.size[3], name .. ": size")
		local counts = {}
		for _, n in ipairs(s.data) do
			if (n.prob or 255) > 1 then
				counts[n.name] = (counts[n.name] or 0) + 1
			end
		end
		for node, c in pairs(exp.counts) do
			assert(counts[node] == c, ("%s: %s count %s, expected %d"):format(name, node, tostring(counts[node]), c))
		end
	end
	-- index order z, y, x: arrow has stone at (0,0,0), brick at (2,0,0), colour (param2 23) at (0,0,1)
	local a = core.read_schematic(FIX .. "arrow.mts", {})
	assert(a.data[1].name == "sagas:m_stone" and a.data[3].name == "sagas:m_brick")
	assert(a.data[4].name == "sagas:color" and a.data[4].param2 == 23)
	assert(a.data[1].force_place == true)
	callback()
end)

mtt.register_with_area(
	"sagas: rotations match util.rotate_local",
	{ size = { x = 16, y = 4, z = 16 }, emerged = true },
	function(pos1, pos2, callback)
		fill(pos1, pos2, "air")
		local def = sagas.registered["sagas:test_arrow"]
		local stone = sagas.materials.resolved.fixed.stone.name
		local brick = sagas.materials.resolved.fixed.brick.name
		for i, rot in ipairs({ 0, 90, 180, 270 }) do
			local anchor = { x = pos1.x + 1 + (i - 1) * 4, y = pos1.y + 1, z = pos1.z + 4 }
			local p1 = util.bbox(def, anchor, rot)
			sagas.place("sagas:test_arrow", anchor, { rot = rot, record = false })
			local function at(lx, lz)
				local r = util.rotate_local({ x = lx, y = 0, z = lz }, def.size, rot)
				return name_at({ x = p1.x + r.x, y = p1.y, z = p1.z + r.z })
			end
			assert(at(0, 0) == stone, ("rot %d: stone expected, got %s"):format(rot, at(0, 0)))
			assert(at(2, 0) == brick, ("rot %d: brick expected, got %s"):format(rot, at(2, 0)))
			assert(at(0, 1) == "sagas:color", ("rot %d: colour expected, got %s"):format(rot, at(0, 1)))
		end
		callback()
	end
)

mtt.register_with_area(
	"sagas: place a ruin with foundation and debris",
	{ size = { x = 20, y = 20, z = 20 }, emerged = true },
	function(pos1, pos2, callback)
		fill(pos1, pos2, "air")
		local rock = sagas.materials.resolved.fixed.rock.name
		local ground = pos1.y + 8
		fill(pos1, { x = pos2.x, y = ground, z = pos2.z }, rock)
		local anchor = { x = pos1.x + 8, y = ground, z = pos1.z + 8 }
		local def = sagas.registered["sagas:test_box"]
		local p1, p2 = util.bbox(def, anchor, 0)
		-- a hole under one corner: the foundation has to fill it
		fill({ x = p1.x, y = ground - 4, z = p1.z }, { x = p1.x + 1, y = ground, z = p1.z + 1 }, "air")
		local placed_cb
		sagas.register_on_placed(function(id)
			if id == "sagas:test_box" then
				placed_cb = true
			end
		end)
		local q1, q2 = sagas.place("sagas:test_box", anchor, { rot = 0, record = false })
		assert(q1 and q2 and vector.equals(q1, p1), "sagas.place returns the box")
		assert(placed_cb, "on_placed callback ran")
		local left = core.find_nodes_in_area(p1, p2, { "group:sagas_placeholder" })
		assert(#left == 0, #left .. " placeholders left")
		local wall = sagas.materials.resolved.fixed.stone.name
		assert(name_at({ x = p1.x, y = p1.y + 2, z = p1.z + 3 }) == wall, "west wall")
		assert(name_at({ x = anchor.x, y = p1.y + 3, z = anchor.z }) == "air", "interior carved")
		for y = ground - 4, ground - 1 do
			local n = name_at({ x = p1.x, y = y, z = p1.z })
			assert(n == rock, ("foundation at y=%d (ground %d): %s"):format(y, ground, n))
		end
		local debris = name_at({ x = anchor.x, y = p1.y + 1, z = anchor.z })
		assert(debris ~= "air" and not debris:find("^sagas:"), "debris resolved, got " .. debris)
		callback()
	end
)

mtt.register("sagas: site predicates on synthetic terrain", function(callback)
	local sites = sagas.sites
	local def = {
		size = { x = 7, y = 5, z = 7 },
		anchor = { x = 3, y = 0, z = 3 },
		y_min = -100,
		y_max = 300,
		exposure = "any",
	}
	local function ctx_for(hfun)
		return {
			minp = { x = 0, y = -32, z = 0 },
			maxp = { x = 79, y = 47, z = 79 },
			water_level = 1,
			H = function(x, z)
				if x < 0 or x > 79 or z < 0 or z > 79 then
					return nil
				end
				return hfun(x, z)
			end,
			node = function()
				return nil
			end,
			biome = function()
				return nil
			end,
		}
	end
	local function check(expr, hfun, x, z)
		def.site = { expr }
		def.site_parsed = { {} }
		for prim in expr:gmatch("[^+]+") do
			table.insert(def.site_parsed[1], prim)
		end
		return sites.evaluate(def, ctx_for(hfun), x or 40, z or 40, 0)
	end
	local flat = function()
		return 10
	end
	assert(check("plain", flat) == 10, "plain on flat land")
	assert(not check("plain", function(x)
		return 10 + x % 9
	end), "rough land is not plain")
	local cone = function(x, z)
		return 40 - math.floor(math.max(math.abs(x - 40), math.abs(z - 40)) * 0.8)
	end
	assert(check("peak", cone), "peak on a cone")
	assert(not check("peak", flat), "flat land is no peak")
	local step = function(x)
		return x >= 37 and 30 or 12
	end
	assert(check("cliff", step, 40, 40), "cliff at a step")
	local coast = function(x)
		return x > 30 and 5 or -6
	end
	assert(check("coast", coast, 40, 40), "coast next to the sea")
	assert(not check("coast", flat), "no sea, no coast")
	assert(
		check("cliff+coast", function(x)
			return x >= 37 and 20 or -6
		end, 40, 40),
		"sea cliff"
	)
	assert(
		check("underwater", function()
			return -20
		end),
		"underwater on the sea floor"
	)
	callback()
end)

mtt.register("sagas: pack schematics match their registrations", function(callback)
	for _, def in ipairs(sagas.registered_list) do
		local s = core.read_schematic(def.schematic, { write_yslice_prob = "none" })
		assert(s, def.id .. ": schematic unreadable")
		assert(s.size.x == def.size.x and s.size.y == def.size.y and s.size.z == def.size.z, def.id .. ": size")
		for _, n in ipairs(s.data) do
			assert(n.name == "air" or n.name:find("^sagas:"), def.id .. ": schematic contains game node " .. n.name)
		end
	end
	callback()
end)

mtt.register("sagas: mapgen places sagas", {
	timeout = 240,
	func = function(callback)
		if sagas.engine.mode ~= "sampler" then
			core.log("action", "[sagas] mapgen test skipped (mode " .. sagas.engine.mode .. ")")
			return callback()
		end
		local def = sagas.registered["sagas:test_box"]
		def.enabled = true
		sagas.engine.configure({ rarity_scale = 1, only = { "sagas:test_box" } })
		local before = sagas.engine.placed
		local c = { x = 3000, y = 0, z = 3000 }
		core.emerge_area(
			vector.subtract(c, { x = 100, y = 20, z = 100 }),
			vector.add(c, { x = 100, y = 30, z = 100 }),
			function(_, _, remaining)
				if remaining == 0 then
					def.enabled = false
					sagas.engine.configure({ only = false })
					local placed = sagas.engine.placed - before
					core.log("action", ("[sagas] mapgen test: %d saga(s) placed"):format(placed))
					if placed < 1 then
						return callback("no saga was placed in 9+ mapchunks")
					end
					local recs = sagas.records.in_box(vector.subtract(c, 200), vector.add(c, 200))
					if #recs < 1 then
						return callback("placements were not recorded")
					end
					callback()
				end
			end
		)
	end,
})
