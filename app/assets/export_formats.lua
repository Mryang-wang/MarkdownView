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
