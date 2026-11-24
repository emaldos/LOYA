import unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
MUST_REDACT=[
    ("mysql -u root -p SuperSecret123","SuperSecret123"),
    ("mysql -pSecretPass","SecretPass"),
    ("mysql -p 12345678","12345678"),
    ("hydra -p Winter2024 target","Winter2024"),
    ("smbclient //srv --password=Passw0rd!","Passw0rd!"),
    ("export API_KEY=sk-live-9f8a7b6c5d4e","sk-live-9f8a7b6c5d4e"),
    ("token=abc123def","abc123def"),
    ("PASSWORD: MyP@ssw0rd","MyP@ssw0rd"),
    ("passphrase = longsecretvalue","longsecretvalue"),
    ("curl -H 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9' https://x","eyJhbGciOiJIUzI1NiJ9"),
    ("psql postgresql://admin:hunter2@10.0.0.5/db","hunter2"),
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIK7MDENG","wJalrXUtnFEMIK7MDENG"),
]
MUST_PRESERVE=[
    "nmap -sV 10.0.0.1 -p 1-1000",
    "nmap -p- 10.0.0.1",
    "nmap -p 80,443,8080 target",
    "nmap -p22,80 host",
    "nmap -sV -p 22,80,443,8080 10.0.0.0/24",
    "nmap -p 1-65535 -T4 host",
    "docker run -p 8080:80 image",
    "docker run -p 127.0.0.1:8080:80 image",
    "grep password /etc/shadow",
    "ls -la",
    "curl -X POST https://api.example.com/v1",
]
class RedactionTests(unittest.TestCase):
    def test_secrets_are_removed(self):
        for command,secret in MUST_REDACT:
            safe,found=terminal.redact_secrets(command)
            self.assertTrue(found,"expected a redaction for %r"%command)
            self.assertNotIn(secret,safe,"secret leaked from %r"%command)
            self.assertIn("[redacted]",safe)
    def test_port_specs_and_benign_commands_are_untouched(self):
        for command in MUST_PRESERVE:
            safe,found=terminal.redact_secrets(command)
            self.assertEqual(command,safe,"wrongly altered %r"%command)
            self.assertEqual([],found)
    def test_private_key_block_is_collapsed(self):
        block="-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKC\nsecretblob\n-----END RSA PRIVATE KEY-----"
        safe,found=terminal.redact_secrets(block)
        self.assertNotIn("secretblob",safe)
        self.assertIn("BEGIN RSA PRIVATE KEY",safe)
        self.assertIn("END RSA PRIVATE KEY",safe)
    def test_multiple_secrets_on_one_line(self):
        safe,found=terminal.redact_secrets("password=a1 token=b2 api_key=c3")
        for secret in ("a1","b2","c3"):self.assertNotIn(secret,safe)
        self.assertEqual(3,sum(item["count"] for item in found))
    def test_empty_and_none_are_safe(self):
        self.assertEqual(("",[]),terminal.redact_secrets(""))
        self.assertEqual(("",[]),terminal.redact_secrets(None))
    def test_audit_records_without_raising(self):
        isolated=IsolatedData()
        isolated.start()
        try:
            self.assertTrue(terminal.audit_command("mysql -p Secret1","snippet","session-1",0))
        finally:
            isolated.stop()
if __name__=="__main__":
    unittest.main()
