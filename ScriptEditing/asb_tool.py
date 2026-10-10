import os
import sys
import glob
import struct
import argparse
import textwrap
from pathlib import Path
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment

SRC_ENC = 'shift_jis'
DST_ENC = 'cp1252'
DEFAULT_WRAP_WIDTH = 42
MAX_LINES_LIMIT = 3

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from ru_f_translate import apply_ru_f
except ImportError:
    apply_ru_f = lambda x: x

def parse_asb_commands(data: bytes):
    pos = 0
    total = len(data)
    commands = []
    while pos < total:
        if pos + 2 > total:
            break
        sz = data[pos] | (data[pos+1] << 8)
        if sz <= 0 or pos + sz > total:
            break
        opcode = data[pos+2] | (data[pos+3] << 8) if sz >= 4 else 0
        commands.append({
            'pos': pos,
            'sz': sz,
            'opcode': opcode,
            'raw': data[pos:pos+sz]
        })
        pos += sz
    return commands

def parse_op26_text(cmd_bytes: bytes):
    if len(cmd_bytes) < 17 or cmd_bytes[-3:] != b'\x00\x02\x1c':
        return None

    line_num = struct.unpack_from('<H', cmd_bytes, 10)[0]

    # Вариант 1: Нарратив (03 07 00 [ll:1] 07 [text] 00 02 1c)
    if cmd_bytes[12:15] == b'\x03\x07\x00':
        ll = cmd_bytes[15]
        marker = cmd_bytes[16]
        if marker == 0x07:
            raw_text = cmd_bytes[17:-3]
            try:
                text_str = raw_text.decode(SRC_ENC, errors='replace')
            except Exception:
                text_str = raw_text.decode('latin1')
            return {
                'type': 'narrative',
                'line': line_num,
                'speaker_raw': b'',
                'speaker': '',
                'text_raw': raw_text,
                'text': text_str,
                'prefix_header': cmd_bytes[:12], # до байта 12
            }

    # Вариант 2: Диалог со спикером
    # [sz:2][1a 00][00 00 00 00][03 00][line:2] [spk_ll:1][07] [speaker] 00 [ll:1][07] [text] 00 02 1c
    # spk_marker должен быть 0x07
    spk_ll = cmd_bytes[12]
    spk_marker = cmd_bytes[13]
    if spk_marker == 0x07:
        name_null = cmd_bytes.find(b'\x00', 14)
        if name_null != -1 and name_null + 2 < len(cmd_bytes):
            ll = cmd_bytes[name_null + 1]
            marker = cmd_bytes[name_null + 2]
            if marker == 0x07:
                speaker_raw = cmd_bytes[14:name_null]
                try:
                    speaker_str = speaker_raw.decode(SRC_ENC, errors='replace')
                except Exception:
                    speaker_str = speaker_raw.decode('latin1')
                raw_text = cmd_bytes[name_null + 3 : -3]
                try:
                    text_str = raw_text.decode(SRC_ENC, errors='replace')
                except Exception:
                    text_str = raw_text.decode('latin1')
                return {
                    'type': 'dialogue',
                    'line': line_num,
                    'speaker_raw': speaker_raw,
                    'speaker': speaker_str,
                    'text_raw': raw_text,
                    'text': text_str,
                    'prefix_header': cmd_bytes[:12],
                }
    return None

def build_op26_command(parsed_info: dict, new_speaker_bytes: bytes | None, new_text_bytes: bytes) -> bytes:
    trailing = b'\x00\x02\x1c'
    if parsed_info['type'] == 'narrative':
        ll = len(new_text_bytes) + 3
        # 12 (hdr) + 3 (03 07 00) + 2 (ll, 0x07) + len(text) + 3 (trailing)
        new_cmd_len = 12 + 3 + 2 + len(new_text_bytes) + len(trailing)
        cmd_hdr = struct.pack('<H', new_cmd_len) + parsed_info['prefix_header'][2:]
        return cmd_hdr + b'\x03\x07\x00' + bytes([ll, 0x07]) + new_text_bytes + trailing
    else:
        speaker_b = new_speaker_bytes if new_speaker_bytes is not None else parsed_info['speaker_raw']
        spk_ll = len(speaker_b) + 3
        text_ll = len(new_text_bytes) + 3
        
        # 12 (hdr) + 2 (spk_ll, 0x07) + len(speaker_b) + 1 (null) + 2 (text_ll, 0x07) + len(text) + 3 (trailing)
        new_cmd_len = 12 + 2 + len(speaker_b) + 1 + 2 + len(new_text_bytes) + len(trailing)
        cmd_hdr = struct.pack('<H', new_cmd_len) + parsed_info['prefix_header'][2:]
        spk_chunk = bytes([spk_ll, 0x07]) + speaker_b + b'\x00'
        text_chunk = bytes([text_ll, 0x07]) + new_text_bytes + trailing
        return cmd_hdr + spk_chunk + text_chunk

