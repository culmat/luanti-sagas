-- /saga chat command for builders and testers (privilege "sagas").
local S = sagas.S
local util = sagas.util

core.register_privilege("sagas", {
	description = S("Can place, inspect and export sagas"),
	give_to_singleplayer = true,
	give_to_admin = true,
})

local UNDO_SLOTS = 8
local MAX_UNDO_VOLUME = 2000000
local undo = {} -- player name -> list of snapshots (newest last)
local marks = {} -- player name -> {p1, p2, armed}

local function pointed_node(player, range)
	local eye = vector.add(player:get_pos(), { x = 0, y = player:get_properties().eye_height or 1.5, z = 0 })
	local dir = player:get_look_dir()
	for pointed in core.raycast(eye, vector.add(eye, vector.multiply(dir, range or 64)), false, false) do
		if pointed.type == "node" then
			return pointed.under
		end
	end
end

local function snapshot(p1, p2)
	local vm = core.get_voxel_manip(p1, p2)
	local emin, emax = vm:get_emerged_area()
	return { emin = emin, emax = emax, data = vm:get_data(), param2 = vm:get_param2_data() }
end

local function restore(snap)
	local vm = core.get_voxel_manip(snap.emin, snap.emax)
	vm:set_data(snap.data)
	vm:set_param2_data(snap.param2)
	vm:write_to_map(true)
end

local function list(saga)
	local lines = {}
	for _, def in ipairs(sagas.landmark_list) do
		if not saga or def.saga == saga then
			lines[#lines + 1] = ("%s  %dx%dx%d  %s  1/%d%s"):format(
				def.id,
				def.size.x,
				def.size.y,
				def.size.z,
				table.concat(def.site, " | "),
				def.rarity,
				def.enabled and "" or "  (disabled)"
			)
		end
	end
	table.sort(lines)
	return #lines > 0 and table.concat(lines, "\n") or S("No landmarks registered.")
end

local function parse_place(args)
	local id, rot, nofound
	for word in args:gmatch("%S+") do
		if word == "--no-foundation" then
			nofound = true
		elseif word == "0" or word == "90" or word == "180" or word == "270" or word == "random" then
			rot = word
		else
			id = word
		end
	end
	return id, rot, nofound
end

local function cmd_place(name, args)
	local player = core.get_player_by_name(name)
	if not player then
		return false, S("Only players can place sagas.")
	end
	local id, rot, nofound = parse_place(args)
	id = sagas.resolve_id(id)
	local def = id and sagas.registered_landmarks[id]
	if not def then
		return false, S("Unknown landmark. Try /saga list")
	end
	local pos = pointed_node(player)
	if not pos then
		return false, S("Point at a node (within 64 nodes) to place the landmark there.")
	end
	local r = rot == "random" or rot == nil and def.rotation == "random"
	local rotn = r and ({ 0, 90, 180, 270 })[math.random(1, 4)] or tonumber(rot or def.rotation) or 0
	local depth = nofound and 0 or def.foundation
	local p1, p2 = util.bbox(def, pos, rotn)
	local q1, q2 = { x = p1.x, y = p1.y - depth - 1, z = p1.z }, { x = p2.x, y = p2.y + 16, z = p2.z }
	local volume = (q2.x - q1.x + 1) * (q2.y - q1.y + 1) * (q2.z - q1.z + 1)
	if volume <= MAX_UNDO_VOLUME then
		undo[name] = undo[name] or {}
		table.insert(undo[name], { snap = snapshot(q1, q2), anchor = pos })
		if #undo[name] > UNDO_SLOTS then
			table.remove(undo[name], 1)
		end
	end
	sagas.place(id, pos, { rot = rotn, foundation = depth, site = "manual" })
	-- Pointing at the ground nearby puts the builder inside the footprint: step them out of it.
	local spot = sagas.placement.exit_spot(p1, p2, player:get_pos())
	if spot then
		player:set_pos({ x = spot.x, y = spot.y - 0.5, z = spot.z })
	end
	return true,
		S("Placed @1 at @2 (rotation @3).", id, core.pos_to_string(pos), rotn)
			.. (volume > MAX_UNDO_VOLUME and " " .. S("Too large to undo.") or "")
end

local function cmd_undo(name)
	local stack = undo[name]
	local last = stack and table.remove(stack)
	if not last then
		return false, S("Nothing to undo.")
	end
	restore(last.snap)
	sagas.records.remove_at(last.anchor)
	return true, S("Undone.")
