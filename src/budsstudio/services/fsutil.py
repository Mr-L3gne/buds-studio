"""Leitura e gravação de arquivos do app: atômicas, privadas (só o dono) e com tamanho limitado."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Config e perfis têm poucos KB; qualquer coisa muito maior que isto não é nossa.
MAX_JSON_BYTES = 1 << 20  # 1 MiB


def private_dir(path: Path) -> Path:
    """Cria a pasta (e as pais) com permissão 0700, sem mexer em pastas que já existem."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def write_private(path: Path, text: str, mode: int = 0o600) -> None:
    """Grava `text` em `path` de forma atômica, por padrão com permissão 0600 (`mode` passa pelo umask).

    Escreve num arquivo temporário do mesmo diretório, força o disco (fsync) e só então troca
    pelo destino, então uma queda de energia deixa o arquivo antigo ou o novo, nunca um pela metade.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, max_bytes: int = MAX_JSON_BYTES):
    """JSON de um arquivo, recusando arquivos grandes demais ou aninhados a ponto de estourar a pilha.

    Levanta `ValueError` (inclui JSON inválido, texto que não é UTF-8, tamanho e aninhamento) ou
    `OSError`.
    """
    with open(path, "rb") as handle:
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"arquivo maior que {max_bytes} bytes")
    try:
        return json.loads(data.decode("utf-8"))
    except RecursionError as exc:
        raise ValueError("JSON aninhado demais") from exc
