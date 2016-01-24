# Override this to rename classes
class DefaultVisitor(object):
    def visit(self, obj):
        return obj.print_(self, self.visit)

    # Experimental - don't use!
    def toTree(self, obj):
        if obj is None:
            return None
        return obj.tree(self, self.toTree)

    def className(self, name): return name
    def methodName(self, cls, name, desc): return name
    def fieldName(self, cls, name, desc): return name


class RenameClassesVisitor(DefaultVisitor):
    def __init__(self, targets, name_length):
        self.targets = targets
        self.name_length = name_length

        print self.name_length

    def className(self, name):
        name = name.split('/')
        if self.should_rename(name[-1]):
            name[-1] = 'Class_{}'.format(name[-1])

        return '/'.join(name)

    def should_rename(self, name):
        return self.name_length == 0 or len(name) < self.name_length
