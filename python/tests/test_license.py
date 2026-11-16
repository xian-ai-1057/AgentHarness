"""授權檔：python/ 底下的 LICENSE、NOTICE 要和根目錄的一樣。

Python 套件從 python/ 建置，拿不到根目錄的檔案，所以複製一份放進來
（pyproject.toml 的 license-files 會把它們打包進 wheel）。改了根目錄的
版本卻忘了同步時，這個測試會失敗。
"""

from pathlib import Path

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_license_files_match_repo_root(name: str) -> None:
    root_copy = REPO_ROOT / name
    if not root_copy.exists():
        pytest.skip("不在完整的 repo 裡執行")
    assert (PYTHON_ROOT / name).read_bytes() == root_copy.read_bytes(), (
        f"python/{name} 和根目錄的 {name} 不一樣，請執行 "
        f"cp {name} python/{name}"
    )
