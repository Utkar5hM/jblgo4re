// Decompile functions by address from a headless Ghidra project.
// Usage: -postScript DumpFunctions.java 0x8fc24 0x8f9b8
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class DumpFunctions extends ghidra.app.script.GhidraScript {
    @Override
    protected void run() throws Exception {
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        for (String arg : getScriptArgs()) {
            long offset = Long.decode(arg);
            var address = toAddr(offset);
            Function function = getFunctionContaining(address);
            if (function == null) {
                disassemble(address);
                function = createFunction(address, null);
            }
            if (function == null) {
                println("NO FUNCTION " + address);
                continue;
            }
            println("FUNCTION " + function.getEntryPoint() + " " + function.getName());
            Reference[] refs = getReferencesTo(function.getEntryPoint());
            println("CALLERS " + refs.length);
            for (int i = 0; i < Math.min(refs.length, 30); i++) {
                var source = refs[i].getFromAddress();
                Function caller = getFunctionContaining(source);
                println("  " + source + " in " + (caller == null ? "?" : caller.getName()));
            }
            DecompileResults result = decompiler.decompileFunction(function, 30, monitor);
            if (result != null && result.decompileCompleted()) {
                println(result.getDecompiledFunction().getC());
            } else {
                println("DECOMPILE FAILED");
            }
        }
        decompiler.dispose();
    }
}
