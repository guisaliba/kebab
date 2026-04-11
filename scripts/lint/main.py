import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.paths import ROOT
from scripts.lib.validation import iter_wiki_pages, validate_page_type_list, validate_wiki_markdown_file


def validate_registry() -> None:
    registry_path = ROOT / 'raw' / 'registry.yaml'
    if not registry_path.exists():
        raise SystemExit('raw/registry.yaml missing')
    data = yaml.safe_load(registry_path.read_text(encoding='utf-8'))
    if 'sources' not in data:
        raise SystemExit('raw/registry.yaml missing sources key')
    print(f"registry ok: {len(data['sources'])} source(s)")


def validate_index() -> None:
    index_path = ROOT / 'wiki' / 'index.md'
    log_path = ROOT / 'wiki' / 'log.md'
    if not index_path.exists() or not log_path.exists():
        raise SystemExit('wiki/index.md or wiki/log.md missing')
    print('wiki navigation ok')


def lint_wiki_pages() -> None:
    errors = []
    errors.extend(validate_page_type_list())
    for page in iter_wiki_pages():
        errors.extend(validate_wiki_markdown_file(page))
    if errors:
        print("lint errors:")
        for error in errors:
            print(f"- {error}")
        raise SystemExit(1)
    print("wiki lint ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', default='validate', choices=['validate', 'lint'])
    args = parser.parse_args()
    validate_registry()
    validate_index()
    if args.mode == 'lint':
        lint_wiki_pages()
    print(f"lint mode: {args.mode}")
    print('starter validation complete')

if __name__ == '__main__':
    main()
