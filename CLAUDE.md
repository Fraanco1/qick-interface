# QICK Analyzer

PNA-X-style web instrument for transmon and fluxonium chips on an RFSoC 4x2 running QICK. Requirements: `SPECS.md`.

## Where to look

- **Adding or changing a measurement:** `docs/developer-guide.md`, "Adding a measurement".
- **Any QICK API call:** `docs/research/qick.md`. It is checked against the installed library; when a QICK tutorial disagrees, trust the library source in `.venv/lib/python3.12/site-packages/qick/`.
- **Board, wiring, service, mixers:** `docs/hardware-setup.md`.
- **Vocabulary:** `GLOSSARY.md`. **Settled decisions:** `docs/adr/`. **Module map:** `docs/architecture.md`.

## How work is done here

- **Ask the user** at every design decision that the spec and docs don't settle. They asked for this explicitly.
- **Test-first** at the four agreed test points (developer guide, "Tests"). New behaviour starts as a red test there.
- **Verify on hardware** after touching `board.py`, `iq.py` or a QICK program: run `.venv/bin/python scripts/hardware_sweep.py` on the bench loopback (DAC_B → ADC_D).
- **Verify the page** in `--fake` mode with screenshots at desktop and phone widths (headless Chromium is cached in `~/.cache/ms-playwright/`).
- **Commit messages are plain:** no co-author or attribution lines (user preference). The user pushes to GitHub; SSH to github.com is blocked from this PC.

## Gotchas

- **The board** is `xilinx@192.168.3.1`, on a USB link, with no internet. Packages for it are downloaded on the PC and copied over.
- **Commands needing sudo on the board** are run by the user in their own terminal, because the `!` prefix has no TTY for the password. Give them the exact command.
- **Pyro4 configuration is global per process.** Use the pickle serializer everywhere the QICK nameserver or server lives.
- **QICK versions:** the `qick` pin in `pyproject.toml` matches the board (0.2.442). Upgrade both together.
- **Firmware:** the board runs `~/jupyter_notebooks/qick_firmware/qick_4x2.bit`, not the library's bundled bitfile. Tests compile against `tests/fixtures/soccfg_rfsoc4x2.json`; refresh it when the firmware changes.
- **The lab HTTP proxy** intercepts local requests. Use `NO_PROXY=localhost` or `curl --noproxy localhost`.
- **Stop background servers by the PID from the port** (`ss -ltnp | grep :8099`). `pkill -f` with the server's command line also matches, and kills, the shell running it.
