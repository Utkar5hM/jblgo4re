// One-shot export of an analyzed program into grep-able text so agents never
// need to cold-start Ghidra for routine lookups.
// Usage: -postScript ExportIndex.java <out_dir>
// Produces:
//   functions.tsv  entry  name  size  n_callers  n_callees
//   calls.tsv      caller_entry  callsite  callee_entry
//   consts.tsv     func_entry  insn_addr  value  kind(imm|lit)   (imm only if >= 0x100)
//   strings.tsv    addr  referencing_funcs  string
//   decomp/<entry>.c   header (callers/callees) + decompiled C
//   asm/<entry>.s      address, bytes, instruction
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.StringDataInstance;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.Reference;
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class ExportIndex extends ghidra.app.script.GhidraScript {
    private String hex(Address a) { return String.format("0x%08x", a.getOffset()); }

    private String funcKey(Function f) { return f == null ? "?" : hex(f.getEntryPoint()); }

    @Override
    protected void run() throws Exception {
        Path out = Paths.get(getScriptArgs()[0]);
        Files.createDirectories(out.resolve("decomp"));
        Files.createDirectories(out.resolve("asm"));
        Listing listing = currentProgram.getListing();
        var mem = currentProgram.getMemory();

        DecompInterface dec = new DecompInterface();
        dec.setOptions(new DecompileOptions());
        dec.openProgram(currentProgram);

        try (PrintWriter fn = new PrintWriter(Files.newBufferedWriter(out.resolve("functions.tsv")));
             PrintWriter calls = new PrintWriter(Files.newBufferedWriter(out.resolve("calls.tsv")));
             PrintWriter consts = new PrintWriter(Files.newBufferedWriter(out.resolve("consts.tsv")))) {
            fn.println("entry\tname\tsize\tn_callers\tn_callees");
            calls.println("caller\tcallsite\tcallee");
            consts.println("func\tinsn\tvalue\tkind");
            int n = 0;
            for (Function f : listing.getFunctions(true)) {
                if (monitor.isCancelled()) break;
                String key = funcKey(f);
                Set<Function> callers = f.getCallingFunctions(monitor);
                Set<Function> callees = f.getCalledFunctions(monitor);
                fn.printf("%s\t%s\t%d\t%d\t%d%n", key, f.getName(), f.getBody().getNumAddresses(),
                    callers.size(), callees.size());

                StringBuilder asm = new StringBuilder();
                for (Instruction insn : listing.getInstructions(f.getBody(), true)) {
                    Address ia = insn.getAddress();
                    byte[] b = insn.getBytes();
                    StringBuilder hb = new StringBuilder();
                    for (byte x : b) hb.append(String.format("%02x", x));
                    asm.append(hex(ia)).append("  ").append(String.format("%-10s", hb)).append(' ')
                       .append(insn.toString()).append('\n');
                    if (insn.getFlowType().isCall()) {
                        for (Address t : insn.getFlows()) {
                            Function callee = getFunctionAt(t);
                            calls.printf("%s\t%s\t%s%n", key, hex(ia), callee == null ? hex(t) : funcKey(callee));
                        }
                    }
                    for (int op = 0; op < insn.getNumOperands(); op++) {
                        for (Object o : insn.getOpObjects(op)) {
                            if (o instanceof Scalar s && s.getUnsignedValue() >= 0x100) {
                                consts.printf("%s\t%s\t0x%x\timm%n", key, hex(ia), s.getUnsignedValue());
                            }
                        }
                    }
                    for (Reference r : insn.getReferencesFrom()) {
                        if (!r.getReferenceType().isData()) continue;
                        Address to = r.getToAddress();
                        if (!mem.contains(to) || !mem.getBlock(to).isInitialized()) continue;
                        try {
                            long v = mem.getInt(to) & 0xffffffffL;
                            consts.printf("%s\t%s\t0x%x\tlit%n", key, hex(ia), v);
                        } catch (Exception e) { /* unreadable pool */ }
                    }
                }
                Files.writeString(out.resolve("asm").resolve(key + ".s"), asm.toString());

                StringBuilder c = new StringBuilder();
                c.append("// ").append(key).append(' ').append(f.getName()).append('\n');
                c.append("// callers:");
                for (Function x : callers) c.append(' ').append(funcKey(x));
                c.append("\n// callees:");
                for (Function x : callees) c.append(' ').append(funcKey(x));
                c.append('\n');
                DecompileResults r = dec.decompileFunction(f, 60, monitor);
                if (r != null && r.decompileCompleted()) c.append(r.getDecompiledFunction().getC());
                else c.append("// DECOMPILE FAILED\n");
                Files.writeString(out.resolve("decomp").resolve(key + ".c"), c.toString());
                if (++n % 250 == 0) println("exported " + n);
            }
            println("exported " + n + " functions");
        }

        try (PrintWriter st = new PrintWriter(Files.newBufferedWriter(out.resolve("strings.tsv")))) {
            st.println("addr\tfuncs\tstring");
            for (Data d : listing.getDefinedData(true)) {
                if (!d.hasStringValue()) continue;
                String s = StringDataInstance.getStringDataInstance(d).getStringValue();
                if (s == null || s.length() < 3) continue;
                Set<String> fs = new TreeSet<>();
                for (Reference ref : getReferencesTo(d.getAddress())) {
                    fs.add(funcKey(getFunctionContaining(ref.getFromAddress())));
                }
                st.printf("%s\t%s\t%s%n", hex(d.getAddress()), String.join(",", fs),
                    s.replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r"));
            }
        }
        dec.dispose();
    }
}
