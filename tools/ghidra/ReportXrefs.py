#@category JBLGo4
# Report code references to known firmware strings after analysis.
from ghidra.app.decompiler import DecompInterface

base = currentProgram.getMemory().getMinAddress().getOffset()
if base == 0x40000:
    targets = {
        "charge_bypass_task": 0x443e0,
        "PowerOffStatusTimer": 0x59590,
        "AT+HMPowerOff": 0x4dc00,
        "AT+HMDevVER": 0x4dab8,
        "App USB Transmit": 0x51a0c,
        "IPC Service": 0x553d0,
        "AT+HMDevKEY=00": 0x40b2c,
    }
else:
    targets = {
        "VOLUME_CHANGED": 0xc7c6c,
        "POWEROFF": 0xc7d4c,
        "VOL_UP": 0xc7e34,
    }

dec = DecompInterface()
dec.openProgram(currentProgram)
for name, offset in targets.items():
    addr = toAddr(offset)
    try:
        raw = getBytes(addr, min(len(name) + 2, 32))
        actual = ''.join(chr(x & 0xff) for x in raw)
    except Exception as exc:
        println("%s at %s unavailable: %s" % (name, addr, exc))
        continue
    println("TARGET %s at %s actual=%r" % (name, addr, actual))
    refs = list(getReferencesTo(addr))
    println("  references: %d" % len(refs))
    for ref in refs[:12]:
        src = ref.getFromAddress()
        func = getFunctionContaining(src)
        println("  from %s function=%s" % (src, func.getName() if func else "?"))
        if func:
            result = dec.decompileFunction(func, 15, monitor)
            if result and result.decompileCompleted():
                code = result.getDecompiledFunction().getC()
                println(code[:5000])
dec.dispose()
