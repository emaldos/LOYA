"""Offline, generic mitigation and detection guidance per weakness class (CWE), shipped with the app.

Data only - no network, no imports. This is NOT vendor guidance: it describes how the weakness class is normally
fixed and spotted, and CVE Intel always labels it as generic next to the vendor / CISA KEV guidance of a CVE.
Text is plain ASCII, one sentence per bullet, no markup.
"""
import re
def _e(name,mitigations,detection):return {"name":name,"mitigations":list(mitigations),"detection":list(detection)}
CWE={
"20":_e("Improper Input Validation",(
    "Validate every input on the server against an allow-list of type, length, range and format before it is used.",
    "Reject invalid input instead of trying to repair it, and validate again after decoding or canonicalising.",
    "Treat data from files, headers, APIs, queues and other internal systems as untrusted, not only form fields.",
    "Use a schema or a typed parser at each trust boundary so validation cannot be skipped by one code path."),(
    "Log and alert on validation failures per client, since a burst usually means probing or fuzzing.",
    "Fuzz the exposed parsers and endpoints and review crashes and unhandled exceptions in the error logs.",
    "Use SAST to find request data that reaches sensitive sinks without passing a validation routine.")),
"22":_e("Improper Limitation of a Pathname to a Restricted Directory ('Path Traversal')",(
    "Do not build file paths from user input; map user-supplied identifiers to server-side file names instead.",
    "Canonicalise the final path and verify that it still starts with the intended base directory before opening it.",
    "Reject input that contains path separators, dot-dot sequences, null bytes or absolute paths, including encoded forms.",
    "Run the service with a low-privilege account and a chroot, container or restricted file-system view."),(
    "Search web and application logs for ../, ..\\, %2e%2e, %252e and absolute paths such as /etc/passwd or C:\\Windows in parameters.",
    "Alert on the service account reading files outside its application and data directories.",
    "Enable the path traversal rules of the WAF and review what they block.")),
"59":_e("Improper Link Resolution Before File Access ('Link Following')",(
    "Open files with flags that refuse symbolic links (O_NOFOLLOW) and operate on file handles rather than on path names.",
    "Create temporary and working files in directories that only the service account can write to.",
    "Drop privileges before touching files in locations that other users can write to.",
    "On Windows, block redirection through junctions and object-manager symlinks for privileged file operations."),(
    "Audit privileged processes that write, delete or change permissions in world-writable or user-writable directories.",
    "Alert on the creation of symbolic links, hard links or junctions inside temp, log and spool directories.",
    "Review code for check-then-use patterns on path names such as access() followed by open().")),
"74":_e("Improper Neutralization of Special Elements in Output Used by a Downstream Component ('Injection')",(
    "Pass data to interpreters through structured, parameterised APIs instead of concatenating strings.",
    "Encode or escape data for the exact syntax of the downstream component at the point where it is emitted.",
    "Validate input against an allow-list and reject characters that are special to the downstream interpreter.",
    "Give the downstream component the least privilege it needs so a successful injection has a small blast radius."),(
    "Log the commands, queries and templates that the application sends downstream and alert on unexpected syntax.",
    "Use SAST taint tracking to find untrusted data that reaches interpreter sinks.",
    "Watch for interpreter error messages in responses and logs, which often reveal injection probing.")),
"77":_e("Improper Neutralization of Special Elements used in a Command ('Command Injection')",(
    "Avoid building command lines from user input; call library functions or APIs that do the job without a shell.",
    "When a program must be run, pass arguments as an array to an exec-style call and never through a shell.",
    "Restrict input to an allow-list of expected values and reject shell metacharacters and argument prefixes such as a leading dash.",
    "Run the process as an unprivileged account inside a sandbox or container with no unnecessary binaries."),(
    "Alert on web or service processes that spawn shells or tools such as sh, bash, cmd, powershell, curl, wget or nc.",
    "Search request logs for metacharacters such as ; | & ` $( ) and encoded newlines in parameters.",
    "Review code for calls to system, popen, exec and similar functions that take concatenated strings.")),
"78":_e("Improper Neutralization of Special Elements used in an OS Command ('OS Command Injection')",(
    "Replace shell commands with native library calls wherever one exists.",
    "Execute programs with an argument array and without a shell so that metacharacters are never interpreted.",
    "Accept only allow-listed values for anything that becomes part of a command, and reject everything else.",
    "Run the service with least privilege and remove interpreters and download tools it does not need."),(
    "Use EDR or process auditing to alert when a server process starts a shell, a script interpreter or a network tool.",
    "Search logs for ; | & ` $( ) and URL-encoded variants in request parameters, headers and file names.",
    "Monitor for unexpected outbound connections and new files in web roots and temp directories.")),
"79":_e("Improper Neutralization of Input During Web Page Generation ('Cross-site Scripting')",(
    "Encode all untrusted data for the output context (HTML body, attribute, JavaScript, CSS, URL) at the point of output.",
    "Use a templating framework that escapes by default and avoid raw-HTML sinks such as innerHTML and document.write.",
    "Sanitise user-supplied rich text with a maintained allow-list HTML sanitiser.",
    "Deploy a strict Content-Security-Policy without unsafe-inline and set HttpOnly and SameSite on session cookies.",
    "Validate and restrict URL schemes for user-supplied links to http and https."),(
    "Collect Content-Security-Policy violation reports and review them for injected script sources.",
    "Search request logs and stored content for script tags, event-handler attributes and javascript: URLs.",
    "Use DAST and code review to find reflected or stored input that reaches HTML output without encoding.")),
"89":_e("Improper Neutralization of Special Elements used in an SQL Command ('SQL Injection')",(
    "Use parameterised queries or prepared statements for every database call and never concatenate input into SQL.",
    "Use allow-lists for identifiers that cannot be bound as parameters, such as table names and sort columns.",
    "Connect to the database with a least-privilege account that cannot read other schemas, write files or run commands.",
    "Return generic error messages to clients and keep detailed database errors in server logs only."),(
    "Alert on database errors about syntax, on UNION SELECT, stacked queries, sleep and benchmark calls and on comment sequences in parameters.",
    "Monitor the database for unusual query shapes, large result sets and access to system catalog tables by the application account.",
    "Enable the SQL injection rules of the WAF and use SAST to find string-built queries.")),
"94":_e("Improper Control of Generation of Code ('Code Injection')",(
    "Never pass untrusted input to eval, exec, dynamic includes, template compilers or expression evaluators.",
    "Replace dynamic code with data-driven logic such as lookup tables and allow-listed operations.",
    "If dynamic evaluation is unavoidable, run it in a hardened sandbox with no file, process or network access.",
    "Run the application with least privilege and keep the code directories read-only for the service account."),(
    "Use SAST and code review to locate eval-style functions, dynamic includes and template rendering of user input.",
    "Alert on the application process spawning shells or interpreters and on new or modified script files in the application tree.",
    "Search logs for template or expression syntax such as ${ }, {{ }}, <% %> and language keywords in parameters.")),
"119":_e("Improper Restriction of Operations within the Bounds of a Memory Buffer",(
    "Apply the vendor patch, because memory-safety flaws can rarely be mitigated reliably by configuration.",
    "Check lengths and indexes against the real buffer size before every read, write and copy.",
    "Use memory-safe languages or bounds-checked containers and string functions for new and rewritten code.",
    "Enable compiler and OS hardening such as ASLR, DEP/NX, stack protectors, CFI and fortified sources.",
    "Reduce exposure by disabling the affected feature or restricting network access to it until it is patched."),(
    "Monitor for crashes, core dumps and service restarts of the affected component and collect the crash reports.",
    "Test builds with AddressSanitizer and fuzzing to find out-of-bounds accesses before release.",
    "Use EDR exploit-protection telemetry to alert on shellcode-like behaviour or unexpected child processes.")),
"120":_e("Buffer Copy without Checking Size of Input ('Classic Buffer Overflow')",(
    "Apply the vendor patch as the primary fix.",
    "Replace unbounded copies such as strcpy, strcat, sprintf and gets with size-limited equivalents and check the result.",
    "Validate the length of input against the destination size before copying.",
    "Build with stack protectors, fortified sources, ASLR and DEP/NX enabled."),(
    "Flag unbounded copy functions with SAST and compiler warnings and treat them as build failures.",
    "Fuzz the parsers that take external input while running under AddressSanitizer.",
    "Monitor for crashes and unexpected restarts of the affected service, and for oversized fields in network traffic.")),
"121":_e("Stack-based Buffer Overflow",(
    "Apply the vendor patch as the primary fix.",
    "Bound every write to a stack buffer by its declared size and avoid variable-length stack arrays sized by input.",
    "Build with stack canaries, shadow stacks or CET, ASLR and non-executable stacks.",
    "Restrict network access to the affected service until it is updated."),(
    "Alert on stack-smashing aborts, segmentation faults and repeated restarts of the affected process.",
    "Use fuzzing with AddressSanitizer and SAST rules for fixed-size local buffers that receive external data.",
    "Use EDR exploit-mitigation events to spot return-oriented programming or stack pivot attempts.")),
"122":_e("Heap-based Buffer Overflow",(
    "Apply the vendor patch as the primary fix.",
    "Compute allocation sizes with overflow-checked arithmetic and verify lengths before every heap write.",
    "Use hardened allocators and enable heap integrity checks, ASLR and control-flow integrity.",
    "Disable or restrict the affected feature or file format until the update is installed."),(
    "Monitor for heap-corruption aborts, allocator integrity errors and crashes in the affected component.",
    "Fuzz file and protocol parsers under AddressSanitizer or a debug allocator.",
    "Alert on unexpected child processes or code execution from the affected process using EDR telemetry.")),
"125":_e("Out-of-bounds Read",(
    "Apply the vendor patch as the primary fix.",
    "Validate offsets, lengths and counts taken from input against the actual buffer size before reading.",
    "Use bounds-checked accessors or memory-safe languages for parsing untrusted data.",
    "Limit exposure of the affected parser or service to trusted sources until it is updated."),(
    "Monitor for crashes of the affected component and for responses that are larger than expected or contain stray memory.",
    "Fuzz the affected parsers with AddressSanitizer or MemorySanitizer enabled.",
    "Review code for length fields from input that are used as read sizes or array indexes without a check.")),
"190":_e("Integer Overflow or Wraparound",(
    "Apply the vendor patch as the primary fix.",
    "Use overflow-checked arithmetic or wider types for sizes, counts and offsets derived from input.",
    "Validate numeric input against sane upper and lower bounds before it is used in calculations or allocations.",
    "Enable compiler options and sanitizers that trap on signed and unsigned overflow in test builds."),(
    "Use SAST to find multiplications and additions that feed memory allocation or copy sizes.",
    "Fuzz with extreme numeric values such as zero, negative numbers and values near the type maximum.",
    "Monitor for crashes and abnormal memory use in the affected component.")),
"200":_e("Exposure of Sensitive Information to an Unauthorized Actor",(
    "Return only the fields a caller is authorised to see and remove secrets, internal identifiers and debug data from responses.",
    "Disable verbose errors, stack traces, directory listings and debug endpoints in production.",
    "Enforce access control on every object, file and API that returns data, including exports and backups.",
    "Encrypt sensitive data in transit and at rest and keep it out of URLs, logs and caches."),(
    "Scan responses, logs and public storage for secrets, keys, tokens and personal data with DLP or secret-scanning rules.",
    "Alert on unusually large downloads or enumeration patterns against data-returning endpoints.",
    "Review error handling and serialisation code for objects that are returned whole instead of field by field.")),
"269":_e("Improper Privilege Management",(
    "Run services, scheduled tasks and containers with the least privilege they need and never as root or SYSTEM by default.",
    "Drop elevated privileges as early as possible and check that the drop succeeded.",
    "Separate administrative functions from normal ones and require re-authentication for privileged actions.",
    "Review group memberships, sudo rules, setuid binaries and token privileges and remove those that are not needed."),(
    "Alert on new members of privileged groups, new sudo rules, new setuid files and new services or scheduled tasks.",
    "Monitor for processes whose privilege level is higher than that of their parent.",
    "Audit use of privileged accounts and compare it with the expected administrative activity.")),
"276":_e("Incorrect Default Permissions",(
    "Install files, directories, registry keys and services with permissions that only the owning account and administrators can modify.",
    "Set a restrictive umask or explicit ACLs in installers and at service start instead of relying on inherited defaults.",
    "Check permissions after installation and after every update, since updates may reset them.",
    "Keep executables and configuration that privileged processes load out of user-writable locations."),(
    "Scan for world-writable or user-writable files, directories and service binaries in program and system paths.",
    "Monitor changes to executables, libraries and configuration of privileged services with file integrity monitoring.",
    "Include permission checks in build and deployment pipelines.")),
"284":_e("Improper Access Control",(
    "Deny by default and enforce access decisions on the server for every request, not in the client.",
    "Centralise authorisation in one well-tested component and apply it to every route, API and background job.",
    "Restrict management interfaces to trusted networks and require strong authentication for them.",
    "Test access control with accounts of every role, including unauthenticated users, as part of release testing."),(
    "Log access-control decisions and alert on repeated denials or on success for resources outside a user's role.",
    "Monitor administrative endpoints for requests from unexpected sources.",
    "Review routes and handlers for any that lack an authorisation check.")),
"285":_e("Improper Authorization",(
    "Check on the server that the authenticated user is allowed to perform the action on the specific resource for every request.",
    "Use a deny-by-default policy and a single authorisation layer rather than per-page checks.",
    "Do not rely on hidden fields, client-side roles or unguessable URLs to protect functions.",
    "Add automated tests that call each function with lower-privileged and cross-tenant accounts."),(
    "Log the user, action and object of sensitive operations and alert on actions outside the user's role.",
    "Look for sequential or enumerated object identifiers requested by one session.",
    "Review code for handlers that load objects by identifier without an ownership or role check.")),
"287":_e("Improper Authentication",(
    "Apply the vendor patch and, until then, restrict access to the affected interface to trusted networks or a VPN.",
    "Use a proven authentication framework and require every protected endpoint to pass through it.",
    "Enforce multi-factor authentication for remote and administrative access.",
    "Rotate credentials, sessions and API tokens that may have been exposed while the flaw was present.",
    "Rate-limit and lock out repeated failed logins."),(
    "Alert on successful access to protected functions that has no matching login event.",
    "Monitor for logins from new locations or devices, impossible travel and bursts of failed attempts.",
    "Review authentication logs of the affected product for the bypass indicators published by the vendor.")),
"295":_e("Improper Certificate Validation",(
    "Validate the full certificate chain, the host name, the validity period and revocation on every TLS connection.",
    "Never disable verification or accept all certificates in production code or configuration.",
    "Pin certificates or public keys for high-value connections where operationally possible.",
    "Keep the trust store up to date and remove test or private CAs that are not needed."),(
    "Search code and configuration for disabled verification such as verify=False, InsecureSkipVerify or trust-all managers.",
    "Test clients against a TLS interception proxy with an untrusted certificate and confirm that they refuse to connect.",
    "Monitor the network for unexpected certificates or issuers on connections to your services.")),
"306":_e("Missing Authentication for Critical Function",(
    "Apply the vendor patch and block access to the affected function from untrusted networks until it is installed.",
    "Require authentication for every management, configuration, file and data function, including internal APIs.",
    "Place administrative interfaces behind a VPN, a jump host or an authenticating reverse proxy.",
    "Disable the affected feature or service if it is not needed."),(
    "Scan your own address space for the affected service or endpoint being reachable without credentials.",
    "Alert on requests to administrative or critical endpoints that carry no session or credentials.",
    "Review firewall and proxy logs for external access to management ports.")),
"327":_e("Use of a Broken or Risky Cryptographic Algorithm",(
    "Replace broken algorithms such as MD5, SHA-1, DES, 3DES, RC4 and ECB mode with current standards such as SHA-256, AES-GCM or ChaCha20-Poly1305.",
    "Use vetted cryptographic libraries and high-level APIs instead of custom constructions.",
    "Disable obsolete protocol versions and cipher suites and require TLS 1.2 or later.",
    "Plan for algorithm agility so algorithms and key sizes can be changed without a redesign."),(
    "Scan services with a TLS configuration scanner and flag weak protocols, ciphers and key sizes.",
    "Use SAST or dependency scanning to find calls to weak hash, cipher and random functions.",
    "Inventory certificates and keys and alert on weak signature algorithms or short keys.")),
"352":_e("Cross-Site Request Forgery (CSRF)",(
    "Require an unpredictable anti-CSRF token, bound to the session, on every state-changing request and verify it on the server.",
    "Set SameSite=Lax or Strict on session cookies and do not change state with GET requests.",
    "Verify the Origin or Referer header for sensitive requests as defence in depth.",
    "Require re-authentication or a second factor for high-impact actions."),(
    "Log and alert on state-changing requests with a missing or invalid token or with a foreign Origin header.",
    "Test each state-changing endpoint with a cross-site form or DAST tool to confirm that it is rejected.",
    "Review code for handlers that are exempt from the framework's CSRF protection.")),
"362":_e("Concurrent Execution using Shared Resource with Improper Synchronization ('Race Condition')",(
    "Apply the vendor patch, since race conditions usually need a code fix.",
    "Protect shared state with locks, atomic operations or transactions and keep the check and the use inside one critical section.",
    "Use atomic file operations and file handles instead of repeated path lookups.",
    "Design operations to be idempotent and enforce uniqueness and limits in the database rather than in application code."),(
    "Test with thread and race sanitizers and with stress tests that send the same request many times in parallel.",
    "Alert on bursts of identical concurrent requests to sensitive actions such as redeem, transfer or permission changes.",
    "Monitor for inconsistent state such as duplicate records or balances that do not reconcile.")),
"384":_e("Session Fixation",(
    "Issue a new session identifier after login, after privilege changes and after logout.",
    "Accept session identifiers only from cookies and never from URLs or request bodies.",
    "Reject session identifiers that the server did not generate itself.",
    "Set Secure, HttpOnly and SameSite on session cookies and expire idle sessions."),(
    "Verify in testing that the session identifier before login differs from the one after login.",
    "Alert on one session identifier being used from different addresses or user agents.",
    "Search logs for session identifiers passed in URLs.")),
"400":_e("Uncontrolled Resource Consumption",(
    "Set limits on request size, body length, nesting depth, item counts and processing time for every input.",
    "Apply rate limiting and quotas per client, per account and per source address.",
    "Use timeouts, bounded queues and worker pools so one request cannot exhaust memory, threads or file handles.",
    "Put a reverse proxy, CDN or DDoS protection service in front of exposed services.",
    "Apply the vendor patch for the specific trigger."),(
    "Monitor CPU, memory, connection counts, queue depth and response times and alert on sudden changes.",
    "Alert on single clients that send unusually large, slow or numerous requests.",
    "Load-test and fuzz with oversized and deeply nested input to find missing limits.")),
"416":_e("Use After Free",(
    "Apply the vendor patch as the primary fix, because use-after-free flaws cannot normally be configured away.",
    "Set pointers to null after freeing and use ownership models or smart pointers that make dangling references impossible.",
    "Prefer memory-safe languages for new components that process untrusted data.",
    "Enable hardened allocators, control-flow integrity and other exploit mitigations of the platform.",
    "Disable or restrict the affected feature, such as a scripting engine or file format, until the update is installed."),(
    "Monitor for crashes of the affected application and collect crash dumps for triage.",
    "Fuzz with AddressSanitizer to catch use of freed memory during testing.",
    "Use EDR exploit-protection alerts and watch for unexpected child processes of browsers, document readers and services.")),
"426":_e("Untrusted Search Path",(
    "Call programs and load libraries by absolute path instead of relying on the search path.",
    "Set a known, minimal PATH and library search path at start and remove the current directory and user-writable entries.",
    "Make sure every directory in the search path of privileged processes is writable by administrators only.",
    "Verify signatures of the executables and libraries that privileged code loads."),(
    "Audit PATH and library path values of services and scheduled tasks for user-writable or relative entries.",
    "Alert on executables or libraries that load from temp, download or user-profile directories into privileged processes.",
    "Review code for process creation and library loading by bare file name.")),
"427":_e("Uncontrolled Search Path Element",(
    "Load libraries by fully qualified path and enable safe DLL search mode or the equivalent on the platform.",
    "Remove user-writable directories from the system PATH and from application directories of privileged software.",
    "Install software in locations that only administrators can modify and fix weak directory ACLs.",
    "Require signed libraries where the platform supports it."),(
    "Use process monitoring to find attempts to load libraries that do not exist from writable directories.",
    "Alert on new DLL or shared-object files created in application, PATH or working directories.",
    "Monitor for unsigned modules loaded by privileged or signed processes.")),
"434":_e("Unrestricted Upload of File with Dangerous Type",(
    "Accept only an allow-list of file extensions and verify the content type by inspecting the file itself.",
    "Store uploads outside the web root or in object storage, with generated names and no execute permission.",
    "Serve uploaded files from a separate domain with Content-Disposition: attachment and a fixed content type.",
    "Limit file size, scan uploads for malware and re-encode images and documents where possible.",
    "Require authentication and authorisation for the upload function."),(
    "Alert on new script or executable files such as .php, .jsp, .aspx or .war appearing in upload or web directories.",
    "Monitor for the web server process executing files from upload locations or spawning shells.",
    "Search access logs for requests to recently uploaded files with executable extensions or double extensions.")),
"476":_e("NULL Pointer Dereference",(
    "Apply the vendor patch for the affected component.",
    "Check return values and pointers for null before use, especially after allocation, lookup and parsing calls.",
    "Handle missing or malformed fields explicitly instead of assuming they are present.",
    "Run the service under a supervisor that restarts it and rate-limit the triggering requests to reduce denial-of-service impact."),(
    "Monitor for segmentation faults, null-reference exceptions and repeated restarts of the service.",
    "Use static analysis and compiler nullability checks to find unchecked dereferences.",
    "Fuzz with missing and empty fields to reproduce crashes before attackers do.")),
"502":_e("Deserialization of Untrusted Data",(
    "Do not deserialise data from untrusted sources with native object serialisers; use simple data formats such as JSON with a strict schema.",
    "If native deserialisation is unavoidable, restrict it to an allow-list of expected classes.",
    "Sign or authenticate serialised data and verify it before deserialising.",
    "Keep libraries with known gadget chains up to date or remove them from the class path.",
    "Run the service with least privilege and restrict its outbound network access."),(
    "Alert on the application process spawning shells, interpreters or network tools.",
    "Inspect traffic and logs for serialised object markers such as rO0AB, AC ED 00 05 or type-carrying JSON fields.",
    "Monitor for unexpected outbound LDAP, RMI, DNS or HTTP connections from application servers.",
    "Use SAST to find calls to native deserialisation functions on request data.")),
"522":_e("Insufficiently Protected Credentials",(
    "Store passwords only as salted hashes from a slow algorithm such as Argon2id, bcrypt or scrypt.",
    "Keep secrets in a secrets manager or OS keystore and never in plain-text files, source code or environment dumps.",
    "Send credentials only over TLS and never in URLs.",
    "Rotate any credentials that were stored or transmitted without protection."),(
    "Run secret scanning on repositories, configuration, images and backups.",
    "Search logs and network captures for credentials in clear text or in query strings.",
    "Alert on access to credential stores and configuration files by unexpected processes or accounts.")),
"532":_e("Insertion of Sensitive Information into Log File",(
    "Never log passwords, tokens, session identifiers, keys or full personal and payment data.",
    "Mask or hash sensitive fields in a central logging filter rather than at each call site.",
    "Restrict read access to log files and log platforms and encrypt them at rest.",
    "Rotate secrets that were written to logs and purge the affected log entries where policy allows."),(
    "Scan log stores for secret patterns such as authorisation headers, API keys and password fields.",
    "Review logging statements that print whole request, response or configuration objects.",
    "Alert on bulk reads or exports of log data by unusual accounts.")),
"601":_e("URL Redirection to Untrusted Site ('Open Redirect')",(
    "Do not take redirect targets from user input; use server-side identifiers that map to fixed destinations.",
    "If a URL parameter is required, allow only relative paths or an allow-list of exact hosts after parsing the URL.",
    "Reject targets with other schemes, protocol-relative forms, backslashes or embedded credentials.",
    "Show an interstitial warning page before sending users to an external site."),(
    "Search logs for redirect parameters that contain external hosts, //, encoded slashes or javascript: schemes.",
    "Monitor phishing reports and referrers for links that abuse your domain as a redirector.",
    "Test every redirect and return-URL parameter with external targets during DAST.")),
"611":_e("Improper Restriction of XML External Entity Reference",(
    "Disable DTD processing and external entity resolution in every XML parser the application uses.",
    "Prefer simpler data formats such as JSON where XML is not required.",
    "Keep XML libraries up to date and use their secure-processing features.",
    "Restrict outbound network access and file-system permissions of the service that parses XML."),(
    "Inspect requests for DOCTYPE and ENTITY declarations and for SYSTEM or PUBLIC identifiers.",
    "Alert on outbound connections or DNS lookups from XML-processing servers to unexpected hosts.",
    "Use SAST to find XML parser instances that are created without hardened settings.")),
"613":_e("Insufficient Session Expiration",(
    "Invalidate the session on the server at logout, on password change and when privileges change.",
    "Set idle and absolute session timeouts that match the sensitivity of the application.",
    "Use short-lived access tokens with refresh tokens that can be revoked.",
    "Provide a way to list and revoke the active sessions of an account."),(
    "Test that a session token is rejected after logout and after the timeout has passed.",
    "Alert on sessions that stay active for unusually long or are reused after a password reset.",
    "Review token lifetimes and revocation handling in configuration and code.")),
"639":_e("Authorization Bypass Through User-Controlled Key",(
    "Verify on the server that the current user owns or may access the object behind every identifier in a request.",
    "Derive the user and tenant from the session instead of from request parameters.",
    "Use unpredictable identifiers as defence in depth, but never as the only control.",
    "Add automated tests that request the objects of another user and another tenant."),(
    "Alert on one session requesting many different object identifiers or sequentially increasing ones.",
    "Log object owner and requester for sensitive reads and writes and alert when they differ without a sharing rule.",
    "Review data-access code for lookups by identifier with no ownership filter.")),
"732":_e("Incorrect Permission Assignment for Critical Resource",(
    "Give files, directories, keys, shares, buckets and services the minimum permissions needed and remove world or Everyone access.",
    "Set permissions explicitly at creation time rather than changing them afterwards.",
    "Keep secrets, configuration and executables used by privileged processes writable by administrators only.",
    "Review permissions regularly and after every deployment or upgrade."),(
    "Scan for world-readable secrets, world-writable files and publicly accessible storage or shares.",
    "Use file integrity monitoring and audit logs to alert on permission changes to critical resources.",
    "Include permission baselines in configuration compliance checks.")),
"770":_e("Allocation of Resources Without Limits or Throttling",(
    "Enforce upper limits on sizes, counts, connections, sessions and allocations that a single client can cause.",
    "Apply rate limiting, quotas and back-pressure per user and per source address.",
    "Use timeouts and release resources promptly on error paths.",
    "Apply the vendor patch for the specific unbounded allocation."),(
    "Monitor memory, file handles, threads and connection counts and alert on steady growth or spikes.",
    "Alert on clients that open many connections or send requests with very large counts or sizes.",
    "Load-test with hostile sizes and counts to confirm that the limits hold.")),
"787":_e("Out-of-bounds Write",(
    "Apply the vendor patch as the primary fix, because out-of-bounds writes are often exploitable for code execution.",
    "Validate indexes, lengths and offsets against the buffer size before every write.",
    "Use memory-safe languages or bounds-checked containers for code that parses untrusted data.",
    "Enable ASLR, DEP/NX, stack protectors, CFI and hardened allocators.",
    "Disable the affected feature or restrict network access to it until the update is installed."),(
    "Monitor for crashes, memory-corruption aborts and unexpected restarts of the affected component.",
    "Fuzz parsers and protocol handlers under AddressSanitizer.",
    "Use EDR exploit-protection events and alert on unexpected child processes or injected threads.")),
"798":_e("Use of Hard-coded Credentials",(
    "Apply the vendor update that removes the built-in credentials, or change them if the product allows it.",
    "Remove credentials and keys from source code, firmware and images and load them from a secrets manager at run time.",
    "Give every installation unique credentials and force a change at first use.",
    "Rotate any hard-coded secret that has shipped and treat it as compromised.",
    "Restrict network access to the affected interface until the credentials are gone."),(
    "Run secret scanning on source repositories, build artefacts, containers and firmware images.",
    "Alert on logins that use known default or vendor account names.",
    "Monitor authentication logs of the affected product for access from unexpected sources.")),
"862":_e("Missing Authorization",(
    "Add a server-side authorisation check to every function and data access, with deny as the default.",
    "Enforce authorisation in a central layer or middleware so new endpoints cannot be published without it.",
    "Restrict access to the affected function at the network or proxy level until it is patched.",
    "Test every endpoint with unauthenticated and low-privileged accounts."),(
    "Alert on low-privileged or anonymous sessions that successfully call administrative or sensitive endpoints.",
    "Compare the list of routes with the list of routes that have an authorisation rule.",
    "Review access logs of the affected product for the endpoints named in the advisory.")),
"863":_e("Incorrect Authorization",(
    "Correct the authorisation logic so that it checks the right user, role, tenant and object for each action.",
    "Evaluate permissions on the server at the time of the action and not from cached or client-supplied values.",
    "Use deny-by-default policies and cover role and tenant boundaries with automated tests.",
    "Apply the vendor patch and review what the affected roles were able to reach."),(
    "Log authorisation decisions with user, role, action and object and alert on cross-role or cross-tenant access.",
    "Run a permission matrix test with every role against every function.",
    "Review code for checks that compare the wrong attribute or that run after the action.")),
"917":_e("Improper Neutralization of Special Elements used in an Expression Language Statement ('Expression Language Injection')",(
    "Never evaluate user input as an expression or template; pass it only as data to a fixed expression.",
    "Disable expression evaluation and message lookups in components that do not need them.",
    "Update the affected framework or library to a version that no longer evaluates untrusted input.",
    "Restrict outbound network access of the application server and run it with least privilege."),(
    "Search requests and logs for expression syntax such as ${ }, #{ }, %{ } and jndi: lookups.",
    "Alert on the application process starting shells or making unexpected LDAP, RMI or DNS connections.",
    "Use SAST to find user input that reaches expression or template evaluation functions.")),
"918":_e("Server-Side Request Forgery (SSRF)",(
    "Allow outbound requests only to an allow-list of hosts and schemes, checked after the URL has been parsed and resolved.",
    "Block requests to loopback, link-local, private and cloud metadata addresses, including after redirects and DNS rebinding.",
    "Send server-side fetches through an egress proxy or an isolated network segment with no access to internal services.",
    "Require IMDSv2 or the equivalent protection for cloud metadata services.",
    "Do not return raw responses of server-side requests to the client."),(
    "Alert on requests from application servers to 169.254.169.254, localhost and internal address ranges.",
    "Search request parameters for URLs, IP addresses in unusual encodings and schemes such as file, gopher and dict.",
    "Monitor egress proxy and DNS logs for destinations that the application has no reason to contact.")),
"1188":_e("Initialization of a Resource with an Insecure Default",(
    "Change default passwords, keys, community strings and sample configuration before the system goes into service.",
    "Disable features, services and accounts that are enabled by default but not needed.",
    "Deploy from a hardened baseline or configuration template rather than from the factory defaults.",
    "Check the configuration again after upgrades, since defaults may be restored."),(
    "Scan for default credentials, sample content and default-enabled services on your systems.",
    "Compare running configuration with a hardening benchmark and alert on drift.",
    "Alert on logins that use default account names.")),
"1321":_e("Improperly Controlled Modification of Object Prototype Attributes ('Prototype Pollution')",(
    "Update the affected library to a version that blocks __proto__, constructor and prototype keys.",
    "Validate JSON input against a schema and reject unexpected keys before merging or cloning objects.",
    "Use Map or objects created with a null prototype for data keyed by user input.",
    "Freeze built-in prototypes where the application allows it."),(
    "Search request bodies and query strings for __proto__, constructor and prototype keys.",
    "Use dependency scanning to find libraries with known prototype pollution issues.",
    "Review code for recursive merge, clone and path-assignment helpers that take user-controlled keys.")),
}
FALLBACK=_e("General vulnerability guidance",(
    "Install the vendor's fixed version or patch as soon as it is available and confirm the installed version afterwards.",
    "Until it is patched, apply the vendor's workaround, disable the affected feature or restrict network access to it.",
    "Remove the affected product from direct internet exposure and place management interfaces behind a VPN.",
    "Run the affected software with least privilege and segment it from sensitive systems.",
    "Keep an inventory of where the product is installed so that every instance is covered."),(
    "Check the vendor advisory for indicators of compromise and search your logs for them.",
    "Monitor the affected systems for crashes, unexpected processes, new accounts and unusual outbound connections.",
    "Scan your environment for the vulnerable version to confirm that remediation is complete."))
_ID_RX=re.compile(r"^\s*(?:CWE-)?0*(\d{1,6})\s*$",re.I)
def _key(cwe):
    if isinstance(cwe,bool) or cwe is None:return ""
    if isinstance(cwe,int):return str(cwe) if cwe>0 else ""
    m=_ID_RX.match(str(cwe))
    return m.group(1) if m else ""
def guidance(cwe):
    """Generic guidance for one CWE ("CWE-79", "79" or 79) as {"cwe","name","mitigations","detection"}, or None when not covered."""
    k=_key(cwe)
    e=CWE.get(k)
    if not e:return None
    return {"cwe":"CWE-"+k,"name":e["name"],"mitigations":list(e["mitigations"]),"detection":list(e["detection"])}
def name(cwe):
    """Official CWE name, or "" when this CWE is not in the shipped list."""
    e=CWE.get(_key(cwe))
    return e["name"] if e else ""
