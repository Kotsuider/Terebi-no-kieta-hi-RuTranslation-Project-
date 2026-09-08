#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <string.h>
#include <stdio.h>

#define PATCH_DIR   "patch\\"
#define TRANS_FILE  PATCH_DIR "translate.txt"
#define MAX_ENTRIES 8192
#define MAX_STR     1024
#define MAX_ACCUM   4096

static struct { char src[MAX_STR]; int src_len; char dst[MAX_STR]; int dst_len; } g_tbl[MAX_ENTRIES];
static int g_tbl_n = 0;

static void load_dict(void) {
    char line[MAX_STR*2+4];
    FILE *f = fopen(TRANS_FILE, "rb");
    if (!f) { OutputDebugStringA("[patch] translate.txt not found\n"); return; }
    while (fgets(line, sizeof line, f) && g_tbl_n < MAX_ENTRIES) {
        int len = strlen(line);
        while (len > 0 && (line[len-1]=='\r'||line[len-1]=='\n')) line[--len]=0;
        if (!len) continue;
        char *eq = strchr(line, '=');
        if (!eq || eq==line || !eq[1]) continue;
        *eq = 0;
        strncpy(g_tbl[g_tbl_n].src, line, MAX_STR-1);
        g_tbl[g_tbl_n].src_len = strlen(line);
        strncpy(g_tbl[g_tbl_n].dst, eq+1, MAX_STR-1);
        g_tbl[g_tbl_n].dst_len = strlen(eq+1);
        g_tbl_n++;
    }
    fclose(f);
    char msg[64];
    _snprintf(msg, sizeof msg, "[patch] Loaded %d translations\n", g_tbl_n);
    OutputDebugStringA(msg);
}

/* ── Загрузка шрифта ── */
static char g_font_face[64] = "MS Gothic";
static void load_font_from_file(void) {
    WIN32_FIND_DATAA fd;
    HANDLE hf = FindFirstFileA(PATCH_DIR "*.ttf", &fd);
    if (hf == INVALID_HANDLE_VALUE) hf = FindFirstFileA(PATCH_DIR "*.TTF", &fd);
    if (hf != INVALID_HANDLE_VALUE) {
        char path[MAX_PATH];
        _snprintf(path, MAX_PATH, PATCH_DIR "%s", fd.cFileName);
        FindClose(hf);
        if (AddFontResourceExA(path, FR_PRIVATE, NULL)) {
            strncpy(g_font_face, fd.cFileName, 63);
            char *dot = strrchr(g_font_face, '.');
            if (dot) *dot = 0;
            char msg[MAX_PATH+64];
            _snprintf(msg, sizeof msg, "[patch] Font loaded: %s -> face='%s'\n", path, g_font_face);
            OutputDebugStringA(msg);
        }
    }
}

typedef BOOL (WINAPI *TextOutA_t)(HDC,int,int,LPCSTR,int);
static TextOutA_t g_orig_TextOutA = NULL;

static BOOL WINAPI hooked_TextOutA(HDC hdc, int x, int y, LPCSTR str, int cb)
{
    // Статический флаг: был ли предыдущий символ 0x16
    static BOOL skip_next = FALSE;
    
    if (!str || cb <= 0)
        return g_orig_TextOutA(hdc, x, y, str, cb);

    unsigned char ch = (unsigned char)str[0];
    
    // Если стоит флаг пропуска — пропускаем текущий символ и сбрасываем флаг
    if (skip_next) {
        skip_next = FALSE;
        // Можно добавить лог для отладки:
        // OutputDebugStringA("[patch] SKIP NEXT after 0x16\n");
        return TRUE;
    }
    
    // Обработка самого 0x16: ставим флаг и пропускаем его
    if (ch == 0x16) {
        skip_next = TRUE;
        OutputDebugStringA("[patch] Found 0x16, will skip next char\n");
        return TRUE;
    }

    // Исходный байт 0xFF (EOF / разделитель движка) игнорируем, чтобы не было фантомной 'я'
    if (ch == 0xFF) {
        return TRUE;
    }

    // Настоящая 'я' закодирована в скрипте как 'z', её переводим в 0xFF ('я')
    if (ch == 'z') {
        ch = 0xFF;
    }

    int allowed = 0;
    // Разрешаем: кириллицу CP1251 (0xC0..0xFF, а также Ё 0xA8, ё 0xB8),
    // ASCII печатные символы (0x20..0x7E),
    // троеточие (0x85), длинное/короткое тире (0x96, 0x97), кавычки-ёлочки (0xAB, 0xBB), кавычки (0x84, 0x93, 0x94)
    if ((ch >= 0xC0 && ch <= 0xFF) ||
        (ch >= 0x20 && ch <= 0x7E) ||
        ch == 0x85 || ch == 0x96 || ch == 0x97 || ch == 0xAB || ch == 0xBB ||
        ch == 0x84 || ch == 0x93 || ch == 0x94 || ch == 0xA8 || ch == 0xB8)
    {
        allowed = 1;
    }

    if (!allowed) {
        return TRUE;
    }

    return g_orig_TextOutA(hdc, x, y, (LPCSTR)&ch, 1);
}

