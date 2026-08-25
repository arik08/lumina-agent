# Tooling and Dependencies

`Installer.bat` installs the standard dependencies for this skill.

## Python Packages

- `python-pptx`
- `markitdown[pptx]`
- `PyMuPDF`
- `mammoth`
- `markdownify`
- `beautifulsoup4`
- `openpyxl`
- `svglib`
- `reportlab`
- `Pillow`
- `numpy`
- `requests`
- `curl_cffi`

## Node Packages

Installed under `.skills/pptx-writer/node-runtime`:

- `pptxgenjs`
- `jszip`
- `fast-xml-parser`

## Environment Checks

```powershell
python .skills\pptx-writer\scripts\check_pptx_env.py
```

Use `--report-only` when diagnosing a partial environment before installing.

