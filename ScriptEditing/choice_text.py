"""Translate ASB opcode 0x15 using readable Russian JSON; safe to run twice."""
from pathlib import Path
import json,struct,argparse

def translate_data(data, translations):
    import asb_tool as tool
    encoded={jp.encode('cp932'):tool.encode_runtime_text(tool.prepare_translation_text(ru,wrap_width=0)) for jp,ru in translations.items()}
    for jp,ru in translations.items():
        if not ru or '\n' in ru or '\r' in ru or r'\n' in ru:raise ValueError('Choice must be a nonempty single line: '+jp)
        if len(encoded[jp.encode('cp932')])+3>255:raise ValueError('Choice exceeds one-byte string length: '+jp)
    commands=tool.parse_asb_commands(data);chunks=[];changed=empty=existing=0
    for c in commands:
        raw=c['raw']
        if c['opcode']==21:
            if len(raw)<23 or raw[12:14]!=b'\x06\x06' or raw[19]!=7 or raw[-3:]!=b'\x00\x02\x1c' or raw[18]!=len(raw[20:-3])+3:
                raise ValueError(f'Unknown choice layout at {c["pos"]:#x}')
            text=raw[20:-3]
            if not text:empty+=1
            elif text in encoded:
                text=encoded[text];chunk=bytearray(raw[:20]+text+raw[-3:]);struct.pack_into('<H',chunk,0,len(chunk));chunk[18]=len(text)+3;raw=bytes(chunk);changed+=1
            elif text in encoded.values():existing+=1
            else:raise ValueError(f'Untranslated choice at {c["pos"]:#x}: {text.decode("cp932",errors="replace")!r}')
        chunks.append(raw)
    return tool.relocate_commands(commands,chunks,len(data)),dict(translated=changed,already_translated=existing,empty=empty)

def translate_folder(folder, dictionary):
    folder=Path(folder)
    dictionary=Path(dictionary)
    if not dictionary.is_file():
        raise FileNotFoundError('Private choice dictionary is not included in Git. Provide it locally: ' + str(dictionary))
    translations=json.loads(dictionary.read_text(encoding='utf-8-sig'));prepared=[];total=dict(translated=0,already_translated=0,empty=0,changed_files=0)
    # Validate every script before replacing any of them.
    for path in sorted(folder.glob('*.asb')):
        data=path.read_bytes()
        try:result,counts=translate_data(data,translations)
        except Exception as error:raise ValueError(f'{path.name}: {error}') from error
        for key,value in counts.items():total[key]+=value
        if result!=data:prepared.append((path,result));total['changed_files']+=1
    if not list(folder.glob('*.asb')):raise ValueError('No ASB files in '+str(folder))
    for path,result in prepared:
        temp=path.with_suffix('.asb.tmp');temp.write_bytes(result);temp.replace(path)
    return total

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--dictionary',type=Path,default=Path(__file__).with_name('choice_translations.json'));args=p.parse_args();print(translate_folder(args.folder,args.dictionary))
