.intel_syntax noprefix
.text
.extern _our_load_script_c
.global _our_load_script

_our_load_script:
    push ebp
    mov  ebp, esp
    push esi
    push ebx

    mov  esi, ecx
    mov  ebx, edi

    mov  ecx, esi
    mov  edi, ebx
    call dword ptr [_g_load_script_ptr]

    push eax

    push ebx
    push esi
    call _our_load_script_c
    add  esp, 8

    pop  eax
    pop  ebx
    pop  esi
    pop  ebp
    ret

.data
.global _g_load_script_ptr
_g_load_script_ptr:
    .long 0x00420b70