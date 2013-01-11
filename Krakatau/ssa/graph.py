import itertools, collections, copy
ODict = collections.OrderedDict

from .ssa_types import *
from . import blockmaker,constraints, variablegraph, objtypes, subproc
from . import ssa_jumps, ssa_ops
from ..verifier.descriptors import parseUnboundMethodDescriptor
from .. import graph_util
# nt = collections.namedtuple

from .. import namegen
makename = namegen.NameGen()

class SSA_Graph(object):
	entryKey, returnKey, rethrowKey = -1,-2,-3

	def __init__(self, code):
		self.code = code
		self.class_ = code.class_
		self.env = self.class_.env

		method = code.method
		inputTypes, returnTypes = parseUnboundMethodDescriptor(method.descriptor, self.class_.name, method.static)

		#entry point
		# funcArgs = [self.makeVarFromVtype(vt) for vt in inputTypes if not (vt.cat2 and vt.top)]
		funcArgs = map(self.makeVarFromVtype, inputTypes)
		funcInMonad = self.makeVariable(SSA_MONAD)
		entryslots = slots_t(monad=funcInMonad, locals=funcArgs, stack=[])
		self.inputArgs = [funcInMonad] + funcArgs

		entryb = BasicBlock(self.entryKey, lines=[], jump=ssa_jumps.Goto(self, 0))
		entryb.successorStates = ODict([((0, False), entryslots)])
		entryb.tempvars = [x for x in self.inputArgs if x is not None]
		del entryb.sourceStates

		#return 
		newmonad = self.makeVariable(SSA_MONAD)
		newstack = map(self.makeVarFromVtype, returnTypes)[:1] #make sure not to include dummy if returning double/long
		returnb = BasicBlock(self.returnKey, lines=[], jump=ssa_jumps.Return(self, [newmonad] + newstack))
		returnb.inslots = slots_t(monad=newmonad, locals=[], stack=newstack)
		returnb.tempvars = []

		#rethrow
		newmonad, newstack = self.makeVariable(SSA_MONAD), [self.makeVariable(SSA_OBJECT)]
		rethrowb = BasicBlock(self.rethrowKey, lines=[], jump=ssa_jumps.Rethrow(self, [newmonad] + newstack))
		rethrowb.inslots = slots_t(monad=newmonad, locals=[], stack=newstack)
		rethrowb.tempvars = []

		self.entryBlock, self.returnBlock, self.rethrowBlock = entryb, returnb, rethrowb
		self.blocks = None
		# self.procs = ''
		# self.uninitMap = collections.defaultdict(list)

	def condenseBlocks(self):
		old = self.blocks

		sccs = graph_util.tarjanSCC([self.entryBlock], lambda block:block.jump.getSuccessors())
		sccs = list(reversed(sccs))
		self.blocks = list(itertools.chain.from_iterable(map(reversed, sccs)))
		
		if len(self.blocks) < len(old):
			kept = set(self.blocks)

			for block in self.blocks:
				for phi in block.phis:
					pairs = [(k,v) for k,v in phi.odict.items() if k[0] in kept]
					phi.updateDict(pairs)

			if self.returnBlock not in kept:
				self.returnBlock = None
			if self.rethrowBlock not in kept:
				self.rethrowBlock = None		

			for proc in self.procs:
				proc.callops = ODict((op,block) for op,block in proc.callops.items() if block not in kept)
				if proc.callops:
					assert(proc.target in kept)
				if proc.retblock not in kept:
					for block in proc.callops.values():
						block.jump = ssa_jumps.Goto(self, proc.target)
					proc.callops = None
			self.procs = [proc for proc in self.procs if proc.callops]

	def removeUnusedVariables(self):
		for proc in self.procs:
			keys = proc.callops.keys()[0].out.keys()
			for key in keys:
				if all(op.out[key] is None for op in proc.callops):
					for op in proc.callops:
						del op.out[key]
					del proc.retop.input[key]
		#################################################################
		roots = [x for x in self.inputArgs if x is not None]
		for block in self.blocks:
			roots += block.jump.params
		reachable = graph_util.topologicalSort(roots, lambda var:(var.origin.params if var.origin else []))

		keepset = set(reachable)
		def filterOps(oldops):
			newops = []
			for op in oldops:
				#if any of the params is being removed due to being unreachable, we can assume the whole function can be removed
				#else if any of the outputs are still needed, keep the function
				# keep = keepset.issuperset(op.params) or not keepset.isdisjoint(op.getOutputs())
				keep = keepset.issuperset(op.params) and not keepset.isdisjoint(op.getOutputs())
				if keep:
					newops.append(op)
					keepset.update(op.getOutputs()) #temp hack
				else:
					assert(keepset.isdisjoint(op.getOutputs()))
			return newops

		for block in self.blocks:
			block.phis = filterOps(block.phis)
			block.lines = filterOps(block.lines)
			block.filterVarConstraints(keepset)
		#################################################################
		for proc in self.procs:
			for op in proc.callops:
				for k, v in op.out.items():
					if v not in keepset:
						op.out[k] = None
			phis = proc.target.phis 
			for op, block in proc.callops.items():
				pvars = set(phi.odict[block,False] for phi in phis)
				op.input = ODict((k,v) for k,v in op.input.items() if v in pvars)
			assert(len(set(tuple(op.input.keys()) for op in proc.callops)) == 1)

	def _getSources(self):
		sources = collections.defaultdict(set)
		for block in self.blocks:
			for child in block.getSuccessors():
				sources[child].add(block)
		return sources

	def mergeSingleSucessorBlocks(self):
		replace = {}
		removed = set()

		# #Make sure that all single jsr procs are inlined first
		self.inlineSubprocs(onlySingle=True)

		sources = self._getSources()
		for block in self.blocks:
			if block in removed:
				continue
			while 1:
				successors = set(block.jump.getSuccessorPairs()) #Warning - make sure not to merge if we have a single successor with a double edge
				if len(successors) != 1:
					break

				#We don't bother modifying sources upon merging since the only property we care about is number of successors, which will be unchanged
				child = successors.pop()[0]
				if len(sources[child]) != 1:
					break

				#We've decided to merge the blocks, now do it
				block.unaryConstraints.update(child.unaryConstraints)

				for phi in child.phis:
					old, new = phi.rval, phi.params[0]
					new = replace.get(new,new)
					replace[old] = new

					uc1 = block.unaryConstraints[old]
					uc2 = block.unaryConstraints[new]
					block.unaryConstraints[new] = constraints.join(uc1, uc2)
					del block.unaryConstraints[old]
				
				block.lines += child.lines
				block.jump = child.jump

				self.returnBlock = block if child == self.returnBlock else self.returnBlock
				self.rethrowBlock = block if child == self.rethrowBlock else self.rethrowBlock
				for proc in self.procs:
					proc.retblock = block if child == proc.retblock else proc.retblock
					#callop values and target obviously cannot be child
					proc.callops = ODict((op, (block if old==child else old)) for op, old in proc.callops.items())

				#remember to update phis of blocks referring to old child!
				for successor in block.jump.getSuccessors():
					for phi in successor.phis:
						phi.replaceBlocks({child:block})

				child.zombie = True
				removed.add(child)
		self.blocks = [b for b in self.blocks if b not in removed]	
		#Fix up replace dict so it can handle multiple chained replacements
		for old in replace.keys()[:]:
			while replace[old] in replace:
				replace[old] = replace[replace[old]]
		if replace:
			for block in self.blocks:
				for op in block.phis + block.lines:
					op.replaceVars(replace)
				block.jump.replaceVars(replace)
		if removed:
			print len(removed), 'blocks merged,', len(replace), 'variables merged'

	def disconnectConstantVariables(self):
		counter = 0
		for block in self.blocks:
			for var, uc in block.unaryConstraints.items():
				if var.origin is not None:
					newval = None
					if var.type[0] == 'int':
						if uc.min == uc.max:
							newval = uc.min
					elif var.type[0] == 'obj':
						if uc.isConstNull():
							newval = 'null'

					if newval is not None:
						var.origin.removeOutput(var)
						var.origin = None
						var.const = newval
						counter += 1
			block.phis = [phi for phi in block.phis if phi.rval is not None]
		if counter: 
			print counter, 'variables disconnected'
		self._conscheck()

	def _conscheck(self):
		sources = self._getSources()
		for block in self.blocks:
			for phi in block.phis:
				if not phi.odict:
					assert(not sources[block])
				else:
					parents = zip(*phi.odict)[0]
					assert(set(parents) == sources[block])
				assert(phi.rval in block.unaryConstraints)
		for proc in self.procs:
			for callop in proc.callops:
				assert(set(proc.retop.input) == set(callop.out))

	def pessimisticPropagation(self):
		assert(not self.procs)
		counter = 0
		graph = variablegraph.makeGraph(self.env, self.blocks)
		variablegraph.processGraph(graph)
		for block in self.blocks:
			for var, oldUC in block.unaryConstraints.items():
				newUC = graph[var].output[0]
				# var.name = makename(var)
				if newUC is None:
					del block.unaryConstraints[var]
					if var.origin is not None:
						var.origin.removeOutput(var)
					#hopefully raise an error if we accidently use it later
					# del var.origin, var.const, var.type
					var.name = "UNREACHABLE"
					# var.name += '-'
					counter += 1
				else:
					newUC = constraints.join(oldUC, newUC)
					if newUC != oldUC:
						counter += 1
					block.unaryConstraints[var] = newUC
		if counter: 
			print counter, 'variables constrained'
		self._conscheck()

	def pruneInferredUnreachable(self):
		self._conscheck()
		badblocks = set()
		for block in self.blocks:
			param_ucs = map(block.unaryConstraints.get, block.jump.params)
			if None in param_ucs and not isinstance(block.jump, ssa_jumps.OnException):
				badblocks.add(block)
				continue

			impossible = []
			impossible2 = set(block.jump.getSuccessorPairs())
			if isinstance(block.jump, ssa_jumps.OnException):
				if None in param_ucs:
					for child in block.jump.getExceptSuccessors():
						impossible.append((child, True))
			
			block.jump = block.jump.reduceSuccessors(impossible)
			temp = set(block.jump.getSuccessorPairs())
			assert((set(impossible)-temp) == (impossible2-temp))

			for child,t in set(impossible)-temp:
				# print 'removing {} from {}'.format(block, child)
				for phi in child.phis:
					phi.removeKey((block,t))
		self.condenseBlocks()
		assert(badblocks.isdisjoint(self.blocks))
		self._conscheck()

	def simplifyJumps(self):
		self._conscheck()
		#Determine if any jumps are impossible based on known constraints of params: if(0 == 0) etc
		counter = 0
		for block in self.blocks:
			if hasattr(block.jump, 'constrainJumps'):
				assert(block.jump.params)
				oldEdges = block.jump.getSuccessorPairs()
				UCs = map(block.unaryConstraints.get, block.jump.params)
				block.jump = block.jump.constrainJumps(*UCs)
				newEdges = block.jump.getSuccessorPairs()
				if newEdges != oldEdges:
					pruned = [x for x in oldEdges if x not in newEdges]
					for (child,t) in pruned:
						for phi in child.phis:
							phi.removeKey((block,t))
					counter += 1
		if counter: 
			print counter, 'jumps constrained'	
		self._conscheck()

	def _duplicateRegion(self, region, callblock, target, retblock):
		blockmap = {}
		varmap = {}
		opmap = {None:None}

		newblocks = []
		#create blocks and variables
		for block in region:
			newb = BasicBlock(key=(block.key, callblock.key), lines=None, jump=None)
			del newb.sourceStates
			blockmap[block] = newb
			newblocks.append(newb)

			for var, UC in block.unaryConstraints.items():
				new = copy.copy(var)
				varmap[var] = new
			newb.unaryConstraints = ODict((varmap[var],UC) for var,UC in block.unaryConstraints.items())

		#now fill in phis, ops, and jump
		for block in region:
			newb = blockmap[block]

			newb.phis = []
			for phi in block.phis:
				pairs = [((blockmap.get(sb,sb),t),varmap.get(var,var)) for (sb,t),var in phi.odict.items()]
				new = ssa_ops.Phi(self, ODict(pairs), varmap[phi.rval])
				new.block = newb
				newb.phis.append(new)
				opmap[phi] = new

			newb.lines = []
			for op in block.lines:
				new = copy.copy(op)
				new.replaceVars(varmap)
				new.replaceOutVars(varmap)
				newb.lines.append(new)
				opmap[op] = new

			if block != retblock:
				assert(not isinstance(block.jump, (subproc.ProcCallOp, subproc.DummyRet)))
				new = block.jump.clone()
				new.replaceVars(varmap)
				#jump.replaceBlocks expects to have a valid mapping for every existing block
				#quick hack, create temp dictionary
				tempmap = {b:b for b in new.getSuccessors()}
				tempmap.update(blockmap)
				new.replaceBlocks(tempmap)
				newb.jump = new

			for var in newb.unaryConstraints:
				var.origin = opmap[var.origin]
		
		#now add new blocks into phi dicts of abscond successors
		dupedSet = frozenset(newblocks) | frozenset(region)
		for block in region:
			if block != retblock:
				newb = blockmap[block]
				temp = block.jump.getSuccessorPairs()
				temp = [(k,v) for k,v in temp if k not in dupedSet]

				for child,t in temp:
					for phi in child.phis:
						assert((newb,t) not in phi.odict)
						var = varmap[phi.odict[block,t]]
						phi.updateDict(phi.odict.items() + [((newb,t), var)])	

		#disconnect from existing jsr target
		for phi in target.phis:
			pairs = [(k,v) for k,v in phi.odict.items() if k[0] != callblock]
			phi.updateDict(pairs)
		return newblocks, blockmap, varmap

	def inlineSubprocs(self, onlySingle=False):
		self._conscheck()
		if not self.procs:
			return
		counter = 0
		#establish DAG of subproc callstacks if we're doing nontrivial inlining, since we can only inline leaf procs
		if not onlySingle:
			sources = self._getSources()
			regions = {}
			for proc in self.procs:
				region = graph_util.topologicalSort([proc.retblock], lambda block:([] if block == proc.target else sources[block]))
				assert(self.entryBlock not in region)
				regions[proc] = frozenset(region)

			parents = {proc:[] for proc in self.procs}
			for x,y in itertools.product(self.procs, repeat=2):
				if regions[x] < regions[y]:
					parents[x].append(y)
			self.procs = graph_util.topologicalSort(self.procs, parents.get)

		#now inline the procs
		for proc in reversed(self.procs):
			sources = self._getSources()
			region = graph_util.topologicalSort([proc.retblock], lambda block:([] if block == proc.target else sources[block]))

			pairs = proc.callops.items()
			while (len(pairs) == 1) or (not onlySingle and len(pairs) >= 1):
				callop, callblock = pairs.pop()

				if pairs:
					assert(not onlySingle)
					newblocks, blockmap, varmap = self._duplicateRegion(region, callblock, proc.target, proc.retblock)
					self.blocks += newblocks

					newregion = newblocks
					newEntryBlock = blockmap[proc.target]
					newExitBlock = blockmap[proc.retblock]
					print 'Inlining subroutine with {} blocks'.format(len(newregion))
				else: #if there's only one call left, don't duplicate, just inline in place
					newregion = region
					newEntryBlock = proc.target
					newExitBlock = proc.retblock
					varmap = {}

				#now fill in JSR specific stuff and insert it
				#add jump to newexit first so it can safely be accessed in skipvar loop
				newExitBlock.jump = ssa_jumps.Goto(self, callop.fallthrough)

				#first we find any vars that bypass the proc since we have to pass them through the new blocks
				skipvars = [phi.odict[callblock,False] for phi in callop.fallthrough.phis]
				skipvars = [var for var in skipvars if var.origin is not callop]

				svarcopy = {}
				newphis = {}
				for var, block in itertools.product(skipvars, newregion):
					svarcopy[var, block] = new = copy.copy(var)
					phi = ssa_ops.Phi(self, [], new)
					phi.block = block
					new.origin = phi 
					block.phis.append(phi)
					newphis[var, block] = phi 
					block.unaryConstraints[new] = callblock.unaryConstraints[var]

				for var, block in itertools.product(skipvars, newregion):
					for child, t in block.jump.getSuccessorPairs():
						if child in newregion:
							phi = newphis[var, child]
							phi.updateDict(phi.odict.items() + [((block,t), svarcopy[var,block])])

				#Fix phis of entryblock
				for phi in newEntryBlock.phis:
					if phi.odict:
						pair = (callblock,False), phi.odict[callblock,False]
						phi.updateDict([pair])
				for var in skipvars:
					phi = newphis[var, newEntryBlock]
					pair = (callblock,False), var
					phi.updateDict([pair])

				ftblock = callop.fallthrough
				callblock.jump = ssa_jumps.Goto(self, newEntryBlock)

				#Now handle exit
				retVarMap = {}
				for key, var in callop.out.items():
					old = proc.retop.input[key]
					retVarMap[var] = varmap.get(old,old) #for inplace inlining, varmap is empty
				for var in skipvars:
					retVarMap[var] = svarcopy[var, newExitBlock]

				for phi in callop.fallthrough.phis:
					pair = (newExitBlock,False), retVarMap[phi.odict[callblock, False]]
					phi.updateDict([pair])
				counter += 1

			proc.callops = ODict(pairs)
		self.procs = [proc for proc in self.procs if proc.callops]
		if counter:
			print counter, 'subprocedure calls inlined'
		self._conscheck()

	def makeVariable(self, *args, **kwargs):
		var = Variable(*args, **kwargs)
		# var.name = 'x' + makename(var)
		return var

	def makeVarFromVtype(self, vtype):
	    type_ = verifierToSSAType(vtype)
	    if type_ is not None:
	        var = self.makeVariable(type_)
	        var.verifier_type = vtype
	        if vtype.isObject:
	        	var.decltype = objtypes.verifierToDeclType(vtype)
	        	# print var, var.decltype
	        return var
	    return None

	def getConstPoolArgs(self, index):
		return self.class_.cpool.getArgs(index)

	def getConstPoolEntry(self, index):
		return self.class_.cpool.pool[index]

	def rawExceptionHandlers(self):
		rethrow_handler = (0, self.code.codelen, self.rethrowKey, 0)
		return self.code.except_raw + [rethrow_handler]

