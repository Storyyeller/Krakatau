class SSAFunctionBase(object):
    def __init__(self, parent, arguments):
        self.parent = parent
        self.params = list(arguments)

    def replaceVars(self, rdict):
        self.params = [rdict.get(x,x) for x in self.params]