-- Small helpers shared by all files: settings, hashing, rotation math, logging.
local util = {}
sagas.util = util

local settings = core.settings
util.settings = {
	rarity_scale = math.max(0.001, tonumber(settings:get("sagas_rarity_scale")) or 1.0),
	disabled = {},
	max_per_chunk = math.max(1, math.min(4, tonumber(settings:get("sagas_max_per_chunk")) or 1)),
	large_enable = settings:get_bool("sagas_large_enable", true),
	lore = settings:get_bool("sagas_lore", true),
	real_water = settings:get_bool("sagas_real_water", false),
	disable_mapgen = settings:get_bool("sagas_disable_mapgen", false),
	debug = settings:get_bool("sagas_debug", false),
}
for item in (settings:get("sagas_disabled") or ""):gmatch("[^,%s]+") do
	util.settings.disabled[item] = true
end

function util.log(level, msg, ...)
	if select("#", ...) > 0 then
		msg = msg:format(...)
	end
	core.log(level, "[sagas] " .. msg)
end

function util.debug(msg, ...)
	if util.settings.debug then
		util.log("action", msg, ...)
	end
end

-- 32-bit hash of the arguments (deterministic across servers and runs).
function util.hash32(...)
	local parts = {}
	for i = 1, select("#", ...) do
		parts[i] = tostring((select(i, ...)))
	end
	return tonumber(core.sha1(table.concat(parts, "\0")):sub(1, 8), 16)
end

-- Size of the box a schematic occupies after rotation by rot degrees (0, 90, 180, 270).
function util.rotated_size(size, rot)
	if rot == 90 or rot == 270 then
		return { x = size.z, y = size.y, z = size.x }
	end
	return { x = size.x, y = size.y, z = size.z }
end

-- Where the local schematic position p ends up inside the placed box, matching the engine's
-- Schematic::blitToVManip rotation (checked by the rotation test in test/mtt.lua).
function util.rotate_local(p, size, rot)
	if rot == 90 then
		return { x = p.z, y = p.y, z = size.x - 1 - p.x }
	elseif rot == 180 then
		return { x = size.x - 1 - p.x, y = p.y, z = size.z - 1 - p.z }
	elseif rot == 270 then
		return { x = size.z - 1 - p.z, y = p.y, z = p.x }
	end
	return { x = p.x, y = p.y, z = p.z }
end

-- Min/max corners of saga def placed with its anchor at world position anchor.
function util.bbox(def, anchor, rot)
	local rs = util.rotated_size(def.size, rot)
	local ra = util.rotate_local(def.anchor, def.size, rot)
	local p1 = { x = anchor.x - ra.x, y = anchor.y - ra.y, z = anchor.z - ra.z }
	local p2 = { x = p1.x + rs.x - 1, y = p1.y + rs.y - 1, z = p1.z + rs.z - 1 }
	return p1, p2
end

function util.set(list)
	local s = {}
	for _, v in ipairs(list or {}) do
		s[v] = true
	end
	return s
end

function util.read_file(path)
	local f = io.open(path, "rb")
	if not f then
		return nil
	end
	local data = f:read("*a")
	f:close()
	return data
end

function util.pos_key(p)
	return ("%d,%d,%d"):format(p.x, p.y, p.z)
end
