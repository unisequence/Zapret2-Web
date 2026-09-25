import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]


class WindowsInstallerEncodingTests(unittest.TestCase):
    def test_non_ascii_powershell_scripts_have_utf8_bom(self):
        for path in ROOT.rglob("*.ps1"):
            data = path.read_bytes()
            if any(byte >= 128 for byte in data):
                with self.subTest(path=path.relative_to(ROOT)):
                    self.assertTrue(data.startswith(b"\xef\xbb\xbf"))
                    data.decode("utf-8-sig")

    @unittest.skipUnless(sys.platform == "win32", "Windows PowerShell test")
    def test_setup_runs_in_windows_powershell_without_network(self):
        launcher = shutil.which("py.exe")
        powershell = shutil.which("powershell.exe")
        if not launcher or not powershell:
            self.skipTest("Python launcher or Windows PowerShell is unavailable")
        probe = subprocess.run(
            [launcher, "-3", "-c", "import sys; sys.exit(sys.version_info < (3, 11))"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        if probe.returncode:
            self.skipTest("Python 3.11+ is unavailable")

        with TemporaryDirectory() as temporary:
            project = Path(temporary)
            scripts = project / "scripts"
            scripts.mkdir()
            shutil.copyfile(ROOT / "scripts" / "setup_windows.ps1", scripts / "setup_windows.ps1")
            (scripts / "bootstrap_windows.ps1").write_text("Write-Host BOOTSTRAP_OK\n", encoding="ascii")
            (project / "run.ps1").write_text("Write-Host RUN_OK\n", encoding="ascii")

            result = subprocess.run(
                [powershell, "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(scripts / "setup_windows.ps1")],
                capture_output=True,
                timeout=90,
                check=False,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 0, output.decode(errors="replace"))
            self.assertIn(b"BOOTSTRAP_OK", output)
            self.assertIn(b"RUN_OK", output)


if __name__ == "__main__":
    unittest.main()
