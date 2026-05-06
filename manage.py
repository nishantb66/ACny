#!/usr/bin/env python
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    # Render sometimes uses `python manage.py runserver`; ensure external bind.
    if len(sys.argv) >= 2 and sys.argv[1] == "runserver":
        has_addrport = any(not arg.startswith("-") for arg in sys.argv[2:])
        if not has_addrport:
            port = os.getenv("PORT", "8000")
            sys.argv.append(f"0.0.0.0:{port}")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
