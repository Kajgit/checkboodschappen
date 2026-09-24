from dataclasses import dataclass
from pathlib import Path
import os
import tempfile


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    test_mode: bool = False
    idle_seconds: int = 15 * 60

    @classmethod
    def load(cls) -> "Settings":
        test_mode = os.getenv("BOODSCHAPPENWIJZER_TEST_MODE", os.getenv("GELDWIJZER_TEST_MODE", "0")) == "1"
        default = (Path(tempfile.gettempdir()) / f"boodschappenwijzer-test-{os.getpid()}" if test_mode else
                   Path.home() / "Library" / "Application Support" / "BoodschappenWijzer")
        data_dir = Path(os.getenv("BOODSCHAPPENWIJZER_DATA_DIR", os.getenv("GELDWIJZER_DATA_DIR", default)))
        data_dir.mkdir(parents=True, exist_ok=True)
        return cls(data_dir, test_mode)
