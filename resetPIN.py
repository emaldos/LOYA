from Cores.Services import security_service as security
def main():
    ok,msg=security.reset_pin()
    print(msg)
    return 0 if ok else 1
if __name__=="__main__":
    raise SystemExit(main())