end

local function cmd_here(name)
	local player = core.get_player_by_name(name)
	if not player then
		return false, ""
	end
	local recs = sagas.records.at(vector.round(player:get_pos()))
	if #recs == 0 then
		return true, S("No landmark here.")
	end
	local out = {}
	for _, rec in ipairs(recs) do
		local def = sagas.registered_landmarks[rec.id]
		out[#out + 1] = ("%s (%s) at %s, site %s, rotation %d"):format(
			rec.id,
			def and def.title or "?",
			core.pos_to_string(rec.anchor),
			tostring(rec.site),
			rec.rot or 0
		)
	end
	return true, table.concat(out, "\n")
end

-- Mark where the landmark's site expression holds around the player (particles for 20 s).
local function cmd_sites(name, args)
	local player = core.get_player_by_name(name)
	local id, radius = args:match("^(%S+)%s*(%d*)")
	id = sagas.resolve_id(id)
	local def = id and sagas.registered_landmarks[id]
	if not player or not def then
		return false, S("Usage: /saga sites <id> [radius]")
	end
	radius = math.min(tonumber(radius) or 48, 96)
	local c = vector.round(player:get_pos())
	local p1 = { x = c.x - radius, y = c.y - 48, z = c.z - radius }
	local p2 = { x = c.x + radius, y = c.y + 48, z = c.z + radius }
	local vm = core.get_voxel_manip(p1, p2)
	local emin, emax = vm:get_emerged_area()
	local area = VoxelArea(emin, emax)
	local data = vm:get_data()
	local kinds = sagas.sites.kinds()
	local tops = {}
	local ctx = {
		minp = p1,
		maxp = p2,
		emin = emin,
		emax = emax,
		water_level = tonumber(core.get_mapgen_setting("water_level")) or 1,
		mg_name = core.get_mapgen_setting("mg_name"),
		data = data,
		area = area,
	}
	function ctx.H(x, z)
		local k = x * 65536 + z
		if tops[k] == nil then
			tops[k] = false
			for y = p2.y, p1.y, -1 do
				if area:contains(x, y, z) then
					local kd = kinds[data[area:index(x, y, z)]]
					if kd and kd.solid then
						tops[k] = y
						break
					end
				end
			end
		end
		return tops[k] or nil
	end
	function ctx.node(x, y, z)
		if area:contains(x, y, z) then
			return data[area:index(x, y, z)]
		end
	end
	function ctx.biome(x, z)
		local bd = core.get_biome_data({ x = x, y = ctx.H(x, z) or c.y, z = z })
		return bd and bd.biome
	end
	local hits = 0
	for x = p1.x, p2.x, 4 do
		for z = p1.z, p2.z, 4 do
			local biome = ctx.biome(x, z)
			if not def.biome_filter or (biome and def.biome_filter[biome]) then
				local y, site = sagas.sites.evaluate(def, ctx, x, z, 0, PcgRandom(x * 31 + z))
				if y then
					hits = hits + 1
					core.add_particlespawner({
						amount = 40,
						time = 20,
						minpos = { x = x, y = y + 1, z = z },
						maxpos = { x = x, y = y + 6, z = z },
						minvel = { x = 0, y = 0.5, z = 0 },
						maxvel = { x = 0, y = 1, z = 0 },
						minexptime = 1,
						maxexptime = 2,
						minsize = 2,
						maxsize = 3,
						texture = "sagas_white.png^[colorize:#ffcc00:200",
						playername = name,
						glow = 14,
					})
					util.debug("site %s for %s at %d,%d,%d", site, id, x, y, z)
				end
			end
		end
	end
	return true, S("@1 candidate anchor(s) marked.", hits)
end

local function cmd_mark(name)
	marks[name] = { armed = true }
	return true, S("Punch two nodes to mark the corners of the area to export.")
end

core.register_on_punchnode(function(pos, _, puncher)
	local name = puncher and puncher:get_player_name()
	local m = name and marks[name]
	if not m or not m.armed then
		return
	end
	if not m.p1 then
		m.p1 = vector.copy(pos)
		core.chat_send_player(name, S("Corner 1: @1", core.pos_to_string(pos)))
	else
		m.p2 = vector.copy(pos)
		m.armed = false
		core.chat_send_player(name, S("Corner 2: @1. Now: /saga export <name>", core.pos_to_string(pos)))
	end
end)

