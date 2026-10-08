-- Run only on generated output files, never an input asset in place.
local input = app.params["input"]
local output = app.params["output"]
local w = tonumber(app.params["width"])
local h = tonumber(app.params["height"])
local durations = {}
for value in string.gmatch(app.params["durations"] or "", "[^,]+") do
  table.insert(durations, tonumber(value))
end
if not input or not output or not w or not h or #durations == 0 then
  error("Missing import parameters")
end
local sheet = app.open(input)
if not sheet or sheet.width ~= w * #durations or sheet.height ~= h then
  error("Unexpected sprite sheet dimensions")
end
local source = Image(sheet.spec)
source:drawSprite(sheet, 1)
local sprite = Sprite(w, h, ColorMode.RGB)
sprite.layers[1].name = "RGBA"
for i = 1, #durations do
  if i > 1 then sprite:newEmptyFrame() end
  local old = sprite.layers[1]:cel(i)
  if old then sprite:deleteCel(old) end
  local image = Image(w, h, ColorMode.RGB)
  image:drawImage(source, Point(-(i - 1) * w, 0))
  sprite:newCel(sprite.layers[1], i, image, Point(0, 0))
  sprite.frames[i].duration = durations[i] / 1000
end
local tag = sprite:newTag(1, #durations)
tag.name = app.params["name"] or "animation"
tag.aniDir = AniDir.FORWARD
sprite.gridBounds = Rectangle(0, 0, w, h)
sprite:saveAs(output)
sprite:close()
sheet:close()