/* ── SetWindowTextA hook — подмена заголовка окна ── */
typedef BOOL (WINAPI *SetWindowTextA_t)(HWND, LPCSTR);
static SetWindowTextA_t g_orig_SetWindowTextA = NULL;

/* "テレビの消えた日" в Shift-JIS */
static const char g_window_title_sjis[] =
    "\x83\x65\x83\x8c\x83\x72\x82\xcc\x8f\xc1\x82\xa6\x82\xbd\x93\xfa";

static BOOL WINAPI hooked_SetWindowTextA(HWND hWnd, LPCSTR str)
{
    if (str && strcmp(str, g_window_title_sjis) == 0)
        return g_orig_SetWindowTextA(hWnd,
            "\xc4\xe5\xed\xfc\x2c\x20\xea\xee\xe3\xe4\xe0\x20\xef\xf0\xee\xef\xe0\xeb\xee\x20\xf2\xe5\xeb\xe5\xe2\xe8\xe4\xe5\xed\xe8\xe5");
    return g_orig_SetWindowTextA(hWnd, str);
}

/* ── CreateFontA hook ── */
typedef HFONT (WINAPI *CreateFontA_t)(int,int,int,int,int,DWORD,DWORD,DWORD,
    DWORD,DWORD,DWORD,DWORD,DWORD,LPCSTR);
static CreateFontA_t g_orig_CreateFontA = NULL;

static HFONT WINAPI hooked_CreateFontA(int h, int w, int esc, int ori, int wt,
    DWORD ital, DWORD ul, DWORD so, DWORD charset,
    DWORD op, DWORD cp, DWORD q, DWORD pf, LPCSTR face)
{
    charset = DEFAULT_CHARSET;
    return g_orig_CreateFontA(h,w,esc,ori,wt,ital,ul,so,charset,op,cp,q,pf,g_font_face);
}

/* ── Hook CPB через IAT CreateFileA ── */
/*
 * Движок читает CPB файлы из .arc архива через единственный в exe вызов
 * CreateFileA (0x442c31). Перехватываем IAT CreateFileA: если имя файла
 * заканчивается на .cpb и в patch\ есть замена — открываем наш файл.
 */
typedef HANDLE (WINAPI *CreateFileA_orig_t)(LPCSTR, DWORD, DWORD,
    LPSECURITY_ATTRIBUTES, DWORD, DWORD, HANDLE);
static CreateFileA_orig_t g_orig_CreateFileA_cpb = NULL;

