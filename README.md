# Проект перевода Terebi no kieta hi на русский язык

## Общие сведения
Перевод делался с gemini с последующей редактурой. Вычитки не будет.

## Статус

**Progress:**
`[▩▩▩▩▩▩▩▩▩▩▩▩▩▩▩▩▩▩▩▩] 100%`

- [x] Хук скриптов
- [x] Хук изображений
- [x] Перевод системного текста
- [x] Перевод графики
- [x] Полный перевод

## Установка
1. Скачайте
2. Распакуйте в папку.
4. Перенесите и запустите `tvlost-patcher.exe`, готово!
3. Профит!

## Редактирование патча
Для распаковки используем [Crass](https://ux.getuploader.com/higurashinamizawa/download/6?__cf_chl_tk=CaN0AsaMqXqAdH95CQHt0yXRdLaH2wQbH7WvYgYaMcs-1776547909-1.0.1.1-Cr5fcCA8AW8bCJAXEQ6xrc95Tszmam0BwKD8OJD2ZCg) с командой, аль же через графический интерфейс.
```Crass
crage -d "E:\テレビの消えた日" -O mt=SFMT132049,system="E:\テレビの消えた日\system.arc"
```

Получаем распакованные папки, нам нужна script. 
Таблица перевода и решений отсутствует, так что создайте сами.

Упаковка:
запустите build_patch.bat.



# Licenses, Credits & Disclaimers

## Original Game

**Terebi no Kieta Hi (テレビの消えた日)** is a visual novel by **Petit KeroQ (プチケロQ)**. This patch is intended for the original Windows version.

Rights to the original script, characters, artwork, music, voice recordings, game engine, and other original materials belong to their respective rights holders.

## Translation & Patch Credits

The Russian translation, editing, translated interface graphics, and patch-specific modifications are the work of this project's contributors.

This project is not affiliated with or endorsed by the original developer or the game's rights holders.

## Build Tools

- **Tvlost Patcher** applies binary changes to a supported original executable, including Russian interface text and text-rendering fixes. It requires the original executable.
- **ASB/ARC tools** are used to import translated dialogue and choices, update script references, and rebuild AZSystem archives.
- **PNG-to-TYP1 tools** convert translated graphics into the image format used by the game.

These tools do not grant any rights to the original game or its assets.

## Fan Patch Disclaimer

This is a free, unofficial Russian fan translation patch. It requires an installed copy of the original game.

The patch grants no rights to the original game materials. Original game files and third-party components remain subject to their respective licenses and terms.

The patch is provided without warranty. Back up your game files and save data before installation.