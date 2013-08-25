from ..mixin import ValueType

class IntConstraint(ValueType):
    __slots__ = "width min max".split()

    def __init__(self, width, min_, max_):
        self.width = width
        self.min = min_
        self.max = max_
        # self.isBot = (-min_ == max_+1 == (1<<width)//2)

    @staticmethod
    def range(width, min_, max_):
        if min_ > max_:
            return None
        return IntConstraint(width, min_, max_)

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

    def _key(self): return self.min, self.max

    def join(*cons):
        xmin = max(c.min for c in cons)
        xmax = min(c.max for c in cons)
        if xmin > xmax:
            return None
        res = IntConstraint(cons[0].width, xmin, xmax)
        return cons[0] if cons[0] == res else res

    def meet(*cons):
        xmin = min(c.min for c in cons)
        xmax = max(c.max for c in cons)
        return IntConstraint(cons[0].width, xmin, xmax)

    def __str__(self): return self.print_('?')
    def __repr__(self): return self.print_('?')