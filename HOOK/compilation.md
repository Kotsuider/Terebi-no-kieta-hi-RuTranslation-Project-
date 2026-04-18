```cmd/powershell
export PATH="/mingw32/bin:$PATH"
```

```cmd/powershell
i686-w64-mingw32-gcc -c hook_asm.S -o hook_asm.o
i686-w64-mingw32-gcc -shared -o version.dll azsystem_patch.c hook_asm.o version.def -lkernel32 -lgdi32 -s -O2 -m32 -Wl,--enable-stdcall-fixup
```

