from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Lampiadim_MVP"))
from lampiadim.data import ElectoralData


@pytest.fixture(scope="session")
def data():
    return ElectoralData()
