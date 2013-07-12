from ..ssa import ssa_ops, ssa_jumps, ssa_types, constraints

def makeFilter(fields):
	def filterStatic(graph, **kwargs):
		for b in graph.blocks:
			removed = []
			exceptVar = None

			for op in b.lines:
				if not isinstance(op, ssa_ops.FieldAccess):
					continue
				if (op.target, op.name, op.desc) not in fields:
					continue

				replace = {}

				if op.rval is not None:
					assert(op.rval.type == ssa_types.SSA_INT)
					new = graph.makeVariable(ssa_types.SSA_INT)
					new.const = fields[op.target, op.name, op.desc]
					replace[op.rval] = new

					del b.unaryConstraints[op.rval]
					b.unaryConstraints[new] = constraints.fromConstant(graph.env, new)

				if op.outException is not None:
					assert(exceptVar is None)
					exceptVar = op.outException
					del b.unaryConstraints[op.outException]

				if op.outMonad is not None:
					replace[op.outMonad] = op.params[0]
					del b.unaryConstraints[op.outMonad]

				for op in b.lines:
					op.replaceVars(replace)
				for b2 in b.jump.getSuccessors():
					for phi in b2.phis:
						phi.replaceVars(replace)
				op.rval = op.outException = op.outMonad = None
				removed.append(op)

			if isinstance(b.jump, ssa_jumps.OnException) and b.jump.params[0] == exceptVar:
				temp = b.jump.getExceptSuccessors()
				b.jump = b.jump.constrainJumps(None)
				for b2 in temp:
					for phi in b2.phis:
						phi.removeKey((b, True))
			b.lines = [x for x in b.lines if x not in removed]

	return filterStatic