-- /saga placed | tp | find | waypoints | stats: see what map generation actually placed, go there, and
-- judge balance (how often each landmark appears, how far apart copies are, why candidates fail).
-- Ideas from mg_villages (/villages, /visit), repixture's rp_village (waypoints) and findbiome
-- (spiral search).
local S = sagas.S
local records = sagas.records
local engine = sagas.engine
local tour = sagas.tour
local explore = {}
sagas.explore = explore

local LIST_MAX = 20
local last_list = {} -- player name -> records shown by /saga placed
local waypoints = {} -- player name -> {radius, huds = {key -> hud id}}

local function compass(from, to)
	local dx, dz = to.x - from.x, to.z - from.z
	local dirs = { "N", "NE", "E", "SE", "S", "SW", "W", "NW" }
	local a = math.deg(math.atan2(dx, dz)) % 360
	return dirs[math.floor((a + 22.5) / 45) % 8 + 1]
end

local function title(id)
	local def = sagas.registered_landmarks[id]
	return def and def.title or id
end

-- ------------------------------------------------------------------ placed / tp

function explore.placed(name, args)
	local player = core.get_player_by_name(name)
	if not player then
		return false, ""
	end
	local word, radius = args:match("^(%S*)%s*(%d*)$")
	local id
	if word and word ~= "" then
		if word:match("^%d+$") and radius == "" then
			radius = word
		else
			id = sagas.resolve_id(word)
			if not id then
				return false, S("Unknown landmark.")
			end
		end
	end
	local pos = player:get_pos()
	local list, dist = records.nearest(pos, id, tonumber(radius))
	if #list == 0 then
		return true, S("No landmarks recorded yet. Explore the world, or try /saga find <id>.")
	end
	last_list[name] = list
	local out = { S("@1 landmark(s) recorded, nearest first:", #list) }
	for i = 1, math.min(#list, LIST_MAX) do
		local rec = list[i]
		out[#out + 1] = ("%2d. %s  %d m %s  %s  %s"):format(
			i,
			title(rec.id),
			math.floor(dist[i] + 0.5),
			compass(pos, rec.anchor),
			rec.biome or "?",
			tostring(rec.site)
		)
	end
	if #list > LIST_MAX then
		out[#out + 1] = S("... and @1 more.", #list - LIST_MAX)
	end
	out[#out + 1] = S("Go there: /saga tp <n>. Tour from there: /saga tour <n>. Markers on screen: /saga waypoints.")
	return true, table.concat(out, "\n")
end

-- The list /saga placed last showed this player, or all records nearest first.
function explore.last_list(player)
	return last_list[player:get_player_name()] or records.nearest(player:get_pos())
end

-- Move the player to a viewpoint of rec, facing it (emerges first, so the terrain is there).
function explore.go(player, rec)
	local from = player:get_pos()
	local name = player:get_player_name()
	tour.emerge(rec, function()
		player = core.get_player_by_name(name)
		if not player then
			return -- left meanwhile
		end
		-- Approach from the side the player came from.
		local angle = math.atan2(from.x - rec.anchor.x, from.z - rec.anchor.z)
		local eye, yaw, pitch = tour.vantage(rec, angle, tour.lift(rec))
		player:set_pos(vector.offset(eye, 0, -(player:get_properties().eye_height or 1.625), 0))
		player:set_look_horizontal(yaw)
		player:set_look_vertical(pitch)
		core.chat_send_player(player:get_player_name(), tour.describe(rec))
	end)
end

function explore.tp(name, args)
	local player = core.get_player_by_name(name)
	if not player then
		return false, ""
	end
	local arg = args:match("^(%S+)")
	if not arg then
		return false, S("Usage: /saga tp <n> | <id>")
	end
	local rec
	local n = tonumber(arg)
	if n then
		local list = last_list[name] or records.nearest(player:get_pos())
		rec = list[n]
		if not rec then
			return false, S("No entry @1; run /saga placed first.", n)
		end
	else
		local id = sagas.resolve_id(arg)
		if not id then
			return false, S("Unknown landmark.")
		end
		-- The nearest copy you are not already looking at, so repeating the command walks through them.
		local pos = player:get_pos()
		for _, r in ipairs((records.nearest(pos, id))) do
			if records.hdist(pos, r.anchor) > math.max(r.p2.x - r.p1.x, r.p2.z - r.p1.z) * 1.5 + 16 then
				rec = r
				break
			end
		end
		rec = rec or records.nearest(pos, id)[1]
		if not rec then
			return false, S("No @1 recorded yet; try /saga find @2.", title(id), arg)
		end
	end
	explore.go(player, rec)
	return true, S("Going to @1 ...", title(rec.id))
end

-- ------------------------------------------------------------------ find

local TILE = 240 -- three mapchunks
local Y1, Y2 = -32, 127 -- two mapchunk layers around sea level

-- Tile offsets on square rings around the start: ring 0, then ring 1 (8 tiles), ring 2 (16), ...
local function ring_tiles(r)
	if r == 0 then
		return { { 0, 0 } }
	end
	local out = {}
	for d = -r, r - 1 do
		out[#out + 1] = { d, -r }
		out[#out + 1] = { r, d }
		out[#out + 1] = { -d, r }
		out[#out + 1] = { -r, -d }
	end
	return out
end
explore.ring_tiles = ring_tiles

-- A search generates the map in square rings of tiles around `origin` until landmark `id` is
-- placed. While it runs the engine is focused on that landmark: no other landmark is placed and it
-- rolls in every new mapchunk (rarity 1), but its site, biome, spacing and anchoring work exactly as
-- in normal map generation. Tiles whose biomes the landmark cannot use are skipped without
-- generating them. One search at a time (the focus is global).
local search -- the running search, or nil

local function restore_focus(st)
	engine.configure({ only = st.saved_only or false, rarity_scale = st.saved_scale })
end

local function stop_search(st, rec)
	if search ~= st then
		return
	end
	search = nil
	restore_focus(st)
	st.on_done(rec, st)
end

-- Could the landmark's biomes be in the tile around (x, z)? Samples five points at the likely ground
-- height (biome noise only, nothing is generated).
local function tile_has_biome(def, x, z)
	if not def.biome_filter then
		return true
	end
	local water = tonumber(core.get_mapgen_setting("water_level")) or 1
	for _, o in ipairs({ { 0, 0 }, { -60, -60 }, { 60, -60 }, { -60, 60 }, { 60, 60 } }) do
		local px, pz = x + o[1], z + o[2]
		local y = core.get_spawn_level(px, pz) or water + 8
		local bd = core.get_biome_data({ x = px, y = y, z = pz })
		if bd and def.biome_filter[bd.biome] then
			return true
		end
	end
	return false
end
explore.tile_has_biome = tile_has_biome

local function search_step(st)
	if search ~= st then
		return
	end
	if st.k > #st.ring then
		st.r, st.k = st.r + 1, 1
		st.ring = ring_tiles(st.r)
		if st.r * TILE > st.radius then
			return stop_search(st, nil)
		end
	end
	local t = st.ring[st.k]
	st.k = st.k + 1
	local c = { x = st.origin.x + t[1] * TILE, z = st.origin.z + t[2] * TILE }
	if not tile_has_biome(st.def, c.x, c.z) then
		st.skipped = st.skipped + 1
		return core.after(0, search_step, st)
	end
	local p1 = { x = c.x - TILE / 2, y = Y1, z = c.z - TILE / 2 }
	local p2 = { x = c.x + TILE / 2 - 1, y = Y2, z = c.z + TILE / 2 - 1 }
	core.emerge_area(p1, p2, function(_, _, remaining)
		if remaining > 0 or search ~= st then
			return
		end
		st.tiles = st.tiles + 1
		if st.on_progress and st.tiles % 10 == 0 then
			st.on_progress(st)
		end
		core.after(0, search_step, st) -- a placement found meanwhile has stopped the search
	end)
end

-- Landmarks are placed from mapgen callbacks (large ones after an extra emerge); the placement
-- callback tells the search.
-- Only placements in the searched area count: while the focus is on, map generated elsewhere (around
-- players, by other mods) may place the landmark too.
local function in_search(st, pos)
	local reach = st.radius + TILE
	return math.abs(pos.x - st.origin.x) <= reach and math.abs(pos.z - st.origin.z) <= reach
end

sagas.register_on_placed(function(id, anchor)
	local st = search
	if st and id == st.id and in_search(st, anchor) then
		core.after(0, function()
			stop_search(st, records.at(anchor)[1] or { id = id, anchor = anchor, p1 = anchor, p2 = anchor })
		end)
	end
end)

-- opts: id, origin, radius (nodes), on_done(rec or nil, state), on_progress(state), owner (player
-- name: the search ends when they leave).
-- Returns the search state, or nil and an error message.
function explore.search(opts)
	if search then
		return nil, S("Another search for @1 is running.", title(search.id))
	end
	if engine.mode ~= "sampler" then
		return nil, S("Automatic placement is off in this world, so searching cannot find anything.")
	end
	local def = sagas.registered_landmarks[opts.id]
	local st = {
		id = opts.id,
		def = def,
		origin = vector.round(opts.origin),
		radius = opts.radius,
		on_done = opts.on_done,
		on_progress = opts.on_progress,
		r = 0,
		k = 1,
		ring = ring_tiles(0),
		tiles = 0,
		skipped = 0,
		saved_only = engine.only and table.copy(engine.only) or nil,
		saved_scale = engine.scale,
		owner = opts.owner,
	}
	if st.saved_only then
		local list = {}
		for k in pairs(st.saved_only) do
			list[#list + 1] = k
		end
		st.saved_only = list
	end
	search = st
	engine.configure({ only = { opts.id }, rarity_scale = 1 / math.max(1, def.rarity) })
	core.after(0, search_step, st)
	return st
end

function explore.stop_search()
	if search then
		stop_search(search, nil)
		return true
	end
	return false
end

local function find_usage()
	return S("Usage: /saga find <id> [km] [--new] | stop")
end

function explore.find(name, args)
	local player = core.get_player_by_name(name)
	if args:match("^stop") then
		return explore.stop_search(), S("Search stopped.")
	end
	local word, km, new
	for w in args:gmatch("%S+") do
		if w == "--new" then
			new = true
		elseif not word then
			word = w
		elseif tonumber(w) then
			km = tonumber(w)
		else
			return false, find_usage()
		end
	end
	local id = sagas.resolve_id(word)
	if not id or not player then
		return false, find_usage()
	end
	if not new then
		local near, dist = records.nearest(player:get_pos(), id)
		if near[1] then
			return true,
				S(
					"Already recorded: @1, @2 m away. /saga tp @3 goes there; --new searches fresh land.",
					tour.describe(near[1]),
					math.floor(dist[1]),
					word
				)
		end
	end
	local radius = math.floor(math.min(16, math.max(0.2, km or 3)) * 1000)
	local st, err = explore.search({
		id = id,
		owner = name,
		origin = player:get_pos(),
		radius = radius,
		on_progress = function(s)
			core.chat_send_player(
				name,
				S("... @1 tile(s) generated, @2 skipped (other biomes), @3 m out.", s.tiles, s.skipped, s.r * TILE)
			)
		end,
		on_done = function(rec, s)
			local p = core.get_player_by_name(name)
			if not rec then
				if p then
					core.chat_send_player(
						name,
						S(
							"No @1 within @2 m (@3 tile(s) generated, @4 without its biomes skipped).",
							title(id),
							s.radius,
							s.tiles,
							s.skipped
						)
					)
				end
				return
			end
			if p then
				core.chat_send_player(
					name,
					S(
						"Placed by map generation after @1 tile(s): @2. /saga tour @3 circles it.",
						s.tiles,
						tour.describe(rec),
						word
					)
				)
				explore.go(p, rec)
			end
		end,
	})
	if not st then
		return false, err
	end
	return true,
		S(
			"Generating fresh map around you, up to @1 m, until map generation places @2 "
				.. "(only it, in every chunk where it fits). /saga find stop ends the search.",
			radius,
			title(id)
		)
end

-- ------------------------------------------------------------------ waypoints

local COLORS = { 0xFFD24A, 0x6FD0FF, 0xFF7A7A, 0x9BE36B, 0xD99BFF, 0xFFA552 }

local function refresh_waypoints(player)
	local name = player:get_player_name()
	local w = waypoints[name]
	if not w then
		return
	end
	local keep = {}
	for _, rec in ipairs((records.nearest(player:get_pos(), nil, w.radius))) do
		local key = sagas.util.pos_key(rec.anchor)
		keep[key] = true
		if not w.huds[key] then
			local center = vector.divide(vector.add(rec.p1, rec.p2), 2)
			w.huds[key] = player:hud_add({
				type = "waypoint",
				name = title(rec.id),
				text = " m",
				precision = 1,
				number = COLORS[sagas.util.hash32(rec.id) % #COLORS + 1],
				world_pos = vector.new(center.x, rec.p2.y + 2, center.z),
			})
		end
	end
	for key, hud in pairs(w.huds) do
		if not keep[key] then
			player:hud_remove(hud)
			w.huds[key] = nil
		end
	end
end

local wp_timer = 0
core.register_globalstep(function(dtime)
	wp_timer = wp_timer + dtime
	if wp_timer < 2 then
		return
	end
	wp_timer = 0
	for name in pairs(waypoints) do
		local player = core.get_player_by_name(name)
		if player then
			refresh_waypoints(player)
		else
			waypoints[name] = nil
		end
	end
end)

core.register_on_leaveplayer(function(player)
	local name = player:get_player_name()
	waypoints[name], last_list[name] = nil, nil
	if search and search.owner == name then
		explore.stop_search()
	end
end)

function explore.waypoints(name, args)
	local player = core.get_player_by_name(name)
	if not player then
		return false, ""
	end
	local w = waypoints[name]
	if args == "off" then
		if w then
			for _, hud in pairs(w.huds) do
				player:hud_remove(hud)
			end
		end
		waypoints[name] = nil
		return true, S("Waypoints off.")
	end
	local radius = math.max(16, math.min(5000, tonumber(args) or 400))
	if w then
		w.radius = radius
	else
		waypoints[name] = { radius = radius, huds = {} }
	end
	refresh_waypoints(player)
	return true, S("Showing landmarks within @1 m (/saga waypoints off).", radius)
end

-- ------------------------------------------------------------------ stats

local function pct(a, b)
	return b > 0 and ("%d%%"):format(math.floor(100 * a / b + 0.5)) or "-"
end

local function reasons(c)
	local parts = {}
	for _, r in ipairs(engine.REASONS) do
		if c[r] > 0 then
			parts[#parts + 1] = ("%s %d"):format(r, c[r])
		end
	end
	return #parts > 0 and table.concat(parts, ", ") or "none"
end

-- Biomes where the landmark fitted best during the survey, as "name 40%, ...". Biomes with fewer than
-- 24 tries (four chunks) are left out: a sliver of a biome says nothing.
local function best_biomes(c, n)
	local list = {}
	for b, bc in pairs(c.biomes) do
		if bc.tries >= 24 then
			list[#list + 1] = { name = b, rate = bc.fit / bc.tries, fit = bc.fit }
		end
	end
	table.sort(list, function(a, b)
		return a.rate > b.rate
	end)
	local parts = {}
	for i = 1, math.min(n, #list) do
		if list[i].fit > 0 then
			parts[#parts + 1] = ("%s %s"):format(list[i].name, pct(list[i].rate, 1))
		end
	end
	return #parts > 0 and table.concat(parts, ", ") or "none"
end
explore.best_biomes = best_biomes

-- Plain-text report; also used by the survey bridge.
function explore.report(only)
	local spread = records.spread()
	local out = {
		("mode %s, rarity scale %s, %d mapchunk(s) generated this session, %d landmark(s) recorded"):format(
			engine.mode,
			tostring(engine.scale),
			engine.chunks or 0,
			records.count()
		),
	}
	for _, def in ipairs(sagas.landmark_list) do
		if (not only or only == def.id) and (def.enabled or only) then
			local sp = spread[def.id] or { count = 0 }
			local st = engine.stats[def.id]
			local line = ("%s: %d recorded"):format(def.id, sp.count)
			if sp.nn_mean then
				line = line .. (", nearest copy avg %d m (min %d m)"):format(sp.nn_mean, sp.nn_min)
			end
			if st then
				line = line
					.. ("; this session %d roll(s) (%d in surface chunks), %d placed, rejected: %s"):format(
						st.rolls,
						st.surface_rolls,
						st.placed,
						reasons(st)
					)
			end
			local pr = engine.probe[def.id]
			if pr then
				line = line
					.. ("; survey fits %s of %d chunk(s), rejected: %s; best biomes: %s"):format(
						pct(pr.fit, pr.chunks),
						pr.chunks,
						reasons(pr),
						best_biomes(pr, 3)
					)
			end
			out[#out + 1] = line
		end
	end
	return table.concat(out, "\n")
end

function explore.stats(_, args)
	local id
	if args ~= "" then
		id = sagas.resolve_id(args)
		if not id then
			return false, S("Unknown landmark.")
		end
	end
	return true, explore.report(id)
end
