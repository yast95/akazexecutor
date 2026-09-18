import time

import pymem
import win32gui
import win32process

from . import offsets


class CustomOffsets:
    module_bytecode = 0x138
    module_state = 0x170  # retained for compatibility
    bytecode_size = 0x28
    bytecode_ptr = 0x18
    local_bytecode = 0x190


class SdkError(Exception):
    pass


MEM_COMMIT = 0x00001000
MEM_RESERVE = 0x00002000
MEM_RELEASE = 0x00008000
PAGE_READWRITE = 0x04

MAX_CHILDREN_PER_INSTANCE = 100_000
MAX_DESCENDANTS = 100_000
MAX_PARENT_DEPTH = 256
MAX_BYTECODE_SIZE = 50 * 1024 * 1024


class Roblox:
    def __init__(self):
        pm = pymem.Pymem("RobloxPlayerBeta.exe")
        self.mem = pm
        self.version = None
        self.offsets = None

        for module in self.mem.list_modules():
            if module.name == "RobloxPlayerBeta.exe":
                parts = module.filename.split("\\")
                if len(parts) >= 2:
                    self.version = parts[-2]
                break

        if not self.version:
            raise SdkError("Cannot find Roblox version")

        offsets.check(self.version)
        self.offsets = offsets.get()

    @property
    def datamodel(self):
        try:
            fake = self.mem.read_ulonglong(
                self.mem.base_address + self.offsets.fake_datamodel_ptr
            )
            if not fake:
                return None
            real = self.mem.read_ulonglong(fake + self.offsets.real_datamodel_ptr)
            if not real:
                return None
            return Instance(self, real)
        except (OSError, RuntimeError, ValueError):
            return None

    def from_class_name(self, address):
        instance = Instance(self, address)
        try:
            class_name = instance.class_name
        except Exception:
            class_name = None

        if class_name in classes:
            return classes[class_name](self, address)
        return instance

    def set_fps_cap(self, fps: int):
        offset = self.offsets.fflag_task_scheduler_target_fps
        if offset is None:
            raise SdkError("FPS cap offset unavailable for this version")
        if not 0 <= fps <= 9999:
            raise ValueError("fps must be between 0 and 9999")
        self.mem.write_int(self.mem.base_address + offset, fps)

    def get_fps_cap(self) -> int:
        offset = self.offsets.fflag_task_scheduler_target_fps
        if offset is None:
            raise SdkError("FPS cap offset unavailable for this version")
        return self.mem.read_int(self.mem.base_address + offset)


class Instance:
    def __init__(self, rbx: Roblox, addr):
        self.memory = rbx.mem
        self.offsets = rbx.offsets
        self.address = addr
        self._rbx = rbx

    @property
    def name(self):
        if not self.address:
            return None
        try:
            container = self.memory.read_ulonglong(
                self.address + self.offsets.ins_name_container
            )
            if not container:
                return None

            ptr = container + self.offsets.ins_name
            try:
                name_ptr = self.memory.read_ulonglong(ptr)
                if name_ptr:
                    return self.memory.read_string(name_ptr)
            except Exception:
                pass

            try:
                return self.memory.read_string(ptr)
            except Exception:
                return None
        except Exception:
            return None

    @property
    def class_name(self):
        if not self.address:
            return None
        try:
            desc = self.memory.read_ulonglong(
                self.address + self.offsets.ins_class_desc
            )
            if not desc:
                return None
            name = self.memory.read_ulonglong(desc + self.offsets.ins_class_name)
            return self.memory.read_string(name) if name else None
        except Exception:
            return None

    @property
    def parent(self):
        if not self.address:
            return None
        try:
            par = self.memory.read_ulonglong(self.address + self.offsets.ins_parent)
            return Instance(self._rbx, par) if par else None
        except Exception:
            return None

    def get_children(self):
        if not self.address:
            return []

        try:
            container = self.memory.read_ulonglong(
                self.address + self.offsets.ins_children_start
            )
            if not container:
                return []

            start = self.memory.read_ulonglong(container)
            end = self.memory.read_ulonglong(
                container + self.offsets.ins_children_end
            )
            if not start or not end or end < start:
                return []

            span = end - start
            if span % 16 != 0 or span // 16 > MAX_CHILDREN_PER_INSTANCE:
                return []

            result = []
            for ptr in range(start, end, 16):
                try:
                    child_addr = self.memory.read_ulonglong(ptr)
                    if child_addr:
                        result.append(self._rbx.from_class_name(child_addr))
                except Exception:
                    continue
            return result
        except Exception:
            return []

    def find_first_child(self, name, recursive=False):
        if recursive:
            for instance in self.get_descendants():
                if instance.name == name:
                    return instance
            return None

        for instance in self.get_children():
            if instance.name == name:
                return instance
        return None

    def wait_for_child(self, name, timeout):
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            child = self.find_first_child(name)
            if child:
                return child
            time.sleep(0.02)
        return None

    def find_first_child_by_class(self, name, recursive=False):
        if recursive:
            for instance in self.get_descendants():
                if instance.class_name == name:
                    return instance
            return None

        for instance in self.get_children():
            if instance.class_name == name:
                return instance
        return None

    def get_descendants(self):
        result = []
        stack = self.get_children()

        while stack and len(result) < MAX_DESCENDANTS:
            current = stack.pop()
            result.append(current)
            children = current.get_children()
            if children:
                stack.extend(reversed(children))

        return result

    def find(self, *path):
        current = self
        for name in path:
            if current is None:
                return None
            current = current.find_first_child(name)
        return current

    def get_full_name(self):
        if self.class_name == "DataModel":
            return "game"

        names = [self.name]
        current = self
        for _ in range(MAX_PARENT_DEPTH):
            current = current.parent
            if current is None:
                break
            if current.class_name == "DataModel":
                names.append("game")
                break
            names.append(current.name)

        return ".".join(reversed([n for n in names if n]))

    def __repr__(self):
        return f'<{self.class_name} "{self.name}">'


