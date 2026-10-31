#@category JBLGo4
# Usage: -postScript DumpFunctions.py 0x576b4 0x4d6d8 ...
from ghidra.app.decompiler import DecompInterface

dec = DecompInterface()
dec.openProgram(currentProgram)
for arg in getScriptArgs():
    addr = toAddr(int(arg, 0))
    func = getFunctionContaining(addr)
    if func is None:
        disassemble(addr)
        func = createFunction(addr, None)
    if func is None:
        println("NO FUNCTION %s" % addr)
        continue
    println("FUNCTION %s %s" % (func.getEntryPoint(), func.getName()))
    refs = list(getReferencesTo(func.getEntryPoint()))
    println("CALLERS %d" % len(refs))
    for ref in refs[:30]:
        src = ref.getFromAddress()
        caller = getFunctionContaining(src)
        println("  %s in %s" % (src, caller.getName() if caller else "?"))
    result = dec.decompileFunction(func, 25, monitor)
    if result and result.decompileCompleted():
        println(result.getDecompiledFunction().getC()[:30000])
    else:
        println("DECOMPILE FAILED")
dec.dispose()
