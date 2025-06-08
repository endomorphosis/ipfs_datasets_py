
import unittest

class SimpleTests(unittest.TestCase):
    def test_addition(self):
        self.assertEqual(1 + 1, 2)

    def test_string(self):
        self.assertEqual("hello" + " world", "hello world")
                