def wrap_text_by_words(text: str, max_width: int = DEFAULT_WRAP_WIDTH) -> str:
    if max_width <= 0:
        return text

    # Поддерживаем как реальный перевод строки (\r\n, \n), так и буквальные '\n'
    raw_paragraphs = text.replace('\r\n', '\n').replace('\\n', '\n').split('\n')
    wrapped_paras = []

    for p in raw_paragraphs:
        if not p:
            wrapped_paras.append('')
            continue
        if len(p) <= max_width:
            wrapped_paras.append(p)
            continue

        lines = textwrap.wrap(
            p,
            width=max_width,
            break_long_words=False,
            break_on_hyphens=False
        )
        # В ASB перенос строки - это два байта: '\' и 'n' (literal \n), а не байт 0x0A
        wrapped_paras.append(r'\n'.join(lines))

    return r'\n'.join(wrapped_paras)

def prepare_translation_text(text: str, wrap_width: int = DEFAULT_WRAP_WIDTH) -> str:
    t = text.replace('\u3000', '  ')
    if wrap_width > 0:
        t = wrap_text_by_words(t, wrap_width)
    t = t.replace('… ', '…')
    t = t.replace('…', '… ')

    # Конвертируем кириллицу в латиницу/спецсимволы RU_F под кастомный шрифт OUCTSfontD1.ttf
    # Заметьте: разделители переноса строк r'\n' состоят из '\' и 'n', которые не заменяются apply_ru_f
    t = apply_ru_f(t)

    # Проверка перед '\n' на случай, если какой-то символ попадает в Lead Byte
    if r'\n' in t:
        parts = t.split(r'\n')
        safe_res = parts[0]
        for p in parts[1:]:
            if safe_res:
                b_last = safe_res.encode(DST_ENC, errors='replace')[-1]
                if (0x81 <= b_last <= 0x9F) or (0xE0 <= b_last <= 0xFC):
                    safe_res += ' '
            safe_res += r'\n' + p
        t = safe_res

    return t

def cmd_export(asb_dir: str, output_xlsx: str):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    asb_files = sorted(glob.glob(os.path.join(asb_dir, '*.asb')))
    if not asb_files:
        print('[!] ASB files not found in ' + asb_dir)
        return False

    print('[*] Exporting ' + str(len(asb_files)) + ' scripts to ' + output_xlsx)
    header_font = Font(name='Segoe UI', size=10, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='336699', end_color='336699', fill_type='solid')
    align_center = Alignment(horizontal='center', vertical='center')

    for asb_path in asb_files:
        sheet_name = Path(asb_path).stem[:31]
        ws = wb.create_sheet(title=sheet_name)
        headers = ['Персонаж', 'Имя TL', 'Имя Байты', 'Оригинал', 'TL', 'MaxБайт', 'TLE']
        ws.append(headers)
        for col_idx, h in enumerate(headers, 1):
            c = ws.cell(row=1, column=col_idx)
            c.font = header_font
            c.fill = header_fill
            c.alignment = align_center

        with open(asb_path, 'rb') as f:
            data = f.read()

        cmds = parse_asb_commands(data)
        row_idx = 2
        for cmd in cmds:
            if cmd['opcode'] == 26:
                info = parse_op26_text(cmd['raw'])
                if info:
                    ws.cell(row=row_idx, column=1, value=info['speaker'])
                    ws.cell(row=row_idx, column=2, value='')
                    ws.cell(row=row_idx, column=3, value=len(info['speaker_raw']))
                    ws.cell(row=row_idx, column=4, value=info['text'])
                    ws.cell(row=row_idx, column=5, value='')
                    ws.cell(row=row_idx, column=6, value=len(info['text_raw']))
                    ws.cell(row=row_idx, column=7, value='')
                    row_idx += 1

        ws.column_dimensions['A'].width = 18
        ws.column_dimensions['B'].width = 18
        ws.column_dimensions['C'].width = 10
        ws.column_dimensions['D'].width = 50
        ws.column_dimensions['E'].width = 50
        ws.column_dimensions['F'].width = 10
        ws.column_dimensions['G'].width = 50

    wb.save(output_xlsx)
    print('[+] Export finished: ' + output_xlsx)
    return True

