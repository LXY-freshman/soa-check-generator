import unittest

from soa_generator._compat import ThreadingHTTPServer, dataclass


@dataclass
class _Sample:
    value: int


class RuntimeCompatibilityTests(unittest.TestCase):
    def test_compatibility_layer_exposes_dataclass_and_threaded_server(self):
        self.assertEqual(_Sample(3).value, 3)
        self.assertTrue(hasattr(ThreadingHTTPServer, "serve_forever"))


if __name__ == "__main__":
    unittest.main()
