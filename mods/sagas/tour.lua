-- /saga tour: visit recorded landmarks one after another and circle each one with the camera.
--
-- Plan A attaches the player to an invisible camera entity that orbits the landmark (the pattern of
-- Signal_'s artifact_cutscenes). If a game detaches the player again, or --static is given, the tour
-- falls back to fixed viewpoints around the landmark.
--
-- Keys while touring (shown on screen): A/D previous/next landmark, W/S closer/farther, Space time of
-- day, E pause and resume (fly around freely while paused), Shift end. Everything the tour
-- changes (position, look, HUD, physics, time of day) is restored at the end.
local S = sagas.S
local records = sagas.records
local tour = {}
sagas.tour = tour

local DEFAULT_PERIOD = 30 -- seconds per orbit; slow enough to be easy on the eyes
local VIEWPOINTS = 4
local ZOOM_MIN, ZOOM_MAX = 0.5, 2
local GLIDE = 1.5 -- seconds from where a paused player resumes to the orbit
local TIMES = {
	{ t = 0.5, name = S("noon") },
	{ t = 0.79, name = S("dusk") },
	{ t = 0.0, name = S("midnight") },
	{ t = 0.22, name = S("dawn") },
}
local active = {} -- player name -> state

core.register_entity("sagas:camera", {
	initial_properties = {
		visual = "sprite",
		textures = { "blank.png" },
		is_visible = false,
		physical = false,
		collide_with_objects = false,
		pointable = false,
		static_save = false,
	},
})

-- Yaw and pitch (radians) for an eye at `eye` looking at `target` (same convention as avanti_camera).
function tour.look_angles(eye, target)
	local dx, dy, dz = target.x - eye.x, target.y - eye.y, target.z - eye.z
	return math.atan2(-dx, dz), -math.atan2(dy, math.sqrt(dx * dx + dz * dz))
end

-- Camera for a record at `angle` (radians around the landmark): eye position, yaw, pitch, look target.
-- The circle's radius and height grow with the landmark, so the camera looks down at 25-35 degrees;
-- zoom scales the distance (1 = default), lift raises the whole circle above hills.
function tour.vantage(rec, angle, lift, zoom)
	local p1, p2 = rec.p1, rec.p2
	zoom = zoom or 1
	local sx, sy, sz = p2.x - p1.x + 1, p2.y - p1.y + 1, p2.z - p1.z + 1
	local center = { x = (p1.x + p2.x) / 2, y = p1.y + sy * 0.35, z = (p1.z + p2.z) / 2 }
	local r = (math.max(sx, sz) * 1.2 + 12) * zoom
	local up = (p2.y + 8 + sy / 2 - center.y) * zoom
	local eye = {
		x = center.x + r * math.sin(angle),
		y = center.y + up + (lift or 0),
		z = center.z + r * math.cos(angle),
	}
	local yaw, pitch = tour.look_angles(eye, center)
	return eye, yaw, pitch, center
end

local function blocked(pos)
	local name = core.get_node(vector.round(pos)).name
	if name == "ignore" then
		return false -- not loaded: no opinion
	end
	local def = core.registered_nodes[name]
	return def == nil or def.walkable ~= false
end

-- How far to raise the whole circle so no viewpoint sits inside a hill (checked after emerging).
function tour.lift(rec, zoom)
	local lift = 0
	for k = 0, 15 do
		local eye = tour.vantage(rec, k * math.pi / 8, lift, zoom)
		local tries = 0
		while tries < 48 and (blocked(eye) or blocked(vector.offset(eye, 0, 1, 0))) do
			lift, tries = lift + 2, tries + 1
			eye.y = eye.y + 2
		end
	end
	return lift
end

-- Emerge everything the camera can see of rec (up to the farthest zoom), then call fn().
function tour.emerge(rec, fn)
	local r = (math.max(rec.p2.x - rec.p1.x, rec.p2.z - rec.p1.z) * 1.2 + 12) * ZOOM_MAX + 16
	local c = { x = (rec.p1.x + rec.p2.x) / 2, z = (rec.p1.z + rec.p2.z) / 2 }
	core.emerge_area(
		{ x = c.x - r, y = rec.p1.y - 16, z = c.z - r },
		{ x = c.x + r, y = rec.p2.y + 96, z = c.z + r },
		function(_, _, remaining)
			if remaining == 0 then
				fn()
			end
		end
	)
end

local function eye_height(player)
	return player:get_properties().eye_height or 1.625
end

local function title(rec)
	local def = sagas.registered_landmarks[rec.id]
	return def and def.title or rec.id
end

local function describe(rec)
	return ("%s (%s) at %s, %s, site %s"):format(
		title(rec),
		rec.id,
		core.pos_to_string(rec.anchor),
		rec.biome or "?",
		tostring(rec.site)
	)
end
tour.describe = describe

-- ------------------------------------------------------------------ HUD

local function hud_text(st)
	local rec = st.list[st.i]
	local where = ("%d/%d: %s (%s, %s)"):format(st.i, #st.list, title(rec), rec.biome or "?", tostring(rec.site))
	if st.time_k then
		where = where .. " - " .. TIMES[st.time_k].name
	end
	if st.paused then
		return S("Paused at @1", where)
			.. "\n"
			.. S("Fly around freely (K toggles flying). E: resume from here. /saga tour stop: end here.")
	elseif st.waiting then
		return S("Tour @1", where) .. "\n" .. S("loading ...")
	end
	return S("Tour @1", where)
		.. "\n"
		.. S("A/D: previous/next   W/S: closer/farther   Space: time of day   E: pause   Shift: end")
end

local function show(player, st)
	local text = hud_text(st)
	if st.hud then
		if text ~= st.hud_text then
			player:hud_change(st.hud, "text", text)
		end
	else
		st.hud = player:hud_add({
			type = "text",
			position = { x = 0.5, y = 0.03 },
			alignment = { x = 0, y = 1 },
			text = text,
			number = 0xFFFFFF,
			style = 1,
		})
	end
	st.hud_text = text
end

-- ------------------------------------------------------------------ camera modes

local function remove_camera(st)
	if st.ent and st.ent:get_pos() then
		st.ent:remove()
	end
	st.ent = nil
end

local function attach_camera(player, st, feet)
	st.ent = core.add_entity(feet, "sagas:camera")
	if not st.ent then
		return false
	end
	player:set_attach(st.ent)
	st.check_attach = true
	return true
end

local function to_static(player, st, why)
	player:set_detach()
	remove_camera(st)
	st.mode = "static"
	st.view = nil
	core.chat_send_player(player:get_player_name(), S("Tour: @1, using fixed viewpoints.", why))
end

local function hide_hud(player)
	player:hud_set_flags({ hotbar = false, healthbar = false, breathbar = false, crosshair = false, wielditem = false })
end

local function freeze(player)
	player:set_physics_override({ speed = 0, jump = 0, gravity = 0 })
end

local function begin(player, st)
	local rec = st.list[st.i]
	st.waiting = true
	show(player, st)
	core.chat_send_player(player:get_player_name(), ("[%d/%d] %s"):format(st.i, #st.list, describe(rec)))
	local name = player:get_player_name()
	tour.emerge(rec, function()
		player = core.get_player_by_name(name)
		if not player or active[name] ~= st or st.list[st.i] ~= rec then
			return -- left, stopped or skipped meanwhile
		end
		st.lift, st.lift_zoom = tour.lift(rec, st.zoom), st.zoom
		st.angle, st.elapsed, st.view, st.glide = 0, 0, nil, nil
		st.waiting = false
		if st.mode == "orbit" and not st.paused then
			local eye = tour.vantage(rec, 0, st.lift, st.zoom)
			local feet = vector.offset(eye, 0, -eye_height(player), 0)
			if not st.ent then
				if not attach_camera(player, st, feet) then
					return to_static(player, st, S("the camera could not be created"))
				end
			else
				st.ent:set_pos(feet)
			end
		end
		show(player, st)
	end)
end

function tour.stop(player, msg)
	local name = player:get_player_name()
	local st = active[name]
	if not st then
		return false, S("No tour running.")
	end
	active[name] = nil
	player:set_detach()
	remove_camera(st)
	if st.hud then
		player:hud_remove(st.hud)
	end
	player:set_physics_override(st.saved.physics)
	player:hud_set_flags(st.saved.hud)
	if not st.paused then -- a paused player ends the tour where they flew to
		player:set_pos(st.saved.pos)
		player:set_look_horizontal(st.saved.yaw)
		player:set_look_vertical(st.saved.pitch)
	end
	if st.time_changed then
		core.set_timeofday(st.saved.time)
	end
	return true, msg or S("Tour ended.")
end

function tour.skip(player, delta)
	local st = active[player:get_player_name()]
	if not st then
		return false, S("No tour running.")
	end
	st.i = math.max(1, math.min(#st.list, st.i + delta))
	begin(player, st)
	return true
end

function tour.pause(player)
	local st = active[player:get_player_name()]
	if not st or st.paused then
		return false, S("No running tour to pause.")
	end
	local pos = player:get_pos()
	player:set_detach()
	remove_camera(st)
	player:set_pos(pos)
	player:set_physics_override(st.saved.physics)
	player:hud_set_flags(st.saved.hud)
	st.paused = true
	show(player, st)
	return true
end

-- Continue circling the current landmark, starting from the side where the player is now.
function tour.resume(player)
	local st = active[player:get_player_name()]
	if not st or not st.paused then
		return false, S("The tour is not paused.")
	end
	local rec = st.list[st.i]
	local pos = player:get_pos()
	local c = { x = (rec.p1.x + rec.p2.x) / 2, z = (rec.p1.z + rec.p2.z) / 2 }
	st.paused = false
	st.angle = math.atan2(pos.x - c.x, pos.z - c.z)
	st.elapsed = 0
	st.view = nil
	st.glide = { from = vector.offset(pos, 0, eye_height(player), 0), t = 0 }
	st.prev = player:get_player_control()
	hide_hud(player)
	freeze(player)
	if st.mode == "orbit" and not attach_camera(player, st, pos) then
		to_static(player, st, S("the camera could not be created"))
	end
	show(player, st)
	return true
end

local function cycle_time(st)
	st.time_k = (st.time_k or 0) % #TIMES + 1
	st.auto_times = false
	st.time_changed = true
	core.set_timeofday(TIMES[st.time_k].t)
end

local function auto_time(st)
	if not st.auto_times or #st.times == 0 then
		return
	end
	local k = math.floor(st.elapsed / st.period * #st.times) % #st.times + 1
	if k ~= st.auto_k then
		st.auto_k = k
		st.time_changed = true
		core.set_timeofday(st.times[k])
	end
end

-- ------------------------------------------------------------------ per step

local function smooth(u)
	u = math.min(math.max(u, 0), 1)
	return u * u * (3 - 2 * u)
end

-- Keys: returns true when the tour ended or moved on (nothing else to do this step).
local function handle_keys(player, st, dtime)
	local ctrl = player:get_player_control()
	local prev = st.prev or {}
	st.prev = ctrl
	local function pressed(key)
		return ctrl[key] and not prev[key]
	end
	if st.paused then
		-- E (aux1) toggles: it sits at the same place on QWERTY, QWERTZ and AZERTY keyboards and is free
		-- while flying fast. The zoom key also resumes, but it is labelled Y on Swiss and German keyboards.
		if pressed("aux1") or pressed("zoom") then
			tour.resume(player)
		end
		return true
	end
	if pressed("sneak") then
		local _, msg = tour.stop(player)
		core.chat_send_player(player:get_player_name(), msg)
		return true
	elseif pressed("left") then
		tour.skip(player, -1)
		return true
	elseif pressed("right") then
		tour.skip(player, 1)
		return true
	elseif pressed("aux1") and not st.waiting then
		tour.pause(player)
		return true
	end
	if pressed("jump") then
		cycle_time(st)
		show(player, st)
	end
	if ctrl.up then
		st.zoom = math.max(ZOOM_MIN, st.zoom - 0.6 * dtime)
	elseif ctrl.down then
		st.zoom = math.min(ZOOM_MAX, st.zoom + 0.6 * dtime)
	end
	return false
end

local function step_player(player, st, dtime)
	if handle_keys(player, st, dtime) or st.waiting then
		return
	end
	local rec = st.list[st.i]
	st.elapsed = st.elapsed + dtime
	if st.elapsed >= st.period then
		if st.i >= #st.list then
			local _, msg = tour.stop(player, S("Tour finished: @1 landmark(s).", #st.list))
			core.chat_send_player(player:get_player_name(), msg)
			return
		end
		st.i = st.i + 1
		begin(player, st)
		return
	end
	auto_time(st)
	if math.abs(st.zoom - st.lift_zoom) > 0.15 then
		st.lift, st.lift_zoom = tour.lift(rec, st.zoom), st.zoom
	end
	st.angle = st.angle + 2 * math.pi * dtime / st.period
	local angle = st.angle
	if st.mode == "static" then
		angle = (math.floor(st.angle / (2 * math.pi / VIEWPOINTS)) + 0.5) * 2 * math.pi / VIEWPOINTS
	end
	local eye, _, _, center = tour.vantage(rec, angle, st.lift, st.zoom)
	if st.glide then
		st.glide.t = st.glide.t + dtime / GLIDE
		local u = smooth(st.glide.t)
		eye = vector.add(vector.multiply(st.glide.from, 1 - u), vector.multiply(eye, u))
		if st.glide.t >= 1 then
			st.glide = nil
		end
	end
	local yaw, pitch = tour.look_angles(eye, center)
	local feet = vector.offset(eye, 0, -eye_height(player), 0)
	if st.mode == "orbit" then
		if st.check_attach and not player:get_attach() then
			return to_static(player, st, S("this game does not keep the player attached"))
		end
		if not (st.ent and st.ent:get_pos()) then
			return to_static(player, st, S("the camera was removed"))
		end
		st.ent:move_to(feet, true)
		player:set_look_horizontal(yaw)
		player:set_look_vertical(pitch)
	else
		local k = math.floor(st.angle / (2 * math.pi / VIEWPOINTS))
		if k ~= st.view or st.glide then
			st.view = k
			player:set_look_horizontal(yaw)
			player:set_look_vertical(pitch)
			player:set_pos(feet)
		elseif vector.distance(player:get_pos(), feet) > 1 then
			player:set_pos(feet)
		end
	end
end

core.register_globalstep(function(dtime)
	for name, st in pairs(active) do
		local player = core.get_player_by_name(name)
		if player then
			step_player(player, st, dtime)
		else
			remove_camera(st)
			active[name] = nil
		end
	end
end)

core.register_on_leaveplayer(function(player)
	local st = active[player:get_player_name()]
	if st then
		player:set_detach()
		remove_camera(st)
		active[player:get_player_name()] = nil
	end
end)

-- ------------------------------------------------------------------ command

local function parse(args)
	local opts = { period = DEFAULT_PERIOD, times = {} }
	local words = {}
	for w in args:gmatch("%S+") do
		words[#words + 1] = w
	end
	local i = 1
	while i <= #words do
		local w = words[i]
		if w == "--static" then
			opts.static = true
		elseif w == "--period" then
			i = i + 1
			opts.period = math.max(6, tonumber(words[i]) or DEFAULT_PERIOD)
		elseif w == "--times" then
			i = i + 1
			for t in (words[i] or ""):gmatch("[^,]+") do
				local v = tonumber(t)
				if v then
					opts.times[#opts.times + 1] = v % 1
				end
			end
		elseif w:sub(1, 2) == "--" then
			return nil, S("Unknown option @1.", w)
		else
			opts.target = w
		end
		i = i + 1
	end
	return opts
end

function tour.start(player, args)
	local opts, err = parse(args)
	if not opts then
		return false, err
	end
	local list, first
	local n = tonumber(opts.target or "")
	if n then
		-- /saga tour <n>: the list /saga placed showed, starting at entry n
		list = sagas.explore.last_list(player)
		first = math.floor(n)
		if not list[first] then
			return false, S("No entry @1; run /saga placed first.", first)
		end
	else
		local id
		if opts.target then
			id = sagas.resolve_id(opts.target)
			if not id then
				return false, S("Unknown landmark.")
			end
		end
		list, first = records.nearest(player:get_pos(), id), 1
	end
	if #list == 0 then
		return false, S("No landmarks recorded yet. Explore the world, or try /saga find <id>.")
	end
	local name = player:get_player_name()
	if active[name] then
		tour.stop(player)
	end
	local st = {
		list = list,
		i = first,
		period = opts.period,
		times = opts.times,
		auto_times = #opts.times > 0,
		mode = opts.static and "static" or "orbit",
		zoom = 1,
		lift_zoom = 1,
		angle = 0,
		elapsed = 0,
		prev = player:get_player_control(),
		saved = {
			pos = player:get_pos(),
			yaw = player:get_look_horizontal(),
			pitch = player:get_look_vertical(),
			hud = player:hud_get_flags(),
			physics = player:get_physics_override(),
			time = core.get_timeofday(),
		},
	}
	active[name] = st
	hide_hud(player)
	freeze(player)
	begin(player, st)
	return true, S("Touring @1 landmark(s); the keys are shown at the top of the screen.", #list - first + 1)
end

function tour.command(name, args)
	local player = core.get_player_by_name(name)
	if not player then
		return false, S("Only players can take the tour.")
	end
	local sub = args:match("^(%S*)")
	if sub == "stop" then
		return tour.stop(player)
	elseif sub == "next" then
		return tour.skip(player, 1)
	elseif sub == "prev" then
		return tour.skip(player, -1)
	elseif sub == "pause" then
		return tour.pause(player)
	elseif sub == "resume" then
		return tour.resume(player)
	end
	return tour.start(player, args)
end
