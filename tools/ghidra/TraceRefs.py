#@category JBLGo4
# Usage: -postScript TraceRefs.py 0x4dbf8 0x59a80
from ghidra.app.decompiler import DecompInterface

dec = DecompInterface()
dec.openProgram(currentProgram)
for arg in getScriptArgs():
    addr = toAddr(int(arg, 0))
    raw = getBytes(addr, 32)
    preview = ''.join(chr(x & 0xff) if 32 <= (x & 0xff) < 127 else '.' for x in raw)
    println("TARGET %s %r" % (addr, preview))
    refs = list(getReferencesTo(addr))
    println("REFERENCES %d" % len(refs))
    for ref in refs[:40]:
        src = ref.getFromAddress()
        func = getFunctionContaining(src)
        println("FROM %s IN %s" % (src, func.getName() if func else "?"))
        if func:
            result = dec.decompileFunction(func, 25, monitor)
            if result and result.decompileCompleted():
                println(result.getDecompiledFunction().getC()[:15000])
dec.dispose()