class Script(Instance):
    def exploit(self, bytecode: bytes):
        ptr = self.memory.read_ulonglong(self.address + CustomOffsets.module_bytecode)
        bytecodebuf = self.memory.read_ulonglong(ptr + CustomOffsets.bytecode_ptr)
        size = self.memory.read_ulonglong(ptr + CustomOffsets.bytecode_size)

        buffer = pymem.memory.allocate_memory(
            self.memory.process_handle,
            len(bytecode),
            allocation_type=MEM_COMMIT | MEM_RESERVE,
            protection_type=PAGE_READWRITE,
        )

        try:
            self.memory.write_bytes(buffer, bytecode, len(bytecode))
            if self.memory.read_bytes(buffer, len(bytecode)) != bytecode:
                raise SdkError("memory verification failed")

            self.memory.write_ulonglong(ptr + CustomOffsets.bytecode_ptr, buffer)
            self.memory.write_ulonglong(ptr + CustomOffsets.bytecode_size, len(bytecode))

            def revert():
                self.memory.write_ulonglong(
                    ptr + CustomOffsets.bytecode_ptr, bytecodebuf
                )
                self.memory.write_ulonglong(ptr + CustomOffsets.bytecode_size, size)
                pymem.memory.free_memory(
                    self.memory.process_handle, buffer, free_type=MEM_RELEASE
                )

            return revert
        except Exception:
            try:
                pymem.memory.free_memory(
                    self.memory.process_handle, buffer, free_type=MEM_RELEASE
                )
            except Exception:
                pass
            raise

    def get_authentic_bytecode(self):
        offset = (
            CustomOffsets.local_bytecode
            if self.class_name == "LocalScript"
            else CustomOffsets.module_bytecode
        )

        ptr = self.memory.read_ulonglong(self.address + offset)
        if not ptr:
            return b""

        buffer = self.memory.read_ulonglong(ptr + CustomOffsets.bytecode_ptr)
        size = self.memory.read_ulonglong(ptr + CustomOffsets.bytecode_size)

        if buffer == 0 or size == 0:
            return b""
        if size > MAX_BYTECODE_SIZE:
            raise SdkError("bytecode size exceeds safety limit")

        return self.memory.read_bytes(buffer, size)

    def set_iscorescript(self, val):
        self.memory.write_bool(self.address, bool(val))


class StringValue(Instance):
    def __init__(self, rbx: Roblox, addr):
        super().__init__(rbx, addr)
        self.content_ptr = self.memory.read_ulonglong(addr + self.offsets.value)
        self.size_ptr = addr + self.offsets.value + self.offsets.string_length
        self._is_buffer = False

    def set_value(self, content: str):
        if not isinstance(content, str):
            raise TypeError("content must be str")

        if self._is_buffer and self.content_ptr:
            pymem.memory.free_memory(
                self.memory.process_handle,
                self.content_ptr,
                free_type=MEM_RELEASE,
            )

        encoded = content.encode("utf-8")
        self.content_ptr = pymem.memory.allocate_memory(
            self.memory.process_handle,
            len(encoded) + 1,
            allocation_type=MEM_COMMIT | MEM_RESERVE,
            protection_type=PAGE_READWRITE,
        )
        self.memory.write_bytes(self.content_ptr, encoded + b"\\x00", len(encoded) + 1)
        self.memory.write_ulonglong(
            self.address + self.offsets.value, self.content_ptr
        )
        self.memory.write_int(self.size_ptr, len(encoded))
        self._is_buffer = True

    def get_value(self):
        if not self.content_ptr:
            return ""
        return self.memory.read_string(
            self.content_ptr,
            self.memory.read_int(self.size_ptr),
        )


class BoolValue(Instance):
    def set_value(self, val: bool):
        self.memory.write_bool(self.address + self.offsets.value, bool(val))

    def get_value(self):
        return self.memory.read_bool(self.address + self.offsets.value)


class ObjectValue(Instance):
    @property
    def value(self):
        ptr = self.memory.read_ulonglong(self.address + self.offsets.value)
        return self._rbx.from_class_name(ptr) if ptr else None


classes = {
    "Instance": Instance,
    "ModuleScript": Script,
    "LocalScript": Script,
    "StringValue": StringValue,
    "BoolValue": BoolValue,
    "ObjectValue": ObjectValue,
}


def get_hwnd(proc_handle):
    target_pid = win32process.GetProcessId(proc_handle)
    matching_hwnds = []

    def enum_windows_callback(hwnd, _):
        try:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            if window_pid == target_pid and win32gui.IsWindowVisible(hwnd):
                matching_hwnds.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(enum_windows_callback, None)
    return matching_hwnds
