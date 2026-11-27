import struct
import unittest
import asb_tool as tool


def dialogue(text):
    data = text.encode('shift_jis')
    return struct.pack('<HHIHH', 20 + len(data), 26, 0, 3, 1) + b'\x03\x07\x00' + bytes([len(data) + 3, 7]) + data + b'\x00\x02\x1c'


class ImportTests(unittest.TestCase):
    def test_extra_resource_does_not_shift_dialogue(self):
        commands = tool.parse_asb_commands(dialogue('昨日') + dialogue('今日'))
        rows = [(None, None, 0, text, translation, 0, None) for text, translation in [('bg005a', 'bg005a'), ('昨日', 'Вчера'), ('今日', 'Сегодня')]]
        self.assertEqual([r[1][4] for r in tool.align_dialogue_rows(commands, rows)], ['Вчера', 'Сегодня'])
        with self.assertRaises(ValueError):
            tool.align_dialogue_rows(commands, rows[2:])

    def test_jump_tracks_command_after_text_growth(self):
        text = dialogue('昨日')
        branch = struct.pack('<HHIHH', 12, 4, 12 + len(text), 0, 0)
        end = struct.pack('<HHIHH', 12, 0, 0xffffffff, 0, 0)
        source = branch + text + end
        commands = tool.parse_asb_commands(source)
        longer = dialogue('昨日今日')
        result = tool.relocate_commands(commands, [branch, longer, end], len(source))
        self.assertEqual(struct.unpack_from('<I', result, 4)[0], 12 + len(longer))
        self.assertEqual(result[12 + len(longer):], end)

    def test_ru_f_and_native_symbols(self):
        self.assertEqual(tool.encode_runtime_text(tool.apply_ru_f('Синго')), b'Rindo')
        self.assertEqual(tool.encode_runtime_text('♪'), '♪'.encode('cp932'))

    def test_truncated_command_rejected(self):
        with self.assertRaises(ValueError):
            tool.parse_asb_commands(dialogue('昨日')[:-1])


if __name__ == '__main__':
    unittest.main()
