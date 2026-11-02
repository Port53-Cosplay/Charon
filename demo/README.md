# The public demo

`charon.empire12.net/demo` is the real dashboard page running on made-up data,
with no login and no backend. The URL is printed on the zine résumé, so it has
to keep working.

## Rebuild

```
python demo/build_demo.py
```

That writes `demo/dist/charon-demo.html` (gitignored). It seeds a throwaway
database from `fixtures.py`, asks the real dashboard functions for their
payloads, and embeds them with `shim.js`, which answers the page's `/api`
calls in the browser. Prep's letters are real `.docx` files made by
`charon.prep` for "Sample Applicant". Nothing reads or writes `~/.charon`.

`tests/test_demo.py` fails when the page calls an API the shim doesn't
answer, or when anything personal (names, the domain, LAN addresses, temp
paths) ends up in the page. Add a route to `ROUTES` in `shim.js` when that
happens.

## Deploy

The page is a static file on Shield, separate from the app, so app deploys
never touch it:

```
/var/www/charon-demo/index.html     (served at /demo by the charon.empire12.net nginx site)
```

Copy the new file up through ops, keep the old one as
`index.html.bak-<date>`, and check `https://charon.empire12.net/demo` loads.
