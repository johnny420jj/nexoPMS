#!/usr/bin/env python
"""Punto de entrada de Django para NexoPMS Web (reutiliza el núcleo POO y ConexionDB)."""

import os
import sys
from pathlib import Path


def main():
    # Agregar la raíz del proyecto (donde viven conexion.py, nexopms.py, etc.) al sys.path
    web_dir = Path(__file__).resolve().parent
    root_dir = web_dir.parent
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nexopms_web.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Django. Instálalo con: pip install django"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
