# Windows-first web application acceptance

Confirmed scope: manual start on Windows/Linux/macOS, browser access locally or
remotely, no boot service; upload a client file, select a host file, URL input,
optional subtitles, clear speech/OCR and frame settings, dependency diagnostics,
existing indexes, durable job results, cancellation and application shutdown.

GPU processing must live in a child process and exit after completion/cancellation.
The web server must not import GPU model runtimes. Keep-loaded mode is deliberately
not a prerequisite: resource release by default is the user's priority.

Dependency UI provides exact installation commands and official links. It does not
execute arbitrary installation commands or change drivers. Packages belong in the
application venv. MLX remains the Apple Silicon path; faster-whisper is deferred
until comparative measurements justify adding a third runtime.

Remote access initially uses SSH forwarding, keeping authenticated SSH as the access
boundary. File browser is restricted to explicitly configured host roots. No full
disk browsing, arbitrary OCR commands or browser-cookie access through HTTP.

Acceptance evidence must distinguish synthetic subprocess/API tests, real FFmpeg
processing and browser tests from hardware-dependent speech/OCR tests. Only Windows
can be declared tested on this host; macOS/Linux remain unverified until run there.
