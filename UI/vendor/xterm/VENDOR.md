# Vendored xterm.js

The files in this directory are unmodified copies of the prebuilt browser (UMD) bundles,
stylesheet and license files published to the npm registry by the xterm.js project. They are
loaded locally by the UI (no CDN, no network fetch at runtime). Nothing here was rebuilt,
minified, patched or reformatted; the trailing `sourceMappingURL` comments are kept as shipped,
but the `.map` files are not vendored.

The WebGL renderer addon (`@xterm/addon-webgl`) is deliberately not vendored: the terminal uses
xterm.js's built-in DOM renderer, which is the default when no renderer addon is loaded.

Date fetched: 2026-11-24

## Packages

| Package | Version | Tarball | Integrity |
| --- | --- | --- | --- |
| @xterm/xterm | 6.0.0 | https://registry.npmjs.org/@xterm/xterm/-/xterm-6.0.0.tgz | sha512-TQwDdQGtwwDt+2cgKDLn0IRaSxYu1tSUjgKarSDkUM0ZNiSRXFpjxEsvc/Zgc5kq5omJ+V0a8/kIM2WD3sMOYg== |
| @xterm/addon-fit | 0.11.0 | https://registry.npmjs.org/@xterm/addon-fit/-/addon-fit-0.11.0.tgz | sha512-jYcgT6xtVYhnhgxh3QgYDnnNMYTcf8ElbxxFzX0IZo+vabQqSPAjC3c1wJrKB5E19VwQei89QCiZZP86DCPF7g== |
| @xterm/addon-web-links | 0.12.0 | https://registry.npmjs.org/@xterm/addon-web-links/-/addon-web-links-0.12.0.tgz | sha512-4Smom3RPyVp7ZMYOYDoC/9eGJJJqYhnPLGGqJ6wOBfB8VxPViJNSKdgRYb8NpaM6YSelEKbA2SStD7lGyqaobw== |
| @xterm/addon-search | 0.16.0 | https://registry.npmjs.org/@xterm/addon-search/-/addon-search-0.16.0.tgz | sha512-9OeuBFu0/uZJPu+9AHKY6g/w0Czyb/Ut0A5t79I4ULoU4IfU5BEpPFVGQxP4zTTMdfZEYkVIRYbHBX1xWwjeSA== |
| @xterm/addon-unicode11 | 0.9.0 | https://registry.npmjs.org/@xterm/addon-unicode11/-/addon-unicode11-0.9.0.tgz | sha512-FxDnYcyuXhNl+XSqGZL/t0U9eiNb/q3EWT5rYkQT/zuig8Gz/VagnQANKHdDWFM2lTMk9ly0EFQxxxtZUoRetw== |

All five are the `latest` dist-tag versions as of the fetch date and were published together
as one xterm.js 6.0 release.

## Files

Source of each file inside its package tarball:

- xterm.js - @xterm/xterm package/lib/xterm.js (sets `window.Terminal`)
- xterm.css - @xterm/xterm package/css/xterm.css
- addon-fit.js - @xterm/addon-fit package/lib/addon-fit.js (sets `window.FitAddon.FitAddon`)
- addon-web-links.js - @xterm/addon-web-links package/lib/addon-web-links.js (sets `window.WebLinksAddon.WebLinksAddon`)
- addon-search.js - @xterm/addon-search package/lib/addon-search.js (sets `window.SearchAddon.SearchAddon`)
- addon-unicode11.js - @xterm/addon-unicode11 package/lib/addon-unicode11.js (sets `window.Unicode11Addon.Unicode11Addon`)
- LICENSE-<name>.txt - package/LICENSE of the matching package (MIT)

| File | SHA-256 |
| --- | --- |
| xterm.js | 14903579ff54664cd72f8e8699e6961a6272c21863ec1c3b118cdc8af5d4a972 |
| xterm.css | 854a7c0fb70e8b1a083c16797ab827299fb18744f5ad34f227b48337e33293c6 |
| addon-fit.js | ba3ea256ce0620a0992a197d6c9baea64823fc93d8da07a9e366ca9943c18527 |
| addon-web-links.js | b74864125ef3889753b94e61eb4dabb99b2a27f920f0c9a7bd53cbe6d10f032a |
| addon-search.js | 7bc1b8c7b3549411f6f6f779524c4ded6ca621fd80d64b40a70ae7c78aefbf55 |
| addon-unicode11.js | 72353b5178e1a7382716df1cfedf8ab070eea655d38995bb9f4f284fe56e2f2b |
| LICENSE-xterm.txt | b569f629d00f2626a8100df2a1798210535621e42164dfd426a6fe5aac7b0ccd |
| LICENSE-addon-fit.txt | e256f01188af527e4d06d21d06fbf785ae9c50d4b328bf03cbe0ba7f0aa4228f |
| LICENSE-addon-web-links.txt | 689ceb10716bd7a87a804c14951d7c2b818cbd60aab83d540902470ce3b13444 |
| LICENSE-addon-search.txt | 689ceb10716bd7a87a804c14951d7c2b818cbd60aab83d540902470ce3b13444 |
| LICENSE-addon-unicode11.txt | e256f01188af527e4d06d21d06fbf785ae9c50d4b328bf03cbe0ba7f0aa4228f |

`tests/test_xterm_vendor.py` checks these hashes, so any change to a vendored file without an
update here fails the test suite.

## How to update

1. Look up the new `latest` version of each package at `https://registry.npmjs.org/<package>`
   and note `dist.tarball` and `dist.integrity`. Update all five together so the addons match
   the @xterm/xterm major version.
2. Download each tarball into its own new empty directory and verify it:
   `echo "sha512-$(openssl dgst -sha512 -binary pkg.tgz | base64 -w0)"` must equal
   `dist.integrity` exactly. Stop on any mismatch.
3. List the tarball (`tar -tzf`) and reject absolute paths or `..` entries, then extract each
   into its own new empty directory with `tar -xzf pkg.tgz --no-same-owner`. Do not run
   anything from the extracted packages.
4. Copy only the files listed above (UMD `lib/*.js`, `css/xterm.css`, `LICENSE`) into this
   directory, unmodified. Do not copy `.map`, `.mjs`, `src/` or `typings/`.
5. Update the version, tarball, integrity and date in this file, recompute every SHA-256
   (`sha256sum *` in this directory, excluding VENDOR.md) and update the table.
6. Review the release notes and `typings/*.d.ts` for API changes, then run
   `python3 -m unittest tests.test_xterm_vendor -v`.
