-- When a player first walks into a placed landmark that has lore, show it briefly (setting sagas_lore).
if not sagas.util.settings.lore then
	return
end

local INTERVAL = 2
local timer = 0

local function seen_set(player)
	local raw = player:get_meta():get_string("sagas:seen")
	return raw ~= "" and core.deserialize(raw) or {}
end

core.register_globalstep(function(dtime)
	timer = timer + dtime
	if timer < INTERVAL then
		return
	end
	timer = 0
	for _, player in ipairs(core.get_connected_players()) do
		local recs = sagas.records.at(vector.round(player:get_pos()))
		for _, rec in ipairs(recs) do
			local def = sagas.registered_landmarks[rec.id]
			if def and def.lore and def.lore ~= "" then
				local seen = seen_set(player)
				if not seen[rec.id] then
					seen[rec.id] = true
					player:get_meta():set_string("sagas:seen", core.serialize(seen))
					local text = (def.title and def.title ~= "" and def.title .. "\n" or "") .. def.lore
					local hud = player:hud_add({
						type = "text",
						position = { x = 0.5, y = 0.2 },
						text = text,
						number = 0xFFE9B0,
						alignment = { x = 0, y = 0 },
						size = { x = 1, y = 0 },
					})
					local pname = player:get_player_name()
					core.after(8, function()
						local p = core.get_player_by_name(pname)
						if p then
							p:hud_remove(hud)
						end
					end)
				end
			end
		end
	end
end)
