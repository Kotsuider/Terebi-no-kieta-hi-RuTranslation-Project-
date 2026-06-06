#!/usr/bin/env ruby
# encoding: utf-8
# asb_xlsx.rb — экспорт/импорт ASB файлов через Excel таблицу
#
# Использование:
#   ruby asb_xlsx.rb export <папка_asb> <output.xlsx>
#   ruby asb_xlsx.rb import <папка_asb> <input.xlsx>  <папка_вывода>
#
# Зависимости: только стандартная библиотека Ruby (zlib, csv)

require 'zlib'

SRC_ENC = 'Shift_JIS'
DST_ENC = 'Windows-1251'

# ── Парсер ASB ──────────────────────────────────────────────────────────────

def find_strings(data)
  strings = []
  i = 4
  while i < data.size - 4

    # Тип 1: нарратив — 07 00 LL 07 [текст] 00
    if data.getbyte(i-3) == 0x07 && data.getbyte(i-2) == 0x00 && data.getbyte(i) == 0x07
      ll = data.getbyte(i-1)
      str_len = ll - 3
      if str_len > 0 && i + 1 + str_len < data.size && data.getbyte(i + 1 + str_len) == 0x00
        raw = data.byteslice(i+1, str_len)
        begin
          text = raw.force_encoding(SRC_ENC).encode('UTF-8', invalid: :replace, undef: :replace)
          strings << { pos: i+1, length: str_len, ll_pos: i-1, raw: raw, text: text, speaker: '' }
        rescue
          nil
        end
        i += 1
        next
      end
    end

    # Тип 2: диалог — 07 07 [имя] 00 LL 07 [текст] 00
    # Также обрабатываем вариант 07 07 07 [имя] 00 (пропускаем лишний 07)
    if data.getbyte(i) == 0x07 && i + 2 < data.size && data.getbyte(i+1) == 0x07
      name_start = i + 2
      name_start += 1 if data.getbyte(name_start) == 0x07
      null_pos = data.index("\x00".b, name_start)
      if null_pos && null_pos > name_start && null_pos - name_start < 32
        ll_pos  = null_pos + 1
        ll      = data.getbyte(ll_pos)
        if ll && ll >= 3 && ll_pos + 1 < data.size && data.getbyte(ll_pos + 1) == 0x07
          str_len    = ll - 3
          text_start = ll_pos + 2
          if str_len > 0 && text_start + str_len < data.size && data.getbyte(text_start + str_len) == 0x00
            name_raw = data.byteslice(name_start, null_pos - name_start)
            speaker  = name_raw.force_encoding(SRC_ENC).encode('UTF-8', invalid: :replace, undef: :replace) rescue ''
            raw = data.byteslice(text_start, str_len)
            begin
              text = raw.force_encoding(SRC_ENC).encode('UTF-8', invalid: :replace, undef: :replace)
              strings << { pos: text_start, length: str_len, ll_pos: ll_pos, raw: raw, text: text, speaker: speaker, name_pos: name_start, name_len: null_pos - name_start }
            rescue
              nil
            end
            i = text_start + str_len + 1
            next
          end
        end
      end
    end

    # Тип 3: диалог с опкод-байтом — [opcode] 07 [имя] 00 LL 07 [текст] 00
    # opcode — одиночный байт < 0x20, не 0x07 и не 0x00
    if data.getbyte(i) != 0x07 && data.getbyte(i) != 0x00 &&
       data.getbyte(i) < 0x20 && i + 1 < data.size && data.getbyte(i+1) == 0x07
      name_start = i + 2
      null_pos = data.index("\x00".b, name_start)
      if null_pos && null_pos > name_start && null_pos - name_start < 20
        ll_pos = null_pos + 1
        ll     = data.getbyte(ll_pos)
        if ll && ll >= 3 && ll_pos + 1 < data.size && data.getbyte(ll_pos + 1) == 0x07
          str_len    = ll - 3
          text_start = ll_pos + 2
          if str_len > 0 && text_start + str_len < data.size && data.getbyte(text_start + str_len) == 0x00
            name_raw = data.byteslice(name_start, null_pos - name_start)
            speaker  = name_raw.force_encoding(SRC_ENC).encode('UTF-8', invalid: :replace, undef: :replace) rescue ''
            raw = data.byteslice(text_start, str_len)
            begin
              text = raw.force_encoding(SRC_ENC).encode('UTF-8', invalid: :replace, undef: :replace)
              strings << { pos: text_start, length: str_len, ll_pos: ll_pos, raw: raw, text: text,
                           speaker: speaker, name_pos: name_start, name_len: null_pos - name_start }
            rescue
              nil
            end
            i = text_start + str_len + 1
            next
          end
        end
      end
    end

    i += 1
  end
  strings
