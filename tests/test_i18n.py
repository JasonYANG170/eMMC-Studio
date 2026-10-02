"""Language selection, message coverage, data preservation and CLI help tests."""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import cli
import i18n


class Languages(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("zh-CN")

    def test_locale_precedence_and_explicit_override(self):
        for env, expected in [
            ({"LANG": "zh_CN.UTF-8"}, "zh-CN"),
            ({"LANG": "en_US.UTF-8"}, "en"),
            ({"LANG": "zh_CN.UTF-8", "LC_ALL": "C"}, "en"),
            ({"LANG": "en_US", "LC_MESSAGES": "zh_TW.UTF-8"}, "zh-CN"),
            ({"EMMC_STUDIO_LANG": "en", "LANG": "zh_CN"}, "en"),
            ({}, "en"),
        ]:
            self.assertEqual(i18n.resolve_language(environ=env), expected)
            self.assertEqual(i18n.resolve_language("zh-CN", env), "zh-CN")
            self.assertEqual(i18n.resolve_language("en", env), "en")

    def test_translation_preserves_parameters_and_unknown_data(self):
        i18n.set_language("en")
        self.assertEqual(
            i18n.t("已清理 {0} 项，文件释放 {1}。", [3, "4 MiB"]),
            "Cleaned 3 items; freed 4 MiB of files.",
        )
        self.assertEqual(i18n.t("/dev/mmcblk2boot0"), "/dev/mmcblk2boot0")
        self.assertEqual(i18n.t("我的文件.txt"), "我的文件.txt")
        self.assertEqual(
            i18n.t("找不到存储区域：/dev/测试；请先运行 devices"),
            "Storage region not found: /dev/测试; run devices first",
        )
        self.assertEqual(
            i18n.t("密码长度应为 8–128 个字符"),
            "Password must contain 8–128 characters",
        )

    def test_templates_are_complete_and_english_has_no_chinese(self):
        for key, value in i18n.ENGLISH.items():
            self.assertEqual(
                set(re.findall(r"\{\d+\}", key)),
                set(re.findall(r"\{\d+\}", value)),
                key,
            )
            self.assertFalse(re.search(r"[\u3400-\u9fff]", value), key)

    def test_status_localization_leaves_paths_labels_and_ids_unchanged(self):
        i18n.set_language("en")
        raw = {
            "phase": "读回校验",
            "path": "/数据/备份.img",
            "label": "备份库",
            "id": "abc",
            "nested": [{"error": "路径越界"}],
        }
        output = i18n.localize_status(raw)
        self.assertEqual(output["phase"], "Read-back verification")
        self.assertEqual(
            output["nested"][0]["error"], "Path escapes the selected partition"
        )
        for field in ("path", "label", "id"):
            self.assertEqual(output[field], raw[field])
        self.assertEqual(raw["phase"], "读回校验")

    def test_json_and_file_content_do_not_get_translated(self):
        i18n.set_language("en")
        for argv, value in [
            (["--json", "jobs", "list"], {"phase": "读回校验", "label": "备份库"}),
            (["files", "cat", "/dev/test", "file"], {"text": "读回校验\n我的文件"}),
        ]:
            args = cli.parser().parse_args(argv)
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                cli.display(value, args)
            if args.json:
                self.assertEqual(json.loads(stream.getvalue()), value)
            else:
                self.assertEqual(stream.getvalue(), value["text"])

    def test_help_language_is_applied_before_parser_creation(self):
        for lang, expected in [("en", "Partition tables"), ("zh-CN", "分区表")]:
            output = subprocess.run(
                [sys.executable, str(Path(cli.__file__)), "--lang", lang, "--help"],
                capture_output=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                check=True,
            ).stdout
            self.assertIn(expected, output)
            self.assertIn("--lang", output)
            if lang == "en":
                self.assertFalse(re.search(r"[\u3400-\u9fff]", output))


if __name__ == "__main__":
    unittest.main()
