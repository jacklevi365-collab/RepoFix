import unittest
from more_itertools import value_chain
class ChainRegression(unittest.TestCase):
    def test_iteration_typeerror_propagates(self):
        def values():
            yield 1
            raise TypeError('internal iteration failure')
        it=value_chain(values(),3)
        self.assertEqual(next(it),1)
        with self.assertRaisesRegex(TypeError,'internal iteration failure'): next(it)
    def test_scalars_and_strings(self):
        self.assertEqual(list(value_chain(1,'abc',[2,3])),[1,'abc',2,3])
    def test_uniterable_is_a_scalar(self):
        class Scalar:
            def __iter__(self): raise TypeError('not iterable')
        obj=Scalar()
        self.assertEqual(list(value_chain(obj,[1])),[obj,1])
