import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

from PIL import Image, ImageDraw

from pet_core import PetRepository, safe_relative


def make_sheet(path: Path, version: int = 1) -> None:
    size = (1536, 1872) if version == 1 else (1536, 2288)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((30, 30, 150, 170), fill=(255, 255, 255, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")


class PetRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / ".codex"
        self.repo = PetRepository(codex_home=self.root)
        self.repo.ensure_directories()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add_pet(self, pet_id: str = "test-pet", name: str = "测试人物") -> None:
        folder = self.repo.pets_dir / pet_id
        make_sheet(folder / "spritesheet.webp")
        (folder / "pet.json").write_text(
            json.dumps(
                {
                    "id": pet_id,
                    "displayName": name,
                    "description": "本地测试",
                    "spriteVersionNumber": 1,
                    "spritesheetPath": "spritesheet.webp",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_safe_relative_accepts_windows_separator(self) -> None:
        self.assertEqual(
            safe_relative(r"assets\spritesheet.webp"),
            Path("assets") / "spritesheet.webp",
        )
        for invalid in ("/absolute.webp", "../outside.webp", r"C:\outside.webp"):
            with self.assertRaises(ValueError):
                safe_relative(invalid)

    def test_scan_disable_enable_rename_and_delete(self) -> None:
        self.add_pet()
        records = self.repo.scan()
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].enabled)
        self.assertTrue(records[0].valid)

        self.repo.disable("test-pet")
        records = self.repo.scan()
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].enabled)
        self.assertFalse((self.repo.pets_dir / "test-pet").exists())

        self.repo.update_metadata("test-pet", "改名人物", "新说明")
        self.repo.enable("test-pet")
        records = self.repo.scan()
        self.assertTrue(records[0].enabled)
        self.assertEqual(records[0].display_name, "改名人物")

        self.repo.delete("test-pet")
        self.assertEqual(self.repo.scan(), [])

    def test_import_folder_creates_both_locations(self) -> None:
        source = Path(self.temp.name) / "import-source"
        make_sheet(source / "spritesheet.webp")
        (source / "pet.json").write_text(
            json.dumps(
                {
                    "id": "imported",
                    "displayName": "导入人物",
                    "description": "",
                    "spriteVersionNumber": 1,
                    "spritesheetPath": "spritesheet.webp",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        imported = self.repo.import_folder(source)
        self.assertEqual(imported, ["imported"])
        self.assertTrue((self.repo.pets_dir / "imported" / "pet.json").is_file())
        self.assertTrue((self.repo.avatars_dir / "imported" / "avatar.json").is_file())
        self.assertEqual(len(self.repo.scan()), 1)

    def test_import_zip(self) -> None:
        source = Path(self.temp.name) / "zip-source"
        make_sheet(source / "spritesheet.webp")
        (source / "pet.json").write_text(
            json.dumps(
                {
                    "displayName": "Zip 人物",
                    "spriteVersionNumber": 1,
                    "spritesheetPath": "spritesheet.webp",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        archive = Path(self.temp.name) / "pet.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.write(source / "pet.json", "pet.json")
            bundle.write(source / "spritesheet.webp", "spritesheet.webp")
        imported = self.repo.import_zip(archive)
        self.assertEqual(len(imported), 1)
        self.assertEqual(len(self.repo.scan()), 1)

    def test_finds_nested_pet_manifest(self) -> None:
        nested = self.repo.pets_dir / "downloaded" / "nested-pet"
        make_sheet(nested / "spritesheet.webp")
        (nested / "pet.json").write_text(
            json.dumps(
                {
                    "id": "nested-pet",
                    "displayName": "嵌套人物",
                    "spriteVersionNumber": 1,
                    "spritesheetPath": "spritesheet.webp",
                }
            ),
            encoding="utf-8",
        )
        records = self.repo.scan()
        self.assertEqual([record.id for record in records], ["nested-pet"])

    def test_uses_codex_home_environment(self) -> None:
        cloud = Path(self.temp.name) / "cloud"
        with patch.dict("os.environ", {"CODEX_HOME": str(self.root)}, clear=False):
            repo = PetRepository(cloud_dir=cloud)
        self.assertEqual(repo.codex_home, self.root.resolve())

    def test_cloud_cache_is_read_only(self) -> None:
        cloud_pet = self.repo.cloud_dir / "pet_cloud123"
        make_sheet(cloud_pet / "spritesheet.webp")
        (cloud_pet / "pet.json").write_text(
            json.dumps(
                {
                    "id": "pet_cloud123",
                    "displayName": "云端人物",
                    "spriteVersionNumber": 1,
                    "spritesheetPath": "spritesheet.webp",
                }
            ),
            encoding="utf-8",
        )
        record = self.repo.scan()[0]
        self.assertTrue(record.is_cloud)
        self.assertEqual(record.id, "cloud:pet_cloud123")
        self.assertEqual(record.source_label, "Codex 云端缓存")
        with self.assertRaises(ValueError):
            self.repo.disable(record.id)
        with self.assertRaises(ValueError):
            self.repo.delete(record.id)
        with self.assertRaises(ValueError):
            self.repo.update_metadata(record.id, "不可修改", "")

    def test_local_and_cloud_pet_with_same_source_id_stay_separate(self) -> None:
        self.add_pet("pet_duplicate", "本地同名人物")
        cloud_pet = self.repo.cloud_dir / "pet_duplicate"
        make_sheet(cloud_pet / "spritesheet.webp")
        (cloud_pet / "pet.json").write_text(
            json.dumps(
                {
                    "id": "pet_duplicate",
                    "displayName": "云端同名人物",
                    "spriteVersionNumber": 1,
                    "spritesheetPath": "spritesheet.webp",
                }
            ),
            encoding="utf-8",
        )
        records = self.repo.scan()
        self.assertEqual(
            {record.id for record in records},
            {"pet_duplicate", "cloud:pet_duplicate"},
        )


if __name__ == "__main__":
    unittest.main()
