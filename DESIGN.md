---
version: alpha
colors:
  ink: "#142018"
  paper: "#f6f5ee"
  panel: "#fffefa"
  lime: "#d7f33b"
  muted: "#667267"
  danger: "#a8341f"
typography:
  display:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
  body:
    fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif"
rounded:
  DEFAULT: "3px"
spacing:
  page: "28px"
  panel: "24px"
components:
  action:
    emphasis: "lime solid"
  panel:
    border: "1px solid #d8dcd1"
---

## Overview

Локальный рабочий интерфейс для человека, который проверяет, что действительно показано в видео. Это продуктовая поверхность: спокойная и плотная, а не маркетинговая страница. Узнаваемый жест — кислотно-лаймовая точка и основное действие: она обозначает доказательство, не декор.

## Colors

Тёплая бумага отделяет рабочую область от «тёмного терминала», тёмно-зелёный держит текст читаемым. Лайм используется только для главного действия и маркера бренда. Красный означает только потерю покрытия или ошибку.

## Typography

Крупный, плотный заголовок задаёт принцип продукта. Обычный интерфейсный текст остаётся нейтральным и системным; технические идентификаторы кадров используют monospace.

## Layout

Три раздела: Новое видео, Обработки, Готовность. Создание содержит источник,
распознавание и качество. На широком экране источник и распознавание стоят рядом,
на узком — последовательно. Результаты открываются в Обработках; кадры только явно.

## Elevation & Depth

Панели отделены тонкой рамкой. Нативный HTML dialog с showModal используется для
файлового выбора и подтверждения остановки; он обеспечивает inert-фон и Escape.

## Shapes

Небольшой радиус подчёркивает инструментальный характер продукта; круглые элементы допустимы только для маркера.

## Components

Основная кнопка всегда запускает только один понятный процесс и становится недоступной на время индексации. Поиск дебаунсится на 300 мс, поддерживает IME и имеет явную очистку. Все действия — нативные кнопки.

Runtime ownership (Model B): `frameproof/assets/web/style.css` owns tokens.
The colors above mirror same-named CSS variables (--ink, --paper, --panel,
--lime, --muted, --danger). --body owns body/display fallback; --radius owns
control radius. Canonical global scrollbar uses --thumb/--track/--hover/--active.
No framework adapter or generated token layer. Native selects deliberately retain
OS popup geometry and keyboard behavior. All inputs have visible labels.

## Do's and Don'ts

Не показывать кадры в результатах поиска, превью или автоматически. Не скрывать состояние покрытия за цветом: всегда выводить текст. Не слушать интерфейс на внешнем IP по умолчанию.
