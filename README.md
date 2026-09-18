# AkazExecutor

A lightweight Roblox desktop executor with a WebView-based editor and an Aero-inspired dark interface.

## UI

- WebView desktop shell built with PySide6 + Qt WebEngine.
- Explorer sidebar with searchable script tabs.
- Multi-tab Luau editor with line numbers and syntax highlighting.
- Integrated terminal/status area.
- Runtime page for connection state, process ID and detected build.
- Minimal settings page.
- Keyboard shortcuts: **Ctrl+Enter** run, **Ctrl+S** export, **Ctrl+Shift+N** new tab.
- Local assets only; no UI framework or icon CDN is required at runtime.

## Runtime architecture

The Python backend remains separated from the WebView layer. Runtime actions are bridged through Qt WebChannel so the interface can evolve without coupling the editor to the low-level backend.

## Installation

Install the dependencies from `requirements.txt`, including the Qt WebEngine addon used by `QWebEngineView`.

Run:

```text
python src/main.py
```

## Notes

The project is provided for educational and testing purposes. Runtime behavior depends on the current Roblox build and the external offset source used by the backend.
