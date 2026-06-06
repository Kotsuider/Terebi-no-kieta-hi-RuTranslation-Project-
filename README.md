# Проект перевода Terebi no kieta hi на русский язык

## Общие сведения
Перевод делается gemini с последующей редактурой.


## Статус

**Progress:**
`[███░░░░░░░░░░░░░░░░] 15%`

- [x] Хук скриптов
- [x] Хук изображений
- [x] Перевод системного текста
- [ ] Перевод графики
- [ ] Полный перевод
- [ ] Редактура

[Таблица с переводом](https://docs.google.com/spreadsheets/d/1bTiLPGrwKxYp-zPZWDMAJWUjgxtnp7Kt/edit?usp=sharing&ouid=103224880279791937700&rtpof=true&sd=true) .


## Установка
1. Скачайте
2. Распакуйте в папку с игрой.
3. Профит!

## Редактирование патча
Для распаковки используем [Crass](https://ux.getuploader.com/higurashinamizawa/download/6?__cf_chl_tk=CaN0AsaMqXqAdH95CQHt0yXRdLaH2wQbH7WvYgYaMcs-1776547909-1.0.1.1-Cr5fcCA8AW8bCJAXEQ6xrc95Tszmam0BwKD8OJD2ZCg) с командой, аль же через графический интерфейс.
```Crass
crage -d "E:\テレビの消えた日" -O mt=SFMT132049,system="E:\テレビの消えた日\system.arc"
```

Получаем распакованные папки, нам нужна script. 

Испортируем:
```Ruby
ruby as.rb import ./script ./Tereba.xlsx ./patch

```

### Упаковщик

Отредактированные файлы можно упаковать, однако лучше их закинуть в patch 
```Python
python arc_pack.py ./script script.arc system.arc script_original.arc
```
