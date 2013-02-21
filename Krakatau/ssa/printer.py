import itertools, collections
import re

from ..namegen import NameGen
from ssa_types import *
import ssa_ops, ssa_jumps, constraints, subproc

'''Prints out SSA graphs, mostly for debugging purposes'''

class VarNameGen(NameGen):
    varletters = {SSA_INT:'i', SSA_LONG:'j', SSA_FLOAT:'f', SSA_DOUBLE:'d', SSA_OBJECT:'a', SSA_MONAD:'m'}

    def __call__(self, var):
        if var.name:
            return var.name
        if var.const is not None:
            if isinstance(var.const, basestring):
                if  var.decltype[0] == '<null>':
                    prefix = 'cn'
                else:
                    #remove all non alphanumeric and _ characters
                    esc = re.sub(r'\W+', '', var.const)
                    prefix = 'cs{}'.format(esc[:16])
            else:
                prefix = 'c{!r}'.format(var.const)
        else:
            prefix = self.varletters.get(var.type, 'x')
        sep = '_' if prefix[-1] in '0123456789' else ''
        return self.getPrefix(prefix, sep)

class SSAPrinter(object):
    def __init__(self, parent):
        self.parent = parent
        self.counters = collections.defaultdict(itertools.count)
        self.referencedBlocks = set()

        self.namegen = VarNameGen()
        self.aliases = {}
        self.doAlias = 0
        self.doConstraints = 1
        self.hideSinglePhis = 0

    def printVariable(self, var):
        if var in self.aliases:
            return self.aliases[var]
        if self.doAlias:
            orig = var.origin    
            if orig.__class__.__name__ == 'Phi':
                vals = list(set(orig.params))

                if len(vals) == 1 and vals[0] in self.aliases:
                    self.aliases[var] = self.aliases[vals[0]]
                    return self.aliases[var]
            if var.type == ('int',32) and var.const is not None:
                self.aliases[var] = str(var.const).strip('L')
                return self.aliases[var]
        self.aliases[var] = self.namegen(var)
        return self.aliases[var]

    _math_types = (ssa_ops.IAdd, ssa_ops.IDiv, ssa_ops.IMul, ssa_ops.IRem, ssa_ops.ISub)
    _math_types += (ssa_ops.IAnd, ssa_ops.IOr, ssa_ops.IShl, ssa_ops.IShr, ssa_ops.IUshr, ssa_ops.IXor)
    _math_types += (ssa_ops.FAdd, ssa_ops.FDiv, ssa_ops.FMul, ssa_ops.FRem, ssa_ops.FSub)
    _math_symbols = dict(zip(_math_types, '+ / * % - & | << >> >>> ^ + / * % -'.split()))
    
    def printTT(self, tt):
        base, dim = tt
        return base.strip('.') + '[]'*dim

    def printOp(self, op):
        params = [var for var in op.params if var.type != SSA_MONAD]
        rval = [op.rval] if op.rval is not None else []
        exception = [op.outException] if op.outException is not None else []
        outmonad = [op.outMonad] if op.outMonad is not None else []

        #move Monad param to end if we are showing moanads
        if params and params[0].type == SSA_MONAD:
            params = params[1:] + [params[0]]

        params, rval, exception, outmonad = [map(self.printVariable, seq) for seq in (params, rval, exception, outmonad)]
        returned = rval + exception + outmonad

        if isinstance(op, ssa_ops.Phi):
            if not rval:
                return None
            left, right = rval[0], ', '.join(params)
            if left == right and self.hideSinglePhis: #don't display aliased assignments
                return
            else:
                rhs_expr = 'phi({})'.format(right)
                # rhs_expr += '\t' + ', '.join(self.printLabel(k[0])[6:] for k in op.odict)
        elif isinstance(op, ssa_ops.ArrLength):
            rhs_expr = '{}.length'.format(params[0])
        elif isinstance(op, ssa_ops.ArrLoad):
            rhs_expr = '{}[{}]'.format(params[0], params[1])        
        elif isinstance(op, ssa_ops.ArrStore):
            rhs_expr = '{}[{}] = {}'.format(params[0], params[1], params[2])
        elif isinstance(op, ssa_ops.CheckCast):
            rhs_expr = '({}){}'.format(self.printTT(op.target_tt), params[0])        
        elif isinstance(op, ssa_ops.Convert):
            typecode = {SSA_INT:'int', SSA_LONG:'long', SSA_FLOAT:'float', SSA_DOUBLE:'double'}[op.target]
            rhs_expr = '({}){}'.format(typecode, params[0])
        elif isinstance(op, ssa_ops.FCmp):
            rhs_expr = 'fcmp({}, {}, onNan={})'.format(params[0], params[1], op.NaN_val)  
        elif isinstance(op, ssa_ops.FNeg):
            rhs_expr = '-' + params[0]
        elif isinstance(op, ssa_ops.FieldAccess):
            if 'static' in op.instruction[0]:
                ident = '{}.{}'.format(op.target, op.name)
            else:
                ident = '{}.{}'.format(params[0], op.name)

            if 'put' in op.instruction[0]:
                ident = ident + ' = ' + params[-1]
            rhs_expr = ident
        elif isinstance(op, ssa_ops.ICmp):
            rhs_expr = 'icmp({}, {})'.format(*params) 
        elif isinstance(op, ssa_ops.InstanceOf):
            rhs_expr = '{} instanceof {}'.format(params[0], self.printTT(op.target_tt))  
        elif isinstance(op, ssa_ops.Invoke):
            if op.instruction[0] in ('invokevirtual','invokeinterface'):
                suffix = '{}.{}({})'.format(params[0], op.name, ', '.join(params[1:]))
            else:
                suffix = '{}.{}({})'.format(op.target, op.name, ', '.join(params))
            rhs_expr = suffix
        elif isinstance(op, ssa_ops.Monitor):
            code = 'exit' if op.exit else 'enter'
            rhs_expr = 'mon{}({})'.format(code, params[0])          
        elif isinstance(op, ssa_ops.New):
            rhs_expr = 'new {}'.format(self.printTT(op.tt))        
        elif isinstance(op, (ssa_ops.NewArray, ssa_ops.MultiNewArray)):
            dims = params
            base, dim = op.tt 
            dim_exprs = params + ['']*(dim-len(params))
            fmt = 'new {}' + '[{}]'*dim
            rhs_expr = fmt.format(self.printTT((base,0)), *dim_exprs)
        elif isinstance(op, ssa_ops.Throw):
            rhs_expr = 'throw {};'.format(params[0])
        elif isinstance(op, ssa_ops.TryReturn):
            rhs_expr = 'TryReturn()'
        elif isinstance(op, self._math_types):
            code = self._math_symbols[type(op)]
            rhs_expr = '{} {} {}'.format(params[0], code, params[1])
        elif isinstance(op, ssa_ops.Truncate):
            typecode = ('s' if op.signed else 'u') + str(op.width)
            rhs_expr = '({}){}'.format(typecode, params[0])
        else:
            rhs_expr = '!' + op.__class__.__name__

        if rval:
            return rval[0] + ' = ' + rhs_expr
        return rhs_expr

    def printLabel(self, block):
        self.referencedBlocks.add(block)
        return 'Label {}'.format(block.key)

    _if_symbols = "== != < >= > <=".split()
    _cmp_strs = dict(zip(('eq','ne','lt','ge','gt','le'), _if_symbols))
    def printJump(self, jump, nextBlock):
        params = [var for var in jump.params if var.type != SSA_MONAD]
        params = map(self.printVariable, params)

        nsuccessors = jump.getNormalSuccessors()
        fallthrough = nsuccessors[0] if nsuccessors else None

        lines = []
        if isinstance(jump, ssa_jumps.Goto):
            if fallthrough != nextBlock:
                lines.append('Goto ' + self.printLabel(fallthrough))
        elif isinstance(jump, ssa_jumps.If):
            cmp_str = self._cmp_strs[jump.cmp]
            target = nsuccessors[1]

            # decide whether to reverse the condition
            if fallthrough != nextBlock and target == nextBlock:
                cmp_str = self._if_symbols[self._if_symbols.index(cmp_str) ^ 1]
                fallthrough, target = target, fallthrough

            lines.append('if({} {} {})'.format(params[0], cmp_str, params[1]))
            lines.append('\tGoto ' + self.printLabel(target))
            if fallthrough != nextBlock:
                lines.append('\tElse ' + self.printLabel(fallthrough))
        elif isinstance(jump, ssa_jumps.OnException):
            lines.append('OnException({})'.format(params[0]))
            for handler, cset in jump.cs.sets.items():
                lines.append('\t{}: {}'.format(cset.getSingleTType()[0], self.printLabel(handler)))
            if fallthrough is not None and fallthrough != nextBlock:
                lines.append('Goto ' + self.printLabel(fallthrough))
        elif isinstance(jump, (ssa_jumps.Return, ssa_jumps.Rethrow)):
            name = jump.__class__.__name__
            if params:
                lines.append('{}({})'.format(name, ', '.join(params)))
            else:
                lines.append(name)
        elif isinstance(jump, ssa_jumps.Switch):
            lines.append('switch({})'.format(params[0]))

            for target in jump.successors[1:]:
                vals = sorted(jump.reverse[target])
                lines.append('\tCase {}: {}'.format(', '.join(map(str, vals)), self.printLabel(target)))
            if jump.successors[0] != nextBlock:
                lines.append('\tDefault: ' + self.printLabel(jump.successors[0]))
        elif isinstance(jump, subproc.ProcCallOp):
            returned = [var for var in jump.out.values() if var is None or var.type != SSA_MONAD]
            returned = [('N/A' if var is None else self.printVariable(var)) for var in returned]

            instr = ', '.join(params)
            outstr = ', '.join(returned)
            addrstr = self.printLabel(jump.target)
            lines.append('{} = Call<{}>({})'.format(outstr, addrstr, instr))
            assert(fallthrough == jump.fallthrough)
            if fallthrough != nextBlock:
                lines.append('Goto ' + self.printLabel(fallthrough))
        elif isinstance(jump, subproc.DummyRet):
            instr = ', '.join(params)
            lines.append('Ret<{}>({})'.format(self.printLabel(jump.target), instr))
        return lines

    def printConstraint(self, var, constraint):
        con = constraint
        if con is None:
            return self.printVariable(var) + ' INVALID'
        if not con.isBot:# and hasattr(con, 'exact'):
            return con.print_(self.printVariable(var))

    def print_(self):
        parent = self.parent
        linear = parent.blocks
        blocklines = []

        header = 'function {}({})'.format(parent.code.method.name, ', '.join(map(self.printVariable, parent.inputArgs[1:])))
        alllines = [header]

        for i,block in enumerate(linear):
            lines = []
            lines.append('Label {}'.format(block.key))

            ops = [op for op in block.getOps() if not (op.rval and op.rval.type == SSA_MONAD)]
            lines += ['\t' + line for line in map(self.printOp, ops) if line is not None]

            nextBlock = linear[i+1] if i<len(linear)-1 else None
            lines += ['\t' + line for line in self.printJump(block.jump, nextBlock)]
            blocklines.append((block,lines))

        # blocklines = [(lines if block in self.referencedBlocks else lines[1:]) for block,lines in blocklines]    
        blocklines = [lines for block,lines in blocklines]    
        alllines += map('\n'.join, blocklines)

        #print Constraints
        if self.doConstraints:
            conlines = set()
            for block in linear:
                for var,con in block.unaryConstraints.items():
                    conlines.add(self.printConstraint(var, con))
            conlines.discard(None)
            if conlines:
                alllines += ['','Constraints:']
                alllines += sorted(conlines)
        return '\n'.join(alllines)