static HANDLE WINAPI hooked_CreateFileA_cpb(
    LPCSTR lpFileName, DWORD dwAccess, DWORD dwShare,
    LPSECURITY_ATTRIBUTES lpSA, DWORD dwCreate, DWORD dwFlags, HANDLE hTemplate)
{
    if (lpFileName) {
        /* Проверяем расширение .cpb */
        const char *dot = strrchr(lpFileName, '.');
        if (dot && _stricmp(dot, ".cpb") == 0) {
            /* Берём только basename */
            const char *base = strrchr(lpFileName, '\\');
            if (!base) base = strrchr(lpFileName, '/');
            base = base ? base + 1 : lpFileName;

            char patch_path[MAX_PATH];
            _snprintf(patch_path, MAX_PATH, PATCH_DIR "%s", base);

            DWORD attr = GetFileAttributesA(patch_path);
            if (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY)) {
                char msg[MAX_PATH + 64];
                _snprintf(msg, sizeof msg, "[patch] CPB redirect: %s -> %s\n",
                          lpFileName, patch_path);
                OutputDebugStringA(msg);
                return g_orig_CreateFileA_cpb(patch_path, dwAccess, dwShare,
                                              lpSA, dwCreate, dwFlags, hTemplate);
            }
        }
    }
    return g_orig_CreateFileA_cpb(lpFileName, dwAccess, dwShare,
                                  lpSA, dwCreate, dwFlags, hTemplate);
}

/* ── Hook load_script (asb замена) ── */
void __cdecl our_load_script_c(const char *name, void *data_struct)
{
    if (!name || !name[0] || !data_struct) return;
    const char *base = strrchr(name, '\\');
    if (!base) base = strrchr(name, '/');
    base = base ? base+1 : name;
    char path[MAX_PATH];
    _snprintf(path, MAX_PATH, PATCH_DIR "%s", base);
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) return;
    DWORD sz = GetFileSize(h, NULL), rd;
    BYTE *buf = (BYTE*)HeapAlloc(GetProcessHeap(), 0, sz+1);
    if (!buf || !ReadFile(h,buf,sz,&rd,NULL)||rd!=sz) {
        if(buf) HeapFree(GetProcessHeap(),0,buf);
        CloseHandle(h); return;
    }
    CloseHandle(h);
    char msg[MAX_PATH+64];
    _snprintf(msg, sizeof msg, "[patch] Loaded: %s (%lu bytes)\n", path, sz);
    OutputDebugStringA(msg);
    BYTE  **raw_pp = (BYTE**)((BYTE*)data_struct + 4);
    DWORD  *raw_sp = (DWORD*)((BYTE*)data_struct + 8);
    if (*raw_pp && *raw_sp) {
        if (sz == *raw_sp) {
            memcpy(*raw_pp, buf, sz);
            OutputDebugStringA("[patch] OK (same size)\n");
        } else {
            char warn[128];
            _snprintf(warn, sizeof warn, "[patch] SKIP: patch=%lu != buf=%lu\n", sz, *raw_sp);
            OutputDebugStringA(warn);
        }
    }
    HeapFree(GetProcessHeap(), 0, buf);
}


/* ── DialogBoxParamA hook — подмена текста диалога выхода ── */
typedef INT_PTR (WINAPI *DialogBoxParamA_t)(HINSTANCE,LPCSTR,HWND,DLGPROC,LPARAM);
static DialogBoxParamA_t g_orig_DialogBoxParamA = NULL;

static DLGPROC g_orig_dlg_proc = NULL;

static INT_PTR CALLBACK patched_dlg_proc(HWND hDlg, UINT msg, WPARAM wp, LPARAM lp)
{
    if (msg == WM_INITDIALOG) {
        DLGPROC orig = (DLGPROC)lp;
        SetWindowLongA(hDlg, DWLP_USER, (LONG)orig);
        INT_PTR res = FALSE;
        if (orig)
            res = CallWindowProcA((WNDPROC)orig, hDlg, msg, wp, 0);
        SetDlgItemTextA(hDlg, 1008,
            "\xc7\xe0\xe2\xe5\xf0\xf8\xe8\xf2\xfc\x20\xe8\xe3\xf0\xf3\x2e\x0a"
            "\xc2\xfb\x20\xf3\xe2\xe5\xf0\xe5\xed\xfb\x3f");
        return res;
    }
    DLGPROC orig = (DLGPROC)GetWindowLongA(hDlg, DWLP_USER);
    if (orig)
        return CallWindowProcA((WNDPROC)orig, hDlg, msg, wp, lp);
    return FALSE;
}

static INT_PTR WINAPI hooked_DialogBoxParamA(
    HINSTANCE hInst, LPCSTR tmpl, HWND hWnd, DLGPROC proc, LPARAM param)
{
    char msg[64];
    _snprintf(msg, sizeof msg, "[patch] DialogBoxParamA tmpl=%p\n", tmpl);
    OutputDebugStringA(msg);
    return g_orig_DialogBoxParamA(hInst, tmpl, hWnd, patched_dlg_proc, (LPARAM)proc);
}