def makePhiFromODict(parent, outvar, d, getter):
	pairs = [(k,getter(v)) for k,v in d.items()]
	return ssa_ops.Phi(parent, ODict(pairs), outvar)

def isTerminal(parent, block):
	return block is parent.returnBlock or block is parent.rethrowBlock

def ssaFromVerified(code, iNodes):
	parent = SSA_Graph(code)

	blocks = [blockmaker.fromInstruction(parent, iNode) for iNode in iNodes if iNode.visited]
	blocks = [parent.entryBlock] + blocks + [parent.returnBlock, parent.rethrowBlock]
	blockDict = {b.key:b for b in blocks}

	#fixup proc info
	jsrs = [block for block in blocks if isinstance(block.jump, subproc.ProcCallOp)]
	procs = ODict((block.jump.target, subproc.ProcInfo(block)) for block in blocks if isinstance(block.jump, subproc.DummyRet))
	for block in jsrs:
		target = blockDict[block.jump.iNode.successors[0]]
		callop = block.jump
		retblock = blockDict[block.jump.iNode.returnedFrom]
		retop = retblock.jump
		assert(isinstance(callop, subproc.ProcCallOp))
		assert(isinstance(retop, subproc.DummyRet))

		#merge states from inodes to create out
		jsrslots = block.successorStates[target.key, False]
		# retslots = retblock.successorStates[callop.iNode.returnPoint, False]
		retslots = retblock.successorStates[block.key, False]

		#Create new variables (will have origin set to callop in registerOuts)
		#Even for skip vars, we temporarily create a variable coming from the ret
		#But it won't be used, and will be later pruned anyway
		newstack = map(copy.copy, retslots.stack)
		newlocals = map(copy.copy, retslots.locals)
		newmonad = copy.copy(retslots.monad)
		newslots = slots_t(monad=newmonad, locals=newlocals, stack=newstack)
		callop.registerOuts(newslots)
		block.tempvars += callop.out.values()

		#The successor state uses the merged locals so it gets skipvars
		zipped = itertools.izip_longest(newlocals, jsrslots.locals, fillvalue=None)
		mask = [mask for entry,mask in retop.iNode.masks if entry==target.key][0]
		merged = [(x if i in mask else y) for i,(x,y) in enumerate(zipped)]
		merged_slots = slots_t(monad=newmonad, locals=merged, stack=newstack)

		block.successorStates[callop.iNode.returnPoint, False] = merged_slots
		del retblock.successorStates[block.key, False]
		# del retblock.successorStates[callop.iNode.returnPoint, False]

		proc = procs[target.key]
		proc.callops[callop] = block 
		assert(proc.target == target.key and proc.retblock == retblock and proc.retop == retop)
		del callop.iNode 
	#Now delete iNodes and fix extra input variables
	procs = procs.values()
	for proc in procs:
		del proc.retop.iNode
		assert(not proc.retblock.successorStates)
		proc.target = blockDict[proc.target]

		ops = proc.callops
		keys = set.intersection(*(set(op.input.keys()) for op in ops))
		for op in ops:
			op.input = ODict((k,v) for k,v in op.input.items() if k in keys)
	parent.procs = procs

	#Propagate successor info
	for block in blocks:
		if isTerminal(parent, block):
			continue

		assert(set(block.jump.getNormalSuccessors()) == set([k for (k,t),o in block.successorStates.items() if not t]))
		assert(set(block.jump.getExceptSuccessors()) == set([k for (k,t),o in block.successorStates.items() if t]))

		#replace the placeholder keys with actual blocks now
		block.jump.replaceBlocks(blockDict)
		for (key, exc),outstate in block.successorStates.items():
			dest = blockDict[key]
			assert(dest.sourceStates.get((block,exc), outstate) == outstate)
			dest.sourceStates[block,exc] = outstate
		del block.successorStates

	#create phi functions for input variables
	for block in blocks:
		if block is parent.entryBlock:
			block.phis = []
			continue
		ins = block.inslots

		ins.monad.origin = makePhiFromODict(parent, ins.monad, block.sourceStates, (lambda i: i.monad))
		for k, v in enumerate(ins.stack):
			if v is not None:
				v.origin = makePhiFromODict(parent, v, block.sourceStates, (lambda i: i.stack[k]))
		for k, v in enumerate(ins.locals):
			if v is not None:
				v.origin = makePhiFromODict(parent, v, block.sourceStates, (lambda i: i.locals[k]))
				assert(v.origin.rval is v)
		# del block.sourceStates, block.inslots
		phivars = [ins.monad] + ins.stack + ins.locals
		block.phis = [var.origin for var in phivars if var is not None]

		for phi in block.phis: #??
			phi.block = block

		for phi in block.phis:
			types = [var.type for var in phi.odict.values()]
			assert(not types or set(types) == set([phi.rval.type]))

	#create unary constraints for each variable
	for block in blocks:
		bvars = list(block.tempvars)
		del block.tempvars
		assert(None not in bvars)
		
		bvars += [phi.rval for phi in block.phis]
		for op in block.lines:
			bvars += op.params
			bvars += op.getOutputs()
		bvars += block.jump.params

		#possibly inefficient, but hey, it's only done once
		for var in bvars:
			block.unaryConstraints[var] = constraints.fromVariable(parent.env, var)

	#Make sure that branch targets are distinct, since this is assumed everywhere
	for block in blocks:
		block.jump = block.jump.reduceSuccessors([])
	parent.blocks = blocks
	
	parent._conscheck()
	return parent