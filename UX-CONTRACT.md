# UX contract

## Основной поток

1. Пользователь выбирает загрузку с браузера, файл на хосте или URL. Результаты
   сохраняются автоматически в уникальную папку: существующие индексы не перезаписываются.
2. Пока задача работает, повторный запуск недоступен; результат сообщает готовность или ошибку.
3. При открытии обработки фокус переходит к «Текст видео»: полная речь доступна
   страницами по 100 реплик; TXT/Markdown/SRT и копирование содержат весь текст.
   Ниже показаны покрытие и поиск по речи/OCR, но не изображения.
4. Поиск по речи/OCR не запрашивает изображения. Явное открытие момента показывает
   до трёх ближайших кадров; выдача записывается в served.jsonl, как при CLI.

## Состояния и доступность

- Ошибка объясняет следующий шаг и не стирает введённые данные.
- Поиск очищается отдельной доступной кнопкой, не полагаясь на нативный `type=search`.
- Ввод поддерживает IME: поиск не запускается до завершения композиции.
- Сервер по умолчанию доступен только по `127.0.0.1`; это часть модели приватности.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | native select | DESIGN.md | OS popup | browser keyboard |
| Form | create-form / app.js validation | this document | source-specific | API + browser |
| Scrollbar | style.css global | DESIGN.md | none | computed style |
| Toast | status + inline error regions | this document | error/status | browser |
| CRUD | Jobs and Application | web-plan.md | create/read/cancel/delete | tests/test_web_api.py |
| Transcript | transcript_export.py + app.js loadTranscript | current user request: read meeting speech | paged reading/full export/partial video failure | tests/test_transcript_export.py |

## Resource and data lifecycle

Source: user decisions recorded in web-plan.md. Start is manual; no boot service.
One active process at a time; a second start returns an actionable error. Closing
a browser tab leaves work running. Cancel terminates child processes. Completed
jobs persist, but the GPU model never lives in the HTTP process. Warm retention is
not enabled. Finished, failed, stopped and interrupted jobs can be permanently
deleted after confirmation. Deletion removes only the selected job folder with
its index, transcript, frames and diagnostics; source videos and separate uploads
are not removed. A running job must be stopped and reach a terminal state first.
Application shutdown requires no active task and closes the server.
Uploads remain in the data directory; cancelling a partial transfer removes its
partial file. Original host files and existing indexes are not overwritten.
Remote usage uses an SSH tunnel. Host roots are explicitly provided on launch.

Worker progress uses a separate atomic progress.json file, never log parsing.
The canonical job-detail progress element shows the current stage. A percentage
is a measured fraction of that stage (extracted picks), not an ETA or overall
completion estimate. Speech/download/OCR without counters use indeterminate
progress. Only a successfully exited job displays final 100%; errors/cancellation
stop the bar and remain explicitly labelled. Existing jobs without progress files
remain readable. All Windows readiness entries must have allowlisted installers.

## Dependencies and recovery

Readiness reports presence, not a successful hardware benchmark. Per the user's
installation-button request, Windows installation now uses allowlisted package IDs
through hidden PowerShell, after the canonical confirmation dialog. Arbitrary
commands/URLs/paths from HTTP are rejected. WinGet handles installer UAC on the host;
the server is not elevated. Python packages target the application's venv only.
One install at a time; video starts and application shutdown are blocked during it.
The canonical status region and persistent log show pending/success/failure; timeout
in the browser requires checking status before retry. Manual commands/links remain.
User PATH is appended, not replaced; Tesseract language data is per-user. No driver
changes. First speech use can download model weights. Platform OCR languages and
GPU runtime compatibility require real processing tests on the destination host.
The OCR select and readiness page are populated from the host's readiness
response, not from the browser's operating system: Windows exposes Windows OCR,
macOS exposes Apple Vision OCR, and Linux exposes Tesseract. Other OCR engines
are not shown for that host.
Search is bounded to 200 displayed matches with explicit load-more; file browser
uses pages of 100. Query is not placed in URL due to transcript privacy. No form
reset on failure or section change. CLI stderr is retained as job diagnostics.

## Расшифровка совещаний и лекций

Источник решения: пользователь запросил автоматическое сохранение и чтение полного
текста для ручной работы или передачи агенту. Сразу после ASR/субтитров CLI атомарно
сохраняет transcript.txt, transcript.md, transcript.srt и segments.jsonl на хосте,
до анализа кадров. Каждая запись получает отдельную папку. Поздняя ошибка кадров
не закрывает доступ к сохранённой речи и не меняет ошибку видео на успех.
Это расшифровка, не конспект и не распознавание участников; текст не редактируется.
Старые индексы читаются из segments.jsonl без повторного ASR и без записи при GET.
Экспорт не передаёт данные внешним сервисам. Пользователь сам решает, куда отправить
скачанный или скопированный текст. Пустой текст не выдаётся за успешную расшифровку.
Пагинация использует existing api/status/button primitives, не localStorage/URL.
Поздний ответ прежнего задания не заменяет выбранный текст. Во время обновления
страницы чтения старый текст остаётся видимым, ошибку можно повторить. Фоновое
завершение задания не перехватывает фокус; явное открытие прокручивает к тексту.
