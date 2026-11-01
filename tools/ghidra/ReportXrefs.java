// Report references to addresses and decompile the functions that contain them.
// Usage: -postScript ReportXrefs.java 0x7ef98 0xb558
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class ReportXrefs extends ghidra.app.script.GhidraScript {
    @Override
    protected void run() throws Exception {
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        for (String arg : getScriptArgs()) {
            var address = toAddr(Long.decode(arg));
            println("TARGET " + address + " references=" + getReferencesTo(address).length);
            for (Reference reference : getReferencesTo(address)) {
                var source = reference.getFromAddress();
                Function function = getFunctionContaining(source);
                println("FROM " + source + " IN " + (function == null ? "?" : function.getName()));
                if (function != null) {
                    DecompileResults result = decompiler.decompileFunction(function, 30, monitor);
                    if (result != null && result.decompileCompleted()) {
                        println(result.getDecompiledFunction().getC());
                    }
                }
            }
        }
        decompiler.dispose();
    }
}