end

# ── XML helpers для XLSX ─────────────────────────────────────────────────────

def xml_esc(s)
  s = s.to_s.gsub(/[^\u0009\u000A\u000D\u0020-\uD7FF\uE000-\uFFFD]/, '')
  s.gsub('&','&amp;').gsub('<','&lt;').gsub('>','&gt;').gsub('"','&quot;').gsub("'",'&apos;')
end

# Индекс строки в таблице разделяемых строк
$shared_strings = []
$ss_index = {}

def ss(str)
  str = str.to_s
  unless $ss_index.key?(str)
    $ss_index[str] = $shared_strings.size
    $shared_strings << str
  end
  $ss_index[str]
end

def cell_ref(col, row)
  col_letter = ('A'.ord + col).chr
  "#{col_letter}#{row}"
end

def build_shared_strings_xml
  items = $shared_strings.map { |s| "<si><t xml:space=\"preserve\">#{xml_esc(s)}</t></si>" }.join
  <<~XML
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
         count="#{$shared_strings.size}" uniqueCount="#{$shared_strings.size}">
    #{items}
    </sst>
  XML
end

def build_sheet_xml(rows, col_widths, last_data_row)
  # rows = array of arrays of [type, value] where type:
  #   :s  — shared string
  #   :n  — number
  #   :h  — header (shared string, особый стиль)
  #   :f  — formula (inline, строка формулы Excel)
  cols_xml = col_widths.each_with_index.map { |w, i|
    "<col min=\"#{i+1}\" max=\"#{i+1}\" width=\"#{w}\" customWidth=\"1\"/>"
  }.join

  rows_xml = rows.each_with_index.map { |row, ri|
    cells = row.each_with_index.map { |cell, ci|
      ref = cell_ref(ci, ri+1)
      type, val = cell
      case type
      when :s
        "<c r=\"#{ref}\" t=\"s\" s=\"#{ci < 4 ? 1 : 0}\"><v>#{val}</v></c>"
      when :n
        "<c r=\"#{ref}\" s=\"2\"><v>#{val}</v></c>"
      when :h
        "<c r=\"#{ref}\" t=\"s\" s=\"3\"><v>#{val}</v></c>"
      when :f
        # Формула; стиль 8 — центр без заливки (CF перекроет цвет)
        "<c r=\"#{ref}\" s=\"8\"><f>#{xml_esc(val)}</f></c>"
      end
    }.join
    "<row r=\"#{ri+1}\">#{cells}</row>"
  }.join

  # Условное форматирование для колонок F (TL, индекс 4) и H (TLE, индекс 6)
  # Статус TL — колонка G (индекс 6), статус TLE — колонка I (индекс 8)
  # Формулы смотрят на E (TL) и G (TLE), сравнивают с F (MaxБайт)
  #
  # Порядок правил важен: Excel применяет первое совпавшее.
  # priority: меньше = выше приоритет.

  cf_tl = if last_data_row >= 2
    ref = "G2:G#{last_data_row}"
    <<~CF
      <conditionalFormatting sqref="#{ref}">
        <cfRule type="expression" priority="1" dxfId="0">
          <formula>AND(E2&lt;&gt;"",LEN(E2)&gt;F2)</formula>
        </cfRule>
        <cfRule type="expression" priority="2" dxfId="1">
          <formula>AND(E2&lt;&gt;"",LEN(E2)&gt;F2-6,LEN(E2)&lt;=F2)</formula>
        </cfRule>
        <cfRule type="expression" priority="3" dxfId="2">
          <formula>AND(E2&lt;&gt;"",LEN(E2)&lt;=F2-6)</formula>
        </cfRule>
        <cfRule type="expression" priority="4" dxfId="3">
          <formula>E2=""</formula>
        </cfRule>
      </conditionalFormatting>
    CF
  else
    ''
  end

  cf_tle = if last_data_row >= 2
    ref = "I2:I#{last_data_row}"
    <<~CF
      <conditionalFormatting sqref="#{ref}">
        <cfRule type="expression" priority="5" dxfId="0">
          <formula>AND(G2&lt;&gt;"",LEN(G2)&gt;F2)</formula>
        </cfRule>
        <cfRule type="expression" priority="6" dxfId="1">
          <formula>AND(G2&lt;&gt;"",LEN(G2)&gt;F2-6,LEN(G2)&lt;=F2)</formula>
        </cfRule>
        <cfRule type="expression" priority="7" dxfId="2">
          <formula>AND(G2&lt;&gt;"",LEN(G2)&lt;=F2-6)</formula>
        </cfRule>
        <cfRule type="expression" priority="8" dxfId="3">
          <formula>G2=""</formula>
        </cfRule>
      </conditionalFormatting>
    CF
  else
    ''
  end

  <<~XML
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
               xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <sheetFormatPr defaultRowHeight="15"/>
    <cols>#{cols_xml}</cols>
    <sheetData>#{rows_xml}</sheetData>
    <autoFilter ref="A1:I#{last_data_row}"/>
    <sheetView workbookViewId="0"><selection activeCell="E2" sqref="E2"/></sheetView>
    #{cf_tl}
    #{cf_tle}
    </worksheet>
  XML
