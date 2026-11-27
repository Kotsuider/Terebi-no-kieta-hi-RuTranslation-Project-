"""Build/test helper; Python standard library only. Does not modify game EXEs."""
from pathlib import Path
import subprocess,hashlib,struct,json,sys,tempfile,shutil

root=Path(__file__).resolve().parents[1]
game=root.parent
source=(game/'tvlost.exe').read_bytes()
reference=Path(sys.argv[sys.argv.index('--reference')+1]) if '--reference' in sys.argv else game/'tvlost_rus_new.exe'
target=reference.read_bytes()
def sha(x):return hashlib.sha256(x).hexdigest()
assert sha(source)=='4e83a346cbec2cfb75e63568244deedb12ffe1cc22ba5ae5d6803ad7f55ffd2e'
assert sha(target)=='d1129cfde8c449cc4ffd5edcae6f176f0bb8160cdddd193ab60294931ce48239'
if '--bootstrap' in sys.argv:
    ranges=[];i=0
    def changed(i):return i>=len(source) or source[i]!=target[i]
    while i<len(target):
        if not changed(i):i+=1;continue
        start=i;end=i+1;i+=1
        while i<len(target):
            if changed(i):end=i+1
            elif i-end>=16:break
            i+=1
        ranges.append((start,end))
    patch=b'TVLPAT01'+struct.pack('<QQ',len(source),len(target))+hashlib.sha256(source).digest()+hashlib.sha256(target).digest()+struct.pack('<I',len(ranges))
    for start,end in ranges:patch+=struct.pack('<QQ',start,end-start)+target[start:end]
    patch+=hashlib.sha256(patch).digest()
    folder=root/'patch';folder.mkdir(exist_ok=True)
    (folder/'tvlost-2007-to-ru.tvp').write_bytes(patch)
    print('Bootstrapped delta:',len(patch),'bytes;',len(ranges),'ranges')
    sys.exit(0)

exe=root/'target/release/tvlost-patcher.exe';maker=root/'target/release/make-patch.exe'
output_root=root/'test-output';output_root.mkdir(exist_ok=True)
out=Path(tempfile.mkdtemp(prefix='run-',dir=output_root))
results=[]
def run(name,args,success,program=None,cwd=None):
    r=subprocess.run([str(program or exe),*map(str,args)],capture_output=True,cwd=cwd)
    assert (r.returncode==0)==success,(name,r.returncode,r.stdout,r.stderr)
    results.append(dict(test=name,passed=True,exit_code=r.returncode))
    return r
original=out/'оригинал игры.exe';original.write_bytes(source)
result=out/'русская версия.exe'
run('patch real original, Unicode paths',[original,result],True)
assert result.read_bytes()==target
assert original.read_bytes()==source
run('check original',['--check',original],True)
run('check patched',['--check',result],True)
run('reject already patched',[result,out/'again.exe'],False);assert not (out/'again.exe').exists()
corrupt=out/'corrupt.exe';altered=bytearray(source);altered[500000]^=1;corrupt.write_bytes(altered)
run('reject modified source',[corrupt,out/'bad.exe'],False);assert not (out/'bad.exe').exists()
truncated=out/'truncated.exe';truncated.write_bytes(source[:-1])
run('reject truncated source',[truncated,out/'bad-short.exe'],False);assert not (out/'bad-short.exe').exists()
run('check unknown source',['--check',corrupt],False)
existing=out/'existing.exe';existing.write_bytes(b'DO NOT OVERWRITE')
run('refuse to overwrite existing output',[original,existing],False);assert existing.read_bytes()==b'DO NOT OVERWRITE'
run('refuse input as output',[original,original],False);assert original.read_bytes()==source
run('default output path',[original],True);assert (out/'tvlost_rus_new.exe').read_bytes()==target
run('default output exists',[original],False)
run('missing input',[out/'missing.exe',out/'missing-result.exe'],False);assert not (out/'missing-result.exe').exists()
run('help',['--help'],True)

auto=out/'автопатч рядом с EXE';auto.mkdir()
auto_exe=auto/'tvlost-patcher.exe';shutil.copyfile(exe,auto_exe)
auto_source=auto/'tvlost.exe';auto_source.write_bytes(source)
foreign=out/'другой рабочий каталог';foreign.mkdir()
(foreign/'tvlost.exe').write_bytes(b'Wrong EXE in working directory')
run('auto mode uses executable folder, not cwd',[],True,auto_exe,foreign)
auto_result=auto/'tvlost_rus_new.exe'
assert auto_result.read_bytes()==target and auto_source.read_bytes()==source
assert not (foreign/'tvlost_rus_new.exe').exists()
run('auto mode refuses existing result',[],False,auto_exe,foreign)
assert auto_result.read_bytes()==target
missing=out/'no adjacent original';missing.mkdir()
missing_exe=missing/'tvlost-patcher.exe';shutil.copyfile(exe,missing_exe)
run('auto mode missing adjacent original ignores valid cwd source',[],False,missing_exe,out)
assert not (missing/'tvlost_rus_new.exe').exists()
# Put a correctly named valid source in cwd: the executable directory still wins.
(foreign/'tvlost.exe').write_bytes(source)
run('auto mode does not fall back to cwd',[],False,missing_exe,foreign)
assert not (foreign/'tvlost_rus_new.exe').exists()
bad_auto=out/'bad adjacent original';bad_auto.mkdir()
bad_exe=bad_auto/'tvlost-patcher.exe';shutil.copyfile(exe,bad_exe)
(bad_auto/'tvlost.exe').write_bytes(altered)
run('auto mode rejects changed source',[],False,bad_exe,foreign)
assert not (bad_auto/'tvlost_rus_new.exe').exists()
delta=out/'recreated.tvp'
r=subprocess.run([str(maker),str(original),str(result),str(delta)],capture_output=True)
assert r.returncode==0,(r.stdout,r.stderr)
assert delta.read_bytes()==(root/'patch/tvlost-2007-to-ru.tvp').read_bytes()
results.append(dict(test='Rust patch generator reproduces embedded delta',passed=True,exit_code=0))
assert (game/'tvlost.exe').read_bytes()==source
assert reference.read_bytes()==target
report=dict(tests=len(results),passed=len(results),exact_binary_match=True,source_unchanged=True,reference_unchanged=True,source_size=len(source),target_size=len(target),source_sha256=sha(source),target_sha256=sha(target),patch_bytes=delta.stat().st_size,results=results)
(root/'TEST_REPORT.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
