import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from repofix.config import load_env_file


class ConfigTests(unittest.TestCase):
    def test_literal_values_and_existing_environment_precedence(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {}, clear=True),
        ):
            file = Path(tmp) / ".env"
            file.write_text(
                '# config\nDEEPSEEK_MODEL="fixture"\nDEEPSEEK_API_KEY=$(not-executed)\n'
            )
            os.environ["DEEPSEEK_MODEL"] = "existing"
            load_env_file(file)
            self.assertEqual(os.environ["DEEPSEEK_MODEL"], "existing")
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "$(not-executed)")

    def test_invalid_file_never_echoes_secret_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / ".env"
            file.write_text("BAD_NAME=private-value\n")
            with self.assertRaises(ValueError) as error:
                load_env_file(file)
            self.assertNotIn("private-value", str(error.exception))