end

def build_styles_xml
  <<~XML
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
    <fonts count="3">
      <font><sz val="10"/><name val="Arial"/></font>
      <font><sz val="10"/><name val="Arial"/><b/></font>
      <font><sz val="10"/><name val="Arial"/><b/><color rgb="FF721C24"/></font>
    </fonts>
    <fills count="7">
      <fill><patternFill patternType="none"/></fill>
      <fill><patternFill patternType="gray125"/></fill>
      <fill><patternFill patternType="solid"><fgColor rgb="FFD9EAD3"/></patternFill></fill>
      <fill><patternFill patternType="solid"><fgColor rgb="FFD4EDDA"/></patternFill></fill>
      <fill><patternFill patternType="solid"><fgColor rgb="FFFFF3CD"/></patternFill></fill>
      <fill><patternFill patternType="solid"><fgColor rgb="FFF8D7DA"/></patternFill></fill>
      <fill><patternFill patternType="solid"><fgColor rgb="FFEEEEEE"/></patternFill></fill>
    </fills>
    <borders count="2">
      <border><left/><right/><top/><bottom/><diagonal/></border>
      <border>
        <left style="thin"><color auto="1"/></left>
        <right style="thin"><color auto="1"/></right>
        <top style="thin"><color auto="1"/></top>
        <bottom style="thin"><color auto="1"/></bottom>
      </border>
    </borders>
    <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
    <cellXfs count="9">
      <!-- 0: обычный с переносом -->
      <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1">
        <alignment wrapText="1" vertical="top"/>
      </xf>
      <!-- 1: обычный с переносом (дубль для совместимости) -->
      <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1">
        <alignment wrapText="1" vertical="top"/>
      </xf>
      <!-- 2: число по центру -->
      <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1">
        <alignment horizontal="center" vertical="top"/>
      </xf>
      <!-- 3: заголовок (зелёный фон, жирный, центр) -->
      <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">
        <alignment horizontal="center" wrapText="1"/>
      </xf>
      <!-- 4: статус OK — зелёный -->
      <xf numFmtId="0" fontId="0" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">
        <alignment horizontal="center" vertical="top"/>
      </xf>
      <!-- 5: статус WARN — жёлтый -->
      <xf numFmtId="0" fontId="0" fillId="4" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">
        <alignment horizontal="center" vertical="top"/>
      </xf>
      <!-- 6: статус OVER — красный, жирный -->
      <xf numFmtId="0" fontId="2" fillId="5" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">
        <alignment horizontal="center" vertical="top"/>
      </xf>
      <!-- 7: статус EMPTY — серый -->
      <xf numFmtId="0" fontId="0" fillId="6" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1">
        <alignment horizontal="center" vertical="top"/>
      </xf>
      <!-- 8: формула (inline string) по центру -->
      <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1">
        <alignment horizontal="center" vertical="top"/>
      </xf>
    </cellXfs>
    <!-- dxf: дифференциальные форматы для условного форматирования -->
    <!-- dxfId=0: OVER — красный фон, жирный красный текст -->
    <!-- dxfId=1: WARN — жёлтый фон -->
    <!-- dxfId=2: OK   — зелёный фон -->
    <!-- dxfId=3: EMPTY— серый фон, серый текст -->
    <dxfs count="4">
      <dxf>
        <font><b/><color rgb="FF721C24"/></font>
        <fill><patternFill><bgColor rgb="FFF8D7DA"/></patternFill></fill>
      </dxf>
      <dxf>
        <fill><patternFill><bgColor rgb="FFFFF3CD"/></patternFill></fill>
      </dxf>
      <dxf>
        <fill><patternFill><bgColor rgb="FFD4EDDA"/></patternFill></fill>
      </dxf>
      <dxf>
        <font><color rgb="FF999999"/></font>
        <fill><patternFill><bgColor rgb="FFEEEEEE"/></patternFill></fill>
      </dxf>
    </dxfs>
    </styleSheet>
  XML
