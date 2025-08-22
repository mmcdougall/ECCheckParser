import unittest

from payee_splitter.heuristics import h_fd_number


class HeuristicFunctionTests(unittest.TestCase):
    def test_h_fd_number(self):
        tokens = "ACME FD 123 Service".split()
        idx = h_fd_number(tokens, "ACME FD 123 Service")
        self.assertEqual(idx, 1)


if __name__ == "__main__":
    unittest.main()