extern void our_load_script(void);

#define ADDR_SIZE_JNZ 0x00420c4au

static void mem_patch(void *addr, const void *src, size_t n) {
    DWORD old;
    VirtualProtect(addr, n, PAGE_EXECUTE_READWRITE, &old);
    memcpy(addr, src, n);
    VirtualProtect(addr, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), addr, n);
}

static const DWORD g_callsites[] = {
    0x0042133c, 0x00422745, 0x00422e76, 0x00423120,
};

static void install_hooks(void) {
    /* ── Патчим проверку Shift-JIS Lead-Byte для 100% однобайтного режима (CP1251) ── */
    {
        BYTE nop2[2] = {0x90, 0x90};
        BYTE jmp_eb03[2] = {0xEB, 0x03};
        BYTE jmp_eb05[2] = {0xEB, 0x05};
        BYTE jmp_eb3d[2] = {0xEB, 0x3D};

        BYTE *s1 = (BYTE*)0x0041c2d1u;
        if (s1[0] == 0x76 && s1[1] == 0x24) { mem_patch(s1, nop2, 2); OutputDebugStringA("[patch] Lead-byte 1 patched\n"); }

        BYTE *s2 = (BYTE*)0x0041c4b1u;
        if (s2[0] == 0x76 && s2[1] == 0x29) { mem_patch(s2, nop2, 2); OutputDebugStringA("[patch] Lead-byte 2 patched\n"); }

        BYTE *s3 = (BYTE*)0x0041c6a2u;
        if (s3[0] == 0x76 && s3[1] == 0x2c) { mem_patch(s3, nop2, 2); OutputDebugStringA("[patch] Lead-byte 3 patched\n"); }

        BYTE *s4 = (BYTE*)0x004324deu;
        if (s4[0] == 0x77 && s4[1] == 0x03) { mem_patch(s4, jmp_eb03, 2); OutputDebugStringA("[patch] Lead-byte 4 patched\n"); }

        BYTE *s5 = (BYTE*)0x00432aebu;
        if (s5[0] == 0x77 && s5[1] == 0x05) { mem_patch(s5, jmp_eb05, 2); OutputDebugStringA("[patch] Lead-byte 5 patched\n"); }

        BYTE *s6 = (BYTE*)0x00432d2du;
        if (s6[0] == 0x77 && s6[1] == 0x3d) { mem_patch(s6, jmp_eb3d, 2); OutputDebugStringA("[patch] Lead-byte 6 patched\n"); }
    }

    BYTE nop2[2] = {0x90,0x90};
    BYTE *jnz = (BYTE*)ADDR_SIZE_JNZ;
    if (jnz[0] == 0x75) {
        mem_patch(jnz, nop2, 2);
        OutputDebugStringA("[patch] Size check NOPped\n");
    }
    for (int i = 0; i < 4; i++) {
        BYTE *site = (BYTE*)g_callsites[i];
        if (site[0] != 0xE8) continue;
        BYTE patch[5] = {0xE8};
        *(DWORD*)(patch+1) = (DWORD)our_load_script - (DWORD)(site+5);
        mem_patch(site, patch, 5);
        char msg[64];
        _snprintf(msg, sizeof msg, "[patch] Hooked 0x%08lx\n", g_callsites[i]);
        OutputDebugStringA(msg);
    }

    /* CreateFileA IAT — перехватываем открытие .cpb файлов для redirect в patch\ */
    {
        DWORD prot;
        BYTE **iat = (BYTE**)0x0047b220u;
        VirtualProtect(iat, 4, PAGE_READWRITE, &prot);
        g_orig_CreateFileA_cpb = (CreateFileA_orig_t)(void*)*iat;
        *iat = (BYTE*)(void*)hooked_CreateFileA_cpb;
        VirtualProtect(iat, 4, prot, &prot);
        OutputDebugStringA("[patch] CreateFileA (CPB) hooked\n");
    }

    /* TextOutA IAT */
    {
        DWORD prot;
        BYTE **iat = (BYTE**)0x0047b080u;
        VirtualProtect(iat, 4, PAGE_READWRITE, &prot);
        g_orig_TextOutA = (TextOutA_t)(void*)*iat;
        *iat = (BYTE*)(void*)hooked_TextOutA;
        VirtualProtect(iat, 4, prot, &prot);
        OutputDebugStringA("[patch] TextOutA hooked\n");
    }

    /* SetWindowTextA IAT */
    {
        DWORD prot;
        BYTE **iat = (BYTE**)0x0047b394u;
        VirtualProtect(iat, 4, PAGE_READWRITE, &prot);
        g_orig_SetWindowTextA = (SetWindowTextA_t)(void*)*iat;
        *iat = (BYTE*)(void*)hooked_SetWindowTextA;
        VirtualProtect(iat, 4, prot, &prot);
        OutputDebugStringA("[patch] SetWindowTextA hooked\n");
    }

    /* CreateFontA IAT */
    {
        DWORD prot;
        BYTE **iat = (BYTE**)0x0047b05cu;
        VirtualProtect(iat, 4, PAGE_READWRITE, &prot);
        g_orig_CreateFontA = (CreateFontA_t)(void*)*iat;
        *iat = (BYTE*)(void*)hooked_CreateFontA;
        VirtualProtect(iat, 4, prot, &prot);
        OutputDebugStringA("[patch] CreateFontA hooked\n");
    }
	
	/* DialogBoxParamA IAT */
    {
        DWORD prot;
        BYTE **iat = (BYTE**)0x0047b2f8u;
        VirtualProtect(iat, 4, PAGE_READWRITE, &prot);
        g_orig_DialogBoxParamA = (DialogBoxParamA_t)(void*)*iat;
        *iat = (BYTE*)(void*)hooked_DialogBoxParamA;
        VirtualProtect(iat, 4, prot, &prot);
        OutputDebugStringA("[patch] DialogBoxParamA hooked\n");
    }
}

