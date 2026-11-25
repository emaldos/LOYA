import re
SKILL_MARKER="<!-- loya-element-rule -->"
ELEMENT_MEANINGS=(
    ("IP address","IPv4",("ip","ipv4","ip4","ipaddr","ipaddress","ipv4address","targetip","targetipv4","tgtip","rhost","rhosts","rip","remoteip","remotehost","hostip","victimip","boxip","machineip","serverip")),
    ("IPv6 address","IPv6",("ipv6","ip6","ipv6address","targetipv6")),
    ("attacker IP","LHOST",("lhost","localip","attackerip","attackip","myip","kaliip","listenip","listenerip","callbackip","tun0","tun0ip","vpnip")),
    ("ports","Ports",("port","ports","rport","rports","targetport","targetports","portlist","openports","tcpports","udpports","serviceport")),
    ("listener port","LPORT",("lport","listenport","listenerport","localport","callbackport")),
    ("hostname","Host",("host","hostname","fqdn","targethost","targethostname","server","servername","computername","vhost")),
    ("domain","Domain",("domain","domainname","addomain","dnsdomain","targetdomain","realm","rootdomain")),
    ("domain controller","DC_IP",("dc","dcip","dchost","domaincontroller","dcname","pdc")),
    ("URL","URL",("url","targeturl","baseurl","website","site","weburl","uri","endpoint","rooturl","webapp")),
    ("username","Username",("user","username","usr","login","loginname","account","accountname","uname")),
    ("password","Password",("pass","password","passwd","pwd","pw","userpassword")),
    ("hash","Hash",("hash","nthash","ntlm","ntlmhash","lmhash","passwordhash")),
    ("wordlist","Wordlist",("wordlist","wl","dict","dictionary","wordfile","fuzzlist","dirlist","directorylist")),
    ("user list","Userlist",("userlist","usersfile","userfile","usernames","users","usernamelist")),
    ("password list","Passlist",("passlist","passwordlist","passwords","passfile","passwordfile","pwlist")),
    ("network interface","Interface",("interface","iface","nic","adapter","netinterface","eth")),
    ("output file","Output",("output","out","outfile","outputfile","outputdir","outdir","outputfolder","outputpath","logfile")),
    ("network range","CIDR",("cidr","subnet","range","network","netrange","iprange","targetrange","scope")),
    ("share","Share",("share","smbshare","sharename")),
)
_ALIAS_TO_MEANING={alias:index for index,(_label,_default,aliases) in enumerate(ELEMENT_MEANINGS) for alias in aliases}
_NAME_PREFIXES=("target","tgt","remote","victim","the","main")
_NAME_SUFFIXES=("address","addr","value","path","file","name")
ELEMENT_RULE_TITLE="Rules for elements ({Name} placeholders)"
ELEMENT_RULE_LINES=(
    "Elements are LOYA's target placeholders. A command that contains {Name} is filled from the live target's value for that element, so the operator can reuse the same command on any target.",
    "Every value in a command that changes per target or per run must be an element, never a literal: IP addresses, hostnames, domains, URLs, ports and port lists, usernames, passwords, hashes, wordlists and other input files, network interfaces, listener addresses and ports, output files and folders. Fixed tool flags and options stay as they are.",
    "Before you write a command, call parameter_list to see the elements that already exist. When one means the same thing, reuse its exact name and spelling, whatever it is called: an IP address may already be {IPv4}, {IP}, {Target_IP} or {RHOST}. Match by meaning, not only by name. parameter_match maps the names you plan to use onto the existing elements.",
    "Only when nothing fits, use a short clean new name such as {IPv4}, {Ports}, {URL}, {Domain}, {Username}, {Password}, {Wordlist}, {Interface} or {Output}. Saving the note or command registers a new element automatically; parameter_add registers one on its own.",
    "Example: ffuf -u {URL}/FUZZ -w {Wordlist} -o {Output}, not ffuf -u http://10.10.11.5/FUZZ -w /usr/share/wordlists/dirb/common.txt -o ffuf.json.",
)
ELEMENT_RULE_SHORT="Write every value that changes per target or per run (IP, host, domain, URL, ports, username, password, hash, wordlist, interface, output file) as a {Name} element, never a literal: reuse the element from parameter_list that means the same thing, whatever its name (IPv4, IP, RHOST...), or use a clean new name such as {IPv4} or {Ports}, which is registered when the command is saved."
ELEMENT_RULE_TEMPLATE="In every command, write each value that changes per target or per run (IP, host, domain, URL, ports, username, password, hash, wordlist, interface, output file) as a {Name} element, never a literal (write ffuf -u {URL}/FUZZ -w {Wordlist}, not a real address and path). Reuse the existing element below that means the same thing, whatever its name (an IP address may be {IPv4}, {IP} or {RHOST}); only when none fits, use a clean new name such as {IPv4} or {Ports}, which LOYA registers when the note or command is saved."
def element_rule_for_template(keys):
    return ELEMENT_RULE_TEMPLATE+" "+existing_elements_text(keys)
