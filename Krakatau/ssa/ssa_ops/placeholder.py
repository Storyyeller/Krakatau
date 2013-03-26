from .base import BaseOp

class Placeholder(BaseOp):
    def __init__(self, parent, *args, **kwargs):
        super(Placeholder, self).__init__(parent, [])

        self.returned = []
        self.rval = None