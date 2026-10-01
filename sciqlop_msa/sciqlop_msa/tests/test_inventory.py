import re
from pathlib import Path

import pytest
import yaml

INVENTORY = yaml.safe_load((Path(__file__).parents[1] / "inventory.yaml").read_text())


@pytest.mark.parametrize("name", INVENTORY)
def test_fname_regex_lets_speasy_keep_the_newest_reprocessing(name):
    regex = re.compile(INVENTORY[name]["fname_regex"])
    prefix = INVENTORY[name]["master_cdf"].rsplit("/", 1)[1].split("_20250108_")[0]
    old = regex.fullmatch(f"{prefix}_20250108_r00-v04-00.cdf")
    new = regex.fullmatch(f"{prefix}_20250108_r01-v00-00.cdf")
    assert old["start"] == new["start"]
    assert (old["version"], new["version"]) == ("r00-v04-00", "r01-v00-00")


@pytest.mark.parametrize("name", INVENTORY)
def test_master_cdf_is_a_current_reprocessing(name):
    master = INVENTORY[name]["master_cdf"].rsplit("/", 1)[1]
    assert re.fullmatch(INVENTORY[name]["fname_regex"], master)["version"].startswith("r01")
