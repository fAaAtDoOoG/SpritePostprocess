local sprite = app.open(app.params["input"])
if not sprite then error("Cannot reopen generated Aseprite") end
if #sprite.layers ~= 1 or sprite.colorMode ~= ColorMode.RGB then
  error("Expected one RGBA layer in generated delivery")
end
for index = 1, #sprite.frames do
  local cel = sprite.layers[1]:cel(index)
  if not cel or cel.position.x ~= 0 or cel.position.y ~= 0 or
      cel.image.width ~= sprite.width or cel.image.height ~= sprite.height then
    error("Frame " .. index .. " does not have an origin-zero full-canvas cel")
  end
end
sprite:close()
