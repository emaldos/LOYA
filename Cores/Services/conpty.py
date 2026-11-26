import os,sys,msvcrt,ctypes
from ctypes import wintypes
_kernel32=ctypes.WinDLL("kernel32",use_last_error=True)
HPCON=wintypes.HANDLE
LPPROC_THREAD_ATTRIBUTE_LIST=ctypes.c_void_p
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE=0x00020016
EXTENDED_STARTUPINFO_PRESENT=0x00080000
CREATE_UNICODE_ENVIRONMENT=0x00000400
STARTF_USESTDHANDLES=0x00000100
STILL_ACTIVE=259
class COORD(ctypes.Structure):
    _fields_=[("X",wintypes.SHORT),("Y",wintypes.SHORT)]
class STARTUPINFOW(ctypes.Structure):
    _fields_=[("cb",wintypes.DWORD),("lpReserved",wintypes.LPWSTR),("lpDesktop",wintypes.LPWSTR),("lpTitle",wintypes.LPWSTR),("dwX",wintypes.DWORD),("dwY",wintypes.DWORD),("dwXSize",wintypes.DWORD),("dwYSize",wintypes.DWORD),("dwXCountChars",wintypes.DWORD),("dwYCountChars",wintypes.DWORD),("dwFillAttribute",wintypes.DWORD),("dwFlags",wintypes.DWORD),("wShowWindow",wintypes.WORD),("cbReserved2",wintypes.WORD),("lpReserved2",ctypes.POINTER(wintypes.BYTE)),("hStdInput",wintypes.HANDLE),("hStdOutput",wintypes.HANDLE),("hStdError",wintypes.HANDLE)]
class STARTUPINFOEXW(ctypes.Structure):
    _fields_=[("StartupInfo",STARTUPINFOW),("lpAttributeList",LPPROC_THREAD_ATTRIBUTE_LIST)]
class PROCESS_INFORMATION(ctypes.Structure):
    _fields_=[("hProcess",wintypes.HANDLE),("hThread",wintypes.HANDLE),("dwProcessId",wintypes.DWORD),("dwThreadId",wintypes.DWORD)]
class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_=[("nLength",wintypes.DWORD),("lpSecurityDescriptor",wintypes.LPVOID),("bInheritHandle",wintypes.BOOL)]
_kernel32.CreatePseudoConsole.argtypes=[COORD,wintypes.HANDLE,wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(HPCON)]
_kernel32.CreatePseudoConsole.restype=ctypes.HRESULT
_kernel32.ResizePseudoConsole.argtypes=[HPCON,COORD]
_kernel32.ResizePseudoConsole.restype=ctypes.HRESULT
_kernel32.ClosePseudoConsole.argtypes=[HPCON]
_kernel32.ClosePseudoConsole.restype=None
_kernel32.CreatePipe.argtypes=[ctypes.POINTER(wintypes.HANDLE),ctypes.POINTER(wintypes.HANDLE),ctypes.POINTER(SECURITY_ATTRIBUTES),wintypes.DWORD]
_kernel32.CreatePipe.restype=wintypes.BOOL
_kernel32.InitializeProcThreadAttributeList.argtypes=[LPPROC_THREAD_ATTRIBUTE_LIST,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.c_size_t)]
_kernel32.InitializeProcThreadAttributeList.restype=wintypes.BOOL
_kernel32.UpdateProcThreadAttribute.argtypes=[LPPROC_THREAD_ATTRIBUTE_LIST,wintypes.DWORD,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.POINTER(ctypes.c_size_t)]
_kernel32.UpdateProcThreadAttribute.restype=wintypes.BOOL
_kernel32.DeleteProcThreadAttributeList.argtypes=[LPPROC_THREAD_ATTRIBUTE_LIST]
_kernel32.DeleteProcThreadAttributeList.restype=None
_kernel32.CreateProcessW.argtypes=[wintypes.LPCWSTR,wintypes.LPWSTR,ctypes.c_void_p,ctypes.c_void_p,wintypes.BOOL,wintypes.DWORD,ctypes.c_void_p,wintypes.LPCWSTR,ctypes.POINTER(STARTUPINFOEXW),ctypes.POINTER(PROCESS_INFORMATION)]
_kernel32.CreateProcessW.restype=wintypes.BOOL
_kernel32.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
_kernel32.GetExitCodeProcess.restype=wintypes.BOOL
_kernel32.TerminateProcess.argtypes=[wintypes.HANDLE,wintypes.UINT]
_kernel32.TerminateProcess.restype=wintypes.BOOL
_kernel32.CloseHandle.argtypes=[wintypes.HANDLE]
_kernel32.CloseHandle.restype=wintypes.BOOL
def available():
    return sys.platform.startswith("win") and hasattr(_kernel32,"CreatePseudoConsole")
def _quote(part):
    text=str(part)
    if not text:return '""'
    if not any(ch in text for ch in ' \t"'):return text
    return '"'+text.replace('"','\\"')+'"'
def _command_line(cmd):
    if isinstance(cmd,str):return cmd
    return " ".join(_quote(part) for part in cmd)
def _env_block(env):
    if not env:return None
    items="".join(f"{key}={value}\0" for key,value in env.items())
    return ctypes.create_unicode_buffer(items+"\0")
