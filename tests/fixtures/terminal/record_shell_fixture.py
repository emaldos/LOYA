"""Records the raw PTY bytes an interactive shell writes while LOYA's terminal panel drives it (Linux only).

Usage: python3 record_shell_fixture.py steps.json out.json
steps.json comes from `node tests/js/terminal_shell_echo.js --emit <scenario>` and holds the exact bytes the app sends.
The shell runs in a throwaway HOME holding only a copy of the given rc file. The user name, host name and that HOME path are
replaced in the recording, so a fixture holds nothing about the machine it was made on.
"""
import fcntl,getpass,json,os,pty,select,shutil,socket,struct,subprocess,sys,tempfile,termios,time
def main(steps_path,out_path):
    spec=json.load(open(steps_path,encoding="utf-8"))
    home=tempfile.mkdtemp(prefix="loya-shell-")
    try:
        rc=".zshrc" if spec["shell"]=="zsh" else ".bashrc"
        shutil.copy(spec["rc"],os.path.join(home,rc))
        for name in spec.get("files",[]):open(os.path.join(home,name),"w").close()
        env={"HOME":home,"SHELL":shutil.which(spec["shell"]),"TERM":"xterm-256color","PATH":os.environ.get("PATH","/usr/bin:/bin"),"LANG":"C.UTF-8","USER":getpass.getuser()}
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack("HHHH",30,int(spec["cols"]),0,0))
        def child():
            os.setsid()
            fcntl.ioctl(0,termios.TIOCSCTTY,0)
        proc=subprocess.Popen([env["SHELL"],"-i"],stdin=slave,stdout=slave,stderr=slave,preexec_fn=child,cwd=home,env=env,close_fds=True)
        os.close(slave)
        events=[]
        def pump(seconds):
            end=time.time()+seconds
            while time.time()<end:
                ready,_,_=select.select([master],[],[],0.05)
                if not ready:continue
                try:data=os.read(master,65536)
                except OSError:return
                if b"\x1b[6n" in data:os.write(master,b"\x1b[30;1R")
                events.append({"out":data.decode("utf-8","replace")})
        pump(2.5)
        for step in spec["steps"]:
            if "control" in step:
                events.append({"control":step["control"]})
                os.write(master,step["control"].encode())
            else:
                events.append({"submit":step["submit"],"jobId":step["jobId"],"sent":step["sent"]})
                os.write(master,step["sent"].encode())
            pump(float(step.get("wait",1.2)))
        proc.kill()
        proc.wait()
    finally:
        shutil.rmtree(home,ignore_errors=True)
    swaps=[(home,"/home/user"),(getpass.getuser(),"user"),(socket.gethostname(),"kali")]
    for ev in events:
        if "out" in ev:
            for old,new in swaps:ev["out"]=ev["out"].replace(old,new)
    json.dump({"shell":spec["shell"],"cols":spec["cols"],"rc":spec["rc"],"events":events},open(out_path,"w",encoding="utf-8"),indent=0,ensure_ascii=True)
if __name__=="__main__":
    main(sys.argv[1],sys.argv[2])
