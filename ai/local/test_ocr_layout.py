import unittest
from ocr import has_column_pairs, order_boxes


def box(x, y, width=120, height=20):
    return [[x,y],[x+width,y],[x+width,y+height],[x,y+height]]


class LayoutTests(unittest.TestCase):
    def test_single_column_stays_rows(self):
        self.assertFalse(has_column_pairs([box(20,y,600) for y in (50,100,150)], 1000))

    def test_two_columns_are_detected(self):
        boxes=[box(x,y) for y in (50,100,150) for x in (40,650)]
        self.assertTrue(has_column_pairs(boxes,1000))

    def test_one_pair_is_not_enough(self):
        self.assertFalse(has_column_pairs([box(40,50),box(650,50)],1000))

    def test_forced_row_order_is_available(self):
        boxes=[box(650,50),box(40,50)]
        self.assertEqual(order_boxes(boxes,'rows'),[boxes[1],boxes[0]])


if __name__ == '__main__':
    unittest.main()
