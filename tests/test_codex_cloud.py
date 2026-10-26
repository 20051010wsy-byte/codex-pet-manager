import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw

from codex_cloud import (
    CLOUD_CACHE_KEY,
    CloudPetArtwork,
    parse_cloud_artworks,
    read_cloud_artworks,
    sync_cloud_artworks,
)


def artwork_bytes() -> bytes:
    image = Image.new("RGBA", (1536, 1872), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((30, 30, 150, 170), fill=(255, 255, 255, 255))
    output = BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class FakeStore:
    def __init__(self, value: str):
        self.value = value
        self.closed = False

    def iter_storage_keys(self):
        yield "app://-"

    def contains_script_key(self, storage_key, script_key):
        return storage_key == "app://-" and script_key == CLOUD_CACHE_KEY

    def iter_records_for_script_key(self, storage_key, script_key, **kwargs):
        assert storage_key == "app://-"
        assert script_key == CLOUD_CACHE_KEY
        yield SimpleNamespace(value=self.value, leveldb_seq_number=9)

    def close(self):
        self.closed = True


class CodexCloudTests(unittest.TestCase):
    def test_parses_valid_cloud_cache_and_ignores_unsafe_urls(self) -> None:
        raw = json.dumps(
            {
                "pets": [
                    {
                        "id": "pet_valid123",
                        "spriteVersionNumber": 1,
                        "spritesheetFingerprint": "fingerprint-1",
                        "spritesheetUrl": "https://chatgpt.com/pets/share/sharepet_1/sprite",
                    },
                    {
                        "id": "pet_unsafe",
                        "spriteVersionNumber": 1,
                        "spritesheetUrl": "http://127.0.0.1/pet.png",
                    },
                ]
            }
        )
        records = parse_cloud_artworks(raw)
        self.assertEqual([record.id for record in records], ["pet_valid123"])
        self.assertEqual(records[0].fingerprint, "fingerprint-1")

    def test_reads_latest_value_through_store_factory(self) -> None:
        raw = json.dumps(
            {
                "pets": [
                    {
                        "id": "pet_cached123",
                        "spriteVersionNumber": 1,
                        "spritesheetUrl": "https://chatgpt.com/pets/share/sharepet_2/sprite",
                    }
                ]
            }
        )
        created = []

        def factory(path):
            store = FakeStore(raw)
            created.append((path, store))
            return store

        records, errors = read_cloud_artworks([Path("fake-leveldb")], factory)
        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        self.assertTrue(created[0][1].closed)

    def test_syncs_artwork_and_reuses_matching_fingerprint(self) -> None:
        artwork = CloudPetArtwork(
            id="pet_sync123",
            sprite_version=1,
            spritesheet_url="https://chatgpt.com/pets/share/sharepet_3/sprite",
            fingerprint="same-fingerprint",
        )
        calls = []

        def fetch(url):
            calls.append(url)
            return artwork_bytes(), "png", 1

        with tempfile.TemporaryDirectory() as temp:
            cache = Path(temp)
            first = sync_cloud_artworks(cache, [artwork], fetch)
            second = sync_cloud_artworks(cache, [artwork], fetch)
            self.assertEqual(first.added, 1)
            self.assertEqual(first.failed, 0)
            self.assertEqual(second.unchanged, 1)
            self.assertEqual(len(calls), 1)
            self.assertTrue((cache / artwork.id / "pet.json").is_file())
            self.assertTrue((cache / artwork.id / "spritesheet.png").is_file())


if __name__ == "__main__":
    unittest.main()
