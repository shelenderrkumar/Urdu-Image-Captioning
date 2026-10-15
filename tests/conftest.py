import pytest
from PIL import Image


@pytest.fixture
def images():
    return [Image.new("RGB", (40, 30), c) for c in ("red", "green", "blue")]
