# Releasing zimlore to PyPI (checklist; nothing here has been done)

From the rfclib release setup (that session's advice, 2026-11-07), adapted. **Status: not ready to publish.** No GitHub
repository exists for zimlore, nothing is registered on PyPI, and the workflow has never run.

1. **Create `b1tninja/zimlore` on GitHub and push** (owner and repository in the PyPI publisher must match the
   repository the workflow runs in). The `[project.urls]` in `pyproject.toml` are broken links until then.
2. **GitHub environments** (`gh api -X PUT repos/b1tninja/zimlore/environments/pypi`, same for `testpypi`). Lock
   `pypi` to version tags: `deployment_branch_policy` with `custom_branch_policies: true`, then a policy
   `name=v*, type=tag`. Add yourself as a required reviewer on `pypi` only if you want a manual click per release.
   Leave `testpypi` unrestricted (manual runs go there).
3. **PyPI pending publisher** (pypi.org, Account, Publishing, "Add a new pending publisher", GitHub): project
   `zimlore`, owner `b1tninja`, repository `zimlore`, workflow `release.yml` (file name only), environment `pypi`.
   Register it shortly before you tag: a pending publisher does **not** reserve the name, and the first upload from
   that repository, workflow and environment creates the project. TestPyPI is a separate site and account (same fields,
   environment `testpypi`). 2FA must be on.
4. **Dry run on TestPyPI first** (versions cannot be re-uploaded): run the `release` workflow by hand from `main`; check
   the project page (README, MIT, URLs, classifiers, requires-python), that wheel and sdist were both uploaded with
   attestations, and install in a clean venv with `--index-url https://test.pypi.org/simple/ --extra-index-url
   https://pypi.org/simple/ "zimlore[mcp]==0.1.0"`, then `zimlore --version`, `zimlore info`, and `zimlore mcp` answering an
   initialize request. Confirm `libzim` and `mcp` came from pypi.org (TestPyPI can hold squatted dependencies).
5. **Tag `v0.1.0` on the same commit** (the workflow checks the tag against `zimlore/__init__.py`).

Update 2026-11-07 (rfclib session, at the user's request): the PyPI and TestPyPI pending publishers for `zimlore` and `itulib` are registered (workflow `release.yml`, environments `pypi` and `testpypi`). The GitHub environments for zimlore cannot exist until `b1tninja/zimlore` does; then:
`gh api -X PUT repos/b1tninja/zimlore/environments/testpypi`, `gh api -X PUT repos/b1tninja/zimlore/environments/pypi --input <(echo '{"deployment_branch_policy":{"protected_branches":false,"custom_branch_policies":true}}')`, `gh api -X POST repos/b1tninja/zimlore/environments/pypi/deployment-branch-policies -f name='v*' -f type=tag`. A pending publisher does not reserve the name; nothing is published.

Already done here: the dev tools are a dependency group; the deployment links to PyPI; the release job runs the suite
against the installed wheel and the sdist; no test needs the network. Untested: `pip install zimlore` on Windows on
ARM (the `libzim` marker excludes that platform on purpose) and the workflow itself on a GitHub runner.
