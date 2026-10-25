"""Download a fixed snapshot of CEN SIP data so the demo never calls the API live.

The API key comes from COORDINADOR_API_KEY (or a KEY=value line in --env-file). It is never
written to disk, logs or manifests: recorded URLs omit user_key, and error bodies are redacted.

Each request is cached as one gzipped page, so an interrupted run resumes where it stopped.
Pages start at 1 (page=0 returns 502). Contact fields (emails, addresses, RUTs) are dropped
before saving; they are not needed and should not be redistributed.
"""

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "cen-sip"
HOST = "https://sipub.api.coordinador.cl"
DROP_FIELDS = {
    "email_distribuidor", "email_suministrador", "direccion_ditribuidor",
    "direccion_suministrador", "rut_distribuidor", "rut_suministrador",
}
# v3 endpoints paginate with pageSize, v4 with limit.
PAGE_PARAM = {"v3": "pageSize", "v4": "limit"}


def load_key(env_file):
    key = os.environ.get("COORDINADOR_API_KEY")
    if not key and env_file:
        for line in Path(env_file).read_text().splitlines():
            if line.startswith("COORDINADOR_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
    if not key:
        sys.exit("COORDINADOR_API_KEY is not set")
    return key


def fetch(path, params, key, attempts=5):
    url = f"{HOST}{path}?{urlencode({**params, 'user_key': key})}"
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=120) as r:
                return json.load(r)
        except HTTPError as e:
            body = e.read(200).decode("utf-8", "replace").replace(key, "<KEY>")
            if e.code in (400, 401, 403, 404) or attempt == attempts - 1:
                raise RuntimeError(f"{e.code} {path} {params}: {body}") from None
        except (TimeoutError, OSError) as e:
            if attempt == attempts - 1:
                raise RuntimeError(f"{type(e).__name__} {path} {params}") from None
        time.sleep(2 ** (attempt + 1))


def clean(rows):
    return [{k: v for k, v in row.items() if k not in DROP_FIELDS} for row in rows]


def download(name, path, params, key, page_size=5000):
    """Fetch every page of one query into data/raw/cen-sip/<name>/ and return its manifest entry."""
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    size_param = PAGE_PARAM[path.split("/")[2][:2]]
    page, total_pages, rows = 1, None, 0
    while total_pages is None or page <= total_pages:
        file = folder / f"page-{page:04d}.json.gz"
        data = None
        if file.exists():
            try:
                data = json.loads(gzip.decompress(file.read_bytes()))
            except (OSError, EOFError, ValueError):
                print(f"  {name}: page {page} was cut off, fetching it again", flush=True)
        if data is None:
            data = fetch(path, {**params, "page": page, size_param: page_size}, key)
            data["data"] = clean(data.get("data", []))
            partial = file.with_suffix(".part")
            partial.write_bytes(gzip.compress(json.dumps(data, ensure_ascii=False).encode()))
            partial.replace(file)  # atomic: an interrupted run never leaves a half-written page
            time.sleep(1)
        total_pages = data.get("totalPages") or 1
        rows += len(data["data"])
        print(f"  {name}: page {page}/{total_pages}", flush=True)
        page += 1
    digest = hashlib.sha256()
    for f in sorted(folder.glob("page-*.json.gz")):
        digest.update(gzip.decompress(f.read_bytes()))
    return {
        "name": name, "endpoint": path, "params": params, "page_size": page_size,
        "pages": total_pages, "rows": rows, "sha256_of_pages": digest.hexdigest(),
        "url_without_key": f"{HOST}{path}?{urlencode(params)}",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", help="JSON file: list of {name, endpoint, params}")
    parser.add_argument("--env-file", help="file containing COORDINADOR_API_KEY=...")
    args = parser.parse_args()
    key = load_key(args.env_file)
    manifest_file = OUT / "manifest.json"
    manifest = json.loads(manifest_file.read_text()) if manifest_file.exists() else {"datasets": {}}
    manifest.update({
        "publisher": "Coordinador Eléctrico Nacional (SIP API)",
        "documentation": "https://portal.api.coordinador.cl/documentacion?service=sipubv2",
        "license": "Public data; attribution to Coordinador Eléctrico Nacional preserved. Contact fields removed.",
    })
    for item in json.loads(Path(args.plan).read_text()):
        print(item["name"], flush=True)
        entry = download(item["name"], item["endpoint"], item.get("params", {}), key)
        entry["retrieved_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        manifest["datasets"][item["name"]] = entry
        manifest_file.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
