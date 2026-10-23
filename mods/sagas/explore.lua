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
local finds = {} -- player name -> search state
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

local function find_step(name)
	local st = finds[name]
	if not st then
		return
	end
	if st.k > #st.ring then
		st.r, st.k = st.r + 1, 1
		st.ring = ring_tiles(st.r)
		if st.r * TILE > st.radius then
			finds[name] = nil
			core.chat_send_player(
				name,
				S("No @1 within @2 m (@3 tiles generated). Rarer than you think?", title(st.id), st.radius, st.tiles)
			)
			return
		end
	end
	local t = st.ring[st.k]
	st.k = st.k + 1
	local c = { x = st.origin.x + t[1] * TILE, z = st.origin.z + t[2] * TILE }
	local p1 = { x = c.x - TILE / 2, y = Y1, z = c.z - TILE / 2 }
	local p2 = { x = c.x + TILE / 2 - 1, y = Y2, z = c.z + TILE / 2 - 1 }
	core.emerge_area(p1, p2, function(_, _, remaining)
		if remaining > 0 or finds[name] ~= st then
			return
		end
		st.tiles = st.tiles + 1
		for _, rec in ipairs(records.in_box(vector.offset(p1, 0, -200, 0), vector.offset(p2, 0, 400, 0))) do
			if rec.id == st.id then
				finds[name] = nil
				core.chat_send_player(
					name,
					S("Found @1 after @2 tile(s): @3. /saga tp @4", title(st.id), st.tiles, tour.describe(rec), st.word)
				)
				return
			end
		end
		if st.tiles % 10 == 0 then
			core.chat_send_player(name, S("... @1 tile(s) searched, @2 m out.", st.tiles, st.r * TILE))
		end
		core.after(0, find_step, name)
	end)
end

function explore.find(name, args)
	local player = core.get_player_by_name(name)
	local word, km = args:match("^(%S*)%s*([%d%.]*)$")
	if word == "stop" then
		finds[name] = nil
		return true, S("Search stopped.")
	end
	local id = sagas.resolve_id(word)
	if not id or not player then
		return false, S("Usage: /saga find <id> [km] | stop")
	end
	local near, dist = records.nearest(player:get_pos(), id)
	if near[1] then
		return true,
			S("Already recorded: @1, @2 m away. /saga tp @3", tour.describe(near[1]), math.floor(dist[1]), word)
	end
	if engine.mode ~= "sampler" then
		return false, S("Automatic placement is off in this world, so searching cannot find anything.")
	end
	local radius = math.floor(math.min(4, math.max(0.2, tonumber(km) or 1)) * 1000)
	finds[name] = {
		id = id,
		word = word,
		origin = vector.round(player:get_pos()),
		radius = radius,
		r = 0,
		k = 1,
		ring = ring_tiles(0),
		tiles = 0,
	}
	core.after(0, find_step, name)
	return true, S("Generating map around you, up to @1 m, until @2 appears (/saga find stop).", radius, title(id))
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
	waypoints[name], finds[name], last_list[name] = nil, nil, nil
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
