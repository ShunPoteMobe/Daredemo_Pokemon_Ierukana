"""コンソールアプリの起動用スクリプト。 python main.py で実行する。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from pokemon_ierukana.cli import main  # noqa: E402

if __name__ == "__main__":
    main()