def element_rule_text():
    return ELEMENT_RULE_TITLE+":\n"+"\n".join("- "+line for line in ELEMENT_RULE_LINES)
def element_rule_markdown():
    return "## Elements ({Name} placeholders)\n"+"\n".join("- "+line for line in ELEMENT_RULE_LINES)
def expand_skill_text(text):
    if SKILL_MARKER not in text:return text
    return text.replace(SKILL_MARKER,element_rule_markdown())
def normalized_name(name):
    text=str(name or "").strip()
    if len(text)>=2 and text.startswith("{") and text.endswith("}"):text=text[1:-1]
    return re.sub(r"[^a-z0-9]","",text.lower())
def _name_candidates(compact):
    candidates=[compact]
    for prefix in _NAME_PREFIXES:
        if compact.startswith(prefix) and len(compact)>len(prefix):candidates.append(compact[len(prefix):])
    for candidate in list(candidates):
        for suffix in _NAME_SUFFIXES:
            if candidate.endswith(suffix) and len(candidate)>len(suffix):candidates.append(candidate[:-len(suffix)])
    for candidate in list(candidates):
        if candidate.endswith("s") and len(candidate)>2:candidates.append(candidate[:-1])
    return candidates
def _meaning_index(name):
    for candidate in _name_candidates(normalized_name(name)):
        if candidate in _ALIAS_TO_MEANING:return _ALIAS_TO_MEANING[candidate]
    return None
def element_meaning(name):
    index=_meaning_index(name)
    return ELEMENT_MEANINGS[index][0] if index is not None else ""
def clean_element_name(name):
    text=str(name or "").strip()
    if len(text)>=2 and text.startswith("{") and text.endswith("}"):text=text[1:-1]
    return re.sub(r"_+","_",re.sub(r"[^A-Za-z0-9_.]","_",text.strip())).strip("_")
def match_element(name,existing_keys):
    keys=[str(key) for key in existing_keys or [] if str(key or "").strip()]
    compact=normalized_name(name)
    index=_meaning_index(name)
    meaning=ELEMENT_MEANINGS[index][0] if index is not None else ""
    exact=next((key for key in keys if normalized_name(key)==compact),None) if compact else None
    if exact:return {"name":str(name or ""),"element":"{"+exact+"}","exists":True,"meaning":meaning or element_meaning(exact)}
    if index is not None:
        same=next((key for key in keys if _meaning_index(key)==index),None)
        if same:return {"name":str(name or ""),"element":"{"+same+"}","exists":True,"meaning":meaning}
        return {"name":str(name or ""),"element":"{"+ELEMENT_MEANINGS[index][1]+"}","exists":False,"meaning":meaning}
    clean=clean_element_name(name)
    return {"name":str(name or ""),"element":"{"+clean+"}" if clean else "","exists":False,"meaning":""}
def describe_elements(rows):
    out=[]
    for row in rows or []:
        if isinstance(row,dict):
            item=dict(row)
            item["meaning"]=element_meaning(item.get("key",""))
            out.append(item)
        else:out.append(row)
    return out
