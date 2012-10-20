class MonadConstraint(object):
    def __init__(self):
        self.reducible = False
        self.isBot = True

    def join(*cons): return cons[0]
    def meet(*cons): return cons[0]