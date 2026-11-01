// Print disassembly in an address range from a headless Ghidra project.
// Usage: -postScript DumpListing.java 0xbc650 0x300
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.CodeUnit;

public class DumpListing extends ghidra.app.script.GhidraScript {
    @Override
    protected void run() throws Exception {
        for (int i = 0; i + 1 < getScriptArgs().length; i += 2) {
            Address start = toAddr(Long.decode(getScriptArgs()[i]));
            long length = Long.decode(getScriptArgs()[i + 1]);
            Address end = start.add(length);
            println("RANGE " + start + ".." + end);
            var units = currentProgram.getListing().getCodeUnits(start, true);
            while (units.hasNext()) {
                CodeUnit unit = units.next();
                if (unit.getMinAddress().compareTo(end) >= 0) break;
                println(unit.getMinAddress() + "  " + unit.toString());
            }
        }
    }
}
