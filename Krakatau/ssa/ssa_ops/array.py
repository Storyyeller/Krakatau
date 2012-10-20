from base import BaseOp
from ..ssa_types import SSA_INT, SSA_OBJECT

from .. import objtypes, excepttypes
from ..constraints import IntConstraint, FloatConstraint, ObjectConstraint, DUMMY

class ArrLoad(BaseOp):
	def __init__(self, parent, args, ssatype, monad):
		super(ArrLoad, self).__init__(parent, [monad]+args, makeException=True)
		self.env = parent.env
		self.rval = parent.makeVariable(ssatype, origin=self)
		self.ssatype = ssatype

	def propagateConstraints(self, m, a, i):
		etypes = ()
		if a.null:
			etypes += (excepttypes.NullPtr,)
			if a.isConstNull():
				return None, ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True), m

		etypes += (excepttypes.ArrayOOB,)
		if i.max < 0:
			eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
			return None, eout, m

		if self.ssatype[0] == 'int':
			rout = IntConstraint.bot(self.ssatype[1])
		elif self.ssatype[0] == 'float':
			rout = FloatConstraint.bot(self.ssatype[1])
		elif self.ssatype[0] == 'obj':
			supers = [(base,dim-1) for base,dim in a.types.supers]
			exact = [(base,dim-1) for base,dim in a.types.exact]
			rout = ObjectConstraint.fromTops(a.types.env, supers, exact)

		eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
		return rout, eout, DUMMY

class ArrStore(BaseOp):
	def __init__(self, parent, args, monad):
		super(ArrStore, self).__init__(parent, [monad]+args, makeException=True)
		self.env = parent.env

	def propagateConstraints(self, m, a, i, x):
		etypes = ()
		if a.null:
			etypes += (excepttypes.NullPtr,)
			if a.isConstNull():
				return ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True), m

		etypes += (excepttypes.ArrayOOB,)
		if i.max < 0:
			eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
			return eout, m

		if isinstance(x, ObjectConstraint):
			exact = [(base,dim-1) for base,dim in a.types.exact]
			allowed = ObjectConstraint.fromTops(a.types.env, exact, [])
			if allowed.meet(x) != allowed:
				etypes += (excepttypes.ArrayStore,)

		eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
		return eout, DUMMY

class ArrLength(BaseOp):
	def __init__(self, parent, args):
		super(ArrLength, self).__init__(parent, args, makeException=True)
		self.env = parent.env
		self.rval = parent.makeVariable(SSA_INT, origin=self)
		self.outExceptionCons = ObjectConstraint.fromTops(parent.env, [], (excepttypes.NullPtr,), nonnull=True)

	def propagateConstraints(self, x):
		etypes = ()
		if x.null:
			etypes += (excepttypes.NullPtr,)
			if x.isConstNull():
				return None, ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)

		excons = eout = ObjectConstraint.fromTops(self.env, [], etypes, nonnull=True)
		rvalcons = IntConstraint.range(32, 0, 1<<31)
		return rvalcons, excons