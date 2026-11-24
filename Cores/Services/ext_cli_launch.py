"""AI panel > Agents > "Claude Code (your CLI)" / "Codex CLI (your CLI)": open the operator's OWN official CLI, interactively,
in a LOYA NG terminal tab (the same thing VS Code's integrated terminal does).

Policy (Anthropic Agent SDK docs): third party products may not offer claude.ai login or rate limits. So LOYA NG never
pipes its chat panel into the CLI and never runs the CLI non-interactively for the operator (no `-p` / `--print` /
`exec`). It only types the CLI's bare name into a terminal the operator then uses themselves, on their own account. The
CLI reaches LOYA NG through the `loya-note` MCP server that Connections registered, so AI Roles decide each call.

The connection state (installed / signed in / connected) comes from ext_connections_service (its background jobs);
this module only maps it and builds the launch line. It never runs the CLI itself.
"""
import os,shlex,subprocess
from Cores.Services import ext_connections_service as _conn
LAUNCH_ARGS={"claude_code":[],"codex_cli":[]}  # the bare interactive CLI: never -p / --print / exec
STATES=("not_installed","not_signed_in","not_connected","signin_unknown","ready")
LAUNCHABLE=("signin_unknown","ready")
_IS_WINDOWS=os.name=="nt"
class LaunchError(Exception):pass
def _tool(tool):
    tool=str(tool or "")
    if tool not in _conn.TOOLS:raise LaunchError(f"Unknown CLI: {tool}")
    return tool
def cli_state(st):
    """Map a Connections status() dict to one AI panel state. Same table as cliEntryState() in ext-cli-launch.js.
    A sign-in state LOYA NG could not read ("unknown") is its own state. It still allows Open in terminal: the CLI asks for its
    own sign-in when it starts."""
    st=st if isinstance(st,dict) else {}
    if not st.get("installed"):return "not_installed"
    if ((st.get("signin") or {}).get("state"))=="signed_out":return "not_signed_in"
    if not st.get("connected"):return "not_connected"
    if ((st.get("signin") or {}).get("state"))!="signed_in":return "signin_unknown"
    return "ready"
def _inside_git_repo(path):
    p=os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(p,".git")):return True
        parent=os.path.dirname(p)
        if parent==p:return False
        p=parent
def _workspace_root():
    """Where the CLI working folders live: a per-user folder OUTSIDE the LOYA NG checkout. The CLIs offer to "trust" their
    working folder, and Codex extends that trust to the enclosing git repository, so a folder under Data/ (inside the
    app's own repo) would hand the CLI the whole LOYA NG source tree.
    Windows: %LOCALAPPDATA%\\LOYA NG\\cli_workspace. Linux: $XDG_DATA_HOME/loya-ng/cli_workspace (default ~/.local/share)."""
    if _IS_WINDOWS:
        base=os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"),"AppData","Local")
        root=os.path.join(base,"LOYA NG","cli_workspace")
    else:
        base=os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"),".local","share")
        root=os.path.join(base,"loya-ng","cli_workspace")
    if _inside_git_repo(root):  # unusual setups (a home folder under git): fall back to the temp folder
        import tempfile
        root=os.path.join(tempfile.gettempdir(),"loya-ng-cli_workspace")
    return root
def workspace(tool):
    """A stable per-tool working folder for the CLI's terminal tab, outside any git repository (see _workspace_root)."""
    d=os.path.normpath(os.path.join(_workspace_root(),_tool(tool)))
    os.makedirs(d,exist_ok=True)
    return d
def launch_line(cli,shell_id,args=None):
    """The line typed into a LOYA terminal of that shell (the same quoting as the Sign in button), or "" for a WSL shell
    on Windows (the Windows CLI is not on its PATH)."""
    argv=[str(a) for a in (args or [])]
    sid=str(shell_id or "")
    if sid.startswith("wsl:"):return ""
    if sid in ("pwsh","powershell"):return " ".join(["&",_conn._ps_quote(cli)]+argv)
    if sid=="cmd":return " ".join(['"'+cli+'"']+argv)
    return " ".join(shlex.quote(x) for x in [cli]+argv)
def _ready_cli(tool):
    """The CLI path, or a clear error when it is missing or not connected. Cheap: no CLI is run here."""
    info=_conn.TOOL_INFO[tool]
    cli,_how=_conn.find_cli(tool)
    if not cli:raise LaunchError(f"{info['label']} was not found. Install it in Settings > AI > Agents > Connections.")
    if not os.path.isfile(_conn.connection_file(tool)):
        raise LaunchError(f"{info['label']} is not connected to LOYA NG yet. Connect it in Settings > AI > Agents > Connections.")
    return cli
def launch_command(tool,shell_id=""):
    """{"line","cwd","name"} for a new LOYA terminal tab running the CLI interactively."""
    tool=_tool(tool)
    cli=_ready_cli(tool)
    info=_conn.TOOL_INFO[tool]
    line=launch_line(cli,shell_id,LAUNCH_ARGS[tool])
    if line:_conn._audit("ext_connection",f"{info['label']}: opened in a LOYA NG terminal tab (interactive, the operator's own account)",True)
    return {"line":line,"cwd":workspace(tool),"name":info["client_label"]}
def launch_os_terminal(tool):
    """The OS terminal running the CLI interactively in its workspace folder (Terminal extension off, or only WSL shells)."""
    tool=_tool(tool)
    cli=_ready_cli(tool)
    info=_conn.TOOL_INFO[tool]
    cwd=workspace(tool)
    args=LAUNCH_ARGS[tool]
    posix="cd "+shlex.quote(cwd)+" && "+" ".join(shlex.quote(x) for x in [cli]+args)
    cmd_line='cd /d "'+cwd+'" && '+" ".join(['"'+cli+'"']+args)
    r=_conn._open_os_terminal(posix,cmd_line)
    _conn._audit("ext_connection",f"{info['label']}: opened in {r['terminal']} (interactive, the operator's own account)",True)
    return dict(r,cwd=cwd)