def current_element_names():
    try:
        from Cores.Services import targets_service as _targets_svc
        return _targets_svc.Store().ordered_keys()
    except Exception:return []
def existing_elements_text(keys,limit=150):
    names=[str(key) for key in keys or [] if str(key or "").strip()]
    if not names:return "No elements exist yet, so every element you write is a clean new name."
    shown=[]
    for key in names[:limit]:
        meaning=element_meaning(key)
        shown.append("{"+key+"}"+(" ("+meaning+")" if meaning else ""))
    more=f" and {len(names)-limit} more" if len(names)>limit else ""
    return "Elements that already exist (reuse these exact names): "+", ".join(shown)+more+"."
_IPV4_RE=re.compile(r"(?<![\w.{])((?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3})(/\d{1,2})?(?![\w.])")
_URL_RE=re.compile(r"\bhttps?://[^\s'\"<>]+",re.I)
_WORDLIST_RE=re.compile(r"(?<![\w{])(?:/usr/share/(?:wordlists|seclists|dirb|dirbuster|wfuzz|metasploit-framework/data/wordlists)|[\w./-]*seclists)[^\s'\"]*",re.I)
_PORT_LIST_RE=re.compile(r"(?:^|\s)(?:-p|--ports?)[ =]?(\d{1,5}(?:\s*[,-]\s*\d{1,5})+)(?=[\s;&|)]|$)")
_OUTPUT_RE=re.compile(r"(?:^|\s)(?:-o[ANGXJ]?|--output|--outfile)[ =]([^\s{'\"=:;&|()-][^\s'\"=:;&|()]*)(?=[\s;&|)]|$)")
_IGNORED_IPS=frozenset(("0.0.0.0","127.0.0.1","255.255.255.255"))
def _suggest(meaning_name,existing_keys):
    return match_element(meaning_name,existing_keys)["element"]
def hardcoded_values(command,existing_keys=None):
    text=str(command or "")
    keys=existing_keys or []
    found=[]
    seen=set()
    def add(value,meaning_name):
        if value in seen:return
        seen.add(value)
        found.append({"value":value,"use":_suggest(meaning_name,keys)})
    url_spans=[]
    for match in _URL_RE.finditer(text):
        url_spans.append(match.span())
        value=match.group(0).rstrip(".,;)")
        if value.split("://",1)[1].startswith("{"):continue
        add(value,"URL")
    for match in _IPV4_RE.finditer(text):
        if match.group(1) in _IGNORED_IPS or match.group(1).startswith("255."):continue
        if any(start<=match.start()<end for start,end in url_spans):continue
        add(match.group(0),"CIDR" if match.group(2) else "IP")
    for match in _WORDLIST_RE.finditer(text):add(match.group(0),"Wordlist")
    for match in _PORT_LIST_RE.finditer(text):add(match.group(1).replace(" ",""),"Ports")
    for match in _OUTPUT_RE.finditer(text):add(match.group(1),"Output")
    return found
def commands_in_note_html(content):
    try:
        from Cores.Services import targets_service as _targets_svc
        return _targets_svc._note_token_commands(content)
    except Exception:return []
def elements_in_commands(commands):
    try:
        from Cores.Services import targets_service as _targets_svc
    except Exception:return []
    out=[]
    seen=set()
    for command in commands or []:
        for key in _targets_svc._extract_keys_from_text(command):
            if key.lower() in seen:continue
            seen.add(key.lower())
            out.append(key)
    return out
def elements_report(commands,keys_before,keys_after):
    before={str(key).lower() for key in keys_before or []}
    used=elements_in_commands(commands)
    report={"used":used,"new":[key for key in used if key.lower() not in before]}
    hardcoded=[]
    for command in commands or []:
        for item in hardcoded_values(command,keys_after):
            if item not in hardcoded:hardcoded.append(item)
    if hardcoded:
        report["hardcoded"]=hardcoded
        report["fix"]="These literal values change per target or per run. Replace each one with the element in 'use' and save the command again, so the operator can reuse it on any target."
    return report
