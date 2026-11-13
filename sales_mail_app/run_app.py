"""デスクトップアプリの起動スクリプト（PyInstaller のエントリポイント）.

`--self-test` を付けると GUI を開かずに依存関係の読み込みだけを確認して終了する（ビルド確認用）。
"""

import sys


def self_test() -> int:
    import tempfile
    from pathlib import Path

    import anthropic  # noqa: F401  AI 機能で使用
    import tkinter  # noqa: F401

    from sales_mailer import __version__
    from sales_mailer.db import Database

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "check.db")
        assert db.list_templates()
    print(f"SalesMailer {__version__} self-test OK (anthropic {anthropic.__version__})")
    return 0


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    from sales_mailer.gui.app import main

    main()