end

# ── XLSX writer (нативный ZIP) ───────────────────────────────────────────────

def write_xlsx(path, sheets)
  # sheets = [{name:, rows:, col_widths:}]
  require 'tmpdir'
  
  files = {}
  
  # [Content_Types]
  sheet_types = sheets.each_with_index.map { |_, i|
    "<Override PartName=\"/xl/worksheets/sheet#{i+1}.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/>"
  }.join
  files['[Content_Types].xml'] = <<~XML
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
    <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
    <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
    #{sheet_types}
    </Types>
  XML

  # _rels/.rels
  files['_rels/.rels'] = <<~XML
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
    </Relationships>
  XML

  # xl/_rels/workbook.xml.rels
  wb_rels = sheets.each_with_index.map { |_, i|
    "<Relationship Id=\"rId#{i+1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet#{i+1}.xml\"/>"
  }.join
  wb_rels += "\n<Relationship Id=\"rId#{sheets.size+1}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings\" Target=\"sharedStrings.xml\"/>"
  wb_rels += "\n<Relationship Id=\"rId#{sheets.size+2}\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles\" Target=\"styles.xml\"/>"
  files['xl/_rels/workbook.xml.rels'] = <<~XML
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    #{wb_rels}
    </Relationships>
  XML

  # xl/workbook.xml
  sheet_els = sheets.each_with_index.map { |sh, i|
    "<sheet name=\"#{xml_esc(sh[:name])}\" sheetId=\"#{i+1}\" r:id=\"rId#{i+1}\"/>"
  }.join
  files['xl/workbook.xml'] = <<~XML
    <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
    <sheets>#{sheet_els}</sheets>
    </workbook>
  XML

  # xl/styles.xml
  files['xl/styles.xml'] = build_styles_xml

  # xl/worksheets/sheetN.xml
  sheets.each_with_index do |sh, i|
    last_data_row = sh[:rows].size  # строки 1..N, заголовок = строка 1
    files["xl/worksheets/sheet#{i+1}.xml"] = build_sheet_xml(sh[:rows], sh[:col_widths], last_data_row)
  end

  # xl/sharedStrings.xml (заполняется при build_sheet_xml вызовах)
  files['xl/sharedStrings.xml'] = build_shared_strings_xml

  # Пишем ZIP
  File.open(path, 'wb') do |f|
    f.write(zip_create(files))
  end
end

