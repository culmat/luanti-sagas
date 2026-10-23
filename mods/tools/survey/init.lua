-- Bridge between sagas and `avanti survey` (avanti-luanti's headless map generation survey).
-- Development only: inert unless the avanti_survey helper mod is loaded, and not part of releases
-- (mods/.gitattributes export-ignores tools/). Run it with
--   avanti survey mods --game minetest --set sagas_survey=true
-- (sagas_survey makes the engine also test every landmark's site in every chunk; see /saga stats).
local survey = rawget(_G, "avanti_survey")
if not survey then
	return
end

local engine = sagas.engine
local records = sagas.records

-- Landmark schematics are reported below as landmarks, not again as plain schematics.
if survey.ignore then
	survey.ignore("sagas[%w_]*/schematics/")
	survey.ignore("/sagas/test/fixtures/")
end

-- Copies of a landmark closer than this feel repetitive. Until landmarks declare how often players
-- should meet them, bigger builds get a bigger target.
local function spacing_target(def)
	if def.encounter_spacing then
		return def.encounter_spacing
	end
	local nodes = def.nodes or (def.size.x * def.size.y * def.size.z / 4)
	if nodes >= 2000 then
		return 2000
	elseif nodes >= 500 then
		return 1000
	end
	return nil
end

local function has_class(def, class)
	for _, c in ipairs(def.classes or {}) do
		if c == class then
			return true
		end
	end
	return false
end

local function light_nodes()
	local out = {}
	for name, def in pairs(core.registered_nodes) do
		if (def.light_source or 0) > 0 and name:sub(1, 6) ~= "sagas:" then
			out[#out + 1] = name
		end
	end
	return out
end

local function large_states()
	local out = {}
	for k, v in pairs(records.storage:to_table().fields) do
		local id = k:match("^L:(.+):%-?%d+:%-?%d+$")
		local rec = id and core.parse_json(v)
		if type(rec) == "table" then
			out[id] = out[id] or { placed = 0, rejected = 0, pending = 0, reasons = {} }
			local s = out[id]
			s[rec.state] = (s[rec.state] or 0) + 1
			if rec.reason and #s.reasons < 5 then
				s.reasons[#s.reasons + 1] = rec.reason
			end
		end
	end
	return out
end

sagas.register_on_placed(function(id, anchor, box, rot)
	local rec = records.at(anchor)[1]
	survey.report("landmark", id, anchor, {
		rot = rot,
		site = rec and rec.site,
		size = vector.subtract(box.max, box.min),
	})
end)

survey.register_on_finish(function(ctx)
	local km2 = ctx.surface_km2
	if engine.mode ~= "sampler" then
		survey.finding(
			"warn",
			"SV010",
			"automatic placement is off in this world (singlenode, Mineclonia levelgen or sagas_disable_mapgen)"
		)
	end
	local spread = records.spread()
	-- With sagas_only or a lowered rarity scale the survey shows where a landmark fits, not how often
	-- players would meet it: repeat findings would be noise.
	local boosted = engine.only ~= nil or engine.scale < 1
	if boosted then
		survey.finding(
			"info",
			"SV011",
			"placement boosted for testing (sagas_only or sagas_rarity_scale below 1): repeat findings (SV001) skipped"
		)
	end
	local lit_count, lights = 0, nil
	for _, def in ipairs(sagas.landmark_list) do
		if def.enabled then
			local sp = spread[def.id] or { count = 0 }
			local target = spacing_target(def)
			if target and sp.nn_mean and sp.nn_mean < target and not boosted then
				survey.finding(
					"warn",
					"SV001",
					("%s repeats too often: copies %d m apart on average (closest %d m); aim for %d m or more"):format(
						def.id,
						sp.nn_mean,
						sp.nn_min,
						target
					)
				)
			end
			local pr = engine.probe[def.id]
			local sampled = pr ~= nil and not def.biome_filter
			if pr and def.biome_filter then
				for name in pairs(pr.biomes) do
					local bid = core.get_biome_id(name)
					if bid and def.biome_filter[bid] then
						sampled = true
					end
				end
				if not sampled then
					survey.finding(
						"info",
						"SV003",
						("%s: none of its biomes (%s) were in the surveyed area"):format(
							def.id,
							table.concat(def.biomes, ", ")
						)
					)
				end
			end
			if sampled and pr.chunks >= 20 and pr.fit / pr.chunks < 0.01 then
				local worst, n = "?", -1
				for _, r in ipairs(engine.REASONS) do
					if pr[r] > n then
						worst, n = r, pr[r]
					end
				end
				survey.finding(
					"warn",
					"SV002",
					("%s almost never fits: %d of %d surface chunks; most tries fail on %s"):format(
						def.id,
						pr.fit,
						pr.chunks,
						worst
					)
				)
			end
			-- Rolls in chunks without terrain surface cannot succeed for surface sites; leave them out.
			local st = engine.stats[def.id]
			local rolls = st and (engine.needs_surface(def) and st.surface_rolls or st.rolls) or 0
			if rolls >= 5 and st.placed / rolls < 0.1 then
				survey.finding(
					"info",
					"SV004",
					(
						"%s: only %d of %d rolls in surface chunks found a fitting site, so it is about %dx rarer "
						.. "than rarity %d suggests"
					):format(def.id, st.placed, rolls, math.floor(rolls / math.max(1, st.placed)), def.rarity)
				)
			end
			if has_class(def, "lamp") then
				lit_count = lit_count + sp.count
				lights = lights or light_nodes()
				for _, rec in ipairs(records.all(def.id)) do
					core.load_area(rec.p1, rec.p2)
					if #core.find_nodes_in_area(rec.p1, rec.p2, lights) == 0 then
						survey.finding(
							"warn",
							"SV006",
							("%s at %s has the lamp class but no light-emitting node"):format(
								def.id,
								core.pos_to_string(rec.anchor)
							)
						)
						break
					end
				end
			end
		end
	end
	if km2 > 0 and lit_count / km2 > 0.5 then
		survey.finding(
			"warn",
			"SV005",
			("%.2f lit landmarks per km2: night is not dark any more (aim for 0.5 or fewer)"):format(lit_count / km2)
		)
	end
	local probe = {}
	for id, c in pairs(engine.probe) do
		probe[id] = {
			chunks = c.chunks,
			fit = c.fit,
			tries = c.tries,
			biome = c.biome,
			site = c.site,
			box = c.box,
			spacing = c.spacing,
			best_biomes = sagas.explore.best_biomes(c, 5),
		}
	end
	return {
		visit = "/saga placed lists the landmarks, /saga tp 1 goes to the nearest, /saga tour flies around them all",
		mode = engine.mode,
		rarity_scale = engine.scale,
		lit_landmarks = lit_count,
		stats = engine.stats,
		probe = probe,
		large = large_states(),
		report = sagas.explore.report(),
	}
end)
