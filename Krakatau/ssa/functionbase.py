class SSAFunctionBase(object):
    def __init__(self, parent, arguments):
        self.parent = parent
        self._params = list(arguments)

    @property
    def params(self): return self._params

    def replaceVars(self, rdict):
        self._params = [rdict.get(x,x) for x in self._params]