/* ── Форварды ── */
FARPROC g_GetFileVersionInfoA, g_GetFileVersionInfoW;
FARPROC g_GetFileVersionInfoSizeA, g_GetFileVersionInfoSizeW;
FARPROC g_VerQueryValueA, g_VerQueryValueW;
FARPROC g_VerFindFileA, g_VerFindFileW;
FARPROC g_VerInstallFileA, g_VerInstallFileW;
FARPROC g_VerLanguageNameA, g_VerLanguageNameW;

static void init_forwards(void) {
    char p[MAX_PATH]; HMODULE v;
    GetSystemDirectoryA(p, MAX_PATH); lstrcat(p, "\\version.dll");
    v = LoadLibraryA(p); if (!v) return;
#define L(n) g_##n = GetProcAddress(v, #n)
    L(GetFileVersionInfoA); L(GetFileVersionInfoW);
    L(GetFileVersionInfoSizeA); L(GetFileVersionInfoSizeW);
    L(VerQueryValueA); L(VerQueryValueW);
    L(VerFindFileA);   L(VerFindFileW);
    L(VerInstallFileA); L(VerInstallFileW);
    L(VerLanguageNameA); L(VerLanguageNameW);
#undef L
}

BOOL WINAPI DllMain(HINSTANCE h, DWORD reason, LPVOID r) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(h);
        init_forwards();
        CreateDirectoryA(PATCH_DIR, NULL);
        load_font_from_file();
        load_dict();
        install_hooks();
        OutputDebugStringA("[patch] Ready.\n");
    }
    return TRUE;
}

#define WRAP(sym) void* __stdcall ver_##sym() { return ((void*(*)())g_##sym)(); }
WRAP(GetFileVersionInfoA) WRAP(GetFileVersionInfoW)
WRAP(GetFileVersionInfoSizeA) WRAP(GetFileVersionInfoSizeW)
WRAP(VerQueryValueA) WRAP(VerQueryValueW)
WRAP(VerFindFileA)   WRAP(VerFindFileW)
WRAP(VerInstallFileA) WRAP(VerInstallFileW)
WRAP(VerLanguageNameA) WRAP(VerLanguageNameW)