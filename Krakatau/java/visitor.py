# Override this to rename classes
class DefaultVisitor(object):
    def visit(self, obj):
        return obj.print_(self, self.visit)

    def className(self, name): return name
    def methodName(self, cls, name, desc): return name
    def fieldName(self, cls, name, desc): return name
