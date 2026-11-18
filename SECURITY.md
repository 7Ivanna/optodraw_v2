# Security policy

optodraw draws diagrams. The parts worth reporting are:

- the local editor server (`optodraw-gui`), which binds `127.0.0.1` and does
  not authenticate. Do not expose that bind to a network.
- `optodraw-gui --hosted`, which requires a shared token (`--auth-token`, else
  `OPTODRAW_AUTH_TOKEN`, else a generated one printed at startup). Pass
  `--allow-anonymous-hosted` only when you mean it.
- scene and GDS files from other people, which are parsed on import
- the packaged desktop app

**Reporting:** use **Report a vulnerability** on the repository's Security tab
(GitHub private vulnerability reporting). Say what you found and how to
reproduce it. Please don't open a public issue for anything exploitable. I am
one person, so expect a first reply within about a week.

**Supported:** the latest release only.
