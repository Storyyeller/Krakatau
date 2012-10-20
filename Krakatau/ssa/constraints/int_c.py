import collections, itertools
from ..mixin import ValueType

class IntConstraint(ValueType):
    def __init__(self, width, min, max):
        self.width = width
        self.min = min
        self.max = max
        self.reducible = min<max
        self.isBot = (-min == max+1 == (1<<width)//2)
        # self.isTop = min > max

    @staticmethod
    def range(width, min, max):
        return IntConstraint(width, min, max)

    @staticmethod
    def const(width, val):
        return IntConstraint(width, val, val)

    @staticmethod
    def bot(width):
        return IntConstraint(width, -1<<(width-1), (1<<(width-1))-1)

    def print_(self, varstr):
        if self.min == self.max:
            return '{} == {}'.format(varstr, self.max)
        return '{} <= {} <= {}'.format(self.min, varstr, self.max)

    def _key(self): return self.width, self.min, self.max

    def join(*cons):
        xmin = max(c.min for c in cons)
        xmax = min(c.max for c in cons)
        if xmin > xmax:
            return None
        return IntConstraint(cons[0].width, xmin, xmax)

    def meet(*cons):
        xmin = min(c.min for c in cons)
        xmax = max(c.max for c in cons)
        return IntConstraint(cons[0].width, xmin, xmax)

    def __str__(self): return self.print_('?')
    def __repr__(self): return self.print_('?')