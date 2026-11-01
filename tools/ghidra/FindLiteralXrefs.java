// Find literal-pool copies of a value and report code references to each copy.
// Usage: -postScript FindLiteralXrefs.java 0x2002051c
import ghidra.program.model.address.Address;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.program.model.symbol.Reference;

public class FindLiteralXrefs extends ghidra.app.script.GhidraScript {
    @Override
    protected void run() throws Exception {
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        for (String arg : getScriptArgs()) {
            long wanted = Long.decode(arg) & 0xffffffffL;
            byte[] pattern = new byte[] {
                (byte) wanted, (byte) (wanted >>> 8), (byte) (wanted >>> 16), (byte) (wanted >>> 24)
            };
            println("VALUE " + Long.toHexString(wanted));
            int found = 0;
            java.util.Set<String> emittedFunctions = new java.util.HashSet<>();
            for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
                if (!block.isInitialized() || block.getSize() < 4) continue;
                Address cursor = block.getStart();
                Address last = block.getEnd().subtract(3);
                while (cursor.compareTo(last) <= 0) {
                    byte[] bytes = new byte[4];
                    currentProgram.getMemory().getBytes(cursor, bytes);
                    if (java.util.Arrays.equals(bytes, pattern)) {
                        println("LITERAL " + cursor);
                        for (Reference ref : getReferencesTo(cursor)) {
                            Function function = getFunctionContaining(ref.getFromAddress());
                            println("  FROM " + ref.getFromAddress() + " " + ref.getReferenceType() + " IN " +
                                (function == null ? "?" : function.getName()));
                            found++;
                            if (function != null && emittedFunctions.add(function.getEntryPoint().toString())) {
                                DecompileResults result = decompiler.decompileFunction(function, 30, monitor);
                                if (result != null && result.decompileCompleted()) {
                                    println(result.getDecompiledFunction().getC());
                                }
                            }
                        }
                    }
                    cursor = cursor.add(4);
                }
            }
            println("XREFS " + found);
        }
        decompiler.dispose();
    }
}
