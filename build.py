#!/usr/bin/env python3
"""Собирает src/*.py в один файл плагина dist/tropa.plugin."""
import pathlib, py_compile, sys
root = pathlib.Path(__file__).resolve().parent
parts = sorted((root / "src").glob("[0-9][0-9]_*.py"))
out = root / "dist" / "tropa.plugin"
out.parent.mkdir(exist_ok=True)
out.write_text("".join(p.read_text(encoding="utf-8") for p in parts), encoding="utf-8")
py_compile.compile(str(out), cfile=str(root / "dist" / ".check.pyc"), doraise=True)
(root / "dist" / ".check.pyc").unlink()
print(f"{out} — {sum(1 for _ in out.open(encoding='utf-8'))} lines from {len(parts)} parts")
