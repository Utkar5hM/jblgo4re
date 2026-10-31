#@category JBLGo4
# Usage: -postScript FindImmediates.py 0x88 0x905
from ghidra.program.model.scalar import Scalar

values = set(int(arg, 0) for arg in getScriptArgs())
matches = {}
it = currentProgram.getListing().getInstructions(True)
while it.hasNext():
    ins = it.next()
    for index in range(ins.getNumOperands()):
        for obj in ins.getOpObjects(index):
            if isinstance(obj, Scalar) and (obj.getUnsignedValue() in values):
                func = getFunctionContaining(ins.getAddress())
                key = func.getEntryPoint() if func else ins.getAddress()
                matches.setdefault(str(key), []).append("%s %s" % (ins.getAddress(), ins))

println("VALUES %s: %d functions/locations" % ([hex(x) for x in values], len(matches)))
for key, lines in sorted(matches.items()):
    println("FUNCTION/LOCATION %s" % key)
    for line in lines[:12]:
        println("  %s" % line)
