-- Sagas: landmarks from real 3D models, placed by terrain and biome hints.
-- The mod owns material mapping and placement; content packs (sagas_<saga>) only register landmark schematics.
local modname = core.get_current_modname()
local modpath = core.get_modpath(modname)

sagas = {
	modpath = modpath,
	S = core.get_translator(modname),
	registered_landmarks = {}, -- id -> definition
	landmark_list = {}, -- definitions in registration order
	registered_on_placed = {},
}

for _, file in ipairs({
	"util",
	"vocab",
	"nodes",
	"storage",
	"materials/init",
	"biomes",
	"sites",
	"placement",
	"api",
	"engine",
	"large",
	"commands",
	"tour",
	"explore",
	"lore",
}) do
	dofile(modpath .. "/" .. file .. ".lua")
end

if core.get_modpath("mtt") and mtt.enabled then
	dofile(modpath .. "/test/mtt.lua")
end