class ConptySession:
    def __init__(self,cmd,cols=120,rows=30,cwd=None,env=None):
        self._closed=False
        self._pc=HPCON()
        self._process=None
        self._thread=None
        self._reader=None
        self._writer=None
        self._start(cmd,cols,rows,cwd,env)
    def _start(self,cmd,cols,rows,cwd,env):
        sa=SECURITY_ATTRIBUTES()
        sa.nLength=ctypes.sizeof(SECURITY_ATTRIBUTES)
        sa.bInheritHandle=False
        sa.lpSecurityDescriptor=None
        in_read=wintypes.HANDLE()
        in_write=wintypes.HANDLE()
        out_read=wintypes.HANDLE()
        out_write=wintypes.HANDLE()
        if not _kernel32.CreatePipe(ctypes.byref(in_read),ctypes.byref(in_write),ctypes.byref(sa),0):
            raise OSError(ctypes.get_last_error(),"CreatePipe for ConPTY input failed")
        if not _kernel32.CreatePipe(ctypes.byref(out_read),ctypes.byref(out_write),ctypes.byref(sa),0):
            _kernel32.CloseHandle(in_read);_kernel32.CloseHandle(in_write)
            raise OSError(ctypes.get_last_error(),"CreatePipe for ConPTY output failed")
        size=COORD(max(1,int(cols)),max(1,int(rows)))
        result=_kernel32.CreatePseudoConsole(size,in_read,out_write,0,ctypes.byref(self._pc))
        _kernel32.CloseHandle(in_read)
        _kernel32.CloseHandle(out_write)
        if result!=0:
            _kernel32.CloseHandle(in_write);_kernel32.CloseHandle(out_read)
            raise OSError(result,"CreatePseudoConsole failed")
        needed=ctypes.c_size_t(0)
        _kernel32.InitializeProcThreadAttributeList(None,1,0,ctypes.byref(needed))
        buffer=ctypes.create_string_buffer(needed.value)
        attribute_list=ctypes.cast(buffer,LPPROC_THREAD_ATTRIBUTE_LIST)
        if not _kernel32.InitializeProcThreadAttributeList(attribute_list,1,0,ctypes.byref(needed)):
            self._cleanup_handles(in_write,out_read)
            raise OSError(ctypes.get_last_error(),"InitializeProcThreadAttributeList failed")
        if not _kernel32.UpdateProcThreadAttribute(attribute_list,0,PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,ctypes.cast(self._pc,ctypes.c_void_p),ctypes.sizeof(HPCON),None,None):
            _kernel32.DeleteProcThreadAttributeList(attribute_list)
            self._cleanup_handles(in_write,out_read)
            raise OSError(ctypes.get_last_error(),"UpdateProcThreadAttribute failed")
        startup=STARTUPINFOEXW()
        startup.StartupInfo.cb=ctypes.sizeof(STARTUPINFOEXW)
        startup.StartupInfo.dwFlags=STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput=None
        startup.StartupInfo.hStdOutput=None
        startup.StartupInfo.hStdError=None
        startup.lpAttributeList=attribute_list
        info=PROCESS_INFORMATION()
        command=ctypes.create_unicode_buffer(_command_line(cmd))
        environment=_env_block(env)
        flags=EXTENDED_STARTUPINFO_PRESENT|(CREATE_UNICODE_ENVIRONMENT if environment else 0)
        created=_kernel32.CreateProcessW(None,command,None,None,False,flags,ctypes.cast(environment,ctypes.c_void_p) if environment else None,cwd,ctypes.byref(startup),ctypes.byref(info))
        _kernel32.DeleteProcThreadAttributeList(attribute_list)
        if not created:
            self._cleanup_handles(in_write,out_read)
            raise OSError(ctypes.get_last_error(),"CreateProcessW for ConPTY failed")
        self._process=info.hProcess
        self._thread=info.hThread
        self.pid=int(info.dwProcessId)
        self._writer=os.fdopen(msvcrt.open_osfhandle(int(in_write.value),os.O_WRONLY),"wb",0)
        self._reader=os.fdopen(msvcrt.open_osfhandle(int(out_read.value),os.O_RDONLY),"rb",0)
    def _cleanup_handles(self,in_write,out_read):
        if self._pc:_kernel32.ClosePseudoConsole(self._pc)
        _kernel32.CloseHandle(in_write)
        _kernel32.CloseHandle(out_read)
    def read(self,size=65536):
        if self._reader is None:return b""
        try:return self._reader.read(size)
        except (OSError,ValueError):return b""
    def write(self,data):
        if self._writer is None or self._closed:return False
        try:
            self._writer.write(data)
            self._writer.flush()
            return True
        except (OSError,ValueError):return False
    def resize(self,cols,rows):
        if not self._pc or self._closed:return False
        try:return _kernel32.ResizePseudoConsole(self._pc,COORD(max(1,int(cols)),max(1,int(rows))))==0
        except OSError:return False
    def exit_code(self):
        if not self._process:return None
        code=wintypes.DWORD(0)
        if not _kernel32.GetExitCodeProcess(self._process,ctypes.byref(code)):return None
        return None if code.value==STILL_ACTIVE else int(code.value)
    def alive(self):
        return self.exit_code() is None
    def close(self):
        if self._closed:return
        self._closed=True
        try:
            if self._process and self.alive():_kernel32.TerminateProcess(self._process,1)
        except OSError:pass
        if self._pc:
            _kernel32.ClosePseudoConsole(self._pc)
            self._pc=HPCON()
        for stream in (self._writer,self._reader):
            try:
                if stream:stream.close()
            except (OSError,ValueError):pass
        self._writer=None
        self._reader=None
        for handle in (self._thread,self._process):
            try:
                if handle:_kernel32.CloseHandle(handle)
            except OSError:pass
        self._thread=None
        self._process=None