def zip_create(files)
  output = ''.b
  central_dir = ''.b
  offsets = {}

  files.each do |name, content|
    content = content.encode('UTF-8').b rescue content.b
    offsets[name] = output.size
    crc = Zlib.crc32(content)
    
    # Local file header
    lh = [0x04034b50, 20, 0, 0, 0, 0, crc, content.size, content.size, name.bytesize, 0].pack('VvvvvvVVVvv')
    output << lh << name.b << content
  end

  files.each do |name, content|
    content = content.encode('UTF-8').b rescue content.b
    crc = Zlib.crc32(content)
    # Central directory entry
    cd = [0x02014b50, 20, 20, 0, 0, 0, 0, crc, content.size, content.size, name.bytesize, 0, 0, 0, 0, 0, offsets[name]].pack('VvvvvvvVVVvvvvvVV')
    central_dir << cd << name.b
  end

  cd_offset = output.size
  output << central_dir
  # End of central directory
  eocd = [0x06054b50, 0, 0, files.size, files.size, central_dir.size, cd_offset, 0].pack('VvvvvVVv')
  output << eocd
  output
end

# ── XLSX reader ──────────────────────────────────────────────────────────────

def read_xlsx(path)
  require 'roo'
  
  xlsx = Roo::Spreadsheet.open(path)
  sheets = {}
  
  xlsx.sheets.each do |sheet_name|
    xlsx.sheet(sheet_name)
    rows = []
    (1..xlsx.last_row).each do |r|
      row = (1..xlsx.last_column).map { |c| xlsx.cell(r, c).to_s.strip }
      rows << row
    end
    sheets[sheet_name] = rows
  end
  
  sheets
end

# ── EXPORT ───────────────────────────────────────────────────────────────────

def cmd_export(asb_dir, output_xlsx)
  $shared_strings = []
  $ss_index = {}
  
  asb_files = Dir.glob(File.join(asb_dir, '*.asb')).sort
  if asb_files.empty?
    puts "[!] ASB файлы не найдены в #{asb_dir}"
    exit 1
  end

  sheets = asb_files.map do |asb_path|
    name = File.basename(asb_path, '.asb')
    data = File.binread(asb_path)
    strings = find_strings(data)

    puts "[+] #{File.basename(asb_path)}: #{strings.size} строк"

    # Заголовок: Персонаж | Имя TL | Имя Байты | Оригинал | TL | MaxБайт | TLE | St.TL | St.TLE
    headers = ['Персонаж', 'Имя TL', 'Имя Байты', 'Оригинал', 'TL', 'MaxБайт', 'TLE', 'St.TL', 'St.TLE']
    rows = [headers.map { |h| [:h, ss(h)] }]

    strings.each_with_index do |s, idx|
      xls_row = idx + 2  # строка в Excel (1 = заголовок)

      # Формула статуса TL (колонка G, смотрит на E=TL и F=MaxБайт):
      # Если E пустое → "-", иначе "LEN/MAX"
      formula_tl  = "IF(E#{xls_row}=\"\",\"-\",LEN(E#{xls_row})&\"/\"&F#{xls_row})"
      # Формула статуса TLE (колонка I, смотрит на G=TLE):
      formula_tle = "IF(G#{xls_row}=\"\",\"-\",LEN(G#{xls_row})&\"/\"&F#{xls_row})"

      row = [
        [:s, ss(s[:speaker] || '')],   # A Персонаж
        [:s, ss('')],                   # B Имя TL
        [:n, s[:name_len] || 0],        # C Имя Байты
        [:s, ss(s[:text])],             # D Оригинал
        [:s, ss('')],                   # E TL
        [:n, s[:length]],               # F MaxБайт
        [:s, ss('')],                   # G TLE
        [:f, formula_tl],               # H St.TL
        [:f, formula_tle],              # I St.TLE
      ]
      rows << row
    end

    { name: name[0, 31], rows: rows, col_widths: [18, 20, 10, 50, 50, 8, 50, 9, 9] }
  end

  write_xlsx(output_xlsx, sheets)
  puts "[+] Экспортировано #{asb_files.size} файлов → #{output_xlsx}"
end

# ── IMPORT ───────────────────────────────────────────────────────────────────

