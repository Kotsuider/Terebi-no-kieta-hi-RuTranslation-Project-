"""Validate complete imports against original ASB and workbook, including branch identity."""
from pathlib import Path
import collections
import json
import struct
import zlib
import openpyxl
import asb_tool as tool
import choice_text


def verify_archive(archive='script_fixed.arc', folder='script_fixed'):
    import arc_pack as pack
    root = Path(__file__).resolve().parent
    raw = (root / archive).read_bytes()
    key = pack.gen_key(pack.INI_TABLE[0])
    header = bytearray(raw[:48])
    pack.xor_stream(header, 0, key)
    magic, _, count, index_size = struct.unpack_from('<4sIII', header)
    assert magic == b'ARC\x00'
    index = bytearray(raw[48:48 + index_size])
    pack.xor_stream(index, 48, key)
    assert struct.unpack_from('<I', index)[0] == pack.ewf_crc(index[4:])
    entries = zlib.decompress(index[4:])
    resource_key = pack.find_key_from_system_arc(root.parent / 'system.arc')
    assert resource_key is not None
    names = set()
    for i in range(count):
        offset, size = struct.unpack_from('<II', entries, i * 48)
        name = entries[i * 48 + 16:i * 48 + 48].split(b'\x00')[0].decode('ascii')
        names.add(name)
        absolute = 48 + index_size + offset
        payload = bytearray(raw[absolute:absolute + size])
        pack.xor_stream(payload, absolute, resource_key)
        magic, compressed, uncompressed, commands = struct.unpack_from('<4sIII', payload)
        assert magic == b'ASB\x00' and compressed == len(payload) - 16
        data = bytearray(payload[16:])
        inner_key = (uncompressed ^ 0x9E370001) & 0xffffffff
        for position in range(0, len(data) - 3, 4):
            value = struct.unpack_from('<I', data, position)[0]
            struct.pack_into('<I', data, position, (value - inner_key) & 0xffffffff)
        assert struct.unpack_from('<I', data)[0] == pack.ewf_crc(data[4:])
        decoded = zlib.decompress(data[4:])
        assert len(decoded) == uncompressed and decoded == (root / folder / name).read_bytes(), name
        assert commands == len(tool.parse_asb_commands(decoded)), name
    assert names == {p.name for p in (root / folder).glob('*.asb')}
    print(f'Archive verified: {count} scripts decrypted and matched byte-for-byte.')


def verify(output='script_fixed'):
    root = Path(__file__).resolve().parent
    workbook = openpyxl.load_workbook(root / 'new_tv.xlsx', data_only=True)
    choices = json.loads((root / 'choice_translations.json').read_text(encoding='utf-8'))
    report = {'files': 0, 'dialogues': 0, 'jumps': 0, 'moved_jumps': 0, 'missing_names': [], 'regressions': {}}
    for source in sorted((root / 'script').glob('*.asb')):
        original = source.read_bytes()
        result = (root / output / source.name).read_bytes()
        if source.stem == 'startup':
            expected, _ = choice_text.translate_data(original, choices)
            assert result == expected
            report['files'] += 1
            continue
        old, new = tool.parse_asb_commands(original), tool.parse_asb_commands(result)
        assert len(old) == len(new), source.name
        mapping = {c['pos']: n['pos'] for c, n in zip(old, new)}
        mapping[len(original)] = len(result)
        rows = tool.align_dialogue_rows(old, list(workbook[source.stem].values)[1:]) if source.stem != 'startup' else []
        index = 0
        for c, n in zip(old, new):
            assert c['opcode'] == n['opcode'], source.name
            info = tool.parse_op26_text(c['raw']) if c['opcode'] == 26 else None
            if info:
                row_number, row = rows[index]
                index += 1
                parsed = tool.parse_op26_text(n['raw'])
                assert parsed is not None
                translation = str(row[6] or row[4] or '').strip()
                speaker = str(row[1] or '').strip()
                expected_text = tool.encode_runtime_text(tool.prepare_translation_text(translation)) if translation else info['text_raw']
                expected_name = tool.encode_runtime_text(tool.prepare_translation_text(speaker, 0)) if speaker else info['speaker_raw']
                assert parsed['text_raw'] == expected_text, (source.name, row_number)
                assert parsed['speaker_raw'] == expected_name, (source.name, row_number)
                assert parsed['line'] == info['line']
                if info['speaker'] and not speaker:
                    report['missing_names'].append([source.name, row_number, info['speaker']])
                if source.stem == 'tv_03' and row_number in (3, 42, 929, 930, 931):
                    report['regressions'][str(row_number)] = {'speaker': speaker, 'text': translation, 'line': info['line']}
                report['dialogues'] += 1
            elif c['opcode'] == 21:
                expected, _ = choice_text.translate_data(c['raw'], choices)
                assert n['raw'] == expected, (source.name, c['pos'])
            elif c['opcode'] in (4, 5):
                before = struct.unpack_from('<I', c['raw'], 4)[0]
                after = struct.unpack_from('<I', n['raw'], 4)[0]
                assert after == mapping[before], (source.name, c['pos'])
                assert c['raw'][:4] + c['raw'][8:] == n['raw'][:4] + n['raw'][8:]
                report['jumps'] += 1
                report['moved_jumps'] += before != after
            else:
                assert c['raw'] == n['raw'], (source.name, c['pos'])
        report['files'] += 1
    (root / 'script_fix_validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'regressions'}, ensure_ascii=False))
    return report


if __name__ == '__main__':
    verify()
