"""Project searches stop between directories, even when they contain no files."""
import queue
import threading
import unittest
from unittest.mock import patch

from app.document_services import ProjectScan


class ProjectScanCancellationTests(unittest.TestCase):
    def scan(self):
        scan = ProjectScan.__new__(ProjectScan)
        scan.cancelled = threading.Event()
        scan.results = queue.Queue(maxsize=1)
        return scan

    def test_cancel_between_empty_directories(self):
        scan = self.scan()
        visited = []

        def directories(*args, **kwargs):
            for index in range(1000):
                visited.append(index)
                if index == 1:
                    scan.cancelled.set()
                yield f"project/{index}", [], []

        with patch("app.document_services.os.walk", directories):
            scan._run("project", "needle", True, False)
        self.assertEqual(visited, [0, 1])
        self.assertTrue(scan.results.empty())

    def test_cancel_releases_full_result_queue(self):
        scan = self.scan()
        scan.results.put(("item", "already-full.md", 0, ""))
        waiting = threading.Event()

        def worker():
            waiting.set()
            scan._put(("item", "next.md", 0, ""))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        self.assertTrue(waiting.wait(1))
        scan.cancelled.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(scan.results.qsize(), 1)


if __name__ == "__main__":
    unittest.main()
