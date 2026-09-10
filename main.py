"""Entrada do playground sem instalação: `python main.py demo`.

Acrescenta `src/` ao caminho de importação e delega para `travel_mas.cli`. Com o pacote instalado
(`pip install -e .`), `python -m travel_mas` e `travel-mas` fazem o mesmo.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from travel_mas.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
