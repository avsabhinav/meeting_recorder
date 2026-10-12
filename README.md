# meeting-recorder

A local-first macOS tool that records a 1:1 call (your mic + the other side via
system audio) and transcribes it locally to an **attributed Markdown
transcript** — each line marked as *You* or *Them*, ready for other AI agents to
consume. No cloud, no LLM: record + transcribe to attributed Markdown, all local.

## Developing

```sh
pip install -e ".[dev]"
ruff check mr tests
pytest
```
