-- Nodes that appear in saga schematics: one placeholder per material class, the palette colour
-- node and a still (non-flowing) water. Placeholders are replaced by game nodes when a saga is
-- placed; they only stay visible if a game lacks every candidate for a class.
local S = sagas.S
local has_default = core.get_modpath("default") ~= nil
local has_mcl_sounds = core.get_modpath("mcl_sounds") ~= nil

local function stone_sounds()
	if has_default and default.node_sound_stone_defaults then
		return default.node_sound_stone_defaults()
	elseif has_mcl_sounds and mcl_sounds.node_sound_stone_defaults then
		return mcl_sounds.node_sound_stone_defaults()
	end
end

local common_groups = { cracky = 3, pickaxey = 1, building_block = 1, not_in_creative_inventory = 1 }

for _, name in ipairs(sagas.vocab.class_names) do
	local class = sagas.vocab.classes[name]
	local groups = table.copy(common_groups)
	groups.sagas_placeholder = 1
	core.register_node("sagas:m_" .. name, {
		description = S("Saga placeholder (@1)", name),
		tiles = { { name = "sagas_placeholder.png", color = class.rgb } },
		groups = groups,
		is_ground_content = false,
		drop = "",
		sounds = stone_sounds(),
		_mcl_hardness = 1.5,
		_mcl_blast_resistance = 6,
	})
end

core.register_node("sagas:color", {
	description = S("Saga stone"),
	tiles = { "sagas_white.png" },
	paramtype2 = "color",
	palette = "sagas_palette.png",
	groups = table.copy(common_groups),
	is_ground_content = false,
	sounds = stone_sounds(),
	_mcl_hardness = 1.5,
	_mcl_blast_resistance = 6,
})

core.register_node("sagas:water", {
	description = S("Still water"),
	drawtype = "liquid",
	tiles = { "sagas_water.png" },
	use_texture_alpha = "blend",
	paramtype = "light",
	walkable = false,
	pointable = false,
	diggable = false,
	buildable_to = true,
	is_ground_content = false,
	drop = "",
	drowning = 1,
	liquidtype = "source",
	liquid_alternative_source = "sagas:water", -- standalone source: never flows (liquid_range = 0)
	liquid_range = 0,
	liquid_renewable = false,
	liquid_viscosity = 1,
	post_effect_color = { a = 103, r = 30, g = 60, b = 90 },
	groups = { water = 3, liquid = 3, not_in_creative_inventory = 1 },
})
