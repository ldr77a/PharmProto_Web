"""tests.product.* 헬퍼(snapshot_fixtures, fakes)를 import 할 수 있게 저장소 루트를 sys.path 에 넣는다."""

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
