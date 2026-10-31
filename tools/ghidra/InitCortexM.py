#@category JBLGo4
# Seed raw ARM Cortex-M images before Ghidra's automatic analysis.
from java.math import BigInteger

mem = currentProgram.getMemory()
start = mem.getMinAddress()
end = mem.getMaxAddress()
ctx = currentProgram.getProgramContext()
tmode = ctx.getRegister("TMode")
ctx.setValue(tmode, start, end, BigInteger.ONE)
println("Image: %s %s..%s" % (currentProgram.getName(), start, end))

# The first words are a Cortex-M vector table. Only odd addresses inside this
# image are Thumb code pointers; the stack pointer and reserved slots are not.
seen = set()
for off in range(4, 0x100, 4):
    ptr = getInt(start.add(off)) & 0xffffffff
    if not (ptr & 1) or not (start.getOffset() <= (ptr & ~1) <= end.getOffset()):
        continue
    addr = toAddr(ptr & ~1)
    if mem.contains(addr) and ptr not in seen:
        seen.add(ptr)
        disassemble(addr)
        if getFunctionAt(addr) is None:
            createFunction(addr, "vector_%02x" % off)
        println("vector +0x%x -> %s" % (off, addr))
