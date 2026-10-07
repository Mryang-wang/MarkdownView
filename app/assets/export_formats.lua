-- Preserve editable underline and exact highlight colors in DOCX.
function Inlines(inlines)
  local result, stack = pandoc.List(), {}
  local function append(inline)
    local target = #stack > 0 and stack[#stack].content or result
    target:insert(inline)
  end
  for _, inline in ipairs(inlines) do
    local raw = inline.t == 'RawInline' and inline.format == 'html' and inline.text:lower() or ''
    local opening = raw:match('^<%s*(%a+)[%s>]')
    local closing = raw:match('^</%s*(%a+)%s*>$')
    if opening == 'u' or opening == 'mark' then
      local color = raw:match('background%-color%s*:%s*#(%x+)') or 'ffe58f'
      local text = raw:match('[;%s]color%s*:%s*#(%x+)') or '272724'
      if #color ~= 6 then color = 'ffe58f' end
      if #text ~= 6 then text = '272724' end
      local line = raw:match('text%-decoration%-style%s*:%s*(%a+)') or 'solid'
      if not ({solid=true, double=true, wavy=true, dashed=true, dotted=true})[line] then line = 'solid' end
      stack[#stack + 1] = { tag = opening, original = inline, content = pandoc.List(),
                           color = color:upper(), text = text:upper(), line = line }
    elseif #stack > 0 and closing == stack[#stack].tag then
      local entry = table.remove(stack)
      local name = closing == 'u' and ('MDViewUnderline_' .. entry.line)
                   or ('MDViewHighlight_' .. entry.color .. '_' .. entry.text)
      -- Word 每段文字只能指定一个字符样式，合并叠加格式并保留最内层选择。
      local content = pandoc.Span(entry.content):walk({ Span = function(span)
        local style = span.attributes['custom-style'] or ''
        if closing == 'u' and style:match('^MDViewHighlight_%x+_%x+$') then
          span.attributes['custom-style'] = style .. '_U_' .. entry.line
        elseif closing == 'mark' and style:match('^MDViewUnderline_') then
          span.attributes['custom-style'] = name .. '_U_' .. style:match('^MDViewUnderline_(%a+)$')
        end
        return span
      end })
      append(pandoc.Span(content.content, pandoc.Attr('', {}, { ['custom-style'] = name })))
    else
      append(inline)
    end
  end
  -- Leave incomplete tags unchanged while the user is still editing them.
  while #stack > 0 do
    local entry = table.remove(stack)
    append(entry.original)
    for _, inline in ipairs(entry.content) do append(inline) end
  end
  return result
end

-- Resolve nested text formatting into one Word character style. Keep an explicit
-- span foreground separate from the automatic contrast color on a highlight.
-- Pandoc parses <span style="..."> as native Span nodes.
local function css_property(style, property)
  local found
  for declaration in style:gmatch('[^;]+') do
    local key, value = declaration:match('^%s*([%w%-]+)%s*:%s*(.-)%s*$')
    if key and key:lower() == property then found = value end
  end
  return found
end

local function font_name(style)
  local value = css_property(style, 'font-family')
  if not value then return nil end
  value = value:match('^%s*(.-)%s*$')
  value = value:match('^"([^"]+)"') or value:match("^'([^']+)'") or value:match('^([^,]+)')
  return value and value:gsub('\\(%x+)%s?', function(hex) return utf8.char(tonumber(hex, 16)) end)
end

local function font_size(style)
  local value = css_property(style, 'font-size') or ''
  local number, unit = value:lower():match('^([%d%.]+)%s*(%a+)$')
  number = tonumber(number)
  if not number or (unit ~= 'pt' and unit ~= 'px') then return nil end
  if unit == 'px' then number = number * 0.75 end
  -- Word uses half points; CSS pixels can fall between two supported values.
  local half_points = math.floor(number * 2 + 0.5)
  return half_points >= 1 and half_points <= 3276 and half_points or nil
end

local function text_color(style)
  local value = (css_property(style, 'color') or ''):lower()
  if value:match('^var%(%s*%-%-mdv%-text%-color%s*%)$') then return 'AUTO' end
  local color = value:match('^#(%x%x%x%x%x%x)$')
  if not color then
    color = value:match('^#(%x%x%x)$')
    if color then color = color:gsub('.', '%0%0') end
  end
  return color and color:upper() or nil
end

local function format_inlines(inlines, inherited)
  local result = pandoc.List()
  local function append(value)
    local previous = result[#result]
    if previous and previous.t == 'Span' and value.t == 'Span' and value.attributes['custom-style']
        and previous.attributes['custom-style'] == value.attributes['custom-style'] then
      previous.content:extend(value.content); result[#result] = previous
    else result:insert(value) end
  end
  for _, inline in ipairs(inlines) do
    local active = {}
    for key, value in pairs(inherited) do active[key] = value end
    if inline.t == 'Span' then
      local name = inline.attributes['custom-style'] or ''
      local color, text, line = name:match('^MDViewHighlight_(%x+)_(%x+)_U_(%a+)$')
      if not color then color, text = name:match('^MDViewHighlight_(%x+)_(%x+)$') end
      line = line or name:match('^MDViewUnderline_(%a+)$')
      if color then active.color, active.text = color, text end
      if line then active.line = line end
      local style = inline.attributes.style or ''
      active.font = font_name(style) or active.font
      active.size = font_size(style) or active.size
      active.foreground = text_color(style) or active.foreground
      inline.content = format_inlines(inline.content, active)
      if name:match('^MDViewHighlight_') or name:match('^MDViewUnderline_') then
        inline.attributes['custom-style'] = nil
      end
      append(inline)
    elseif inline.content and inline.t ~= 'Note' then
      inline.content = format_inlines(inline.content, active); append(inline)
    else
      local name = ''
      if active.font then
        local encoded = active.font:gsub('.', function(byte) return string.format('%02X', string.byte(byte)) end)
        name = 'MDViewFont_' .. encoded
        if active.color then name = name .. '_H_' .. active.color .. '_' .. active.text end
      elseif active.color then name = 'MDViewHighlight_' .. active.color .. '_' .. active.text end
      if active.line then name = name ~= '' and (name .. '_U_' .. active.line) or ('MDViewUnderline_' .. active.line) end
      if active.size or active.foreground then
        if name == '' then name = 'MDViewText' end
        if active.size then name = name .. '_S_' .. tostring(active.size) end
        if active.foreground then name = name .. '_C_' .. active.foreground end
      end
      append(name ~= '' and pandoc.Span({inline}, pandoc.Attr('', {}, {['custom-style'] = name})) or inline)
    end
  end
  return result
end

local function format_block(block)
  block.content = format_inlines(block.content, {})
  return block
end

return {{Inlines = Inlines}, {Para = format_block, Plain = format_block, Header = format_block}}