def cmd_import(asb_dir, input_xlsx, output_dir)
  require 'fileutils'
  FileUtils.mkdir_p(output_dir)

  sheets = read_xlsx(input_xlsx)
  puts "[+] Прочитано листов: #{sheets.size}"

  sheets.each do |sheet_name, rows|
    asb_path = File.join(asb_dir, "#{sheet_name}.asb")
    unless File.exist?(asb_path)
      puts "[!] #{asb_path} не найден, пропускаю"
      next
    end

    data = File.binread(asb_path).b
    strings = find_strings(data)
    data = data.dup

    # Строки данных (пропускаем заголовок)
    data_rows = rows[1..] || []
    replaced = 0
    skipped = 0
    errors = []

    data_rows.each_with_index do |row, i|
      s = strings[i]
      next unless s

      name_tl = row[1].to_s.strip
      orig = row[3].to_s.strip
      tl   = row[4].to_s.strip
      max  = row[5].to_s.strip
      tle  = row[6].to_s.strip

      # Перевод имени персонажа
      if !name_tl.empty? && s[:name_pos] && s[:name_len] && s[:name_len] > 0
        begin
          new_name = name_tl.encode(DST_ENC, 'UTF-8').b
          orig_name_len = s[:name_len]
          if new_name.size > orig_name_len
            new_name = new_name.byteslice(0, orig_name_len)
            errors << "##{i+2} имя: обрезано до #{orig_name_len} байт"
          end
          padded_name = new_name + (' '.b * (orig_name_len - new_name.size))
          data[s[:name_pos], orig_name_len] = padded_name
        rescue => e
          errors << "##{i+2} имя: #{e}"
        end
      end

      # Выбираем перевод: TLE > TL > ничего
      translation = tle.empty? ? tl : tle
      next if translation.empty?
	  
	  translation = translation.gsub('я', 'z')
	  translation = translation.gsub('… ', '…')
	  translation = translation.gsub('…', '… ')

      begin
        new_raw = translation.encode(DST_ENC, 'UTF-8').b
      rescue => e
        errors << "##{i+2}: #{e}"
        skipped += 1
        next
      end

      orig_len = s[:length]
      if new_raw.size > orig_len
        new_raw = new_raw.byteslice(0, orig_len)
        errors << "##{i+2}: обрезано до #{orig_len} байт"
      end

      padded = new_raw + (' '.b * (orig_len - new_raw.size))
      data[s[:pos], orig_len] = padded
      replaced += 1
    end

    out_path = File.join(output_dir, "#{sheet_name}.asb")
    File.binwrite(out_path, data)
    puts "[+] #{sheet_name}.asb: заменено #{replaced}, пропущено #{skipped}"
    errors.each { |e| puts "    [!] #{e}" }
  end

  puts "[+] Готово → #{output_dir}"
end

# ── MAIN ─────────────────────────────────────────────────────────────────────

require 'shellwords'

if ARGV.size < 3
  puts <<~HELP
    asb_xlsx.rb — конвертер ASB ↔ Excel для перевода игр AZSystem

    Использование:
      ruby asb_xlsx.rb export <папка_asb>  <output.xlsx>
      ruby asb_xlsx.rb import <папка_asb>  <input.xlsx>  <папка_вывода>

    Столбцы Excel:
      Оригинал  — оригинальный японский текст
      TL        — черновой перевод
      MaxБайт   — максимум байт для строки (cp1251: 1 байт/символ)
      TLE       — финальный перевод (приоритет над TL)

    При импорте: если TLE не пустой — берётся TLE, иначе TL, иначе без изменений.
  HELP
  exit 1
end

mode = ARGV[0].downcase
case mode
when 'export'
  cmd_export(ARGV[1], ARGV[2])
when 'import'
  if ARGV.size < 4
    puts "Нужна папка вывода: ruby asb_xlsx.rb import <папка> <xlsx> <вывод>"
    exit 1
  end
  cmd_import(ARGV[1], ARGV[2], ARGV[3])
else
  puts "Неизвестный режим: #{mode}"
  exit 1
end