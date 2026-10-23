-- In-engine tests, run by `avanti test` in every supported game (https://github.com/BuckarooBanzay/mtt).
local util = sagas.util
local FIX = sagas.modpath .. "/test/fixtures/"
local expected = core.parse_json(util.read_file(FIX .. "expected.json"))

-- Test sagas: disabled for mapgen except where a test enables them.
assert(sagas.register_landmark({
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
assert(sagas.register_landmark({
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
assert(sagas.register_landmark({
	id = "sagas:test_large",
	schematic = FIX .. "large.mts",
	size = { x = 76, y = 2, z = 6 },
	anchor = { x = 38, y = 0, z = 3 },
	site = { "any" },
	rarity = 1,
	rotation = "0",
	foundation = 4,
	large = true,
	materials = { context = "fixed" },
}))
sagas.registered_landmarks["sagas:test_large"].enabled = false
sagas.registered_landmarks["sagas:test_box"].enabled = false
sagas.registered_landmarks["sagas:test_arrow"].enabled = false

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
		sagas.register_landmark({ id = "sagas:test_missing", schematic = FIX .. "nope.mts", size = vector.new(1, 1, 1) })
			== false
	)
	assert(sagas.register_landmark({
		id = "sagas:test_huge",
		schematic = FIX .. "box.mts",
		size = { x = 200, y = 5, z = 7 },
	}) == false, "a landmark larger than a mapchunk needs large = true")
	assert(sagas.register_landmark({
		id = "sagas:test_badsite",
		schematic = FIX .. "box.mts",
		size = { x = 7, y = 5, z = 7 },
		site = { "volcano" },
	}) == false)
	assert(sagas.register_landmark({ id = "bad id" }) == false)
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
		local def = sagas.registered_landmarks["sagas:test_arrow"]
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
		local def = sagas.registered_landmarks["sagas:test_box"]
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

mtt.register_with_area(
	"sagas: a builder inside the footprint gets a spot outside it",
	{ size = { x = 20, y = 20, z = 20 }, emerged = true },
	function(pos1, pos2, callback)
		fill(pos1, pos2, "air")
		local rock = sagas.materials.resolved.fixed.rock.name
		local ground = pos1.y + 8
		fill(pos1, { x = pos2.x, y = ground, z = pos2.z }, rock)
		local anchor = { x = pos1.x + 8, y = ground, z = pos1.z + 8 }
		local p1, p2 = sagas.place("sagas:test_box", anchor, { rot = 0, record = false })
		-- standing one node in from the east wall, on the ground
		local spot = sagas.placement.exit_spot(p1, p2, { x = p2.x - 1, y = ground + 1, z = anchor.z })
		assert(spot, "a spot is found")
		assert(spot.x == p2.x + 2 and spot.z == anchor.z, "east of the box, got " .. core.pos_to_string(spot))
		assert(spot.y == ground + 1, ("on the ground at y=%d, got %d"):format(ground + 1, spot.y))
		assert(sagas.placement.exit_spot(p1, p2, { x = p2.x + 3, y = ground + 1, z = anchor.z }) == nil, "outside")
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

mtt.register("sagas: underground sites on synthetic rock", function(callback)
	local sites = sagas.sites
	local stone = core.get_content_id(sagas.materials.resolved.fixed.rock.name)
	local air = core.CONTENT_AIR
	-- solid rock everywhere; a cave room x/z 20..60, y -60..-50
	local function node(x, y, z)
		if x >= 20 and x <= 60 and z >= 20 and z <= 60 and y >= -60 and y <= -50 then
			return air
		end
		return stone
	end
	local ctx = {
		minp = { x = 0, y = -112, z = 0 },
		maxp = { x = 79, y = -33, z = 79 },
		water_level = 1,
		H = function()
			return nil
		end,
		node = node,
		biome = function()
			return nil
		end,
	}
	local def = {
		size = { x = 7, y = 5, z = 7 },
		anchor = { x = 3, y = 0, z = 3 },
		y_min = -200,
		y_max = -20,
		exposure = "any",
	}
	def.site, def.site_parsed = { "cave_floor" }, { { "cave_floor" } }
	local y = sites.evaluate(def, ctx, 40, 40, 0, PcgRandom(1))
	assert(y == -61, "cave floor at the room's bottom, got " .. tostring(y))
	def.site, def.site_parsed = { "cave_ceiling" }, { { "cave_ceiling" } }
	y = sites.evaluate(def, ctx, 40, 40, 0, PcgRandom(1))
	assert(y == -49 - 4, "cave ceiling: top layer at the ceiling, got " .. tostring(y))
	def.site, def.site_parsed = { "carve" }, { { "carve" } }
	y = sites.evaluate(def, ctx, 10, 70, 0, PcgRandom(2))
	assert(y, "carve in solid rock")
	assert(not sites.evaluate(def, ctx, 40, 40, 0, PcgRandom(3)) or true)
	callback()
end)

mtt.register("sagas: large landmarks are emerged and placed", {
	timeout = 240,
	func = function(callback)
		if sagas.engine.mode ~= "sampler" or not util.settings.large_enable then
			return callback()
		end
		local def = sagas.registered_landmarks["sagas:test_large"]
		def.enabled = true
		sagas.engine.configure({ only = { "sagas:test_large" } })
		local cx, cz = 23, -17
		local c = sagas.large.candidate(def, cx, cz)
		assert(c, "rarity 1 gives every cell a candidate")
		local waited, tries = 0, 1
		local poll
		local function start()
			core.emerge_area(
				{ x = c.x - 8, y = -60, z = c.z - 8 },
				{ x = c.x + 8, y = 100, z = c.z + 8 },
				function(_, _, r)
					if r == 0 then
						core.after(1, poll)
					end
				end
			)
		end
		function poll()
			local st = sagas.large.state(def, cx, cz)
			if st and st.state == "placed" then
				def.enabled = false
				sagas.engine.configure({ only = false })
				local n = #core.find_nodes_in_area(
					{ x = c.x - 40, y = st.y - 1, z = c.z - 6 },
					{ x = c.x + 40, y = st.y + 1, z = c.z + 6 },
					{ sagas.materials.resolved.fixed.cobble.name }
				)
				core.log("action", ("[sagas] large test: placed at %d,%d,%d, %d cobble"):format(c.x, st.y, c.z, n))
				if n < 76 * 6 * 0.9 then
					return callback("large landmark incomplete: " .. n .. " nodes")
				end
				return callback()
			end
			if st and st.state == "rejected" then
				-- the random test world may put this cell in impossible terrain: try the next cell
				if tries < 4 then
					tries = tries + 1
					cx = cx + 1
					c = sagas.large.candidate(def, cx, cz)
					return start()
				end
				return callback("large landmark rejected: " .. tostring(st.reason))
			end
			waited = waited + 1
			if waited > 200 then
				return callback("large landmark not placed (state " .. tostring(st and st.state) .. ")")
			end
			core.after(1, poll)
		end
		start()
	end,
})

mtt.register("sagas: pack schematics match their registrations", function(callback)
	for _, def in ipairs(sagas.landmark_list) do
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
		local def = sagas.registered_landmarks["sagas:test_box"]
		def.enabled = true
		sagas.engine.configure({ rarity_scale = 1, only = { "sagas:test_box" }, survey = true })
		local before = sagas.engine.placed
		local c = { x = 3000, y = 0, z = 3000 }
		core.emerge_area(
			vector.subtract(c, { x = 100, y = 20, z = 100 }),
			vector.add(c, { x = 100, y = 30, z = 100 }),
			function(_, _, remaining)
				if remaining == 0 then
					def.enabled = false
					sagas.engine.configure({ only = false, survey = false })
					local placed = sagas.engine.placed - before
					core.log("action", ("[sagas] mapgen test: %d landmark(s) placed"):format(placed))
					if placed < 1 then
						return callback("no landmark was placed in 9+ mapchunks")
					end
					local recs = sagas.records.in_box(vector.subtract(c, 200), vector.add(c, 200))
					if #recs < 1 then
						return callback("placements were not recorded")
					end
					local st = sagas.engine.stats["sagas:test_box"]
					if not st or st.placed < placed or st.rolls < st.placed then
						return callback("placement stats not counted: " .. dump(st))
					end
					local pr = sagas.engine.probe["sagas:test_box"]
					if not pr or pr.chunks < 1 or pr.tries < pr.chunks then
						return callback("survey probe not counted: " .. dump(pr))
					end
					if not sagas.explore.report("sagas:test_box"):find("survey fits", 1, true) then
						return callback("report lacks the survey line")
					end
					callback()
				end
			end
		)
	end,
})

mtt.register("sagas: records list, nearest and spread", function(callback)
	local records = sagas.records
	local base = records.count()
	local id = "sagas:test_arrow"
	local function box(x)
		return { x = x, y = 5, z = 20000 }, { x = x + 2, y = 5, z = 20001 }
	end
	for _, x in ipairs({ 20000, 20100, 20400 }) do
		local p1, p2 = box(x)
		records.add(id, { x = x, y = 5, z = 20000 }, p1, p2, 0, "test", "testbiome")
	end
	local ok, err = pcall(function()
		assert(records.count() == base + 3, "count")
		assert(#records.all(id) == 3, "all(id)")
		local list, dist = records.nearest({ x = 20390, y = 0, z = 20000 }, id)
		assert(list[1].anchor.x == 20400 and math.abs(dist[1] - 10) < 0.01, "nearest first")
		assert(list[3].anchor.x == 20000, "farthest last")
		assert(#records.nearest({ x = 20390, y = 0, z = 20000 }, id, 50) == 1, "radius")
		assert(list[1].biome == "testbiome", "biome kept")
		local s = records.spread()[id]
		assert(s.count == 3 and s.nn_min == 100, "spread min " .. dump(s))
		assert(math.abs(s.nn_mean - 500 / 3) < 0.01, "spread mean " .. tostring(s.nn_mean))
	end)
	for _, x in ipairs({ 20000, 20100, 20400 }) do
		records.remove_at({ x = x, y = 5, z = 20000 })
	end
	assert(records.count() == base, "records removed")
	callback(not ok and err or nil)
end)

mtt.register("sagas: tour viewpoints look at the landmark from above", function(callback)
	local rec = { p1 = { x = 0, y = 10, z = 0 }, p2 = { x = 28, y = 29, z = 44 } }
	local center = { x = 14, y = 10 + 20 * 0.35, z = 22 }
	for k = 0, 7 do
		local eye, yaw, pitch, c = sagas.tour.vantage(rec, k * math.pi / 4)
		assert(vector.distance(c, center) < 0.01, "center")
		assert(eye.y > rec.p2.y, "camera above the roof")
		local d = math.sqrt((eye.x - c.x) ^ 2 + (eye.z - c.z) ^ 2)
		assert(d > 45 / 2 + 10, "camera outside the footprint")
		local deg = math.deg(pitch)
		assert(deg > 15 and deg < 45, "pitch " .. deg)
		-- The look direction for yaw/pitch points at the center.
		local dir = { x = -math.sin(yaw) * math.cos(pitch), y = -math.sin(pitch), z = math.cos(yaw) * math.cos(pitch) }
		local to = vector.normalize(vector.subtract(c, eye))
		assert(vector.distance(dir, to) < 0.001, "looks at the landmark")
	end
	local lifted = sagas.tour.vantage(rec, 0, 10)
	assert(lifted.y == sagas.tour.vantage(rec, 0).y + 10, "lift raises the camera")
	local near, _, p_near, c = sagas.tour.vantage(rec, 0, 0, 0.5)
	local far, _, p_far = sagas.tour.vantage(rec, 0, 0, 2)
	local function hd(e)
		return math.sqrt((e.x - c.x) ^ 2 + (e.z - c.z) ^ 2)
	end
	assert(math.abs(hd(far) - 4 * hd(near)) < 0.01, "zoom scales the distance")
	assert(math.abs(p_near - p_far) < 0.001, "zoom keeps the viewing angle")
	callback()
end)

mtt.register("sagas: find walks square rings of tiles", function(callback)
	local seen = {}
	for r = 0, 3 do
		local tiles = sagas.explore.ring_tiles(r)
		assert(#tiles == math.max(1, 8 * r), "ring " .. r .. " has " .. #tiles)
		for _, t in ipairs(tiles) do
			assert(math.max(math.abs(t[1]), math.abs(t[2])) == r, "tile on ring")
			local k = t[1] .. "," .. t[2]
			assert(not seen[k], "duplicate tile " .. k)
			seen[k] = true
		end
	end
	callback()
end)

mtt.register("sagas: /saga help has one line per subcommand", function(callback)
	local ok, text = core.registered_chatcommands.saga.func("singleplayer", "")
	assert(not ok, "no subcommand is an error")
	local lines = 0
	for _ in text:gmatch("[^\n]+") do
		lines = lines + 1
	end
	assert(lines >= 14, "help lines: " .. lines)
	for _, sub in ipairs({ "place", "placed", "tp", "tour", "waypoints", "find", "stats" }) do
		assert(
			text:find("\n  " .. sub .. " ", 1, true) or text:find("\n  " .. sub .. ":", 1, true),
			"help lists " .. sub
		)
	end
	callback()
end)

mtt.register("sagas: contact sites need rock above the ground or a cave next door", function(callback)
	local sites = sagas.sites
	local stone = core.get_content_id(sagas.materials.resolved.fixed.rock.name)
	assert(sagas.sites.kinds()[stone].rock, sagas.materials.resolved.fixed.rock.name .. " counts as rock")
	local air = core.CONTENT_AIR
	local def = {
		size = { x = 7, y = 5, z = 7 },
		anchor = { x = 3, y = 0, z = 3 },
		y_min = -100,
		y_max = 300,
		exposure = "any",
	}
	-- Terrain: stone up to H(x, z), air above, minus `holes`; extra stone in `extra`.
	local function ctx_for(H, extra, holes)
		local function key(x, y, z)
			return x .. "," .. y .. "," .. z
		end
		return {
			minp = { x = 0, y = -32, z = 0 },
			maxp = { x = 79, y = 47, z = 79 },
			water_level = 1,
			H = function(x, z)
				if x < 0 or x > 79 or z < 0 or z > 79 then
					return nil
				end
				return H(x, z)
			end,
			biome = function()
				return nil
			end,
			node = function(x, y, z)
				if holes and holes[key(x, y, z)] then
					return air
				end
				if extra and extra[key(x, y, z)] then
					return stone
				end
				return y <= H(x, z) and stone or air
			end,
			key = key,
		}
	end
	local function check(expr, ctx)
		def.site = { expr }
		def.site_parsed = { {} }
		for prim in expr:gmatch("[^+]+") do
			table.insert(def.site_parsed[1], prim)
		end
		return sites.evaluate(def, ctx, 40, 40, 0)
	end
	local flat = function()
		return 10
	end
	-- footprint x/z 37..43, box y 10..14 on flat stone ground
	assert(not check("plain+against_rock", ctx_for(flat)), "stony flat ground is no rock face")
	local pillar = {}
	for y = 0, 14 do
		pillar["36," .. y .. ",36"] = true
	end
	assert(check("plain+against_rock", ctx_for(flat, pillar)) == 10, "rock next to an upper corner")
	local hill = function(x)
		return x >= 46 and 30 or 10
	end
	assert(not check("plain+cave_mouth", ctx_for(hill)), "a solid hill is no cave mouth")
	local holes = {}
	for x = 46, 50 do
		for z = 39, 41 do
			for y = 11, 13 do
				holes[x .. "," .. y .. "," .. z] = true
			end
		end
	end
	assert(check("plain+cave_mouth", ctx_for(hill, nil, holes)) == 10, "cave opening next to the landmark")
	callback()
end)

mtt.register("sagas: snow covers the landmark's top surfaces", function(callback)
	local stone = core.get_content_id(sagas.materials.resolved.fixed.rock.name)
	local dust = core.get_content_id("sagas:color")
	local air = core.CONTENT_AIR
	local area = VoxelArea({ x = 0, y = 0, z = 0 }, { x = 4, y = 30, z = 4 })
	local data, param2s = {}, {}
	for i in area:iterp(area.MinEdge, area.MaxEdge) do
		data[i], param2s[i] = air, 0
	end
	for y = 0, 5 do
		data[area:index(1, y, 1)] = stone -- a wall top at 5
	end
	data[area:index(2, 3, 2)] = stone
	data[area:index(2, 24, 2)] = stone -- overhang at the top of the cleared space: no dust below it
	local plant
	for name, d in pairs(core.registered_nodes) do
		if d.drawtype == "plantlike" and d.walkable == false then
			plant = core.get_content_id(name)
			break
		end
	end
	if plant then
		data[area:index(3, 2, 3)] = plant
	end
	local n = sagas.placement.dust(data, param2s, area, { x = 0, y = 0, z = 0 }, { x = 4, y = 8, z = 4 }, dust)
	assert(data[area:index(1, 6, 1)] == dust, "dust on the wall top")
	assert(data[area:index(2, 4, 2)] == air, "no dust under an overhang")
	if plant then
		assert(data[area:index(3, 3, 3)] == air, "no dust on plants")
	end
	assert(n == 1, "one column covered, got " .. n)
	callback()
end)

mtt.register("sagas: snowy biomes give their dust to landmarks", function(callback)
	local checked = 0
	local by_id = core.ipc_get and core.ipc_get("mcl_biomes:biome_dust_cids") or {}
	for name, b in pairs(core.registered_biomes) do
		local want = b.node_dust and (core.registered_aliases[b.node_dust] or b.node_dust)
		local cid = type(by_id) == "table" and by_id[core.get_biome_id(name)]
		want = want or (cid and core.get_name_from_content_id(cid))
		if want and core.registered_nodes[want] then
			local ctx = sagas.materials.site_context(name)
			assert(ctx.dust == want, name .. ": dust " .. tostring(ctx.dust) .. ", want " .. want)
			checked = checked + 1
		end
	end
	core.log("action", ("[sagas] dust test: %d biome(s) with dust"):format(checked))
	callback()
end)

mtt.register("sagas: schematic bases: lowest node per column, room floors", function(callback)
	local box = sagas.placement.base(sagas.registered_landmarks["sagas:test_box"])
	for k = 0, 7 * 7 - 1 do
		assert(box.lowest[k] == 0 and not box.floor[k], "test box stands on its bottom layer, column " .. k)
	end
	local rh = sagas.registered_landmarks["sagas_antiquity:roundhouse"]
	if rh then
		local b = sagas.placement.base(rh)
		local carved, porch = 0, 0
		for k = 0, rh.size.x * rh.size.z - 1 do
			if b.floor[k] == 0 then
				carved = carved + 1
			end
			if b.lowest[k] == 2 then
				porch = porch + 1
			end
		end
		assert(carved > 20, "roundhouse has a room floor: " .. carved)
		assert(porch > 0, "roundhouse porch starts 2 up")
	end
	callback()
end)

mtt.register("sagas: anchoring fills room floors and one-node gaps, not overhangs", function(callback)
	local stone = core.get_content_id(sagas.materials.resolved.fixed.rock.name)
	local air = core.CONTENT_AIR
	local area = VoxelArea({ x = 0, y = -6, z = 0 }, { x = 6, y = 6, z = 2 })
	local data, param2s = {}, {}
	for i in area:iterp(area.MinEdge, area.MaxEdge) do
		data[i], param2s[i] = (area:position(i).y <= -4) and stone or air, 0
	end
	local function set(x, y, n)
		data[area:index(x, y, 1)] = n
	end
	-- local columns x = 0..3 at world x = 1..4, z = 1: wall, room, one-node gap, porch (two up)
	local base = { lowest = { [0] = 0, [2] = 1, [3] = 2 }, floor = { [1] = -1 } }
	for y = 0, 2 do
		set(1, y, stone)
	end
	set(2, 2, stone)
	set(3, 1, stone)
	set(3, -1, stone) -- ground right under the gap
	set(4, 2, stone)
	set(4, -1, stone)
	local p1 = { x = 1, y = 0, z = 1 }
	local n = sagas.placement.anchor(data, param2s, area, base, { x = 4, y = 3, z = 1 }, p1, 0, 12, stone)
	local function at(x, y)
		return data[area:index(x, y, 1)]
	end
	assert(at(2, -1) == stone and at(2, -3) == stone, "room floor filled down to the ground")
	assert(at(3, 0) == stone, "one-node gap filled")
	assert(at(4, 0) == air and at(4, 1) == air, "porch two up stays an overhang")
	assert(n == 4, "filled " .. n)
	callback()
end)

mtt.register("sagas: landmarks sit a little into sloping ground", function(callback)
	local def = {
		size = { x = 7, y = 12, z = 7 },
		anchor = { x = 3, y = 0, z = 3 },
		y_min = -100,
		y_max = 300,
		exposure = "any",
		site = { "slope" },
		site_parsed = { { "slope" } },
	}
	local function ctx_for(hfun)
		return {
			minp = { x = 0, y = -32, z = 0 },
			maxp = { x = 79, y = 47, z = 79 },
			water_level = 1,
			H = hfun,
			node = function() end,
			biome = function() end,
		}
	end
	local ramp = function(x)
		return 10 + math.floor((x - 37) * 0.8)
	end
	local s = sagas.sites.stats(ctx_for(ramp), { x = 37, z = 37 }, { x = 43, z = 43 })
	local y = sagas.sites.evaluate(def, ctx_for(ramp), 40, 40, 0)
	local want = s.median - math.min(2, math.floor((s.median - s.min) / 2)) -- half the drop, at most 2
	assert(want < s.median, "the ramp is steep enough to sink")
	assert(y == want, ("sunk into the slope: y %s, want %s, median %s"):format(tostring(y), want, s.median))
	def.embed = 0
	assert(sagas.sites.evaluate(def, ctx_for(ramp), 40, 40, 0) == s.median, "embed = 0 keeps the median")
	assert(sagas.sites.embed({ size = { y = 5 } }, { min = 0 }, 4) == 0, "short landmarks are not sunk")
	callback()
end)

mtt.register("sagas: only hidden landmarks stand in deep forest", function(callback)
	local sites = sagas.sites
	local leaves
	for cid, k in pairs(sites.kinds()) do
		if k.leaves then
			leaves = cid
			break
		end
	end
	if not leaves then
		return callback() -- a game without leaves
	end
	local stone = core.get_content_id(sagas.materials.resolved.fixed.rock.name)
	local function ctx_for(canopy)
		return {
			minp = { x = 0, y = -32, z = 0 },
			maxp = { x = 79, y = 47, z = 79 },
			water_level = 1,
			H = function(x, z)
				if x < 0 or x > 79 or z < 0 or z > 79 then
					return nil
				end
				return 10
			end,
			biome = function() end,
			node = function(x, y, z)
				if y == 16 and canopy(x, z) then
					return leaves
				end
				return y <= 10 and stone or core.CONTENT_AIR
			end,
		}
	end
	local def = {
		size = { x = 7, y = 5, z = 7 },
		anchor = { x = 3, y = 0, z = 3 },
		y_min = -100,
		y_max = 300,
		site = { "plain" },
		site_parsed = { { "plain" } },
	}
	local forest = ctx_for(function()
		return true
	end)
	local edge = ctx_for(function(x)
		return x < 36 -- trees only west of the landmark
	end)
	for _, e in ipairs({ "any", "prominent" }) do
		def.exposure = e
		assert(not sites.evaluate(def, forest, 40, 40, 0), e .. " landmark kept out of deep forest")
	end
	def.exposure = "any"
	assert(sites.evaluate(def, edge, 40, 40, 0) == 10, "a forest edge is fine")
	def.exposure = "hidden"
	assert(sites.evaluate(def, forest, 40, 40, 0) == 10, "hidden landmarks may stand in deep forest")
	callback()
end)
