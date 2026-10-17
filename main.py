"""Точка входа для Amvera.

Запускает bot/connect.py как __main__, но при этом sys.path[0] = /app,
поэтому импорты `from bot...`, `from database...` работают нативно,
без хака с sys.path внутри connect.py.
"""
import runpy

if __name__ == "__main__":
    runpy.run_path("bot/connect.py", run_name="__main__")