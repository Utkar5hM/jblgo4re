// Find instructions that reference literal scalar values (including RAM addresses).
// Usage: -postScript FindScalars.java 0x2002051c 0x20021c84
import ghidra.program.model.listing.Function;
import ghidra.program.model.scalar.Scalar;

public class FindScalars extends ghidra.app.script.GhidraScript {
    @Override
    protected void run() throws Exception {
        for (String arg : getScriptArgs()) {
            long wanted = Long.decode(arg);
            println("VALUE " + Long.toHexString(wanted));
            var iterator = currentProgram.getListing().getInstructions(true);
            int count = 0;
            while (iterator.hasNext()) {
                var instruction = iterator.next();
                boolean match = false;
                for (int operand = 0; operand < instruction.getNumOperands(); operand++) {
                    for (Object object : instruction.getOpObjects(operand)) {
                        if (object instanceof Scalar scalar && scalar.getUnsignedValue() == wanted) {
                            match = true;
                        }
                    }
                }
                if (match) {
                    Function function = getFunctionContaining(instruction.getAddress());
                    println("  " + instruction.getAddress() + " " + instruction + " IN " +
                        (function == null ? "?" : function.getName()));
                    count++;
                }
            }
            println("MATCHES " + count);
        }
    }
}
