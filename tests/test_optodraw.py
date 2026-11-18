import unittest
from optodraw import Grid

class TestOptodraw(unittest.TestCase):
    def test_grid(self):
        grid = Grid()
        self.assertIsNotNone(grid)

if __name__ == '__main__':
    unittest.main()