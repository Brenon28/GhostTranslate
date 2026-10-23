import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ghosttranslate.single_instance import (  # noqa: E402
    ActivationServer,
    acquire_single_instance,
    notify_running_instance,
    release_single_instance,
)

APP = QApplication.instance() or QApplication(sys.argv)


class MutexTests(unittest.TestCase):
    def test_second_acquire_is_refused_until_release(self):
        name = f"GhostTranslateTest-{uuid.uuid4()}"
        first = acquire_single_instance(name)
        self.assertIsNotNone(first)
        self.assertIsNone(acquire_single_instance(name))
        release_single_instance(first)
        again = acquire_single_instance(name)
        self.assertIsNotNone(again)
        release_single_instance(again)


class ActivationTests(unittest.TestCase):
    def test_second_launch_reaches_running_instance(self):
        # Второй запуск — отдельный процесс: в одном потоке сервер не читает, пока клиент ждёт записи.
        name = f"GhostTranslateTest-{uuid.uuid4()}"
        server = ActivationServer(name)
        self.assertTrue(server.listening)
        received = []
        server.activation_requested.connect(lambda: received.append(True))
        client = subprocess.Popen(
            [sys.executable, "-c", f"import sys; from ghosttranslate.single_instance import notify_running_instance; "
                                   f"sys.exit(0 if notify_running_instance({name!r}) else 1)"],
            cwd=str(ROOT),
        )
        deadline = time.monotonic() + 15
        while (not received or client.poll() is None) and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.01)
        self.assertEqual(client.wait(5), 0)
        self.assertEqual(received, [True])

    def test_no_running_instance_gives_false(self):
        self.assertFalse(notify_running_instance(f"GhostTranslateTest-{uuid.uuid4()}"))


if __name__ == "__main__":
    unittest.main()