def cmd_import(asb_dir: str, input_xlsx: str, output_dir: str, wrap_width: int = DEFAULT_WRAP_WIDTH, auto_pack: bool = False):
    os.makedirs(output_dir, exist_ok=True)
    print('[*] Loading workbook: ' + input_xlsx)
    wb = openpyxl.load_workbook(input_xlsx, data_only=True)
    sheet_names = wb.sheetnames
    print('[*] Sheet count: ' + str(len(sheet_names)) + ' (auto-wrap: ' + str(wrap_width) + ' chars)')

    total_files = 0
    total_replaced = 0
    overflow_records = []
    EXCLUDE_SHEETS = {'startup'}

    for sheet_name in sheet_names:
        if sheet_name in EXCLUDE_SHEETS:
            # Копируем оригинальный файл без изменений
            orig_src = os.path.join(asb_dir, sheet_name + '.asb')
            if os.path.exists(orig_src):
                import shutil
                shutil.copy2(orig_src, os.path.join(output_dir, sheet_name + '.asb'))
                total_files += 1
            continue

        asb_candidates = [
            os.path.join(asb_dir, sheet_name + '.asb'),
            os.path.join(asb_dir, sheet_name)
        ]
        asb_path = next((p for p in asb_candidates if os.path.exists(p)), None)
        if not asb_path:
            continue

        ws = wb[sheet_name]
        with open(asb_path, 'rb') as f:
            data = f.read()

        cmds = parse_asb_commands(data)
        rows_data = list(ws.iter_rows(values_only=True))
        dialogue_rows = rows_data[1:] if len(rows_data) > 1 else []
        diag_idx = 0

        new_cmd_chunks = []
        file_replaced = 0

        for cmd in cmds:
            if cmd['opcode'] == 26:
                info = parse_op26_text(cmd['raw'])
                if info:
                    if diag_idx < len(dialogue_rows):
                        excel_row_num = diag_idx + 2  # 1-indexed, заголовок на строке 1
                        row = dialogue_rows[diag_idx]
                        diag_idx += 1

                        speaker_tl = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ''

                        tl = ''
                        tle = ''
                        if len(row) >= 7:
                            tl = str(row[4]).strip() if row[4] is not None else ''
                            tle = str(row[6]).strip() if row[6] is not None else ''
                        elif len(row) == 5:
                            tl = str(row[3]).strip() if row[3] is not None else ''
                            tle = str(row[4]).strip() if row[4] is not None else ''

                        trans = tle if tle else tl

                        if trans or speaker_tl:
                            file_replaced += 1
                            new_text_str = trans if trans else info['text']
                            trans_proc = prepare_translation_text(new_text_str, wrap_width=wrap_width)
                            
                            # Проверяем количество строк после переноса
                            if wrap_width > 0 and trans:
                                line_count = trans_proc.count(r'\n') + 1
                                if line_count > MAX_LINES_LIMIT:
                                    overflow_records.append({
                                        'sheet': sheet_name,
                                        'row': excel_row_num,
                                        'line_count': line_count,
                                        'speaker': speaker_tl or info['speaker'],
                                        'text': trans,
                                        'wrapped': trans_proc.replace(r'\n', '\n')
                                    })

                            new_text_bytes = trans_proc.encode(DST_ENC, errors='replace')

                            new_spk_bytes = None
                            if speaker_tl:
                                spk_proc = prepare_translation_text(speaker_tl, wrap_width=0)
                                new_spk_bytes = spk_proc.encode(DST_ENC, errors='replace')

                            new_cmd_raw = build_op26_command(info, new_spk_bytes, new_text_bytes)
                            new_cmd_chunks.append(new_cmd_raw)
                            continue

            new_cmd_chunks.append(cmd['raw'])

        new_asb_data = b''.join(new_cmd_chunks)
        out_asb_path = os.path.join(output_dir, sheet_name + '.asb')
        with open(out_asb_path, 'wb') as f:
            f.write(new_asb_data)

        total_files += 1
        total_replaced += file_replaced
        if file_replaced > 0:
            print('  [+] ' + sheet_name + '.asb: ' + str(file_replaced) + ' lines replaced (' + str(len(data)) + ' -> ' + str(len(new_asb_data)) + ' bytes)')

    print('[+] Finished! Processed ' + str(total_files) + ' files, ' + str(total_replaced) + ' lines replaced.')

    # Запись лога превышения строк
    report_path = os.path.join(os.path.dirname(input_xlsx), 'exceeded_lines.txt')
    if not os.path.isabs(report_path):
        report_path = os.path.abspath(report_path)

    with open(report_path, 'w', encoding='utf-8') as rf:
        rf.write("================================================================================\n")
        rf.write(f"  ОТЧЁТ О СТРОКАХ, ПРЕВЫШАЮЩИХ ЛИМИТ В {MAX_LINES_LIMIT} СТРОКИ (ШИРИНА: {wrap_width} СИМВОЛОВ)\n")
        rf.write(f"  Всего превышений: {len(overflow_records)}\n")
        rf.write("================================================================================\n\n")
        for rec in overflow_records:
            spk_str = f" [{rec['speaker']}]" if rec['speaker'] else ""
            rf.write(f"Лист: {rec['sheet']} | Строка в Excel: {rec['row']}{spk_str} | Строк: {rec['line_count']}\n")
            rf.write("Текст в Excel:\n")
            rf.write(f"  {rec['text']}\n")
            rf.write("Как разобьётся на экране:\n")
            for sub_i, sub_line in enumerate(rec['wrapped'].split('\n'), start=1):
                rf.write(f"  {sub_i}: {sub_line}\n")
            rf.write("-" * 80 + "\n\n")

    if overflow_records:
        print(f"\n[!] ВНИМАНИЕ: Найдено {len(overflow_records)} реплик, которые превышают {MAX_LINES_LIMIT} строки в окне!")
        print(f"[!] Полный список с номерами строк сохранён в: {report_path}\n")
    else:
        print(f"\n[+] Отлично! Ни одна реплика не превышает лимит в {MAX_LINES_LIMIT} строки.\n")

    if auto_pack:
        pack_script = os.path.join(os.path.dirname(__file__), 'arc_pack.py')
        if not os.path.exists(pack_script):
            pack_script = 'arc_pack.py'
        if os.path.exists(pack_script):
            print('[*] Auto-packing script.arc...')
            import subprocess
            cmd = [
                sys.executable, pack_script,
                output_dir, 'script.arc', 'system.arc', 'script_original.arc'
            ]
            res = subprocess.run(cmd)
            if res.returncode == 0:
                print('[+] script.arc created successfully!')
            else:
                print('[!] Error packing script.arc')

def main():
    parser = argparse.ArgumentParser(description='ASB Script Tool')
    subparsers = parser.add_subparsers(dest='command', required=True)

    p_exp = subparsers.add_parser('export')
    p_exp.add_argument('asb_dir')
    p_exp.add_argument('output_xlsx')

    p_imp = subparsers.add_parser('import')
    p_imp.add_argument('asb_dir')
    p_imp.add_argument('input_xlsx')
    p_imp.add_argument('output_dir')
    p_imp.add_argument('--wrap', type=int, default=DEFAULT_WRAP_WIDTH, help='Максимальная ширина строки в символах для автопереноса слов (по умолчанию 42)')
    p_imp.add_argument('--pack', action='store_true')

    args = parser.parse_args()
    if args.command == 'export':
        cmd_export(args.asb_dir, args.output_xlsx)
    elif args.command == 'import':
        cmd_import(args.asb_dir, args.input_xlsx, args.output_dir, wrap_width=args.wrap, auto_pack=args.pack)

if __name__ == '__main__':
    main()
