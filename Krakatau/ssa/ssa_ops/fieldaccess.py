from base import BaseOp
from ...inference_verifier import parseFieldDescriptor
from ..ssa_types import verifierToSSAType, SSA_MONAD

from .. import objtypes, constraints

class FieldAccess(BaseOp):
	def __init__(self, parent, instr, info, args, monad):
		super(FieldAccess, self).__init__(parent, [monad]+args, makeException=True)

		self.instruction = instr
		self.target, self.name, self.desc = info

		if 'get' in instr[0]:
			vtypes = parseFieldDescriptor(self.desc)
			stype = verifierToSSAType(vtypes[0])
			cat = len(vtypes)

			self.rval = parent.makeVariable(stype, origin=self)
			self.returned = [self.rval] + [None]*(cat-1)
		else:
			self.returned = []

		self.outMonad = parent.makeVariable(SSA_MONAD, origin=self)

		#just use a fixed cosntraint until we can do interprocedural analysis
		#output order is rval, exception, monad, defined by BaseOp.getOutputs
		env = parent.env
		self.mout = constraints.DUMMY
		self.eout = constraints.ObjectConstraint.fromTops(env, [objtypes.ThrowableTT], [])
		if self.rval is not None:
			if vtypes[0].isObject:
				decltype = objtypes.verifierToDeclType(vtypes[0])
				self.rout = constraints.ObjectConstraint.fromTops(env, *objtypes.declTypeToActual(env, decltype))
			else:
				self.rout = constraints.fromVariable(env, self.rval)

	def propagateConstraints(self, *incons):
		if self.rval is None:
			return self.eout, self.mout
		return self.rout, self.eout, self.mout