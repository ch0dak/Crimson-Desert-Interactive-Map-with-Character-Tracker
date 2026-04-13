"""
CD Map Tracker — Memory Reader
Reads player position from Crimson Desert using pymem.

Uses a minimal entity-capture hook to reliably identify the player entity.
The hook only captures the entity pointer — no teleporting, no health
manipulation, no position blocking.
"""

import struct
import json
import os
import ctypes
import logging
import time

from config import (
    PROCESS_NAME, AOB_ENTITY, AOB_WORLD, POINTER_CHAIN_FILE, SAVE_DIR,
)

log = logging.getLogger("memory_reader")

try:
    import pymem
    import pymem.process
except ImportError:
    log.error("pymem is required. Install with: pip install pymem")
    raise

# Windows API constants
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_EXECUTE_READWRITE = 0x40

k32 = ctypes.windll.kernel32
k32.VirtualAllocEx.restype = ctypes.c_ulonglong
k32.VirtualAllocEx.argtypes = [
    ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_size_t,
    ctypes.c_ulong, ctypes.c_ulong,
]
k32.VirtualFreeEx.argtypes = [
    ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_size_t, ctypes.c_ulong,
]


class MemoryReader:
    """Game memory reader with minimal entity-capture hook."""

    # Data block layout
    OFF_ENTITY_PTR = 0x00   # uint64: captured entity pointer
    OFF_POS = 0x20          # 3 floats: captured local position (x, y, z)
    OFF_CAVE = 0x40         # code cave starts here
    BLOCK_SIZE = 0x100      # 256 bytes total

    def __init__(self):
        self.pm = None
        self.module = None
        self.attached = False

        self.world_offset_addr = 0
        self.hook_addr = 0

        # Hook state
        self.block = 0
        self.entity_ptr_addr = 0
        self.orig_bytes = None
        self.hooked = False

        # Pointer chain fallback
        self.pointer_chain = None
        self.entity_offsets = {"x": 0x90, "y": 0x94, "z": 0x98}

    # ── Attach / Detach ──────────────────────────────────────────────

    def attach(self):
        """Attach to CrimsonDesert.exe using pymem."""
        try:
            self.pm = pymem.Pymem(PROCESS_NAME)
            self.module = pymem.process.module_from_name(
                self.pm.process_handle, PROCESS_NAME)
            self.attached = True
            base = self.module.lpBaseOfDll
            size = self.module.SizeOfImage
            log.info(f"Attached to {PROCESS_NAME} (PID {self.pm.process_id}), "
                     f"base=0x{base:X}, size=0x{size:X}")
            self._load_pointer_chain()
            return True
        except Exception as e:
            log.debug(f"Attach failed: {e}")
            self.pm = None
            self.module = None
            return False

    def detach(self):
        """Detach and clean up hook."""
        if self.hooked:
            self._uninstall_hook()
        if self.block and self.pm:
            try:
                k32.VirtualFreeEx(self.pm.process_handle, self.block, 0, MEM_RELEASE)
            except Exception:
                pass
            self.block = 0
        if self.pm:
            try:
                self.pm.close_process()
            except Exception:
                pass
        self.pm = None
        self.attached = False
        log.info("Detached from game")

    def is_attached(self):
        if not self.attached or not self.pm:
            return False
        try:
            self.pm.read_bytes(self.module.lpBaseOfDll, 1)
            return True
        except Exception:
            self.attached = False
            return False

    # ── AOB Scanning ─────────────────────────────────────────────────

    def _read_module_data(self):
        """Read entire game module for AOB scanning."""
        base = self.module.lpBaseOfDll
        size = self.module.SizeOfImage
        data = bytearray(size)
        CHUNK = 0x10000
        read_ok = 0
        read_fail = 0
        for off in range(0, size, CHUNK):
            sz = min(CHUNK, size - off)
            try:
                chunk = self.pm.read_bytes(base + off, sz)
                data[off:off + sz] = chunk
                read_ok += 1
            except Exception:
                read_fail += 1
        total = read_ok + read_fail
        log.info(f"Module read: {read_ok}/{total} chunks OK "
                 f"({read_ok * CHUNK / 1024 / 1024:.1f} MB of {size / 1024 / 1024:.1f} MB)")
        return bytes(data)

    def scan_aobs(self):
        """Scan for AOB signatures."""
        log.info("Scanning for AOB signatures...")
        data = self._read_module_data()
        base = self.module.lpBaseOfDll
        found_world = False

        # World offset: 0F 5C 1D ?? ?? ?? ?? 0F 11 99 90 00 00 00
        suffix = b'\x0F\x11\x99\x90\x00\x00\x00'
        pos = 0
        while pos < len(data) - 14:
            i = data.find(AOB_WORLD, pos)
            if i == -1:
                break
            if data[i + 7:i + 14] == suffix:
                disp = struct.unpack_from('<i', data, i + 3)[0]
                self.world_offset_addr = base + i + 7 + disp
                found_world = True
                log.info(f"World offset address: 0x{self.world_offset_addr:X}")
                break
            pos = i + 1

        if not found_world:
            log.warning("World offset AOB not found")

        # Entity hook: search for the full AOB first, then fallback patterns
        self.hook_addr = 0
        self._find_entity_aob(data, base)

        return found_world

    def _find_entity_aob(self, data, base):
        """Search for entity hook AOB with multiple fallback patterns."""

        # Pattern 1: exact original AOB (48 8B 06 0F 11 88 B0 01 00 00)
        idx = data.find(AOB_ENTITY)
        if idx != -1:
            self.hook_addr = base + idx + 3  # hook the 7-byte movups instruction
            log.info(f"Entity AOB found (exact match) at 0x{self.hook_addr:X}")
            return

        # Pattern 2: search for the standalone movups [rax+1B0h], xmm1
        # Must NOT have F3/F2/41/66 prefix (those change the instruction meaning)
        core = b'\x0F\x11\x88\xB0\x01\x00\x00'
        bad_prefixes = {0xF3, 0xF2, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x66}
        pos = 0
        candidates = []
        while pos < len(data) - 7:
            i = data.find(core, pos)
            if i == -1:
                break
            if i > 0 and data[i - 1] in bad_prefixes:
                pos = i + 1
                continue
            candidates.append(i)
            pos = i + 1

        if candidates:
            for ci, off in enumerate(candidates[:5]):
                ctx_start = max(0, off - 10)
                ctx = data[ctx_start:off + 7]
                ctx_hex = ' '.join(f'{b:02X}' for b in ctx)
                log.info(f"  Core match #{ci}: 0x{base + off:X}  context: [{ctx_hex}]")
            self.hook_addr = base + candidates[0]
            log.info(f"Entity AOB found (core match) at 0x{self.hook_addr:X}")
            return

        log.warning("Entity AOB not found. Make sure no other mod is hooked, then restart the game.")

    # ── Entity Capture Hook ──────────────────────────────────────────

    def install_hook(self):
        """Install minimal entity-capture hook.

        Hooks a 7-byte instruction (movups [rax+disp32], xmmN).
        Our cave saves RAX (entity pointer), executes the original
        instruction, and jumps back.
        """
        if not self.hook_addr:
            log.error("Cannot install hook: no hook address found")
            return False

        handle = self.pm.process_handle

        # Read original bytes first
        try:
            self.orig_bytes = self.pm.read_bytes(self.hook_addr, 7)
        except Exception as e:
            log.error(f"Failed to read original bytes at 0x{self.hook_addr:X}: {e}")
            return False
        log.info(f"Original bytes at hook: [{' '.join(f'{b:02X}' for b in self.orig_bytes)}]")

        # Allocate memory near the hook for our code cave
        self.block = self._alloc_near(handle, self.hook_addr, self.BLOCK_SIZE)
        if not self.block:
            log.error("Could not allocate memory near hook point")
            return False

        self.entity_ptr_addr = self.block + self.OFF_ENTITY_PTR
        cave_addr = self.block + self.OFF_CAVE
        ret_addr = self.hook_addr + 7

        # Initialize entity pointer to 0
        self.pm.write_bytes(self.entity_ptr_addr, b'\x00' * 8, 8)

        # Build the code cave
        cave = bytearray()
        cave += b'\x51'                                             # push rcx
        cave += b'\x48\xB9' + struct.pack('<Q', self.entity_ptr_addr)  # mov rcx, &entity_ptr
        cave += b'\x48\x89\x01'                                    # mov [rcx], rax
        cave += b'\x59'                                             # pop rcx
        cave += bytes(self.orig_bytes)                              # original 7-byte instruction
        cave += b'\xFF\x25\x00\x00\x00\x00' + struct.pack('<Q', ret_addr)  # jmp abs

        # Write cave
        self.pm.write_bytes(cave_addr, bytes(cave), len(cave))

        # Build JMP rel32 patch (5 bytes) + 2 NOPs
        rel = cave_addr - (self.hook_addr + 5)
        if not (-0x80000000 <= rel <= 0x7FFFFFFF):
            log.error(f"Cave too far for rel32: 0x{self.hook_addr:X} -> 0x{cave_addr:X}")
            return False
        patch = b'\xE9' + struct.pack('<i', rel) + b'\x90\x90'

        # Install hook
        self.pm.write_bytes(self.hook_addr, patch, 7)
        self.hooked = True
        log.info(f"Entity capture hook installed at 0x{self.hook_addr:X}")
        log.info(f"  Cave at 0x{cave_addr:X}, entity ptr at 0x{self.entity_ptr_addr:X}")
        return True

    def _uninstall_hook(self):
        """Restore original bytes at hook point."""
        if not self.hooked or not self.orig_bytes:
            return
        try:
            self.pm.write_bytes(self.hook_addr, self.orig_bytes, len(self.orig_bytes))
            log.info("Hook uninstalled, original bytes restored")
        except Exception:
            log.warning("Failed to uninstall hook")
        self.hooked = False

    def _alloc_near(self, handle, near, size):
        """Allocate memory within +-2GB of `near` for rel32 jumps."""
        for offset in range(0x10000, 0x7FFF0000, 0x10000):
            for addr in [near + offset, near - offset]:
                if addr <= 0:
                    continue
                result = k32.VirtualAllocEx(
                    handle, addr, size,
                    MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE)
                if result:
                    return result
        return 0

    # ── Pointer Chain (fallback) ─────────────────────────────────────

    def _load_pointer_chain(self):
        if not os.path.isfile(POINTER_CHAIN_FILE):
            return
        try:
            with open(POINTER_CHAIN_FILE, "r") as f:
                cfg = json.load(f)
            self.pointer_chain = cfg.get("player_position", {}).get("chain", [])
            offsets = cfg.get("player_position", {}).get("offsets", {})
            if offsets:
                self.entity_offsets = {
                    "x": offsets.get("x", 0x90),
                    "y": offsets.get("y", 0x94),
                    "z": offsets.get("z", 0x98),
                }
            log.info(f"Loaded pointer chain: {self.pointer_chain}")
        except Exception as e:
            log.warning(f"Failed to load pointer chain: {e}")

    def _resolve_pointer_chain(self):
        if not self.pointer_chain:
            return None
        try:
            addr = None
            for i, entry in enumerate(self.pointer_chain):
                if i == 0:
                    if entry.startswith(PROCESS_NAME + "+"):
                        offset = int(entry.split("+")[1], 16)
                        ptr = self.pm.read_ulonglong(self.module.lpBaseOfDll + offset)
                    else:
                        ptr = self.pm.read_ulonglong(int(entry, 16))
                    if not ptr:
                        return None
                    addr = ptr
                else:
                    offset = int(entry, 16) if isinstance(entry, str) else entry
                    ptr = self.pm.read_ulonglong(addr + offset)
                    if not ptr:
                        return None
                    addr = ptr
            return addr
        except Exception:
            return None

    # ── Entity Resolution ────────────────────────────────────────────

    def get_entity_addr(self):
        """Get the player entity address from hook capture or pointer chain."""
        if self.entity_ptr_addr:
            try:
                addr = self.pm.read_ulonglong(self.entity_ptr_addr)
                if addr and addr > 0x10000:
                    return addr
            except Exception:
                pass
        return self._resolve_pointer_chain()

    # ── Position Reading ─────────────────────────────────────────────

    def get_player_local_pos(self):
        """Read local player position (x, y, z)."""
        entity = self.get_entity_addr()
        if not entity:
            return None
        try:
            ox = self.entity_offsets["x"]
            raw = self.pm.read_bytes(entity + ox, 12)
            x, y, z = struct.unpack('<fff', raw)
            if x == 0.0 and y == 0.0 and z == 0.0:
                return None
            if x != x or y != y or z != z:  # NaN
                return None
            return x, y, z
        except Exception:
            return None

    def get_world_offsets(self):
        """Read world offset constants."""
        if not self.world_offset_addr:
            return None
        try:
            raw = self.pm.read_bytes(self.world_offset_addr, 16)
            return struct.unpack('<ffff', raw)
        except Exception:
            return None

    def get_player_abs(self):
        """Return absolute world position (x, y, z), or None."""
        pos = self.get_player_local_pos()
        if not pos:
            return None
        off = self.get_world_offsets()
        if off:
            return pos[0] + off[0], pos[1], pos[2] + off[2]
        return pos


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    reader = MemoryReader()
    if not reader.attach():
        print(f"Could not attach to {PROCESS_NAME}. Is the game running?")
        print("Make sure to run as Administrator.")
        sys.exit(1)

    reader.scan_aobs()

    if reader.pointer_chain:
        print("Using pointer chain mode...")
    elif reader.hook_addr:
        print(f"Installing entity capture hook at 0x{reader.hook_addr:X}...")
        if not reader.install_hook():
            print("Hook installation failed.")
            reader.detach()
            sys.exit(1)
        print("Hook installed. WALK AROUND in-game now...")
    else:
        print("No hook address found and no pointer chain configured.")
        print("Make sure no other mod is hooked, then restart the game.")
        reader.detach()
        sys.exit(1)

    print("\nPolling for 30s — keep moving in-game. Ctrl+C to stop early.\n")
    print(f"  entity_ptr storage: 0x{reader.entity_ptr_addr:X}")
    print(f"  hook address:       0x{reader.hook_addr:X}\n")

    try:
        for i in range(60):
            time.sleep(0.5)

            # Raw entity pointer value
            raw_ptr = 0
            if reader.entity_ptr_addr:
                try:
                    raw_ptr = reader.pm.read_ulonglong(reader.entity_ptr_addr)
                except Exception:
                    pass

            entity = reader.get_entity_addr()

            if raw_ptr == 0:
                print(f"  [{i*0.5:5.1f}s] entity_ptr = 0x0  (hook hasn't fired yet — keep moving)")
                continue

            print(f"  [{i*0.5:5.1f}s] entity_ptr = 0x{raw_ptr:X}", end="")

            if entity is None:
                print("  (ignored: < 0x10000 or null)")
                continue

            # Read raw bytes at position offsets
            try:
                raw = reader.pm.read_bytes(entity + 0x90, 12)
                x, y, z = struct.unpack('<fff', raw)
                print(f"  x={x:.2f}  y={y:.2f}  z={z:.2f}", end="")

                off = reader.get_world_offsets()
                if off:
                    print(f"  world=({off[0]:.1f},{off[1]:.1f},{off[2]:.1f})"
                          f"  abs=({x+off[0]:.2f},{y:.2f},{z+off[2]:.2f})", end="")
            except Exception as e:
                print(f"  read error: {e}", end="")

            print()

    except KeyboardInterrupt:
        pass

    reader.detach()
