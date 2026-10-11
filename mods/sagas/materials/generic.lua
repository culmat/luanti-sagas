-- Fallback candidates for games without a material table: mapgen aliases every game defines,
-- then nodes found by name pattern. Returns candidate lists usable by materials' pick().
local generic = {}

local ALIASES = {
	rock = { "mapgen_stone" },
	stone = { "mapgen_stone" },
	cobble = { "mapgen_cobble", "mapgen_stone" },
	moss = { "mapgen_mossycobble", "mapgen_cobble" },
	sandstone = { "mapgen_sandstone", "mapgen_desert_stone" },
	dirt = { "mapgen_dirt" },
	grass = { "mapgen_dirt_with_grass", "mapgen_dirt" },
	log = { "mapgen_tree", "mapgen_jungletree", "mapgen_pine_tree" },
	leaves = { "mapgen_leaves", "mapgen_jungleleaves", "mapgen_pine_needles" },
	snow = { "mapgen_snowblock" },
	ice = { "mapgen_ice" },
	gravel = { "mapgen_gravel" },
}

local PATTERNS = {
	stone = { ":stonebrick$", ":stone_brick$", ":stone_bricks$" },
	stone_dark = { ":obsidianbrick$", ":obsidian_brick$", ":deepslate_bricks$" },
	brick = { ":brick$", ":brick_block$", ":bricks$" },
	marble = { ":marble$", ":stone_block$" },
	wood = { ":wood$", ":planks$", ":wood_oak$" },
	planks = { ":wood$", ":planks$" },
	roof_red = { ":brick$", ":bricks$" },
	roof_dark = { ":junglewood$", ":darkwood$" },
	thatch = { ":straw$", ":hay_block$", ":thatch$" },
	metal = { ":steelblock$", ":ironblock$", ":steel_block$" },
	gold = { ":goldblock$", ":gold_block$" },
	glass = { ":glass$" },
	lamp = { ":meselamp$", ":sea_lantern$", ":lamp$" },
	bone = { ":bone_block$", ":bones$" },
}

function generic.candidates(class)
	local out = {}
	for _, alias in ipairs(ALIASES[class] or {}) do
		if core.registered_aliases[alias] then
			out[#out + 1] = core.registered_aliases[alias]
		end
	end
	for _, pat in ipairs(PATTERNS[class] or {}) do
		local names = {}
		for name in pairs(core.registered_nodes) do
			if name:find(pat) and not name:find("^sagas:") then
				names[#names + 1] = name
			end
		end
		table.sort(names)
		for _, n in ipairs(names) do
			out[#out + 1] = n
		end
	end
	return out
end

return generic
