import os
import sys
import tempfile
from pathlib import Path

from make_demo_assets import build


ROOT = Path(__file__).resolve().parents[1]
DEMO_ROOT = Path(tempfile.mkdtemp(prefix="CodexPetManagerScreenshot-"))
DEMO_HOME = DEMO_ROOT / ".codex"

build(DEMO_HOME)
os.environ["CODEX_PET_MANAGER_HOME"] = str(DEMO_HOME)
sys.path.insert(0, str(ROOT))

from pet_manager import main


if __name__ == "__main__":
    main()