local function cmd_export(name, args)
	local m = marks[name]
	local id = args:match("^([a-z][a-z0-9_]*)$")
	if not id then
		return false, S("Usage: /saga export <name> (lowercase letters, digits, _)")
	end
	if not m or not m.p1 or not m.p2 then
		return false, S("Mark the area first: /saga mark")
	end
	local p1, p2 = vector.sort(m.p1, m.p2)
	local dir = core.get_worldpath() .. "/sagas"
	core.mkdir(dir)
	local path = dir .. "/" .. id .. ".mts"
	core.create_schematic(p1, p2, nil, path, nil)
	core.safe_file_write(
		dir .. "/" .. id .. ".json",
		core.write_json({
			size = vector.subtract(p2, p1),
			p1 = p1,
			p2 = p2,
			exported_by = name,
			game = core.get_game_info and core.get_game_info().id or "?",
		}, true)
	)
	return true, S("Exported to @1", path)
end

-- Subcommands added by other files (tour.lua, explore.lua): name -> {params, func(name, args)}.
local extra = {}
sagas.subcommands = extra

-- One line per subcommand: what to type, then what it does.
local function help()
	local lines = {
		S("/saga subcommands:"),
		"  list [saga]: " .. S("registered landmarks"),
		"  info <id>: " .. S("size, site, biomes, author and licence"),
		"  place <id> [0|90|180|270] [--no-foundation]: " .. S("place at the node you point at"),
		"  undo: " .. S("revert the last place"),
		"  here: " .. S("landmarks at your position"),
		"  sites <id> [radius]: " .. S("mark spots where the landmark's site fits"),
		"  mark, export <name>: " .. S("punch two corners, then save them as a schematic"),
	}
	for _, sub in ipairs({ "placed", "tp", "tour", "waypoints", "find", "stats" }) do
		if extra[sub] then
			lines[#lines + 1] = ("  %s %s: %s"):format(sub, extra[sub].params, extra[sub].desc)
		end
	end
	return table.concat(lines, "\n")
end

core.register_on_mods_loaded(function()
	local explore, tour = sagas.explore, sagas.tour
	extra.placed = { params = "[id] [radius]", desc = S("placed landmarks, nearest first"), func = explore.placed }
	extra.tp = {
		params = "<n>|<id>",
		desc = S("go to entry n of /saga placed, or the next copy of a landmark"),
		func = explore.tp,
	}
	extra.tour = {
		params = "[n|id] [--static] [--times 0.5,0]|stop",
		desc = S("fly around placed landmarks"),
		func = tour.command,
	}
	extra.waypoints = { params = "[radius]|off", desc = S("markers on screen"), func = explore.waypoints }
	extra.find = {
		params = "<id> [km]|stop",
		desc = S("generate the map around you until a landmark appears"),
		func = explore.find,
	}
	extra.stats = { params = "[id]", desc = S("placement statistics of this session"), func = explore.stats }
end)

core.register_chatcommand("saga", {
	params = "[subcommand] (/saga alone lists them)",
	description = S("Place and inspect landmarks"),
	privs = { sagas = true },
	func = function(name, param)
		local sub, rest = param:match("^(%S*)%s*(.-)$")
		if sub == "list" then
			return true, list(rest ~= "" and rest or nil)
		elseif sub == "place" then
			return cmd_place(name, rest)
		elseif sub == "undo" then
			return cmd_undo(name)
		elseif sub == "here" then
			return cmd_here(name)
		elseif sub == "sites" then
			return cmd_sites(name, rest)
		elseif sub == "mark" then
			return cmd_mark(name)
		elseif sub == "export" then
			return cmd_export(name, rest)
		elseif sub == "info" then
			local def = sagas.registered_landmarks[sagas.resolve_id(rest) or ""]
			if not def then
				return false, S("Unknown landmark.")
			end
			return true,
				("%s: %s\n%dx%dx%d, site %s, exposure %s, biomes %s, 1 per %d chunks\n%s, %s, %s"):format(
					def.id,
					def.title or "",
					def.size.x,
					def.size.y,
					def.size.z,
					table.concat(def.site, " | "),
					def.exposure,
					table.concat(def.biomes, ","),
					def.rarity,
					def.author or "?",
					def.license or "?",
					def.source_url or ""
				)
		elseif extra[sub] then
			return extra[sub].func(name, rest)
		end
		return false, help()
	end,
})
